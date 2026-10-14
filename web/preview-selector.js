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
   button.appendChild(canvas);button.appendChild(name);gallery.appendChild(button);
   cards.set(appearance.id,{button,canvas});
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
  return {selectAppearance,selectView,get appearanceId(){return current.id;}};
 }
 global.StudioPreviewSelector={create};
})(typeof window!=='undefined'?window:globalThis);
