#!/usr/bin/env python3
"""Official setup protocol and Windows discovery fixtures; no account/network access."""
import asyncio,json,os,queue,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import codex_runtime,codex_connection
from agent_tasks import TaskStore
SERVER=r'''
import json,sys
mode=MODE;signed=mode=='signed'
for line in sys.stdin:
 m=json.loads(line);p=m.get('params') or {};method=m.get('method');result={}
 if method=='initialize':result={'userAgent':'fixture'}
 elif method=='account/read':result={'account':{'type':'chatgpt','email':'private-fixture@example.test'} if signed else None,'requiresOpenaiAuth':True}
 elif method=='account/login/start':
  assert p['type']=='chatgpt' and p['appBrand']=='codex'
  result={'loginId':'fixture-login','authUrl':'https://evil.example.test/steal' if mode=='badurl' else 'https://auth.openai.com/fixture-login'}
 elif method=='account/login/cancel':result={}
 elif method:assert method=='initialized','Setup must not execute task tools: '+method
 if 'id' in m:print(json.dumps({'id':m['id'],'result':result}),flush=True)
 if method=='account/login/start' and mode!='wait':
  signed=True;print(json.dumps({'method':'account/login/completed','params':{'loginId':'fixture-login','success':True,'error':None}}),flush=True)
'''
class Input:
 def __init__(self):self.q=queue.Queue()
 def readline(self,limit=-1):return self.q.get()
 def put(self,x):self.q.put(json.dumps(x)+'\n')
 def close(self):self.q.put('')
class Checks(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory(prefix='Codex-setup-');self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def run_connection(self,mode,login=False,cancel=False):
  exe=self.root/'codex';exe.write_text('#!'+sys.executable+'\n'+SERVER.replace('mode=MODE','mode='+repr(mode)));exe.chmod(0o700);stream=Input();events=[]
  def emit(e):
   events.append(e)
   if cancel and e.get('type')=='codexLogin':stream.put({'type':'cancel'})
  async def go():
   conn=codex_connection.Connection({'mode':'login' if login else 'check'},emit,stream,state_dir=self.root,cli=str(exe))
   r=await conn.execute();self.assertTrue(conn.closed);self.assertIsNotNone(conn.proc.returncode);return r
  try:return asyncio.run(go()),events
  finally:stream.close()
 def test_official_signed_in_check_does_not_expose_identity(self):
  r,e=self.run_connection('signed');self.assertTrue(r['authenticated']);self.assertNotIn('@',json.dumps([r,e]));self.assertNotIn('account',r)
 def test_unauthed_does_not_silently_start_login(self):
  r,e=self.run_connection('unsigned');self.assertTrue(r['installed']);self.assertFalse(r['authenticated']);self.assertEqual(e,[])
 def test_browser_login_waits_for_formal_completion(self):
  r,e=self.run_connection('login',login=True);self.assertTrue(r['authenticated']);self.assertEqual(len(e),1)
 def test_rejects_untrusted_auth_destination(self):
  r,e=self.run_connection('badurl',login=True);self.assertFalse(r['authenticated']);self.assertEqual(e,[])
 def test_cancel_login_reaps_server(self):
  r,e=self.run_connection('wait',login=True,cancel=True);self.assertEqual(r['code'],'connection_cancelled')
 def test_native_standalone_found_without_fresh_path(self):
  cli=self.root/'Programs/OpenAI/Codex/bin/codex.exe';cli.parent.mkdir(parents=True);cli.touch();cli.chmod(0o700)
  self.assertEqual(codex_runtime.locate(windows=True,environ={'LOCALAPPDATA':str(self.root)},which=lambda _:None),str(cli.resolve()))
 def test_npm_cmd_is_never_launched_as_shell(self):
  shim=self.root/'npm/codex.cmd';cli=self.root/'npm/node_modules/@openai/codex/vendor/x86_64-pc-windows-msvc/codex/codex.exe';cli.parent.mkdir(parents=True);cli.touch();cli.chmod(0o700)
  self.assertEqual(codex_runtime.locate(windows=True,environ={},which=lambda _:str(shim)),str(cli.resolve()))
 def test_manual_runtime_selection_and_preservation(self):
  cli=self.root/'codex.exe';cli.touch();cli.chmod(0o700);store=TaskStore(self.root/'state');store.configure({'cliPath':str(cli)});store.configure({'mode':'workspace-write'})
  self.assertEqual(store.context()['cliPath'],str(cli.resolve()))
 def test_no_powershell_or_cmd_as_codex_runtime(self):
  cli=self.root/'codex.cmd';cli.touch();cli.chmod(0o700)
  with self.assertRaises(FileNotFoundError):codex_runtime.locate(str(cli),windows=True)
 def test_removed_work_folder_does_not_block_setup_or_repair(self):
  work=self.root/'work';work.mkdir();store=TaskStore(self.root/'state');store.configure({'cwd':str(work)});work.rmdir()
  cli=self.root/'codex.exe';cli.touch();cli.chmod(0o700);store.configure({'cliPath':str(cli)})
  self.assertEqual(store.configured_cli(),str(cli.resolve()))
  replacement=self.root/'replacement';replacement.mkdir();store.configure({'cwd':str(replacement)})
  self.assertEqual(store.context()['cwd'],str(replacement.resolve()))
 def test_manual_runtime_selection_rejects_non_path_values(self):
  for value in [[],{},False,'relative.exe']:
   with self.assertRaises(ValueError):TaskStore(self.root/'state').configure({'cliPath':value})
 def test_auth_link_validation(self):
  for u in ['http://auth.openai.com/a','https://auth.openai.com.evil.test/a','https://user@auth.openai.com/a','file:///tmp/a','https://chatgpt.com:444/a']:
   self.assertFalse(codex_connection.auth_url(u),u)
if __name__=='__main__':unittest.main()
