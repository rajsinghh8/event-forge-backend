from __future__ import annotations
import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from flask import Flask, g, jsonify, request
from .config import Settings
from .database import Database
from .errors import DomainError, ValidationError, NotFoundError, AuthorizationError, ConflictError
from .security import hash_password, require_auth, token_for, verify_password

def _value(value):
    if isinstance(value, (UUID, Decimal)): return str(value)
    if isinstance(value, datetime): return value.isoformat()
    return value

def create_app(settings: Settings | None = None) -> Flask:
    app = Flask(__name__); settings = settings or Settings.from_env(); database = Database(settings.database_url)
    app.extensions['settings'] = settings; app.extensions['services'] = {'database': database}
    logging.basicConfig(level=logging.INFO)
    @app.errorhandler(DomainError)
    def domain_error(error): return jsonify(timestamp=datetime.now(timezone.utc).isoformat(), status=error.status_code, error=error.__class__.__name__, message=error.message, path=request.path), error.status_code
    @app.errorhandler(404)
    def not_found(error): return jsonify(timestamp=datetime.now(timezone.utc).isoformat(), status=404, error='NotFound', message='Resource not found', path=request.path), 404
    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception('Unhandled request failure')
        return jsonify(timestamp=datetime.now(timezone.utc).isoformat(), status=500, error='InternalServerError', message='An internal error occurred', path=request.path), 500
    @app.get('/health')
    def health(): return {'status':'ok'}
    @app.post('/auth/register')
    def register():
        body = request.get_json(silent=True)
        if not isinstance(body,dict) or not isinstance(body.get('email'),str) or not isinstance(body.get('password'),str) or len(body['password']) < 8: raise ValidationError('email and password (minimum 8 characters) are required')
        email=body['email'].strip().lower()
        if '@' not in email or email.startswith('@') or email.endswith('@'): raise ValidationError('email is invalid')
        user_id=uuid4()
        try: database.execute('INSERT INTO users (id,email,password_hash) VALUES (%s,%s,%s)',(user_id,email,hash_password(body['password'])))
        except Exception as exc:
            if 'unique' in str(exc).lower(): raise ConflictError('Email is already registered') from exc
            raise
        return jsonify({'id':str(user_id),'email':email}),201
    @app.post('/auth/login')
    def login():
        body=request.get_json(silent=True)
        if not isinstance(body,dict): raise ValidationError('Request body must be a JSON object')
        row=database.fetchone('SELECT id,password_hash FROM users WHERE email=%s',(str(body.get('email','')).strip().lower(),))
        if row is None or not verify_password(str(body.get('password','')),row['password_hash']):
            from .errors import AuthenticationError; raise AuthenticationError('Invalid credentials')
        return {'accessToken':token_for(row['id']),'tokenType':'Bearer'}
    def event_for_owner(event_id):
        row=database.fetchone('SELECT * FROM events WHERE id=%s',(event_id,))
        if row is None: raise NotFoundError('Event not found')
        if str(row['owner_id']) != str(g.user_id): raise AuthorizationError('You do not own this event')
        return row
    @app.get('/events')
    @require_auth
    def list_events():
        rows=database.fetchall('SELECT * FROM events WHERE owner_id=%s ORDER BY created_at DESC',(g.user_id,)); return {'items':[{k:_value(v) for k,v in r.items()} for r in rows], 'total':len(rows),'page':1,'size':len(rows)}
    @app.post('/events')
    @require_auth
    def create_event():
        body=request.get_json(silent=True)
        if not isinstance(body,dict): raise ValidationError('Request body must be a JSON object')
        required=['name','startAt','endAt','capacity','plannedBudget']
        if any(key not in body for key in required): raise ValidationError('Missing required event fields')
        try: start=datetime.fromisoformat(body['startAt']); end=datetime.fromisoformat(body['endAt']); budget=Decimal(str(body['plannedBudget'])); capacity=int(body['capacity'])
        except (ValueError,ArithmeticError) as exc: raise ValidationError('Invalid event values') from exc
        if start>=end or budget<0 or capacity<0: raise ValidationError('Invalid event dates, capacity, or plannedBudget')
        eid=uuid4(); database.execute('INSERT INTO events(id,owner_id,name,description,start_at,end_at,capacity,planned_budget) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(eid,g.user_id,body['name'],body.get('description'),start,end,capacity,budget)); return {'id':str(eid)},201
    @app.get('/events/<uuid:event_id>')
    @require_auth
    def get_event(event_id): return {k:_value(v) for k,v in event_for_owner(event_id).items()}
    @app.patch('/events/<uuid:event_id>')
    @require_auth
    def patch_event(event_id):
        event_for_owner(event_id); body=request.get_json(silent=True)
        if not isinstance(body,dict): raise ValidationError('Request body must be a JSON object')
        allowed={'name':'name','description':'description','capacity':'capacity','plannedBudget':'planned_budget'}
        pairs=[(allowed[k],body[k]) for k in body if k in allowed]
        if not pairs: raise ValidationError('No updatable fields supplied')
        database.execute('UPDATE events SET '+','.join(f'{c}=%s' for c,_ in pairs)+',updated_at=now() WHERE id=%s',tuple(v for _,v in pairs)+(event_id,)); return {k:_value(v) for k,v in event_for_owner(event_id).items()}
    @app.delete('/events/<uuid:event_id>')
    @require_auth
    def delete_event(event_id): event_for_owner(event_id); database.execute('DELETE FROM events WHERE id=%s',(event_id,)); return '',204
    @app.get('/events/<uuid:event_id>/budget')
    @require_auth
    def budget(event_id):
        row=event_for_owner(event_id); actual=database.fetchone('SELECT COALESCE(SUM(e.amount),0) actual FROM expenses e JOIN budget_categories b ON b.id=e.budget_category_id WHERE b.event_id=%s',(event_id,))['actual']; return {'planned':str(row['planned_budget']),'actual':str(actual),'remaining':str(Decimal(row['planned_budget'])-Decimal(actual))}
    _register_modules(app,database)
    @app.get('/openapi.json')
    @require_auth
    def openapi(): return _openapi()
    @app.get('/docs')
    @require_auth
    def docs(): return '<!doctype html><html><body><div id="swagger-ui"></div><script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script><script>SwaggerUIBundle({url:"/openapi.json",dom_id:"#swagger-ui"})</script></body></html>'
    return app

def _register_modules(app, db):
    try:
        from .budget_service import BudgetService; from .budget_routes import budget_bp
        app.extensions['services']['budget']=BudgetService(db); app.register_blueprint(budget_bp)
        from .tasks.service import TaskService; from .tasks.routes import task_bp
        app.extensions['services']['task_service']=TaskService(db); app.register_blueprint(task_bp,url_prefix='/events/<event_id>/tasks')
        from .notifications import NotificationAuditService, notification_audit_bp
        app.extensions['services']['notifications']=NotificationAuditService(db); app.register_blueprint(notification_audit_bp)
        from .schedule_routes import create_schedule_blueprint; app.register_blueprint(create_schedule_blueprint(db))
        from .vendors import create_vendor_blueprint; app.register_blueprint(create_vendor_blueprint(db))
    except ImportError as error: app.logger.warning('Optional resource module unavailable: %s',error)

def _openapi(): return {'openapi':'3.0.3','info':{'title':'EventForge','version':'1.0.0'},'paths':{},'components':{'securitySchemes':{'bearerAuth':{'type':'http','scheme':'bearer','bearerFormat':'JWT'}}}}

app = create_app() if __import__('os').environ.get('DATABASE_URL') and __import__('os').environ.get('JWT_SECRET') else None
