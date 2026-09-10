from datetime import datetime, timedelta, timezone
from decimal import Decimal

from crm.intelligence import assess_opportunity, build_today


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def opportunity(**overrides):
    row = {
        "id": 1,
        "contact_id": 10,
        "company_name": "Empresa Norte",
        "contact_name": "Ana",
        "title": "Renovación anual",
        "stage": "proposal",
        "estimated_value": Decimal("10000.00"),
        "probability": 80,
        "updated_at": NOW - timedelta(days=10),
        "last_contact_at": NOW - timedelta(days=10),
        "last_activity_at": NOW - timedelta(days=10),
        "next_followup_at": NOW - timedelta(days=2),
        "expected_close_date": (NOW - timedelta(days=1)).date(),
    }
    row.update(overrides)
    return row


def test_closed_opportunity_is_not_scored():
    assert assess_opportunity(opportunity(stage="won"), now=NOW) is None


def test_risk_is_explainable_and_bounded():
    result = assess_opportunity(opportunity(), now=NOW)
    assert result is not None
    assert 0 <= result.risk_score <= 100
    codes = {item.code for item in result.evidence}
    assert "followup_overdue" in codes
    assert "proposal_silent" in codes
    assert "close_date_overdue" in codes
    assert result.recommended_action


def test_money_at_risk_is_not_the_full_pipeline_value():
    result = assess_opportunity(opportunity(), now=NOW)
    assert result is not None
    assert Decimal("0") <= result.money_at_risk <= result.estimated_value


def test_low_risk_opportunity_remains_low():
    result = assess_opportunity(opportunity(
        stage="qualified",
        probability=40,
        last_activity_at=NOW - timedelta(days=1),
        last_contact_at=NOW - timedelta(days=1),
        next_followup_at=NOW + timedelta(days=2),
        expected_close_date=(NOW + timedelta(days=20)).date(),
    ), now=NOW)
    assert result is not None
    assert result.risk_level == "low"
    assert result.risk_score == 0
    assert result.money_at_risk == Decimal("0.00")


def test_today_prioritizes_exposure_and_returns_summary():
    high = opportunity(id=1, estimated_value=Decimal("25000"))
    medium = opportunity(
        id=2,
        company_name="Empresa Sur",
        stage="qualified",
        estimated_value=Decimal("5000"),
        probability=50,
        last_activity_at=NOW - timedelta(days=16),
        last_contact_at=NOW - timedelta(days=16),
        next_followup_at=NOW + timedelta(days=2),
        expected_close_date=(NOW + timedelta(days=30)).date(),
    )
    result = build_today([medium, high], now=NOW)
    assert result["total_open"] == 2
    assert result["pipeline_value"] == 30000.0
    assert result["money_at_risk"] >= 0
    assert result["priorities"][0]["opportunity_id"] == 1
    assert result["priorities"][0]["evidence"]


def test_today_never_includes_closed_business():
    result = build_today([opportunity(stage="lost")], now=NOW)
    assert result["total_open"] == 0
    assert result["priorities"] == []
