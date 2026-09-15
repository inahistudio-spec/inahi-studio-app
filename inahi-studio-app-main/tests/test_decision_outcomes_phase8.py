from crm.decision_outcomes import evaluate_outcome, summarize_outcomes


def outcome(**overrides):
    row = {
        "recommendation_id": "rec-1",
        "opportunity_id": 10,
        "action_taken": True,
        "previous_risk_score": 70,
        "current_risk_score": 45,
        "previous_probability": 50,
        "current_probability": 65,
        "previous_value": 10000,
        "current_value": 10000,
    }
    row.update(overrides)
    return row


def test_executed_recommendation_can_be_marked_improved():
    result = evaluate_outcome(outcome())
    assert result.outcome == "improved"
    assert result.effectiveness_score > 50
    assert result.action_taken is True


def test_non_executed_action_never_claims_improvement():
    result = evaluate_outcome(outcome(action_taken=False))
    assert result.outcome == "not_executed"
    assert result.effectiveness_score <= 50


def test_worsening_is_detected_and_explained():
    result = evaluate_outcome(outcome(current_risk_score=90, current_probability=35))
    assert result.outcome == "worsened"
    assert result.effectiveness_score < 50
    assert result.explanation


def test_summary_reports_observed_effectiveness_without_claiming_causality():
    summary = summarize_outcomes([
        outcome(opportunity_id=1),
        outcome(opportunity_id=2, current_risk_score=68, current_probability=52),
        outcome(opportunity_id=3, action_taken=False),
    ])
    assert summary["total"] == 3
    assert summary["executed"] == 2
    assert summary["improved"] == 1
    assert summary["improvement_rate"] == 50.0
    assert "no implica causalidad" in summary["methodology"]
