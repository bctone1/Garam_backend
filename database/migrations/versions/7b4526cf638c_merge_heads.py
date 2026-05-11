"""merge_heads

Revision ID: 7b4526cf638c
Revises: 7382256206db, c750f08ac421
Create Date: 2026-02-12 10:22:23.472845

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b4526cf638c'
down_revision: Union[str, Sequence[str], None] = ('7382256206db', 'c750f08ac421')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
