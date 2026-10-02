import csv
import io
import pytest
from conftest import authenticated


@pytest.fixture
def scoped_data(db):
    db.execute("UPDATE branches SET name='Centro' WHERE id=1")
    db.execute("INSERT INTO branches(name) VALUES('Norte'),('Sem movimentos')")
    db.execute("INSERT INTO categories(name) VALUES('Categoria Norte'),('Sem vínculo')")
    db.execute("INSERT INTO products(code,name,category_id,unit,current_stock,min_stock,purchase_price,sale_price) VALUES('N02','Peça Norte',2,'un',0,2,100,200),('S03','Sem destino',3,'un',15,3,50,80)")
    db.execute('INSERT INTO product_stocks(product_id,branch_id,quantity,min_stock) VALUES(2,2,0,2)')
    db.execute('UPDATE products SET stock_allocation_pending=true,unallocated_stock=15 WHERE id=3')
    for pid, bid, uid, kind, quantity in [(1,1,1,'SAIDA',2),(1,1,1,'ENTRADA',1),(2,2,2,'SAIDA',4)]:
        db.execute("""INSERT INTO movements(product_id,branch_id,user_id,type,quantity,unit_price,total_price,legacy,product_name,product_code,product_unit,branch_name_snapshot,actor_name)
            SELECT p.id,%s,%s,%s,%s,10,10,true,p.name,p.code,p.unit,b.name,u.name
            FROM products p,branches b,users u WHERE p.id=%s AND b.id=%s AND u.id=%s""", (bid,uid,kind,quantity,pid,bid,uid))


def test_products_categories_and_users_filter_by_destination(client, scoped_data):
    data = client.get('/api/products?branch_id=1').json
    assert data['total'] == 1 and [p['code'] for p in data['items']] == ['P01']
    assert data['items'][0]['current_stock'] == '10.000'  # The central balance is unchanged.
    assert client.get('/api/products?branch_id=2').json['items'][0]['code'] == 'N02'
    assert client.get('/api/products?branch_id=3').json['total'] == 0
    assert client.get('/api/products?branch_id=1&search=Norte').json['total'] == 0
    assert client.get('/api/products?branch_id=1&category_id=2').json['total'] == 0
    assert client.get('/api/alerts?branch_id=1').json['items'] == []
    assert client.get('/api/alerts?branch_id=2').json['items'][0]['code'] == 'N02'
    cats = client.get('/api/categories?branch_id=1').json
    assert len(cats) == 1 and cats[0]['product_count'] == 1
    assert [u['username'] for u in client.get('/api/users?branch_id=1').json] == ['admin']
    assert [u['username'] for u in client.get('/api/users?branch_id=2').json] == ['operator']
    assert client.get('/api/users?branch_id=3').json == []
    assert [b['name'] for b in client.get('/api/branches?branch_id=1').json] == ['Centro']
    assert len(client.get('/api/branches').json) == 3


def test_filters_are_private_and_do_not_persist_on_server(app, scoped_data):
    first_user = authenticated(app, 1)
    second_user = authenticated(app, 2)
    assert first_user.get('/api/products?branch_id=1').json['items'][0]['code'] == 'P01'
    assert second_user.get('/api/products').json['total'] == 3
    assert second_user.get('/api/products?branch_id=2').json['items'][0]['code'] == 'N02'
    assert first_user.get('/api/products?branch_id=1').json['items'][0]['code'] == 'P01'
    assert first_user.get('/api/products').json['total'] == 3
    assert second_user.get('/api/products?branch_id=2').json['items'][0]['code'] == 'N02'
    assert second_user.get('/api/products').json['total'] == 3


def test_dashboard_filters_totals_recent_and_flow(client, scoped_data):
    stats = client.get('/api/dashboard/stats?branch_id=1').json
    assert stats['total_skus'] == 1 and stats['low_stock_count'] == 0 and stats['branches'] == 1
    assert stats['selected_branch'] == {'id':1,'name':'Centro'}
    assert len(stats['recent_movements']) == 2
    assert {m['branch_name_snapshot'] for m in stats['recent_movements']} == {'Centro'}
    assert stats['stock_by_unit'] == [{'unit':'un','quantity':'10.000'}]
    assert stats['purchase_valuation'] == '123.40000'
    assert {(r['type'],r['quantity']) for r in stats['movement_flow']} == {('SAIDA','2.000'),('ENTRADA','1.000')}
    empty = client.get('/api/dashboard/stats?branch_id=3').json
    assert empty['total_skus'] == 0 and empty['movement_flow'] == [] and empty['stock_by_unit'] == []
    assert client.get('/api/dashboard/stats').json['total_skus'] == 3


def test_movement_pagination_and_exports_preserve_filter(client, scoped_data):
    first = client.get('/api/movements?branch_id=1&limit=1').json
    assert first['next_cursor'] is not None and first['items'][0]['branch_id'] == 1
    second = client.get('/api/movements?branch_id=1&limit=1&before_id='+str(first['next_cursor'])).json
    assert len(second['items']) == 1 and second['items'][0]['branch_id'] == 1
    assert second['next_cursor'] is None
    movements = client.get('/api/export/csv?target=movements&branch_id=1').text
    assert 'Centro' in movements and 'Norte' not in movements
    products = client.get('/api/export/csv?target=products&branch_id=2').text
    assert 'N02' in products and 'P01' not in products and 'S03' not in products
    parsed = list(csv.reader(io.StringIO(products.lstrip('\ufeff')),delimiter=';'))
    assert len(parsed) == 2


def test_permissions_and_cost_hiding_survive_filter(app, scoped_data):
    client = authenticated(app, 2)
    data = client.get('/api/products?branch_id=2').json['items'][0]
    assert 'purchase_price' not in data and 'sale_price' not in data
    stats = client.get('/api/dashboard/stats?branch_id=2').json
    assert 'purchase_valuation' not in stats
    assert client.get('/api/users?branch_id=2').status_code == 403
    assert 'Custo' not in client.get('/api/export/csv?branch_id=2').text


@pytest.mark.parametrize('endpoint',['products','alerts','products/lookup','categories','branches','users','movements','dashboard/stats','export/csv'])
def test_invalid_filter_is_a_friendly_error(client, endpoint):
    for value, code in [('1 OR 1=1',422),('0',422),('-1',422),('99999',404)]:
        response = client.get('/api/'+endpoint, query_string={'branch_id':value})
        assert response.status_code == code and 'error' in response.json
