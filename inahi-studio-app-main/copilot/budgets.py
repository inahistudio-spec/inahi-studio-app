"""Atomic monetary reservations and conservative accounting of uncertain requests."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import os
from persistence.database import has_table
from copilot.errors import QuotaExceeded, Unavailable
from saas_schema import now, audit

UNIT = Decimal('0.0000000001')


def money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or not 0 <= result <= 1000000:
            raise ValueError()
        return result.quantize(UNIT, rounding=ROUND_CEILING)
    except (InvalidOperation, ValueError):
        raise ValueError('Importe no válido') from None


def enabled(c):
    if not has_table(c,'ai_staging_state'):
        return False
    row = c.execute("SELECT enabled FROM ai_staging_state WHERE version='0006_ai_staging'").fetchone()
    return bool(row and row[0])


def policy(c, oid, lock=False):
    if not enabled(c):
        return None
    suffix = ' FOR UPDATE' if lock and getattr(c,'dialect','sqlite') == 'postgresql' else ''
    row = c.execute('SELECT * FROM organization_ai_policies WHERE organization_id=?'+suffix,(oid,)).fetchone()
    return dict(row) if row else None


def configure(c, oid, budget, external=False, block=True, rate=5, concurrent=2):
    if not enabled(c) or not c.execute('SELECT 1 FROM organizations WHERE id=?',(oid,)).fetchone():
        raise ValueError('Organización o migración no disponible')
    if type(external) is not bool or type(block) is not bool or not 1 <= rate <= 100 or not 1 <= concurrent <= 10:
        raise ValueError('Política no válida')
    c.execute('''INSERT INTO organization_ai_policies(organization_id,monthly_budget_usd,external_enabled,block_at_budget,requests_per_minute,max_inflight,updated_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(organization_id) DO UPDATE SET monthly_budget_usd=excluded.monthly_budget_usd,
        external_enabled=excluded.external_enabled,block_at_budget=excluded.block_at_budget,requests_per_minute=excluded.requests_per_minute,max_inflight=excluded.max_inflight,updated_at=excluded.updated_at''',
        (oid,str(money(budget)),int(external),int(block),rate,concurrent,now()))
    audit(c,'ai_policy_changed',oid)


def summary(c, oid):
    config = policy(c,oid)
    if config is None:
        return {'configured':False,'external_enabled':False}
    start = datetime.now(timezone.utc).replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat()
    rows = c.execute('''SELECT a.charged_usd,a.cost_known,a.latency_ms FROM ai_call_controls a
        JOIN copilot_usage u ON u.id=a.call_id WHERE u.organization_id=? AND u.created_at>=?''',(oid,start))
    charged, unknown, latencies = Decimal(0),0,[]
    for row in rows:
        charged += Decimal(str(row['charged_usd']))
        unknown += not row['cost_known']
        if row['latency_ms'] is not None:
            latencies.append(row['latency_ms'])
    limit = money(config['monthly_budget_usd'])
    level = next((n for n in (100,90,70) if (charged*100 >= limit*n and (limit > 0 or charged > 0))),0)
    return {'configured':True,'external_enabled':bool(config['external_enabled']),'budget_usd':format(limit,'.10f'),
        'committed_usd':format(charged,'.10f'), 'remaining_usd':format(max(Decimal(0),limit-charged),'.10f'),
        'alert':level,'block_at_budget':bool(config['block_at_budget']),'uncertain_calls':unknown,
        'average_latency_ms':round(sum(latencies)/len(latencies)) if latencies else None}


def rates(provider):
    if provider.name == 'local':
        return Decimal(0),Decimal(0)
    if os.environ.get('COPILOT_PRICE_PROVIDER') != provider.name or os.environ.get('COPILOT_PRICE_MODEL') != provider.model:
        raise Unavailable()
    try:
        a,b = money(os.environ.get('COPILOT_INPUT_USD_PER_MILLION')),money(os.environ.get('COPILOT_OUTPUT_USD_PER_MILLION'))
        if a <= 0 or b <= 0:
            raise ValueError()
        return a,b
    except ValueError:
        raise Unavailable() from None


def alerts(c, oid):
    state = summary(c,oid)
    if not state['configured']:
        return
    period = datetime.now(timezone.utc).strftime('%Y-%m')
    for threshold in (70,90,100):
        if state['alert'] >= threshold:
            count = c.execute('INSERT INTO ai_budget_alerts(organization_id,period,threshold,created_at) VALUES(?,?,?,?) ON CONFLICT(organization_id,period,threshold) DO NOTHING',(oid,period,threshold,now())).rowcount
            if count:
                audit(c,'ai_budget_'+str(threshold),oid)


def reserve(c, actor, call_id, provider, system, payload):
    if not enabled(c):
        return
    config = policy(c,actor.organization_id,lock=True)
    a,b = rates(provider)
    amount = Decimal(0)
    if provider.name != 'local':
        if config is None or not config['external_enabled']:
            raise Unavailable()
        # UTF-8 bytes plus framing allowance conservatively bound the input token estimate.
        cap = int(getattr(provider,'max_tokens',1200))
        if not 1 <= cap <= 4000:
            raise Unavailable()
        amount = (((len((system+payload).encode('utf-8'))+2048)*a+cap*b)/1000000).quantize(UNIT,rounding=ROUND_CEILING)
        current = summary(c,actor.organization_id)
        if config['block_at_budget'] and Decimal(current['committed_usd'])+amount > money(config['monthly_budget_usd']):
            raise QuotaExceeded()
    if config:
        since = (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
        recent = c.execute('SELECT count(*) FROM copilot_usage WHERE organization_id=? AND created_at>=?',(actor.organization_id,since)).fetchone()[0]
        inflight = c.execute("SELECT count(*) FROM copilot_usage WHERE organization_id=? AND status='reserved'",(actor.organization_id,)).fetchone()[0]
        if recent > config['requests_per_minute'] or inflight > config['max_inflight']:
            raise QuotaExceeded()
    c.execute('INSERT INTO ai_call_controls(call_id,reserved_usd,charged_usd,input_rate,output_rate,cost_known) VALUES(?,?,?,?,?,?)',
        (call_id,str(amount),str(amount),str(a),str(b),int(provider.name=='local')))
    alerts(c,actor.organization_id)


def finish(c, actor, call_id, values, latency, delivered, reason=None, fallback=False):
    if not enabled(c):
        return
    row = c.execute('''SELECT a.* FROM ai_call_controls a JOIN copilot_usage u ON u.id=a.call_id
        WHERE a.call_id=? AND u.organization_id=? AND u.user_id=?''',(call_id,actor.organization_id,actor.user_id)).fetchone()
    if not row:
        raise Unavailable()
    cost = None
    if values[0] is not None and values[1] is not None:
        cost = ((Decimal(str(row['input_rate']))*values[0]+Decimal(str(row['output_rate']))*values[1])/1000000).quantize(UNIT,rounding=ROUND_CEILING)
    elif row['cost_known']:
        cost = Decimal(0)
    c.execute('UPDATE ai_call_controls SET charged_usd=?,cost_known=?,latency_ms=?,error_code=?,delivered_provider=?,delivered_model=?,fallback=? WHERE call_id=?',
        (str(cost) if cost is not None else str(row['charged_usd']),int(cost is not None),latency,reason,delivered.name,delivered.model,int(fallback),call_id))
    c.execute('UPDATE copilot_usage SET estimated_cost=?,cost_currency=? WHERE id=? AND organization_id=?',
        (str(cost) if cost is not None else None,'USD' if cost is not None else None,call_id,actor.organization_id))
    alerts(c,actor.organization_id)
