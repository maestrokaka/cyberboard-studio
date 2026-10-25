#!/usr/bin/env python3
"""Isolated task storage and official-protocol fixtures; no model, mic, USB or personal files."""
import asyncio, json, os, queue, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import agent_tasks, codex_tasks

SERVER = r'''
import json, sys
from pathlib import Path
mode = MODE
thread = 'fixture-thread'
turn = 'fixture-turn'
def send(value): print(json.dumps(value), flush=True)
def done(text='已检查测试资料。'):
    if text: send({'method':'item/completed','params':{'threadId':thread,'turnId':turn,'item':{'type':'agentMessage','text':text,'phase':'final_answer'}}})
    send({'method':'turn/completed','params':{'threadId':thread,'turn':{'id':turn,'status':'completed'}}})
for line in sys.stdin:
    m=json.loads(line); method=m.get('method'); p=m.get('params',{})
    if method=='initialize': send({'id':m['id'],'result':{'userAgent':'fixture'}})
    elif method=='account/read': send({'id':m['id'],'result':{'account':{'type':'chatgpt'}}})
    elif method in ('thread/start','thread/resume'):
        assert p['sandbox'] in ('read-only','workspace-write') and p['approvalPolicy']=='on-request'
        assert not p.get('dynamicTools'), 'Ordinary tasks must not require a Spotify catalog'
        if method=='thread/start': assert p['ephemeral'] is False
        else: assert p['threadId']==thread and p['excludeTurns'] is True
        send({'id':m['id'],'result':{'thread':{'id':thread,'ephemeral':False}}})
    elif method=='turn/start':
        send({'id':m['id'],'result':{'turn':{'id':turn,'status':'inProgress'}}})
        if mode in ('cancel','timeout','steer'): continue
        if mode in ('approval','decline','permissions','questions'):
            req={'threadId':thread,'turnId':turn,'reason':'fixture only','command':'echo fixture','cwd':str(Path.cwd())}
            name='item/commandExecution/requestApproval'
            if mode=='permissions': name='item/permissions/requestApproval';req['permissions']={'network':{'enabled':True}}
            if mode=='questions': name='item/tool/requestUserInput';req['questions']=[{'id':'q1','question':'选择名称','options':[{'label':'甲','description':'fixture'}]}]
            send({'id':'ask1','method':name,'params':req})
        elif mode=='artifact':
            Path('summary.md').write_text('fixture summary')
            send({'method':'item/completed','params':{'threadId':thread,'item':{'type':'commandExecution','command':'write summary.md','status':'completed','exitCode':0}}})
            done('已生成 summary.md。')
        elif mode=='empty': done('')
        elif mode=='wrong-thread': send({'id':'x','method':'item/commandExecution/requestApproval','params':{'threadId':'other'}})
        else: done()
    elif method=='turn/steer':
        assert p['expectedTurnId']==turn
        send({'id':m['id'],'result':{'turnId':turn}});done('已按补充指令完成。')
    elif method=='turn/interrupt':
        send({'id':m['id'],'result':{}})
        send({'method':'turn/completed','params':{'threadId':thread,'turn':{'id':turn,'status':'interrupted'}}})
    elif m.get('id')=='ask1':
        r=m['result']
        if mode=='questions': assert r=={'answers':{'q1':{'answers':['甲']}}}
        elif mode=='permissions': assert r=={'permissions':{'network':{'enabled':True}},'scope':'turn'}
        else: assert r=={'decision':'decline' if mode=='decline' else 'accept'}
        done()
'''
class Input:
    def __init__(self): self.q=queue.Queue()
    def readline(self, limit=-1): return self.q.get()
    def put(self,value): self.q.put(json.dumps(value)+'\n')
    def close(self): self.q.put('')

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='MiaoTasks-offline-');self.root=Path(self.tmp.name)
        self.store=agent_tasks.TaskStore(self.root/'state'); self.work=self.root/'work';self.work.mkdir()
        self.store.configure({'cwd':str(self.work),'mode':'workspace-write'})
    def tearDown(self): self.tmp.cleanup()
    def run_task(self, mode='success', identity=None):
        cli=self.root/'codex-fixture';cli.write_text('#!'+sys.executable+'\n'+SERVER.replace('mode = MODE','mode = '+repr(mode)));cli.chmod(0o700)
        stream=Input(); events=[]
        def emit(e):
            events.append(e)
            if e.get('type')=='request':
                stream.put({'type':'approval','id':'stale','decision':'accept'})
                stream.put({'type':'answers' if mode=='questions' else 'approval','id':e['request']['id'], 'decision':'decline' if mode=='decline' else 'accept','answers':{'q1':'甲'}})
            if e.get('state')=='thinking' and mode in ('cancel','steer'):
                # Wait until the server has a turn to avoid an intentionally premature steer.
                import threading
                threading.Timer(.12,lambda:stream.put({'type':'cancel'} if mode=='cancel' else {'type':'steer','text':'补充fixture'})).start()
        async def execute():
            task=codex_tasks.ManagedTask({'text':'测试资料任务','taskId':identity},emit,stream,state_dir=self.store.root,cli=str(cli))
            result=await task.execute();self.assertTrue(task.closed);self.assertIsNotNone(task.proc.returncode)
            return result
        try:
            with patch.object(codex_tasks,'MAX_TASK_SECONDS',.25 if mode=='timeout' else 6): return asyncio.run(execute()),events
        finally: stream.close()
    def test_non_music_formal_result_persistent_resume(self):
        first,_=self.run_task();self.assertTrue(first['ok']);tid=first['taskId'];r=self.store.get(tid)
        self.assertEqual(r['threadId'],'fixture-thread');self.assertEqual(len(r['messages']),2)
        second,_=self.run_task(identity=tid);self.assertTrue(second['ok']);self.assertEqual(len(self.store.get(tid)['messages']),4)
    def test_command_generated_file_is_reported(self):
        r,events=self.run_task('artifact');self.assertTrue(r['ok']);self.assertIn(str((self.work/'summary.md').resolve()),r['artifacts'])
        self.assertTrue(any(e.get('step',{}).get('exitCode')==0 for e in events))
    def test_explicit_approval(self): self.assertTrue(self.run_task('approval')[0]['ok'])
    def test_decline_does_not_implicitly_accept(self): self.assertTrue(self.run_task('decline')[0]['ok'])
    def test_permission_is_turn_scoped(self): self.assertTrue(self.run_task('permissions')[0]['ok'])
    def test_user_question_mapping(self): self.assertTrue(self.run_task('questions')[0]['ok'])
    def test_empty_completion_is_rejected(self): self.assertEqual(self.run_task('empty')[0]['code'],'task_result_missing')
    def test_wrong_thread_cannot_prompt(self):
        r,e=self.run_task('wrong-thread');self.assertFalse(r['ok']);self.assertFalse(any(x.get('type')=='request' for x in e))
    def test_formal_cancellation_and_reaped_process(self):
        r,_=self.run_task('cancel');self.assertEqual(r['status'],'cancelled');self.assertEqual(self.store.get(r['taskId'])['status'],'cancelled')
    def test_timeout_is_not_success(self): self.assertEqual(self.run_task('timeout')[0]['code'],'timeout')
    def test_steer_persisted_on_same_task(self):
        r,_=self.run_task('steer');self.assertTrue(r['ok']);self.assertTrue(self.store.get(r['taskId'])['messages'][1]['steer'])
    def test_archive_restore_delete_only_record(self):
        r=self.store.begin(None,'fixture');r['status']='completed';self.store.save(r)
        with self.assertRaises(agent_tasks.TaskStoreError):self.store.delete({'taskId':r['id']})
        self.store.archive({'taskId':r['id']});self.store.archive({'taskId':r['id'],'archived':False})
        self.assertFalse(self.store.get(r['id'])['archived']);self.store.archive({'taskId':r['id']});self.store.delete({'taskId':r['id']})
        self.assertTrue(self.work.exists())
    def test_restart_recovers_abandoned_but_not_live_worker(self):
        r=self.store.begin(None,'fixture');self.assertEqual(self.store.list()['tasks'][0]['status'],'running')
        r['workerPid']=999999999;self.store.save(r);self.assertEqual(self.store.list()['tasks'][0]['status'],'interrupted')
    def test_corrupt_record_kept(self):
        p=self.store.path('task-'+'a'*32);p.parent.mkdir(exist_ok=True);p.write_text('{broken')
        self.assertEqual(self.store.list()['tasks'][0]['status'],'error');self.assertEqual(p.read_text(),'{broken')
    def test_reveal_rejects_outside_and_symlink(self):
        (self.work/'link').symlink_to(self.root)
        for target in [str(self.root),str(self.work/'link')]:
            with self.assertRaises(agent_tasks.TaskStoreError):self.store.reveal({'path':target})
    def test_invalid_identity_and_attachment(self):
        with self.assertRaises(agent_tasks.TaskStoreError):self.store.get('../../credentials')
        with self.assertRaises(codex_tasks.MiaoCallError):codex_tasks.validated({'text':'x','attachments':['relative']})
    def test_archiving_frees_active_capacity(self):
        for i in range(50):self.store.create(str(i))
        with self.assertRaises(agent_tasks.TaskStoreError):self.store.create('overflow')
        r=self.store.list()['tasks'][0];self.store.archive({'taskId':r['id']});self.store.create('new task')
    def test_export_has_only_task_state(self):
        r=self.store.create('fixture');e=self.store.export({'taskId':r['id']});self.assertEqual(e['json']['messages'],[])
        self.assertNotIn('key',e['json'])

if __name__=='__main__':unittest.main()
