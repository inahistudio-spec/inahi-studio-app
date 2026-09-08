"""Motores deterministas de automatización comercial de Inahi Studio.

No utiliza servicios externos ni envía datos del cliente fuera de la aplicación.
"""

from datetime import date


def contexto_conversion(datos):
    modos = {
        "compra": {"verbo": "comprar", "accion": "Compra", "resultado": "ventas", "disponibilidad": "unidades disponibles", "codigo": "QUIERO COMPRAR"},
        "encargo": {"verbo": "hacer tu encargo", "accion": "Haz tu encargo", "resultado": "pedidos", "disponibilidad": "fechas de entrega disponibles", "codigo": "QUIERO ENCARGAR"},
        "reserva": {"verbo": "reservar", "accion": "Reserva", "resultado": "reservas", "disponibilidad": "disponibilidad", "codigo": "QUIERO RESERVAR"},
        "cita": {"verbo": "pedir cita", "accion": "Pide tu cita", "resultado": "citas", "disponibilidad": "horarios disponibles", "codigo": "QUIERO MI CITA"},
        "presupuesto": {"verbo": "solicitar presupuesto", "accion": "Solicita presupuesto", "resultado": "presupuestos", "disponibilidad": "plazos disponibles", "codigo": "QUIERO PRESUPUESTO"},
        "contacto": {"verbo": "pedir información", "accion": "Pide información", "resultado": "contactos", "disponibilidad": "condiciones y disponibilidad", "codigo": "QUIERO INFORMACIÓN"},
    }
    return modos.get(datos.get("conversion"), modos["contacto"])


def hashtags_para(datos):
    actividad = "".join(c if c.isalnum() else " " for c in datos.get("actividad", "negocio local")).title().replace(" ", "")
    ubicacion = "".join(c if c.isalnum() else " " for c in datos.get("ubicacion", "tu zona")).title().replace(" ", "")
    return f"#{actividad or 'NegocioLocal'} #{ubicacion or 'ComercioLocal'} #CompraLocal #PequeñoNegocio #InahiStudio"


def generar_respuesta_automatica(asunto, descripcion, estrategia=None):
    texto = f"{asunto} {descripcion}".lower()
    datos = (estrategia or {}).get("datos", {})
    plan = (estrategia or {}).get("plan", {})
    oferta = datos.get("oferta", "tu producto o servicio principal")
    cliente = datos.get("cliente_ideal", "tu cliente ideal")
    ubicacion = datos.get("ubicacion", "tu zona")
    actividad = datos.get("actividad", "negocio local")
    conversion = contexto_conversion(datos)
    respuesta_detallada = None

    if any(p in texto for p in ("instagram", "redes", "publicar", "contenido", "reel")):
        titulo = "Plan inmediato para redes sociales"
        acciones = [
            f"Publica una prueba real de {oferta} y explica el resultado conseguido.",
            f"Responde una duda frecuente de {cliente} en un vídeo o carrusel sencillo.",
            f"Incluye siempre una llamada concreta: {conversion['accion']} por WhatsApp o visita el negocio.",
            "Repite durante cuatro semanas el formato que genere más conversaciones, no el que tenga más likes.",
        ]
        metrica = "Mide mensajes, clics, reservas y ventas procedentes de cada publicación."
    elif any(p in texto for p in ("google", "mapas", "reseña", "reseñas", "ficha")):
        titulo = "Plan inmediato para Google Business"
        acciones = [
            f"Comprueba que categoría, horario, teléfono, ubicación en {ubicacion} y enlace de contacto sean correctos.",
            f"Añade {oferta} como servicio o producto con una descripción clara y precio orientativo cuando sea posible.",
            "Sube fotografías reales y recientes del negocio, del equipo y del resultado del servicio.",
            "Pide reseñas de forma constante y responde todas mencionando el servicio realizado.",
        ]
        metrica = "Mide llamadas, solicitudes de ruta, clics y nuevas reseñas desde Google."
    elif any(p in texto for p in ("precio", "oferta", "promoción", "promocion", "descuento", "vender")):
        titulo = "Promoción comercial lista para utilizar"
        acciones = [
            f"Describe {oferta} mediante el problema que resuelve para {cliente}.",
            "Indica qué incluye, cuánto tarda, precio o rango y qué debe hacer el cliente para comprar.",
            "Crea una oferta de entrada con alcance cerrado sin rebajar permanentemente el servicio principal.",
            f"Añade una razón real para actuar ahora: fecha límite o {conversion['disponibilidad']}.",
        ]
        respuesta_detallada = (
            f"NOMBRE DE LA PROMOCIÓN\nSemana especial de {oferta}\n\n"
            f"TEXTO PARA INSTAGRAM\n¿Te gustaría disfrutar de {oferta} con una propuesta pensada para {cliente}? "
            f"Durante esta semana tenemos {conversion['disponibilidad']} en {ubicacion}. Escríbenos por WhatsApp y te contamos precio y condiciones.\n\n"
            f"TEXTO PARA WHATSAPP\nHola, esta semana hemos preparado una promoción especial de {oferta}. "
            f"La disponibilidad es limitada. Si te interesa, responde a este mensaje y te enviamos {conversion['disponibilidad']}, precio y condiciones.\n\n"
            f"DURACIÓN RECOMENDADA\n7 días o hasta agotar {conversion['disponibilidad']}.\n\n"
            f"CONDICIONES\nDefine por escrito qué incluye, precio final, {conversion['disponibilidad']}, fecha límite y si puede combinarse con otras ofertas. "
            "No utilices urgencia falsa ni mantengas el descuento de forma permanente.\n\n"
            f"LLAMADA A LA ACCIÓN\n{conversion['accion']} por WhatsApp indicando «{conversion['codigo']}» y te confirmamos los siguientes pasos."
        )
        metrica = "Mide cuántas personas preguntan y qué porcentaje termina comprando."
    elif any(p in texto for p in ("cliente", "clientes", "reserva", "reservas", "captar", "ventas")):
        titulo = "Plan para captar y convertir clientes"
        acciones = [
            f"Concentra el mensaje en {cliente} y en una sola oferta: {oferta}.",
            "Elige un canal principal de captación y un canal de seguimiento; evita intentar hacerlo todo a la vez.",
            "Responde cada contacto con una pregunta de necesidad y una propuesta de siguiente paso.",
            "Haz seguimiento a las 24–48 horas cuando una persona muestre interés y no cierre.",
        ]
        metrica = "Registra contactos, propuestas, reservas o ventas y porcentaje de conversión."
    elif any(p in texto for p in ("web", "página", "pagina", "seo")):
        titulo = "Plan inmediato para la página web"
        acciones = [
            f"Haz visible en la primera pantalla qué ofrece el negocio en {ubicacion} y para quién.",
            f"Crea una sección específica para {oferta}, con beneficios, proceso, precio orientativo y preguntas frecuentes.",
            "Coloca un botón de contacto o reserva en las zonas principales y comprueba el funcionamiento en móvil.",
            "Añade pruebas de confianza: casos, reseñas, fotografías reales y datos de contacto completos.",
        ]
        metrica = "Mide visitas, clics en contacto, formularios y reservas procedentes de la web."
    else:
        titulo = "Siguiente acción comercial recomendada"
        prioridades = plan.get("prioridades", [])
        acciones = prioridades[:4] or [
            f"Define una oferta clara de {oferta} para {cliente}.",
            "Elige una acción de captación y otra de seguimiento para esta semana.",
            "Incluye una llamada a la acción en todos tus canales.",
            "Registra el resultado y mejora lo que no esté convirtiendo.",
        ]
        metrica = "Mide contactos, ventas o reservas y repite solo las acciones que funcionen."

    return {
        "titulo": titulo,
        "respuesta": respuesta_detallada or "\n".join(f"{indice}. {accion}" for indice, accion in enumerate(acciones, 1)),
        "metrica": metrica,
        "aviso": "Esta orientación es automática y utiliza la información guardada en tu estrategia comercial.",
    }


def generar_calendario_contenidos(datos, cantidad, periodo=None):
    sector = datos.get("sector", "otro")
    oferta = datos.get("oferta", "tu servicio principal")
    cliente = datos.get("cliente_ideal", "tu cliente ideal")
    cliente_frase = cliente[:1].lower() + cliente[1:] if cliente else "tu cliente ideal"
    ubicacion = datos.get("ubicacion", "tu zona")
    fortaleza = datos.get("fortaleza", "la atención personalizada")
    actividad = datos.get("actividad", "negocio local")
    conversion = contexto_conversion(datos)
    periodo = periodo or date.today().strftime("%Y-%m")

    sectoriales = {
        "peluqueria_estetica": [
            ("Resultado real", f"Antes y después de {oferta}, explicando el proceso y para quién es adecuado."),
            ("Consejo profesional", "Tres cuidados sencillos para mantener el resultado durante más tiempo."),
            ("Confianza", "Presentación del equipo y de la forma de trabajar durante una cita."),
            ("Reserva", "Disponibilidad de la semana con llamada directa a reservar."),
        ],
        "comercio": [
            ("Producto destacado", f"Muestra un producto relacionado con {oferta}, su precio y cómo comprarlo."),
            ("Uso real", "Tres maneras de utilizar o combinar un producto de la tienda."),
            ("Novedad", "Nueva llegada, reposición o selección de temporada."),
            ("Confianza", "Recomendación personal del equipo para una necesidad concreta."),
        ],
        "hosteleria": [
            ("Producto", f"Plato o experiencia destacada vinculada a {oferta}."),
            ("Proceso", "Cómo se prepara un producto y qué lo hace especial."),
            ("Ambiente", "Una situación real del local que ayude a imaginar la visita."),
            ("Reserva", "Propuesta para una fecha u horario concreto con enlace de reserva."),
        ],
        "salud_bienestar": [
            ("Educación", f"Duda frecuente sobre {oferta} explicada sin promesas exageradas."),
            ("Proceso", "Qué puede esperar una persona en la primera visita."),
            ("Prevención", "Consejo práctico y seguro relacionado con el servicio."),
            ("Confianza", "Experiencia, método de trabajo y límites profesionales del servicio."),
        ],
        "servicios_profesionales": [
            ("Problema", f"Señal que indica que una empresa puede necesitar {oferta}."),
            ("Proceso", "Explicación breve de cómo se desarrolla el servicio paso a paso."),
            ("Caso", "Situación de cliente, solución aplicada y aprendizaje sin revelar datos privados."),
            ("Objeción", "Respuesta clara a una duda habitual sobre precio, plazo o resultado."),
        ],
        "otro": [
            ("Oferta", f"Explica qué incluye {oferta} y qué problema resuelve."),
            ("Consejo", f"Consejo útil para {cliente} relacionado con la actividad."),
            ("Prueba", "Caso, resultado, reseña o demostración real del trabajo."),
            ("Acción", "Invitación clara a contactar, reservar o comprar."),
        ],
    }
    base = sectoriales.get(sector, sectoriales["otro"])
    complementos = [
        ("Pregunta frecuente", f"Responde una duda frecuente de {cliente_frase} antes de comprar."),
        ("Diferenciación", f"Explica cómo {fortaleza} mejora la experiencia del cliente."),
        ("Local", f"Contenido relacionado con {ubicacion} y la utilidad del negocio para la zona."),
        ("Reseña", "Convierte una reseña real en una publicación y agradece la confianza."),
        ("Error habitual", f"Explica un error habitual entre {cliente_frase} y cómo evitarlo."),
        ("Comparación", "Explica dos opciones y cuándo conviene elegir cada una."),
        ("Detrás de cámaras", "Muestra una parte real del proceso de trabajo y explica por qué es importante."),
        ("Mito o realidad", f"Aclara una creencia equivocada relacionada con {oferta}."),
        ("Paso a paso", f"Resume en tres pasos cómo una persona puede {conversion['verbo']} {oferta}."),
        ("Disponibilidad", f"Publica {conversion['disponibilidad']} con una llamada directa: {conversion['accion']}."),
        ("Encuesta", f"Pregunta a la audiencia qué necesita mejorar en relación con {oferta}."),
        ("Temporada", f"Relaciona {oferta} con una necesidad concreta del momento o de la temporada."),
    ]
    banco = base + complementos
    llamadas = ["Escríbenos para más información.", f"{conversion['accion']} por WhatsApp.", f"Consulta {conversion['disponibilidad']}.", "Guarda esta publicación.", "Compártelo con alguien a quien le sirva."]
    calendario = []
    for indice in range(cantidad):
        tipo, idea = banco[indice % len(banco)]
        semana = indice // 4 + 1
        cta = llamadas[indice % len(llamadas)]
        titulo = f"{tipo}: {oferta}"
        texto_instagram = (
            f"{idea}\n\nEn {actividad} trabajamos para ayudar a {cliente} en {ubicacion}. "
            f"Nuestro punto fuerte es {fortaleza}.\n\n{cta}\n\n{hashtags_para(datos)}"
        )
        texto_facebook = f"{idea}\n\nSi estás en {ubicacion} y buscas {oferta}, podemos ayudarte. {cta}"
        texto_whatsapp = f"Hola. Esta semana queremos enseñarte {oferta}. {idea} {cta}"
        calendario.append({
            "numero": indice + 1,
            "semana": semana,
            "tipo": tipo,
            "idea": idea,
            "objetivo": "Confianza" if tipo in ("Confianza", "Reseña", "Caso") else "Captación",
            "cta": cta,
            "titulo": titulo,
            "texto_instagram": texto_instagram,
            "texto_facebook": texto_facebook,
            "texto_whatsapp": texto_whatsapp,
            "hashtags": hashtags_para(datos),
            "visual": f"Fotografía o vídeo vertical real de {oferta}; evita imágenes de banco y muestra el producto, proceso o resultado.",
        })
    return {"version": 2, "periodo": periodo, "cantidad": cantidad, "contenidos": calendario}


def generar_informe_mensual(actual, anterior=None):
    contactos = max(int(actual.get("contactos", 0)), 0)
    ventas = max(int(actual.get("ventas", 0)), 0)
    ingresos = max(float(actual.get("ingresos", 0)), 0)
    resenas = max(int(actual.get("resenas", 0)), 0)
    conversion = round((ventas / contactos * 100), 1) if contactos else 0
    ticket = round((ingresos / ventas), 2) if ventas else 0

    alertas, logros, acciones = [], [], []
    if contactos == 0:
        alertas.append("No se registraron nuevos contactos; aumenta la visibilidad y revisa la llamada a la acción.")
        acciones.append("Publica una oferta clara y activa un canal local de captación durante dos semanas.")
    elif conversion < 20:
        alertas.append("La conversión de contactos a clientes es inferior al 20 %.")
        acciones.append("Mejora el seguimiento y responde con una propuesta concreta de siguiente paso.")
    else:
        logros.append(f"La conversión ha alcanzado el {conversion} %.")
        acciones.append("Mantén el proceso de respuesta y busca aumentar el número de contactos cualificados.")
    if resenas < 4:
        acciones.append("Solicita al menos una reseña nueva por semana durante el próximo mes.")
    else:
        logros.append(f"Se consiguieron {resenas} reseñas nuevas.")
    if ingresos and ticket:
        logros.append(f"El importe medio por venta o reserva fue de {ticket:.2f} €.")

    comparacion = None
    if anterior:
        contactos_anteriores = max(int(anterior.get("contactos", 0)), 0)
        ventas_anteriores = max(int(anterior.get("ventas", 0)), 0)
        comparacion = {
            "contactos": contactos - contactos_anteriores,
            "ventas": ventas - ventas_anteriores,
            "mensaje": "Mejora respecto al mes anterior." if ventas > ventas_anteriores else "Revisa las acciones que no generaron ventas y concentra el esfuerzo en las que sí funcionaron.",
        }
    return {
        "metricas": {"contactos": contactos, "ventas": ventas, "ingresos": ingresos, "resenas": resenas, "conversion": conversion, "ticket": ticket},
        "logros": logros or ["Ya dispones de una base de datos mensual para tomar mejores decisiones."],
        "alertas": alertas,
        "acciones": acciones[:4],
        "comparacion": comparacion,
    }
