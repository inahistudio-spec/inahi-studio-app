# Login de la demo: causa raíz confirmada

## Evidencia en el proceso real

El 9 de septiembre se encontraron dos listeners simultáneos sobre `127.0.0.1:5055`:

- PID 11732, iniciado a las 15:30:05: demo antigua que el agente había dejado abierta con `a@example.com`.
- PID 20600, iniciado a las 18:36:04: nueva demo del usuario con `qa@example.com`.

El servidor de desarrollo de Werkzeug tenía `allow_reuse_address=True`. En Windows, `SO_REUSEADDR` permitió que los dos procesos coexistieran en el mismo puerto. El mensaje de arranque del proceso nuevo no demostraba qué proceso atendía las peticiones de Chrome.

Los logs de la sesión antigua contenían los POST reales fallidos del usuario. Se reprodujo por TCP/HTTP con cookies y CSRF:

1. `qa@example.com` permanecía en `/cliente/acceso`, con estado 200 y credenciales incorrectas.
2. `a@example.com` accedía a `/saas/dashboard` por el mismo puerto.
3. Tras detener únicamente el proceso antiguo del agente, `qa@example.com` accedió a `/saas/dashboard`, mostrando Estudio Norte, sin modificar contraseña, datos ni autenticación del proceso nuevo.

Por tanto, la causa real de la persistencia del fallo era el proceso antiguo atendiendo el puerto, no un hash incorrecto. La corrección anterior del correo no podía modificar una base temporal ya cargada en otro proceso.

## Bases, configuración y autenticación

- Cada arranque utiliza su propio `TemporaryDirectory` y `saas.db`. La instancia antigua y la nueva tenían bases distintas; la fixture no desaparece al iniciar el servidor. Se limpia al terminar normalmente su proceso.
- La fixture crea las identidades A/B y su migración SaaS. El bootstrap de demo asigna `qa@example.com` al usuario 1 y al carrier legacy 1, y lo mantiene como owner de Estudio Norte.
- `/cliente/acceso` usa la autenticación normal: `saas_authenticate`, búsqueda por `users.email` y `check_password_hash`. El hash real de la fixture es `pbkdf2:sha256:1000`, con salt y digest; no se sustituye por texto plano ni se debilita respecto a la fixture existente.
- `app.conectar()` delega en la persistencia, donde `DATABASE_URL` tiene precedencia sobre `app.DB`. Antes dependía de que el entorno siguiera limpio. Ahora ambos apuntan explícitamente al mismo SQLite temporal; se comprueba `PRAGMA database_list` antes de servir.
- El entorno de aplicación se aísla antes de importar `app.py`. Solo se conservan ubicaciones temporales. No se heredan credenciales, DATABASE_URL, FLASK_ENV o proveedor IA del entorno exterior.
- No se usa `Flask.run()` en esta demo: el servidor WSGI local se crea directamente, sin cargar `.env`, `.flaskenv` ni reloader. La carga de dotenv se investigó como riesgo, pero no fue la causa del incidente confirmado.

## Corrección

`ExclusiveDemoServer` desactiva la reutilización de dirección y utiliza `SO_EXCLUSIVEADDRUSE` cuando está disponible en Windows. Un puerto ocupado provoca un fallo explícito, sin anunciar credenciales ni disponibilidad. La comprobación no es una prueba previa seguida de cerrar/reabrir el socket: se conserva el socket reservado durante toda la ejecución.

Solo después de abrir el puerto se imprime `DEMO_RUNTIME`, con PID real, PID padre, ruta SQLite efectiva, DATABASE_URL local, usuario, organización y formato del hash (no el hash ni su salt). La cookie de sesión tiene un nombre propio por puerto de demo, manteniendo la autenticación, CSRF y permisos habituales.

No se ha modificado el login general, el backend de producción ni la fixture genérica A/B. Los cambios de esta corrección se limitan al runner de demo, tests y documentación.

## Pruebas

La prueba anterior sustituía `app.run()` y por eso no podía detectar la colisión de puertos. Se conserva su comprobación de bootstrap, contraseña real, sesión y aislamiento, adaptada al nuevo servidor y a la DATABASE_URL explícita.

`tests/test_workspace_demo_process.py` añade pruebas con un **subproceso real**, el mismo script de arranque y conexiones HTTP TCP; no sustituye el servidor ni utiliza Flask test_client:

- Arranque desde otro directorio, con DATABASE_URL/DATABASE_PATH ajenas, `.env` y variables de proveedor externo deliberadamente configuradas con valores de prueba.
- Verificación de PID/parent PID (el launcher del venv Windows crea un intérprete hijo), ruta SQLite temporal y correspondencia con DATABASE_URL.
- Login GET → CSRF → contraseña incorrecta rechazada → contraseña correcta → redirect `/saas/dashboard` → Estudio Norte.
- Recursos de otra organización rechazados con 404.
- Consulta Copilot atendida exclusivamente por reglas locales.
- Base SQLite ajena de control conservada byte a byte.
- Segundo proceso en el mismo puerto rechazado antes de anunciar credenciales; el primer proceso continúa atendiendo.
- Intento de bind con SO_REUSEADDR rechazado mientras la demo exclusiva está activa.

Las tres pruebas focalizadas de demo pasan. La validación final ejecuta toda la suite con:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Reinicio del usuario

Detener con Ctrl+C la demo actual en su consola. Desde `inahi-studio-app-main`:

```powershell
.\.venv\Scripts\python.exe devtools/run_workspace_demo.py --port 5055
```

Abrir `http://127.0.0.1:5055/saas/dashboard` y acceder con `qa@example.com` / `Legacy-password-123`. Si el puerto está ocupado, cerrar la otra demo en su consola; no ejecutar otra instancia encima ni terminar procesos desconocidos.

Sin conexiones a producción, pagos, llamadas externas de IA, deploy o merge. `original-app-backup` permanece intacto.
