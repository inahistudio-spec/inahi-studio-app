"""Explicit environment boundaries. Never print credentials or infer a staging target."""
import os
import re
from flask import has_app_context, current_app


def mode():
    value = os.environ.get('APP_ENV', os.environ.get('FLASK_ENV', 'development')).strip().lower()
    if value not in ('development', 'test', 'staging', 'production'):
        raise ValueError('APP_ENV no válido')
    return value


def validate():
    environment = mode()
    if environment == 'staging':
        # These ambient credentials are intentionally not reused by staging adapters.
        forbidden = ('OPENAI_API_KEY','COPILOT_API_KEY','STRIPE_SECRET_KEY','STRIPE_WEBHOOK_SECRET','SMTP_PASSWORD')
        if any(os.environ.get(key, '').strip() for key in forbidden):
            raise ValueError('Staging requiere un entorno limpio y credenciales dedicadas')
        if os.environ.get('ALLOW_LIVE_PAYMENTS') == 'true' or os.environ.get('STRIPE_MODE', 'test') != 'test':
            raise ValueError('Pagos externos deshabilitados en staging')
        if os.environ.get('FLASK_ENV') == 'production':
            raise ValueError('Configuración de entorno contradictoria')
    return environment


def database_guard(url):
    if validate() != 'staging':
        return
    expected = (os.environ.get('STAGING_DB_HOST'), os.environ.get('STAGING_DB_NAME'), os.environ.get('STAGING_DB_USER'))
    if not all(expected) or (url.host, url.database, url.username) != expected:
        raise ValueError('La conexión no corresponde al destino staging declarado')
    if url.get_backend_name() != 'postgresql' or not re.fullmatch(r'inahi_staging_[a-z0-9_]+', url.database or ''):
        raise ValueError('Staging requiere una base PostgreSQL exclusiva inahi_staging_*')
    if not re.fullmatch(r'inahi_staging_[a-z0-9_]+', url.username or '') or not url.password:
        raise ValueError('Staging requiere un usuario exclusivo con contraseña')
    if set(url.query) - {'sslmode', 'connect_timeout'}:
        raise ValueError('Opciones de conexión staging no permitidas')
    if url.host not in ('127.0.0.1','localhost','::1') and url.query.get('sslmode') != 'verify-full':
        raise ValueError('Staging remoto requiere sslmode=verify-full')


def external_enabled():
    environment = validate()
    if environment in ('test','production') or (has_app_context() and current_app.testing):
        return False
    return os.environ.get('COPILOT_ALLOW_EXTERNAL') == 'true' and os.environ.get('COPILOT_EXTERNAL_ENABLED') == 'true'


def provider_key():
    return os.environ.get('STAGING_COPILOT_API_KEY' if mode() == 'staging' else 'COPILOT_API_KEY', '').strip()


def configure_app(app):
    environment=validate()
    app.config['ENVIRONMENT']=environment
    if environment=='production':
        app.config['SESSION_COOKIE_SECURE']=True
    elif environment=='staging':
        from urllib.parse import urlsplit
        if len(os.environ.get('SECRET_KEY',''))<32:
            raise ValueError('Staging requiere un secreto de sesión independiente de al menos 32 caracteres')
        local_http=os.environ.get('STAGING_LOCAL_HTTP')=='true'
        if local_http:
            target=urlsplit(os.environ.get('PUBLIC_BASE_URL',''))
            if target.scheme!='http' or target.hostname not in ('127.0.0.1','localhost','::1'):
                raise ValueError('HTTP de staging solo permitido en loopback explícito')
        app.config.update(SESSION_COOKIE_NAME='inahi_staging',SESSION_COOKIE_SECURE=not local_http)
