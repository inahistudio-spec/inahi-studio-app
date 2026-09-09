"""Explicit, reported Alembic operations. Never invoked by application startup."""
from contextlib import closing
import json
import sqlite3
from pathlib import Path
import click
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from persistence.database import configured_url, make_engine, Connection
from persistence.planning import dry_run, inspect_legacy, require_clean

ROOT = Path(__file__).resolve().parent.parent


def configuration():
    return Config(str(ROOT / "alembic.ini"))


def preview(legacy_path=None):
    url = configured_url(legacy_path)
    if url.get_backend_name() == "sqlite" and url.database != ":memory:" and not Path(url.database).exists():
        return {"mode": "dry-run", "empty_database": True, "clients": 0,
                "organizations_to_create": 0, "users_to_create": 0,
                "memberships_to_create": 0, "resources": {}, "conflicts": [], "incomplete": []}
    return dry_run(legacy_path)


def migrate(report_file, legacy_path=None, downgrade=False, billing=False, copilot=False):
    """Persist an exclusive preflight report, recheck under transaction, then migrate."""
    report = preview(legacy_path)
    report["operation"] = "downgrade" if downgrade else "upgrade"
    report["target_revision"] = ("0002_saas_core" if billing else "0001_legacy_baseline") if downgrade else ("0003_org_billing" if billing else "0002_saas_core")
    if copilot:
        report["target_revision"] = "0003_org_billing" if downgrade else "0004_copilot"
    # Exclusive creation prevents accidentally overwriting an existing report or DB.
    with Path(report_file).open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, ensure_ascii=False)
        output.write("\n")
    require_clean(report)
    engine = make_engine(configured_url(legacy_path))
    try:
        with engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                # Serialize administrative migration runs, then prevent concurrent legacy writes.
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(731904220)")
                from persistence.models import metadata
                present = set(sa.inspect(connection).get_table_names())
                for name in sorted(present & set(metadata.tables)):
                    connection.exec_driver_sql(f'LOCK TABLE "{name}" IN SHARE ROW EXCLUSIVE MODE')
            bridge = Connection(connection, owned=False)
            # The inspector supports both dialects; the report stays read-only.
            current = inspect_legacy(bridge)
            require_clean(current)
            if any(current[key] != report[key] for key in ("clients", "organizations_to_create", "users_to_create", "memberships_to_create", "resources")):
                raise ValueError("La base cambió desde el informe; generar un informe nuevo")
            cfg = configuration()
            cfg.attributes["connection"] = connection
            if downgrade:
                command.downgrade(cfg, report["target_revision"])
            else:
                command.upgrade(cfg, report["target_revision"])
    finally:
        engine.dispose()
    return report


def install_cli(app, legacy_path):
    @app.cli.command("db-dry-run")
    def db_dry_run():
        """Inventory only. Does not create or alter a database."""
        try:
            click.echo(json.dumps(preview(legacy_path()), ensure_ascii=False, indent=2))
        except (ValueError, sqlite3.Error, sa.exc.SQLAlchemyError):
            raise click.ClickException("No se pudo inspeccionar la base configurada") from None

    def execute(report_file, reverse, billing=False, copilot=False):
        try:
            report = migrate(report_file, legacy_path(), downgrade=reverse, billing=billing, copilot=copilot)
        except (ValueError, OSError, sqlite3.Error, sa.exc.SQLAlchemyError):
            raise click.ClickException("Operación cancelada; revise el informe, configuración y estado local") from None
        click.echo(f"Operación completada. Clientes conservados: {report['clients']}. Informe: {report_file}")

    @app.cli.command("db-upgrade")
    @click.option("--report-file", required=True, type=click.Path(dir_okay=False))
    @click.option("--billing", is_flag=True, help="Incluir expansión explícita Fase 3, sin asociar suscripciones legacy.")
    @click.option("--copilot", is_flag=True, help="Include explicit Phase 4 expansion.")
    def db_upgrade(report_file, billing, copilot):
        """Explicit additive migration after saving the preflight report."""
        execute(report_file, False, billing, copilot)

    @app.cli.command("db-downgrade")
    @click.option("--report-file", required=True, type=click.Path(dir_okay=False))
    @click.option("--billing", is_flag=True, help="Revertir solo billing a Fase 2 conservando SaaS.")
    @click.option("--copilot", is_flag=True, help="Disable only Copilot, preserving usage history.")
    def db_downgrade(report_file, billing, copilot):
        """Guarded logical rollback; keeps all tables and customer data."""
        execute(report_file, True, billing, copilot)
