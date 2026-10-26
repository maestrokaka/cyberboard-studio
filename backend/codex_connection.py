"""Official app-server detection and browser login. No private auth-file access."""
from __future__ import annotations
import asyncio,json,os
from pathlib import Path
from urllib.parse import urlsplit
from agent_tasks import TaskStore
from miao_call import CodexTask, MiaoCallError, find_cli, ERROR_MESSAGES
ERROR_MESSAGES.update({'connection_timeout':'登录或连接等待超时，请重新检测后再试。','connection_cancelled':'已取消 Codex 连接操作。'})

def auth_url(value):
    if not isinstance(value,str) or len(value)>8192:return False
    try:
        u=urlsplit(value)
        return u.scheme=='https' and u.hostname in ('auth.openai.com','chatgpt.com') and u.port in (None,443) and not u.username and not u.password
    except ValueError:return False

class Connection(CodexTask):
    def __init__(self,payload,emit,input_stream,*,state_dir,cli=None):
        super().__init__({},emit,input_stream,cli=cli,_validator=lambda p:{'tracks':[]})
        self.store=TaskStore(state_dir);self.mode=payload.get('mode','check');self.login_id=None;self.logged_in=asyncio.Event();self.login_success=False
        if self.mode not in ('check','login'):raise MiaoCallError('invalid_request')
    async def _read_stdout(self):
        try:
            while line:=await self.proc.stdout.readline():
                m=json.loads(line);identity=m.get('id');method=m.get('method')
                if identity is not None and not method:
                    f=self.pending.get(identity)
                    if f and not f.done():
                        if 'error' in m:f.set_exception(MiaoCallError('codex_unsupported'))
                        else:f.set_result(m.get('result') or {})
                elif identity is not None:
                    await self.send({'id':identity,'error':{'code':-32601,'message':'No task tools are available during sign-in'}})
                elif method=='account/login/completed':
                    p=m.get('params') or {}
                    if self.login_id is None or p.get('loginId')==self.login_id:
                        self.login_success=p.get('success') is True;self.logged_in.set()
        except (ValueError,OSError,TypeError):pass
        finally:
            for f in self.pending.values():
                if not f.done():f.set_exception(MiaoCallError('codex_protocol_error'))
            self.logged_in.set()
    async def connect(self):
        cli=self.cli or find_cli(self.store.configured_cli())
        self.proc=await asyncio.create_subprocess_exec(cli,'app-server','--listen','stdio://',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,limit=2**20,start_new_session=os.name!='nt',**({'creationflags':0x08000000} if os.name=='nt' else {}))
        self.readers=[asyncio.create_task(self._read_stdout()),asyncio.create_task(self._read_stderr())]
        await self.request('initialize',{'clientInfo':{'name':'cyberboard_miaocall_setup','version':'1.0.0'},'capabilities':{'experimentalApi':True}})
        await self.send({'method':'initialized','params':{}})
        account=await self.request('account/read',{'refreshToken':False})
        signed=isinstance(account.get('account'),dict) or account.get('requiresOpenaiAuth') is False
        if self.mode=='login' and not signed:
            login=await self.request('account/login/start',{'type':'chatgpt','useHostedLoginSuccessPage':True,'appBrand':'codex'})
            self.login_id=login.get('loginId');url=login.get('authUrl')
            if not self.login_id or not auth_url(url):raise MiaoCallError('codex_protocol_error')
            self.emit({'event':'miaoCall','type':'codexLogin','authUrl':url})
            await self.logged_in.wait()
            account=await self.request('account/read',{'refreshToken':False})
            signed=self.login_success and isinstance(account.get('account'),dict)
        return {'installed':True,'protocolReady':True,'authenticated':signed,'message':'Codex 已连接，可交代任务。' if signed else '已找到 Codex，请点击登录。'}
    async def execute(self):
        host=asyncio.create_task(self._host_messages());op=asyncio.create_task(self.connect());cancel=asyncio.create_task(self.cancelled.wait())
        try:
            done,_=await asyncio.wait((op,cancel),timeout=600 if self.mode=='login' else 40,return_when=asyncio.FIRST_COMPLETED)
            if cancel in done:raise MiaoCallError('connection_cancelled')
            if op not in done:raise MiaoCallError('connection_timeout')
            return await op
        except (MiaoCallError,OSError) as e:
            if self.login_id:
                try:await self.request('account/login/cancel',{'loginId':self.login_id},timeout=3)
                except (MiaoCallError,OSError):pass
            code=e.code if isinstance(e,MiaoCallError) else 'codex_start_failed'
            return {'installed':code!='codex_not_installed','authenticated':False,'protocolReady':False,'code':code,'message':ERROR_MESSAGES[code]}
        finally:
            for t in (host,op,cancel):t.cancel()
            await asyncio.gather(host,op,cancel,return_exceptions=True);await self.close()

def run(payload,emit,input_stream,*,state_dir,cli=None):
    try:return asyncio.run(Connection(payload,emit,input_stream,state_dir=state_dir,cli=cli).execute())
    except (MiaoCallError,OSError,ValueError):return {'installed':False,'authenticated':False,'protocolReady':False,'message':'未找到 Codex，请先安装或手动选择 codex.exe。'}
