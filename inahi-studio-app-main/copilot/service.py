"""Reserve once, call outside the transaction, reauthorize before delivery."""
from contextlib import closing
import hashlib
import hmac
import json
import uuid
import time
import os
from flask import current_app, g, abort
from werkzeug.exceptions import HTTPException
from billing.entitlements import require_paid, LimitExceeded
from copilot import context, prompts, usage, providers, budgets
from copilot.permissions import authorize
from copilot.sanitization import text
from copilot.validation import validate
from copilot.errors import CopilotError, ProviderError, InvalidOutput
from copilot.features import FEATURES


def ask(connect, feature, question, request_key, resource_kind=None, resource_id=None, contact_id=None, crm_task=None):
    if not isinstance(feature, str) or feature not in FEATURES or not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
        raise CopilotError()
    try:
        if str(uuid.UUID(request_key)) != request_key:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise CopilotError() from None
    with closing(connect()) as c, c:
        c.execute("BEGIN IMMEDIATE")
        actor, data, sources = context.build(c, feature, resource_kind, resource_id, contact_id, crm_task)
        provider = providers.for_organization(c, actor)
        system, payload = prompts.build(feature, text(question, 2000), data)
        if len(payload) > 22000:
            raise CopilotError()
        fingerprint = hmac.new(str(current_app.secret_key).encode(), payload.encode(), hashlib.sha256).hexdigest()
        if data['clients'].get('available'):
            from saas_schema import audit
            audit(c, 'crm_copilot_used', actor.organization_id, actor.user_id)
        call_id = usage.reserve(c, actor, feature, provider, request_key, fingerprint, len(sources))
        budgets.reserve(c, actor, call_id, provider, system, payload)
        fallback_allowed = budgets.enabled(c) and os.environ.get("COPILOT_FALLBACK_LOCAL", "true") == "true"
    values = (None, None, None, None)
    failure = None
    status = "succeeded"
    started = time.monotonic()
    delivered, fallback, reason = provider, False, None
    try:
        completion = provider.generate(system, payload)
        values = usage.metrics(completion, provider)
        output = validate(completion.output, sources)
    except InvalidOutput:
        status, failure = "invalid_output", InvalidOutput()
    except ProviderError as error:
        status, failure = "provider_error", error
    except Exception:
        status, failure = "provider_error", ProviderError()
    if failure:
        reason = failure.code
        if fallback_allowed and provider.name != "local":
            delivered = providers.LocalProvider()
            output = validate(delivered.generate(system, payload).output, sources)
            fallback, failure = True, None
    latency = max(0, int((time.monotonic()-started)*1000))
    # Even failed/invalid calls consume their reservation: retrying cannot evade quotas.
    with closing(connect()) as c, c:
        c.execute("BEGIN IMMEDIATE")
        if failure is None:
            try:
                current = authorize(c, feature)
                if current.organization_id != actor.organization_id or current.user_id != actor.user_id:
                    abort(403)
                require_paid(c, actor.organization_id)
                if delivered.name != 'local' and budgets.enabled(c):
                    active_policy = budgets.policy(c,actor.organization_id)
                    if not active_policy or not active_policy['external_enabled']:
                        abort(403)
                if data['clients'].get('available'):
                    from crm.policy import authorize as crm_authorize
                    from crm.service import get_contact
                    crm_authorize(c)
                    if contact_id is not None:
                        get_contact(c, current, contact_id)
            except (HTTPException, CopilotError, LimitExceeded):
                status = "denied_after_call"
        usage.finish(c, actor, call_id, status, values)
        budgets.finish(c, actor, call_id, values, latency, delivered, reason, fallback)
    g.copilot_audited = True
    if status == "denied_after_call":
        abort(403)
    if failure:
        raise failure
    with closing(connect()) as c:
        totals = usage.summary(c, actor)
    return {**output, "delivery": {"provider": delivered.name, "model": delivered.model, "fallback": fallback, "reason": reason}, "request_id": call_id, "next_request_key": str(uuid.uuid4()), "usage": totals}
