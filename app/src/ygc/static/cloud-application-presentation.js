// The exact local pure form formatters are served from their canonical source.
export function createApplicationPresentation({panel,title,detail,form,fields,photos,inputs,files,previews,save,submit,close,cancel,retry,replacePhotos,dialogRefresh,keep}){
 const t=key=>globalThis.YGCI18n.t(key),html=()=>globalThis.YGCOwnershipPresentation;
 const actions=document.createElement('div');actions.className='modal-actions ownership-request-actions';panel.append(actions);
 fields.style.cssText=photos.style.cssText='border:0;padding:0;margin:0;min-width:0;display:contents';
 function mount(kind,row){
  panel.className='modal ownership-request-modal';
  title.textContent=t(kind==='listing'?'ui.listing_request_32432123':'ui.acquire_request_c11c1e49');
  const state=document.createElement('small');state.className='ownership-request-status';state.textContent='- '+(row?html().acquireStatusLabel({...row,request_kind:kind}):t('ui.awaiting_details_041b5dbf'));title.append(' ',state);
  const draft=!row||row.status==='draft';
  if(draft){
   const content=document.createElement('div');
   content.innerHTML=(kind==='listing'?html().listingMetadataFields(row?.payload||{},Boolean(row)):'')+html().ownershipChallengeBox(row)+html().ownershipEvidenceFields({listing:kind==='listing',issued:Boolean(row),date:row?.acquisition_date||inputs.occurred_at.input.value,body:row?.body||inputs.body.input.value});
   // The canonical Listing notice explains that the accepted overview becomes
   // the initial public representative image. Close-ups remain private.
   const mapping={manufacturer:'guitarMaker',model:'guitarModel',year:'guitarYear',finish:'guitarFinish',serial_number:'guitarSerial',occurred_at:'acquireDate',body:'acquireBody'};
   for(const [key,id] of Object.entries(mapping)){const old=content.querySelector('#'+id);if(!old)continue;const input=inputs[key].input;input.readOnly=old.readOnly;input.hidden=false;input.disabled=false;input.value=old.value;inputs[key].label=old.parentElement;old.replaceWith(input)}
   photos.replaceChildren();for(const [role,id] of [['closeup','acquireCloseup'],['overview','acquireOverview']]){const old=content.querySelector('#'+id),label=old.parentElement;old.replaceWith(files[role]);files[role].hidden=false;label.append(previews[role].view,previews[role].image);photos.append(label)}
   const grid=content.querySelectorAll('.modal-grid');grid[grid.length-1].append(photos);photos.style.display='contents';
   fields.replaceChildren(...content.childNodes);form.hidden=false;
   inputs.individual_id.input.hidden=true;fields.append(inputs.individual_id.input);
   detail.textContent=!row?t('ui.1_enter_details_and_generate_a_challenge_2_photograph_the__5c8a6d06'):(kind==='acquire'?t('ui.individual_056c49a5')+(row.individual_id||inputs.individual_id.input.value):[row.payload?.manufacturer,row.payload?.model].filter(Boolean).join(' '))+' / '+(row.unsaved?t('ui.not_saved_22b3467c'):row.revision);
  }
  actions.replaceChildren(save,submit,dialogRefresh,retry,...(replacePhotos?[replacePhotos]:[]),keep,close,cancel);save.textContent=t('ui.generate_challenge_321afa1e');save.setAttribute('form',form.id);submit.textContent=t('ui.submit_155f816c');submit.dataset.uiAction='primary';keep.textContent=t('ui.keep_request_95011d14');keep.dataset.uiAction='primary';close.textContent=t('action.cancel');close.className='secondary';close.dataset.uiAction='close';cancel.textContent=t('ui.cansel_request_dfc8109a');cancel.dataset.uiAction='danger';dialogRefresh.textContent=t('ui.reflesh_7228c81b');
  update(kind,row);
 }
 function update(kind,row){
  const draft=!row||row.status==='draft';
  form.hidden=!draft;photos.hidden=!draft;save.hidden=Boolean(row)||kind!=='listing';submit.hidden=!draft;submit.disabled=submit.disabled||!row;keep.hidden=!draft;keep.disabled=keep.disabled||(!row&&kind==='acquire');
  dialogRefresh.hidden=kind==='acquire';cancel.hidden=!row||row.unsaved||['accepted','rejected','cancelled','closed','expired'].includes(row.status);
  if(kind==='acquire'&&row&&row.status!=='draft'){for(const action of [cancel,retry,keep,dialogRefresh])action.hidden=true;close.textContent='OK'}
  for(const role of ['closeup','overview']){files[role].disabled=files[role].disabled||!row;previews[role].view.hidden=!row?.photos?.includes(role)}
 }
 return {mount,update,confirm:(title,message)=>ownershipConfirmation(t(title),t(message),title==='ui.cansel_request_dfc8109a'),closeConfirmation:()=>closeOwnershipConfirmation()};
}
let confirmation=null,resolveConfirmation=null;
export function closeOwnershipConfirmation(value=false){const done=resolveConfirmation;resolveConfirmation=null;if(confirmation)globalThis.YGCOverlays.close(confirmation);done?.(value)}
export function ownershipConfirmation(title,message,danger=false){
 if(resolveConfirmation)return Promise.resolve(false);
 const t=key=>globalThis.YGCI18n.t(key);
 if(!confirmation){
  confirmation=document.getElementById('formalClaimTemplates').content.querySelector('#ownershipConfirmModal').cloneNode(true);document.body.append(confirmation);
  confirmation.querySelector('#ownershipConfirmSubmit').onclick=()=>closeOwnershipConfirmation(true);confirmation.querySelector('button.secondary').onclick=()=>closeOwnershipConfirmation();
  confirmation.addEventListener('ygc:closed',()=>closeOwnershipConfirmation());
 }
 confirmation.querySelector('#ownershipConfirmTitle').textContent=title;confirmation.querySelector('#ownershipConfirmMessage').textContent=message;
 const button=confirmation.querySelector('#ownershipConfirmSubmit');button.textContent=t('ui.confirm_eebdd24a');button.dataset.uiAction=danger?'danger':'primary';confirmation.querySelector('button.secondary').textContent=t('ui.back_76900f1b');
 return new Promise(resolve=>{resolveConfirmation=resolve;globalThis.YGCOverlays.open(confirmation)})
}
