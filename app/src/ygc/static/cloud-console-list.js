import {createProfileList} from './cloud-profile-list.js';
// The same presentation as member guitar lists; Console owns all authority/API calls.
export function createConsoleList({section,list,title=null,refreshButton=null,columns=null,numericId=true,onSelect=null,renderCell=null,auth=()=>null,state=()=>null,busy=()=>false,numericFields=[],initialSort='id',initialDirection=1}){
 section.classList.add('console-data-list');list.classList.add('console-list-rows');
 const old=list.closest('table')?.parentElement;old?.remove();title=title||section.querySelector('h2');
 const emptyKeys={userBrowser:['ui.no_users_yet_44e4e2d9','ui.no_matching_users_579f8c39'],applicationBrowser:['admin_applications.empty','admin_applications.empty'],backupBrowser:['backups.empty','backups.no_matching']},messages=emptyKeys[section.id];
 const view=createProfileList({section,title,list,refreshButton,columnsOverride:columns,numericId,renderCell,auth,state,busy,onSelect,sharedSelection:false,emptyLabel:messages?globalThis.YGCI18n.t(messages[0]):null,noMatchLabel:messages?globalThis.YGCI18n.t(messages[1]):null,numericFields:columns?numericFields:['claim_count'],initialSort,initialDirection,filterLabel:columns?.filter(([key])=>key!=='action').map(([,label])=>label).join(' / '),guitarHref:id=>'#'+section.id,filterText:row=>Object.values(row).filter(v=>typeof v==='string'||typeof v==='number').join(' ')});
 const toolbar=section.lastElementChild.previousElementSibling;section.prepend(toolbar);
 return view;
}
