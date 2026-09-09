"""Verified events are signals: reconcile canonical state under the organization lock."""
from contextlib import closing
from datetime import datetime, timezone
from billing import gateway
from billing.repository import enabled, subscription
from billing.plans import plan_for_price, REVERSE, LEGACY
import os
from saas_schema import now, audit

EVENTS = frozenset(("checkout.session.completed", "customer.subscription.created", "customer.subscription.updated",
                    "customer.subscription.deleted", "invoice.paid", "invoice.payment_failed"))
STATES = {"trialing": "trialing", "active": "active", "past_due": "past_due", "unpaid": "past_due",
          "paused": "past_due", "canceled": "canceled", "incomplete": "incomplete", "incomplete_expired": "canceled"}


def identifier(value):
    return value.get("id") if isinstance(value, dict) else value


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def synchronize(c, row, current):
    if current.get("livemode") is not False or identifier(current.get("customer")) != row["stripe_customer_id"]:
        raise ValueError("Snapshot live o customer incorrecto")
    sid = current.get("id")
    if not isinstance(sid, str) or not sid.startswith("sub_"):
        raise ValueError("Suscripción Stripe inválida")
    if row["stripe_subscription_id"] != sid:
        meta = current.get("metadata") or {}
        if (row["stripe_subscription_id"] and row["status"] != "canceled") or not row["checkout_key"] or meta.get("billing_key") != row["checkout_key"] or meta.get("organization_id") != str(row["organization_id"]) or meta.get("billing_scope") != "b2b":
            raise ValueError("No existe checkout autorizado para esta suscripción")
    items = current.get("items", {}).get("data", [])
    if len(items) != 1 or current.get("status") not in STATES:
        raise ValueError("Estado o items no soportados")
    price_id = identifier(items[0].get("price"))
    legacy_mode = 0
    try:
        plan = plan_for_price(price_id)
    except ValueError:
        old_env = {"esencial": "STRIPE_PRICE_ESENCIAL", "crecimiento": "STRIPE_PRICE_CRECIMIENTO", "pro": "STRIPE_PRICE_PRO"}
        matches = [key for key, env in old_env.items() if price_id and os.environ.get(env) == price_id]
        if not row["legacy_mode"] or len(matches) != 1:
            raise
        plan, legacy_mode = LEGACY[matches[0]], 1
    status = STATES[current["status"]]
    start = stamp(current.get("current_period_start", items[0].get("current_period_start")))
    end = stamp(current.get("trial_end") if status == "trialing" else current.get("current_period_end", items[0].get("current_period_end")))
    c.execute("""UPDATE organization_subscriptions SET plan=?,status=?,stripe_subscription_id=?,
        current_period_start=?,current_period_end=?,cancel_at_period_end=?,updated_at=?,legacy_mode=? WHERE organization_id=?""",
        (plan, status, sid, start, end, int(bool(current.get("cancel_at_period_end"))), now(), legacy_mode, row["organization_id"]))
    # Keep old product flows and provider references usable; do not reinterpret legacy data elsewhere.
    legacy_key = REVERSE[plan]
    c.execute("""UPDATE clientes SET stripe_customer_id=?,stripe_subscription_id=?,subscription_status=?,activo=?,
        plan_key=?,trial_end=CASE WHEN ?='trialing' THEN ? ELSE trial_end END WHERE id=(SELECT legacy_cliente_id FROM organizations WHERE id=?)""",
        (row["stripe_customer_id"], sid, "activa" if status == "active" else "prueba" if status == "trialing" else status,
         int(status in ("active", "trialing")), legacy_key, status, end[:10] if end else "", row["organization_id"]))
    audit(c, "billing_reconciled", row["organization_id"])


def handles(event, connect):
    obj = (event.get("data") or {}).get("object") or {}
    if not isinstance(obj, dict):
        return False
    if (obj.get("metadata") or {}).get("billing_scope") == "b2b":
        return True
    customer = identifier(obj.get("customer"))
    if not customer:
        return False
    with closing(connect()) as c:
        return bool(enabled(c) and c.execute("SELECT 1 FROM organization_subscriptions WHERE stripe_customer_id=?", (customer,)).fetchone())


def process(event, connect):
    if event.get("livemode") is not False:
        raise ValueError("B2B solo admite eventos test")
    kind, eid = event.get("type"), event.get("id")
    if not isinstance(eid, str) or not eid or type(event.get("created")) is not int:
        raise ValueError("Evento sin identidad/fecha")
    if kind not in EVENTS:
        return False
    obj = (event.get("data") or {}).get("object")
    if not isinstance(obj, dict):
        raise ValueError("Objeto inválido")
    cid = identifier(obj.get("customer"))
    with closing(connect()) as c, c:
        c.execute("BEGIN IMMEDIATE")
        if not enabled(c):
            raise ValueError("Billing no preparado")
        match = c.execute("SELECT organization_id FROM organization_subscriptions WHERE stripe_customer_id=?", (cid,)).fetchone()
        if not match:
            raise ValueError("Customer B2B no asociado")
        row = subscription(c, match[0], lock=True)
        if c.execute("SELECT 1 FROM billing_events WHERE event_id=?", (eid,)).fetchone():
            return False
        sid = obj.get("id") if kind.startswith("customer.subscription.") else identifier(obj.get("subscription"))
        if not sid and kind.startswith("invoice."):
            sid = identifier(((obj.get("parent") or {}).get("subscription_details") or {}).get("subscription"))
        if not isinstance(sid, str) or not sid.startswith("sub_"):
            raise ValueError("Evento sin suscripción")
        # No event-created ordering heuristic: retrieve canonical state, even for old invoices.
        snapshot = gateway.Gateway().retrieve_subscription(sid)
        if snapshot.get("livemode") is not False or identifier(snapshot.get("customer")) != row["stripe_customer_id"] or snapshot.get("id") != sid:
            raise ValueError("Snapshot de otra suscripción/customer o live")
        meta = snapshot.get("metadata") or {}
        replacement = (row["status"] == "canceled" and row["checkout_key"] and meta.get("billing_key") == row["checkout_key"]
                       and meta.get("organization_id") == str(row["organization_id"]) and meta.get("billing_scope") == "b2b")
        if row["stripe_subscription_id"] and row["stripe_subscription_id"] != sid and not replacement:
            # An old subscription of the same customer cannot overwrite its replacement.
            c.execute("INSERT INTO billing_events(event_id,organization_id,event_type,event_created,processed_at) VALUES(?,?,?,?,?)", (eid, row["organization_id"], kind, event["created"], now()))
            return True
        synchronize(c, row, snapshot)
        c.execute("INSERT INTO billing_events(event_id,organization_id,event_type,event_created,processed_at) VALUES(?,?,?,?,?)", (eid, row["organization_id"], kind, event["created"], now()))
    return True
