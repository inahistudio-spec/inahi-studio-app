# Fase 1 — núcleo SaaS B2B

Fecha: 2026-09-08. Rama: `saas-b2b-v2`.

## Resultado y alcance

Núcleo Organization/User/OrganizationMembership implementado sobre SQLite con
migración explícita versionada, autorización server-side y puente para las rutas
existentes. No se cambian templates, static, precios, proveedor de pagos ni modelo
de producción. No se ha hecho deploy, merge, cambio de rama ni migración de una
base real. `original-app-backup` se conserva en
`f245ed07151309f18fc463d817e491af138e0684`.

La Fase 0.5 fue validada por el usuario con 37 tests. Esta fase conserva esos tests
y añade pruebas de migración y autorización; resultado de la ejecución final al
pie de este documento.

## Archivos de esta fase

| Archivo | Responsabilidad |
| --- | --- |
| `inahi-studio-app-main/saas_schema.py` | Migración `0001_saas_core`, backfill, integridad SQLite, reversión protegida |
| `inahi-studio-app-main/saas_core.py` | TenantContext, identidad, permisos, organizaciones, membresías y contraseñas |
| `inahi-studio-app-main/saas_routes.py` | Blueprint de API mínima, comandos CLI y control de rutas legacy |
| `inahi-studio-app-main/app.py` | Integración acotada: login, registro, verificación, cambio de contraseña y administración heredada |
| `inahi-studio-app-main/tests/test_saas_core.py` | Nuevos tests aislados de migración y multi-tenancy |
| `inahi-studio-app-main/README.md` | Comandos y enlace a este informe |
| `docs/SAAS_AUDIT.md`, `docs/SAAS_ARCHITECTURE.md`, `docs/MIGRATION_PLAN.md`, `docs/STABILIZATION_0_5.md` | Notas de estado, manteniendo el contenido histórico |
| `docs/SAAS_PHASE_1.md` | Esquema, compatibilidad, operación, tests y riesgos |

Los archivos y cambios no confirmados de fases anteriores permanecen en el
workspace; esta lista distingue la Fase 1. `.venv/` local está ignorada por Git y
no forma parte del código entregable. No se modificó `requirements.txt`.

## Esquema implementado

| Tabla | Campos y restricciones |
| --- | --- |
| `organizations` | id PK; name; slug UNIQUE; status active/suspended/archived; plan; created_at; updated_at; legacy_cliente_id UNIQUE NOT NULL FK clientes |
| `users` | id PK; email UNIQUE COLLATE NOCASE normalizado; password_hash; name; status active/suspended; created_at; last_login_at nullable; credential_version; legacy_cliente_id UNIQUE nullable FK clientes |
| `organization_memberships` | id PK; organization_id FK; user_id FK; role owner/admin/manager/member/viewer; status active/revoked; created_at; UNIQUE(organization_id,user_id) |
| `saas_migrations` | version PK; enabled 0/1; applied_at |
| `saas_audit` | id; action; organization_id nullable; user_id nullable; created_at. Metadatos de actividad nueva, sin contraseñas ni payloads |

`organization_id` y su índice se añaden a `clientes`, `solicitudes`, `informes`,
`citas`, `diagnosticos`, `estrategias_comerciales`, `calendarios_contenido` y
`resultados_mensuales`. Las columnas permanecen nullable para la reversión y el
puente legacy, pero los triggers de recursos impiden nulos persistentes o propiedad
cruzada en las escrituras normales mientras SaaS está activo.

La tabla `clientes` se conserva como cuenta de compatibilidad de una organización:
suscripción, trial y funciones comerciales existentes siguen leyendo sus columnas.
La autorización se resuelve desde User + Membership + Organization. No se copia a
todos los miembros la contraseña de la empresa. Una persona puede pertenecer a
múltiples organizaciones con roles diferentes.

Los clientes finales de una empresa aún no son un CRM separado: los diagnósticos,
estrategias y métricas históricos describen a la propia empresa. No se cambia ese
significado durante el backfill.

`consultas` públicas y `servicios_solicitados` son contactos comerciales de INAHI,
sin vínculo fiable con una cuenta cliente. Se conservan íntegramente como datos de
plataforma, accesibles solo a INAHI (y, para consultas, mediante su enlace bearer
existente). No se adjudican a tenants por coincidencia de nombre/email. Tokens de
reset/verificación son datos de identidad; rate limits y eventos Stripe son datos
operativos. No se ofrecen como recursos empresariales en la nueva API.

## Migración y reversión

La aplicación no ejecuta migraciones al importarse ni al arrancar. Sobre una copia
de ensayo explícitamente seleccionada mediante DATABASE_PATH, desde el directorio
de la aplicación y con el entorno local disponible:

```powershell
$env:DATABASE_PATH = 'C:\ruta\de\ensayo\consultas-copia.db'
.venv/Scripts/python.exe -m flask --app app saas-upgrade
```

El ejemplo exige sustituir la ruta por una copia real de ensayo. No ejecutar contra
producción. El esquema debe estar preparado con la Fase 0.5; para una base nueva,
`init-db` sigue siendo un paso explícito independiente.

`saas-upgrade` ejecuta prevalidación, DDL aditivo, backfill, triggers y activación en
una transacción `BEGIN IMMEDIATE`. Rechaza correos normalizados duplicados, recursos
huérfanos y hashes legacy cuyo formato no reconozca como PBKDF2/scrypt. No intenta
adivinar o convertir credenciales. Errores a mitad del proceso revierten también el
esquema. Una segunda ejecución con la versión activa no vuelve a transformar datos.

Por cada cliente: Organization con slug estable `legacy-<id>`, User con el hash
exacto ya existente y Membership owner activa. IDs y datos legacy permanecen,
incluidos cupos, estados, suscripción, referencias Stripe, JSON, informes y servicios.
Solo se añade la atribución organizacional. La antigüedad de la cuenta sigue en
sus campos legacy; created_at del núcleo nuevo refleja la incorporación al núcleo.

Después de la activación se exige login de nuevo. Las credenciales no cambian,
pero sesiones antiguas que solo contienen cliente_id no se convierten en owners.
Registro y alta administrativa posteriores crean el núcleo nuevo en la misma
transacción que la cuenta, sin ejecutar la migración otra vez. La verificación de
email válida enlaza la sesión con la identidad nueva.

Reversión, solo en la copia seleccionada:

```powershell
.venv/Scripts/python.exe -m flask --app app saas-downgrade
```

Es una reversión lógica conservadora: desactiva el núcleo y retira el backfill de
organization_id, sin DROP ni DELETE de clientes o recursos. Retiene las tablas
nuevas aparcadas, para reactivarlas con los mismos IDs. Las sesiones SaaS no se
reinterpretan como cuentas legacy: requieren reautenticación. Las lecturas/escrituras
de negocio legacy representables se conservan.

Si hay actividad registrada en `saas_audit`, nuevas identidades, membresías/roles o
estados incompatibles, se rechaza la reversión completa sin cambiar nada. No es un
botón universal para volver atrás después de operar con varios usuarios: eso exige
reconciliación y un procedimiento adicional. Cambios SQL fuera de estos servicios
no forman parte de la garantía; no modificar directamente las tablas del núcleo.

Antes de usar esta migración con datos reales: backup consistente, restauración
ensayada, copia representativa, recuentos y verificación de identidades/derechos.
Aquí únicamente se ejecutó dentro de bases temporales de tests.

## Aislamiento y permisos

`resolve_context` verifica User activo, versión de credenciales, organización activa,
membresía vigente y permiso en cada petición. El acceso al producto también verifica
cuenta, email y trial. Billing permite recuperar una cuenta inactiva por facturación
si la organización y la identidad siguen autorizadas. Suspender/archivar Organization
es independiente del estado Stripe: un webhook no reactiva la organización.

Los IDs del navegador nunca deciden la cuenta sobre la que trabajan las rutas
legacy: `session['cliente_id']` se obtiene de la organización validada. Parámetros
de organización/cuenta manipulados en esas rutas se rechazan. Las lecturas y
actualizaciones de la nueva API filtran explícitamente por organization_id e ID
del recurso; inexistente y ajeno responden 404. Las listas no cuentan ni devuelven
datos de otras organizaciones. Los tipos de tabla proceden de una lista cerrada.

Triggers impiden referencias cliente/organización contradictorias, traslado de
recursos entre cuentas y reasignación del vínculo de una organización. Las
escrituras legacy sin organization_id lo reciben automáticamente desde la cuenta
autorizada. Son garantías adicionales de integridad; no sustituyen a autorización
HTTP ni equivalen a RLS PostgreSQL.

| Permiso | owner | admin | manager | member | viewer |
| --- | --- | --- | --- | --- | --- |
| Lectura del negocio y miembros de su organización | Sí | Sí | Sí | Sí | Sí |
| Modificar diagnóstico/estrategia/resultados e informes | Sí | Sí | Sí | No | No |
| Enviar consulta al asistente | Sí | Sí | Sí | Sí | No |
| Billing y Checkout | Sí | Sí | No | No | No |
| Cambiar roles o revocar miembros | Sí | Sí, salvo owner | No | No | No |
| Promover/retirar owner | Sí, conservando uno activo | No | No | No | No |
| Cambiar la contraseña propia | Sí | Sí | Sí | Sí | Sí |
| Superadmin de INAHI | No | No | No | No | No |

Un viewer/member puede consultar un calendario ya generado; generar o actualizar
automáticamente uno desde el GET legacy requiere permiso write. Se limita así una
escritura oculta sin eliminar el flujo actual para roles autorizados. Las mutaciones
de membresías usan bloqueo de escritura y revalidación para proteger el último owner.

La IA sigue cargando únicamente la estrategia de la cuenta resuelta en servidor.
Un test captura el contexto enviado al adaptador y comprueba que el prompt de A,
aunque pida datos de B, no recibe esos datos.

## Superadmin y API mínima

La base Superadmin utiliza exclusivamente el login INAHI existente `/acceso` y su
sesión firmada `administrador`. Una sesión con User de tenant no puede usar ese
privilegio, ni siquiera si contiene además la bandera. Los admins de empresa no
entran en `/platform` ni en las rutas globales heredadas. Es una base server-side,
no un nuevo panel visual ni autenticación de operadores individuales con MFA.

Los endpoints mutables usan los formularios actuales y `csrf_token` en form data;
no se introduce API JSON de escritura ni bypass de CSRF.

| Endpoint | Método y propósito |
| --- | --- |
| `/cliente/acceso` | Login existente, ahora por User cuando SaaS está activo |
| `/saas/session` | GET: identidad, organización, rol y CSRF de la sesión |
| `/saas/organizations` | GET: organizaciones a las que pertenece el usuario |
| `/saas/organizations/<id>/activate` | POST: cambiar a una organización con membresía activa |
| `/saas/memberships` | GET: miembros de la organización activa, sin otras membresías del usuario |
| `/saas/memberships/<id>` | POST: role/status bajo autorización y protección del último owner |
| `/saas/resources/<tabla>` | GET: hasta 100 recursos de la organización, solo tablas admitidas |
| `/saas/resources/<tabla>/<id>` | GET: recurso propio; POST: editar informe propio con titulo/contenido |
| `/saas/reports` | POST: crear informe con atribución organizacional en servidor |
| `/platform/organizations` | INAHI GET/POST: listar/crear organización con owner existente |
| `/platform/organizations/<id>` | INAHI POST: status active/suspended/archived |
| `/platform/users` | INAHI POST: crear identidad con hash de contraseña |
| `/platform/memberships` | INAHI POST: añadir usuario existente con rol validado |

El resto de escrituras de negocio conserva los formularios existentes. La creación
de miembros en esta fase es administrativa por INAHI: no hay aún invitaciones por
correo ni búsqueda global de identidades por un administrador de empresa.
Una organización nueva recibe una cuenta de compatibilidad con email interno y
hash aleatorio que no sirven como identidad de sus miembros. El alta INAHI concede
acceso administrativo como el alta legacy: no crea una suscripción/cobro Stripe.

En modo SaaS, la acción global heredada de eliminar una cuenta la archiva de forma
reversible. Se informa expresamente de que los datos y la suscripción se mantienen:
archivar no cancela Stripe. No se ejecutó ninguna eliminación ni archivo real.

## Compatibilidad de identidad y billing

Los cambios de contraseña/correo desde flujos legacy actualizan la identidad
correspondiente mediante trigger. El reset incrementa credential_version y revoca
sesiones User anteriores. Cada miembro cambia su propia contraseña, sin cambiar
la del owner ni la de la cuenta portadora. Editar nombre de empresa sincroniza
Organization, sin renombrar la persona User. Cambios de plan desde Stripe reflejan
el plan de Organization conservando las referencias de suscripción legacy.

Las columnas de billing no se duplican ni se migran al proveedor. Organización.plan
refleja la clave legacy cuando existe o su descripción cuando todavía no existe.
La corrección de incoherencias históricas entre plan/plan_key se mantiene separada:
no se inventan nuevos derechos ni se recortan cupos al migrar.

## Validación

Se encontró un Python 3.13.3 ya instalado junto a Unity. Se utilizó para crear
`.venv/` local y cargar las dependencias existentes del proyecto. Unity y el Python
del sistema no se modificaron. Flask 3.1.3, Stripe 12.5.1 y Werkzeug 3.1.8 fueron
las versiones efectivamente usadas en este entorno de pruebas.

Comando desde `inahi-studio-app-main/`:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Pruebas nuevas cubren: creación, hashes, unicidad, membresías y roles; credenciales
legacy; activación multiempresa; todos los recursos A/B; IDs, parámetros y form
data manipulados; aislamiento IA; roles ante endpoints legacy; Superadmin; último
owner; revocación; contraseña de miembro y reset; nuevas altas; sincronización de
plan y nombre; integridad por triggers; migración idempotente, reversión, errores de
prevalidación y rollback completo ante fallo intermedio. La prueba obligatoria
autentica a A e intenta GET/POST sobre los IDs de B en las siete tablas de negocio.

Los tests usan DB temporales, bloquean red y protegen el import durante discovery.
No se usaron credenciales de proveedores, DB real ni endpoints externos. Los errores
de webhook simulados en logs son resultados intencionados de los tests de rollback.

Resultado final: **80 tests aprobados (37 existentes + 43 nuevos), 0 fallos y
0 errores**, en 42,123 segundos. Se ejecutó la suite completa tras los últimos
cambios de código. No es una medición de porcentaje de cobertura. La comprobación
de sintaxis Python y `git diff --check` también finalizaron correctamente.

Validación adicional solicitada por el usuario, ejecutada desde
`inahi-studio-app-main/` con el mismo Python del entorno existente:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Resultado: **80 passed, 54 subtests passed in 48.13s**, código de salida 0;
ningún test fallido. La ruta literal `...venv` no existía; se usó `.venv`.
Se añadió pytest 9.1.1 exclusivamente a ese entorno, sin instalar otro Python.
No se modificó código ni se eliminaron pruebas para conseguir este resultado.
El test `test_mandatory_cross_organization_resource_id_attack_is_rejected`
pasó dentro de la suite: exige 404 al acceder desde A a IDs de B mediante GET y
POST en siete tablas y verifica la conservación de datos.
No se ejecutaron comandos operativos de inicialización/migración ni se accedió
a producción; las fixtures de la suite usan exclusivamente bases temporales.

## Riesgos y siguientes pasos

- SQLite sigue siendo el backend; no hay todavía PostgreSQL/RLS. Los triggers y el
  puente cliente/organización permiten transición; nuevos servicios deben seguir
  usando TenantContext y consultas acotadas, nunca SQL global desde rutas tenant.
- Superadmin conserva la autenticación compartida legacy. Identidades de operador,
  MFA y auditoría de plataforma completa siguen pendientes. `saas_audit` registra
  acciones nuevas y protege rollback, no es un registro inmutable de todo el sistema.
- Se mantienen los riesgos históricos de configuración de secretos/proxies, rate
  limits, concurrencia de cuotas, GET con escritura y conciliación de eventos Stripe
  distintos fuera de orden. No se proclama una certificación de seguridad completa.
- El reset por email conserva las identidades legacy. Para identidades creadas
  exclusivamente en User queda pendiente el flujo de recuperación/invitación por
  correo; sí tienen login y cambio autenticado de contraseña propia.
- Las listas nuevas tienen un límite fijo de 100; paginación, administración
  empresarial visual, invitaciones y catálogo nuevo B2B se abordarán después.
- Python 3.13 advierte sobre conexiones legacy sin cierre explícito. Los módulos
  nuevos usan cierre explícito; no se reescribió toda la persistencia heredada en
  esta fase. Los avisos no se han confundido con tests fallidos.
- La reversión segura tras actividad multiusuario requiere reconciliación; el
  comando actual falla de forma conservadora. Un backup sin ensayo de restauración
  no basta para autorizar migración de clientes reales.

La fase deja un núcleo funcional y verificable para continuar en local/ensayo.
No autoriza ni ejecuta activación de SaaS o migración en producción.
