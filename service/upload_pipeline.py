# services/upload_pipeline.py

from fastapi import UploadFile
from sqlalchemy.orm import Session
from models.knowledge import Knowledge
import crud.knowledge as crud


class UploadPipeline:
    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id
        self.file_path: str | None = None
        self.knowledge: Knowledge | None = None

    def save_file(self, file: UploadFile) -> str:
        """원본 파일을 로컬에 저장 후 경로 반환"""
        ...

    def create_metadata(self, file: UploadFile) -> Knowledge:
        """Knowledge 메타데이터 DB에 기록"""
        ...

    def extract_text(self, file_path: str) -> str:
        """파일에서 텍스트 추출"""
        ...

    def chunk_text(self, text: str) -> list[str]:
        """텍스트를 청크 단위로 분리"""
        ...

    def embed_chunks(self, chunks: list[str]) -> list[list[float]]:
        """청크 리스트를 벡터화"""
        ...

    def store_chunks(self, knowledge_id: int, chunks: list[str], vectors: list[list[float]]):
        """청크 + 벡터를 DB 저장"""
        crud.store_chunks_to_db(self.db, knowledge_id, chunks, vectors)

    def run(self, file: UploadFile) -> Knowledge:
        file_path = self.save_file(file)
        knowledge = self.create_metadata(file)
        text = self.extract_text(file_path)
        chunks = self.chunk_text(text)
        vectors = self.embed_chunks(chunks)
        self.store_chunks(knowledge.id, chunks, vectors)
        crud.update_knowledge_status(self.db, knowledge.id, "active")
        return knowledge