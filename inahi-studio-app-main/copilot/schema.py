"""Frozen additive revision 0004. No prompts/responses/secrets stored."""
import sqlalchemy as sa
from billing.schema import metadata as previous

metadata = sa.MetaData()
for table in previous.tables.values():
    table.to_metadata(metadata)
ID = sa.BigInteger().with_variant(sa.Integer, "sqlite")
usage = sa.Table("copilot_usage", metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("organization_id", ID, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("user_id", ID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("request_key", sa.String(36), nullable=False),
    sa.Column("fingerprint", sa.String(64), nullable=False),
    sa.Column("feature", sa.String(32), nullable=False),
    sa.Column("provider", sa.String(32), nullable=False),
    sa.Column("model", sa.String(100), nullable=False),
    sa.Column("input_tokens", sa.BigInteger),
    sa.Column("output_tokens", sa.BigInteger),
    sa.Column("total_tokens", sa.BigInteger),
    sa.Column("estimated_cost", sa.Numeric(20, 10)),
    sa.Column("cost_currency", sa.String(3)),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.Column("source_count", sa.Integer, nullable=False),
    sa.UniqueConstraint("organization_id", "user_id", "request_key"),
    sa.ForeignKeyConstraint(["organization_id", "user_id"], ["organization_memberships.organization_id", "organization_memberships.user_id"], ondelete="RESTRICT"),
    sa.CheckConstraint("status IN ('reserved','succeeded','provider_error','invalid_output','denied_after_call','abandoned')"),
    sa.CheckConstraint("feature IN ('business_overview','client_analysis','sales_strategy','content','reports','pending_actions','opportunities')"),
    sa.CheckConstraint("input_tokens>=0 AND output_tokens>=0 AND total_tokens>=0 AND estimated_cost>=0 AND source_count>=0"),
)
sa.Index("ix_copilot_usage_organization_created", usage.c.organization_id, usage.c.created_at)
sa.Index("ix_copilot_usage_user_created", usage.c.organization_id, usage.c.user_id, usage.c.created_at)
state = sa.Table("copilot_schema_state", metadata,
    sa.Column("version", sa.String(32), primary_key=True),
    sa.Column("enabled", sa.Integer, nullable=False),
    sa.CheckConstraint("enabled IN (0,1)"),
)
TABLES = (usage, state)
