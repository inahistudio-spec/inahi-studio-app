from datetime import datetime, timezone
from crm.decision_history_view import history_summary


def test_history_summary_prepares_auditable_timeline():
    rows = [{
        "id": 1, "risk_score": 74, "decision_priority": 89,
        "money_at_risk": 1250, "attention_age_days": 12,
        "recommended_action": "Llamar hoy", "why_now": "Seguimiento vencido",
        "captured_at": datetime(2026, 9, 15, 18, 30, tzinfo=timezone.utc),
    }]
    summary = history_summary(rows)
    assert summary["count"] == 1
    assert summary["money_at_risk"] == 1250.0
    assert summary["high_priority"] == 1
    assert summary["items"][0]["captured_label"] == "15/09/2026 18:30"


def test_history_summary_is_empty_without_persisted_snapshots():
    assert history_summary([]) == {"items": [], "count": 0, "money_at_risk": 0, "high_priority": 0}
