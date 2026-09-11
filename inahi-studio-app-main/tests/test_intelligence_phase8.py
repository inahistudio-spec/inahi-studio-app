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
        "owner_user_id": 7,
        "owner_name": "Marta Comercial",
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
    assert result.why_now


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
    assert result.attention_age_days == 1


def test_owner_and_why_now_are_exposed_for_accountability():
    result = assess_opportunity(opportunity(), now=NOW)
    assert result is not None
    assert result.owner_user_id == 7
    assert result.owner_name == "Marta Comercial"
    assert "seguimiento vencido" in result.why_now.lower()


def test_unowned_risks_are_counted_without_changing_risk_score():
    assigned = opportunity(id=1)
    unowned = opportunity(id=2, owner_user_id=None, owner_name=None)
    result = build_today([assigned, unowned], now=NOW)
    assert result["unowned_risks"] == 1
    assert result["priorities"][0]["risk_score"] == result["priorities"][1]["risk_score"]


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
    assert result["priorities"][0]["owner_name"] == "Marta Comercial"


def test_today_never_includes_closed_business():
    result = build_today([opportunity(stage="lost")], now=NOW)
    assert result["total_open"] == 0
    assert result["priorities"] == []
