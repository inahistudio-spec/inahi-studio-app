"""Exercise the actual demo bootstrap and real password/CSRF login on its temporary DB."""
import os
from pathlib import Path
from unittest.mock import patch

import app as inahi
from devtools import run_workspace_demo
from werkzeug.security import check_password_hash


def test_demo_qa_real_login_dashboard_and_tenant_isolation():
    original_db = inahi.DB
    temporary_paths = []

    def check_running_demo(app, port, database_path, password):
        assert app is inahi.app and port == 5055
        assert str(database_path) == inahi.DB and password == "Legacy-password-123"
        from sqlalchemy.engine import make_url
        assert make_url(os.environ["DATABASE_URL"]).get_backend_name() == "sqlite"
        assert Path(make_url(os.environ["DATABASE_URL"]).database) == database_path
        assert inahi.DB != original_db
        temporary_paths.append(Path(inahi.DB))
        client = inahi.app.test_client()
        entry = client.get("/saas/dashboard")
        assert entry.status_code == 302 and entry.location.endswith("/cliente/acceso")
        client.get(entry.location)
        with client.session_transaction() as session:
            token = session["csrf_token"]
        bad = client.post("/cliente/acceso", data={"correo": "qa@example.com", "contrasena": "wrong-password", "csrf_token": token})
        assert not bad.location or not bad.location.endswith("/saas/dashboard")
        with client.session_transaction() as session:
            assert "user_id" not in session
        response = client.post("/cliente/acceso", data={"correo": "qa@example.com", "contrasena": "Legacy-password-123", "csrf_token": token})
        assert response.status_code == 302
        assert response.location.endswith("/saas/dashboard")
        dashboard = client.get(response.location)
        assert dashboard.status_code == 200
        assert "Estudio Norte" in dashboard.get_data(as_text=True)
        assert "Empresa B" not in dashboard.get_data(as_text=True)
        with client.session_transaction() as session:
            assert session["organization_id"] == 1 and session["user_id"] == 1
        with inahi.conectar() as c:
            row = c.execute("SELECT password_hash FROM users WHERE email='qa@example.com'").fetchone()
            assert row and row[0] != "Legacy-password-123"
            assert check_password_hash(row[0], "Legacy-password-123")
            assert c.execute("SELECT name FROM organizations WHERE id=1").fetchone()[0] == "Estudio Norte"
            assert c.execute("SELECT role FROM organization_memberships WHERE user_id=1 AND organization_id=1").fetchone()[0] == "owner"
        assert client.get("/saas/informes/2").status_code == 404
        assert client.get("/saas/informes/1").status_code == 200

    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://unused:unused@invalid.example/never_connect"}), \
         patch("sys.argv", ["run_workspace_demo.py", "--port", "5055"]), \
         patch.object(run_workspace_demo, "serve_demo", side_effect=check_running_demo) as run:
        run_workspace_demo.main()
        run.assert_called_once()
    assert inahi.DB == original_db
    assert temporary_paths and not temporary_paths[0].exists()
