# Fase 2 — persistencia y migraciones

Implementación incremental en `saas-b2b-v2`. No se ha conectado a producción,
ejecutado init-db fuera de fixtures temporales, desplegado ni hecho merge.
SQLite y el modelo `clientes` siguen disponibles.

## Persistencia y configuración

- SQLAlchemy Core describe el esquema objetivo; Alembic mantiene las revisiones.
- `persistence/database.py` configura conexiones de forma perezosa. Importar la
  aplicación no conecta, crea tablas ni migra datos.
- `DATABASE_URL` tiene prioridad sobre `DATABASE_PATH`. Admite `sqlite:///...`,
  `postgresql://...` y `postgresql+psycopg://...`; PostgreSQL utiliza psycopg 3.
  Host y base PostgreSQL deben ser explícitos. Credenciales únicamente en el
  entorno/gestor de secretos; no en Python, alembic.ini ni informes.
- Se conserva `DATABASE_PATH` y el antiguo archivo local como compatibilidad de
  desarrollo. En entornos nuevos se debe configurar DATABASE_URL explícitamente.
- SQLite usa archivos temporales en tests, claves foráneas activas y timeout.
  No usar `:memory:` para el servidor Flask, que abre conexiones independientes.
- El adaptador mantiene filas por nombre/posición, rowcount, lastrowid y fechas
  ISO que espera el producto. PostgreSQL usa parámetros enlazados y RETURNING.
- Las consultas antes dispersas en app.py residen en `persistence/queries.py` y
  las búsquedas en `persistence/repositories.py`. Los servicios SaaS y Stripe
  conservan sus consultas y límites transaccionales. No es una reescritura ORM.

Véase [inventario de todas las dependencias SQL](SQL_INVENTORY_PHASE_2.md).

## Esquema PostgreSQL

El [SQL generado offline](postgresql_schema.sql) es un artefacto de revisión,
no una instrucción para ejecutarlo en producción.

| Tabla | Integridad y compatibilidad |
|---|---|
| organizations | BIGINT IDENTITY; name, slug único/formato validado, status, plan, created_at/updated_at con zona horaria; legacy_cliente_id único y FK RESTRICT |
| users | BIGINT IDENTITY; email único/normalizado; password_hash, name, status, created_at, last_login_at, credential_version; FK legacy opcional |
| organization_memberships | FK a empresa/usuario, pareja única, roles owner/admin/manager/member/viewer, estados active/revoked, fecha e índices de consulta |
| saas_audit | Acción, fecha con zona horaria, FK opcionales a empresa/usuario e índice por organización/fecha |
| clientes | Conserva todos los campos de credenciales, suscripción y referencias; añade organization_id y pareja única (organization_id,id) |
| 7 recursos de negocio | FK organization_id, índice de tenant y FK compuesta (organization_id,cliente_id) al carrier de esa empresa |
| saas_migrations / alembic_version | Activación reversible del modo SaaS y revisión profesional del esquema |

Los recursos son solicitudes, informes, citas, diagnosticos,
estrategias_comerciales, calendarios_contenido y resultados_mensuales.
Los IDs PostgreSQL son de 64 bits para conservar el rango de SQLite. Los textos
legacy y JSON almacenados como TEXT permanecen intactos. No se reinterpretan
importes ni fechas de texto durante esta fase.

Los triggers PostgreSQL rellenan organization_id de las escrituras legacy antes
de comprobar las FK, rechazan un tenant distinto y hacen inmutable el carrier.
También sincronizan cambios legacy de correo/hash, versión de credenciales,
nombre y plan. La autorización de las peticiones sigue resolviendo la empresa y
membership desde la sesión en el servidor. No se incorpora RLS en esta fase;
una cuenta SQL con acceso directo no constituye un usuario tenant de la API.

SQLite nuevo recibe constraints de las tablas core y los triggers de aislamiento.
Al adoptar un SQLite de Fase 1 no se reconstruyen sus tablas: conserva sus
constraints originales y sus triggers. No se afirma que tenga todas las nuevas
FK de auditoría/compuestas del esquema PostgreSQL.

## Revisiones y ejecución explícita

1. `0001_legacy_baseline`: crea el esquema legacy completo en una base vacía o
   adopta uno existente que supera el preflight; nunca borra filas.
2. `0002_saas_core`: expansión, backfill, guards e índices; adopta Fase 1 sin
   recrear identidades ni cambiar IDs. Reactiva una reversión compatible.

Ejecutar los siguientes comandos solo contra una copia local o una base
desechable, desde `inahi-studio-app-main`, después de configurar DATABASE_URL:

```powershell
.\.venv\Scripts\python.exe -m flask --app app db-dry-run
.\.venv\Scripts\python.exe -m flask --app app db-upgrade --report-file preflight-nuevo.json
.\.venv\Scripts\python.exe -m flask --app app db-downgrade --report-file rollback-nuevo.json
```

No se ejecutaron estos comandos contra la base de trabajo. Las migraciones
online de Alembic directas se rechazan para impedir saltarse el informe. Se
puede generar SQL PostgreSQL para revisar con `python -m alembic upgrade head
--sql`; ese modo no conecta. Las revisiones importan el catálogo de esta fase:
mantenerlo congelado y añadir nuevas revisiones/copias de metadatos al evolucionar.

Los antiguos `saas-upgrade`/`saas-downgrade` siguen como compatibilidad SQLite;
el upgrade muestra su inventario antes de modificar. Para nuevos procedimientos
usar db-upgrade/db-downgrade: guardan informe y revisión Alembic coherentes.
Una base ya gestionada por Alembic rechaza los comandos antiguos para evitar
desincronizar la activación SaaS y el historial de revisiones.
`init-db` rechaza PostgreSQL y nunca se llama al arrancar.

## Dry run y conservación

El informe muestra clientes, organizaciones/usuarios/memberships previstos,
conteos de recursos, conflictos y datos incompletos. Detecta correos normalizados
duplicados, hashes sin formato reconocido, esquemas incompletos, referencias
huérfanas y mappings incoherentes. No contiene emails, hashes, payloads ni URL.
Un archivo SQLite inexistente se informa como vacío sin crearlo. Una base
existente se abre en modo de solo lectura; PostgreSQL usa transacción READ ONLY.

El upgrade guarda el informe con creación exclusiva (no sobrescribe archivos),
repite el preflight dentro de la transacción y rechaza cambios de conteos desde
el informe. PostgreSQL serializa migraciones con advisory lock y bloquea las
tablas afectadas frente a escrituras concurrentes. SQLite incluye el DDL en una
transacción explícita: los tests inyectan un fallo después de copiar una cuenta
y comprueban que se revierten esquema y datos.

La conversión asigna slug legacy-ID y owner al usuario convertido, copia el hash
sin descifrarlo ni reemplazarlo, y enlaza los recursos existentes. No toca las
columnas originales de clientes, Stripe, diagnósticos, estrategias, contenidos,
informes o servicios. Los carriers de empresas creadas ya en Fase 1 no se
convierten en nuevas identidades artificiales.

## Rollback y traslado entre motores

El downgrade a `0001_legacy_baseline` es **lógico y no destructivo**: desactiva
SaaS y limpia únicamente las columnas añadidas organization_id; retiene tablas,
identidades, memberships, IDs, índices y datos originales. Una reactivación
reutiliza esos registros. Se rechaza si hay auditoría/identidades nuevas o
memberships/estados no representables en legacy. No existe DROP automático del
baseline. Este rollback no es una promesa de downgrade físico del esquema.

Antes de cualquier ensayo de traslado SQLite → PostgreSQL:

1. Obtener una copia consistente y comprobar su restauración. Con SQLite activo
   usar su API de backup; no copiar solo el archivo principal ignorando el WAL.
2. Ejecutar el dry run y resolver conflictos en una copia, con revisión humana.
3. Preparar PostgreSQL desechable y aplicar el esquema. Ensayar una exportación/
   carga que mantenga IDs y todos los campos, seguida de reconciliación de
   secuencias IDENTITY, conteos, hashes y referencias por tabla/tenant.
4. Verificar inicio de sesión, aislamiento A/B, archivos/datos, suscripciones y
   rollback con esa copia. No alternar escrituras entre dos motores.
5. Diseñar después un corte controlado con respaldo y restauración. Esta fase
   **no incluye un transportador ETL SQLite→PostgreSQL ni cambia producción**.

Si existe actividad SaaS incompatible con legacy, restaurar un respaldo
verificado o hacer una migración hacia delante; no forzar el downgrade. Restaurar
un respaldo exige reconciliar la actividad posterior: nunca descartarla sin más.

## Validación y límites

Suite: `.\.venv\Scripts\python.exe -m pytest -q`. Conserva los 80 tests previos;
resultado final: **127 passed, 0 fallos, 54 subtests passed**; 47 tests nuevos.
Véase el [informe final y lista de archivos](VALIDATION_PHASE_2.md).
`tests/test_persistence.py` añade pruebas de configuración, migración real SQLite,
rollback, fallos transaccionales, dry run, adopción Fase 1, constraints, parámetros,
DDL PostgreSQL offline y rechazo HTTP de recursos ajenos tras migrar.

No hay PostgreSQL, psql ni Docker disponible para un ensayo real local. Las
pruebas PostgreSQL comprueban metadatos, compilación Alembic y contrato del
adaptador; **no certifican todavía ejecución PL/pgSQL ni concurrencia real**.
Antes de usar PostgreSQL: ejecutar integración en un servidor desechable,
probar altas/login/reset/Stripe test, serialización/reintentos, rendimiento,
constraints al cargar datos históricos y restauración completa.

Pendiente además: ETL y reconciliación de secuencias; validación completa de
esquemas legacy no estándar (preflight verifica columnas/datos, no equivalencia
de todos sus constraints); TLS/roles SQL/backups del entorno destino; diagnóstico
de almacenamiento del panel adaptado a PostgreSQL; estrategia de pooling y
observabilidad. No se ha implementado Stripe B2B: la suscripción sigue en el
carrier clientes y aún debe diseñarse su titularidad por organización, eventos
fuera de orden y operaciones concurrentes. Tampoco se añadió Copilot avanzado.

Referencias de diseño: [Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html),
[transacciones SQLite en SQLAlchemy](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html),
[constraints PostgreSQL](https://www.postgresql.org/docs/current/ddl-constraints.html).
