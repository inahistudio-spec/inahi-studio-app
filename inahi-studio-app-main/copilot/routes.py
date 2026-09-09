"""Session-scoped form endpoints. No browser-selected organization or tools."""
from contextlib import closing
import sqlite3
import uuid
from flask import Blueprint, abort, g, render_template, request
from werkzeug.exceptions import HTTPException
from billing.entitlements import LimitExceeded
from copilot import service, usage, audit
from copilot.permissions import authorize
from copilot.features import FEATURES, ROLES
from copilot.errors import CopilotError


def install(app, connect):
    bp = Blueprint("copilot", __name__)

    def parameters(allowed=()):
        if request.args or request.is_json or set(request.form) - {"csrf_token", *allowed}:
            abort(400)
        if any(len(request.form.getlist(key)) != 1 for key in request.form):
            abort(400)

    def suggestions(actor):
        return [{"feature": key, "label": value[0], "question": value[1]}
                for key, value in FEATURES.items() if actor.role in ROLES[key]]

    @bp.errorhandler(CopilotError)
    def invalid(error):
        return {"error": error.message, "code": error.code}, error.status

    @bp.errorhandler(LimitExceeded)
    def quota(_error):
        return {"error": "La suscripción o su cuota no permite esta consulta.", "code": "quota"}, 429

    @bp.errorhandler(sqlite3.Error)
    def unavailable(_error):
        return {"error": "Copilot no disponible. No repitas una consulta cuyo estado sea incierto.", "code": "unavailable"}, 503

    @bp.errorhandler(HTTPException)
    def rejected(error):
        return {"error": "Solicitud no autorizada o no válida.", "code": "rejected"}, error.code

    @app.after_request
    def audit_denials(response):
        if (request.endpoint or "").startswith("copilot.") and response.status_code >= 400 and not getattr(g, "copilot_audited", False):
            try:
                audit.denied(connect, "quota" if response.status_code == 429 else "denied")
            except sqlite3.Error:
                # Do not expose DB/provider details or turn an error into a successful call.
                app.logger.error("Copilot: no se pudo registrar el acceso denegado")
        if (request.endpoint or "").startswith("copilot."):
            response.headers["Cache-Control"] = "no-store"
        return response

    @bp.get("/saas/copilot")
    def page():
        parameters()
        with closing(connect()) as c:
            actor = authorize(c)
            return render_template("copilot.html", suggestions=suggestions(actor), usage=usage.summary(c, actor), request_key=str(uuid.uuid4()))

    @bp.get("/saas/copilot/suggestions")
    def suggested():
        parameters()
        with closing(connect()) as c:
            return {"suggestions": suggestions(authorize(c))}

    @bp.get("/saas/copilot/usage")
    def totals():
        parameters()
        with closing(connect()) as c:
            return usage.summary(c, authorize(c))

    @bp.post("/saas/copilot/ask")
    def ask():
        parameters(("feature", "question", "request_key", "resource_kind", "resource_id"))
        kind, rid = request.form.get("resource_kind") or None, request.form.get("resource_id") or None
        if rid is not None:
            if not rid.isascii() or not rid.isdecimal() or len(rid) > 18:
                abort(400)
            rid = int(rid)
        return service.ask(connect, request.form.get("feature"), request.form.get("question"), request.form.get("request_key"), kind, rid)

    app.register_blueprint(bp)
