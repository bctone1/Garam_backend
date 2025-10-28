# services/upload_pipeline.py
import os
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
from core.pricing import normalize_usage_embedding, estimate_embedding_cost_usd

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

# 토큰 길이 함수: tiktoken 있으면 사용, 없으면 문자 길이
try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")

    def _tok_len(s: str) -> int:
        return len(_enc.encode(s))
except Exception:
    def _tok_len(s: str) -> int:
        return len(s)


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

    # 7) 청크
    def chunk_text(self, text: str) -> List[str]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=900,
            chunk_overlap=150,
            length_function=_tok_len,
            separators=["\n\n", "\n", " ", ""],
        )
        return splitter.split_text(text)

    # 8) 임베딩
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

            chunks = self.chunk_text(text)
            chunks, vectors = self.embed_chunks(chunks)
            if vectors:
                self.store_chunks(know.id, chunks, vectors)

                # ==== 비용 집계: 임베딩 ====
                try:
                    total_tokens = sum(_tok_len(c or "") for c in chunks)
                    usage = normalize_usage_embedding(total_tokens)
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
