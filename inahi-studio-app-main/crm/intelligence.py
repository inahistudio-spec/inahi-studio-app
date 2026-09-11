"""Phase 8: explainable CRM intelligence for INAHI Today and Money at Risk.

Deterministic and auditable by design. External AI may later explain or draft actions,
but commercial scores and monetary estimates remain traceable.
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
    recoverable_value: Decimal
    decision_priority: int
    recommended_action: str
    evidence: tuple[Signal, ...]
    owner_user_id: int | None = None
    owner_name: str = "Sin responsable asignado"
    why_now: str = "Revisar la oportunidad para mantener el pipeline actualizado"
    attention_age_days: int = 0

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("estimated_value", "money_at_risk", "recoverable_value"):
            value[key] = float(getattr(self, key))
        return value

def _parse_datetime(value: Any) -> datetime | None:
    if not value: return None
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)

def _days_since(value: Any, now: datetime) -> int | None:
    stamp = _parse_datetime(value)
    return None if stamp is None else max(0, (now - stamp).days)

def _risk_level(score: int) -> str:
    if score >= 70: return "critical"
    if score >= 45: return "high"
    if score >= 20: return "medium"
    return "low"

def _recommended_action(signals: list[Signal], stage: str) -> str:
    codes = {s.code for s in signals}
    if "followup_overdue" in codes: return "Contactar hoy y cerrar una próxima acción con fecha"
    if "proposal_silent" in codes: return "Hacer seguimiento de la propuesta y registrar la respuesta"
    if "no_next_step" in codes: return "Asignar una próxima acción concreta antes de terminar el día"
    if stage in {"qualified", "proposal", "negotiation"}: return "Revisar la oportunidad y confirmar el siguiente paso comercial"
    return "Revisar la oportunidad y actualizar su estado"

def _why_now(signals: list[Signal], money_at_risk: Decimal) -> str:
    codes = {s.code for s in signals}
    if "followup_overdue" in codes and "proposal_silent" in codes:
        return "Hay un seguimiento vencido y una propuesta sin respuesta; esperar aumenta el riesgo comercial"
    if "followup_overdue" in codes:
        return "El siguiente contacto comprometido ya está vencido"
    if "close_date_overdue" in codes:
        return "La fecha prevista de cierre ya pasó y necesita una decisión comercial"
    if "proposal_silent" in codes:
        return "La propuesta lleva demasiado tiempo sin contacto registrado"
    if money_at_risk >= Decimal("1000"):
        return "La exposición económica justifica revisarla antes que oportunidades de menor impacto"
    if signals:
        return signals[0].reason
    return "No hay urgencia relevante detectada; mantener el seguimiento previsto"

def assess_opportunity(row: Mapping[str, Any], *, now: datetime | None = None) -> RiskAssessment | None:
    stage = str(row.get("stage") or "")
    if stage not in OPEN_STAGES: return None
    now = now or datetime.now(timezone.utc)
    signals: list[Signal] = []
    days_activity = _days_since(row.get("last_activity_at") or row.get("last_contact_at") or row.get("updated_at"), now)
    days_contact = _days_since(row.get("last_contact_at"), now)
    next_followup = _parse_datetime(row.get("next_followup_at"))
    if days_activity is not None and days_activity >= 30: signals.append(Signal("stale_30d",35,f"Lleva {days_activity} días sin actividad registrada"))
    elif days_activity is not None and days_activity >= 14: signals.append(Signal("stale_14d",24,f"Lleva {days_activity} días sin actividad registrada"))
    elif days_activity is not None and days_activity >= 7: signals.append(Signal("stale_7d",12,f"Lleva {days_activity} días sin actividad registrada"))
    if next_followup and next_followup < now: signals.append(Signal("followup_overdue",28,"El seguimiento programado está vencido"))
    elif not next_followup: signals.append(Signal("no_next_step",14,"No hay una próxima acción comercial programada"))
    if stage in {"proposal","negotiation"} and days_contact is not None and days_contact >= 7:
        signals.append(Signal("proposal_silent",24,f"La oportunidad está en {stage} y lleva {days_contact} días sin contacto"))
    close_date = row.get("expected_close_date")
    if close_date:
        try:
            close_day = datetime.fromisoformat(close_date.isoformat() if hasattr(close_date,"isoformat") else str(close_date)).date()
            if close_day < now.date(): signals.append(Signal("close_date_overdue",22,"La fecha prevista de cierre ya ha vencido"))
        except ValueError: pass
    probability = max(0,min(100,int(row.get("probability") or 0)))
    if probability >= 70 and days_activity is not None and days_activity >= 7:
        signals.append(Signal("high_value_attention",10,"Es una oportunidad con probabilidad alta que está perdiendo ritmo"))
    score = min(100,sum(s.points for s in signals))
    value = Decimal(str(row.get("estimated_value") or 0))
    exposure = Decimal(score)/Decimal(100)
    weighted_probability = Decimal(probability)/Decimal(100)
    money_at_risk = (value*exposure*weighted_probability).quantize(Decimal("0.01"))
    recovery_factor = max(Decimal("0.20"), Decimal("0.70")-(Decimal(score)/Decimal(200))) if score else Decimal("0")
    recoverable = (money_at_risk*recovery_factor).quantize(Decimal("0.01"))
    economic_boost = min(30, int(money_at_risk/Decimal("250"))) if money_at_risk > 0 else 0
    decision_priority = min(100, score + economic_boost)
    owner_id = row.get("owner_user_id")
    owner_name = str(row.get("owner_name") or "Sin responsable asignado")
    return RiskAssessment(int(row["id"]),int(row["contact_id"]),str(row.get("company_name") or row.get("contact_name") or "Sin nombre"),str(row.get("title") or "Oportunidad"),value,probability,score,_risk_level(score),money_at_risk,recoverable,decision_priority,_recommended_action(signals,stage),tuple(signals),int(owner_id) if owner_id is not None else None,owner_name,_why_now(signals,money_at_risk),days_activity or 0)

def build_today(rows: Iterable[Mapping[str, Any]], *, now: datetime | None = None, limit: int = 10) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    assessments = [item for row in rows if (item := assess_opportunity(row,now=now)) is not None]
    assessments.sort(key=lambda x:(x.decision_priority,x.money_at_risk,x.risk_score),reverse=True)
    total_at_risk = sum((x.money_at_risk for x in assessments),Decimal("0.00"))
    total_recoverable = sum((x.recoverable_value for x in assessments),Decimal("0.00"))
    total_pipeline = sum((x.estimated_value for x in assessments),Decimal("0.00"))
    unowned = sum(x.owner_user_id is None for x in assessments if x.risk_score > 0)
    return {"total_open":len(assessments),"critical":sum(x.risk_level=="critical" for x in assessments),"high":sum(x.risk_level=="high" for x in assessments),"unowned_risks":unowned,"money_at_risk":float(total_at_risk.quantize(Decimal("0.01"))),"recoverable_value":float(total_recoverable.quantize(Decimal("0.01"))),"pipeline_value":float(total_pipeline.quantize(Decimal("0.01"))),"priorities":[x.to_dict() for x in assessments[:max(1,min(limit,50))]]}
