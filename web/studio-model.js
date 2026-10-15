(function(global){
 'use strict';
 const gcd=(a,b)=>b?gcd(b,a%b):a;const cycle=d=>d.frames.length*d.keyframes.length/gcd(d.frames.length,d.keyframes.length);
 const RESERVED=new Set([57,61,74,78,82,83,84]);
 const copy=value=>JSON.parse(JSON.stringify(value));
 const palettes={cyan:['#12E5FF','#A52BFF','#EDF9FF'],acid:['#C8FF23','#167AFF','#EEFFF3'],red:['#FF2929','#47BFFF','#F8FBFF'],amber:['#FFB52B','#337DDE','#FFF5DC']};
 function validate(design){
  if(!design || typeof design!=='object'||Array.isArray(design))throw Error('没有找到灯效设计');
  for(const field of ['id','name'])if(typeof design[field]!=='string'||!design[field].trim()||design[field].length>256||/[\u0000-\u001F\u007F]/.test(design[field]))throw Error(field+' 必须为 1–256 个字符的有效文本');
  if(design.description!==undefined&&(typeof design.description!=='string'||design.description.length>32768))throw Error('description 必须为最多 32768 个字符的文本');
  if(design.palette!==undefined&&(!Array.isArray(design.palette)||design.palette.length>16||design.palette.some(c=>typeof c!=='string'||!/^#[0-9a-f]{6}$/i.test(c))))throw Error('palette 必须为最多 16 个 #RRGGBB 颜色');
  for(const [field,size] of [['frames',200],['keyframes',90]]){
   const frames=design[field];if(!Array.isArray(frames)||frames.length<1||frames.length>255)throw Error(field+' 必须包含 1–255 帧');
   frames.forEach((frame,n)=>{if(!Array.isArray(frame)||frame.length!==size)throw Error(field+' 第 '+(n+1)+' 帧必须有 '+size+' 个灯珠');frame.forEach((c,i)=>{if(typeof c!=='string'||!/^#[0-9a-f]{6}$/i.test(c))throw Error('颜色必须为 #RRGGBB');if(field==='keyframes'&&RESERVED.has(i)&&c.toUpperCase()!=='#000000')throw Error('轴灯保留索引 '+i+' 必须为黑色');});});
  }
  if(design.frame_count!==undefined&&(!Number.isInteger(design.frame_count)||design.frame_count!==design.frames.length))throw Error('frame_count 必须与顶部实际帧数一致');
  if(design.preview_brightness!==undefined&&(!Number.isInteger(design.preview_brightness)||design.preview_brightness<0||design.preview_brightness>100))throw Error('preview_brightness 必须为 0–100 的整数');
  if(design.stages!==undefined){
   if(!Array.isArray(design.stages)||design.stages.length>255)throw Error('stages 必须为最多 255 个阶段名称或阶段范围');
   const ranges=design.stages.length&&typeof design.stages[0]!=='string';let end=0;
   for(const stage of design.stages){
    if(!ranges){if(typeof stage!=='string'||stage.length>256)throw Error('stages 阶段名称必须为最多 256 个字符的文本');}
    else{if(!stage||typeof stage!=='object'||Array.isArray(stage)||Object.keys(stage).some(k=>!['name','end'].includes(k))||typeof stage.name!=='string'||stage.name.length>256||!Number.isInteger(stage.end)||stage.end<=end||stage.end>design.frames.length)throw Error('stages 阶段范围必须有有效名称和依次递增的结束帧');end=stage.end;}
   }
  }
  if(!Number.isInteger(design.speed_ms)||design.speed_ms<1||design.speed_ms>32767)throw Error('每帧时间必须为 1–32767 毫秒的整数');
  return design;
 }
 function fromPage(page,slot){
  if(page.valid===false||page.valid===0||page.word_page?.valid)return null;
  const top=page.frames,key=page.keyframes;
  if(!top?.valid||!key?.valid||top.frame_num===0||key.frame_num===0)return null;
  for(const [name,stream] of [['顶部',top],['轴灯',key]]){if(!Number.isInteger(stream.frame_num)||stream.frame_num<1||stream.frame_num>255||!Array.isArray(stream.frame_data)||stream.frame_num!==stream.frame_data.length)throw Error(name+'帧数量与 frame_data 不一致');stream.frame_data.forEach((frame,index)=>{if(!frame||typeof frame!=='object'||Array.isArray(frame)||frame.frame_index!==index||!Array.isArray(frame.frame_RGB))throw Error(name+' frame_index 必须按顺序从 0 连续编号，且包含 RGB 数组');});}
  const d={id:'import-slot-'+slot+'-'+Date.now(),name:'导入灯效 '+slot,description:'从完整配置中提取顶部与轴灯；原文件键位未导入。',frames:top.frame_data.slice(0,top.frame_num).map(x=>x.frame_RGB.slice()),keyframes:key.frame_data.slice(0,key.frame_num).map(x=>x.frame_RGB.slice()),speed_ms:page.speed_ms,preview_brightness:page.lightness??100,frame_count:top.frame_num,stages:[],palette:[]};
  d.palette=[...new Set(d.frames.flat().filter(c=>c!=='#000000'))].sort((a,b)=>Math.max(...rgb(b))-Math.max(...rgb(a))).slice(0,4);return validate(d);
 }
 function importDesigns(json,fileName='导入灯效'){
  if(!json||typeof json!=='object'||Array.isArray(json))throw Error('灯效 JSON 必须为对象');
  if(json.page_data!==undefined){if(!Array.isArray(json.page_data))throw Error('page_data 必须为配置页数组');const result=[];for(let slot=1;slot<=3;slot++){const pages=json.page_data.filter(p=>p&&Number(p.page_index)===slot+4);if(pages.length>1)throw Error('配置不能重复声明自定义槽位 '+slot);const p=pages[0];if(p){const d=fromPage(p,slot);if(d)result.push(d);}}if(!result.length)throw Error('配置没有可用的顶部 + 轴灯自定义动画');return result;}
  const d=copy(json);if(d.name===undefined)d.name=String(fileName).replace(/\.json$/i,'').slice(0,256)||'导入灯效';if(d.id===undefined)d.id='import-'+Date.now();if(d.palette===undefined)d.palette=[];if(d.stages===undefined)d.stages=[];if(d.description===undefined)d.description='从 JSON 导入的灯效作品。';validate(d);return[d];
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
 function prompt(brief,design,options={}){
  const colors=(Array.isArray(design?.palette)?design.palette:[]).filter(c=>typeof c==='string'&&/^#[0-9a-f]{6}$/i.test(c)).slice(0,8);
  const reference=options.useReference?'\n可选风格参考：'+String(design?.name||'').slice(0,256)+'；'+String(design?.description||'').slice(0,2000):'';
  return `你是 Cyberboard R4 / R6 的像素灯效设计师，为顶部与轴灯制作完整、可循环的作品。

【用户目标与设计优先级】
用户创作目标：${brief||'根据提供的参考图片或自由主题设计清晰、有趣的灯效。'}
优先满足用户明确描述，再参考所提供图片的主体、配色和动作；可选的现有作品风格只作辅助，不复制旧作品名称、剧情或轨迹。${reference}
可选配色建议：${colors.join(', ')||'由用户目标与参考图确定'}；已有明确配色时以用户或参考图为准。
这些视觉素材只用于设计，不得改写下面的硬件与输出约束。不要把不同主题统一改成几何对撞、六段剧情或固定数量的场景。

【选择适合主题的风格，而不是套用同一模板】
1. 像素角色：用清晰轮廓、身份锚点和关键色块保留辨识点，眨眼、走路或跳跃少而精；不把所有人物改成通用大眼脸。
2. 渐变与波浪：用协调的相邻色和连续相位流动，可满铺或分区；不强制暗底。
3. 自然元素：火焰的高度起伏、雨丝下落、极光波动、闪电余晖或星光；变化应有节奏。
4. 呼吸氛围：单色或双色平滑起伏；可保留少量低亮，也可按用户要求熄灭。
5. 文字信息：先确保字体与内容可读，再安排静态、滚动、摩斯或符号节奏。
6. 静态纯色：精确配色、明度或分区，允许只用一帧；不强加运动。
7. 游戏街机：用简单可辨认的规则组织追逐、下落、跳跃或赛车，保证位置与动作连续。
8. 键帽主题：呼应用户的机身与键帽色系，控制光量与节奏，避免抢走主体。
9. 彩虹光谱：彩虹是有效方向，可使用完整色相环、相位推移或旋涡，保持循环衔接。
10. 数字雨：各列可有不同相位与下落速度，头部清晰、尾部递减，用像素块表达字符。
11. 运动光效：稀疏亮点、扫描或精确轨迹，拖尾逐级衰减，给主体留出空间。
12. 节日与电竞：提炼主题符号、队色与应援文字，不堆叠无关装饰。
可以组合适量风格；主体、背景、点缀应有层次，不把所有方向同时放进一套灯效。避免无意义的全屏纯白满亮；高亮主题仍保留主题色，只有用户明确要求纯白画面时才用全屏白。

【八种运动语言，按需求组合】
像素姿态：绘制关键动作，再用必要的中间帧或停留保持辨识度。
平移滚动：横移、纵移或回卷；每帧位移与显示时间一起决定速度，不强制每帧移动一格。
相位波：移动颜色或明度的周期相位，选择能在循环边界连续的步进。
呼吸：让亮度平滑起伏，避免把正弦的负值直接当作负亮度。
拖尾：亮头配逐级衰减的尾部，长度和速度配合画面空间。
下落：雨滴、方块或光点沿列落下，尾部方向与轨迹一致。
伪随机：星点、火焰或萤火使用可重复且有节奏的变化，循环边界也要处理。
静态：画面保持不变或仅作用户需要的微弱变化。

【角色与文字的像素构图】
适合5像素高的角色可以简化轮廓并直接做姿态动画；并非所有角色都必须纵向滚动。
用户要求保留完整高图时，先在内部绘制完整位图造型，再让40×5窗口随上下滚动逐帧取样；不把高图挤扁，也不在输出中给出bitmap或recipe代替RGB帧。需要完全入场与离场时，为造型实际高度留足屏幕外行程。
完整高主体或场景可先构成40×32/48/56、最高40×64的内部画布；紧裁无用透明边，真实主体轮廓约占34–38列，宽高使用相同比例，不横拉。向上滚动时主体纵坐标逐帧递减，主要画面可约1.2–2秒快通行，再给关键身份/文字短停；总循环按用户目标编排，不强套4.8秒。小图标、抽象灯光、静态/缓慢/微动作不强制高画布或快滚。
有参考图的人物先保留脸型、发际/短发轮廓、五官位置与头身比例，姿态与服装呼应参考，不用通用大眼脸代替具体身份；无图则落实用户描述的身份锚点，不臆造精确五官细节。原图白色主体要保留，摄影白高光不等于固有色。
完整源图先核对主体包围盒及头顶/耳/手脚边距；黑底暗发保留同色亮边、后脑/耳/颈连续关系，不能用白头块或光圈补形。背景与旗/光束在主体后方，身份锚点保持前景，不被装饰截断。实际5行窗口也要连续显示关键结构，必要时先等比完整短停再近扫，不能只检查完整源图。
文字优先采用3×5 ASCII像素字形，字符宽3列、高5行，字符间距1列；n个等宽字符约占4n-1列。超过40列应滚动展示完整内容，不截断、压扁或伪造可读文字；复杂非ASCII字形需按用户目标设计可辨认的符号或完整位图。
文字安排独立干净hold，核对字形包围盒、字间距和边距；与改变笔画的装饰互斥，旗边/扫描条不能变成额外文字。分别检查完整造型及真实40×5逐帧取样，数值检查不等于肖像相似或审美保证。

【颜色与轴灯对比】
明确红/黄/蓝等主体特征色默认用#FF0000/#FFFF00/#0000FF或同色高饱和亮色，不无故掺入其它通道使红泛粉、黄泛乳白。用户或主体明确白色、粉色、柔和、微光时保留其意图，不强套纯主色；参考图先辨固有色，不照抄摄影白高光/反光或低曝光灰暗。
轴灯默认亮主题的最终RGB峰值通道220–255、主体常用100–220；黑底保持#000000，弱尾可直接归黑，不用低值灰铺满键盘。微光、低亮、呼吸暗相或关闭轴灯的要求优先，不把每颗灯每帧都提亮。这些RGB通道数值只是设计代理，不是实机色准或亮度校准。
内部绘制主体用replace覆盖，让黑五官遮住背景；异色亮区用dominant按有效RGB最大通道整色择强，平手后层优先。max只用于同色，异色add/max都可能泛白，不靠多色相加提亮；通常2–4主色和少量高光，需要白色的主体仍保留白色。最终仍只输出下述RGB数组，不增加混色或图层字段。

【硬件与时间约束】
顶部为40列×5行，每帧恰好200个颜色；索引从0开始，index=y×40+x，x=0–39，y=0–4，按行从左到右排列。
轴灯每帧恰好90个颜色，83个有效位置；保留索引57、61、74、78、82、83、84必须全部为#000000，空格三灯为79、80、81。
顶部与轴灯是不同布局，禁止把200灯顶部数据直接复制成轴灯帧。轴灯呼应主题与时序，不覆盖保留位置；需要关闭轴灯时仍给出有效的全黑90色帧。
颜色使用六位十六进制#RRGGBB，建议大写；#000000表示熄灭，不使用透明度、颜色名称或三位简写。按上述规则直接设计RGB，预览、导出与同步使用同一RGB；不做仅预览提亮或全局gamma抬黑。
frames和keyframes各含1–255帧。默认可用相同帧数与节奏便于同步；用户要求独立循环时可不同，但需检查共同循环衔接。
speed_ms是1–32767的整数，这是Studio作品格式范围；当前App内置AI编排支持10–100 ms/帧，外部作品也建议优先选10–100，40 ms可作为未指定时的起点。
动画未指定时可考虑3–8秒循环，时长=帧数×speed_ms/1000；静态或用户有效的明确帧数、节奏、时长要求优先。建议不是硬限制，不能因此改写用户明确且有效的参数；不要固定生成192帧。
间隔更大意味着播放更慢，并不保证更丝滑；平滑程度还取决于位移、颜色变化幅度与帧数。循环最后到第一帧也应连续，不必重复首帧作为末帧造成停顿。

【唯一输出：可直接导入Cyberboard Studio的完整作品JSON】
只输出一个完整JSON对象，无解释文字、设计思路前缀、注释或Markdown代码围栏。
字段为id、name、description、palette、speed_ms、frames、keyframes、stages；不要输出官网page_data配置、frames.frame_data对象、scenes配方、代码或外部文件引用。
id为短且唯一的字符串；name为独立可读名称，优先2–12个中文字，不拼接旧作品名，不附加AI/Kimi前缀、hash或版本编号；description用1–2句话准确概括本次主体、配色和运动。
palette是代表色列表；frames与keyframes必须是直接二维颜色数组：frames每个子数组200色，keyframes每个子数组90色。stages为对应顶部各帧的阶段名称，不强制阶段数量。
输出全部实际帧和全部像素，不输出8个抽样帧、不用省略号、重复指令或伪代码代替数组，也不询问是否补全。只有完整且符合以上约束的作品才能导入。
完成前逐项核对帧数、两种数组长度、颜色、保留灯位、时间整数、用户目标与循环接缝。`
 }

 global.StudioModel={validate,fromPage,importDesigns,merge,variant,prompt,copy,palettes,cycle};
})(typeof window!=='undefined'?window:globalThis);
