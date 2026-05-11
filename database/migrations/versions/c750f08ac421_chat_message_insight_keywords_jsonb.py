"""chat_message_insight_keywords_jsonb

Revision ID: c750f08ac421
Revises: 72dda9c8565e
Create Date: 2026-01-16 10:59:52.128461

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c750f08ac421'
down_revision: Union[str, Sequence[str], None] = '72dda9c8565e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.alter_column(
        "chat_message_insight",
        "keywords",
        type_=postgresql.JSONB(),
        postgresql_using="keywords::jsonb",
        existing_type=postgresql.JSON(),
        existing_nullable=True,
    )

def downgrade():
    op.alter_column(
        "chat_message_insight",
        "keywords",
        type_=postgresql.JSON(),
        postgresql_using="keywords::json",
        existing_type=postgresql.JSONB(),
        existing_nullable=True,
    )