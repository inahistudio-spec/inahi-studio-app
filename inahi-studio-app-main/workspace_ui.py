"""Read-only SaaS presentation over the existing tenant and billing services."""
from contextlib import closing
from datetime import datetime
import json
import sqlite3
from flask import Blueprint, abort, render_template, request, session, redirect, url_for, current_app
from werkzeug.exceptions import HTTPException
from saas_core import resolve_context
from billing.entitlements import describe, LimitExceeded

NAV = (
    ("dashboard", "Inicio", "grid"), ("clientes", "Clientes", "users"),
    ("diagnosticos", "Diagnósticos", "pulse"), ("estrategias", "Estrategias", "target"),
    ("contenido", "Contenido", "layers"), ("informes", "Informes", "chart"),
    ("automatizaciones", "Automatizaciones", "bolt"), ("copilot", "INAHI Copilot", "spark"),
    ("equipo", "Equipo", "users"), ("facturacion", "Facturación", "card"),
    ("configuracion", "Configuración", "settings"),
)
COLLECTIONS = {
    "diagnosticos": ("diagnosticos", "Diagnósticos", "Conoce el punto de partida de tu negocio.", ("id", "objetivos", "puntuacion", "web", "google", "redes", "resenas", "actualizado"), "diagnostico"),
    "estrategias": ("estrategias_comerciales", "Estrategias", "Tu dirección comercial, en un solo lugar.", ("id", "respuestas", "estrategia", "actualizado"), "estrategia_comercial"),
    "contenido": ("calendarios_contenido", "Contenido", "Ideas y calendarios que dan continuidad a tu marca.", ("id", "periodo", "contenido", "creado"), "calendario_contenidos"),
    "informes": ("informes", "Informes", "Una visión compartida de los resultados.", ("id", "titulo", "contenido", "fecha"), "informes_cliente"),
    "automatizaciones": ("solicitudes", "Automatizaciones", "Consulta solicitudes, respuestas y su estado real.", ("id", "asunto", "descripcion", "respuesta", "estado", "origen_respuesta", "fecha"), "portal"),
}
ACTIVITY = {"report_created": "Informe creado", "report_updated": "Informe actualizado", "membership_created": "Miembro incorporado", "organization_created": "Organización creada", "copilot_succeeded": "Consulta al Copilot completada", "copilot_provider_error": "Consulta al Copilot no completada", "copilot_reserved": "Consulta al Copilot iniciada"}
METRICS = {"ai": "Consultas de IA", "members": "Miembros", "clients": "Clientes", "automations": "Automatizaciones", "reports": "Informes"}


def shell(c, actor, active):
    organization = dict(c.execute("SELECT id,name,slug,status,plan FROM organizations WHERE id=?", (actor.organization_id,)).fetchone())
    user = dict(c.execute("SELECT name,email FROM users WHERE id=?", (actor.user_id,)).fetchone())
    policy = describe(c, actor.organization_id)
    return {"organization": organization, "user": user, "role": actor.role, "policy": policy,
            "active": active, "nav": NAV, "plan": policy.get("plan", organization["plan"]),
            "can_write": actor.role in ("owner", "admin", "manager"),
            "can_bill": actor.role in ("owner", "admin"), "demo": bool(current_app.config.get("SAAS_DEMO")),
            "meters": [{"label": label, "used": policy["usage"].get(key, 0), "limit": policy["limits"].get(key)} for key, label in METRICS.items()] if policy.get("managed") else []}


def records(c, actor, section, rid=None):
    table, title, description, fields, legacy = COLLECTIONS[section]
    sql = f"SELECT {','.join(fields)} FROM {table} WHERE organization_id=?"
    params = [actor.organization_id]
    if rid is not None:
        sql += " AND id=?"
        params.append(rid)
    rows = c.execute(sql + " ORDER BY id DESC LIMIT 100", params).fetchall()
    if rid is not None and not rows:
        abort(404)
    return [dict(row) for row in rows]


def pretty(value):
    if value is None or value == "":
        return "Sin información registrada"
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            return json.dumps(json.loads(value), ensure_ascii=False, indent=2)
        except (ValueError, RecursionError):
            pass
    return str(value)


def install(app, connect):
    bp = Blueprint("workspace", __name__)
    bp.add_app_template_filter(pretty, "workspace_text")

    @bp.before_request
    def validate_parameters():
        if request.args:
            abort(400)
        if not session.get("user_id"):
            return redirect(url_for("cliente_acceso"))

    @bp.after_request
    def private(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.errorhandler(HTTPException)
    def error(error):
        return render_template("workspace/error.html", code=error.code), error.code

    @bp.errorhandler(LimitExceeded)
    def limited(_error):
        return render_template("workspace/error.html", code=402), 402

    @bp.errorhandler(sqlite3.Error)
    def unavailable(_error):
        return render_template("workspace/error.html", code=503), 503

    @bp.get("/saas/dashboard")
    def dashboard():
        with closing(connect()) as c:
            actor = resolve_context(c, product=False)
            ui = shell(c, actor, "dashboard")
            allowed = not ui["policy"].get("managed") or ui["policy"].get("paid")
            stats, pending, results, activity = {}, [], [], []
            if allowed:
                resolve_context(c)
                for section in ("diagnosticos", "contenido", "informes"):
                    table = COLLECTIONS[section][0]
                    stats[section] = c.execute(f"SELECT count(*) FROM {table} WHERE organization_id=?", (actor.organization_id,)).fetchone()[0]
                stats["pending"] = c.execute("SELECT count(*) FROM solicitudes WHERE organization_id=? AND estado='Pendiente'", (actor.organization_id,)).fetchone()[0]
                pending = [dict(row) for row in c.execute("SELECT id,asunto,estado,fecha FROM solicitudes WHERE organization_id=? AND estado='Pendiente' ORDER BY id DESC LIMIT 4", (actor.organization_id,))]
                results = [dict(row) for row in c.execute("SELECT periodo,contactos,ventas,ingresos FROM resultados_mensuales WHERE organization_id=? ORDER BY periodo DESC LIMIT 6", (actor.organization_id,))][::-1]
                activity = [{"label": ACTIVITY.get(row["action"], "Actividad de la organización"), "date": str(row["created_at"])[:16].replace("T", " ")} for row in c.execute("SELECT action,created_at FROM saas_audit WHERE organization_id=? ORDER BY id DESC LIMIT 5", (actor.organization_id,))]
            return render_template("workspace/dashboard.html", ui=ui, stats=stats, pending=pending, results=results, activity=activity, allowed=allowed, today=datetime.now().strftime("%d / %m / %Y"), max_contacts=max([row["contactos"] for row in results] + [1]))

    @bp.get("/saas/clientes", endpoint="clientes")
    def clients():
        with closing(connect()) as c:
            actor = resolve_context(c)
            return render_template("workspace/clients.html", ui=shell(c, actor, "clientes"))

    @bp.get("/saas/equipo", endpoint="equipo")
    def team():
        with closing(connect()) as c:
            actor = resolve_context(c)
            members = [dict(row) for row in c.execute("SELECT m.role,m.status,u.name,u.email FROM organization_memberships m JOIN users u ON u.id=m.user_id WHERE m.organization_id=? ORDER BY m.id", (actor.organization_id,))]
            return render_template("workspace/team.html", ui=shell(c, actor, "equipo"), members=members)

    @bp.get("/saas/facturacion", endpoint="facturacion")
    def billing():
        with closing(connect()) as c:
            actor = resolve_context(c, "billing", product=False)
            return render_template("workspace/billing.html", ui=shell(c, actor, "facturacion"))

    @bp.get("/saas/configuracion", endpoint="configuracion")
    def settings():
        with closing(connect()) as c:
            actor = resolve_context(c, product=False)
            return render_template("workspace/settings.html", ui=shell(c, actor, "configuracion"))

    def collection(section, rid=None):
        with closing(connect()) as c:
            actor = resolve_context(c)
            return render_template("workspace/collection.html", ui=shell(c, actor, section), section=section,
                info=COLLECTIONS[section], rows=records(c, actor, section, rid), detail=rid is not None)

    for section in COLLECTIONS:
        bp.add_url_rule(f"/saas/{section}", endpoint=section, view_func=lambda section=section: collection(section))
        bp.add_url_rule(f"/saas/{section}/<int:rid>", endpoint=section + "_detail", view_func=lambda rid, section=section: collection(section, rid))
    app.register_blueprint(bp)
