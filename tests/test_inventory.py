from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
import uuid
import pytest
import psycopg
from conftest import authenticated,headers

MOV={'product_id':1,'type':'SAIDA','quantity':'1','branch_id':1,'notes':'Teste'}


def test_20_concurrent_users_cannot_overdraw(app,db):
    for i in range(3,23):
        db.execute("INSERT INTO users(id,username,name,password_hash,role) VALUES(%s,%s,'Operador','unused','OPERATOR')",(i,'operator'+str(i)))
    barrier=Barrier(20)
    def run(uid):
        client=authenticated(app,uid)
        barrier.wait()
        return client.post('/api/movements',json=MOV,headers=headers()).status_code
    with ThreadPoolExecutor(20) as executor:
        codes=list(executor.map(run,range(3,23)))
    assert codes.count(201)==10 and codes.count(409)==10,codes
    assert db.execute('SELECT current_stock FROM products WHERE id=1').fetchone()['current_stock']==0
    assert db.execute('SELECT count(*) AS n FROM movements').fetchone()['n']==10


def test_two_seven_unit_withdrawals(app,db):
    barrier=Barrier(2)
    def run(_):
        c=authenticated(app);barrier.wait()
        return c.post('/api/movements',json={**MOV,'quantity':'7'},headers=headers()).status_code
    with ThreadPoolExecutor(2) as executor:
        assert sorted(executor.map(run,range(2)))==[201,409]
    assert db.execute('SELECT current_stock FROM products').fetchone()['current_stock']==3


def test_concurrent_idempotency(app,db):
    key=str(uuid.uuid4());barrier=Barrier(10)
    def run(_):
        c=authenticated(app);barrier.wait()
        return c.post('/api/movements',json=MOV,headers=headers(key)).status_code
    with ThreadPoolExecutor(10) as executor:
        codes=list(executor.map(run,range(10)))
    assert codes.count(201)==1 and codes.count(200)==9
    assert db.execute('SELECT count(*) AS n FROM movements').fetchone()['n']==1
    assert db.execute('SELECT current_stock FROM products').fetchone()['current_stock']==9


def test_retry_and_payload_mismatch(client,db):
    key=str(uuid.uuid4())
    first=client.post('/api/movements',json=MOV,headers=headers(key))
    assert first.status_code==201
    assert client.get('/api/operations/'+key).json['found']
    assert client.post('/api/movements',json=MOV,headers=headers(key)).json==first.json
    assert client.post('/api/movements',json={**MOV,'quantity':'2'},headers=headers(key)).status_code==409


def test_transaction_rollback_after_insert(client,app,db,monkeypatch):
    from inventory import api
    original=api.write_movement
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('Internal detail must not leak')
    monkeypatch.setattr(api,'write_movement',fail)
    res=client.post('/api/movements',json=MOV,headers=headers())
    assert res.status_code==500 and 'Internal detail' not in res.text
    assert db.execute('SELECT current_stock FROM products').fetchone()['current_stock']==10
    assert db.execute('SELECT count(*) AS n FROM movements').fetchone()['n']==0
    assert db.execute('SELECT count(*) AS n FROM operation_keys').fetchone()['n']==0


@pytest.mark.parametrize('value',['abc',None,True,-1,'NaN','Infinity',{},'1.5','0'])
def test_bad_quantities_are_friendly(client,value):
    res=client.post('/api/movements',json={**MOV,'quantity':value},headers=headers())
    assert res.status_code==422,res.json
    assert res.is_json and res.json['error']['request_id']


def test_csrf_auth_and_revocation(app,client,db):
    assert client.post('/api/movements',json=MOV).status_code==403
    assert app.test_client().get('/api/products').status_code==401
    db.execute('UPDATE users SET active=0 WHERE id=1')
    assert client.get('/api/products').status_code==401


def test_role_rechecked(app,client,db):
    db.execute("UPDATE users SET role='OPERATOR' WHERE id=1")
    assert client.get('/api/users').status_code==403
    assert 'purchase_price' not in client.get('/api/products').json['items'][0]


def test_costs_not_exposed_anywhere(app,db):
    client=authenticated(app,2)
    db.execute("UPDATE role_permissions SET reports_export=1 WHERE role='OPERATOR'")
    client.post('/api/movements',json=MOV,headers=headers())
    for path in ('/api/products','/api/movements','/api/dashboard/stats'):
        res=client.get(path)
        assert res.status_code==200
        for key in ('purchase_price','sale_price','unit_price','total_price','purchase_valuation','sale_valuation'):
            assert key not in res.text
    assert 'Preço unitário' not in client.get('/api/export/csv?target=movements').text


def test_zero_stock_alert(client,db):
    db.execute('UPDATE products SET current_stock=0 WHERE id=1')
    assert client.get('/api/alerts').json['total']==1


def test_optimistic_version_conflict(client):
    p=client.get('/api/products/1').json
    data={**p,'name':'Novo nome'}
    assert client.put('/api/products/1',json=data,headers=headers()).status_code==200
    assert client.put('/api/products/1',json=data,headers=headers()).status_code==409


def test_reversal_is_unique_and_immutable(client,db):
    mid=client.post('/api/movements',json=MOV,headers=headers()).json['id']
    res=client.post(f'/api/movements/{mid}/reverse',json={'reason':'Correção'},headers=headers())
    assert res.status_code==201,res.json
    assert db.execute('SELECT current_stock FROM products').fetchone()['current_stock']==10
    assert client.post(f'/api/movements/{mid}/reverse',json={'reason':'Novamente'},headers=headers()).status_code==409
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute('DELETE FROM movements WHERE id=%s',(mid,))


def test_initial_stock_is_audited(client,db):
    data={'code':'P02','name':'Nova','category_id':1,'unit':'m','current_stock':'1.250','min_stock':'0.500','purchase_price':'12.34','sale_price':'20.50','location':''}
    res=client.post('/api/products',json=data,headers=headers())
    assert res.status_code==201,res.json
    row=db.execute('SELECT * FROM movements WHERE product_id=%s',(res.json['id'],)).fetchone()
    assert row['quantity']==Decimal('1.250') and row['type']=='ENTRADA'
    assert row['total_price']==Decimal('15.43')


def test_users_update_does_not_produce_bad_sql(client,db):
    res=client.put('/api/users/2',json={'version':1,'username':'operator','name':'Novo operador','email':'','role':'OPERATOR','password':''},headers=headers())
    assert res.status_code==200,res.json
    assert db.execute('SELECT session_version FROM users WHERE id=2').fetchone()['session_version']==2


def test_permissions_save_is_atomic(client,db):
    rows=client.get('/api/permissions').json
    for row in rows:
        for k in ('dashboard','products_view','products_manage','costs_view','categories_manage','movements_in','movements_out','alerts_view','branches_manage','users_manage','reports_export'):
            row[k]=bool(row[k])
    rows[-1]['costs_view']='false'
    res=client.put('/api/permissions',json={'roles':rows},headers=headers())
    assert res.status_code==422
    assert all(r['version']==1 for r in db.execute('SELECT version FROM role_permissions'))


def test_last_admin_and_csv_formulas(client,db):
    data={'version':1,'username':'admin','name':'Admin','email':'','role':'OPERATOR','password':''}
    assert client.put('/api/users/1',json=data,headers=headers()).status_code==409
    db.execute('UPDATE products SET name=%s',('=1+1',))
    assert "'=1+1" in client.get('/api/export/csv').text


def test_socket_requires_identity_and_revokes(app,client,db):
    sio=app.extensions['realtime'].socket
    anon=sio.test_client(app,auth={'csrf':'x'})
    assert not anon.is_connected()
    socket=sio.test_client(app,flask_test_client=client,auth={'csrf':'test-csrf'})
    assert socket.is_connected()
    db.execute('UPDATE users SET session_version=2 WHERE id=1')
    socket.emit('heartbeat')
    assert not socket.is_connected()


def test_security_headers_and_unknown_error(client):
    res=client.get('/api/does-not-exist')
    assert res.status_code==404 and res.is_json
    assert "script-src 'self'" in res.headers['Content-Security-Policy']
    assert res.headers['X-Content-Type-Options']=='nosniff'


def test_login_and_logout(app,db):
    c=app.test_client();csrf=c.get('/api/csrf').json['csrf_token']
    res=c.post('/api/login',json={'username':'admin','password':'Test-password-123'},headers={'X-CSRF-Token':csrf})
    assert res.status_code==200
    assert c.get('/api/me').json['user']['role']=='ADMIN'
    assert c.post('/api/logout',headers={'X-CSRF-Token':res.json['csrf_token']}).status_code==200
    assert c.get('/api/me').status_code==401
