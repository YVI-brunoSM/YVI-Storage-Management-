from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from cryptography.fernet import Fernet
import pytest
from conftest import authenticated, headers
from inventory import mail_transport as transport
from inventory.db import transaction
from inventory.mail_worker import process_once, claim, render_message
from inventory.notifications import queue_event
REAL_GOOGLE_REQUEST = transport.google_request


def test_restricted_manager_does_not_receive_other_unit_stock(mail, client, db, monkeypatch):
    captured=mock_sender(monkeypatch)
    db.execute("INSERT INTO branches(name) VALUES('Outra unidade')")
    db.execute('INSERT INTO product_stocks(product_id,branch_id,quantity,min_stock,opening_quantity) VALUES(1,2,10,2,10)')
    db.execute('UPDATE products SET current_stock=20 WHERE id=1')
    db.execute('UPDATE users SET branch_restricted=true WHERE id=3')
    db.execute('INSERT INTO user_branches(user_id,branch_id) VALUES(3,1)')
    response=client.post('/api/movements',json={'product_id':1,'branch_id':2,'type':'SAIDA','quantity':8},headers=headers())
    assert response.status_code==201
    run_once(mail);run_once(mail)
    assert len(captured)==1 and captured[0]['To']=='admin@example.test'
    assert db.execute("SELECT status FROM email_messages WHERE recipient='manager@example.test'").fetchone()['status']=='cancelled'


def test_summary_is_filtered_for_each_recipient(mail, client, db, monkeypatch):
    captured=mock_sender(monkeypatch)
    db.execute("INSERT INTO branches(name) VALUES('Outra unidade')")
    db.execute('INSERT INTO product_stocks(product_id,branch_id,quantity,min_stock,opening_quantity) VALUES(1,2,10,2,10)')
    db.execute('UPDATE products SET current_stock=20 WHERE id=1')
    db.execute("UPDATE products SET current_stock=0 WHERE id=1")
    db.execute("UPDATE product_stocks SET quantity=0 WHERE product_id=1")
    db.execute("INSERT INTO products(code,name,category_id,unit,current_stock,min_stock) VALUES('OUTSIDE','Peça de outra unidade',1,'un',0,2)")
    db.execute('INSERT INTO product_stocks(product_id,branch_id,min_stock) VALUES(2,2,2)')
    for pid,bid in ((1,1),(2,2)):
        db.execute("INSERT INTO movements(product_id,branch_id,user_id,type,quantity,unit_price,total_price,legacy) VALUES(%s,%s,1,'SAIDA',1,0,0,true)",(pid,bid))
    db.execute('UPDATE users SET branch_restricted=true WHERE id=3')
    db.execute('INSERT INTO user_branches(user_id,branch_id) VALUES(3,1)')
    assert client.post('/api/notifications/summary',json={},headers=headers()).status_code==202
    run_once(mail);run_once(mail)
    messages={m['To']:m.get_body(preferencelist=('plain',)).get_content() for m in captured}
    assert 'OUTSIDE' in messages['admin@example.test']
    assert 'P01' in messages['manager@example.test'] and 'OUTSIDE' not in messages['manager@example.test']
    assert 'Outra unidade' not in messages['manager@example.test']
    assert 'Central' in messages['manager@example.test']


def test_unit_permission_is_rechecked_after_token_renewal(mail, client, db, monkeypatch):
    captured=mock_sender(monkeypatch)
    db.execute("INSERT INTO branches(name) VALUES('Outra unidade')")
    db.execute('INSERT INTO product_stocks(product_id,branch_id,quantity,min_stock,opening_quantity) VALUES(1,2,10,2,10)')
    db.execute('UPDATE products SET current_stock=20 WHERE id=1')
    assert client.post('/api/movements',json={'product_id':1,'branch_id':2,'type':'SAIDA','quantity':8},headers=headers()).status_code==201
    run_once(mail)
    def narrow_access(refresh):
        db.execute('UPDATE users SET branch_restricted=true WHERE id=3')
        db.execute('INSERT INTO user_branches(user_id,branch_id) VALUES(3,1)')
        return 'test-access'
    monkeypatch.setattr(transport,'access_token',narrow_access)
    run_once(mail)
    assert len(captured)==1


@pytest.fixture(autouse=True)
def no_google_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Real Google network is forbidden in this suite')
    monkeypatch.setattr(transport, 'google_request', blocked)


@pytest.fixture
def mail(app, db):
    app.config.update(APP_BASE_URL='https://inventory.example.test', GOOGLE_CLIENT_ID='test-client', GOOGLE_CLIENT_SECRET='test-secret',
        EMAIL_TOKEN_KEY=Fernet.generate_key().decode(), GMAIL_SENDER='sender@example.test', EMAIL_REPLY_TO='owner@example.test',
        EMAIL_ENABLED=True, EMAIL_DAILY_LIMIT=100)
    db.execute("UPDATE users SET email=CASE WHEN id=1 THEN 'admin@example.test' ELSE 'operator@example.test' END")
    db.execute("INSERT INTO users(username,name,password_hash,role,email) VALUES('manager','Gerente','unused','MANAGER','manager@example.test')")
    with app.app_context():
        cipher = transport.encrypt('refresh-secret')
    db.execute("UPDATE email_settings SET enabled=true,sender='sender@example.test',client_id='test-client',refresh_token_cipher=%s,connection_status='connected',connection_revision=1,test_accepted_at=now() WHERE id=1", (cipher,))
    return app


def move(client, quantity, kind='SAIDA', key=None):
    return client.post('/api/movements', json={'product_id':1,'type':kind,'quantity':quantity,'branch_id':1,'notes':'Teste'}, headers=headers(key))


def single_test(app):
    with app.app_context(), transaction() as conn:
        queue_event(conn, 'test-event', 'test', {'at':datetime.now(timezone.utc).isoformat(),'actor':'Equipe'}, test=True)


def run_once(app):
    with app.app_context():
        return process_once()


def mock_sender(monkeypatch):
    captured = []
    monkeypatch.setattr(transport, 'access_token', lambda refresh: 'access-token')
    def send(token, message):
        captured.append(message)
        return 'gmail-message'
    monkeypatch.setattr(transport, 'send_message', send)
    return captured


def test_disabled_by_default_and_admin_only(client, app, db):
    info=client.get('/api/notifications').json
    assert info['enabled'] is False and info['configured'] is False
    assert move(client, 8).status_code == 201
    assert db.execute('SELECT count(*) AS n FROM email_events').fetchone()['n'] == 0
    operator=authenticated(app,2)
    assert operator.get('/api/notifications').status_code == 403
    assert operator.post('/api/notifications/connect',json={},headers=headers()).status_code == 403
    assert client.post('/api/notifications/settings',json={'enabled':True}).status_code == 403
    assert app.test_client().get('/api/notifications').status_code == 401


def test_stock_transitions_recovery_and_no_repeat(mail, client, db):
    for quantity,kind in [(8,'SAIDA'),(1,'SAIDA'),(1,'SAIDA'),(1,'ENTRADA'),(10,'ENTRADA'),(9,'SAIDA')]:
        assert move(client,quantity,kind).status_code == 201
    events=db.execute('SELECT payload FROM email_events ORDER BY id').fetchall()
    assert [e['payload']['state'] for e in events] == ['low','out','low']
    recipients=db.execute('SELECT recipient FROM email_messages').fetchall()
    assert len(recipients)==6
    assert {r['recipient'] for r in recipients}=={'admin@example.test','manager@example.test'}
    assert events[0]['payload']['branch']=='Central'
    assert 'purchase_price' not in events[0]['payload']


def test_repeated_operation_and_concurrent_depletion_only_one_event(mail, app, db):
    def call(_):
        return move(authenticated(app),10).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(call,range(2)))==[201,409]
    assert db.execute('SELECT count(*) AS n FROM email_events').fetchone()['n']==1
    assert db.execute('SELECT count(*) AS n FROM email_messages').fetchone()['n']==2


def test_idempotency_and_transaction_rollback(mail, client, db, monkeypatch):
    import uuid
    from inventory import notifications
    key=str(uuid.uuid4())
    assert move(client,8,key=key).status_code==201
    assert move(client,8,key=key).status_code in (200,201)
    assert db.execute('SELECT count(*) AS n FROM email_events').fetchone()['n']==1
    original=notifications.stock_event
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('test rollback')
    monkeypatch.setattr(notifications,'stock_event',fail)
    assert move(client,2).status_code==500
    assert db.execute('SELECT current_stock FROM products WHERE id=1').fetchone()['current_stock']==2
    assert db.execute('SELECT count(*) AS n FROM email_events').fetchone()['n']==1


def test_minimum_change_creation_and_reversal(mail, client, db):
    values={'name':'Peça 1','category_id':1,'unit':'un','min_stock':12,'location':'A','purchase_price':12,'sale_price':20,'version':1,'unit_stocks':[{'branch_id':1,'min_stock':12}]}
    assert client.put('/api/products/1',json=values,headers=headers()).status_code==200
    new={'code':'NEW','name':'Nova','category_id':1,'unit':'un','min_stock':3,'current_stock':1,'purchase_price':0,'sale_price':0}
    new['unit_stocks']=[{'branch_id':1,'quantity':new.get('current_stock',0),'min_stock':new.get('min_stock',0)}]
    assert client.post('/api/products',json=new,headers=headers()).status_code==201
    new.update(code='ZERO',current_stock=0)
    new['unit_stocks']=[{'branch_id':1,'quantity':new.get('current_stock',0),'min_stock':new.get('min_stock',0)}]
    assert client.post('/api/products',json=new,headers=headers()).status_code==201
    entry=move(client,5,'ENTRADA').json
    assert client.post('/api/movements/'+str(entry['id'])+'/reverse',json={'reason':'Teste de estorno'},headers=headers()).status_code==201
    rows=db.execute('SELECT payload FROM email_events ORDER BY id').fetchall()
    assert len(rows)==4
    assert [r['payload']['state'] for r in rows]==['low','low','out','low']
    assert rows[-1]['payload']['operation']=='Estorno · Saída'


def test_same_address_dedup_and_invalid_recipients(mail, client, db):
    db.execute("UPDATE users SET email='ADMIN@example.test' WHERE username='manager'")
    assert move(client,8).status_code==201
    assert db.execute('SELECT count(*) AS n FROM email_messages').fetchone()['n']==1
    db.execute("UPDATE users SET email='bad' WHERE role IN ('ADMIN','MANAGER')")
    assert move(client,2).status_code==201
    assert db.execute('SELECT count(*) AS n FROM email_messages').fetchone()['n']==1


def test_sender_test_enables_configuration_without_secrets(mail, client, db, monkeypatch):
    db.execute('UPDATE email_settings SET enabled=false,test_accepted_at=NULL')
    assert client.post('/api/notifications/settings',json={'enabled':True},headers=headers()).status_code==409
    assert client.post('/api/notifications/test',json={'to':'ignored@example.test'},headers=headers()).status_code==202
    assert client.post('/api/notifications/test',json={},headers=headers()).status_code==429
    captured=mock_sender(monkeypatch)
    assert run_once(mail)
    assert captured[0]['To']=='owner@example.test'
    assert client.post('/api/notifications/settings',json={'enabled':True},headers=headers()).status_code==200
    response=client.get('/api/notifications')
    assert response.json['connected'] and response.json['test_accepted_at']
    assert 'refresh-secret' not in response.text and 'test-secret' not in response.text
    assert 'refresh_token_cipher' not in response.text


def test_pending_recipient_revoked_before_send(mail, client, db, monkeypatch):
    move(client,8)
    db.execute("UPDATE users SET active=0 WHERE id=1")
    captured=mock_sender(monkeypatch)
    run_once(mail)
    run_once(mail)
    assert len(captured)==1 and captured[0]['To']=='manager@example.test'
    assert db.execute("SELECT status FROM email_messages WHERE recipient='admin@example.test'").fetchone()['status']=='cancelled'


@pytest.mark.parametrize('failure,status',[
    (transport.MailFailure('google_limit',retry=True),'pending'),
    (transport.MailFailure('google_connection',uncertain=True),'uncertain'),
    (transport.MailFailure('google_rejected'),'failed'),
    (transport.MailFailure('authorization_expired',reconnect=True),'failed'),
])
def test_delivery_failures_are_durable(mail, db, monkeypatch, failure, status):
    single_test(mail)
    mock_sender(monkeypatch)
    def fail(*args): raise failure
    monkeypatch.setattr(transport,'send_message',fail)
    assert run_once(mail)
    row=db.execute('SELECT * FROM email_messages').fetchone()
    assert row['status']==status and row['last_error']==failure.code
    if failure.reconnect:
        assert db.execute('SELECT connection_status FROM email_settings').fetchone()['connection_status']=='needs_reconnect'
    assert run_once(mail) is False


def test_ambiguous_retry_requires_review_and_interrupted_worker_is_not_retried(mail, client, db):
    single_test(mail)
    db.execute("UPDATE email_messages SET status='processing',claimed_at=now()-interval '6 minutes'")
    assert run_once(mail) is False
    assert db.execute('SELECT status FROM email_messages').fetchone()['status']=='uncertain'
    assert client.post('/api/notifications/1/retry',json={},headers=headers()).status_code==409
    assert client.post('/api/notifications/1/retry',json={'reviewed_sent_folder':True},headers=headers()).status_code==200


def test_atomic_claim_budget_and_master_switch(mail, db):
    single_test(mail)
    def reserve(_):
        with mail.app_context(): return claim()
    with ThreadPoolExecutor(max_workers=2) as executor:
        result=list(executor.map(reserve,range(2)))
    assert sum(item is not None for item in result)==1
    mail.config['EMAIL_DAILY_LIMIT']=1
    db.execute("UPDATE email_messages SET status='pending'")
    assert reserve(0) is None
    mail.config['EMAIL_DAILY_LIMIT']=100
    mail.config['EMAIL_ENABLED']=False
    assert reserve(0) is None


def test_pause_pending_and_disconnect_remove_local_credentials(mail, client, db, monkeypatch):
    move(client,8)
    assert client.post('/api/notifications/settings',json={'enabled':False},headers=headers()).status_code==200
    assert run_once(mail) is False
    assert client.post('/api/notifications/disconnect',json={},headers=headers()).status_code==200
    row=db.execute('SELECT * FROM email_settings').fetchone()
    assert row['refresh_token_cipher'] is None and not row['enabled']
    assert {r['status'] for r in db.execute('SELECT status FROM email_messages')}=={'cancelled'}


def test_oauth_pkce_single_use_encryption_and_replay(mail, client, db, monkeypatch):
    response=client.post('/api/notifications/connect',json={},headers=headers())
    query=parse_qs(urlsplit(response.json['url']).query)
    assert query['redirect_uri']==['https://inventory.example.test/integrations/gmail/callback']
    assert query['code_challenge_method']==['S256'] and query['access_type']==['offline']
    assert set(query['scope'][0].split())=={transport.SEND_SCOPE,'openid','email'}
    calls=[]
    def exchange(code, verifier):
        assert len(verifier)>40
        calls.append(code)
        return 'new-refresh-token','sender@example.test'
    monkeypatch.setattr(transport,'exchange_code',exchange)
    path='/integrations/gmail/callback?state='+query['state'][0]+'&code=secret-code'
    assert 'Gmail conectado' in client.get(path).text
    row=db.execute('SELECT * FROM email_settings').fetchone()
    assert row['refresh_token_cipher']!='new-refresh-token'
    assert not row['enabled'] and row['test_accepted_at'] is None
    with mail.app_context(): assert transport.decrypt(row['refresh_token_cipher'])=='new-refresh-token'
    repeat=client.get(path)
    assert 'Conexão pendente' in repeat.text and len(calls)==1
    assert repeat.headers['Referrer-Policy']=='no-referrer'
    assert 'secret-code' not in repeat.text


def test_oauth_rejects_other_session_and_expiry(mail, client, db, monkeypatch):
    response=client.post('/api/notifications/connect',json={},headers=headers())
    state=parse_qs(urlsplit(response.json['url']).query)['state'][0]
    other=authenticated(mail)
    assert 'Conexão pendente' in other.get('/integrations/gmail/callback?state='+state+'&code=x').text
    db.execute("UPDATE email_oauth_states SET expires_at=now()-interval '1 minute'")
    assert 'expirou' in client.get('/integrations/gmail/callback?state='+state+'&code=x').text


def test_google_account_must_match_and_scope_must_include_send(mail, monkeypatch):
    def provider(url,**kwargs):
        if url==transport.TOKEN_URL: return {'access_token':'access','refresh_token':'refresh','scope':transport.SEND_SCOPE}
        return {'email':'another@example.test','email_verified':True}
    monkeypatch.setattr(transport,'google_request',provider)
    with mail.app_context(), pytest.raises(transport.MailFailure,match='wrong_sender'):
        transport.exchange_code('code','verifier')
    monkeypatch.setattr(transport,'google_request',lambda *a,**kw:{'access_token':'a','refresh_token':'b','scope':'openid email'})
    with mail.app_context(), pytest.raises(transport.MailFailure,match='permission_missing'):
        transport.exchange_code('code','verifier')


def test_summary_and_mime_escape_content(mail, client, db):
    assert client.post('/api/notifications/summary',json={},headers=headers()).status_code==202
    assert client.post('/api/notifications/summary',json={},headers=headers()).status_code==429
    db.execute("UPDATE products SET name='<script>alert(1)</script>'")
    move(client,8)
    row=db.execute("SELECT m.*,e.kind,e.payload FROM email_messages m JOIN email_events e ON e.id=m.event_id WHERE e.kind='stock' LIMIT 1").fetchone()
    with mail.app_context(): msg=render_message(row,'sender@example.test')
    assert '&lt;script&gt;' in msg.get_body(preferencelist=('html',)).get_content()
    assert '<script>' not in msg.get_body(preferencelist=('html',)).get_content()
    assert 'purchase_price' not in msg.as_string()
    assert msg['Reply-To']=='owner@example.test'
    movement = db.execute('SELECT timestamp FROM movements ORDER BY id DESC LIMIT 1').fetchone()
    assert datetime.fromisoformat(row['payload']['at']) == movement['timestamp']


def test_manager_can_receive_but_cannot_manage(mail):
    client=authenticated(mail,3)
    assert client.get('/api/notifications').status_code==403
    assert client.post('/api/notifications/settings',json={'enabled':False},headers=headers()).status_code==403


def test_recipient_revoked_while_refreshing_is_not_sent(mail, client, db, monkeypatch):
    move(client,8)
    captured=mock_sender(monkeypatch)
    def refresh(token):
        db.execute('UPDATE users SET active=0 WHERE id=1')
        return 'access'
    monkeypatch.setattr(transport,'access_token',refresh)
    run_once(mail)
    assert captured==[]
    assert db.execute('SELECT status FROM email_messages ORDER BY id LIMIT 1').fetchone()['status']=='cancelled'


@pytest.mark.parametrize('status,sending,code,uncertain,retry',[
    (500,True,'google_unavailable',True,False),
    (500,False,'google_unavailable',False,True),
    (429,True,'google_limit',False,True),
    (401,True,'authorization_expired',False,False),
    (400,True,'google_rejected',False,False),
])
def test_http_error_classification_never_repeats_ambiguous_sends(monkeypatch,status,sending,code,uncertain,retry):
    from urllib.error import HTTPError
    from io import BytesIO
    class Opener:
        def open(self,*args,**kwargs):
            raise HTTPError(transport.SEND_URL,status,'redacted',{'Retry-After':'7200'},BytesIO(b'{"error":{"message":"private content"}}'))
    monkeypatch.setattr(transport,'build_opener',lambda *args:Opener())
    with pytest.raises(transport.MailFailure) as error:
        REAL_GOOGLE_REQUEST(transport.SEND_URL,payload={'raw':'fake'},sending=sending)
    assert (error.value.code,error.value.uncertain,error.value.retry)==(code,uncertain,retry)
    assert 'private content' not in str(error.value)
    if status==429: assert error.value.retry_after==7200


def test_network_timeout_is_uncertain_only_after_send(monkeypatch):
    class Opener:
        def open(self,*args,**kwargs): raise TimeoutError()
    monkeypatch.setattr(transport,'build_opener',lambda *args:Opener())
    for sending in (False,True):
        with pytest.raises(transport.MailFailure) as error:
            REAL_GOOGLE_REQUEST(transport.SEND_URL,payload={'raw':'fake'},sending=sending)
        assert error.value.uncertain==sending and error.value.retry!=sending
