"""faq: add quick_category_id + idx + fk + trigram

Revision ID: 520251a6c431
Revises: 7979db34599a
Create Date: 2025-10-27 15:57:11.666312
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "520251a6c431"
down_revision: Union[str, Sequence[str], None] = "7979db34599a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 컬럼
    op.add_column(
        "faq",
        sa.Column("quick_category_id", sa.BigInteger(), nullable=True),
    )
    # 인덱스(FK 보조)
    op.create_index("idx_faq_qc", "faq", ["quick_category_id"], unique=False)
    # FK 이름 고정 + ondelete
    op.create_foreign_key(
        "fk_faq_qc",
        "faq",
        "quick_category",
        ["quick_category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # trigram 확장 + 식 인덱스
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS gin_trgm_faq_question
        ON faq
        USING gin (lower(question) gin_trgm_ops)
        """
    )


def downgrade() -> None:
    # trigram 인덱스 제거
    op.execute("DROP INDEX IF EXISTS gin_trgm_faq_question")
    # FK/인덱스/컬럼 제거(역순)
    op.drop_constraint("fk_faq_qc", "faq", type_="foreignkey")
    op.drop_index("idx_faq_qc", table_name="faq")
    op.drop_column("faq", "quick_category_id")
