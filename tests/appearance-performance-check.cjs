/* AI → appearances must paint first, stay cancellable, and compare only one frame. */
const assert=require('assert/strict');
const {harness,settle,clone}=require('./ui-check.cjs');
(async()=>{
 const h=harness();await settle();const frames=new Map(),instances=[];let id=0,compiles=0,wakes=0,prepares=0,releaseHold=null,holdNext=false,failNext=false;
 h.window.requestAnimationFrame=fn=>{frames.set(++id,fn);return id;};h.window.cancelAnimationFrame=id=>frames.delete(id);
 const Original=h.window.KeyboardPreview;
 Original.prototype.setVisible=function(value){this.visible=!!value;return this;};
 h.window.KeyboardPreview=class extends Original{
  constructor(container,options){super(container,options);this.visible=options.visible!==false;instances.push(this);}
  setVisible(value){if(value)wakes++;this.visible=!!value;return this;}
  setDesign(d){compiles++;return super.setDesign(d);}
  async prepareLayoutAsync(current){
   prepares++;assert.equal(this.visible,false);assert.equal(this.playing,false);
   if(holdNext){holdNext=false;await new Promise(resolve=>releaseHold=resolve);}
   if(failNext){failNext=false;return false;}
   await Promise.resolve();return current();
  }
 };
 async function step(){const next=frames.entries().next().value;if(next){frames.delete(next[0]);next[1]();await settle();}}
 async function drain(){let turns=0;while(frames.size){assert.ok(turns++<100,'failed/cancelled card cannot loop forever');await step();}}
 h.app.navigate('create');h.app.navigate('appearances');
 assert.equal(instances.length,0,'AI → appearances cannot compile previews synchronously');assert.equal(wakes,0);
 await step();assert.equal(instances.length,0,'the first page paint precedes all card preparation');
 await step();assert.equal(instances.length,1,'only one card can begin after the page paint');
 h.app.navigate('create');assert.equal(frames.size,0,'leaving cancels queued work');
 assert.equal(h.app.preview.visible,false,'workbench stays suspended outside its page');
 h.app.navigate('appearances');await drain();assert.equal(instances.length,8);
 for(const p of instances){assert.equal(p.design.frames.length,1);assert.equal(p.design.keyframes.length,1);}
 const before={compiles,prepares,wakes};h.app.previewChoices.refreshGallery(h.app.state.selected,0,{brightness:100});
 assert.equal(frames.size,0,'unchanged visible comparison needs no work');assert.deepEqual({compiles,prepares,wakes},before);
 const data=clone({designs:h.app.state.designs,pending:[...h.app.state.pending],slots:h.app.state.slots});
 for(const appearance of h.window.STUDIO_DATA.previewCatalog.appearances)h.app.previewChoices.selectAppearance(appearance.id);
 assert.deepEqual(clone({designs:h.app.state.designs,pending:[...h.app.state.pending],slots:h.app.state.slots}),data);
 assert.deepEqual({compiles,prepares,wakes},before,'selecting a card cannot rebuild all comparison cards');
 h.app.navigate('create');const warmWakes=wakes;h.app.navigate('appearances');
 assert.equal(wakes,warmWakes,'warm AI → appearances cannot synchronously wake eight renderers');
 await step();assert.equal(wakes,warmWakes);await drain();
 holdNext=true;h.app.previewChoices.refreshGallery(h.app.state.designs[1],7,{brightness:70});await step();await step();assert.ok(releaseHold);
 h.app.previewChoices.refreshGallery(h.app.state.designs[2],11,{brightness:80});releaseHold();await settle();await drain();
 const expected=h.app.state.designs[2];
 for(const p of instances){assert.equal(p.design.id,expected.id);assert.deepEqual(p.design.frames[0],expected.frames[11%expected.frames.length]);assert.deepEqual(p.design.keyframes[0],expected.keyframes[11%expected.keyframes.length]);assert.equal(p.brightness,80);}
 failNext=true;h.app.previewChoices.refreshGallery(expected,12,{brightness:80});await drain();
 assert.equal(h.el('appearanceGallery').querySelectorAll('[data-thumbnail-status="unavailable"]').length,1,'failure leaves a usable photograph instead of retrying forever');
 const independent={...expected,id:'independent-cycle-fixture',frames:expected.frames.slice(0,2),keyframes:expected.keyframes.slice(0,3)};
 h.app.previewChoices.refreshGallery(independent,5,{brightness:90});await drain();
 for(const p of instances){assert.deepEqual(p.design.frames[0],independent.frames[1]);assert.deepEqual(p.design.keyframes[0],independent.keyframes[2]);}
 assert.ok(h.calls.every(c=>!['detect','execute','plan','generateAI','startVoiceRecording'].includes(c.action)));
 console.log('PASS: cold/warm AI entry paints before preparation, no synchronous renderer wake, single-frame RGB, cancellation/latest snapshot wins, failure fallback, unchanged artwork/slots.');
})().catch(e=>{console.error(e);process.exitCode=1;});
