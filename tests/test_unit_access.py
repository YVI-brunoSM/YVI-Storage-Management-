import pytest
from conftest import authenticated, headers
from test_branch_filters import scoped_data


@pytest.fixture
def restricted(app, db, scoped_data):
    db.execute('UPDATE users SET branch_restricted=true WHERE id=2')
    db.execute('INSERT INTO user_branches(user_id,branch_id) VALUES(2,1)')
    return authenticated(app, 2)


@pytest.mark.parametrize('path', ['products', 'alerts', 'products/lookup', 'categories', 'branches', 'movements', 'dashboard/stats', 'export/csv'])
def test_unit_scope_cannot_be_bypassed_by_query(restricted, path):
    response = restricted.get('/api/'+path+'?branch_id=2')
    assert response.status_code == 403
    assert response.json['error']['code'] == 'BRANCH_FORBIDDEN'


def test_default_scope_detail_lookup_and_csv(restricted):
    assert [p['code'] for p in restricted.get('/api/products').json['items']] == ['P01']
    assert [b['name'] for b in restricted.get('/api/branches').json] == ['Centro']
    assert restricted.get('/api/dashboard/stats').json['total_skus'] == 1
    assert {m['branch_id'] for m in restricted.get('/api/movements').json['items']} == {1}
    assert [p['code'] for p in restricted.get('/api/products/lookup').json['items']] == ['P01']
    assert restricted.get('/api/products/2').status_code == 403
    assert restricted.get('/api/products/1').status_code == 200
    for target in ('products', 'movements'):
        text = restricted.get('/api/export/csv?target='+target).text
        assert 'N02' not in text and 'S03' not in text
    assert restricted.get('/api/admin/settings').status_code == 403
    assert restricted.get('/api/users').status_code == 403
    assert restricted.get('/api/notifications').status_code == 403


def test_multi_unit_union_and_individual_filter(restricted, db):
    db.execute('INSERT INTO user_branches(user_id,branch_id) VALUES(2,2)')
    assert {p['code'] for p in restricted.get('/api/products').json['items']} == {'P01','N02'}
    assert len(restricted.get('/api/branches').json) == 2
    assert restricted.get('/api/dashboard/stats').json['branches'] == 2
    assert restricted.get('/api/products?branch_id=2').json['items'][0]['code'] == 'N02'
    assert restricted.get('/api/products?branch_id=3').status_code == 403


def test_empty_restricted_scope_fails_closed(restricted, db):
    db.execute('DELETE FROM user_branches WHERE user_id=2')
    assert restricted.get('/api/products').json['total'] == 0
    assert restricted.get('/api/branches').json == []
    assert restricted.get('/api/movements').json['items'] == []


def test_mutations_enforce_units_and_protect_shared_catalog(restricted, db):
    db.execute("UPDATE role_permissions SET movements_in=1,products_manage=1,categories_manage=1,branches_manage=1 WHERE role='OPERATOR'")
    for bid,pid in ((2,1),(1,2)):
        response=restricted.post('/api/movements',json={'product_id':pid,'branch_id':bid,'type':'SAIDA','quantity':1},headers=headers())
        assert response.status_code == 403
    response=restricted.post('/api/movements',json={'product_id':1,'branch_id':1,'type':'SAIDA','quantity':1},headers=headers())
    assert response.status_code == 201
    assert restricted.post('/api/products',json={},headers=headers()).status_code == 403
    assert restricted.put('/api/products/2',json={},headers=headers()).status_code == 403
    assert restricted.delete('/api/products/2',json={},headers=headers()).status_code == 403
    for resource in ('branches','categories'):
        assert restricted.post('/api/'+resource,json={},headers=headers()).status_code == 403
        assert restricted.put('/api/'+resource+'/2',json={},headers=headers()).status_code == 403
        assert restricted.delete('/api/'+resource+'/2',json={},headers=headers()).status_code == 403


def test_admin_assigns_access_and_old_sessions_are_revoked(client, app, db, scoped_data):
    operator=authenticated(app,2)
    data={'username':'operator','name':'João','email':'joao@example.test','role':'MANAGER','password':'','version':1,'branch_ids':[1,2]}
    response=client.put('/api/users/2',json=data,headers=headers())
    assert response.status_code == 200
    assert operator.get('/api/me').status_code == 401
    row=db.execute('SELECT branch_restricted,session_version FROM users WHERE id=2').fetchone()
    assert row['branch_restricted'] and row['session_version']==2
    with operator.session_transaction() as session:
        session['user_id']=2;session['session_version']=2;session['csrf']='test-csrf'
    assert operator.get('/api/me').json['user']['branch_ids']==[1,2]
    assert operator.put('/api/users/2',json={**data,'branch_ids':None},headers=headers()).status_code==403
    user=next(u for u in client.get('/api/users').json if u['id']==2)
    assert user['branch_ids']==[1,2]
    # Older clients cannot accidentally remove the restriction by omitting the field.
    del data['branch_ids'];data['version']=2
    assert client.put('/api/users/2',json=data,headers=headers()).status_code==200
    assert db.execute('SELECT count(*) AS n FROM user_branches WHERE user_id=2').fetchone()['n']==2


@pytest.mark.parametrize('ids',[[],[999],[True],['1'],'1'])
def test_invalid_assignment_rolls_back(client, db, ids):
    response=client.post('/api/users',json={'username':'new-user','name':'Novo','role':'MANAGER','password':'Test-password-123','branch_ids':ids},headers=headers())
    assert response.status_code==422
    assert not db.execute("SELECT id FROM users WHERE username='new-user'").fetchone()


def test_admin_promotion_demotion_and_creation(client, db, scoped_data):
    response=client.post('/api/users',json={'username':'manager-new','name':'Novo','role':'MANAGER','password':'Test-password-123','branch_ids':[1,2]},headers=headers())
    assert response.status_code==201
    uid=response.json['id']
    data={'username':'manager-new','name':'Novo','role':'ADMIN','password':'','branch_ids':None,'version':1}
    assert client.put('/api/users/'+str(uid),json=data,headers=headers()).status_code==200
    data.update(role='MANAGER',branch_ids=[2],version=2)
    assert client.put('/api/users/'+str(uid),json=data,headers=headers()).status_code==200
    assert db.execute('SELECT branch_restricted FROM users WHERE id=%s',(uid,)).fetchone()['branch_restricted']
    assert client.get('/api/admin/settings').status_code==200


def test_restricted_cursor_cannot_reference_other_unit(restricted, db):
    outside=db.execute('SELECT id FROM movements WHERE branch_id=2').fetchone()['id']
    assert restricted.get('/api/movements?before_id='+str(outside)).json['items']==[]
