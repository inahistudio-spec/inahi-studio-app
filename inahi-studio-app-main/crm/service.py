"""All CRM reads/writes take server-resolved actors, rechecked for every mutation."""
from datetime import datetime, timezone, timedelta
from flask import abort
from crm import policy
from saas_schema import now, audit
from billing.entitlements import reserve
from billing.repository import subscription

CONTACT_FIELDS = ("company_name","contact_name","email","phone","website","source","status","owner_user_id","notes","last_contact_at","next_followup_at")
OPPORTUNITY_FIELDS = ("title","stage","estimated_value","probability","expected_close_date","owner_user_id")


def get_contact(c, actor, cid, lock=False):
    suffix = " FOR UPDATE" if lock and getattr(c, "dialect", "sqlite") == "postgresql" else ""
    row = c.execute("SELECT * FROM crm_contacts WHERE organization_id=? AND id=? AND archived_at IS NULL" + suffix, (actor.organization_id, policy.integer(cid))).fetchone()
    if not row:
        abort(404)
    return dict(row)


def owner(c, actor, uid):
    if uid is not None and not c.execute("SELECT 1 FROM organization_memberships m JOIN users u ON u.id=m.user_id WHERE m.organization_id=? AND m.user_id=? AND m.status='active' AND u.status='active'", (actor.organization_id, uid)).fetchone():
        abort(404)


def members(c, actor):
    return [dict(row) for row in c.execute("SELECT u.id,u.name FROM organization_memberships m JOIN users u ON u.id=m.user_id WHERE m.organization_id=? AND m.status='active' AND u.status='active' ORDER BY u.name", (actor.organization_id,))]


def save_contact(c, values, cid=None):
    actor = policy.authorize(c, "edit")
    old = get_contact(c, actor, cid, True) if cid is not None else None
    fields = policy.contact_fields(values)
    owner(c, actor, fields["owner_user_id"])
    stamp = now()
    if old is None:
        if not subscription(c, actor.organization_id, lock=True):
            abort(503)
        reserve(c, actor.organization_id, "clients")
        cid = c.execute(f"INSERT INTO crm_contacts(organization_id,{','.join(CONTACT_FIELDS)},created_at,updated_at) VALUES({','.join('?' for _ in range(len(CONTACT_FIELDS)+3))}) RETURNING id", (actor.organization_id, *[fields[key] for key in CONTACT_FIELDS], stamp, stamp)).fetchone()[0]
    else:
        c.execute(f"UPDATE crm_contacts SET {','.join(key+'=?' for key in CONTACT_FIELDS)},updated_at=? WHERE organization_id=? AND id=?", (*[fields[key] for key in CONTACT_FIELDS], stamp, actor.organization_id, cid))
    audit(c, "crm_contact_created" if old is None else "crm_contact_updated", actor.organization_id, actor.user_id)
    return cid


def archive_contact(c, cid):
    actor = policy.authorize(c, "delete")
    get_contact(c, actor, cid, True)
    c.execute("UPDATE crm_contacts SET archived_at=?,updated_at=? WHERE organization_id=? AND id=?", (now(), now(), actor.organization_id, cid))
    audit(c, "crm_contact_archived", actor.organization_id, actor.user_id)


def activity(c, cid, values):
    actor = policy.authorize(c)
    contact = get_contact(c, actor, cid, True)
    if actor.role not in policy.EDIT_ROLES and not (actor.role == "member" and contact["owner_user_id"] == actor.user_id):
        abort(403)
    kind = policy.choice(values.get("type"), policy.ACTIVITY_TYPES)
    description = policy.text(values.get("description", ""), 6000, True)
    occurred = policy.stamp(values.get("occurred_at")) or now()
    if occurred > now():
        raise ValueError("La actividad no puede estar en el futuro")
    aid = c.execute("INSERT INTO crm_activities(organization_id,contact_id,user_id,type,description,occurred_at,created_at) VALUES(?,?,?,?,?,?,?) RETURNING id", (actor.organization_id,cid,actor.user_id,kind,description,occurred,now())).fetchone()[0]
    if kind != "note":
        c.execute("UPDATE crm_contacts SET last_contact_at=CASE WHEN last_contact_at IS NULL OR last_contact_at<? THEN ? ELSE last_contact_at END,updated_at=? WHERE organization_id=? AND id=?", (occurred,occurred,now(),actor.organization_id,cid))
    if "next_followup_at" in values:
        c.execute("UPDATE crm_contacts SET next_followup_at=?,updated_at=? WHERE organization_id=? AND id=?", (policy.stamp(values["next_followup_at"]),now(),actor.organization_id,cid))
    audit(c, "crm_activity_created", actor.organization_id,actor.user_id)
    return aid


def get_opportunity(c, actor, oid):
    row = c.execute("SELECT o.* FROM crm_opportunities o JOIN crm_contacts t ON t.id=o.contact_id AND t.organization_id=o.organization_id WHERE o.organization_id=? AND o.id=? AND t.archived_at IS NULL", (actor.organization_id, policy.integer(oid))).fetchone()
    if not row:
        abort(404)
    return dict(row)


def save_opportunity(c, values, cid=None, oid=None):
    actor = policy.authorize(c, "edit")
    if oid is not None:
        old = get_opportunity(c, actor, oid)
        cid = old["contact_id"]
    get_contact(c, actor, cid, True)
    fields = policy.opportunity_fields(values)
    owner(c, actor, fields["owner_user_id"])
    stamp = now()
    if oid is None:
        oid = c.execute(f"INSERT INTO crm_opportunities(organization_id,contact_id,{','.join(OPPORTUNITY_FIELDS)},created_at,updated_at) VALUES({','.join('?' for _ in range(len(OPPORTUNITY_FIELDS)+4))}) RETURNING id", (actor.organization_id,cid,*[fields[key] for key in OPPORTUNITY_FIELDS],stamp,stamp)).fetchone()[0]
    else:
        c.execute(f"UPDATE crm_opportunities SET {','.join(key+'=?' for key in OPPORTUNITY_FIELDS)},updated_at=? WHERE organization_id=? AND id=?", (*[fields[key] for key in OPPORTUNITY_FIELDS],stamp,actor.organization_id,oid))
    audit(c, "crm_opportunity_changed", actor.organization_id,actor.user_id)
    return cid, oid


def flags(contact, instant=None):
    instant = instant or datetime.now(timezone.utc)
    def parse(value):
        if not value:
            return None
        result = datetime.fromisoformat(str(value))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    upcoming = parse(contact.get("next_followup_at"))
    dates = [parse(contact.get(key)) for key in ("last_activity_at", "last_contact_at", "created_at")]
    recent = max(date for date in dates if date is not None)
    active = contact["status"] != "inactive"
    return {"overdue": bool(active and upcoming and upcoming < instant),
            "upcoming": bool(active and upcoming and instant <= upcoming <= instant + timedelta(days=7)),
            "stale": bool(active and recent < instant - timedelta(days=30)),
            "uncontacted": bool(contact["status"] == "lead" and not contact.get("last_contact_at"))}


def contact_query():
    return """SELECT t.*,u.name AS owner_name,
        (SELECT max(a.occurred_at) FROM crm_activities a WHERE a.organization_id=t.organization_id AND a.contact_id=t.id) AS last_activity_at,
        (SELECT count(*) FROM crm_opportunities o WHERE o.organization_id=t.organization_id AND o.contact_id=t.id AND o.stage NOT IN ('won','lost')) AS opportunities,
        (SELECT COALESCE(sum(o.estimated_value),0) FROM crm_opportunities o WHERE o.organization_id=t.organization_id AND o.contact_id=t.id AND o.stage NOT IN ('won','lost')) AS pipeline_value
        FROM crm_contacts t LEFT JOIN users u ON u.id=t.owner_user_id WHERE t.organization_id=? AND t.archived_at IS NULL"""


def contacts(c, actor, filters=None):
    filters = filters or {}
    if set(filters) - {"q","status","owner","followup","page"}:
        raise ValueError("Filtro inválido")
    query, args = contact_query(), [actor.organization_id]
    search = policy.text(filters.get("q", ""), 120)
    if search:
        term = "%" + search.lower().replace("!","!!").replace("%","!%").replace("_","!_") + "%"
        query += " AND (lower(t.company_name) LIKE ? ESCAPE '!' OR lower(t.contact_name) LIKE ? ESCAPE '!' OR lower(t.email) LIKE ? ESCAPE '!')"
        args.extend([term]*3)
    if filters.get("status"):
        query += " AND t.status=?"
        args.append(policy.choice(filters["status"], policy.STATUSES))
    if filters.get("owner"):
        uid = policy.integer(filters["owner"])
        owner(c, actor, uid)
        query += " AND t.owner_user_id=?"
        args.append(uid)
    if filters.get("followup"):
        kind = policy.choice(filters["followup"], ("overdue","upcoming","stale","uncontacted"))
        instant = datetime.now(timezone.utc)
        if kind == 'uncontacted':
            query += " AND t.status='lead' AND t.last_contact_at IS NULL"
        else:
            query += " AND t.status<>'inactive'"
            if kind == 'overdue':
                query += " AND t.next_followup_at<?"
                args.append(instant.isoformat())
            elif kind == 'upcoming':
                query += " AND t.next_followup_at>=? AND t.next_followup_at<=?"
                args.extend((instant.isoformat(), (instant+timedelta(days=7)).isoformat()))
            else:
                cutoff = (instant-timedelta(days=30)).isoformat()
                query += " AND t.created_at<? AND (t.last_contact_at IS NULL OR t.last_contact_at<?) AND NOT EXISTS(SELECT 1 FROM crm_activities a WHERE a.organization_id=t.organization_id AND a.contact_id=t.id AND a.occurred_at>=?)"
                args.extend((cutoff,cutoff,cutoff))
    page = policy.integer(filters.get("page", "1"))
    if page > 10000000:
        raise ValueError('Invalid page')
    count = c.execute('SELECT count(*) FROM (' + query + ') AS filtered', args).fetchone()[0]
    rows = [dict(row) for row in c.execute(query + ' ORDER BY t.id DESC LIMIT 25 OFFSET ?', (*args,(page-1)*25))]
    for row in rows:
        row['flags'] = flags(row)
    return rows, count, page


def pipeline(c, actor):
    return [dict(row) for row in c.execute("SELECT o.*,t.company_name,t.contact_name,u.name AS owner_name FROM crm_opportunities o JOIN crm_contacts t ON t.id=o.contact_id AND t.organization_id=o.organization_id LEFT JOIN users u ON u.id=o.owner_user_id WHERE o.organization_id=? AND t.archived_at IS NULL ORDER BY o.probability DESC,o.id DESC LIMIT 200", (actor.organization_id,))]


def detail(c, actor, cid):
    contact = get_contact(c, actor, cid)
    activities = [dict(row) for row in c.execute("SELECT a.*,u.name AS author FROM crm_activities a JOIN users u ON u.id=a.user_id WHERE a.organization_id=? AND a.contact_id=? ORDER BY a.occurred_at DESC,a.id DESC LIMIT 100", (actor.organization_id,cid))]
    contact["last_activity_at"] = activities[0]["occurred_at"] if activities else None
    opportunities = [dict(row) for row in c.execute("SELECT * FROM crm_opportunities WHERE organization_id=? AND contact_id=? ORDER BY id DESC LIMIT 100", (actor.organization_id,cid))]
    return contact, activities, opportunities, flags(contact)


def overview(c, actor):
    if not policy.enabled(c):
        return None
    instant = datetime.now(timezone.utc)
    stamp, soon, stale = instant.isoformat(), (instant+timedelta(days=7)).isoformat(), (instant-timedelta(days=30)).isoformat()
    row = c.execute("""SELECT count(*) AS contacts,
        COALESCE(sum(CASE WHEN status='lead' THEN 1 ELSE 0 END),0) AS leads,
        COALESCE(sum(CASE WHEN status<>'inactive' AND next_followup_at<? THEN 1 ELSE 0 END),0) AS overdue,
        COALESCE(sum(CASE WHEN status<>'inactive' AND next_followup_at>=? AND next_followup_at<=? THEN 1 ELSE 0 END),0) AS upcoming,
        COALESCE(sum(CASE WHEN status='lead' AND last_contact_at IS NULL THEN 1 ELSE 0 END),0) AS uncontacted
        FROM crm_contacts WHERE organization_id=? AND archived_at IS NULL""", (stamp,stamp,soon,actor.organization_id)).fetchone()
    opened = c.execute("SELECT count(*) AS opportunities,COALESCE(sum(o.estimated_value),0) AS pipeline_value FROM crm_opportunities o JOIN crm_contacts t ON t.id=o.contact_id AND t.organization_id=o.organization_id WHERE o.organization_id=? AND t.archived_at IS NULL AND o.stage NOT IN ('won','lost')", (actor.organization_id,)).fetchone()
    inactive = c.execute("""SELECT count(*) FROM crm_contacts t WHERE t.organization_id=? AND t.archived_at IS NULL AND t.status<>'inactive'
        AND t.created_at<? AND (t.last_contact_at IS NULL OR t.last_contact_at<?)
        AND NOT EXISTS(SELECT 1 FROM crm_activities a WHERE a.organization_id=t.organization_id AND a.contact_id=t.id AND a.occurred_at>=?)""", (actor.organization_id,stale,stale,stale)).fetchone()[0]
    recent = [dict(r) for r in c.execute("SELECT a.type,a.description,a.occurred_at,t.id AS contact_id,t.company_name,t.contact_name FROM crm_activities a JOIN crm_contacts t ON t.id=a.contact_id AND t.organization_id=a.organization_id WHERE a.organization_id=? AND t.archived_at IS NULL ORDER BY a.occurred_at DESC,a.id DESC LIMIT 5", (actor.organization_id,))]
    return {**dict(row), **dict(opened), "stale": inactive, "recent": recent}
