# Fase 0.5 — estabilización y seguridad

Fecha: 2026-09-08. Rama exclusiva: `saas-b2b-v2`.
Estado: implementado, revisado estáticamente; tests pendientes por falta de Python.

> Actualización posterior: el usuario validó los 37 tests de esta fase. La
> [Fase 1](SAAS_PHASE_1.md) incluye una ejecución conjunta con los tests nuevos.
> Las referencias a ejecución pendiente que siguen describen la entrega original.

## Alcance e inspección previa

Se inspeccionaron las funciones de esquema, inicialización y campaña, configuración
de ruta SQLite, CSRF, webhook Stripe y suite de regresión antes de editar.
En la versión de fase 0, el nivel superior de `app.py` ejecutaba:

| Código original | Efecto al importar | Estado tras 0.5 |
| --- | --- | --- |
| `os.makedirs(DB_DIR, exist_ok=True)` | Creación de directorios persistentes | Solo en preparación administrativa explícita |
| `crear_db()` | Creación de SQLite/tablas | Solo invocación intencionada; no import ni request |
| `actualizar_consultas()` | ALTER de tablas y UPDATE de trial_slot/trial_queries_used/activo/subscription_status | Solo preparación explícita; eliminados los UPDATE de campaña |
| `limpiar_cuentas_anteriores_a_campana()` | DELETE de clientes y nueve tablas relacionadas al faltar marcador | No se llama; función conservada como bloqueo explícito con RuntimeError sin conexión DB |

La preparación no se ha trasladado a `before_request`, al primer acceso, a un
factory ni al inicio de Gunicorn. La instancia Flask global y el contrato WSGI
`app:app` se conservan. No se añade una reescritura con application factory en esta
fase. Importar el módulo construye esa instancia sin acceder a la base de datos.

Las operaciones normales iniciadas por requests (diagnósticos, solicitudes,
caducidad de trial en acceso, calendarios y administración) mantienen su lógica.
Esta fase no elimina esas funcionalidades ni afirma haber hecho todos los GET
libres de escrituras. La limpieza y recálculo histórico de campaña eran operaciones
de mantenimiento, no funciones necesarias para el servicio actual, y no se ofrece
un comando que reactive su borrado irreversible.

## Archivos

| Archivo | Cambios |
| --- | --- |
| `inahi-studio-app-main/app.py` | Import sin efectos DB/directorio; inicialización explícita; campaña bloqueada; CSRF no vacío; ruta de webhook delegada, rollback/error reintentable |
| `inahi-studio-app-main/billing_webhooks.py` (nuevo) | Registro y procesamiento local de eventos en una única transacción SQLite |
| `inahi-studio-app-main/tests/test_stripe_test_mode.py` | Fixtures aisladas por test, inicialización explícita, sin credenciales heredadas ni red; sustitución del test que exigía borrado |
| `inahi-studio-app-main/tests/test_stabilization.py` (nuevo) | Pruebas de conservación, esquema explícito, CSRF y Stripe |
| `inahi-studio-app-main/README.md` | Preparación intencionada y ejecución segura de tests |
| `docs/SAAS_AUDIT.md`, `docs/MIGRATION_PLAN.md` | Notas de actualización sin alterar evidencias históricas |
| `docs/STABILIZATION_0_5.md` (nuevo) | Informe de esta fase y riesgos pendientes |

No se cambian requirements, templates, static, modelo clientes, configuración de
producción, PostgreSQL ni `original-app-backup`. No se ejecutan cambios sobre una
base de clientes, migraciones ni despliegues. Los documentos de fase 0 ya estaban
sin seguimiento en el workspace y se conservaron.

## Preparación administrativa explícita

Desde el directorio de la aplicación, con Python y dependencias ya disponibles y
DATABASE_PATH apuntando intencionadamente a una base de ensayo:

```text
python -m flask --app app init-db
```

Implementación: `inicializar_base_datos()` llama a crear tablas, añadir columnas
legacy ausentes y crear `stripe_webhook_events(event_id PRIMARY KEY, event_type,
processed_at)`. No modifica valores de columnas existentes de clientes ni altera
cupos o estados. En esquemas antiguos, columnas nuevas reciben sus defaults;
no se infiere una transformación de derechos de prueba.

El comando conserva las primitivas de esquema existentes para minimizar cambios.
Es aditivo e intencionado, pero aún no es un runner de migraciones versionadas ni
una única transacción para todo el esquema. Puede dejar preparación parcial ante
fallo; debe repetirse y verificarse primero en una copia, nunca presentarse como
rollback completo. No automatizarlo al iniciar workers. No se ejecutó en esta entrega.

Una base nueva requiere este paso antes de usar rutas que consultan datos. Una
base existente necesita la nueva tabla antes de recibir webhooks con esta versión.
Si la tabla falta o la escritura falla, el webhook devuelve 503; no crea tablas en
la petición ni confirma falsamente el evento.

## Correcciones

### Import y campaña

El arranque no llama a ninguna operación persistente. También se eliminó el
recálculo de prueba de `actualizar_consultas`, para que invocar el comando de
preparación no suspenda cuentas o reinicie consumo. La limpieza histórica no puede
ejecutarse accidentalmente mediante su antiguo nombre: falla antes de abrir DB.

### CSRF

POST, PUT, PATCH y DELETE requieren token de sesión no vacío y token de formulario
no vacío; comparación constante de bytes UTF-8. Esto rechaza ausencia doble,
token incorrecto y entradas Unicode sin TypeError. Se conservan el campo
`csrf_token`, el context processor y los formularios actuales. El único endpoint
exento continúa siendo `stripe_webhook`, con autenticación por firma.

No se añade API JSON ni un mecanismo alternativo de token en encabezado; no es
necesario para los formularios actuales. Las mutaciones existentes mediante GET
son un riesgo distinto, fuera de este bloque.

### Stripe

La ruta mantiene `stripe.Webhook.construct_event` sobre el cuerpo recibido y
`Stripe-Signature`, usando STRIPE_WEBHOOK_SECRET. La firma se comprueba antes de
delegar o abrir la transacción. Firma inválida/expirada o cuerpo inválido: 400;
configuración incompleta: 503. El SDK aplica su tolerancia de firma predeterminada.

`procesar_evento_stripe` registra el ID único del evento y ejecuta sus UPDATE en la
misma conexión/transacción. `BEGIN IMMEDIATE` serializa escritores entre workers;
`ON CONFLICT(event_id) DO NOTHING` reconoce duplicados y omite sus efectos.
La transacción solo confirma al completarse. Un error revierte tanto el registro
como los UPDATE, permitiendo reintentar sin perder el evento. La conexión se cierra
explícitamente. Los duplicados válidos reciben 200, también tras reiniciar el proceso
porque la deduplicación reside en SQLite, no en memoria.

No se guardan payloads de clientes, firmas, secretos o datos de tarjeta en el
registro: solo ID, tipo y fecha. Un evento sin identidad válida o una actualización
de suscripción sin ID se rechaza; no puede actualizar cuentas con ID Stripe vacío.
Los tipos desconocidos válidos se reconocen y registran sin cambios de clientes.

Esta corrección garantiza una sola aplicación local por event_id conservado, no
“exactamente una vez” para todo Stripe. No elimina duplicados semánticos enviados
con IDs diferentes ni ordena eventos distintos.

## Tests

La suite original mantiene 20 métodos test; uno pasa de exigir borrado a exigir
su bloqueo y conservación de cuenta/solicitud. Cada prueba prepara su propia DB
temporal; se retiran las mutaciones de entorno y preparación DB a nivel de módulo.
Credenciales externas no se heredan y los sockets se bloquean por defecto.
El primer import durante discovery también bloquea SQLite y creación de
directorios: una regresión de arranque hace fallar la carga de tests antes de
alcanzar DATABASE_PATH, incluso antes de configurar las fixtures temporales.

La nueva suite añade 17 métodos test (37 en total con los 20 existentes) y comprueba:

- Import inicial y reload en subproceso, creación de la instancia Flask y `/salud`
  sin intentar conexión SQLite ni crear directorios; siete cuentas de prueba con
  cupos no recalculables y solicitud conservadas, con/sin marcador de campaña.
  Compara dump completo y hash del archivo.
- Base/directorio ausentes permanecen ausentes; esquema legacy no se actualiza al
  importar; `init-db` explícito es idempotente y preserva valores heredados.
- CSRF ausente, vacío, incorrecto y Unicode rechazados; token generado por formulario
  existente aceptado; métodos mutables protegidos.
- Firma real del SDK sobre payload local con HMAC de prueba: válida, ausente,
  inválida, expirada y cuerpo alterado; sin llamadas de red ni claves reales.
- Cada uno de los tres eventos soportados se procesa una sola vez; dos entregas
  concurrentes tienen un ganador; fallo de UPDATE revierte ledger y efectos, y el
  reintento funciona; tabla ausente devuelve 503 sin crear esquema.
- Configuración incompleta, eventos inválidos y tipos desconocidos.

Comando previsto, desde `inahi-studio-app-main/`:

```text
python -m unittest discover -s tests -v
```

**No ejecutados:** no hay `python`, `python3` ni `py` disponible en PATH. En esta
fase no se intentó instalar software, descargar intérpretes ni cambiar el sistema.
No se atribuye ningún test aprobado ni validación de sintaxis mediante Python.
**Verificación realizada:** inspección de código/diffs, ausencia de llamadas de
preparación a nivel superior, comprobación de rama y `git diff --check`.

## Riesgos pendientes y recomendación

1. Ejecutar la suite en un entorno ya provisionado y corregir cualquier fallo antes
   de declarar lista la fase. La revisión estática no sustituye pruebas SQLite,
   concurrencia y compatibilidad efectiva con el SDK instalado.
2. Ensayar `init-db` sobre copia representativa y probar backup/restauración. La
   tabla de eventos empieza vacía: eventos históricos no registrados podrían
   aplicarse por primera vez. No borrar el ledger como tarea de limpieza.
3. Stripe: persisten la lógica legacy de activación de Checkout, la activación en
   `/pago/correcto`, falta de conciliación de pagos/orden y asociaciones desconocidas.
   Un evento distinto retrasado puede sobrescribir estado reciente; la deduplicación
   por ID no lo soluciona. No se habilitaron ni modificaron cobros reales.
4. Se conservan los hallazgos de secretos/configuración, administrador compartido,
   proxies/rate limits, revocación de sesiones/reset, cuotas, GET con escrituras y
   eliminación administrativa permanente iniciada explícitamente por usuario.
   Esta última no es parte del import y no se ejecutó ni se amplió.
5. No existe aún aislamiento organizacional, RBAC o auditoría de plataforma. No
   presentar la app como SaaS multiempresa seguro a partir de este bloque.

**Recomendación:** el cambio elimina en código el bloqueo destructivo de import y
permite preparar los tests sin apuntar a datos reales. Fase 1 puede diseñarse y
desarrollarse en entornos aislados, pero no se da luz verde a migrar datos existentes
hasta ejecutar y aprobar la suite, verificar preparación sobre copia y ensayar
restauración. No hay autorización ni recomendación de despliegue a producción.
