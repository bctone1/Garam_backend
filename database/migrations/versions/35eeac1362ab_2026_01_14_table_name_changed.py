"""2026-01-14_table name changed

Revision ID: 35eeac1362ab
Revises: 9515948b9cab
Create Date: 2026-01-14 11:22:18.411279
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "35eeac1362ab"
down_revision = "9515948b9cab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("inquiry")}

    # 1) company -> business_number
    if "company" in cols and "business_number" not in cols:
        op.alter_column(
            "inquiry",
            "company",
            new_column_name="business_number",
            existing_type=sa.String(),
        )

    # 2) customer_name -> business_name
    if "customer_name" in cols and "business_name" not in cols:
        op.alter_column(
            "inquiry",
            "customer_name",
            new_column_name="business_name",
            existing_type=sa.String(),
        )

    # 3) business_number nullable 보장
    cols = {c["name"] for c in insp.get_columns("inquiry")}
    if "business_number" in cols:
        op.alter_column(
            "inquiry",
            "business_number",
            existing_type=sa.String(),
            nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("inquiry")}

    # 역순 rename
    if "business_name" in cols and "customer_name" not in cols:
        op.alter_column(
            "inquiry",
            "business_name",
            new_column_name="customer_name",
            existing_type=sa.String(),
        )

    if "business_number" in cols and "company" not in cols:
        op.alter_column(
            "inquiry",
            "business_number",
            new_column_name="company",
            existing_type=sa.String(),
        )
