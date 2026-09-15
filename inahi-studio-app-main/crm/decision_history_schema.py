"""Phase 8 persistent decision-history schema.

Additive, tenant-scoped tables for auditable INAHI Today snapshots and observed
outcomes. These records support decision review; they do not claim causality.
"""
import sqlalchemy as sa
from crm.schema import metadata as previous

metadata = sa.MetaData()
for existing in previous.tables.values():
    existing.to_metadata(metadata)

ID = sa.BigInteger().with_variant(sa.Integer, "sqlite")

# PostgreSQL requires the referenced columns of a composite FK to be backed by
# a UNIQUE/PRIMARY constraint. Older Phase 5-7 databases only guaranteed the
# opportunity primary key, so Phase 8 explicitly establishes the tenant pair.
CRMOpportunity = metadata.tables["crm_opportunities"]
if not any(
    isinstance(constraint, sa.UniqueConstraint)
    and {column.name for column in constraint.columns} == {"organization_id", "id"}
    for constraint in CRMOpportunity.constraints
):
    sa.UniqueConstraint(
        CRMOpportunity.c.organization_id,
        CRMOpportunity.c.id,
        name="uq_crm_opportunities_organization_id_id",
    )

DecisionSnapshot = sa.Table(
    "decision_snapshots", metadata,
    sa.Column("id", ID, sa.Identity(), primary_key=True),
    sa.Column("organization_id", ID, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("opportunity_id", ID, nullable=False),
    sa.Column("owner_user_id", ID),
    sa.Column("risk_score", sa.Integer, nullable=False),
    sa.Column("decision_priority", sa.Integer, nullable=False),
    sa.Column("money_at_risk", sa.Numeric(14, 2), nullable=False),
    sa.Column("recommended_action", sa.Text, nullable=False),
    sa.Column("why_now", sa.Text, nullable=False, server_default=""),
    sa.Column("attention_age_days", sa.Integer, nullable=False, server_default="0"),
    sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(["organization_id", "opportunity_id"], ["crm_opportunities.organization_id", "crm_opportunities.id"], ondelete="RESTRICT"),
    sa.ForeignKeyConstraint(["organization_id", "owner_user_id"], ["organization_memberships.organization_id", "organization_memberships.user_id"], ondelete="RESTRICT"),
    sa.CheckConstraint("risk_score>=0 AND risk_score<=100"),
    sa.CheckConstraint("decision_priority>=0 AND decision_priority<=100"),
    sa.CheckConstraint("money_at_risk>=0"),
    sa.CheckConstraint("attention_age_days>=0"),
    sa.UniqueConstraint("organization_id", "id"),
)

DecisionOutcomeRecord = sa.Table(
    "decision_outcome_records", metadata,
    sa.Column("id", ID, sa.Identity(), primary_key=True),
    sa.Column("organization_id", ID, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("snapshot_id", ID, nullable=False),
    sa.Column("action_taken", sa.Boolean, nullable=False),
    sa.Column("outcome", sa.String(24), nullable=False),
    sa.Column("effectiveness_score", sa.Integer, nullable=False),
    sa.Column("previous_risk_score", sa.Integer, nullable=False),
    sa.Column("current_risk_score", sa.Integer, nullable=False),
    sa.Column("previous_probability", sa.Integer, nullable=False),
    sa.Column("current_probability", sa.Integer, nullable=False),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("explanation", sa.Text, nullable=False, server_default=""),
    sa.ForeignKeyConstraint(["organization_id", "snapshot_id"], ["decision_snapshots.organization_id", "decision_snapshots.id"], ondelete="RESTRICT"),
    sa.CheckConstraint("outcome IN ('improved','worsened','stable','not_executed')"),
    sa.CheckConstraint("effectiveness_score>=0 AND effectiveness_score<=100"),
    sa.CheckConstraint("previous_risk_score>=0 AND previous_risk_score<=100"),
    sa.CheckConstraint("current_risk_score>=0 AND current_risk_score<=100"),
    sa.CheckConstraint("previous_probability>=0 AND previous_probability<=100"),
    sa.CheckConstraint("current_probability>=0 AND current_probability<=100"),
    sa.UniqueConstraint("organization_id", "id"),
)

state = sa.Table(
    "decision_history_schema_state", metadata,
    sa.Column("version", sa.String(32), primary_key=True),
    sa.Column("enabled", sa.Integer, nullable=False),
    sa.CheckConstraint("enabled IN (0,1)"),
)

sa.Index("ix_decision_snapshots_scope_time", DecisionSnapshot.c.organization_id, DecisionSnapshot.c.captured_at)
sa.Index("ix_decision_snapshots_opportunity", DecisionSnapshot.c.organization_id, DecisionSnapshot.c.opportunity_id, DecisionSnapshot.c.captured_at)
sa.Index("ix_decision_outcomes_snapshot", DecisionOutcomeRecord.c.organization_id, DecisionOutcomeRecord.c.snapshot_id, DecisionOutcomeRecord.c.observed_at)

TABLES = (DecisionSnapshot, DecisionOutcomeRecord, state)
