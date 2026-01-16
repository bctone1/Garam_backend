"""2026-01-14_notification

Revision ID: 49d1b8e6cbcd
Revises: 35eeac1362ab
Create Date: 2026-01-14 16:56:05.796284

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '49d1b8e6cbcd'
down_revision: Union[str, Sequence[str], None] = '35eeac1362ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------
    # 1) inquiry: add columns
    # -----------------------------
    op.add_column("inquiry", sa.Column("assigned_by_admin_id", sa.BigInteger(), nullable=True))
    op.add_column("inquiry", sa.Column("delegated_from_admin_id", sa.BigInteger(), nullable=True))
    op.add_column("inquiry", sa.Column("completed_by_admin_id", sa.BigInteger(), nullable=True))

    # FK (explicit)
    op.create_foreign_key(
        "fk_inquiry_assigned_by_admin",
        "inquiry",
        "admin_user",
        ["assigned_by_admin_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_inquiry_delegated_from_admin",
        "inquiry",
        "admin_user",
        ["delegated_from_admin_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_inquiry_completed_by_admin",
        "inquiry",
        "admin_user",
        ["completed_by_admin_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # -----------------------------
    # 2) backfill (to satisfy new CHECKs)
    # -----------------------------
    # 기존에 이미 할당된 데이터가 있으면 assigned_by_admin_id를 0(대표)로 채워서 CHECK 위반 방지
    op.execute(
        """
        UPDATE inquiry
        SET assigned_by_admin_id = 0
        WHERE assignee_admin_id IS NOT NULL
          AND assigned_by_admin_id IS NULL
        """
    )

    # 기존 completed 데이터가 있으면 completed_by_admin_id를 assignee(없으면 0)로 채워서 CHECK 위반 방지
    op.execute(
        """
        UPDATE inquiry
        SET completed_by_admin_id = COALESCE(assignee_admin_id, 0)
        WHERE status = 'completed'
          AND completed_by_admin_id IS NULL
        """
    )

    # delegated_from_admin_id는 과거 데이터에 대해 억지로 채우지 않음(대표 위임 여부를 잘못 찍을 수 있어서)
    # 이후 assign 로직에서 대표가 처음 위임할 때만 0을 "한 번" 세팅하는 걸 권장

    # -----------------------------
    # 3) inquiry: add CHECK constraints
    # -----------------------------
    op.create_check_constraint(
        "chk_inquiry_assigned_by_required",
        "inquiry",
        "assignee_admin_id IS NULL OR assigned_by_admin_id IS NOT NULL",
    )

    # delegated_from_admin_id는 NULL 또는 0만 허용(대표관리자 id=0 고정 룰)
    op.create_check_constraint(
        "chk_inquiry_delegated_from_rep_only",
        "inquiry",
        "delegated_from_admin_id IS NULL OR delegated_from_admin_id = 0",
    )

    op.create_check_constraint(
        "chk_inquiry_completed_by_required",
        "inquiry",
        "status <> 'completed' OR completed_by_admin_id IS NOT NULL",
    )

    # -----------------------------
    # 4) inquiry: indexes
    # -----------------------------
    op.create_index(
        "idx_inquiry_assigned_by_created",
        "inquiry",
        ["assigned_by_admin_id", "created_at"],
    )
    op.create_index(
        "idx_inquiry_delegated_from_created",
        "inquiry",
        ["delegated_from_admin_id", "created_at"],
    )
    op.create_index(
        "idx_inquiry_completed_by_created",
        "inquiry",
        ["completed_by_admin_id", "created_at"],
    )

    # -----------------------------
    # 5) notification table
    # -----------------------------
    op.create_table(
        "notification",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("recipient_admin_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("inquiry_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["recipient_admin_id"],
            ["admin_user.id"],
            name="fk_notification_recipient_admin",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["inquiry_id"],
            ["inquiry.id"],
            name="fk_notification_inquiry",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_admin_id"],
            ["admin_user.id"],
            name="fk_notification_actor_admin",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "event_type IN ('inquiry_new','inquiry_assigned','inquiry_completed')",
            name="chk_notification_event_type",
        ),
    )

    op.create_index(
        "idx_notification_recipient_read_created",
        "notification",
        ["recipient_admin_id", "read_at", "created_at"],
    )
    op.create_index(
        "idx_notification_inquiry_created",
        "notification",
        ["inquiry_id", "created_at"],
    )


def downgrade() -> None:
    # -----------------------------
    # 1) drop notification
    # -----------------------------
    op.drop_index("idx_notification_inquiry_created", table_name="notification")
    op.drop_index("idx_notification_recipient_read_created", table_name="notification")
    op.drop_table("notification")

    # -----------------------------
    # 2) drop inquiry indexes
    # -----------------------------
    op.drop_index("idx_inquiry_completed_by_created", table_name="inquiry")
    op.drop_index("idx_inquiry_delegated_from_created", table_name="inquiry")
    op.drop_index("idx_inquiry_assigned_by_created", table_name="inquiry")

    # -----------------------------
    # 3) drop inquiry CHECK constraints
    # -----------------------------
    op.drop_constraint("chk_inquiry_completed_by_required", "inquiry", type_="check")
    op.drop_constraint("chk_inquiry_delegated_from_rep_only", "inquiry", type_="check")
    op.drop_constraint("chk_inquiry_assigned_by_required", "inquiry", type_="check")

    # -----------------------------
    # 4) drop inquiry FKs + columns
    # -----------------------------
    op.drop_constraint("fk_inquiry_completed_by_admin", "inquiry", type_="foreignkey")
    op.drop_constraint("fk_inquiry_delegated_from_admin", "inquiry", type_="foreignkey")
    op.drop_constraint("fk_inquiry_assigned_by_admin", "inquiry", type_="foreignkey")

    op.drop_column("inquiry", "completed_by_admin_id")
    op.drop_column("inquiry", "delegated_from_admin_id")
    op.drop_column("inquiry", "assigned_by_admin_id")
