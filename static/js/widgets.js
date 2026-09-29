import {api} from './http.js';

const iconPaths = {
  folder: ['Pasta','M3 4h7l3 3h8v13H3zM3 10h18'],
  dumbbell: ['Equipamentos','M3 8v8M6 5v14M18 5v14M21 8v8M6 12h12'],
  zap: ['Elétrica','m13 2-9 12h7l-1 8L21 9h-8z'],
  'file-text': ['Documentos','M5 3h10l4 4v14H5zM14 3v5h5M8 12h8M8 16h6'],
  droplet: ['Líquidos','M12 3S5 11 5 15a7 7 0 0 0 14 0c0-4-7-12-7-12Z'],
  sparkles: ['Limpeza','m10 3 2 6 6 2-6 2-2 6-2-6-6-2 6-2zM19 2v5M17 4h4'],
  box: ['Caixas','m3 7 9-4 9 4v10l-9 4-9-4zM3 7l9 4 9-4M12 11v10'],
  wrench: ['Ferramentas','M14 4a6 6 0 0 0-7 8l-5 5 5 5 5-5a6 6 0 0 0 8-7l-4 4-6-6z'],
  gear: ['Mecânica','M9 3h6l1 4 4 2v6l-4 2-1 4H9l-1-4-4-2V9l4-2zM15 12a3 3 0 1 0-6 0 3 3 0 0 0 6 0'],
  cable: ['Cabos','M7 3v5M11 3v5M5 8h8v3a4 4 0 0 1-8 0zM9 15v3a3 3 0 0 0 6 0v-3a3 3 0 0 1 6 0v6'],
  shield: ['Proteção','m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6'],
  truck: ['Transporte','M2 5h12v12H2zM14 9h5l3 4v4h-8M8 18a2 2 0 1 0-4 0 2 2 0 0 0 4 0M20 18a2 2 0 1 0-4 0 2 2 0 0 0 4 0']
};
export function categoryIcon(name) {
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.classList.add('category-icon');
  const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',(iconPaths[name]||iconPaths.folder)[1]);svg.append(path);return svg;
}
export function categoryLabel(row) {
  const wrap=document.createElement('span');wrap.className='category-label';wrap.append(categoryIcon(row.icon),document.createTextNode(row.name));return wrap;
}
export function iconPicker(ctx,value) {
  const group=document.createElement('fieldset');group.className='icon-picker full';
  const legend=document.createElement('legend');legend.textContent='Ícone da categoria';group.append(legend);
  for(const [key,[name]] of Object.entries(iconPaths)) {
    const label=document.createElement('label');const input=document.createElement('input');input.type='radio';input.name='icon';input.value=key;input.checked=key===(iconPaths[value]?value:'folder');
    const caption=document.createElement('span');caption.textContent=name;label.append(input,categoryIcon(key),caption);group.append(label);
  }
  ctx.grid.append(group);
}

export function pieceCombobox(ctx,selected,onChange) {
  const wrap=document.createElement('div');wrap.className='piece-combobox full';
  const label=document.createElement('label');label.htmlFor='piece-search';label.textContent='Peça';
  const input=document.createElement('input');input.id='piece-search';input.placeholder='Digite o nome ou código da peça';input.autocomplete='off';input.required=true;input.maxLength=200;
  input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-controls','piece-options');input.setAttribute('aria-expanded','false');
  const hidden=document.createElement('input');hidden.type='hidden';hidden.name='product_id';
  const list=document.createElement('div');list.id='piece-options';list.role='listbox';list.setAttribute('aria-label','Peças encontradas');list.hidden=true;
  const status=document.createElement('small');status.role='status';status.className='muted';status.textContent='Busque por nome ou código e selecione uma sugestão.';
  wrap.append(label,input,hidden,list,status);ctx.grid.append(wrap);ctx.fields.product_id=hidden;ctx.fields.piece_search=input;
  let rows=[],active=-1,timer,controller,alive=true,revision=0;
  const open=value=>{list.hidden=!value;input.setAttribute('aria-expanded',String(value));if(!value)input.removeAttribute('aria-activedescendant');};
  const choose=row=>{hidden.value=row.id;input.value=row.name+' · '+row.code;input.setCustomValidity('');open(false);status.textContent='Peça selecionada.';onChange(row);};
  const highlight=()=>{[...list.children].forEach((node,i)=>node.setAttribute('aria-selected',String(i===active)));if(active>=0){input.setAttribute('aria-activedescendant',list.children[active].id);list.children[active].scrollIntoView({block:'nearest'});}};
  const lookup=async()=>{
    controller?.abort();controller=new AbortController();const current=++revision;
    rows=[];active=-1;list.replaceChildren();input.removeAttribute('aria-activedescendant');status.textContent='Buscando peças…';
    try {
      const data=await api('/api/products/lookup?search='+encodeURIComponent(hidden.value?'':input.value),{signal:controller.signal});
      if(!alive||current!==revision)return;rows=data.items;
      rows.forEach((row,i)=>{const option=document.createElement('div');option.role='option';option.id='piece-option-'+row.id;option.setAttribute('aria-selected','false');option.textContent=row.name+' · '+row.code+' — '+row.current_stock+' '+row.unit;option.addEventListener('pointerdown',e=>e.preventDefault());option.addEventListener('click',()=>{if(!input.disabled)choose(row);});list.append(option);});
      status.textContent=rows.length?'Selecione uma peça. Use ↑ e ↓ para navegar.':'Nenhuma peça encontrada. Tente outro nome ou código.';open(document.activeElement===input&&rows.length>0);
    }catch(error){if(error.name!=='AbortError'&&alive&&current===revision){open(false);status.textContent=error.message+' Digite novamente para tentar.';}}
  };
  input.addEventListener('input',()=>{hidden.value='';input.setCustomValidity('Selecione uma peça da lista.');onChange(null);controller?.abort();revision++;rows=[];open(false);clearTimeout(timer);timer=setTimeout(lookup,250);});
  input.addEventListener('focus',lookup);input.addEventListener('blur',()=>open(false));
  input.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&!list.hidden){e.preventDefault();e.stopPropagation();open(false);}
    if((e.key==='ArrowDown'||e.key==='ArrowUp')&&rows.length){e.preventDefault();open(true);active=(active+(e.key==='ArrowDown'?1:-1)+rows.length)%rows.length;highlight();}
    if(e.key==='Enter'&&!list.hidden){e.preventDefault();if(active>=0)choose(rows[active]);else if(rows.length===1)choose(rows[0]);}
  });
  if(selected)choose(selected);else input.setCustomValidity('Selecione uma peça da lista.');
  return ()=>{alive=false;clearTimeout(timer);controller?.abort();};
}

export function avatarNode(user) {
  const node=document.createElement('span');node.className='avatar';node.textContent=user.name.trim().split(/\s+/).slice(0,2).map(s=>s[0]).join('').toUpperCase();
  if(user.has_avatar){const img=document.createElement('img');img.alt='';img.src='/api/users/'+user.id+'/avatar?v='+user.avatar_revision;img.addEventListener('error',()=>img.remove());node.append(img);}return node;
}
