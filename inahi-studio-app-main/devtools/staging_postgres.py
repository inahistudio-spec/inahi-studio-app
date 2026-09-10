"""Explicit staging DB preparation/check; no production, no DROP and no real AI."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def destination():
    from runtime_environment import validate
    from persistence.database import configured_url
    if validate()!='staging':
        raise ValueError('Solo staging')
    url=configured_url()
    if url.get_backend_name()!='postgresql':
        raise ValueError('Se requiere PostgreSQL real')
    return url


def initialize(report_file,password):
    from persistence.database import make_engine,connect
    from persistence.migrations import migrate
    import sqlalchemy as sa
    engine=make_engine(destination())
    try:
        with engine.connect() as c:
            if sa.inspect(c).get_table_names():
                raise ValueError('Se requiere base staging vacía')
        migrate(report_file,ai_staging=True)
        from evaluations.dataset import seed
        with closing(connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            return seed(c,password)
    finally:
        engine.dispose()


def check(report_directory):
    from persistence.database import connect,make_engine
    from persistence.migrations import migrate
    from evaluations.dataset import verified
    from copilot.providers import LocalProvider
    from copilot.staging_schema import TABLES
    from flask import session
    import sqlalchemy as sa
    import sqlite3
    import uuid
    import app
    url=destination()
    engine=make_engine(url)
    try:
        with engine.connect() as c:
            row=c.exec_driver_sql('SELECT current_database(),current_user').one()
            assert row[0]==url.database and row[1]==url.username
            inspector=sa.inspect(c)
            assert set(table.name for table in TABLES)<=set(inspector.get_table_names())
            assert inspector.get_foreign_keys('crm_opportunities')
            assert any(index['name']=='ix_crm_contacts_followup' for index in inspector.get_indexes('crm_contacts'))
        with closing(connect()) as c:
            orgs=c.execute("SELECT id FROM organizations WHERE slug IN ('evaluation-a','evaluation-b') ORDER BY slug").fetchall()
            assert len(orgs)==2 and all(verified(c,row[0]) for row in orgs)
            a,b=orgs[0][0],orgs[1][0]
            own=c.execute('SELECT id FROM crm_contacts WHERE organization_id=? ORDER BY id LIMIT 1',(a,)).fetchone()[0]
            foreign=c.execute('SELECT id FROM crm_contacts WHERE organization_id=? ORDER BY id LIMIT 1',(b,)).fetchone()[0]
        client=app.app.test_client()
        client.get('/cliente/acceso')
        with client.session_transaction() as state:
            token=state['csrf_token']
        response=client.post('/cliente/acceso',data={'csrf_token':token,'correo':'eval-a@example.invalid','contrasena':os.environ.get('STAGING_DEMO_PASSWORD','')})
        assert response.status_code==302 and response.location.endswith('/saas/dashboard')
        assert client.get("/saas/dashboard").status_code==200
        with client.session_transaction() as state:
            identity=dict(state)
            token=state['csrf_token']
        assert client.get(f'/saas/clientes/{own}').status_code==200
        assert client.get(f'/saas/clientes/{foreign}').status_code==404
        with patch('copilot.providers.get_provider',side_effect=AssertionError('Provider must not run')):
            response=client.post('/saas/copilot/ask',data={'csrf_token':token,'feature':'client_analysis','contact_id':str(foreign),'question':'Synthetic test','request_key':str(uuid.uuid4())})
            assert response.status_code==404
        with patch('copilot.providers.for_organization',return_value=LocalProvider()):
            response=client.post('/saas/copilot/ask',data={'csrf_token':token,'feature':'client_analysis','contact_id':str(own),'question':'Synthetic test','request_key':str(uuid.uuid4())})
            assert response.status_code==200
        with app.app.test_request_context():
            session.update(identity)
            c=connect()
            try:
                c.execute('BEGIN IMMEDIATE')
                from crm.service import save_contact,save_opportunity,activity
                created=save_contact(c,{'company_name':'Temporary PostgreSQL probe'})
                save_opportunity(c,{'title':'Probe','estimated_value':'15.50'},cid=created)
                activity(c,created,{'type':'note','description':'Synthetic probe'})
                c.execute('SAVEPOINT invalid_fk')
                try:
                    c.execute('UPDATE crm_opportunities SET contact_id=? WHERE contact_id=?',(foreign,created))
                    raise AssertionError('Foreign key allowed cross-tenant contact')
                except sqlite3.IntegrityError:
                    c.execute('ROLLBACK TO SAVEPOINT invalid_fk')
            finally:
                c.bind.rollback()
                c.close()
        with closing(connect()) as c:
            assert c.execute('SELECT count(*) FROM organization_subscriptions WHERE organization_id=?',(a,)).fetchone()[0]==1
            assert c.execute('SELECT count(*) FROM ai_call_controls t JOIN copilot_usage u ON u.id=t.call_id WHERE u.organization_id=?',(a,)).fetchone()[0]>=1
            assert c.execute('SELECT count(*) FROM saas_audit WHERE organization_id=?',(a,)).fetchone()[0]>0
            assert verified(c,a)
        directory=Path(report_directory)
        migrate(directory/'rollback-preflight.json',ai_staging=True,downgrade=True)
        migrate(directory/'reactivate-preflight.json',ai_staging=True)
        return {'postgresql_real':True,'connection':True,'migrations_and_rollback':True,'indexes_and_foreign_keys':True,
                'tenant_isolation':True,'crm':True,'billing':True,'copilot_usage':True,'audit':True,'external_ai_calls':0}
    finally:
        engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-directory',required=True)
    parser.add_argument('--initialize-empty',action='store_true')
    args=parser.parse_args()
    directory=Path(args.report_directory)
    directory.mkdir(exist_ok=False,parents=True)
    try:
        if args.initialize_empty:
            initialize(directory/'upgrade-preflight.json',os.environ.get('STAGING_DEMO_PASSWORD',''))
        result=check(directory)
    except Exception:
        (directory/'result.json').write_text(json.dumps({'postgresql_real_validated':False,'error':'Validación incompleta; revisar conexión staging y dataset. Sin detalles de credenciales.'}),encoding='utf-8')
        raise SystemExit(1) from None
    (directory/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
