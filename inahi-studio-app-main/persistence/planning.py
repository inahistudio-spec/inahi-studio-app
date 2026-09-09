"""Read-only, credential-free inventory before any explicit conversion."""
from contextlib import closing
from persistence.database import connect, has_table, columns
from persistence.models import legacy_metadata, metadata, RESOURCE_TABLES, CORE_TABLES


def inspect_legacy(c):
    report = {"clients": 0, "organizations_to_create": 0, "users_to_create": 0,
              "memberships_to_create": 0, "conflicts": [], "incomplete": [],
              "resources": {}, "mode": "dry-run"}
    def conflict(code, **details):
        report["conflicts"].append({"code": code, **details})
    present = [name for name in legacy_metadata.tables if has_table(c, name)]
    if not present:
        report["empty_database"] = True
        return report
    for name, table in legacy_metadata.tables.items():
        missing = set(table.c.keys()) - columns(c, name) if name in present else set(table.c.keys())
        if missing:
            conflict("incomplete_schema", table=name, columns=sorted(missing))
    if report["conflicts"]:
        return report
    core_present = [name for name in CORE_TABLES if has_table(c, name)]
    if core_present:
        for name in CORE_TABLES:
            missing = set(metadata.tables[name].c.keys()) - columns(c, name) if name in core_present else set(metadata.tables[name].c.keys())
            if missing:
                conflict("incomplete_saas_schema", table=name, columns=sorted(missing))
        if report["conflicts"]:
            return report
    accounts = c.execute("SELECT id,nombre,correo,contrasena,plan,plan_key FROM clientes ORDER BY id").fetchall()
    report["clients"] = len(accounts)
    seen = set()
    from saas_schema import enabled
    core = has_table(c, "organizations") and has_table(c, "users")
    active = enabled(c)
    for row in accounts:
        email = (row["correo"] or "").strip().lower()
        if email in seen:
            conflict("duplicate_normalized_email", client_id=row["id"])
        seen.add(email)
        if not email or "@" not in email or len(email) > 254 or not (row["nombre"] or "").strip():
            report["incomplete"].append({"client_id": row["id"], "code": "name_or_email"})
        if not (row["plan_key"] or row["plan"] or "").strip():
            report["incomplete"].append({"client_id": row["id"], "code": "plan"})
        parts = (row["contrasena"] or "").split("$")
        if len(parts) != 3 or not parts[0].startswith(("pbkdf2:", "scrypt:")) or not all(parts):
            conflict("unsupported_password_hash", client_id=row["id"])
        org = c.execute("SELECT id FROM organizations WHERE legacy_cliente_id=?", (row["id"],)).fetchone() if core else None
        user = c.execute("SELECT id FROM users WHERE legacy_cliente_id=?", (row["id"],)).fetchone() if core else None
        carrier = bool(org and c.execute("SELECT 1 FROM organization_memberships WHERE organization_id=? AND role='owner'", (org[0],)).fetchone())
        if (org and not user and not carrier) or (user and not org):
            conflict("partial_identity_mapping", client_id=row["id"])
        if active and not org:
            conflict("unenrolled_active_account", client_id=row["id"])
        if core and not user and c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            conflict("existing_user_email", client_id=row["id"])
        if org and user and not c.execute("SELECT 1 FROM organization_memberships WHERE organization_id=? AND user_id=?", (org[0], user[0])).fetchone():
            conflict("missing_legacy_membership", client_id=row["id"])
        if core and not org and c.execute("SELECT 1 FROM organizations WHERE slug=?", (f"legacy-{row['id']}",)).fetchone():
            conflict("reserved_legacy_slug", client_id=row["id"])
        if not org:
            report["organizations_to_create"] += 1
        if not user and not carrier:
            report["users_to_create"] += 1
        if not org or (not user and not carrier):
            report["memberships_to_create"] += 1
        if org and "organization_id" in columns(c, "clientes"):
            linked = c.execute("SELECT organization_id FROM clientes WHERE id=?", (row["id"],)).fetchone()[0]
            if (linked is not None and linked != org[0]) or (active and linked is None):
                conflict("account_tenant_mismatch", client_id=row["id"])
    for name in RESOURCE_TABLES:
        report["resources"][name] = c.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        if c.execute(f"SELECT 1 FROM {name} r LEFT JOIN clientes c ON c.id=r.cliente_id WHERE c.id IS NULL LIMIT 1").fetchone():
            conflict("orphan_resource", table=name)
        if core and "organization_id" in columns(c, name):
            condition = "r.organization_id<>o.id" + (" OR r.organization_id IS NULL" if active else "")
            if c.execute(f"SELECT 1 FROM {name} r JOIN organizations o ON o.legacy_cliente_id=r.cliente_id WHERE {condition} LIMIT 1").fetchone():
                conflict("tenant_mismatch", table=name)
    for name in ("email_verifications", "password_resets"):
        if c.execute(f"SELECT 1 FROM {name} r LEFT JOIN clientes c ON c.id=r.cliente_id WHERE c.id IS NULL LIMIT 1").fetchone():
            conflict("orphan_credential_token", table=name)
    if core:
        if c.execute("""SELECT 1 FROM organization_memberships m LEFT JOIN organizations o ON o.id=m.organization_id
            LEFT JOIN users u ON u.id=m.user_id WHERE o.id IS NULL OR u.id IS NULL LIMIT 1""").fetchone():
            conflict("orphan_membership")
        if c.execute("SELECT 1 FROM organization_memberships GROUP BY organization_id,user_id HAVING count(*)>1").fetchone():
            conflict("duplicate_membership")
        if c.execute("SELECT 1 FROM organization_memberships WHERE role NOT IN ('owner','admin','manager','member','viewer') LIMIT 1").fetchone():
            conflict("invalid_role")
    return report


def require_clean(report):
    if report["conflicts"] or report["incomplete"]:
        raise ValueError("Migración cancelada: resolver conflictos/datos incompletos del informe")


def dry_run(legacy_path=None):
    with closing(connect(legacy_path, readonly=True)) as c:
        return inspect_legacy(c)
