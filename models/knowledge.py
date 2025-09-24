# SQLAlchemy ORM (물리설계 반영): knowledge, knowledge_page, knowledge_chunk

from sqlalchemy import (
    Column, BigInteger, Integer, Text, DateTime, String,
    ForeignKey, UniqueConstraint, CheckConstraint, Index, func, text)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSON
from pgvector.sqlalchemy import Vector
from database.base import Base


class Knowledge(Base):
    __tablename__ = "knowledge"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    original_name = Column(Text, nullable=False)
    type = Column(Text, nullable=False)                       # MIME
    size = Column(BigInteger, nullable=False)
    status = Column(Text, nullable=False)                     # 'active' | 'processing' | 'error'
    preview = Column(Text, nullable=False)                    # 짧은 요약문
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # 역참조: pages, chunks (아래 backref로 생성)

    __table_args__ = (
        CheckConstraint("size >= 0", name="chk_kdoc_size_nonneg"),
        CheckConstraint("status IN ('active','processing','error')", name="chk_kdoc_status"),
        Index("idx_kdoc_created_at", created_at.desc()),
        # 선택: pg_trgm 설치 시 활성화
        Index("gin_trgm_kdoc_name", text("lower(original_name) gin_trgm_ops"), postgresql_using="gin"),
        Index("gin_trgm_kdoc_preview", text("lower(preview) gin_trgm_ops"), postgresql_using="gin"),

    )


class KnowledgePage(Base):
    __tablename__ = "knowledge_page"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_id = Column(BigInteger, ForeignKey("knowledge.id", ondelete="CASCADE"), nullable=False)
    page_no = Column(Integer, nullable=False)                 # 1부터
    image_url = Column(Text, nullable=False)                  # WebP 권장
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    knowledge = relationship("Knowledge", backref="pages", passive_deletes=True)

    __table_args__ = (
        UniqueConstraint("knowledge_id", "page_no", name="uq_kpage_doc_page"),
        CheckConstraint("page_no >= 1", name="chk_kpage_page_no_ge_1"),
        Index("idx_docpage_doc_page", "knowledge_id", "page_no"),
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_id = Column(BigInteger, ForeignKey("knowledge.id", ondelete="CASCADE"), nullable=False)
    page_id = Column(BigInteger, ForeignKey("knowledge_page.id", ondelete="SET NULL"), nullable=True)
    chunk_index = Column(Integer, nullable=False)             # 1부터
    chunk_text = Column(Text, nullable=False)
    vector_memory = Column(Vector(1536), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    knowledge = relationship("Knowledge", backref="chunks", passive_deletes=True)
    page = relationship("KnowledgePage", backref="chunks", passive_deletes=True)

    __table_args__ = (
        CheckConstraint("chunk_index >= 1", name="chk_kchunk_index_ge_1"),
        UniqueConstraint("knowledge_id", "chunk_index", name="uq_kchunk_doc_idx"),
        Index("idx_chunk_doc_index", "knowledge_id", "chunk_index"),
        Index("idx_chunk_doc_page", "knowledge_id", "page_id"),
        # 벡터 유사도 검색용 (pgvector)
        Index(
            "idx_kchunk_vec_ivfflat",
            "vector_memory",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"vector_memory": "vector_cosine_ops"},
        ),
        # 선택: pg_trgm 설치 시 키워드 보조검색
        # Index("idx_kchunk_text_trgm", text("lower(chunk_text)"), postgresql_using="gin"),
    )


__all__ = ["Knowledge", "KnowledgePage", "KnowledgeChunk"]
