"""Persistence helpers for auditable INAHI Today decision snapshots."""
from datetime import datetime, timezone
from decimal import Decimal
import sqlalchemy as sa
from crm.decision_history_schema import DecisionSnapshot, DecisionOutcomeRecord


def _value(item, name, default=None):
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def capture_snapshot(connection, organization_id, assessment, captured_at=None):
    """Persist one tenant-scoped assessment and return its snapshot id."""
    captured_at = captured_at or datetime.now(timezone.utc)
    values = {
        "organization_id": organization_id,
        "opportunity_id": _value(assessment, "opportunity_id"),
        "owner_user_id": _value(assessment, "owner_user_id"),
        "risk_score": int(_value(assessment, "risk_score", 0)),
        "decision_priority": int(_value(assessment, "decision_priority", 0)),
        "money_at_risk": Decimal(str(_value(assessment, "money_at_risk", 0))),
        "recommended_action": str(_value(assessment, "recommended_action", "")),
        "why_now": str(_value(assessment, "why_now", "")),
        "attention_age_days": int(_value(assessment, "attention_age_days", 0)),
        "captured_at": captured_at,
    }
    result = connection.execute(sa.insert(DecisionSnapshot).values(**values).returning(DecisionSnapshot.c.id))
    return result.scalar_one()


def capture_today(connection, organization_id, today_snapshot, captured_at=None):
    """Persist the current INAHI Today priorities already scoped to one tenant."""
    priorities = _value(today_snapshot, "priorities", []) or []
    return [capture_snapshot(connection, organization_id, item, captured_at) for item in priorities]


def recent_snapshots(connection, organization_id, limit=50):
    """Return newest decision snapshots for exactly one organization."""
    query = (
        sa.select(DecisionSnapshot)
        .where(DecisionSnapshot.c.organization_id == organization_id)
        .order_by(DecisionSnapshot.c.captured_at.desc(), DecisionSnapshot.c.id.desc())
        .limit(max(1, min(int(limit), 200)))
    )
    return [dict(row._mapping) for row in connection.execute(query)]


def record_outcome(connection, organization_id, snapshot_id, outcome, observed_at=None):
    """Persist an observed outcome without making a causal claim."""
    observed_at = observed_at or datetime.now(timezone.utc)
    values = {
        "organization_id": organization_id,
        "snapshot_id": snapshot_id,
        "action_taken": bool(_value(outcome, "action_taken", False)),
        "outcome": str(_value(outcome, "outcome")),
        "effectiveness_score": int(_value(outcome, "effectiveness_score", 0)),
        "previous_risk_score": int(_value(outcome, "previous_risk_score", 0)),
        "current_risk_score": int(_value(outcome, "current_risk_score", 0)),
        "previous_probability": int(_value(outcome, "previous_probability", 0)),
        "current_probability": int(_value(outcome, "current_probability", 0)),
        "observed_at": observed_at,
        "explanation": str(_value(outcome, "explanation", "")),
    }
    result = connection.execute(sa.insert(DecisionOutcomeRecord).values(**values).returning(DecisionOutcomeRecord.c.id))
    return result.scalar_one()
