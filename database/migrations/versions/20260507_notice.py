"""create notice table

Revision ID: a1b2c3d4e5f6
Revises: 074d53db845f
Create Date: 2026-05-07 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '074d53db845f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notice",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_important", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("author_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_admin_id"],
            ["admin_user.id"],
            name="fk_notice_author_admin",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "end_at IS NULL OR start_at IS NULL OR end_at > start_at",
            name="chk_notice_end_after_start",
        ),
    )

    op.create_index("idx_notice_created", "notice", [sa.text("created_at DESC")])
    op.create_index("idx_notice_start_end", "notice", ["start_at", "end_at"])
    op.create_index("idx_notice_important", "notice", ["is_important"])


def downgrade() -> None:
    op.drop_index("idx_notice_important", table_name="notice")
    op.drop_index("idx_notice_start_end", table_name="notice")
    op.drop_index("idx_notice_created", table_name="notice")
    op.drop_table("notice")
