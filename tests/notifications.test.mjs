import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const httpSource=await readFile(new URL('../static/js/http.js',import.meta.url),'utf8');
const httpUrl='data:text/javascript;base64,'+Buffer.from(httpSource).toString('base64');
const source=(await readFile(new URL('../static/js/notifications.js',import.meta.url),'utf8')).replace("'./http.js'",JSON.stringify(httpUrl));
const {notificationsPage}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

class Element {
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.events={};}
  append(...children){this.children.push(...children);}
  setAttribute(){}
  addEventListener(event,callback){this.events[event]=callback;}
}
globalThis.document={createElement:tag=>new Element(tag)};
const text=node=>[node.textContent||'',...node.children.map(text)].join(' ');

test('failed notifications render their own page and retry without sending',async()=>{
  let requests=0,refreshes=0;
  globalThis.fetch=async(path,options)=>{
    requests++;assert.equal(path,'/api/notifications');assert.equal(options.method,'GET');
    return new Response(JSON.stringify({error:{code:'SCHEMA_NOT_READY',message:'Atualize o banco.',request_id:'safe-protocol'}}),{status:503,headers:{'Content-Type':'application/json'}});
  };
  const root=await notificationsPage({onRefresh:()=>refreshes++});
  assert.equal(root.dataset.loadError,'true');
  assert.match(text(root),/Notificações.*Atualize o banco.*safe-protocol.*Tentar novamente/);
  const retry=root.children[1].children.find(child=>child.tag==='button');
  retry.events.click();assert.equal(refreshes,1);assert.equal(requests,1);
});

test('expired login propagates to the session handler',async()=>{
  globalThis.fetch=async()=>new Response('{"error":{"code":"UNAUTHORIZED","message":"Entre novamente."}}',{status:401,headers:{'Content-Type':'application/json'}});
  await assert.rejects(notificationsPage({}),error=>error.status===401);
});

test('superseded navigation does not show an error page',async()=>{
  const controller=new AbortController();controller.abort();
  globalThis.fetch=async()=>{throw new DOMException('Aborted','AbortError');};
  await assert.rejects(notificationsPage({signal:controller.signal}),error=>error.name==='AbortError');
});
