"""2026-01-14_add inquiry_attatch_type

Revision ID: 9515948b9cab
Revises: 34c99fc9648c
Create Date: 2026-01-14 10:44:39.102519

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9515948b9cab'
down_revision: Union[str, Sequence[str], None] = '34c99fc9648c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1) 컬럼 추가 (기본값 local)
    op.add_column(
        "inquiry_attachment",
        sa.Column("storage_type", sa.String(), server_default="local", nullable=False),
    )

    # 2) CHECK 제약 추가
    op.create_check_constraint(
        "chk_inqa_storage_type",
        "inquiry_attachment",
        "storage_type IN ('local','s3')",
    )

    # 3) 새 컬럼에 기본값이 남는 게 싫으면(선택)
    # op.alter_column("inquiry_attachment", "storage_type", server_default=None)


def downgrade() -> None:
    op.drop_constraint("chk_inqa_storage_type", "inquiry_attachment", type_="check")
    op.drop_column("inquiry_attachment", "storage_type")