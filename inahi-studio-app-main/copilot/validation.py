"""Output is plain text and allowlisted references, never executable markup/actions."""
import re
from copilot.errors import InvalidOutput
from copilot.sanitization import text


def validate(output, sources):
    if not isinstance(output, dict) or set(output) != {"answer", "recommendations", "limitations", "sources"}:
        raise InvalidOutput()
    if not isinstance(output["answer"], str) or not 1 <= len(output["answer"].strip()) <= 5000:
        raise InvalidOutput()
    for key, maximum in (("recommendations", 7), ("limitations", 5), ("sources", 35)):
        if not isinstance(output[key], list) or len(output[key]) > maximum or any(not isinstance(item, str) or len(item) > 1200 for item in output[key]):
            raise InvalidOutput()
    if any(item not in sources for item in output["sources"]):
        raise InvalidOutput()
    for value in [output["answer"], *output["recommendations"], *output["limitations"]]:
        if re.search(r"<[^>]+>|```|javascript:|data:text/html", value, re.I) or text(value, 5000) != value.strip():
            raise InvalidOutput()
    return {**output, "sources": list(dict.fromkeys(output["sources"]))}
