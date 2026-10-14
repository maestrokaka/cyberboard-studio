/* Appearance selection must be local, persistent and independent of lighting or USB. */
const assert=require('assert/strict');
const fs=require('fs');
const path=require('path');
const {harness,settle,clone}=require('./ui-check.cjs');
const root=path.resolve(__dirname,'..');

(async()=>{
 const h=harness();await settle();
 const catalog=h.window.STUDIO_DATA.previewCatalog;
 for(const selector of ['#appearanceSelect','#viewSwitch','#framingSelect','[data-view]'])assert.equal(h.document.querySelectorAll(selector).length,0,'appearance choices must use thumbnails without alternate-view controls');
 assert.equal(h.window.STUDIO_DATA.views.desk,undefined);
 assert.equal(h.window.STUDIO_DATA.views['r4-cloud-perspective'],undefined);
 assert.ok(catalog.appearances.length>=8);
 assert.equal(Object.keys(h.window.STUDIO_DATA.views).length,catalog.appearances.length);
 assert.equal(catalog.appearances[0].name,'CYBERBOARD R6「Vision」');
 for(const appearance of catalog.appearances)assert.match(appearance.name,/^CYBERBOARD R[46]「[^」]+」$/);
 assert.equal(h.app.previewChoices.appearanceId,catalog.default_appearance_id);
 const gallery=h.el('appearanceGallery');
 assert.equal(gallery.getAttribute('role'),'group');
 const cards=()=>gallery.querySelectorAll('.appearance-card');
 const cardFor=id=>cards().find(card=>card.dataset.appearance===id);
 assert.deepEqual(cards().map(card=>card.dataset.appearance),Array.from(catalog.appearances,item=>item.id));
 function assertSelection(appearance){
  const selected=cards().filter(card=>card.getAttribute('aria-pressed')==='true');
  assert.equal(selected.length,1,'exactly one appearance card must be selected');
  assert.equal(selected[0].dataset.appearance,appearance.id);
  for(const card of cards())assert.equal(card.getAttribute('aria-pressed'),card.dataset.appearance===appearance.id?'true':'false');
  assert.equal(h.app.previewChoices.appearanceId,appearance.id);
  assert.equal(h.app.preview.view,appearance.defaultViewId);
  assert.equal(h.el('previewAppearanceName').textContent,appearance.name);
  assert.equal(h.el('previewPhotoSource').textContent,appearance.source);
  assert.equal(h.el('previewPhotoNote').textContent,appearance.note);
 }
 for(const appearance of catalog.appearances){
  const card=cardFor(appearance.id);
  assert.equal(card.tagName,'BUTTON');
  assert.equal(card.getAttribute('aria-label'),appearance.name,'screen readers must receive the full model and color name');
  const names=card.querySelectorAll('.appearance-name');
  assert.equal(names.length,1);assert.equal(names[0].textContent,appearance.name.replace(/^CYBERBOARD\s+/,''),'thumbnail labels omit the CYBERBOARD prefix while retaining model and colorway');
  const thumbs=card.querySelectorAll('.appearance-thumb');
  assert.equal(thumbs.length,1);assert.equal(thumbs[0].tagName,'CANVAS');assert.equal(thumbs[0].getAttribute('aria-hidden'),'true');
  assert.equal(thumbs[0].thumbnailViewId,appearance.defaultViewId,'each static thumbnail uses its own calibrated front view');
 }
 assert.equal(h.app.preview.thumbnailCalls.length,catalog.appearances.length,'one existing renderer draws all static thumbnails without separate playback instances');
 assertSelection(catalog.appearances.find(item=>item.id===catalog.default_appearance_id));
 await h.el('assignBtn').click();await h.flushSave();
 const lightingState=()=>JSON.stringify({design:h.app.state.selected,pending:[...h.app.state.pending],slots:h.app.state.slots,brightness:h.app.state.brightness,speedMs:h.app.state.speedMs});
 const lightingBefore=lightingState();
 const hardwareCount=()=>h.calls.filter(call=>['detect','plan','execute','keymap','setTime','generateAI','testAIConnection'].includes(call.action)).length;
 const beforeHardware=hardwareCount();
 for(const appearance of catalog.appearances){
  await cardFor(appearance.id).click();
  assertSelection(appearance);
  assert.equal(appearance.viewIds.length,1);
  assert.equal(h.app.preview.framing,'keyboard');
  assert.equal(h.window.STUDIO_DATA.views[appearance.defaultViewId].angle,'front');
  assert.equal(lightingState(),lightingBefore,'appearance switching cannot change design RGB, brightness, speed or slot drafts');
 }
 const last=catalog.appearances.at(-1);
 async function press(card,key,expected){
  let prevented=false;
  await card.onkeydown({key,target:card,preventDefault(){prevented=true;}});
  assert.equal(prevented,true,'appearance navigation must prevent page scrolling');
  assertSelection(expected);assert.equal(h.document.activeElement,cardFor(expected.id),'keyboard selection follows the focused card');
 }
 await press(cardFor(last.id),'Home',catalog.appearances[0]);
 await press(cardFor(catalog.appearances[0].id),'ArrowDown',catalog.appearances[1]);
 await press(cardFor(catalog.appearances[1].id),'ArrowUp',catalog.appearances[0]);
 await press(cardFor(catalog.appearances[0].id),'ArrowRight',catalog.appearances[1]);
 await press(cardFor(catalog.appearances[1].id),'ArrowLeft',catalog.appearances[0]);
 await press(cardFor(catalog.appearances[0].id),'End',last);
 assert.equal(lightingState(),lightingBefore,'keyboard appearance navigation cannot change LED settings or drafts');
 await h.flushSave();
 assert.equal(h.control.workspace.previewAppearanceId,last.id);
 assert.equal(hardwareCount(),beforeHardware,'appearance choices cannot contact models or USB');
 const restored=harness({workspace:clone(h.control.workspace)});await settle();
 assert.equal(restored.app.previewChoices.appearanceId,last.id);
 assert.equal(restored.app.preview.view,last.defaultViewId);
 const merged=clone(h.control.workspace);merged.previewAppearanceId='r6-launch';
 const mergedR6=harness({workspace:merged});await settle();
 assert.equal(mergedR6.app.previewChoices.appearanceId,'user-vision');
 const unknown=clone(h.control.workspace);unknown.previewAppearanceId='future-unbundled-appearance';
 const fallback=harness({workspace:unknown});await settle();
 assert.equal(fallback.app.previewChoices.appearanceId,catalog.default_appearance_id,'unavailable old choices fall back to the bundled original photo');
 const old=clone(h.control.workspace);delete old.previewAppearanceId;
 const legacy=harness({workspace:old});await settle();
 assert.equal(legacy.app.previewChoices.appearanceId,catalog.default_appearance_id);
 const calibration=JSON.parse(fs.readFileSync(path.join(root,'data/photos/photo-calibration.json'),'utf8'));
 for(const [id,view] of Object.entries(calibration)){
  const bundled=h.window.STUDIO_DATA.views[id];
  const original=fs.readFileSync(path.join(root,'web/assets',view.asset||id+'.jpg'));
  assert.equal(Buffer.compare(Buffer.from(bundled.image.split(',')[1],'base64'),original),0,'bundled image bytes must match the original photo');
 }
 console.log('Preview choices passed: front-only thumbnail cards, complete names, unique selection, calibrated static thumbnails, keyboard navigation and focus, unchanged LED/drafts, no model/USB calls, restored selections and byte-exact photo bundling.');
})().catch(error=>{console.error(error);process.exitCode=1;});
