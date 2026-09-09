"""Opt-in Copilot telemetry; logical rollback retains quota and audit history."""
from alembic import op, context
import sqlalchemy as sa
from copilot.schema import TABLES

revision = "0004_copilot"
down_revision = "0003_org_billing"
branch_labels = depends_on = None


def upgrade():
    for table in TABLES:
        table.create(op.get_bind(), checkfirst=not context.is_offline_mode())
    op.execute("INSERT INTO copilot_schema_state(version,enabled) VALUES('0004_copilot',1) ON CONFLICT(version) DO UPDATE SET enabled=1")


def downgrade():
    if context.is_offline_mode():
        raise ValueError("Copilot rollback requires online inspection")
    if op.get_bind().execute(sa.text("SELECT 1 FROM copilot_usage WHERE status='reserved' LIMIT 1")).first():
        raise ValueError("Resolve pending Copilot calls before rollback")
    op.execute("UPDATE copilot_schema_state SET enabled=0 WHERE version='0004_copilot'")
