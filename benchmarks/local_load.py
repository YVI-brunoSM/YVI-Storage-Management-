from pathlib import Path
import os,sys,json,uuid,threading,time,statistics,logging
from concurrent.futures import ThreadPoolExecutor
import requests,psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
from inventory import create_app
from migrate import migrate
admin=os.environ['YVI_TEST_ADMIN_URL']
from psycopg.conninfo import conninfo_to_dict
if conninfo_to_dict(admin).get('host') not in ('127.0.0.1','localhost'):
 raise SystemExit('Use somente Postgres local descartável.')
name='yvi_test_load_'+uuid.uuid4().hex
with psycopg.connect(admin,autocommit=True) as conn:conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
url=make_conninfo(admin,dbname=name)
server=None;app=None
try:
 migrate(url)
 with psycopg.connect(url) as conn:
  pw=generate_password_hash('Local-load-test-123')
  conn.execute("INSERT INTO users(username,name,password_hash,role) SELECT 'load'||n,'Teste '||n,%s,'ADMIN' FROM generate_series(1,20) n",(pw,))
  conn.execute("INSERT INTO categories(name) VALUES('Carga')")
  conn.execute("INSERT INTO branches(name) VALUES('Carga')")
  conn.execute("INSERT INTO products(code,name,category_id,current_stock,min_stock,purchase_price,sale_price) SELECT 'LOAD'||n,'Peça de teste '||n,1,100,10,2.50,5 FROM generate_series(1,10000) n")
  conn.execute('INSERT INTO product_baselines(product_id,quantity) SELECT id,current_stock FROM products')
  conn.execute("INSERT INTO movements(product_id,type,quantity,unit_price,total_price,branch_id,user_id,legacy,product_name,product_code,product_unit) SELECT (n%10000)+1,'ENTRADA',1,2.50,2.50,1,1,true,'Histórico de teste','LEG','un' FROM generate_series(1,100000) n")
  conn.execute('ANALYZE')
 app=create_app({'DATABASE_URL':url,'SECRET_KEY':uuid.uuid4().hex+uuid.uuid4().hex,'APP_ENV':'development'})
 app.logger.disabled=True;logging.getLogger('werkzeug').disabled=True
 server=make_server('127.0.0.1',5090,app,threaded=True)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 sessions=[]
 for i in range(1,21):
  s=requests.Session();csrf=s.get('http://127.0.0.1:5090/api/csrf').json()['csrf_token']
  r=s.post('http://127.0.0.1:5090/api/login',json={'username':'load'+str(i),'password':'Local-load-test-123'},headers={'X-CSRF-Token':csrf});assert r.status_code==200
  s.headers['X-CSRF-Token']=r.json()['csrf_token'];sessions.append(s)
 durations=[];statuses={};lock=threading.Lock();barrier=threading.Barrier(20)
 def record(s,method,path,**kw):
  start=time.perf_counter();r=s.request(method,'http://127.0.0.1:5090'+path,timeout=15,**kw)
  with lock:
   durations.append((time.perf_counter()-start)*1000);statuses[str(r.status_code)]=statuses.get(str(r.status_code),0)+1
  return r
 def worker(i):
  s=sessions[i];barrier.wait();end=time.monotonic()+120;cycles=0
  while time.monotonic()<end:
   for typ in ('ENTRADA','SAIDA'):
    r=record(s,'POST','/api/movements',json={'product_id':1,'type':typ,'quantity':1,'branch_id':1},headers={'Idempotency-Key':str(uuid.uuid4())});assert r.status_code==201,r.status_code
   path=['/api/products?search=teste&page=2','/api/movements?limit=50','/api/dashboard/stats'][cycles%3]
   assert record(s,'GET',path).status_code==200
   cycles+=1;time.sleep(.3)
  return cycles
 start=time.perf_counter()
 with ThreadPoolExecutor(max_workers=20) as pool:cycles=list(pool.map(worker,range(20)))
 elapsed=time.perf_counter()-start
 with psycopg.connect(url) as conn:
  saldo=conn.execute('SELECT current_stock FROM products WHERE id=1').fetchone()[0]
  count=conn.execute('SELECT count(*) FROM movements WHERE NOT legacy').fetchone()[0]
  assert saldo==100 and count==sum(cycles)*2
 ordered=sorted(durations)
 result={'environment':'Local Windows, Python 3.12, PostgreSQL 17.6, HTTP threaded Werkzeug (not Railway/Gunicorn)','users':20,'products':10000,'legacy_movements':100000,'duration_seconds':round(elapsed,2),'requests':len(durations),'status_counts':statuses,'median_ms':round(statistics.median(durations),2),'p95_ms':round(ordered[int(len(ordered)*.95)],2),'max_ms':round(max(durations),2),'final_stock':str(saldo),'expected_stock':'100','new_movements':count,'pool':app.extensions['db'].get_pool().get_stats()}
 print(json.dumps(result,indent=2))
finally:
 if server:server.shutdown()
 if app:app.extensions['db'].close()
 with psycopg.connect(admin,autocommit=True) as conn:conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
