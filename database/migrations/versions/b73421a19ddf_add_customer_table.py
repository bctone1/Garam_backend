"""add customer table

Revision ID: b73421a19ddf
Revises: c750f08ac421
Create Date: 2026-02-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b73421a19ddf'
down_revision: Union[str, None] = 'c750f08ac421'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'customer',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('business_number', sa.String(), nullable=True),
        sa.Column('business_name', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('address', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('customer')
