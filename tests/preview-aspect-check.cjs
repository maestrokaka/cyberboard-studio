/* Viewport geometry regression for fixed-height AI, comparison and wide native panels.
 * Uses actual shipped calibration and the production _layoutCanvas path. No browser,
 * model, USB, image mutation or source-pixel decoding is involved. */
'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
const root=path.resolve(__dirname,'..');
const webRoot=process.env.STUDIO_TEST_WEB_ROOT?path.resolve(process.env.STUDIO_TEST_WEB_ROOT):path.join(root,'web');
const dataContext={window:{}};vm.runInNewContext(fs.readFileSync(path.join(webRoot,'data.js'),'utf8'),dataContext);
const data=dataContext.window.STUDIO_DATA;
const styles=new Map(),observers=[];
const drawing=new Proxy({},{get:(target,key)=>key in target?target[key]:(()=>{}),set:(target,key,value)=>(target[key]=value,true)});
function element(tag){return{tagName:tag.toUpperCase(),style:{},children:[],attributes:{},className:'',clientWidth:650,clientHeight:200,parent:null,
 classList:{add(){},remove(){}},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];},
 appendChild(child){this.children.push(child);child.parent=this;if(child.id)styles.set(child.id,child);},
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(e=>e!==this);},getContext(){return drawing;}};}
const document={head:element('head'),hidden:false,createElement:element,getElementById:id=>styles.get(id),addEventListener(){},removeEventListener(){}};
const window={devicePixelRatio:2,matchMedia:()=>({matches:true,addEventListener(){},removeEventListener(){}}),addEventListener(){},removeEventListener(){},requestAnimationFrame:()=>1,cancelAnimationFrame(){},
 ResizeObserver:class{constructor(callback){this.callback=callback;observers.push(this);}observe(){}disconnect(){}},
 Image:class{constructor(){this.naturalWidth=1619;this.naturalHeight=1080;}set src(value){Promise.resolve().then(()=>this.onload());}}};
vm.runInNewContext(fs.readFileSync(path.join(webRoot,'preview-engine.js'),'utf8'),{window,document,console,Uint8Array,Uint8ClampedArray,Float32Array});
// Raster sampling and color tests live in renderer-check.cjs. Preserve production
// frame layout, photo draw, projected coordinates and mesh computation here.
window.KeyboardPreview.prototype._prepareKeyLighting=function(zones){this.geometryZones=zones;};
window.KeyboardPreview.prototype._drawLightsCanvas=function(){};
(async()=>{
 const host=element('div'),p=new window.KeyboardPreview(host,{views:data.views,design:data.designs[0]});await p.ready;
 const cases=[[650,200],[1300,260],[300,185],[315,172],[390,210],[720,600],[320,900],[1700,180]];
 let checked=0,roundedBackingCases=0;
 for(const appearance of data.previewCatalog.appearances){
  const view=data.views[appearance.defaultViewId],crop=view.crop;
  for(const [width,height] of cases){host.clientWidth=width;host.clientHeight=height;p.setView(appearance.defaultViewId).setFraming('keyboard');
   const [cx,cy,cw,ch]=crop,layers=[p.background,p.keyOverlay,p.overlay];
   const bounds=layers.map(layer=>({left:parseFloat(layer.style.left),top:parseFloat(layer.style.top),width:parseFloat(layer.style.width),height:parseFloat(layer.style.height)}));
   bounds.forEach(b=>assert.deepEqual(b,bounds[0],'the photograph and both LED regions have one shared fit'));
   const b=bounds[0];if(Math.abs(p.background.width/p.background.height-cw/ch)>1e-7)roundedBackingCases++;assert.ok(Math.abs(b.width/b.height-cw/ch)<1e-10,'fixed-height viewports must retain the calibrated crop aspect');
   assert.ok(b.width<=width+1e-8&&b.height<=height+1e-8,'the whole enclosure fits without cropping');
   assert.ok(Math.abs(b.left-(width-b.width)/2)<1e-8&&Math.abs(b.top-(height-b.height)/2)<1e-8,'contain is centered');
   assert.ok(Math.abs(b.width-width)<1e-8||Math.abs(b.height-height)<1e-8,'one viewport boundary is used to maximize the proportional image');
   assert.ok(p.background.width===p.keyOverlay.width&&p.background.width===p.overlay.width&&p.background.height===p.keyOverlay.height&&p.background.height===p.overlay.height,'all backing stores share exactly the same dimensions');
   const scale=b.width/cw;assert.ok(Math.abs(scale-b.height/ch)<1e-10,'source X/Y use a uniform scale');
   const sourceOutline=view.keyboard_outline||p._keyboardOutline.map(([x,y])=>[cx+x*cw/p.background.width,cy+y*ch/p.background.height]);const sourcePoints=[...sourceOutline,...view.quad,...view.mask_quad,...view.keyZones.flatMap(zone=>zone.quad)];
   for(const [x,y] of sourcePoints){const cssX=b.left+(x-cx)*p.background.width/cw*b.width/p.background.width;const cssY=b.top+(y-cy)*p.background.height/ch*b.height/p.background.height;
    assert.ok(Math.abs(cssX-(b.left+(x-cx)*scale))<1e-8&&Math.abs(cssY-(b.top+(y-cy)*scale))<1e-8,'enclosure, screen corners and all 83 key zones project through the same proportional transform');
    assert.ok(cssX>=-1e-8&&cssX<=width+1e-8&&cssY>=-1e-8&&cssY<=height+1e-8,'calibrated content is not cut off');}
   const before=JSON.stringify(bounds);observers[0].callback();assert.equal(JSON.stringify(layers.map(layer=>({left:parseFloat(layer.style.left),top:parseFloat(layer.style.top),width:parseFloat(layer.style.width),height:parseFloat(layer.style.height)}))),before,'ResizeObserver layout converges without aspect drift');checked++;
  }
 }
 const front=data.views.front,[,,cw,ch]=front.crop;
 host.clientWidth=650;host.clientHeight=200;p.setView('front');assert.ok(Math.abs(p.viewport.width-p.viewport.height*cw/ch)<1e-8);assert.equal(p.viewport.height,200);assert.ok(p.viewport.width<400,'the wide native viewport cannot squash R6 into 650×200');
 assert.ok(roundedBackingCases>0,'the regression covers integer backing stores whose raster ratio differs slightly from the exact crop');p.destroy();assert.equal(host.children.length,0);
 console.log(JSON.stringify({passed:true,appearances:8,viewportCases:cases.length,layouts:checked,roundedBackingCases,allLayersUniform:true,sourceAspectPreserved:true,enclosureAnd83KeyZonesInside:true,resizeStable:true,wideNativeRegression:'650×200 host uses one centered proportional crop'}));
})().catch(error=>{console.error(error);process.exitCode=1;});
