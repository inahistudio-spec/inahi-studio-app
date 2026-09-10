"""New Phase 7 demo in its real subprocess, isolated from ambient credentials."""
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
import uuid
import pytest
from test_workspace_demo_process import http_client,post


def test_synthetic_ai_demo_real_login_and_no_external_provider(tmp_path):
    decoy=tmp_path/'decoy.sqlite'
    with sqlite3.connect(decoy) as c:
        c.execute('CREATE TABLE sentinel(value TEXT)')
        c.execute("INSERT INTO sentinel VALUES('untouched')")
    before=decoy.read_bytes()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0))
        port=probe.getsockname()[1]
    script=Path(__file__).resolve().parents[1]/'devtools'/'run_ai_staging_demo.py'
    env={**os.environ,'DATABASE_URL':'sqlite:///'+str(decoy),'APP_ENV':'production',
         'COPILOT_EXTERNAL_ENABLED':'true','COPILOT_ALLOW_EXTERNAL':'true','COPILOT_PROVIDER':'openai',
         'COPILOT_API_KEY':'not-a-real-key','PYTHONIOENCODING':'utf-8','TEMP':str(tmp_path),'TMP':str(tmp_path)}
    with (tmp_path/'demo.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen([sys.executable,str(script),'--port',str(port),'--stop-on-stdin'],cwd=tmp_path,env=env,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            client=http_client()
            root=f'http://127.0.0.1:{port}'
            deadline=time.monotonic()+40
            while True:
                assert process.poll() is None,(tmp_path/'demo.log').read_text(encoding='utf-8')
                try:
                    with client.open(root+'/salud',timeout=.5) as response:
                        assert response.status==200
                        break
                except (urllib.error.URLError,TimeoutError):
                    assert time.monotonic()<deadline,'Synthetic demo not ready'
                    time.sleep(.1)
            with client.open(root+'/cliente/acceso',timeout=5) as response:
                token=re.search(r'name="csrf_token" value="([^"]+)"',response.read().decode()).group(1)
            with pytest.raises(urllib.error.HTTPError) as login:
                post(client,root+'/cliente/acceso',{'csrf_token':token,'correo':'eval-a@example.invalid','contrasena':'Synthetic-evaluation-password-123'})
            assert login.value.code==302 and login.value.headers['Location']=='/saas/dashboard'
            with client.open(root+'/saas/copilot',timeout=5) as response:
                body=response.read().decode()
                assert 'rules-v1' in body and 'copilot-budget' in body
                assert 'not-a-real-key' not in body
                token=re.search(r'name="csrf_token" value="([^"]+)"',body).group(1)
            with post(client,root+'/saas/copilot/ask',{'csrf_token':token,'feature':'client_analysis','question':'Seguimiento sintético','request_key':str(uuid.uuid4())}) as response:
                answer=json.loads(response.read())
                assert answer['delivery']['provider']=='local'
                assert answer['usage']['budget']['committed_usd']=='0.0000000000'
                assert 'Faro Solar B' not in json.dumps(answer)
            assert decoy.read_bytes()==before
        finally:
            process.stdin.close()
            process.wait(timeout=10)
