# Validación final — Fase 3

Fecha: 2026-09-09. Rama: `saas-b2b-v2`.

Comando ejecutado desde `inahi-studio-app-main`, con el Python del entorno virtual existente:

```text
.\.venv\Scripts\python.exe -m pytest -q
194 passed, 60 subtests passed in 106.04s (0:01:46)
```

- 194 tests pasados, 0 fallidos, ninguno omitido.
- 127 tests anteriores conservados; sus archivos no se editaron.
- 67 tests nuevos de Fase 3, incluidas parametrizaciones.
- 60 subtests pasados: 54 anteriores y 6 nuevos para los eventos Stripe soportados.
- `git diff --check` sin errores. Git solo avisa de normalización LF/CRLF.

## Test obligatorio

`BillingTests.test_admin_a_cannot_read_or_modify_b_subscription_using_manipulated_ids`
crea recursos/suscripciones A/B, autentica a un admin de A, confirma acceso al
billing propio, y comprueba 404 para consultar B y para sus endpoints checkout,
portal, change-plan y cancel. No cambia la suscripción B ni llama al proveedor.

También pasan pruebas de inyección de customer/organization por formulario/query,
roles sin billing, CSRF, firma inválida, evento live, snapshot de otro customer,
deduplicación concurrente, eventos fuera de orden/del mismo segundo/de una
suscripción sustituida, errores transaccionales y reintentos.

## Cobertura funcional

- Suscripción por organización y constraints de estado/plan/FKs/IDs Stripe únicos.
- STARTER, PROFESSIONAL, BUSINESS, ENTERPRISE y overrides de límites.
- Miembros activos/reactivación, reserva atómica de clientes/IA/automatizaciones/
  informes, concurrencia y política premium. Integración en los controladores
  actuales para IA, automatizaciones e informes; la cuota clients queda preparada
  para el futuro modelo de contactos comerciales.
- Estado de pago server-side y acceso a billing para recuperar pagos pendientes.
- Customer, checkout, portal, confirmación de cambio/cancelación y reconciliación
  con mocks. Checkout conserva claves/precio al reintentar y no duplica una sesión
  completada cuyo webhook esté pendiente.
- Seis tipos de eventos, incluido payment_failed; nunca se confía en el estado
  enviado por navegador ni solo en la antigüedad del evento.
- Compatibilidad de precios legacy, derechos adquiridos y último día del trial.
- Dry run sin cambios de bytes, asociación explícita y rollback lógico separado
  que conserva SaaS Fase 2 y rechaza actividad incompatible.
- Esquema PostgreSQL y revisión Alembic compilados offline.

## Incidencias corregidas durante la validación

La primera ejecución detectó una DLL de psycopg bloqueada por la política de
Control de aplicaciones de Windows. Se cambió la creación del motor PostgreSQL
para cargar el driver únicamente al abrir una conexión explícita. Un test nuevo
comprueba que el error de importación sigue propagándose al conectar: no hay
fallback silencioso a SQLite ni se modificó la política de Windows. Una conexión
PostgreSQL real continúa pendiente de validación en un entorno autorizado.

Dos tests nuevos detectaron que el manejador genérico ValueError de SaaS convertía
errores de límite en 400. Se separó la excepción de dominio para devolver 402 de
forma consistente. Se volvió a ejecutar toda la suite hasta el resultado anterior.
No se ocultaron, eliminaron ni relajaron tests para conseguirlo.

## Archivos modificados

- `app.py`
- `billing_webhooks.py`
- `saas_core.py`
- `saas_routes.py`
- `persistence/database.py`
- `persistence/migrations.py`
- `requirements.txt`
- `README.md`

## Archivos añadidos

- `billing/__init__.py`
- `billing/schema.py`
- `billing/repository.py`
- `billing/plans.py`
- `billing/entitlements.py`
- `billing/gateway.py`
- `billing/service.py`
- `billing/webhooks.py`
- `billing/migration.py`
- `billing/legacy.py`
- `billing/routes.py`
- `migrations/versions/0003_org_billing.py`
- `tests/test_b2b_billing.py`
- `docs/BILLING_PHASE_3.md`
- `docs/billing_schema.sql`
- `docs/VALIDATION_PHASE_3.md`

## Límites de esta validación

No se hicieron llamadas reales a Stripe, ni siquiera test. Los transportes usan
mocks y la firma se verifica con el SDK real y un secreto ficticio. Falta ensayar
Stripe test completo con configuración real de productos, portal y webhook.

No se abrió PostgreSQL: faltan ensayos reales de esquema, PL/pgSQL, concurrencia,
recuperación y restauración. También requieren decisiones las cuotas comerciales,
el catálogo premium, el CRM consumidor de clients, prorrateo/impuestos/gracia de
pago, observabilidad e historial de Price IDs. La interfaz B2B es server-side/JSON;
las pantallas comerciales legacy conservan su catálogo anterior.

Las migraciones de esta validación se ejecutaron exclusivamente en SQLite
temporal de tests. No se instaló otro Python ni software del sistema. No hubo
deploy, merge, cargos, cancelaciones reales ni conexiones a producción.
`original-app-backup` mantiene
`f245ed07151309f18fc463d817e491af138e0684`.

Véase [arquitectura, configuración y procedimiento](BILLING_PHASE_3.md).
