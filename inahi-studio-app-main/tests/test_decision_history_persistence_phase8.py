from datetime import datetime, timezone
from types import SimpleNamespace
import sqlalchemy as sa
from crm.decision_history_schema import DecisionSnapshot
from crm.decision_history import capture_snapshot, recent_snapshots


def _test_metadata():
    """Minimal dialect-neutral schema for persistence helper tests."""
    metadata = sa.MetaData()
    sa.Table(
        "organizations", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )
    sa.Table(
        "organization_memberships", metadata,
        sa.Column("organization_id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, primary_key=True),
    )
    sa.Table(
        "crm_opportunities", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, nullable=False),
        sa.UniqueConstraint("organization_id", "id"),
    )
    DecisionSnapshot.to_metadata(metadata)
    return metadata


def test_decision_snapshot_is_persisted_and_tenant_scoped():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = _test_metadata()
    metadata.create_all(engine)
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    assessment = SimpleNamespace(
        opportunity_id=10, owner_user_id=None, risk_score=72,
        decision_priority=88, money_at_risk=1250,
        recommended_action="Contactar hoy", why_now="Seguimiento vencido",
        attention_age_days=9,
    )
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO organizations(id) VALUES(1)"))
        connection.execute(sa.text("INSERT INTO crm_opportunities(id,organization_id) VALUES(10,1)"))
        snapshot_id = capture_snapshot(connection, 1, assessment, now)
        rows = recent_snapshots(connection, 1)
        assert snapshot_id == rows[0]["id"]
        assert rows[0]["risk_score"] == 72
        assert recent_snapshots(connection, 2) == []
    engine.dispose()


def test_recent_snapshots_never_cross_organization_boundary():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = _test_metadata()
    metadata.create_all(engine)
    with engine.begin() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(metadata.tables["decision_snapshots"])).scalar_one() == 0
        assert recent_snapshots(connection, 99) == []
    engine.dispose()
