# INAHI Studio — auditoría técnica SaaS B2B

> Documento histórico del commit auditado. La [Fase 0.5](STABILIZATION_0_5.md)
> registra los cambios posteriores de arranque, CSRF y deduplicación Stripe;
> sus pruebas aún están pendientes de ejecución. Los hallazgos siguientes
> describen la versión original, no una reauditoría del código actualizado.

> Estado posterior: [Fase 1](SAAS_PHASE_1.md) implementa el núcleo multiempresa
> y documenta la validación ejecutada, compatibilidad y riesgos todavía pendientes.

Fecha: 2026-09-08. Rama: `saas-b2b-v2`. Commit examinado: `f245ed07151309f18fc463d817e491af138e0684`.

## Dictamen y alcance

La aplicación es un portal comercial funcional por cuenta, con administración global de INAHI. No es todavía un SaaS multiempresa con usuarios, membresías y roles. Se recomienda evolución modular del monolito, conservando motores comerciales, rutas y datos existentes.

**Existe un riesgo destructivo que bloquea continuar con la implementación en esta fase:** importar `app.py` crea y altera la base y ejecuta una limpieza de cuentas. Conforme a la condición del encargo, esta entrega se limita a la auditoría y al diseño de la transición. No se ha modificado código operativo, arrancado la aplicación contra datos existentes, ejecutado migraciones ni desplegado nada. `original-app-backup` permanece sin modificaciones.

Revisión estática de los tres módulos Python, todos los templates y assets de texto, tests, dependencias, configuración de ejemplo, README, licencia, Procfile y workflow. El logo PNG se inventarió como activo a conservar; no se realizó auditoría visual en navegador. No hay `AGENTS.md` ni configuración Sites en los archivos encontrados. No se encontró una base `.db` en el workspace: el esquema descrito se deriva del código, no de una inspección de producción. No se han consultado secretos, infraestructura, cuentas Stripe ni información de clientes. No se puede certificar seguridad de producción, titularidad jurídica ni ausencia absoluta de vulnerabilidades con esta revisión.

Las rutas de código siguientes son relativas a `inahi-studio-app-main/`; los números de línea corresponden al commit auditado.

## Arquitectura y funcionalidades actuales

| Componente | Evidencia y comportamiento | Decisión |
| --- | --- | --- |
| `app.py` (1.801 líneas) | Instancia Flask global, SQL SQLite directo, rutas, seguridad, correo, Stripe, generación de estrategias y esquema en un módulo | Extraer progresivamente servicios y blueprints; mantener entrada `app:app` |
| `ia.py` | Llamada HTTP síncrona a Responses, modelo por entorno, timeout de 35 s, extracción de texto y fallback | Conservar adaptador, añadir resultado estructurado y servicio de contexto autorizado |
| `automatizacion.py` | Respuestas por reglas, calendarios sectoriales y métricas mensuales; sin red | Conservar funciones puras y sus resultados; versionar nuevas salidas |
| `requirements.txt` | Flask 3.1.3, gunicorn 23.0.0, Stripe >=11,<13 | Añadir persistencia/migraciones mediante bloques verificados; fijar entorno reproducible |
| `templates/` | 34 HTML, mayoritariamente Jinja con `base.html`; formularios server-rendered | Mantener navegación y flujos antes de cambios visuales |
| `static/` | `style.css`, `brand.css`, logo PNG, `consulta_cliente.js` | Conservar identidad. JS consulta estado cada 5 s y escribe con `textContent` |
| `tests/` | Un archivo unittest, 20 pruebas; base temporal antes de importar la app | Ampliar seguridad, concurrencia, aislamiento y migraciones |
| `Procfile` / README | Gunicorn `app:app`; configuración descrita para Railway y volumen `/data` | No es evidencia de la configuración real de producción |
| `.github/workflows/` | Workflow de importación de archivo que escribe en `main` | No hay CI de tests en el workflow observado; no ejecutarlo para esta transición |

Se mantienen: consulta pública con enlace privado y polling; registro y verificación de correo; login de clientes y equipo; recuperación y cambio de contraseña; demostración de 14 días para cinco cuentas y diez consultas; Checkout y portal de Stripe; diagnóstico digital; estrategia de 30/60/90 días; calendario mensual; asistente IA con respaldo local; resultados e informes mensuales; informes manuales; reuniones; contratación separada de servicios; administración de clientes, consultas, servicios, informes y citas; estado del sistema y páginas informativas.

No hay scheduler, cola de trabajos, publicación automática en redes ni CRM de clientes finales de cada empresa. Las “automatizaciones” son funciones ejecutadas al solicitar una página o enviar un formulario. El Copilot actual solo recibe los datos de la estrategia del cliente autenticado, asunto y descripción; no analiza una cartera de clientes, tareas persistidas o todos los informes.

## Esquema actual reconstruido

SQLite con `sqlite3.Row`, claves foráneas activadas y timeout de 15 s (`app.py:403`). Esquema en `crear_db` (434), ampliaciones en `actualizar_consultas` (567) y marcador en `limpiar_cuentas_anteriores_a_campana` (624).

| Tabla | Campos y restricciones relevantes | Propiedad actual |
| --- | --- | --- |
| `clientes` | PK id; nombre, correo UNIQUE, contrasena, plan, activo; plan_key, stripe_customer_id, stripe_subscription_id, subscription_status, creado, trial_end, email_verificado, legal_accepted_at, trial_slot, trial_queries_used | Cuenta = empresa = credenciales = billing |
| `consultas` | PK id; empresa, problema; correo, respuesta, token añadidos posteriormente | Contactos públicos de INAHI, sin FK; token sin índice UNIQUE explícito |
| `solicitudes` | PK id; FK cliente_id; asunto, descripcion, respuesta, estado, fecha, origen_respuesta | Cuenta cliente |
| `informes` | PK id; FK cliente_id; titulo, contenido, fecha | Cuenta cliente |
| `citas` | PK id; FK cliente_id; fecha, hora, modalidad, motivo, estado | Cuenta cliente |
| `diagnosticos` | PK id; FK cliente_id UNIQUE; web, google, redes, resenas, objetivos, puntuacion, actualizado | Un diagnóstico por cuenta |
| `estrategias_comerciales` | PK id; FK cliente_id UNIQUE; respuestas y estrategia JSON en TEXT, actualizado | Una estrategia por cuenta |
| `calendarios_contenido` | PK id; FK cliente_id; periodo, contenido JSON TEXT, creado; UNIQUE(cliente_id, periodo) | Calendario por cuenta/mes |
| `resultados_mensuales` | PK id; FK cliente_id; periodo, contactos, ventas, ingresos REAL, resenas, notas, informe JSON TEXT, creado; UNIQUE(cliente_id, periodo) | Métricas por cuenta/mes |
| `password_resets` | token PK en claro; FK cliente_id, expira, usado | Identidad heredada |
| `email_verifications` | token PK en claro; FK cliente_id, expira, usado | Identidad heredada |
| `servicios_solicitados` | PK id; servicio_key/nombre, precio TEXT, nombre, empresa, correo, telefono, mensaje, estado, fecha | Contactos públicos de INAHI sin vínculo a cuenta |
| `rate_limits` | clave PK, inicio, intentos | Contador por acción e IP derivada |
| `app_migrations` | nombre PK, aplicada | Marcador de limpieza; no framework de migraciones reversibles |

No existen Organization, User independiente, Membership, invitaciones, roles, suscripción propia, AIUsage ni AuditLog. No hay `organization_id`. Las FK no tienen borrado en cascada declarado. Fechas combinan texto ISO, fechas simples y CURRENT_TIMESTAMP; JSON no tiene validación estructural en base. La mayoría de FK no tiene índice explícito. Los importes de resultados usan coma flotante. `DATABASE_URL` no está implementada: cambiar una variable no habilitará PostgreSQL; PRAGMA, placeholders `?`, AUTOINCREMENT y manejo de filas necesitan adaptación.

## Hallazgos priorizados

P0: riesgo de pérdida de datos; P1: resolver antes de habilitar multiempresa; P2: consistencia y endurecimiento. “Confirmado” significa observable en código; no implica explotación en producción.

| ID | Prioridad | Evidencia | Impacto y corrección propuesta |
| --- | --- | --- | --- |
| A01 | P0 | `app.py:624–656`: limpieza sin condición de entorno en el import; DELETE de nueve tablas hijas y clientes si falta un marcador | Pérdida irreversible de cuentas al iniciar. Separar inicialización/migración del import; retirar limpieza del ciclo de vida; respaldo y ensayo de restauración antes de cualquier transformación |
| A02 | P0 | `actualizar_consultas`, 600–615: UPDATE de cupos, consumo y estado en cada import | Modifica derechos existentes, incluso sin limpieza. Migración explícita con valores anteriores y comprobación de idempotencia |
| A03 | P1 | `admin_required` (658) solo comprueba booleano de sesión; `clientes` mezcla empresa e identidad | No hay RBAC ni control de membresía. Nunca reutilizar `administrador` para administradores de organizaciones |
| A04 | P1 | `csrf` (690): compara dos cadenas vacías si no hay token en sesión ni formulario | POST sin token puede pasar con sesión nueva o recién limpiada. Exigir token presente y no vacío en ambos lados; cubrir métodos mutables y encabezado para futuras APIs |
| A05 | P1 | Configuración 33–36, `identificador_cliente` 406 | Hash administrador predeterminado embebido; clave de sesión aleatoria por proceso si falta configuración; Secure depende de FLASK_ENV. El hash no demuestra que la contraseña sea conocida. Exigir credenciales por entorno y secreto estable, cookies seguras y revocación |
| A06 | P1 | `identificador_cliente` confía directamente en X-Forwarded-For; `permitir_intento` 410 | Cliente podría rotar cabecera si el proxy no la sanea. Definir proxies de confianza; contador atómico por usuario/organización/IP con expiración |
| A07 | P1 | `pago_correcto` 1062 y `stripe_webhook` 1088 | Activación por Checkout completo/suscripción presente sin reconciliar estado de pago; eventos sin deduplicación, control de orden ni vínculo organizacional. Validar mapping server-side y estado del proveedor; persistir eventos y reconciliar |
| A08 | P1 | `eliminar_cliente` 1686; `clientes_admin.html` | Borrado permanente sin restauración. La protección de cobros no incluye el estado local `activa`; omite borrar `email_verifications`, por lo que FK puede abortar. Sustituir operación cotidiana por archivo reversible; preservar historial |
| A09 | P1 | `nueva_contrasena` 974: lectura de token, cambio y consumo en transacciones separadas | Uso concurrente del token y sesiones antiguas no revocadas. Consumir y cambiar de forma atómica; almacenar digest de tokens nuevos, invalidar sesiones |
| A10 | P1 | `solicitud_cliente` 1425 y `ia.py` | No hay AIUsage ni presupuesto por organización; texto se recorta después de llamar al proveedor. Limitar entrada antes de red; reservar cuota, registrar tokens reales y resultado/fallback |
| A11 | P2 | `solicitud_cliente`, `solicitar_cita`, `permitir_intento` | Cuotas mensuales/reuniones mediante lectura y escritura separadas; carreras. La cuota trial sí usa UPDATE condicionado, pero se confirma antes de guardar solicitud. Reservas transaccionales y conciliación de fallos |
| A12 | P2 | `calendario_contenidos` 1345 | GET inserta calendario o sobrescribe versión antigua sin guardar la anterior; concurrencia puede chocar con UNIQUE. Versionar contenido y usar POST explícito para generación |
| A13 | P2 | `crear_cliente` 1617 y `editar_cliente` 1720 | Plan descriptivo no sincronizado con plan_key/Stripe. Mantener servicio único de derechos y separar concesiones manuales de billing |
| A14 | P2 | `resultados_mensuales` 1388; formularios | float admite valores no finitos; fechas de citas comparadas como texto; tamaños y correo validados de manera desigual. Esquemas de entrada, números finitos, fechas tipadas y límites antes de procesamiento |
| A15 | P2 | `headers` 696; `clientes_admin.html`, `portal.html` | CSP bloquea onsubmit inline y ancho inline. Confirmación de borrado puede no ejecutarse; `|e` no es escape de contexto JavaScript. Eliminar JS inline, confirmación server-side. No debilitar CSP para arreglar interfaz |
| A16 | P2 | `consulta/<token>`, `enlace_publico` 352 | Enlaces bearer sin caducidad/revocación y fallback de URL basado en request. Canonicalizar PUBLIC_BASE_URL/hosts; no-store en páginas privadas; tokens revocables sin romper enlaces heredados durante transición |
| A17 | P2 | `ia.py` y correo 268 | Errores de proveedores se registran con detalles; riesgo de PII. Peticiones síncronas ocupan workers; IA de trial se ejecuta dentro de transacción de escritura. Redactar logs y sacar red de transacciones |
| A18 | P2 | README, `.env.example`, `/admin/sistema`, tests y workflow | Ejemplo de entorno incompleto; estado SMTP no representa Resend; no CI de seguridad ni prueba de restauración. Inventario de configuración y CI aislada |

### Controles existentes que deben mantenerse

- Hashes Werkzeug, comparaciones de CSRF en tiempo constante cuando sí hay token, limpieza de sesión al autenticar, HttpOnly y SameSite=Lax, tamaño máximo de request de 2 MB.
- Login y formularios públicos con límites y honeypot; reset con respuesta genérica y tokens aleatorios con caducidad; verificación de email.
- SQL de valores parametrizado. Los identificadores SQL interpolados observados provienen de listas internas, no del usuario. No se detectó inyección SQL directa en las rutas revisadas.
- Portal y funciones de cliente filtran por `session['cliente_id']`; no toman ese identificador de un formulario. Esto ayuda al aislamiento heredado, pero no constituye multi-tenancy ni demuestra que toda la superficie sea segura.
- Firma Stripe verificada sobre cuerpo recibido; excepción CSRF específica del webhook; barreras para modos test/live.
- Escape Jinja en HTML, `html.escape` en emails y `textContent` en polling. No se observan uploads, descargas privadas ni rutas de archivos arbitrarias; diseñar autorización antes de añadirlas.

Las listas y mutaciones globales del equipo son intencionales para el administrador actual de INAHI. Serían una fuga grave si se habilitaran a un rol `admin` de empresa. No hay registro de quién realizó una acción sensible ni identidad individual del equipo.

## Billing, IA y producto

Planes actuales: esencial 29 €, crecimiento 59 €, pro 99 €; cuotas respectivas de consultas 10/30/999, contenidos 8/16/30 y reuniones 0/1/2. La UI anuncia consultas ilimitadas para Pro pero backend limita a 999. No cambiar contratos ni identificadores Stripe automáticamente. Los nuevos Starter, Professional, Business y Enterprise serán versiones de catálogo separadas; precios y límites nuevos quedan pendientes de definición comercial.

Stripe almacena customer/subscription en `clientes`; maneja tres tipos de evento y un portal por cuenta. No hay libro de eventos, periodos persistidos, factura fallida como evento independiente ni conciliación de cambios fuera de orden. El bloqueo por cuenta inactiva también impide abrir el portal de facturación: separar acceso de recuperación de billing del acceso al producto.

IA usa clave y modelo configurados por entorno; respuesta de texto o None. Desecha `usage` y la identidad del modelo devuelta por el proveedor. La estrategia JSON se carga por cliente autenticado; el proveedor recibe solo `contexto.datos`, no `contexto.plan`. Sin herramientas SQL, retrieval, caché compartida o acciones externas del modelo observadas. El nuevo Copilot debe construir contexto desde repositorios autorizados, no confiar en instrucciones del prompt para separar empresas.

La licencia del repositorio ya declara software propietario con titular nominal. La UI contractual no expresa de forma completa el derecho de uso B2B sin transferencia del software. Conservar licencia y titular; documentar el modelo de suscripción en producto sin inventar ni cambiar la titularidad jurídica.

## Verificación y límites

Se revisaron las 20 pruebas existentes: Stripe test/live y activación simulada, registro/verificación, estrategias, respuesta IA/fallback, cinco plazas, diez consultas trial, calendario, conversión sectorial, reuniones y correo/reset. Una prueba **exige la limpieza destructiva** (`test_campaign_cleanup_runs_once_and_preserves_new_accounts`): debe reemplazarse por conservación al arrancar; pasar esta suite no garantiza seguridad.

No hay pruebas explícitas de Organization A/B, roles, permisos Superadmin, CSRF ausente, revocación, firma/replay/orden de webhooks, PostgreSQL, rollback ni contexto IA entre organizaciones. Se usa base temporal antes del import, pero el entorno no se limpia completamente y algunas llamadas a proveedores no están simuladas globalmente.

**Tests no ejecutados:** `python --version` falló por intérprete ausente. Se intentó preparar un intérprete temporal mediante uv para ejecutar la suite con credenciales de proveedores retiradas y conexiones de socket bloqueadas; falló la descarga. La comprobación offline terminó con `No interpreter found in virtual environments, managed installations, search path, or registry`. No se atribuye ningún test aprobado. No se instalaron dependencias en el proyecto ni se alteró una base de clientes.

La auditoría estática y revisión de diffs permiten entregar los documentos; la validación dinámica, backups reales, versiones instaladas en servidor, proxies, TLS, rendimiento y configuración Stripe quedan pendientes. Véanse [arquitectura](SAAS_ARCHITECTURE.md) y [plan de migración](MIGRATION_PLAN.md).
