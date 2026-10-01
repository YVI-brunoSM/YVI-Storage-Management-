"""Gmail HTTPS transport. No automatic retries of ambiguous send requests."""
import base64
import json
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from .validation import ApiError

SEND_SCOPE = 'https://www.googleapis.com/auth/gmail.send'
SCOPES = SEND_SCOPE + ' openid email'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
SEND_URL = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'


class MailFailure(Exception):
    def __init__(self, code, retry=False, uncertain=False, reconnect=False, retry_after=0):
        self.code, self.retry, self.uncertain, self.reconnect = code, retry, uncertain, reconnect
        self.retry_after = retry_after
        super().__init__(code)


def valid_email(value):
    return isinstance(value, str) and len(value) <= 200 and bool(re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", value))


def cipher():
    try:
        return Fernet(current_app.config['EMAIL_TOKEN_KEY'].encode('ascii'))
    except (ValueError, UnicodeError, KeyError):
        raise ApiError('EMAIL_CONFIG', 'Configure uma chave válida para proteger a conexão de e-mail.', 503) from None


def encrypt(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except (InvalidToken, AttributeError, UnicodeError):
        raise MailFailure('connection_key_changed', reconnect=True) from None


def configuration():
    config = current_app.config
    missing = [name for name in ('APP_BASE_URL', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'EMAIL_TOKEN_KEY', 'GMAIL_SENDER', 'EMAIL_REPLY_TO') if not config.get(name)]
    try:
        url = urlsplit(config.get('APP_BASE_URL', ''))
        valid_url = url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password and url.path in ('', '/') and not url.query and not url.fragment
        if config['APP_ENV'] == 'development' and url.hostname in ('localhost', '127.0.0.1'):
            valid_url = url.scheme in ('http', 'https') and not url.query and not url.fragment and url.path in ('', '/')
    except ValueError:
        valid_url = False
    if not valid_url and 'APP_BASE_URL' not in missing:
        missing.append('APP_BASE_URL')
    for name in ('GMAIL_SENDER', 'EMAIL_REPLY_TO'):
        if not valid_email(config.get(name, '')) and name not in missing:
            missing.append(name)
    try:
        cipher()
    except ApiError:
        if 'EMAIL_TOKEN_KEY' not in missing:
            missing.append('EMAIL_TOKEN_KEY')
    return missing


def callback_url():
    return current_app.config['APP_BASE_URL'].rstrip('/') + '/integrations/gmail/callback'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def google_request(url, *, form=None, payload=None, token=None, sending=False):
    # Fixed Google endpoints; credentials never follow redirects or appear in logs.
    if url not in (TOKEN_URL, USERINFO_URL, SEND_URL):
        raise ValueError('Unsupported Google endpoint')
    headers = {'Accept': 'application/json'}
    data = None
    if form is not None:
        data = urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    if payload is not None:
        data = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        with build_opener(NoRedirect).open(Request(url, data=data, headers=headers), timeout=15) as response:
            result = json.loads(response.read(1_000_000))
            if not isinstance(result, dict):
                raise ValueError()
            return result
    except HTTPError as exc:
        reason = ''
        try:
            error = json.loads(exc.read(32768)).get('error', {})
            if isinstance(error, str):
                reason = error
            elif isinstance(error, dict):
                reason = next((e.get('reason', '') for e in error.get('errors', []) if isinstance(e, dict)), '')
        except (ValueError, AttributeError, TypeError):
            pass
        if reason == 'invalid_grant' or exc.code == 401:
            raise MailFailure('authorization_expired', reconnect=True) from None
        if reason in ('invalid_client', 'unauthorized_client'):
            raise MailFailure('google_credentials_invalid', reconnect=True) from None
        if exc.code == 429 or reason in ('rateLimitExceeded', 'userRateLimitExceeded', 'dailyLimitExceeded'):
            try:
                retry_after = max(0, min(86400, int(exc.headers.get('Retry-After', '0'))))
            except (ValueError, AttributeError, TypeError):
                retry_after = 0
            raise MailFailure('google_limit', retry=True, retry_after=retry_after) from None
        if exc.code >= 500:
            raise MailFailure('google_unavailable', retry=not sending, uncertain=sending) from None
        raise MailFailure('google_rejected') from None
    except (URLError, TimeoutError, socket.timeout, OSError, ValueError):
        raise MailFailure('google_connection', retry=not sending, uncertain=sending) from None


def exchange_code(code, verifier):
    config = current_app.config
    tokens = google_request(TOKEN_URL, form={'client_id': config['GOOGLE_CLIENT_ID'], 'client_secret': config['GOOGLE_CLIENT_SECRET'], 'code': code,
        'grant_type': 'authorization_code', 'redirect_uri': callback_url(), 'code_verifier': verifier})
    if not tokens.get('access_token') or not tokens.get('refresh_token') or SEND_SCOPE not in tokens.get('scope', '').split():
        raise MailFailure('permission_missing')
    account = google_request(USERINFO_URL, token=tokens['access_token'])
    if account.get('email_verified') is not True or account.get('email', '').lower() != config['GMAIL_SENDER'].lower():
        raise MailFailure('wrong_sender')
    return tokens['refresh_token'], account['email'].lower()


def access_token(refresh_token):
    config = current_app.config
    result = google_request(TOKEN_URL, form={'client_id': config['GOOGLE_CLIENT_ID'], 'client_secret': config['GOOGLE_CLIENT_SECRET'],
        'refresh_token': refresh_token, 'grant_type': 'refresh_token'})
    if not result.get('access_token'):
        raise MailFailure('authorization_expired', reconnect=True)
    return result['access_token']


def send_message(token, message):
    result = google_request(SEND_URL, token=token, payload={'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}, sending=True)
    if not isinstance(result.get('id'), str) or not result['id']:
        raise MailFailure('google_response_uncertain', uncertain=True)
    return result['id']
