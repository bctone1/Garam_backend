# services/upload_pipeline.py
import os
import shutil
import tempfile
import subprocess
from uuid import uuid4
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

from fastapi import UploadFile
from sqlalchemy.orm import Session

from models.knowledge import Knowledge
import crud.knowledge as crud
import core.config as config


from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 임베딩: 배치가 있으면 우선 사용, 없으면 단건 + 스레드풀
try:
    from langchain_service.embedding.get_vector import text_to_vector, text_list_to_vectors  # type: ignore
    _HAS_BATCH = True
except Exception:
    from langchain_service.embedding.get_vector import text_to_vector  # type: ignore
    _HAS_BATCH = False

# 프리뷰 LLM 사용 여부(기본: 비활성, 텍스트 기반)
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
    파일 저장 → PyMuPDF 1회 로드 → 텍스트 추출 → 프리뷰 생성 → 메타 생성(processing)
    → 페이지 저장 → 토큰 기준 청크 → 임베딩(배치/병렬) → 청크 저장 → 상태(active)
    실패 시 상태(error)
    """
    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id
        self.file_path: Optional[str] = None
        self.knowledge: Optional[Knowledge] = None

    # 1) 스트리밍 저장
    def save_file(self, file: UploadFile) -> str:
        base_dir = config.UPLOAD_FOLDER
        user_dir = os.path.join(base_dir, str(self.user_id), "document")
        os.makedirs(user_dir, exist_ok=True)

        origin = file.filename or "uploaded.pdf"
        fname = f"{self.user_id}_{uuid4().hex[:8]}_{origin}"
        fpath = os.path.join(user_dir, fname)

        with open(fpath, "wb") as f:
            shutil.copyfileobj(file.file, f, length=1024 * 1024)  # 1MB 버퍼

        self.file_path = fpath
        return fpath

    # 2) 한 번만 로드하고 재사용
    def _load_docs(self, file_path: str):
        return PyMuPDFLoader(file_path).load()

    # 3) 텍스트
    def extract_text(self, file_path: str) -> tuple[str, int]:
        docs = PyMuPDFLoader(file_path).load()
        text = "\n".join(d.page_content for d in docs).strip()
        return text, len(docs)

    def run(self, file: UploadFile) -> Knowledge:
        path = self.save_file(file)
        text, num_pages = self.extract_text(path)  # ← 여기서 호출
        preview = self._build_preview(text)
        know = self.create_metadata(file, preview)
        self.store_pages(know.id, num_pages)
        chunks = self.chunk_text(text)
        chunks, vectors = self.embed_chunks(chunks)
        if vectors:
            self.store_chunks(know.id, chunks, vectors)
        self._set_status(know.id, "active")
        return know

    # 4) 가벼운 프리뷰 생성(LLM 비사용 기본)
    def _build_preview(self, text: str, max_chars: int = 400) -> str:
        if _USE_LLM_PREVIEW and self.file_path:
            try:
                prev_obj = pdf_preview_prompt(self.file_path)  # LLM 사용 모드
                if isinstance(prev_obj, dict):
                    p = prev_obj.get("preview", "")
                    if isinstance(p, list):
                        p = " ".join(p[:3])
                    return str(p)[:max_chars]
                return str(prev_obj)[:max_chars]
            except Exception:
                pass
        # 헤더 라인 몇 개 + 본문 앞부분
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

    # 7) 토큰 기준 청크
    def chunk_text(self, text: str) -> List[str]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=900,       # 토큰 기준 약 700~900 권장
            chunk_overlap=150,
            length_function=_tok_len,
            separators=["\n\n", "\n", " ", ""],
        )
        return splitter.split_text(text)

    # 8) 임베딩(배치/병렬)
    def embed_chunks(self, chunks: List[str]) -> Tuple[List[str], List[List[float]]]:
        cleaned = [c for c in chunks if c and c.strip()]
        if not cleaned:
            return [], []

        if _HAS_BATCH:
            vecs = text_list_to_vectors(cleaned)  # type: ignore
            return cleaned, vecs

        # 단건 API만 있을 때: 제한된 스레드풀 병렬
        vecs: List[List[float]] = []
        max_workers = min(4, (os.cpu_count() or 4))  # 과한 동시성 방지
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for v in ex.map(text_to_vector, cleaned):
                vecs.append(v)
        return cleaned, vecs

    # 9) 청크 저장
    def store_chunks(self, knowledge_id: int, chunks: List[str], vectors: List[List[float]]):
        # crud.create_knowledge_chunks(db, knowledge_id, chunks, vectors) 형태를 가정
        crud.create_knowledge_chunks(self.db, knowledge_id, chunks, vectors)

    # 10) 상태 갱신
    def _set_status(self, knowledge_id: int, status: str):
        try:
            crud.update_knowledge(self.db, knowledge_id, {"status": status})
        except Exception:
            pass

    # 파이프라인 실행
    def run(self, file: UploadFile) -> Knowledge:
        try:
            path = self.save_file(file)

            # 한 번만 로드하여 텍스트와 페이지 수 확보(+OCR 폴백)
            text, num_pages = self.extract_text_with_ocr_fallback(path)

            # 프리뷰 먼저 만들고 메타 생성
            preview = self._build_preview(text)
            know = self.create_metadata(file, preview)

            # 페이지 정보 저장
            self.store_pages(know.id, num_pages=num_pages)

            # 청크 → 임베딩
            chunks = self.chunk_text(text)
            chunks, vectors = self.embed_chunks(chunks)

            if vectors:
                self.store_chunks(know.id, chunks, vectors)

            # 완료
            self._set_status(know.id, "active")
            return know

        except Exception as e:
            # 실패 시 상태 업데이트
            if self.knowledge:
                self._set_status(self.knowledge.id, "error")
            raise

# 11) 각 문서에 대한 토큰수 계산
# counts =[]

