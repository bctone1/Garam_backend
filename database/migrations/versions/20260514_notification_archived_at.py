"""notification archived_at

Revision ID: 20260514_archived_at
Revises: a1b2c3d4e5f6
Create Date: 2026-05-14

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '20260514_archived_at'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notification",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 기존 completed inquiry의 inquiry_new/inquiry_assigned 알림 백필
    op.execute("""
        UPDATE notification n
        SET archived_at = NOW()
        FROM inquiry i
        WHERE n.inquiry_id = i.id
          AND i.status = 'completed'
          AND n.event_type IN ('inquiry_new', 'inquiry_assigned')
          AND n.archived_at IS NULL
    """)


def downgrade() -> None:
    op.drop_column("notification", "archived_at")
