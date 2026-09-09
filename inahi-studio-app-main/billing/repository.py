from persistence.database import has_table
from saas_schema import now
import uuid


def enabled(c):
    if not has_table(c, "billing_schema_state"):
        return False
    row = c.execute("SELECT enabled FROM billing_schema_state WHERE version='0003_org_billing'").fetchone()
    return bool(row and row[0])


def subscription(c, oid, lock=False):
    if not enabled(c):
        return None
    suffix = " FOR UPDATE" if lock and getattr(c, "dialect", "sqlite") == "postgresql" else ""
    row = c.execute("SELECT * FROM organization_subscriptions WHERE organization_id=?" + suffix, (oid,)).fetchone()
    return dict(row) if row else None


def provision(c, oid, plan="STARTER", status="incomplete", customer=None, stripe_subscription=None, legacy=False):
    stamp = now()
    c.execute("""INSERT INTO organization_subscriptions(organization_id,plan,status,stripe_customer_id,
        stripe_subscription_id,created_at,updated_at,legacy_mode,customer_key) VALUES(?,?,?,?,?,?,?,?,?)""",
        (oid, plan, status, customer or None, stripe_subscription or None, stamp, stamp, int(legacy), str(uuid.uuid4())))
    return subscription(c, oid)
