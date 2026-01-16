"""add norm columns + pg_trgm gin indexes for knowledge

Revision ID: 6fb08e442f37
Revises: dd214cffbbc8
Create Date: 2026-01-02 15:53:32.472883

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6fb08e442f37'
down_revision: Union[str, Sequence[str], None] = 'dd214cffbbc8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    # 1) extensions
    # - 권한 필요할 수 있음(보통 DB owner/superuser)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # 2) drop old expression trigram indexes if you had them
    # (예: 이전에 lower(...) 표현식으로 인덱스 만들었던 케이스 정리)
    op.execute("DROP INDEX IF EXISTS gin_trgm_kdoc_name;")
    op.execute("DROP INDEX IF EXISTS gin_trgm_kdoc_preview;")
    op.execute("DROP INDEX IF EXISTS idx_kchunk_text_trgm;")

    # 3) add generated(norm) columns
    op.add_column(
        "knowledge",
        sa.Column(
            "original_name_norm",
            sa.Text(),
            sa.Computed("lower(original_name)", persisted=True),
            nullable=False,
        ),
    )
    op.add_column(
        "knowledge",
        sa.Column(
            "preview_norm",
            sa.Text(),
            sa.Computed("lower(preview)", persisted=True),
            nullable=False,
        ),
    )

    op.add_column(
        "knowledge_chunk",
        sa.Column(
            "chunk_text_norm",
            sa.Text(),
            sa.Computed(r"lower(regexp_replace(chunk_text, '\s+', '', 'g'))", persisted=True),
            nullable=False,
        ),
    )

    # 4) create trigram GIN indexes on norm columns
    op.create_index(
        "idx_kdoc_original_name_trgm",
        "knowledge",
        ["original_name_norm"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"original_name_norm": "gin_trgm_ops"},
    )
    op.create_index(
        "idx_kdoc_preview_trgm",
        "knowledge",
        ["preview_norm"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"preview_norm": "gin_trgm_ops"},
    )
    op.create_index(
        "idx_kchunk_text_norm_trgm",
        "knowledge_chunk",
        ["chunk_text_norm"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"chunk_text_norm": "gin_trgm_ops"},
    )

    # (옵션) created_at 인덱스 추가 (없으면 생성)
    op.create_index(
        "idx_kchunk_created_at",
        "knowledge_chunk",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    # drop indexes (new)
    op.drop_index("idx_kchunk_created_at", table_name="knowledge_chunk")
    op.drop_index("idx_kchunk_text_norm_trgm", table_name="knowledge_chunk")
    op.drop_index("idx_kdoc_preview_trgm", table_name="knowledge")
    op.drop_index("idx_kdoc_original_name_trgm", table_name="knowledge")

    # drop columns (new generated columns)
    op.drop_column("knowledge_chunk", "chunk_text_norm")
    op.drop_column("knowledge", "preview_norm")
    op.drop_column("knowledge", "original_name_norm")

    # (선택) 예전 expression 기반 인덱스로 되돌리고 싶으면 아래 주석 해제
    # op.execute("CREATE INDEX gin_trgm_kdoc_name ON knowledge USING gin (lower(original_name) gin_trgm_ops);")
    # op.execute("CREATE INDEX gin_trgm_kdoc_preview ON knowledge USING gin (lower(preview) gin_trgm_ops);")
    # op.execute("CREATE INDEX idx_kchunk_text_trgm ON knowledge_chunk USING gin (lower(chunk_text) gin_trgm_ops);")

    # pg_trgm extension은 다른 곳에서도 쓸 수 있어서 보통 downgrade에서 삭제 안 함
    # op.execute("DROP EXTENSION IF EXISTS pg_trgm;")