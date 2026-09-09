"""Explicit legacy subscription association; no provider calls or legacy writes."""
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import click
from billing.plans import LEGACY
from billing.repository import enabled, subscription, provision
from persistence.database import connect
from saas_schema import enabled as saas_enabled

STATES = {"activa": "active", "active": "active", "prueba": "trialing", "trialing": "trialing",
          "past_due": "past_due", "unpaid": "past_due", "cancelada": "canceled", "canceled": "canceled",
          "pendiente": "incomplete", "sin_pago": "incomplete", "incomplete": "incomplete"}


def inspect(c):
    if not saas_enabled(c):
        raise ValueError("Preparar organizaciones antes de asociar suscripciones")
    rows = c.execute("""SELECT c.*,o.id AS oid FROM clientes c JOIN organizations o ON o.legacy_cliente_id=c.id ORDER BY o.id""").fetchall()
    report = {"organizations": len(rows), "subscriptions_to_associate": 0, "billing_schema_ready": enabled(c), "conflicts": [], "warnings": []}
    seen_customers, seen_subs = set(), set()
    for row in rows:
        for field, seen in (("stripe_customer_id", seen_customers), ("stripe_subscription_id", seen_subs)):
            value = row[field]
            if value and value in seen:
                report["conflicts"].append({"organization_id": row["oid"], "code": "duplicate_" + field})
            if value:
                seen.add(value)
        if subscription(c, row["oid"]):
            continue
        for field in ("stripe_customer_id", "stripe_subscription_id"):
            if report["billing_schema_ready"] and row[field] and c.execute(f"SELECT 1 FROM organization_subscriptions WHERE {field}=? AND organization_id<>?", (row[field], row["oid"])).fetchone():
                report["conflicts"].append({"organization_id": row["oid"], "code": "already_assigned_" + field})
        if row["plan_key"] not in LEGACY or row["subscription_status"] not in STATES:
            report["conflicts"].append({"organization_id": row["oid"], "code": "unknown_plan_or_status"})
        if row["stripe_subscription_id"] and not row["stripe_customer_id"]:
            report["conflicts"].append({"organization_id": row["oid"], "code": "missing_customer"})
        if row["subscription_status"] in ("prueba", "trialing"):
            try:
                datetime.fromisoformat(row["trial_end"])
            except (ValueError, TypeError):
                report["conflicts"].append({"organization_id": row["oid"], "code": "invalid_trial_end"})
        report["subscriptions_to_associate"] += 1
        report["warnings"].append({"organization_id": row["oid"], "code": "preserve_legacy_allowances_and_reconcile_period"})
    return report


def associate(path, report_file=None):
    with closing(connect(path, readonly=True)) as c:
        report = inspect(c)
    if report_file is None:
        return report
    with Path(report_file).open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
    if report["conflicts"]:
        raise ValueError("Resolver conflictos del informe")
    if not report["billing_schema_ready"]:
        raise ValueError("Aplicar expansión con db-upgrade --billing antes de asociar")
    with closing(connect(path)) as c, c:
        c.execute("BEGIN IMMEDIATE")
        if getattr(c, "dialect", "sqlite") == "postgresql":
            c.execute("LOCK TABLE clientes,organizations,organization_subscriptions IN SHARE ROW EXCLUSIVE MODE")
        if inspect(c) != report:
            raise ValueError("La base cambió; generar otro informe")
        rows = c.execute("SELECT c.*,o.id AS oid FROM clientes c JOIN organizations o ON o.legacy_cliente_id=c.id").fetchall()
        for row in rows:
            if subscription(c, row["oid"]):
                continue
            status = STATES[row["subscription_status"]]
            if not row["activo"] and status in ("active", "trialing"):
                status = "past_due"
            provision(c, row["oid"], LEGACY[row["plan_key"]], status, row["stripe_customer_id"], row["stripe_subscription_id"], legacy=True)
            if status == "trialing":
                end_date = datetime.fromisoformat(row["trial_end"])
                # Legacy dates include the entire last trial day; never shorten the trial.
                if len(row["trial_end"]) == 10:
                    end_date += timedelta(days=1)
                end_date = end_date.replace(tzinfo=timezone.utc) if end_date.tzinfo is None else end_date.astimezone(timezone.utc)
                end = end_date.isoformat()
                c.execute("UPDATE organization_subscriptions SET current_period_end=? WHERE organization_id=?", (end, row["oid"]))
    return report


def install_cli(app, path):
    @app.cli.command("billing-migrate-legacy")
    @click.option("--apply", "apply_changes", is_flag=True)
    @click.option("--report-file", type=click.Path(dir_okay=False))
    def legacy(apply_changes, report_file):
        """Default: read-only dry run. --apply requires a new report file."""
        if apply_changes and not report_file:
            raise click.ClickException("--apply requiere --report-file")
        try:
            click.echo(json.dumps(associate(path(), report_file if apply_changes else None), indent=2))
        except (ValueError, OSError):
            raise click.ClickException("Asociación cancelada; revise el informe") from None
