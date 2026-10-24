(function(global){
 'use strict';
 function create({$,preview,views,catalog,onSelect}){
  const fallback={id:'user-vision',name:'CYBERBOARD R6「Vision」',model:'CYBERBOARD R6',source:'用户提供实拍',viewIds:['front'],defaultViewId:'front',note:'正面整机去背景预览；显示器、曝光与真实 LED 观感可能不同。'};
  const allowed=id=>views[id]&&(typeof global.KeyboardPreview.isGalleryAllowed==='function'?global.KeyboardPreview.isGalleryAllowed(views[id]):views[id].galleryAllowed!==false&&(views[id].angle==='front'||id==='front'));
  const entries=(Array.isArray(catalog?.appearances)?catalog.appearances:[fallback]).filter(item=>item&&typeof item.id==='string'&&Array.isArray(item.viewIds)&&item.viewIds.some(allowed));
  if(!entries.length)return null;
  const gallery=$('appearanceGallery'),cards=new Map();
  gallery.innerHTML='';
  let current=null;
  let snapshot=null,filter='all',visible=true,paintJob=null,preparing=false,generation=0;
  const viewFor=appearance=>appearance.viewIds.includes(appearance.defaultViewId)&&allowed(appearance.defaultViewId)?appearance.defaultViewId:appearance.viewIds.find(allowed);
  function selectView(id){
   if(!current?.viewIds.includes(id)||!allowed(id))return false;
   preview.setFraming('keyboard');
   preview.setView(id);
   return true;
  }
  function selectAppearance(id,{notify=true,focus=false,scroll=true}={}){
   const appearance=entries.find(item=>item.id===id);
   if(!appearance)return false;
   const changed=current?.id!==id;
   current=appearance;
   cards.forEach((card,key)=>{
    const selected=key===id;
    card.button.classList.toggle('selected',selected);
    card.button.setAttribute('aria-pressed',String(selected));
   });
   $('previewAppearanceName').textContent=appearance.name;
   const source=appearance.source||'';
   $('previewPhotoSource').textContent=source;
   $('previewPhotoSource').setAttribute('title',source);
   $('previewPhotoNote').textContent=appearance.note||'照片投影预览；显示器、曝光与真实 LED 观感可能不同。';
   if(changed)selectView(viewFor(appearance));
   const button=cards.get(id).button;
   if(focus)button.focus({preventScroll:true});
   if(scroll)button.scrollIntoView({block:'nearest',inline:'nearest',behavior:'auto'});
   if(changed&&notify)onSelect?.(id);
   return true;
  }
  entries.forEach((appearance,index)=>{
   const button=document.createElement('button');
   button.setAttribute('type','button');
   button.className='appearance-card';
   button.setAttribute('data-appearance',appearance.id);
   button.setAttribute('aria-label',appearance.name);
   button.setAttribute('aria-pressed','false');
   button.setAttribute('title',appearance.name);
   button.setAttribute('data-thumbnail-status','loading');
   const canvas=document.createElement('canvas');
   canvas.className='appearance-thumb';
   canvas.setAttribute('aria-hidden','true');
   const name=document.createElement('span');
   name.className='appearance-name';
   name.textContent=appearance.name.replace(/^CYBERBOARD\s+/,'');
   const visual=document.createElement('div');visual.className='appearance-visual';visual.appendChild(canvas);button.appendChild(visual);button.appendChild(name);gallery.appendChild(button);
   const source=document.createElement('small');source.className='appearance-source';source.textContent=appearance.source||'正面整机';button.appendChild(source);
   cards.set(appearance.id,{button,canvas,visual,renderer:null,root:null});
   button.onclick=()=>selectAppearance(appearance.id);
   button.onkeydown=event=>{
    const directions={ArrowUp:-1,ArrowLeft:-1,ArrowDown:1,ArrowRight:1};
    let target;
    if(event.key==='Home')target=0;
    else if(event.key==='End')target=entries.length-1;
    else if(Object.hasOwn(directions,event.key))target=(index+directions[event.key]+entries.length)%entries.length;
    else return;
    event.preventDefault();
    selectAppearance(entries[target].id,{focus:true,scroll:true});
   };
  });
  const initial=entries.find(item=>item.id===catalog?.default_appearance_id)||entries[0];
  selectAppearance(initial.id,{notify:false});
  Promise.resolve(preview.ready).then(()=>{
   cards.forEach(({button,canvas},id)=>{
    try{
     if(!preview.drawAppearanceThumbnail(canvas,viewFor(entries.find(item=>item.id===id))))throw new Error('照片尚未就绪');
     button.setAttribute('data-thumbnail-status','ready');
    }catch(error){
     button.classList.add('thumbnail-unavailable');
     button.setAttribute('data-thumbnail-status','unavailable');
     button.setAttribute('title',button.getAttribute('aria-label')+' · 缩略图暂时不可用，点击查看整机');
    }
   });
  }).catch(()=>cards.forEach(({button})=>{
   button.classList.add('thumbnail-unavailable');
   button.setAttribute('data-thumbnail-status','unavailable');
  }));
  function applyFilter(){
   cards.forEach(({button,renderer},id)=>{const model=entries.find(a=>a.id===id).model||'';button.hidden=filter!=='all'&&!model.includes(filter);if(button.hidden)renderer?.setVisible?.(false);});
   document.querySelectorAll('[data-appearance-model]').forEach(button=>{const selected=button.dataset.appearanceModel===filter;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected));});
  }
  const matches=card=>snapshot&&card.design===snapshot.design&&card.tick===snapshot.tick&&card.brightness===(snapshot.options.brightness??100)&&card.rendererMode===(preview.renderer||'editor');
  const pending=()=>Array.from(cards).filter(([,card])=>!card.button.hidden&&(!matches(card)||(!card.failed&&card.renderer?.visible===false)));
  function comparisonNote(){if($('appearanceComparisonNote')&&snapshot)$('appearanceComparisonNote').textContent=snapshot.design.name+' · 同一帧 '+(snapshot.tick+1)+(pending().length?' · 正在准备预览':'');}
  function refreshGallery(design,tick=0,options={}){
   if(!design)return;snapshot={design,tick:Math.max(0,Math.floor(Number(tick)||0)),options};
   applyFilter();scheduleGallery();
  }
  // Cards display one frozen frame. They must not parse/store an entire movie
  // eight times just to compare the same instant across different photographs.
  function frameDesign(target){const d=target.design;return {id:d.id,name:d.name,speed_ms:d.speed_ms,frames:[d.frames[target.tick%d.frames.length]],keyframes:[d.keyframes[target.tick%d.keyframes.length]],stages:[]};}
  async function renderCard(card,id,version){
   const target=snapshot,brightness=target.options.brightness??100,renderer=preview.renderer||'editor';
   const current=()=>visible&&!document.hidden&&!card.button.hidden&&version===generation;
   if(!current())return;
   card.button.setAttribute('aria-busy','true');
   card.button.setAttribute('data-thumbnail-status','updating');
   try{
    const view=viewFor(entries.find(a=>a.id===id));
    if(!card.renderer){
     const container=document.createElement('div');container.className='appearance-preview';container.style.width='100%';container.style.visibility='hidden';
     card.visual.appendChild(container);card.root=container;
     card.renderer=new global.KeyboardPreview(container,{views:{[view]:views[view]},view,design:frameDesign(target),visible:false,rasterMinWidth:320,rasterMaxWidth:640});
    }else{
     card.renderer.setVisible?.(false);
     if(card.design!==target.design||card.tick!==target.tick)card.renderer.setDesign(frameDesign(target));
    }
    card.renderer.pause();
    card.renderer.setBrightness(brightness);
    card.renderer.setRenderer(renderer);
    card.root.style.visibility='hidden';card.canvas.hidden=false;
    await card.renderer.ready;
    if(!current())return;
    if(card.renderer.prepareLayoutAsync&&!await card.renderer.prepareLayoutAsync(current)){
     if(!current())return;
     throw card.renderer.error||new Error('照片灯效预览未完成');
    }
    if(!current())return;
    card.renderer.setVisible?.(true);
    card.root.style.visibility='visible';card.canvas.hidden=true;card.failed=false;
    card.button.setAttribute('data-thumbnail-status','ready');
   }catch(error){
    if(!current())return;
    if(card.root)card.root.style.visibility='hidden';card.canvas.hidden=false;card.failed=true;
    card.button.setAttribute('data-thumbnail-status','unavailable');
   }
   if(current()){
    card.design=target.design;card.tick=target.tick;card.brightness=brightness;card.rendererMode=renderer;
    card.button.setAttribute('aria-busy','false');
   }
  }
  function cancelQueued(){if(paintJob!==null)global.cancelAnimationFrame?.(paintJob);paintJob=null;}
  function queueAfterPaint(){
   if(!visible||!snapshot||preparing||paintJob!==null||!pending().length)return;
   const version=generation;
   const run=()=>{paintJob=null;if(version===generation)runNext();};
   // rAF callbacks run BEFORE paint. Two frames let the new page be presented
   // before image decoding/preparation starts, including on a cold entry.
   if(typeof global.requestAnimationFrame==='function')paintJob=global.requestAnimationFrame(()=>{paintJob=global.requestAnimationFrame(run);});
   else {paintJob=-1;Promise.resolve().then(run);}
  }
  async function runNext(){
   if(preparing||!visible)return;
   const item=pending()[0];if(!item)return;
   preparing=true;
   try{await renderCard(item[1],item[0],generation);}finally{preparing=false;comparisonNote();queueAfterPaint();}
  }
  function scheduleGallery(){generation++;cancelQueued();comparisonNote();queueAfterPaint();}
  function setVisible(value){
   const next=Boolean(value);if(next===visible)return;visible=next;generation++;cancelQueued();
   if(!visible)cards.forEach(card=>{card.renderer?.setVisible?.(false);card.button.setAttribute('aria-busy','false');});
   else queueAfterPaint();
  }
  document.querySelectorAll('[data-appearance-model]').forEach(button=>button.onclick=()=>{filter=button.dataset.appearanceModel;applyFilter();scheduleGallery();});
  return {selectAppearance,selectView,refreshGallery,setVisible,get appearanceId(){return current.id;}};
 }
 global.StudioPreviewSelector={create};
})(typeof window!=='undefined'?window:globalThis);
