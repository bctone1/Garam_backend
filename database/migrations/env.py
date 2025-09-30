import os, sys
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool

# 1) 프로젝트 루트 경로 주입 (env.py: database/migrations/ 기준으로 두 단계 상위가 루트)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 2) DATABASE_URL 로드
from database.base import Base, DATABASE_URL
import models  # 모든 모델 로드


# 3) Alembic 설정
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 4) Alembic이 앱과 동일 DB를 보게 강제
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# 5) 메타데이터 지정
target_metadata = Base.metadata

def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
