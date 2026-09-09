# INAHI Studio — arquitectura propuesta

Estado: propuesta de fase 0, no implementada. Base: [auditoría](SAAS_AUDIT.md), 2026-09-08.

> Esta propuesta describe el objetivo completo. La implementación incremental de
> [Fase 1](SAAS_PHASE_1.md) utiliza módulos SQLite y migración aditiva explícita,
> antes de SQLAlchemy/PostgreSQL. Implementa Organization/User/Membership,
> autorización y puente legacy; no presupone que el resto de esta propuesta esté
> implementado. La matriz de permisos efectiva figura en ese informe.

## Decisiones

Mantener Flask, renderizado Jinja, URL pública `app.inahistudio.com` y funciones comerciales existentes. Evolucionar a monolito modular con una base compartida y propiedad organizacional explícita; preparar PostgreSQL conservando SQLite durante la transición. Sin reescritura SPA ni microservicios iniciales.

El software y su operación corresponden a INAHI Studio según el encargo; las organizaciones contratan derecho de uso. No cambiar automáticamente la licencia ni su titular nominal. Los datos empresariales y su acceso se separan por organización. Un administrador de empresa nunca adquiere permisos de plataforma.

## Modelo de dominio

| Entidad | Campos y relaciones esenciales |
| --- | --- |
| Organization | id, nombre, estado (active/suspended/archived), timezone, created_at, archived_at; límite de aislamiento |
| User | id, email_normalized UNIQUE, password_hash, email_verified_at, status, session_version; identidad global mínima |
| Membership | organization_id, user_id, role, status, joined_at; UNIQUE(organization_id,user_id); roles cerrados |
| Invitation | organization_id, email_normalized, role, token_digest UNIQUE, expires_at, accepted_at, revoked_at, invited_by |
| Customer | id, organization_id, nombre, contacto, estado, archived_at; cliente final del CRM, no login |
| BusinessProfile | organization_id UNIQUE; datos del negocio de la propia organización |
| Diagnostic / Strategy | id, organization_id, customer_id opcional, versión, datos, created_by, created_at; sin customer = negocio propio |
| Content / ContentCalendar | id, organization_id, customer_id opcional, periodo, versión, borrador/publicado, contenido |
| Report / MonthlyResult | id, organization_id, customer_id opcional, periodo, versión, métricas, notas y resultados |
| Request / Appointment | id, organization_id, created_by, datos de consulta/cita, estado; mantienen funcionalidades heredadas |
| Task / Automation / AutomationRun | organization_id, actor, configuración, estado, programación, idempotency_key, resultado, timestamps |
| PlanVersion / PlanLimit | catálogo global versionado, código, derechos, límites por métrica y periodo; precios Stripe por entorno |
| Subscription | organization_id, plan_version_id, stripe_customer_id, stripe_subscription_id, status, current_period_start/end, cancel_at_period_end; historial |
| BillingEvent | provider_event_id UNIQUE, tipo, modo, organization_id resuelta, received_at, processed_at, status, digest/error redactado |
| UsageReservation / UsageCounter | organization_id, métrica, periodo, cantidad, request_id UNIQUE, estado de reserva; límites transaccionales |
| AIUsage | organization_id, user_id, feature, provider, model, input_tokens/output_tokens/total_tokens nullable, unidades, status, request_id, timestamp UTC |
| AuditLog | organization_id cuando aplique, actor, acción, tipo/id de recurso, resultado, request_id, timestamp; metadatos redactados |
| PlatformOperator / PlatformIncident | identidad/permisos internos de INAHI; incidencias con organización afectada y acceso restringido |
| LegacyAccountMapping | legacy_cliente_id UNIQUE, organization_id UNIQUE, user_id, batch_id; correspondencia determinista reversible |

Users y catálogo de planes son globales; su existencia no se expone a otras organizaciones. Membership une identidad y empresa. Un usuario puede tener diferentes roles en empresas diferentes. Consultas públicas y solicitudes de servicios actuales pertenecen al negocio comercial de INAHI: asignarlas a una organización interna de INAHI, no inferir propiedad por nombre o correo. La tabla de eventos no asociados es exclusivamente interna hasta resolver la organización.

**La cuenta legacy no es automáticamente un Customer del CRM.** Su empresa pasa a Organization y BusinessProfile; su credencial a User con Membership owner. Diagnóstico/estrategia actuales describen esa empresa y conservan ese significado. Los clientes finales se crean después como Customer. No agrupar automáticamente cuentas por dominio de email.

## Invariantes de aislamiento

1. Resolver User desde sesión válida y estado en servidor. Obtener organización activa solo tras verificar Membership vigente y estado de Organization en cada request; el organization_id aportado por URL/body no autoriza nada.
2. Toda lectura o mutación de negocio recibe un TenantContext explícito. Buscar por `(organization_id, resource_id)`, incluidos joins, count, búsquedas, exportaciones, informes, relaciones y validaciones de unicidad. Recurso ajeno e inexistente responden igual (404), sin nombres, totales o diferencias de error que revelen existencia.
3. `organization_id NOT NULL` en entidades de negocio después de un backfill validado. UNIQUE(organization_id,id) y FK compuestas `(organization_id,customer_id)` impiden referencias cruzadas. Prohibir mover recursos de organización mediante edición masiva.
4. No hay repositorio con tenant opcional ni fallback global. Las operaciones de plataforma usan servicios separados y un contexto de operador distinto, con razón y auditoría.
5. Cachés, almacenamiento privado, trabajos y retrieval IA incluyen organización en clave y validación de acceso. Nunca almacenar archivos privados en `static/`. Al ejecutar un trabajo, volver a verificar permisos/estado y usar contexto explícito independiente de una sesión HTTP.
6. PostgreSQL añadirá RLS como defensa adicional, con rol de aplicación sin BYPASSRLS ni propiedad que eluda políticas, políticas para lectura/escritura y contexto local por transacción. Verificar limpieza del contexto al reutilizar conexiones. Migraciones y operaciones de plataforma usan credenciales separadas. SQLite mantiene filtros y pruebas equivalentes sin simular que dispone de RLS.
7. Conservar tokens públicos legacy como acceso limitado a una consulta, sin otorgar membresía o acceso al resto del tenant; revocación y expiración nuevas mediante transición explícita.

## Autorización server-side

Permisos definidos centralmente y denegación por defecto. La UI refleja permisos, pero el servicio vuelve a validarlos. Propuesta inicial: member puede editar recursos propios/asignados y leer recursos empresariales autorizados; viewer solo lectura y sin generación IA facturable.

| Capacidad | owner | admin | manager | member | viewer |
| --- | --- | --- | --- | --- | --- |
| Leer recursos de su organización | Sí | Sí | Sí | Sí | Sí |
| Crear/editar CRM, diagnósticos, estrategias y borradores | Sí | Sí | Sí | Propios/asignados | No |
| Generar Copilot, contenido e informes dentro de cuota | Sí | Sí | Sí | Contexto permitido | No |
| Gestionar tareas propias | Sí | Sí | Sí | Sí | No |
| Configurar/programar automatizaciones | Sí | Sí | Sí | No | No |
| Invitar, revocar y cambiar roles inferiores | Sí | Sí, sin owner | No | No | No |
| Gestionar facturación y plan | Sí | Sí | No | No | No |
| Transferir propiedad o archivar organización | Sí | No | No | No | No |
| Superadmin INAHI | No | No | No | No | No |

Mantener al menos un owner activo, con transferencia atómica y reautenticación. Admin no puede autoascender ni modificar al owner. Invitaciones con digest aleatorio, vencimiento, email verificado coincidente, consumo único atómico, límite de plazas y bloqueo de escalada de rol. Aceptar una invitación no informa de otras membresías del usuario.

## Módulos y transición

Estructura propuesta dentro de `inahi-studio-app-main/`:

```text
app.py                       # compatibilidad WSGI, sin migración al importar
inahi/
  __init__.py                # create_app(config)
  config.py
  db/                       # modelos, unidad de trabajo, repositorios
  auth/                     # login, reset, sesiones
  tenancy/                  # TenantContext, membresías, políticas
  customers/                # CRM de cada organización
  business/                 # diagnóstico, estrategia, contenido, informes, citas
  billing/                  # checkout, portal, webhook, derechos y cuotas
  copilot/                  # contexto, proveedor, orquestación, consumo
  automations/              # definiciones y ejecución de trabajos
  platform/                 # exclusivamente operadores INAHI
  audit/                    # eventos sensibles
  public/                   # consultas públicas, servicios, páginas existentes
migrations/                 # versiones explícitas, sin ejecución en startup
tests/                      # regresión y matriz SQLite/PostgreSQL
ia.py                       # fachada compatible durante extracción
automatizacion.py           # motores puros reutilizados
templates/                  # se mantienen y extraen por módulo gradualmente
static/                     # identidad INAHI preservada
```

Propuesta de persistencia: SQLAlchemy y Alembic, con adaptador PostgreSQL; elegir versiones e instalar solo al implementar el bloque de persistencia, comprobando compatibilidad real. Repositorios y unidad de trabajo encapsulan transacciones; las rutas no construyen SQL de negocio. Extraer un flujo cada vez, conservar endpoint names para `url_for` y no duplicar reglas entre código nuevo y legacy.

## Billing B2B

Conservar planes legacy y sus price IDs. Crear catálogo Starter, Professional, Business y Enterprise sin precios/cuotas inventados; no ofertarlos hasta que sus límites estén configurados. `NULL` puede representar ilimitado explícito; cero = no permitido. Cuotas de usuarios activos más invitaciones reservadas, clientes activos, solicitudes/tokens IA, automatizaciones activas/ejecuciones y feature flags. Derechos versionados por suscripción; exceder un límite bloquea nuevas altas, no elimina datos.

Checkout y portal deben derivar customer de Subscription de la organización autorizada. Persistir intento local antes de la llamada, usar idempotency key y metadata organizacional verificable. Validar modo, moneda/precio permitido y vínculo local del customer/subscription; metadata sola no es autoridad. Evitar más de una suscripción vigente por organización.

Webhook: verificar firma del cuerpo crudo, persistir event ID único, resolver vínculo, reconciliar estado de proveedor, actualizar suscripción y registrar auditoría de manera consistente. Duplicados no repiten efectos; eventos retrasados no reactivan una cuenta cancelada. Reintentos recuperables y conciliación periódica. La URL de éxito muestra estado verificado y no es una segunda fuente de activación independiente. Incorporar pagos asíncronos/fallos según medios habilitados al implementar.

Separar suspensión de producto y derecho del owner/admin a recuperar billing. Acciones administrativas de cuenta no cancelan o generan cobros implícitamente. Ninguna migración local recreará suscripciones o cambiará precios en Stripe.

## INAHI AI Copilot

Flujo: autenticar → resolver TenantContext → comprobar permiso/feature → reservar cuota atómicamente → recuperar solo datos autorizados → construir contexto limitado → proveedor fuera de transacción DB → validar salida → persistir borrador, AIUsage y resultado de reserva.

| Intención | Contexto permitido y resultado |
| --- | --- |
| Acciones comerciales de la semana | Estrategia, tareas y métricas de la organización; propuesta priorizada |
| Seguimiento de clientes | Customers e interacciones autorizadas; lista con referencias verificadas |
| Estrategia para un cliente | Customer seleccionado y diagnósticos de la misma organización; borrador versionado |
| Calendario de 7 días | Estrategia, contenidos y canales autorizados; borrador de siete fechas |
| Resumen mensual de dirección | Resultados y Report del periodo autorizado; resumen con fuentes y datos ausentes |
| Pendientes y oportunidades | Task y actividad disponible; sugerencias sin inventar seguimiento inexistente |

No enviar hashes, tokens, secretos, identidades ajenas, datos de billing innecesarios o logs internos. Texto de clientes/documentos es dato no confiable, nunca instrucción que amplíe permisos. Ninguna herramienta del modelo acepta SQL arbitrario o un tenant elegido por el modelo. Verificar pertenencia también en las referencias devueltas por IA. No mantener memoria global entre organizaciones.

Proveedor devuelve texto, proveedor, modelo real cuando disponible, request ID, usage nullable, latencia y estado. Registrar fallos y fallback como tales; no inventar tokens ni coste cero cuando se desconoce. AIUsage no guarda prompts completos por defecto. Reintentos no duplican consumo; diferenciar reserva, consumo real y cuota comercial. Mantener fallback determinista actual y el contrato compatible de `asesor_comercial_ia` durante extracción.

Copilot prepara borradores y recomendaciones. Envíos, publicación o cambios sensibles requieren la acción explícita del usuario autorizado y una nueva comprobación de permisos; no se ejecutan por contenido del prompt. Empezar sin vector DB; añadir retrieval solo con partición y tests de aislamiento cuando el volumen lo justifique.

## Superadmin y operación

Zona `/platform` con identidades individuales de operadores INAHI y autenticación reforzada; no derivar acceso de Membership owner/admin ni del correo que envía el cliente. Migrar el acceso compartido legacy mediante un procedimiento interno y no conceder privilegios globales a cuentas de clientes.

Servicios de plataforma para organizaciones/usuarios, planes versionados, suscripciones, estados de cuenta, límites y excepciones con caducidad, consumo agregado y de IA, actividad, auditoría e incidencias. Cada acceso detallado a una organización exige permiso interno y queda registrado; sin impersonación silenciosa. No mostrar secretos en el panel.

AuditLog append-only a nivel de servicio y permisos DB, redactado, con actor, objetivo, resultado y correlación. Registrar login sensible, invitaciones/roles, suspensiones, billing, exportaciones y cambios de límites; eventos denegados sin revelar datos ajenos. Timestamps UTC y timezone de organización para periodos de negocio.

Sesiones revocables, secreto estable externo, HTTPS/cookies seguras, CSRF obligatorio, hosts/proxies de confianza y rate limiting compartido. Colas y outbox para tareas y notificaciones cuando se extraigan las operaciones síncronas; workers sin contexto global, con idempotencia y revalidación de permisos. Copias cifradas, restauración ensayada y métricas de errores/latencia/consumo. No se especifican RPO/RTO como garantía hasta medir y acordarlos.

## Criterios de aceptación

No habilitar multiempresa hasta que la matriz A/B cubra cada recurso, lista, búsqueda, count, relación, exportación, tarea e IA; los roles se validen en servidor; un admin empresarial no acceda a plataforma; y SQLite/PostgreSQL demuestren integridad y migración reversible. Mantener todos los flujos comerciales de la auditoría y los planes vigentes. Mejorar el dashboard después de superar estas puertas, conservando marca, claridad de organización activa y permisos.
