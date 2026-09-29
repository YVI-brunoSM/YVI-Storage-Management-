"""HTTP API. All authenticated operations run inside require()'s transaction."""
import csv
import hashlib
import hmac
import io
import json
import secrets
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID
from flask import Blueprint, g, jsonify, request, session, current_app, Response
from psycopg import sql
from psycopg.types.json import Jsonb
from werkzeug.security import check_password_hash, generate_password_hash
from .db import transaction
from .validation import ApiError, body, text, integer, number, choice, boolean, password, quantity_for_unit, page, invalid
from .security import require, csrf_token, identity, permitted, expect_version, PERMISSIONS, ROLES

api = Blueprint('api', __name__, url_prefix='/api')
UNITS = ('un','m','par','cx','kg')
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(24))


def audit(action, target=None, details=None):
    g.conn.execute('INSERT INTO audit_events(actor_id,action,target_id,details) VALUES(%s,%s,%s,%s)',
                   (g.user['id'], action, target, Jsonb(details or {})))


def public_user(user):
    return {k: v for k, v in user.items() if k not in ('session_version','password_hash','avatar')}


def product_public(row):
    result = dict(row)
    if not g.user['permissions']['costs_view']:
        result.pop('purchase_price', None)
        result.pop('sale_price', None)
    return result


def movement_public(row):
    result = dict(row)
    # Present the renamed brand without rewriting immutable historical records.
    if result.get('actor_name'):
        result['actor_name'] = re.sub(r'\bvibe\b', 'YVI', result['actor_name'], flags=re.IGNORECASE)
    if not g.user['permissions']['costs_view']:
        result.pop('unit_price', None)
        result.pop('total_price', None)
    return result


@api.get('/csrf')
def csrf():
    return jsonify({'csrf_token': csrf_token()})


@api.post('/login')
def login():
    data = body()
    username = text(data, 'username', True, 100).lower()
    raw_password = data.get('password')
    if not isinstance(raw_password, str) or not 1 <= len(raw_password) <= 128:
        invalid('password', 'Informe sua senha.')
    # Both buckets limit parallel hashing attempts. No account or IP stored in cleartext.
    values = ['ip:' + (request.remote_addr or 'unknown'), 'account:' + username]
    keys = [hmac.new(current_app.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest() for value in values]
    with transaction() as conn:
        counts = []
        for key in sorted(keys):
            counts.append(conn.execute("INSERT INTO login_limits(key,attempts) VALUES(%s,1) ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN login_limits.window_start<now()-interval '15 minutes' THEN 1 ELSE login_limits.attempts+1 END, window_start=CASE WHEN login_limits.window_start<now()-interval '15 minutes' THEN now() ELSE login_limits.window_start END RETURNING attempts", (key,)).fetchone()['attempts'])
    if max(counts) > 30:
        raise ApiError('RATE_LIMITED', 'Muitas tentativas. Aguarde 15 minutos antes de tentar novamente.', 429)
    with transaction() as conn:
        user = conn.execute('SELECT * FROM users WHERE lower(username)=%s AND active=1', (username,)).fetchone()
    if not check_password_hash(user['password_hash'] if user else DUMMY_HASH, raw_password) or not user:
        raise ApiError('INVALID_CREDENTIALS', 'Usuário ou senha incorretos.', 401)
    session.clear()
    session.permanent = True
    session['user_id'], session['session_version'] = user['id'], user['session_version']
    return jsonify({'message':'Bem-vindo.', 'csrf_token':csrf_token()})


@api.post('/logout')
def logout():
    uid = session.get('user_id')
    if uid:
        with transaction() as conn:
            conn.execute('UPDATE users SET session_version=session_version+1 WHERE id=%s', (uid,))
        current_app.extensions['realtime'].revoke(uid)
    session.clear()
    return jsonify({'message':'Sessões encerradas.', 'csrf_token':csrf_token()})


@api.get('/me')
@require()
def me():
    return jsonify({'user':public_user(g.user), 'csrf_token':csrf_token(), 'authenticated':True})


@api.get('/dashboard/stats')
@require('dashboard')
def dashboard():
    stats = g.conn.execute("SELECT count(*) AS total_skus,count(*) FILTER(WHERE current_stock<=min_stock) AS low_stock_count,count(*) FILTER(WHERE current_stock=0) AS out_count,sum(current_stock*purchase_price) AS purchase_valuation,sum(current_stock*sale_price) AS sale_valuation FROM products WHERE active=1").fetchone()
    if not g.user['permissions']['costs_view']:
        stats.pop('purchase_valuation'); stats.pop('sale_valuation')
    stats['stock_by_unit'] = g.conn.execute('SELECT unit,sum(current_stock) AS quantity FROM products WHERE active=1 GROUP BY unit ORDER BY unit').fetchall()
    stats['branches'] = g.conn.execute('SELECT count(*) AS n FROM branches').fetchone()['n']
    today = datetime.now(ZoneInfo('America/Sao_Paulo')).replace(hour=0, minute=0, second=0, microsecond=0)
    start, end = today - timedelta(days=6), today + timedelta(days=1)
    stats['flow_days'] = [(start + timedelta(days=i)).date().isoformat() for i in range(7)]
    stats['movement_flow'] = g.conn.execute("""
        SELECT (m.timestamp AT TIME ZONE 'America/Sao_Paulo')::date AS day,
               coalesce(m.product_unit,p.unit) AS unit, m.type, sum(m.quantity) AS quantity
        FROM movements m LEFT JOIN products p ON p.id=m.product_id
        WHERE m.timestamp >= %s AND m.timestamp < %s
        GROUP BY 1,2,3 ORDER BY 1,2,3
    """, (start,end)).fetchall()
    stats['recent_movements'] = [movement_public(m) for m in g.conn.execute('SELECT id,type,quantity,product_name,product_code,product_unit,actor_name,branch_name_snapshot,timestamp FROM movements ORDER BY timestamp DESC,id DESC LIMIT 5')]
    return jsonify(stats)


def product_query(alerts=False):
    conditions, params = ['p.active=1'], []
    search = text(request.args, 'search', maximum=100)
    if search:
        conditions.append('(p.name ILIKE %s OR p.code ILIKE %s OR p.location ILIKE %s)')
        params.extend(['%' + search + '%'] * 3)
    if request.args.get('category_id'):
        conditions.append('p.category_id=%s'); params.append(integer(request.args['category_id'],'category_id'))
    status = choice(request.args, 'status', ('','low','out','ok'), '')
    if alerts or status == 'low':
        conditions.append('p.current_stock<=p.min_stock')
    elif status == 'out':
        conditions.append('p.current_stock=0')
    elif status == 'ok':
        conditions.append('p.current_stock>p.min_stock')
    return ' AND '.join(conditions), params


def list_products(alerts=False):
    page_no, limit = page()
    where, params = product_query(alerts)
    total = g.conn.execute('SELECT count(*) AS n FROM products p WHERE ' + where, params).fetchone()['n']
    rows = g.conn.execute('SELECT p.*,c.name AS category_name FROM products p JOIN categories c ON c.id=p.category_id WHERE '+where+' ORDER BY p.code,p.id LIMIT %s OFFSET %s', (*params,limit,(page_no-1)*limit)).fetchall()
    return jsonify({'items':[product_public(p) for p in rows], 'total':total, 'page':page_no, 'limit':limit})


@api.get('/products')
@require('products_view')
def products():
    return list_products()


@api.get('/alerts')
@require('alerts_view')
def alerts():
    return list_products(True)


@api.get('/products/lookup')
@require()
def products_lookup():
    if not any(g.user['permissions'][p] for p in ('products_view','movements_in','movements_out')):
        permitted('products_view')
    where, params = product_query()
    rows = g.conn.execute('SELECT p.id,p.code,p.name,p.unit,p.current_stock FROM products p WHERE '+where+' ORDER BY p.code,p.id LIMIT 50',params).fetchall()
    return jsonify({'items': rows})


@api.get('/products/<int:pid>')
@require('products_view')
def product_detail(pid):
    row = g.conn.execute('SELECT p.*,c.name AS category_name FROM products p JOIN categories c ON c.id=p.category_id WHERE p.id=%s', (pid,)).fetchone()
    if not row:
        raise ApiError('NOT_FOUND','Peça não encontrada.',404)
    return jsonify(product_public(row))


def product_fields(data, old=None):
    values = dict(code=text(data,'code',True,50).upper() if old is None else old['code'], name=text(data,'name',True),
        category_id=integer(data.get('category_id'),'category_id'), unit=choice(data,'unit',UNITS),
        min_stock=number(data,'min_stock'), location=text(data,'location',maximum=200))
    quantity_for_unit(values['min_stock'], values['unit'], 'min_stock')
    if old and old['unit'] != values['unit']:
        raise ApiError('UNIT_IMMUTABLE','A unidade de medida não pode mudar após o cadastro. Crie uma nova peça.',409)
    for key in ('purchase_price','sale_price'):
        if g.user['permissions']['costs_view']:
            values[key] = number(data,key,places=2,default='0')
        elif key in data:
            raise ApiError('FORBIDDEN','Seu perfil não pode alterar valores financeiros.',403)
        else:
            values[key] = old[key] if old else Decimal(0)
    return values


def operation(data, scope, callback):
    key = request.headers.get('Idempotency-Key', '')
    try:
        UUID(key)
    except (ValueError, TypeError):
        raise ApiError('IDEMPOTENCY_REQUIRED','Identificação da operação ausente. Atualize a página.',422)
    payload_hash = hashlib.sha256(json.dumps({'scope':scope,'data':data},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    g.conn.execute('INSERT INTO operation_keys(user_id,key,payload_hash) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (g.user['id'],key,payload_hash))
    record = g.conn.execute('SELECT * FROM operation_keys WHERE user_id=%s AND key=%s FOR UPDATE', (g.user['id'],key)).fetchone()
    if record['payload_hash'] != payload_hash:
        raise ApiError('IDEMPOTENCY_CONFLICT','Este envio já foi usado com outros dados. Verifique o resultado antes de iniciar outra operação.',409)
    if record['result'] is not None:
        return jsonify(record['result'])
    result = callback()
    # Store exactly the JSON representation returned, including Decimal values as strings.
    result = json.loads(current_app.json.dumps(result))
    g.conn.execute('UPDATE operation_keys SET result=%s WHERE user_id=%s AND key=%s', (Jsonb(result),g.user['id'],key))
    return jsonify(result), 201


@api.get('/operations/<key>')
@require()
def operation_status(key):
    if len(key) > 40:
        invalid('key')
    row = g.conn.execute('SELECT result FROM operation_keys WHERE user_id=%s AND key=%s', (g.user['id'],key)).fetchone()
    return jsonify({'found':bool(row and row['result']), 'result':row['result'] if row else None})


def write_movement(product, mov_type, qty, branch_id, destination, notes, reversal_of=None):
    quantity_for_unit(qty,product['unit'])
    delta = qty if mov_type=='ENTRADA' else -qty
    new_stock = product['current_stock'] + delta
    if new_stock < 0:
        raise ApiError('STOCK_CONFLICT',f'O saldo mudou ou é insuficiente. Disponível: {product["current_stock"]} {product["unit"]}. Revise a quantidade.',409)
    price = product['purchase_price'] if mov_type=='ENTRADA' else product['sale_price']
    branch = g.conn.execute('SELECT name FROM branches WHERE id=%s', (branch_id,)).fetchone() if branch_id else None
    if branch_id and not branch:
        invalid('branch_id','Unidade não encontrada.')
    total = (price*qty).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    if total >= Decimal('1000000000000000'):
        invalid('quantity','Valor total da operação excede o limite.')
    row = g.conn.execute('INSERT INTO movements(product_id,type,quantity,unit_price,total_price,branch_id,destination_equipment,notes,user_id,product_code,product_name,product_unit,actor_name,branch_name_snapshot,stock_after,reversal_of) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
        (product['id'],mov_type,qty,price,total,branch_id,destination,notes,g.user['id'],product['code'],product['name'],product['unit'],g.user['name'],branch['name'] if branch else None,new_stock,reversal_of)).fetchone()
    g.conn.execute('UPDATE products SET current_stock=%s,version=version+1 WHERE id=%s', (new_stock,product['id']))
    return {'id':row['id'],'new_stock':new_stock,'message':'Movimentação registrada.'}


@api.post('/products')
@require('products_manage')
def create_product():
    data = body()
    fields = product_fields(data)
    initial = number(data,'current_stock',default=0)
    quantity_for_unit(initial, fields['unit'], 'current_stock')
    if initial:
        permitted('movements_in')
    def create():
        p = g.conn.execute('INSERT INTO products(code,name,category_id,unit,min_stock,purchase_price,sale_price,location) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *', tuple(fields[k] for k in ('code','name','category_id','unit','min_stock','purchase_price','sale_price','location'))).fetchone()
        g.conn.execute('INSERT INTO product_baselines(product_id,quantity) VALUES(%s,0)', (p['id'],))
        if initial:
            write_movement(p,'ENTRADA',initial,None,'Abertura','Saldo inicial registrado no cadastro.')
        audit('product_created',p['id'])
        return {'id':p['id'],'message':'Peça cadastrada.'}
    return operation(data,'product:create',create)


@api.put('/products/<int:pid>')
@require('products_manage')
def update_product(pid):
    data=body()
    old=g.conn.execute('SELECT * FROM products WHERE id=%s AND active=1 FOR UPDATE',(pid,)).fetchone()
    expect_version(old,data)
    values=product_fields(data,old)
    g.conn.execute('UPDATE products SET name=%s,category_id=%s,min_stock=%s,location=%s,purchase_price=%s,sale_price=%s,version=version+1 WHERE id=%s',(*(values[k] for k in ('name','category_id','min_stock','location','purchase_price','sale_price')),pid))
    audit('product_updated',pid,{'version_before':old['version']})
    return jsonify({'message':'Peça atualizada.'})


@api.delete('/products/<int:pid>')
@require('products_manage')
def archive_product(pid):
    old=g.conn.execute('SELECT * FROM products WHERE id=%s AND active=1 FOR UPDATE',(pid,)).fetchone()
    expect_version(old,body())
    if old['current_stock']:
        raise ApiError('NONZERO_STOCK','Registre uma saída justificada antes de arquivar uma peça com saldo.',409)
    g.conn.execute('UPDATE products SET active=0,version=version+1 WHERE id=%s',(pid,))
    audit('product_archived',pid)
    return jsonify({'message':'Peça arquivada. Histórico preservado.'})


@api.post('/movements')
@require()
def create_movement():
    data=body()
    mov_type=choice(data,'type',('ENTRADA','SAIDA'))
    permitted('movements_in' if mov_type=='ENTRADA' else 'movements_out')
    pid=integer(data.get('product_id'),'product_id')
    qty=number(data,'quantity',minimum=Decimal('.001'))
    branch=integer(data.get('branch_id'),'branch_id')
    destination=text(data,'destination_equipment',maximum=200)
    notes=text(data,'notes',maximum=1000)
    def create():
        product=g.conn.execute('SELECT * FROM products WHERE id=%s AND active=1 FOR UPDATE',(pid,)).fetchone()
        if not product:
            raise ApiError('NOT_FOUND','Peça não encontrada ou arquivada.',404)
        return write_movement(product,mov_type,qty,branch,destination,notes)
    return operation(data,'movement:create',create)


@api.post('/movements/<int:mid>/reverse')
@require(admin=True)
def reverse_movement(mid):
    data=body()
    reason=text(data,'reason',True,1000)
    def reverse():
        mov=g.conn.execute('SELECT * FROM movements WHERE id=%s',(mid,)).fetchone()
        if not mov:
            raise ApiError('NOT_FOUND','Movimentação não encontrada.',404)
        if mov['legacy'] or mov['reversal_of']:
            raise ApiError('REVERSAL_NOT_ALLOWED','Registro legado ou estorno não pode ser estornado automaticamente. Registre um ajuste justificado.',409)
        p=g.conn.execute('SELECT * FROM products WHERE id=%s FOR UPDATE',(mov['product_id'],)).fetchone()
        if not p or not p['active']:
            raise ApiError('ARCHIVED_PRODUCT','Peça arquivada; ajuste exige revisão do cadastro.',409)
        if g.conn.execute('SELECT id FROM movements WHERE reversal_of=%s',(mid,)).fetchone():
            raise ApiError('ALREADY_REVERSED','Movimentação já estornada.',409)
        # Financial reversal uses the historical unit price, never today's price.
        p['purchase_price']=p['sale_price']=mov['unit_price']
        result=write_movement(p,'SAIDA' if mov['type']=='ENTRADA' else 'ENTRADA',mov['quantity'],mov['branch_id'],mov['destination_equipment'],'Estorno #'+str(mid)+': '+reason,mid)
        audit('movement_reversed',mid,{'reversal_id':result['id'],'reason':reason})
        return result
    return operation(data,'movement:reverse:'+str(mid),reverse)


@api.route('/movements/<int:mid>', methods=['PUT','DELETE'])
@require(admin=True)
def immutable_movement(mid):
    raise ApiError('IMMUTABLE_HISTORY','O histórico é preservado. Use Estornar e registre o lançamento corrigido.',409)


def movement_query():
    conditions,params=['true'],[]
    for field in ('product_id','branch_id'):
        if request.args.get(field):
            conditions.append('m.'+field+'=%s');params.append(integer(request.args[field],field))
    for field,op in (('from','>='),('to','<')):
        if request.args.get(field):
            try:
                value=datetime.fromisoformat(request.args[field])
                if value.tzinfo is None:
                    value=value.replace(tzinfo=timezone.utc)
            except ValueError:
                invalid(field,'Data inválida.')
            conditions.append('m.timestamp'+op+'%s');params.append(value)
    if request.args.get('before_id'):
        conditions.append('(m.timestamp,m.id)<(SELECT timestamp,id FROM movements WHERE id=%s)')
        params.append(integer(request.args['before_id'],'before_id'))
    return ' AND '.join(conditions),params


@api.get('/movements')
@require('products_view')
def movements():
    _,limit=page()
    where,params=movement_query()
    rows=g.conn.execute('SELECT m.*,EXISTS(SELECT 1 FROM movements r WHERE r.reversal_of=m.id) AS reversed FROM movements m WHERE '+where+' ORDER BY m.timestamp DESC,m.id DESC LIMIT %s',(*params,limit+1)).fetchall()
    return jsonify({'items':[movement_public(r) for r in rows[:limit]],'next_cursor':rows[limit-1]['id'] if len(rows)>limit else None})


@api.get('/categories')
@require()
def categories():
    if not any(g.user['permissions'][p] for p in ('products_view','categories_manage','alerts_view','movements_in','movements_out')):
        permitted('products_view')
    return jsonify(g.conn.execute('SELECT c.*,count(p.id) AS product_count FROM categories c LEFT JOIN products p ON p.category_id=c.id AND p.active=1 GROUP BY c.id ORDER BY c.name').fetchall())


@api.get('/branches')
@require()
def branches():
    return jsonify(g.conn.execute('SELECT * FROM branches ORDER BY name').fetchall())


def catalog_write(table, fields, resource_id=None):
    data=body()
    values={field:text(data,field,field=='name',500 if field=='description' else 200) for field in fields}
    if table=='categories':
        values['icon']=choice(data,'icon',('folder','dumbbell','zap','file-text','droplet','sparkles','box','wrench','gear','cable','shield','truck'),'folder')
    if resource_id:
        old=g.conn.execute(sql.SQL('SELECT * FROM {} WHERE id=%s FOR UPDATE').format(sql.Identifier(table)),(resource_id,)).fetchone()
        expect_version(old,data)
        assignments=sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(k)) for k in values)
        g.conn.execute(sql.SQL('UPDATE {} SET {},version=version+1 WHERE id=%s').format(sql.Identifier(table),assignments),(*values.values(),resource_id))
    else:
        query=sql.SQL('INSERT INTO {} ({}) VALUES ({}) RETURNING id').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,values)),sql.SQL(',').join(sql.Placeholder() for _ in values))
        resource_id=g.conn.execute(query,tuple(values.values())).fetchone()['id']
    audit(table+'_saved',resource_id)
    return jsonify({'id':resource_id,'message':'Cadastro salvo.'})


@api.post('/categories')
@require('categories_manage')
def create_category():
    return catalog_write('categories',('name','description'))


@api.put('/categories/<int:cid>')
@require('categories_manage')
def update_category(cid):
    return catalog_write('categories',('name','description'),cid)


@api.post('/branches')
@require('branches_manage')
def create_branch():
    return catalog_write('branches',('name','address','phone'))


@api.put('/branches/<int:bid>')
@require('branches_manage')
def update_branch(bid):
    return catalog_write('branches',('name','address','phone'),bid)


def catalog_delete(table,rid):
    old=g.conn.execute(sql.SQL('SELECT * FROM {} WHERE id=%s FOR UPDATE').format(sql.Identifier(table)),(rid,)).fetchone()
    expect_version(old,body())
    g.conn.execute(sql.SQL('DELETE FROM {} WHERE id=%s').format(sql.Identifier(table)),(rid,))
    audit(table+'_deleted',rid)
    return jsonify({'message':'Registro excluído.'})


@api.delete('/categories/<int:cid>')
@require('categories_manage')
def delete_category(cid):
    return catalog_delete('categories',cid)


@api.delete('/branches/<int:bid>')
@require('branches_manage')
def delete_branch(bid):
    return catalog_delete('branches',bid)


@api.get('/users')
@require('users_manage',admin=True)
def users():
    return jsonify(g.conn.execute('SELECT id,username,name,email,role,active,version,created_at,avatar_revision,(avatar IS NOT NULL) AS has_avatar FROM users ORDER BY name').fetchall())


def user_fields(data, create=False):
    username=text(data,'username',True,100).lower()
    if not all(c.isalnum() or c in '._-' for c in username):
        invalid('username','Use letras, números, ponto, hífen ou sublinhado.')
    email=text(data,'email',maximum=200)
    if email and ('@' not in email or email.startswith('@') or email.endswith('@')):
        invalid('email','Informe um e-mail válido.')
    return username,text(data,'name',True),email,choice(data,'role',ROLES),password(data,required=create)


@api.post('/users')
@require('users_manage',admin=True)
def create_user():
    values=user_fields(body(),True)
    uid=g.conn.execute('INSERT INTO users(username,name,email,role,password_hash) VALUES(%s,%s,%s,%s,%s) RETURNING id',(*values[:4],generate_password_hash(values[4]))).fetchone()['id']
    audit('user_created',uid)
    return jsonify({'id':uid,'message':'Usuário criado.'}),201


def lock_administration():
    g.conn.execute('SELECT pg_advisory_xact_lock(791648231)')


def protect_last_admin(uid,role,active):
    if role!='ADMIN' or not active:
        other=g.conn.execute("SELECT id FROM users WHERE role='ADMIN' AND active=1 AND id<>%s LIMIT 1",(uid,)).fetchone()
        if not other:
            raise ApiError('LAST_ADMIN','Mantenha pelo menos um administrador ativo.',409)


@api.put('/users/<int:uid>')
@require('users_manage',admin=True)
def update_user(uid):
    data=body();values=user_fields(data)
    lock_administration()
    old=g.conn.execute('SELECT * FROM users WHERE id=%s FOR UPDATE',(uid,)).fetchone()
    expect_version(old,data)
    protect_last_admin(uid,values[3],old['active'])
    g.conn.execute('UPDATE users SET username=%s,name=%s,email=%s,role=%s,password_hash=%s,version=version+1,session_version=session_version+1 WHERE id=%s',(*values[:4],generate_password_hash(values[4]) if values[4] else old['password_hash'],uid))
    g.revoke_users=[uid]
    audit('user_updated',uid,{'role_before':old['role'],'role_after':values[3]})
    return jsonify({'message':'Usuário atualizado. Sessões anteriores encerradas.'})


@api.put('/users/<int:uid>/active')
@require('users_manage',admin=True)
def set_user_active(uid):
    data=body();active=boolean(data,'active')
    lock_administration()
    old=g.conn.execute('SELECT * FROM users WHERE id=%s FOR UPDATE',(uid,)).fetchone()
    expect_version(old,data)
    if uid==g.user['id'] and not active:
        raise ApiError('SELF_DISABLE','Você não pode desativar sua própria conta.',409)
    protect_last_admin(uid,old['role'],active)
    g.conn.execute('UPDATE users SET active=%s,version=version+1,session_version=session_version+1 WHERE id=%s',(active,uid))
    g.revoke_users=[uid]
    audit('user_active_changed',uid,{'active':bool(active)})
    return jsonify({'message':'Status atualizado. Histórico preservado.'})


@api.get('/permissions')
@require('users_manage',admin=True)
def permissions():
    return jsonify(g.conn.execute('SELECT * FROM role_permissions ORDER BY role').fetchall())


@api.put('/permissions')
@require('users_manage',admin=True)
def save_permissions():
    data=body()
    roles=data.get('roles')
    if not isinstance(roles,list) or len(roles)!=3 or any(not isinstance(r,dict) for r in roles) or {r.get('role') for r in roles}!=set(ROLES):
        invalid('roles','Envie os três perfis juntos.')
    lock_administration()
    for row in sorted(roles,key=lambda r:r['role']):
        old=g.conn.execute('SELECT * FROM role_permissions WHERE role=%s FOR UPDATE',(row['role'],)).fetchone()
        expect_version(old,row)
        values={key:boolean(row,key) for key in PERMISSIONS}
        if row['role']=='ADMIN' and not values['users_manage']:
            raise ApiError('ADMIN_LOCKOUT','O administrador precisa manter acesso à gestão de usuários.',409)
        if row['role']!='ADMIN' and values['users_manage']:
            invalid('users_manage','Gestão de usuários é exclusiva de administradores.')
        assigns=sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(k)) for k in values)
        g.conn.execute(sql.SQL('UPDATE role_permissions SET {},version=version+1 WHERE role=%s').format(assigns),(*values.values(),row['role']))
    audit('permissions_updated',details={'roles':list(ROLES)})
    return jsonify({'message':'Permissões salvas em uma única operação.'})


def safe_csv(value):
    value='' if value is None else str(value)
    if value.lstrip(' \t\r\n').startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')):
        return "'"+value
    return value


@api.get('/export/csv')
@require('reports_export')
def export():
    target=choice(request.args,'target',('products','movements'),'products')
    costs=g.user['permissions']['costs_view']
    if target=='products':
        where,params=product_query()
        rows=g.conn.execute('SELECT p.code,p.name,c.name AS category,p.unit,p.current_stock,p.min_stock,p.location,p.purchase_price,p.sale_price FROM products p JOIN categories c ON c.id=p.category_id WHERE '+where+' ORDER BY p.code LIMIT 10001',params).fetchall()
        columns=['code','name','category','unit','current_stock','min_stock','location']+(['purchase_price','sale_price'] if costs else [])
        headers=['SKU','Peça','Categoria','Unidade','Saldo','Mínimo','Localização']+(['Custo','Repasse'] if costs else [])
    else:
        where,params=movement_query()
        rows=[movement_public(row) for row in g.conn.execute('SELECT m.* FROM movements m WHERE '+where+' ORDER BY timestamp DESC,id DESC LIMIT 10001',params).fetchall()]
        columns=['timestamp','type','product_code','product_name','quantity','product_unit','branch_name_snapshot','destination_equipment','actor_name','notes','reversal_of','legacy']+(['unit_price','total_price'] if costs else [])
        headers=['Data UTC','Tipo','SKU','Peça','Quantidade','Medida','Unidade destino','Equipamento','Responsável','Observação','Estorno de','Legado']+(['Preço unitário','Total'] if costs else [])
    if len(rows)>10000:
        raise ApiError('EXPORT_LIMIT','A exportação excede 10.000 linhas. Restrinja os filtros ou o período.',422)
    output=io.StringIO(newline='');output.write('\ufeff')
    writer=csv.writer(output,delimiter=';');writer.writerow(headers)
    for row in rows:
        writer.writerow([safe_csv(row[column]) for column in columns])
    response=Response(output.getvalue(),content_type='text/csv; charset=utf-8')
    response.headers['Content-Disposition']=f'attachment; filename="yvi_{target}.csv"'
    return response


@api.put('/me/avatar')
@require()
def save_avatar():
    from .photos import thumbnail
    data = body()
    photo = thumbnail(data.get('image'))
    row = g.conn.execute('UPDATE users SET avatar=%s,avatar_revision=avatar_revision+1 WHERE id=%s RETURNING avatar_revision', (photo,g.user['id'])).fetchone()
    audit('profile.photo.updated', g.user['id'])
    return jsonify({'message':'Foto de perfil salva.', **row})


@api.delete('/me/avatar')
@require()
def remove_avatar():
    g.conn.execute('UPDATE users SET avatar=NULL,avatar_revision=avatar_revision+1 WHERE id=%s', (g.user['id'],))
    audit('profile.photo.removed', g.user['id'])
    return jsonify({'message':'Foto de perfil removida.'})


@api.get('/users/<int:user_id>/avatar')
@require()
def avatar(user_id):
    if user_id != g.user['id'] and (g.user['role'] != 'ADMIN' or not g.user['permissions']['users_manage']):
        raise ApiError('FORBIDDEN', 'Você não tem acesso a esta foto.', 403)
    row = g.conn.execute('SELECT avatar FROM users WHERE id=%s', (user_id,)).fetchone()
    if not row or row['avatar'] is None:
        raise ApiError('NOT_FOUND', 'Foto não cadastrada.', 404)
    return Response(bytes(row['avatar']), mimetype='image/jpeg')
