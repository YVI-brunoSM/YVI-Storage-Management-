from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
import pytest
from conftest import authenticated, headers


@pytest.fixture
def network(client, db):
    db.execute("UPDATE branches SET name='Miramar' WHERE id=1")
    db.execute("INSERT INTO branches(name) VALUES('Bemais'),('Bessa')")
    body={'code':'MULTI','name':'Cabo de aço','category_id':1,'unit':'un','min_stock':0,
          'unit_stocks':[{'branch_id':1,'quantity':2,'min_stock':3},{'branch_id':2,'quantity':8,'min_stock':3},{'branch_id':3,'quantity':0,'min_stock':2}]}
    response=client.post('/api/products',json=body,headers=headers())
    assert response.status_code==201,response.json
    return response.json['id']


def balances(db,pid):
    return {r['branch_id']:r['quantity'] for r in db.execute('SELECT branch_id,quantity FROM product_stocks WHERE product_id=%s ORDER BY branch_id',(pid,))}


def test_sum_filter_and_local_shortage_even_with_sufficient_global_stock(client,db,network):
    pid=network
    whole=client.get(f'/api/products/{pid}').json
    assert Decimal(whole['current_stock'])==10
    assert whole['branch_ids']==[2,3,1] # alphabetical names
    assert whole['low_unit_count']==2
    assert client.get('/api/alerts?search=MULTI').json['total']==1
    assert client.get('/api/products?branch_id=2&status=ok&search=MULTI').json['total']==1
    assert client.get('/api/alerts?branch_id=2&search=MULTI').json['total']==0
    local=client.get('/api/products?branch_id=1&search=MULTI').json['items'][0]
    assert Decimal(local['current_stock'])==2 and len(local['unit_stocks'])==1
    assert Decimal(client.get('/api/dashboard/stats?branch_id=2').json['stock_by_unit'][0]['quantity'])==8
    csv=client.get('/api/export/csv?branch_id=1&search=MULTI').text
    assert 'Bemais' not in csv and 'Bessa' not in csv and 'Miramar' in csv


@pytest.mark.parametrize('role',['OPERATOR','MANAGER'])
def test_restricted_roles_never_receive_other_balances(app,client,db,network,role):
    db.execute('UPDATE users SET role=%s,branch_restricted=true WHERE id=2',(role,))
    db.execute('INSERT INTO user_branches(user_id,branch_id) VALUES(2,3)')
    user=authenticated(app,2)
    for path in (f'/api/products/{network}','/api/products?search=MULTI','/api/products/lookup?search=MULTI'):
        result=user.get(path)
        assert result.status_code==200
        item=result.json if 'items' not in result.json else result.json['items'][0]
        assert Decimal(item['current_stock'])==0
        assert len(item['unit_stocks'])==1 and item['unit_stocks'][0]['branch_id']==3
        assert 'Bemais' not in result.text and 'Miramar' not in result.text
    assert user.get('/api/products?branch_id=1').status_code==403
    assert user.get('/api/dashboard/stats').json['total_skus']==1
    # The zero balance is visible without an opening movement in Bessa.
    assert db.execute('SELECT count(*) AS n FROM movements WHERE product_id=%s AND branch_id=3',(network,)).fetchone()['n']==0
    request={'product_id':network,'branch_id':3,'type':'SAIDA','quantity':1}
    assert user.post('/api/movements',json=request,headers=headers()).status_code==409
    assert balances(db,network)=={1:Decimal(2),2:Decimal(8),3:Decimal(0)}


def test_multi_unit_user_sum_excludes_unassigned_units(app,client,db,network):
    db.execute('UPDATE users SET branch_restricted=true WHERE id=2')
    db.execute('INSERT INTO user_branches(user_id,branch_id) VALUES(2,1),(2,3)')
    user=authenticated(app,2)
    row=user.get(f'/api/products/{network}').json
    assert Decimal(row['current_stock'])==2 and set(row['branch_ids'])=={1,3}
    assert 'Bemais' not in str(row)


def test_entry_exit_and_reversal_change_only_selected_unit(client,db,network):
    data={'product_id':network,'branch_id':1,'type':'ENTRADA','quantity':3}
    movement=client.post('/api/movements',json=data,headers=headers())
    assert movement.status_code==201
    assert balances(db,network)=={1:Decimal(5),2:Decimal(8),3:Decimal(0)}
    reverse=client.post('/api/movements/'+str(movement.json['id'])+'/reverse',json={'reason':'Teste'},headers=headers())
    assert reverse.status_code==201
    assert balances(db,network)=={1:Decimal(2),2:Decimal(8),3:Decimal(0)}
    assert db.execute('SELECT current_stock FROM products WHERE id=%s',(network,)).fetchone()['current_stock']==10


def test_transfers_atomic_idempotent_and_preserve_total(client,db,network):
    data={'product_id':network,'source_id':2,'destination_id':1,'quantity':3,'notes':'Reposição Miramar'}
    key=headers()
    first=client.post('/api/transfers',json=data,headers=key)
    assert first.status_code==201,first.json
    assert client.post('/api/transfers',json=data,headers=key).status_code==200
    assert balances(db,network)=={1:Decimal(5),2:Decimal(5),3:Decimal(0)}
    assert db.execute('SELECT current_stock FROM products WHERE id=%s',(network,)).fetchone()['current_stock']==10
    logs=db.execute('SELECT * FROM movements WHERE transfer_id=%s ORDER BY id',(first.json['transfer_id'],)).fetchall()
    assert len(logs)==2 and {m['type'] for m in logs}=={'ENTRADA','SAIDA'}
    assert client.post('/api/movements/'+str(logs[0]['id'])+'/reverse',json={'reason':'Estorno parcial proibido'},headers=headers()).status_code==409
    assert client.post('/api/transfers',json={**data,'quantity':999},headers=headers()).status_code==409
    assert db.execute('SELECT count(*) AS n FROM stock_transfers').fetchone()['n']==1
    assert balances(db,network)[2]==5


def test_transfer_requires_access_to_both_units(app,client,db,network):
    db.execute("UPDATE users SET role='MANAGER',branch_restricted=true WHERE id=2")
    db.execute('INSERT INTO user_branches(user_id,branch_id) VALUES(2,1)')
    response=authenticated(app,2).post('/api/transfers',json={'product_id':network,'source_id':1,'destination_id':2,'quantity':1,'notes':'Não autorizado'},headers=headers())
    assert response.status_code==403
    assert not db.execute('SELECT 1 FROM stock_transfers').fetchone()


def test_unit_cannot_be_unlinked_with_balance_and_cannot_be_edited_directly(client,db,network):
    row=client.get(f'/api/products/{network}').json
    data={**row,'min_stock':0,'unit_stocks':[{'branch_id':3,'min_stock':2}]}
    assert client.put(f'/api/products/{network}',json=data,headers=headers()).status_code==409
    data['unit_stocks']=[{'branch_id':1,'quantity':500}]
    assert client.put(f'/api/products/{network}',json=data,headers=headers()).status_code==422
    assert balances(db,network)[1]==2


def test_unlink_zero_and_relink_preserves_historical_opening(client,db,network):
    client.post('/api/movements',json={'product_id':network,'branch_id':1,'type':'SAIDA','quantity':2},headers=headers())
    row=client.get(f'/api/products/{network}').json
    body={**row,'min_stock':0,'unit_stocks':[{'branch_id':2,'min_stock':3},{'branch_id':3,'min_stock':2}]}
    assert client.put(f'/api/products/{network}',json=body,headers=headers()).status_code==200
    assert client.get(f'/api/products?branch_id=1&search=MULTI').json['total']==0
    body['version']+=1
    body['unit_stocks'].append({'branch_id':1,'min_stock':3})
    assert client.put(f'/api/products/{network}',json=body,headers=headers()).status_code==200
    assert client.get(f'/api/products?branch_id=1&search=MULTI').json['total']==1


@pytest.mark.parametrize('units',[[],[{'branch_id':999}],[{'branch_id':1},{'branch_id':1}],[{'branch_id':True}],[{'branch_id':1,'quantity':'1.5'}]])
def test_invalid_unit_assignment_is_atomic(client,db,units):
    response=client.post('/api/products',json={'code':'BAD','name':'Inválida','category_id':1,'unit':'un','min_stock':0,'unit_stocks':units},headers=headers())
    assert response.status_code==422
    assert not db.execute("SELECT 1 FROM products WHERE code='BAD'").fetchone()


def test_pending_stock_must_be_allocated_once_without_inventing_history(client,db,network):
    pid=network
    # Mimic a migration: central stock retained, unit balances not yet known.
    db.execute('UPDATE products SET stock_allocation_pending=true,unallocated_stock=10 WHERE id=%s',(pid,))
    db.execute('UPDATE product_stocks SET quantity=0 WHERE product_id=%s',(pid,))
    previous=db.execute('SELECT count(*) AS n FROM movements WHERE product_id=%s',(pid,)).fetchone()['n']
    assert client.post('/api/movements',json={'product_id':pid,'branch_id':1,'type':'ENTRADA','quantity':1},headers=headers()).status_code==409
    row=client.get(f'/api/products/{pid}').json
    assert row['stock_allocation_pending'] and Decimal(row['unallocated_stock'])==10
    stats=client.get('/api/dashboard/stats').json
    assert stats['pending_count']==1
    export=client.get('/api/export/csv?search=MULTI').text
    assert 'A conferir' in export and 'Conferência' in export
    data={'version':row['version'],'reason':'Contagem conferida','unit_stocks':[{'branch_id':1,'quantity':6,'min_stock':3},{'branch_id':2,'quantity':3,'min_stock':2}]}
    assert client.post(f'/api/products/{pid}/allocate',json=data,headers=headers()).status_code==422
    data['unit_stocks'][1]['quantity']=4
    key=headers()
    assert client.post(f'/api/products/{pid}/allocate',json=data,headers=key).status_code==201
    assert client.post(f'/api/products/{pid}/allocate',json=data,headers=key).status_code==200
    assert db.execute('SELECT count(*) AS n FROM movements WHERE product_id=%s',(pid,)).fetchone()['n']==previous
    assert balances(db,pid)=={1:Decimal(6),2:Decimal(4),3:Decimal(0)}
    updated=client.get(f'/api/products/{pid}').json
    assert not updated['stock_allocation_pending'] and Decimal(updated['current_stock'])==10
    assert db.execute("SELECT count(*) AS n FROM audit_events WHERE action='stock_allocated'").fetchone()['n']==1


def test_simultaneous_local_withdrawals_do_not_use_other_unit_balance(app,client,db,network):
    barrier=Barrier(6)
    def take(_):
        user=authenticated(app)
        barrier.wait()
        return user.post('/api/movements',json={'product_id':network,'branch_id':1,'type':'SAIDA','quantity':1},headers=headers()).status_code
    with ThreadPoolExecutor(6) as pool:
        codes=list(pool.map(take,range(6)))
    assert codes.count(201)==2 and codes.count(409)==4
    assert balances(db,network)=={1:Decimal(0),2:Decimal(8),3:Decimal(0)}



def test_reconciliation_checks_local_ledger_and_global_sum(client,db,network):
    from manage import reconciliation
    checks,pending=reconciliation(db)
    assert not any(checks.values()) and pending==0
    db.execute('UPDATE product_stocks SET quantity=quantity+1 WHERE product_id=%s AND branch_id=1',(network,))
    checks,pending=reconciliation(db)
    assert len(checks['saldos por unidade'])==1
    assert len(checks['soma das unidades'])==1
    assert not checks['histórico geral']
