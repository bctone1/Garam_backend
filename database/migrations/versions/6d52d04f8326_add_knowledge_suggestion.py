"""add_knowledge_suggestion

Revision ID: 6d52d04f8326
Revises: 28b1837d2cc4
Create Date: 2026-01-19 14:38:12.107038

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6d52d04f8326'
down_revision: Union[str, Sequence[str], None] = '28b1837d2cc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_suggestion",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),

        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("chat_session.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.BigInteger(), sa.ForeignKey("message.id", ondelete="CASCADE"), nullable=False, unique=True),

        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("assistant_answer", sa.Text(), nullable=True),
        sa.Column("final_answer", sa.Text(), nullable=True),

        sa.Column("answer_status", sa.String(length=16), nullable=False, server_default="error"),
        sa.Column("review_status", sa.String(length=16), nullable=False, server_default="pending"),

        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("retrieval_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.Column("target_knowledge_id", sa.BigInteger(), sa.ForeignKey("knowledge.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ingested_chunk_id", sa.BigInteger(), sa.ForeignKey("knowledge_chunk.id", ondelete="SET NULL"), nullable=True),

        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),

        sa.CheckConstraint("answer_status IN ('ok','error')", name="chk_k_suggest_answer_status"),
        sa.CheckConstraint("review_status IN ('pending','ingested','deleted')", name="chk_k_suggest_review_status"),
        sa.CheckConstraint(
            "(review_status <> 'ingested') OR (final_answer IS NOT NULL AND ingested_chunk_id IS NOT NULL)",
            name="chk_k_suggest_ingested_requires_answer_chunk",
        ),
    )

    op.create_index("idx_k_suggest_review_created", "knowledge_suggestion", ["review_status", "created_at"])
    op.create_index("idx_k_suggest_session_created", "knowledge_suggestion", ["session_id", "created_at"])
    op.create_index("idx_k_suggest_target_review", "knowledge_suggestion", ["target_knowledge_id", "review_status"])


def downgrade() -> None:
    op.drop_index("idx_k_suggest_target_review", table_name="knowledge_suggestion")
    op.drop_index("idx_k_suggest_session_created", table_name="knowledge_suggestion")
    op.drop_index("idx_k_suggest_review_created", table_name="knowledge_suggestion")
    op.drop_table("knowledge_suggestion")