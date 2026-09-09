"""Local visual preview using the existing disposable A/B test fixture.

Never opens the application's configured database. No outgoing network is allowed.
Run with the existing app venv; fixture data disappears when this process stops.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import sys
from unittest.mock import patch
from werkzeug.serving import ThreadedWSGIServer

ROOT = Path(__file__).resolve().parents[1]
DEMO_EMAIL = "qa@example.com"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


class ExclusiveDemoServer(ThreadedWSGIServer):
    """Windows SO_REUSEADDR can let two different demos serve the same port."""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve_demo(app, port, database_path, password):
    # Bind before announcing readiness. No Flask.run(), dotenv loading or reloader.
    try:
        server = ExclusiveDemoServer("127.0.0.1", port, app)
    except SystemExit:
        raise SystemExit(f"DEMO NO INICIADA: puerto {port} no disponible. Deten la demo anterior o elige otro puerto.") from None
    with server:
        print("DEMO_RUNTIME " + json.dumps({"pid": os.getpid(), "parent_pid": os.getppid(), "database": str(database_path),
              "database_url": os.environ["DATABASE_URL"], "user": DEMO_EMAIL,
              "organization": "Estudio Norte", "hash_format": app.config["DEMO_HASH_FORMAT"]}), flush=True)
        print(f"LOCAL DEMO: http://127.0.0.1:{port}/saas/dashboard", flush=True)
        print(f"Disposable demo account: {DEMO_EMAIL} / {password}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5055)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a local unprivileged port")
    # Keep only temporary-directory locations, never ambient application credentials.
    clean = {key: os.environ[key] for key in ("TMP", "TEMP", "TMPDIR") if key in os.environ}
    with patch.dict(os.environ, clean, clear=True):
        prepare_demo(args.port)


def prepare_demo(port):
    from test_saas_core import SaaSFixture, inahi
    from persistence.migrations import migrate
    from billing.repository import provision
    from saas_core import create_user, add_membership
    from sqlalchemy.engine import URL
    from werkzeug.security import check_password_hash
    fixture = SaaSFixture()
    fixture.setUp()  # Own TemporaryDirectory; clears environment and blocks socket.connect.
    try:
        # DATABASE_URL has precedence over app.DB; pin both to the same owned file.
        os.environ["DATABASE_URL"] = URL.create("sqlite", database=str(fixture.path)).render_as_string(hide_password=False)
        os.environ["DATABASE_PATH"] = str(fixture.path)
        os.environ["FLASK_SKIP_DOTENV"] = "1"
        migrate(fixture.path.parent / "visual-demo.json", str(fixture.path), crm=True)
        with fixture.db() as c:
            provision(c, 1, "PROFESSIONAL", "active")
            provision(c, 2, "STARTER", "active")
            c.execute("UPDATE organizations SET name='Estudio Norte',slug='estudio-norte-demo' WHERE id=1")
            # Change only the disposable fixture's identity, keeping its password hash.
            c.execute("UPDATE users SET name='Alex',email=? WHERE id=1", (DEMO_EMAIL,))
            c.execute("UPDATE clientes SET nombre='Estudio Norte',correo=? WHERE id=1", (DEMO_EMAIL,))
            c.execute("UPDATE solicitudes SET asunto='Revisar la propuesta comercial',descripcion='Datos ficticios: preparar la propuesta de septiembre.',fecha='2026-09-09' WHERE organization_id=1")
            c.execute("UPDATE diagnosticos SET objetivos='Mejorar la captacion y dar continuidad al contenido.',puntuacion=72,web=3,google=4,redes=3,resenas=4 WHERE organization_id=1")
            c.execute("UPDATE informes SET titulo='Perspectiva comercial de septiembre',contenido='Informe ficticio para revisar el diseno del panel. No representa resultados reales.' WHERE organization_id=1")
            for period, contacts, sales in (("2026-04",18,3),("2026-05",26,5),("2026-06",22,4),("2026-07",35,7),("2026-08",31,6)):
                c.execute("INSERT INTO resultados_mensuales(cliente_id,organization_id,periodo,contactos,ventas,ingresos,informe,creado) VALUES(1,1,?,?,?,?,?,?)", (period,contacts,sales,sales*120,'{}','2026-09-09'))
            c.execute("UPDATE resultados_mensuales SET contactos=42,ventas=9,ingresos=1080 WHERE organization_id=1 AND periodo='2026-09'")
            for name, role in (("Elena", "admin"), ("Marcos", "manager"), ("Lucia", "member"), ("Hugo", "viewer")):
                uid = create_user(c, role + "@demo.invalid", secrets.token_urlsafe(32), name)
                add_membership(c, 1, uid, role)
        from devtools.demo_crm import seed
        with fixture.db() as c:
            seed(c)
        with fixture.db() as c:
            actual = Path(c.execute("PRAGMA database_list").fetchone()[2]).resolve()
            if actual != fixture.path.resolve():
                raise RuntimeError("Demo database mismatch; server not started")
            hashed = c.execute("SELECT password_hash FROM users WHERE email=?", (DEMO_EMAIL,)).fetchone()[0]
            if not check_password_hash(hashed, fixture.password):
                raise RuntimeError("Demo password verification failed; server not started")
            inahi.app.config["DEMO_HASH_FORMAT"] = hashed.split("$", 1)[0]
        inahi.app.config.update(SAAS_DEMO=True, SECRET_KEY=secrets.token_hex(32), SESSION_COOKIE_NAME=f"inahi_demo_{port}")
        serve_demo(inahi.app, port, fixture.path, fixture.password)
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    main()
