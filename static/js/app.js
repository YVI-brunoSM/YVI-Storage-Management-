import {categoryLabel, iconPicker, pieceCombobox, avatarNode} from './widgets.js';
import {api, ApiError, refreshCsrf, setCsrf, getCsrf} from './http.js';
import {notificationsPage} from './notifications.js';

const $ = id => document.getElementById(id);
const state = {user:null, view:'dashboard', branch:'', branchOptions:[], page:1, search:'', category:'', status:'', cursor:null, cursors:[], socket:null, controller:null, sequence:0, metadata:{categories:[],branches:[]}};
const labels = {dashboard:'Visão geral',products:'Peças e Estoque',movements:'Movimentações',alerts:'Reposição',categories:'Categorias',branches:'Unidades da rede',users:'Usuários e acessos',notifications:'Notificações',reports:'Relatórios',settings:'Configurações'};
const permission = {dashboard:'dashboard',products:'products_view',movements:'products_view',alerts:'alerts_view',categories:'categories_manage',branches:'branches_manage',users:'users_manage',reports:'reports_export',notifications:'users_manage',settings:'users_manage'};
const permissions = {dashboard:'Visão geral',products_view:'Consultar peças e histórico',products_manage:'Gerenciar peças',costs_view:'Consultar e alterar custos',categories_manage:'Gerenciar categorias',movements_in:'Registrar entradas',movements_out:'Registrar saídas',alerts_view:'Consultar reposição',branches_manage:'Gerenciar unidades',users_manage:'Gerenciar usuários e permissões',reports_export:'Exportar relatórios'};
let metadataPromise, toastTimer, reloadTimer, editorCleanup = () => {};
const can = p => !!state.user?.permissions[p]&&!(state.user.branch_restricted&&['products_manage','categories_manage','branches_manage'].includes(p));
const canView = view => can(permission[view])&&(!['settings','users','notifications'].includes(view)||state.user?.role==='ADMIN');
const num = value => new Intl.NumberFormat('pt-BR',{maximumFractionDigits:3}).format(Number(value));
const money = value => new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(Number(value || 0));
const date = value => value ? new Date(value).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'}) : '—';

function el(tag, text, cls) { const node=document.createElement(tag); if(text !== undefined) node.textContent=text; if(cls)node.className=cls; return node; }
function button(label, action, cls='button') { const b=el('button',label,cls); b.type='button'; b.addEventListener('click',action); return b; }
function actions(...items) { const row=el('div',undefined,'actions'); row.append(...items.filter(Boolean)); return row; }
function heading(title,subtitle='',...buttons) { const row=el('div',undefined,'page-heading'); const text=el('div'); text.append(el('p','Estoque central · YVI','eyebrow'),el('h1',title)); if(subtitle)text.append(el('p',subtitle,'muted')); row.append(text,actions(...buttons)); return row; }
function cell(content,cls) { const td=el('td',undefined,cls); if(content instanceof Node)td.append(content);else td.textContent=content??'—'; return td; }
function pieceName(p) { const n=el('div'); n.append(el('strong',p.name),el('span',p.code,'sub'));return n; }
function badge(p) { const stock=Number(p.current_stock),min=Number(p.min_stock);return el('span',stock===0?'Esgotado':stock<=min?'Repor':'Disponível','badge stock-status '+(stock===0?'out':stock<=min?'low':'available')); }
function table(headers,rows,cls='') { const wrap=el('div',undefined,'table-wrap');const t=el('table',undefined,cls);const tr=el('tr');headers.forEach(h=>{const th=el('th',h);th.scope='col';tr.append(th);});const head=el('thead');head.append(tr);const body=el('tbody');if(!rows.length){const td=cell('Nenhum registro encontrado.','empty');td.colSpan=headers.length;const r=el('tr');r.append(td);body.append(r);}else rows.forEach(r=>{const tr=el('tr');tr.append(...r);body.append(tr);});t.append(head,body);wrap.append(t);return wrap; }
function field(label,name,value='',type='text',options) { const wrap=el('label',label);let input;if(options){input=el('select');options.forEach(o=>{const option=el('option',o.label);option.value=o.value;input.append(option);});}else input=el(type==='textarea'?'textarea':'input');if(!options&&type!=='textarea')input.type=type;input.name=name;input.id='field-'+name;input.value=value??'';wrap.append(input);return {wrap,input}; }
function select(label,name,value,options) { return field(label,name,value,'select',options); }
function toast(message) { $('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,5500); }
function online(ok) { $('connection').textContent=ok?'Dados sincronizados · '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'}):'Conexão interrompida · dados podem estar desatualizados';$('connection').classList.toggle('offline',!ok); }
function pageError(error) { if(error.name==='AbortError')return; if(error.status===401){showLogin(error.message);return;}online(false);const box=$('page-status');box.replaceChildren(el('span',error.message+(error.requestId?' Protocolo: '+error.requestId:'')),button('Tentar novamente',()=>loadPage(),'button small'));box.className='notice error';box.hidden=false; }
function showLogin(message='') { state.controller?.abort();state.sequence++;state.user=null;state.branch='';state.branchOptions=[];state.socket?.disconnect();state.socket=null;state.metadata={categories:[],branches:[]};metadataPromise=null;$('workspace').hidden=true;$('login-panel').hidden=false;$('logout').hidden=true;$('user-name').textContent='';$('profile').hidden=true;$('page').replaceChildren();if($('editor').open){editorCleanup();$('editor').close();}$('editor-content').replaceChildren();if(message){$('login-error').textContent=message;$('login-error').hidden=false;} }
async function metadata() { if(!metadataPromise)metadataPromise=Promise.all([api('/api/categories'),api('/api/branches')]).then(([categories,branches])=>(state.metadata={categories,branches})).catch(e=>{metadataPromise=null;throw e;});return metadataPromise; }
function applyUser(user) { state.user=user;$('user-name').textContent=user.name;$('profile').hidden=false;$('profile').replaceChildren(avatarNode(user),el('span','Meu perfil')); $('logout').hidden=false;$('login-panel').hidden=true;$('workspace').hidden=false;document.querySelectorAll('[data-permission]').forEach(b=>b.hidden=!canView(b.dataset.view)); }
function navigate(view) { if(!canView(view))return;Object.assign(state,{view,page:1,search:'',category:'',status:'',cursor:null,cursors:[]});history.replaceState(null,'','#'+view);loadPage(); }

async function loadPage(silent=false) {
  if(!state.user)return;
  state.controller?.abort();const controller=new AbortController();state.controller=controller;const sequence=++state.sequence;
  if(!silent)$('page').setAttribute('aria-busy','true');
  if($('page').dataset.view!==state.view){$('page').dataset.view=state.view;$('page').replaceChildren(heading(labels[state.view],'Carregando…'));$('page-status').hidden=true;}
  document.querySelectorAll('[data-view]').forEach(b=>{if(b.dataset.view===state.view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  try {
    await refreshBranchFilter(controller.signal);
    if(sequence!==state.sequence)return;
    const node=await ({dashboard:dashboardPage,products:()=>productsPage(false),alerts:()=>productsPage(true),movements:movementPage,categories:()=>catalogPage('categories'),branches:()=>catalogPage('branches'),users:usersPage,reports:reportsPage,settings:settingsPage,notifications:()=>notificationsPage({signal:controller.signal,cursor:state.cursor,onRefresh:()=>loadPage(),onPage:cursor=>{state.cursor=cursor;return loadPage();}})}[state.view])();
    if(sequence!==state.sequence)return;
    const focused=document.activeElement;const focusName=focused?.dataset.filter;const start=focused?.selectionStart;
    $('page').replaceChildren(node);$('page-status').hidden=true;online(node.dataset.loadError!=='true');
    if(focusName){const replacement=$('page').querySelector(`[data-filter="${focusName}"]`);replacement?.focus();if(replacement?.type==='search'&&start!==null)replacement.setSelectionRange(start,start);}
  } catch(error) { if(sequence===state.sequence)pageError(error); }
  finally {if(sequence===state.sequence)$('page').setAttribute('aria-busy','false');}
}
function branchPath(path) { const url=new URL(path,location.origin);if(state.branch)url.searchParams.set('branch_id',state.branch);return url.pathname+url.search; }
function fetchPage(path) { return api(branchPath(path),{signal:state.controller.signal}); }
async function refreshBranchFilter(signal) {
  $('branch-filter').closest('.unit-toolbar').hidden=['notifications','settings'].includes(state.view);
  if(['notifications','settings'].includes(state.view))return;
  const rows=await api('/api/branches',{signal});
  if(signal.aborted)return;
  state.branchOptions=rows;
  if(state.branch&&!rows.some(row=>String(row.id)===state.branch)){state.branch='';state.page=1;state.cursor=null;state.cursors=[];toast('A unidade selecionada não está mais disponível. Exibindo as unidades autorizadas.');}
  const picker=$('branch-filter');
  const restricted=state.user.branch_restricted;const single=restricted&&rows.length===1;
  if(single)state.branch=String(rows[0].id);picker.disabled=restricted&&rows.length<=1;
  const options=[...(single?[]:[{id:'',name:restricted?'Todas as unidades autorizadas':'Todas as academias'}]),...rows];
  if(JSON.stringify(options)!==picker.dataset.options){picker.replaceChildren(...options.map(row=>{const option=el('option',row.name);option.value=row.id;return option;}));picker.dataset.options=JSON.stringify(options);}
  picker.value=state.branch;
  picker.closest('.unit-toolbar').classList.toggle('filtered',!!state.branch);
  const scope={dashboard:'Movimentações desta unidade e saldo central das peças relacionadas.',products:'Peças com movimentações para esta unidade. Saldo e mínimo referem-se ao estoque central.',alerts:'Reposição no estoque central das peças com movimentações para esta unidade.',movements:'Entradas e saídas registradas para esta unidade.',categories:'Categorias das peças com movimentações para esta unidade.',branches:'Cadastro da unidade selecionada.',users:'Usuários com acesso atribuído ou movimentações para esta unidade.',reports:'Exportações limitadas à unidade selecionada. Saldos referem-se ao estoque central.'};
  const branch=rows.find(row=>String(row.id)===state.branch);
  $('branch-scope').textContent=branch?branch.name+' · '+scope[state.view]:(restricted?'Acesso restrito às unidades definidas pelo administrador. Saldos referem-se ao estoque central.':'Exibindo informações de todas as unidades.');
}
function changeBranch(value) { state.branch=value;state.page=1;state.cursor=null;state.cursors=[];$('page').replaceChildren(el('p','Carregando informações da unidade…','notice'));loadPage(); }
$('branch-filter').addEventListener('change',event=>changeBranch(event.target.value));
const entryButtons = () => [can('movements_out')&&button('↗ Registrar saída',()=>movementEditor('SAIDA'),'button movement-out'),can('movements_in')&&button('+ Registrar entrada',()=>movementEditor('ENTRADA'),'button movement-in')];

function svgNode(tag,attrs={},text) {
  const node=document.createElementNS('http://www.w3.org/2000/svg',tag);
  Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,String(value)));
  if(text!==undefined)node.textContent=text;
  return node;
}
function shelfDrawing() {
  const svg=svgNode('svg',{viewBox:'0 0 220 210',fill:'none',stroke:'currentColor','stroke-width':1.2,'stroke-linejoin':'round'});
  svg.append(svgNode('path',{d:'M28 198V12M190 198V12M22 55H196M22 100H196M22 145H196M22 190H196M28 198H21M190 198H197'}));
  const boxes=[[40,27,49,28],[112,20,60,35],[39,68,65,32],[123,76,48,24],[43,115,43,30],[108,111,65,34],[40,159,58,31],[119,163,51,27]];
  boxes.forEach(([x,y,w,h])=>{
    svg.append(svgNode('rect',{x,y,width:w,height:h,rx:1}));
    svg.append(svgNode('path',{d:`M${x} ${y+7}H${x+w}M${x+w/2} ${y}V${y+7}M${x+w/2-4} ${y+7}V${y+14}H${x+w/2+4}V${y+7}`}));
  });
  return svg;
}
function flowChart(stats) {
  const section=el('section',undefined,'flow-chart');section.setAttribute('aria-labelledby','flow-title');
  const heading=el('div',undefined,'section-heading');const copy=el('div');const title=el('h2','Entradas e saídas');title.id='flow-title';
  copy.append(title,el('p','Últimos 7 dias · horário de Brasília · inclui estornos','muted'));
  const rows=(stats.movement_flow||[]).filter(r=>r.unit);const units=['un','m','par','cx','kg'].filter(u=>rows.some(r=>r.unit===u));if(!units.length)units.push('un');
  const unitLabels={un:'Unidades',m:'Metros',par:'Pares',cx:'Caixas',kg:'Quilos'};
  const measure=select('Medida','flow-unit',units[0],units.map(u=>({value:u,label:unitLabels[u]||u})));
  heading.append(copy,measure.wrap);section.append(heading);
  const body=el('div');section.append(body);
  const draw=()=>{
    const unit=measure.input.value;const days=(stats.flow_days||[]).map(day=>({day,incoming:0,outgoing:0}));
    rows.filter(r=>r.unit===unit).forEach(r=>{const day=days.find(d=>d.day===r.day);if(day)day[r.type==='ENTRADA'?'incoming':'outgoing']+=Number(r.quantity);});
    const incoming=days.reduce((n,d)=>n+d.incoming,0),outgoing=days.reduce((n,d)=>n+d.outgoing,0);
    body.replaceChildren();
    const legend=el('div',undefined,'flow-legend');legend.append(el('span',`Entradas · ${num(incoming)} ${unit}`,'flow-in'),el('span',`Saídas · ${num(outgoing)} ${unit}`,'flow-out'));body.append(legend);
    const max=Math.max(1,...days.flatMap(d=>[d.incoming,d.outgoing]));const ceiling=max<=5?Math.ceil(max):Math.ceil(max/5)*5;
    const svg=svgNode('svg',{viewBox:'0 0 760 244',role:'img','aria-label':`Entradas e saídas nos últimos sete dias: ${num(incoming)} ${unit} entraram e ${num(outgoing)} ${unit} saíram. Valores diários disponíveis abaixo.`});
    for(let i=0;i<=4;i++){const y=190-i*40;svg.append(svgNode('line',{x1:58,y1:y,x2:745,y2:y,class:'flow-grid'}),svgNode('text',{x:48,y:y+4,'text-anchor':'end',class:'flow-label'},num(ceiling*i/4)));}
    const shortDate=day=>day.slice(8)+'/'+day.slice(5,7);
    days.forEach((d,i)=>{
      const x=105+i*96;
      for(const [key,dx,cls,label] of [['incoming',-23,'flow-bar-in','Entradas'],['outgoing',3,'flow-bar-out','Saídas']]){
        const h=d[key]/ceiling*160;const rect=svgNode('rect',{x:x+dx,y:190-h,width:20,height:h,rx:2,class:cls});rect.append(svgNode('title',{},`${shortDate(d.day)} · ${label}: ${num(d[key])} ${unit}`));svg.append(rect);
      }
      svg.append(svgNode('text',{x,y:216,'text-anchor':'middle',class:'flow-label'},shortDate(d.day)));
    });
    const chart=el('div',undefined,'flow-plot');chart.append(svg);body.append(chart);
    if(!incoming&&!outgoing)body.append(el('p','Ainda não há entradas ou saídas nesta medida no período.','muted flow-empty'));
    if((stats.movement_flow||[]).some(r=>!r.unit))body.append(el('p','Lançamentos antigos sem unidade de medida não entram neste gráfico.','muted flow-empty'));
    const details=el('details',undefined,'flow-details');details.append(el('summary','Ver valores por dia'),table(['Dia',`Entradas (${unit})`,`Saídas (${unit})`],days.map(d=>[cell(shortDate(d.day)),cell(num(d.incoming)),cell(num(d.outgoing))])));body.append(details);
  };
  measure.input.addEventListener('change',()=>{state.flowUnit=measure.input.value;draw();});
  if(units.includes(state.flowUnit))measure.input.value=state.flowUnit;
  draw();return section;
}

async function dashboardPage() {
  const stats=await fetchPage('/api/dashboard/stats');const root=el('div');
  const hero=el('div',undefined,'hero');const text=el('div');text.append(el('p','Operação em equilíbrio','eyebrow'),el('h1','O cuidado está nos detalhes.'),el('p','Peças disponíveis. Manutenção em movimento.','muted'));const art=el('div',undefined,'art');art.setAttribute('aria-hidden','true');art.classList.add('shelf-art');art.append(shelfDrawing());hero.append(text,art);root.append(hero);
  const metrics=el('div',undefined,'metrics');[[state.branch?'Peças relacionadas':'Peças cadastradas',stats.total_skus,'SKUs no catálogo'],['Precisam de atenção',stats.low_stock_count,'Inclui peças esgotadas no estoque central'],[state.branch?'Unidade selecionada':'Unidades atendidas',stats.branches,'Destinos da manutenção']].forEach(([label,value,note])=>{const m=el('div',undefined,'metric');m.append(el('p',label,'eyebrow'),el('p',num(value),'value'),el('small',note));metrics.append(m);});root.append(metrics);
  if(can('costs_view')){const f=el('div',undefined,'financials');f.append(el('span','Valoração de compra: '+money(stats.purchase_valuation)),el('span','Repasse potencial: '+money(stats.sale_valuation)));root.append(f);}
  root.append(actions(...entryButtons()));
  root.append(flowChart(stats));
  const split=el('div',undefined,'split');const recent=el('section');recent.append(el('div',undefined,'section-heading'));recent.firstChild.append(el('h2','Últimas movimentações'));stats.recent_movements.forEach(m=>{const row=el('div',undefined,'activity');const text=el('div');text.append(el('strong',m.product_name||'Peça legada'),el('small',(m.branch_name_snapshot||'Estoque central')+' · '+date(m.timestamp)));row.append(text,el('span',(m.type==='SAIDA'?'−':'+')+num(m.quantity)+' '+(m.product_unit||''),m.type==='SAIDA'?'movement-out-text':'movement-in-text'));recent.append(row);});if(!stats.recent_movements.length)recent.append(el('p','Ainda não há movimentações.','empty'));
  const stock=el('section');stock.append(el('div',undefined,'section-heading'));stock.firstChild.append(el('h2','Saldos centrais por medida'));stock.append(table(['Medida','Saldo central'],stats.stock_by_unit.map(s=>[cell(s.unit),cell(num(s.quantity),'numeric')])));split.append(recent,stock);root.append(split);
  if(can('alerts_view'))root.append(button('Ver peças que precisam de reposição',()=>navigate('alerts'),'text-button'));
  const footer=el('footer',undefined,'page-footer');const links=el('span',undefined,'legal-links');const privacy=el('a','Política de privacidade');privacy.href='/politica-de-privacidade';const terms=el('a','Termos de Serviço');terms.href='/termos-de-servico';links.append(privacy,terms);footer.append(el('span','YVI · Gestão de peças'),links);root.append(footer);
  return root;
}

async function productsPage(alerts) {
  const params=new URLSearchParams({page:state.page,search:state.search,category_id:state.category,status:state.status});
  const [data,meta]=await Promise.all([fetchPage((alerts?'/api/alerts':'/api/products')+'?'+params),metadata()]);
  const root=el('div');root.append(heading(alerts?'Atenção às próximas reposições':'Peças e Estoque',alerts?'Inclui peças no mínimo e esgotadas.':'Encontre a peça. Confira o saldo. Siga com a operação.',can('products_manage')&&button('+ Nova peça',()=>productEditor(),'button primary')));
  const filters=el('div',undefined,'filters');const search=field('Buscar peça ou localização','search',state.search,'search');search.wrap.className='search';search.input.placeholder='SKU, nome ou prateleira';search.input.dataset.filter='search';let timer;search.input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>{state.search=search.input.value;state.page=1;loadPage(true);},300);});
  const cat=select('Categoria','category',state.category,[{value:'',label:'Todas as categorias'},...meta.categories.map(c=>({value:c.id,label:c.name}))]);cat.input.addEventListener('change',()=>{state.category=cat.input.value;state.page=1;loadPage();});filters.append(search.wrap,cat.wrap);
  if(!alerts){const status=select('Situação','status',state.status,[{value:'',label:'Todas'},{value:'ok',label:'Disponível'},{value:'low',label:'Repor / esgotado'},{value:'out',label:'Esgotado'}]);status.input.addEventListener('change',()=>{state.status=status.input.value;state.page=1;loadPage();});filters.append(status.wrap);}root.append(filters);
  const headers=['Peça / SKU','Localização','Saldo central','Mínimo','Situação'];if(can('costs_view'))headers.push('Custo / repasse');headers.push('Ações');
  root.append(table(headers,data.items.map(p=>{const row=[cell(pieceName(p)),cell(p.location||'—'),cell(num(p.current_stock)+' '+p.unit,'numeric'),cell(num(p.min_stock)+' '+p.unit,'numeric'),cell(badge(p))];if(can('costs_view'))row.push(cell(money(p.purchase_price)+' / '+money(p.sale_price),'numeric'));row.push(cell(actions(can('movements_out')&&button('Saída',()=>movementEditor('SAIDA',p),'button small movement-out'),can('movements_in')&&button('Entrada',()=>movementEditor('ENTRADA',p),'button small movement-in'),can('products_manage')&&button('Editar',()=>productEditor(p),'button small quiet'))));return row;})));
  const pager=el('div',undefined,'pager');pager.append(el('span',`${data.total} ${data.total===1?'peça':'peças'} · página ${state.page}`));const prev=button('Anterior',()=>{state.page--;loadPage();},'button small');prev.disabled=state.page<=1;const next=button('Próxima',()=>{state.page++;loadPage();},'button small');next.disabled=state.page*data.limit>=data.total;pager.append(actions(prev,next));root.append(pager);return root;
}

async function movementPage() {
  const data=await fetchPage('/api/movements?limit=50'+(state.cursor?'&before_id='+state.cursor:''));const root=el('div');root.append(heading('Movimentações','Cada entrada e saída, com origem e destino.',...entryButtons()));
  const headers=['Data / tipo','Peça','Quantidade','Destino / responsável','Observação'];if(can('costs_view'))headers.push('Total');headers.push('Rastreabilidade');
  root.append(table(headers,data.items.map(m=>{const r=[cell(el('span',date(m.timestamp)+' · '+(m.type==='SAIDA'?'Saída':'Entrada'),m.type==='SAIDA'?'movement-out-text':'movement-in-text')),cell(m.product_name||'Peça legada'),cell(num(m.quantity)+' '+(m.product_unit||''),'numeric'),cell((m.branch_name_snapshot||'Estoque central')+' · '+(m.actor_name||'Autor legado não disponível')),cell(m.notes||'—')];if(can('costs_view'))r.push(cell(money(m.total_price),'numeric'));const status=m.legacy?'Legado preservado':m.reversal_of?'Estorno de #'+m.reversal_of:m.reversed?'Estornado':'#'+m.id;r.push(cell(actions(el('span',status,'badge'),state.user.role==='ADMIN'&&!m.legacy&&!m.reversal_of&&!m.reversed&&button('Estornar',()=>reverseEditor(m),'button small danger'))));return r;})));
  const prev=button('Mais recentes',()=>{state.cursor=state.cursors.pop()??null;loadPage();},'button small');prev.disabled=!state.cursors.length;const next=button('Mais antigas',()=>{state.cursors.push(state.cursor);state.cursor=data.next_cursor;loadPage();},'button small');next.disabled=!data.next_cursor;const pager=el('div',undefined,'pager');pager.append(el('span','Histórico preservado · correções por estorno'),actions(prev,next));root.append(pager);return root;
}

async function catalogPage(kind) {
  const rows=await fetchPage('/api/'+kind);const root=el('div');root.append(heading(labels[kind],kind==='categories'?'Organize as peças por finalidade.':'Unidades que recebem materiais para manutenção.',button('+ Novo cadastro',()=>catalogEditor(kind),'button primary')));
  root.append(table(kind==='categories'?['Categoria','Descrição','Peças','Ações']:['Unidade','Endereço','Telefone','Ações'],rows.map(r=>[cell(kind==='categories'?categoryLabel(r):el('strong',r.name)),cell(kind==='categories'?r.description:r.address),cell(kind==='categories'?r.product_count:r.phone),cell(actions(button('Editar',()=>catalogEditor(kind,r),'button small'),button('Excluir',()=>deleteEditor(kind,r),'button small danger')))])));return root;
}

async function usersPage() {
  const [rows,branches]=await Promise.all([fetchPage('/api/users'),api('/api/branches')]);const root=el('div');root.append(heading('Usuários e acessos','Contas, perfis e unidades autorizadas da equipe.',button('+ Novo usuário',()=>userEditor(),'button primary')));
  root.append(table(['Nome / login','E-mail','Perfil','Unidades autorizadas','Status','Ações'],rows.map(u=>{const name=el('div',undefined,'category-label');const identity=el('div');identity.append(el('strong',u.name),el('span',u.username,'sub'));name.append(avatarNode(u),identity);return [cell(name),cell(u.email),cell(u.role),cell(u.branch_restricted?branches.filter(b=>u.branch_ids.includes(b.id)).map(b=>b.name).join(', ')||'Nenhuma unidade':'Todas as academias'),cell(u.active?'Ativo':'Inativo'),cell(actions(button('Editar',()=>userEditor(u),'button small'),u.id!==state.user.id&&button(u.active?'Desativar':'Ativar',()=>toggleUserEditor(u),'button small quiet')))];})));return root;
}

async function settingsPage() {
  const data=await api('/api/admin/settings');const root=el('div');root.append(heading('Configurações','Administração do sistema · acesso exclusivo de administradores.'));
  const cards=[['Usuários e unidades autorizadas',data.active_users+' usuários ativos. Defina o perfil e as academias que cada pessoa pode acessar.',button('Gerenciar usuários',()=>navigate('users'))],['Permissões por perfil','Defina os recursos liberados para administradores, gerentes e operadores.',button('Editar permissões',()=>permissionsEditor())],['Notificações por e-mail','Gerencie a conexão Gmail, os alertas de estoque e o histórico de envios.',button('Abrir Notificações',()=>navigate('notifications'))]];
  if(can('branches_manage'))cards.push(['Unidades da rede',data.branches+' unidades cadastradas.',button('Gerenciar unidades',()=>navigate('branches'))]);
  if(can('categories_manage'))cards.push(['Categorias e ícones','Organize o catálogo e personalize os ícones.',button('Gerenciar categorias',()=>navigate('categories'))]);
  for(const [title,copy,action] of cards){const card=el('section',undefined,'notification-card');card.append(el('h2',title),el('p',copy,'muted'),actions(action));root.append(card);}return root;
}

async function reportsPage() {
  const root=el('div');root.append(heading('Relatórios','Exportações respeitam as permissões de custos do seu perfil.'));
  const stock=el('section',undefined,'report');stock.append(el('h2','Estoque de peças'),el('p','Catálogo, saldos, localização e valores autorizados. Até 10.000 linhas.','muted'));const s=field('Filtrar por peça ou localização','report-search','','search');stock.append(s.wrap,button('Baixar CSV de estoque',()=>download('/api/export/csv?target=products&search='+encodeURIComponent(s.input.value),'yvi_estoque.csv'),'button primary'));
  const movements=el('section',undefined,'report');movements.append(el('h2','Histórico de movimentações'),el('p','Entradas, saídas, estornos e responsáveis. Horários exportados em UTC.','muted'));const from=field('De (data local)','from','','date'),to=field('Até (data local, inclusive)','to','','date');const filters=el('div',undefined,'filters');filters.append(from.wrap,to.wrap);movements.append(filters,button('Baixar CSV de movimentações',()=>{const params=new URLSearchParams({target:'movements'});if(from.input.value)params.set('from',new Date(from.input.value+'T00:00:00').toISOString());if(to.input.value){const d=new Date(to.input.value+'T00:00:00');d.setDate(d.getDate()+1);params.set('to',d.toISOString());}download('/api/export/csv?'+params,'yvi_movimentacoes.csv');},'button primary'));root.append(stock,movements);return root;
}
async function download(path,name) { try{const blob=await api(branchPath(path),{blob:true});const url=URL.createObjectURL(blob);const a=el('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){pageError(e);} }

function editor(title,kicker='Cadastro') {
  editorCleanup();editorCleanup=()=>{};$('editor-close').disabled=false;$('editor-content').replaceChildren();$('editor-title').textContent=title;$('editor-kicker').textContent=kicker;
  if(!$('editor').open)$('editor').showModal();
  const form=el('form');const grid=el('div',undefined,'form-grid');const errors=el('div',undefined,'notice error');errors.role='alert';errors.hidden=true;form.append(grid,errors);$('editor-content').append(form);
  return {form,grid,errors,fields:{},dirty:false};
}
function addField(ctx,label,name,value='',type='text',options,required=false,full=false) {
  const f=field(label,name,value,type,options);f.input.required=required;if(full)f.wrap.classList.add('full');ctx.grid.append(f.wrap);ctx.fields[name]=f.input;ctx.form.addEventListener('input',()=>ctx.dirty=true,{once:true});return f.input;
}
function bindSave(ctx,makeRequest,label='Salvar',idempotent=false) {
  const submit=el('button',label,label==='Confirmar saída'?'button movement-out':label==='Confirmar entrada'?'button movement-in':'button primary');submit.type='submit';const cancel=button('Cancelar',()=>closeEditor());const footer=el('div',undefined,'form-footer');footer.append(cancel,submit);ctx.form.append(footer);
  let key=crypto.randomUUID(),pending=null,busy=false;
  const disabledBefore=new Map(Object.values(ctx.fields).map(f=>[f,f.disabled]));
  ctx.form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;if(!pending&&!ctx.form.reportValidity())return;
    busy=true;submit.disabled=true;cancel.disabled=true;$('editor-close').disabled=true;ctx.errors.hidden=true;ctx.form.querySelectorAll('.form-error').forEach(e=>e.remove());
    let submitted=false;
    try {
      const request=pending||makeRequest(Object.fromEntries(new FormData(ctx.form)));
      let result;
      if(pending&&idempotent){const previous=await api('/api/operations/'+key);if(previous.found)result=previous.result;}
      if(!result){submitted=true;result=await api(request.path,{...request,key:idempotent?key:undefined});}
      pending=null;ctx.dirty=false;editorCleanup();$('editor').close();toast(result.message||'Alterações salvas.');metadataPromise=null;await loadPage();
    } catch(error) {
      if(error.status===401){showLogin(error.message);refreshCsrf().catch(()=>{});return;}
      if(error.code==='CSRF_EXPIRED'){await refreshCsrf().catch(()=>{});}
      ctx.errors.textContent=error.message+(error.requestId?' Protocolo: '+error.requestId:'');ctx.errors.hidden=false;
      Object.entries(error.fields||{}).forEach(([name,message])=>{const input=ctx.fields[name];if(input){input.setAttribute('aria-invalid','true');const msg=el('p',message,'form-error');input.parentElement.append(msg);}});
      if(idempotent&&(error.status===0||error.status>=500)){
        pending=pending||makeRequest(Object.fromEntries(new FormData(ctx.form)));
        Object.values(ctx.fields).forEach(f=>f.disabled=true);
        submit.textContent='Verificar / repetir o mesmo envio';
        ctx.errors.append(el('p','Antes de iniciar outra operação, verifique este envio. O sistema usará a mesma identificação para evitar duplicação.'));
      }else if(submitted&&error.status>=400&&error.status<500){
        pending=null;key=crypto.randomUUID();submit.textContent=label;
        disabledBefore.forEach((disabled,field)=>field.disabled=disabled);
      }else if(!pending){key=crypto.randomUUID();}
    } finally {busy=false;submit.disabled=false;cancel.disabled=!!pending;$('editor-close').disabled=!!pending;}
  });
  editorCleanup=()=>{};
}
function closeEditor() { if($('editor-close').disabled)return;$('editor').close();editorCleanup(); }
$('editor-close').addEventListener('click',closeEditor);
$('editor').addEventListener('cancel',e=>{if($('editor-close').disabled)e.preventDefault();});
window.addEventListener('beforeunload',event=>{if($('editor').open&&$('editor-close').disabled){event.preventDefault();event.returnValue='';}});

async function productEditor(old=null) {
  try{
    const meta=await metadata();const p=old?await api('/api/products/'+old.id):{};const ctx=editor(old?'Editar peça':'Nova peça');
    const code=addField(ctx,'Código SKU','code',p.code||'','text',null,true);code.maxLength=50;if(old)code.readOnly=true;
    const unit=addField(ctx,'Unidade de medida','unit',p.unit||'un','select',['un','m','par','cx','kg'].map(v=>({value:v,label:v})),true);if(old)unit.disabled=true;
    addField(ctx,'Nome da peça','name',p.name||'','text',null,true,true).maxLength=200;
    addField(ctx,'Categoria','category_id',p.category_id||'','select',[{value:'',label:'Selecione…'},...meta.categories.map(c=>({value:c.id,label:c.name}))],true);
    addField(ctx,'Localização','location',p.location||'').maxLength=200;
    const min=addField(ctx,'Estoque mínimo','min_stock',p.min_stock??'0','number',null,true);min.min=0;min.step='.001';
    if(!old){const initial=addField(ctx,'Saldo inicial','current_stock','0','number',null,true);initial.min=0;initial.step='.001';if(!can('movements_in'))initial.readOnly=true;}
    if(can('costs_view'))for(const [name,label] of [['purchase_price','Custo de compra (R$)'],['sale_price','Valor de repasse (R$)']]){const input=addField(ctx,label,name,p[name]??'0','number',null,true);input.min=0;input.step='.01';}
    bindSave(ctx,data=>({path:'/api/products'+(old?'/'+old.id:''),method:old?'PUT':'POST',body:{...data,unit:old?p.unit:data.unit,...(old?{version:p.version}:{})}}),'Salvar peça',!old);
    if(old){ctx.form.append(button('Arquivar peça',()=>deleteEditor('products',p),'text-button'));}
  }catch(e){pageError(e);}
}

async function movementEditor(type,selected=null) {
  try{
    const meta=await metadata();const ctx=editor(type==='SAIDA'?'Registrar saída':'Registrar entrada','Nova movimentação');
    let currentPiece=selected;
    const quantity=addField(ctx,'Quantidade','quantity','1','number',null,true);quantity.min='.001';quantity.step='.001';
    addField(ctx,'Unidade de destino','branch_id',state.branch,'select',[{value:'',label:'Selecione…'},...meta.branches.map(b=>({value:b.id,label:b.name}))],true);
    addField(ctx,'Equipamento / aplicação','destination_equipment','','text',null,false,true).maxLength=200;
    addField(ctx,'Observação / motivo','notes','','textarea',null,false,true).maxLength=1000;
    const balance=el('div',undefined,'balance');balance.setAttribute('aria-live','polite');ctx.grid.after(balance);
    const updateBalance=()=>{const p=currentPiece;balance.replaceChildren();if(!p)return;const before=el('span','Saldo disponível');before.append(el('strong',num(p.current_stock)+' '+p.unit));const after=el('span','Após esta movimentação');after.append(el('strong',num(Number(p.current_stock)+(type==='SAIDA'?-1:1)*Number(quantity.value))+' '+p.unit));balance.append(before,after);quantity.step=['m','kg'].includes(p.unit)?'.001':'1';quantity.min=quantity.step;};
    const cleanup=pieceCombobox(ctx,selected,p=>{currentPiece=p;updateBalance();});ctx.grid.prepend(ctx.grid.lastElementChild);
    quantity.addEventListener('input',updateBalance);
    bindSave(ctx,data=>({path:'/api/movements',method:'POST',body:{...data,type}}),type==='SAIDA'?'Confirmar saída':'Confirmar entrada',true);
    editorCleanup=cleanup;

  }catch(e){pageError(e);}
}

function reverseEditor(m) {
  const ctx=editor('Estornar movimentação #'+m.id,'Histórico preservado');ctx.grid.append(el('p',`O lançamento original será mantido e um movimento inverso será registrado. Peça: ${m.product_name}. Quantidade: ${num(m.quantity)} ${m.product_unit||''}.`,'full muted'));addField(ctx,'Motivo do estorno','reason','','textarea',null,true,true).maxLength=1000;bindSave(ctx,data=>({path:`/api/movements/${m.id}/reverse`,method:'POST',body:data}),'Confirmar estorno',true);
}
function catalogEditor(kind,row=null) {
  const ctx=editor((row?'Editar ':'Novo cadastro · ')+(kind==='categories'?'categoria':'unidade'));addField(ctx,'Nome','name',row?.name||'','text',null,true,true);
  if(kind==='categories'){addField(ctx,'Descrição','description',row?.description||'','textarea',null,false,true);iconPicker(ctx,row?.icon||'folder');}else{addField(ctx,'Endereço','address',row?.address||'','text',null,false,true);addField(ctx,'Telefone','phone',row?.phone||'');}
  bindSave(ctx,data=>({path:'/api/'+kind+(row?'/'+row.id:''),method:row?'PUT':'POST',body:{...data,...(row?{version:row.version}:{})}}));
}
function deleteEditor(kind,row) {
  const ctx=editor(kind==='products'?'Arquivar peça':'Excluir cadastro','Revisar ação');ctx.grid.append(el('p',kind==='products'?`Arquivar “${row.name}”? O saldo deve estar zerado e o histórico será mantido.`:`Excluir “${row.name}”? Cadastros com referências não podem ser excluídos.`,'full'));bindSave(ctx,()=>({path:'/api/'+kind+'/'+row.id,method:'DELETE',body:{version:row.version}}),'Confirmar');
}
async function userEditor(user=null) {
  try{
    const branches=await api('/api/branches');const ctx=editor(user?'Editar usuário':'Novo usuário');addField(ctx,'Nome completo','name',user?.name||'','text',null,true,true);addField(ctx,'Login','username',user?.username||'','text',null,true);addField(ctx,'E-mail','email',user?.email||'','email');const role=addField(ctx,'Perfil','role',user?.role||'OPERATOR','select',[{value:'OPERATOR',label:'Operador'},{value:'MANAGER',label:'Gerente'},{value:'ADMIN',label:'Administrador'}],true);const pass=addField(ctx,user?'Nova senha (opcional)':'Senha inicial','password','','password',null,!user);pass.minLength=12;pass.maxLength=128;pass.autocomplete='new-password';
    const mode=addField(ctx,'Acesso às unidades','unit_access',user?(user.branch_restricted?'selected':'all'):'selected','select',[{value:'selected',label:'Somente as unidades selecionadas'},{value:'all',label:'Todas as academias'}],true,true);
    const group=el('fieldset',undefined,'unit-access full');group.append(el('legend','Unidades autorizadas'));const checks=[];
    for(const branch of branches){const label=el('label',undefined,'unit-access-option');const input=el('input');input.type='checkbox';input.checked=!!user?.branch_ids?.includes(branch.id);input.value=branch.id;label.append(input,el('span',branch.name));group.append(label);checks.push(input);}
    const note=el('p','Uma unidade fixa o filtro. Várias unidades permitem alternar somente entre as selecionadas.','muted full');ctx.grid.append(group,note);
    const sync=()=>{const admin=role.value==='ADMIN';mode.disabled=admin;group.hidden=admin||mode.value==='all';note.textContent=admin?'Administradores mantêm acesso geral para administrar o sistema.':'O acesso será limitado no servidor. Cadastros centrais compartilhados exigem um usuário com acesso geral.';};role.addEventListener('change',sync);mode.addEventListener('change',sync);sync();
    bindSave(ctx,data=>({path:'/api/users'+(user?'/'+user.id:''),method:user?'PUT':'POST',body:{...data,branch_ids:role.value==='ADMIN'||mode.value==='all'?null:checks.filter(c=>c.checked).map(c=>Number(c.value)),...(user?{version:user.version}:{})}}));
  }catch(error){pageError(error);}
}
function toggleUserEditor(user) {
  const ctx=editor(user.active?'Desativar usuário':'Ativar usuário','Controle de acesso');ctx.grid.append(el('p',`${user.name}: ${user.active?'as sessões serão encerradas e o histórico preservado':'o acesso será reativado'}.`,'full'));bindSave(ctx,()=>({path:'/api/users/'+user.id+'/active',method:'PUT',body:{version:user.version,active:!user.active}}),'Confirmar');
}
async function permissionsEditor() {
  try{const rows=await api('/api/permissions');const ctx=editor('Permissões por perfil','Acessos da equipe');const headers=['Recurso',...rows.map(r=>r.role)];const boxes={};const t=table(headers,Object.entries(permissions).map(([key,label])=>[cell(label),...rows.map(r=>{const box=el('input');box.type='checkbox';box.checked=!!r[key];box.setAttribute('aria-label',label+' · '+r.role);if(key==='users_manage'){box.disabled=true;box.checked=r.role==='ADMIN';}boxes[r.role+'-'+key]=box;return cell(box);})]),'permissions-table');t.classList.add('full');ctx.grid.append(t);bindSave(ctx,()=>({path:'/api/permissions',method:'PUT',body:{roles:rows.map(r=>({role:r.role,version:r.version,...Object.fromEntries(Object.keys(permissions).map(k=>[k,boxes[r.role+'-'+k].checked]))}))}}),'Salvar todas as permissões');}catch(e){pageError(e);}
}

function connectSocket() {
  state.socket?.disconnect();
  if(typeof window.io!=='function')return;
  const socket=window.io({auth:{csrf:getCsrf()},transports:['websocket','polling']});state.socket=socket;
  socket.on('update_data',()=>{clearTimeout(reloadTimer);reloadTimer=setTimeout(async()=>{try{const me=await api('/api/me');applyUser(me.user);metadataPromise=null;if(!canView(state.view))navigate(Object.keys(labels).find(v=>canView(v))||'dashboard');else if(!$('editor').open)loadPage(true);else toast('Há atualizações da equipe. O saldo será conferido ao confirmar.');}catch(e){pageError(e);}},500);});
  socket.on('disconnect',()=>{if(state.user)online(false);});socket.on('connect_error',()=>online(false));
  socket.on('connect',()=>{if(state.user)loadPage(true);});
  socket.on('session_revoked',()=>showLogin('Seu acesso foi atualizado. Entre novamente.'));
}
async function boot() {
  try{await refreshCsrf();const data=await api('/api/me');setCsrf(data.csrf_token);applyUser(data.user);const requested=location.hash.slice(1);state.view=canView(requested)?requested:Object.keys(labels).find(v=>canView(v))||'dashboard';if(!canView(state.view)){$('page').replaceChildren(el('p','Seu perfil ainda não possui módulos liberados. Procure um administrador.','notice'));return;}await loadPage();connectSocket();}
  catch(e){showLogin(e.status===401?'':e.message);}
}
$('login-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;const submit=form.querySelector('button');submit.disabled=true;$('login-error').hidden=true;try{await refreshCsrf();const data=await api('/api/login',{method:'POST',body:Object.fromEntries(new FormData(form))});setCsrf(data.csrf_token);$('login-form').reset();await boot();}catch(e){$('login-error').textContent=e.message;$('login-error').hidden=false;}finally{submit.disabled=false;}});
$('logout').addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST'});showLogin();await refreshCsrf();}catch(e){pageError(e);}});
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.view)));
document.querySelector('.brand').addEventListener('click',event=>{event.preventDefault();if(state.user)navigate('dashboard');});
window.addEventListener('offline',()=>online(false));window.addEventListener('online',()=>{if(state.user)loadPage(true);});
setInterval(async()=>{if(!state.user||document.hidden)return;state.socket?.emit('heartbeat');try{const me=await api('/api/me');applyUser(me.user);if(!$('editor').open)loadPage(true);}catch(e){pageError(e);}},20000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.user&&!$('editor').open)loadPage(true);});
$('sidebar-toggle').addEventListener('click',()=>{const collapsed=$('workspace').classList.toggle('sidebar-collapsed');const toggle=$('sidebar-toggle');toggle.setAttribute('aria-expanded',String(!collapsed));toggle.setAttribute('aria-label',collapsed?'Expandir menu':'Recolher menu');toggle.title=collapsed?'Expandir menu':'Recolher menu';});
function profileEditor() {
  const ctx=editor('Meu perfil','Sua conta');
  const preview=el('div',undefined,'profile-preview full');preview.append(avatarNode(state.user),el('strong',state.user.name));ctx.grid.append(preview);
  const input=addField(ctx,'Foto de perfil','photo','','file',null,false,true);input.accept='image/jpeg,image/png,image/webp';
  ctx.grid.append(el('p','JPG, PNG ou WebP, até 2 MB e 16 megapixels. A foto será recortada ao centro.','muted full'));
  let encoded=null,busy=false,alive=true,reader;
  const save=button('Salvar foto',()=>{if(encoded)send('PUT',{image:encoded});},'button primary');save.disabled=true;
  const remove=button('Remover foto',()=>send('DELETE'),'button danger');remove.disabled=!state.user.has_avatar;
  const send=async(method,body)=>{
    if(busy)return;busy=true;save.disabled=true;remove.disabled=true;input.disabled=true;$('editor-close').disabled=true;ctx.errors.hidden=true;
    try {const result=await api('/api/me/avatar',{method,body});const me=await api('/api/me');applyUser(me.user);editorCleanup();$('editor').close();toast(result.message);}
    catch(error){ctx.errors.textContent=error.message;ctx.errors.hidden=false;}
    finally{busy=false;input.disabled=false;save.disabled=!encoded;remove.disabled=!state.user?.has_avatar;$('editor-close').disabled=false;}
  };
  input.addEventListener('change',()=>{
    reader?.abort();encoded=null;save.disabled=true;ctx.errors.hidden=true;const file=input.files[0];if(!file)return;
    if(file.size>2*1024*1024||!['image/jpeg','image/png','image/webp'].includes(file.type)){ctx.errors.textContent='Escolha uma imagem JPG, PNG ou WebP de até 2 MB.';ctx.errors.hidden=false;return;}
    reader=new FileReader();
    reader.onload=()=>{if(!alive)return;encoded=String(reader.result).split(',')[1];const img=el('img');img.alt='Prévia da nova foto';img.src=reader.result;preview.replaceChildren(img,el('strong',state.user.name));save.disabled=false;};
    reader.onerror=()=>{ctx.errors.textContent='Não foi possível ler a imagem. Selecione novamente.';ctx.errors.hidden=false;};reader.readAsDataURL(file);
  });
  ctx.form.addEventListener('submit',e=>e.preventDefault());ctx.form.append(actions(remove,save));editorCleanup=()=>{alive=false;reader?.abort();};
}
$('profile').addEventListener('click',profileEditor);
boot();
