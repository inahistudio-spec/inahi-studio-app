"""No app import, no schema creation on startup, configuration from environment only."""
from alembic import context
from persistence.database import configured_url, make_engine
from crm.schema import metadata

config = context.config
if context.is_offline_mode():
    context.configure(url=configured_url(), target_metadata=metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    # Online operations must pass the report/preflight service, including the CLI.
    connection = config.attributes.get("connection")
    if connection is None:
        raise RuntimeError("Use flask db-upgrade/db-downgrade con --report-file; no migración online directa")
    context.configure(connection=connection, target_metadata=metadata, transactional_ddl=True,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
