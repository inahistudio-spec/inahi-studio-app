"""Tenant identity, authorization and compatibility services (no import I/O)."""

from contextlib import closing
from dataclasses import dataclass
from functools import wraps
import re
import secrets

from flask import abort, session
from werkzeug.security import check_password_hash, generate_password_hash

from saas_schema import ROLES, audit, enabled, enroll_legacy, now

PERMISSIONS = {
    "owner": frozenset(("read", "write", "request", "billing", "members", "ownership")),
    "admin": frozenset(("read", "write", "request", "billing", "members")),
    "manager": frozenset(("read", "write", "request")),
    "member": frozenset(("read", "request")),
    "viewer": frozenset(("read",)),
}


@dataclass(frozen=True)
class TenantContext:
    organization_id: int
    user_id: int
    membership_id: int
    role: str
    cliente_id: int

    def require(self, permission):
        if permission not in PERMISSIONS.get(self.role, ()):
            abort(403)


def resolve_context(c, permission="read", product=True):
    if not enabled(c):
        abort(404)
    uid, oid = session.get("user_id"), session.get("organization_id")
    if not uid or not oid:
        session.clear()
        abort(401)
    row = c.execute("""SELECT m.id,m.role,m.status AS membership_status,u.status AS user_status,
        u.credential_version,o.status AS organization_status,o.legacy_cliente_id,c.activo,c.email_verificado,
        c.subscription_status,c.trial_end FROM organization_memberships m
        JOIN users u ON u.id=m.user_id JOIN organizations o ON o.id=m.organization_id
        JOIN clientes c ON c.id=o.legacy_cliente_id
        WHERE m.user_id=? AND m.organization_id=?""", (uid, oid)).fetchone()
    if not row:
        abort(404)
    if (row["membership_status"] != "active" or row["user_status"] != "active"
            or row["organization_status"] != "active"
            or session.get("credential_version") != row["credential_version"]):
        abort(403)
    if not row["email_verificado"]:
        abort(403)
    if product:
        from datetime import date
        if not row["activo"]:
            abort(403)
        if row["subscription_status"] == "prueba" and row["trial_end"] and row["trial_end"] < date.today().isoformat():
            abort(403)
    context = TenantContext(oid, uid, row["id"], row["role"], row["legacy_cliente_id"])
    context.require(permission)
    # Old controllers only ever see the server-resolved carrier account.
    session["cliente_id"] = context.cliente_id
    return context


def tenant_required(connect, permission="read", product=True):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with closing(connect()) as c:
                context = resolve_context(c, permission, product)
            return fn(context, *args, **kwargs)
        return wrapped
    return decorate


def platform_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        # Only the pre-existing INAHI /acceso login sets this signed flag.
        # Tenant identities, including owners, are never platform operators.
        if not session.get("administrador") or session.get("user_id"):
            abort(403)
        return fn(*args, **kwargs)
    return wrapped


def authenticate(c, email, password):
    user = c.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    if not user or user["status"] != "active" or not check_password_hash(user["password_hash"], password):
        return None
    membership = c.execute("""SELECT m.organization_id,o.legacy_cliente_id FROM organization_memberships m
        JOIN organizations o ON o.id=m.organization_id JOIN clientes c ON c.id=o.legacy_cliente_id
        WHERE m.user_id=? AND m.status='active'
        AND o.status='active' ORDER BY c.activo DESC,m.id LIMIT 1""", (user["id"],)).fetchone()
    if not membership:
        return None
    c.execute("UPDATE users SET last_login_at=? WHERE id=?", (now(), user["id"]))
    return {"user_id": user["id"], "organization_id": membership["organization_id"],
            "cliente_id": membership["legacy_cliente_id"], "credential_version": user["credential_version"]}


def enroll_if_enabled(c, cliente_id):
    if enabled(c):
        oid = enroll_legacy(c, cliente_id)
        audit(c, "legacy_account_created", oid)


def create_user(c, email, password, name):
    email, name = email.strip().lower(), name.strip()
    if not name or len(name) > 120 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
        raise ValueError("Nombre o correo inválido")
    if not isinstance(password, str) or not 8 <= len(password) <= 256:
        raise ValueError("La contraseña debe tener entre 8 y 256 caracteres")
    uid = c.execute("INSERT INTO users(email,password_hash,name,status,created_at) VALUES(?,?,?,'active',?)",
                    (email, generate_password_hash(password), name, now())).lastrowid
    audit(c, "user_created", user_id=uid)
    return uid


def create_organization(c, name, slug, plan, owner_id, plans):
    if not name.strip() or len(name) > 120 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or len(slug) > 80 or slug.startswith("legacy-"):
        raise ValueError("Nombre o slug inválido")
    if plan not in plans:
        raise ValueError("Plan inválido")
    if not c.execute("SELECT 1 FROM users WHERE id=? AND status='active'", (owner_id,)).fetchone():
        raise ValueError("Owner inválido")
    stamp = now()
    # Carrier preserves all existing product flows and billing columns. It is not a login identity.
    cid = c.execute("""INSERT INTO clientes(nombre,correo,contrasena,plan,plan_key,activo,
        subscription_status,email_verificado,creado) VALUES(?,?,?,?,?,1,'sin_pago',1,?)""",
        (name.strip(), f"{secrets.token_hex(16)}@accounts.invalid", generate_password_hash(secrets.token_urlsafe(48)),
         name_for_plan(plan, plans), plan, stamp)).lastrowid
    oid = c.execute("""INSERT INTO organizations(name,slug,status,plan,created_at,updated_at,legacy_cliente_id)
        VALUES(?,?,'active',?,?,?,?)""", (name.strip(), slug, plan, stamp, stamp, cid)).lastrowid
    c.execute("UPDATE clientes SET organization_id=? WHERE id=?", (oid, cid))
    c.execute("INSERT INTO organization_memberships(organization_id,user_id,role,status,created_at) VALUES(?,?,'owner','active',?)",
              (oid, owner_id, stamp))
    audit(c, "organization_created", oid, owner_id)
    return oid


def name_for_plan(plan, plans):
    info = plans[plan]
    return f"Plan {info['nombre']} — {info['precio']} €/mes"


def add_membership(c, organization_id, user_id, role):
    if role not in ROLES:
        raise ValueError("Rol inválido")
    if not c.execute("SELECT 1 FROM organizations WHERE id=? AND status='active'", (organization_id,)).fetchone():
        raise ValueError("Organización inválida")
    if not c.execute("SELECT 1 FROM users WHERE id=? AND status='active'", (user_id,)).fetchone():
        raise ValueError("Usuario inválido")
    mid = c.execute("INSERT INTO organization_memberships(organization_id,user_id,role,status,created_at) VALUES(?,?,?,'active',?)",
                    (organization_id, user_id, role, now())).lastrowid
    audit(c, "membership_created", organization_id, user_id)
    return mid


def change_membership(c, context, membership_id, role, status):
    context.require("members")
    if role not in ROLES or status not in ("active", "revoked"):
        raise ValueError("Rol o estado inválido")
    target = c.execute("SELECT * FROM organization_memberships WHERE id=? AND organization_id=?",
                       (membership_id, context.organization_id)).fetchone()
    if not target:
        abort(404)
    if context.role != "owner" and (target["role"] == "owner" or role == "owner"):
        abort(403)
    if target["role"] == "owner" and target["status"] == "active" and (role != "owner" or status != "active"):
        owners = c.execute("""SELECT count(*) FROM organization_memberships m JOIN users u ON u.id=m.user_id
            WHERE m.organization_id=? AND m.role='owner' AND m.status='active' AND u.status='active'""",
                           (context.organization_id,)).fetchone()[0]
        if owners <= 1:
            raise ValueError("No se puede retirar al último owner activo")
    c.execute("UPDATE organization_memberships SET role=?,status=? WHERE id=? AND organization_id=?",
              (role, status, membership_id, context.organization_id))
    audit(c, "membership_changed", context.organization_id, context.user_id)


def change_password(c, context, old_password, new_password):
    user = c.execute("SELECT * FROM users WHERE id=?", (context.user_id,)).fetchone()
    if not check_password_hash(user["password_hash"], old_password) or not 8 <= len(new_password) <= 256:
        raise ValueError("Contraseña actual incorrecta o nueva contraseña inválida")
    hashed = generate_password_hash(new_password)
    if user["legacy_cliente_id"]:
        # The compatibility trigger updates User and credential_version atomically.
        c.execute("UPDATE clientes SET contrasena=? WHERE id=?", (hashed, user["legacy_cliente_id"]))
    else:
        c.execute("UPDATE users SET password_hash=?,credential_version=credential_version+1 WHERE id=?", (hashed, context.user_id))
    audit(c, "password_changed", context.organization_id, context.user_id)
    session["credential_version"] = c.execute("SELECT credential_version FROM users WHERE id=?", (context.user_id,)).fetchone()[0]
