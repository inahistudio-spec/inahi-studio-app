# Validación Fase 4 — 9 de septiembre de 2026

## Resultado

```text
245 passed, 60 subtests passed in 112.85s (0:01:52)
```

**245 tests pasados, 0 fallos; 51 tests nuevos de Fase 4.** Los 194 tests anteriores permanecen intactos y siguen pasando. Los 60 subtests anteriores también pasan. No se eliminó ningún test para obtener este resultado.

La suite de partida se ejecutó antes de integrar Fase 4: `194 passed, 60 subtests passed in 94.61s`.

## Comando y entorno

Desde `inahi-studio-app-main` se intentó el comando solicitado:

```powershell
..\.venv\Scripts\python.exe -m pytest -q
```

El entorno del directorio padre no pudo iniciarse porque Windows denegó acceso al ejecutable base:

```text
did not find executable at 'C:\Users\usuario\AppData\Local\Programs\Python\Python313\python.exe': Acceso denegado.
```

Se utilizó el entorno **existente dentro de la aplicación**, previamente utilizado para validar Fase 3:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Este es el comando que produjo el resultado de 245 tests. No se instaló Python, no se alteró ningún entorno virtual ni se cambiaron políticas de Windows para ejecutar el intérprete bloqueado. El comando exacto del directorio padre sigue pendiente de resolver en ese entorno; no se presenta como ejecutado correctamente.

## Cobertura nueva

`tests/test_copilot.py` contiene 51 casos recolectados:

- Contexto por función; filtros A/B; exclusión de contraseñas, hashes, emails, tokens y IDs Stripe.
- ID de recurso manipulado, organization/client/user IDs en formularios/query parameters, sesión sin membership y autorización directa del context builder.
- Roles viewer/member/manager/admin; autenticación y CSRF; revocación de membership o suscripción durante la llamada.
- Las siete funciones con proveedor local; proveedor falso con tokens/coste; adaptador OpenAI con transporte falso y bloqueo de red en modo de tests.
- Prompt injection en pregunta y datos almacenados; salida con HTML, enlaces, secretos, herramientas o referencias ajenas rechazada.
- Reserva durable, deduplicación, cuotas mensuales y compartidas con billing, rate limit, consultas concurrentes y consumo aislado A/B.
- Errores de proveedor sin detalles sensibles; auditoría; tokens/costes conocidos y desconocidos; rechazo de contabilidad de tokens inválida.
- Renderizado de interfaz, elementos accesibles y ausencia de caché en respuestas.
- DDL PostgreSQL offline; migración SQLite real en base temporal, rollback lógico, rechazo de rollback con llamadas pendientes, integridad referencial y conservación de datos legacy.

**Test obligatorio aprobado:**
`CopilotTests.test_mandatory_a_cannot_include_b_by_manipulated_resource_id` crea datos A/B, autentica A y solicita `resource_kind=informes&resource_id=2` perteneciente a B. El servidor devuelve **404**, no reserva consumo ni invoca al proveedor. La petición posterior al informe propio devuelve 200 y el payload contiene `Secret A`, sin `Secret B`, `Empresa B` ni `informes:2`.

La primera ejecución focalizada produjo 50 aprobados y un fallo de montaje en un test nuevo: se intentaba revocar una membership con `inactive`, estado que el esquema no admite. Se corrigió el dato del fixture a `revoked`, manteniendo la misma exigencia de respuesta 403 y estado `denied_after_call`. Después se ejecutó toda la suite con el resultado final anterior. Ningún test de fases anteriores se modificó.

Verificaciones adicionales: `node --check static/copilot.js` y `git diff --check` sin errores. No se declara QA visual completa en navegador ni ejecución de un proveedor real/PostgreSQL real.

## Archivos de esta fase

Modificados:

- `.env.example`
- `app.py` (solo registro del módulo)
- `persistence/migrations.py` (opción explícita `--copilot`)
- `templates/base.html` (acceso al Copilot)

Añadidos:

- `copilot/__init__.py`
- `copilot/audit.py`
- `copilot/context.py`
- `copilot/errors.py`
- `copilot/features.py`
- `copilot/permissions.py`
- `copilot/prompts.py`
- `copilot/providers.py`
- `copilot/routes.py`
- `copilot/sanitization.py`
- `copilot/schema.py`
- `copilot/service.py`
- `copilot/usage.py`
- `copilot/validation.py`
- `migrations/versions/0004_copilot.py`
- `static/copilot.js`
- `templates/copilot.html`
- `tests/test_copilot.py`
- `docs/COPILOT_PHASE_4.md`
- `docs/VALIDATION_PHASE_4.md`

El directorio `../docs/` ya figuraba sin seguimiento antes de empezar y no forma parte de esta implementación ni se ha modificado.

## Límites operativos respetados

- Rama de trabajo: `saas-b2b-v2`.
- `original-app-backup` conserva la referencia `f245ed07151309f18fc463d817e491af138e0684`.
- Sin deploy, merge, cambios sobre producción ni llamadas reales a IA o Stripe.
- Sin ejecutar `init-db` o migraciones contra la base de trabajo. Los fixtures existentes inicializan únicamente bases SQLite temporales; los tests nuevos migran esas bases desechables.
- No se han borrado clientes existentes ni sustituido funcionalidades legacy.

Riesgos pendientes y configuración de activación: [COPILOT_PHASE_4.md](COPILOT_PHASE_4.md). La validación técnica local está completada; la activación externa requiere todavía revisar modelo, privacidad, costes y probar PostgreSQL/UX en el entorno previsto.
