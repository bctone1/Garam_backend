"""add inquiry_attatch

Revision ID: 34c99fc9648c
Revises: 9a0fa508ade9
Create Date: 2026-01-13 16:45:46.711566

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '34c99fc9648c'
down_revision: Union[str, Sequence[str], None] = '9a0fa508ade9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inquiry_attachment",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("inquiry_id", sa.BigInteger(), sa.ForeignKey("inquiry.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("original_name", sa.String(), nullable=True),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "content_type IS NULL OR content_type LIKE 'image/%'",
            name="chk_inqa_content_type_image",
        ),
    )

    op.create_index("idx_inqa_inquiry_time", "inquiry_attachment", ["inquiry_id", "created_at"], unique=False)
    op.create_index("idx_inqa_inquiry", "inquiry_attachment", ["inquiry_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_inqa_inquiry", table_name="inquiry_attachment")
    op.drop_index("idx_inqa_inquiry_time", table_name="inquiry_attachment")
    op.drop_table("inquiry_attachment")