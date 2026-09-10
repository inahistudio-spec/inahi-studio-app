"""Allowlisted data plus bounded, best-effort secret/PII redaction.

This is not a proof against every encoded injection. No tools, arbitrary SQL,
global retrieval, provider history or executable output are available to the model.
"""
import html
import json
import re
import unicodedata
import math

KEYS = re.compile(r"password|passwd|contras|hash|secret|token|api.?key|authorization|cookie|stripe|credential|correo|email|telefono|phone|address|direccion|system|developer|instructions|instrucciones", re.I)
SECRETS = [
    re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:sk|rk|pk)_(?:live_|test_|proj_)?[A-Za-z0-9_-]{5,}\b"),
    re.compile(r"\bwhsec_[A-Za-z0-9_-]+\b"),
    re.compile(r"(?:pbkdf2|scrypt):[^\s\"',}]+", re.I),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9+/=_-]+", re.I),
    re.compile(r"\b(?:password|contrasena|contraseña|secret|token|api[_ -]?key)\s*[:=]\s*[^\s,;}]+", re.I),
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    re.compile(r"https?://[^\s<>\"']+", re.I),
    re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)"),
]
INJECTION = re.compile(r"ignore.{0,50}(?:previous|instructions|system)|ignora.{0,50}(?:instrucciones|reglas)|olvida.{0,40}instrucciones|system\s*prompt|developer\s*message|reveal.{0,40}(?:secret|key)|<\|(?:system|im_start)|exfiltrat", re.I | re.S)


def text(value, limit=1500):
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", html.unescape(value[:12000]))
    value = "".join(ch for ch in value if not unicodedata.category(ch).startswith("C") or ch in "\n\t")
    if INJECTION.search(value):
        return "[Contenido con instrucciones no fiables omitido]"
    value = re.sub(r"<[^>]*>", "", value)
    for pattern in SECRETS:
        value = pattern.sub("[dato omitido]", value)
    return value.strip()[:limit]


def data(value, depth=0):
    if depth > 4:
        return "[contenido limitado]"
    if isinstance(value, dict):
        return {text(str(key), 60): data(item, depth + 1) for key, item in list(value.items())[:25] if not KEYS.search(str(key))}
    if isinstance(value, list):
        return [data(item, depth + 1) for item in value[:12]]
    if isinstance(value, str):
        if value.strip().startswith(("{", "[")) and len(value) <= 12000:
            try:
                return data(json.loads(value), depth + 1)
            except (ValueError, RecursionError):
                pass
        return text(value)
    if type(value) is float and not math.isfinite(value):
        return None
    if value is None or type(value) in (int, float, bool):
        return value
    return text(str(value))
