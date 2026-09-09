"""Additive SaaS target and guarded logical rollback."""
from alembic import op, context
import sqlalchemy as sa
from persistence.database import Connection
from persistence.models import metadata, CORE_TABLES, RESOURCE_TABLES
from persistence.postgres_guards import install_guards, backfill_sql
from saas_schema import upgrade_connection, downgrade_connection

revision = "0002_saas_core"
down_revision = "0001_legacy_baseline"
branch_labels = depends_on = None

def native(bind):
    raw = bind.connection.driver_connection
    import sqlite3
    raw.row_factory = sqlite3.Row
    return raw

def upgrade():
    bind = op.get_bind()
    offline = context.is_offline_mode()
    if bind.dialect.name == "sqlite":
        if offline:
            raise ValueError("SQL offline disponible para PostgreSQL; SQLite necesita inspección online local")
        for name in CORE_TABLES:
            metadata.tables[name].create(bind, checkfirst=True)
        upgrade_connection(native(bind))
        return
    existing = set() if offline else set(sa.inspect(bind).get_table_names())
    for name in CORE_TABLES:
        if name not in existing:
            metadata.tables[name].create(bind, checkfirst=False)
    for name in ("clientes", *RESOURCE_TABLES):
        if offline or "organization_id" not in {c["name"] for c in sa.inspect(bind).get_columns(name)}:
            op.add_column(name, sa.Column("organization_id", sa.BigInteger))
            op.create_foreign_key(f"fk_{name}_organization_id_organizations", name, "organizations", ["organization_id"], ["id"], ondelete="RESTRICT")
            op.create_index(f"ix_{name}_organization", name, ["organization_id"])
    # Re-upgrade after logical rollback retains these constraints.
    if offline or not any(x["name"] == "uq_clientes_organization_id_id" for x in sa.inspect(bind).get_unique_constraints("clientes")):
        op.create_unique_constraint("uq_clientes_organization_id_id", "clientes", ["organization_id", "id"])
    for name in RESOURCE_TABLES:
        constraint = f"fk_{name}_tenant_account"
        if offline or not any(x["name"] == constraint for x in sa.inspect(bind).get_foreign_keys(name)):
            op.create_foreign_key(constraint, name, "clientes", ["organization_id", "cliente_id"], ["organization_id", "id"], ondelete="RESTRICT")
    for sql in backfill_sql():
        op.execute(sa.text(sql))
    for sql in install_guards():
        op.execute(sa.text(sql))

def downgrade():
    if context.is_offline_mode():
        raise ValueError("Rollback requiere inspeccionar actividad y generar informe previo")
    bind = op.get_bind()
    downgrade_connection(native(bind) if bind.dialect.name == "sqlite" else Connection(bind, owned=False))
