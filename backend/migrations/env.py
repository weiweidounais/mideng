"""Run migrations through the caller's connection or the configured database."""
from alembic import context
from sqlalchemy import create_engine
from app.config import config as app_config
from app.db import Base

migration_config = context.config

def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata,
                      compare_type=True, render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()

if context.is_offline_mode():
    # This initial baseline introspects old prototype databases; use online mode.
    raise RuntimeError("本项目初始迁移需要在线连接数据库，请运行 alembic upgrade head")
else:
    provided = migration_config.attributes.get("connection")
    if provided is not None:
        run(provided)
    else:
        engine = create_engine(app_config.sql_url, pool_pre_ping=True)
        with engine.begin() as connection:
            run(connection)
        engine.dispose()
