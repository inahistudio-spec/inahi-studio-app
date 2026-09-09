"""Explicit organization billing expansion; no automatic legacy adoption."""
from alembic import op, context
import sqlalchemy as sa
from billing.schema import TABLES

revision = "0003_org_billing"
down_revision = "0002_saas_core"
branch_labels = depends_on = None


def upgrade():
    for table in TABLES:
        table.create(op.get_bind(), checkfirst=not context.is_offline_mode())
    op.execute("INSERT INTO billing_schema_state(version,enabled) VALUES('0003_org_billing',1) ON CONFLICT(version) DO UPDATE SET enabled=1")


def downgrade():
    if context.is_offline_mode():
        raise ValueError("Rollback billing necesita inspección online e informe")
    bind = op.get_bind()
    for sql in (
        "SELECT 1 FROM billing_events LIMIT 1",
        "SELECT 1 FROM billing_usage WHERE amount>0 LIMIT 1",
        "SELECT 1 FROM organization_subscriptions WHERE legacy_mode=0 OR checkout_key IS NOT NULL LIMIT 1",
        "SELECT 1 FROM saas_audit WHERE action LIKE 'billing_%' LIMIT 1",
    ):
        if bind.execute(sa.text(sql)).first():
            raise ValueError("Actividad billing nueva: reconciliar antes del rollback")
    op.execute("UPDATE billing_schema_state SET enabled=0 WHERE version='0003_org_billing'")
