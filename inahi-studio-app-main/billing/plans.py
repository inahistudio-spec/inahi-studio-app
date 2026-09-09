"""Internal product catalog. Price identifiers and limit overrides are environment-only."""
import os

PLANS = ("STARTER", "PROFESSIONAL", "BUSINESS", "ENTERPRISE")
METRICS = ("members", "clients", "ai", "automations", "reports")
DEFAULTS = {
    "STARTER": (3, 100, 100, 20, 10),
    "PROFESSIONAL": (10, 1000, 1000, 200, 100),
    "BUSINESS": (50, 10000, 10000, 2000, 1000),
    "ENTERPRISE": (None, None, None, None, None),
}
LEGACY = {"esencial": "STARTER", "crecimiento": "PROFESSIONAL", "pro": "BUSINESS"}
REVERSE = {"STARTER": "esencial", "PROFESSIONAL": "crecimiento", "BUSINESS": "pro", "ENTERPRISE": "pro"}


def catalog(plan):
    if plan not in PLANS:
        raise ValueError("Plan desconocido")
    limits = {}
    for metric, default in zip(METRICS, DEFAULTS[plan]):
        raw = os.environ.get(f"B2B_LIMIT_{plan}_{metric.upper()}")
        value = default if raw is None else (None if raw == "unlimited" else int(raw))
        if value is not None and value < 0:
            raise ValueError("Límite inválido")
        limits[metric] = value
    premium = os.environ.get(f"B2B_PREMIUM_{plan}", "true" if plan != "STARTER" else "false")
    if premium not in ("true", "false"):
        raise ValueError("Configuración premium inválida")
    return {"plan": plan, "limits": limits, "premium": premium == "true"}


def price(plan):
    catalog(plan)
    value = os.environ.get(f"STRIPE_B2B_PRICE_{plan}", "").strip()
    if not value.startswith("price_"):
        raise ValueError("Falta configurar el precio B2B")
    if sum(os.environ.get(f"STRIPE_B2B_PRICE_{p}", "").strip() == value for p in PLANS) != 1:
        raise ValueError("Un precio no puede representar varios planes")
    return value


def plan_for_price(value):
    matches = [p for p in PLANS if os.environ.get(f"STRIPE_B2B_PRICE_{p}", "").strip() == value and value]
    if len(matches) != 1:
        raise ValueError("Precio Stripe B2B sin correspondencia única")
    return matches[0]
