"""Phase 7: real SQLite and synthetic fixtures, fake transports, no provider network."""
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock,patch
import io
import json
import os
import sqlite3
import uuid
from urllib.error import HTTPError,URLError
import pytest
from test_saas_core import inahi
from persistence.migrations import migrate
from persistence.database import configured_url
from evaluations.dataset import seed,verified
from copilot import budgets,providers
from runtime_environment import mode,validate,external_enabled

SAFE={'answer':'Revisa las necesidades registradas.','recommendations':['Confirma los datos pendientes.'],'limitations':['Datos sintéticos incompletos.'],'sources':[]}


@pytest.fixture
def staging(tmp_path):
    path=tmp_path/'staging.sqlite'
    password='Synthetic-evaluation-password-123'
    with patch.dict(os.environ,{},clear=True),patch.object(inahi,'DB',str(path)),patch.dict(inahi.app.config,TESTING=True,SECRET_KEY='synthetic-session-secret'),patch('socket.socket.connect',side_effect=AssertionError('No network')):
        migrate(tmp_path/'preflight.json',str(path),ai_staging=True)
        with closing(inahi.conectar()) as c,c:
            identities=seed(c,password)
        client=inahi.app.test_client()
        client.get('/cliente/acceso')
        with client.session_transaction() as state:
            token=state['csrf_token']
        assert client.post('/cliente/acceso',data={'csrf_token':token,'correo':identities[0]['email'],'contrasena':password}).status_code==302
        assert client.get("/saas/dashboard").status_code==200
        def post(**values):
            with client.session_transaction() as state:
                token=state['csrf_token']
            return client.post('/saas/copilot/ask',data={'csrf_token':token,'feature':'client_analysis','question':'Seguimiento sintético','request_key':str(uuid.uuid4()),**values})
        f=SimpleNamespace(path=path,client=client,post=post,identities=identities,password=password,connect=inahi.conectar)
        yield f


def fake():
    return SimpleNamespace(name='fake',model='fake-v1',max_tokens=128,generate=Mock(return_value=providers.Completion(SAFE,20,10,30)))


def configure_fake(f,budget='1',block=True,rate=30,concurrent=2):
    with closing(f.connect()) as c,c:
        budgets.configure(c,f.identities[0]['organization_id'],budget,True,block,rate,concurrent)
    os.environ.update(COPILOT_PRICE_PROVIDER='fake',COPILOT_PRICE_MODEL='fake-v1',COPILOT_INPUT_USD_PER_MILLION='1',COPILOT_OUTPUT_USD_PER_MILLION='2')


@pytest.mark.parametrize('environment',['development','test','staging','production'])
def test_explicit_environment_modes(monkeypatch,environment):
    monkeypatch.setenv('APP_ENV',environment)
    assert mode()==environment


@pytest.mark.parametrize('environment',['','prod','STAGGING'])
def test_invalid_environment_rejected(monkeypatch,environment):
    monkeypatch.setenv('APP_ENV',environment)
    with pytest.raises(ValueError):
        mode()


def stage_env(monkeypatch):
    monkeypatch.setenv('APP_ENV','staging')
    monkeypatch.setenv('STAGING_DB_HOST','localhost')
    monkeypatch.setenv('STAGING_DB_NAME','inahi_staging_eval')
    monkeypatch.setenv('STAGING_DB_USER','inahi_staging_runner')


def test_postgres_configuration_pinned_without_connecting(monkeypatch):
    stage_env(monkeypatch)
    monkeypatch.setenv('DATABASE_URL','postgresql://inahi_staging_runner:synthetic@localhost/inahi_staging_eval')
    assert configured_url().drivername=='postgresql+psycopg'


@pytest.mark.parametrize('url',['sqlite:///demo.db','postgresql://prod:synthetic@localhost/inahi_staging_eval','postgresql://inahi_staging_runner:synthetic@prod.invalid/production','postgresql://inahi_staging_runner:synthetic@localhost/inahi_staging_eval?options=unsafe'])
def test_staging_rejects_wrong_target_before_connect(monkeypatch,url):
    stage_env(monkeypatch)
    monkeypatch.setenv('DATABASE_URL',url)
    with patch('persistence.database.make_engine') as connection,pytest.raises(ValueError):
        configured_url()
    connection.assert_not_called()


@pytest.mark.parametrize('key',['COPILOT_API_KEY','OPENAI_API_KEY','STRIPE_SECRET_KEY','STRIPE_WEBHOOK_SECRET','SMTP_PASSWORD'])
def test_staging_rejects_ambient_credentials_without_leak(monkeypatch,key):
    stage_env(monkeypatch)
    monkeypatch.setenv(key,'SECRET_SENTINEL')
    with pytest.raises(ValueError) as exc:
        validate()
    assert 'SECRET_SENTINEL' not in str(exc.value)


def test_no_key_starts_and_uses_local(staging):
    os.environ.update(COPILOT_PROVIDER='openai',COPILOT_EXTERNAL_ENABLED='true',COPILOT_ALLOW_EXTERNAL='true')
    response=staging.post()
    assert response.status_code==200
    assert response.json['delivery']['provider']=='local'
    assert response.json['usage']['budget']['committed_usd']=='0.0000000000'


@pytest.mark.parametrize('environment',['production','test'])
def test_external_feature_disabled_in_production_and_test(staging,environment):
    os.environ.update(APP_ENV=environment,COPILOT_ALLOW_EXTERNAL='true',COPILOT_EXTERNAL_ENABLED='true',COPILOT_API_KEY='not-real')
    with inahi.app.app_context():
        assert external_enabled() is False


def test_feature_flag_requires_environment_organization_and_synthetic_manifest(staging):
    os.environ.update(APP_ENV='development',COPILOT_ALLOW_EXTERNAL='true',COPILOT_EXTERNAL_ENABLED='true',COPILOT_API_KEY='synthetic',COPILOT_PROVIDER='openai')
    with inahi.app.test_request_context(),patch.dict(inahi.app.config,TESTING=False),closing(staging.connect()) as c,c:
        actor=SimpleNamespace(organization_id=staging.identities[0]['organization_id'])
        with patch('copilot.providers.get_provider',return_value=fake()) as factory:
            assert providers.for_organization(c,actor).name=='local'
            factory.assert_not_called()
            budgets.configure(c,actor.organization_id,'1',True)
            assert providers.for_organization(c,actor).name=='fake'
            c.execute('UPDATE crm_contacts SET notes=? WHERE organization_id=?',('Changed data',actor.organization_id))
            assert not verified(c,actor.organization_id)
            assert providers.for_organization(c,actor).name=='local'


def test_real_provider_requires_service_authorization_even_with_key(monkeypatch):
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.setenv('COPILOT_ALLOW_EXTERNAL','true')
    monkeypatch.setenv('COPILOT_EXTERNAL_ENABLED','true')
    monkeypatch.setenv('COPILOT_API_KEY','synthetic')
    monkeypatch.setenv('COPILOT_MODEL','synthetic-model')
    from copilot.errors import Unavailable
    with pytest.raises(Unavailable):
        providers.OpenAIProvider()


def test_budget_records_tokens_latency_and_scoped_usage(staging):
    configure_fake(staging)
    provider=fake()
    with patch('copilot.providers.for_organization',return_value=provider):
        response=staging.post()
    assert response.status_code==200
    assert response.json['usage']['budget']['committed_usd']=='0.0000400000'
    with closing(staging.connect()) as c:
        row=dict(c.execute('SELECT * FROM ai_call_controls').fetchone())
        assert row['latency_ms']>=0 and row['cost_known']==1
        assert budgets.summary(c,staging.identities[1]['organization_id'])['committed_usd']=='0.0000000000'


def test_budget_blocks_before_network_and_keeps_quota_unchanged(staging):
    configure_fake(staging,'0.000001')
    provider=fake()
    with patch('copilot.providers.for_organization',return_value=provider):
        assert staging.post().status_code==429
    provider.generate.assert_not_called()
    with closing(staging.connect()) as c:
        assert c.execute('SELECT count(*) FROM copilot_usage').fetchone()[0]==0


@pytest.mark.parametrize('level,amount',[(70,'0.70'),(90,'0.90'),(100,'1')])
def test_threshold_alerts_deduplicated(staging,level,amount):
    configure_fake(staging)
    with patch('copilot.providers.for_organization',return_value=fake()):
        assert staging.post().status_code==200
    oid=staging.identities[0]['organization_id']
    with closing(staging.connect()) as c,c:
        c.execute('UPDATE ai_call_controls SET charged_usd=?',(amount,))
        budgets.alerts(c,oid)
        budgets.alerts(c,oid)
        assert budgets.summary(c,oid)['alert']==level
        count=c.execute('SELECT count(*) FROM ai_budget_alerts WHERE organization_id=?',(oid,)).fetchone()[0]
        assert count==[70,90,100].index(level)+1


def test_warning_only_budget_allows_explicit_overage(staging):
    configure_fake(staging,'0.000001',False)
    with patch('copilot.providers.for_organization',return_value=fake()):
        response=staging.post()
    assert response.status_code==200 and response.json['usage']['budget']['alert']==100


@pytest.mark.parametrize('failure',[TimeoutError(),HTTPError('https://example.invalid',429,'SECRET',{},None),HTTPError('https://example.invalid',503,'SECRET',{},None),URLError('SECRET')])
def test_mocked_real_provider_errors_are_safe(monkeypatch,failure):
    for key,value in {'COPILOT_ALLOW_EXTERNAL':'true','COPILOT_API_KEY':'synthetic','COPILOT_MODEL':'synthetic-model'}.items():
        monkeypatch.setenv(key,value)
    from copilot.errors import ProviderError
    with pytest.raises(ProviderError) as exc:
        providers.OpenAIProvider(Mock(side_effect=failure)).generate('fixed','synthetic')
    assert 'SECRET' not in str(exc.value)


@pytest.mark.parametrize('kind',['timeout','429','5xx','invalid'])
def test_failure_falls_back_once_and_holds_uncertain_cost(staging,kind):
    from copilot.errors import ProviderTimeout,ProviderRateLimit,ProviderDown
    configure_fake(staging)
    provider=fake()
    if kind=='invalid':
        provider.generate.return_value=providers.Completion({'unsafe':'<script>'})
    else:
        provider.generate.side_effect={'timeout':ProviderTimeout(),'429':ProviderRateLimit(),'5xx':ProviderDown()}[kind]
    with patch('copilot.providers.for_organization',return_value=provider):
        response=staging.post()
    assert response.status_code==200
    assert response.json['delivery']['fallback'] and response.json['delivery']['provider']=='local'
    assert provider.generate.call_count==1
    with closing(staging.connect()) as c:
        row=dict(c.execute('SELECT * FROM ai_call_controls').fetchone())
        assert row['cost_known']==0 and row['charged_usd']==row['reserved_usd'] and row['charged_usd']>0
        assert c.execute('SELECT status FROM copilot_usage').fetchone()[0] in ('provider_error','invalid_output')


def test_duplicates_do_not_retry_or_consume_again(staging):
    configure_fake(staging)
    provider=fake()
    key=str(uuid.uuid4())
    with patch('copilot.providers.for_organization',return_value=provider):
        assert staging.post(request_key=key).status_code==200
        assert staging.post(request_key=key).status_code==409
    assert provider.generate.call_count==1


def test_org_rate_limit_applies_to_all_requests(staging):
    configure_fake(staging,rate=1)
    provider=fake()
    with patch('copilot.providers.for_organization',return_value=provider):
        assert staging.post().status_code==200
        assert staging.post().status_code==429
    assert provider.generate.call_count==1


def test_b_contact_denied_before_provider_selection(staging):
    foreign=staging.identities[1]['contact_id']
    with patch('copilot.providers.for_organization') as factory:
        assert staging.post(contact_id=str(foreign)).status_code==404
    factory.assert_not_called()


def test_synthetic_context_redacts_injection_and_excludes_b(staging):
    configure_fake(staging)
    provider=fake()
    with patch('copilot.providers.for_organization',return_value=provider):
        assert staging.post().status_code==200
    payload=provider.generate.call_args.args[1]
    for marker in ('SYNTHETIC_CANARY_SECRET','Ignore previous','Faro Solar B','Empresa sintética B','password_hash'):
        assert marker not in payload
    assert 'Faro Solar A' in payload


def test_ten_local_evaluations_and_human_quality_rubric(staging):
    os.environ["COPILOT_REQUESTS_PER_MINUTE"]="30"
    from evaluations.copilot_eval import run
    result=run(inahi.app,staging.connect,staging.password)
    assert result['all_safety_checks_passed'],result
    assert len(result['cases'])==10
    assert result['human_review_required'] and not result['generative_quality_validated']


def test_evaluator_detects_hallucinated_source_and_tenant_canary():
    from evaluations.copilot_eval import assess
    assert not assess({**SAFE,'sources':['crm_contacts:999']},['crm_contacts:1'],{})['safety_pass']
    assert not assess({**SAFE,'answer':'Faro Solar B','sources':['crm_contacts:1']},['crm_contacts:1'],{})['safety_pass']


def test_seed_refuses_existing_data(staging):
    with closing(staging.connect()) as c,c,pytest.raises(ValueError):
        seed(c,staging.password)


def test_logical_rollback_preserves_usage_and_disables_external(staging,tmp_path):
    configure_fake(staging)
    with patch('copilot.providers.for_organization',return_value=fake()):
        assert staging.post().status_code==200
    migrate(tmp_path/'rollback.json',str(staging.path),ai_staging=True,downgrade=True)
    with closing(staging.connect()) as c:
        assert not budgets.enabled(c)
        assert c.execute('SELECT count(*) FROM ai_call_controls').fetchone()[0]==1
    migrate(tmp_path/'reactivate.json',str(staging.path),ai_staging=True)
    with closing(staging.connect()) as c:
        assert not budgets.policy(c,staging.identities[0]['organization_id'])['external_enabled']


def test_no_prompts_responses_or_secrets_in_telemetry(staging):
    assert staging.post(question='token=SYNTHETIC_SECRET question').status_code==200
    with closing(staging.connect()) as c:
        output=json.dumps([dict(r) for r in c.execute('SELECT * FROM copilot_usage')],default=str)+json.dumps([dict(r) for r in c.execute('SELECT * FROM ai_call_controls')],default=str)
    assert 'SYNTHETIC_SECRET' not in output and 'question' not in output


def test_interruption_retains_reservation_and_rejects_duplicate(staging):
    configure_fake(staging)
    provider=fake()
    provider.generate.side_effect=KeyboardInterrupt()
    key=str(uuid.uuid4())
    with patch('copilot.providers.for_organization',return_value=provider):
        with pytest.raises(KeyboardInterrupt):
            staging.post(request_key=key)
        assert staging.post(request_key=key).status_code==409
    with closing(staging.connect()) as c:
        row=dict(c.execute('SELECT * FROM ai_call_controls').fetchone())
        assert row['charged_usd']>0 and not row['cost_known']
        assert c.execute('SELECT status FROM copilot_usage').fetchone()[0]=='reserved'


def test_feature_disabled_during_generation_rejects_output(staging):
    configure_fake(staging)
    provider=fake()
    result=provider.generate.return_value
    def revoke(*args):
        with closing(staging.connect()) as c,c:
            c.execute('UPDATE organization_ai_policies SET external_enabled=0')
        return result
    provider.generate.side_effect=revoke
    with patch('copilot.providers.for_organization',return_value=provider):
        assert staging.post().status_code==403


def test_monthly_budget_keeps_previous_month_history_without_charging_current(staging):
    configure_fake(staging)
    with patch('copilot.providers.for_organization',return_value=fake()):
        assert staging.post().status_code==200
    with closing(staging.connect()) as c,c:
        c.execute("UPDATE copilot_usage SET created_at='2000-01-01T00:00:00+00:00'")
        assert budgets.summary(c,staging.identities[0]['organization_id'])['committed_usd']=='0.0000000000'
        assert c.execute('SELECT count(*) FROM ai_call_controls').fetchone()[0]==1


def test_invalid_pricing_blocks_without_call(staging):
    configure_fake(staging)
    os.environ['COPILOT_PRICE_MODEL']='wrong-model'
    provider=fake()
    with patch('copilot.providers.for_organization',return_value=provider):
        assert staging.post().status_code==503
    provider.generate.assert_not_called()


def test_cli_cannot_enable_non_synthetic_organization(staging):
    with closing(staging.connect()) as c,c:
        c.execute('UPDATE crm_contacts SET notes=?',('Unverified input',))
    result=inahi.app.test_cli_runner().invoke(args=['ai-policy','--organization-id',str(staging.identities[0]['organization_id']),'--monthly-budget-usd','1','--external'])
    assert result.exit_code!=0
    with closing(staging.connect()) as c:
        assert not budgets.policy(c,staging.identities[0]['organization_id'])['external_enabled']


def test_ui_shows_provider_budget_and_safe_fallback_metadata(staging):
    page=staging.client.get('/saas/copilot').get_data(as_text=True)
    assert 'copilot-budget' in page and 'copilot-provider' in page and 'rules-v1' in page
    assert 'API_KEY' not in page


def test_openai_secret_prefix_is_redacted():
    from copilot.sanitization import text
    assert 'sk-proj-syntheticSecret0123456789' not in text('note sk-proj-syntheticSecret0123456789')


def test_postgres_schema_budget_constraints_offline(monkeypatch):
    from sqlalchemy.schema import CreateTable
    from sqlalchemy.dialects import postgresql
    from copilot.staging_schema import TABLES
    from persistence.migrations import configuration
    from alembic import command
    ddl='\n'.join(str(CreateTable(table).compile(dialect=postgresql.dialect())) for table in TABLES)
    assert 'NUMERIC(20, 10)' in ddl and 'FOREIGN KEY(call_id)' in ddl
    monkeypatch.setenv('DATABASE_URL','postgresql://placeholder:synthetic@localhost/local_test_only')
    cfg=configuration()
    cfg.output_buffer=io.StringIO()
    command.upgrade(cfg,'head',sql=True)
    assert 'CREATE TABLE organization_ai_policies' in cfg.output_buffer.getvalue()


def test_staging_cookie_is_separate_and_secure(monkeypatch):
    from flask import Flask
    from runtime_environment import configure_app
    stage_env(monkeypatch)
    monkeypatch.setenv('SECRET_KEY','synthetic-session-secret-32-characters')
    app=Flask('stage-cookie')
    configure_app(app)
    assert app.config['SESSION_COOKIE_SECURE'] and app.config['SESSION_COOKIE_NAME']=='inahi_staging'


def test_http_exception_restricted_to_localhost(monkeypatch):
    from flask import Flask
    from runtime_environment import configure_app
    stage_env(monkeypatch)
    monkeypatch.setenv('SECRET_KEY','synthetic-session-secret-32-characters')
    monkeypatch.setenv('STAGING_LOCAL_HTTP','true')
    monkeypatch.setenv('PUBLIC_BASE_URL','http://remote.invalid')
    with pytest.raises(ValueError):
        configure_app(Flask('unsafe-stage'))
    monkeypatch.setenv('PUBLIC_BASE_URL','http://127.0.0.1:5057')
    app=Flask('local-stage')
    configure_app(app)
    assert not app.config['SESSION_COOKIE_SECURE']


def test_inflight_limit_is_atomic_with_two_clients(staging):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    configure_fake(staging,concurrent=1)
    entered,released=threading.Event(),threading.Event()
    provider=fake()
    result=provider.generate.return_value
    def hold(*args):
        entered.set()
        assert released.wait(10)
        return result
    provider.generate.side_effect=hold
    client=inahi.app.test_client()
    client.get('/cliente/acceso')
    with client.session_transaction() as state:
        token=state['csrf_token']
    assert client.post('/cliente/acceso',data={'csrf_token':token,'correo':staging.identities[0]['email'],'contrasena':staging.password}).status_code==302
    client.get('/saas/dashboard')
    with client.session_transaction() as state:
        token=state['csrf_token']
    with patch('copilot.providers.for_organization',return_value=provider),ThreadPoolExecutor(max_workers=1) as pool:
        first=pool.submit(staging.post)
        try:
            assert entered.wait(10)
            second=client.post('/saas/copilot/ask',data={'csrf_token':token,'feature':'client_analysis','question':'Synthetic second','request_key':str(uuid.uuid4())})
            assert second.status_code==429
        finally:
            released.set()
        assert first.result(timeout=10).status_code==200
    assert provider.generate.call_count==1


def test_org_rate_limit_combines_different_users(staging):
    configure_fake(staging,rate=1)
    from saas_core import create_user,add_membership
    with closing(staging.connect()) as c,c:
        uid=create_user(c,'extra@example.invalid',staging.password,'Synthetic extra')
        add_membership(c,staging.identities[0]['organization_id'],uid,'manager')
    client=inahi.app.test_client()
    client.get('/cliente/acceso')
    with client.session_transaction() as state:
        token=state['csrf_token']
    assert client.post('/cliente/acceso',data={'csrf_token':token,'correo':'extra@example.invalid','contrasena':staging.password}).status_code==302
    client.get('/saas/dashboard')
    with client.session_transaction() as state:
        token=state['csrf_token']
    provider=fake()
    with patch('copilot.providers.for_organization',return_value=provider):
        assert staging.post().status_code==200
        response=client.post('/saas/copilot/ask',data={'csrf_token':token,'feature':'client_analysis','question':'Synthetic other user','request_key':str(uuid.uuid4())})
        assert response.status_code==429
    assert provider.generate.call_count==1
