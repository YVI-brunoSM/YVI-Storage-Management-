from functools import wraps
import secrets
from flask import g, session, request, current_app
from .db import transaction
from .validation import ApiError

PERMISSIONS = ('dashboard', 'products_view', 'products_manage', 'costs_view', 'categories_manage',
               'movements_in', 'movements_out', 'alerts_view', 'branches_manage', 'users_manage', 'reports_export')
ROLES = ('ADMIN', 'MANAGER', 'OPERATOR')


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


def identity(conn):
    uid = session.get('user_id')
    if not isinstance(uid, int):
        raise ApiError('LOGIN_REQUIRED', 'Entre novamente para continuar.', 401)
    user = conn.execute('SELECT id, username, name, email, role, active, session_version, version, avatar_revision, (avatar IS NOT NULL) AS has_avatar, branch_restricted, ARRAY(SELECT branch_id FROM user_branches WHERE user_id=users.id ORDER BY branch_id) AS branch_ids FROM users WHERE id=%s', (uid,)).fetchone()
    if not user or not user['active'] or user['session_version'] != session.get('session_version'):
        session.clear()
        raise ApiError('LOGIN_REQUIRED', 'Sua sessão foi encerrada. Entre novamente.', 401)
    permissions = conn.execute('SELECT * FROM role_permissions WHERE role=%s', (user['role'],)).fetchone()
    if not permissions:
        raise ApiError('FORBIDDEN', 'Perfil sem permissões configuradas.', 403)
    user['permissions'] = {p: bool(permissions[p]) for p in PERMISSIONS}
    return user


def require(permission=None, admin=False):
    def decorate(fn):
        @wraps(fn)
        def run(*args, **kwargs):
            with transaction() as conn:
                g.conn = conn
                g.user = identity(conn)
                if admin and g.user['role'] != 'ADMIN':
                    raise ApiError('FORBIDDEN', 'Apenas administradores podem realizar esta ação.', 403)
                if permission and not g.user['permissions'][permission]:
                    raise ApiError('FORBIDDEN', 'Você não tem permissão para esta ação.', 403)
                result = fn(*args, **kwargs)
            # A notification failure never changes the result of an already committed write.
            realtime = current_app.extensions['realtime']
            for uid in getattr(g, 'revoke_users', []):
                realtime.revoke(uid)
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                realtime.changed()
            return result
        return run
    return decorate


def permitted(permission):
    if not g.user['permissions'][permission]:
        raise ApiError('FORBIDDEN', 'Você não tem permissão para esta ação.', 403)


def expect_version(row, data):
    from .validation import integer
    if not row:
        raise ApiError('NOT_FOUND', 'Registro não encontrado.', 404)
    version = integer(data.get('version'), 'version')
    if row['version'] != version:
        raise ApiError('VERSION_CONFLICT', 'Outra pessoa alterou este registro. Reabra a versão atual antes de salvar.', 409)
