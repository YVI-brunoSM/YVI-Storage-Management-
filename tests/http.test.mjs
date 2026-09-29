import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../static/js/http.js',import.meta.url),'utf8');
const {api,setCsrf}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

test('proxy HTML becomes a friendly API error',async()=>{
  globalThis.fetch=async()=>new Response('<h1>Fatal proxy error with private info</h1>',{status:502,headers:{'Content-Type':'text/html'}});
  await assert.rejects(api('/api/products'),e=>e.status===502&&!e.message.includes('private info'));
});
test('network failure is recoverable',async()=>{
  globalThis.fetch=async()=>{throw new TypeError('offline')};
  await assert.rejects(api('/api/products'),e=>e.code==='NETWORK_ERROR'&&e.status===0);
});
test('validation error preserves field and protocol',async()=>{
  globalThis.fetch=async()=>new Response(JSON.stringify({error:{code:'VALIDATION_ERROR',message:'Revise',fields:{quantity:'Inválido'},request_id:'abc'}}),{status:422,headers:{'Content-Type':'application/json'}});
  await assert.rejects(api('/api/products'),e=>e.fields.quantity==='Inválido'&&e.requestId==='abc');
});
test('mutations carry CSRF and the original idempotency key',async()=>{
  setCsrf('test-token');
  globalThis.fetch=async(path,options)=>{
    assert.equal(options.headers['X-CSRF-Token'],'test-token');
    assert.equal(options.headers['Idempotency-Key'],'same-operation');
    assert.equal(options.body,'{"quantity":"1.5"}');
    return new Response('{"id":1}',{headers:{'Content-Type':'application/json'}});
  };
  assert.deepEqual(await api('/api/movements',{method:'POST',body:{quantity:'1.5'},key:'same-operation'}),{id:1});
});
test('invalid JSON response never exposes a parse stack',async()=>{
  globalThis.fetch=async()=>new Response('{bad json',{headers:{'Content-Type':'application/json'}});
  await assert.rejects(api('/api/products'),e=>e.code==='NETWORK_ERROR'&&!e.message.includes('SyntaxError'));
});
