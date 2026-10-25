#!/usr/bin/env python3
"""Actual frozen task storage endpoints; isolated state and no model/network/USB."""
import argparse,json,os,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--app',required=True,type=Path);a=p.parse_args()
resources=a.app.resolve()/'Contents/Resources';binary=resources/'backend/CyberboardBackend/CyberboardBackend'
with tempfile.TemporaryDirectory(prefix='tasks-package-') as name:
 root=Path(name);state=root/'state';env={**os.environ,'CYBERBOARD_DATA_DIR':str(root/'cli')};env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
 def call(action,payload):
  r=subprocess.run([str(binary),'--action',action,'--state-dir',str(state),'--resource-dir',str(resources)],input=json.dumps(payload),capture_output=True,text=True,env=env,timeout=20)
  value=json.loads(r.stdout);assert not r.returncode and 'error' not in value,value
  return value['result']
 c=call('agentTaskContext',{});assert c['mode']=='read-only' and Path(c['cwd']).is_dir()
 assert call('agentTaskList',{})['tasks']==[]
 c=call('agentTaskConfigure',{'cwd':str(root),'mode':'workspace-write'});assert c['mode']=='workspace-write'
 identity='task-'+'a'*32;folder=state/'agent-tasks';folder.mkdir();record={'id':identity,'title':'fixture','cwd':str(root),'mode':'read-only','status':'completed','archived':False,'messages':[{'role':'user','text':'fixture'}]}
 (folder/(identity+'.json')).write_text(json.dumps(record))
 assert call('agentTaskRead',{'taskId':identity})['title']=='fixture'
 assert call('agentTaskExport',{'taskId':identity})['json']['messages'][0]['text']=='fixture'
 call('agentTaskArchive',{'taskId':identity});assert call('agentTaskDelete',{'taskId':identity})['deleted']
 assert root.is_dir() and call('agentTaskList',{})['tasks']==[]
 assert not (root/'cli/current.json').exists()
print('PASS actual frozen task context, configure, list, read, archive, export and record-only deletion; no model, personal data or USB')
