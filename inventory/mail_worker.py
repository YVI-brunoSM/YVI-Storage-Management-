"""Short database reservations, HTTPS outside transactions, conservative send recovery."""
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from html import escape
from zoneinfo import ZoneInfo
from flask import current_app
from .db import transaction
from .branch_access import product_scope
from .notifications import available
from . import mail_transport as transport


def render_message(row, sender):
    payload = row['payload']
    when = datetime.fromisoformat(payload['at']).astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y às %H:%M')
    if row['kind'] == 'test':
        title = 'Teste de conexão'
        lines = ['A conexão do sistema YVI com o Gmail está funcionando.', 'Solicitado por: ' + payload['actor'], 'Data: ' + when,
                 'Esta mensagem é um teste. Os alertas só serão enviados após a ativação no sistema.']
    elif row['kind'] == 'summary':
        title = 'Resumo de reposição'
        lines = ['Estoque Geral · posição em ' + when]
        for item in payload['items']:
            lines.append(f"{item.get('branch', 'Unidade não informada')} | {item['code']} — {item['name']} | Saldo: {item['current_stock']} {item['unit']} | Mínimo: {item['min_stock']} {item['unit']}")
        if not payload['items']:
            lines.append('Nenhuma peça precisa de reposição nesta consulta.')
        if payload.get('truncated'):
            lines.append('Exibindo as primeiras 1.000 peças. Consulte a lista completa no sistema.')
    else:
        title = ('Esgotado' if payload['state'] == 'out' else 'Repor') + ' — ' + payload['name']
        lines = ['Estoque Geral', 'Peça: ' + payload['name'], 'Código: ' + payload['code'], 'Categoria: ' + payload['category'],
            'Localização: ' + payload['location'], f"Saldo anterior: {payload['before']} {payload['unit']}",
            f"Saldo no alerta: {payload['stock']} {payload['unit']}", f"Estoque mínimo: {payload['minimum']} {payload['unit']}",
            'Ocorrência: ' + payload['operation'], 'Responsável: ' + payload['actor'], 'Data: ' + when]
        if payload.get('quantity'):
            lines.append(f"Quantidade movimentada: {payload['quantity']} {payload['unit']}")
        if payload.get('branch'):
            lines.append('Unidade: ' + payload['branch'])
        if payload.get('notes'):
            lines.append('Observação: ' + payload['notes'])
        lines.append('Os valores correspondem ao momento do alerta; o saldo atual pode ter mudado.')
    title = ' '.join(title.split())[:160]
    url = current_app.config['APP_BASE_URL'].rstrip('/') + ('/#notifications' if row['kind'] == 'test' else '/#alerts')
    lines.append(f"Referência: YVI-{row['id']}")
    message = EmailMessage(policy=SMTP)
    message['From'] = f'YVI — Notificações <{sender}>'
    message['To'] = row['recipient']
    message['Reply-To'] = current_app.config['EMAIL_REPLY_TO']
    message['Subject'] = f"[YVI #{row['id']}] {title}"
    message['Date'] = format_datetime(datetime.now(timezone.utc))
    message.set_content('\n'.join(lines) + '\n\nConsultar no sistema: ' + url)
    paragraphs = ''.join('<p style="margin:0 0 10px;white-space:pre-line">' + escape(line) + '</p>' for line in lines)
    message.add_alternative('<!doctype html><html lang="pt-BR"><body style="margin:0;background:#f7f4ee;color:#302d28;font:15px Arial,sans-serif"><div style="max-width:640px;margin:24px auto;padding:28px;background:#fff"><p style="font-weight:bold;letter-spacing:3px">YVI</p><h1 style="font-size:23px">' + escape(title) + '</h1>' + paragraphs + '<p><a href="' + escape(url, quote=True) + '" style="color:#a34b26">Consultar no sistema</a></p></div></body></html>', subtype='html')
    return message


def recipient_allowed(conn, row):
    if row['kind'] == 'test':
        return row['recipient'] == current_app.config['EMAIL_REPLY_TO'].lower()
    user = conn.execute('SELECT active,role,email,branch_restricted FROM users WHERE id=%s', (row['user_id'],)).fetchone()
    if not (user and user['active'] and user['role'] in ('ADMIN', 'MANAGER') and (user['email'] or '').strip().lower() == row['recipient']):
        return False
    if not user['branch_restricted']:
        return True
    ids = [r['branch_id'] for r in conn.execute('SELECT branch_id FROM user_branches WHERE user_id=%s', (row['user_id'],))]
    if not ids:
        return False
    condition, params = product_scope(ids)
    if row['kind'] == 'summary':
        codes = {r['code'] for r in conn.execute('SELECT p.code FROM products p WHERE '+condition, params)}
        row['payload'] = {**row['payload'], 'items': [p for p in row['payload']['items'] if p['code'] in codes and str(p.get('branch_id')) in {str(bid) for bid in ids}], 'truncated': False}
        return True
    payload = row['payload']
    if payload.get('branch_id') not in ids:
        return False
    return bool(conn.execute('SELECT 1 FROM products p WHERE p.id=%s AND '+condition, (row.get('product_id'), *params)).fetchone())


def claim():
    with transaction() as conn:
        settings = conn.execute('SELECT * FROM email_settings WHERE id=1 FOR UPDATE').fetchone()
        conn.execute('UPDATE email_settings SET worker_seen_at=now() WHERE id=1')
        conn.execute("UPDATE email_messages SET status='uncertain',last_error='worker_interrupted' WHERE status='processing' AND claimed_at<now()-interval '5 minutes'")
        conn.execute('DELETE FROM email_oauth_states WHERE expires_at<now()')
        conn.execute("DELETE FROM email_attempts WHERE started_at<now()-interval '90 days'")
        # Retain unresolved messages; only terminal events older than 90 days are removed.
        conn.execute("DELETE FROM email_events e WHERE e.created_at<now()-interval '90 days' AND NOT EXISTS(SELECT 1 FROM email_messages m WHERE m.event_id=e.id AND m.status IN ('pending','processing','uncertain','failed'))")
        if not current_app.config['EMAIL_ENABLED'] or transport.configuration() or not available(settings):
            return None
        used = conn.execute("SELECT count(*) AS n FROM email_attempts WHERE started_at>now()-interval '24 hours'").fetchone()['n']
        if used >= current_app.config['EMAIL_DAILY_LIMIT']:
            return None
        row = conn.execute("SELECT m.*,e.kind,e.payload,e.product_id FROM email_messages m JOIN email_events e ON e.id=m.event_id WHERE m.status='pending' AND m.next_attempt_at<=now() AND (e.kind='test' OR %s) ORDER BY m.id LIMIT 1 FOR UPDATE OF m SKIP LOCKED", (settings['enabled'],)).fetchone()
        if not row:
            return None
        if not recipient_allowed(conn, row):
            conn.execute("UPDATE email_messages SET status='cancelled',last_error='recipient_changed' WHERE id=%s", (row['id'],))
            return None
        conn.execute("UPDATE email_messages SET status='processing',attempts=attempts+1,claimed_at=now(),connection_revision=%s WHERE id=%s", (settings['connection_revision'], row['id']))
        conn.execute('INSERT INTO email_attempts(message_id) VALUES(%s)', (row['id'],))
        row['attempts'] += 1
        row['connection_revision'] = settings['connection_revision']
        return row, settings


def process_once():
    claimed = claim()
    if not claimed:
        return False
    row, settings = claimed
    try:
        token = transport.access_token(transport.decrypt(settings['refresh_token_cipher']))
        # Recheck after token renewal. Nothing holds a stock transaction during HTTPS.
        with transaction() as conn:
            latest = conn.execute('SELECT * FROM email_settings WHERE id=1').fetchone()
            if latest['connection_revision'] != settings['connection_revision'] or not available(latest):
                conn.execute("UPDATE email_messages SET status='cancelled',last_error='connection_changed' WHERE id=%s", (row['id'],))
                return True
            if row['kind'] != 'test' and not latest['enabled']:
                conn.execute("UPDATE email_messages SET status='pending',next_attempt_at=now()+interval '1 minute' WHERE id=%s", (row['id'],))
                return True
            if not recipient_allowed(conn, row):
                conn.execute("UPDATE email_messages SET status='cancelled',last_error='recipient_changed' WHERE id=%s", (row['id'],))
                return True
        message = render_message(row, settings['sender'])
        provider_id = transport.send_message(token, message)
        with transaction() as conn:
            conn.execute("UPDATE email_messages SET status='accepted',accepted_at=now(),provider_id=%s,last_error=NULL WHERE id=%s AND status='processing'", (provider_id, row['id']))
            if row['kind'] == 'test':
                conn.execute("UPDATE email_settings SET test_accepted_at=now() WHERE id=1 AND connection_revision=%s AND connection_status='connected'", (row['connection_revision'],))
        current_app.logger.info('email_accepted message_id=' + str(row['id']))
    except transport.MailFailure as exc:
        status = 'uncertain' if exc.uncertain else 'pending' if exc.retry and row['attempts'] < 5 else 'failed'
        delay = max(exc.retry_after, min(3600, 60 * 2 ** min(row['attempts'], 6)))
        with transaction() as conn:
            conn.execute("UPDATE email_messages SET status=%s,last_error=%s,next_attempt_at=now()+(%s * interval '1 second') WHERE id=%s AND status='processing'", (status, exc.code, delay, row['id']))
            if exc.reconnect:
                conn.execute("UPDATE email_settings SET connection_status='needs_reconnect',test_accepted_at=NULL WHERE id=1 AND connection_revision=%s", (row['connection_revision'],))
        current_app.logger.warning('email_send_failed message_id=' + str(row['id']) + ' code=' + exc.code)
    except Exception:
        # A crash after Gmail accepted the message must never silently cause a duplicate.
        with transaction() as conn:
            conn.execute("UPDATE email_messages SET status='uncertain',last_error='internal_worker_error' WHERE id=%s AND status='processing'", (row['id'],))
        current_app.logger.error('email_worker_failure message_id=' + str(row['id']), exc_info=True)
    return True
