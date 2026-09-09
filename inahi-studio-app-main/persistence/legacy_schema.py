"""Frozen SQLite preparation for pre-Alembic compatibility; explicit calls only."""
from contextlib import closing

def crear_db(conectar):
    with closing(conectar()) as c, c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS consultas(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL,
            problema TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS clientes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            correo TEXT UNIQUE NOT NULL,
            contrasena TEXT NOT NULL,
            plan TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS solicitudes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            asunto TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            respuesta TEXT DEFAULT '',
            estado TEXT DEFAULT 'Pendiente',
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS informes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            contenido TEXT NOT NULL,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS citas(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            hora TEXT NOT NULL,
            modalidad TEXT NOT NULL,
            motivo TEXT NOT NULL,
            estado TEXT DEFAULT 'Pendiente',
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS diagnosticos(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL UNIQUE,
            web INTEGER NOT NULL DEFAULT 0,
            google INTEGER NOT NULL DEFAULT 0,
            redes INTEGER NOT NULL DEFAULT 0,
            resenas INTEGER NOT NULL DEFAULT 0,
            objetivos TEXT DEFAULT '',
            puntuacion INTEGER NOT NULL DEFAULT 0,
            actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS password_resets(
            token TEXT PRIMARY KEY,
            cliente_id INTEGER NOT NULL,
            expira TIMESTAMP NOT NULL,
            usado INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS email_verifications(
            token TEXT PRIMARY KEY,
            cliente_id INTEGER NOT NULL,
            expira TIMESTAMP NOT NULL,
            usado INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS rate_limits(
            clave TEXT PRIMARY KEY,
            inicio INTEGER NOT NULL,
            intentos INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS servicios_solicitados(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            servicio_key TEXT NOT NULL,
            servicio_nombre TEXT NOT NULL,
            precio TEXT NOT NULL,
            nombre TEXT NOT NULL,
            empresa TEXT NOT NULL,
            correo TEXT NOT NULL,
            telefono TEXT DEFAULT '',
            mensaje TEXT DEFAULT '',
            estado TEXT NOT NULL DEFAULT 'Nueva',
            fecha TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS estrategias_comerciales(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL UNIQUE,
            respuestas TEXT NOT NULL,
            estrategia TEXT NOT NULL,
            actualizado TEXT NOT NULL,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS calendarios_contenido(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            periodo TEXT NOT NULL,
            contenido TEXT NOT NULL,
            creado TEXT NOT NULL,
            UNIQUE(cliente_id, periodo),
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS resultados_mensuales(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            periodo TEXT NOT NULL,
            contactos INTEGER NOT NULL DEFAULT 0,
            ventas INTEGER NOT NULL DEFAULT 0,
            ingresos REAL NOT NULL DEFAULT 0,
            resenas INTEGER NOT NULL DEFAULT 0,
            notas TEXT DEFAULT '',
            informe TEXT NOT NULL,
            creado TEXT NOT NULL,
            UNIQUE(cliente_id, periodo),
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );
        """)

def actualizar_consultas(conectar):
    """Añade columnas legacy ausentes; nunca recalcula cuentas o cupos."""
    with closing(conectar()) as c, c:
        columnas = [
            fila["name"]
            for fila in c.execute("PRAGMA table_info(consultas)").fetchall()
        ]

        if "correo" not in columnas:
            c.execute("ALTER TABLE consultas ADD COLUMN correo TEXT DEFAULT ''")

        if "respuesta" not in columnas:
            c.execute("ALTER TABLE consultas ADD COLUMN respuesta TEXT DEFAULT ''")

        if "token" not in columnas:
            c.execute("ALTER TABLE consultas ADD COLUMN token TEXT DEFAULT ''")

        columnas_cliente = {fila["name"] for fila in c.execute("PRAGMA table_info(clientes)").fetchall()}
        nuevas = {
            "plan_key": "TEXT DEFAULT ''",
            "stripe_customer_id": "TEXT DEFAULT ''",
            "stripe_subscription_id": "TEXT DEFAULT ''",
            "subscription_status": "TEXT DEFAULT 'sin_pago'",
            "creado": "TEXT DEFAULT ''",
            "trial_end": "TEXT DEFAULT ''",
            "email_verificado": "INTEGER NOT NULL DEFAULT 1",
            "legal_accepted_at": "TEXT DEFAULT ''",
            "trial_slot": "INTEGER NOT NULL DEFAULT 0",
            "trial_queries_used": "INTEGER NOT NULL DEFAULT 0",
        }
        for nombre, definicion in nuevas.items():
            if nombre not in columnas_cliente:
                c.execute(f"ALTER TABLE clientes ADD COLUMN {nombre} {definicion}")

        columnas_solicitud = {fila["name"] for fila in c.execute("PRAGMA table_info(solicitudes)").fetchall()}
        if "fecha" not in columnas_solicitud:
            c.execute("ALTER TABLE solicitudes ADD COLUMN fecha TEXT DEFAULT ''")
        if "origen_respuesta" not in columnas_solicitud:
            c.execute("ALTER TABLE solicitudes ADD COLUMN origen_respuesta TEXT DEFAULT 'automatizacion'")

