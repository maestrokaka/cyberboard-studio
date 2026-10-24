/* Production raster-preparation workload with deterministic canvas pixels.
   Reports CPU time, but asserts work counts/output rather than machine speed.
   No browser automation, model requests or device access. */
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict'),crypto=require('crypto');
const root=path.resolve(__dirname,'..'),dataContext={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(root,'web/data.js'),'utf8'),dataContext);
const data=dataContext.window.STUDIO_DATA,callbacks=new Map(),observers=[],styles=new Map();let raf=0;
function element(tag){const e={tagName:tag.toUpperCase(),className:'',width:0,height:0,style:{},children:[],attributes:{},clientWidth:720,clientHeight:400,
 classList:{add(){},remove(){}},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];},
 appendChild(c){this.children.push(c);c.parent=this;if(c.id)styles.set(c.id,c);},remove(){if(this.parent)this.parent.children=this.parent.children.filter(c=>c!==this);}};
 const ctx=new Proxy({getImageData(x,y,w,h){const bytes=new Uint8ClampedArray(w*h*4);new Uint32Array(bytes.buffer).fill(0xffdca064);return {width:w,height:h,data:bytes};},
 createImageData(w,h){return {width:w,height:h,data:new Uint8ClampedArray(w*h*4)};},putImageData(pixels){this.pixels=pixels;},createRadialGradient(){return {addColorStop(){}};}},
 {get:(o,k)=>k in o?o[k]:(()=>{}),set:(o,k,v)=>(o[k]=v,true)});e.getContext=()=>ctx;return e;}
const document={head:element('head'),hidden:false,getElementById:id=>styles.get(id),createElement:element,addEventListener(){},removeEventListener(){}};
const window={devicePixelRatio:2,matchMedia:()=>({matches:false,addEventListener(){},removeEventListener(){}}),addEventListener(){},removeEventListener(){},
 requestAnimationFrame(fn){callbacks.set(++raf,fn);return raf;},cancelAnimationFrame(id){callbacks.delete(id);},
 ResizeObserver:class{constructor(fn){this.fn=fn;observers.push(this);}observe(){}disconnect(){}},
 Image:class{constructor(){this.naturalWidth=1619;this.naturalHeight=1080;}set src(v){Promise.resolve().then(()=>this.onload());}}};
const source=process.env.STUDIO_PREVIEW_SOURCE||path.join(root,'web/preview-engine.js');
vm.runInNewContext(fs.readFileSync(source,'utf8'),{window,document,console,Uint8Array,Uint8ClampedArray,Float32Array});
let prepares=0;
const prepare=window.KeyboardPreview.prototype._prepareKeyLighting;
window.KeyboardPreview.prototype._prepareKeyLighting=function(...args){prepares++;return prepare.apply(this,args);};
const hash=p=>crypto.createHash('sha256').update(p._bg.pixels.data).digest('hex');
(async()=>{
 const host=element('div'),p=new window.KeyboardPreview(host,{views:data.views,design:data.designs[0]});await p.ready;
 const front=p.view,other=Object.keys(p.views).find(id=>id!==front),before=hash(p),baseline=process.argv.includes('--baseline');
 const measure=(fn)=>{const count=prepares,start=performance.now();fn();return {ms:Math.round((performance.now()-start)*100)/100,prepares:prepares-count};};
 const repeated=measure(()=>{for(let i=0;i<8;i++)p.setFraming('keyboard').setView(front);});
 const cold=measure(()=>p.setView(other));
 const warm=measure(()=>{for(let i=0;i<4;i++)p.setView(front).setView(other);p.setView(front);});
 assert.equal(hash(p),before,'returning to a cached appearance restores identical background pixels');
 const resize=measure(()=>{for(let i=0;i<8;i++)observers[0].fn();});
 const renderers=measure(()=>p.setRenderer('library').setRenderer('editor'));
 let hidden=null;
 if(p.setVisible){
  p.play();const playing=p.playing;p.setVisible(false);assert.equal(callbacks.size,0,'hidden preview stops scheduling animation');
  hidden=measure(()=>p.setView(other).setView(front).setView(other));
  assert.equal(p.playing,playing,'visibility must preserve the user playback choice');
  p.setVisible(true);assert.equal(p.view,other);assert.equal(callbacks.size,1);p.pause();
 }
 if(!baseline){assert.equal(repeated.prepares,0);assert.equal(warm.prepares,0);assert.equal(resize.prepares,0);assert.equal(renderers.prepares,0);assert.equal(hidden.prepares,0);
  assert.ok(p._staticCacheBytes<=24*1024*1024);assert.ok(p._staticCache.size<=2);}
 const report={source:path.basename(source),repeated,cold,warm,unchangedResize:resize,rendererSwitch:renderers,hidden,identicalBackground:true,cacheBytes:p._staticCacheBytes||0};
 p.destroy();assert.equal(callbacks.size,0);if(!baseline)assert.equal(p._staticCache.size,0);
 if(!baseline){
  const options={views:data.views,design:data.designs[0],rasterMinWidth:320,rasterMaxWidth:640};
  const reference=new window.KeyboardPreview(element('div'),options);await reference.ready;reference.pause();
  const expected=hash(reference),maskHash=preview=>crypto.createHash('sha256').update(Buffer.concat(preview._keySprites.map(s=>Buffer.from(s.mask.getContext('2d').pixels.data)))).digest('hex');
  const expectedMasks=maskHash(reference);reference.destroy();
  const count=prepares,progressive=new window.KeyboardPreview(element('div'),{...options,visible:false});await progressive.ready;progressive.pause();
  assert.equal(prepares,count,'hidden gallery readiness cannot prepare pixels before the page paints');
  let clock=0,yields=0,current=true;
  window.performance={now:()=>++clock};window.setTimeout=fn=>{yields++;setImmediate(()=>{if(yields===3)current=false;fn();});};
  assert.equal(await progressive.prepareLayoutAsync(()=>current),false);assert.equal(progressive.error,null);assert.equal(progressive._staticKey,null);
  current=true;assert.equal(await progressive.prepareLayoutAsync(()=>current),true);
  assert.ok(yields>3,'pixel preparation must yield tasks, not only chain microtasks');
  assert.equal(hash(progressive),expected,'progressive neutral pixels match synchronous preparation byte for byte');
  assert.equal(maskHash(progressive),expectedMasks,'all 83 progressive light masks match');
  progressive.setVisible(true);progressive.destroy();assert.equal(callbacks.size,0);
  report.progressive={taskYields:yields,cancelledAndResumed:true,identicalBackground:true,identical83Masks:true};
 }
 console.log(JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
