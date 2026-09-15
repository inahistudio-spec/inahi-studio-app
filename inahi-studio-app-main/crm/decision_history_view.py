"""Read-model helpers for the auditable Decision History UI."""


def history_summary(rows, limit=8):
    """Turn tenant-scoped persisted snapshots into a compact UI timeline."""
    items = []
    for row in list(rows or [])[: max(1, min(int(limit), 50))]:
        item = dict(row)
        item["money_at_risk"] = float(item.get("money_at_risk") or 0)
        item["risk_score"] = int(item.get("risk_score") or 0)
        item["decision_priority"] = int(item.get("decision_priority") or 0)
        item["attention_age_days"] = int(item.get("attention_age_days") or 0)
        captured = item.get("captured_at")
        item["captured_label"] = captured.strftime("%d/%m/%Y %H:%M") if hasattr(captured, "strftime") else str(captured or "")[:16].replace("T", " ")
        items.append(item)
    return {
        "items": items,
        "count": len(items),
        "money_at_risk": round(sum(item["money_at_risk"] for item in items), 2),
        "high_priority": sum(1 for item in items if item["decision_priority"] >= 70),
    }
