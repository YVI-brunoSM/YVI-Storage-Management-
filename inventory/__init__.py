import json
import logging
import os
import secrets
import time
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from flask import Flask, g, request, session, jsonify, render_template
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from psycopg import OperationalError, InterfaceError, errors
from psycopg_pool import PoolTimeout, TooManyRequests
from dotenv import load_dotenv
from .db import Database, transaction
from .validation import ApiError

ROOT = Path(__file__).resolve().parent.parent


class JSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(value):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return DefaultJSONProvider.default(value)


class SafeLogFormatter(logging.Formatter):
    def format(self, record):
        data = {'time': datetime.now(timezone.utc).isoformat(), 'level': record.levelname,
                'event': record.getMessage()}
        if record.exc_info:
            # SQL exception messages can contain field values; log class and source frames only.
            import traceback
            data['exception'] = record.exc_info[0].__name__
            data['frames'] = [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                              for f in traceback.extract_tb(record.exc_info[2])]
        return json.dumps(data, ensure_ascii=False)


def create_app(config=None):
    load_dotenv(ROOT / '.env')
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.json = JSONProvider(app)
    app.config.update(
        SECRET_KEY=os.getenv('SECRET_KEY', ''), DATABASE_URL=os.getenv('DATABASE_URL', ''),
        REDIS_URL=os.getenv('REDIS_URL'), APP_ENV=os.getenv('APP_ENV', 'production'),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=True,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8), SESSION_REFRESH_EACH_REQUEST=False,
        MAX_CONTENT_LENGTH=65536, DB_POOL_SIZE=int(os.getenv('DB_POOL_SIZE', '8')),
        DB_POOL_TIMEOUT=float(os.getenv('DB_POOL_TIMEOUT', '3')),
        DB_STATEMENT_TIMEOUT_MS=int(os.getenv('DB_STATEMENT_TIMEOUT_MS', '5000')),
        TRUST_PROXY=int(os.getenv('TRUST_PROXY', '0')), TESTING=False,
        APP_BASE_URL=os.getenv('APP_BASE_URL', '').rstrip('/'),
        GOOGLE_CLIENT_ID=os.getenv('GOOGLE_CLIENT_ID', ''), GOOGLE_CLIENT_SECRET=os.getenv('GOOGLE_CLIENT_SECRET', ''),
        EMAIL_TOKEN_KEY=os.getenv('EMAIL_TOKEN_KEY', ''), EMAIL_ENABLED=os.getenv('EMAIL_ENABLED', 'false').lower() == 'true',
        GMAIL_SENDER=os.getenv('GMAIL_SENDER', 'yvigestaofitness@gmail.com').strip().lower(),
        EMAIL_REPLY_TO=os.getenv('EMAIL_REPLY_TO', 'yvibrunosilva@gmail.com').strip().lower(),
        EMAIL_DAILY_LIMIT=100,
    )
    if config:
        app.config.update(config)
    if os.getenv('EMAIL_DAILY_LIMIT') and not (config and 'EMAIL_DAILY_LIMIT' in config):
        try:
            app.config['EMAIL_DAILY_LIMIT'] = max(1, min(450, int(os.environ['EMAIL_DAILY_LIMIT'])))
        except ValueError:
            app.config['EMAIL_DAILY_LIMIT'] = 100
    if len(app.config['SECRET_KEY']) < 32 or app.config['SECRET_KEY'].startswith('troque'):
        raise RuntimeError('Configure SECRET_KEY aleatória com pelo menos 32 caracteres.')
    if not app.config['DATABASE_URL']:
        raise RuntimeError('Configure DATABASE_URL para PostgreSQL.')
    from psycopg.conninfo import conninfo_to_dict
    try:
        database_config = conninfo_to_dict(app.config['DATABASE_URL'])
        if not database_config.get('host') or not database_config.get('dbname'):
            raise ValueError()
    except Exception:
        raise RuntimeError('DATABASE_URL deve identificar servidor e banco PostgreSQL.') from None
    if app.config['APP_ENV'] == 'development':
        app.config['SESSION_COOKIE_SECURE'] = False
    if app.config['TRUST_PROXY']:
        # Enable only after confirming a single trusted proxy, e.g. Railway ingress.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    handler = logging.StreamHandler()
    handler.setFormatter(SafeLogFormatter())
    app.logger.handlers = [handler]
    app.logger.setLevel(logging.INFO)
    app.extensions['db'] = Database(app.config)
    from .realtime import Realtime
    app.extensions['realtime'] = Realtime(app)
    from .api import api
    app.register_blueprint(api)
    from .notifications import notifications
    app.register_blueprint(notifications)

    @app.before_request
    def begin_request():
        g.request_id = secrets.token_hex(12)
        g.start_time = time.monotonic()
        if request.path == '/api/me/avatar' and request.method == 'PUT':
            request.max_content_length = 2_850_000
        if request.path.startswith('/api/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            expected, actual = session.get('csrf'), request.headers.get('X-CSRF-Token', '')
            if not expected or not secrets.compare_digest(expected, actual):
                raise ApiError('CSRF_EXPIRED', 'Atualize a sessão e tente novamente. Seu formulário foi mantido.', 403)

    @app.after_request
    def finish_request(response):
        response.headers['X-Request-ID'] = getattr(g, 'request_id', '')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer' if request.path == '/integrations/gmail/callback' else 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
        if request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if not request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store'
        if request.path.startswith('/api/'):
            app.logger.info(json.dumps({'request_id': getattr(g, 'request_id', ''), 'method': request.method,
                            'route': str(request.url_rule), 'status': response.status_code,
                            'duration_ms': round((time.monotonic() - g.start_time) * 1000)}))
        return response

    def error_response(code, message, status, fields=None):
        payload = {'error': {'code': code, 'message': message, 'fields': fields or {}, 'request_id': getattr(g, 'request_id', '')}}
        response = jsonify(payload)
        response.status_code = status
        if status in (429, 503):
            response.headers['Retry-After'] = '15'
        return response

    @app.errorhandler(Exception)
    def handle_error(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.code, exc.message, exc.status, exc.fields)
        if isinstance(exc, (errors.UndefinedTable, errors.UndefinedColumn)):
            app.logger.error('schema_not_ready request_id=' + getattr(g, 'request_id', ''), exc_info=True)
            return error_response('SCHEMA_NOT_READY', 'O banco precisa ser atualizado. Peça ao administrador para executar python migrate.py no serviço do sistema no Railway.', 503)
        if isinstance(exc, (errors.LockNotAvailable, errors.DeadlockDetected, errors.SerializationFailure)):
            return error_response('BUSY', 'Outro usuário está concluindo uma operação. Aguarde e tente novamente.', 409)
        if isinstance(exc, (PoolTimeout, TooManyRequests, OperationalError, InterfaceError)):
            app.logger.error('database_unavailable request_id=' + getattr(g, 'request_id', ''), exc_info=True)
            return error_response('TEMPORARILY_UNAVAILABLE', 'Serviço temporariamente indisponível. Tente novamente em instantes.', 503)
        if isinstance(exc, errors.UniqueViolation):
            return error_response('DUPLICATE', 'Já existe um registro com este código ou identificação.', 409)
        if isinstance(exc, (errors.CheckViolation, errors.ForeignKeyViolation, errors.NotNullViolation, errors.NumericValueOutOfRange)):
            return error_response('INVALID_REFERENCE', 'Revise os valores e os registros relacionados.', 422)
        if isinstance(exc, HTTPException):
            return error_response('HTTP_ERROR', {400:'Solicitação inválida.',404:'Recurso não encontrado.',405:'Ação não permitida.',413:'Solicitação muito grande.',415:'Envie dados no formato JSON.'}.get(exc.code,'Não foi possível atender à solicitação.'), exc.code)
        app.logger.error('unhandled_error request_id=' + getattr(g, 'request_id', ''), exc_info=True)
        return error_response('INTERNAL_ERROR', 'Não foi possível concluir. Tente novamente ou informe o protocolo ao suporte.', 500)

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/politica-de-privacidade')
    def privacy():
        return render_template('privacy.html')

    @app.get('/health/live')
    def live():
        return jsonify({'status': 'ok'})

    @app.get('/health/ready')
    def ready():
        with transaction() as conn:
            row = conn.execute('SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1').fetchone()
            if not row or row['version'] != '005_email_notifications':
                raise ApiError('SCHEMA_NOT_READY', 'Sistema em atualização.', 503)
        return jsonify({'status': 'ready'})
    return app
