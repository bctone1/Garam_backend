"""add owner_name and store_phone to inquiry

Revision ID: 20260604_inq_owner_store
Revises: 20260604_cust_owner_store
Create Date: 2026-06-04

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '20260604_inq_owner_store'
down_revision: Union[str, Sequence[str], None] = '20260604_cust_owner_store'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('inquiry', sa.Column('owner_name', sa.String(), nullable=True))
    op.add_column('inquiry', sa.Column('store_phone', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('inquiry', 'store_phone')
    op.drop_column('inquiry', 'owner_name')
