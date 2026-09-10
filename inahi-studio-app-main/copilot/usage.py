"""Durable reservations, scoped rate limits and optional cost estimates. No request bodies."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import os
import uuid
from copilot.errors import QuotaExceeded, Duplicate, Unavailable, InvalidOutput
from copilot.audit import record
from billing.repository import subscription
from billing.entitlements import reserve as reserve_billing, require_paid
from billing.plans import catalog
from saas_schema import now


def policy(c, actor):
    row = subscription(c, actor.organization_id, lock=True)
    if not row:
        raise Unavailable()
    base = catalog(row["plan"])["limits"]["ai"]
    raw = os.environ.get(f"COPILOT_LIMIT_{row['plan']}")
    try:
        limit = base if raw is None else (None if raw == "unlimited" else int(raw))
        rate = int(os.environ.get("COPILOT_REQUESTS_PER_MINUTE", "5"))
        concurrent = int(os.environ.get("COPILOT_MAX_INFLIGHT", "2"))
        if (limit is not None and limit < 0) or not 1 <= rate <= 100 or not 1 <= concurrent <= 10:
            raise ValueError()
    except ValueError:
        raise Unavailable() from None
    return {"plan": row["plan"], "limit": limit, "rate_per_minute": rate, "max_inflight": concurrent}


def summary(c, actor):
    rules = policy(c, actor)
    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    row = c.execute("""SELECT count(*) AS calls,COALESCE(sum(input_tokens),0) AS input_tokens,
        COALESCE(sum(output_tokens),0) AS output_tokens,COALESCE(sum(total_tokens),0) AS total_tokens,
        sum(estimated_cost) AS estimated_cost,COUNT(total_tokens) AS calls_with_known_tokens
        FROM copilot_usage WHERE organization_id=? AND created_at>=?""", (actor.organization_id, start)).fetchone()
    from copilot.budgets import summary as budget_summary
    return {**rules, **dict(row), "budget": budget_summary(c, actor.organization_id), "estimated_cost": str(row["estimated_cost"]) if row["estimated_cost"] is not None else None,
            "remaining": None if rules["limit"] is None else max(0, rules["limit"] - row["calls"]),
            "period": start[:7], "currency": "USD"}


def reserve(c, actor, feature, provider, request_key, fingerprint, source_count):
    rules = policy(c, actor)  # Row lock serializes reservations across workers on PostgreSQL.
    require_paid(c, actor.organization_id)
    previous = c.execute("SELECT id FROM copilot_usage WHERE organization_id=? AND user_id=? AND request_key=?",
                         (actor.organization_id, actor.user_id, request_key)).fetchone()
    if previous:
        raise Duplicate()
    instant = datetime.now(timezone.utc)
    stale = (instant - timedelta(minutes=10)).isoformat()
    recent = (instant - timedelta(minutes=1)).isoformat()
    c.execute("UPDATE copilot_usage SET status='abandoned',completed_at=? WHERE organization_id=? AND status='reserved' AND created_at<?", (now(), actor.organization_id, stale))
    current = summary(c, actor)
    per_user = c.execute("SELECT count(*) FROM copilot_usage WHERE organization_id=? AND user_id=? AND created_at>=?", (actor.organization_id, actor.user_id, recent)).fetchone()[0]
    running = c.execute("SELECT count(*) FROM copilot_usage WHERE organization_id=? AND status='reserved'", (actor.organization_id,)).fetchone()[0]
    if (rules["limit"] is not None and current["calls"] >= rules["limit"]) or per_user >= rules["rate_per_minute"] or running >= rules["max_inflight"]:
        raise QuotaExceeded()
    reserve_billing(c, actor.organization_id, "ai")
    call_id = str(uuid.uuid4())
    c.execute("""INSERT INTO copilot_usage(id,organization_id,user_id,request_key,fingerprint,feature,provider,model,status,created_at,source_count)
        VALUES(?,?,?,?,?,?,?,?,'reserved',?,?)""", (call_id, actor.organization_id, actor.user_id, request_key, fingerprint,
                 feature, provider.name, provider.model, now(), source_count))
    record(c, "reserved", actor)
    return call_id


def metrics(completion, provider):
    counts = (completion.input_tokens, completion.output_tokens, completion.total_tokens)
    if any(value is not None and (type(value) is not int or not 0 <= value <= 1000000000) for value in counts):
        raise InvalidOutput()
    incoming, outgoing, total = counts
    if incoming is not None and outgoing is not None:
        if total is not None and total != incoming + outgoing:
            raise InvalidOutput()
        total = incoming + outgoing
    cost = "0" if provider.name == "local" else None
    if provider.name != "local" and incoming is not None and outgoing is not None:
        try:
            a = Decimal(os.environ["COPILOT_INPUT_USD_PER_MILLION"])
            b = Decimal(os.environ["COPILOT_OUTPUT_USD_PER_MILLION"])
            if a.is_finite() and b.is_finite() and 0 <= a <= 100000 and 0 <= b <= 100000:
                cost = str(((a * incoming + b * outgoing) / 1000000).quantize(Decimal("0.0000000001")))
        except (KeyError, InvalidOperation):
            pass
    return incoming, outgoing, total, cost


def finish(c, actor, call_id, status, values=(None, None, None, None)):
    count = c.execute("""UPDATE copilot_usage SET status=?,input_tokens=?,output_tokens=?,total_tokens=?,estimated_cost=?,
        cost_currency=?,completed_at=? WHERE id=? AND organization_id=? AND user_id=? AND status='reserved'""",
        (status, *values, "USD" if values[3] is not None else None, now(), call_id, actor.organization_id, actor.user_id)).rowcount
    if count != 1:
        raise Duplicate()
    record(c, status, actor)
