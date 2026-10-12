// Translate known system templates only. User-written dispute notes, reasons,
// names and guitar descriptions are retained verbatim.
export function notificationText(row,locale=globalThis.YGCI18n.locale){
 if(locale!=='ja')return {title:row.title,body:row.body};
 const kinds={Listing:'掲載',Specification:'スペック',Repair:'修理',Incident:'事故・被害',Event:'イベント',Media:'メディア',Ownership:'所有権','Former Owner':'以前の所有者','Identity Correction':'個体情報訂正'};
 const states={Positive:'肯定',Negative:'否定',Unverified:'未検証',accepted:'承諾',declined:'辞退',cancelled:'取消',approved:'承認',rejected:'却下',unverified:'未検証',needs_review:'確認待ち'};
 let title=row.title,body=row.body,match;
 if(row.notification_type==='claim_added'){
   match=/^New (.+) Claim$/.exec(title);if(match&&kinds[match[1]])title='新しい'+kinds[match[1]]+'Claim';
   match=/^(.+) added a (.+) Claim to (.+)\.$/.exec(body||'');if(match&&kinds[match[2]])body=match[1]+'が'+match[3]+'に'+kinds[match[2]]+'Claimを追加しました。';
 }else if(row.notification_type==='claim_verified'){
   match=/^Claim Verification: (Positive|Negative|Unverified)$/.exec(title);if(match)title='Claimの判定：'+states[match[1]];
   match=/^(.+) set your Claim on (.+) to (Positive|Negative|Unverified)\.$/.exec(body||'');if(match)body=match[1]+'が'+match[2]+'のあなたのClaimを「'+states[match[3]]+'」に判定しました。';
 }else if(row.notification_type==='transfer_request'){
   if(title==='Transfer request')title='譲渡の提案';
   if(body==='The Current Owner proposes transferring this guitar to you. Open the Transfer to Accept or Decline.')body='現在の所有者があなたへの譲渡を提案しています。譲渡画面を開いて承諾または辞退してください。';
 }else if(row.notification_type==='transfer_result'){
   match=/^Transfer (accepted|declined|cancelled)$/.exec(title);if(match)title='譲渡：'+states[match[1]];
   match=/^The Transfer proposal was (accepted|declined|cancelled)\.$/.exec(body||'');if(match)body='譲渡の提案は'+states[match[1]]+'されました。';
 }else if(row.notification_type==='ownership_decline'&&title==='Acquire declined')title='所有者申請の否認';
 else if(row.notification_type==='ownership_dispute'&&title==='Ownership dispute updated')title='所有権の異議申立てが更新されました';
 else if(row.notification_type==='claim_review'){
   if(title==='Acquire awaiting approval'||title==='Acquire承認待ち')title='所有者申請の承認待ち';
   if(body==='Image review passed. Please review the evidence and ownership request.')body='画像審議を通過しました。証拠と所有者申請を確認してください。';
 }else if(row.notification_type==='acquire_review'){
   if(title==='Ownership Request updated by administrator'){
     title='管理者が所有者申請を更新しました';
     match=/^(accept|reject|positive|negative|unverified|cancel|retry): ([\s\S]*)$/.exec(body||'');
     if(match){const actions={accept:'承認',reject:'却下',positive:'肯定',negative:'否定',unverified:'未検証',cancel:'取消',retry:'再試行'};body=actions[match[1]]+'：'+match[2]}
   }
   match=/^(Listing|Acquire) review result$/.exec(title);if(match)title=(match[1]==='Listing'?'掲載':'所有者申請')+'の審議結果';
   match=/^Open Ownership Requests to view the report\. Status: (.+)$/.exec(body||'');if(match)body='申請一覧を開いて審議結果を確認してください。状態：'+(states[match[1]]||match[1]);
 }
 return {title,body};
}
