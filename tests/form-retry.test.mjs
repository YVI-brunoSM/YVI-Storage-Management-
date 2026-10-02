import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';

test('ambiguous save retries the original quantities and freezes dynamic unit fields',async()=>{
  const source=fs.readFileSync(new URL('../static/js/app.js',import.meta.url),'utf8');
  const code=source.slice(source.indexOf('function bindSave('),source.indexOf('function closeEditor('));
  const quantity={value:'1',disabled:false},unselected={disabled:true};
  let submitHandler,posts=0,seen=[];
  const element=()=>({disabled:false,append(){},addEventListener(){},setAttribute(){}});
  const nodes={'editor-close':element(),editor:{close(){}}};
  const ctx={fields:{},errors:{hidden:true,append(){}},form:{append(){},reportValidity(){return true;},
    querySelectorAll(selector){return selector==='input,select,textarea'?[quantity,unselected]:[];},
    addEventListener(name,handler){if(name==='submit')submitHandler=handler;}}};
  const context={crypto:webcrypto,FormData:class{*[Symbol.iterator](){yield ['quantity',quantity.value];}},
    $:name=>nodes[name],el:element,button:element,closeEditor(){},editorCleanup(){},toast(){},
    async loadPage(){},ctx,makeRequest:data=>({path:'/api/products',method:'POST',body:{unit_stocks:[{branch_id:1,quantity:data.quantity}]}}),
    api:async(path,options)=>{if(path.startsWith('/api/operations/'))return {found:false};
      assert.equal(quantity.disabled,true);seen.push(structuredClone(options));posts++;
      if(posts===1){quantity.value='99';throw Object.assign(new Error('Conexão interrompida'),{status:0});}
      return {message:'Salvo'};}};
  vm.createContext(context);vm.runInContext(code+'\nbindSave(ctx,makeRequest,"Salvar",true);',context);
  await submitHandler({preventDefault(){}});
  assert.equal(quantity.disabled,true);
  await submitHandler({preventDefault(){}});
  assert.equal(seen.length,2);
  assert.equal(seen[0].key,seen[1].key);
  assert.deepEqual(seen[1].body,seen[0].body);
  assert.equal(seen[1].body.unit_stocks[0].quantity,'1');
  assert.equal(quantity.disabled,false);
  assert.equal(unselected.disabled,true);
});
