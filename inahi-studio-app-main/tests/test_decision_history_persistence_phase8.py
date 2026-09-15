from datetime import datetime, timezone
from types import SimpleNamespace
import sqlalchemy as sa
from crm.decision_history_schema import metadata, DecisionSnapshot
from crm.decision_history import capture_snapshot, recent_snapshots


def test_decision_snapshot_is_persisted_and_tenant_scoped():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    assessment = SimpleNamespace(
        opportunity_id=10, owner_user_id=None, risk_score=72,
        decision_priority=88, money_at_risk=1250,
        recommended_action="Contactar hoy", why_now="Seguimiento vencido",
        attention_age_days=9,
    )
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO organizations(id,name,slug,status,created_at) VALUES(1,'Org','org','active',:now)"), {"now": now})
        connection.execute(sa.text("INSERT INTO crm_contacts(id,organization_id,company_name,contact_name,email,phone,website,source,status,notes,created_at,updated_at) VALUES(5,1,'ACME','','','','','','lead','',:now,:now)"), {"now": now})
        connection.execute(sa.text("INSERT INTO crm_opportunities(id,organization_id,contact_id,title,stage,estimated_value,probability,created_at,updated_at) VALUES(10,1,5,'Deal','proposal',5000,50,:now,:now)"), {"now": now})
        snapshot_id = capture_snapshot(connection, 1, assessment, now)
        rows = recent_snapshots(connection, 1)
        assert snapshot_id == rows[0]["id"]
        assert rows[0]["risk_score"] == 72
        assert recent_snapshots(connection, 2) == []
    engine.dispose()


def test_recent_snapshots_never_cross_organization_boundary():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(DecisionSnapshot)).scalar_one() == 0
        assert recent_snapshots(connection, 99) == []
    engine.dispose()
