# Validación final — Fase 2

Fecha: 2026-09-08. Rama comprobada: `saas-b2b-v2`.

Desde `inahi-studio-app-main`, usando el entorno virtual existente:

```text
.\.venv\Scripts\python.exe -m pytest -q
127 passed, 54 subtests passed in 67.73s (0:01:07)
```

- 127 tests pasados, 0 fallidos, ninguno omitido.
- 80 tests anteriores conservados sin editar sus archivos.
- 47 tests nuevos de Fase 2, incluidas parametrizaciones, en test_persistence.py.
- 54 subtests existentes pasados; no se suman a los 127 como casos independientes.
- `git diff --check` sin errores; solo avisos de normalización LF/CRLF de Git.

Pasa `MigrationTests.test_migrated_server_rejects_org_a_manipulated_org_b_resource_id`:
crea A/B con recursos, migra, autentica A, confirma GET propio 200 y GET del ID de
B (incluyendo query organization_id manipulada) 404. También rechaza POST sobre
el recurso de B y comprueba que sus datos originales se conservan.

Pruebas ejecutadas: migraciones/rollback reales sobre SQLite temporal, fallos
transaccionales, constraints core nuevos, FKs/triggers de aislamiento, copia de
hashes/suscripciones/recursos, adopción Fase 1, carriers, informes previos,
dry run sin cambios de bytes, conflictos, configuración y contrato del adaptador.

PostgreSQL: compilación de metadatos y revisiones Alembic offline, constraints,
índices, identidad de 64 bits, timestamps y guards. **No se ha ejecutado contra
un servidor PostgreSQL**; ese ensayo queda pendiente y no está contabilizado
como realizado. La compilación no sustituye una prueba real de PL/pgSQL,
concurrencia y flujos completos.

## Archivos modificados

- `app.py`
- `saas_schema.py`
- `saas_routes.py`
- `requirements.txt`
- `README.md`

## Archivos añadidos

- `alembic.ini`
- `persistence/__init__.py`
- `persistence/database.py`
- `persistence/models.py`
- `persistence/legacy_schema.py`
- `persistence/queries.py`
- `persistence/repositories.py`
- `persistence/planning.py`
- `persistence/migrations.py`
- `persistence/postgres_guards.py`
- `migrations/env.py`
- `migrations/script.py.mako`
- `migrations/versions/0001_legacy_baseline.py`
- `migrations/versions/0002_saas_core.py`
- `tests/test_persistence.py`
- `docs/POSTGRESQL_PHASE_2.md`
- `docs/SQL_INVENTORY_PHASE_2.md`
- `docs/postgresql_schema.sql`
- `docs/VALIDATION_PHASE_2.md`

La carpeta `../docs/` ya estaba sin seguimiento al comenzar esta fase y no se ha
modificado como parte de este trabajo. Las dependencias se instalaron solamente
en el entorno virtual local existente; no se instaló otro Python.

## Resultado y pendientes

Preparada una base de persistencia PostgreSQL/SQLite, dos revisiones Alembic,
preflight y conversión explícita. El rollback es lógico: conserva esquema y
datos y rechaza actividad incompatible; la recuperación física exige respaldo
verificado. El baseline no se elimina automáticamente.

Antes de cambiar de motor: integración PostgreSQL desechable, transporte ETL,
reconciliación de secuencias/fechas/datos, ensayo de restauración, reintentos por
serialización y validación operativa. Stripe B2B continúa pendiente; no cambió la
titularidad actual de suscripciones. Véase [procedimiento y límites](POSTGRESQL_PHASE_2.md).

No hubo deploy, merge, conexión a producción ni migración de datos reales.
`original-app-backup` conserva el ref
`f245ed07151309f18fc463d817e491af138e0684`.
