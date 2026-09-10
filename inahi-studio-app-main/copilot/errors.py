class CopilotError(Exception):
    status = 400
    code = "invalid_request"
    message = "Revisa la pregunta y la función seleccionada."

class Unavailable(CopilotError):
    status = 503
    code = "unavailable"
    message = "Copilot no está disponible. Consulta con el administrador."

class QuotaExceeded(CopilotError):
    status = 429
    code = "quota"
    message = "Has alcanzado un límite de uso. Revisa la cuota o inténtalo más tarde."

class Duplicate(CopilotError):
    status = 409
    code = "duplicate"
    message = "Esta solicitud ya se ha registrado. No se ha vuelto a llamar al proveedor."

class ProviderError(CopilotError):
    status = 502
    code = "provider_error"
    message = "El proveedor no pudo completar la respuesta. Puedes iniciar otra solicitud."

class InvalidOutput(CopilotError):
    status = 502
    code = "invalid_output"
    message = "La respuesta no superó la validación de seguridad."

class ProviderTimeout(ProviderError):
    code = 'provider_timeout'
    message = 'El proveedor ha tardado demasiado. No se reintentó automáticamente.'

class ProviderRateLimit(ProviderError):
    code = 'provider_rate_limit'
    message = 'El proveedor está limitando las consultas. No se reintentó automáticamente.'

class ProviderDown(ProviderError):
    code = 'provider_unavailable'
    message = 'El proveedor no está disponible. No se reintentó automáticamente.'
