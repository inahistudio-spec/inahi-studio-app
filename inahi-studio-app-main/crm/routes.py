"""HTML CRM endpoints; every request resolves identity before accessing records."""
from contextlib import closing
import sqlite3
import uuid
from flask import Blueprint, abort, render_template, request, redirect, url_for, session
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from crm import policy, service
from billing.entitlements import LimitExceeded
from saas_schema import audit
from saas_core import resolve_context
from workspace_ui import shell


def listing(c, actor):
    try:
        rows, count, page = service.contacts(c, actor, request.args.to_dict())
    except ValueError:
        abort(400)
    return render_template('crm/list.html', ui=shell(c, actor, 'clientes'), rows=rows,
        count=count, page=page, filters=request.args, members=service.members(c, actor),
        statuses=policy.STATUSES, labels=policy.LABELS, summary=service.overview(c, actor))


def install(app, connect):
    bp = Blueprint('crm', __name__)

    @bp.before_request
    def parameters():
        if request.args or request.is_json or any(len(request.form.getlist(k)) != 1 for k in request.form):
            abort(400)
        if not session.get('user_id'):
            return redirect(url_for('cliente_acceso'))

    def fields(allowed):
        if set(request.form) - {'csrf_token', *allowed}:
            abort(400)
        return request.form

    @bp.errorhandler(ValueError)
    def invalid(_error):
        return render_template('workspace/error.html', code=400), 400

    @bp.errorhandler(LimitExceeded)
    def limited(_error):
        return render_template('workspace/error.html', code=402), 402

    @bp.errorhandler(sqlite3.Error)
    @bp.errorhandler(SQLAlchemyError)
    def unavailable(_error):
        return render_template('workspace/error.html', code=503), 503

    @bp.errorhandler(HTTPException)
    def rejected(error):
        return render_template('workspace/error.html', code=error.code), error.code

    @app.after_request
    def private(response):
        if (request.endpoint or '').startswith('crm.') or request.endpoint == 'workspace.clientes':
            response.headers['Cache-Control'] = 'no-store'
            if response.status_code >= 400:
                try:
                    with closing(connect()) as c, c:
                        if policy.enabled(c):
                            try:
                                actor = resolve_context(c, product=False)
                            except HTTPException:
                                actor = None
                            audit(c, 'crm_access_denied', actor.organization_id if actor else None, actor.user_id if actor else None)
                except (sqlite3.Error, SQLAlchemyError):
                    app.logger.error('CRM audit unavailable')
        return response

    @bp.route('/saas/clientes/nuevo', methods=['GET', 'POST'])
    @bp.route('/saas/clientes/<int:cid>/editar', methods=['GET', 'POST'])
    def edit(cid=None):
        with closing(connect()) as c, c:
            if request.method == 'POST':
                c.execute('BEGIN IMMEDIATE')
                cid = service.save_contact(c, fields(service.CONTACT_FIELDS), cid)
                return redirect(url_for('crm.contact', cid=cid), 303)
            actor = policy.authorize(c, 'edit')
            row = service.get_contact(c, actor, cid) if cid else {}
            return render_template('crm/form.html', ui=shell(c, actor, 'clientes'), row=row,
                kind='contact', members=service.members(c, actor), choices=policy.STATUSES, labels=policy.LABELS)

    @bp.get('/saas/clientes/<int:cid>')
    def contact(cid):
        with closing(connect()) as c:
            actor = policy.authorize(c)
            row, activities, opportunities, flags = service.detail(c, actor, cid)
            return render_template('crm/detail.html', ui=shell(c, actor, 'clientes'), row=row,
                activities=activities, opportunities=opportunities, flags=flags, labels=policy.LABELS,
                can_activity=actor.role in policy.EDIT_ROLES or (actor.role == 'member' and row['owner_user_id'] == actor.user_id), types=policy.ACTIVITY_TYPES)

    @bp.post('/saas/clientes/<int:cid>/eliminar')
    def archive(cid):
        fields(())
        with closing(connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            service.archive_contact(c, cid)
        return redirect(url_for('workspace.clientes'), 303)

    @bp.post('/saas/clientes/<int:cid>/actividad')
    def activity(cid):
        values = fields(('type', 'description', 'occurred_at', 'next_followup_at'))
        with closing(connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            service.activity(c, cid, values)
        return redirect(url_for('crm.contact', cid=cid), 303)

    @bp.route('/saas/clientes/<int:cid>/oportunidades', methods=['GET', 'POST'])
    @bp.route('/saas/oportunidades/<int:oid>/editar', methods=['GET', 'POST'])
    def opportunity(cid=None, oid=None):
        with closing(connect()) as c, c:
            if request.method == 'POST':
                c.execute('BEGIN IMMEDIATE')
                cid, oid = service.save_opportunity(c, fields(service.OPPORTUNITY_FIELDS), cid, oid)
                return redirect(url_for('crm.contact', cid=cid), 303)
            actor = policy.authorize(c, 'edit')
            row = service.get_opportunity(c, actor, oid) if oid else {}
            contact = service.get_contact(c, actor, row.get('contact_id', cid))
            return render_template('crm/form.html', ui=shell(c, actor, 'clientes'), row=row,
                contact=contact, kind='opportunity', members=service.members(c, actor), choices=policy.STAGES, labels=policy.LABELS)

    @bp.get('/saas/pipeline')
    def pipeline():
        with closing(connect()) as c:
            actor = policy.authorize(c)
            return render_template('crm/pipeline.html', ui=shell(c, actor, 'clientes'), rows=service.pipeline(c, actor), stages=policy.STAGES, labels=policy.LABELS)

    @bp.get('/saas/clientes/<int:cid>/copilot')
    def copilot(cid):
        from copilot.permissions import authorize
        from copilot.usage import summary
        from crm.copilot import suggestions
        with closing(connect()) as c:
            actor = policy.authorize(c)
            row = service.get_contact(c, actor, cid)
            authorize(c)
            return render_template('copilot.html', ui=shell(c, actor, 'copilot'),
                crm_contact=row, suggestions=suggestions(actor), usage=summary(c, actor), request_key=str(uuid.uuid4()))

    app.register_blueprint(bp)
