"""chat_message_category

Revision ID: 28b1837d2cc4
Revises: c750f08ac421
Create Date: 2026-01-16 15:43:40.257291

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "28b1837d2cc4"
down_revision: Union[str, Sequence[str], None] = "c750f08ac421"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # ---------------------------------------------------------
    # 0) quick_category 시퀀스 꼬임 방지 + etc row(없으면만) 생성
    # ---------------------------------------------------------
    # 시퀀스가 뒤로 가 있으면 nextval이 기존 id를 다시 뽑아서 PK 충돌이 난다.
    # quick_category.id가 serial/identity면 pg_get_serial_sequence가 시퀀스명을 준다.
    bind.execute(
        sa.text(
            """
            DO $$
            DECLARE
              seq_name text;
              max_id bigint;
            BEGIN
              SELECT pg_get_serial_sequence('quick_category', 'id') INTO seq_name;
              IF seq_name IS NOT NULL THEN
                SELECT COALESCE(MAX(id), 0) INTO max_id FROM quick_category;
            
                IF max_id < 1 THEN
                  -- 테이블이 비어있으면 nextval이 1 나오게 세팅
                  EXECUTE format('SELECT setval(%L, 1, false)', seq_name);
                ELSE
                  -- 데이터가 있으면 nextval이 max_id+1 나오게 세팅
                  EXECUTE format('SELECT setval(%L, %s, true)', seq_name, max_id);
                END IF;
              END IF;
            END $$;
            """
        )
    )

    # etc row는 없으면만 생성 (id는 시퀀스로)
    bind.execute(
        sa.text(
            """
            INSERT INTO quick_category (icon_emoji, name, description, sort_order)
            SELECT :emoji, :name, :desc, :sort_order
            WHERE NOT EXISTS (
                SELECT 1 FROM quick_category WHERE lower(name) = lower(:name)
            )
            """
        ),
        {
            "emoji": "🗂️",
            "name": "etc",
            "desc": "기타",
            "sort_order": 9999,
        },
    )

    # ---------------------------------------------------------
    # 1) chat_session_insight: quick_category_id 추가 + FK + 인덱스
    # ---------------------------------------------------------
    op.add_column(
        "chat_session_insight",
        sa.Column("quick_category_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_s_insight_quick_category",
        "chat_session_insight",
        "quick_category",
        ["quick_category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_chat_s_insight_qc_started_at",
        "chat_session_insight",
        ["quick_category_id", "started_at"],
    )

    # ---------------------------------------------------------
    # 2) chat_keyword_daily: category 삭제 + quick_category_id 추가 + UNIQUE 교체
    # ---------------------------------------------------------
    op.add_column(
        "chat_keyword_daily",
        sa.Column("quick_category_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_kw_daily_quick_category",
        "chat_keyword_daily",
        "quick_category",
        ["quick_category_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 기존 UNIQUE/인덱스 제거(있으면만)
    op.execute(sa.text("ALTER TABLE chat_keyword_daily DROP CONSTRAINT IF EXISTS uq_chat_kw_daily"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_chat_kw_daily_dt_category"))

    # category 컬럼 제거
    op.drop_column("chat_keyword_daily", "category")

    # 새 UNIQUE/인덱스 생성
    op.create_unique_constraint(
        "uq_chat_kw_daily",
        "chat_keyword_daily",
        ["dt", "keyword", "channel", "quick_category_id"],
    )
    op.create_index(
        "idx_chat_kw_daily_dt_qc",
        "chat_keyword_daily",
        ["dt", "quick_category_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()

    # ---------------------------------------------------------
    # 2) chat_keyword_daily 되돌리기
    # ---------------------------------------------------------
    op.execute(sa.text("ALTER TABLE chat_keyword_daily DROP CONSTRAINT IF EXISTS uq_chat_kw_daily"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_chat_kw_daily_dt_qc"))

    op.add_column(
        "chat_keyword_daily",
        sa.Column("category", sa.String(length=64), nullable=True),
    )

    op.create_unique_constraint(
        "uq_chat_kw_daily",
        "chat_keyword_daily",
        ["dt", "keyword", "channel", "category"],
    )
    op.create_index(
        "idx_chat_kw_daily_dt_category",
        "chat_keyword_daily",
        ["dt", "category"],
    )

    op.drop_constraint("fk_chat_kw_daily_quick_category", "chat_keyword_daily", type_="foreignkey")
    op.drop_column("chat_keyword_daily", "quick_category_id")

    # ---------------------------------------------------------
    # 1) chat_session_insight 되돌리기
    # ---------------------------------------------------------
    op.execute(sa.text("DROP INDEX IF EXISTS idx_chat_s_insight_qc_started_at"))
    op.drop_constraint("fk_chat_s_insight_quick_category", "chat_session_insight", type_="foreignkey")
    op.drop_column("chat_session_insight", "quick_category_id")

    # etc row는 롤백에서 굳이 삭제 안 함(데이터 보존)
