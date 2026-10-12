import {worldCountries} from './cloud-world-geometry.js';

const claimTypes=['listing','ownership','identity_correction','specification','repair','incident','event','media'];
const palette=['#d0a45d','#66c58a','#6fa8dc','#c27ba0','#e07171','#8e7cc3','#76a5af','#f6b26b','#93c47d','#a4c2f4','#999999'];
const words={
  en:{discovery:'New Discovery',statistics:'Statistics',map:'World Map',models:'Model Distribution',years:'Year Distribution',listings:'Listings — Last 30 Days (UTC)',locations:'Current Product Locations',refresh:'Refresh',loading:'Loading…',empty:'No recent activity.',noModels:'No model data.',noYears:'No single-year data.',noCountries:'No public country data.',failed:'Could not load this section. Try Refresh.',restricted:'Viewing is temporarily restricted.',session:'Your session could not be verified. Try Refresh or sign in again.',added:'has been newly added to the list!',updated:'has a new {kind} record!',coverage:'Countries with public location data only.',counts:'Country counts',chartCounts:'Show counts',count:'{count} guitars',mapLabel:'World map showing guitar counts by country',more:'More guitars',other:'Other',unknown:'Unknown',country:'Country',value:'Count',date:'Date',year:'Year',model:'Model',listing:'Listing',ownership:'Ownership',identity_correction:'Identity correction',specification:'Specification',repair:'Repair',incident:'Incident',event:'Event',media:'Media'},
  ja:{discovery:'新着ギター',statistics:'統計',map:'世界地図',models:'モデル分布',years:'年式分布',listings:'掲載数 — 直近30日間（UTC）',locations:'現在のギター所在地',refresh:'更新',loading:'読み込み中…',empty:'新着情報はありません。',noModels:'モデルのデータはありません。',noYears:'単一年式のデータはありません。',noCountries:'公開されている国のデータはありません。',failed:'この項目を取得できませんでした。「更新」をお試しください。',restricted:'現在、閲覧が一時的に制限されています。',session:'セッションを確認できません。「更新」または再サインインをお試しください。',added:'が新しく登録されました！',updated:'に新しい{kind}の記録が追加されました！',coverage:'公開できる所在地があるギターのみを国別に集計しています。',counts:'国別件数',chartCounts:'件数表を表示',count:'{count}本',mapLabel:'ギターの国別件数を示す世界地図',more:'件数が多い',other:'その他',unknown:'不明',country:'国',value:'件数',date:'日付',year:'年式',model:'モデル',listing:'掲載',ownership:'所有権',identity_correction:'個体情報の訂正',specification:'仕様',repair:'修理',incident:'事故・被害',event:'イベント',media:'メディア'}
};
const count=value=>typeof value==='string'&&/^(0|[1-9][0-9]{0,18})$/.test(value)&&BigInt(value)<2n**63n;
const id=value=>count(value)&&value!=='0';
const text=(value,max)=>typeof value==='string'&&value.length<=max&&!/[\u0000-\u001f\u007f]/.test(value);
const array=(value,max)=>Array.isArray(value)&&value.length<=max;
const day=value=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value;
export function validateDiscoveries(data){
  if(!data||!array(data.items,200))throw Error('Invalid discoveries');
  const seen=new Set();
  return {items:data.items.map(row=>{
    if(!row||!id(row.id)||seen.has(row.id)||!['claim','discovery'].includes(row.activity_type)||
      (row.activity_type==='claim'?!claimTypes.includes(row.claim_type):row.claim_type!==null)||
      !text(row.activity_at,40)||!/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(row.activity_at)||!Number.isFinite(Date.parse(row.activity_at))||
      ['manufacturer','model','finish','year','serial_number'].some(key=>row[key]!==null&&!text(row[key],200)))throw Error('Invalid discovery');
    seen.add(row.id);
    return Object.fromEntries(['id','manufacturer','model','finish','year','serial_number','activity_at','activity_type','claim_type'].map(key=>[key,row[key]]));
  })};
}
export function validateStatistics(data){
  if(!data||!count(data.individuals)||!array(data.models,11)||!array(data.years,10000)||!array(data.listings_30d,30)||data.listings_30d.length!==30)throw Error('Invalid statistics');
  const models=data.models.map(row=>{if(!row||!text(row.label,10000)||!count(row.count)||row.count==='0')throw Error('Invalid model');return {label:row.label,count:row.count}});
  if(models.reduce((sum,row)=>sum+BigInt(row.count),0n)!==BigInt(data.individuals))throw Error('Incomplete models');
  const years=data.years.map((row,index)=>{if(!row||!/^\d{4}$/.test(row.label)||!count(row.count)||row.count==='0'||index>0&&data.years[index-1].label>=row.label)throw Error('Invalid year');return {label:row.label,count:row.count}});
  if(years.reduce((sum,row)=>sum+BigInt(row.count),0n)>BigInt(data.individuals))throw Error('Invalid year total');
  const listings_30d=data.listings_30d.map((row,index)=>{if(!row||!day(row.date)||!count(row.count)||index>0&&Date.parse(row.date)-Date.parse(data.listings_30d[index-1].date)!==86400000)throw Error('Invalid day');return {date:row.date,count:row.count}});
  return {individuals:data.individuals,models,years,listings_30d};
}
export function validateMap(data){
  if(!data||!array(data.countries,2000))throw Error('Invalid country counts');
  const seen=new Set();
  return {countries:data.countries.map(row=>{if(!row||!text(row.country,200)||!row.country.trim()||seen.has(row.country)||!count(row.count)||row.count==='0')throw Error('Invalid country');seen.add(row.country);return {country:row.country,count:row.count}})};
}
const normalize=value=>String(value).trim().toLowerCase().replace(/\./g,'').replace(/&/g,'and').replace(/\s+/g,' ');
export function countryIndex(countries=worldCountries){
  const result=new Map();
  for(const country of countries){
    for(const alias of country.aliases)result.set(normalize(alias),country);
    for(const locale of ['en','ja'])try{if(country.code)result.set(normalize(new Intl.DisplayNames([locale],{type:'region'}).of(country.code)),country)}catch{}
  }
  // Small countries/territories omitted by the 1:110m geometry still need
  // localized names in the complete country table.
  try{
    const english=new Intl.DisplayNames(['en'],{type:'region'}),japanese=new Intl.DisplayNames(['ja'],{type:'region'});
    for(let a=65;a<=90;a++)for(let b=65;b<=90;b++){
      const code=String.fromCharCode(a,b),name=english.of(code);if(name===code)continue;
      const country=result.get(normalize(code))||result.get(normalize(name))||{name,code,aliases:[]};
      for(const alias of [code,name,japanese.of(code)])if(!result.has(normalize(alias)))result.set(normalize(alias),country);
    }
    for(const [alias,code] of Object.entries({sgp:'SG',hkg:'HK',mac:'MO'}))if(result.has(normalize(code)))result.set(alias,result.get(normalize(code)));
  }catch{/* Keep original country names when DisplayNames is unavailable. */}
  for(const [alias,target] of Object.entries({'uk':'United Kingdom','great britain':'United Kingdom','us':'United States of America','korea, south':'South Korea','russian federation':'Russia','viet nam':'Vietnam','czech republic':'Czechia'})){
    const value=result.get(normalize(target));if(value)result.set(alias,value);
  }
  return result;
}

export function createCatalogInsights({document=globalThis.document,read,onSelect,onRefresh,countries=worldCountries}={}){
  const $=id=>document.getElementById(id),index=countryIndex(countries);
  let locale='en',revision=0,signature=null,paused=false,controller=null,pending=Promise.resolve(),data={},statuses={discovery:'loading',statistics:'loading',map:'loading'};
  const t=(key,args={})=>(words[locale][key]||key).replace(/\{(\w+)\}/g,(_,name)=>String(args[name]??''));
  const node=(tag,label)=>{const n=document.createElement(tag);if(label!==undefined)n.textContent=label;return n};
  const svgNode=(tag,attrs={},label)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(label!==undefined)n.textContent=label;return n};
  const formatted=value=>BigInt(value).toLocaleString(locale==='ja'?'ja-JP':'en-US');
  const label=value=>value==='Other'?t('other'):value==='Unknown'?t('unknown'):value;
  function labels(){
    for(const [name,key] of Object.entries({shellDiscovery:'discovery',shellStatistics:'statistics',shellMap:'map',discoveryHeading:'discovery',modelHeading:'models',yearHeading:'years',listingHeading:'listings',mapHeading:'locations',insightsRefresh:'refresh',mapCoverage:'coverage',mapMore:'more'}))$(name).textContent=t(key);
    $('statistics').setAttribute('aria-label',t('statistics'));$('worldMapSvg').setAttribute('aria-label',t('mapLabel'));
  }
  function table(rows,key,heading){
    const details=node('details'),summary=node('summary',t(heading)),table=node('table'),head=node('thead'),header=node('tr');
    header.append(node('th',t(key==='date'?'date':key==='country'?'country':key==='year'?'year':'model')),node('th',t('value')));head.append(header);table.append(head);
    const body=node('tbody');for(const row of rows){const tr=node('tr');tr.append(node('td',key==='country'?countryName(row.country):label(row[key==='year'?'label':key])),node('td',formatted(row.count)));body.append(tr)}table.append(body);details.append(summary,table);return details;
  }
  function countryName(value){const country=index.get(normalize(value));try{if(country?.code)return new Intl.DisplayNames([locale],{type:'region'}).of(country.code)}catch{}return country?.name||value}
  function chartRoot(root,title){const svg=svgNode('svg',{viewBox:'0 0 600 230',role:'img','aria-label':title});svg.append(svgNode('title',{},title));root.append(svg);return svg}
  function pie(rows){
    const root=$('modelChart');root.replaceChildren();if(!rows.length){root.append(node('p',t('noModels')));return}
    const svg=chartRoot(root,t('models')),total=rows.reduce((sum,row)=>sum+Number(row.count),0);let angle=-Math.PI/2;
    rows.forEach((row,i)=>{
      const span=Number(row.count)/total*Math.PI*2,end=angle+span,x=130+100*Math.cos(angle),y=115+100*Math.sin(angle),ex=130+100*Math.cos(end),ey=115+100*Math.sin(end);
      const shape=rows.length===1?svgNode('circle',{cx:130,cy:115,r:100,fill:palette[i]}):svgNode('path',{d:`M130,115 L${x},${y} A100,100 0 ${span>Math.PI?1:0},1 ${ex},${ey} Z`,fill:palette[i],stroke:'var(--panel)','stroke-width':2});
      shape.append(svgNode('title',{},label(row.label)+': '+formatted(row.count)));svg.append(shape);angle=end;
      svg.append(svgNode('rect',{x:260,y:6+i*21,width:10,height:10,fill:palette[i]}));
      const entry=svgNode('text',{x:278,y:15+i*21,'font-size':12},label(row.label)+' — '+formatted(row.count));entry.append(svgNode('title',{},label(row.label)));svg.append(entry);
    });root.append(table(rows,'label','chartCounts'));
  }
  function plot(rootId,rows,kind){
    const root=$(rootId);root.replaceChildren();if(!rows.length){root.append(node('p',t('noYears')));return}
    const svg=chartRoot(root,t(kind==='bar'?'years':'listings')),max=Math.max(1,Math.ceil(Math.max(0,...rows.map(row=>Number(row.count)))/4))*4,width=530,height=170,x0=56,y0=190;
    for(let tick=0;tick<=4;tick++){const y=y0-height*tick/4;svg.append(svgNode('line',{x1:x0,x2:586,y1:y,y2:y,class:'chart-grid'}),svgNode('text',{x:48,y:y+4,'text-anchor':'end','font-size':10},new Intl.NumberFormat(locale,{maximumFractionDigits:0}).format(max*tick/4)))}
    if(kind==='bar')rows.forEach((row,i)=>{const w=width/rows.length,x=x0+i*w,h=Number(row.count)/max*height,r=svgNode('rect',{x:x+w*.1,y:y0-h,width:Math.max(.1,w*.8),height:h,fill:palette[0]});r.append(svgNode('title',{},row.label+': '+formatted(row.count)));svg.append(r)});
    else{
      const points=rows.map((row,i)=>`${x0+i*width/(rows.length-1)},${y0-Number(row.count)/max*height}`);
      svg.append(svgNode('polyline',{points:points.join(' '),fill:'none',stroke:palette[0],'stroke-width':2}));
      rows.forEach((row,i)=>{const c=svgNode('circle',{cx:x0+i*width/(rows.length-1),cy:y0-Number(row.count)/max*height,r:3,fill:palette[0]});c.append(svgNode('title',{},row.date+': '+formatted(row.count)));svg.append(c)});
    }
    const every=Math.max(1,Math.ceil(rows.length/6));rows.forEach((row,i)=>{if(i!==rows.length-1&&(i%every!==0||rows.length-1-i<every))return;svg.append(svgNode('text',{x:x0+(kind==='bar'?(i+.5)*width/rows.length:i*width/(rows.length-1)),y:212,'text-anchor':kind==='line'&&i===rows.length-1?'end':'middle','font-size':10},row.label||row.date.slice(5)))});
    root.append(table(rows,kind==='bar'?'year':'date','chartCounts'));
  }
  function renderDiscovery(){
    const root=$('newDiscoveryList');root.replaceChildren();const rows=data.discovery?.items;
    if(!rows)return;
    if(!rows.length){root.append(node('p',t('empty')));return}
    for(const row of rows){
      const link=node('a');link.className='discovery-item';link.href='/ui/guitars/'+row.id;
      const time=node('time',new Date(row.activity_at).toLocaleString(locale==='ja'?'ja-JP':'en-US'));time.className='discovery-time';time.dateTime=row.activity_at;
      const story=node('span');story.className='discovery-story';story.append(node('strong',[row.manufacturer,row.model,row.year&&'('+row.year+')',row.finish].filter(Boolean).join(' ')||'#'+row.id));
      const message=row.activity_type==='discovery'||row.claim_type==='listing'?t('added'):t('updated',{kind:t(row.claim_type)});story.append(node('span',' '+message));link.title=time.textContent+' '+story.textContent;link.append(time,story);
      link.onclick=event=>{if(event.button>0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();onSelect(row.id)};
      root.append(link);
    }
  }
  function renderMap(){
    const svg=$('worldMapSvg');svg.replaceChildren();$('mapCounts').replaceChildren();$('mapSelection').textContent='';if(!data.map)return;
    const values=new Map();for(const row of data.map.countries){const name=index.get(normalize(row.country))?.name||row.country;values.set(name,(values.get(name)||0n)+BigInt(row.count))}
    const max=Math.max(1,...Array.from(values.values(),Number));
    svg.append(svgNode('title',{},t('mapLabel')));
    for(const country of countries){
      const amount=values.get(country.name)||0n,factor=amount?Math.log(Number(amount)+1)/Math.log(max+1):0;
      const fill=amount?'rgb('+[65,55,39].map((n,i)=>Math.round(n+([208,164,93][i]-n)*factor)).join(',')+')':'#20262a';
      const p=svgNode('path',{d:country.path,fill,class:'world-country'}),description=countryName(country.name)+' — '+t('count',{count:amount.toLocaleString(locale)});p.append(svgNode('title',{},description));
      p.onclick=p.onmouseenter=p.onfocus=()=>{$('mapSelection').textContent=description};
      if(amount){p.setAttribute('tabindex','0');p.setAttribute('aria-label',description)}svg.append(p);
    }
    // Include unmatched small countries in the count table; geometry coverage
    // must never silently remove their recorded counts.
    const grouped=Array.from(values,([country,amount])=>({country,count:amount.toString()})).sort((a,b)=>BigInt(a.count)===BigInt(b.count)?a.country.localeCompare(b.country):BigInt(a.count)>BigInt(b.count)?-1:1);
    $('mapCounts').append(table(grouped,'country','counts'));
    if(!data.map.countries.length)$('mapSelection').textContent=t('noCountries');
  }
  function render(){
    labels();for(const name of ['discovery','statistics','map']){$(name+'Status').textContent=statuses[name]?t(statuses[name]):'';$(name+'Status').hidden=!statuses[name]}
    $('discoveryHeading').dataset.countPending=String(!data.discovery);$('newDiscoveryList').setAttribute('aria-busy',String(statuses.discovery==='loading'));
    renderDiscovery();for(const id of ['modelChart','yearChart','listingChart'])$(id).replaceChildren();
    if(data.statistics){pie(data.statistics.models);plot('yearChart',data.statistics.years,'bar');plot('listingChart',data.statistics.listings_30d,'line')}
    renderMap();$('insightsRefresh').disabled=paused||Object.values(statuses).includes('loading');
  }
  function clear({pause=false,status='loading'}={}){++revision;controller?.abort();signature=null;paused=pause;data={};statuses={discovery:status,statistics:status,map:status};render()}
  function sync(state){
    const nextLocale=state.locale==='ja'?'ja':'en',languageChanged=locale!==nextLocale;locale=nextLocale;if(paused)return pending;
    const restricted=state.serviceMode==='offline'||state.serviceMode==='admin_only'&&state.auth?.account?.user?.role!=='admin';
    if(state.blocked||restricted){clear({status:state.blocked&&state.blockCode!=='service_restricted'?'session':'restricted'});return Promise.resolve()}
    const key=JSON.stringify([state.readRevision,state.auth?.account?.user?.app_user_id||null,state.serviceMode]);
    if(key===signature){if(languageChanged)render();return pending}
    if(state.loading){clear();return pending}
    clear();signature=key;const current=revision;controller=new AbortController();const signal=controller.signal;
    // clear() advances revision; slow responses from a previous identity or
    // BFCache page cannot restore erased rows, charts, or country counts.
    pending=(async()=>{
      const names=['discovery','statistics','map'],paths=['discoveries','statistics','world-map'],validators=[validateDiscoveries,validateStatistics,validateMap];
      const results=await Promise.allSettled(paths.map((path,i)=>Promise.resolve().then(()=>{if(signal.aborted)throw Error('Stale insights');return read('/api/public/guitars/'+path,signal)}).then(validators[i])));
      if(current!==revision||paused)return;
      const authFailure=results.find(result=>result.status==='rejected'&&[401,403].includes(result.reason?.status));
      if(authFailure){data={};const status=authFailure.reason.status===401?'session':'restricted';statuses={discovery:status,statistics:status,map:status}}
      else results.forEach((result,i)=>{const name=names[i];if(result.status==='fulfilled'){data[name]=result.value;statuses[name]=''}else{delete data[name];statuses[name]='failed'}});
      render();
    })();return pending;
  }
  $('insightsRefresh').onclick=async()=>{clear();await onRefresh()};
  return {sync,clear,resume(){paused=false;signature=null},whenReady:()=>pending,pickDiscovery:(random=Math.random)=>{const rows=data.discovery?.items;return rows?.length?rows[Math.floor(random()*rows.length)]?.id||null:null}};
}
