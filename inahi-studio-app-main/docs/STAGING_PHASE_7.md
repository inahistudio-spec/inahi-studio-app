# Fase 7 — preparación y evaluación segura

Esta fase añade configuración de staging, políticas monetarias de IA y un banco de datos sintético. La validación local con SQLite/mocks no equivale a validar PostgreSQL real ni calidad generativa real. Ambas ejecuciones externas requieren una base y una clave dedicadas; no deben considerarse completadas sin sus informes.

## Fronteras de entorno

`APP_ENV` admite exclusivamente `development`, `test`, `staging`, `production`. Por compatibilidad, cuando falta se consulta `FLASK_ENV`; el defecto es development. Tests Flask bloquea transportes externos aunque una variable intente activarlos. Producción no puede activar el proveedor externo en esta fase: requiere un cambio y aprobación posteriores.

Staging exige `DATABASE_URL` PostgreSQL y coincidencia exacta de host/base/usuario con `STAGING_DB_HOST`, `STAGING_DB_NAME`, `STAGING_DB_USER`. La base y el usuario deben empezar por `inahi_staging_`. No acepta SQLite ni opciones arbitrarias de conexión. Fuera de loopback exige `sslmode=verify-full`.

Se rechazan credenciales heredadas `OPENAI_API_KEY`, `COPILOT_API_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` y `SMTP_PASSWORD`, o configuración de pagos reales. La clave usada por staging es exclusivamente `STAGING_COPILOT_API_KEY`. Se valida al arrancar y antes de configurar conexiones, sin conectar durante la importación.

Estos controles impiden reutilización accidental de variables y destinos conocidos. **No pueden identificar el origen de una clave arbitraria copiada manualmente bajo otro nombre.** El operador debe provisionar un proyecto de IA y un servidor/rol de PostgreSQL exclusivos de staging, sin acceso a producción. No compartir proyectos, secretos ni bases con producción.

`staging.env.example` es una referencia sin secretos; no se carga automáticamente. Inyectar variables en un proceso limpio o mediante el gestor de secretos. No imprimir variables completas, URLs con contraseña ni claves. Mantener `FLASK_SKIP_DOTENV=1` evita que Flask añada accidentalmente un `.env` legacy.

## Crear PostgreSQL de staging

En una **instancia PostgreSQL exclusiva de pruebas**, el administrador puede preparar:

```sql
CREATE ROLE inahi_staging_runner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
-- En psql, asignar contraseña mediante el prompt seguro:
\password inahi_staging_runner
CREATE DATABASE inahi_staging_eval OWNER inahi_staging_runner;
REVOKE CONNECT ON DATABASE inahi_staging_eval FROM PUBLIC;
GRANT CONNECT ON DATABASE inahi_staging_eval TO inahi_staging_runner;
```

Configurar en el proceso `APP_ENV=staging`, los tres valores de destino y `DATABASE_URL` con ese usuario/base. Usar un secreto de sesión independiente en `SECRET_KEY`, y `STAGING_DEMO_PASSWORD` de al menos 16 caracteres para las identidades sintéticas. No usar contraseñas de usuarios reales. Una URL remota debe incluir `?sslmode=verify-full&connect_timeout=10`; el certificado y hostname deben ser válidos. No se instala PostgreSQL, Docker ni Python automáticamente.

Desde `inahi-studio-app-main`, con las variables ya configuradas:

```powershell
.\.venv\Scripts\python.exe devtools/staging_postgres.py --initialize-empty --report-directory staging-check-001
```

El comando rechaza una base que ya contenga tablas, guarda un preflight exclusivo, migra hasta `0006_ai_staging`, crea únicamente el dataset sintético y ejecuta el contrato real. Comprueba identidad de conexión, esquema, índices, FKs compuestas, login, rechazo A/B antes del proveedor, CRM transaccional con rollback de sus datos de prueba, billing, uso de Copilot local, auditoría y downgrade/reactivación. Conserva la base sintética; no hace `DROP`, `init-db`, pagos ni llamadas de IA externas. Si falla, devuelve código 1 y un informe seguro; no imprimir excepciones con credenciales.

Para una base ya preparada:

```powershell
.\.venv\Scripts\python.exe devtools/staging_postgres.py --report-directory staging-check-002
```

El checker desactiva las políticas externas durante su prueba de rollback. Volver a habilitarlas requiere una acción explícita. Los directorios e informes deben ser nuevos en cada ejecución.

La prueba pytest real es optativa:

```powershell
$env:INAHI_RUN_POSTGRES_TESTS='true'
.\.venv\Scripts\python.exe -m pytest tests/test_postgresql_live.py -q
Remove-Item Env:INAHI_RUN_POSTGRES_TESTS
```

No habilitarla en la suite habitual sin haber verificado el destino. El resto de tests usa bases temporales y no necesita el driver PostgreSQL nativo.

## Migraciones, rollback y restauración

La revisión `0006_ai_staging` depende de `0005_crm`; no modifica revisiones anteriores ni columnas legacy. Añade:

- `organization_ai_policies`: permiso externo, presupuesto USD, bloqueo/aviso y límites por organización.
- `ai_call_controls`: extensión 1:1 de `copilot_usage`, reservas/coste comprometido, tarifas utilizadas, latencia, resultado del proveedor, error y fallback. El scope siempre se obtiene uniendo con `copilot_usage.organization_id`.
- `ai_budget_alerts`: umbrales mensuales 70/90/100, únicos por organización/período/umbral.
- `ai_synthetic_manifests`: versión y hash del dataset autorizado por organización.
- `ai_staging_state`: activación lógica.

Aplicación explícita, únicamente con la conexión staging comprobada:

```powershell
.\.venv\Scripts\python.exe -m flask --app app db-upgrade --ai-staging --report-file upgrade-ai-001.json
.\.venv\Scripts\python.exe -m flask --app app db-downgrade --ai-staging --report-file rollback-ai-001.json
```

El downgrade lógico conserva datos, cuotas, auditoría y manifiestos, deshabilita permisos externos y vuelve a 0005. Rechaza llamadas reservadas pendientes. Un upgrade posterior no reactiva permisos externos previamente apagados. Realizar estas operaciones sin tráfico concurrente, en mantenimiento.

Para restauración física, usar `pg_dump --format=custom` y `pg_restore` **hacia otra base vacía de staging**, nunca `--clean` sobre la original. Pasar credenciales mediante variables PostgreSQL/gestor de secretos, no URL con contraseña en argumentos. Verificar el dump con `pg_restore --list`, crear una nueva base de restauración y restaurar con `--no-owner --no-acl`. Actualizar `DATABASE_URL` y los tres pines al nuevo destino, manteniendo ambos flags de IA externos a false; validar allí antes de adoptar la copia. Conservar el dump y la base original según la política de pruebas. Esta restauración requiere ensayo real; no se afirma ejecutada localmente.

## Dataset sintético

El sembrador solo acepta una base sin organizaciones, usuarios ni cuentas legacy y con 0006 aplicada. Crea empresas A/B, usuarios con hashes, CRM normal/incompleto/malicioso, oportunidades, actividad, diagnósticos, estrategias, contenido, informes, resultados y solicitudes. No copia ninguna base real. La contraseña procede de `STAGING_DEMO_PASSWORD` y nunca se imprime por el comando de staging.

Alternativa al inicializador integral, tras migrar una base vacía:

```powershell
.\.venv\Scripts\python.exe -m flask --app app seed-ai-evaluation --confirm-empty-synthetic-database
```

Las identidades son `eval-a@example.invalid` y `eval-b@example.invalid`. Se autentican en el login real. El manifiesto se calcula sobre los datos persistidos que pueden alimentar el contexto; no se puede habilitar IA externa para una organización sin manifiesto válido. Si se modifica el CRM o un documento, la selección vuelve a local. No se ofrece un botón para certificar datos arbitrarios como sintéticos: hay que preparar otra base de evaluación vacía.

## Activar IA real SOLO en staging

1. Provisionar una clave de proyecto de staging con límites de gasto en el propio proveedor; guardarla como `STAGING_COPILOT_API_KEY`. No ponerla en archivos versionados ni en el chat.
2. Elegir el modelo compatible con Responses/Structured Outputs disponible en ese proyecto. Configurar `COPILOT_PROVIDER=openai` y `COPILOT_MODEL` sin valor por defecto externo.
3. Establecer tarifas verificadas para ese modelo en `COPILOT_INPUT_USD_PER_MILLION` y `COPILOT_OUTPUT_USD_PER_MILLION`, más coincidencia exacta de `COPILOT_PRICE_PROVIDER` y `COPILOT_PRICE_MODEL`. No se hardcodean precios ni se adivinan modelos.
4. Establecer `COPILOT_EXTERNAL_ENABLED=true` y `COPILOT_ALLOW_EXTERNAL=true` en staging.
5. Configurar explícitamente la organización A sintética, usando su ID devuelto por el sembrador:

```powershell
# Ejemplo de un techo de evaluación de 1 USD; el operador debe autorizar el importe.
.\.venv\Scripts\python.exe -m flask --app app ai-policy --organization-id <ID_A> --monthly-budget-usd 1 --external --block --requests-per-minute 30 --max-inflight 2
```

Sin clave, permiso de organización, manifiesto o activación de entorno se utiliza local. Una configuración de precio ausente/incompatible bloquea el envío antes de generar gasto. Para desactivar, poner los flags del entorno a false y/o aplicar `ai-policy ... --local`. Una desactivación durante la generación impide entregar la respuesta externa.

La arquitectura conserva el protocolo `Provider` y su registro de fábricas. OpenAI es el adaptador real implementado; otros requieren su adaptador y contrato de costes. Las pantallas legacy siguen usando sus respaldos locales: la salida externa se centraliza en Copilot, con scope y presupuesto, para que una antigua `OPENAI_API_KEY` no eluda los controles.

## Presupuesto y recuperación

`copilot_usage` sigue registrando organización, usuario, función, proveedor/modelo, tokens, coste estimado y estado. La tabla asociada añade latencia y datos de reserva/fallback. No se inventan tokens para reglas locales. Las tarifas usadas quedan fijadas al reservar.

Antes de llamar al proveedor se reserva un coste conservador según bytes UTF-8 de entrada más margen de framing y el máximo de tokens de salida. Se bloquea si el importe comprometido más esa reserva supera el presupuesto. Las llamadas concurrentes también cuentan. Tras recibir uso válido se liquida a coste estimado; si el proveedor falla, faltan métricas o se interrumpe el worker, se conserva la reserva como coste incierto. Nunca se reembolsa automáticamente una llamada que podría haberse cobrado.

Alertas 70%, 90% y 100% aparecen en la UI y en auditoría, una vez por organización/mes/umbral. Incluyen reservas, por eso pueden anticipar el coste final. El modo `--warn-only` permite superar el presupuesto por decisión administrativa; la evaluación real exige `--block`. La estimación no sustituye la factura ni el límite duro del proyecto del proveedor.

Se combinan los límites de plan existentes, llamadas por minuto por usuario, límite adicional por organización, concurrencia e idempotencia. Timeouts configurables de 1–45 segundos para el transporte; no hay reintentos automáticos ante 429, 5xx, respuesta inválida o refresh. Si está habilitado `COPILOT_FALLBACK_LOCAL`, una respuesta externa fallida puede entregar una propuesta local validada y claramente identificada. El fallo externo se conserva en telemetría, no se registra como éxito generativo. Si falla la persistencia final, se devuelve error seguro y se mantiene la reserva; resolverla exige conciliación administrativa con el proveedor, no borrar filas para liberar saldo.

## Evaluación

Diez casos cubren prioridades semanales, clientes, cierre, leads inactivos, estrategia individual, historial, siete días de contenido, resumen mensual, pendientes y oportunidades comerciales. El lote requiere `COPILOT_REQUESTS_PER_MINUTE=30` y política de organización suficiente; no se saltan ni reinician cuotas.

```powershell
# Solo reglas locales, incluso si hay una clave configurada:
.\.venv\Scripts\python.exe evaluations/copilot_eval.py --report-file eval-local-001.json
# Solo tras autorización de un techo de gasto y configuración de staging:
.\.venv\Scripts\python.exe evaluations/copilot_eval.py --real --max-cost-usd 1 --report-file eval-real-001.json --save-synthetic-answers
```

El evaluador usa login real, CSRF, el constructor de contexto y el endpoint real. No llama directamente a un modelo eludiendo entitlements. El techo mensual de A no puede superar `--max-cost-usd`. Un fallback no cuenta como validación generativa real.

Las comprobaciones automáticas verifican estructura segura, referencias autorizadas y canarios A/B/secretos. Los números nuevos se señalan para revisión, sin pruebas frágiles de frases exactas. Se añade una rúbrica de relevancia, factualidad, no invención, manejo de datos incompletos e instrucciones. **La calidad semántica no se declara validada automáticamente:** necesita revisión humana; `generative_quality_validated` permanece false. La exportación opcional contiene únicamente contexto y respuestas sintéticos para esa revisión. Por defecto no se guardan prompts ni respuestas en informes.

## Privacidad

El proveedor recibe la pregunta sanitizada, nombre sintético de empresa, un conjunto limitado de campos de negocio autorizados y referencias, conforme a los allowlists existentes. Se excluyen passwords/hashes, sesiones, tokens, claves API, datos Stripe, emails/teléfonos/webs CRM y campos internos no necesarios. Los nombres/notas/documentos sí pueden enviarse tras sanitización: no introducir datos reales en esta evaluación.

Los datos se envían como información no fiable, separada de las instrucciones. No hay herramientas, búsqueda externa, conversación persistente ni cambio de organización permitido desde un campo CRM. Se amplía la redacción para claves `sk-proj-`/`sk-svcacct-`. La sanitización no demuestra inmunidad a toda inyección codificada; las barreras de scope, ausencia de herramientas y validación de salida siguen siendo necesarias.

El adaptador usa `store=false`, `tools=[]`, salida estructurada y no envía historial. Esto no equivale a retención cero: revisar controles y contrato del proyecto. La documentación oficial distingue almacenamiento de Responses y logs de prevención de abuso, que pueden conservar contenido; no asumir que este parámetro elimina esos logs. Fuentes: [Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create), [controles de datos](https://developers.openai.com/api/docs/guides/your-data).

La aplicación no persiste prompts/respuestas completos por defecto. Conserva contadores, tarifas, latencia, estado, auditoría y referencias contabilizadas; el historial visible sigue en memoria de la página. Los informes con `--save-synthetic-answers` son optativos y requieren retención/eliminación local definida. Eliminar una copia/dataset de staging no borra por sí solo logs del proveedor. La eliminación física no es automática ni forma parte del rollback.

## Demo local sin servicios externos

```powershell
.\.venv\Scripts\python.exe devtools/run_ai_staging_demo.py --port 5057
```

URL: **http://127.0.0.1:5057/saas/copilot**. Usuario `eval-a@example.invalid`, contraseña de fixture **`Synthetic-evaluation-password-123`**. Solo en esta demo temporal, no para staging expuesto a internet. Crea SQLite temporal desde cero, bloquea conexiones salientes y descarta variables heredadas. La demo CRM anterior de 5055 y sus credenciales no cambian.

Para usar PostgreSQL staging configurado en loopback, establecer `STAGING_LOCAL_HTTP=true` y `PUBLIC_BASE_URL=http://127.0.0.1:5057`, y ejecutar Flask sin reloader/debug. Las cookies de staging son independientes y requieren HTTPS por defecto; esta excepción solo admite loopback:

```powershell
.\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1 --port 5057 --no-reload
```

No publicar el servidor de desarrollo. Un staging remoto necesita terminación HTTPS, sesión segura, acceso restringido y proceso WSGI administrado; no se despliega desde esta fase.

## Estado de validación

No hay destino PostgreSQL ni clave/presupuesto de IA real proporcionados en esta sesión. La prueba PostgreSQL optativa queda marcada como omitida, no pasada. No se han realizado operaciones reales en esos servicios. Windows bloqueó la carga de la DLL de psycopg durante la suite, aunque una comprobación aislada había importado el driver; no se modificó esa política del sistema.

Resultado final local (2026-09-10): **396 passed, 1 skipped, 60 subtests passed**, **0 fallos**, en 300,11 segundos. Se conservan los 338 tests anteriores; Fase 7 añade 59 casos: 58 pasan y 1 contrato PostgreSQL real queda omitido por falta de destino autorizado. No se han modificado ni eliminado tests anteriores. Las pruebas nuevas de configuración no cargan drivers nativos: comprueban que se rechaza el destino antes de crear un motor. Los casos de 429/timeout/5xx usan transportes fake.

El comando solicitado `..\.venv\Scripts\python.exe -m pytest -q` no arrancó porque ese entorno apunta a un Python313 inaccesible. La suite completa se ejecutó desde `inahi-studio-app-main` con el otro entorno **ya existente**: `.\.venv\Scripts\python.exe -m pytest -q`. No se instaló Python ni se cambió la política de Windows. También pasan `node --check static/copilot.js` y `git diff --check`.

Sin producción, Stripe, merge, deploy, commit ni cambios en `original-app-backup`. Antes de cerrar funcionalmente la fase faltan ejecutar el contrato PostgreSQL en un entorno autorizado, revisar restauración real y evaluar/revisar las diez respuestas generativas con presupuesto aprobado.

## Inventario de archivos

Modificados (18): `.env.example`, `README.md`, `app.py`, `copilot/errors.py`, `copilot/providers.py`, `copilot/routes.py`, `copilot/sanitization.py`, `copilot/service.py`, `copilot/usage.py`, `crm/routes.py`, `ia.py`, `migrations/env.py`, `persistence/database.py`, `persistence/migrations.py`, `static/copilot.js`, `templates/copilot.html`, `templates/workspace/base.html`, `workspace_ui.py`.

Creados (15): `runtime_environment.py`, `staging.env.example`, `copilot/admin.py`, `copilot/budgets.py`, `copilot/staging_schema.py`, `migrations/versions/0006_ai_staging.py`, `evaluations/__init__.py`, `evaluations/dataset.py`, `evaluations/copilot_eval.py`, `devtools/staging_postgres.py`, `devtools/run_ai_staging_demo.py`, `tests/test_ai_staging.py`, `tests/test_ai_staging_demo.py`, `tests/test_postgresql_live.py`, `docs/STAGING_PHASE_7.md`.

La demo admite `--stop-on-stdin` exclusivamente para controlar su ciclo de vida desde el proceso padre de integración. No añade endpoints de cierre ni excepciones de autenticación. La prueba usa login y HTTP reales, verifica el proveedor local y conserva intacta una base señuelo heredada.
