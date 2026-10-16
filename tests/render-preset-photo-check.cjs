/* Isolated original-engine rendering checks. Writes only temporary build output. */
'use strict';
const fs=require('fs'),path=require('path'),assert=require('assert/strict'),crypto=require('crypto'),vm=require('vm');
const {renderFrames,compositeLayers,publicAsset,canvasModule}=require('../scripts/render-preset-photo-frames.cjs');
const ROOT=path.resolve(__dirname,'..'),hash=data=>crypto.createHash('sha256').update(data).digest('hex');
const pixel=(canvas,x=0,y=0)=>[...canvas.getContext('2d').getImageData(x,y,1,1).data];
(async()=>{
 const modulePath=process.argv[2],canvas=canvasModule(modulePath);
 for(const source of ['https://example.com/a.jpg','file:///tmp/a.jpg','../data/photos/source-archive/desk.jpg','/tmp/a.jpg'])assert.throws(()=>publicAsset(source),/relative|outside/);
 const layer=color=>{const c=canvas.createCanvas(1,1);if(color){c.getContext('2d').fillStyle=color;c.getContext('2d').fillRect(0,0,1,1);}return c;};
 const bg=layer('#404040'),keys=layer('rgba(128,0,0,0.5)'),led=layer(),before=hash(bg.toBuffer('image/png'));
 const composed=compositeLayers(canvas,{background:bg,keyOverlay:keys,overlay:led}),screen=pixel(composed);
 assert.ok(screen[0]>=110&&screen[0]<=114);assert.equal(screen[1],64);assert.equal(screen[2],64);assert.equal(hash(bg.toBuffer('image/png')),before);
 const source=path.join(ROOT,'data/designs/neon-rift.design.json'),sourceHash=hash(fs.readFileSync(source)),design=JSON.parse(fs.readFileSync(source,'utf8'));
 const directory=fs.mkdtempSync(path.join(ROOT,'build/photo-adapter-check-'));
 try{
  const keyOff={...design,id:'test-photo-keys-off',keyframes:design.keyframes.map(()=>Array(90).fill('#000000'))};
  const topOff={...design,id:'test-photo-top-off',frames:design.frames.map(()=>Array(200).fill('#000000'))};
  fs.writeFileSync(path.join(directory,'keys-off.design.json'),JSON.stringify(keyOff));fs.writeFileSync(path.join(directory,'top-off.design.json'),JSON.stringify(topOff));
  const run=(source,out)=>renderFrames({design:source,out:path.join(directory,out),width:800,frame:80,canvasModule:modulePath});
  const a=await run(source,'original'),again=await run(source,'repeat'),k=await run(path.join(directory,'keys-off.design.json'),'keys-off'),t=await run(path.join(directory,'top-off.design.json'),'top-off');
  assert.equal(a.frameCount,1);assert.equal(a.sourceFrameCount,192);assert.equal(a.loopTicks,192);assert.equal(a.totalDurationMs,40);assert.equal(a.fullLoopDurationMs,7680);assert.equal(a.keySpriteCount,83);assert.equal(a.warpTriangles,128);assert.equal(a.frames[0].sha256,again.frames[0].sha256,'explicit seek must be deterministic');
  const image=async out=>{const im=await canvas.loadImage(fs.readFileSync(path.join(directory,out,'frame-0080.png'))),c=canvas.createCanvas(im.width,im.height);c.getContext('2d').drawImage(im,0,0);return c.getContext('2d').getImageData(0,0,c.width,c.height).data;};
  const [original,keyBlack,topBlack]=await Promise.all(['original','keys-off','top-off'].map(image));
  const c={window:{}};vm.runInNewContext(fs.readFileSync(path.join(ROOT,'web/data.js'),'utf8'),c);const view=c.window.STUDIO_DATA.views.front,[cx,cy,cw,ch]=view.crop;
  const bounds=points=>{const x=points.map(p=>(p[0]-cx)*a.width/cw),y=points.map(p=>(p[1]-cy)*a.height/ch);return [Math.floor(Math.min(...x))-2,Math.floor(Math.min(...y))-2,Math.ceil(Math.max(...x))+2,Math.ceil(Math.max(...y))+2];};
  const keyBounds=bounds(view.keyZones.flatMap(zone=>zone.quad)),topBounds=bounds([...view.quad,...view.mask_quad]);
  function changedOnlyWithin(other,box){let count=0;for(let i=0;i<original.length;i+=4)if(original[i]!==other[i]||original[i+1]!==other[i+1]||original[i+2]!==other[i+2]){count++;const x=i/4%a.width,y=Math.floor(i/4/a.width);assert.ok(x>=box[0]&&x<=box[2]&&y>=box[1]&&y<=box[3],'a lighting variant changed unrelated photo pixels');}assert.ok(count>100,'the synthetic off variant must visibly change its lighting region');return count;}
  const changedKeys=changedOnlyWithin(keyBlack,keyBounds),changedTop=changedOnlyWithin(topBlack,topBounds);
  assert.equal(hash(fs.readFileSync(source)),sourceHash,'the preset RGB source remains byte-for-byte unchanged');
  console.log(JSON.stringify({passed:true,deterministicSeek:true,correctScreenBlend:true,keyOffChangedPixels:changedKeys,topOffChangedPixels:changedTop,unrelatedPhotoPixelsStable:true,sourceUnchanged:true,singleFrameCount:a.frameCount,sourceFrameCount:a.sourceFrameCount,keySpriteCount:a.keySpriteCount,warpTriangles:a.warpTriangles}));
 }finally{fs.rmSync(directory,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1});
