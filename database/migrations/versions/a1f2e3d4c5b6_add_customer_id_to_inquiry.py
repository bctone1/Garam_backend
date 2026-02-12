"""add customer_id to inquiry

Revision ID: a1f2e3d4c5b6
Revises: b73421a19ddf
Create Date: 2026-02-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1f2e3d4c5b6'
down_revision: Union[str, None] = 'b73421a19ddf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('inquiry', sa.Column('customer_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_inquiry_customer_id',
        'inquiry', 'customer',
        ['customer_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('idx_inquiry_customer_id', 'inquiry', ['customer_id'])


def downgrade() -> None:
    op.drop_index('idx_inquiry_customer_id', table_name='inquiry')
    op.drop_constraint('fk_inquiry_customer_id', 'inquiry', type_='foreignkey')
    op.drop_column('inquiry', 'customer_id')
