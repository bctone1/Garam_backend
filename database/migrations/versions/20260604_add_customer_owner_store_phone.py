"""add owner_name and store_phone to customer

Revision ID: 20260604_customer_owner_store_phone
Revises: 20260514_archived_at
Create Date: 2026-06-04

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '20260604_cust_owner_store'
down_revision: Union[str, Sequence[str], None] = '20260514_archived_at'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('customer', sa.Column('owner_name', sa.String(), nullable=True))
    op.add_column('customer', sa.Column('store_phone', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('customer', 'store_phone')
    op.drop_column('customer', 'owner_name')
