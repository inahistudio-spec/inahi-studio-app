"""Explicit opt-in only. Requires a previously prepared synthetic staging database."""
import os
import pytest


@pytest.mark.skipif(os.environ.get('INAHI_RUN_POSTGRES_TESTS')!='true',reason='PostgreSQL staging real no configurado/autorizado en esta ejecución')
def test_real_postgresql_staging_contract(tmp_path):
    from devtools.staging_postgres import check
    result=check(tmp_path)
    assert result['postgresql_real'] and result['tenant_isolation'] and result['migrations_and_rollback']
