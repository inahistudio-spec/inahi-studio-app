"""Central states, roles, validation and server-resolved identity."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlsplit
from flask import abort
from persistence.database import has_table
from saas_core import resolve_context

STATUSES = ("lead", "prospect", "customer", "inactive")
STAGES = ("new", "contacted", "qualified", "proposal", "negotiation", "won", "lost")
OPEN_STAGES = STAGES[:-2]
ACTIVITY_TYPES = ("call", "email", "meeting", "note", "followup")
EDIT_ROLES = ("owner", "admin", "manager")
LABELS = {"lead": "Lead", "prospect": "Prospecto", "customer": "Cliente", "inactive": "Inactivo", "new": "Nueva", "contacted": "Contactada", "qualified": "Cualificada", "proposal": "Propuesta", "negotiation": "Negociación", "won": "Ganada", "lost": "Perdida", "call": "Llamada", "email": "Email", "meeting": "Reunión", "note": "Nota", "followup": "Seguimiento"}


def enabled(c):
    if not has_table(c, "crm_schema_state"):
        return False
    row = c.execute("SELECT enabled FROM crm_schema_state WHERE version='0005_crm'").fetchone()
    return bool(row and row[0])


def authorize(c, action="read"):
    actor = resolve_context(c)
    if not enabled(c):
        abort(404)
    if action == "edit" and actor.role not in EDIT_ROLES:
        abort(403)
    if action == "delete" and actor.role not in ("owner", "admin"):
        abort(403)
    return actor


def integer(value, optional=False):
    if optional and value in (None, ""):
        return None
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]{0,17}", str(value)):
        raise ValueError("ID inválido")
    return int(value)


def text(value, maximum, required=False):
    if not isinstance(value, str):
        raise ValueError("Texto inválido")
    value = value.strip()
    if len(value) > maximum or (required and not value) or any(ord(ch) < 32 and ch not in "\n\t" for ch in value):
        raise ValueError("Texto inválido")
    return value


def stamp(value, date_only=False):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Fecha inválida")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Fecha inválida") from None
    parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    return parsed.date().isoformat() if date_only else parsed.isoformat()


def choice(value, allowed):
    if value not in allowed:
        raise ValueError("Estado no permitido")
    return value


def contact_fields(values):
    result = {key: text(values.get(key, ""), maximum) for key, maximum in (("company_name", 160), ("contact_name", 160), ("email", 254), ("phone", 40), ("website", 500), ("source", 100), ("notes", 6000))}
    if not result["company_name"] and not result["contact_name"]:
        raise ValueError("Indica una empresa o un nombre")
    if result["email"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", result["email"]):
        raise ValueError("Email inválido")
    if result["website"]:
        url = urlsplit(result["website"])
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise ValueError("Web inválida")
    result.update(status=choice(values.get("status", "lead"), STATUSES), owner_user_id=integer(values.get("owner_user_id"), True),
                  last_contact_at=stamp(values.get("last_contact_at")), next_followup_at=stamp(values.get("next_followup_at")))
    if result["last_contact_at"] and result["last_contact_at"] > datetime.now(timezone.utc).isoformat():
        raise ValueError("El último contacto no puede estar en el futuro")
    return result


def opportunity_fields(values):
    try:
        amount = Decimal(str(values.get("estimated_value") or "0"))
        probability = int(str(values.get("probability") or "0"))
        if not amount.is_finite() or amount < 0 or amount > Decimal("9999999999.99") or amount.as_tuple().exponent < -2 or not 0 <= probability <= 100:
            raise ValueError()
    except (ValueError, InvalidOperation):
        raise ValueError("Valor o probabilidad inválidos") from None
    stage = choice(values.get("stage", "new"), STAGES)
    return {"title": text(values.get("title", ""), 180, True), "stage": stage, "estimated_value": str(amount),
            "probability": 100 if stage == "won" else 0 if stage == "lost" else probability,
            "expected_close_date": stamp(values.get("expected_close_date"), True), "owner_user_id": integer(values.get("owner_user_id"), True)}
