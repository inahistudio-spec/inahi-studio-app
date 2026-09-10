"""Explicit AI budgets, latency, alerts and feature flags; no external calls."""
from alembic import op, context
import sqlalchemy as sa
from copilot.staging_schema import TABLES
revision = '0006_ai_staging'
down_revision = '0005_crm'
branch_labels = depends_on = None


def upgrade():
    for table in TABLES:
        table.create(op.get_bind(),checkfirst=not context.is_offline_mode())
    op.execute("INSERT INTO ai_staging_state(version,enabled) VALUES('0006_ai_staging',1) ON CONFLICT(version) DO UPDATE SET enabled=1")


def downgrade():
    if context.is_offline_mode():
        raise ValueError('Rollback requires online inspection')
    if op.get_bind().execute(sa.text("SELECT 1 FROM copilot_usage WHERE status='reserved' LIMIT 1")).first():
        raise ValueError('Resolve pending calls before rollback')
    op.execute('UPDATE organization_ai_policies SET external_enabled=0')
    op.execute("UPDATE ai_staging_state SET enabled=0 WHERE version='0006_ai_staging'")
