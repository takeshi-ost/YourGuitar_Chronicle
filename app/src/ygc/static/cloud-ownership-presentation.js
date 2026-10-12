// Canonical Transfer/Release entry markup; the controller retains all authority,
// stale-revision, fresh-read and unknown-result recovery checks.
export function createOwnershipPresentation({panel,title,detail,form,fields,kind,date,previous,body,transferFields,releaseFields,query,search,candidates,searchMore,selectedText,review,close,confirm,check,acknowledge,reload,message,saved,evidence,accept,decline,cancel}){
 const t=key=>globalThis.YGCI18n.t(key);let mounted=false,entryActions=null,reviewMounted=false;
 function mount(guitar){
  reviewMounted=false;close.style.cssText='';panel.setAttribute('aria-labelledby','ownershipTitle');panel.className='modal';panel.style.cssText='';title.hidden=detail.hidden=saved.hidden=evidence.hidden=false;message.className='';
  const source=document.getElementById('formalClaimTemplates').content.querySelector('#ownershipClaimModal .modal'),clone=source.cloneNode(true);
  for(const el of clone.querySelectorAll('[data-i18n]'))el.textContent=t(el.dataset.i18n);
  for(const el of clone.querySelectorAll('[data-i18n-placeholder]'))el.placeholder=t(el.dataset.i18nPlaceholder);
  title.textContent=clone.querySelector('h2').textContent;clone.querySelector('h2').remove();
  const summary=clone.querySelector('#ownershipClaimGuitar');detail.className=summary.className;detail.style.cssText=summary.style.cssText;detail.textContent=[guitar.manufacturer,guitar.model].filter(Boolean).join(' ')+(guitar.serial_number?' / '+guitar.serial_number:'');summary.remove();
  clone.querySelector('#ownershipClaimFixedTag').remove();kind.style.display='block';
  const replace=(id,input)=>{const old=clone.querySelector('#'+id);if(old.tagName==='INPUT')input.type=old.type;input.className=old.className;input.style.cssText=old.style.cssText;if(old.placeholder)input.placeholder=old.placeholder;old.replaceWith(input);for(const label of clone.querySelectorAll('label'))if(label.htmlFor===id)label.htmlFor=input.id};
  replace('ownershipClaimKind',kind);kind.style.display='block';replace('ownershipClaimDate',date);replace('ownershipClaimPrevious',previous);replace('ownershipClaimBody',body);
  const transfer=clone.querySelector('#transferRecipientRow');replace('transferRecipientSearch',query);query.nextElementSibling.replaceWith(search);search.textContent=t('ui.search_49c266ba');
  replace('transferSearchResults',candidates);replace('transferSelectedRecipient',selectedText);replace('transferSearchMore',searchMore);searchMore.textContent=t('ui.more_candidates_d4148527');transferFields.className=transfer.className;transferFields.replaceChildren(...transfer.childNodes);transfer.replaceWith(transferFields);
  releaseFields.style.display='contents';releaseFields.replaceChildren(date.closest('.form-row'),previous.closest('.form-row'),body.closest('.form-row'));transferFields.before(releaseFields);
  const actions=clone.querySelector('.modal-actions');entryActions=actions;actions.replaceChildren(close,review);close.textContent=t('action.cancel');close.className='secondary';close.dataset.uiAction='close';review.textContent=t('ui.add_claim_62b52157');review.dataset.uiAction='primary';
  fields.style.cssText='display:contents;border:0;padding:0;margin:0;min-width:0';form.style.margin='0';fields.replaceChildren(...clone.childNodes);form.replaceChildren(fields,actions);
  // Empty protocol/recovery states never change normal form geometry.
  panel.replaceChildren(title,detail,form,saved,evidence,message,confirm,check,acknowledge,reload,accept,decline,cancel);
  mounted=true;update(false,false);
 }
 function update(isTransfer,uncertain){
  if(reviewMounted)return;
  if(!mounted)return;
  if(!isTransfer){for(const row of releaseFields.children)row.hidden=kind.value==='transfer';reload.hidden=!uncertain;confirm.hidden=true}
  else{reload.hidden=false;panel.append(close);close.textContent=t('action.close')}
  if(!isTransfer){entryActions.prepend(close);close.textContent=t('action.cancel')}
 }
 function mountReview(row){
  const source=document.getElementById('formalClaimTemplates').content.querySelector('#transferReviewDialog'),clone=source.cloneNode(true);panel.style.cssText=source.style.cssText;panel.className='modal';
  for(const el of clone.querySelectorAll('[data-i18n]'))el.textContent=t(el.dataset.i18n);
  const content=clone.querySelector('#transferReviewBody'),who=document.createElement('strong');
  for(const [index,person] of [row.from_user,row.to_user].entries()){if(index)who.append(' → ');const link=document.createElement('a');link.href='/ui/members/'+person.id;link.textContent=person.display_name||'—';who.append(link)}
  const info=document.createElement('p');info.textContent=[row.individual.manufacturer,row.individual.model,row.individual.serial_number].filter(Boolean).join(' / ')+' · #'+row.individual_id+' · '+row.state;
  const evidenceText=document.createElement('p');evidenceText.className='sub';evidenceText.textContent=row.acceptance?t('ui.info_transfer_accepted_on_ba2319c7')+' '+new Date(row.acceptance.accepted_at).toLocaleString(globalThis.YGCI18n.locale||'en-US'):t('ui.accept_confirms_this_ownership_transfer_verification_remai_886c7b21');content.replaceChildren(who,info,evidenceText);
  const status=clone.querySelector('#transferReviewStatus');message.className='sub';status.replaceWith(message);
  clone.querySelector('#transferReviewActions').replaceChildren(accept,decline,cancel);accept.textContent='Accept';decline.textContent='Decline';cancel.textContent='Cancel';accept.dataset.uiAction='primary';cancel.dataset.uiAction='danger';
  const exit=clone.querySelector('button[data-ui-action="close"]');close.style.cssText=exit.style.cssText;close.textContent=t('action.close');exit.replaceWith(close);
  panel.replaceChildren(...clone.childNodes,check,acknowledge);panel.setAttribute('aria-labelledby','transferReviewTitle');reviewMounted=true;
 }
 return {mount,update,mountReview};
}
