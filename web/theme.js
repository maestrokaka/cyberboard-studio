(function () {
 'use strict';
 const root=document.documentElement,key='cyberboard-ui-theme',valid=t=>t==='dark'||t==='island';
 let current='dark',mounted=null,switching=false;
 function apply(theme){
  if(!valid(theme))throw Error('Invalid UI theme');
  current=theme;root.setAttribute('data-ui-theme',theme);
  if(theme==='island')root.setAttribute('data-island-ui','');else root.removeAttribute('data-island-ui');
  try{localStorage.setItem(key,theme);}catch(_){} // Optional first-paint cache; the workspace is authoritative.
  refresh();
 }
 function refresh(){
  if(!mounted)return;
  for(const button of document.querySelectorAll('[data-theme]')){
   button.setAttribute('aria-pressed',String(button.dataset.theme===current));
   button.disabled=switching||!mounted.canChange();
  }
  const label=document.getElementById('themeStatus');
  if(label)label.textContent=switching?'正在保存风格…':'当前使用'+(current==='island'?'暖岛浅色':'经典深色');
 }
 function mount(options){
  mounted=options;
  for(const button of document.querySelectorAll('[data-theme]'))button.onclick=async()=>{
   const theme=button.dataset.theme;
   if(!valid(theme)||theme===current||switching||!options.canChange())return;
   switching=true;refresh();
   try{await options.onSelect(theme);}catch(_){/* Owner restores the previous appearance and reports save failure. */}
   finally{switching=false;refresh();}
  };
  refresh();return {refresh};
 }
 try{const cached=localStorage.getItem(key);if(valid(cached))current=cached;}catch(_){}
 apply(current);
 window.StudioTheme=Object.freeze({get:()=>current,apply,mount});
})();
