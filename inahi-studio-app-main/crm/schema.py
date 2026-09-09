"""Frozen additive revision 0005; composite tenant FKs, no legacy customer conversion."""
import sqlalchemy as sa
from copilot.schema import metadata as previous

metadata = sa.MetaData()
for existing in previous.tables.values():
    existing.to_metadata(metadata)
ID = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def identity():
    return [sa.Column("id", ID, sa.Identity(), primary_key=True),
            sa.Column("organization_id", ID, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)]


def owner():
    return [sa.Column("owner_user_id", ID), sa.ForeignKeyConstraint(["organization_id", "owner_user_id"], ["organization_memberships.organization_id", "organization_memberships.user_id"], ondelete="RESTRICT")]


CRMContact = sa.Table("crm_contacts", metadata, *identity(),
    *[sa.Column(key, sa.String(size), nullable=False, server_default="") for key, size in (("company_name",160),("contact_name",160),("email",254),("phone",40),("website",500),("source",100))],
    sa.Column("status", sa.String(16), nullable=False), *owner(), sa.Column("notes", sa.Text, nullable=False, server_default=""),
    *[sa.Column(key, sa.DateTime(timezone=True), nullable=key not in ("created_at", "updated_at")) for key in ("created_at", "updated_at", "last_contact_at", "next_followup_at", "archived_at")],
    sa.UniqueConstraint("organization_id", "id"), sa.CheckConstraint("status IN ('lead','prospect','customer','inactive')"),
    sa.CheckConstraint("company_name<>'' OR contact_name<>''"))
CRMOpportunity = sa.Table("crm_opportunities", metadata, *identity(),
    sa.Column("contact_id", ID, nullable=False), sa.Column("title", sa.String(180), nullable=False),
    sa.Column("stage", sa.String(20), nullable=False), sa.Column("estimated_value", sa.Numeric(14,2), nullable=False),
    sa.Column("probability", sa.Integer, nullable=False), sa.Column("expected_close_date", sa.Date), *owner(),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(["organization_id", "contact_id"], ["crm_contacts.organization_id", "crm_contacts.id"], ondelete="RESTRICT"),
    sa.CheckConstraint("stage IN ('new','contacted','qualified','proposal','negotiation','won','lost')"),
    sa.CheckConstraint("estimated_value>=0 AND probability>=0 AND probability<=100"))
CRMActivity = sa.Table("crm_activities", metadata, *identity(),
    sa.Column("contact_id", ID, nullable=False), sa.Column("user_id", ID, nullable=False),
    sa.Column("type", sa.String(16), nullable=False), sa.Column("description", sa.Text, nullable=False),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(["organization_id", "contact_id"], ["crm_contacts.organization_id", "crm_contacts.id"], ondelete="RESTRICT"),
    sa.ForeignKeyConstraint(["organization_id", "user_id"], ["organization_memberships.organization_id", "organization_memberships.user_id"], ondelete="RESTRICT"),
    sa.CheckConstraint("type IN ('call','email','meeting','note','followup')"))
state = sa.Table("crm_schema_state", metadata, sa.Column("version",sa.String(32),primary_key=True),sa.Column("enabled",sa.Integer,nullable=False),sa.CheckConstraint("enabled IN (0,1)"))
sa.Index("ix_crm_contacts_scope_status", CRMContact.c.organization_id, CRMContact.c.archived_at, CRMContact.c.status)
sa.Index("ix_crm_contacts_followup", CRMContact.c.organization_id, CRMContact.c.next_followup_at)
sa.Index("ix_crm_contacts_owner", CRMContact.c.organization_id, CRMContact.c.owner_user_id)
sa.Index("ix_crm_opportunities_contact", CRMOpportunity.c.organization_id, CRMOpportunity.c.contact_id)
sa.Index("ix_crm_opportunities_stage", CRMOpportunity.c.organization_id, CRMOpportunity.c.stage)
sa.Index("ix_crm_activities_contact_time", CRMActivity.c.organization_id, CRMActivity.c.contact_id, CRMActivity.c.occurred_at)
TABLES = (CRMContact, CRMOpportunity, CRMActivity, state)
