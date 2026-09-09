# Fase 3 — billing por organización

Trabajo local en `saas-b2b-v2`. No se ejecutaron operaciones reales en Stripe,
deploy, merge, migraciones de datos reales ni conexiones a producción.

## Arquitectura

| Módulo | Responsabilidad |
|---|---|
| billing/schema.py | Esquema congelado de la revisión 0003 |
| billing/repository.py | Suscripción por Organization, activación y bloqueos |
| billing/plans.py | Catálogo, correspondencia de Price IDs y límites configurables |
| billing/entitlements.py | Estado de pago, premium, miembros y reserva atómica de consumo |
| billing/gateway.py | Transporte Stripe test: customer, checkout, lectura de suscripción, portal y firma |
| billing/service.py | Orquestación, reintentos, cambio/cancelación con confirmación y reconciliación |
| billing/webhooks.py | Dedupe transaccional y reconciliación de eventos autenticados |
| billing/migration.py | Inventario legacy de solo lectura y asociación explícita con informe |
| billing/legacy.py | Adaptación de los controladores existentes a las políticas centrales |
| billing/routes.py | Endpoints de owner/admin y Superadmin separados |

`organization_subscriptions` tiene organization_id como PK/FK, plan, status,
stripe_customer_id, stripe_subscription_id, current_period_start/end,
cancel_at_period_end, created_at/updated_at. IDs Stripe únicos y opcionales;
timestamps con zona horaria en PostgreSQL. Campos adicionales internos conservan
las claves de idempotencia, sesión/plan/precio/expiración de checkout y el modo
de compatibilidad legacy. Esos campos internos no se exponen en los endpoints.

`billing_usage` usa PK (organization_id,metric,period), cantidad no negativa y FK
a la suscripción. `billing_events` tiene event_id único, FK de organización,
tipo, fecha del evento y fecha de procesamiento. No guarda payloads con datos
personales. `billing_schema_state` permite desactivación lógica sin borrar tablas.
Los eventos y la reconciliación se confirman en la misma transacción.

## Planes y límites

Estos son valores iniciales configurables, pendientes de validación comercial;
no son precios de venta ni contratos de Enterprise.

| Plan | Miembros activos | Clientes CRM | IA/mes | Automatizaciones/mes | Informes/mes | Premium |
|---|---:|---:|---:|---:|---:|---|
| STARTER | 3 | 100 | 100 | 20 | 10 | No |
| PROFESSIONAL | 10 | 1.000 | 1.000 | 200 | 100 | Sí |
| BUSINESS | 50 | 10.000 | 10.000 | 2.000 | 1.000 | Sí |
| ENTERPRISE | Sin límite | Sin límite | Sin límite | Sin límite | Sin límite | Sí |

Overrides: `B2B_LIMIT_<PLAN>_<METRIC>` con entero no negativo o `unlimited`.
METRIC: MEMBERS, CLIENTS, AI, AUTOMATIONS, REPORTS. Premium:
`B2B_PREMIUM_<PLAN>=true|false`.

Miembros cuenta memberships activas e incluye la reactivación de una revocada.
No se expulsa a miembros existentes al bajar un límite: se bloquean nuevas altas.
IA, automatizaciones e informes usan meses UTC naturales, no el ciclo de factura.
IA representa intentos de consulta al asistente, no tokens ni euros. La generación
legacy reserva el intento antes del trabajo; un intento fallido puede consumir
cuota. Los informes creados mediante el servicio SaaS reservan dentro de la
transacción de escritura. Los contadores no se pueden modificar desde el navegador.

El límite CLIENTS dispone de contador y reserva atómica, pero aún no existe un
CRM multiempresa al que conectarlo: la tabla legacy clientes representa empresas
cliente de INAHI, no sus contactos comerciales. No se cuenta una organización
como contacto de otra. Premium dispone de policy/guard centralizado; queda por
concretar el catálogo comercial de funciones premium. No se retiraron funciones
legacy para inventar ese catálogo.

Estados internos: trialing, active, past_due, canceled, incomplete. Un trial debe
tener fecha de fin vigente. Paid access requiere active o trialing vigente;
billing sigue accesible para owner/admin con pagos pendientes. El navegador no
puede activar estados, editar Stripe IDs ni alterar consumos.

## Configuración Stripe

- `STRIPE_B2B_MODE=test` (único modo admitido en esta fase).
- `STRIPE_B2B_SECRET_KEY`: clave test del entorno; sk_live/rk_live se rechazan.
- `STRIPE_B2B_WEBHOOK_SECRET`: secreto propio del nuevo endpoint.
- `STRIPE_B2B_PRICE_STARTER`, `STRIPE_B2B_PRICE_PROFESSIONAL`,
  `STRIPE_B2B_PRICE_BUSINESS`, `STRIPE_B2B_PRICE_ENTERPRISE`.
- `B2B_RETURN_URL`: URL configurada por el servidor, HTTPS o HTTP localhost.

No hay Price IDs reales ni credenciales incrustados. Se usa StripeClient por
instancia; no se cambia la clave global del proveedor legacy. La dependencia
queda en Stripe >=12.5,<13, compatible con el SDK local inspeccionado.
Los cambios de plan y cancelaciones crean flujos de Customer Portal: el cliente
confirma allí los efectos, según la configuración del portal test. No se aplica
un plan local por aceptar una petición del navegador.

Checkout persiste clave, plan, Price ID y expiración antes de llamar al proveedor.
Un reintento reutiliza esa solicitud; cambiar de plan durante una sesión pendiente
se rechaza. Una expiración local no basta para crear otra sesión: se comprueba
Stripe. Si consta completada se exige reconciliar. Una respuesta perdida sin ID
de sesión conserva su clave; no la rota automáticamente. La retención de claves
del proveedor es limitada: tras una interrupción prolongada puede requerirse
reconciliación manual, nunca crear otra suscripción a ciegas.

## Webhooks

Endpoint nuevo: `POST /stripe/b2b/webhook`. Solo esta ruta y el webhook legacy
están exentos de CSRF; ambos verifican la firma sobre el cuerpo original.
El endpoint B2B rechaza eventos live y snapshots live incluso con firma válida.

Eventos soportados:

- checkout.session.completed
- customer.subscription.created
- customer.subscription.updated
- customer.subscription.deleted
- invoice.paid
- invoice.payment_failed

El evento se asocia por el customer guardado en la base. Para vincular una nueva
suscripción se exige metadata del checkout autorizado por el servidor. Se consulta
la suscripción actual en Stripe bajo bloqueo de la organización, se verifica su
customer y se actualizan estado/plan/período y el registro legacy compatible.
La fecha del evento no decide qué estado gana; incluye eventos del mismo segundo.
Una factura antigua fallida no invalida una suscripción hoy activa; un pago viejo
no reactiva una cancelada. Eventos de suscripciones sustituidas se reconocen y
deduplican sin sobrescribir la actual, tras verificar el customer.

SQLite serializa escrituras; PostgreSQL utiliza transacciones SERIALIZABLE y
bloqueo de fila. Un error deja evento y efectos sin confirmar para reintentar.
El webhook original deriva los eventos de organizaciones ya asociadas al nuevo
servicio; los clientes no asociados conservan su procesamiento anterior.

## API y autorización

Owner/admin de la organización activa:

- GET `/saas/billing/<organization_id>`: plan, estado, límites, consumo y IDs Stripe.
- POST `.../checkout`: plan del catálogo; obtiene URL test.
- POST `.../portal`: abre el portal del customer de esa organización.
- POST `.../change-plan`: plan del catálogo; confirmación en Customer Portal.
- POST `.../cancel`: confirmación de cancelación en Customer Portal.

Los POST usan formularios con csrf_token. Se rechazan campos adicionales e IDs
de otra empresa, incluso para un usuario con membresías en varias empresas si
esa no es su organización activa. Manager/member/viewer no tienen billing.
La ruta GET de checkout legacy no puede crear una segunda suscripción para una
empresa ya asociada: dirige al estado B2B. El botón legacy de facturación utiliza
el portal de la organización con la misma autorización server-side.

Superadmin INAHI: GET `/platform/billing`, GET `/platform/billing/<id>` y POST
`/platform/billing/<id>/reconcile`. La lista inicial tiene hasta 100 empresas;
la consulta individual permite revisar cualquier empresa. No se exponen claves,
secretos de webhook ni claves internas de reintento. No se creó un rediseño visual.

## Migración y rollback

Revisión nueva `0003_org_billing`, dependiente de `0002_saas_core`. Las revisiones
anteriores y su metadata permanecen congeladas. El comando db-upgrade sin flag
conserva el alcance Fase 2; la ampliación billing es una decisión explícita.
Importar o arrancar Flask no hace DDL ni asocia cuentas.

Comandos para una copia local/desechable, con DATABASE_URL o DATABASE_PATH ya
configurada. No se ejecutaron contra la base de trabajo:

```powershell
.\.venv\Scripts\python.exe -m flask --app app billing-migrate-legacy
.\.venv\Scripts\python.exe -m flask --app app db-upgrade --billing --report-file esquema-billing.json
.\.venv\Scripts\python.exe -m flask --app app billing-migrate-legacy --apply --report-file asociacion-billing.json
.\.venv\Scripts\python.exe -m flask --app app db-downgrade --billing --report-file rollback-billing.json
```

Sin --apply, la asociación es dry run y funciona desde Fase 2, antes de crear las
tablas billing. Cuenta asociaciones, detecta IDs Stripe duplicados, mappings
ambiguos, customer ausente y trial inválido; avisa de períodos por reconciliar.
No imprime IDs Stripe ni credenciales. El informe se guarda de forma exclusiva
antes de aplicar; se repite dentro de la transacción. Aplicar requiere el esquema
billing activo y no llama a Stripe.

Correspondencia: esencial→STARTER, crecimiento→PROFESSIONAL, pro→BUSINESS. Se
copian las referencias Stripe y estados sin cambiar campos legacy, hashes,
miembros ni recursos. Las suscripciones asociadas retienen derechos anteriores;
las cuotas nuevas no se aplican retroactivamente. Un precio legacy sigue siendo
reconocido mediante sus variables existentes. Solo un precio B2B confirmado por
Stripe activa las cuotas nuevas. Se conserva el último día completo de un trial
legacy con fecha sin hora. Los períodos de pago desconocidos no se inventan.

`db-downgrade --billing` desactiva solo billing y mantiene SaaS Fase 2 y todas las
tablas/filas. Rechaza consumos, eventos, checkout, solicitudes de portal o nuevas
suscripciones que requieran reconciliación. No cancela nada en Stripe. Si no es
reversible sin perder actividad, reconciliar y restaurar un respaldo verificado
o migrar hacia delante; no forzar un DROP.

## Validación y riesgos pendientes

Resultado final: **194 tests pasados, 0 fallos y 60 subtests pasados**. Se mantienen
los 127 tests anteriores y se añaden 67. [Informe y archivos](VALIDATION_PHASE_3.md).

Todas las llamadas Stripe de los tests usan mocks; las pruebas de firma usan el
verificador real con secretos locales ficticios. Se comprueba A/B con un admin,
roles, límites, concurrencia, duplicados, eventos antiguos, estado canónico,
payment_failed, cancelación, checkout con respuesta perdida, compatibilidad,
dry run sin cambios de bytes y rollback con integridad referencial.

PostgreSQL se valida offline. Windows bloqueó la DLL nativa de psycopg durante
una prueba: se corrigió la carga anticipada del driver para que solo ocurra al
conectar. **No se eludió la política de Windows ni se certificó una conexión real**;
el error sigue propagándose si el entorno bloquea el driver. Queda pendiente un
entorno PostgreSQL autorizado para integración real.

Antes de un uso real: ensayo integral Stripe test con portal/precios/webhooks
configurados; PostgreSQL real, concurrencia y restauración; validación comercial
de cuotas/premium/Enterprise; CRM que consuma la cuota clients; políticas de
prorrateo, impuestos y gracia de pagos; rotación/historial de Price IDs; gestión de
reintentos prolongados y observabilidad. La reconciliación mantiene bloqueos
mientras consulta Stripe: evaluar timeouts y procesamiento en segundo plano con
carga real. Las pantallas legacy siguen mostrando su catálogo histórico; los
endpoints B2B son la fuente del nuevo plan. No se habilita Stripe live en esta fase.

Referencias: [webhooks y orden de entrega](https://docs.stripe.com/webhooks),
[idempotencia](https://docs.stripe.com/api/idempotent_requests),
[StripeClient de Python](https://github.com/stripe/stripe-python).
