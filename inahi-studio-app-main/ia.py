"""Capa de IA de InahiStudio con salida segura y respaldo determinista."""

import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def ia_configurada():
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def _extraer_texto(respuesta):
    if respuesta.get("output_text"):
        return respuesta["output_text"].strip()
    textos = []
    for item in respuesta.get("output", []):
        for contenido in item.get("content", []):
            if contenido.get("type") in ("output_text", "text") and contenido.get("text"):
                textos.append(contenido["text"])
    return "\n".join(textos).strip()


def generar_con_ia(instrucciones, entrada, max_output_tokens=1200):
    """Llama a Responses API. Devuelve texto o None para activar el respaldo local."""
    clave = os.environ.get("OPENAI_API_KEY", "").strip()
    if not clave:
        return None
    modelo = os.environ.get("OPENAI_MODEL", "gpt-5-mini").strip()
    cuerpo = {
        "model": modelo,
        "instructions": instrucciones,
        "input": entrada,
        "max_output_tokens": max_output_tokens,
    }
    peticion = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(cuerpo, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {clave}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "InahiStudio/1.0 (+https://app.inahistudio.com)",
        },
        method="POST",
    )
    try:
        with urlopen(peticion, timeout=35) as respuesta:
            return _extraer_texto(json.loads(respuesta.read().decode("utf-8"))) or None
    except HTTPError as error:
        detalle = error.read().decode("utf-8", errors="replace")[:1000]
        logger.error("La IA rechazó la solicitud (HTTP %s): %s", error.code, detalle)
    except (URLError, OSError, ValueError, json.JSONDecodeError):
        logger.exception("No se pudo generar la respuesta con IA")
    return None


def asesor_comercial_ia(asunto, descripcion, contexto):
    datos = (contexto or {}).get("datos", {})
    negocio = json.dumps(datos, ensure_ascii=False, indent=2)
    instrucciones = """Eres el asesor comercial de InahiStudio para pequeños negocios españoles.
Da una respuesta práctica, específica y honesta en español. No inventes datos, resultados ni urgencia.
Incluye: diagnóstico breve, 4 acciones numeradas, un texto listo para usar, una métrica y el siguiente paso.
Evita explicaciones genéricas y no prometas resultados garantizados. Máximo 650 palabras."""
    entrada = f"DATOS DEL NEGOCIO:\n{negocio}\n\nCONSULTA:\nAsunto: {asunto}\nDetalle: {descripcion}"
    return generar_con_ia(instrucciones, entrada, 1100)
