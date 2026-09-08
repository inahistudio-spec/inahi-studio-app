"""Versioned, explicit SQLite expansion. No database access at import time."""

from contextlib import closing
from datetime import datetime, timezone

VERSION = "0001_saas_core"
ROLES = ("owner", "admin", "manager", "member", "viewer")
RESOURCES = ("solicitudes", "informes", "citas", "diagnosticos",
             "estrategias_comerciales", "calendarios_contenido", "resultados_mensuales")


def now():
    return datetime.now(timezone.utc).isoformat()


def enabled(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='saas_migrations'").fetchone():
        return False
    row = c.execute("SELECT enabled FROM saas_migrations WHERE version=?", (VERSION,)).fetchone()
    return bool(row and row[0])


def audit(c, action, organization_id=None, user_id=None):
    c.execute("INSERT INTO saas_audit(action,organization_id,user_id,created_at) VALUES(?,?,?,?)",
              (action, organization_id, user_id, now()))


def enroll_legacy(c, cliente_id):
    """Copy identity, never rewrite legacy credentials, subscriptions or business data."""
    account = c.execute("SELECT * FROM clientes WHERE id=?", (cliente_id,)).fetchone()
    if account is None:
        raise ValueError("Cuenta inexistente")
    organization = c.execute("SELECT id FROM organizations WHERE legacy_cliente_id=?", (cliente_id,)).fetchone()
    if organization:
        organization_id = organization[0]
    else:
        stamp = now()
        organization_id = c.execute(
            """INSERT INTO organizations(name,slug,status,plan,created_at,updated_at,legacy_cliente_id)
               VALUES(?,?,'active',?,?,?,?)""",
            (account["nombre"], f"legacy-{cliente_id}", account["plan_key"] or account["plan"], stamp, stamp, cliente_id),
        ).lastrowid
        user_id = c.execute(
            """INSERT INTO users(email,password_hash,name,status,created_at,legacy_cliente_id)
               VALUES(?,?,?,'active',?,?)""",
            (account["correo"].strip().lower(), account["contrasena"], account["nombre"], stamp, cliente_id),
        ).lastrowid
        c.execute("INSERT INTO organization_memberships(organization_id,user_id,role,status,created_at) VALUES(?,?,'owner','active',?)",
                  (organization_id, user_id, stamp))
    c.execute("UPDATE clientes SET organization_id=? WHERE id=?", (organization_id, cliente_id))
    for table in RESOURCES:
        c.execute(f"UPDATE {table} SET organization_id=? WHERE cliente_id=? AND organization_id IS NULL",
                  (organization_id, cliente_id))
    return organization_id


def upgrade(connect):
    """Transactional additive migration. The runtime never calls this function."""
    with closing(connect()) as c, c:
        c.execute("BEGIN IMMEDIATE")
        if enabled(c):
            # Accounts created outside the service are never silently adopted.
            return False
        # Refuse ambiguous identity conversion before making any schema changes.
        if c.execute("SELECT lower(trim(correo)) FROM clientes GROUP BY lower(trim(correo)) HAVING count(*)>1").fetchone():
            raise ValueError("Correos normalizados duplicados: resolver antes de migrar")
        for row in c.execute("SELECT contrasena FROM clientes"):
            parts = row[0].split("$")
            if len(parts) != 3 or not parts[0].startswith(("pbkdf2:", "scrypt:")) or not parts[1] or not parts[2]:
                raise ValueError("Hash legacy no reconocido; no se copiarán credenciales sin verificar su formato")
        for table in RESOURCES:
            if c.execute(f"SELECT 1 FROM {table} r LEFT JOIN clientes c ON c.id=r.cliente_id WHERE c.id IS NULL LIMIT 1").fetchone():
                raise ValueError("Existen recursos huérfanos; migración cancelada")
        statements = [
            """CREATE TABLE IF NOT EXISTS saas_migrations(
                version TEXT PRIMARY KEY, enabled INTEGER NOT NULL CHECK(enabled IN(0,1)), applied_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS organizations(
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL CHECK(status IN('active','suspended','archived')),
                plan TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                legacy_cliente_id INTEGER NOT NULL UNIQUE REFERENCES clientes(id) ON DELETE RESTRICT)""",
            """CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL, name TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN('active','suspended')),
                created_at TEXT NOT NULL, last_login_at TEXT,
                credential_version INTEGER NOT NULL DEFAULT 1,
                legacy_cliente_id INTEGER UNIQUE REFERENCES clientes(id) ON DELETE RESTRICT)""",
            """CREATE TABLE IF NOT EXISTS organization_memberships(
                id INTEGER PRIMARY KEY, organization_id INTEGER NOT NULL REFERENCES organizations(id),
                user_id INTEGER NOT NULL REFERENCES users(id),
                role TEXT NOT NULL CHECK(role IN('owner','admin','manager','member','viewer')),
                status TEXT NOT NULL CHECK(status IN('active','revoked')),
                created_at TEXT NOT NULL, UNIQUE(organization_id,user_id))""",
            """CREATE TABLE IF NOT EXISTS saas_audit(
                id INTEGER PRIMARY KEY, action TEXT NOT NULL, organization_id INTEGER,
                user_id INTEGER, created_at TEXT NOT NULL)""",
        ]
        for sql in statements:
            c.execute(sql)
        c.execute("INSERT OR IGNORE INTO saas_migrations(version,enabled,applied_at) VALUES(?,0,?)", (VERSION, now()))
        for table in ("clientes", *RESOURCES):
            if "organization_id" not in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
                c.execute(f"ALTER TABLE {table} ADD COLUMN organization_id INTEGER REFERENCES organizations(id)")
            c.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_organization ON {table}(organization_id)")
        for account in c.execute("SELECT id FROM clientes ORDER BY id").fetchall():
            enroll_legacy(c, account[0])
        for table in RESOURCES:
            if c.execute(f"SELECT 1 FROM {table} r JOIN clientes c ON c.id=r.cliente_id WHERE r.organization_id IS NOT c.organization_id LIMIT 1").fetchone():
                raise ValueError("Propiedad de recursos incoherente")
            # Trigger identifiers come exclusively from the fixed RESOURCES allowlist.
            c.execute(f"""CREATE TRIGGER IF NOT EXISTS saas_{table}_insert
                BEFORE INSERT ON {table}
                WHEN (SELECT enabled FROM saas_migrations WHERE version='{VERSION}')=1
                AND ((SELECT organization_id FROM clientes WHERE id=NEW.cliente_id) IS NULL
                  OR (NEW.organization_id IS NOT NULL AND NEW.organization_id IS NOT
                    (SELECT organization_id FROM clientes WHERE id=NEW.cliente_id)))
                BEGIN SELECT RAISE(ABORT,'tenant mismatch'); END""")
            c.execute(f"""CREATE TRIGGER IF NOT EXISTS saas_{table}_fill
                AFTER INSERT ON {table}
                WHEN (SELECT enabled FROM saas_migrations WHERE version='{VERSION}')=1 AND NEW.organization_id IS NULL
                BEGIN UPDATE {table} SET organization_id=(SELECT organization_id FROM clientes WHERE id=NEW.cliente_id)
                  WHERE id=NEW.id; END""")
            c.execute(f"""CREATE TRIGGER IF NOT EXISTS saas_{table}_update
                BEFORE UPDATE ON {table}
                WHEN (SELECT enabled FROM saas_migrations WHERE version='{VERSION}')=1
                AND (NEW.cliente_id IS NOT OLD.cliente_id OR NEW.organization_id IS NOT
                  (SELECT organization_id FROM clientes WHERE id=NEW.cliente_id))
                BEGIN SELECT RAISE(ABORT,'tenant mismatch'); END""")
        c.execute(f"""CREATE TRIGGER IF NOT EXISTS saas_client_organization
            BEFORE UPDATE OF organization_id ON clientes
            WHEN (SELECT enabled FROM saas_migrations WHERE version='{VERSION}')=1
            AND NEW.organization_id IS NOT (SELECT id FROM organizations WHERE legacy_cliente_id=NEW.id)
            BEGIN SELECT RAISE(ABORT,'tenant mismatch'); END""")
        c.execute(f"""CREATE TRIGGER IF NOT EXISTS saas_client_insert_organization
            BEFORE INSERT ON clientes
            WHEN (SELECT enabled FROM saas_migrations WHERE version='{VERSION}')=1 AND NEW.organization_id IS NOT NULL
            BEGIN SELECT RAISE(ABORT,'assign organization through enrollment'); END""")
        c.execute(f"""CREATE TRIGGER IF NOT EXISTS saas_organization_carrier
            BEFORE UPDATE OF legacy_cliente_id ON organizations
            WHEN (SELECT enabled FROM saas_migrations WHERE version='{VERSION}')=1
            AND NEW.legacy_cliente_id IS NOT OLD.legacy_cliente_id
            BEGIN SELECT RAISE(ABORT,'organization carrier is immutable'); END""")
        # Legacy reset/edit/Stripe flows remain the authoritative compatibility writers.
        c.execute("""CREATE TRIGGER IF NOT EXISTS saas_legacy_identity AFTER UPDATE OF correo,contrasena ON clientes
            BEGIN UPDATE users SET email=lower(trim(NEW.correo)),password_hash=NEW.contrasena,
              credential_version=credential_version + CASE WHEN password_hash<>NEW.contrasena THEN 1 ELSE 0 END
              WHERE legacy_cliente_id=NEW.id; END""")
        c.execute("""CREATE TRIGGER IF NOT EXISTS saas_legacy_plan AFTER UPDATE OF plan,plan_key ON clientes
            BEGIN UPDATE organizations SET plan=COALESCE(NULLIF(NEW.plan_key,''),NEW.plan),updated_at=CURRENT_TIMESTAMP
              WHERE legacy_cliente_id=NEW.id; END""")
        c.execute("""CREATE TRIGGER IF NOT EXISTS saas_legacy_name AFTER UPDATE OF nombre ON clientes
            BEGIN UPDATE organizations SET name=NEW.nombre,updated_at=CURRENT_TIMESTAMP
              WHERE legacy_cliente_id=NEW.id; END""")
        c.execute("UPDATE saas_migrations SET enabled=1 WHERE version=?", (VERSION,))
    return True


def downgrade(connect):
    """Return to legacy routing without deleting customers or the additive schema.

    Refuse rollback after new SaaS administrative/identity activity. The retained
    schema supports a later upgrade with stable IDs; no DROP or customer DELETE.
    """
    with closing(connect()) as c, c:
        c.execute("BEGIN IMMEDIATE")
        if not enabled(c):
            return False
        if c.execute("SELECT 1 FROM saas_audit LIMIT 1").fetchone():
            raise ValueError("Hay actividad SaaS nueva: requiere reconciliación antes de revertir")
        if c.execute("SELECT 1 FROM users WHERE legacy_cliente_id IS NULL LIMIT 1").fetchone():
            raise ValueError("Hay identidades nuevas no representables en legacy")
        if c.execute("""SELECT 1 FROM organization_memberships m JOIN users u ON u.id=m.user_id
                        JOIN organizations o ON o.id=m.organization_id
                        WHERE m.role<>'owner' OR m.status<>'active' OR u.status<>'active'
                        OR o.status<>'active' OR u.legacy_cliente_id<>o.legacy_cliente_id LIMIT 1""").fetchone():
            raise ValueError("Membresías o estados modificados; reversión cancelada")
        c.execute("UPDATE saas_migrations SET enabled=0 WHERE version=?", (VERSION,))
        for table in (*RESOURCES, "clientes"):
            c.execute(f"UPDATE {table} SET organization_id=NULL")
    return True
