"""PostgreSQL migration DDL; identifiers restricted to the frozen schema allowlist."""
from persistence.models import RESOURCE_TABLES


def backfill_sql():
    yield """INSERT INTO saas_migrations(version,enabled,applied_at)
        VALUES('0001_saas_core',0,CURRENT_TIMESTAMP) ON CONFLICT(version) DO NOTHING"""
    yield """INSERT INTO organizations(name,slug,status,plan,created_at,updated_at,legacy_cliente_id)
        SELECT nombre,'legacy-' || CAST(id AS TEXT),'active',COALESCE(NULLIF(plan_key,''),plan),
        CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,id FROM clientes c
        WHERE NOT EXISTS(SELECT 1 FROM organizations o WHERE o.legacy_cliente_id=c.id)"""
    yield """INSERT INTO users(email,password_hash,name,status,created_at,legacy_cliente_id)
        SELECT lower(trim(correo)),contrasena,nombre,'active',CURRENT_TIMESTAMP,id FROM clientes c
        WHERE NOT EXISTS(SELECT 1 FROM users u WHERE u.legacy_cliente_id=c.id)
        AND NOT EXISTS(SELECT 1 FROM organizations o JOIN organization_memberships m
          ON m.organization_id=o.id WHERE o.legacy_cliente_id=c.id)"""
    yield """INSERT INTO organization_memberships(organization_id,user_id,role,status,created_at)
        SELECT o.id,u.id,'owner','active',CURRENT_TIMESTAMP FROM organizations o
        JOIN users u ON u.legacy_cliente_id=o.legacy_cliente_id
        WHERE NOT EXISTS(SELECT 1 FROM organization_memberships m WHERE m.organization_id=o.id AND m.user_id=u.id)"""
    yield "UPDATE clientes SET organization_id=(SELECT id FROM organizations WHERE legacy_cliente_id=clientes.id) WHERE organization_id IS NULL"
    for name in RESOURCE_TABLES:
        yield f"UPDATE {name} SET organization_id=(SELECT organization_id FROM clientes WHERE id={name}.cliente_id) WHERE organization_id IS NULL"
    yield "UPDATE saas_migrations SET enabled=1 WHERE version='0001_saas_core'"


def install_guards():
    yield """CREATE OR REPLACE FUNCTION inahi_tenant_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE tenant bigint;
    BEGIN
      IF NOT EXISTS(SELECT 1 FROM saas_migrations WHERE version='0001_saas_core' AND enabled=1) THEN RETURN NEW; END IF;
      SELECT organization_id INTO tenant FROM clientes WHERE id=NEW.cliente_id;
      IF TG_OP='INSERT' AND NEW.organization_id IS NULL THEN NEW.organization_id:=tenant; END IF;
      IF tenant IS NULL OR NEW.organization_id IS DISTINCT FROM tenant THEN RAISE EXCEPTION 'tenant mismatch'; END IF;
      IF TG_OP='UPDATE' AND NEW.cliente_id IS DISTINCT FROM OLD.cliente_id THEN RAISE EXCEPTION 'immutable tenant'; END IF;
      RETURN NEW;
    END; $$"""
    for name in RESOURCE_TABLES:
        yield f"DROP TRIGGER IF EXISTS saas_{name}_guard ON {name}"
        yield f"CREATE TRIGGER saas_{name}_guard BEFORE INSERT OR UPDATE ON {name} FOR EACH ROW EXECUTE FUNCTION inahi_tenant_guard()"
    yield """CREATE OR REPLACE FUNCTION inahi_account_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF EXISTS(SELECT 1 FROM saas_migrations WHERE version='0001_saas_core' AND enabled=1) THEN
        IF TG_OP='INSERT' AND NEW.organization_id IS NOT NULL THEN RAISE EXCEPTION 'use enrollment'; END IF;
        IF TG_OP='UPDATE' AND NEW.organization_id IS DISTINCT FROM OLD.organization_id
          AND NEW.organization_id IS DISTINCT FROM (SELECT id FROM organizations WHERE legacy_cliente_id=NEW.id)
          THEN RAISE EXCEPTION 'tenant mismatch'; END IF;
      END IF;
      RETURN NEW;
    END; $$"""
    yield "DROP TRIGGER IF EXISTS saas_account_guard ON clientes"
    yield "CREATE TRIGGER saas_account_guard BEFORE INSERT OR UPDATE ON clientes FOR EACH ROW EXECUTE FUNCTION inahi_account_guard()"
    yield """CREATE OR REPLACE FUNCTION inahi_carrier_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.legacy_cliente_id IS DISTINCT FROM OLD.legacy_cliente_id THEN RAISE EXCEPTION 'immutable carrier'; END IF;
      RETURN NEW;
    END; $$"""
    yield "DROP TRIGGER IF EXISTS saas_carrier_guard ON organizations"
    yield "CREATE TRIGGER saas_carrier_guard BEFORE UPDATE ON organizations FOR EACH ROW EXECUTE FUNCTION inahi_carrier_guard()"
    yield """CREATE OR REPLACE FUNCTION inahi_legacy_sync() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.correo IS DISTINCT FROM OLD.correo OR NEW.contrasena IS DISTINCT FROM OLD.contrasena THEN
        UPDATE users SET email=lower(trim(NEW.correo)),password_hash=NEW.contrasena,
          credential_version=credential_version+CASE WHEN password_hash<>NEW.contrasena THEN 1 ELSE 0 END
          WHERE legacy_cliente_id=NEW.id;
      END IF;
      IF NEW.nombre IS DISTINCT FROM OLD.nombre OR NEW.plan IS DISTINCT FROM OLD.plan OR NEW.plan_key IS DISTINCT FROM OLD.plan_key THEN
        UPDATE organizations SET name=NEW.nombre,plan=COALESCE(NULLIF(NEW.plan_key,''),NEW.plan),updated_at=CURRENT_TIMESTAMP WHERE legacy_cliente_id=NEW.id;
      END IF;
      RETURN NEW;
    END; $$"""
    yield "DROP TRIGGER IF EXISTS saas_legacy_sync ON clientes"
    yield "CREATE TRIGGER saas_legacy_sync AFTER UPDATE ON clientes FOR EACH ROW EXECUTE FUNCTION inahi_legacy_sync()"
