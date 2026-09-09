"""Frozen revision 0003 tables. Phase 2 metadata remains unchanged."""
import sqlalchemy as sa
from persistence.models import metadata as phase_two

metadata = sa.MetaData()
for table in phase_two.tables.values():
    table.to_metadata(metadata)
ID = sa.BigInteger().with_variant(sa.Integer, "sqlite")
subscriptions = sa.Table("organization_subscriptions", metadata,
    sa.Column("organization_id", ID, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), primary_key=True),
    sa.Column("plan", sa.String(32), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("stripe_customer_id", sa.Text, unique=True),
    sa.Column("stripe_subscription_id", sa.Text, unique=True),
    sa.Column("current_period_start", sa.DateTime(timezone=True)),
    sa.Column("current_period_end", sa.DateTime(timezone=True)),
    sa.Column("cancel_at_period_end", sa.Integer, nullable=False, server_default="0"),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("legacy_mode", sa.Integer, nullable=False, server_default="0"),
    sa.Column("customer_key", sa.Text, nullable=False, unique=True),
    sa.Column("checkout_key", sa.Text),
    sa.Column("checkout_plan", sa.String(32)),
    sa.Column("checkout_price_id", sa.Text),
    sa.Column("checkout_id", sa.Text),
    sa.Column("checkout_url", sa.Text),
    sa.Column("checkout_expires_at", sa.BigInteger),
    sa.CheckConstraint("plan IN ('STARTER','PROFESSIONAL','BUSINESS','ENTERPRISE')"),
    sa.CheckConstraint("status IN ('trialing','active','past_due','canceled','incomplete')"),
    sa.CheckConstraint("cancel_at_period_end IN (0,1) AND legacy_mode IN (0,1)"),
)
usage = sa.Table("billing_usage", metadata,
    sa.Column("organization_id", ID, sa.ForeignKey("organization_subscriptions.organization_id", ondelete="RESTRICT"), primary_key=True),
    sa.Column("metric", sa.String(32), primary_key=True),
    sa.Column("period", sa.String(16), primary_key=True),
    sa.Column("amount", sa.BigInteger, nullable=False, server_default="0"),
    sa.CheckConstraint("amount>=0"),
    sa.CheckConstraint("metric IN ('members','clients','ai','automations','reports')"),
)
events = sa.Table("billing_events", metadata,
    sa.Column("event_id", sa.Text, primary_key=True),
    sa.Column("organization_id", ID, sa.ForeignKey("organization_subscriptions.organization_id", ondelete="RESTRICT"), nullable=False),
    sa.Column("event_type", sa.Text, nullable=False),
    sa.Column("event_created", sa.BigInteger, nullable=False),
    sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
)
sa.Index("ix_billing_events_organization", events.c.organization_id, events.c.processed_at)
state = sa.Table("billing_schema_state", metadata,
    sa.Column("version", sa.String(32), primary_key=True),
    sa.Column("enabled", sa.Integer, nullable=False),
    sa.CheckConstraint("enabled IN (0,1)"),
)
TABLES = (subscriptions, usage, events, state)
