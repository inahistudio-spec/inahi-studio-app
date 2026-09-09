# Inventario SQL — Fase 2

Revisión estática de todos los módulos Python de la aplicación, sin consultar bases reales.

| Archivo | Llamadas SQL / constantes | Dependencia y tratamiento |
|---|---:|---|
| app.py | 103 | Consultas extraídas al catálogo; conserva orquestación de controladores. |
| automatizacion.py / ia.py | 0 | Sin SQL. |
| billing_webhooks.py | 5 | ON CONFLICT para deduplicación; evento y efectos en una transacción. |
| persistence/database.py | 10 | PRAGMA/sqlite_master aislados por dialecto; binds, RETURNING y transacciones SQLAlchemy. |
| persistence/legacy_schema.py | 10 | CREATE/ALTER y PRAGMA table_info: solo inicialización SQLite explícita. |
| persistence/migrations.py | 2 | Advisory lock y locks PostgreSQL; Alembic explícito. |
| persistence/models.py | 0 | Catálogo Core de tipos, relaciones, constraints e índices. |
| persistence/planning.py | 15 | SELECT e inspección del esquema; identificadores del catálogo fijo. |
| persistence/postgres_guards.py | 0 | Genera backfill y triggers PL/pgSQL para las revisiones. |
| persistence/queries.py | 103 | SQL parametrizado del producto. ON CONFLICT compatible; DDL init-db solo SQLite. |
| persistence/repositories.py | 2 | LIKE SQLite / ILIKE PostgreSQL, valores enlazados. |
| saas_core.py | 20 | Servicios de identidad/permisos con SQL estándar y parámetros. |
| saas_routes.py | 16 | Recursos por ID + organización, tablas en allowlist. |
| saas_schema.py | 36 | Migración histórica y triggers SQLite; Alembic reutiliza lógica sin commit interno. |
| migrations/versions/0001_legacy_baseline.py | DDL Core | Crea/adopta baseline; no permite DROP automático. |
| migrations/versions/0002_saas_core.py | DDL Alembic | Expansión por dialecto, backfill y guards; rollback lógico. |

Los conteos son llamadas estáticas, no consultas emitidas: bucles y metadatos generan varias sentencias. No se incluyen tests ni dependencias de .venv.

Dependencias revisadas:

- INTEGER PRIMARY KEY/lastrowid: PostgreSQL BIGINT IDENTITY/RETURNING; no se renumeran IDs legacy.
- Parámetros ?: conversión a parámetros nombrados respetando literales entre comillas. No es un traductor de SQL arbitrario; solo admite SQL conocido de los servicios.
- COLLATE NOCASE: correo normalizado en el servicio, UNIQUE/CHECK en el esquema objetivo. Búsquedas LIKE/ILIKE seleccionadas en repositorios.
- sqlite_master/PRAGMA: inspector SQLAlchemy en PostgreSQL, funciones específicas para SQLite.
- INSERT OR IGNORE: solo migración histórica SQLite; PostgreSQL usa ON CONFLICT.
- BEGIN IMMEDIATE: bloqueo SQLite; PostgreSQL SERIALIZABLE. Una colisión puede requerir reintento de petición, nunca repetición ciega de efectos externos.
- IS NOT, RAISE y triggers SQLite: PostgreSQL usa IS DISTINCT FROM, PL/pgSQL y BEFORE INSERT para rellenar tenant antes de comprobar FK.
- Fechas legacy TEXT intactas; columnas TIMESTAMP y fechas SaaS con zona horaria en PostgreSQL. El adaptador devuelve fechas ISO a los controladores.
- DDL fuera de las peticiones HTTP; migraciones online con informe. init-db rechaza PostgreSQL.
- consultas/servicios_solicitados: leads y servicios de INAHI; no se les asigna tenant por inferencia.

Los servicios SaaS y Stripe conservan sus consultas en sus módulos. Esta fase extrae el SQL de app.py sin reescribir todos los controladores como ORM.
