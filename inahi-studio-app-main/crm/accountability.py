"""Phase 8 accountability intelligence.

Turns explainable commercial risk into an auditable ownership queue: who owns
it, how long it has needed attention, and which decisions are still unattended.
No external AI is used for accountability status or escalation.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class AccountabilityItem:
    opportunity_id: int
    company_name: str
    owner_user_id: int | None
    owner_name: str
    decision_priority: int
    risk_score: int
    attention_age_days: int
    attended: bool
    status: str
    escalation_level: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_accountability(row: Mapping[str, Any]) -> AccountabilityItem:
    owner_id = row.get("owner_user_id")
    owner_name = str(row.get("owner_name") or "Sin responsable asignado")
    risk = max(0, min(100, int(row.get("risk_score") or 0)))
    priority = max(0, min(100, int(row.get("decision_priority") or risk)))
    age = max(0, int(row.get("attention_age_days") or 0))
    attended = bool(row.get("attended", False))

    if attended:
        status = "attended"
        escalation = "none"
        reason = "La decisión consta como atendida"
    elif owner_id is None:
        status = "unowned"
        escalation = "critical" if risk >= 45 or priority >= 60 else "high"
        reason = "Existe riesgo comercial sin una persona responsable asignada"
    elif age >= 14 and (risk >= 45 or priority >= 60):
        status = "overdue"
        escalation = "critical"
        reason = f"La decisión lleva {age} días requiriendo atención"
    elif age >= 7 or risk >= 45 or priority >= 60:
        status = "pending"
        escalation = "high"
        reason = f"{owner_name} tiene una decisión comercial pendiente de atención"
    else:
        status = "pending"
        escalation = "normal"
        reason = f"{owner_name} mantiene el seguimiento de esta oportunidad"

    return AccountabilityItem(
        opportunity_id=int(row["opportunity_id"]),
        company_name=str(row.get("company_name") or "Sin nombre"),
        owner_user_id=int(owner_id) if owner_id is not None else None,
        owner_name=owner_name,
        decision_priority=priority,
        risk_score=risk,
        attention_age_days=age,
        attended=attended,
        status=status,
        escalation_level=escalation,
        reason=reason,
    )


def build_accountability_queue(rows: Iterable[Mapping[str, Any]], *, limit: int = 20) -> dict[str, Any]:
    items = [evaluate_accountability(row) for row in rows]
    rank = {"critical": 3, "high": 2, "normal": 1, "none": 0}
    items.sort(
        key=lambda item: (
            rank[item.escalation_level],
            item.decision_priority,
            item.risk_score,
            item.attention_age_days,
        ),
        reverse=True,
    )
    pending = [item for item in items if not item.attended]
    return {
        "total": len(items),
        "pending": len(pending),
        "unowned": sum(item.status == "unowned" for item in items),
        "overdue": sum(item.status == "overdue" for item in items),
        "critical": sum(item.escalation_level == "critical" for item in items),
        "queue": [item.to_dict() for item in items[: max(1, min(limit, 100))]],
        "methodology": "Priorización determinista por responsabilidad, antigüedad, riesgo e impacto; auditable y sin IA opaca.",
    }
