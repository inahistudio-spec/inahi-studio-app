"""Fictional contacts for the owned disposable demo database only."""
from datetime import datetime, timezone, timedelta
from billing.entitlements import reserve


def seed(c):
    instant = datetime.now(timezone.utc)
    stamp = instant.isoformat()
    for organization, company, status, days, stage, probability, amount in (
        (1, 'Atelier Oliva · DEMO', 'prospect', -2, 'proposal', 65, 1800),
        (1, 'Librería Horizonte · DEMO', 'lead', 3, 'contacted', 25, 600),
        (1, 'Taller Brisa · DEMO', 'lead', -5, 'new', 10, 350),
        (2, 'Contacto privado B · DEMO', 'prospect', -1, 'negotiation', 85, 9000),
    ):
        reserve(c, organization, 'clients')
        cid = c.execute("INSERT INTO crm_contacts(organization_id,company_name,contact_name,status,owner_user_id,notes,created_at,updated_at,next_followup_at,source) VALUES(?,?,?,?,?,?,?,?,?,?) RETURNING id", (organization, company, 'Contacto ficticio', status, organization, 'Datos ficticios para explorar el CRM. Pendiente validar necesidades y presupuesto.', (instant-timedelta(days=45)).isoformat(), stamp, (instant+timedelta(days=days)).isoformat(), 'Demostración local')).fetchone()[0]
        c.execute("INSERT INTO crm_opportunities(organization_id,contact_id,title,stage,estimated_value,probability,owner_user_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", (organization,cid,'Propuesta de acompañamiento · DEMO',stage,amount,probability,organization,stamp,stamp))
        if status == 'prospect':
            c.execute("INSERT INTO crm_activities(organization_id,contact_id,user_id,type,description,occurred_at,created_at) VALUES(?,?,?,?,?,?,?)", (organization,cid,organization,'meeting','Reunión ficticia: interés en mejorar la captación.',(instant-timedelta(days=4)).isoformat(),stamp))
            c.execute('UPDATE crm_contacts SET last_contact_at=? WHERE organization_id=? AND id=?', ((instant-timedelta(days=4)).isoformat(),organization,cid))
