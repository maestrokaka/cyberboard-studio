#!/usr/bin/env python3
"""Offline release gate. No live services, microphone capture or USB operations."""
import argparse, json, os, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PYTHON_TESTS=['device-sync-state-check.py','r6-audio-check.py','r6-keymap-check.py','r6-partial-lighting-check.py','r6-firmware-check.py','backend-check.py','ai-conversation-check.py','workspace-conversation-check.py','speech-input-check.py','companion-check.py','miaocall-codex-check.py','agent-tasks-check.py','codex-connection-check.py']
JS_TESTS=['r6-audio-ui-check.cjs','r6-keymap-ui-check.cjs','model-check.cjs','chat-ui-check.cjs','workspace-save-ui-check.cjs','miaocall-ui-check.cjs','agent-tasks-ui-check.cjs','codex-setup-ui-check.cjs','theme-ui-check.cjs','appearance-performance-check.cjs','preview-aspect-check.cjs']
MAC_TESTS=['r6-native-audio-check.py','companion-native-check.py','miaocall-native-check.py','native-workspace-exit-check.py']
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mac-native',action='store_true');p.add_argument('--output',type=Path,default=ROOT/'build/release-check');args=p.parse_args()
 args.output.mkdir(parents=True,exist_ok=True);results=[]
 tests=[(sys.executable,f) for f in PYTHON_TESTS]+[('node',f) for f in JS_TESTS]
 if args.mac_native:tests += [(sys.executable,f) for f in MAC_TESTS]
 for runtime,name in tests:
  start=time.monotonic()
  with (args.output/(name+'.log')).open('w') as log:
   try:r=subprocess.run([runtime,str(ROOT/'tests'/name)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=240);code=r.returncode
   except subprocess.TimeoutExpired:code=124
  results.append({'test':name,'exitCode':code,'seconds':round(time.monotonic()-start,2)})
  print(('PASS ' if code==0 else 'FAIL ')+name,flush=True)
 (args.output/'report.json').write_text(json.dumps({'offline':True,'results':results},indent=2)+'\n')
 return int(any(r['exitCode'] for r in results))
if __name__=='__main__':sys.exit(main())
