from flask import abort
from persistence.database import has_table
from saas_core import resolve_context
from copilot.features import ROLES, FEATURES
from copilot.errors import Unavailable, CopilotError


def enabled(c):
    if not has_table(c, "copilot_schema_state"):
        return False
    row = c.execute("SELECT enabled FROM copilot_schema_state WHERE version='0004_copilot'").fetchone()
    return bool(row and row[0])


def authorize(c, feature=None):
    actor = resolve_context(c, "read", product=False)
    if not enabled(c):
        raise Unavailable()
    if feature is not None:
        if feature not in FEATURES:
            raise CopilotError()
        if actor.role not in ROLES[feature]:
            abort(403)
    return actor
