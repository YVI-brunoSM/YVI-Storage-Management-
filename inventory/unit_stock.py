"""Per-academy stock and explicit opening-stock allocation."""
from decimal import Decimal
from flask import g
from .validation import ApiError, integer, number, invalid, quantity_for_unit
from .branch_access import check_branch


def selections(data, product, old=False):
    raw = data.get('unit_stocks')
    if raw is None and old:
        return None
    if not isinstance(raw, list) or not 1 <= len(raw) <= 1000:
        invalid('unit_stocks', 'Selecione pelo menos uma unidade para a peça.')
    rows, seen = [], set()
    for row in raw:
        if not isinstance(row, dict):
            invalid('unit_stocks')
        bid = integer(row.get('branch_id'), 'unit_stocks')
        if bid in seen:
            invalid('unit_stocks', 'Uma unidade foi selecionada mais de uma vez.')
        seen.add(bid)
        check_branch(bid)
        try:
            minimum = number(row, 'min_stock', default=product['min_stock'])
            initial = number(row, 'quantity', default=0)
        except ApiError as error:
            invalid('unit_stocks', 'Revise os saldos e mínimos das unidades. '+next(iter(error.fields.values()), error.message))
        quantity_for_unit(minimum, product['unit'], 'unit_stocks')
        quantity_for_unit(initial, product['unit'], 'unit_stocks')
        if old and initial:
            invalid('unit_stocks', 'Altere saldos por entradas, saídas ou conferência inicial.')
        rows.append({'branch_id': bid, 'min_stock': minimum, 'quantity': initial})
    existing = g.conn.execute('SELECT id FROM branches WHERE id=ANY(%s) ORDER BY id FOR KEY SHARE', (sorted(seen),)).fetchall()
    if len(existing) != len(seen):
        invalid('unit_stocks', 'Uma unidade não existe. Atualize a lista.')
    if sum((r['quantity'] for r in rows), Decimal(0)) >= Decimal('100000000000'):
        invalid('unit_stocks', 'O saldo geral excede o limite permitido.')
    return rows


def save_links(product, rows, notify_new=False):
    if rows is None:
        return
    ids = [r['branch_id'] for r in rows]
    old = {r['branch_id']: r for r in g.conn.execute('SELECT * FROM product_stocks WHERE product_id=%s ORDER BY branch_id FOR UPDATE', (product['id'],))}
    if any(row['quantity'] for bid, row in old.items() if bid not in ids):
        raise ApiError('UNIT_HAS_STOCK', 'Transfira ou registre a saída do saldo antes de desvincular uma unidade.', 409)
    g.conn.execute('UPDATE product_stocks SET enabled=false WHERE product_id=%s AND NOT(branch_id=ANY(%s))', (product['id'], ids))
    from .notifications import stock_event
    for row in sorted(rows, key=lambda r: r['branch_id']):
        bid = row['branch_id']
        g.conn.execute('INSERT INTO product_stocks(product_id,branch_id,min_stock) VALUES(%s,%s,%s) ON CONFLICT(product_id,branch_id) DO UPDATE SET enabled=true,min_stock=EXCLUDED.min_stock,version=product_stocks.version+1', (product['id'], bid, row['min_stock']))
        if (bid in old or notify_new) and not product['stock_allocation_pending']:
            name = g.conn.execute('SELECT name FROM branches WHERE id=%s', (bid,)).fetchone()['name']
            previous_row = old.get(bid, {'quantity': Decimal(0), 'min_stock': row['min_stock'], 'version': 0})
            previous = {**product, 'current_stock': previous_row['quantity'], 'min_stock': previous_row['min_stock'], 'location': name}
            stock_event(g.conn, previous, {**previous, 'min_stock': row['min_stock']},
                        {'branch_id': bid, 'branch': name, 'actor': g.user['name'], 'operation': 'Alteração do mínimo da unidade'},
                        f'unit-minimum:{product["id"]}:{bid}:{previous_row["version"]+1}', initial=bid not in old)


def lock_stock(product, bid):
    if product['stock_allocation_pending']:
        raise ApiError('STOCK_ALLOCATION_PENDING', 'O saldo antigo desta peça precisa ser distribuído por um administrador antes de movimentar.', 409)
    row = g.conn.execute('SELECT * FROM product_stocks WHERE product_id=%s AND branch_id=%s AND enabled FOR UPDATE', (product['id'], bid)).fetchone()
    if not row:
        raise ApiError('PRODUCT_UNIT_NOT_LINKED', 'Esta peça não está vinculada à unidade selecionada. Revise o cadastro.', 409)
    return row
