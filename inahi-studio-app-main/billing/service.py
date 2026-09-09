"""Organization-owned Stripe operations; browser input never determines subscription state."""
from contextlib import closing
import time
import uuid
from billing import gateway
from billing.plans import catalog, price
from billing.repository import subscription, provision, enabled
from saas_schema import audit


def ensure(connect, oid, plan):
    catalog(plan)
    with closing(connect()) as c, c:
        c.execute("BEGIN IMMEDIATE")
        if not enabled(c):
            raise ValueError("Aplicar migración billing explícita")
        row = subscription(c, oid, lock=True)
        if row:
            return row
        account = c.execute("SELECT c.* FROM clientes c JOIN organizations o ON o.legacy_cliente_id=c.id WHERE o.id=?", (oid,)).fetchone()
        if not account:
            raise ValueError("Organización inexistente")
        raise ValueError("Asociar primero la suscripción legacy mediante informe; conservar prueba y derechos actuales")


def customer(connect, oid, provider):
    with closing(connect()) as c, c:
        c.execute("BEGIN IMMEDIATE")
        row = subscription(c, oid, lock=True)
        if not row:
            raise ValueError("Suscripción local inexistente")
        if not row["stripe_customer_id"]:
            name = c.execute("SELECT name FROM organizations WHERE id=?", (oid,)).fetchone()[0]
            result = provider.create_customer(oid, name, row["customer_key"])
            if result.get("livemode") is not False or not str(result.get("id", "")).startswith("cus_"):
                raise ValueError("Customer Stripe inválido o live")
            c.execute("UPDATE organization_subscriptions SET stripe_customer_id=? WHERE organization_id=?", (result["id"], oid))
        return subscription(c, oid)


def start_checkout(connect, oid, plan):
    price_id = price(plan)
    ensure(connect, oid, plan)
    provider = gateway.Gateway()
    customer(connect, oid, provider)
    with closing(connect()) as c, c:
        c.execute("BEGIN IMMEDIATE")
        row = subscription(c, oid, lock=True)
        if row["stripe_subscription_id"] and row["status"] != "canceled":
            raise ValueError("La suscripción existente se modifica mediante Customer Portal")
        replace = not row["checkout_key"]
        if row["checkout_id"] and (row["checkout_expires_at"] <= int(time.time()) or row["status"] == "canceled"):
            previous = provider.retrieve_checkout(row["checkout_id"])
            if previous.get("livemode") is not False or previous.get("customer") != row["stripe_customer_id"]:
                raise ValueError("Checkout anterior no pertenece a esta organización")
            if previous.get("status") == "expired":
                replace = True
            elif previous.get("status") == "complete":
                if row["status"] != "canceled" or previous.get("subscription") != row["stripe_subscription_id"]:
                    raise ValueError("Checkout completado: reconciliar antes de crear otra suscripción")
                previous_subscription = provider.retrieve_subscription(row["stripe_subscription_id"])
                if previous_subscription.get("livemode") is not False or previous_subscription.get("customer") != row["stripe_customer_id"] or previous_subscription.get("status") != "canceled":
                    raise ValueError("Confirmar cancelación en Stripe antes de iniciar otra suscripción")
                replace = True
            elif previous.get("status") != "open":
                raise ValueError("Estado de checkout no reconocido")
        if not replace:
            if row["checkout_plan"] != plan:
                raise ValueError("Hay un checkout pendiente para otro plan")
        else:
            c.execute("""UPDATE organization_subscriptions SET checkout_key=?,checkout_plan=?,checkout_price_id=?,checkout_id=NULL,
                checkout_url=NULL,checkout_expires_at=? WHERE organization_id=?""", (str(uuid.uuid4()), plan, price_id, int(time.time()) + 3600, oid))
        row = subscription(c, oid)
    # The retry key and exact plan/expiry are committed before the provider call.
    if row["checkout_url"]:
        return {"url": row["checkout_url"]}
    result = provider.checkout(row, row["checkout_price_id"] or price_id)
    if result.get("livemode") is not False or result.get("customer") != row["stripe_customer_id"]:
        raise ValueError("Checkout de otro customer o live")
    with closing(connect()) as c, c:
        c.execute("UPDATE organization_subscriptions SET checkout_id=?,checkout_url=? WHERE organization_id=? AND checkout_key=?",
                  (result["id"], result["url"], oid, row["checkout_key"]))
    return {"url": result["url"]}


def portal(connect, oid, plan=None, cancel=False):
    with closing(connect()) as c:
        row = subscription(c, oid)
    if not row or not row["stripe_customer_id"]:
        raise ValueError("La organización no tiene Customer asociado")
    provider = gateway.Gateway()
    flow = None
    if plan is not None or cancel:
        if not row["stripe_subscription_id"]:
            raise ValueError("No existe suscripción")
        current = provider.retrieve_subscription(row["stripe_subscription_id"])
        if current.get("livemode") is not False or current.get("customer") != row["stripe_customer_id"]:
            raise ValueError("La suscripción no pertenece a la organización")
        if cancel:
            flow = {"type": "subscription_cancel", "subscription_cancel": {"subscription": current["id"]}}
        else:
            items = current.get("items", {}).get("data", [])
            if len(items) != 1:
                raise ValueError("Revisar suscripción con múltiples items")
            flow = {"type": "subscription_update_confirm", "subscription_update_confirm": {
                "subscription": current["id"], "items": [{"id": items[0]["id"], "price": price(plan), "quantity": 1}]}}
    with closing(connect()) as c, c:
        audit(c, "billing_portal_requested", oid)
    result = provider.portal(row["stripe_customer_id"], flow)
    return {"url": result["url"]}


def reconcile(connect, oid):
    from billing.webhooks import synchronize
    with closing(connect()) as c, c:
        c.execute("BEGIN IMMEDIATE")
        row = subscription(c, oid, lock=True)
        if not row:
            raise ValueError("Sin suscripción para reconciliar")
        provider = gateway.Gateway()
        sid = row["stripe_subscription_id"]
        if row["checkout_id"]:
            checkout = provider.retrieve_checkout(row["checkout_id"])
            if checkout.get("livemode") is not False or checkout.get("customer") != row["stripe_customer_id"]:
                raise ValueError("Checkout no pertenece a la organización")
            if checkout.get("status") == "complete":
                sid = checkout.get("subscription")
        if not sid:
            raise ValueError("Sin suscripción para reconciliar")
        snapshot = provider.retrieve_subscription(sid)
        synchronize(c, row, snapshot)


def change_subscription(connect, oid, plan):
    return portal(connect, oid, plan=plan)


def cancel_subscription(connect, oid):
    return portal(connect, oid, cancel=True)
