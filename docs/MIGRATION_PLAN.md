# INAHI Studio — plan de migración reversible

> Actualización: se ha implementado la [estabilización 0.5](STABILIZATION_0_5.md)
> por autorización posterior del usuario. Se retiraron los efectos de importación,
> se corrigió CSRF y se añadió deduplicación Stripe transaccional. La validación
> dinámica sigue pendiente; este plan de migración completa no se ha ejecutado.

> Actualización de Fase 1: la Fase 0.5 fue validada y se implementó
> [el núcleo SaaS con upgrade/downgrade explícitos](SAAS_PHASE_1.md).
> Solo se ejecutaron migraciones en DB temporales de tests, no sobre clientes reales.

Estado: diseño, sin ejecución. Rama exclusiva `saas-b2b-v2`; no modificar `original-app-backup`, no desplegar a producción. Documentos relacionados: [auditoría](SAAS_AUDIT.md), [arquitectura](SAAS_ARCHITECTURE.md).

## Puerta de seguridad inicial

El encargo permite continuar con implementación si no existe riesgo destructivo. A01/A02 confirman borrados y transformaciones durante el import; por ello se entrega fase 0 sin cambios operativos. No ejecutar `python app.py`, `flask`, Gunicorn ni herramientas que importen `app` contra una base existente. Incluso un comando para listar rutas dispararía actualmente la inicialización.

El siguiente bloque a implementar es neutralizar los efectos de arranque y demostrar preservación usando bases temporales. No hace falta decidir precios, infraestructura final o diseño visual para preparar ese bloque, pero esta entrega no lo ejecuta al haberse activado la condición de riesgo del encargo.

## Secuencia de bloques verificables

Antes de cada bloque: anunciar alcance y archivos, comprobar rama y cambios de usuario. Después: tests del bloque, regresión y documentación de resultados/riesgos. Sin mezcla de cosmética, billing externo y migración de datos en un mismo cambio.

| Bloque | Archivos previstos dentro de la app | Cambio y condición de salida | Reversión |
| --- | --- | --- | --- |
| 1. Arranque seguro | `app.py`, módulo de inicialización, tests, README | Retirar limpieza y UPDATE de campaña del import; bootstrap explícito para base nueva; arranque de base compatible no cambia datos. Sustituir test que exige borrado | Revertir solo a versión segura; nunca relanzar commit legacy con borrado sobre datos |
| 2. Seguridad heredada | `auth/`, CSRF/config en app, tests, template de borrado | Token CSRF obligatorio; secreto/admin fail-closed fuera de tests; sesiones revocables; proxy definido; archivo reversible en vez de eliminación cotidiana. Conservar flujos autorizados | Reversión de código sin restablecer credenciales inseguras o borrar campos de archivo |
| 3. Persistencia versionada | `db/`, `migrations/`, requirements, tests | Baseline del esquema real, repositorios y runner explícito; SQLite y PostgreSQL de pruebas. No ALTER durante requests/import | Expand-only; dejar tablas aditivas, desactivar lectores nuevos |
| 4. Identidades y organizaciones | `tenancy/`, `auth/`, migraciones y CLI de backfill | Organization, User, Membership, mapping legacy; creación/backfill idempotente en copia; comparación de hashes y derechos | Mapping y ledger restauran valores anteriores; no eliminar identidades con actividad nueva |
| 5. Aislamiento de negocio | Repositorios, blueprints por flujo, migraciones, tests A/B | Añadir organization_id, validarlo, cubrir todas las rutas; plataforma separada. Activar tenant solo al cerrar todas las rutas de escape | Volver a versión puente segura, conservar datos nuevos, nunca a rutas globales para usuarios de empresa |
| 6. Roles e invitaciones | `tenancy/`, `auth/`, UI mínima, tests | Matriz de permisos server-side, invitación atómica, último owner protegido, límites de plazas | Revocar invitaciones nuevas, mantener membresías y auditoría; sin downgrades que fusionen usuarios |
| 7. Billing B2B | `billing/`, migraciones, fixtures Stripe, tests | Asociar suscripción legacy sin tocar Stripe; catálogo nuevo separado, eventos idempotentes, cuotas concurrentes | Mantener event ledger; detener activaciones nuevas, reconciliar eventos; no borrar suscripciones ni repetir cobros |
| 8. Copilot y automatizaciones | `copilot/`, `ia.py`, `automations/`, usage, tests | Contexto autorizado, reservas, uso real, fallback, borradores y ejecución de tareas aislada | Feature flags independientes, preservar historial/consumo y motores deterministas |
| 9. Superadmin | `platform/`, auditoría, templates, tests | Operadores INAHI individuales y gestión de catálogo/organizaciones/consumo/incidencias con auditoría | Deshabilitar rutas nuevas sin transferir privilegios a tenants |
| 10. Ensayo PostgreSQL | CLI export/import, migraciones, CI y runbook | Copia completa, comparación, secuencias, aislamiento RLS y restauración probados | SQLite intacta; captura/reconciliación de escrituras posteriores antes de cualquier retorno |
| 11. Dashboard B2B | templates/static | Organización activa, miembros, límites y Copilot claros; mantener marca y funciones | Cambios de presentación reversibles e independientes de datos |

El orden distingue crear la barrera de plataforma (bloque 5) de completar sus pantallas de gestión (bloque 9). No se concede acceso empresarial al admin heredado durante el intervalo.

## Migraciones versionadas propuestas

Identificadores ilustrativos, todavía sin scripts:

- `0001_legacy_baseline`: inspeccionar tablas/columnas/índices reales sin importar app. Aceptar solo variantes reconocidas; nunca marcar aplicada una baseline sin comparar esquema. No ejecutar la limpieza histórica.
- `0002_identity_tenancy_expand`: tablas Organization/User/Membership/mapping y ledger de lotes; no actualizar cuentas originales todavía.
- `0003_business_tenant_columns`: añadir organization_id nullable e índices; preparación de tablas futuras y auditoría. Tenant nuevo cerrado mientras haya recursos sin atribución.
- `0004_legacy_backfill`: lote explícito con dry-run, precondiciones, before-images y reporte de correspondencias. No habilitarlo en startup.
- `0005_tenant_constraints`: comprobar nulos/huérfanos/referencias cruzadas; aplicar NOT NULL y FK compuestas. SQLite puede requerir reconstruir tablas: copia de trabajo, transacción y restauración ensayadas antes de aprobar el script.
- `0006_organization_billing_usage`: suscripciones/derechos/eventos/consumo, conservando columnas legacy mientras lo necesite la versión puente.
- `0007_copilot_automations`: trazabilidad de IA, tareas y automatizaciones, sin conversión destructiva de JSON existente.

Cada versión incluye checksum, precondición, estimación de filas, validación posterior y política de rollback. No confundir `app_migrations` legacy con historial confiable del nuevo runner. Ningún downgrade elimina tablas con actividad nueva: se conserva el esquema aditivo o se restaura mediante procedimiento de reconciliación. La fase de eliminación de columnas legacy se pospone hasta una ventana posterior expresamente planificada.

## Correspondencia de datos

| Origen | Destino y conservación |
| --- | --- |
| `clientes.id/nombre` | Organization + BusinessProfile; mapping estable por id original, no por nombre |
| `clientes.correo/contrasena` | User y Membership owner; copiar hash exacto, sin reset forzoso. Colisiones tras normalizar emails se reportan, no se fusionan |
| `clientes.activo`, trial, verificación y fechas | Conservar valores legacy y calcular estado equivalente mediante tabla de correspondencia documentada; sin reiniciar días, cupos o consumo |
| plan descriptivo/plan_key/Stripe | Subscription y versión legacy de derechos; conservar todos los valores originales y resolver discrepancias antes de activar nuevos lectores |
| diagnósticos/estrategias/calendarios/resultados | organización del mapping, customer_id vacío porque describen el negocio propio; conservar IDs, periodos y JSON original |
| solicitudes/informes/citas | organización del cliente FK; created_by nullable para registros históricos sin identidad demostrable |
| reset/verificación | Compatibilidad temporal de enlaces actuales; nuevas emisiones con digest. Mantener expiración y consumo sin ampliarlos |
| consultas/servicios públicos | Organización interna INAHI; conservar enlaces y datos, sin asignación automática a tenants por correo |
| rate limits | Estado operacional, no fuente de identidad. Transición sin reset de cuotas comerciales |

Antes de escribir, detectar correos normalizados duplicados, IDs Stripe repetidos, estados desconocidos, JSON ilegible, fechas inválidas, datos huérfanos y diferencias entre plan/plan_key. Registrar incidencias internas sin incluir PII en Git. Un registro ambiguo detiene ese lote y no desaparece de los conteos. No migrar todas las cuentas a una organización común.

## Procedimiento SQLite → PostgreSQL (ensayo, no autorización de despliegue)

1. Inventariar versiones y esquema real mediante acceso de solo lectura independiente del import. Medir filas, FK, índices, volumen y distribución de tipos; registrar manifiesto fuera del repositorio si contiene datos privados.
2. Crear snapshot consistente mediante mecanismo de backup SQLite; no copiar a ciegas un archivo abierto ignorando WAL. Verificar hash, integrity_check y restauración en una ruta distinta. La copia de seguridad no se guarda en Git.
3. Ejecutar migraciones y backfill en copia aislada, con correo/Stripe/IA deshabilitados. Mantener snapshot previo y ledger de valores originales; comprobar recuentos y comparación por PK, no solo totales.
4. Crear PostgreSQL vacío con esquema versionado y credenciales separadas. Exportar con tipos explícitos: fechas/UTC, booleanos, JSON válido e ingresos a decimal solo con política de redondeo y valor original preservado. Si una conversión es ambigua, detenerla.
5. Cargar por orden de dependencias preservando IDs y hashes. Reajustar secuencias. Validar FK, UNIQUE, nulos, hashes de contenido, mapping, periodos y derechos; comparar pantallas y respuestas de ambos backends con fixtures anonimizadas.
6. Probar matriz de aislamiento y RLS con el rol real de aplicación y pool reutilizado; probar cuota concurrente, replay de eventos, jobs y recuperación de fallo a mitad de lote.
7. Diseñar corte futuro con ventana de escrituras detenidas o captura de delta/outbox. Congelar escrituras incluye jobs y webhooks: eventos entrantes deben quedar en una cola duradera o reintentarse sin confirmación prematura. Este documento no ejecuta el corte.
8. Mantener SQLite intacta y binario puente seguro. Si PostgreSQL recibió escrituras, restaurar snapshot viejo sin reconciliación perdería datos: detener escrituras, exportar delta y conciliar primero. Cuando exista funcionalidad multiusuario no representable en legacy, volver a versión puente compatible, no al código original.

Sin prueba de restauración y equivalencia no se considera reversible una migración solo porque tenga función `downgrade`. RPO, RTO, retención y duración de la ventana se determinan con medidas reales antes de operación.

## Plan de tests y aceptación

Todas las pruebas con DB temporal antes del import, SECRET_KEY de test, entorno de proveedores limpio y red bloqueada por defecto. Stripe y correo simulados; ningún envío real. Instalar intérprete/dependencias en entorno aislado reproducible. No reutilizar `DATABASE_PATH` del operador.

| Área | Pruebas mínimas y resultado requerido |
| --- | --- |
| Preservación | Importar/iniciar dos veces con cuentas, relaciones y marcador ausente/presente: ningún dato cambia; base nueva solo se crea explícitamente |
| Migración | Dry-run sin escritura, ida/validación/reversión en copia, segunda ejecución idempotente, interrupción y reanudación, datos ambiguos rechazados; hashes/IDs/cupos conservados |
| Autenticación | Login válido/inválido, usuario inactivo, expiración y revocación, reset concurrente y de un uso, verificación, invalidación de sesiones tras cambio |
| CSRF y endpoints | POST sin cookie/token, ambos vacíos, token incorrecto, token válido; métodos mutables protegidos; webhook solo con firma válida |
| Roles | Cada celda de matriz, edición ajena dentro del tenant para member, elevación por body/URL, revocación inmediata, último owner, invitaciones cruzadas/vencidas/reutilizadas |
| Aislamiento crítico | Usuario A intenta GET/POST/PATCH/DELETE con IDs de B, organization_id falsificado y FK de B: mismo resultado que inexistente, sin mutación ni filtración |
| Alcance completo A/B | Listas, búsqueda, counts, paginación, informes, calendario, citas, archivos futuros, exportación, caché, trabajos y eventos; usuario con A/B cambia contexto sin conservar datos previos |
| Superadmin | owner/admin de organización rechazados en todas las rutas; operador válido autorizado según permiso y auditado; ninguna bandera enviada concede privilegio |
| Billing | Mapping ajeno rechazado; firma inválida; replay; eventos fuera de orden; pago incompleto/asíncrono; cancelación; portal de cuenta suspendida autorizado; planes legacy preservados |
| Límites | Dos altas/consultas/ejecuciones simultáneas ante última plaza; una sola obtiene reserva. Fallo/reintento no pierde ni duplica consumo |
| IA | Capturar payload al proveedor: contiene solo A y omite marcadores secretos de B; prompt que pide B no lo obtiene; modelo no puede elegir tenant; tokens ausentes no inventados; fallback y errores registrados |
| PostgreSQL | Mismas pruebas funcionales que SQLite, FK compuestas y RLS, contexto ausente denegado y pool sin contaminación; restauración ensayada |
| Regresión | Conservar los flujos auditados, nombres de endpoints y enlaces legacy; ningún cambio implícito de contrato o precio |

Añadir CI que ejecute unittest o el runner elegido en ambas bases y compruebe documentos/migraciones; el workflow actual de importación no cubre esa función. Un test que reproduce pérdida de clientes no puede seguir siendo criterio de éxito del nuevo arranque.

## Estado de esta entrega

Auditoría y arquitectura completadas como documentos; implementación, migraciones, ensayos y PostgreSQL pendientes. No hay cambios en archivos de aplicación ni datos. No se ejecutaron tests: falta Python y falló la obtención de intérprete temporal; comprobación uv offline confirmó ausencia. Los 20 tests fueron revisados estáticamente, sin afirmar que pasan.

Primer resultado esperado del siguiente bloque: evidencia automatizada de que abrir la aplicación nunca borra ni transforma cuentas existentes, junto con corrección de CSRF. No se debe activar multiempresa ni modificar billing antes de cumplir las puertas anteriores.
