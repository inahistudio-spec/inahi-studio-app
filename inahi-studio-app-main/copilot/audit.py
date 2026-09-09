"""Audit codes only; never log question, context, output, provider error or requested IDs."""
from contextlib import closing
from flask import session
from copilot.permissions import enabled
from saas_schema import audit

CODES = frozenset(("reserved", "succeeded", "denied", "quota", "provider_error", "invalid_output", "denied_after_call"))


def record(c, code, actor=None):
    if code not in CODES:
        raise ValueError("Unknown audit code")
    audit(c, "copilot_" + code, actor.organization_id if actor else None, actor.user_id if actor else None)


def denied(connect, code="denied"):
    with closing(connect()) as c, c:
        if not enabled(c):
            return
        # A manipulated or revoked session must never attribute an audit to another tenant.
        row = c.execute("""SELECT m.organization_id,m.user_id FROM organization_memberships m
            JOIN users u ON u.id=m.user_id WHERE m.organization_id=? AND m.user_id=? AND m.status='active'
            AND u.status='active' AND u.credential_version=?""", (session.get("organization_id"), session.get("user_id"), session.get("credential_version"))).fetchone()
        audit(c, "copilot_" + code, row[0] if row else None, row[1] if row else None)
