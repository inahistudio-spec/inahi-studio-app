"""One policy service; reserves usage atomically inside the caller's transaction."""
from datetime import datetime, timezone
from billing.plans import catalog, METRICS
from billing.repository import subscription


class LimitExceeded(Exception):
    pass


def period(metric):
    return "total" if metric in ("members", "clients") else datetime.now(timezone.utc).strftime("%Y-%m")


def describe(c, oid):
    row = subscription(c, oid)
    if not row:
        return {"legacy": True, "managed": False}
    policy = catalog(row["plan"])
    # Explicit legacy adoption must not silently lower purchased allowances.
    if row["legacy_mode"]:
        policy["limits"] = dict.fromkeys(METRICS)
        policy["premium"] = True
    used = {}
    for metric in METRICS:
        entry = c.execute("SELECT amount FROM billing_usage WHERE organization_id=? AND metric=? AND period=?", (oid, metric, period(metric))).fetchone()
        used[metric] = entry[0] if entry else 0
    used["members"] = c.execute("SELECT count(*) FROM organization_memberships WHERE organization_id=? AND status='active'", (oid,)).fetchone()[0]
    paid = row["status"] in ("active", "trialing")
    if row["status"] == "trialing":
        paid = bool(row["current_period_end"] and datetime.fromisoformat(str(row["current_period_end"])) > datetime.now(timezone.utc))
    return {**policy, "managed": True, "legacy": bool(row["legacy_mode"]), "status": row["status"], "paid": paid, "usage": used}


def require_paid(c, oid, premium=False):
    policy = describe(c, oid)
    if policy["managed"] and (not policy["paid"] or (premium and not policy["premium"])):
        raise LimitExceeded("La suscripción no permite esta funcionalidad")
    return policy


def reserve(c, oid, metric, amount=1):
    if metric not in METRICS or type(amount) is not int or amount <= 0:
        raise ValueError("Consumo inválido")
    # Lock also serializes membership counts on PostgreSQL; SQLite writers use BEGIN IMMEDIATE.
    subscription(c, oid, lock=True)
    policy = require_paid(c, oid)
    if not policy["managed"]:
        return
    limit = policy["limits"][metric]
    if metric == "members":
        if limit is not None and policy["usage"][metric] + amount > limit:
            raise LimitExceeded("Límite de miembros alcanzado")
        return
    window = period(metric)
    c.execute("INSERT INTO billing_usage(organization_id,metric,period,amount) VALUES(?,?,?,0) ON CONFLICT(organization_id,metric,period) DO NOTHING", (oid, metric, window))
    sql = "UPDATE billing_usage SET amount=amount+? WHERE organization_id=? AND metric=? AND period=?"
    args = [amount, oid, metric, window]
    if limit is not None:
        sql += " AND amount+?<=?"
        args.extend((amount, limit))
    if c.execute(sql, args).rowcount != 1:
        raise LimitExceeded("Límite de consumo alcanzado")
