(function(){
 'use strict';
 const app=window.StudioApp,options=window.STUDIO_LOGO_OPTIONS||[],materials=window.STUDIO_MATERIAL_ICON_OPTIONS||[];
 if(!app||!options.length)return;
 const $=id=>document.getElementById(id),mark=$('brandMark');
 const originalMark=mark.innerHTML,originalMarkClass=mark.className;
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let selectedId=null,group=materials.length?'material':'geometry';
 const allOptions=options.concat(materials);
 function artwork(option,white=false){return option.image?`<img src="${esc(option.image)}" alt="${esc(option.name)} 应用图标">`:white?(option.whiteSvg||option.svg):option.svg;}
 function render(){
  const list=group==='material'?materials:options;
  $('brandMaterialTabBtn').classList.toggle('selected',group==='material');$('brandGeometryTabBtn').classList.toggle('selected',group==='geometry');
  $('logoGrid').classList.toggle('material-icons-grid',group==='material');$('logoGrid').classList.toggle('single-product-icon',group==='material'&&materials.length===1);
  $('logoGrid').innerHTML=list.map(option=>`<article class="logo-option ${selectedId===option.id?'previewing':''}"><div class="logo-option-head"><span class="mono">${esc(option.number)}</span><span class="badge">${option.formal?'正式 Logo':option.recommended?'推荐方向':'备选方案'}</span></div><div class="logo-mark-large" aria-label="${esc(option.name)}标志">${artwork(option,true)}</div><div class="logo-small-samples"><span class="sample24" title="24px">${artwork(option)}</span><span class="sample48" title="48px">${artwork(option)}</span><div class="logo-wordmark-sample">${artwork(option)}<div><b>Cyberboard</b><small>STUDIO</small></div></div></div><div class="logo-info"><h2>${esc(option.name)}</h2><p>${esc(option.description)}</p><button class="button ${selectedId===option.id?'primary':''}" data-logo-preview="${esc(option.id)}">${selectedId===option.id?'正在侧栏预览':'预览到侧栏'}</button></div></article>`).join('');
  document.querySelectorAll('[data-logo-preview]').forEach(button=>button.onclick=()=>preview(button.dataset.logoPreview));
  $('logoPreviewStatus').textContent=selectedId?'临时侧栏预览：'+allOptions.find(o=>o.id===selectedId).name:'正式 Logo';
  $('resetLogoBtn').hidden=!selectedId;
 }
 function preview(id){
  const option=allOptions.find(o=>o.id===id);if(!option)return;
  selectedId=id;mark.innerHTML=artwork(option);mark.classList.remove('brand-official-mark');mark.classList.add('brand-preview-mark');render();
 }
 function reset(){selectedId=null;mark.innerHTML=originalMark;mark.className=originalMarkClass;render();}
 $('brandReviewBtn').onclick=()=>{app.navigate('branding');render();};
 $('settingsBrandBtn').onclick=()=>{app.navigate('branding');render();};
 $('resetLogoBtn').onclick=reset;
 $('brandMaterialTabBtn').onclick=()=>{group='material';render();};
 $('brandGeometryTabBtn').onclick=()=>{group='geometry';render();};
 $('returnWorkbenchBtn').onclick=()=>app.navigate('workbench');
 render();
 window.StudioBrandReview={options,materials,preview,reset,get selectedId(){return selectedId;},get group(){return group;}};
})();
