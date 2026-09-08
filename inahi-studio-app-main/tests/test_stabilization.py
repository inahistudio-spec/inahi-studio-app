"""Phase 0.5: temporary databases only; no provider calls or system setup."""

import gc
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import patch

# Protect the first import too, before setUp has selected a temporary database.
with patch("sqlite3.connect", side_effect=AssertionError("DB access during test discovery")), \
     patch("os.makedirs", side_effect=AssertionError("Directory creation during test discovery")):
    import app as inahi
from billing_webhooks import procesar_evento_stripe


class StabilizationTests(unittest.TestCase):
    def setUp(self):
        self.child_environment = {key: value for key, value in os.environ.items()
                                  if key.upper() in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")}
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.addCleanup(gc.collect)
        self.directory = Path(temporary.name)
        self.database = self.directory / "test.db"
        for mock in (
            patch.object(inahi, "DB", str(self.database)),
            patch.object(inahi, "DB_DIR", str(self.directory)),
            patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "test-webhook-secret"}, clear=True),
            patch("socket.socket.connect", side_effect=OSError("Network disabled in tests")),
            patch.dict(inahi.app.config, TESTING=True, SECRET_KEY="test-secret"),
        ):
            mock.start()
            self.addCleanup(mock.stop)
        inahi.inicializar_base_datos()
        with closing(inahi.conectar()) as c, c:
            # More than five trial accounts expose the former campaign updates.
            for cid in range(1, 8):
                c.execute(
                    """INSERT INTO clientes(id,nombre,correo,contrasena,plan,activo,
                       plan_key,subscription_status,trial_slot,trial_queries_used,
                       stripe_subscription_id) VALUES(?,?,?,?,?,1,'crecimiento','prueba',0,7,?)""",
                    (cid, f"Cliente {cid}", f"{cid}@example.com", "preserved-hash",
                     "Plan Crecimiento", f"sub_{cid}"),
                )
            c.execute("INSERT INTO solicitudes(cliente_id,asunto,descripcion) VALUES(1,'Keep','Keep')")
        self.client = inahi.app.test_client()

    def snapshot(self):
        with closing(inahi.conectar()) as c:
            return "\n".join(c.iterdump())

    def import_in_subprocess(self, database):
        environment = dict(self.child_environment)
        environment.update(DATABASE_PATH=str(database), SECRET_KEY="import-test-secret",
                           PYTHONDONTWRITEBYTECODE="1")
        # The child must not even attempt DB access or directory creation.
        script = """
from unittest.mock import patch
import importlib
with patch('sqlite3.connect', side_effect=AssertionError('DB access on import')), \
     patch('os.makedirs', side_effect=AssertionError('mkdir on import')):
    import app
    importlib.reload(app)
    assert app.app.test_client().get('/salud').status_code == 200
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script], env=environment,
            cwd=Path(inahi.__file__).parent, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_import_and_application_creation_preserve_all_data_with_or_without_marker(self):
        for marker in (False, True):
            with self.subTest(campaign_marker=marker):
                if marker:
                    with closing(inahi.conectar()) as c, c:
                        c.execute("CREATE TABLE app_migrations(nombre TEXT PRIMARY KEY,aplicada TEXT)")
                        c.execute("INSERT INTO app_migrations VALUES(?,?)",
                                  (inahi.CAMPAIGN_RESET_MIGRATION, "2026-09-01"))
                before = self.snapshot()
                digest = hashlib.sha256(self.database.read_bytes()).digest()
                self.import_in_subprocess(self.database)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(hashlib.sha256(self.database.read_bytes()).digest(), digest)

    def test_import_does_not_create_missing_database_or_parent(self):
        missing = self.directory / "absent" / "data.db"
        self.import_in_subprocess(missing)
        self.assertFalse(missing.parent.exists())

    def test_import_does_not_upgrade_legacy_schema(self):
        legacy = self.directory / "legacy.db"
        with closing(sqlite3.connect(legacy)) as c, c:
            c.execute("CREATE TABLE clientes(id INTEGER PRIMARY KEY,nombre TEXT)")
            c.execute("INSERT INTO clientes VALUES(1,'Preservar')")
        before = legacy.read_bytes()
        self.import_in_subprocess(legacy)
        self.assertEqual(legacy.read_bytes(), before)

    def test_explicit_preparation_is_idempotent_and_preserves_accounts(self):
        before = self.snapshot()
        for _ in range(2):
            result = inahi.app.test_cli_runner().invoke(args=["init-db"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(self.snapshot(), before)

    def test_explicit_preparation_adds_schema_without_overwriting_legacy_values(self):
        legacy = self.directory / "older.db"
        with closing(sqlite3.connect(legacy)) as c, c:
            c.execute("""CREATE TABLE clientes(id INTEGER PRIMARY KEY,nombre TEXT NOT NULL,
                       correo TEXT UNIQUE NOT NULL,contrasena TEXT NOT NULL,
                       plan TEXT NOT NULL,activo INTEGER NOT NULL DEFAULT 1)""")
            c.execute("INSERT INTO clientes VALUES(1,'Keep','keep@example.com','hash','Custom',0)")
        with patch.object(inahi, "DB", str(legacy)):
            inahi.inicializar_base_datos()
            with closing(inahi.conectar()) as c:
                row = c.execute("SELECT id,nombre,correo,contrasena,plan,activo FROM clientes").fetchone()
                self.assertEqual(tuple(row), (1, "Keep", "keep@example.com", "hash", "Custom", 0))

    def test_csrf_missing_empty_incorrect_and_unicode_are_rejected(self):
        for expected, submitted in ((None, None), ("", ""), (None, "forged"),
                                    ("valid", None), ("valid", ""), ("valid", "wrong"),
                                    ("valid", "á")):
            with self.subTest(expected=expected, submitted=submitted):
                client = inahi.app.test_client()
                with client.session_transaction() as session:
                    if expected is not None:
                        session["csrf_token"] = expected
                response = client.post("/", data={} if submitted is None else {"csrf_token": submitted})
                self.assertEqual(response.status_code, 400)

    def test_current_form_token_is_accepted(self):
        self.assertEqual(self.client.get("/cliente/acceso").status_code, 200)
        with self.client.session_transaction() as session:
            token = session["csrf_token"]
        with patch.object(inahi, "permitir_intento", return_value=True):
            response = self.client.post("/cliente/acceso", data={"csrf_token": token})
        self.assertEqual(response.status_code, 200)

    def test_other_mutating_methods_require_csrf(self):
        for method in ("PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                self.assertEqual(self.client.open("/", method=method).status_code, 400)

    def event(self, event_id="evt_test", kind="checkout.session.completed"):
        obj = {"client_reference_id": "1", "metadata": {"plan_key": "crecimiento"},
               "customer": "cus_1", "subscription": "sub_1"}
        if kind.startswith("customer.subscription."):
            obj = {"id": "sub_1", "status": "canceled" if kind.endswith("deleted") else "active",
                   "items": {"data": []}}
        return {"id": event_id, "type": kind, "data": {"object": obj}}

    def process(self, event):
        return procesar_evento_stripe(event, inahi.conectar, inahi.PLANES_INFO,
                                     inahi.nombre_plan, inahi.plan_por_precio)

    def post_signed(self, event, signature=None, timestamp=None, tamper=False):
        import stripe
        payload = json.dumps(event).encode()
        timestamp = int(time.time()) if timestamp is None else timestamp
        digest = hmac.new(b"test-webhook-secret", str(timestamp).encode() + b"." + payload,
                          hashlib.sha256).hexdigest()
        header = f"t={timestamp},v1={digest}" if signature is None else signature
        if tamper:
            payload += b" "
        with patch.object(inahi, "stripe_cliente", return_value=stripe):
            return self.client.post("/stripe/webhook", data=payload,
                                    content_type="application/json", headers={"Stripe-Signature": header})

    def test_real_signature_validation_and_webhook_csrf_exemption(self):
        response = self.post_signed(self.event())
        self.assertEqual(response.status_code, 200)
        with closing(inahi.conectar()) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM stripe_webhook_events").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT subscription_status FROM clientes WHERE id=1").fetchone()[0], "activa")

    def test_bad_missing_expired_and_tampered_signatures_do_not_write(self):
        before = self.snapshot()
        for options in ({"signature": ""}, {"signature": "invalid"},
                        {"timestamp": int(time.time()) - 1000}, {"tamper": True}):
            with self.subTest(options=options):
                self.assertEqual(self.post_signed(self.event(), **options).status_code, 400)
                self.assertEqual(self.snapshot(), before)

    def test_missing_webhook_configuration_fails_closed(self):
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": ""}), patch.object(inahi, "stripe_cliente", return_value=None):
            self.assertEqual(self.client.post("/stripe/webhook", data=b"{}").status_code, 503)

    def test_each_supported_event_is_applied_once(self):
        for index, kind in enumerate(("checkout.session.completed", "customer.subscription.updated",
                                      "customer.subscription.deleted")):
            with self.subTest(kind=kind):
                event = self.event(f"evt_{index}", kind)
                self.assertEqual(self.post_signed(event).status_code, 200)
                with closing(inahi.conectar()) as c, c:
                    status = c.execute("SELECT subscription_status FROM clientes WHERE id=1").fetchone()[0]
                    self.assertEqual(status, "activa" if index == 0 else "active" if index == 1 else "canceled")
                    c.execute("UPDATE clientes SET activo=0,subscription_status='manual' WHERE id=1")
                self.assertEqual(self.post_signed(event).status_code, 200)
                with closing(inahi.conectar()) as c:
                    self.assertEqual(c.execute("SELECT activo FROM clientes WHERE id=1").fetchone()[0], 0)
                    self.assertEqual(c.execute("SELECT subscription_status FROM clientes WHERE id=1").fetchone()[0], "manual")
                    self.assertEqual(c.execute("SELECT COUNT(*) FROM stripe_webhook_events WHERE event_id=?",
                                               (event["id"],)).fetchone()[0], 1)

    def test_concurrent_deliveries_have_one_winner(self):
        barrier = threading.Barrier(2)
        def deliver():
            barrier.wait(timeout=10)
            return self.process(self.event())
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: deliver(), range(2)))
        self.assertEqual(sorted(results), [False, True])

    def test_failed_effect_rolls_back_event_and_retry_succeeds(self):
        with closing(inahi.conectar()) as c, c:
            c.execute("""CREATE TRIGGER fail_update BEFORE UPDATE ON clientes
                       BEGIN SELECT RAISE(ABORT,'simulated failure'); END""")
        before = self.snapshot()
        self.assertEqual(self.post_signed(self.event()).status_code, 503)
        self.assertEqual(self.snapshot(), before)
        with closing(inahi.conectar()) as c, c:
            c.execute("DROP TRIGGER fail_update")
        self.assertEqual(self.post_signed(self.event()).status_code, 200)

    def test_missing_ledger_returns_retryable_error_without_creating_schema(self):
        with closing(inahi.conectar()) as c, c:
            c.execute("DROP TABLE stripe_webhook_events")
        before = self.snapshot()
        self.assertEqual(self.post_signed(self.event()).status_code, 503)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_events_do_not_mutate_customers_or_record_success(self):
        events = [self.event(), self.event(kind="customer.subscription.updated")]
        events[0].pop("id")
        events[1]["data"]["object"]["id"] = ""
        before = self.snapshot()
        for event in events:
            with self.subTest(event=event):
                self.assertEqual(self.post_signed(event).status_code, 400)
                self.assertEqual(self.snapshot(), before)

    def test_unknown_event_is_acknowledged_without_customer_changes(self):
        event = {"id": "evt_unknown", "type": "future.event", "data": {"object": {}}}
        self.assertTrue(self.process(event))
        self.assertFalse(self.process(event))
        with closing(inahi.conectar()) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM clientes WHERE subscription_status='prueba'").fetchone()[0], 7)


if __name__ == "__main__":
    unittest.main()
