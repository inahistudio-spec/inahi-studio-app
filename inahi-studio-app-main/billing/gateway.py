"""Stripe transport for B2B. Live keys are deliberately unsupported in this phase."""
import os
from urllib.parse import urlparse
import stripe


def return_url():
    value = os.environ.get("B2B_RETURN_URL", "").strip()
    parsed = urlparse(value)
    if not parsed.hostname or parsed.username or not (parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1"))):
        raise ValueError("Configurar B2B_RETURN_URL seguro en el servidor")
    return value


class Gateway:
    def __init__(self):
        key = os.environ.get("STRIPE_B2B_SECRET_KEY", "").strip()
        if not key.startswith("sk_test_") or os.environ.get("STRIPE_B2B_MODE", "test") != "test":
            raise ValueError("Billing B2B solo admite Stripe test mode")
        self.api = stripe.StripeClient(key, max_network_retries=2).v1

    def create_customer(self, oid, name, key):
        return self.api.customers.create({"name": name, "metadata": {"organization_id": str(oid), "billing_scope": "b2b"}}, options={"idempotency_key": key})

    def checkout(self, row, price_id):
        meta = {"organization_id": str(row["organization_id"]), "billing_scope": "b2b", "billing_key": row["checkout_key"]}
        return self.api.checkout.sessions.create({"customer": row["stripe_customer_id"], "mode": "subscription",
            "client_reference_id": str(row["organization_id"]), "line_items": [{"price": price_id, "quantity": 1}],
            "metadata": meta, "subscription_data": {"metadata": meta},
            "success_url": return_url(), "cancel_url": return_url(), "expires_at": row["checkout_expires_at"]},
            options={"idempotency_key": row["checkout_key"]})

    def retrieve_subscription(self, sid):
        return self.api.subscriptions.retrieve(sid)

    def retrieve_checkout(self, session_id):
        return self.api.checkout.sessions.retrieve(session_id)

    def portal(self, customer, flow=None):
        params = {"customer": customer, "return_url": return_url()}
        if flow:
            params["flow_data"] = flow
        return self.api.billing_portal.sessions.create(params)


def verify(payload, signature):
    secret = os.environ.get("STRIPE_B2B_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise ValueError("Falta secreto del webhook B2B")
    return stripe.Webhook.construct_event(payload, signature, secret)
