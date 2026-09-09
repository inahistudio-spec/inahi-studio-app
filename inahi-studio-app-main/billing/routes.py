"""Small JSON surface. All organization access is checked against the active membership."""
from contextlib import closing
from flask import Blueprint, abort, request, session, redirect, url_for
import sqlite3
import stripe
from billing import service, gateway
from billing.repository import subscription, enabled
from billing.entitlements import describe, LimitExceeded
from billing.webhooks import process
from saas_core import tenant_required, platform_required, resolve_context

PUBLIC_FIELDS = ("organization_id", "plan", "status", "stripe_customer_id", "stripe_subscription_id",
                 "current_period_start", "current_period_end", "cancel_at_period_end", "created_at", "updated_at")


def snapshot(c, oid):
    row = subscription(c, oid)
    return {"subscription": {k: row[k] for k in PUBLIC_FIELDS} if row else None, "entitlements": describe(c, oid)}


def install(app, connect):
    bp = Blueprint("b2b_billing", __name__)

    @app.before_request
    def managed_legacy_entrypoints():
        if request.endpoint not in ("crear_checkout", "facturacion", "pago_correcto") or not session.get("cliente_id"):
            return
        from billing.legacy import organization
        with closing(connect()) as c:
            oid = organization(c, session["cliente_id"])
            row = subscription(c, oid) if oid else None
            if row and resolve_context(c, "billing", product=False).organization_id != oid:
                abort(404)
        if not row:
            return
        # SaaS's earlier guard already validates active organization and billing role.
        # A legacy GET cannot create a second subscription once B2B owns billing.
        if request.endpoint == "facturacion":
            try:
                return redirect(service.portal(connect, oid)["url"], code=303)
            except (ValueError, sqlite3.Error, stripe.error.StripeError):
                return {"error": "Portal B2B no disponible"}, 503
        return redirect(url_for("b2b_billing.read", oid=oid), code=303)

    @bp.errorhandler(ValueError)
    def invalid(_error):
        return {"error": "Operación de billing inválida o configuración incompleta"}, 400

    @bp.errorhandler(sqlite3.Error)
    @bp.errorhandler(stripe.error.StripeError)
    def unavailable(_error):
        return {"error": "Billing no disponible; reintentar de forma segura"}, 503

    @app.errorhandler(LimitExceeded)
    def limited(_error):
        return {"error": "La suscripción o su límite no permite esta operación"}, 402

    def validate(context, oid, allowed=()):
        if context.organization_id != oid:
            abort(404)
        if request.args or set(request.form) - {"csrf_token", *allowed}:
            abort(400)

    @bp.get("/saas/billing/<int:oid>")
    @tenant_required(connect, "billing", product=False)
    def read(context, oid):
        validate(context, oid)
        with closing(connect()) as c:
            return snapshot(c, oid)

    @bp.post("/saas/billing/<int:oid>/checkout")
    @tenant_required(connect, "billing", product=False)
    def checkout(context, oid):
        validate(context, oid, ("plan",))
        return service.start_checkout(connect, oid, request.form.get("plan", ""))

    @bp.post("/saas/billing/<int:oid>/portal")
    @tenant_required(connect, "billing", product=False)
    def portal(context, oid):
        validate(context, oid)
        return service.portal(connect, oid)

    @bp.post("/saas/billing/<int:oid>/change-plan")
    @tenant_required(connect, "billing", product=False)
    def change(context, oid):
        validate(context, oid, ("plan",))
        return service.change_subscription(connect, oid, request.form.get("plan", ""))

    @bp.post("/saas/billing/<int:oid>/cancel")
    @tenant_required(connect, "billing", product=False)
    def cancel(context, oid):
        validate(context, oid)
        return service.cancel_subscription(connect, oid)

    @bp.get("/platform/billing")
    @platform_required
    def platform():
        with closing(connect()) as c:
            if not enabled(c):
                abort(404)
            rows = c.execute("SELECT id,name FROM organizations ORDER BY id LIMIT 100").fetchall()
            return {"organizations": [{"id": r["id"], "name": r["name"], **snapshot(c, r["id"])} for r in rows]}

    @bp.post("/platform/billing/<int:oid>/reconcile")
    @platform_required
    def reconcile(oid):
        if request.args or set(request.form) - {"csrf_token"}:
            abort(400)
        service.reconcile(connect, oid)
        return {"reconciled": True}

    @bp.get("/platform/billing/<int:oid>")
    @platform_required
    def platform_detail(oid):
        with closing(connect()) as c:
            if not enabled(c):
                abort(404)
            row = c.execute("SELECT name FROM organizations WHERE id=?", (oid,)).fetchone()
            if not row:
                abort(404)
            return {"id": oid, "name": row[0], **snapshot(c, oid)}

    @bp.post("/stripe/b2b/webhook")
    def webhook():
        try:
            event = gateway.verify(request.get_data(), request.headers.get("Stripe-Signature", ""))
        except (ValueError, stripe.error.SignatureVerificationError):
            abort(400)
        processed = process(event, connect)
        return {"received": True, "processed": processed}

    app.register_blueprint(bp)
