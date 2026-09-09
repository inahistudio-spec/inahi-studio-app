"""Feature registry; analysis only, never autonomous actions."""
FEATURES = {
    "business_overview": ("Prioridades de la semana", "¿Qué debería hacer esta semana para captar más clientes?"),
    "client_analysis": ("Análisis de clientes", "¿Qué clientes necesitan seguimiento y qué datos nos faltan?"),
    "sales_strategy": ("Estrategia comercial", "Propón una estrategia comercial basada en los datos disponibles."),
    "content": ("Contenido de 7 días", "Prepara propuestas de contenido para los próximos 7 días."),
    "reports": ("Resumen para dirección", "Resume los resultados del mes y señala los datos pendientes."),
    "pending_actions": ("Acciones pendientes", "¿Qué acciones tenemos pendientes?"),
    "opportunities": ("Oportunidades", "Detecta oportunidades comerciales y explica en qué te basas."),
}
ALL_ROLES = frozenset(("owner", "admin", "manager", "member"))
MANAGEMENT = frozenset(("owner", "admin", "manager"))
ROLES = {name: MANAGEMENT if name in ("client_analysis", "sales_strategy", "reports") else ALL_ROLES for name in FEATURES}
SOURCES = {
    "business_overview": ("diagnosticos", "estrategias_comerciales", "resultados_mensuales", "solicitudes"),
    "client_analysis": ("estrategias_comerciales",),
    "sales_strategy": ("diagnosticos", "estrategias_comerciales"),
    "content": ("estrategias_comerciales", "calendarios_contenido"),
    "reports": ("resultados_mensuales", "informes"),
    "pending_actions": ("solicitudes", "citas"),
    "opportunities": ("diagnosticos", "estrategias_comerciales", "resultados_mensuales"),
}
