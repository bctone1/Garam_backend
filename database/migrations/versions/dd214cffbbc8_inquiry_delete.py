"""inquiry_delete

Revision ID: dd214cffbbc8
Revises: 5bc6802b9b22
Create Date: 2025-11-21 14:17:46.387270

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dd214cffbbc8'
down_revision: Union[str, Sequence[str], None] = '5bc6802b9b22'
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
