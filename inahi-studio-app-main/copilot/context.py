"""No SELECT *, global client lookup, arbitrary table, or cross-tenant cache."""
import json
from flask import abort
from copilot.features import SOURCES
from copilot.permissions import authorize
from copilot.sanitization import data, text
from copilot.errors import CopilotError
from billing.entitlements import describe

FIELDS = {
    "diagnosticos": ("id", "web", "google", "redes", "resenas", "objetivos", "puntuacion"),
    "estrategias_comerciales": ("id", "respuestas", "estrategia"),
    "calendarios_contenido": ("id", "periodo", "contenido"),
    "resultados_mensuales": ("id", "periodo", "contactos", "ventas", "ingresos", "resenas", "notas", "informe"),
    "informes": ("id", "titulo", "contenido"),
    "solicitudes": ("id", "asunto", "descripcion", "estado", "origen_respuesta"),
    "citas": ("id", "fecha", "hora", "modalidad", "motivo", "estado"),
}
MAX_CONTEXT = 18000


def build(c, feature, resource_kind=None, resource_id=None, contact_id=None, crm_task=None):
    # Resolve from signed session + current membership even when called outside the route.
    actor = authorize(c, feature)
    if (resource_kind is None) != (resource_id is None):
        raise CopilotError()
    if resource_kind is not None and (resource_kind not in SOURCES[feature] or type(resource_id) is not int or resource_id <= 0):
        raise CopilotError()
    from crm.policy import enabled as crm_enabled
    if contact_id is not None and (type(contact_id) is not int or contact_id <= 0 or resource_kind is not None):
        raise CopilotError()
    if (contact_id is not None or crm_task is not None) and not crm_enabled(c):
        abort(404)
    policy = describe(c, actor.organization_id)
    company = c.execute("SELECT name FROM organizations WHERE id=?", (actor.organization_id,)).fetchone()
    context = {"company": {"name": text(company[0], 120)},
               "clients": {"available": False, "note": "No hay CRM de contactos comerciales. No inventar clientes ni seguimientos."},
               "entitlements": {key: policy[key] for key in ("plan", "status", "premium", "limits") if key in policy},
               "records": {}, "activity": [], "limitations": []}
    refs = []
    if crm_enabled(c):
        from crm.copilot import build as crm_build
        context['clients'], context['records'], refs = crm_build(c, actor, feature, contact_id, crm_task)
        context['limitations'].append('CRM: muestra limitada; los documentos generales no se atribuyen a contactos individuales.')
    for kind in (() if contact_id is not None else SOURCES[feature]):
        # Identifiers come exclusively from the fixed registry, values stay bound.
        columns = ",".join(FIELDS[kind])
        params = [actor.organization_id]
        where = "organization_id=?"
        if resource_kind == kind:
            where += " AND id=?"
            params.append(resource_id)
        rows = c.execute(f"SELECT {columns} FROM {kind} WHERE {where} ORDER BY id DESC LIMIT 5", params).fetchall()
        if resource_kind == kind and not rows:
            abort(404)
        records = []
        for row in rows:
            record = data({key: row[key] for key in FIELDS[kind] if key != "id"})
            ref = f"{kind}:{row['id']}"
            item = {"source": ref, "data": record}
            candidate = {**context, "records": {**context["records"], kind: [*records, item]}}
            if len(json.dumps(candidate, ensure_ascii=False)) > MAX_CONTEXT:
                context["limitations"].append("Contexto limitado por tamaño; no representa todos los registros.")
                break
            records.append(item)
            refs.append(ref)
        context["records"][kind] = records
    if contact_id is None and feature in ("business_overview", "pending_actions", "opportunities"):
        # Audit descriptions may contain operator details: only counts of allowlisted actions.
        for action in ("report_created", "membership_created", "report_updated"):
            count = c.execute("SELECT count(*) FROM saas_audit WHERE organization_id=? AND action=?", (actor.organization_id, action)).fetchone()[0]
            context["activity"].append({"action": action, "count": count})
    context["limitations"].append("Muestra de hasta cinco registros por categoría; no es un inventario completo.")
    if not refs:
        context["limitations"].append("Sin registros de negocio disponibles para esta función.")
    # Include metadata/limitations in the same hard budget, not just each record insertion.
    while len(json.dumps(context, ensure_ascii=False)) > MAX_CONTEXT:
        populated = [items for items in context['records'].values() if items]
        if not populated:
            raise CopilotError()
        removed = populated[-1].pop()
        refs.remove(removed['source'])
    return actor, context, tuple(refs)
