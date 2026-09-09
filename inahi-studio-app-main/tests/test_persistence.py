"""Phase 2: disposable SQLite execution and offline PostgreSQL DDL validation."""
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from alembic import command

import app as inahi
from test_saas_core import SaaSFixture
from persistence.database import configured_url, connect, bind_parameters, make_engine, Connection
from persistence.migrations import migrate, preview, configuration
from persistence.models import metadata, RESOURCE_TABLES
from persistence.planning import dry_run
from saas_schema import enabled, upgrade


class MigrationTests(SaaSFixture):
    def migration(self, filename="before.json", reverse=False):
        return migrate(self.path.parent / filename, str(self.path), downgrade=reverse)

    def test_dry_run_counts_and_preserves_exact_bytes(self):
        before = self.path.read_bytes()
        report = dry_run(str(self.path))
        assert report["clients"] == report["organizations_to_create"] == report["users_to_create"] == report["memberships_to_create"] == 2
        assert report["conflicts"] == report["incomplete"] == []
        assert set(report["resources"].values()) == {2}
        assert self.path.read_bytes() == before
        assert self.hashed not in json.dumps(report)
        assert "a@example.com" not in json.dumps(report)

    def test_migration_preserves_all_legacy_resources_credentials_and_subscriptions(self):
        self.migration()
        assert self.legacy_snapshot() == self.before
        with self.db() as c:
            assert enabled(c)
            assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002_saas_core"
            assert c.execute("SELECT password_hash FROM users WHERE id=1").fetchone()[0] == self.hashed

    def test_adopt_phase_one_without_recreating_identities(self):
        upgrade(inahi.conectar)
        with self.db() as c:
            before = [tuple(r) for r in c.execute("SELECT * FROM users ORDER BY id")]
        assert self.migration()["users_to_create"] == 0
        with self.db() as c:
            assert [tuple(r) for r in c.execute("SELECT * FROM users ORDER BY id")] == before

    def test_logical_rollback_and_reupgrade_keep_ids_and_data(self):
        self.migration()
        self.migration("rollback.json", True)
        assert self.legacy_snapshot() == self.before
        with self.db() as c:
            assert not enabled(c)
            assert c.execute("SELECT count(*) FROM organizations").fetchone()[0] == 2
        self.migration("again.json")
        with self.db() as c:
            assert enabled(c)
            assert [r[0] for r in c.execute("SELECT id FROM users ORDER BY id")] == [1, 2]

    def test_rollback_refuses_activity_and_keeps_revision(self):
        self.migration()
        with self.db() as c:
            c.execute("INSERT INTO saas_audit(action,created_at) VALUES('new','2026-09-08')")
        with pytest.raises(ValueError):
            self.migration("rollback.json", True)
        with self.db() as c:
            assert enabled(c)
            assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002_saas_core"

    def test_report_exists_before_first_migration_write(self):
        original = command.upgrade
        def verify(cfg, target):
            assert json.loads((self.path.parent / "before.json").read_text())["clients"] == 2
            with self.db() as c:
                assert not enabled(c)
            return original(cfg, target)
        with patch("persistence.migrations.command.upgrade", side_effect=verify):
            self.migration()

    def test_report_collision_prevents_mutation(self):
        report = self.path.parent / "before.json"
        report.write_text("Keep this report")
        before = self.path.read_bytes()
        with pytest.raises(FileExistsError):
            self.migration()
        assert self.path.read_bytes() == before
        assert report.read_text() == "Keep this report"

    def test_duplicate_normalized_email_blocks_conversion_after_report(self):
        with self.db() as c:
            c.execute("UPDATE clientes SET correo=' A@example.com ' WHERE id=2")
        before = self.path.read_bytes()
        with pytest.raises(ValueError):
            self.migration()
        assert self.path.read_bytes() == before
        report = json.loads((self.path.parent / "before.json").read_text())
        assert report["conflicts"][0]["code"] == "duplicate_normalized_email"

    def test_plaintext_credentials_are_never_copied(self):
        with self.db() as c:
            c.execute("UPDATE clientes SET contrasena='plaintext-secret' WHERE id=1")
        report = dry_run(str(self.path))
        assert any(c["code"] == "unsupported_password_hash" for c in report["conflicts"])
        assert "plaintext-secret" not in json.dumps(report)
        with pytest.raises(ValueError):
            self.migration()

    def test_failure_rolls_back_ddl_and_customer_updates(self):
        from saas_schema import enroll_legacy
        def fail_after_one(c, cid):
            if cid == 2:
                raise RuntimeError("injected failure")
            return enroll_legacy(c, cid)
        with patch("saas_schema.enroll_legacy", side_effect=fail_after_one), pytest.raises(RuntimeError):
            self.migration()
        assert self.legacy_snapshot() == self.before
        with self.db() as c:
            assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='organizations'").fetchone()

    def test_database_url_sqlite_overrides_legacy_path(self):
        with patch.dict(os.environ, DATABASE_URL="sqlite:///" + str(self.path)):
            with closing(connect("does-not-exist.db")) as c:
                assert c.execute("SELECT count(*) FROM clientes").fetchone()[0] == 2

    def test_readonly_connection_rejects_writes(self):
        with closing(connect(str(self.path), readonly=True)) as c:
            with pytest.raises(sqlite3.OperationalError):
                c.execute("DELETE FROM clientes")

    def test_migrated_server_rejects_org_a_manipulated_org_b_resource_id(self):
        self.migration()
        self.login()
        own = self.client.get("/saas/resources/informes/1")
        other = self.client.get("/saas/resources/informes/2?organization_id=2")
        assert own.status_code == 200
        assert other.status_code == 404
        assert b"Secret B" not in other.data
        response = self.post("/saas/resources/informes/2", {"titulo": "intrusion", "contenido": "changed"})
        assert response.status_code in (403, 404)
        assert self.legacy_snapshot() == self.before

    def test_database_tenant_guard_and_foreign_keys_after_migration(self):
        self.migration()
        with self.db() as c:
            with pytest.raises(sqlite3.IntegrityError):
                c.execute("INSERT INTO informes(cliente_id,organization_id,titulo,contenido) VALUES(1,2,'x','x')")
            with pytest.raises(sqlite3.IntegrityError):
                c.execute("INSERT INTO organization_memberships(organization_id,user_id,role,status,created_at) VALUES(999,1,'viewer','active','2026-09-08')")

    def test_migration_is_idempotent(self):
        self.migration()
        before = self.legacy_snapshot()
        self.migration("second.json")
        assert self.legacy_snapshot() == before
        with self.db() as c:
            assert c.execute("SELECT count(*) FROM organization_memberships").fetchone()[0] == 2

    def test_adopt_phase_one_with_new_multi_membership_organization(self):
        from saas_core import create_organization
        upgrade(inahi.conectar)
        with self.db() as c:
            oid = create_organization(c, "Future", "future", "crecimiento", 1, inahi.PLANES_INFO)
        report = self.migration()
        assert report["users_to_create"] == 0
        with self.db() as c:
            assert c.execute("SELECT user_id FROM organization_memberships WHERE organization_id=?", (oid,)).fetchone()[0] == 1
            assert c.execute("SELECT count(*) FROM users").fetchone()[0] == 2

    def test_target_backfill_does_not_convert_existing_carrier_to_login_identity(self):
        from saas_core import create_organization
        from persistence.postgres_guards import backfill_sql
        upgrade(inahi.conectar)
        with self.db() as c:
            oid = create_organization(c, "Carrier", "carrier", "crecimiento", 1, inahi.PLANES_INFO)
            # Backfill DML is portable: execute it on real SQLite as well as compile for PG.
            for sql in backfill_sql():
                c.execute(sql)
            assert c.execute("SELECT count(*) FROM users").fetchone()[0] == 2
            assert c.execute("SELECT count(*) FROM organization_memberships WHERE organization_id=?", (oid,)).fetchone()[0] == 1

    def test_incomplete_data_reports_without_writing(self):
        with self.db() as c:
            c.execute("UPDATE clientes SET nombre='' WHERE id=1")
        before = self.path.read_bytes()
        report = dry_run(str(self.path))
        assert report["incomplete"] == [{"client_id": 1, "code": "name_or_email"}]
        assert self.path.read_bytes() == before

    def test_orphan_resource_blocks_before_ddl(self):
        with self.db() as c:
            c.execute("PRAGMA foreign_keys=OFF")
            c.execute("INSERT INTO informes(cliente_id,titulo,contenido) VALUES(999,'orphan','x')")
        with pytest.raises(ValueError):
            self.migration()
        with self.db() as c:
            assert not enabled(c)

    def test_target_core_constraints_execute_on_sqlite(self):
        self.migration()
        with self.db() as c:
            for sql in (
                "UPDATE users SET email='UPPER@example.com' WHERE id=1",
                "UPDATE organization_memberships SET role='superadmin' WHERE id=1",
                "INSERT INTO saas_audit(action,organization_id,created_at) VALUES('x',999,'2026-09-08')",
                "INSERT INTO organization_memberships(organization_id,user_id,role,status,created_at) VALUES(1,1,'viewer','active','2026-09-08')",
            ):
                with pytest.raises(sqlite3.IntegrityError):
                    c.execute(sql)

    def test_cli_requires_report_and_dry_run_does_not_change_database(self):
        runner = inahi.app.test_cli_runner()
        before = self.path.read_bytes()
        assert runner.invoke(args=["db-upgrade"]).exit_code != 0
        result = runner.invoke(args=["db-dry-run"])
        assert result.exit_code == 0
        assert json.loads(result.output)["clients"] == 2
        assert self.path.read_bytes() == before

    def test_old_commands_cannot_desynchronize_alembic_revision(self):
        self.migration()
        runner = inahi.app.test_cli_runner()
        for name in ("saas-upgrade", "saas-downgrade"):
            result = runner.invoke(args=[name])
            assert result.exit_code != 0
            assert "--report-file" in result.output
        with self.db() as c:
            assert enabled(c)
            assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002_saas_core"

    def test_concurrent_change_after_report_aborts_before_migration(self):
        from persistence.migrations import make_engine as original
        def concurrent(url):
            with self.db() as c:
                c.execute("INSERT INTO informes(cliente_id,titulo,contenido) VALUES(1,'new','new')")
            return original(url)
        with patch("persistence.migrations.make_engine", side_effect=concurrent), pytest.raises(ValueError, match="cambió"):
            self.migration()
        with self.db() as c:
            assert not enabled(c)
            assert c.execute("SELECT count(*) FROM informes").fetchone()[0] == 3


@pytest.fixture
def isolated_environment(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.setattr("socket.socket.connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No network")))


@pytest.mark.parametrize("value", ["postgresql://user:secret@localhost/local", "postgres://user:secret@localhost/local", "postgresql+psycopg://user:secret@localhost/local"])
def test_postgresql_url_uses_psycopg_without_connecting(monkeypatch, isolated_environment, value):
    monkeypatch.setenv("DATABASE_URL", value)
    assert configured_url().drivername == "postgresql+psycopg"


@pytest.mark.parametrize("value", ["mysql://user:secret@host/db", "postgresql:///missinghost", "sqlite://host/db", "not-a-url-secret"])
def test_invalid_database_configuration_hides_credentials(monkeypatch, isolated_environment, value):
    monkeypatch.setenv("DATABASE_URL", value)
    with pytest.raises(ValueError) as error:
        configured_url()
    assert "secret" not in str(error.value)


def test_configuration_requires_environment_or_explicit_legacy_path(isolated_environment):
    with pytest.raises(ValueError):
        configured_url()


def test_dry_run_absent_database_creates_nothing(tmp_path, isolated_environment):
    target = tmp_path / "absent" / "db.sqlite"
    assert preview(str(target))["clients"] == 0
    assert not target.parent.exists()


def test_empty_database_migration_is_explicit_and_reversible(tmp_path, isolated_environment):
    target = tmp_path / "empty.sqlite"
    migrate(tmp_path / "plan.json", str(target))
    with closing(connect(str(target))) as c:
        assert enabled(c)
        assert c.execute("SELECT count(*) FROM clientes").fetchone()[0] == 0
    migrate(tmp_path / "reverse.json", str(target), downgrade=True)
    with closing(connect(str(target))) as c:
        assert not enabled(c)


def test_qmark_translation_never_interpolates_values():
    sql, params = bind_parameters("SELECT '?' AS literal, ? AS value, 'it''s ?' AS quoted", ["'; DELETE FROM clientes; --"])
    assert sql == "SELECT '?' AS literal, :p0 AS value, 'it''s ?' AS quoted"
    assert params == {"p0": "'; DELETE FROM clientes; --"}
    with pytest.raises(ValueError):
        bind_parameters("SELECT ?", [])


def test_sqlalchemy_bridge_row_mapping_and_transaction(tmp_path):
    engine = make_engine(sa.URL.create("sqlite", database=str(tmp_path / "bridge.db")))
    try:
        with engine.begin() as bind:
            c = Connection(bind, owned=False)
            c.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY,name TEXT)")
            assert c.execute("INSERT INTO sample(name) VALUES(?)", ("safe '?'",)).lastrowid == 1
            row = c.execute("SELECT * FROM sample").fetchone()
            assert row["name"] == row[1] == "safe '?'"
    finally:
        engine.dispose()


@pytest.mark.parametrize("name", RESOURCE_TABLES)
def test_postgresql_schema_has_composite_tenant_fk_and_index(name):
    table = metadata.tables[name]
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert f"fk_{name}_tenant_account" in ddl
    assert "FOREIGN KEY(organization_id, cliente_id) REFERENCES clientes (organization_id, id)" in ddl
    assert any(tuple(c.name for c in index.columns) == ("organization_id",) for index in table.indexes)


def test_postgresql_schema_identity_timestamp_and_security_constraints():
    ddl = "\n".join(str(CreateTable(metadata.tables[n]).compile(dialect=postgresql.dialect())) for n in ("organizations", "users", "organization_memberships", "saas_audit"))
    for expected in ("GENERATED BY DEFAULT AS IDENTITY", "TIMESTAMP WITH TIME ZONE", "UNIQUE (email)", "UNIQUE (slug)", "UNIQUE (organization_id, user_id)", "'viewer'", "normalized_email", "REFERENCES organizations (id)", "REFERENCES users (id)"):
        assert expected in ddl


def test_postgresql_alembic_offline_schema_without_database_connection(monkeypatch, isolated_environment):
    monkeypatch.setenv("DATABASE_URL", "postgresql://offline@localhost/schema_preview")
    output = io.StringIO()
    cfg = configuration()
    cfg.output_buffer = output
    command.upgrade(cfg, "head", sql=True)
    ddl = output.getvalue()
    for expected in ("CREATE TABLE organizations", "CREATE TABLE users", "CREATE TABLE organization_memberships", "inahi_tenant_guard", "IS DISTINCT FROM", "0002_saas_core", "COMMIT;"):
        assert expected in ddl
    for forbidden in ("PRAGMA", "INSERT OR IGNORE", "COLLATE NOCASE", "BEGIN IMMEDIATE"):
        assert forbidden not in ddl
    assert ddl.count("END; $$") == 4


def test_online_alembic_cannot_bypass_report(monkeypatch, isolated_environment):
    with pytest.raises(RuntimeError, match="report-file"):
        command.upgrade(configuration(), "head")


def test_postgresql_adapter_returns_identity_and_binds_payload():
    from unittest.mock import Mock
    bind = Mock()
    bind.dialect.name = "postgresql"
    result = bind.execute.return_value
    result.rowcount = 1
    result.fetchone.return_value = (47,)
    c = Connection(bind, owned=False)
    payload = "untrusted '?'; DELETE FROM users; --"
    inserted = c.execute("INSERT INTO informes(cliente_id,titulo,contenido) VALUES(?,?,?)", (1, "title", payload))
    assert inserted.lastrowid == 47
    statement, params = bind.execute.call_args.args
    assert str(statement).endswith("RETURNING id")
    assert payload not in str(statement)
    assert params["p2"] == payload


def test_postgresql_engine_is_lazy_and_does_not_connect(isolated_environment):
    engine = make_engine(sa.URL.create("postgresql+psycopg", host="localhost", database="offline"))
    try:
        assert engine.dialect.name == "postgresql"
        assert engine.hide_parameters is True
    finally:
        engine.dispose()
