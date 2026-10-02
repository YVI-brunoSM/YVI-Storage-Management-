import {api} from './http.js';

const statuses={pending:'Na fila',processing:'Em envio',accepted:'Aceito pelo Gmail',failed:'Falhou',uncertain:'Conferir envio',cancelled:'Cancelado'};
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const date=value=>value?new Date(value).toLocaleString('pt-BR'):'—';

export async function notificationsPage({signal,cursor,onPage,onRefresh}) {
  let data;
  try{data=await api('/api/notifications'+(cursor?'?before_id='+cursor:''),{signal});}
  catch(error){
    if(error.name==='AbortError'||error.status===401)throw error;
    const root=node('div',undefined,'notifications-page');root.dataset.loadError='true';root.append(node('h1','Notificações'));
    const card=node('section',undefined,'notification-card');const message=node('p',error.message+(error.requestId?' Protocolo: '+error.requestId:''),'notice error');message.setAttribute('role','alert');card.append(message);
    card.append(node('p','As configurações e o histórico não puderam ser carregados. Nenhum envio foi solicitado por esta página.','muted'));
    const retry=node('button','Tentar novamente','button');retry.type='button';retry.addEventListener('click',()=>onRefresh());card.append(retry);root.append(card);return root;
  }
  const root=node('div',undefined,'notifications-page');
  const message=node('p',undefined,'notice');message.hidden=true;message.setAttribute('role','status');
  let busy=false;
  const buttons=[];
  const action=(label,fn,cls='button')=>{const b=node('button',label,cls);b.type='button';buttons.push(b);b.addEventListener('click',async()=>{
    if(busy)return;busy=true;buttons.forEach(x=>x.disabled=true);message.hidden=true;
    try{await fn();}catch(error){message.textContent=error.message;message.className='notice error';message.hidden=false;}
    finally{busy=false;buttons.forEach(x=>x.disabled=x.dataset.unavailable==='true');}
  });return b;};
  const unavailable=(b,value)=>{b.disabled=value;b.dataset.unavailable=String(value);return b;};
  const run=async(path,body={})=>{const result=await api('/api/notifications/'+path,{method:'POST',body});await onRefresh();return result;};
  const top=node('div',undefined,'page-heading');const title=node('div');title.append(node('p','Estoque Geral · YVI','eyebrow'),node('h1','Notificações'),node('p','Alertas de reposição para administradores e gerentes.','muted'));
  top.append(title,action('Atualizar',()=>onRefresh()));root.append(top,message);
  const connection=node('section',undefined,'notification-card');connection.append(node('h2','Conta de envio'));
  const account=node('p');account.append(node('strong',data.sender),node('span',data.connected?' · Conectada':' · Não conectada',data.connected?'movement-in-text':'movement-out-text'));connection.append(account,node('p','Respostas para '+data.reply_to,'muted'));
  if(!data.configured||!data.master_enabled){
    connection.append(node('p','Conclua a configuração de e-mail no Railway para liberar os envios. O estoque continua funcionando normalmente.','notice'));
    const details=node('details');details.append(node('summary','Ver configuração pendente'));
    details.append(node('p',(!data.master_enabled?'Defina EMAIL_ENABLED=true nos serviços da aplicação e de e-mail. ':'')+(data.missing.length?'Revise: '+data.missing.join(', ')+'.':''),'muted'));connection.append(details);
  }
  if(data.connection_status==='needs_reconnect')connection.append(node('p','A autorização precisa ser renovada. Conecte o Gmail novamente e envie outro teste.','notice error'));
  if(data.callback_url){const details=node('details');details.append(node('summary','Endereço de retorno para cadastrar no Google'),node('code',data.callback_url,'notification-url'));connection.append(details);}
  const controls=node('div',undefined,'actions');
  controls.append(unavailable(action(data.connected?'Reconectar Gmail':'Conectar Gmail',async()=>{
    if(data.connected&&!confirm('Reconectar pausa os alertas e exige um novo teste. Continuar?'))return;
    const result=await api('/api/notifications/connect',{method:'POST',body:{}});const url=new URL(result.url);
    if(url.origin!=='https://accounts.google.com')throw new Error('Endereço de autorização inválido.');
    window.location.assign(url.href);
  },'button primary'),!data.configured));
  if(data.connected||data.connection_status==='needs_reconnect')controls.append(action('Desconectar',async()=>{
    if(confirm('Remover a conexão e cancelar as mensagens que ainda estão na fila?'))await run('disconnect');
  },'button danger'));
  controls.append(unavailable(action('Enviar teste',()=>run('test')),!data.connected||!data.master_enabled||!data.configured));
  connection.append(controls,node('p','O teste é enviado somente para '+data.reply_to+'. Após solicitar, atualize o histórico e confira sua caixa de entrada.','muted'));
  const workerFresh=data.worker_seen_at&&Date.now()-new Date(data.worker_seen_at).getTime()<90000;
  connection.append(node('p',workerFresh?'Serviço de envio em execução.':'Serviço de envio sem comunicação recente. Confira o serviço de e-mail no Railway.',workerFresh?'muted':'notice'));
  connection.append(node('p','Última comunicação: '+date(data.worker_seen_at)+' · Limite local: '+data.daily_limit+' tentativas em 24 horas.','muted'));
  root.append(connection);
  const delivery=node('section',undefined,'notification-card');delivery.append(node('h2','Alertas de estoque'),node('p',data.enabled?'Ativados: novas ocorrências de Repor e Esgotado entram na fila.':'Pausados: novas ocorrências não geram e-mails.','notice'));
  delivery.append(node('p','A seleção de unidade nas outras páginas não altera os destinatários. Os e-mails respeitam as unidades autorizadas de cada usuário. Cada alerta informa o saldo e o mínimo da unidade afetada.','muted'));
  const deliveryButtons=node('div',undefined,'actions');
  deliveryButtons.append(unavailable(action(data.enabled?'Pausar alertas':'Ativar alertas',async()=>{
    if(!data.enabled&&!confirm('Você recebeu o teste? Ativar enviará os novos alertas aos administradores e gerentes listados abaixo.'))return;
    await run('settings',{enabled:!data.enabled});
  },'button primary'),!data.enabled&&(!data.test_accepted_at||!data.connected||!data.master_enabled||!data.configured)));
  deliveryButtons.append(unavailable(action('Enviar resumo das pendências',async()=>{
    if(confirm('Enviar um resumo do estoque atual em reposição para os destinatários listados?'))await run('summary');
  }),!data.enabled||!data.connected||!data.master_enabled));
  delivery.append(deliveryButtons,node('p',data.test_accepted_at?'Último teste aceito pelo Gmail: '+date(data.test_accepted_at):'Para ativar, conecte o Gmail e aguarde um teste aceito no histórico.','muted'));
  delivery.append(node('h3','Quem recebe'));
  const recipients=node('ul',undefined,'notification-recipients');
  for(const user of data.recipients){const row=node('li');row.append(node('strong',user.name),node('span',' · '+(user.role==='ADMIN'?'Administrador':'Gerente')),node('span',user.valid?' — '+user.email:' — cadastre um e-mail válido em Usuários e acessos',user.valid?'muted':'movement-out-text'),node('span',user.branch_restricted?' · Unidades: '+(user.branch_names||[]).join(', '):' · Todas as academias','muted'));recipients.append(row);}
  if(!data.recipients.length)recipients.append(node('li','Nenhum administrador ou gerente ativo.'));
  delivery.append(recipients);root.append(delivery);
  const history=node('section',undefined,'notification-card');history.append(node('h2','Histórico de envios'),node('p','Aceito pelo Gmail não confirma entrega nem leitura. Para resultado incerto, procure a referência YVI na pasta Enviados antes de reenviar.','muted'));
  const counts=node('div',undefined,'actions');for(const item of data.counts)counts.append(node('span',(statuses[item.status]||item.status)+': '+item.total,'badge'));history.append(counts);
  const wrap=node('div',undefined,'table-wrap'),table=node('table'),head=node('thead'),hr=node('tr');for(const label of ['Mensagem','Destinatário','Situação','Data','Ações']){const th=node('th',label);th.scope='col';hr.append(th);}head.append(hr);table.append(head);const tbody=node('tbody');
  for(const item of data.items){const row=node('tr'),subject=node('td');subject.append(node('strong',item.subject),node('span','YVI-'+item.id+' · '+item.attempts+' tentativa(s)','sub'));
    const state=node('td');state.append(node('span',statuses[item.status]||item.status,'badge '+(item.status==='accepted'?'available':['failed','uncertain'].includes(item.status)?'out':'')));if(item.error_message)state.append(node('span',item.error_message,'sub'));
    const commands=node('td');if(['failed','uncertain'].includes(item.status))commands.append(action('Reenviar',async()=>{
      const uncertain=item.status==='uncertain';if(!confirm(uncertain?'Confirme que conferiu a pasta Enviados e esta mensagem NÃO foi enviada. Reenviar mesmo assim?':'Solicitar uma nova tentativa desta mensagem?'))return;
      await run(item.id+'/retry',{reviewed_sent_folder:uncertain});
    },'button small'));
    row.append(subject,node('td',item.recipient),state,node('td',date(item.created_at)),commands);tbody.append(row);
  }
  if(!data.items.length){const row=node('tr'),cell=node('td','Nenhum envio registrado.','empty');cell.colSpan=5;row.append(cell);tbody.append(row);}table.append(tbody);wrap.append(table);history.append(wrap);
  const paging=node('div',undefined,'actions');if(cursor)paging.append(action('Mais recentes',()=>onPage(null)));if(data.next_cursor)paging.append(action('Mais antigos',()=>onPage(data.next_cursor)));history.append(paging);root.append(history);
  return root;
}
