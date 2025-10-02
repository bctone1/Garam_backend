# database/migrations/versions/20251002_message_cols_nullable.py
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# Alembic identifiers
revision = "20251002_message_cols_nullable"
down_revision = "20251002_model_singleton"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("message", "vector_memory",
                    existing_type=Vector(1536), nullable=True)
    op.alter_column("message", "response_latency_ms",
                    existing_type=sa.Integer(), nullable=True)


def downgrade():
    # NULL 존재 시 원복 불가
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM message
        WHERE vector_memory IS NULL OR response_latency_ms IS NULL
      ) THEN
        RAISE EXCEPTION 'Downgrade blocked: NULLs exist in message.vector_memory or response_latency_ms';
      END IF;
    END $$;
    """)
    op.alter_column("message", "response_latency_ms",
                    existing_type=sa.Integer(), nullable=False)
    op.alter_column("message", "vector_memory",
                    existing_type=Vector(1536), nullable=False)
