"""Actual demo subprocess + TCP HTTP, including the Windows duplicate-port failure."""
import http.cookiejar
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "devtools" / "run_workspace_demo.py"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_client():
    # Local test traffic must not use ambient HTTP proxies.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect())


def post(client, url, fields):
    return client.open(url, urllib.parse.urlencode(fields).encode(), timeout=5)


@pytest.fixture(scope="module")
def real_demo(tmp_path_factory):
    directory = tmp_path_factory.mktemp("real-demo")
    decoy = directory / "unrelated.db"
    with sqlite3.connect(decoy) as c:
        c.execute("CREATE TABLE sentinel(value TEXT)")
        c.execute("INSERT INTO sentinel VALUES('do not touch')")
    before = decoy.read_bytes()
    from sqlalchemy.engine import URL
    decoy_url = URL.create("sqlite", database=str(decoy)).render_as_string(hide_password=False)
    (directory / ".env").write_text(f"DATABASE_URL={decoy_url}\nFLASK_ENV=production\n", encoding="utf-8")
    env = {**os.environ, "DATABASE_URL": decoy_url, "DATABASE_PATH": str(decoy),
           "FLASK_ENV": "production", "FLASK_RUN_FROM_CLI": "true",
           "COPILOT_PROVIDER": "openai", "COPILOT_ALLOW_EXTERNAL": "true",
           "COPILOT_API_KEY": "not-a-real-test-key", "PYTHONIOENCODING": "utf-8",
           "TMP": str(directory), "TEMP": str(directory), "TMPDIR": str(directory)}
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    log_path = directory / "server.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, str(SCRIPT), "--port", str(port)], cwd=directory,
            env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            root = f"http://127.0.0.1:{port}"
            client = http_client()
            deadline = time.monotonic() + 40
            while True:
                if process.poll() is not None:
                    pytest.fail("Demo exited before HTTP ready: " + log_path.read_text(encoding="utf-8"))
                try:
                    with client.open(root + "/salud", timeout=.5) as response:
                        assert response.status == 200
                    break
                except (urllib.error.URLError, TimeoutError):
                    if time.monotonic() > deadline:
                        pytest.fail("Demo did not become HTTP ready")
                    time.sleep(.1)
            output = log_path.read_text(encoding="utf-8")
            runtime = json.loads(next(line.removeprefix("DEMO_RUNTIME ") for line in output.splitlines() if line.startswith("DEMO_RUNTIME ")))
            # Windows venv python.exe launches its base interpreter as a child.
            assert runtime["pid"] == process.pid or runtime["parent_pid"] == process.pid
            database = Path(runtime["database"]).resolve()
            assert database.is_relative_to(directory.resolve()) and database != decoy.resolve()
            from sqlalchemy.engine import make_url
            assert Path(make_url(runtime["database_url"]).database).resolve() == database
            assert runtime["hash_format"] == "pbkdf2:sha256:1000"
            yield root, port, runtime, directory, env
            assert decoy.read_bytes() == before
        finally:
            # Only the process this test spawned, with all its files inside our own tmp dir.
            if os.name == "nt" and process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
            else:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def test_real_demo_process_password_login_database_and_scope(real_demo):
    root, port, runtime, directory, env = real_demo
    client = http_client()
    with pytest.raises(urllib.error.HTTPError) as entry:
        client.open(root + "/saas/dashboard", timeout=5)
    assert entry.value.code == 302 and entry.value.headers["Location"] == "/cliente/acceso"
    with client.open(root + "/cliente/acceso", timeout=5) as response:
        html = response.read().decode()
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    with post(client, root + "/cliente/acceso", {"correo": "qa@example.com", "contrasena": "incorrect", "csrf_token": token}) as response:
        assert response.status == 200 and "no son correctos" in response.read().decode()
    with pytest.raises(urllib.error.HTTPError) as login:
        post(client, root + "/cliente/acceso", {"correo": "qa@example.com", "contrasena": "Legacy-password-123", "csrf_token": token})
    assert login.value.code == 302 and login.value.headers["Location"] == "/saas/dashboard"
    assert f"inahi_demo_{port}=" in login.value.headers["Set-Cookie"]
    with client.open(root + "/saas/dashboard", timeout=5) as response:
        html = response.read().decode()
        assert response.status == 200 and "Estudio Norte" in html and "Empresa B" not in html
    with pytest.raises(urllib.error.HTTPError) as foreign:
        client.open(root + "/saas/informes/2", timeout=5)
    assert foreign.value.code == 404
    with client.open(root + "/saas/copilot", timeout=5) as response:
        token = re.search(r'name="csrf_token" value="([^"]+)"', response.read().decode()).group(1)
    with post(client, root + "/saas/copilot/ask", {"csrf_token": token, "feature": "business_overview", "question": "Prioridades de esta semana", "request_key": str(uuid.uuid4())}) as response:
        answer = json.loads(response.read())
        assert any("reglas locales" in item for item in answer["limitations"])
    # Inspect only the explicitly reported disposable file, never an app/production database.
    with sqlite3.connect(runtime["database"]) as c:
        assert c.execute("SELECT count(*) FROM users WHERE email='qa@example.com'").fetchone()[0] == 1
        assert c.execute("SELECT last_login_at FROM users WHERE email='qa@example.com'").fetchone()[0]
        assert c.execute("SELECT provider FROM copilot_usage").fetchone()[0] == "local"


def test_real_demo_refuses_duplicate_port_before_announcing_credentials(real_demo):
    root, port, runtime, directory, env = real_demo
    with socket.socket() as duplicate:
        duplicate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with pytest.raises(OSError):
            duplicate.bind(("127.0.0.1", port))
    second = subprocess.run([sys.executable, str(SCRIPT), "--port", str(port)], cwd=directory,
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert second.returncode != 0
    assert "DEMO NO INICIADA" in second.stderr
    assert "LOCAL DEMO:" not in second.stdout
    assert "Disposable demo account:" not in second.stdout
    with http_client().open(root + "/salud", timeout=5) as response:
        assert response.status == 200
