# services/upload_pipeline.py
import os
import re
import shutil
import logging
from uuid import uuid4
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import UploadFile
from sqlalchemy.orm import Session

from models.knowledge import Knowledge
import crud.knowledge as crud
import crud.api_cost as cost
import core.config as config
from core.pricing import (
    tokens_for_texts,
    normalize_usage_embedding,
    estimate_embedding_cost_usd,
)

from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

log = logging.getLogger("api_cost")

DEBUG_RAG_URL = os.getenv("DEBUG_RAG_URL") == "1"

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
# parent-child chunking configs
# =========================================================
_USE_PARENT_CHILD_CHUNKING = getattr(config, "USE_PARENT_CHILD_CHUNKING", True)

_CHILD_CHUNK_SIZE = getattr(config, "CHILD_CHUNK_SIZE", 900)
_CHILD_CHUNK_OVERLAP = getattr(config, "CHILD_CHUNK_OVERLAP", 150)
_PARENT_SUMMARY_MAX_CHARS = getattr(config, "PARENT_SUMMARY_MAX_CHARS", 220)

_EMBED_INCLUDE_PARENT_TITLE = getattr(config, "EMBED_INCLUDE_PARENT_TITLE", True)
_EMBED_INCLUDE_ALIASES = getattr(config, "EMBED_INCLUDE_ALIASES", True)
_EXTRA_ALIAS_MAP = getattr(config, "EMBED_ALIAS_MAP", None)

_DEFAULT_ALIAS_MAP = {
    "POS": "포스",
    "포스": "POS",
}

_PARENT_PREFIX = "[PARENT]"
_CHILD_PREFIX = "[CHILD]"

_GARAM_READ_MARK = "m.garampos.co.kr/bbs_shop/read.htm"


# =========================================================
# helpers
# =========================================================
def _tok_len(s: str) -> int:
    model = getattr(config, "DEFAULT_EMBEDDING_MODEL", "text-embedding-3-small")
    return tokens_for_texts(model, [s])


def _snip(s: str, n: int = 420) -> str:
    return (s or "").replace("\n", "\\n")[:n]


def _normalize_garampos_pdf_text(text: str) -> str:
    """
    가람포스텍 자료실 PDF(또는 PDF로 렌더된 리스트)에서 흔히 발생하는 깨짐 복원:
    - idx=32068134. 처럼 idx 뒤에 글번호(34.)가 붙는 문제를 분리
    - board_code=rw38... 같이 깨진 값을 rwdboard로 강제(가람 URL일 때만)
    """
    t = text or ""
    if not t or _GARAM_READ_MARK not in t:
        return t

    # board_code=rwdboard가 아닌 이상한 값으로 깨졌을 때만 교정
    t = re.sub(r"(board_code=)rw(?!dboard)[^\s&]+", r"\1rwdboard", t)

    def _split_idx_and_no(digits: str) -> tuple[str, str]:
        """
        digits = idx + no(글번호) 형태로 붙어있는 숫자열을 (idx, no)로 분리.
        - 기본: 끝 2자리가 10~200이면 글번호 2자리 우선
        - idx 길이가 5~6자리가 아니면 1자리로 fallback
        """
        entry_len = 2 if (len(digits) >= 7 and 10 <= int(digits[-2:]) <= 200) else 1
        idx = digits[:-entry_len]
        entry = digits[-entry_len:]

        if len(idx) not in (5, 6):
            idx, entry = digits[:-1], digits[-1:]
        return idx, entry

    def _repl_with_dot(m: re.Match) -> str:
        digits = m.group("digits")
        tail = m.group("tail")  # ". " 등
        idx, entry = _split_idx_and_no(digits)
        return f"idx={idx}\n{entry}{tail}"

    # 케이스1) idx=32068134. 처럼 dot이 바로 오는 경우
    t = re.sub(r"idx=(?P<digits>\d{6,9})(?P<tail>\.\s*)", _repl_with_dot, t)

    def _repl_no_dot(m: re.Match) -> str:
        digits = m.group("digits")
        ws = m.group("ws") or ""
        idx, entry = _split_idx_and_no(digits)
        return f"idx={idx}\n{entry}{ws}"

    # 케이스2) idx=32068134 시트롤... 처럼 dot 없이 바로 제목이 오는 경우
    t = re.sub(r"idx=(?P<digits>\d{6,9})(?P<ws>\s*)(?=[가-힣A-Za-z])", _repl_no_dot, t)

    return t


def _normalize_extracted_text(text: str) -> str:
    """
    PDF 추출 결과에서 URL/href가 줄바꿈으로 쪼개지는 문제를 최대한 복원합니다.
    - href="...": 따옴표 내부 공백/줄바꿈 제거
    - http(s)://... 가 줄바꿈으로 끊긴 경우 이어붙이기
    - (가람포스텍) idx 뒤에 글번호가 붙는 문제 복원
    """
    t = text or ""

    # href=" ... " 내부의 공백/줄바꿈 제거
    def _fix_href(m: re.Match) -> str:
        url = m.group(1) or ""
        url = re.sub(r"\s+", "", url)
        return f'href="{url}"'

    t = re.sub(r'href="([^"]*)"', _fix_href, t, flags=re.IGNORECASE | re.DOTALL)

    # 일반 URL이 줄바꿈으로 끊긴 경우 이어붙이기 (최대 3회)
    for _ in range(3):
        new_t = re.sub(
            r"(https?://[^\s<>\"]+)\s*\n\s*([^\s<>\"]+)",
            r"\1\2",
            t,
            flags=re.IGNORECASE,
        )
        if new_t == t:
            break
        t = new_t

    # 가람포스텍 리스트 깨짐 복원(가람 URL일 때만 동작)
    t = _normalize_garampos_pdf_text(t)

    return t


def _is_urlish_line(raw: str) -> bool:
    s = raw or ""
    return (
        "http://" in s
        or "https://" in s
        or "href=" in s
        or "read.htm" in s
        or "me_popup=" in s
        or "search_first_subject=" in s
        or "idx=" in s
    )


def _norm_line(s: str) -> str:
    """
    기본은 공백 정규화.
    단, URL/쿼리스트링 라인은 공백 정규화를 하면 링크가 깨질 수 있어 원문 유지.
    """
    raw = (s or "").strip()
    if not raw:
        return ""
    if _is_urlish_line(raw):
        return raw
    return " ".join(raw.split())


def _is_heading(line: str) -> bool:
    ln = _norm_line(line)
    if not ln:
        return False
    if ln.startswith("#"):
        return True
    if re.match(r"^(\(?\d+(\.\d+)*\)?[\.\)])\s+\S+", ln):
        return True
    if len(ln) <= 50:
        if sum(ch in ln for ch in ".?!") >= 1:
            return False
        keywords = ("설정", "오류", "방법", "주의", "개요", "원인", "해결", "FAQ", "가이드", "정의", "예시")
        if ln.endswith(keywords):
            return True
        if re.search(r"\b[A-Z]{2,}\b", ln):
            return True
    return False


def _make_parent_summary(body: str, max_chars: int) -> str:
    lines = [_norm_line(x) for x in (body or "").splitlines() if _norm_line(x)]
    if not lines:
        return ""
    head = " ".join(lines[:3]).strip()
    return head[:max_chars]


def _alias_map() -> dict:
    m = dict(_DEFAULT_ALIAS_MAP)
    if isinstance(_EXTRA_ALIAS_MAP, dict):
        for k, v in _EXTRA_ALIAS_MAP.items():
            if isinstance(k, str) and isinstance(v, str) and k and v:
                m[k] = v
    return m


def _aliases_for_title(title: str) -> List[str]:
    t = title or ""
    amap = _alias_map()
    out: List[str] = []
    for k, v in amap.items():
        if k in t and v not in t:
            out.append(v)
    seen = set()
    uniq: List[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _log_url_stage(stage: str, text: str) -> None:
    if not DEBUG_RAG_URL:
        return
    try:
        log.info(
            "[URL-%s] len=%d has_href=%s has_read=%s has_idx=%s",
            stage,
            len(text or ""),
            ("href=" in (text or "")),
            ("read.htm?" in (text or "")),
            ("idx=" in (text or "")),
        )
        if "read.htm?" in (text or "") and "idx=" not in (text or ""):
            m = re.search(r"read\.htm\?.{0,180}", text or "", flags=re.IGNORECASE | re.DOTALL)
            if m:
                log.info("[URL-%s] read_snip=%s", stage, _snip(m.group(0), 360))
    except Exception as e:
        log.exception("[URL-%s] debug failed: %s", stage, e)


# =========================================================
# pipeline
# =========================================================
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

    def save_file(self, file: UploadFile) -> str:
        base_dir = config.UPLOAD_FOLDER
        user_dir = os.path.join(base_dir, str(self.user_id), "document")
        os.makedirs(user_dir, exist_ok=True)

        origin = file.filename or "uploaded.pdf"
        fname = f"{self.user_id}_{uuid4().hex[:8]}_{origin}"
        fpath = os.path.join(user_dir, fname)

        file.file.seek(0)
        with open(fpath, "wb") as f:
            shutil.copyfileobj(file.file, f, length=1024 * 1024)

        self.file_path = fpath
        return fpath

    def _load_docs(self, file_path: str):
        return PyMuPDFLoader(file_path).load()

    def extract_text(self, file_path: str) -> Tuple[str, int]:
        docs = self._load_docs(file_path)
        raw = "\n".join(d.page_content for d in docs if getattr(d, "page_content", "")).strip()

        _log_url_stage("EXTRACT_RAW", raw)

        text = _normalize_extracted_text(raw)

        _log_url_stage("EXTRACT_NORM", text)

        return text, len(docs)

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
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        return " ".join(lines[:5])[:max_chars]

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

    def store_pages(self, knowledge_id: int, num_pages: int, image_urls: Optional[List[str]] = None):
        pages = [
            {"page_no": i, "image_url": (image_urls[i - 1] if image_urls and i - 1 < len(image_urls) else "")}
            for i in range(1, num_pages + 1)
        ]
        crud.bulk_create_pages(self.db, knowledge_id, pages)

    def chunk_text(self, text: str) -> List[str]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=200,
            length_function=_tok_len,
            separators=["\n\n", "\n", " ", ""],
        )
        return splitter.split_text(text)

    def chunk_parent_child(self, text: str, *, default_title: str = "문서") -> List[Tuple[str, str]]:
        raw_lines = (text or "").splitlines()
        lines = [_norm_line(ln) for ln in raw_lines]
        lines = [ln for ln in lines if ln]

        if not lines:
            return []

        sections: List[Tuple[str, str]] = []
        cur_title = default_title or "문서"
        cur_body: List[str] = []

        for ln in lines:
            if _is_heading(ln):
                if cur_body:
                    sections.append((cur_title, "\n".join(cur_body).strip()))
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

                embed_text = c
                if _EMBED_INCLUDE_PARENT_TITLE:
                    aliases = _aliases_for_title(title) if _EMBED_INCLUDE_ALIASES else []
                    if aliases:
                        embed_text = f"{title}\n{' / '.join(aliases)}\n{c}"
                    else:
                        embed_text = f"{title}\n{c}"

                pairs.append((store_text, embed_text))

        if DEBUG_RAG_URL:
            try:
                sample = "\n\n".join(p[0] for p in pairs[:8])
                _log_url_stage("CHUNK_SAMPLE", sample)
            except Exception:
                pass

        return pairs

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

    def embed_parent_child_pairs(self, pairs: List[Tuple[str, str]]) -> Tuple[List[str], List[List[float]], int]:
        cleaned_store: List[str] = []
        embed_inputs: List[str] = []

        for store_text, embed_text in pairs:
            st = (store_text or "").strip()
            et = (embed_text or "").strip()
            if not st or not et:
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

    def store_chunks(self, knowledge_id: int, chunks: List[str], vectors: List[List[float]]):
        crud.create_knowledge_chunks(self.db, knowledge_id, chunks, vectors)

    def _set_status(self, knowledge_id: int, status: str):
        try:
            crud.update_knowledge(self.db, knowledge_id, {"status": status})
        except Exception:
            pass

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

            if total_tokens_for_cost > 0:
                try:
                    usage = normalize_usage_embedding(total_tokens_for_cost)
                    usd = estimate_embedding_cost_usd(
                        model=getattr(config, "DEFAULT_EMBEDDING_MODEL", "text-embedding-3-small"),
                        total_tokens=usage["embedding_tokens"],
                    )
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
                except Exception as e:
                    log.exception("api-cost embedding record failed: %s", e)

            self._set_status(know.id, "active")
            return know

        except Exception:
            if self.knowledge:
                self._set_status(self.knowledge.id, "error")
            raise
