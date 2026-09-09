"""Adapters for existing product controllers; no plan conditions in controllers."""
from contextlib import closing
from persistence.database import has_table
from billing.entitlements import reserve, describe


def organization(c, cid):
    if not has_table(c, "organizations"):
        return None
    row = c.execute("SELECT id FROM organizations WHERE legacy_cliente_id=?", (cid,)).fetchone()
    return row[0] if row else None


def consume(c, cid, metric):
    oid = organization(c, cid)
    if oid:
        reserve(c, oid, metric)


def meter(connect, cid, metric):
    with closing(connect()) as c, c:
        c.execute("BEGIN IMMEDIATE")
        consume(c, cid, metric)


def assistant_limit(c, cid, fallback):
    oid = organization(c, cid)
    policy = describe(c, oid) if oid else {"managed": False}
    return policy["limits"]["ai"] if policy["managed"] and not policy["legacy"] else fallback
