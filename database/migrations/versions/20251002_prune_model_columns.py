# database/migrations/versions/20251002_prune_model_columns.py
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20251002_prune_model_columns"
down_revision = "912620c0ced6"
branch_labels = None
depends_on = None


def _drop_index_if_exists(name: str):
    # schema 미지정 시 public 기본
    op.execute(f'DROP INDEX IF EXISTS "{name}"')


def upgrade():
    # 인덱스/부분 유니크는 IF EXISTS로 안전 삭제
    _drop_index_if_exists("uq_model_active_one")
    _drop_index_if_exists("idx_model_active")
    _drop_index_if_exists("idx_model_provider")
    _drop_index_if_exists("idx_model_features_gin")

    # 컬럼 삭제
    with op.batch_alter_table("model") as b:
        # 존재 여부 체크 후 드롭
        for col in ["provider_name", "description", "features", "is_active", "status_text"]:
            try:
                b.drop_column(col)
            except Exception:
                # 이미 제거된 경우 무시
                pass


def downgrade():
    with op.batch_alter_table("model") as b:
        b.add_column(sa.Column("provider_name", sa.Text(), nullable=False, server_default=sa.text("''")))
        b.add_column(sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")))
        b.add_column(sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
        b.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        b.add_column(sa.Column("status_text", sa.Text(), nullable=False, server_default=sa.text("''")))

    # default 제거(선택)
    op.execute("ALTER TABLE model ALTER COLUMN provider_name DROP DEFAULT;")
    op.execute("ALTER TABLE model ALTER COLUMN description DROP DEFAULT;")
    op.execute("ALTER TABLE model ALTER COLUMN features DROP DEFAULT;")
    op.execute("ALTER TABLE model ALTER COLUMN is_active DROP DEFAULT;")
    op.execute("ALTER TABLE model ALTER COLUMN status_text DROP DEFAULT;")

    # 인덱스 복구
    op.execute('CREATE UNIQUE INDEX IF NOT EXISTS "uq_model_active_one" ON "model" ((true)) WHERE is_active')
    op.execute('CREATE INDEX IF NOT EXISTS "idx_model_active" ON "model" (is_active DESC)')
    op.execute('CREATE INDEX IF NOT EXISTS "idx_model_provider" ON "model" (provider_name)')
    # 필요시 GIN 인덱스 복구:
    # op.execute('CREATE INDEX IF NOT EXISTS "idx_model_features_gin" ON "model" USING gin (features)')
