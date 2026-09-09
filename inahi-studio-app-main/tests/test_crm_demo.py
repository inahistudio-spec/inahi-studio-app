"""Use exactly the real demo bootstrap and TCP login, not an app test client."""
import json
import re
import sqlite3
import urllib.error
import uuid
import pytest
from test_workspace_demo_process import real_demo, http_client, post


def test_real_demo_login_crm_write_and_contextual_copilot(real_demo):
    root, port, runtime, directory, env = real_demo
    client = http_client()
    with client.open(root+'/cliente/acceso',timeout=5) as response:
        token = re.search(r'name="csrf_token" value="([^"]+)"',response.read().decode()).group(1)
    with pytest.raises(urllib.error.HTTPError) as login:
        post(client,root+'/cliente/acceso',{'correo':'qa@example.com','contrasena':'Legacy-password-123','csrf_token':token})
    assert login.value.code == 302 and login.value.headers['Location'] == '/saas/dashboard'
    with client.open(root+'/saas/clientes',timeout=5) as response:
        body = response.read().decode()
        assert 'Atelier Oliva' in body and 'Estudio Norte' in body
        assert 'Contacto privado B' not in body
    with client.open(root+'/saas/clientes/nuevo',timeout=5) as response:
        token = re.search(r'name="csrf_token" value="([^"]+)"',response.read().decode()).group(1)
    with pytest.raises(urllib.error.HTTPError) as created:
        post(client,root+'/saas/clientes/nuevo',{'company_name':'HTTP DEMO contact','csrf_token':token})
    assert created.value.code == 303
    path = created.value.headers['Location']
    cid = path.rsplit('/',1)[1]
    with client.open(root+path+'/copilot',timeout=5) as response:
        assert 'HTTP DEMO contact' in response.read().decode()
    fields = {'csrf_token':token,'feature':'sales_strategy','crm_task':'strategy','question':'Estrategia comercial','contact_id':cid,'request_key':str(uuid.uuid4())}
    with post(client,root+'/saas/copilot/ask',fields) as response:
        result = json.loads(response.read())
        assert response.status == 200
        assert any('HTTP DEMO contact' in item for item in result['recommendations'])
        assert 'Contacto privado B' not in json.dumps(result)
    # Reported file belongs exclusively to the subprocess fixture.
    with sqlite3.connect(runtime['database']) as c:
        foreign = c.execute('SELECT id FROM crm_contacts WHERE organization_id=2').fetchone()[0]
        count = c.execute('SELECT count(*) FROM copilot_usage').fetchone()[0]
    with pytest.raises(urllib.error.HTTPError) as denied:
        post(client,root+'/saas/copilot/ask',{**fields,'contact_id':str(foreign),'request_key':str(uuid.uuid4())})
    assert denied.value.code == 404
    with sqlite3.connect(runtime['database']) as c:
        assert c.execute('SELECT count(*) FROM copilot_usage').fetchone()[0] == count
        assert c.execute('SELECT provider FROM copilot_usage').fetchone()[0] == 'local'
