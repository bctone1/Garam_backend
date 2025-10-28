"""new default

Revision ID: 6b03b7952219
Revises: af06cfd15e72
Create Date: 2025-10-28 12:03:10.414029
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "6b03b7952219"
down_revision: Union[str, Sequence[str], None] = "af06cfd15e72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow 'new' action in inquiry_history.action."""
    # drop old CHECK constraint
    op.drop_constraint("chk_inqh_action", "inquiry_history", type_="check")
    # recreate with 'new' included
    op.create_check_constraint(
        "chk_inqh_action",
        "inquiry_history",
        "action IN ('new','assign','on_hold','resume','transfer','complete','note','contact','delete')",
    )


def downgrade() -> None:
    """Revert: disallow 'new' action."""
    op.drop_constraint("chk_inqh_action", "inquiry_history", type_="check")
    op.create_check_constraint(
        "chk_inqh_action",
        "inquiry_history",
        "action IN ('assign','on_hold','resume','transfer','complete','note','contact','delete')",
    )
