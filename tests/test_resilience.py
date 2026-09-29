import uuid
import pytest
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from pathlib import Path
from migrate import migrate
from conftest import headers
from inventory.validation import ApiError


def test_friendly_internal_error(client,monkeypatch):
    import inventory.api as routes
    def fail(*args,**kwargs):
        raise RuntimeError('private diagnostic never sent to browser')
    monkeypatch.setattr(routes,'product_query',fail)
    r=client.get('/api/products')
    assert r.status_code==500
    assert r.json['error']['code']=='INTERNAL_ERROR'
    assert 'private diagnostic' not in r.text
    assert r.json['error']['request_id']


def test_lock_timeout_is_friendly(client,test_url):
    with psycopg.connect(test_url) as blocker:
        blocker.execute('SELECT id FROM products WHERE id=1 FOR UPDATE')
        r=client.post('/api/movements',json={'product_id':1,'type':'SAIDA','quantity':1,'branch_id':1},headers=headers())
        assert r.status_code==409
        assert r.json['error']['code']=='BUSY'


def test_pool_failure_is_friendly(client,app,monkeypatch):
    from psycopg_pool import PoolTimeout
    def fail(*args,**kwargs):raise PoolTimeout('private details')
    monkeypatch.setattr(app.extensions['db'],'transaction',fail)
    r=client.get('/api/products')
    assert r.status_code==503
    assert r.json['error']['code']=='TEMPORARILY_UNAVAILABLE'


def test_sql_search_is_literal(client,db):
    r=client.get('/api/products',query_string={'search':"'; DROP TABLE products; --"})
    assert r.status_code==200 and r.json['items']==[]
    assert db.execute('SELECT count(*) AS n FROM products').fetchone()['n']==1


def test_legacy_migration_preserves_balances_and_orphan_id(test_url):
    name='yvi_test_legacy_'+uuid.uuid4().hex
    with psycopg.connect(test_url,autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    url=make_conninfo(test_url,dbname=name)
    try:
        with psycopg.connect(url) as conn:
            conn.execute((Path(__file__).parents[1]/'migrations/001_base.sql').read_text())
            conn.execute("INSERT INTO categories(name) VALUES('Legado')")
            conn.execute("INSERT INTO users(username,name,password_hash,role) VALUES('old','Pessoa','hash','ADMIN')")
            conn.execute("INSERT INTO products(code,name,category_id,current_stock) VALUES('OLD','Legada',1,12)")
            conn.execute('ALTER TABLE movements DROP CONSTRAINT movements_product_id_fkey')
            conn.execute("INSERT INTO deleted_products(id,name,code) VALUES(99,'Arquivada','DEL')")
            conn.execute("INSERT INTO movements(product_id,type,quantity,unit_price,total_price,user_id,timestamp) VALUES(99,'SAIDA',1,2,2,1,'2024-01-15 12:00:00')")
        with pytest.raises(RuntimeError):migrate(url)
        report=migrate(url,'America/Sao_Paulo',True)
        assert report['orphan_movement_products']==1
        migrate(url) # checksum and rerun must be harmless
        with psycopg.connect(url) as conn:
            assert conn.execute('SELECT quantity FROM product_baselines').fetchone()[0]==12
            m=conn.execute('SELECT legacy,legacy_product_id,product_id,product_name,extract(hour from timestamp AT TIME ZONE \'UTC\') FROM movements').fetchone()
            assert m==(True,99,None,'Arquivada',15)
            assert conn.execute('SELECT count(*) FROM schema_migrations').fetchone()[0]==3
    finally:
        with psycopg.connect(test_url,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
