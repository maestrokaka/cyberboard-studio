#!/usr/bin/env node
'use strict';

/* Offline photo frames from the unchanged shipped preview engine.
 * No browser, network, user workspace, model, CLI store or USB is accessed.
 * Example:
 *   STUDIO_CANVAS_MODULE=/path/to/@napi-rs/canvas node scripts/render-preset-photo-frames.cjs \
 *     --design data/designs/neon-rift.design.json --out build/photo-frames/neon-rift --width 900
 */
const fs=require('fs'),path=require('path'),vm=require('vm'),crypto=require('crypto');
const ROOT=path.resolve(__dirname,'..'),WEB=path.join(ROOT,'web'),ASSETS=path.join(WEB,'assets');
const sha256=value=>crypto.createHash('sha256').update(value).digest('hex');
const relative=value=>path.relative(ROOT,value).split(path.sep).join('/');
const inside=(file,directory)=>file===directory||file.startsWith(directory+path.sep);

function canvasModule(explicit){
 const requested=explicit||process.env.STUDIO_CANVAS_MODULE;
 if(requested)return require(path.isAbsolute(requested)?requested:path.resolve(ROOT,requested));
 try{return require('@napi-rs/canvas');}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
 const fallback=path.join(ROOT,'.tools/gif-render/node_modules/@napi-rs/canvas');
 if(fs.existsSync(fallback))return require(fallback);
 throw Error('An offline Canvas module is required: use --canvas-module or STUDIO_CANVAS_MODULE.');
}

function publicAsset(source){
 if(typeof source!=='string'||!source||path.isAbsolute(source)||/^[a-z][a-z0-9+.-]*:/i.test(source)||source.includes('\\'))throw Error('Photo sources must be relative public web/assets paths.');
 const target=path.resolve(WEB,source);
 if(!inside(target,ASSETS))throw Error('Photo source is outside public web/assets.');
 const real=fs.realpathSync(target);
 if(!inside(real,fs.realpathSync(ASSETS)))throw Error('Photo symlinks must stay inside public web/assets.');
 if(!/\.(?:jpe?g|png|webp)$/i.test(real))throw Error('Unsupported public photo format.');
 return real;
}

function loadInputs(designPath){
 const source=path.resolve(ROOT,designPath),sourceReal=fs.realpathSync(source);
 if(!inside(sourceReal,ROOT)||!sourceReal.endsWith('.design.json'))throw Error('Use a repository-relative .design.json source.');
 const designBytes=fs.readFileSync(sourceReal),design=JSON.parse(designBytes.toString('utf8'));
 const dataPath=path.join(WEB,'data.js'),dataBytes=fs.readFileSync(dataPath),context={window:{}};
 vm.runInNewContext(dataBytes.toString('utf8'),context,{filename:'public-data.js',timeout:5000});
 const data=context.window.STUDIO_DATA;
 if(!data||data.baseConfig!==null||data.snapshot?.connected!==false)throw Error('Expected the sanitized public preview bundle.');
 const modelContext={window:{}},modelBytes=fs.readFileSync(path.join(WEB,'studio-model.js'));
 vm.runInNewContext(modelBytes.toString('utf8'),modelContext,{filename:'studio-model.js',timeout:5000});
 modelContext.window.StudioModel.validate(design);
 const view=JSON.parse(JSON.stringify(data.views?.front));
 if(!view||view.keyZones?.length!==83)throw Error('The public front view must include 83 calibrated key LEDs.');
 const calibrationBytes=fs.readFileSync(path.join(ROOT,'data/photos/photo-calibration.json')),keyCalibrationBytes=fs.readFileSync(path.join(ROOT,'data/photos/key-photo-layout.json'));
 const calibration=JSON.parse(calibrationBytes.toString('utf8')).front;
 const photo=publicAsset('assets/'+(calibration.asset||'front.jpg')),photoBytes=fs.readFileSync(photo);
 // The App embeds this same public file to avoid WebKit local-origin issues.
 // Confirm identity before replacing only its transport URL for offline Node.
 if(typeof view.image==='string'&&view.image.startsWith('data:')){
  const match=/^data:image\/(?:jpeg|png|webp);base64,([A-Za-z0-9+/=]+)$/.exec(view.image);
  if(!match||sha256(Buffer.from(match[1],'base64'))!==sha256(photoBytes))throw Error('Bundled front photo does not match the public asset.');
 }else if(publicAsset(view.image)!==photo)throw Error('Bundled front photo path is inconsistent with calibration.');
 view.image=relative(photo).replace(/^web\//,'');
 return {source:sourceReal,design,view,loopTicks:modelContext.window.StudioModel.cycle(design),hashes:{design:sha256(designBytes),data:sha256(dataBytes),photo:sha256(photoBytes),model:sha256(modelBytes),calibration:sha256(calibrationBytes),keyCalibration:sha256(keyCalibrationBytes)},photo};
}

function minimalDOM(canvas,width){
 const elements=new Map(),events=new Map();
 function element(tag){
  const node={tagName:tag.toUpperCase(),style:{},children:[],attributes:{},clientWidth:width,parentNode:null,className:'',textContent:''};
  const classes=new Set();
  node.classList={add(...names){names.forEach(name=>classes.add(name));},remove(...names){names.forEach(name=>classes.delete(name));},contains(name){return classes.has(name);}};
  node.setAttribute=(name,value)=>{node.attributes[name]=String(value);};
  node.removeAttribute=name=>{delete node.attributes[name];};
  node.appendChild=child=>{child.parentNode=node;node.children.push(child);if(child.id)elements.set(child.id,child);return child;};
  node.remove=()=>{if(node.parentNode)node.parentNode.children=node.parentNode.children.filter(child=>child!==node);};
  return node;
 }
 function canvasElement(){
  const native=canvas.createCanvas(300,150),node=element('canvas');
  Object.assign(native,node);
  native.remove=()=>{if(native.parentNode)native.parentNode.children=native.parentNode.children.filter(child=>child!==native);};
  const get=native.getContext.bind(native);let wrapped;
  native.getContext=kind=>{
   const context=get(kind);
   if(kind==='2d'&&wrapped!==context){const draw=context.drawImage.bind(context);context.drawImage=(source,...args)=>draw(source?._nativeImage||source,...args);wrapped=context;}
   return context;
  };
  return native;
 }
 const document={hidden:false,createElement:tag=>tag==='canvas'?canvasElement():element(tag),getElementById:id=>elements.get(id)||null,addEventListener:(name,callback)=>events.set(name,callback),removeEventListener:name=>events.delete(name)};
 document.head=element('head');document.documentElement=element('html');
 class ImageShim{
  constructor(){this._nativeImage=null;this.onload=null;this.onerror=null;}
  set src(source){
   this._source=source;
   Promise.resolve().then(()=>canvas.loadImage(fs.readFileSync(publicAsset(source)))).then(image=>{this._nativeImage=image;queueMicrotask(()=>this.onload?.());},()=>queueMicrotask(()=>this.onerror?.()));
  }
  get src(){return this._source;}
  get naturalWidth(){return this._nativeImage?.width||0;}
  get naturalHeight(){return this._nativeImage?.height||0;}
  get width(){return this.naturalWidth;}
  get height(){return this.naturalHeight;}
 }
 const global={Image:ImageShim,devicePixelRatio:1,matchMedia:()=>({matches:true,addEventListener(){},removeEventListener(){}}),addEventListener(){},removeEventListener(){},requestAnimationFrame(){throw Error('Offline rendering must use seek(), not animation clocks.');},cancelAnimationFrame(){}};
 return {document,global,container:element('div')};
}

function compositeLayers(canvas,preview){
 const result=canvas.createCanvas(preview.background.width,preview.background.height),context=result.getContext('2d');
 context.fillStyle='#0f1215';context.fillRect(0,0,result.width,result.height);
 context.globalCompositeOperation='source-over';context.drawImage(preview.background,0,0);
 // The browser applies mix-blend-mode:screen to this entire canvas. The
 // screen operation inside the key canvas alone does not reproduce that CSS.
 context.globalCompositeOperation='screen';context.drawImage(preview.keyOverlay,0,0);
 context.globalCompositeOperation='source-over';context.drawImage(preview.overlay,0,0);
 return result;
}

async function renderFrames(options){
 const canvas=canvasModule(options.canvasModule),input=loadInputs(options.design),width=options.width??800;
 if(!Number.isInteger(width)||width<640||width>1400)throw Error('Width must be an integer from 640 to 1400 pixels.');
 const output=path.resolve(ROOT,options.out);
 if(inside(output,ROOT)&&!inside(output,path.join(ROOT,'build')))throw Error('Repository outputs must stay under build/, outside App/source resources.');
 const adapter=minimalDOM(canvas,width),enginePath=path.join(WEB,'preview-engine.js'),engineBytes=fs.readFileSync(enginePath);
 vm.runInNewContext(engineBytes.toString('utf8'),{window:adapter.global,document:adapter.document,console},{filename:'preview-engine.js',timeout:5000});
 let lastFrame;
 const preview=new adapter.global.KeyboardPreview(adapter.container,{views:{front:input.view},design:input.design,view:'front',onFrame:frame=>{lastFrame=frame;}});
 try{
  await preview.ready;preview.pause();preview.setFraming('keyboard');preview.setRenderer('editor');preview.setKeyMode('json');preview.setBrightness(input.design.preview_brightness??100);
  if(preview.error||preview._keySprites.length!==83)throw Error('Photo/key lighting calibration failed.');
  const ticks=options.frame===undefined?Array.from({length:input.loopTicks},(_,i)=>i):[options.frame];
  if(ticks.some(tick=>!Number.isInteger(tick)||tick<0||tick>=input.loopTicks))throw Error('Frame is outside the complete source animation loop.');
  fs.mkdirSync(output,{recursive:true});
  const records=[];
  for(const tick of ticks){
   preview.seek(tick);
   if(preview.error||lastFrame?.tick!==tick||lastFrame.frame!==tick%input.design.frames.length||lastFrame.keyFrame!==tick%input.design.keyframes.length)throw Error('Seek did not render the requested top/key tick.');
   const composed=compositeLayers(canvas,preview),bytes=composed.toBuffer('image/png'),file='frame-'+String(tick).padStart(4,'0')+'.png';
   fs.writeFileSync(path.join(output,file),bytes);
   records.push({file,tick,topFrame:lastFrame.frame,keyFrame:lastFrame.keyFrame,durationMs:input.design.speed_ms,sha256:sha256(bytes)});
  }
  const manifest={schemaVersion:1,kind:'photo-composite-rgb-frames',designId:input.design.id,name:input.design.name,source:relative(input.source),sourceSha256:input.hashes.design,engineSha256:sha256(engineBytes),adapterSha256:sha256(fs.readFileSync(__filename)),modelSha256:input.hashes.model,dataSha256:input.hashes.data,calibrationSha256:input.hashes.calibration,keyCalibrationSha256:input.hashes.keyCalibration,sourcePaths:{engine:relative(enginePath),adapter:relative(__filename),model:'web/studio-model.js',data:'web/data.js',calibration:'data/photos/photo-calibration.json',keyCalibration:'data/photos/key-photo-layout.json'},photo:relative(input.photo),photoSha256:input.hashes.photo,view:'front',framing:'keyboard',renderer:'editor',keyMode:'json',background:'#0f1215',composition:['photo:source-over','keys:screen','top:source-over'],width:preview.background.width,height:preview.background.height,brightness:input.design.preview_brightness??100,sourceFrameCount:input.design.frames.length,topFrameCount:input.design.frames.length,keyFrameCount:input.design.keyframes.length,loopTicks:input.loopTicks,speedMs:input.design.speed_ms,fullLoopDurationMs:input.loopTicks*input.design.speed_ms,frameCount:records.length,totalDurationMs:records.length*input.design.speed_ms,exportedFrames:records.length,exportedDurationMs:records.length*input.design.speed_ms,photoKeyboardOutlinePoints:preview._keyboardOutline.length,keySpriteCount:preview._keySprites.length,warpTriangles:preview._warpTriangles.length,frames:records};
  const temporary=path.join(output,'manifest.json.tmp');fs.writeFileSync(temporary,JSON.stringify(manifest,null,2)+'\n');fs.renameSync(temporary,path.join(output,'manifest.json'));
  return manifest;
 }finally{preview.destroy();}
}

function argumentsFrom(argv){
 const options={};
 const names={'--design':'design','--out':'out','--width':'width','--frame':'frame','--canvas-module':'canvasModule'};
 for(let i=0;i<argv.length;i++){
  if(argv[i]==='--help'||argv[i]==='-h')return {help:true};
  const name=names[argv[i]];if(!name||argv[i+1]===undefined)throw Error('Unknown/missing argument: '+argv[i]);
  if(Object.hasOwn(options,name))throw Error('Duplicate argument: '+argv[i]);options[name]=argv[++i];
 }
 if(!options.design||!options.out)throw Error('Provide --design and --out.');
 for(const name of ['width','frame'])if(options[name]!==undefined){if(!/^\d+$/.test(options[name]))throw Error(name+' must be an integer.');options[name]=Number(options[name]);}
 return options;
}
module.exports={renderFrames,compositeLayers,publicAsset,canvasModule,argumentsFrom};
if(require.main===module)(async()=>{
 const options=argumentsFrom(process.argv.slice(2));
 if(options.help){console.log('Usage: node scripts/render-preset-photo-frames.cjs --design data/designs/name.design.json --out build/photo-frames/name [--width 800] [--frame 80] [--canvas-module path]');return;}
 const result=await renderFrames(options);
 console.log(JSON.stringify({designId:result.designId,width:result.width,height:result.height,exportedFrames:result.exportedFrames,loopTicks:result.loopTicks,speedMs:result.speedMs,sourceSha256:result.sourceSha256,manifest:path.resolve(ROOT,options.out,'manifest.json')}));
})().catch(error=>{console.error('Photo rendering failed: '+error.message);process.exitCode=1;});
