# versions/20251002_model_singleton.py
from alembic import op
import sqlalchemy as sa

revision = "20251002_model_singleton"
down_revision = "20251002_prune_model_columns"
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    # 1) 행 1개로 정규화
    conn.exec_driver_sql("""
        DO $$
        BEGIN
          IF (SELECT COUNT(*) FROM model) = 0 THEN
            INSERT INTO model (id, name, accuracy, avg_response_time_ms, month_conversations,
                               uptime_percent, response_style, block_inappropriate, restrict_non_tech,
                               fast_response_mode, suggest_agent_handoff)
            VALUES (1, 'default', 0, 0, 0, 0, 'professional', false, false, false, false);
          ELSE
            -- 임의의 최신 한 행만 남기고 id=1로 설정
            WITH x AS (
              SELECT id FROM model ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST, id ASC LIMIT 1
            )
            UPDATE model SET id = 1 WHERE id = (SELECT id FROM x);
            DELETE FROM model WHERE id <> 1;
          END IF;
        END $$;
    """)
    # 2) id 기본값을 1로, 시퀀스 의존 제거
    conn.exec_driver_sql("ALTER TABLE model ALTER COLUMN id SET DEFAULT 1;")
    # 3) 싱글톤 체크
    op.create_check_constraint("chk_model_singleton", "model", "id = 1")

def downgrade():
    op.drop_constraint("chk_model_singleton", "model", type_="check")
    # 필요시 기본값 해제
    op.execute("ALTER TABLE model ALTER COLUMN id DROP DEFAULT;")
