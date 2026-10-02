"""Server-side unit authorization, independent of browser filters."""
from flask import g
from .validation import ApiError, integer, invalid


def allowed_ids():
    return g.user['branch_ids'] if g.user['branch_restricted'] else None


def check_branch(bid):
    ids = allowed_ids()
    if ids is not None and bid not in ids:
        raise ApiError('BRANCH_FORBIDDEN', 'Você não tem acesso a esta unidade.', 403)


def product_scope(ids):
    return 'EXISTS(SELECT 1 FROM product_stocks scope WHERE scope.product_id=p.id AND scope.enabled AND scope.branch_id=ANY(%s))', [ids]


def check_product(pid):
    ids = allowed_ids()
    if ids is not None:
        condition, params = product_scope(ids)
        if not g.conn.execute('SELECT 1 FROM products p WHERE p.id=%s AND '+condition, (pid, *params)).fetchone():
            raise ApiError('PRODUCT_FORBIDDEN', 'Esta peça não está vinculada às suas unidades autorizadas.', 403)


def shared_catalog():
    if allowed_ids() is not None:
        raise ApiError('SHARED_CATALOG', 'O cadastro é compartilhado entre as unidades. Solicite esta alteração a um administrador.', 403)


def scope_ids(branch):
    return branch.get('ids', [branch['id']])


def save_access(conn, uid, data, role, *, create=False):
    # Omission on old API clients preserves existing restrictions.
    if 'branch_ids' not in data and not create and role != 'ADMIN':
        return
    raw = data.get('branch_ids')
    if role == 'ADMIN' and raw is not None:
        invalid('branch_ids', 'Administradores mantêm acesso a todas as unidades.')
    ids = None
    if raw is not None:
        if not isinstance(raw, list) or not 1 <= len(raw) <= 1000 or any(type(v) is not int for v in raw):
            invalid('branch_ids', 'Selecione pelo menos uma unidade válida ou acesso geral.')
        ids = sorted({integer(v, 'branch_ids') for v in raw})
        # Key-share protects against deletion while access is assigned.
        rows = conn.execute('SELECT id FROM branches WHERE id=ANY(%s) FOR KEY SHARE', (ids,)).fetchall()
        if len(rows) != len(ids):
            invalid('branch_ids', 'Uma unidade selecionada não existe. Atualize a lista.')
    conn.execute('UPDATE users SET branch_restricted=%s WHERE id=%s', (ids is not None, uid))
    conn.execute('DELETE FROM user_branches WHERE user_id=%s', (uid,))
    for bid in ids or []:
        conn.execute('INSERT INTO user_branches(user_id,branch_id) VALUES(%s,%s)', (uid, bid))
