"""Minimal server-side SaaS surface and guards for the existing Flask product."""

from contextlib import closing
import secrets
import sqlite3
import json

import click
from flask import Blueprint, abort, jsonify, request, session

from saas_core import (add_membership, change_membership, create_organization,
                       create_user, platform_required, resolve_context, tenant_required)
from saas_schema import RESOURCES, audit, downgrade, enabled, now, upgrade

LEGACY_ENDPOINTS = frozenset(("portal", "diagnostico", "estrategia_comercial", "calendario_contenidos",
    "resultados_mensuales", "solicitud_cliente", "informes_cliente", "cambiar_contrasena",
    "solicitar_cita", "facturacion", "crear_checkout", "pago_correcto"))


def install_saas(app, connect, plans):
    bp = Blueprint("saas", __name__)

    @app.cli.command("saas-upgrade")
    def upgrade_command():
        """Apply additive SaaS migration to the explicitly configured DATABASE_PATH."""
        try:
            from persistence.planning import inspect_legacy, require_clean
            with closing(connect()) as c:
                report = inspect_legacy(c)
            click.echo(json.dumps(report, ensure_ascii=False, indent=2))
            require_clean(report)
            applied = upgrade(connect)
        except (ValueError, sqlite3.Error) as error:
            raise click.ClickException(str(error)) from error
        click.echo("SaaS activado." if applied else "SaaS ya estaba activo.")

    @app.cli.command("saas-downgrade")
    def downgrade_command():
        """Revert routing/backfill only when no incompatible SaaS activity exists."""
        try:
            reverted = downgrade(connect)
        except (ValueError, sqlite3.Error) as error:
            raise click.ClickException(str(error)) from error
        click.echo("Modo legacy restaurado sin borrar datos." if reverted else "SaaS no estaba activo.")

    @app.before_request
    def guard_legacy_tenant():
        if request.endpoint not in LEGACY_ENDPOINTS:
            return
        if not session.get("cliente_id") and not session.get("user_id"):
            return
        with closing(connect()) as c:
            if not enabled(c):
                # Never interpret a parked multi-user session as a legacy owner.
                if session.get("user_id"):
                    session.clear()
                    abort(401)
                return
            billing = request.endpoint in ("facturacion", "crear_checkout", "pago_correcto")
            permission = "billing" if billing else "read"
            if request.method == "POST" and not billing:
                permission = "request" if request.endpoint == "solicitud_cliente" else "write"
            if request.endpoint == "cambiar_contrasena":
                permission = "read"  # All roles can change their own User password.
            context = resolve_context(c, permission, product=not billing)
            for source in (request.args, request.form):
                for field, actual in (("organization_id", context.organization_id), ("cliente_id", context.cliente_id)):
                    if field in source and source.getlist(field) != [str(actual)]:
                        abort(404)
            if request.endpoint == "calendario_contenidos":
                # This legacy GET may generate or upgrade stored content.
                from datetime import date
                import json
                saved = c.execute("SELECT contenido FROM calendarios_contenido WHERE organization_id=? AND periodo=?",
                                  (context.organization_id, date.today().strftime("%Y-%m"))).fetchone()
                if not saved or json.loads(saved[0]).get("version", 1) < 2:
                    context.require("write")

    @bp.before_request
    def require_schema():
        with closing(connect()) as c:
            if not enabled(c):
                abort(404)

    @bp.errorhandler(ValueError)
    def invalid_input(_error):
        return {"error": "Datos inválidos o transición no permitida."}, 400

    @bp.errorhandler(sqlite3.IntegrityError)
    def conflicting_input(_error):
        return {"error": "Operación incompatible con los datos existentes."}, 409

    @bp.route("/saas/session")
    @tenant_required(connect)
    def current_session(context):
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return {"user_id": context.user_id, "organization_id": context.organization_id,
                "role": context.role, "csrf_token": session["csrf_token"]}

    @bp.route("/saas/organizations")
    @tenant_required(connect, product=False)
    def own_organizations(context):
        with closing(connect()) as c:
            rows = c.execute("""SELECT o.id,o.name,o.slug,o.status,o.plan,m.role FROM organizations o
                JOIN organization_memberships m ON m.organization_id=o.id
                WHERE m.user_id=? AND m.status='active' ORDER BY o.id""", (context.user_id,)).fetchall()
        return jsonify([dict(row) for row in rows])

    @bp.route("/saas/organizations/<int:organization_id>/activate", methods=["POST"])
    def activate(organization_id):
        with closing(connect()) as c:
            # Validate identity independently of the old active org, so users can leave a suspended org.
            user = c.execute("SELECT status,credential_version FROM users WHERE id=?", (session.get("user_id"),)).fetchone()
            if not user or user["status"] != "active" or session.get("credential_version") != user["credential_version"]:
                abort(401)
            target = c.execute("""SELECT o.legacy_cliente_id FROM organizations o JOIN organization_memberships m
                ON m.organization_id=o.id WHERE o.id=? AND m.user_id=? AND m.status='active' AND o.status='active'""",
                               (organization_id, session["user_id"])).fetchone()
            if not target:
                abort(404)
            session.update(organization_id=organization_id, cliente_id=target[0])
        return {"organization_id": organization_id}

    @bp.route("/saas/memberships")
    @tenant_required(connect)
    def memberships(context):
        with closing(connect()) as c:
            rows = c.execute("""SELECT m.id,m.user_id,m.role,m.status,u.name,u.email FROM organization_memberships m
                JOIN users u ON u.id=m.user_id WHERE m.organization_id=? ORDER BY m.id""",
                             (context.organization_id,)).fetchall()
        return jsonify([dict(row) for row in rows])

    @bp.route("/saas/memberships/<int:membership_id>", methods=["POST"])
    @tenant_required(connect, "members")
    def update_membership(context, membership_id):
        with closing(connect()) as c, c:
            c.execute("BEGIN IMMEDIATE")
            # Recheck membership under the writer lock (revocation/last-owner races).
            context = resolve_context(c, "members")
            change_membership(c, context, membership_id, request.form.get("role", ""), request.form.get("status", ""))
        return {"updated": True}

    @bp.route("/saas/resources/<kind>")
    @tenant_required(connect)
    def resource_list(context, kind):
        if kind not in RESOURCES:
            abort(404)
        # Client-supplied tenant filters are rejected rather than used as authorization.
        if any(key in request.args for key in ("organization_id", "cliente_id")):
            abort(400)
        with closing(connect()) as c:
            rows = c.execute(f"SELECT * FROM {kind} WHERE organization_id=? ORDER BY id LIMIT 100",
                             (context.organization_id,)).fetchall()
        return jsonify([dict(row) for row in rows])

    @bp.route("/saas/resources/<kind>/<int:resource_id>", methods=["GET", "POST"])
    @tenant_required(connect)
    def resource(context, kind, resource_id):
        if kind not in RESOURCES:
            abort(404)
        with closing(connect()) as c, c:
            if request.method == "POST":
                c.execute("BEGIN IMMEDIATE")
                context = resolve_context(c)
            row = c.execute(f"SELECT * FROM {kind} WHERE id=? AND organization_id=?",
                            (resource_id, context.organization_id)).fetchone()
            if not row:
                abort(404)
            if request.method == "GET":
                return dict(row)
            context.require("write")
            if kind != "informes":
                abort(405)  # Other writes retain their existing validated forms.
            if set(request.form) - {"csrf_token", "titulo", "contenido"}:
                abort(400)
            title, content = request.form.get("titulo", "").strip(), request.form.get("contenido", "").strip()
            if not title or len(title) > 150 or not content or len(content) > 10000:
                raise ValueError("Informe inválido")
            c.execute("UPDATE informes SET titulo=?,contenido=? WHERE id=? AND organization_id=?",
                      (title, content, resource_id, context.organization_id))
            audit(c, "report_updated", context.organization_id, context.user_id)
        return {"updated": True}

    @bp.route("/saas/reports", methods=["POST"])
    @tenant_required(connect, "write")
    def create_report(context):
        if set(request.form) - {"csrf_token", "titulo", "contenido"}:
            abort(400)
        title, content = request.form.get("titulo", "").strip(), request.form.get("contenido", "").strip()
        if not title or len(title) > 150 or not content or len(content) > 10000:
            raise ValueError("Informe inválido")
        with closing(connect()) as c, c:
            c.execute("BEGIN IMMEDIATE")
            context = resolve_context(c, "write")
            rid = c.execute("INSERT INTO informes(cliente_id,organization_id,titulo,contenido) VALUES(?,?,?,?)",
                            (context.cliente_id, context.organization_id, title, content)).lastrowid
            audit(c, "report_created", context.organization_id, context.user_id)
        return {"id": rid}, 201

    @bp.route("/platform/organizations", methods=["GET", "POST"])
    @platform_required
    def platform_organizations():
        with closing(connect()) as c, c:
            if request.method == "POST":
                c.execute("BEGIN IMMEDIATE")
                oid = create_organization(c, request.form.get("name", ""), request.form.get("slug", ""),
                                          request.form.get("plan", ""), int(request.form.get("owner_id", "0")), plans)
                return {"id": oid}, 201
            rows = c.execute("SELECT id,name,slug,status,plan,created_at,updated_at FROM organizations ORDER BY id LIMIT 100").fetchall()
        return jsonify([dict(row) for row in rows])

    @bp.route("/platform/organizations/<int:organization_id>", methods=["POST"])
    @platform_required
    def platform_organization_status(organization_id):
        status = request.form.get("status", "")
        if status not in ("active", "suspended", "archived"):
            raise ValueError("Estado inválido")
        with closing(connect()) as c, c:
            if c.execute("UPDATE organizations SET status=?,updated_at=? WHERE id=?", (status, now(), organization_id)).rowcount != 1:
                abort(404)
            audit(c, "organization_status_changed", organization_id)
        return {"updated": True}

    @bp.route("/platform/users", methods=["POST"])
    @platform_required
    def platform_create_user():
        with closing(connect()) as c, c:
            uid = create_user(c, request.form.get("email", ""), request.form.get("password", ""), request.form.get("name", ""))
        return {"id": uid}, 201

    @bp.route("/platform/memberships", methods=["POST"])
    @platform_required
    def platform_add_member():
        with closing(connect()) as c, c:
            c.execute("BEGIN IMMEDIATE")
            mid = add_membership(c, int(request.form.get("organization_id", "0")), int(request.form.get("user_id", "0")), request.form.get("role", ""))
        return {"id": mid}, 201

    app.register_blueprint(bp)
