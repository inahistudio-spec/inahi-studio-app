# Fase 5 — Nueva interfaz INAHI SaaS B2B

**Corrección posterior del login real:** se confirmó una demo antigua compartiendo el puerto 5055 en Windows. El runner ahora reserva el puerto de forma exclusiva y fija su base temporal antes de servir. Evidencia, diagnóstico y pruebas con subproceso/HTTP real: [DEMO_LOGIN_ROOT_CAUSE.md](DEMO_LOGIN_ROOT_CAUSE.md).

Nueva zona autenticada, visualmente independiente de la landing y el portal anterior. Sidebar verde oscuro, superficies claras, acentos lima, iconos SVG propios, tarjetas de negocio, gráficos basados en resultados registrados, navegación móvil y menú de cuenta. No hay nuevas migraciones ni cambios en el modelo de datos.

## Abrir la nueva experiencia

La demostración local se sirve en **http://127.0.0.1:5055/saas/dashboard**. Al acceder sin sesión se muestra el login; una cuenta SaaS válida se redirige al dashboard.

Cuenta de la fixture desechable existente:

- Email: `qa@example.com`
- Contraseña: `Legacy-password-123`
- Usuario: Alex; organización de demostración: Estudio Norte; plan Professional.

Estas credenciales pertenecen exclusivamente a datos ficticios de prueba. No son credenciales de un cliente real. La demo reutiliza la fixture A/B existente en una nueva base temporal y añade registros ficticios para visualizar las tarjetas y el gráfico; todas las pantallas muestran el aviso de demostración.

Corrección del login demo: la fixture genérica creaba `a@example.com`, por lo que intentar acceder con `qa@example.com` devolvía credenciales incorrectas. El bootstrap de esta demo cambia únicamente el correo del usuario y su cuenta legacy temporal a `qa@example.com`, preservando el hash de contraseña y la membership owner de Estudio Norte. No cambia la autenticación de la aplicación ni la fixture genérica A/B. Es necesario detener y reiniciar la demo para recrear su base temporal con el correo definitivo.

Regresión añadida: `tests/test_workspace_demo.py::test_demo_qa_real_login_dashboard_and_tenant_isolation`. Antes del arreglo reproducía el fallo (login 200 con error, sin redirección); después verifica el login real con CSRF, contraseña incorrecta rechazada, dashboard 200 de Estudio Norte, password hash preservado y acceso A/B rechazado. Ejecuta el bootstrap real de la demo sustituyendo únicamente el arranque del servidor, sobre su base temporal, y comprueba que una DATABASE_URL ambiental queda descartada y que la base temporal se limpia al terminar.

Validación completa posterior a esta corrección, con `.\.venv\Scripts\python.exe -m pytest -q`: **265 passed, 60 subtests passed in 121.09s; 0 fallos**. Los 264 tests anteriores permanecen intactos.

Para volver a iniciar la demo, desde `inahi-studio-app-main`:

```powershell
.\.venv\Scripts\python.exe devtools/run_workspace_demo.py --port 5055
```

Se utiliza el entorno existente. El servidor escucha solo en `127.0.0.1`, bloquea conexiones salientes, usa exclusivamente el proveedor de reglas locales y no lee la base configurada de la aplicación. No habilita Stripe. La fixture se limpia al cerrar normalmente el proceso con Ctrl+C. Si el proceso termina abruptamente pueden quedar archivos temporales, pero no se convierten en la base de trabajo ni se reutilizan automáticamente.

El puerto 5055 es deliberadamente independiente del servidor legacy que pudiera estar abierto en 5000. Para usar la interfaz con una instalación local existente que ya haya completado las fases SaaS, reinicia su proceso para cargar el código y abre `/saas/dashboard` en su puerto. No hace falta modificar la landing ni redirigir `/`.

## Pantallas disponibles

| Ruta | Contenido real |
| --- | --- |
| `/saas/dashboard` | Organización, usuario, plan y rol; recuentos de recursos; solicitudes pendientes; hasta seis períodos de resultados; consumo y actividad reciente; acceso a Copilot |
| `/saas/clientes` | Estado vacío de CRM y ficha de la organización activa; no transforma organizaciones de INAHI en contactos comerciales |
| `/saas/diagnosticos` | Diagnósticos autorizados y detalle de objetivos/puntuaciones |
| `/saas/estrategias` | Estrategias guardadas y detalle |
| `/saas/contenido` | Calendarios guardados y detalle; el GET no genera contenido |
| `/saas/informes` | Informes guardados y detalle |
| `/saas/automatizaciones` | Solicitudes y respuestas existentes, estado y origen; no ejecuta acciones |
| `/saas/copilot` | Pregunta, sugerencias por rol, respuesta, propuestas, alcance, fuentes, carga, errores y cuota |
| `/saas/equipo` | Miembros de la organización y roles owner/admin/manager/member/viewer |
| `/saas/facturacion` | Plan, estado, límites y consumo; solo owner/admin; sin operaciones Stripe |
| `/saas/configuracion` | Organización y cuenta del usuario actual; acceso a gestión legacy |

Las cinco colecciones de recursos admiten detalles con `/<id>` y muestran como máximo 100 registros. Cada ID se comprueba contra la organización autorizada. No se admiten filtros arbitrarios por organización.

## Copilot y navegación

Se reutilizan los endpoints y las cuotas de Fase 4. La interfaz incorpora una composición propia de asistente empresarial y sugerencias rápidas. El historial contiene como máximo cinco consultas, exclusivamente en el DOM de la página: no hay localStorage, sessionStorage, IndexedDB ni almacenamiento de conversaciones en el servidor. Se limpia al salir o recargar y utiliza `textContent` para las respuestas.

Los permisos de cada función siguen aplicándose server-side. El modo local ofrece recomendaciones por reglas, no análisis generativo. El análisis de clientes individuales sigue pendiente del CRM. Las cuotas se reservan en el backend; las tarjetas no autorizan operaciones.

Sidebar y cuenta muestran la organización, plan, usuario y rol actuales. En móvil hay un botón de navegación, panel lateral superpuesto y cierre mediante fondo/Escape; las tarjetas pasan a una o dos columnas y las tablas tienen desplazamiento horizontal. Se incluyen foco visible, enlace de salto, estados accesibles, viewport móvil y adaptación a reducción de movimiento. El CSS y JavaScript nuevos solo se cargan en la zona SaaS.

## Seguridad y compatibilidad

- Cada vista resuelve sesión, membership, estado y permisos mediante `saas_core`.
- Los recursos usan consultas con `organization_id` validado; los detalles manipulados de otra organización devuelven 404.
- Facturación exige el permiso `billing`. Ocultar botones no sustituye la autorización.
- Las pantallas de negocio exigen entitlements; el dashboard de una suscripción no pagada muestra aviso y no carga recursos de negocio. Facturación y datos de cuenta siguen accesibles con sus permisos.
- Consumo no disponible se presenta como desconocido, no como capacidad ilimitada.
- Todas las vistas devuelven `Cache-Control: no-store`; Jinja escapa textos almacenados.
- Las vistas nuevas son de consulta. Las funciones de edición existentes permanecen disponibles en el área anterior y conservan sus guards.
- El login SaaS cambia de destino a `/saas/dashboard`; el login legacy mantiene `/portal`.
- No se modifica la landing pública, su plantilla base o sus estilos; no se cambia `/portal` ni se eliminan funcionalidades anteriores.

## Archivos

Añadidos:

- `workspace_ui.py`
- `templates/workspace/base.html`
- `templates/workspace/macros.html`
- `templates/workspace/dashboard.html`
- `templates/workspace/clients.html`
- `templates/workspace/collection.html`
- `templates/workspace/team.html`
- `templates/workspace/billing.html`
- `templates/workspace/settings.html`
- `templates/workspace/error.html`
- `static/workspace.css`
- `static/workspace.js`
- `devtools/run_workspace_demo.py`
- `tests/test_workspace_ui.py`
- `docs/WORKSPACE_PHASE_5.md`

Modificados: `app.py` (registro y destino del login SaaS), `copilot/routes.py` (contexto de cabecera), `templates/copilot.html` (interfaz) y `static/copilot.js` (historial efímero).

El directorio `../docs/` ya existía sin seguimiento y no se ha modificado. Los tests anteriores permanecen intactos.

## Validación y alcance pendiente

Resultado final desde `inahi-studio-app-main`, usando el entorno existente:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

```text
264 passed, 60 subtests passed in 131.32s (0:02:11)
```

**264 pasados, 0 fallos: 245 anteriores intactos + 19 nuevos de Fase 5.** La ejecución previa pasó con 263; después se añadió la comprobación de consumo desconocido para suscripciones no asociadas y se volvió a ejecutar toda la suite. No se modificó ni eliminó ningún test de fases anteriores.

Se verificó por HTTP real contra la demo local el login/redirección, las once pantallas (200), los tres recursos CSS/JS (200) y una consulta Copilot (200) usando reglas locales. Sin solicitudes a IA externa ni Stripe. `node --check` valida ambos scripts.

Los tests nuevos cubren las rutas, navegación, scope A/B, IDs manipulados, roles, cuotas, escape de HTML, preservación de datos legacy, ausencia de llamadas externas al cargar vistas, login y compatibilidad pública. Durante la implementación se corrigieron nombres internos de endpoints; una prueba nueva de cuatro roles necesitó configurar cuatro plazas en su fixture, sin cambiar los límites del producto.

La herramienta de navegador devolvió `No browser is available` y el navegador integrado tampoco estuvo disponible. **No se ha podido realizar inspección visual ni interacción real en navegador de escritorio/móvil.** El diseño responsive está implementado y el renderizado Flask se valida, pero esa QA queda pendiente; no se presentan capturas ni se afirma haberlas comprobado.

No hay todavía formularios nuevos para editar roles/invitar miembros, modificar suscripciones o crear contactos CRM. Equipo, facturación y configuración son vistas de consulta; los detalles JSON de estrategias/calendarios conservan una presentación textual estructurada. El portal anterior permite continuar con las herramientas existentes. Estos límites están visibles, sin botones de acciones ficticias.

Sin deploy, merge, cambios en producción o en `original-app-backup`.
