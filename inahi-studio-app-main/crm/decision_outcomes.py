"""Phase 8: auditable feedback for commercial decisions.

This module records/evaluates outcomes without letting an opaque model rewrite
risk scores. It is deliberately deterministic so every result can be audited.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class DecisionOutcome:
    recommendation_id: str
    opportunity_id: int
    action_taken: bool
    previous_risk_score: int
    current_risk_score: int
    previous_probability: int
    current_probability: int
    previous_value: Decimal
    current_value: Decimal
    outcome: str
    effectiveness_score: int
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["previous_value"] = float(self.previous_value)
        data["current_value"] = float(self.current_value)
        return data


def evaluate_outcome(row: Mapping[str, Any]) -> DecisionOutcome:
    """Evaluate whether a recommended action was followed by improvement.

    This is correlation for decision support, not a claim of causation.
    """
    previous_risk = max(0, min(100, int(row.get("previous_risk_score") or 0)))
    current_risk = max(0, min(100, int(row.get("current_risk_score") or 0)))
    previous_probability = max(0, min(100, int(row.get("previous_probability") or 0)))
    current_probability = max(0, min(100, int(row.get("current_probability") or 0)))
    previous_value = Decimal(str(row.get("previous_value") or 0))
    current_value = Decimal(str(row.get("current_value") or 0))
    action_taken = bool(row.get("action_taken"))

    risk_gain = previous_risk - current_risk
    probability_gain = current_probability - previous_probability
    value_gain = current_value - previous_value

    score = 50
    score += max(-30, min(30, risk_gain))
    score += max(-15, min(15, probability_gain))
    if value_gain > 0:
        score += 5
    elif value_gain < 0:
        score -= 5
    if not action_taken:
        score = min(score, 50)
    score = max(0, min(100, score))

    if not action_taken:
        outcome = "not_executed"
        explanation = "La recomendación no consta como ejecutada; no se atribuye mejora a la acción"
    elif risk_gain >= 10 or probability_gain >= 10:
        outcome = "improved"
        explanation = "Tras ejecutar la acción, mejoraron indicadores comerciales observables"
    elif risk_gain <= -10 or probability_gain <= -10:
        outcome = "worsened"
        explanation = "Tras ejecutar la acción, empeoraron indicadores comerciales observables"
    else:
        outcome = "stable"
        explanation = "Tras ejecutar la acción, los indicadores permanecen esencialmente estables"

    return DecisionOutcome(
        recommendation_id=str(row.get("recommendation_id") or ""),
        opportunity_id=int(row["opportunity_id"]),
        action_taken=action_taken,
        previous_risk_score=previous_risk,
        current_risk_score=current_risk,
        previous_probability=previous_probability,
        current_probability=current_probability,
        previous_value=previous_value,
        current_value=current_value,
        outcome=outcome,
        effectiveness_score=score,
        explanation=explanation,
    )


def summarize_outcomes(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    outcomes = [evaluate_outcome(row) for row in rows]
    executed = [item for item in outcomes if item.action_taken]
    improved = [item for item in executed if item.outcome == "improved"]
    average = round(sum(item.effectiveness_score for item in executed) / len(executed), 1) if executed else 0.0
    return {
        "total": len(outcomes),
        "executed": len(executed),
        "improved": len(improved),
        "improvement_rate": round((len(improved) / len(executed)) * 100, 1) if executed else 0.0,
        "average_effectiveness": average,
        "outcomes": [item.to_dict() for item in outcomes],
        "methodology": "Indicadores observados después de la acción; no implica causalidad.",
    }
