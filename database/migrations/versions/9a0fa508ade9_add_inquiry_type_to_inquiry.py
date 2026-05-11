"""add inquiry_type to inquiry

Revision ID: 9a0fa508ade9
Revises: 6fb08e442f37
Create Date: 2026-01-13 15:41:48.759403

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a0fa508ade9'
down_revision: Union[str, Sequence[str], None] = '6fb08e442f37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inquiry",
        sa.Column("inquiry_type", sa.String(), nullable=False, server_default="other"),
    )

    op.create_check_constraint(
        "chk_inquiry_type",
        "inquiry",
        "inquiry_type IN ('paper_request','sales_report','kiosk_menu_update','other')",
    )

    op.create_index(
        "idx_inquiry_type_created",
        "inquiry",
        ["inquiry_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_inquiry_type_created", table_name="inquiry")
    op.drop_constraint("chk_inquiry_type", "inquiry", type_="check")
    op.drop_column("inquiry", "inquiry_type")