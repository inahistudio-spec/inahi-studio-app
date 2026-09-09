import hashlib, html, json, logging, os, secrets, smtplib, sqlite3, time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
from contextlib import closing
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from automatizacion import generar_calendario_contenidos, generar_informe_mensual, generar_respuesta_automatica
from ia import asesor_comercial_ia, ia_configurada
from billing_webhooks import procesar_evento_stripe
from saas_schema import enabled as saas_enabled, audit as saas_audit, now as saas_now
from saas_core import authenticate as saas_authenticate, enroll_if_enabled, resolve_context, change_password
from saas_routes import install_saas
from persistence import legacy_schema, queries, repositories
from persistence.database import connect as connect_database, configured_url

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DATABASE_PATH", os.path.join(BASE, "consultas.db"))
DB_DIR = os.path.dirname(os.path.abspath(DB))
TRIAL_MAX_COMPANIES = 5
TRIAL_DAYS = 14
TRIAL_QUERY_LIMIT = 10
CAMPAIGN_RESET_MIGRATION = "2026-09-prueba-cinco-empresas"
PLANES_INFO = {
    "esencial": {"nombre": "Esencial", "precio": 29, "price_env": "STRIPE_PRICE_ESENCIAL", "consultas": 10, "contenidos": 8, "reuniones": 0, "duracion": 0},
    "crecimiento": {"nombre": "Crecimiento", "precio": 59, "price_env": "STRIPE_PRICE_CRECIMIENTO", "consultas": 30, "contenidos": 16, "reuniones": 1, "duracion": 30},
    "pro": {"nombre": "Pro", "precio": 99, "price_env": "STRIPE_PRICE_PRO", "consultas": 999, "contenidos": 30, "reuniones": 2, "duracion": 45},
}
PLANES = tuple(f"Plan {p['nombre']} — {p['precio']} €/mes" for p in PLANES_INFO.values())
SERVICIOS_INFO = {
    "diagnostico": {"nombre": "Diagnóstico digital", "precio": "89 €", "categoria": "Análisis", "descripcion": "Revisión de tu presencia digital y prioridades de mejora."},
    "google": {"nombre": "Optimización de Google Business", "precio": "119 €", "categoria": "Google", "descripcion": "Creación u optimización de tu ficha para mejorar la visibilidad local."},
    "instagram": {"nombre": "Instagram profesional", "precio": "119 €", "categoria": "Redes sociales", "descripcion": "Optimización del perfil, imagen, biografía y estructura de contenidos."},
    "mejora-web": {"nombre": "Mejora de página web", "precio": "Desde 149 €", "categoria": "Web", "descripcion": "Revisión y optimización de una web existente."},
    "web-profesional": {"nombre": "Web profesional", "precio": "Desde 599 €", "categoria": "Web", "descripcion": "Web clara, adaptable a móvil y preparada para captar contactos."},
}
ADMIN_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "pbkdf2:sha256:1000000$3LH0fWpOHefT4uex$1199e495a1f095bfe67b38784679923696b876c826612febd0a74d354276c37e")

app = Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY", secrets.token_hex(32)), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV")=="production", MAX_CONTENT_LENGTH=2*1024*1024)

logger = logging.getLogger(__name__)

def identidad_legal_completa():
    return all(os.environ.get(k, "").strip() for k in ("LEGAL_BUSINESS_NAME", "LEGAL_TAX_ID", "LEGAL_ADDRESS"))

def pagos_reales_permitidos():
    return (
        os.environ.get("ALLOW_LIVE_PAYMENTS", "").strip().lower() == "true"
        and os.environ.get("LEGAL_TERMS_APPROVED", "").strip().lower() == "true"
        and not stripe_es_modo_prueba()
        and identidad_legal_completa()
    )

def stripe_es_modo_prueba():
    return os.environ.get("STRIPE_MODE", "test").strip().lower() == "test"

def stripe_cliente():
    clave = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not clave:
        return None
    if stripe_es_modo_prueba() and not clave.startswith("sk_test_"):
        logger.error("Stripe bloqueado: STRIPE_MODE=test solo admite claves sk_test_")
        return None
    if not stripe_es_modo_prueba() and (not clave.startswith("sk_live_") or not pagos_reales_permitidos()):
        logger.error("Stripe real bloqueado: faltan autorización explícita o datos legales")
        return None
    try:
        import stripe
        stripe.api_key = clave
        return stripe
    except ImportError:
        logger.exception("Falta instalar la dependencia stripe")
        return None

def nombre_plan(plan_key):
    plan = PLANES_INFO.get(plan_key)
    return f"Plan {plan['nombre']} — {plan['precio']} €/mes" if plan else "Sin plan activo"

def plan_por_precio(price_id):
    for key, plan in PLANES_INFO.items():
        if price_id and price_id == os.environ.get(plan["price_env"], "").strip():
            return key
    return None

def stripe_configurado(plan_key=None):
    if not stripe_cliente():
        return False
    planes = (plan_key,) if plan_key in PLANES_INFO else PLANES_INFO.keys()
    return all(os.environ.get(PLANES_INFO[key]["price_env"], "").strip().startswith("price_") for key in planes)

def generar_estrategia_comercial(datos):
    sector = datos["sector"]
    ubicacion = datos["ubicacion"]
    oferta = datos["oferta"]
    cliente = datos["cliente_ideal"]
    objetivo = datos["objetivo"]
    meta = datos["meta"]
    presupuesto = datos["presupuesto"]
    tiempo = datos["tiempo"]

    perfiles = {
        "peluqueria_estetica": {
            "nombre": "peluquería o negocio de estética",
            "canales": ["Google Business", "Instagram", "WhatsApp"],
            "acciones": [
                "Publicar resultados reales con permiso del cliente y una llamada clara a reservar.",
                "Pedir reseñas después de cada servicio y responderlas en un máximo de 48 horas.",
                "Ofrecer la siguiente cita antes de que el cliente abandone el establecimiento.",
            ],
            "promociones": [
                "Primera visita con diagnóstico o asesoramiento breve incluido.",
                "Programa de recomendación: beneficio para quien invita y para el nuevo cliente.",
                "Pack de dos servicios complementarios sin rebajar el servicio principal.",
            ],
        },
        "comercio": {
            "nombre": "comercio local",
            "canales": ["Google Business", "Instagram", "WhatsApp"],
            "acciones": [
                "Mostrar productos concretos con precio, disponibilidad y forma de compra.",
                "Actualizar semanalmente Google con novedades, horarios y fotografías reales.",
                "Crear una lista de clientes que acepten recibir novedades y reposiciones.",
            ],
            "promociones": [
                "Pack temático que aumente el importe medio de compra.",
                "Ventaja de segunda compra con fecha de caducidad.",
                "Campaña sobre producto lento combinándolo con uno de alta demanda.",
            ],
        },
        "hosteleria": {
            "nombre": "negocio de hostelería",
            "canales": ["Google Business", "Instagram", "Reservas directas"],
            "acciones": [
                "Mantener carta, horarios, teléfono y enlace de reserva actualizados en Google.",
                "Publicar platos, ambiente y experiencias reales, no solo carteles promocionales.",
                "Pedir reseñas en los momentos de mayor satisfacción del cliente.",
            ],
            "promociones": [
                "Propuesta específica para las horas o días con menor ocupación.",
                "Menú o experiencia cerrada para grupos y celebraciones.",
                "Incentivo de repetición que no dependa de descuentos permanentes.",
            ],
        },
        "salud_bienestar": {
            "nombre": "negocio de salud o bienestar",
            "canales": ["Google Business", "Instagram", "Recomendaciones"],
            "acciones": [
                "Explicar cada servicio mediante problemas que resuelve y expectativas realistas.",
                "Publicar contenido educativo que responda dudas frecuentes sin promesas exageradas.",
                "Crear un seguimiento después de la primera visita para favorecer la continuidad.",
            ],
            "promociones": [
                "Primera valoración con alcance y precio claramente definidos.",
                "Programa de continuidad basado en objetivos, no en descuentos agresivos.",
                "Colaboración con un negocio local complementario.",
            ],
        },
        "servicios_profesionales": {
            "nombre": "negocio de servicios profesionales",
            "canales": ["Google Business", "LinkedIn", "Correo electrónico"],
            "acciones": [
                "Convertir los servicios en paquetes con resultado, alcance y precio orientativo.",
                "Publicar casos, procesos y respuestas a objeciones habituales.",
                "Solicitar recomendaciones a clientes satisfechos de forma sistemática.",
            ],
            "promociones": [
                "Diagnóstico inicial con una propuesta de siguientes pasos.",
                "Paquete de entrada con alcance cerrado y riesgo reducido.",
                "Programa de recomendación para clientes y colaboradores.",
            ],
        },
        "otro": {
            "nombre": "negocio local",
            "canales": ["Google Business", "Red social principal", "Contacto directo"],
            "acciones": [
                "Explicar con claridad qué problema resuelve la oferta y cómo contratarla.",
                "Publicar pruebas reales del trabajo y respuestas a dudas frecuentes.",
                "Pedir recomendaciones y reseñas de forma constante.",
            ],
            "promociones": [
                "Oferta de entrada con alcance y precio cerrados.",
                "Programa de recomendación para clientes satisfechos.",
                "Pack que combine el servicio principal con un complemento útil.",
            ],
        },
    }
    perfil = perfiles.get(sector, perfiles["otro"])
    actividad = datos.get("actividad", "").strip() or perfil["nombre"]
    conversion = datos.get("conversion", "contacto")
    acciones_conversion = {
        "compra": ("comprar", "ventas"),
        "encargo": ("hacer su encargo", "pedidos"),
        "reserva": ("reservar", "reservas"),
        "cita": ("pedir cita", "citas"),
        "presupuesto": ("solicitar presupuesto", "presupuestos"),
        "contacto": ("contactar", "oportunidades"),
    }
    accion_cliente, resultado = acciones_conversion.get(conversion, acciones_conversion["contacto"])
    objetivos = {
        "captar_clientes": "captar nuevos clientes",
        "aumentar_reservas": "aumentar las reservas",
        "aumentar_ventas": "aumentar las ventas",
        "fidelizar": "conseguir que los clientes repitan",
        "visibilidad": "mejorar la visibilidad local",
    }
    objetivo_texto = objetivos.get(objetivo, "mejorar los resultados comerciales")
    canales_elegidos = datos.get("canales") or perfil["canales"]
    canal_principal = canales_elegidos[0]

    if presupuesto == "sin_presupuesto":
        accion_presupuesto = "Prioriza Google, recomendaciones y contenido orgánico; no inviertas en anuncios durante los primeros 30 días."
    elif presupuesto == "hasta_100":
        accion_presupuesto = "Reserva hasta 100 € para una única prueba publicitaria local después de mejorar la oferta y la medición."
    elif presupuesto == "100_300":
        accion_presupuesto = "Destina entre 100 € y 300 € a una campaña local de prueba con una sola oferta y seguimiento semanal."
    else:
        accion_presupuesto = "Divide el presupuesto entre captación, seguimiento y una reserva para repetir únicamente lo que demuestre resultados."

    if tiempo == "menos_2":
        ritmo = "dos acciones esenciales por semana"
        semana = ["Actualizar un activo comercial.", "Contactar o hacer seguimiento a cinco clientes."]
    elif tiempo == "2_4":
        ritmo = "tres acciones comerciales por semana"
        semana = ["Publicar una prueba o caso real.", "Pedir reseñas o recomendaciones.", "Revisar contactos, reservas y ventas."]
    else:
        ritmo = "cuatro acciones comerciales por semana"
        semana = ["Publicar dos contenidos útiles o pruebas reales.", "Pedir reseñas o recomendaciones.", "Realizar seguimiento de clientes anteriores.", "Revisar métricas y preparar la siguiente semana."]

    prioridades = [
        f"Definir una oferta principal de {oferta} dirigida a {cliente}.",
        f"Optimizar {canal_principal} para que cualquier persona entienda qué comprar y cómo contactar.",
        *perfil["acciones"][:2],
        accion_presupuesto,
    ]
    return {
        "titulo": f"Estrategia comercial para {datos['nombre_negocio']}",
        "resumen": f"Plan para {actividad} en {ubicacion} que quiere {objetivo_texto}. La prioridad será convertir la oferta «{oferta}» en una propuesta clara para {cliente}, trabajando con {ritmo}.",
        "objetivo": f"Objetivo principal: {objetivo_texto}. Meta declarada: {meta}.",
        "propuesta": f"Presenta {oferta} como una solución concreta para {cliente}. Destaca como fortaleza «{datos['fortaleza']}» y elimina la principal barrera detectada: «{datos['problema']}». Cada mensaje debe terminar explicando claramente cómo {accion_cliente}.",
        "canales": canales_elegidos[:3],
        "prioridades": prioridades,
        "plan_30": [
            "Completar la información comercial, precios orientativos y llamada a la acción en los canales elegidos.",
            "Preparar una oferta principal y una promoción de entrada sin devaluar el servicio.",
            "Recopilar cinco pruebas de confianza: reseñas, fotografías, resultados o casos.",
            f"Registrar durante cuatro semanas contactos y {resultado} procedentes de cada canal.",
        ],
        "plan_60": [
            "Repetir el contenido y la oferta que hayan generado más contactos.",
            "Contactar con clientes anteriores mediante un mensaje útil y personalizado.",
            "Probar una de las promociones propuestas durante un periodo limitado.",
            "Corregir el canal que reciba visitas pero no genere conversaciones o compras.",
        ],
        "plan_90": [
            "Comparar resultados con la meta y calcular qué canal produce mejores oportunidades.",
            "Mantener solo las acciones que puedan repetirse de forma sostenible.",
            "Crear un sistema mensual de reseñas, seguimiento y reactivación de clientes.",
            "Actualizar esta estrategia con los resultados reales de los primeros 90 días.",
        ],
        "semana": semana,
        "promociones": perfil["promociones"],
        "kpis": [
            "Nuevos contactos recibidos.",
            "Reservas o ventas conseguidas.",
            "Porcentaje de contactos que terminan comprando.",
            "Importe medio por cliente.",
            "Clientes que repiten y nuevas reseñas.",
        ],
    }

def enviar_email(destinatario, asunto, texto, contenido_html=None):
    """Envía por la API HTTPS de Resend; conserva SMTP como alternativa."""
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if resend_key:
        remitente_resend = os.environ.get(
            "RESEND_FROM", "Inahi Studio <notificaciones@send.inahistudio.com>"
        ).strip()
        datos = {
            "from": remitente_resend,
            "to": [destinatario],
            "subject": asunto,
            "text": texto,
            "html": contenido_html or f"<p>{html.escape(texto)}</p>",
        }
        peticion = Request(
            "https://api.resend.com/emails",
            data=json.dumps(datos).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {resend_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Evita el bloqueo 1010 de Cloudflare/Resend que puede provocar
                # el identificador predeterminado de urllib (Python-urllib).
                "User-Agent": "InahiStudio/1.0 (+https://app.inahistudio.com)",
            },
            method="POST",
        )
        try:
            with urlopen(peticion, timeout=15) as respuesta:
                return 200 <= respuesta.status < 300
        except HTTPError as error:
            try:
                detalle = error.read().decode("utf-8", errors="replace")
            except Exception:
                detalle = "Sin detalle"
            logger.error(
                "Resend rechazó el correo a %s (HTTP %s): %s",
                destinatario,
                error.code,
                detalle,
            )
            return False
        except (URLError, OSError):
            logger.exception("No se pudo conectar con Resend para %s", destinatario)
            return False

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    usuario = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    remitente = os.environ.get("SMTP_FROM", usuario).strip()

    if not usuario or not password or not remitente:
        logger.warning("Correo no enviado: faltan SMTP_USER, SMTP_PASSWORD o SMTP_FROM")
        return False

    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = remitente
    mensaje["To"] = destinatario
    mensaje.set_content(texto)
    if contenido_html:
        mensaje.add_alternative(contenido_html, subtype="html")

    try:
        with smtplib.SMTP(host, port, timeout=15) as servidor:
            servidor.ehlo()
            servidor.starttls()
            servidor.ehlo()
            servidor.login(usuario, password)
            servidor.send_message(mensaje)
        return True
    except (OSError, smtplib.SMTPException):
        logger.exception("No se pudo enviar el correo a %s", destinatario)
        return False

def notificar_equipo(asunto, texto):
    """Avisa al equipo sin exponer la dirección interna en formularios públicos."""
    destino = os.environ.get("TEAM_NOTIFICATION_EMAIL", "").strip() or os.environ.get("SMTP_FROM", "").strip()
    if not destino:
        logger.warning("Aviso al equipo no enviado: falta TEAM_NOTIFICATION_EMAIL o SMTP_FROM")
        return False
    return enviar_email(destino, asunto, texto)

def enlace_publico(endpoint, **valores):
    base = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    ruta = url_for(endpoint, **valores)
    return f"{base}{ruta}" if base else url_for(endpoint, _external=True, **valores)

def email_consulta_recibida(destinatario, empresa, token):
    enlace = enlace_publico("consulta_cliente", token=token)
    empresa_html = html.escape(empresa)
    enlace_html = html.escape(enlace, quote=True)
    texto = (
        f"Hola, {empresa}.\n\n"
        "Hemos recibido tu consulta en Inahistudio. "
        "Puedes guardar este enlace privado para consultar nuestra respuesta:\n\n"
        f"{enlace}\n\n"
        "No compartas este enlace con otras personas."
    )
    contenido_html = f"""
    <p>Hola, <strong>{empresa_html}</strong>.</p>
    <p>Hemos recibido tu consulta en Inahistudio.</p>
    <p><a href="{enlace_html}">Ver mi consulta</a></p>
    <p>Guarda este enlace privado y no lo compartas con otras personas.</p>
    """
    return enviar_email(destinatario, "Hemos recibido tu consulta | Inahistudio", texto, contenido_html)

def email_respuesta_disponible(destinatario, empresa, token):
    enlace = enlace_publico("consulta_cliente", token=token)
    empresa_html = html.escape(empresa)
    enlace_html = html.escape(enlace, quote=True)
    texto = (
        f"Hola, {empresa}.\n\n"
        "Inahistudio ya ha respondido a tu consulta. "
        "Puedes verla desde tu enlace privado:\n\n"
        f"{enlace}\n\n"
        "No compartas este enlace con otras personas."
    )
    contenido_html = f"""
    <p>Hola, <strong>{empresa_html}</strong>.</p>
    <p>Inahistudio ya ha respondido a tu consulta.</p>
    <p><a href="{enlace_html}">Ver la respuesta</a></p>
    <p>Este enlace es privado. No lo compartas con otras personas.</p>
    """
    return enviar_email(destinatario, "Ya tienes respuesta de Inahistudio", texto, contenido_html)

def email_verificar_cuenta(destinatario, empresa, token):
    enlace = enlace_publico("verificar_email", token=token)
    empresa_html = html.escape(empresa)
    enlace_html = html.escape(enlace, quote=True)
    texto = f"Hola, {empresa}.\n\nConfirma tu correo para activar tu demostración de InahiStudio:\n\n{enlace}\n\nEl enlace caduca en 24 horas."
    contenido_html = f"<p>Hola, <strong>{empresa_html}</strong>.</p><p>Confirma tu correo para activar tu demostración de InahiStudio.</p><p><a href=\"{enlace_html}\">Verificar mi correo</a></p><p>El enlace caduca en 24 horas.</p>"
    return enviar_email(destinatario, "Verifica tu cuenta de InahiStudio", texto, contenido_html)

def conectar():
    return connect_database(DB)

def identificador_cliente():
    ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "desconocido")
    return hashlib.sha256((ip + app.config["SECRET_KEY"][:16]).encode()).hexdigest()[:24]

def permitir_intento(accion, limite, ventana_segundos):
    ahora = int(time.time())
    clave = f"{accion}:{identificador_cliente()}"
    with conectar() as c:
        fila = c.execute(queries.PERMITIR_INTENTO_3, (clave,)).fetchone()
        if not fila or ahora - fila["inicio"] >= ventana_segundos:
            c.execute(queries.PERMITIR_INTENTO_2, (clave, ahora))
            return True
        if fila["intentos"] >= limite:
            return False
        c.execute(queries.PERMITIR_INTENTO_1, (clave,))
        return True

def crear_token_verificacion(cliente_id):
    token = secrets.token_urlsafe(32)
    ahora = datetime.now(timezone.utc)
    with conectar() as c:
        c.execute(queries.CREAR_TOKEN_VERIFICACION_1, (cliente_id, ahora.isoformat()))
        c.execute(
            queries.CREAR_TOKEN_VERIFICACION_2,
            (token, cliente_id, (ahora + timedelta(hours=24)).isoformat()),
        )
    return token

def crear_db():
    return legacy_schema.crear_db(conectar)


def actualizar_consultas():
    return legacy_schema.actualizar_consultas(conectar)


def limpiar_cuentas_anteriores_a_campana():
    """Compatibilidad: la limpieza histórica irreversible ya no está permitida."""
    raise RuntimeError("Limpieza de campaña deshabilitada: no se borrarán clientes.")


def inicializar_base_datos():
    """Preparación explícita y aditiva; no recalcula ni elimina cuentas."""
    if configured_url(DB).get_backend_name() != "sqlite":
        raise ValueError("PostgreSQL requiere db-upgrade con informe previo")
    os.makedirs(os.path.dirname(os.path.abspath(configured_url(DB).database)), exist_ok=True)
    crear_db()
    actualizar_consultas()
    with closing(conectar()) as c, c:
        c.execute(queries.INICIALIZAR_BASE_DATOS_1)


@app.cli.command("init-db")
def init_db_command():
    """Prepara explícitamente DATABASE_PATH sin transformar cuentas existentes."""
    inicializar_base_datos()

def admin_required(f):
    @wraps(f)
    def w(*a,**k):
        if session.get("user_id"): abort(403)
        if not session.get("administrador"): return redirect(url_for("acceso"))
        return f(*a,**k)
    return w

def client_required(f):
    @wraps(f)
    def w(*a,**k):
        cid=session.get("cliente_id")
        if not cid: return redirect(url_for("cliente_acceso"))
        with conectar() as c:
            cliente=c.execute(queries.CLIENT_REQUIRED_1,(cid,)).fetchone()
            if cliente and cliente["subscription_status"] == "prueba" and cliente["trial_end"]:
                if date.fromisoformat(cliente["trial_end"]) < date.today():
                    c.execute(queries.CLIENT_REQUIRED_2,(cid,))
                    cliente=None
            ok=cliente if cliente and cliente["activo"] else None
        if not ok: session.clear(); flash("La cuenta no está activa.","error"); return redirect(url_for("cliente_acceso"))
        return f(*a,**k)
    return w

@app.context_processor
def globals_():
    session.setdefault("csrf_token",secrets.token_urlsafe(32)); return {
        "csrf_token":session["csrf_token"], "planes":PLANES, "planes_info":PLANES_INFO,
        "servicios_info":SERVICIOS_INFO, "ia_activa":ia_configurada(),
        "pagos_reales":pagos_reales_permitidos(), "identidad_legal_ok":identidad_legal_completa(),
    }

@app.before_request
def csrf():
    if request.endpoint == "stripe_webhook":
        return
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        esperado = session.get("csrf_token")
        recibido = request.form.get("csrf_token")
        if (not isinstance(esperado, str) or not esperado or not recibido
                or not secrets.compare_digest(recibido.encode("utf-8"), esperado.encode("utf-8"))):
            abort(400, "El formulario ha caducado. Recarga la página.")

@app.after_request
def headers(r):
    r.headers.update({"X-Content-Type-Options":"nosniff","X-Frame-Options":"SAMEORIGIN","Referrer-Policy":"strict-origin-when-cross-origin","Content-Security-Policy":"default-src 'self'; style-src 'self'; img-src 'self' data:"}); return r

@app.route("/",methods=["GET","POST"])
def inicio():
    if request.method == "POST":
        if (request.form.get("website") or "").strip():
            abort(400)
        if not permitir_intento("consulta_publica", 5, 3600):
            flash("Has enviado demasiadas consultas. Inténtalo de nuevo más tarde.", "error")
            return redirect(url_for("inicio"))
        empresa = (request.form.get("empresa") or "").strip()
        correo = (request.form.get("correo") or "").strip().lower()
        problema = (request.form.get("problema") or "").strip()

        if not empresa or not correo or not problema:
            flash("Completa empresa, correo y consulta.", "error")
        elif "@" not in correo:
            flash("Introduce un correo electrónico válido.", "error")
        elif len(empresa) > 120 or len(problema) > 3000:
            flash("El texto es demasiado largo.", "error")
        else:
            token = secrets.token_urlsafe(32)

            with conectar() as c:
                c.execute(
                    queries.INICIO_1,
                    (empresa, correo, problema, token, "")
                )

            enviado = email_consulta_recibida(correo, empresa, token)
            if enviado:
                flash("Consulta enviada. Te hemos mandado el enlace privado por correo.", "success")
            else:
                flash("Consulta enviada correctamente. Guarda esta página para consultar la respuesta.", "success")
            return redirect(url_for("consulta_cliente", token=token))

    return render_template("index.html")
@app.route("/consulta/<token>")
def consulta_cliente(token):
    with conectar() as c:
        consulta = c.execute(
            queries.CONSULTA_CLIENTE_1,
            (token,)
        ).fetchone()

    if not consulta:
        abort(404)

    return render_template(
        "consulta_cliente.html",
        consulta=consulta,
        token=token
    )  

@app.route("/consulta/<token>/estado")
def estado_consulta(token):
    """Devuelve la respuesta actual para actualizar la página sin recargarla."""
    with conectar() as c:
        consulta = c.execute(
            queries.ESTADO_CONSULTA_1,
            (token,)
        ).fetchone()

    if not consulta:
        abort(404)

    respuesta = (consulta["respuesta"] or "").strip()
    response = jsonify({
        "respondida": bool(respuesta),
        "respuesta": respuesta
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response
@app.route("/acceso",methods=["GET","POST"])
def acceso():
    if request.method=="POST":
        if not permitir_intento("admin_login", 8, 900):
            flash("Demasiados intentos. Espera 15 minutos.", "error")
            return redirect(url_for("acceso"))
        if check_password_hash(ADMIN_HASH,request.form.get("contrasena","")): session.clear(); session["administrador"]=True; return redirect(url_for("panel_admin"))
        flash("La contraseña no es correcta.","error")
    return render_template("acceso.html")

@app.route("/equipo", methods=["GET", "POST"])
def acceso_equipo():
    if session.get("administrador"):
        return redirect(url_for("panel_admin"))
    return acceso()
@app.route("/cliente/registro", methods=["GET", "POST"])
def cliente_registro():

    if request.method == "POST":

        if (request.form.get("website") or "").strip():
            abort(400)
        if not permitir_intento("registro", 4, 3600):
            flash("Demasiados intentos de registro. Inténtalo de nuevo dentro de una hora.", "error")
            return redirect(url_for("cliente_registro"))

        nombre = (request.form.get("nombre") or "").strip()
        correo = (request.form.get("correo") or "").strip().lower()
        contrasena = request.form.get("contrasena", "")
        repetida = request.form.get("repetida", "")
        plan_key = (request.form.get("plan") or "crecimiento").strip()
        acepta_legal = request.form.get("acepta_legal") == "si"

        if not nombre:
            flash("Introduce el nombre de tu empresa.", "error")

        elif "@" not in correo:
            flash("Introduce un correo electrónico válido.", "error")

        elif len(contrasena) < 8:
            flash("La contraseña necesita al menos 8 caracteres.", "error")

        elif contrasena != repetida:
            flash("Las contraseñas no coinciden.", "error")

        elif plan_key not in PLANES_INFO:
            flash("Selecciona un plan válido.", "error")

        elif not acepta_legal:
            flash("Debes aceptar la política de privacidad y las condiciones.", "error")

        else:

            try:

                with conectar() as c:

                    c.execute(
                        queries.CLIENTE_REGISTRO_1,
                        (
                            nombre[:120],
                            correo,
                            generate_password_hash(
                                contrasena,
                                method="pbkdf2:sha256"
                            ),
                            nombre_plan(plan_key)
                        )
                    )

                    ahora = datetime.now(timezone.utc)
                    c.execute(
                        queries.CLIENTE_REGISTRO_2,
                        (plan_key, "verificacion_pendiente", 0, ahora.isoformat(), "", ahora.isoformat(), correo),
                    )

                    cliente_id = c.execute(
                        queries.CLIENTE_REGISTRO_3,
                        (correo,)
                    ).fetchone()["id"]
                    enroll_if_enabled(c, cliente_id)

                session.clear()
                token = crear_token_verificacion(cliente_id)
                enviado = email_verificar_cuenta(correo, nombre[:120], token)
                notificar_equipo(
                    "Nueva empresa registrada | Inahistudio",
                    f"Se ha registrado {nombre[:120]} con el plan {PLANES_INFO[plan_key]['nombre']}. Estado: correo pendiente de verificación.",
                )
                if enviado:
                    flash("Cuenta creada. Revisa tu correo y pulsa el enlace de verificación para activarla.", "success")
                else:
                    flash("Cuenta creada, pero no pudimos enviar el correo. Inicia sesión para solicitar otro enlace.", "error")
                return redirect(url_for("cliente_acceso"))

            except sqlite3.IntegrityError:

                flash(
                    "Ya existe una cuenta con ese correo electrónico.",
                    "error"
                )

    plan_elegido = request.args.get("plan", "crecimiento")
    if plan_elegido not in PLANES_INFO:
        plan_elegido = "crecimiento"
    return render_template(
        "cliente_registro.html",
        plan_elegido=plan_elegido,
        stripe_configurado=stripe_configurado(plan_elegido),
        stripe_modo_prueba=stripe_es_modo_prueba(),
    )

@app.route("/cliente/verificar-email/<token>")
def verificar_email(token):
    ahora = datetime.now(timezone.utc)
    with conectar() as c:
        verificacion = c.execute(
            queries.VERIFICAR_EMAIL_4, (token,)
        ).fetchone()
        if not verificacion or verificacion["usado"] or datetime.fromisoformat(verificacion["expira"]) < ahora:
            flash("El enlace de verificación no es válido o ha caducado.", "error")
            return redirect(url_for("cliente_acceso"))
        cliente_id = verificacion["cliente_id"]
        plan_key = verificacion["plan_key"] if verificacion["plan_key"] in PLANES_INFO else "crecimiento"
        stripe_disponible = stripe_configurado(plan_key)
        c.execute(queries.VERIFICAR_EMAIL_1, (token,))
        if stripe_disponible:
            c.execute(
                queries.VERIFICAR_EMAIL_2,
                (cliente_id,),
            )
            plaza_prueba = False
        else:
            trial_end = (ahora + timedelta(days=TRIAL_DAYS)).date().isoformat()
            asignada = c.execute(
                queries.VERIFICAR_EMAIL_3,
                (trial_end, cliente_id, TRIAL_MAX_COMPANIES),
            )
            plaza_prueba = asignada.rowcount == 1
            if not plaza_prueba:
                c.execute(
                    queries.VERIFICAR_EMAIL_5,
                    (cliente_id,),
                )
    session.clear()
    session["cliente_id"] = cliente_id
    with closing(conectar()) as c:
        if saas_enabled(c):
            identity = c.execute(queries.VERIFICAR_EMAIL_6, (cliente_id,)).fetchone()
            if identity:
                session.update(user_id=identity["id"], organization_id=identity["organization_id"],
                               credential_version=identity["credential_version"])
    if stripe_disponible:
        flash("Correo verificado. Continúa con el checkout seguro de Stripe.", "success")
        return redirect(url_for("crear_checkout", plan_key=plan_key))
    if not plaza_prueba:
        session.clear()
        flash("Las 5 plazas gratuitas ya están ocupadas. Hemos guardado tu cuenta en la lista de espera.", "error")
        return redirect(url_for("cliente_acceso"))
    flash(f"Correo verificado. Tu demostración de {TRIAL_DAYS} días incluye {TRIAL_QUERY_LIMIT} consultas y no habrá ningún cobro.", "success")
    return redirect(url_for("diagnostico"))

@app.route("/cliente/recuperar-contrasena", methods=["GET", "POST"])
def recuperar_contrasena():

    if request.method == "POST":

        if not permitir_intento("recuperar", 4, 3600):
            flash("Demasiadas solicitudes. Inténtalo de nuevo dentro de una hora.", "error")
            return redirect(url_for("cliente_acceso"))

        correo = (request.form.get("correo") or "").strip().lower()

        with conectar() as c:
            cliente = c.execute(
                queries.RECUPERAR_CONTRASENA_3,
                (correo,)
            ).fetchone()

        if cliente:
            token = secrets.token_urlsafe(32)
            expira = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            with conectar() as c:
                c.execute(queries.RECUPERAR_CONTRASENA_1, (cliente["id"], datetime.now(timezone.utc).isoformat()))
                c.execute(queries.RECUPERAR_CONTRASENA_2, (token, cliente["id"], expira))
            enlace = enlace_publico("nueva_contrasena", token=token)
            enviar_email(correo, "Recupera tu contraseña | Inahistudio", f"Usa este enlace durante los próximos 30 minutos:\n\n{enlace}")
        flash("Si existe una cuenta con ese correo, recibirás un enlace válido durante 30 minutos.", "success")
        return redirect(url_for("cliente_acceso"))

    return render_template("recuperar_contrasena.html")


@app.route("/cliente/nueva-contrasena/<token>", methods=["GET", "POST"])
def nueva_contrasena(token):
    with conectar() as c:
        reset = c.execute(queries.NUEVA_CONTRASENA_1, (token,)).fetchone()
    if not reset or datetime.fromisoformat(reset["expira"]) < datetime.now(timezone.utc):
        flash("El enlace ha caducado. Solicita uno nuevo.", "error")
        return redirect(url_for("recuperar_contrasena"))
    cliente_id = reset["cliente_id"]

    if request.method == "POST":

        contrasena = request.form.get("contrasena", "")
        repetida = request.form.get("repetida", "")

        if len(contrasena) < 8:
            flash(
                "La contraseña necesita al menos 8 caracteres.",
                "error"
            )

        elif contrasena != repetida:
            flash(
                "Las contraseñas no coinciden.",
                "error"
            )

        else:

            with conectar() as c:
                c.execute(
                    queries.NUEVA_CONTRASENA_2,
                    (
                        generate_password_hash(
                            contrasena,
                            method="pbkdf2:sha256"
                        ),
                        cliente_id
                    )
                )

            with conectar() as c:
                c.execute(queries.NUEVA_CONTRASENA_3, (token,))

            flash(
                "Contraseña actualizada. Ya puedes iniciar sesión.",
                "success"
            )

            return redirect(url_for("cliente_acceso"))

    return render_template("nueva_contrasena.html")

@app.route("/pago/<plan_key>")
def crear_checkout(plan_key):
    cliente_id = session.get("cliente_id")
    if not cliente_id or plan_key not in PLANES_INFO:
        return redirect(url_for("cliente_registro", plan=plan_key))
    stripe = stripe_cliente()
    precio_id = os.environ.get(PLANES_INFO[plan_key]["price_env"], "").strip()
    if not stripe or not precio_id:
        return render_template("pago_pendiente.html", plan=PLANES_INFO[plan_key])
    with conectar() as c:
        cliente = c.execute(queries.CREAR_CHECKOUT_1, (cliente_id,)).fetchone()
    if not cliente or not cliente["email_verificado"]:
        session.clear()
        flash("Verifica primero tu correo electrónico.", "error")
        return redirect(url_for("cliente_acceso"))
    datos_checkout = dict(
        mode="subscription",
        line_items=[{"price": precio_id, "quantity": 1}],
        client_reference_id=str(cliente_id),
        metadata={"cliente_id": str(cliente_id), "plan_key": plan_key},
        success_url=enlace_publico("pago_correcto") + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=enlace_publico("precios") + "?cancelado=1",
        allow_promotion_codes=True,
    )
    if cliente["stripe_customer_id"]:
        datos_checkout["customer"] = cliente["stripe_customer_id"]
    else:
        datos_checkout["customer_email"] = cliente["correo"]
    try:
        checkout = stripe.checkout.Session.create(**datos_checkout)
    except stripe.error.StripeError:
        logger.exception("Stripe no pudo crear Checkout para el plan %s", plan_key)
        flash("No hemos podido abrir el pago de Stripe. Revisa la configuración de prueba.", "error")
        return redirect(url_for("precios"))
    return redirect(checkout.url, code=303)

@app.route("/pago/correcto")
def pago_correcto():
    cliente_id = session.get("cliente_id")
    session_id = (request.args.get("session_id") or "").strip()
    stripe = stripe_cliente()
    if not cliente_id or not session_id or not stripe:
        return render_template("pago_correcto.html", verificado=False)
    try:
        checkout = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError:
        logger.exception("No se pudo verificar la sesión de Checkout")
        return render_template("pago_correcto.html", verificado=False)
    referencia = str(checkout.get("client_reference_id") or "")
    metadata = checkout.get("metadata") or {}
    plan_key = metadata.get("plan_key", "")
    completado = checkout.get("status") == "complete" and checkout.get("subscription")
    if referencia != str(cliente_id) or plan_key not in PLANES_INFO or not completado:
        return render_template("pago_correcto.html", verificado=False)
    with conectar() as c:
        c.execute(
            queries.PAGO_CORRECTO_1,
            (plan_key, nombre_plan(plan_key), checkout.get("customer", ""), checkout.get("subscription", ""), cliente_id),
        )
    return render_template("pago_correcto.html", verificado=True)

@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    stripe = stripe_cliente()
    secreto = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not stripe or not secreto:
        abort(503)
    try:
        evento = stripe.Webhook.construct_event(request.data, request.headers.get("Stripe-Signature", ""), secreto)
    except (ValueError, stripe.error.SignatureVerificationError):
        abort(400)
    try:
        procesar_evento_stripe(evento, conectar, PLANES_INFO, nombre_plan, plan_por_precio)
    except ValueError:
        abort(400)
    except sqlite3.Error:
        logger.exception("No se pudo confirmar el webhook; Stripe debe reintentarlo. Comprueba init-db.")
        abort(503)
    return {"recibido": True}

@app.route("/cliente/facturacion", methods=["POST"])
@client_required
def facturacion():
    stripe = stripe_cliente()
    with conectar() as c:
        cliente = c.execute(queries.FACTURACION_1, (session["cliente_id"],)).fetchone()
    if not stripe or not cliente["stripe_customer_id"]:
        flash("La gestión de facturación todavía no está configurada.", "error")
        return redirect(url_for("portal"))
    portal = stripe.billing_portal.Session.create(customer=cliente["stripe_customer_id"], return_url=enlace_publico("portal"))
    return redirect(portal.url, code=303)

@app.route("/precios")
def precios():
    return render_template(
        "precios.html",
        stripe_disponible=any(stripe_configurado(key) for key in PLANES_INFO),
        stripe_modo_prueba=stripe_es_modo_prueba(),
    )

@app.route("/servicios", methods=["GET", "POST"])
def servicios():
    seleccionado = (request.values.get("servicio") or "").strip()
    if seleccionado not in SERVICIOS_INFO:
        seleccionado = ""

    if request.method == "POST":
        if (request.form.get("website") or "").strip():
            abort(400)
        if not permitir_intento("servicios", 5, 3600):
            flash("Has enviado demasiadas solicitudes. Inténtalo de nuevo más tarde.", "error")
            return redirect(url_for("servicios"))
        nombre = (request.form.get("nombre") or "").strip()
        empresa = (request.form.get("empresa") or "").strip()
        correo = (request.form.get("correo") or "").strip().lower()
        telefono = (request.form.get("telefono") or "").strip()
        mensaje = (request.form.get("mensaje") or "").strip()
        servicio = SERVICIOS_INFO.get(seleccionado)

        if not servicio or not nombre or not empresa or "@" not in correo:
            flash("Elige un servicio y completa nombre, empresa y correo.", "error")
        else:
            with conectar() as c:
                c.execute(
                    queries.SERVICIOS_1,
                    (seleccionado, servicio["nombre"], servicio["precio"], nombre[:120], empresa[:120], correo[:254], telefono[:40], mensaje[:2000], datetime.now(timezone.utc).isoformat())
                )
            enviar_email(
                correo,
                "Hemos recibido tu solicitud | Inahistudio",
                f"Hola, {nombre}.\n\nHemos recibido tu solicitud de {servicio['nombre']} ({servicio['precio']}). Nos pondremos en contacto contigo para confirmar el alcance y el presupuesto antes de empezar."
            )
            notificar_equipo(
                f"Nueva solicitud: {servicio['nombre']}",
                f"Empresa: {empresa}\nContacto: {nombre}\nCorreo: {correo}\nTeléfono: {telefono or 'No indicado'}\nServicio: {servicio['nombre']} ({servicio['precio']})\nMensaje: {mensaje or 'Sin mensaje'}",
            )
            flash("Solicitud enviada. Contactaremos contigo para confirmar el trabajo y el presupuesto.", "success")
            return redirect(url_for("servicios"))

    return render_template("servicios.html", seleccionado=seleccionado)

@app.route("/legal/<pagina>")
def legal(pagina):
    if pagina not in ("privacidad", "condiciones"):
        abort(404)
    return render_template(
        "legal.html", pagina=pagina,
        legal_business_name=os.environ.get("LEGAL_BUSINESS_NAME", "").strip(),
        legal_tax_id=os.environ.get("LEGAL_TAX_ID", "").strip(),
        legal_address=os.environ.get("LEGAL_ADDRESS", "").strip(),
    )

@app.route("/cliente/acceso",methods=["GET","POST"])
def cliente_acceso():
    if request.method=="POST":
        if not permitir_intento("cliente_login", 10, 900):
            flash("Demasiados intentos. Espera 15 minutos.", "error")
            return redirect(url_for("cliente_acceso"))
        email=(request.form.get("correo") or "").strip().lower()
        identity = None
        with conectar() as c:
            if saas_enabled(c):
                identity = saas_authenticate(c, email, request.form.get("contrasena", ""))
                cl = c.execute(queries.CLIENTE_ACCESO_2, (identity["cliente_id"],)).fetchone() if identity else None
                password_ok = bool(identity)
            else:
                cl = c.execute(queries.CLIENTE_ACCESO_1, (email,)).fetchone()
                password_ok = bool(cl and check_password_hash(cl["contrasena"], request.form.get("contrasena", "")))
        if cl and password_ok:
            if not cl["email_verificado"]:
                token = crear_token_verificacion(cl["id"])
                email_verificar_cuenta(cl["correo"], cl["nombre"], token)
                flash("Debes verificar tu correo. Te acabamos de enviar un enlace nuevo.", "success")
                return redirect(url_for("cliente_acceso"))
            session.clear()
            session["cliente_id"] = cl["id"]
            if identity:
                session.update(identity)
            if cl["activo"]:
                return redirect(url_for("portal"))
            if cl["subscription_status"] == "pendiente" and cl["plan_key"] in PLANES_INFO:
                flash("Completa el pago de prueba para activar tu cuenta.", "success")
                return redirect(url_for("crear_checkout", plan_key=cl["plan_key"]))
            session.clear()
        flash("El correo o la contraseña no son correctos.","error")
    return render_template("cliente_acceso.html")

@app.route("/salir")
def salir(): session.clear(); return redirect(url_for("acceso"))
@app.route("/salir-cliente")
def salir_cliente(): session.clear(); return redirect(url_for("cliente_acceso"))

@app.route("/portal")
@client_required
def portal():
    cid=session["cliente_id"]
    with conectar() as c:
        cl=c.execute(queries.PORTAL_1,(cid,)).fetchone()
        ss=c.execute(queries.PORTAL_2,(cid,)).fetchall()
        citas=c.execute(queries.PORTAL_3,(cid,)).fetchall()
        diagnostico=c.execute(queries.PORTAL_4,(cid,)).fetchone()
        estrategia=c.execute(queries.PORTAL_5,(cid,)).fetchone()
        periodo_actual=date.today().strftime("%Y-%m")
        calendario=c.execute(queries.PORTAL_6,(cid,periodo_actual)).fetchone()
        if cl["subscription_status"] == "prueba":
            usadas=cl["trial_queries_used"]
        else:
            inicio_mes=date.today().replace(day=1).isoformat()
            usadas=c.execute(queries.PORTAL_7,(cid,inicio_mes)).fetchone()[0]
    plan_info=PLANES_INFO.get(cl["plan_key"],PLANES_INFO["esencial"])
    limite=TRIAL_QUERY_LIMIT if cl["subscription_status"] == "prueba" else plan_info["consultas"]
    restantes=None if limite >= 999 else max(limite-usadas,0)
    pasos=[bool(diagnostico), bool(estrategia), bool(calendario), bool(ss)]
    progreso=round(sum(pasos)/len(pasos)*100)
    dias_prueba=None
    if cl["subscription_status"] == "prueba" and cl["trial_end"]:
        dias_prueba=max((date.fromisoformat(cl["trial_end"])-date.today()).days,0)
    return render_template("portal.html",cliente=cl,solicitudes=ss,citas=citas,diagnostico=diagnostico,estrategia=estrategia,
                           calendario=calendario,plan_info=plan_info,usadas=usadas,restantes=restantes,
                           progreso=progreso,dias_prueba=dias_prueba)

@app.route("/cliente/diagnostico", methods=["GET", "POST"])
@client_required
def diagnostico():
    cid = session["cliente_id"]
    if request.method == "POST":
        valores = [1 if request.form.get(campo) == "si" else 0 for campo in ("web", "google", "redes", "resenas")]
        objetivos = (request.form.get("objetivos") or "").strip()[:1500]
        puntuacion = sum(valores) * 25
        with conectar() as c:
            c.execute(queries.DIAGNOSTICO_1,
                      (cid, *valores, objetivos, puntuacion))
        flash("Diagnóstico actualizado. Ya tienes un plan de acción personalizado.", "success")
        return redirect(url_for("portal"))
    with conectar() as c:
        item = c.execute(queries.DIAGNOSTICO_2, (cid,)).fetchone()
    return render_template("diagnostico.html", diagnostico=item)

@app.route("/cliente/estrategia", methods=["GET", "POST"])
@client_required
def estrategia_comercial():
    cid = session["cliente_id"]
    sectores = {
        "peluqueria_estetica", "comercio", "hosteleria",
        "salud_bienestar", "servicios_profesionales", "otro"
    }
    objetivos = {"captar_clientes", "aumentar_reservas", "aumentar_ventas", "fidelizar", "visibilidad"}
    presupuestos = {"sin_presupuesto", "hasta_100", "100_300", "mas_300"}
    tiempos = {"menos_2", "2_4", "mas_4"}
    conversiones = {"compra", "encargo", "reserva", "cita", "presupuesto", "contacto"}
    canales_validos = {"Google Business", "Instagram", "Facebook", "TikTok", "WhatsApp", "LinkedIn", "Correo electrónico", "Página web"}

    with conectar() as c:
        cliente = c.execute(queries.ESTRATEGIA_COMERCIAL_2, (cid,)).fetchone()
        guardada = c.execute(queries.ESTRATEGIA_COMERCIAL_3, (cid,)).fetchone()

    if request.method == "POST":
        datos = {
            "nombre_negocio": cliente["nombre"],
            "sector": (request.form.get("sector") or "").strip(),
            "actividad": (request.form.get("actividad") or "").strip()[:120],
            "conversion": (request.form.get("conversion") or "").strip(),
            "ubicacion": (request.form.get("ubicacion") or "").strip()[:120],
            "oferta": (request.form.get("oferta") or "").strip()[:300],
            "cliente_ideal": (request.form.get("cliente_ideal") or "").strip()[:300],
            "objetivo": (request.form.get("objetivo") or "").strip(),
            "meta": (request.form.get("meta") or "").strip()[:300],
            "canales": [canal for canal in request.form.getlist("canales") if canal in canales_validos],
            "presupuesto": (request.form.get("presupuesto") or "").strip(),
            "tiempo": (request.form.get("tiempo") or "").strip(),
            "fortaleza": (request.form.get("fortaleza") or "").strip()[:500],
            "problema": (request.form.get("problema") or "").strip()[:500],
        }
        completos = all(datos[campo] for campo in ("actividad", "ubicacion", "oferta", "cliente_ideal", "meta", "fortaleza", "problema"))
        validos = datos["sector"] in sectores and datos["conversion"] in conversiones and datos["objetivo"] in objetivos and datos["presupuesto"] in presupuestos and datos["tiempo"] in tiempos
        if not completos or not validos:
            flash("Completa todos los campos para generar una estrategia útil.", "error")
            return render_template("estrategia.html", datos=datos, estrategia=None, plan_key=cliente["plan_key"])

        estrategia = generar_estrategia_comercial(datos)
        ahora = datetime.now(timezone.utc).isoformat()
        with conectar() as c:
            c.execute(
                queries.ESTRATEGIA_COMERCIAL_1,
                (cid, json.dumps(datos, ensure_ascii=False), json.dumps(estrategia, ensure_ascii=False), ahora),
            )
        flash("Tu estrategia comercial de 90 días está preparada.", "success")
        return redirect(url_for("estrategia_comercial"))

    datos, estrategia = {}, None
    if guardada:
        try:
            datos = json.loads(guardada["respuestas"])
            estrategia = json.loads(guardada["estrategia"])
        except (TypeError, json.JSONDecodeError):
            logger.exception("No se pudo leer la estrategia del cliente %s", cid)
    return render_template("estrategia.html", datos=datos, estrategia=estrategia, plan_key=cliente["plan_key"], actualizado=guardada["actualizado"] if guardada else None)

@app.route("/cliente/contenidos")
@client_required
def calendario_contenidos():
    cid = session["cliente_id"]
    periodo = date.today().strftime("%Y-%m")
    with conectar() as c:
        cliente = c.execute(queries.CALENDARIO_CONTENIDOS_3, (cid,)).fetchone()
        estrategia = c.execute(queries.CALENDARIO_CONTENIDOS_4, (cid,)).fetchone()
        guardado = c.execute(queries.CALENDARIO_CONTENIDOS_5, (cid, periodo)).fetchone()
    if not estrategia:
        flash("Crea primero tu estrategia comercial para generar contenidos adaptados.", "error")
        return redirect(url_for("estrategia_comercial"))
    plan_info = PLANES_INFO.get(cliente["plan_key"], PLANES_INFO["esencial"])
    datos = json.loads(estrategia["respuestas"])
    conversion_por_sector = {
        "peluqueria_estetica": "cita", "comercio": "compra", "hosteleria": "reserva",
        "salud_bienestar": "cita", "servicios_profesionales": "presupuesto", "otro": "contacto",
    }
    actividad_por_sector = {
        "peluqueria_estetica": "peluquería o centro de estética", "comercio": "comercio local",
        "hosteleria": "negocio de hostelería", "salud_bienestar": "negocio de salud o bienestar",
        "servicios_profesionales": "empresa de servicios profesionales", "otro": "negocio local",
    }
    datos.setdefault("conversion", conversion_por_sector.get(datos.get("sector"), "contacto"))
    datos.setdefault("actividad", actividad_por_sector.get(datos.get("sector"), "negocio local"))
    if guardado:
        calendario = json.loads(guardado["contenido"])
    else:
        calendario = generar_calendario_contenidos(datos, plan_info["contenidos"], periodo)
        with conectar() as c:
            c.execute(
                queries.CALENDARIO_CONTENIDOS_1,
                (cid, periodo, json.dumps(calendario, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
            )
    if calendario.get("version", 1) < 2:
        calendario = generar_calendario_contenidos(datos, plan_info["contenidos"], periodo)
        with conectar() as c:
            c.execute(
                queries.CALENDARIO_CONTENIDOS_2,
                (json.dumps(calendario, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), cid, periodo),
            )
    return render_template("contenidos.html", calendario=calendario, plan=plan_info)

@app.route("/cliente/resultados", methods=["GET", "POST"])
@client_required
def resultados_mensuales():
    cid = session["cliente_id"]
    periodo = date.today().strftime("%Y-%m")
    with conectar() as c:
        actual = c.execute(queries.RESULTADOS_MENSUALES_2, (cid, periodo)).fetchone()
        anterior = c.execute(queries.RESULTADOS_MENSUALES_3, (cid, periodo)).fetchone()
    if request.method == "POST":
        try:
            datos = {
                "contactos": max(int(request.form.get("contactos", "0")), 0),
                "ventas": max(int(request.form.get("ventas", "0")), 0),
                "ingresos": max(float((request.form.get("ingresos") or "0").replace(",", ".")), 0),
                "resenas": max(int(request.form.get("resenas", "0")), 0),
            }
        except ValueError:
            flash("Introduce números válidos en los resultados.", "error")
            return redirect(url_for("resultados_mensuales"))
        notas = (request.form.get("notas") or "").strip()[:1000]
        anterior_datos = dict(anterior) if anterior else None
        informe = generar_informe_mensual(datos, anterior_datos)
        with conectar() as c:
            c.execute(
                queries.RESULTADOS_MENSUALES_1,
                (cid, periodo, datos["contactos"], datos["ventas"], datos["ingresos"], datos["resenas"], notas, json.dumps(informe, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
            )
        flash("Tu informe mensual automático está actualizado.", "success")
        return redirect(url_for("resultados_mensuales"))
    informe = json.loads(actual["informe"]) if actual else None
    return render_template("resultados.html", actual=actual, informe=informe, periodo=periodo)

@app.route("/cliente/solicitud",methods=["GET","POST"])
@client_required
def solicitud_cliente():
    if request.method=="POST":
        a=(request.form.get("asunto") or "").strip(); d=(request.form.get("descripcion") or "").strip()
        if a and d:
            cid = session["cliente_id"]
            with conectar() as c:
                cliente=c.execute(queries.SOLICITUD_CLIENTE_3,(cid,)).fetchone()
                if cliente["subscription_status"] == "prueba":
                    reservada = c.execute(
                        queries.SOLICITUD_CLIENTE_2,
                        (cid, TRIAL_QUERY_LIMIT),
                    )
                    if reservada.rowcount != 1:
                        flash(f"Has utilizado las {TRIAL_QUERY_LIMIT} consultas incluidas en tu prueba gratuita.","error")
                        return redirect(url_for("portal"))
                else:
                    limite=PLANES_INFO.get(cliente["plan_key"], PLANES_INFO["esencial"])["consultas"]
                    inicio_mes=date.today().replace(day=1).isoformat()
                    usadas=c.execute(queries.SOLICITUD_CLIENTE_5,(cid,inicio_mes)).fetchone()[0]
                    if usadas >= limite:
                        flash("Has utilizado las consultas incluidas este mes. Puedes cambiar de plan desde Facturación.","error")
                        return redirect(url_for("portal"))
                estrategia = c.execute(queries.SOLICITUD_CLIENTE_4, (session["cliente_id"],)).fetchone()
                contexto = None
                if estrategia:
                    contexto = {"datos": json.loads(estrategia["respuestas"]), "plan": json.loads(estrategia["estrategia"])}
                respuesta_ia = asesor_comercial_ia(a, d, contexto)
                if respuesta_ia:
                    respuesta, estado, origen = respuesta_ia, "Respondida con IA", "ia"
                else:
                    automatica = generar_respuesta_automatica(a, d, contexto)
                    respuesta = f"{automatica['titulo']}\n\n{automatica['respuesta']}\n\nQué medir: {automatica['metrica']}\n\n{automatica['aviso']}"
                    estado, origen = "Respondida automáticamente", "automatizacion"
            with conectar() as c:
                c.execute(queries.SOLICITUD_CLIENTE_1,(cid,a[:150],d[:4000],respuesta[:4000],estado,datetime.now(timezone.utc).isoformat(),origen))
            flash("El asistente ha preparado una respuesta personalizada.","success"); return redirect(url_for("portal"))
        flash("Completa los dos campos.","error")
    asunto_inicial = (request.args.get("asunto") or "").strip()[:150]
    return render_template("solicitud_cliente.html", asunto_inicial=asunto_inicial)

@app.route("/cliente/informes")
@client_required
def informes_cliente():
    with conectar() as c: items=c.execute(queries.INFORMES_CLIENTE_1,(session["cliente_id"],)).fetchall()
    return render_template("informes_cliente.html",informes=items)

@app.route("/cliente/cambiar-contrasena",methods=["GET","POST"])
@client_required
def cambiar_contrasena():
    with closing(conectar()) as c, c:
        if saas_enabled(c):
            context = resolve_context(c)
            if request.method == "POST":
                if request.form.get("nueva", "") != request.form.get("repetida", ""):
                    flash("Las contraseñas no coinciden.", "error")
                else:
                    try:
                        change_password(c, context, request.form.get("actual", ""), request.form.get("nueva", ""))
                    except ValueError:
                        flash("Revisa la contraseña actual y la nueva contraseña (8–256 caracteres).", "error")
                    else:
                        flash("Contraseña actualizada.", "success")
                        return redirect(url_for("portal"))
            return render_template("cambiar_contrasena.html")
    if request.method=="POST":
        actual=request.form.get("actual",""); nueva=request.form.get("nueva",""); rep=request.form.get("repetida","")
        with conectar() as c:
            cl=c.execute(queries.CAMBIAR_CONTRASENA_1,(session["cliente_id"],)).fetchone()
            if not check_password_hash(cl[0],actual): flash("La contraseña actual no es correcta.","error")
            elif len(nueva)<8: flash("La nueva contraseña necesita 8 caracteres.","error")
            elif nueva!=rep: flash("Las contraseñas no coinciden.","error")
            else: c.execute(queries.CAMBIAR_CONTRASENA_2,(generate_password_hash(nueva,method="pbkdf2:sha256"),session["cliente_id"])); flash("Contraseña actualizada.","success"); return redirect(url_for("portal"))
    return render_template("cambiar_contrasena.html")

@app.route("/cliente/solicitar-cita",methods=["GET","POST"])
@client_required
def solicitar_cita():
    cid = session["cliente_id"]
    inicio_mes = date.today().replace(day=1).isoformat()
    with conectar() as c:
        cliente = c.execute(queries.SOLICITAR_CITA_1, (cid,)).fetchone()
        usadas = c.execute(queries.SOLICITAR_CITA_2, (cid, inicio_mes)).fetchone()[0]
    plan_info = PLANES_INFO.get(cliente["plan_key"], PLANES_INFO["esencial"])
    if plan_info["reuniones"] == 0:
        flash("El plan Esencial funciona de forma totalmente automática y no incluye reuniones. Puedes cambiar a Crecimiento o Pro.", "error")
        return redirect(url_for("portal"))
    if request.method=="POST":
        f=request.form.get("fecha",""); h=request.form.get("hora",""); m=request.form.get("modalidad",""); motivo=(request.form.get("motivo") or "").strip()
        if not f or not h or m not in ("Online","Presencial","Teléfono") or not motivo: flash("Completa correctamente los campos.","error")
        elif f<date.today().isoformat(): flash("Elige una fecha futura.","error")
        elif usadas >= plan_info["reuniones"]: flash("Ya has utilizado las reuniones incluidas este mes.","error")
        else:
            with conectar() as c:
                c.execute(queries.SOLICITAR_CITA_3,(cid,f,h,m,motivo[:1000]))
                empresa = c.execute(queries.SOLICITAR_CITA_4, (cid,)).fetchone()
            notificar_equipo(
                "Nueva reunión solicitada | Inahistudio",
                f"Empresa: {empresa['nombre']}\nCorreo: {empresa['correo']}\nFecha: {f}\nHora: {h}\nModalidad: {m}\nMotivo: {motivo[:1000]}",
            )
            flash("Reunión solicitada.","success"); return redirect(url_for("portal"))
    return render_template("solicitar_cita.html",hoy=date.today().isoformat(),plan=plan_info,restantes=max(plan_info["reuniones"]-usadas,0))

@app.route("/admin")
@admin_required
def panel_admin():
    with conectar() as c:
        resumen = {
            "clientes": c.execute(queries.PANEL_ADMIN_4).fetchone()[0],
            "activos": c.execute(queries.PANEL_ADMIN_5).fetchone()[0],
            "pruebas": c.execute(queries.PANEL_ADMIN_6).fetchone()[0],
            "consultas": c.execute(queries.PANEL_ADMIN_7).fetchone()[0],
            "solicitudes": c.execute(queries.PANEL_ADMIN_8).fetchone()[0],
            "servicios": c.execute(queries.PANEL_ADMIN_9).fetchone()[0],
            "citas": c.execute(queries.PANEL_ADMIN_10).fetchone()[0],
        }
        servicios_recientes = c.execute(queries.PANEL_ADMIN_1).fetchall()
        clientes_recientes = c.execute(queries.PANEL_ADMIN_2).fetchall()
        citas_proximas = c.execute(
            queries.PANEL_ADMIN_3
        ).fetchall()
    return render_template("panel_admin.html", resumen=resumen, servicios_recientes=servicios_recientes, clientes_recientes=clientes_recientes, citas_proximas=citas_proximas)

@app.route("/admin/sistema")
@admin_required
def estado_sistema():
    ruta_db = os.path.abspath(DB)
    smtp_ok = all(os.environ.get(k, "").strip() for k in ("SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"))
    avisos_ok = bool(os.environ.get("TEAM_NOTIFICATION_EMAIL", "").strip() or os.environ.get("SMTP_FROM", "").strip())
    persistencia_ok = bool(os.environ.get("DATABASE_PATH", "").strip()) and ruta_db.startswith("/data/")
    return render_template("estado_sistema.html", smtp_ok=smtp_ok, avisos_ok=avisos_ok, persistencia_ok=persistencia_ok, database_path=ruta_db)

@app.route("/admin/servicios", methods=["GET", "POST"])
@admin_required
def servicios_admin():
    if request.method == "POST":
        solicitud_id = request.form.get("solicitud_id")
        estado = request.form.get("estado")
        if estado in ("Nueva", "Contactada", "Aceptada", "Finalizada", "Descartada"):
            with conectar() as c:
                c.execute(queries.SERVICIOS_ADMIN_1, (estado, solicitud_id))
            flash("Estado del servicio actualizado.", "success")
        return redirect(url_for("servicios_admin"))
    estado_filtro = (request.args.get("estado") or "").strip()
    busqueda = (request.args.get("q") or "").strip()
    with conectar() as c:
        items = repositories.search_services(c, estado_filtro, busqueda)
    return render_template("servicios_admin.html", servicios=items, estado_filtro=estado_filtro, busqueda=busqueda)

@app.route("/consultas", methods=["GET", "POST"])
@admin_required
def ver_consultas():

    if request.method == "POST":
        consulta_id = request.form.get("consulta_id")
        respuesta = (request.form.get("respuesta") or "").strip()

        if consulta_id and respuesta:
            with conectar() as c:
                consulta = c.execute(
                    queries.VER_CONSULTAS_3,
                    (consulta_id,)
                ).fetchone()

                if not consulta:
                    abort(404)

                primera_respuesta = not (consulta["respuesta"] or "").strip()
                c.execute(
                    queries.VER_CONSULTAS_1,
                    (respuesta, consulta_id)
                )

            aviso_enviado = True
            if primera_respuesta and consulta["correo"]:
                aviso_enviado = email_respuesta_disponible(
                    consulta["correo"], consulta["empresa"], consulta["token"]
                )

            if primera_respuesta and not aviso_enviado:
                flash("Respuesta guardada, pero el aviso por correo no pudo enviarse.", "error")
            else:
                flash("Respuesta guardada correctamente.", "success")

        return redirect(url_for("ver_consultas"))

    with conectar() as c:
        consultas = c.execute(
            queries.VER_CONSULTAS_2
        ).fetchall()

    return render_template(
        "consultas.html",
        consultas=consultas
    )
@app.route("/crear-cliente", methods=["GET", "POST"])
@admin_required
def crear_cliente():
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        correo = (request.form.get("correo") or "").strip().lower()
        contrasena = request.form.get("contrasena", "")
        plan = (request.form.get("plan") or "").strip()

        if not nombre or not correo or not contrasena or not plan:
            flash("Completa todos los campos.", "error")
            return render_template("crear_cliente.html")

        if "@" not in correo:
            flash("Introduce un correo electrónico válido.", "error")
            return render_template("crear_cliente.html")

        if len(contrasena) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "error")
            return render_template("crear_cliente.html")

        try:
            with conectar() as c:
                c.execute(
                    queries.CREAR_CLIENTE_1,
                    (
                        nombre,
                        correo,
                        generate_password_hash(contrasena),
                        plan
                    )
                )
                cliente_id = c.execute(queries.CREAR_CLIENTE_2, (correo,)).fetchone()["id"]
                enroll_if_enabled(c, cliente_id)

            flash("Cliente creado correctamente.", "success")
            return redirect(url_for("clientes_admin"))

        except sqlite3.IntegrityError:
            flash("Ya existe un cliente con ese correo.", "error")

    return render_template("crear_cliente.html")
@app.route("/admin/clientes")
@admin_required
def clientes_admin():
    busqueda = (request.args.get("q") or "").strip()
    estado = (request.args.get("estado") or "").strip()
    with conectar() as c:
        items = repositories.search_accounts(c, estado, busqueda)
    return render_template("clientes_admin.html", clientes=items, busqueda=busqueda, estado_filtro=estado)

@app.route("/admin/clientes/<int:cid>/estado",methods=["POST"])
@admin_required
def cambiar_estado_cliente(cid):
    with conectar() as c:c.execute(queries.CAMBIAR_ESTADO_CLIENTE_1,(cid,))
    flash("Estado actualizado.","success"); return redirect(url_for("clientes_admin"))

@app.route("/admin/clientes/<int:cid>/eliminar", methods=["POST"])
@admin_required
def eliminar_cliente(cid):
    confirmacion = (request.form.get("confirmacion") or "").strip()
    if confirmacion != "ELIMINAR":
        flash("No se eliminó el cliente: faltó la confirmación.", "error")
        return redirect(url_for("clientes_admin"))

    with conectar() as c:
        cliente = c.execute(
            queries.ELIMINAR_CLIENTE_11,
            (cid,)
        ).fetchone()
        if not cliente:
            abort(404)

        if saas_enabled(c):
            organization = c.execute(queries.ELIMINAR_CLIENTE_12, (cid,)).fetchone()
            if not organization:
                abort(409)
            c.execute(queries.ELIMINAR_CLIENTE_10, (saas_now(), organization[0]))
            saas_audit(c, "organization_archived", organization[0])
            flash("Organización archivada de forma reversible. Sus datos y su suscripción se conservan; no se ha cancelado Stripe.", "success")
            return redirect(url_for("clientes_admin"))

        estados_con_cobro = {"active", "trialing", "past_due", "unpaid"}
        if cliente["stripe_subscription_id"] and cliente["subscription_status"] in estados_con_cobro:
            flash("Cancela primero la suscripción en Stripe para evitar que el cliente siga recibiendo cobros.", "error")
            return redirect(url_for("clientes_admin"))

        c.execute(queries.ELIMINAR_CLIENTE_1, (cid,))
        c.execute(queries.ELIMINAR_CLIENTE_2, (cid,))
        c.execute(queries.ELIMINAR_CLIENTE_3, (cid,))
        c.execute(queries.ELIMINAR_CLIENTE_4, (cid,))
        c.execute(queries.ELIMINAR_CLIENTE_5, (cid,))
        c.execute(queries.ELIMINAR_CLIENTE_6, (cid,))
        c.execute(queries.ELIMINAR_CLIENTE_7, (cid,))
        c.execute(queries.ELIMINAR_CLIENTE_8, (cid,))
        c.execute(queries.ELIMINAR_CLIENTE_9, (cid,))

    flash(f"Cliente {cliente['nombre']} eliminado definitivamente.", "success")
    return redirect(url_for("clientes_admin"))

@app.route("/admin/clientes/<int:cid>/editar",methods=["GET","POST"])
@admin_required
def editar_cliente(cid):
    with conectar() as c:
        cl=c.execute(queries.EDITAR_CLIENTE_1,(cid,)).fetchone()
        if not cl: abort(404)
        if request.method=="POST":
            n=(request.form.get("nombre") or "").strip(); e=(request.form.get("correo") or "").strip().lower(); p=request.form.get("plan",""); pw=request.form.get("nueva_contrasena","")
            if not n or "@" not in e or p not in PLANES or (pw and len(pw)<8): flash("Revisa los datos.","error")
            else:
                try:
                    c.execute(queries.EDITAR_CLIENTE_2,(n[:120],e,p,cid))
                    if pw:c.execute(queries.EDITAR_CLIENTE_3,(generate_password_hash(pw,method="pbkdf2:sha256"),cid))
                    flash("Cliente actualizado.","success"); return redirect(url_for("clientes_admin"))
                except sqlite3.IntegrityError:flash("Ese correo ya existe.","error")
    return render_template("editar_cliente.html",cliente=cl)

@app.route("/admin/solicitudes",methods=["GET","POST"])
@admin_required
def solicitudes_admin():
    if request.method=="POST":
        resp=(request.form.get("respuesta") or "").strip()
        if resp:
            with conectar() as c:c.execute(queries.SOLICITUDES_ADMIN_1,(resp[:4000],request.form.get("solicitud_id")))
            flash("Respuesta guardada.","success"); return redirect(url_for("solicitudes_admin"))
    with conectar() as c:items=c.execute(queries.SOLICITUDES_ADMIN_2).fetchall()
    return render_template("solicitudes_admin.html",solicitudes=items)

@app.route("/admin/informes/crear", methods=["GET", "POST"])
@admin_required
def crear_informe():
    if request.method == "POST":
        cliente_id = request.form.get("cliente_id")
        titulo = (request.form.get("titulo") or "").strip()
        contenido = (request.form.get("contenido") or "").strip()

        if cliente_id and titulo and contenido:
            with conectar() as c:
                c.execute(
                    queries.CREAR_INFORME_1,
                    (cliente_id, titulo[:150], contenido[:10000])
                )

            flash("Informe guardado.", "success")
            return redirect(url_for("informes_admin"))

        flash("Completa cliente, título y contenido.", "error")

    with conectar() as c:
        clientes = c.execute(
            queries.CREAR_INFORME_2
        ).fetchall()

    return render_template(
        "crear_informe.html",
        clientes=clientes
    )
@app.route("/admin/informes")
@admin_required
def informes_admin():
    with conectar() as c:items=c.execute(queries.INFORMES_ADMIN_1).fetchall()
    return render_template("informes_admin.html",informes=items)

@app.route("/admin/citas")
@admin_required
def citas_admin():
    with conectar() as c:items=c.execute(queries.CITAS_ADMIN_1).fetchall()
    return render_template("citas_admin.html",citas=items)

@app.route("/admin/citas/<int:cid>/estado",methods=["POST"])
@admin_required
def cambiar_estado_cita(cid):
    e=request.form.get("estado")
    if e in ("Confirmada","Cancelada","Pendiente"):
        with conectar() as c:c.execute(queries.CAMBIAR_ESTADO_CITA_1,(e,cid))
    flash("Reunión actualizada.","success"); return redirect(url_for("citas_admin"))

@app.route("/salud")
def salud():return {"estado":"ok"}
@app.errorhandler(400)
@app.errorhandler(404)
def error(e):return render_template("error.html",codigo=e.code,mensaje=e.description),e.code

install_saas(app, lambda: conectar(), PLANES_INFO)
from persistence.migrations import install_cli as install_database_cli
install_database_cli(app, lambda: DB)

if __name__=="__main__":app.run(debug=os.environ.get("FLASK_DEBUG")=="1")
