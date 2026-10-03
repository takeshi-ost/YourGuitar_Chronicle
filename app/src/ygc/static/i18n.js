/* Only UI-owned strings use this API. User content and protocol values never do. */
(() => {
  'use strict';
  const resources=globalThis.YGCI18nResources;
  const {manifest,catalogs}=resources;
  const defaultLocale=manifest.defaultLocale;
  const languages=manifest.languages;
  const preferenceKey='ygc_ui_language';
  let locale=defaultLocale;
  let changingLanguage=false;
  try{
    const saved=localStorage.getItem(preferenceKey);
    if(languages.some(language=>language.code===saved))locale=saved;
  }catch{/* The default language remains available when browser storage is unavailable. */}
  const own=(object,key)=>Object.prototype.hasOwnProperty.call(object||{},key);
  const escape=value=>String(value).replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  function template(key,params={},fallback=key){
    const english=own(catalogs[defaultLocale],key)?catalogs[defaultLocale][key]:undefined;
    let value=own(catalogs[locale],key)?catalogs[locale][key]:english;
    if(value&&typeof value==='object'){
      const category=new Intl.PluralRules(locale).select(Number(params.count));
      value=value[category]??value.other??(typeof english==='object'?english[category]??english.other:english);
    }
    return typeof value==='string'?value:typeof english==='string'?english:String(fallback);
  }
  function t(key,params={},fallback=key){
    return template(key,params,fallback).replace(/\{([A-Za-z][\w]*)\}/g,(match,name)=>own(params,name)?String(params[name]):match);
  }
  function html(key,params={},fallback=key){
    // Existing fragments contain encoded entities; decode only the template fallback.
    const encoded=template(key,params,fallback);
    const plain=encoded.replace(/&(amp|lt|gt|quot|apos|#39);/g,(_,entity)=>({amp:'&',lt:'<',gt:'>',quot:'"',apos:"'",'#39':"'"}[entity]));
    return escape(plain.replace(/\{([A-Za-z][\w]*)\}/g,(match,name)=>own(params,name)?String(params[name]):match));
  }
  function label(group,value){return t('values.'+group+'.'+String(value),{},String(value??''))}
  function number(value,options={}){return new Intl.NumberFormat(locale,options).format(value)}
  function date(value,options={}){
    const parsed=value instanceof Date?value:new Date(value);
    return Number.isNaN(parsed.getTime())?String(value??''):new Intl.DateTimeFormat(locale,options).format(parsed);
  }
  function errorMessage(payload,fallback='Request failed.'){
    if(Array.isArray(payload?.detail))return payload.detail.map(item=>item.msg).join(' / ');
    const detail=typeof payload?.detail==='string'?payload.detail:fallback;
    const key=payload?.message_key||(own(resources.errorKeys,detail)?resources.errorKeys[detail]:undefined);
    return key?t(key,payload.message_params||{},detail):detail;
  }
  function apply(root=document){
    const nodes=root.matches?.('[data-i18n], [data-i18n-placeholder], [data-i18n-title], [data-i18n-aria-label], [data-i18n-alt]')?[root]:[];
    if(root.querySelectorAll)nodes.push(...root.querySelectorAll('[data-i18n], [data-i18n-placeholder], [data-i18n-title], [data-i18n-aria-label], [data-i18n-alt]'));
    for(const node of nodes){
      if(node.dataset.i18n){const text=t(node.dataset.i18n);if(node.textContent!==text)node.textContent=text;}
      for(const attribute of ['placeholder','title','aria-label','alt']){
        const key=node.getAttribute('data-i18n-'+attribute);
        if(key){const text=t(key);if(node.getAttribute(attribute)!==text)node.setAttribute(attribute,text);}
      }
    }
  }
  function setLanguage(code){
    if(!languages.some(language=>language.code===code))throw new RangeError('Unsupported UI language');
    if(code===locale)return;
    // A reload rerenders JS-owned menus, charts and dialogs without translating user data.
    try{localStorage.setItem(preferenceKey,code)}catch{throw new Error('Language preference could not be saved.')}
    changingLanguage=true;
    location.reload();
  }
  const api={t,html,label,number,date,errorMessage,apply,setLanguage,
    get locale(){return locale},get changingLanguage(){return changingLanguage},
    get languages(){return languages.map(item=>({...item}))}};
  globalThis.YGCI18n=api;
  document.documentElement.lang=locale;
  document.documentElement.dir=languages.find(language=>language.code===locale)?.dir||'ltr';
  function mountLanguagePicker(){
    const nav=document.querySelector('header .page-nav');
    if(nav&&!nav.querySelector('[data-language-picker]')){
      const labelNode=document.createElement('label');labelNode.className='language-picker';
      const select=document.createElement('select');select.setAttribute('aria-label',t('settings.language',{},'Language'));
      select.dataset.languagePicker='';
      for(const language of languages){const option=document.createElement('option');option.value=language.code;option.textContent=language.label;select.append(option)}
      select.value=locale;select.addEventListener('change',()=>setLanguage(select.value));
      select.disabled=true;
      Promise.resolve(globalThis.YGCPageReady).catch(()=>{}).then(()=>{select.disabled=false});
      labelNode.append(select);nav.append(labelNode);
    }
  }
  function initialize(){
    apply();
    mountLanguagePicker();
    // Localize only explicitly annotated UI nodes added by a page renderer.
    new MutationObserver(records=>{
      for(const record of records)for(const node of record.addedNodes)if(node.nodeType===1)apply(node);
      mountLanguagePicker();
    }).observe(document.body,{childList:true,subtree:true});
  }
  if(document.readyState!=='complete')document.addEventListener('DOMContentLoaded',initialize,{once:true});else initialize();
})();
