import os
import uuid
import pytest
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from werkzeug.security import generate_password_hash
from inventory import create_app
from migrate import migrate


@pytest.fixture(scope='session')
def test_url():
    admin_url=os.environ.get('YVI_TEST_ADMIN_URL')
    if not admin_url:
        pytest.fail('YVI_TEST_ADMIN_URL é obrigatório; a suíte não usa DATABASE_URL.')
    args=conninfo_to_dict(admin_url)
    if args.get('host') not in ('127.0.0.1','localhost'):
        pytest.fail('A suíte só cria bancos descartáveis em PostgreSQL local.')
    name='yvi_test_'+uuid.uuid4().hex
    with psycopg.connect(admin_url,autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    url=make_conninfo(admin_url,dbname=name)
    migrate(url)
    yield url
    with psycopg.connect(admin_url,autocommit=True) as conn:
        conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


@pytest.fixture
def app(test_url):
    with psycopg.connect(test_url) as conn:
        assert conn.info.dbname.startswith('yvi_test_')
        conn.execute('TRUNCATE audit_events,operation_keys,product_baselines,movements,products,users,categories,branches,login_limits RESTART IDENTITY CASCADE')
        conn.execute('TRUNCATE email_attempts,email_messages,email_events,email_oauth_states RESTART IDENTITY CASCADE')
        conn.execute('DELETE FROM email_settings')
        conn.execute('INSERT INTO email_settings(id) VALUES(1)')
        conn.execute("UPDATE role_permissions SET costs_view=CASE WHEN role='OPERATOR' THEN 0 ELSE 1 END,users_manage=CASE WHEN role='ADMIN' THEN 1 ELSE 0 END,version=1")
        conn.execute("INSERT INTO users(username,name,password_hash,role) VALUES('admin','Administrador',%s,'ADMIN'),('operator','Operador',%s,'OPERATOR')",(generate_password_hash('Test-password-123'),generate_password_hash('Test-password-123')))
        conn.execute("INSERT INTO categories(name) VALUES('Equipamentos')")
        conn.execute("INSERT INTO branches(name) VALUES('Central')")
        conn.execute("INSERT INTO products(code,name,category_id,unit,current_stock,min_stock,purchase_price,sale_price) VALUES('P01','Peça 1',1,'un',10,2,12.34,20.50)")
        conn.execute('INSERT INTO product_baselines(product_id,quantity) VALUES(1,10)')
        conn.execute('INSERT INTO product_stocks(product_id,branch_id,quantity,min_stock,opening_quantity) VALUES(1,1,10,2,10)')
    app=create_app({'DATABASE_URL':test_url,'SECRET_KEY':'test-secret-key-not-for-production-123456','TESTING':True,'APP_ENV':'development','DB_POOL_TIMEOUT':5})
    yield app
    app.extensions['db'].close()


def authenticated(app,uid=1):
    client=app.test_client()
    with client.session_transaction() as session:
        session['user_id']=uid;session['session_version']=1;session['csrf']='test-csrf'
    return client


@pytest.fixture
def client(app):
    return authenticated(app)


def headers(key=None):
    return {'X-CSRF-Token':'test-csrf','Idempotency-Key':key or str(uuid.uuid4())}


@pytest.fixture
def db(test_url):
    with psycopg.connect(test_url,row_factory=dict_row,autocommit=True) as conn:
        yield conn
