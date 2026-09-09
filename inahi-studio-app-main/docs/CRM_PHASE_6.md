# Fase 6 — CRM comercial por organización

El CRM mantiene `clientes` como cuentas legacy de INAHI y crea contactos comerciales independientes. Importar Flask no crea tablas, contactos ni migraciones. Se conserva el workspace y las funciones generales del Copilot.

## Arquitectura y esquema

- `crm/schema.py`: metadata congelada de `CRMContact`, `CRMOpportunity`, `CRMActivity` y el indicador de activación. Identidades, timestamps UTC, índices por organización, estado, responsable, contacto y seguimiento.
- `crm/policy.py`: estados y roles centralizados, validación de campos, importes, fechas, enlaces HTTP/HTTPS y responsables.
- `crm/service.py`: consultas parametrizadas y escrituras transaccionales. Cada escritura resuelve nuevamente la sesión y membership; los IDs nunca sustituyen la organización activa.
- `crm/routes.py`: formularios con CSRF, parámetros permitidos, respuestas privadas y auditoría de denegaciones. No envía emails ni realiza pagos.
- `crm/copilot.py`: contexto mínimo autorizado y seis tareas comerciales, compatibles con el proveedor local y la interfaz de proveedores existente.

Contactos: empresa/persona, email, teléfono, web, origen, estado, responsable, notas, creación/actualización, último contacto y próximo seguimiento. `archived_at` permite ocultar la ficha sin borrar su historial.

Oportunidades: contacto, título, etapa, importe `Numeric(14,2)`, probabilidad, cierre previsto y responsable. Ganada fija 100%; perdida fija 0%. Los importes son estimaciones, no ingresos. No hay conversión de moneda: el equipo debe usar una unidad común.

Actividades: contacto, usuario autor, tipo, descripción y fecha de realización/registro. Las notas no equivalen a una conversación; llamadas, emails, reuniones y seguimientos actualizan el último contacto sin retroceder su fecha.

Las FKs compuestas `(organization_id, contact_id)` impiden vincular oportunidades/actividades a contactos de otra organización. Las FKs compuestas de responsable y autor exigen pertenencia a la organización; además, el servicio comprueba membership y usuario activos. No se eliminan contactos, cuentas, memberships ni datos legacy mediante estas rutas.

## Permisos

| Rol | Consultar CRM | Crear/editar contactos y oportunidades | Registrar actividad | Archivar |
|---|---|---|---|---|
| owner/admin | Sí | Sí | Sí | Sí |
| manager | Sí | Sí | Sí | No |
| member | Sí, dentro de su organización | No | Solo en contactos asignados | No |
| viewer | Sí | No | No | No |

Se mantienen las restricciones de funciones Copilot existentes: análisis de clientes, estrategia e historial requieren owner/admin/manager; llamadas, detección de oportunidades y leads inactivos admiten member. Viewer no puede generar consultas. Ocultar botones no sustituye estas comprobaciones.

## Rutas

| Ruta | Función |
|---|---|
| `GET /saas/clientes` | Búsqueda y filtros `q`, `status`, `owner`, `followup`, `page`; 25 filas por página, recuento completo |
| `GET/POST /saas/clientes/nuevo` | Crear contacto |
| `GET /saas/clientes/<id>` | Ficha, notas, oportunidades e historial |
| `GET/POST /saas/clientes/<id>/editar` | Editar campos y responsable |
| `POST /saas/clientes/<id>/eliminar` | Archivado lógico, únicamente owner/admin |
| `POST /saas/clientes/<id>/actividad` | Registrar actividad y siguiente seguimiento |
| `GET/POST /saas/clientes/<id>/oportunidades` | Crear oportunidad |
| `GET/POST /saas/oportunidades/<id>/editar` | Actualizar oportunidad o marcar ganada/perdida |
| `GET /saas/pipeline` | Hasta 200 oportunidades, agrupadas por etapa |
| `GET /saas/clientes/<id>/copilot` | Asistente contextual de una ficha autorizada |
| `POST /saas/copilot/ask` | Endpoint existente, ampliado con `contact_id` y `crm_task` validados |

Las fechas de formularios se indican en UTC. Seguimientos: vencido, próximo en siete días, sin actividad en treinta días y lead sin contactar. Un contacto inactivo no genera avisos. El dashboard utiliza recuentos completos de la organización, valor abierto y cinco actividades recientes. La ficha muestra hasta cien actividades y cien oportunidades.

No se atribuyen diagnósticos o estrategias generales a una persona sin una relación real. La ficha explica esta ausencia; los documentos originales siguen accesibles en sus secciones.

## Copilot y cuotas

Las sugerencias comerciales son:

1. Seguimientos: `followups` / `client_analysis`.
2. Mayor probabilidad declarada de cierre: `closing` / `opportunities`.
3. Leads sin actividad: `stale` / `pending_actions`.
4. Estrategia del contacto: `strategy` / `sales_strategy`.
5. Historial del contacto: `history` / `reports`.
6. Llamadas de la semana: `calls` / `business_overview`.

El tipo de tarea debe corresponder a la función autorizada. El proveedor local produce propuestas deterministas basadas en fichas, fechas y actividades reales de la muestra; no es un modelo predictivo ni ejecuta acciones. Las funciones generales anteriores permanecen disponibles.

El contexto recibe hasta cinco contactos priorizados, cinco oportunidades y cinco actividades, con un presupuesto CRM de 6.500 caracteres y un límite conjunto de 18.000. Los leads inactivos se filtran antes de muestrear. En una consulta individual todas las fuentes se restringen a esa ficha; se excluyen documentos y auditoría generales de empresa.

Se excluyen email, teléfono, web, IDs de usuario internos, credenciales y datos Stripe. Nombres, notas y descripciones pasan por la sanitización existente; las fechas se normalizan para no confundirse con teléfonos. Los textos almacenados se tratan como datos no fiables, nunca instrucciones. Sin herramientas, recuperación arbitraria ni respuestas HTML ejecutables. Se revalida la autorización después del proveedor, incluida la vigencia de una ficha individual.

La creación consume el entitlement existente `clients` con reserva atómica; requiere una suscripción asociada. Editar no vuelve a consumirlo. Archivar no devuelve cuota, evitando ciclos de altas/bajas para eludirla. Se conservan las concesiones de compatibilidad legacy ya existentes. No se añaden planes ni precios.

Copilot usa el mismo medidor de IA, límites mensuales, rate limit, idempotencia y `copilot_usage` de la Fase 4. Registra organización, usuario, función, proveedor/modelo, tokens si se conocen y estado. La demo usa reglas locales, sin tokens ficticios. Los códigos de auditoría CRM registran creaciones, modificaciones, archivados, actividad, denegaciones y uso de Copilot; no registran preguntas, notas, respuestas ni IDs manipulados de otra organización.

## Migración y rollback

`0005_crm` depende de `0004_copilot`. Crea las tablas y activa el módulo explícitamente. SQLite sigue operativo y el DDL se compila para PostgreSQL con claves compuestas y timestamps con zona. No se reescriben migraciones anteriores.

`db-upgrade --crm --report-file <archivo-nuevo>` amplía hasta 0005 tras guardar y verificar el informe previo. Los destinos por defecto y las opciones `--billing`/`--copilot` conservan su comportamiento. Los comandos requieren que `DATABASE_URL` apunte deliberadamente a una copia local o entorno de pruebas. **No se han ejecutado sobre producción.**

`db-downgrade --crm --report-file <otro-archivo-nuevo>` vuelve lógicamente a 0004: desactiva el acceso CRM y conserva tablas, cuotas, auditoría e historial. Rechaza la operación si hay consultas Copilot reservadas. Un nuevo upgrade reactiva los mismos datos. Es un rollback funcional no destructivo; una restauración física requeriría una copia de seguridad verificada.

Ejecutar migraciones en ventana de mantenimiento sin tráfico. Las pruebas validan upgrade, rollback, reactivación, preflight, preservación legacy y FKs en SQLite; no sustituyen una prueba con un servidor PostgreSQL real.

## Demo local

Desde `inahi-studio-app-main`, detener la demo anterior de ese puerto y ejecutar:

```powershell
.\.venv\Scripts\python.exe devtools/run_workspace_demo.py --port 5055
```

Abrir **http://127.0.0.1:5055/saas/clientes**. Login real: `qa@example.com` / `Legacy-password-123`, organización **Estudio Norte**.

El runner crea y migra únicamente su SQLite temporal, borra variables de entorno heredadas, fija la conexión a ese archivo y bloquea conexiones salientes. Añade tres contactos ficticios de A y uno privado de B con oportunidades y actividad. La base desaparece al cerrar normalmente la demo. El puerto es exclusivo: no anuncia credenciales si ya está ocupado. No debe ejecutarse con `init-db`.

`..\.venv\Scripts\python.exe` apunta a un intérprete de Python313 denegado por Windows. Se utiliza el otro entorno **ya existente**, `.\.venv\Scripts\python.exe`; no se instala Python ni se cambian permisos del sistema.

## Validación y pendientes

Resultado final de la suite completa, ejecutada desde `inahi-studio-app-main`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

```text
338 passed, 60 subtests passed in 207.53s (0:03:27)
```

**338 pasados, 0 fallos: 267 anteriores + 71 nuevos.** `node --check static/copilot.js` y `git diff --check` también pasan. No se realizan cambios de código después de esta validación.

La suite anterior de 267 tests y 60 subtests pasó sin cambios. Se añaden pruebas CRM de CRUD, roles, aislamiento por URL/form/sesión, proveedor no invocado para B, cuotas y concurrencia, sanitización, contexto, DDL PostgreSQL, rollback y una demo en proceso real con tráfico HTTP local.

La ejecución específica de Fase 6 pasó con **71 tests nuevos, 0 fallos**. El test obligatorio `test_mandatory_copilot_contact_b_denied_before_provider` comprueba `404`, que ni siquiera se crea el proveedor y que no se reserva consumo. `test_real_demo_login_crm_write_and_contextual_copilot` recorre el bootstrap real, TCP, login, creación de contacto y consulta individual; también rechaza un ID de B.

Durante las pruebas nuevas se corrigió el bloque de actividad global que aparecía en listas filtradas; ahora pertenece al dashboard. La fixture de revocación usa el estado real `revoked` y verifica `403`, conservando `404` para recursos ajenos. Ningún test anterior se modifica o elimina.

Pendientes antes de ofrecerlo a clientes:

- Ejecutar las migraciones y pruebas de concurrencia contra PostgreSQL de staging; aquí solo se valida DDL offline y ejecución SQLite.
- QA visual manual de escritorio/móvil. Los formularios renderizan y la demo se valida por HTTP real; esto no equivale a inspección visual en navegador.
- Las propuestas locales son orientativas. Sanitizar texto libre no garantiza detectar secretos sin etiquetar ni toda inyección codificada. Revisar minimización, consentimiento y retención antes de habilitar un proveedor externo.
- Añadir vínculos reales contacto-diagnóstico/estrategia, monedas, restauración de archivados desde UI y paginación de historiales/pipeline si se necesita mayor volumen. No hay envíos de email, recordatorios automáticos ni Kanban avanzado.
- El rollback conserva datos; la administración debe definir restauración, retención y copias de seguridad antes de cualquier uso real.

Sin producción, deploy, merge ni cambios en `original-app-backup`.

## Archivos de esta fase

Rutas relativas a `inahi-studio-app-main`.

Creados (17):

```text
crm/__init__.py
crm/policy.py
crm/schema.py
crm/service.py
crm/routes.py
crm/copilot.py
migrations/versions/0005_crm.py
devtools/demo_crm.py
static/crm.css
templates/crm/list.html
templates/crm/form.html
templates/crm/detail.html
templates/crm/pipeline.html
templates/crm/summary.html
tests/test_crm.py
tests/test_crm_demo.py
docs/CRM_PHASE_6.md
```

Modificados (14):

```text
app.py
workspace_ui.py
copilot/context.py
copilot/service.py
copilot/providers.py
copilot/routes.py
persistence/migrations.py
migrations/env.py
devtools/run_workspace_demo.py
static/copilot.js
templates/copilot.html
templates/workspace/base.html
templates/workspace/dashboard.html
README.md
```
