# services/upload_pipeline.py
import os
from uuid import uuid4
from fastapi import UploadFile
from sqlalchemy.orm import Session
from models.knowledge import Knowledge
import crud.knowledge as crud
import core.config as config
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_service.embedding.get_vector import text_to_vector
from service.prompt import pdf_preview_prompt


class UploadPipeline:
    """
    파일 저장 → 메타 생성(processing) → 텍스트 추출 → 청크 → 임베딩 → 청크 저장 → 상태(active)
    """
    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id
        self.file_path: str | None = None
        self.knowledge: Knowledge | None = None

    def save_file(self, file: UploadFile) -> str:
        base_dir = config.UPLOAD_FOLDER
        user_dir = os.path.join(base_dir, str(self.user_id), "document")
        os.makedirs(user_dir, exist_ok=True)

        origin = file.filename
        fname = f"{self.user_id}_{uuid4().hex[:8]}_{origin}"
        fpath = os.path.join(user_dir, fname)
        with open(fpath, "wb") as f:
            f.write(file.file.read())
        self.file_path = fpath
        return fpath

    def create_metadata(self, file: UploadFile) -> Knowledge:
        file_size = os.path.getsize(self.file_path)
        # 프리뷰 생성(요약문). dict/list 대응
        preview_obj = pdf_preview_prompt(self.file_path)
        if isinstance(preview_obj, dict):
            preview = preview_obj.get("preview", "")
            if isinstance(preview, list):
                preview = " ".join(preview[:3])
        else:
            preview = str(preview_obj)[:500]

        data = {
            "original_name": file.filename,
            "type": file.content_type,
            "size": file_size,
            "status": "processing",   # 제약조건과 일치
            "preview": preview or "",
        }
        self.knowledge = crud.create_knowledge(self.db, data)
        return self.knowledge

    def store_pages(self, knowledge_id: int, num_pages: int, image_urls: list[str] | None = None):
        pages = [
            {"page_no": i, "image_url": (image_urls[i - 1] if image_urls and i - 1 < len(image_urls) else "")}
            for i in range(1, num_pages + 1)
        ]
        crud.bulk_create_pages(self.db, knowledge_id, pages)

    def extract_text(self, file_path: str) -> str:
        loader = PyMuPDFLoader(file_path)
        docs = loader.load()
        return "\n".join(d.page_content for d in docs)

    def chunk_text(self, text: str) -> list[str]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=100, length_function=len
        )
        return splitter.split_text(text)

    def embed_chunks(self, chunks: list[str]) -> list[list[float]]:
        return [text_to_vector(c) for c in chunks if c and c.strip()]


    def store_chunks(self, knowledge_id: int, chunks: list[str], vectors: list[list[float]]):
        crud.create_knowledge_chunks(self.db, knowledge_id, chunks, vectors)

    def run(self, file: UploadFile) -> Knowledge:
        path = self.save_file(file)
        know = self.create_metadata(file)

        num_pages = len(PyMuPDFLoader(path).load())
        self.store_pages(know.id, num_pages=num_pages)

        text = self.extract_text(path)
        chunks = self.chunk_text(text)
        vectors = self.embed_chunks(chunks)
        if vectors:
            self.store_chunks(know.id, chunks, vectors)

        return know