"""Phase 8: explainable CRM intelligence for INAHI Today and Money at Risk.

This module is deliberately deterministic and auditable. It does not call external AI.
AI can later summarize these signals, but the underlying risk score and evidence stay
traceable for enterprise users.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Mapping, Any

OPEN_STAGES = {"new", "contacted", "qualified", "proposal", "negotiation"}


@dataclass(frozen=True)
class Signal:
    code: str
    points: int
    reason: str


@dataclass(frozen=True)
class RiskAssessment:
    opportunity_id: int
    contact_id: int
    company_name: str
    title: str
    estimated_value: Decimal
    probability: int
    risk_score: int
    risk_level: str
    money_at_risk: Decimal
    recommended_action: str
    evidence: tuple[Signal, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["estimated_value"] = float(self.estimated_value)
        value["money_at_risk"] = float(self.money_at_risk)
        return value


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _days_since(value: Any, now: datetime) -> int | None:
    stamp = _parse_datetime(value)
    if stamp is None:
        return None
    return max(0, (now - stamp).days)


def _risk_level(score: int) -> str:
    if score >= 70:
        return "critical"
    if score >= 45:
        return "high"
    if score >= 20:
        return "medium"
    return "low"


def _recommended_action(signals: list[Signal], stage: str) -> str:
    codes = {signal.code for signal in signals}
    if "followup_overdue" in codes:
        return "Contactar hoy y cerrar una próxima acción con fecha"
    if "proposal_silent" in codes:
        return "Hacer seguimiento de la propuesta y registrar la respuesta"
    if "no_next_step" in codes:
        return "Asignar una próxima acción concreta antes de terminar el día"
    if stage in {"qualified", "proposal", "negotiation"}:
        return "Revisar la oportunidad y confirmar el siguiente paso comercial"
    return "Revisar la oportunidad y actualizar su estado"


def assess_opportunity(row: Mapping[str, Any], *, now: datetime | None = None) -> RiskAssessment | None:
    """Return an explainable risk assessment for one open opportunity.

    Expected fields are already present in INAHI's CRM queries or can be derived by
    a tenant-scoped SQL query: id, contact_id, company_name/contact_name, title,
    stage, estimated_value, probability, updated_at, expected_close_date,
    last_contact_at, last_activity_at and next_followup_at.
    """
    stage = str(row.get("stage") or "")
    if stage not in OPEN_STAGES:
        return None

    now = now or datetime.now(timezone.utc)
    signals: list[Signal] = []
    days_activity = _days_since(row.get("last_activity_at") or row.get("last_contact_at") or row.get("updated_at"), now)
    days_contact = _days_since(row.get("last_contact_at"), now)
    next_followup = _parse_datetime(row.get("next_followup_at"))

    if days_activity is not None and days_activity >= 30:
        signals.append(Signal("stale_30d", 35, f"Lleva {days_activity} días sin actividad registrada"))
    elif days_activity is not None and days_activity >= 14:
        signals.append(Signal("stale_14d", 24, f"Lleva {days_activity} días sin actividad registrada"))
    elif days_activity is not None and days_activity >= 7:
        signals.append(Signal("stale_7d", 12, f"Lleva {days_activity} días sin actividad registrada"))

    if next_followup and next_followup < now:
        signals.append(Signal("followup_overdue", 28, "El seguimiento programado está vencido"))
    elif not next_followup:
        signals.append(Signal("no_next_step", 14, "No hay una próxima acción comercial programada"))

    if stage in {"proposal", "negotiation"} and days_contact is not None and days_contact >= 7:
        signals.append(Signal("proposal_silent", 24, f"La oportunidad está en {stage} y lleva {days_contact} días sin contacto"))

    close_date = row.get("expected_close_date")
    if close_date:
        if hasattr(close_date, "isoformat"):
            close_text = close_date.isoformat()
        else:
            close_text = str(close_date)
        try:
            close_day = datetime.fromisoformat(close_text).date()
            if close_day < now.date():
                signals.append(Signal("close_date_overdue", 22, "La fecha prevista de cierre ya ha vencido"))
        except ValueError:
            pass

    probability = max(0, min(100, int(row.get("probability") or 0)))
    if probability >= 70 and days_activity is not None and days_activity >= 7:
        signals.append(Signal("high_value_attention", 10, "Es una oportunidad con probabilidad alta que está perdiendo ritmo"))

    score = min(100, sum(signal.points for signal in signals))
    value = Decimal(str(row.get("estimated_value") or 0))
    # Money at risk is deliberately conservative: exposure increases with the
    # explainable risk score, while probability reflects commercial relevance.
    exposure = Decimal(score) / Decimal(100)
    weighted_probability = Decimal(probability) / Decimal(100)
    money_at_risk = (value * exposure * weighted_probability).quantize(Decimal("0.01"))

    return RiskAssessment(
        opportunity_id=int(row["id"]),
        contact_id=int(row["contact_id"]),
        company_name=str(row.get("company_name") or row.get("contact_name") or "Sin nombre"),
        title=str(row.get("title") or "Oportunidad"),
        estimated_value=value,
        probability=probability,
        risk_score=score,
        risk_level=_risk_level(score),
        money_at_risk=money_at_risk,
        recommended_action=_recommended_action(signals, stage),
        evidence=tuple(signals),
    )


def build_today(rows: Iterable[Mapping[str, Any]], *, now: datetime | None = None, limit: int = 10) -> dict[str, Any]:
    """Build INAHI Today: prioritized, explainable opportunities for one organization."""
    now = now or datetime.now(timezone.utc)
    assessments = [item for row in rows if (item := assess_opportunity(row, now=now)) is not None]
    assessments.sort(key=lambda item: (item.risk_score, item.money_at_risk, item.estimated_value), reverse=True)
    critical = sum(1 for item in assessments if item.risk_level == "critical")
    high = sum(1 for item in assessments if item.risk_level == "high")
    total_at_risk = sum((item.money_at_risk for item in assessments), Decimal("0.00"))
    total_pipeline = sum((item.estimated_value for item in assessments), Decimal("0.00"))
    return {
        "total_open": len(assessments),
        "critical": critical,
        "high": high,
        "money_at_risk": float(total_at_risk.quantize(Decimal("0.01"))),
        "pipeline_value": float(total_pipeline.quantize(Decimal("0.01"))),
        "priorities": [item.to_dict() for item in assessments[: max(1, min(limit, 50))]],
    }
