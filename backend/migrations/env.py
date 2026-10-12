from alembic import context
from sqlalchemy import engine_from_config, pool

cfg = context.config
with engine_from_config(cfg.get_section(cfg.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool).connect() as conn:
    context.configure(connection=conn, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
