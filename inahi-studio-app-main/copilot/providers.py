"""Provider boundary: local rules and a stateless OpenAI adapter, no tools or history."""
from dataclasses import dataclass
import json
import os
import re
from typing import Protocol
from urllib.request import Request, build_opener, HTTPRedirectHandler
from flask import current_app, has_app_context
from copilot.errors import Unavailable, ProviderError
from copilot.prompts import OUTPUT_SCHEMA


@dataclass(frozen=True)
class Completion:
    output: dict
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class Provider(Protocol):
    name: str
    model: str
    def generate(self, system: str, payload: str) -> Completion: ...


class LocalProvider:
    """Useful deterministic recommendations, explicitly not a remote model."""
    name = "local"
    model = "rules-v1"

    def generate(self, system, payload):
        value = json.loads(payload)
        context = value["untrusted_organization_data"]
        if context['clients'].get('commercial_request'):
            from crm.copilot import local_answer
            return Completion(local_answer(context))
        refs = [item["source"] for rows in context["records"].values() for item in rows]
        actions = {
            "Prioridades de la semana": ["Define un objetivo semanal medible de captación.", "Revisa el canal con menor puntuación del diagnóstico.", "Prepara una propuesta y mide contactos y ventas al final de la semana."],
            "Análisis de clientes": ["Registra contactos, fecha de última interacción y siguiente paso en un CRM.", "Prioriza después los seguimientos vencidos con datos verificables."],
            "Estrategia comercial": ["Define el segmento y el problema que resuelves.", "Contrasta la propuesta con las respuestas de la estrategia guardada.", "Prueba una oferta con una métrica de conversión antes de ampliarla."],
            "Contenido de 7 días": [f"Día {i}: {idea}." for i, idea in enumerate(("explica un problema frecuente", "comparte un consejo", "muestra tu proceso", "responde una pregunta", "presenta una oferta verificable", "invita a una conversación", "revisa resultados y aprendizajes"), 1)],
            "Resumen para dirección": ["Compara contactos, ventas e ingresos del período disponible.", "Separa resultados observados de objetivos futuros.", "Anota los datos que faltan antes de tomar decisiones."],
            "Acciones pendientes": ["Revisa solicitudes y citas abiertas de la muestra disponible.", "Asigna responsable y fecha a cada siguiente paso sin darlo por ejecutado."],
            "Oportunidades": ["Contrasta debilidades del diagnóstico con objetivos de la estrategia.", "Prueba una mejora pequeña con seguimiento de resultados."],
        }
        return Completion({"answer": f"Propuesta local para {value['task'].lower()}. Se han consultado {len(refs)} registros autorizados; revisa la muestra antes de decidir.",
            "recommendations": actions[value["task"]],
            "limitations": ["Respuesta orientativa de reglas locales, no un análisis generativo.", ("El CRM aporta una muestra limitada de contactos comerciales." if context["clients"].get("available") else "No hay CRM de contactos comerciales para evaluar clientes individuales."), *context["limitations"]][:5],
            "sources": refs})


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ProviderError()


class OpenAIProvider:
    name = "openai"

    def __init__(self, transport=None):
        self.model = os.environ.get("COPILOT_MODEL", "").strip()
        self.key = os.environ.get("COPILOT_API_KEY", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,100}", self.model) or not self.key or os.environ.get("COPILOT_ALLOW_EXTERNAL") != "true":
            raise Unavailable()
        if transport is None and has_app_context() and current_app.testing:
            # Tests must inject a fake transport; ambient credentials cannot send tenant data.
            raise Unavailable()
        self.transport = transport or build_opener(NoRedirect()).open
        self.max_tokens = min(max(int(os.environ.get("COPILOT_MAX_OUTPUT_TOKENS", "1200")), 128), 4000)

    def generate(self, system, payload):
        body = {"model": self.model, "instructions": system,
                "input": [{"role": "user", "content": payload}], "store": False,
                "tools": [], "max_output_tokens": self.max_tokens,
                "text": {"format": {"type": "json_schema", "name": "copilot_answer", "strict": True, "schema": OUTPUT_SCHEMA}}}
        request = Request("https://api.openai.com/v1/responses", data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                          headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}, method="POST")
        try:
            with self.transport(request, timeout=30) as response:
                raw = response.read(262145)
            if len(raw) > 262144:
                raise ProviderError()
            result = json.loads(raw)
            if result.get("status") != "completed":
                raise ProviderError()
            output = []
            for item in result.get("output", []):
                if item.get("type") != "message":
                    continue
                for content in item.get("content", []):
                    if content.get("type") == "refusal":
                        raise ProviderError()
                    if content.get("type") == "output_text":
                        output.append(content.get("text", ""))
            usage = result.get("usage") or {}
            return Completion(json.loads("".join(output)), usage.get("input_tokens"), usage.get("output_tokens"), usage.get("total_tokens"))
        except Exception:
            # Do not log provider bodies, keys, prompts, or raw exception messages.
            raise ProviderError() from None


FACTORIES = {"local": LocalProvider, "openai": OpenAIProvider}


def get_provider():
    name = os.environ.get("COPILOT_PROVIDER", "local").strip().lower()
    if name not in FACTORIES:
        raise Unavailable()
    try:
        return FACTORIES[name]()
    except (ValueError, TypeError):
        raise Unavailable() from None
