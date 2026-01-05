# models/knowledge.py
from sqlalchemy import (
    Column,
    BigInteger,
    Integer,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    Index,
    Computed,
    func,
    text,
)
from sqlalchemy.orm import relationship, backref
from pgvector.sqlalchemy import Vector
from database.base import Base


class Knowledge(Base):
    __tablename__ = "knowledge"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    original_name = Column(Text, nullable=False)
    # 정규화(검색용): 항상 lower(original_name) 유지
    original_name_norm = Column(
        Text,
        Computed("lower(original_name)", persisted=True),
        nullable=False,
    )

    type = Column(Text, nullable=False)  # MIME
    size = Column(BigInteger, nullable=False)

    status = Column(Text, nullable=False)  # 'active' | 'processing' | 'error'

    preview = Column(Text, nullable=False)
    preview_norm = Column(
        Text,
        Computed("lower(preview)", persisted=True),
        nullable=False,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("size >= 0", name="chk_kdoc_size_nonneg"),
        CheckConstraint("status IN ('active','processing','error')", name="chk_kdoc_status"),
        Index("idx_kdoc_created_at", created_at.desc()),

        Index(
            "idx_kdoc_original_name_trgm",
            "original_name_norm",
            postgresql_using="gin",
            postgresql_ops={"original_name_norm": "gin_trgm_ops"},
        ),
        Index(
            "idx_kdoc_preview_trgm",
            "preview_norm",
            postgresql_using="gin",
            postgresql_ops={"preview_norm": "gin_trgm_ops"},
        ),
    )


class KnowledgePage(Base):
    __tablename__ = "knowledge_page"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_id = Column(
        BigInteger,
        ForeignKey("knowledge.id", ondelete="CASCADE"),
        nullable=False,
    )

    page_no = Column(Integer, nullable=True)  # 1부터 (이미지 없는 청크/메타면 null 허용)
    image_url = Column(Text, nullable=True)  # WebP 권장

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    knowledge = relationship(
        "Knowledge",
        backref=backref(
            "pages",
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("knowledge_id", "page_no", name="uq_kpage_doc_page"),
        CheckConstraint("page_no IS NULL OR page_no >= 1", name="chk_kpage_page_no_ge_1"),
        Index("idx_kpage_doc_page", "knowledge_id", "page_no"),
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    knowledge_id = Column(
        BigInteger,
        ForeignKey("knowledge.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_id = Column(
        BigInteger,
        ForeignKey("knowledge_page.id", ondelete="SET NULL"),
        nullable=True,
    )

    chunk_index = Column(Integer, nullable=False)  # 1부터
    chunk_text = Column(Text, nullable=False)

    chunk_text_norm = Column(
        Text,
        Computed(r"lower(regexp_replace(chunk_text, '\s+', '', 'g'))", persisted=True),
        nullable=False,
    )

    vector_memory = Column(Vector(1536), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    knowledge = relationship(
        "Knowledge",
        backref=backref(
            "chunks",
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
        passive_deletes=True,
    )
    page = relationship(
        "KnowledgePage",
        backref=backref("chunks", passive_deletes=True),
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("chunk_index >= 1", name="chk_kchunk_index_ge_1"),
        UniqueConstraint("knowledge_id", "chunk_index", name="uq_kchunk_doc_idx"),
        Index("idx_kchunk_doc_index", "knowledge_id", "chunk_index"),
        Index("idx_kchunk_doc_page", "knowledge_id", "page_id"),
        Index("idx_kchunk_created_at", created_at.desc()),
        # pgvector ivfflat
        Index(
            "idx_kchunk_vec_ivfflat",
            "vector_memory",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"vector_memory": "vector_cosine_ops"},
        ),
        Index(
            "idx_kchunk_text_norm_trgm",
            "chunk_text_norm",
            postgresql_using="gin",
            postgresql_ops={"chunk_text_norm": "gin_trgm_ops"},
        ),
    )


__all__ = ["Knowledge", "KnowledgePage", "KnowledgeChunk"]
