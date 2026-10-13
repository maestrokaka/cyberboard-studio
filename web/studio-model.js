(function(global){
 'use strict';
 const gcd=(a,b)=>b?gcd(b,a%b):a;const cycle=d=>d.frames.length*d.keyframes.length/gcd(d.frames.length,d.keyframes.length);
 const RESERVED=new Set([57,61,74,78,82,83,84]);
 const copy=value=>JSON.parse(JSON.stringify(value));
 const palettes={cyan:['#12E5FF','#A52BFF','#EDF9FF'],acid:['#C8FF23','#167AFF','#EEFFF3'],red:['#FF2929','#47BFFF','#F8FBFF'],amber:['#FFB52B','#337DDE','#FFF5DC']};
 function validate(design){
  if(!design || typeof design!=='object')throw Error('没有找到灯效设计');
  for(const [field,size] of [['frames',200],['keyframes',90]]){
   const frames=design[field];if(!Array.isArray(frames)||frames.length<1||frames.length>255)throw Error(field+' 必须包含 1–255 帧');
   frames.forEach((frame,n)=>{if(!Array.isArray(frame)||frame.length!==size)throw Error(field+' 第 '+(n+1)+' 帧必须有 '+size+' 个灯珠');frame.forEach((c,i)=>{if(typeof c!=='string'||!/^#[0-9a-f]{6}$/i.test(c))throw Error('颜色必须为 #RRGGBB');if(field==='keyframes'&&RESERVED.has(i)&&c.toUpperCase()!=='#000000')throw Error('轴灯保留索引 '+i+' 必须为黑色');});});
  }
  if(!Number.isInteger(design.speed_ms)||design.speed_ms<1||design.speed_ms>32767)throw Error('每帧时间必须为 1–32767 毫秒的整数');
  return design;
 }
 function fromPage(page,slot){
  const top=page.frames,key=page.keyframes;
  if(!top?.valid||!top.frame_num||!key?.valid||!key.frame_num)return null;
  for(const [name,stream] of [['顶部',top],['轴灯',key]]){if(!Number.isInteger(stream.frame_num)||stream.frame_num<1||stream.frame_num>255||!Array.isArray(stream.frame_data)||stream.frame_num!==stream.frame_data.length)throw Error(name+'帧数量与 frame_data 不一致');}
  const d={id:'import-slot-'+slot+'-'+Date.now(),name:'导入灯效 '+slot,description:'从完整配置中提取顶部与轴灯；原文件键位未导入。',frames:top.frame_data.slice(0,top.frame_num).map(x=>x.frame_RGB.slice()),keyframes:key.frame_data.slice(0,key.frame_num).map(x=>x.frame_RGB.slice()),speed_ms:page.speed_ms,frame_count:top.frame_num,stages:[],palette:[]};
  d.palette=[...new Set(d.frames.flat().filter(c=>c!=='#000000'))].sort((a,b)=>Math.max(...rgb(b))-Math.max(...rgb(a))).slice(0,4);return validate(d);
 }
 function importDesigns(json,fileName='导入灯效'){
  if(json.page_data){const result=[];for(let slot=1;slot<=3;slot++){const p=json.page_data.find(p=>Number(p.page_index)===slot+4);if(p){const d=fromPage(p,slot);if(d)result.push(d);}}if(!result.length)throw Error('配置没有可用的顶部 + 轴灯自定义动画');return result;}
  const d=copy(json);d.name=String(d.name||fileName.replace(/\.json$/i,''));d.id=String(d.id||'import-'+Date.now());d.palette=d.palette||[];d.stages=d.stages||[];d.description=d.description||'从 JSON 导入的灯效作品。';validate(d);return[d];
 }
 function merge(config,assignments){
  const result=copy(config);if(!result?.page_data)throw Error('缺少完整配置基线');const slots=new Set();
  for(const a of assignments){if(!Number.isInteger(a.slot)||a.slot<1||a.slot>3||slots.has(a.slot))throw Error('槽位必须为不重复的 1、2 或 3');slots.add(a.slot);validate(a.design);if(!Number.isInteger(a.speedMs)||a.speedMs<1||a.speedMs>32767||!Number.isInteger(a.brightness)||a.brightness<0||a.brightness>100)throw Error('亮度或节奏超出范围');const page=result.page_data.find(p=>Number(p.page_index)===a.slot+4);if(!page)throw Error('基线缺少槽位 '+a.slot);page.valid=true;page.speed_ms=a.speedMs;page.lightness=a.brightness;page.word_page={valid:0,word_len:0,unicode:[]};for(const field of ['frames','keyframes']){page[field]={valid:1,frame_num:a.design[field].length,frame_data:a.design[field].map((f,i)=>({frame_index:i,frame_RGB:f.slice()}))};}}
  delete result._provenance;return result;
 }
 function rgb(c){return[1,3,5].map(i=>parseInt(c.slice(i,i+2),16));}
 function hue(c){const [r,g,b]=rgb(c).map(x=>x/255),mx=Math.max(r,g,b),mn=Math.min(r,g,b),delta=mx-mn;if(delta<.0001)return 0;let h=mx===r?(g-b)/delta:mx===g?(b-r)/delta+2:(r-g)/delta+4;return (h*60+360)%360;}
 function chroma(c){const v=rgb(c);return Math.max(...v)-Math.min(...v);}
 function rotated(c,shift){const v=rgb(c).map(x=>x/255),mx=Math.max(...v),mn=Math.min(...v),d=mx-mn;if(d<.03)return c.toUpperCase();const h=(hue(c)+shift+360)%360,x=d*(1-Math.abs(h/60%2-1));let vv=h<60?[d,x,0]:h<120?[x,d,0]:h<180?[0,d,x]:h<240?[0,x,d]:h<300?[x,0,d]:[d,0,x];return '#'+vv.map(x=>Math.round((x+mn)*255).toString(16).padStart(2,'0')).join('').toUpperCase();}
 function variant(base,color,speedMs,brief){
  validate(base);const target=palettes[color];const d=copy(base);const original=(d.palette||[]).find(c=>chroma(c)>20)||d.frames.flat().find(c=>chroma(c)>20)||'#12E5FF';
  if(target){const shift=hue(target[0])-hue(original);d.frames=d.frames.map(f=>f.map(c=>rotated(c,shift)));d.keyframes=d.keyframes.map(f=>f.map(c=>rotated(c,shift)));d.palette=(d.palette?.length?d.palette:[original]).map(c=>rotated(c,shift));}
  d.id='variant-'+Date.now();d.name=base.name+' · '+({cyan:'冰蓝',acid:'酸绿',red:'热红',amber:'琥珀'}[color]||'节奏变体');d.speed_ms=speedMs;d.description='基于「'+base.name+'」的本地模板变体。'+(brief?'创作备注：'+brief:'保留原动画结构，调整配色与播放节奏。');d.origin='template-variant';d.frame_count=d.frames.length;return validate(d);
 }
 function prompt(brief,design){return `为 Cyberboard R4 / R6 设计灯效。\n创作方向：${brief||design.description}\n参考作品：${design.name}\n外观：黑白几何图案、金属反光机身、黑色透明键帽。避免普通彩虹，设计有叙事的几何变形和纵向滚动转场。\n输出单个 JSON 对象，不要 Markdown：\n{id,name,description,palette,speed_ms,frames,keyframes,stages}\nframes：1–255 帧，每帧必须有 200 个 #RRGGBB；40 列 × 5 行，按行从左到右排列。\nkeyframes：1–255 帧，每帧必须有 90 个 #RRGGBB；保留索引 57,61,74,78,82,83,84 必须 #000000；空格灯索引 79,80,81。\nspeed_ms：正整数，建议 40ms。顶部与轴灯同步设计，保留原始 RGB，不因预览而提高亮度。\nstages：每个顶部帧对应的阶段名称。包含起势、展开、高潮、循环衔接，注意只有 5 行的可读性。\n参考配色：${(design.palette||[]).join(', ')}\n不要输出键位或设备配置字段。`}
 global.StudioModel={validate,fromPage,importDesigns,merge,variant,prompt,copy,palettes,cycle};
})(typeof window!=='undefined'?window:globalThis);
