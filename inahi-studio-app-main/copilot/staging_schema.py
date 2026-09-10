"""Frozen 0006 metadata: policy and telemetry sidecars preserve previous revisions."""
import sqlalchemy as sa
from crm.schema import metadata as previous

metadata = sa.MetaData()
for table in previous.tables.values():
    table.to_metadata(metadata)
ID = sa.BigInteger().with_variant(sa.Integer, 'sqlite')
policies = sa.Table('organization_ai_policies', metadata,
    sa.Column('organization_id', ID, sa.ForeignKey('organizations.id', ondelete='RESTRICT'), primary_key=True),
    sa.Column('external_enabled', sa.Integer, nullable=False, server_default='0'),
    sa.Column('monthly_budget_usd', sa.Numeric(20,10), nullable=False, server_default='0'),
    sa.Column('block_at_budget', sa.Integer, nullable=False, server_default='1'),
    sa.Column('requests_per_minute', sa.Integer, nullable=False, server_default='5'),
    sa.Column('max_inflight', sa.Integer, nullable=False, server_default='2'),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('external_enabled IN (0,1) AND block_at_budget IN (0,1)'),
    sa.CheckConstraint('monthly_budget_usd>=0 AND requests_per_minute BETWEEN 1 AND 100 AND max_inflight BETWEEN 1 AND 10'))
calls = sa.Table('ai_call_controls', metadata,
    sa.Column('call_id', sa.String(36), sa.ForeignKey('copilot_usage.id', ondelete='RESTRICT'), primary_key=True),
    *[sa.Column(key,sa.Numeric(20,10),nullable=False) for key in ('reserved_usd','charged_usd','input_rate','output_rate')],
    sa.Column('cost_known',sa.Integer,nullable=False,server_default='0'),
    sa.Column('latency_ms',sa.BigInteger),
    sa.Column('error_code',sa.String(32)),
    sa.Column('delivered_provider',sa.String(32)),
    sa.Column('delivered_model',sa.String(100)),
    sa.Column('fallback',sa.Integer,nullable=False,server_default='0'),
    sa.CheckConstraint('reserved_usd>=0 AND charged_usd>=0 AND input_rate>=0 AND output_rate>=0 AND latency_ms>=0'),
    sa.CheckConstraint('cost_known IN (0,1) AND fallback IN (0,1)'))
alerts = sa.Table('ai_budget_alerts',metadata,
    sa.Column('organization_id',ID,sa.ForeignKey('organizations.id',ondelete='RESTRICT'),primary_key=True),
    sa.Column('period',sa.String(7),primary_key=True),
    sa.Column('threshold',sa.Integer,primary_key=True),
    sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
    sa.CheckConstraint('threshold IN (70,90,100)'))
state = sa.Table('ai_staging_state',metadata,sa.Column('version',sa.String(32),primary_key=True),sa.Column('enabled',sa.Integer,nullable=False),sa.CheckConstraint('enabled IN (0,1)'))
manifests = sa.Table('ai_synthetic_manifests',metadata,
    sa.Column('organization_id',ID,sa.ForeignKey('organizations.id',ondelete='RESTRICT'),primary_key=True),
    sa.Column('dataset_version',sa.String(32),nullable=False),
    sa.Column('digest',sa.String(64),nullable=False),
    sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
TABLES = (policies,calls,alerts,state,manifests)
