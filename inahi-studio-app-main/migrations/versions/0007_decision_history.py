"""Persist tenant-scoped decision snapshots and observed outcomes."""
from alembic import op, context
import sqlalchemy as sa
from crm.decision_history_schema import TABLES

revision = "0007_decision_history"
down_revision = "0006_ai_staging"
branch_labels = depends_on = None


def _ensure_opportunity_tenant_key(bind):
    """Ensure PostgreSQL can target (organization_id, id) with a composite FK."""
    if bind.dialect.name != "postgresql":
        return
    bind.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_opportunities_organization_id_id "
        "ON crm_opportunities (organization_id, id)"
    ))


def upgrade():
    bind = op.get_bind()
    _ensure_opportunity_tenant_key(bind)
    for table in TABLES:
        table.create(bind, checkfirst=not context.is_offline_mode())
    op.execute("INSERT INTO decision_history_schema_state(version,enabled) VALUES('0007_decision_history',1) ON CONFLICT(version) DO UPDATE SET enabled=1")


def downgrade():
    if context.is_offline_mode():
        raise ValueError("Rollback requires online inspection")
    bind = op.get_bind()
    outcomes = bind.execute(sa.text("SELECT 1 FROM decision_outcome_records LIMIT 1")).first()
    snapshots = bind.execute(sa.text("SELECT 1 FROM decision_snapshots LIMIT 1")).first()
    if outcomes or snapshots:
        raise ValueError("Decision history contains audit data; export or explicitly resolve it before rollback")
    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)
