# Fase 4 — INAHI AI Copilot

Implementación incremental en `saas-b2b-v2`. No modifica las funciones legacy ni activa migraciones al importar `app.py`. El módulo queda disponible después de una migración administrativa explícita y de disponer de una suscripción asociada a la organización. No se han usado bases de producción ni proveedores externos en la validación.

## Arquitectura y flujo

| Módulo | Responsabilidad |
| --- | --- |
| `copilot/features.py`, `permissions.py` | Registro de funciones y roles; sesión, identidad y membership vigentes |
| `copilot/context.py`, `sanitization.py` | Consultas por organización y función, selección de campos, minimización y redacción |
| `copilot/prompts.py`, `service.py` | Instrucciones constantes; reserva, invocación y autorización final |
| `copilot/providers.py` | Interfaz `Provider` / `Completion`, reglas locales y adaptador OpenAI |
| `copilot/usage.py` | Cuota mensual, límite por usuario/minuto, llamadas simultáneas, tokens y coste |
| `copilot/validation.py` | Forma, tamaño, referencias y contenido de la respuesta |
| `copilot/audit.py` | Códigos de auditoría sin preguntas, respuestas ni mensajes del proveedor |
| `copilot/routes.py` | Endpoints Flask pequeños; CSRF, parámetros y errores seguros |
| `copilot/schema.py` | Esquema aditivo de telemetría compatible con SQLite/PostgreSQL |

Una consulta sigue este flujo:

1. Valida la pregunta, función y UUID de petición. No admite IDs de empresa/usuario enviados en formularios o query parameters.
2. Resuelve organización y usuario desde sesión firmada y membership actual, comprobando estado, versión de credenciales y rol. El context builder vuelve a aplicar esta comprobación incluso fuera del endpoint.
3. Consulta exclusivamente columnas permitidas con `WHERE organization_id=?`. Un selector opcional `resource_kind` + `resource_id` debe pertenecer a esa organización y a las fuentes autorizadas para la función; un ID ajeno devuelve 404 antes de invocar al proveedor.
4. Minimiza y sanitiza los datos. Separa las instrucciones constantes del JSON no fiable de pregunta/contexto.
5. Reserva cuota y un registro de llamada en una transacción. SQLite usa `BEGIN IMMEDIATE`; PostgreSQL bloquea la fila de suscripción para serializar reservas de la organización. La reserva queda confirmada antes de salir al proveedor.
6. Invoca al proveedor fuera de la transacción. No existen herramientas, navegación, SQL generado, acciones autónomas ni historial compartido.
7. Valida la respuesta y vuelve a comprobar autorización y estado de suscripción. Una revocación durante la llamada impide entregar la respuesta.
8. Finaliza el registro y devuelve texto estructurado. No persiste pregunta, contexto ni respuesta.

## Funciones y alcance real

| Función | Contexto permitido | Roles que pueden consultar |
| --- | --- | --- |
| `business_overview` | Diagnósticos, estrategias, resultados y solicitudes | owner, admin, manager, member |
| `client_analysis` | Estrategia comercial de la empresa | owner, admin, manager |
| `sales_strategy` | Diagnósticos y estrategias | owner, admin, manager |
| `content` | Estrategias y calendarios de contenido | owner, admin, manager, member |
| `reports` | Resultados mensuales e informes | owner, admin, manager |
| `pending_actions` | Solicitudes y citas, incluyendo su estado | owner, admin, manager, member |
| `opportunities` | Diagnósticos, estrategias y resultados | owner, admin, manager, member |

`viewer` puede consultar la página y el uso, pero no enviar preguntas. Un superadmin no obtiene acceso al contexto de una empresa por su sesión de plataforma: necesita membership autorizada como cualquier otro usuario.

El contexto incluye nombre de empresa y entitlements, y prepara actividad mediante recuentos de acciones permitidas del audit log. Las solicitudes permiten observar el origen de respuestas automatizadas; no se añaden motores de automatización nuevos.

**El modelo actual `clientes` representa empresas abonadas, no contactos comerciales de cada empresa.** Por tanto, no se presentan las empresas de otros tenants como clientes del usuario. El contexto declara expresamente que no hay CRM de contactos y no permite inventar perfiles/seguimientos. El análisis individual y la estrategia para un contacto concreto requieren incorporar ese modelo en una fase posterior. Las funciones actuales ofrecen recomendaciones sobre la empresa y un método de trabajo cuando faltan datos.

Se consulta una muestra de hasta cinco registros recientes por categoría, con límites de profundidad y longitud. No equivale a un inventario completo ni a una búsqueda exhaustiva del mes. La respuesta expone esas limitaciones.

## Proveedores y configuración

El valor predeterminado `COPILOT_PROVIDER=local` utiliza recomendaciones deterministas. Es funcional sin red, pero **no es un modelo generativo**. Identifica la muestra de contexto y ofrece propuestas por función; lo indica explícitamente en la respuesta.

El adaptador `openai` usa Responses con instrucciones separadas, salida JSON Schema estricta, `store=false` y `tools=[]`. Requiere configurar externamente:

```dotenv
COPILOT_PROVIDER=openai
COPILOT_MODEL=<modelo compatible con Responses y Structured Outputs>
COPILOT_API_KEY=<secreto proporcionado fuera de Git>
COPILOT_ALLOW_EXTERNAL=true
COPILOT_MAX_OUTPUT_TOKENS=1200
```

Los marcadores anteriores son documentación, no credenciales utilizables. No se configura un modelo/precio comercial predeterminado. `.env.example` contiene valores locales seguros y campos de credenciales vacíos. No se escribe ni lee una clave real durante las pruebas.

El transporte fija el endpoint HTTPS del proveedor, rechaza redirecciones, limita la respuesta a 256 KiB, aplica un timeout de 30 segundos y no reintenta automáticamente. El límite de salida configurable se acota a 128–4000 tokens. En `TESTING`, un adaptador externo sin transporte falso se rechaza aunque existan credenciales ambientales.

Referencias utilizadas para el adaptador: [Responses](https://developers.openai.com/api/reference/cli/resources/responses/methods/create) y [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs). `store=false` evita la persistencia solicitada mediante esta API; no constituye una garantía de retención cero por parte del proveedor. La política contractual y de tratamiento de datos debe revisarse antes de una activación real.

## Cuotas y contabilización

| Plan | Cuota mensual inicial del Copilot |
| --- | ---: |
| Starter | 100 |
| Professional | 1000 |
| Business | 10000 |
| Enterprise | Configurable; sin límite mensual predeterminado |

La cuota deriva del catálogo B2B y puede ajustarse con `COPILOT_LIMIT_STARTER`, `COPILOT_LIMIT_PROFESSIONAL`, `COPILOT_LIMIT_BUSINESS` y `COPILOT_LIMIT_ENTERPRISE` (entero no negativo o `unlimited`). Además, cada reserva consume una unidad del entitlement compartido `ai` de billing; siempre se aplica también ese límite. Una cuota Copilot mayor no anula una cuota B2B menor.

`COPILOT_REQUESTS_PER_MINUTE` limita consultas por usuario y organización (5 por defecto, rango 1–100). `COPILOT_MAX_INFLIGHT` limita consultas simultáneas por organización (2 por defecto, rango 1–10). Estos controles se persisten en la base; no dependen de contadores del navegador ni de un único proceso web.

Una suscripción debe existir y estar habilitada para producto (`active`, o `trialing` vigente). Una suscripción no asociada no se crea automáticamente. Las operaciones legacy siguen su política anterior. Para el nuevo Copilot, incluso una suscripción asociada en modo legacy tiene la cuota del catálogo o su override Copilot; las funcionalidades antiguas conservan sus allowances.

Los intentos que llegan al proveedor consumen reserva aunque fallen, sean inválidos o se revoque el acceso durante la llamada. Los rechazos previos por autenticación, CSRF, recursos, configuración o cuota no invocan al proveedor ni reservan una llamada. Una clave `(organization_id,user_id,request_key)` repetida devuelve 409 sin repetir ejecución; no se reproduce una respuesta almacenada porque no existe ese almacenamiento.

Reservas de más de diez minutos pueden pasar a `abandoned` al reservar una consulta posterior. Siguen contando para la cuota: no se devuelve crédito automáticamente cuando se desconoce si el proveedor llegó a ejecutarse. Una caída después de la reserva necesita revisión operativa antes de volver a lanzar la consulta con otra clave.

## Esquema y auditoría

`copilot_usage` conserva:

- UUID interno y clave UUID de petición; huella HMAC del payload con la clave de aplicación.
- `organization_id`, `user_id`, función, proveedor y modelo.
- Tokens de entrada/salida/total cuando el proveedor los comunica y son válidos.
- Coste estimado opcional en USD, estado, creación/finalización y número de fuentes.

Estados: `reserved`, `succeeded`, `provider_error`, `invalid_output`, `denied_after_call`, `abandoned`. Tokens desconocidos se guardan como NULL, no se inventan. El coste local es cero; el remoto solo se estima si existen tokens y precios válidos en `COPILOT_INPUT_USD_PER_MILLION` y `COPILOT_OUTPUT_USD_PER_MILLION`. La suma de costes conocidos no equivale a una factura completa cuando hay llamadas sin coste conocido.

El esquema define FKs hacia organización y usuario, FK compuesta hacia su membership, deduplicación por organización/usuario/clave, estados y funciones válidos, valores no negativos e índices por organización/fecha y organización/usuario/fecha. PostgreSQL utiliza timestamps con zona horaria y `NUMERIC(20,10)` para costes.

`saas_audit` registra códigos `copilot_reserved`, `copilot_succeeded`, `copilot_denied`, `copilot_quota`, `copilot_provider_error`, `copilot_invalid_output` y `copilot_denied_after_call`. No registra IDs manipulados como si fueran la organización real del solicitante. Tampoco registra mensajes de error brutos del proveedor.

## Migración explícita y rollback

La revisión `0004_copilot`, dependiente de `0003_org_billing`, añade `copilot_usage` y `copilot_schema_state`. No ejecuta backfills de negocio ni asociación de suscripciones. Las revisiones previas permanecen intactas.

El CLI existente incorpora `--copilot`. Estos ejemplos son para una **base local desechable configurada explícitamente**, después de revisar el dry-run; no se ejecutaron contra la base de trabajo ni producción:

```powershell
.\.venv\Scripts\python.exe -m flask --app app db-dry-run
.\.venv\Scripts\python.exe -m flask --app app db-upgrade --copilot --report-file phase4-preflight.json
.\.venv\Scripts\python.exe -m flask --app app db-downgrade --copilot --report-file phase4-rollback.json
```

La operación guarda un informe exclusivo antes de modificar la base, verifica de nuevo los datos y ejecuta Alembic en una transacción. El upgrade incluye las dependencias necesarias; por defecto los comandos sin `--copilot` conservan sus destinos previos.

El rollback a Fase 3 **deshabilita lógicamente** el Copilot y conserva tablas, historial, cuotas y clientes. Rechaza llamadas con estado `reserved`; hay que comprobar su desenlace antes de proceder. Reaplicar la revisión reactiva el módulo sin reiniciar contadores. No se introduce ningún `DROP TABLE` del Copilot.

## Endpoints e interfaz

- `GET /saas/copilot`: formulario con CSRF, pregunta, selector, sugerencias, cuota y respuesta.
- `GET /saas/copilot/suggestions`: preguntas permitidas para el rol; no invoca IA.
- `GET /saas/copilot/usage`: consumo agregado de la organización activa.
- `POST /saas/copilot/ask`: formulario con `csrf_token`, `feature`, `question`, `request_key` y opcionalmente `resource_kind` + `resource_id`.

Se rechazan JSON, parámetros de scope y claves duplicadas en formularios. Los endpoints responden con `Cache-Control: no-store`. La interfaz usa el estilo existente y un script propio compatible con CSP: muestra carga/errores y crea contenido con `textContent`, sin ejecutar HTML generado. No hay reintentos automáticos ni acciones comerciales. No se modifica el asistente legacy.

## Límites y tareas posteriores

1. Probar con PostgreSQL real en un entorno local/staging autorizado: aquí se verifican compilación de DDL PostgreSQL y migraciones/constraints/concurrencia reales en SQLite, no concurrencia PostgreSQL ejecutada.
2. Evaluar calidad, latencia, coste y contrato de privacidad del modelo externo elegido antes de activarlo. Los tests usan fakes y transporte simulado; no prueban una API real.
3. La redacción de secretos y detección de prompt injection son defensas parciales. Las barreras de seguridad son el scope server-side, ausencia de herramientas/historial/recuperación global y validación de salida. No se promete detectar toda codificación maliciosa ni evitar toda alucinación.
4. Definir retención/purga administrativa de telemetría y auditoría, gestión de reservas abandonadas, alertas y presupuesto monetario. La Fase 4 limita solicitudes y tokens de salida, no garantiza un techo monetario global.
5. Incorporar un CRM de contactos multiempresa antes de análisis individual de clientes. Añadir filtros temporales, paginación o selección más completa cuando el volumen lo justifique.
6. Realizar QA visual/interactiva en navegador antes del lanzamiento. En esta validación se comprueban renderizado Flask, estados/elementos del formulario y sintaxis JavaScript; no se declara una prueba visual de navegador completa.
7. La organización sigue teniendo un carrier legacy `clientes`, como en Fase 1. Su separación definitiva queda fuera de este cambio.

Resultados reproducibles y entorno: [VALIDATION_PHASE_4.md](VALIDATION_PHASE_4.md).
