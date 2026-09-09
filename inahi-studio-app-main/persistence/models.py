"""Frozen legacy schema baseline and portable SaaS SQLAlchemy Core metadata."""

import sqlalchemy as sa

NAMING = {"ix": "ix_%(table_name)s_%(column_0_name)s", "uq": "uq_%(table_name)s_%(column_0_name)s",
          "ck": "ck_%(table_name)s_%(constraint_name)s", "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
          "pk": "pk_%(table_name)s"}
legacy_metadata = sa.MetaData(naming_convention=NAMING)

calendarios_contenido = sa.Table('calendarios_contenido', legacy_metadata,
    sa.Column('id', sa.Integer, sa.Identity(), primary_key=True),
    sa.Column('cliente_id', sa.Integer, sa.ForeignKey('clientes.id'), nullable=False),
    sa.Column('periodo', sa.Text, nullable=False),
    sa.Column('contenido', sa.Text, nullable=False),
    sa.Column('creado', sa.Text, nullable=False),
    sa.UniqueConstraint('cliente_id', 'periodo'),
)

citas = sa.Table('citas', legacy_metadata,
    sa.Column('id', sa.Integer, sa.Identity(), primary_key=True),
    sa.Column('cliente_id', sa.Integer, sa.ForeignKey('clientes.id'), nullable=False),
    sa.Column('fecha', sa.Text, nullable=False),
    sa.Column('hora', sa.Text, nullable=False),
    sa.Column('modalidad', sa.Text, nullable=False),
    sa.Column('motivo', sa.Text, nullable=False),
    sa.Column('estado', sa.Text, server_default=sa.text("'Pendiente'")),
)

clientes = sa.Table('clientes', legacy_metadata,
    sa.Column('id', sa.Integer, sa.Identity(), primary_key=True),
    sa.Column('nombre', sa.Text, nullable=False),
    sa.Column('correo', sa.Text, nullable=False),
    sa.Column('contrasena', sa.Text, nullable=False),
    sa.Column('plan', sa.Text, nullable=False),
    sa.Column('activo', sa.Integer, nullable=False, server_default=sa.text('1')),
    sa.Column('plan_key', sa.Text, server_default=sa.text("''")),
    sa.Column('stripe_customer_id', sa.Text, server_default=sa.text("''")),
    sa.Column('stripe_subscription_id', sa.Text, server_default=sa.text("''")),
    sa.Column('subscription_status', sa.Text, server_default=sa.text("'sin_pago'")),
    sa.Column('creado', sa.Text, server_default=sa.text("''")),
    sa.Column('trial_end', sa.Text, server_default=sa.text("''")),
    sa.Column('email_verificado', sa.Integer, nullable=False, server_default=sa.text('1')),
    sa.Column('legal_accepted_at', sa.Text, server_default=sa.text("''")),
    sa.Column('trial_slot', sa.Integer, nullable=False, server_default=sa.text('0')),
    sa.Column('trial_queries_used', sa.Integer, nullable=False, server_default=sa.text('0')),
    sa.UniqueConstraint('correo'),
)

consultas = sa.Table('consultas', legacy_metadata,
    sa.Column('id', sa.Integer, sa.Identity(), primary_key=True),
    sa.Column('empresa', sa.Text, nullable=False),
    sa.Column('problema', sa.Text, nullable=False),
    sa.Column('correo', sa.Text, server_default=sa.text("''")),
    sa.Column('respuesta', sa.Text, server_default=sa.text("''")),
    sa.Column('token', sa.Text, server_default=sa.text("''")),
)

diagnosticos = sa.Table('diagnosticos', legacy_metadata,
    sa.Column('id', sa.Integer, sa.Identity(), primary_key=True),
    sa.Column('cliente_id', sa.Integer, sa.ForeignKey('clientes.id'), nullable=False),
    sa.Column('web', sa.Integer, nullable=False, server_default=sa.text('0')),
    sa.Column('google', sa.Integer, nullable=False, server_default=sa.text('0')),
    sa.Column('redes', sa.Integer, nullable=False, server_default=sa.text('0')),
    sa.Column('resenas', sa.Integer, nullable=False, server_default=sa.text('0')),
    sa.Column('objetivos', sa.Text, server_default=sa.text("''")),
    sa.Column('puntuacion', sa.Integer, nullable=False, server_default=sa.text('0')),
    sa.Column('actualizado', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
    sa.UniqueConstraint('cliente_id'),
)

email_verifications = sa.Table('email_verifications', legacy_metadata,
    sa.Column('token', sa.Text, primary_key=True),
    sa.Column('cliente_id', sa.Integer, sa.ForeignKey('clientes.id'), nullable=False),
    sa.Column('expira', sa.DateTime(timezone=True), nullable=False),
    sa.Column('usado', sa.Integer, nullable=False, server_default=sa.text('0')),
)

estrategias_comerciales = sa.Table('estrategias_comerciales', legacy_metadata,
    sa.Column('id', sa.Integer, sa.Identity(), primary_key=True),
    sa.Column('cliente_id', sa.Integer, sa.ForeignKey('clientes.id'), nullable=False),
    sa.Column('respuestas', sa.Text, nullable=False),
    sa.Column('estrategia', sa.Text, nullable=False),
    sa.Column('actualizado', sa.Text, nullable=False),
    sa.UniqueConstraint('cliente_id'),
)

informes = sa.Table('informes', legacy_metadata,
    sa.Column('id', sa.Integer, sa.Identity(), primary_key=True),
    sa.Column('cliente_id', sa.Integer, sa.ForeignKey('clientes.id'), nullable=False),
    sa.Column('titulo', sa.Text, nullable=False),
    sa.Column('contenido', sa.Text, nullable=False),
    sa.Column('fecha', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
)

password_resets = sa.Table('password_resets', legacy_metadata,
    sa.Column('token', sa.Text, primary_key=True),
    sa.Column('cliente_id', sa.Integer, sa.ForeignKey('clientes.id'), nullable=False),
    sa.Column('expira', sa.DateTime(timezone=True), nullable=False),
    sa.Column('usado', sa.Integer, nullable=False, server_default=sa.text('0')),
)

rate_limits = sa.Table('rate_limits', legacy_metadata,
    sa.Column('clave', sa.Text, primary_key=True),
    sa.Column('inicio', sa.Integer, nullable=False),
    sa.Column('intentos', sa.Integer, nullable=False, server_default=sa.text('0')),
)

resultados_mensuales = sa.Table('resultados_mensuales', legacy_metadata,
    sa.Column('id', sa.Integer, sa.Identity(), primary_key=True),
    sa.Column('cliente_id', sa.Integer, sa.ForeignKey('clientes.id'), nullable=False),
    sa.Column('periodo', sa.Text, nullable=False),
    sa.Column('contactos', sa.Integer, nullable=False, server_default=sa.text('0')),
    sa.Column('ventas', sa.Integer, nullable=False, server_default=sa.text('0')),
    sa.Column('ingresos', sa.Float, nullable=False, server_default=sa.text('0')),
    sa.Column('resenas', sa.Integer, nullable=False, server_default=sa.text('0')),
    sa.Column('notas', sa.Text, server_default=sa.text("''")),
    sa.Column('informe', sa.Text, nullable=False),
    sa.Column('creado', sa.Text, nullable=False),
    sa.UniqueConstraint('cliente_id', 'periodo'),
)

servicios_solicitados = sa.Table('servicios_solicitados', legacy_metadata,
    sa.Column('id', sa.Integer, sa.Identity(), primary_key=True),
    sa.Column('servicio_key', sa.Text, nullable=False),
    sa.Column('servicio_nombre', sa.Text, nullable=False),
    sa.Column('precio', sa.Text, nullable=False),
    sa.Column('nombre', sa.Text, nullable=False),
    sa.Column('empresa', sa.Text, nullable=False),
    sa.Column('correo', sa.Text, nullable=False),
    sa.Column('telefono', sa.Text, server_default=sa.text("''")),
    sa.Column('mensaje', sa.Text, server_default=sa.text("''")),
    sa.Column('estado', sa.Text, nullable=False, server_default=sa.text("'Nueva'")),
    sa.Column('fecha', sa.Text, nullable=False),
)

solicitudes = sa.Table('solicitudes', legacy_metadata,
    sa.Column('id', sa.Integer, sa.Identity(), primary_key=True),
    sa.Column('cliente_id', sa.Integer, sa.ForeignKey('clientes.id'), nullable=False),
    sa.Column('asunto', sa.Text, nullable=False),
    sa.Column('descripcion', sa.Text, nullable=False),
    sa.Column('respuesta', sa.Text, server_default=sa.text("''")),
    sa.Column('estado', sa.Text, server_default=sa.text("'Pendiente'")),
    sa.Column('fecha', sa.Text, server_default=sa.text("''")),
    sa.Column('origen_respuesta', sa.Text, server_default=sa.text("'automatizacion'")),
)

stripe_webhook_events = sa.Table('stripe_webhook_events', legacy_metadata,
    sa.Column('event_id', sa.Text, primary_key=True),
    sa.Column('event_type', sa.Text, nullable=False),
    sa.Column('processed_at', sa.Text, nullable=False),
)

metadata = sa.MetaData(naming_convention=NAMING)
for table in legacy_metadata.tables.values():
    table.to_metadata(metadata)

organizations = sa.Table("organizations", metadata,
    sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("slug", sa.String(80), nullable=False, unique=True),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("plan", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("legacy_cliente_id", sa.Integer, sa.ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=False, unique=True),
    sa.CheckConstraint("status IN ('active','suspended','archived')", name="status"),
    sa.CheckConstraint("length(trim(name)) > 0", name="name"),
    sa.CheckConstraint("slug=lower(slug) AND length(slug)>0", name="slug"),
)
users = sa.Table("users", metadata,
    sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
    sa.Column("email", sa.String(254), nullable=False, unique=True),
    sa.Column("password_hash", sa.Text, nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_login_at", sa.DateTime(timezone=True)),
    sa.Column("credential_version", sa.Integer, nullable=False, server_default=sa.text("1")),
    sa.Column("legacy_cliente_id", sa.Integer, sa.ForeignKey("clientes.id", ondelete="RESTRICT"), unique=True),
    sa.CheckConstraint("status IN ('active','suspended')", name="status"),
    sa.CheckConstraint("email=lower(trim(email)) AND length(email)>0", name="normalized_email"),
    sa.CheckConstraint("length(password_hash)>0", name="password_hash"),
)
organization_memberships = sa.Table("organization_memberships", metadata,
    sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
    sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("role", sa.String(16), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("organization_id", "user_id"),
    sa.CheckConstraint("role IN ('owner','admin','manager','member','viewer')", name="role"),
    sa.CheckConstraint("status IN ('active','revoked')", name="status"),
)
saas_migrations = sa.Table("saas_migrations", metadata,
    sa.Column("version", sa.String(80), primary_key=True),
    sa.Column("enabled", sa.Integer, nullable=False),
    sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("enabled IN (0,1)", name="enabled"),
)
saas_audit = sa.Table("saas_audit", metadata,
    sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
    sa.Column("action", sa.Text, nullable=False),
    sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="RESTRICT")),
    sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="RESTRICT")),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
RESOURCE_TABLES = ("solicitudes", "informes", "citas", "diagnosticos",
                   "estrategias_comerciales", "calendarios_contenido", "resultados_mensuales")
for name in ("clientes", *RESOURCE_TABLES):
    table = metadata.tables[name]
    table.append_column(sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="RESTRICT")))
    sa.Index(f"ix_{name}_organization", table.c.organization_id)
metadata.tables["clientes"].append_constraint(sa.UniqueConstraint("organization_id", "id", name="uq_clientes_organization_id_id"))
for name in RESOURCE_TABLES:
    metadata.tables[name].append_constraint(sa.ForeignKeyConstraint(
        ["organization_id", "cliente_id"], ["clientes.organization_id", "clientes.id"],
        name=f"fk_{name}_tenant_account", ondelete="RESTRICT"))
sa.Index("ix_memberships_user", organization_memberships.c.user_id, organization_memberships.c.status)
sa.Index("ix_memberships_organization", organization_memberships.c.organization_id)
sa.Index("ix_audit_organization_created", saas_audit.c.organization_id, saas_audit.c.created_at)
CORE_TABLES = ("organizations", "users", "organization_memberships", "saas_migrations", "saas_audit")
ID_TABLES = frozenset(name for name, table in metadata.tables.items() if "id" in table.c)

# Preserve SQLite's signed 64-bit identifiers on the PostgreSQL target.
for catalog in (legacy_metadata, metadata):
    for table in catalog.tables.values():
        for column in table.c:
            if column.name in ("id", "cliente_id", "legacy_cliente_id", "organization_id", "user_id"):
                column.type = sa.BigInteger().with_variant(sa.Integer, "sqlite")
organizations.append_constraint(sa.CheckConstraint(
    "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format").ddl_if(dialect="postgresql"))
