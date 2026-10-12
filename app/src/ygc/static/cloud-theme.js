// Tab-scoped presentation preference only; this never identifies or authorizes a
// user. The canonical adapter reconciles and clears it on principal changes.
(()=>{const key='ygc-theme-display-v1',allowed=new Set(['dark_default','light_default','sunburst_3ply','butterscotch_black','olympic_white_mint','surf_green_white','sonic_blue_white','fiesta_red_white','black_pearl','goldtop_cream','cherry_red_black','vintage_white_gold','lake_blue_pearl']);let owner=null,remembered=null;
 function clear(){owner=remembered=null;try{sessionStorage.removeItem(key)}catch{}document.documentElement.dataset.theme='sunburst_3ply'}
 try{const saved=JSON.parse(sessionStorage.getItem(key));if(saved&&allowed.has(saved.theme)&&typeof saved.owner==='string'){owner=remembered=saved.owner;document.documentElement.dataset.theme=saved.theme}}catch{}
 function bind(value){if(!value){clear();return}if(owner&&owner!==value)clear();owner=value;return remembered===value}
 function remember(theme){if(!owner||!allowed.has(theme))return;remembered=owner;document.documentElement.dataset.theme=theme;try{sessionStorage.setItem(key,JSON.stringify({owner,theme}))}catch{}}
 globalThis.YGCTheme={bind,remember,clear};
})();
