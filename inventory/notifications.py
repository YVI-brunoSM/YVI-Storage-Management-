"""Durable stock events and admin-only Gmail configuration."""
import base64
import hashlib
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlencode
from flask import Blueprint, current_app, g, jsonify, render_template, request, session
from psycopg.types.json import Jsonb
from .db import transaction
from .security import require, identity
from .validation import ApiError, body, integer
from . import mail_transport as transport

notifications = Blueprint('notifications', __name__)
ERRORS = {
    'authorization_expired': 'A autorização expirou ou foi revogada. Conecte o Gmail novamente.',
    'google_credentials_invalid': 'Revise as credenciais Google configuradas no Railway.',
    'connection_key_changed': 'A chave de proteção mudou. Restaure a chave original ou reconecte o Gmail.',
    'google_limit': 'Limite do Google atingido. A mensagem aguardará nova tentativa.',
    'google_unavailable': 'O Google ficou indisponível durante a operação.',
    'google_connection': 'A conexão com o Google foi interrompida.',
    'google_rejected': 'O Google recusou a solicitação. Confira a API, as permissões e o destinatário.',
    'google_response_uncertain': 'O Google não confirmou o resultado. Confira Enviados antes de reenviar.',
    'worker_interrupted': 'O envio foi interrompido. Confira Enviados antes de reenviar.',
    'recipient_changed': 'Destinatário desativado, alterado ou sem perfil de administrador/gerente.',
    'connection_changed': 'A conexão Gmail mudou antes do envio. Revise antes de reenviar.',
    'permission_missing': 'Autorize o envio e a identificação da conta Google e tente novamente.',
    'wrong_sender': 'Selecione a conta remetente configurada para o sistema.',
    'internal_worker_error': 'Não foi possível confirmar o envio. Revise o histórico.',
}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def stock_state(stock, minimum):
    return 'out' if Decimal(stock) == 0 else 'low' if Decimal(stock) <= Decimal(minimum) else 'available'


def recipient_rows(conn):
    return conn.execute("SELECT id,name,role,email,branch_restricted,ARRAY(SELECT b.name FROM user_branches ub JOIN branches b ON b.id=ub.branch_id WHERE ub.user_id=users.id ORDER BY b.name) AS branch_names FROM users WHERE active=1 AND role IN ('ADMIN','MANAGER') ORDER BY id").fetchall()


def queue_event(conn, key, kind, payload, product_id=None, test=False):
    event = conn.execute('INSERT INTO email_events(event_key,kind,product_id,payload) VALUES(%s,%s,%s,%s) ON CONFLICT(event_key) DO NOTHING RETURNING id',
        (key, kind, product_id, Jsonb(payload))).fetchone()
    if not event:
        return 0
    recipients = [{'id': None, 'email': current_app.config['EMAIL_REPLY_TO']}] if test else recipient_rows(conn)
    count = 0
    for user in recipients:
        address = (user['email'] or '').strip().lower()
        if transport.valid_email(address):
            row = conn.execute('INSERT INTO email_messages(event_id,user_id,recipient) VALUES(%s,%s,%s) ON CONFLICT(event_id,recipient) DO NOTHING RETURNING id',
                (event['id'], user['id'], address)).fetchone()
            count += bool(row)
    return count


def stock_event(conn, old, new, cause, key, *, initial=False):
    before = stock_state(old['current_stock'], old['min_stock'])
    after = stock_state(new['current_stock'], new['min_stock'])
    # Zero -> low is an improvement, not a new shortage. Initial stock is assessed once.
    alert = (after != 'available') if initial else ((after == 'out' and before != 'out') or (after == 'low' and before == 'available'))
    if not alert or not conn.execute('SELECT enabled FROM email_settings WHERE id=1').fetchone()['enabled']:
        return
    category = conn.execute('SELECT name FROM categories WHERE id=%s', (new['category_id'],)).fetchone()
    payload = {'name': new['name'], 'code': new['code'], 'category': category['name'], 'location': new.get('location') or 'Não informada',
        'state': after, 'before': str(old['current_stock']), 'stock': str(new['current_stock']), 'minimum': str(new['min_stock']),
        'unit': new['unit'], 'at': stamp(), **cause}
    queue_event(conn, key, 'stock', payload, new['id'])


def configured():
    if transport.configuration():
        raise ApiError('EMAIL_CONFIG', 'Conclua as variáveis de e-mail no Railway antes de continuar.', 503)


def available(settings):
    return settings['connection_status'] == 'connected' and bool(settings['refresh_token_cipher']) and settings['client_id'] == current_app.config.get('GOOGLE_CLIENT_ID') and settings['sender'] == current_app.config.get('GMAIL_SENDER', '').lower()


@notifications.get('/api/notifications')
@require(admin=True)
def overview():
    settings = g.conn.execute('SELECT enabled,connection_status,refresh_token_cipher,client_id,sender,test_accepted_at,worker_seen_at FROM email_settings WHERE id=1').fetchone()
    if not settings:
        raise ApiError('EMAIL_SETTINGS_MISSING', 'A configuração de e-mail está ausente no banco. Peça ao suporte para restaurar o registro de configuração; os envios devem permanecer pausados.', 503)
    limit = 30
    before = request.args.get('before_id')
    params = (integer(before, 'before_id'),) if before else ()
    rows = g.conn.execute("SELECT m.id,m.recipient,m.status,m.attempts,m.created_at,m.accepted_at,m.last_error,e.kind,e.payload,m.provider_id FROM email_messages m JOIN email_events e ON e.id=m.event_id " +
        ('WHERE m.id<%s ' if before else '') + 'ORDER BY m.id DESC LIMIT 31', params).fetchall()
    items = []
    for row in rows[:limit]:
        payload = row.pop('payload')
        row['subject'] = ('Teste de conexão' if row['kind'] == 'test' else 'Resumo de reposição' if row['kind'] == 'summary' else ('Esgotado' if payload.get('state') == 'out' else 'Repor') + ' · ' + payload.get('name', 'Peça'))
        row['error_message'] = ERRORS.get(row.pop('last_error'), '')
        items.append(row)
    recipients = [{**row, 'valid': transport.valid_email((row['email'] or '').strip())} for row in recipient_rows(g.conn)]
    counts = g.conn.execute('SELECT status,count(*) AS total FROM email_messages GROUP BY status').fetchall()
    connected = available(settings)
    return jsonify({'enabled': settings['enabled'], 'configured': not transport.configuration(), 'missing': transport.configuration(),
        'master_enabled': current_app.config['EMAIL_ENABLED'], 'connected': connected, 'connection_status': settings['connection_status'],
        'sender': current_app.config['GMAIL_SENDER'], 'reply_to': current_app.config['EMAIL_REPLY_TO'],
        'callback_url': transport.callback_url() if current_app.config.get('APP_BASE_URL') else None,
        'test_accepted_at': settings['test_accepted_at'] if connected else None,
        'worker_seen_at': settings['worker_seen_at'], 'daily_limit': current_app.config['EMAIL_DAILY_LIMIT'],
        'recipients': recipients, 'counts': counts, 'items': items, 'next_cursor': items[-1]['id'] if len(rows) > limit else None})


@notifications.post('/api/notifications/settings')
@require(admin=True)
def settings_update():
    data = body()
    if type(data.get('enabled')) is not bool:
        raise ApiError('INVALID_SETTING', 'Informe se os alertas devem ficar ativos.')
    settings = g.conn.execute('SELECT * FROM email_settings WHERE id=1 FOR UPDATE').fetchone()
    if data['enabled']:
        configured()
        if not current_app.config['EMAIL_ENABLED'] or not available(settings) or not settings['test_accepted_at']:
            raise ApiError('EMAIL_NOT_READY', 'Conecte o Gmail e aguarde um teste aceito antes de ativar os alertas.', 409)
        if not any(transport.valid_email((u['email'] or '').strip()) for u in recipient_rows(g.conn)):
            raise ApiError('NO_RECIPIENT', 'Cadastre o e-mail de um administrador ou gerente ativo.', 409)
    g.conn.execute('UPDATE email_settings SET enabled=%s,updated_at=now() WHERE id=1', (data['enabled'],))
    from .api import audit
    audit('email_alerts_enabled' if data['enabled'] else 'email_alerts_paused')
    return jsonify({'message': 'Alertas ativados.' if data['enabled'] else 'Alertas pausados. Mensagens já em envio podem ser concluídas.'})


@notifications.post('/api/notifications/connect')
@require(admin=True)
def connect():
    configured()
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    g.conn.execute('DELETE FROM email_oauth_states WHERE expires_at<now() OR user_id=%s', (g.user['id'],))
    g.conn.execute("INSERT INTO email_oauth_states(state_hash,user_id,session_hash,verifier_cipher,expires_at) VALUES(%s,%s,%s,%s,now()+interval '10 minutes')",
        (hashlib.sha256(state.encode()).hexdigest(), g.user['id'], hashlib.sha256(session['csrf'].encode()).hexdigest(), transport.encrypt(verifier)))
    session['gmail_oauth_state'] = state
    params = {'client_id': current_app.config['GOOGLE_CLIENT_ID'], 'redirect_uri': transport.callback_url(), 'response_type': 'code',
        'scope': transport.SCOPES, 'access_type': 'offline', 'prompt': 'consent select_account', 'state': state,
        'login_hint': current_app.config['GMAIL_SENDER'], 'code_challenge_method': 'S256',
        'code_challenge': base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()}
    return jsonify({'url': 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params)})


@notifications.get('/integrations/gmail/callback')
def callback():
    success = False
    message = 'A conexão não foi concluída. Volte ao sistema e tente novamente.'
    try:
        configured()
        state = request.args.get('state', '')
        expected = session.pop('gmail_oauth_state', '')
        if not state or not expected or not secrets.compare_digest(state, expected):
            raise ApiError('OAUTH_STATE', 'A autorização expirou ou não corresponde a esta sessão. Inicie a conexão novamente.', 400)
        with transaction() as conn:
            user = identity(conn)
            if user['role'] != 'ADMIN':
                raise ApiError('FORBIDDEN', 'Entre como administrador para conectar o Gmail.', 403)
            binding = hashlib.sha256(session['csrf'].encode()).hexdigest()
            stored = conn.execute('DELETE FROM email_oauth_states WHERE state_hash=%s AND user_id=%s AND session_hash=%s AND expires_at>now() RETURNING verifier_cipher',
                (hashlib.sha256(state.encode()).hexdigest(), user['id'], binding)).fetchone()
        if not stored:
            raise ApiError('OAUTH_STATE', 'Esta autorização expirou ou já foi utilizada. Inicie outra conexão.', 400)
        if request.args.get('error') or not request.args.get('code'):
            raise ApiError('OAUTH_DENIED', 'A autorização foi cancelada. Nenhum envio foi ativado.', 400)
        refresh, sender = transport.exchange_code(request.args['code'], transport.decrypt(stored['verifier_cipher']))
        encrypted = transport.encrypt(refresh)
        with transaction() as conn:
            current_user = identity(conn)
            if current_user['id'] != user['id'] or current_user['role'] != 'ADMIN':
                raise ApiError('FORBIDDEN', 'Seu acesso mudou. Entre novamente.', 403)
            conn.execute("UPDATE email_settings SET enabled=false,sender=%s,client_id=%s,refresh_token_cipher=%s,connection_status='connected',connection_revision=connection_revision+1,test_accepted_at=NULL,connected_at=now(),updated_at=now() WHERE id=1",
                (sender, current_app.config['GOOGLE_CLIENT_ID'], encrypted))
            conn.execute("INSERT INTO audit_events(actor_id,action,details) VALUES(%s,'gmail_connected','{}')", (user['id'],))
        success, message = True, 'Gmail conectado. Volte às notificações e envie uma mensagem de teste antes de ativar os alertas.'
    except ApiError as exc:
        message = exc.message
    except transport.MailFailure as exc:
        message = ERRORS.get(exc.code, message)
        current_app.logger.warning('gmail_oauth_failed code=' + exc.code)
    except Exception:
        current_app.logger.error('gmail_oauth_failed', exc_info=True)
    response = current_app.make_response(render_template('gmail_result.html', success=success, message=message))
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@notifications.post('/api/notifications/disconnect')
@require(admin=True)
def disconnect():
    g.conn.execute("UPDATE email_settings SET enabled=false,refresh_token_cipher=NULL,sender=NULL,client_id=NULL,connection_status='disconnected',connection_revision=connection_revision+1,test_accepted_at=NULL,updated_at=now() WHERE id=1")
    g.conn.execute('DELETE FROM email_oauth_states')
    g.conn.execute("UPDATE email_messages SET status='cancelled',last_error='connection_changed' WHERE status='pending'")
    from .api import audit
    audit('gmail_disconnected')
    return jsonify({'message': 'Conexão removida do sistema. Você também pode revogar o acesso nas conexões da sua Conta Google.'})


@notifications.post('/api/notifications/test')
@require(admin=True)
def test_email():
    configured()
    settings = g.conn.execute('SELECT * FROM email_settings WHERE id=1 FOR UPDATE').fetchone()
    if not current_app.config['EMAIL_ENABLED'] or not available(settings):
        raise ApiError('EMAIL_NOT_READY', 'Habilite o serviço de envio e conecte o Gmail primeiro.', 409)
    if g.conn.execute("SELECT 1 FROM email_events WHERE kind='test' AND created_at>now()-interval '1 minute'").fetchone():
        raise ApiError('TEST_LIMIT', 'Aguarde um minuto antes de solicitar outro teste.', 429)
    queue_event(g.conn, 'test:' + secrets.token_hex(16), 'test', {'at': stamp(), 'actor': g.user['name']}, test=True)
    return jsonify({'message': 'Teste colocado na fila para ' + current_app.config['EMAIL_REPLY_TO'] + '. Aguarde o processamento e confira sua caixa de entrada.'}), 202


@notifications.post('/api/notifications/summary')
@require(admin=True)
def summary():
    settings = g.conn.execute('SELECT * FROM email_settings WHERE id=1 FOR UPDATE').fetchone()
    if not settings['enabled']:
        raise ApiError('EMAIL_PAUSED', 'Ative os alertas antes de enviar o resumo.', 409)
    if g.conn.execute("SELECT 1 FROM email_events WHERE kind='summary' AND created_at>now()-interval '1 hour'").fetchone():
        raise ApiError('SUMMARY_LIMIT', 'Um resumo já foi solicitado na última hora.', 429)
    rows = g.conn.execute('SELECT code,name,unit,current_stock,min_stock FROM products WHERE active=1 AND current_stock<=min_stock ORDER BY code LIMIT 1001').fetchall()
    payload = {'at': stamp(), 'items': [{k: str(v) for k,v in row.items()} for row in rows[:1000]], 'truncated': len(rows)>1000}
    count = queue_event(g.conn, 'summary:' + secrets.token_hex(16), 'summary', payload)
    return jsonify({'message': f'Resumo colocado na fila para {count} destinatário(s).'}), 202


@notifications.post('/api/notifications/<int:mid>/retry')
@require(admin=True)
def retry(mid):
    data = body()
    row = g.conn.execute('SELECT * FROM email_messages WHERE id=%s FOR UPDATE', (mid,)).fetchone()
    if not row or row['status'] not in ('failed', 'uncertain'):
        raise ApiError('RETRY_CONFLICT', 'Esta mensagem não está disponível para reenvio.', 409)
    if row['status'] == 'uncertain' and data.get('reviewed_sent_folder') is not True:
        raise ApiError('REVIEW_REQUIRED', 'Confira a pasta Enviados do Gmail antes de reenviar uma mensagem com resultado incerto.', 409)
    g.conn.execute("UPDATE email_messages SET status='pending',attempts=0,last_error=NULL,next_attempt_at=now(),claimed_at=NULL WHERE id=%s", (mid,))
    from .api import audit
    audit('email_retry_requested', mid, {'previous_status': row['status']})
    return jsonify({'message': 'Mensagem recolocada na fila. O serviço verificará a conexão e o destinatário antes do envio.'})
