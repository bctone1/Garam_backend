# services/upload_pipeline.py
import os
import re
import shutil
from uuid import uuid4
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging

from fastapi import UploadFile
from sqlalchemy.orm import Session

from models.knowledge import Knowledge
import crud.knowledge as crud
import crud.api_cost as cost
import core.config as config
from core.pricing import (
    tokens_for_texts,               # tiktoken 기반 토큰 계산
    normalize_usage_embedding,
    estimate_embedding_cost_usd,
)

from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

log = logging.getLogger("api_cost")

# 임베딩: 배치가 있으면 우선 사용, 없으면 단건 + 스레드풀
try:
    from langchain_service.embedding.get_vector import text_to_vector, text_list_to_vectors  # type: ignore
    _HAS_BATCH = True
except Exception:
    from langchain_service.embedding.get_vector import text_to_vector  # type: ignore
    _HAS_BATCH = False

# 프리뷰 LLM 사용 여부(기본 비활성)
_USE_LLM_PREVIEW = getattr(config, "USE_LLM_PREVIEW", False)
if _USE_LLM_PREVIEW:
    from service.prompt import pdf_preview_prompt  # type: ignore


# =========================================================
# parent-child chunking configs (safe defaults)
# =========================================================
_USE_PARENT_CHILD_CHUNKING = getattr(config, "USE_PARENT_CHILD_CHUNKING", True)

_CHILD_CHUNK_SIZE = getattr(config, "CHILD_CHUNK_SIZE", 900)
_CHILD_CHUNK_OVERLAP = getattr(config, "CHILD_CHUNK_OVERLAP", 150)
_PARENT_SUMMARY_MAX_CHARS = getattr(config, "PARENT_SUMMARY_MAX_CHARS", 220)

# 임베딩 입력에 parent title을 아주 짧게 섞어서 키워드/약어 매칭 보강
_EMBED_INCLUDE_PARENT_TITLE = getattr(config, "EMBED_INCLUDE_PARENT_TITLE", True)

# 아주 가벼운 alias 확장(예: POS <-> 포스)
_EMBED_INCLUDE_ALIASES = getattr(config, "EMBED_INCLUDE_ALIASES", True)
# 프로젝트 config에 dict로 덮어쓸 수 있음
_EXTRA_ALIAS_MAP = getattr(config, "EMBED_ALIAS_MAP", None)

_DEFAULT_ALIAS_MAP = {
    "POS": "포스",
    "포스": "POS",
}

_PARENT_PREFIX = "[PARENT]"
_CHILD_PREFIX = "[CHILD]"


def _tok_len(s: str) -> int:
    model = getattr(config, "DEFAULT_EMBEDDING_MODEL", "text-embedding-3-small")
    return tokens_for_texts(model, [s])


def _norm_line(s: str) -> str:
    # PDF 추출 텍스트는 공백이 난잡한 경우가 많아서 normalize
    return " ".join((s or "").strip().split())


def _is_heading(line: str) -> bool:
    """
    헤더(Parent) 라인 추정 휴리스틱.
    - #/## 같은 마크다운 스타일
    - 1. / 1) / (1) 같은 섹션 표기
    - 짧고(<= 50) 문장부호가 적고, 특정 키워드로 끝나면 헤더로 간주
    """
    ln = _norm_line(line)
    if not ln:
        return False

    # markdown heading
    if ln.startswith("#"):
        return True

    # numbered headings
    if re.match(r"^(\(?\d+(\.\d+)*\)?[\.\)])\s+\S+", ln):
        return True

    # very short / title-ish lines
    if len(ln) <= 50:
        # 너무 문장 같은 건 제외(마침표/물음표/느낌표가 많으면 문장)
        if sum(ch in ln for ch in ".?!") >= 1:
            return False
        # 흔한 문서 헤더 키워드
        keywords = ("설정", "오류", "방법", "주의", "개요", "원인", "해결", "FAQ", "가이드", "정의", "예시")
        if ln.endswith(keywords):
            return True
        # 대문자 약어 중심(예: POS, API, DB 등)
        if re.search(r"\b[A-Z]{2,}\b", ln):
            return True

    return False


def _make_parent_summary(body: str, max_chars: int) -> str:
    lines = [ _norm_line(x) for x in (body or "").splitlines() if _norm_line(x) ]
    if not lines:
        return ""
    # 앞 2~3줄 정도를 요약처럼 사용
    head = " ".join(lines[:3]).strip()
    if len(head) > max_chars:
        return head[:max_chars]
    return head


def _alias_map() -> dict:
    m = dict(_DEFAULT_ALIAS_MAP)
    if isinstance(_EXTRA_ALIAS_MAP, dict):
        for k, v in _EXTRA_ALIAS_MAP.items():
            if isinstance(k, str) and isinstance(v, str) and k and v:
                m[k] = v
    return m


def _aliases_for_title(title: str) -> List[str]:
    """
    title에서 alias를 얇게 추가해주는 용도.
    예: "POS 설정"이면 "포스"를 같이 넣어준다.
    """
    t = title or ""
    amap = _alias_map()
    out: List[str] = []
    for k, v in amap.items():
        if k in t and v not in t:
            out.append(v)
    # 중복 제거(입력 순서 유지)
    seen = set()
    uniq: List[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


class UploadPipeline:
    """
    파일 저장 → 텍스트 추출 → 프리뷰 → 메타 생성(processing)
    → 페이지 저장 → 청크 → 임베딩 → 청크 저장 → 상태(active)
    실패 시 상태(error)
    """
    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id
        self.file_path: Optional[str] = None
        self.knowledge: Optional[Knowledge] = None

    # 1) 파일 저장
    def save_file(self, file: UploadFile) -> str:
        base_dir = config.UPLOAD_FOLDER
        user_dir = os.path.join(base_dir, str(self.user_id), "document")
        os.makedirs(user_dir, exist_ok=True)

        origin = file.filename or "uploaded.pdf"
        fname = f"{self.user_id}_{uuid4().hex[:8]}_{origin}"
        fpath = os.path.join(user_dir, fname)

        file.file.seek(0)
        with open(fpath, "wb") as f:
            shutil.copyfileobj(file.file, f, length=1024 * 1024)  # 1MB 버퍼

        self.file_path = fpath
        return fpath

    # 2) 로더 1회
    def _load_docs(self, file_path: str):
        return PyMuPDFLoader(file_path).load()

    # 3) 텍스트 추출
    def extract_text(self, file_path: str) -> Tuple[str, int]:
        docs = self._load_docs(file_path)
        text = "\n".join(d.page_content for d in docs if getattr(d, "page_content", "")).strip()
        return text, len(docs)

    # 4) 프리뷰
    def _build_preview(self, text: str, max_chars: int = 400) -> str:
        if _USE_LLM_PREVIEW and self.file_path:
            try:
                prev_obj = pdf_preview_prompt(self.file_path)  # type: ignore
                if isinstance(prev_obj, dict):
                    p = prev_obj.get("preview", "")
                    if isinstance(p, list):
                        p = " ".join(p[:3])
                    return str(p)[:max_chars]
                return str(prev_obj)[:max_chars]
            except Exception:
                pass
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        head = " ".join(lines[:5])
        return head[:max_chars]

    # 5) 메타 생성
    def create_metadata(self, file: UploadFile, preview: str) -> Knowledge:
        file_size = os.path.getsize(self.file_path or "")
        data = {
            "original_name": file.filename,
            "type": file.content_type,
            "size": file_size,
            "status": "processing",
            "preview": preview or "",
        }
        self.knowledge = crud.create_knowledge(self.db, data)
        return self.knowledge

    # 6) 페이지 저장
    def store_pages(self, knowledge_id: int, num_pages: int, image_urls: Optional[List[str]] = None):
        pages = [
            {
                "page_no": i,
                "image_url": (image_urls[i - 1] if image_urls and i - 1 < len(image_urls) else "")
            }
            for i in range(1, num_pages + 1)
        ]
        crud.bulk_create_pages(self.db, knowledge_id, pages)

    # 7) (기존) 일반 청킹
    def chunk_text(self, text: str) -> List[str]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=200,
            length_function=_tok_len,
            separators=["\n\n", "\n", " ", ""],
        )
        return splitter.split_text(text)

    # 7-2) parent-child 청킹: store_text(parent+child) / embed_text(child 중심)
    def chunk_parent_child(self, text: str, *, default_title: str = "문서") -> List[Tuple[str, str]]:
        """
        returns: List[(store_text, embed_text)]
        - store_text: parent(title/summary) + child (컨텍스트용)
        - embed_text: 검색/임베딩용(기본 child, 옵션 title/alias 살짝)
        """
        raw_lines = text.splitlines() if text else []
        lines = [_norm_line(ln) for ln in raw_lines]
        lines = [ln for ln in lines if ln]  # 빈 줄 제거(너무 과하게는 제거하지 않음)

        if not lines:
            return []

        # 섹션 분리
        sections: List[Tuple[str, str]] = []
        cur_title = default_title or "문서"
        cur_body: List[str] = []

        for ln in lines:
            if _is_heading(ln):
                # 이전 섹션 flush
                if cur_body:
                    sections.append((cur_title, "\n".join(cur_body).strip()))
                # 새 섹션 시작
                t = ln.lstrip("#").strip()
                cur_title = t or default_title or "문서"
                cur_body = []
            else:
                cur_body.append(ln)

        if cur_body:
            sections.append((cur_title, "\n".join(cur_body).strip()))

        if not sections:
            sections = [(default_title or "문서", "\n".join(lines).strip())]

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=_CHILD_CHUNK_SIZE,
            chunk_overlap=_CHILD_CHUNK_OVERLAP,
            length_function=_tok_len,
            separators=["\n\n", "\n", " ", ""],
        )

        pairs: List[Tuple[str, str]] = []
        for title, body in sections:
            title = _norm_line(title) or (default_title or "문서")
            summary = _make_parent_summary(body, _PARENT_SUMMARY_MAX_CHARS)

            # body가 너무 비면 title/summary만으로 child를 만들지 않고 skip
            if not (body and body.strip()):
                continue

            child_chunks = splitter.split_text(body)
            for child in child_chunks:
                c = (child or "").strip()
                if not c:
                    continue

                store_text = (
                    f"{_PARENT_PREFIX}\n"
                    f"{title}\n"
                    f"{summary}\n\n"
                    f"{_CHILD_PREFIX}\n"
                    f"{c}"
                ).strip()

                # 임베딩 텍스트(검색용): child 중심 + (옵션) title/alias 조금
                embed_text = c
                if _EMBED_INCLUDE_PARENT_TITLE:
                    aliases = _aliases_for_title(title) if _EMBED_INCLUDE_ALIASES else []
                    if aliases:
                        alias_line = " / ".join(aliases)
                        embed_text = f"{title}\n{alias_line}\n{c}"
                    else:
                        embed_text = f"{title}\n{c}"

                pairs.append((store_text, embed_text))

        return pairs

    # 8) (기존) 임베딩
    def embed_chunks(self, chunks: List[str]) -> Tuple[List[str], List[List[float]]]:
        cleaned = [c for c in chunks if c and c.strip()]
        if not cleaned:
            return [], []
        if _HAS_BATCH:
            vecs = text_list_to_vectors(cleaned)  # type: ignore
        else:
            vecs: List[List[float]] = []
            max_workers = min(4, (os.cpu_count() or 4))
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                for v in ex.map(text_to_vector, cleaned):
                    vecs.append(v)
        return cleaned, vecs

    # 8-2) parent-child pair 임베딩: store_text와 벡터를 정렬된 상태로 반환
    def embed_parent_child_pairs(self, pairs: List[Tuple[str, str]]) -> Tuple[List[str], List[List[float]], int]:
        """
        returns:
        - store_texts: DB 저장용 (parent+child)
        - vectors: embed_text들에 대한 벡터
        - total_tokens: embed_text 기준 토큰 합(비용 집계용)
        """
        cleaned_store: List[str] = []
        embed_inputs: List[str] = []

        for store_text, embed_text in pairs:
            st = (store_text or "").strip()
            et = (embed_text or "").strip()
            if not et:
                continue
            if not st:
                # store_text는 비어있으면 의미가 없으니 같이 제거
                continue
            cleaned_store.append(st)
            embed_inputs.append(et)

        if not embed_inputs:
            return [], [], 0

        if _HAS_BATCH:
            vecs = text_list_to_vectors(embed_inputs)  # type: ignore
        else:
            vecs: List[List[float]] = []
            max_workers = min(4, (os.cpu_count() or 4))
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                for v in ex.map(text_to_vector, embed_inputs):
                    vecs.append(v)

        total_tokens = sum(_tok_len(et) for et in embed_inputs)
        return cleaned_store, vecs, total_tokens

    # 9) 청크 저장
    def store_chunks(self, knowledge_id: int, chunks: List[str], vectors: List[List[float]]):
        crud.create_knowledge_chunks(self.db, knowledge_id, chunks, vectors)

    # 10) 상태
    def _set_status(self, knowledge_id: int, status: str):
        try:
            crud.update_knowledge(self.db, knowledge_id, {"status": status})
        except Exception:
            pass

    # 파이프라인 실행
    def run(self, file: UploadFile) -> Knowledge:
        try:
            path = self.save_file(file)
            text, num_pages = self.extract_text(path)

            preview = self._build_preview(text)
            know = self.create_metadata(file, preview)

            self.store_pages(know.id, num_pages)

            total_tokens_for_cost = 0

            if _USE_PARENT_CHILD_CHUNKING:
                pairs = self.chunk_parent_child(text, default_title=(file.filename or "문서"))
                store_texts, vectors, total_tokens_for_cost = self.embed_parent_child_pairs(pairs)
                if vectors:
                    self.store_chunks(know.id, store_texts, vectors)
            else:
                chunks = self.chunk_text(text)
                chunks, vectors = self.embed_chunks(chunks)
                if vectors:
                    self.store_chunks(know.id, chunks, vectors)
                    total_tokens_for_cost = sum(_tok_len(c or "") for c in chunks)

            # ==== 비용 집계: 임베딩 ====
            if total_tokens_for_cost > 0:
                try:
                    usage = normalize_usage_embedding(total_tokens_for_cost)
                    usd = estimate_embedding_cost_usd(
                        model=getattr(config, "DEFAULT_EMBEDDING_MODEL", "text-embedding-3-small"),
                        total_tokens=usage["embedding_tokens"],
                    )
                    log.info("api-cost: will record embedding tokens=%d usd=%s", usage["embedding_tokens"], usd)
                    cost.add_event(
                        self.db,
                        ts_utc=datetime.now(timezone.utc),
                        product="embedding",
                        model=getattr(config, "DEFAULT_EMBEDDING_MODEL", "text-embedding-3-small"),
                        llm_tokens=0,
                        embedding_tokens=usage["embedding_tokens"],
                        audio_seconds=0,
                        cost_usd=usd,
                    )
                    log.info("api-cost: recorded embedding tokens=%d usd=%s", usage["embedding_tokens"], usd)
                except Exception as e:
                    log.exception("api-cost embedding record failed: %s", e)

            self._set_status(know.id, "active")
            return know
        except Exception:
            if self.knowledge:
                self._set_status(self.knowledge.id, "error")
            raise
