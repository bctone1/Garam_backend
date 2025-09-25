"""drop setting_id from quick_category

Revision ID: 42528effd83d
Revises: 7837f4c859c9
Create Date: 2025-09-25 10:56:47.346763

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '42528effd83d'
down_revision: Union[str, Sequence[str], None] = '7837f4c859c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 먼저 FK 제약 조건 제거 (존재한다면)
    op.drop_constraint(
        "quick_category_setting_id_fkey", "quick_category", type_="foreignkey"
    )
    # setting_id 관련 인덱스 제거
    op.drop_index("idx_qc_setting_order", table_name="quick_category")
    op.drop_index("idx_qc_setting", table_name="quick_category")
    # 컬럼 제거
    op.drop_column("quick_category", "setting_id")


def downgrade() -> None:
    # 되돌릴 때는 다시 컬럼과 제약 추가
    op.add_column(
        "quick_category",
        sa.Column("setting_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "quick_category_setting_id_fkey",
        "quick_category",
        "system_setting",
        ["setting_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "idx_qc_setting_order",
        "quick_category",
        ["setting_id", "sort_order"],
    )
    op.create_index("idx_qc_setting", "quick_category", ["setting_id"])