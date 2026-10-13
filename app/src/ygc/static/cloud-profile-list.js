/* Authenticated adapter around the canonical local profile-list presentation.
   Callers own loading, identity invalidation and actions; this module owns no API. */
import {createFavoriteControl,createFavoriteSnapshotReader} from './cloud-account-favorites.js';
const presentations=new Set();
export function selectProfileGuitar(id){for(const view of presentations)view.select(id)}
export function createProfileList({section,title,list,onSelect,guitarHref,actions,auth,state,busy,refreshButton=null,columnsOverride=null,numericId=true,renderCell=null,filterText=null,sharedSelection=true,numericFields=['claim_count'],initialSort='id',initialDirection=1,filterLabel=null,emptyLabel=null,noMatchLabel=null}){
  const favorites=new Map(),readFavorite=createFavoriteSnapshotReader({auth,state});
  const t=key=>globalThis.YGCI18n.t(key),columns=columnsOverride||globalThis.YGCProfileList.columns();
  section.classList.add('panel','profile-panel','profile-list-panel','page-section');
  const toolbar=document.createElement('div');toolbar.className='toolbar';
  const filter=document.createElement('input');filter.placeholder=filterLabel||t('ui.maker_model_finish_year_serial_c99806fd');filter.setAttribute('aria-label',filter.placeholder);
  title.dataset.countItems='#'+list.id+' > tr.clickable';title.dataset.countPending='true';toolbar.append(title,filter);if(refreshButton){refreshButton.hidden=false;toolbar.append(refreshButton)}
  const wrap=document.createElement('div');wrap.className='table-wrap';
  const table=document.createElement('table'),head=document.createElement('thead'),headers=document.createElement('tr');
  const indicators=new Map();let rows=[],key=initialSort,direction=initialDirection,selected=null;
  for(const [field,label] of columns){const th=document.createElement('th');th.textContent=label;
    if(field==='favorite'){th.className='favorite-cell';th.setAttribute('aria-label',t('ui.favorite_ea713ecd'))}
    else if(field!=='action'){th.className='sortable';th.tabIndex=0;const indicator=document.createElement('span');indicator.className='sort-indicator';th.append(indicator);indicators.set(field,{th,indicator});const sort=()=>{if(key===field)direction*=-1;else{key=field;direction=1}render();wrap.scrollTop=0};th.onclick=sort;th.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();sort()}}}headers.append(th);
  }
  head.append(headers);table.append(head,list);wrap.append(table);section.append(toolbar,wrap);
  const normalize=(row,field)=>field==='id'&&numericId?BigInt(row.id):numericFields.includes(field)?BigInt(row[field]||0):String(row[field]??'').toLowerCase();
  function render(){
    const query=filter.value.trim().toLowerCase();const visible=rows.filter(row=>(filterText?filterText(row):[row.manufacturer,row.model,row.finish,row.year,row.serial_number].join(' ')).toLowerCase().includes(query)).sort((a,b)=>{const av=normalize(a,key),bv=normalize(b,key);return av<bv?-direction:av>bv?direction:numericId?(BigInt(a.id)<BigInt(b.id)?-1:BigInt(a.id)>BigInt(b.id)?1:0):String(a.id).localeCompare(String(b.id))});
    list.replaceChildren();for(const row of visible){const tr=document.createElement('tr');tr.className='clickable'+(row.id===selected?' selected':'');tr.dataset.guitarId=row.id;tr.dataset.favoriteId=row.id;
      const select=()=>{if(busy?.())return;if(sharedSelection)selectProfileGuitar(row.id);else view.select(row.id);onSelect?.(row.id)};tr.onclick=e=>{if(!e.target.closest('a,button,input,select'))select()};
      for(const [field] of columns){const td=document.createElement('td');if(renderCell?.(row,field,td)){}else if(field==='favorite'){td.className='favorite-cell';let item=favorites.get(row.id);if(!item){const root=document.createElement('span');const control=createFavoriteControl({root,compact:true,idPrefix:list.id+'_'+row.id+'_',auth,state,t,busy});item={root,control};favorites.set(row.id,item);void control.select(row.id,readFavorite).catch(()=>{})}td.append(item.root)}else if(field==='id'){const link=document.createElement('a');link.href=guitarHref(row.id);link.textContent=row.id;link.onclick=e=>{if(e.button>0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();select()};td.append(link)}else{td.textContent=row[field]??'';if(field==='serial_number')td.className='mono'}tr.append(td)}
      actions?.(row,tr);list.append(tr);
    }
    if(!visible.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=columns.length;td.className='sub';td.textContent=query?(noMatchLabel||t('ui.no_matching_guitars_eb9458e7')):(emptyLabel||t('ui.no_guitars_yet_9cac0d7d'));tr.append(td);list.append(tr)}
    for(const [field,{th,indicator}] of indicators){indicator.textContent=key===field?(direction===1?'▲':'▼'):'';th.setAttribute('aria-sort',key===field?(direction===1?'ascending':'descending'):'none')}
    globalThis.YGCProfileList.sizeGuitarList(section,rows.length);
  }
  filter.oninput=render;
  const view={setRows(value){title.dataset.countPending='false';rows=value;render()},clear(){title.dataset.countPending='true';rows=[];for(const item of favorites.values())item.control.clear();favorites.clear();list.replaceChildren()},select(id){selected=id;for(const row of list.children)row.classList.toggle('selected',row.dataset.guitarId===id)},renderControls(){for(const item of favorites.values())item.control.render()},filter};
  if(sharedSelection)presentations.add(view);return view;
}
