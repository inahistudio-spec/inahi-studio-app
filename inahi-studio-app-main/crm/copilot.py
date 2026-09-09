"""Bounded CRM retrieval and deterministic local advice; no remote calls or actions."""
from datetime import datetime, timezone, timedelta
import json
from copilot.sanitization import data, text
from copilot.features import ROLES
from copilot.errors import CopilotError
from crm import service, policy

TASKS = {
    'followups': ('client_analysis', 'Seguimientos', 'Analiza mis clientes y dime cuáles necesitan seguimiento.'),
    'closing': ('opportunities', 'Cierre de oportunidades', '¿Qué oportunidades tienen más probabilidad de cerrar?'),
    'stale': ('pending_actions', 'Leads sin actividad', '¿Qué leads llevan demasiado tiempo sin actividad?'),
    'strategy': ('sales_strategy', 'Estrategia del contacto', 'Prepárame una estrategia para este cliente.'),
    'history': ('reports', 'Historial del contacto', 'Resume el historial de este contacto.'),
    'calls': ('business_overview', 'Llamadas de la semana', '¿A quién debería llamar esta semana?'),
}


def suggestions(actor):
    return [{'crm_task': key, 'feature': value[0], 'label': value[1], 'question': value[2]}
            for key, value in TASKS.items() if actor.role in ROLES[value[0]]]


def build(c, actor, feature, contact_id=None, task=None):
    if task is not None and (task not in TASKS or TASKS[task][0] != feature):
        raise CopilotError()
    commercial_request = task is not None or contact_id is not None or feature == 'client_analysis'
    task = task or next((key for key, value in TASKS.items() if value[0] == feature), 'followups')
    if contact_id is not None:
        service.get_contact(c, actor, contact_id)
    query = service.contact_query()
    args = [actor.organization_id]
    if contact_id is not None:
        query += ' AND t.id=?'
        args.append(contact_id)
    # Prioritize due/uncontacted/old records over simply taking the newest IDs.
    contact_args = list(args)
    if task == 'stale' and contact_id is None:
        cutoff = (datetime.now(timezone.utc)-timedelta(days=30)).isoformat()
        query += " AND t.status='lead' AND t.created_at<? AND (t.last_contact_at IS NULL OR t.last_contact_at<?) AND NOT EXISTS(SELECT 1 FROM crm_activities a WHERE a.organization_id=t.organization_id AND a.contact_id=t.id AND a.occurred_at>=?)"
        contact_args.extend((cutoff,cutoff,cutoff))
    query += " ORDER BY CASE WHEN t.status='inactive' THEN 1 ELSE 0 END, CASE WHEN t.next_followup_at<=? THEN 0 WHEN t.last_contact_at IS NULL THEN 1 ELSE 2 END,t.next_followup_at,t.last_contact_at,t.created_at LIMIT 5"
    contact_args.append((datetime.now(timezone.utc)+timedelta(days=7)).isoformat())
    contacts = [dict(r) for r in c.execute(query, contact_args)]
    extra = ' AND t.id=?' if contact_id is not None else ''
    opportunities = [dict(r) for r in c.execute("SELECT o.id,o.title,o.stage,o.estimated_value,o.probability,o.expected_close_date,t.company_name,t.contact_name FROM crm_opportunities o JOIN crm_contacts t ON t.id=o.contact_id AND t.organization_id=o.organization_id WHERE o.organization_id=? AND t.archived_at IS NULL" + extra + " ORDER BY CASE WHEN o.stage IN ('won','lost') THEN 1 ELSE 0 END,o.probability DESC,o.id DESC LIMIT 5", args)]
    activities = [dict(r) for r in c.execute("SELECT a.id,a.type,a.description,a.occurred_at,t.company_name,t.contact_name FROM crm_activities a JOIN crm_contacts t ON t.id=a.contact_id AND t.organization_id=a.organization_id WHERE a.organization_id=? AND t.archived_at IS NULL" + extra + ' ORDER BY a.occurred_at DESC,a.id DESC LIMIT 5', args)]
    rows = {'crm_contacts': [], 'crm_opportunities': [], 'crm_activities': []}
    refs = []
    fields = {
        'crm_contacts': ('company_name','contact_name','status','source','notes','last_contact_at','next_followup_at'),
        'crm_opportunities': ('company_name','contact_name','title','stage','estimated_value','probability','expected_close_date'),
        'crm_activities': ('company_name','contact_name','type','description','occurred_at'),
    }
    for kind, records in zip(rows, (contacts, opportunities, activities)):
        for row in records:
            safe = {key: row[key] for key in fields[kind]}
            for key in ('last_contact_at','next_followup_at','expected_close_date','occurred_at'):
                if safe.get(key):
                    safe[key] = datetime.fromisoformat(str(safe[key])).strftime('%Y/%m/%d %H:%M UTC')
            for key in ('notes','description'):
                if key in safe:
                    safe[key] = text(safe[key], 450)
            if kind == 'crm_contacts':
                safe['followup_flags'] = service.flags(row)
            ref = f"{kind}:{row['id']}"
            item = {'source': ref, 'data': data(safe)}
            rows[kind].append(item)
            if len(json.dumps(rows, ensure_ascii=False)) > 6500:
                rows[kind].pop()
                break
            refs.append(ref)
    return {'available': True, 'task': task, 'commercial_request': commercial_request, 'individual': contact_id is not None,
            'note': 'Muestra de hasta cinco fichas, oportunidades y actividades; importes estimados y probabilidades declaradas, no predicciones.'}, rows, refs


def local_answer(context):
    task = context['clients']['task']
    contacts = context['records'].get('crm_contacts', [])
    opportunities = context['records'].get('crm_opportunities', [])
    activities = context['records'].get('crm_activities', [])
    refs = [item['source'] for kind, rows in context['records'].items() if kind.startswith('crm_') for item in rows]
    actions = []
    def label(row):
        return str(row.get('company_name') or row.get('contact_name') or 'Contacto')[:160]
    if task == 'closing':
        for item in opportunities:
            row = item['data']
            if row['stage'] in policy.OPEN_STAGES:
                actions.append(f"{label(row)}: {row['title']} está en {policy.LABELS[row['stage']]} con probabilidad declarada del {row['probability']}% y valor estimado {row['estimated_value']}. Confirma el siguiente paso y la fecha con el responsable.")
    elif task == 'history':
        for item in activities:
            row = item['data']
            actions.append(f"{label(row)} · {row['occurred_at']} · {policy.LABELS[row['type']]}: {row['description']}")
    else:
        for item in contacts:
            row = item['data']
            flags = row['followup_flags']
            if row['status'] == 'inactive':
                continue
            if task == 'strategy':
                actions.append(f"{label(row)} está en estado {policy.LABELS[row['status']]}. Propuesta: validar necesidades en una conversación, contrastar las notas de la ficha y acordar un siguiente paso medible. Notas disponibles: {row['notes'] or 'sin notas registradas'}.")
            elif task == 'stale':
                if row['status'] == 'lead' and flags['stale']:
                    actions.append(f"{label(row)}: lead sin actividad en 30 días. Revisa su interés antes de proponer una nueva conversación.")
            elif flags['overdue'] or flags['upcoming'] or flags['uncontacted'] or flags['stale']:
                reason = 'seguimiento vencido' if flags['overdue'] else 'seguimiento en los próximos siete días' if flags['upcoming'] else 'lead sin contactar' if flags['uncontacted'] else 'sin actividad en 30 días'
                actions.append(f"{label(row)}: {reason}. Propón una llamada y registra el resultado; fecha prevista: {row['next_followup_at'] or 'sin programar'}.")
    if not actions:
        actions.append('La muestra autorizada no contiene registros que cumplan este criterio. Revisa los filtros del CRM y completa fechas o actividades pendientes.')
    return {'answer': f"Revisión comercial de {len(contacts)} contactos autorizados. Las propuestas siguientes se basan en los registros disponibles.",
            'recommendations': [text(action, 1100) for action in actions[:7]],
            'limitations': ['Respuesta orientativa de reglas locales, no un análisis generativo.', 'No se han enviado mensajes ni modificado fichas. La probabilidad es una valoración del equipo.', *context['limitations']][:5],
            'sources': refs}
