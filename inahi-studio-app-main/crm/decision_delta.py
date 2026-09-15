"""Phase 8: explainable changes between commercial decision snapshots."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Mapping


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def compare_snapshot(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> dict[str, Any]:
    """Describe what materially changed for one opportunity since last review."""
    opportunity_id = int(current["opportunity_id"])
    if previous is None:
        return {
            "opportunity_id": opportunity_id,
            "status": "new",
            "risk_delta": int(current.get("risk_score") or 0),
            "money_at_risk_delta": float(_money(current.get("money_at_risk"))),
            "priority_delta": int(current.get("decision_priority") or 0),
            "material_change": True,
            "reason": "Nueva oportunidad incorporada a la revisión ejecutiva",
        }

    risk_delta = int(current.get("risk_score") or 0) - int(previous.get("risk_score") or 0)
    money_delta = _money(current.get("money_at_risk")) - _money(previous.get("money_at_risk"))
    priority_delta = int(current.get("decision_priority") or 0) - int(previous.get("decision_priority") or 0)
    previous_level = str(previous.get("risk_level") or "")
    current_level = str(current.get("risk_level") or "")
    material = abs(risk_delta) >= 10 or abs(money_delta) >= Decimal("250") or previous_level != current_level

    if risk_delta >= 10 or money_delta >= Decimal("250"):
        status = "worsened"
        reason = "Ha aumentado de forma material el riesgo comercial o económico"
    elif risk_delta <= -10 or money_delta <= Decimal("-250"):
        status = "improved"
        reason = "Ha disminuido de forma material el riesgo comercial o económico"
    elif previous_level != current_level:
        status = "changed"
        reason = "Ha cambiado el nivel de riesgo desde la última revisión"
    else:
        status = "stable"
        reason = "Sin cambios materiales desde la última revisión"

    return {
        "opportunity_id": opportunity_id,
        "status": status,
        "risk_delta": risk_delta,
        "money_at_risk_delta": float(money_delta),
        "priority_delta": priority_delta,
        "material_change": material,
        "reason": reason,
    }


def build_decision_delta(previous_rows: Iterable[Mapping[str, Any]], current_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    previous_by_id = {int(row["opportunity_id"]): row for row in previous_rows}
    changes = [compare_snapshot(previous_by_id.get(int(row["opportunity_id"])), row) for row in current_rows]
    material = [item for item in changes if item["material_change"]]
    material.sort(key=lambda item: (abs(item["money_at_risk_delta"]), abs(item["risk_delta"])), reverse=True)
    new_money_at_risk = sum(max(0.0, item["money_at_risk_delta"]) for item in changes)
    reduced_money_at_risk = sum(abs(min(0.0, item["money_at_risk_delta"])) for item in changes)
    return {
        "material_changes": material,
        "material_change_count": len(material),
        "new_money_at_risk": round(new_money_at_risk, 2),
        "reduced_money_at_risk": round(reduced_money_at_risk, 2),
        "methodology": "Comparación determinista entre revisiones; los umbrales son explícitos y auditables.",
    }
