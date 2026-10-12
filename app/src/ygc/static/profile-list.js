/* Canonical profile list columns and unfiltered height measurement, shared by
   local and authenticated Web adapters. No requests, identity or data projection. */
(function(){
function columns(){
return [['id','ID'],['favorite','♡'],['manufacturer',(globalThis.YGCI18n?.t("ui.maker_287f4955",{},"Maker")??"Maker")],['model',(globalThis.YGCI18n?.t("ui.model_5e2c614c",{},"Model")??"Model")],['finish',(globalThis.YGCI18n?.t("ui.finish_a6c7a84b",{},"Finish")??"Finish")],['year',(globalThis.YGCI18n?.t("ui.year_89f68325",{},"Year")??"Year")],['serial_number',(globalThis.YGCI18n?.t("ui.serial_8ea09493",{},"Serial")??"Serial")],['claim_count',(globalThis.YGCI18n?.t("ui.claims_1c85c122",{},"Claims")??"Claims")]];
}
function sizeGuitarList(panel,count){
  if(!panel)return;
  panel.dataset.totalItems=String(count);
  if(!panel._sizeObserver&&typeof ResizeObserver==='function'){
    panel._sizeObserver=new ResizeObserver(()=>measureGuitarList(panel));
    panel._sizeObserver.observe(panel);
    for(const child of panel.children)if(!child.classList.contains('table-wrap'))panel._sizeObserver.observe(child);
  }
  measureGuitarList(panel);
}
function measureGuitarList(panel){
  const wrap=panel.querySelector('.table-wrap'),table=wrap?.querySelector('table');
  if(!table)return;
  const probe=table.cloneNode(false);
  probe.removeAttribute('id');
  probe.style.cssText='position:absolute;visibility:hidden;pointer-events:none;width:'+table.getBoundingClientRect().width+'px';
  probe.innerHTML=("<tbody><tr><td>0</td><td class=\"favorite-cell\"><button class=\"favorite-button\">♡</button></td><td>"+(globalThis.YGCI18n?.html("ui.maker_287f4955",{},"Maker")??"Maker")+"</td><td>"+(globalThis.YGCI18n?.html("ui.model_5e2c614c",{},"Model")??"Model")+"</td><td>"+(globalThis.YGCI18n?.html("ui.finish_a6c7a84b",{},"Finish")??"Finish")+"</td><td>"+(globalThis.YGCI18n?.html("ui.year_89f68325",{},"Year")??"Year")+"</td><td>"+(globalThis.YGCI18n?.html("ui.serial_8ea09493",{},"Serial")??"Serial")+"</td><td>0</td></tr></tbody>");
  wrap.append(probe);
  const rowHeight=probe.rows[0].getBoundingClientRect().height;
  probe.remove();
  const css=getComputedStyle(panel),wc=getComputedStyle(wrap);
  const px=v=>parseFloat(v)||0;
  let height=px(css.paddingTop)+px(css.paddingBottom)+px(css.borderTopWidth)+px(css.borderBottomWidth);
  for(const child of panel.children){
    if(child===wrap||getComputedStyle(child).display==='none')continue;
    const style=getComputedStyle(child);
    height+=child.getBoundingClientRect().height+px(style.marginTop)+px(style.marginBottom);
  }
  height+=(table.tHead?.getBoundingClientRect().height||0)+rowHeight*Math.max(1,Number(panel.dataset.totalItems)||0)+px(wc.borderTopWidth)+px(wc.borderBottomWidth)+2;
  panel.style.setProperty('--list-content-height',Math.ceil(height)+'px');
}
globalThis.addEventListener('resize',()=>document.querySelectorAll('[data-total-items]').forEach(measureGuitarList));
document.fonts?.ready.then(()=>document.querySelectorAll('[data-total-items]').forEach(measureGuitarList));

globalThis.YGCProfileList={columns,sizeGuitarList};
})();
