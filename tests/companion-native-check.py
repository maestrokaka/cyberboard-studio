#!/usr/bin/env python3
"""Compile actual companion timing, placement and preferences against isolated fixtures."""
from pathlib import Path
import os, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[1]
code=r'''
func check(_ ok: @autoclosure () -> Bool, _ detail: String) { if !ok() { fatalError(detail) } }
var gate=CompanionInteractionGate()
check(gate.consume("hair",now:0,blocked:false)==nil,"dwell starts")
check(gate.consume("hair",now:0.47,blocked:false)==nil,"early dwell")
check(gate.consume("hair",now:0.5,blocked:false)=="hair","dwell triggers")
check(gate.consume("hair",now:30,blocked:false)==nil,"one response per hover")
_ = gate.consume(nil,now:31,blocked:false)
_ = gate.consume("hair",now:32,blocked:false)
check(gate.consume("hair",now:32.5,blocked:false)=="hair","reenter after cooldown")
_ = gate.consume("cheek",now:33,blocked:false)
check(gate.consume("cheek",now:33.5,blocked:false)==nil,"global cooldown")
check(gate.consume("cheek",now:36,blocked:true)==nil,"drag/task cannot speak")
check(gate.consume("cheek",now:36.2,blocked:false)==nil,"fresh dwell after drag")
check(gate.consume("cheek",now:36.6,blocked:false)=="cheek","new dwell after drag")
_ = gate.consume(nil,now:37,blocked:false)
_ = gate.consume("cheek",now:38,blocked:false)
check(gate.consume("cheek",now:41,blocked:false)==nil,"per-zone cooldown")
let visible=NSRect(x:0,y:0,width:1440,height:900)
for size in [240.0,340,440] {
 for x in [0.0,400,1400] {
  let a=CompanionPlacement.calculate(anchor:NSPoint(x:x,y:800),size:size,expanded:false,visible:visible)
  let b=CompanionPlacement.calculate(anchor:NSPoint(x:a.frame.minX,y:a.frame.minY),size:size,expanded:true,visible:visible)
  check(visible.contains(a.frame) && visible.contains(b.frame),"expanded bubble off screen")
  check(a.frame.minX+a.image.minX == b.frame.minX+b.image.minX,"pet jumps when bubble expands")
  let c=CompanionPlacement.calculate(anchor:NSPoint(x:b.frame.minX+b.image.minX,y:b.frame.minY),size:size,expanded:false,visible:visible)
  check(c.frame.minX==a.frame.minX && c.frame.minY==a.frame.minY,"pet jumps when bubble closes")
 }
}
let root=URL(fileURLWithPath:CommandLine.arguments[1]), temp=URL(fileURLWithPath:CommandLine.arguments[2])
let suite="CompanionTests."+UUID().uuidString, defaults=UserDefaults(suiteName:suite)!
defer { defaults.removePersistentDomain(forName:suite) }
let style=CompanionStyle(resources:root,defaults:defaults,stateRoot:temp)
check(!style.resident && !style.soundEnabled,"defaults automatically enable pet/sound")
var prefs=style.preferences;prefs["mode"]="resident";prefs["outfit"]="sailor-long";prefs["voice"]="mature"
try style.save(prefs)
check(CompanionStyle(resources:root,defaults:defaults,stateRoot:temp).preferences["outfit"] as? String == "sailor-long","outfit not persistent")
check(style.picture() != nil && style.picture("ears") != nil,"packaged pose unavailable")
for (key,value) in [("outfit","../../a" as Any),("volume",Double.nan),("size",900),("voice","unknown")] {
 var invalid=prefs;invalid[key]=value
 do { try style.save(invalid);fatalError("invalid settings accepted: "+key) } catch {}
}
check(style.zone(at:NSPoint(x:0.4,y:0.29))?["id"] as? String == "ribbon","zone overlap priority")

let customFolder=temp.appendingPathComponent("companion-outfits")
try FileManager.default.createDirectory(at:customFolder,withIntermediateDirectories:true)
let png=try Data(contentsOf:root.appendingPathComponent("web/assets/companion/sailor-short/idle.png"))
for i in 0..<20 {
 let id="custom-"+String(format:"%032x",i)
 try png.write(to:customFolder.appendingPathComponent(id+".png"))
 try Data("{\"hair\":\"long\"}".utf8).write(to:customFolder.appendingPathComponent(id+".json"))
}
check(style.customOutfits().count==20,"PNG+metadata must still expose all twenty outfits")
private let view=MiaoCallDraggablePetView(frame:NSRect(x:0,y:0,width:320,height:640))
let idle=style.picture()!, reaction=style.picture("wave")!
view.image=idle;view.setInteractionImage(idle)
var initial:[String?]=[]
for y in stride(from:10.0,to:630.0,by:20) { for x in stride(from:10.0,to:310.0,by:20) {
 initial.append(view.opaquePoint(NSPoint(x:x,y:y),forInteraction:true).flatMap{ style.zone(at:$0)?["id"] as? String })
}}
view.image=reaction
var after:[String?]=[]
for y in stride(from:10.0,to:630.0,by:20) { for x in stride(from:10.0,to:310.0,by:20) {
 after.append(view.opaquePoint(NSPoint(x:x,y:y),forInteraction:true).flatMap{ style.zone(at:$0)?["id"] as? String })
}}
check(initial==after && initial.contains(where:{$0 != nil}),"stationary pointer changed hit zone with pose")
check(CompanionPalette(light:true).background.alphaComponent==1 && CompanionPalette(light:false).background.alphaComponent==1,"bubble must hide underlying text")
check(CompanionPalette(light:true).text.redComponent < 0.5 && CompanionPalette(light:false).text.usingColorSpace(.sRGB)!.redComponent > 0.9,"theme text contrast inverted")
print("PASS all twenty PNG+metadata outfits and stable idle-mask hit zones across reaction poses")
print("PASS companion dwell/cooldowns/drag; 9 edge placements; isolated defaults/persistence/validation and real pose assets")
'''
with tempfile.TemporaryDirectory(prefix='Companion-native-') as temp:
    temp=Path(temp);source=temp/'main.swift';native=(ROOT/'native/MiaoCall.swift').read_text();pet=native[native.index('private final class MiaoCallDraggablePetView'):native.index('private final class MiaoCallOverlay')]
    source.write_text((ROOT/'native/Companion.swift').read_text()+pet+code)
    env=os.environ.copy();env['CLANG_MODULE_CACHE_PATH']=str(ROOT/'build/swift-module-cache')
    subprocess.run(['/usr/bin/swiftc',str(source),'-o',str(temp/'check')],env=env,check=True)
    subprocess.run([str(temp/'check'),str(ROOT),str(temp)],check=True)
