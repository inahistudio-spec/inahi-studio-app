from crm.decision_delta import build_decision_delta, compare_snapshot


def snap(opportunity_id=1, risk_score=30, money_at_risk=300, decision_priority=40, risk_level="medium"):
    return {
        "opportunity_id": opportunity_id,
        "risk_score": risk_score,
        "money_at_risk": money_at_risk,
        "decision_priority": decision_priority,
        "risk_level": risk_level,
    }


def test_detects_material_worsening_since_last_review():
    result = compare_snapshot(snap(), snap(risk_score=55, money_at_risk=700, decision_priority=70, risk_level="high"))
    assert result["status"] == "worsened"
    assert result["risk_delta"] == 25
    assert result["money_at_risk_delta"] == 400.0
    assert result["material_change"] is True


def test_stable_change_does_not_distract_executive_feed():
    result = compare_snapshot(snap(), snap(risk_score=34, money_at_risk=320, decision_priority=42))
    assert result["status"] == "stable"
    assert result["material_change"] is False


def test_new_opportunity_is_visible_in_delta():
    result = compare_snapshot(None, snap(opportunity_id=8, risk_score=20, money_at_risk=150))
    assert result["status"] == "new"
    assert result["opportunity_id"] == 8
    assert result["material_change"] is True


def test_executive_delta_prioritizes_economic_change_and_totals_risk_movement():
    previous = [snap(1), snap(2, money_at_risk=900)]
    current = [
        snap(1, risk_score=50, money_at_risk=800, risk_level="high"),
        snap(2, risk_score=15, money_at_risk=500, decision_priority=20, risk_level="low"),
    ]
    result = build_decision_delta(previous, current)
    assert result["material_change_count"] == 2
    assert result["new_money_at_risk"] == 500.0
    assert result["reduced_money_at_risk"] == 400.0
    assert result["material_changes"][0]["opportunity_id"] == 1
    assert "auditables" in result["methodology"]
