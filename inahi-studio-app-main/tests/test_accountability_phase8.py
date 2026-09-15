from crm.accountability import evaluate_accountability, build_accountability_queue


def item(**overrides):
    row = {
        "opportunity_id": 1,
        "company_name": "Empresa Norte",
        "owner_user_id": 7,
        "owner_name": "Marta Comercial",
        "decision_priority": 65,
        "risk_score": 50,
        "attention_age_days": 8,
        "attended": False,
    }
    row.update(overrides)
    return row


def test_unowned_risk_is_escalated():
    result = evaluate_accountability(item(owner_user_id=None, owner_name=None))
    assert result.status == "unowned"
    assert result.escalation_level == "critical"
    assert result.owner_name == "Sin responsable asignado"


def test_old_high_risk_decision_becomes_critical_overdue():
    result = evaluate_accountability(item(attention_age_days=16))
    assert result.status == "overdue"
    assert result.escalation_level == "critical"
    assert "16 días" in result.reason


def test_attended_decision_does_not_remain_escalated():
    result = evaluate_accountability(item(attended=True, attention_age_days=30, risk_score=90))
    assert result.status == "attended"
    assert result.escalation_level == "none"


def test_queue_prioritizes_accountability_and_reports_gaps():
    queue = build_accountability_queue([
        item(opportunity_id=1, attended=True),
        item(opportunity_id=2, owner_user_id=None, owner_name=None),
        item(opportunity_id=3, attention_age_days=20),
    ])
    assert queue["total"] == 3
    assert queue["pending"] == 2
    assert queue["unowned"] == 1
    assert queue["overdue"] == 1
    assert queue["critical"] == 2
    assert queue["queue"][0]["opportunity_id"] in {2, 3}
    assert "auditable" in queue["methodology"]
