"""fix_inquiry_delete

Revision ID: 5bc6802b9b22
Revises: 8cfcef3956eb
Create Date: 2025-11-21 14:14:58.892736

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5bc6802b9b22'
down_revision: Union[str, Sequence[str], None] = '8cfcef3956eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.drop_constraint(
        "chk_inquiry_assignment_consistency",
        "inquiry",
        type_="check",
    )
    op.create_check_constraint(
        "chk_inquiry_assignment_consistency",
        "inquiry",
        "assignee_admin_id IS NULL OR assigned_at IS NOT NULL",
    )


def downgrade():
    op.drop_constraint(
        "chk_inquiry_assignment_consistency",
        "inquiry",
        type_="check",
    )
    op.create_check_constraint(
        "chk_inquiry_assignment_consistency",
        "inquiry",
        "(assignee_admin_id IS NULL AND assigned_at IS NULL) OR "
        "(assignee_admin_id IS NOT NULL AND assigned_at IS NOT NULL)",
    )