// Private controls decorate the selected guitar only. The public DTO is unchanged.
export function createDetailClaimActions({state,busy,owners,claims}){
 const t=key=>globalThis.YGCI18n.t(key);let epoch=0,snapshot=null,root=null,pending=Promise.resolve();
 const actor=()=>state()?.identity?.email_verified===true?state()?.user?.app_user_id:null;
 function clear(){epoch++;snapshot=null;root=null;document.querySelectorAll('[data-private-claim-action]').forEach(el=>el.remove())}
 function render(){for(const control of document.querySelectorAll('[data-private-claim-action]'))if('disabled' in control)control.disabled=busy()||!actor()||control.dataset.readonly==='true'}
 function decorate(card,id,guitar){
  if(!snapshot||snapshot.guitar!==guitar||snapshot.actor!==actor()||!card.isConnected)return;
  card.querySelectorAll('[data-private-claim-action]').forEach(el=>el.remove());
  const current=snapshot,valid=()=>snapshot===current&&actor()===current.actor&&card.isConnected&&!busy();
  const owner=current.owners.find(row=>row.id===id),own=current.own.find(row=>row.id===id),head=card.querySelector('.claim-head');
  if(owner&&head&&!own){
   const select=document.createElement('select');select.className='claim-response-select';select.dataset.privateClaimAction='verify';select.dataset.readonly=String(!owner.can_write);select.setAttribute('aria-label',t('owner.decision'));
   for(const value of ['positive','negative','unverified']){const option=document.createElement('option');option.value=value;option.textContent=t('chronicle.'+value);select.append(option)}select.value=owner.verification_status;
   select.onchange=()=>{if(!valid()||!owner.can_write)return;const value=select.value;select.value=owner.verification_status;const opener=root?.querySelector('[data-claim-id="'+id+'"] button')||select;const popup=document.getElementById('claimPopupModal');if(popup)globalThis.YGCOverlays.close(popup);return owners.openOwner(guitar,id,value,opener)};
   head.querySelector('.claim-event-date')?.before(select);
  }
  if(own&&head){const footer=card.querySelector('.claim-footer')||document.createElement('div');footer.className='claim-footer';const edit=document.createElement('button');edit.type='button';edit.className='claim-vote';edit.dataset.privateClaimAction='edit';edit.textContent=t(own.status==='active'?'claims.edit':'claims.view');edit.onclick=()=>{if(!valid())return;const popup=document.getElementById('claimPopupModal');if(popup)globalThis.YGCOverlays.close(popup);return claims.openEdit(guitar,id)};footer.append(edit);if(!footer.parentNode)card.append(footer)}
  render();
 }
 async function load(container,guitar){
  const version=++epoch,identity=actor();document.querySelectorAll('[data-private-claim-action]').forEach(el=>el.remove());snapshot=null;root=container;if(!identity)return;
  pending=(async()=>{
   const results=await Promise.allSettled([owners.readActions(guitar),claims.readActions(guitar)]);
   if(epoch!==version||actor()!==identity||root!==container||!container.isConnected)return;
   snapshot={guitar,actor:identity,owners:results[0].status==='fulfilled'?results[0].value:[],own:results[1].status==='fulfilled'?results[1].value:[]};
   for(const row of snapshot.own)if(!container.querySelector('[data-claim-id="'+row.id+'"]')){
    const card=document.createElement('div');card.className='claim-card claim-type-'+row.claim_type;card.dataset.claimId=row.id;card.dataset.privateClaimAction='own-card';const head=document.createElement('div'),badge=document.createElement('span'),date=document.createElement('span');head.className='claim-head';badge.className='claim-badge';badge.textContent=t('claims.'+row.claim_type);date.className='claim-event-date';date.textContent=globalThis.YGCOwnershipPresentation.displayEventDate(row.occurred_at);head.append(badge,date);card.append(head);container.append(card);
   }
   for(const card of container.querySelectorAll('[data-claim-id]'))decorate(card,card.dataset.claimId,guitar);
   if(results.some(r=>r.status==='rejected')){const status=document.createElement('p'),retry=document.createElement('button');status.dataset.privateClaimAction='status';status.setAttribute('role','status');status.textContent=t('claims.failed');retry.type='button';retry.textContent=t('action.refresh');retry.onclick=()=>{status.remove();void load(container,guitar)};status.append(retry);container.append(status)}
  })();await pending;
 }
 async function popup(card,id,guitar){await pending;decorate(card,id,guitar)}
 return {load,popup,render,clear};
}
