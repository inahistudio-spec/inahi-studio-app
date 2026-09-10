"""Intentional local/staging administration; no browser-supplied organization policy."""
from contextlib import closing
import json
import os
import click
import sqlite3
from runtime_environment import validate
from copilot import budgets


def install(app,connect):
    def allowed():
        if validate() not in ('development','test','staging'):
            raise click.ClickException('Administración experimental deshabilitada en producción')

    @app.cli.command('ai-policy')
    @click.option('--organization-id',required=True,type=int)
    @click.option('--monthly-budget-usd',required=True)
    @click.option('--external/--local',default=False)
    @click.option('--block/--warn-only',default=True)
    @click.option('--requests-per-minute',default=5,type=int)
    @click.option('--max-inflight',default=2,type=int)
    def policy(organization_id,monthly_budget_usd,external,block,requests_per_minute,max_inflight):
        allowed()
        try:
            with closing(connect()) as c,c:
                c.execute('BEGIN IMMEDIATE')
                from evaluations.dataset import verified
                if external and not verified(c,organization_id):
                    raise ValueError('Dataset sintético no verificado')
                budgets.configure(c,organization_id,monthly_budget_usd,external,block,requests_per_minute,max_inflight)
            click.echo('Política guardada; no se ha llamado al proveedor.')
        except (ValueError,sqlite3.Error):
            raise click.ClickException('Política no aplicada: revisar destino, dataset y valores') from None

    @app.cli.command('seed-ai-evaluation')
    @click.option('--confirm-empty-synthetic-database',is_flag=True,required=True)
    def seed(confirm_empty_synthetic_database):
        allowed()
        if not confirm_empty_synthetic_database:
            raise click.ClickException('Se requiere confirmación explícita del destino vacío')
        try:
            from evaluations.dataset import seed
            with closing(connect()) as c,c:
                c.execute('BEGIN IMMEDIATE')
                identities=seed(c,os.environ.get('STAGING_DEMO_PASSWORD',''))
            click.echo(json.dumps({'synthetic_identities':identities}))
        except (ValueError,sqlite3.Error):
            raise click.ClickException('Dataset no creado: requiere base vacía, migración 0006 y contraseña de evaluación') from None
