// Reuse inert copies of the canonical local forms; business rules and transport
// remain in createClaims. No private response is interpreted as markup.
export function createClaimPresentation(refs){
 const {panel,form,fields,title,guitarDetail,kind,eventKind,date,body,items,save,close,mediaInput,addItem}=refs;
 const template=document.getElementById('formalClaimTemplates'),t=key=>globalThis.YGCI18n.t(key);
 const fieldKeys=[['nut','ui.nut_67c45877'],['frets','ui.frets_08aa1381'],['pickguard','ui.pickguard_280dde37'],['potentiometers','ui.potentiometers_5beb07c1'],['wiring','ui.wiring_72529059'],['neck','ui.neck_6b27a971'],['pickups','ui.pickups_088cf7e8'],['bridge','ui.bridge_3892e103'],['tuners','ui.tuners_1de22981'],['body','ui.body_6ccaa641'],['fingerboard','ui.fingerboard_92d85445'],['finish','ui.finish_a6c7a84b'],['weight','ui.weight_81d27ef6']];
 let category=null,menu=null,buttons=[];const customLabels=new Map();
 const categoryOf=value=>['specification','repair'].includes(value)?'spec':['damage','lost','theft'].includes(value)?'incident':value;
 function replace(clone,selector,input){const old=clone.querySelector(selector);if(!old)return;const oldId=old.id;if(input.tagName==='SELECT'){const labels=new Map([...old.options].map(option=>[option.value,option.textContent]));for(const option of input.options)if(labels.has(option.value))option.textContent=labels.get(option.value)}input.className=old.className;if(old.placeholder)input.placeholder=old.placeholder;old.replaceWith(input);for(const label of clone.querySelectorAll('label'))if(label.htmlFor===oldId)label.htmlFor=input.id}
 function mount(value,editing){
  for(const old of form.querySelectorAll('.modal-actions'))old.remove();
  category=categoryOf(value);const source=template.content.querySelector('#'+category+'ClaimModal .modal');
  if(!source)throw Error('Canonical Claim form unavailable.');
  const clone=source.cloneNode(true);for(const el of clone.querySelectorAll('[data-i18n]'))el.textContent=t(el.dataset.i18n);
  for(const el of clone.querySelectorAll('[data-i18n-placeholder]'))el.placeholder=t(el.dataset.i18nPlaceholder);
  title.textContent=clone.querySelector('h2').textContent;clone.querySelector('h2').remove();
  const summary=clone.querySelector('#'+category+'ClaimGuitar');guitarDetail.className=summary.className;guitarDetail.style.cssText=summary.style.cssText;summary.remove();
  panel.className=source.className;fields.style.cssText='border:0;padding:0;margin:0;min-width:0';form.style.margin='0';
  const actions=clone.querySelector('.modal-actions');actions.replaceChildren(close,save);close.className='secondary';close.dataset.uiAction='close';close.textContent=t('action.cancel');save.dataset.uiAction='primary';
  replace(clone,'#'+category+'ClaimDate',date);
  replace(clone,category==='spec'?'#specClaimBody':category==='media'?'#mediaClaimCaption':'#'+category+'ClaimDetail',body);
  if(category==='event')replace(clone,'#eventClaimKind',eventKind);
  if(category==='incident')replace(clone,'#incidentClaimKind',kind);
  if(category==='spec'){
   replace(clone,'#specClaimItems',items);menu=clone.querySelector('#specItemMenu');
   buttons=[clone.querySelector('#specKindSpecification'),clone.querySelector('#specKindRepair')];
   buttons.forEach((button,index)=>{button.onclick=()=>{kind.value=index?'repair':'specification';kind.onchange();render()}});
   const plus=clone.querySelector('.spec-add-button');plus.onclick=event=>{event.stopPropagation();renderMenu();menu.classList.toggle('open')};
  }else{menu=null;buttons=[]}
  if(category==='event')replace(clone,'#eventClaimImages',mediaInput);
  if(category==='media'){
   const slots=clone.querySelectorAll('.media-image-input');mediaInput.hidden=true;
   slots.forEach(input=>{input.accept=mediaInput.accept;input.onchange=()=>{const transfer=new DataTransfer();for(const slot of slots)for(const file of slot.files)transfer.items.add(file);mediaInput.files=transfer.files;mediaInput.onchange();let last=0;slots.forEach((slot,index)=>{if(slot.files.length)last=index+1});slots.forEach((slot,index)=>slot.parentElement.classList.toggle('visible',index<=last))}});
   clone.append(mediaInput);
  }
  if(!['event','media'].includes(category))mediaInput.hidden=true;
  fields.replaceChildren(...clone.childNodes);form.append(actions);
  if(category!=='incident'){kind.hidden=true;fields.append(kind)}else kind.hidden=false;
  if(category==='spec')renderMenu();
  render();
 }
 function renderMenu(){
  if(!menu)return;menu.replaceChildren();const used=new Set(refs.getItems().map(item=>item.field.value));
  const add=(field,label)=>{if(used.has(field))return;customLabels.set(field,label);refs.addField(field,'');menu.classList.remove('open');renderMenu()};
  for(const [field,key] of fieldKeys)if(!used.has(field)){const button=document.createElement('button');button.type='button';button.textContent=t(key);button.onclick=()=>add(field,t(key));menu.append(button)}
  const custom=document.createElement('button');custom.type='button';custom.textContent=t('ui.custom_c4e69d54');custom.onclick=()=>{const raw=window.prompt(t('ui.enter_a_specification_field_name_a6cb1fe1'));const field=raw?.trim().toLowerCase().replace(/\s+/g,'_');if(!field)return;if(used.has(field)){window.alert(t('ui.that_field_has_already_been_added_9e05c0d8'));return}add(field,raw.trim())};menu.append(custom);
 }
 function decorateField(row,field,value,remove){
  row.className='spec-item-row';field.type='hidden';const label=document.createElement('div');label.className='spec-item-label';label.textContent=fieldKeys.some(([key])=>key===field.value)?t(fieldKeys.find(([key])=>key===field.value)[1]):(customLabels.get(field.value)||field.value);
  remove.className='spec-item-remove';remove.dataset.uiAction='close';remove.textContent='×';value.placeholder='Value';row.replaceChildren(label,field,value,remove);
 }
 function render(){if(category==='media')mediaInput.hidden=true;for(const [index,button] of buttons.entries())button.classList.toggle('active',kind.value===(index?'repair':'specification'));if(category==='spec'&&!refs.getItems().length){items.replaceChildren();const empty=document.createElement('div');empty.className='sub';empty.textContent=t('ui.use_to_add_a_field_b047f788');items.append(empty)}}
 document.addEventListener('click',event=>{if(menu&&!event.target.closest('.spec-add-wrap'))menu.classList.remove('open')});
 return {mount,decorateField,render};
}
