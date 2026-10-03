/* Desktop table column sizing. Preferences stay in this browser. */
(() => {
  'use strict';
  const desktop = matchMedia('(min-width: 901px)');
  const tables = new Map();
  const minimum = 48;
  function remember(state) {
    try { localStorage.setItem(state.key, JSON.stringify(state.widths)); } catch (_) {}
  }
  function apply(state) {
    const enabled = desktop.matches && state.widths;
    state.table.classList.toggle('resizable-columns', desktop.matches);
    state.table.style.tableLayout = enabled ? 'fixed' : state.original.layout;
    state.table.style.width = enabled ? state.widths.reduce((a,b)=>a+b,0)+'px' : state.original.width;
    state.table.style.minWidth = enabled ? '0' : state.original.minWidth;
    state.cols.forEach((col,i)=>col.style.width=enabled?state.widths[i]+'px':'');
    state.handles.forEach(handle=>handle.hidden=!desktop.matches);
  }
  function measure(state) {
    if (!state.widths) state.widths=state.headers.map(h=>Math.max(minimum,h.getBoundingClientRect().width));
  }
  function resize(state,index,width) {
    state.widths[index]=Math.max(minimum,Math.min(4000,Math.round(width)));
    apply(state);
    state.handles[index].setAttribute('aria-valuenow',state.widths[index]);
  }
  function setup(table) {
    if(tables.has(table) || table.querySelector('colgroup'))return;
    const headers=[...table.querySelectorAll(':scope > thead > tr')];
    if(headers.length!==1)return;
    const cells=[...headers[0].cells];
    if(cells.length<2 || cells.some(h=>h.colSpan!==1||h.rowSpan!==1))return;
    const identity=table.id||table.tBodies[0]?.id||table.closest('[id]')?.id||'table';
    const labels=cells.map(h=>h.textContent.trim()).join('|');
    const key='ygc:columns:v1:'+location.pathname+':'+identity+':'+labels;
    const state={table,headers:cells,key,widths:null,cols:[],handles:[],original:{layout:table.style.tableLayout,width:table.style.width,minWidth:table.style.minWidth}};
    tables.set(table,state);
    try {
      const saved=JSON.parse(localStorage.getItem(key));
      if(Array.isArray(saved)&&saved.length===cells.length&&saved.every(w=>Number.isFinite(w)&&w>=minimum&&w<=4000))state.widths=saved;
    } catch (_) {}
    const group=document.createElement('colgroup');
    state.cols=cells.map(()=>group.appendChild(document.createElement('col')));
    table.prepend(group);
    cells.forEach((header,index)=>{
      const handle=document.createElement('span');handle.className='column-resize-handle';handle.tabIndex=0;
      handle.setAttribute('role','separator');handle.setAttribute('aria-orientation','vertical');handle.setAttribute('aria-label','Resize '+header.textContent.trim()+' column');handle.setAttribute('aria-valuemin',minimum);handle.setAttribute('aria-valuemax','4000');
      handle.addEventListener('click',e=>{e.stopPropagation();e.preventDefault()});
      handle.addEventListener('keydown',e=>{
        if(!desktop.matches||!['ArrowLeft','ArrowRight'].includes(e.key))return;
        e.preventDefault();e.stopPropagation();measure(state);resize(state,index,state.widths[index]+(e.key==='ArrowRight'?10:-10));remember(state);
      });
      handle.addEventListener('pointerdown',e=>{
        if(!desktop.matches||e.button!==0||e.pointerType==='touch')return;
        e.preventDefault();e.stopPropagation();measure(state);apply(state);
        const start=e.clientX,width=state.widths[index];handle.setPointerCapture(e.pointerId);
        document.body.classList.add('resizing-table-column');
        const move=event=>resize(state,index,width+event.clientX-start);
        const finish=()=>{handle.removeEventListener('pointermove',move);handle.removeEventListener('pointerup',finish);handle.removeEventListener('pointercancel',finish);handle.removeEventListener('lostpointercapture',finish);document.body.classList.remove('resizing-table-column');remember(state)};
        handle.addEventListener('pointermove',move);handle.addEventListener('pointerup',finish);handle.addEventListener('pointercancel',finish);handle.addEventListener('lostpointercapture',finish);
      });
      state.handles.push(handle);header.append(handle);
    });
    apply(state);
  }
  function scan(){
    for(const [table] of tables)if(!table.isConnected)tables.delete(table);
    document.querySelectorAll('table').forEach(setup);
  }
  let pending=false;
  new MutationObserver(()=>{if(pending)return;pending=true;requestAnimationFrame(()=>{pending=false;scan()})}).observe(document.body,{childList:true,subtree:true});
  desktop.addEventListener('change',()=>tables.forEach(apply));
  scan();
})();
