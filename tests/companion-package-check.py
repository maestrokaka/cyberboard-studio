#!/usr/bin/env python3
"""Companion actions in the actual frozen App. Temp stores only; no network or device access."""
import argparse, json, os, subprocess, tempfile
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);args=parser.parse_args()
resources=args.app.resolve()/'Contents/Resources';binary=resources/'backend/CyberboardBackend/CyberboardBackend'
with tempfile.TemporaryDirectory(prefix='companion-package-') as directory:
    temp=Path(directory);env=os.environ.copy();env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None);env['CYBERBOARD_DATA_DIR']=str(temp/'cli')
    def call(action,payload):
        result=subprocess.run([str(binary),'--action',action,'--state-dir',str(temp/'state'),'--resource-dir',str(resources)],input=json.dumps(payload),text=True,capture_output=True,env=env,timeout=20)
        assert result.returncode==0, result.stderr[:300]
        value=json.loads(result.stdout); assert 'error' not in value,value
        return value['result']
    value=call('companionImageSettings',{});assert not value['hasKey'] and not value['canReuseVoiceKey']
    value=call('companionImageSave',{'apiKey':'fixture-not-a-real-key','region':'china'});assert value['hasKey'] and 'apiKey' not in value
    assert call('companionImageReveal',{})['apiKey']=='fixture-not-a-real-key'
    assert not call('companionImageSave',{'removeKey':True})['hasKey']
    assert not (temp/'cli/current.json').exists()
print('PASS actual frozen companion module, isolated connection/key save-reveal-delete; no network, user keys or USB')
