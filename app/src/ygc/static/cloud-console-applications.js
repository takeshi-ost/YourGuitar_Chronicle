// Application image review is separate from Claim Verification and Owner consent.
export function createApplicationBrowser({request,authorized,onUnauthorized,onGuitar}){
  const root=document.getElementById('applicationBrowser'),t=(key,params={})=>globalThis.YGCI18n.t(key,params);
  const node=(tag,text,id)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(id)n.id=id;return n};
  const button=(key,id)=>{const n=node('button',t(key),id);n.type='button';return n};
  const label=(key,input)=>{const n=node('label',t(key));n.htmlFor=input.id;return n};
  const kinds=['acquire','listing'],statuses=['draft','pending','processing','error','accepted','rejected','closed','expired','cancelled'],operations=['accept','reject','retry','cancel'],roles=['closeup','overview','reference'];
  const revisionOK=value=>typeof value==='string'&&/^[a-f0-9]{32}$/.test(value),versionOK=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
  const countOK=value=>typeof value==='string'&&/^(0|[1-9][0-9]*)$/.test(value);
  const display=value=>value===null||value===undefined||value===''?'—':typeof value==='object'?JSON.stringify(value,null,2):String(value);
  const refreshButton=button('action.refresh','adminApplicationRefresh'),form=node('form',undefined,'adminApplicationSearchForm');
  const search=node('input',undefined,'adminApplicationSearch'),statusFilter=node('select',undefined,'adminApplicationStatusFilter'),kindFilter=node('select',undefined,'adminApplicationKindFilter'),searchSubmit=node('button',t('guitars.search_button'),'adminApplicationSearchSubmit');
  search.maxLength=200;search.type='search';searchSubmit.type='submit';
  for(const [select,values,prefix] of [[statusFilter,statuses,'applications.status_'],[kindFilter,kinds,'applications.']]){
    const all=node('option',t('admin_applications.all'));all.value='';select.append(all);
    for(const value of values){const option=node('option',t(prefix+value));option.value=value;select.append(option)}
  }
  form.className='application-filters';form.append(label('admin_applications.search',search),search,label('admin_applications.status',statusFilter),statusFilter,label('admin_applications.kind',kindFilter),kindFilter,searchSubmit);
  const toolbar=node('div'),heading=node('h2',t('admin_applications.heading'));toolbar.className='toolbar';toolbar.append(heading,refreshButton);
  const reviewNotice=node('p',undefined,'adminApplicationReviewNotice'),manual=node('p',undefined,'adminApplicationManualReview'),status=node('p',undefined,'adminApplicationStatus');status.setAttribute('role','status');reviewNotice.setAttribute('role','status');
  const table=node('table'),head=node('thead'),headRow=node('tr'),rows=node('tbody',undefined,'adminApplicationRows'),scroll=node('div');scroll.className='guitar-table-scroll';
  for(const key of ['applicant','product','serial','kind','status'])headRow.append(node('th',t('admin_applications.'+key)));
  headRow.append(node('th',t('action.detail')));head.append(headRow);table.append(head,rows);scroll.append(table);
  const previous=button('guitars.previous','adminApplicationPrevious'),next=button('guitars.next','adminApplicationNext');
  root.append(toolbar,node('p',t('admin_applications.scope')),form,reviewNotice,manual,scroll,status,node('span',t('guitars.page_size')+' '),previous,next);

  const dialog=node('dialog',undefined,'adminApplicationDialog'),title=node('h2',t('admin_applications.detail'),'adminApplicationTitle'),detailRefresh=button('action.refresh','adminApplicationDetailRefresh'),close=button('action.close','adminApplicationClose');
  dialog.setAttribute('aria-labelledby',title.id);
  const detailToolbar=node('div');detailToolbar.className='toolbar';detailToolbar.append(title,detailRefresh,close);
  const detailStatus=node('p',undefined,'adminApplicationDetailStatus'),detailReview=node('p',undefined,'adminApplicationDetailReview'),detailManual=node('p',undefined,'adminApplicationDetailManual'),detailFields=node('dl',undefined,'adminApplicationDetailFields');detailStatus.setAttribute('role','status');
  const photoWarning=node('p',undefined,'adminApplicationPhotoWarning'),ownerNotice=node('p',undefined,'adminApplicationOwnerNotice');photoWarning.setAttribute('role','status');
  const guitar=button('admin_applications.open_guitar','adminApplicationOpenGuitar'),photos=node('div',undefined,'adminApplicationPhotos'),photoViews={};photos.className='application-photos';
  for(const role of roles){
    const figure=node('figure'),caption=node('figcaption',t('applications.'+role)),view=button('admin_applications.view_photo','adminApplicationPhoto_'+role),image=node('img'),message=node('p');
    image.alt=t('applications.'+role);image.hidden=true;message.setAttribute('role','status');figure.append(caption,view,message,image);photos.append(figure);photoViews[role]={figure,view,image,message,epoch:0,url:null};
    view.onclick=()=>loadPhoto(role);
  }
  const diagnostics=node('section'),diagnosticNodes={};
  for(const key of ['result','received','report','product_details','product_observations','admin_review']){
    const section=node('details'),summary=node('summary',t('admin_applications.'+key)),pre=node('pre',undefined,'adminApplication'+key.split('_').map(part=>part[0].toUpperCase()+part.slice(1)).join(''));
    if(['report','admin_review'].includes(key))section.open=true;section.append(summary,pre);diagnostics.append(section);diagnosticNodes[key]=pre;
  }
  const historyTitle=node('h3',t('admin_applications.events')),events=node('ol',undefined,'adminApplicationEvents');
  const actionPanel=node('section'),operation=node('select',undefined,'adminApplicationOperation'),reason=node('textarea',undefined,'adminApplicationReason'),reviewAction=button('admin_applications.review_action','adminApplicationReviewAction'),confirm=button('admin_applications.confirm','adminApplicationConfirm'),confirmation=node('p',undefined,'adminApplicationConfirmation');
  reason.maxLength=2000;reason.required=true;confirmation.setAttribute('role','status');
  actionPanel.append(node('h3',t('admin_applications.action')),node('p',t('admin_applications.action_scope')),label('admin_applications.operation',operation),operation,label('admin_applications.reason',reason),reason,reviewAction,confirmation,confirm);
  dialog.append(detailToolbar,detailStatus,detailReview,detailManual,detailFields,ownerNotice,guitar,photoWarning,photos,diagnostics,historyTitle,events,actionPanel);document.body.append(dialog);

  // The authorization lifetime, list navigation, and open detail have separate
  // generations. Closing a dialog cannot cancel a delivered server mutation.
  let accountEpoch=0,listEpoch=0,detailEpoch=0,history=[null],cursor=null,query='',filterStatus='',filterKind='',listLoading=false,detailLoading=false,mutation=false,selected=null,pending=null,stale=false,reviewEnabled=null;
  const alive=epoch=>epoch===accountEpoch&&authorized();
  const sameDetail=(account,epoch,revision)=>alive(account)&&epoch===detailEpoch&&selected?.revision===revision&&dialog.open;
  const read=(path,options={},binary=false)=>request(path,{...options,cache:'no-store'},binary);
  function resetConfirmation(){pending=null;confirmation.textContent='';confirm.hidden=true;confirm.disabled=true}
  function clearPhotos(){
    for(const item of Object.values(photoViews)){item.epoch++;if(item.url)URL.revokeObjectURL(item.url);item.url=null;item.image.removeAttribute('src');item.image.hidden=true;item.message.textContent='';item.figure.hidden=true}
  }
  function clearDetail(){
    detailEpoch++;selected=null;detailLoading=false;stale=false;resetConfirmation();clearPhotos();reason.value='';operation.replaceChildren();detailFields.replaceChildren();events.replaceChildren();
    for(const pre of Object.values(diagnosticNodes))pre.textContent='';detailStatus.textContent=detailReview.textContent=detailManual.textContent=photoWarning.textContent=ownerNotice.textContent='';guitar.hidden=true;
  }
  function clear(){
    accountEpoch++;listEpoch++;listLoading=false;mutation=false;history=[null];cursor=null;query=filterStatus=filterKind='';reviewEnabled=null;
    globalThis.YGCOverlays.close(dialog);clearDetail();rows.replaceChildren();status.textContent=reviewNotice.textContent=manual.textContent='';search.value=statusFilter.value=kindFilter.value='';render();
  }
  function render(){
    const allowed=authorized();
    if(!allowed&&(selected||rows.children.length||listLoading||mutation)){clear();return}
    root.hidden=!allowed;
    for(const input of [search,statusFilter,kindFilter,searchSubmit,refreshButton])input.disabled=!allowed||mutation;
    previous.disabled=!allowed||mutation||listLoading||history.length<2;next.disabled=!allowed||mutation||listLoading||cursor===null;
    for(const b of rows.querySelectorAll('button'))b.disabled=!allowed||mutation;
    detailRefresh.disabled=!allowed||mutation||!selected;
    for(const input of [operation,reason,reviewAction])input.disabled=!allowed||mutation||detailLoading||stale||!selected?.admin_actions.length;
    reviewAction.disabled=reviewAction.disabled||!reason.value.trim();confirm.disabled=!allowed||mutation||detailLoading||stale||!pending;
    guitar.hidden=!selected?.individual_id;guitar.disabled=!allowed||mutation||detailLoading;
    for(const [role,item] of Object.entries(photoViews))item.view.disabled=!allowed||detailLoading||!selected?.photos?.includes(role);
  }
  function unauthorized(error,account){if(alive(account)&&[401,403].includes(error.status)){clear();onUnauthorized(error);return true}return false}
  const errorText=error=>t(error.status===409?'admin_applications.conflict':error.status===404?'admin_applications.missing':error.status===400?'admin_applications.invalid':'admin_applications.failed');
  function validateManual(value){if(!value||value.mode!=='external_mcp'||value.automatic_start!==false||typeof value.instructions!=='string')throw Error('Invalid manual review state')}
  function validateRow(row,detail=false){
    if(!row||!revisionOK(row.revision)||!versionOK(row.management_version)||!kinds.includes(row.request_kind)||!statuses.includes(row.status)||!Array.isArray(row.admin_actions)||row.admin_actions.some(op=>!operations.includes(op)))throw Error('Invalid application');
    for(const key of ['individual_id','claim_id'])if(row[key]!==null&&row[key]!==undefined&&!(typeof row[key]==='string'&&/^[1-9][0-9]*$/.test(row[key])))throw Error('Invalid identifier');
    if(detail){if(typeof row.review_enabled!=='boolean'||!Array.isArray(row.photos)||row.photos.some(role=>!roles.includes(role))||!Array.isArray(row.events))throw Error('Invalid application detail');validateManual(row.manual_review)}
  }
  function reviewText(enabled){return t(enabled?'admin_applications.review_on':'admin_applications.review_off')}
  async function refresh(){
    if(!authorized())return;const account=accountEpoch,current=++listEpoch;listLoading=true;cursor=null;rows.replaceChildren();status.textContent=t('cloud.working');render();
    const params=new URLSearchParams({q:query,status:filterStatus,kind:filterKind,limit:'25'});if(history.at(-1))params.set('after',history.at(-1));
    try{
      const result=await read('/api/admin/applications?'+params);
      if(!alive(account)||current!==listEpoch)return;
      if(!result||!countOK(result.total)||!Array.isArray(result.items)||result.items.length>25||!(result.next_after===null||revisionOK(result.next_after))||typeof result.review_enabled!=='boolean')throw Error('Invalid application page');
      validateManual(result.manual_review);for(const row of result.items)validateRow(row);
      cursor=result.next_after;reviewEnabled=result.review_enabled;reviewNotice.textContent=reviewText(reviewEnabled);manual.textContent=result.manual_review.instructions;
      for(const row of result.items){
        const tr=node('tr');
        for(const value of [row.applicant_name||row.applicant_id,row.product_name,row.serial,t('applications.'+row.request_kind),t('applications.status_'+row.status)])tr.append(node('td',display(value)));
        const cell=node('td'),view=button('action.detail');view.onclick=()=>detail(row.revision);cell.append(view);tr.append(cell);rows.append(tr);
      }
      status.textContent=t(result.total==='0'?'admin_applications.empty':'admin_applications.total',{count:result.total});
    }catch(error){if(!alive(account)||current!==listEpoch)return;if(!unauthorized(error,account)){rows.replaceChildren();cursor=null;status.textContent=errorText(error)}}
    finally{if(alive(account)&&current===listEpoch){listLoading=false;render()}}
  }
  function showDetail(row){
    validateRow(row,true);selected=row;stale=false;detailLoading=false;resetConfirmation();clearPhotos();reason.value='';detailFields.replaceChildren();events.replaceChildren();operation.replaceChildren();
    detailReview.textContent=reviewText(row.review_enabled);detailManual.textContent=row.manual_review.instructions;
    photoWarning.textContent=row.photos_unavailable?t('admin_applications.photos_unavailable'):'';ownerNotice.textContent=row.status==='accepted'&&row.verification_status==='unverified'?t('applications.owner_waiting'):'';
    const fields=['revision','request_kind','status','applicant_id','applicant_name','product_name','serial','individual_id','claim_id','verification_status','created_at','submitted_at','completed_at','acquisition_date','challenge','body','attempts','lease_until','error','paused_answers','management_version'];
    for(const key of fields){const value=key==='status'?t('applications.status_'+row[key]):key==='request_kind'?t('applications.'+row[key]):display(row[key]);detailFields.append(node('dt',t('admin_applications.field_'+key)),node('dd',value))}
    for(const [key,pre] of Object.entries(diagnosticNodes))pre.textContent=display(row[key]);
    for(const event of row.events){const li=node('li');li.append(node('p',[event.at,event.kind].filter(Boolean).join(' · ')),node('pre',display(event.note)));events.append(li)}
    if(!row.events.length)events.append(node('li',t('admin_applications.no_events')));
    for(const op of [...new Set(row.admin_actions)]){const option=node('option',t('admin_applications.operation_'+op));option.value=op;operation.append(option)}
    for(const [role,item] of Object.entries(photoViews)){item.figure.hidden=!row.photos.includes(role);item.view.textContent=t('admin_applications.view_photo')}
    render();
  }
  async function detail(revision){
    if(!authorized()||mutation||!revisionOK(revision))return;const account=accountEpoch;
    clearDetail();selected={revision,admin_actions:[],photos:[]};detailLoading=true;detailStatus.textContent=t('cloud.working');globalThis.YGCOverlays.open(dialog);render();
    const current=detailEpoch;
    try{
      const row=await read('/api/admin/applications/'+revision);
      if(!sameDetail(account,current,revision))return;if(row?.revision!==revision)throw Error('Mismatched application');
      showDetail(row);detailStatus.textContent='';
    }catch(error){if(!sameDetail(account,current,revision))return;if(!unauthorized(error,account)){detailLoading=false;stale=true;detailStatus.textContent=errorText(error);render()}}
  }
  async function loadPhoto(role){
    if(!authorized()||detailLoading||!selected?.photos.includes(role))return;
    const account=accountEpoch,current=detailEpoch,revision=selected.revision,item=photoViews[role],imageEpoch=++item.epoch;item.message.textContent=t('cloud.working');
    try{
      const blob=await read('/api/admin/applications/'+revision+'/photos/'+role,{},true);
      if(!sameDetail(account,current,revision)||imageEpoch!==item.epoch)return;
      if(item.url)URL.revokeObjectURL(item.url);item.url=URL.createObjectURL(blob);item.image.src=item.url;item.image.hidden=false;item.message.textContent='';
    }catch(error){if(!sameDetail(account,current,revision)||imageEpoch!==item.epoch)return;if(!unauthorized(error,account))item.message.textContent=t('admin_applications.photo_failed')}
  }
  function invalidateConfirmation(){resetConfirmation();render()}
  operation.onchange=reason.oninput=invalidateConfirmation;
  reviewAction.onclick=()=>{
    if(!authorized()||mutation||detailLoading||stale||!selected?.admin_actions.includes(operation.value))return;
    const text=reason.value.trim();if(!text||text.length>2000){detailStatus.textContent=t('admin_applications.reason_required');return}
    pending={revision:selected.revision,operation:operation.value,reason:text,expected_version:selected.management_version};
    confirmation.textContent=t('admin_applications.confirm_'+pending.operation)+'\n'+(selected.review_enabled?'':t('admin_applications.confirm_off')+'\n')+t('admin_applications.reason')+': '+text;
    confirm.textContent=t('admin_applications.confirm')+' · '+t('admin_applications.operation_'+pending.operation);confirm.hidden=false;render();
  };
  confirm.onclick=async()=>{
    if(!authorized()||mutation||detailLoading||stale||!pending||!selected)return;
    if(pending.reason!==reason.value.trim()||pending.operation!==operation.value||pending.revision!==selected.revision||pending.expected_version!==selected.management_version){invalidateConfirmation();return}
    const saved={...pending},account=accountEpoch,current=detailEpoch;resetConfirmation();mutation=true;detailStatus.textContent=t('admin_applications.saving');render();
    try{
      const row=await read('/api/admin/applications/'+saved.revision+'/decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operation:saved.operation,reason:saved.reason,expected_version:saved.expected_version})});
      if(!alive(account))return;validateRow(row,true);if(row.revision!==saved.revision)throw Error('Mismatched application');
      if(sameDetail(account,current,saved.revision)){showDetail(row);detailStatus.textContent=t('admin_applications.saved')}
      await refresh();if(alive(account))status.textContent=t('admin_applications.saved')+' '+status.textContent;
    }catch(error){
      if(!alive(account))return;if(unauthorized(error,account))return;
      if(sameDetail(account,current,saved.revision)){stale=true;detailStatus.textContent=errorText(error)+' '+t('admin_applications.refresh_before_retry');resetConfirmation()}
      else status.textContent=errorText(error)+' '+t('admin_applications.refresh_before_retry');
    }finally{if(alive(account)){mutation=false;render()}}
  };
  close.onclick=()=>globalThis.YGCOverlays.close(dialog);dialog.addEventListener('ygc:closed',()=>{clearDetail();render()});
  detailRefresh.onclick=()=>{if(selected)return detail(selected.revision)};
  guitar.onclick=()=>{if(!authorized()||mutation||!selected?.individual_id)return;const id=selected.individual_id;globalThis.YGCOverlays.close(dialog);onGuitar?.(id)};
  form.onsubmit=event=>{event.preventDefault();if(!authorized()||mutation)return;query=search.value.trim();filterStatus=statusFilter.value;filterKind=kindFilter.value;history=[null];refresh()};
  refreshButton.onclick=()=>{if(!mutation){history=[null];refresh()}};
  next.onclick=()=>{if(!mutation&&!listLoading&&cursor!==null){history.push(cursor);refresh()}};
  previous.onclick=()=>{if(!mutation&&!listLoading&&history.length>1){history.pop();refresh()}};
  render();return {render,clear,refresh,detail};
}
