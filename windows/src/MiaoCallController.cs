using System.Diagnostics;
using System.Text.Json;
namespace CyberboardStudio;

internal sealed class MiaoCallController : IDisposable
{
    private readonly Form owner;
    private readonly Action<Action> ui;
    private readonly Action<object> emit;
    private readonly Func<bool> canBegin;
    private readonly Action showTask;
    private readonly BackendClient metadata=new();
    private readonly VoiceRecorder recorder=new();
    private readonly CompanionDesktop pet;
    private MiaoCallHotkey? hook;
    private BackendSession? session,wardrobe;
    private Task? runningTask;
    private readonly HashSet<BackendSession> activeSessions=new();
    private int generation;
    private bool earlyRelease,disposed;
    private string state="idle",message="",transcript="",voiceId="",taskId="";
    private JsonElement options=JsonSerializer.SerializeToElement(new{confirmBeforeSend=true}),profile,request,result;
    private readonly HashSet<string> selectedFiles=new(StringComparer.OrdinalIgnoreCase);
    internal bool IsBusy=>MiaoCallContracts.Busy.Contains(state)||activeSessions.Count>0||wardrobe!=null;
    internal MiaoCallController(Form owner,Action<Action> ui,Action<object> emit,Func<bool> canBegin,Action showTask)
    {
        this.owner=owner;this.ui=ui;this.emit=emit;this.canBegin=canBegin;this.showTask=showTask;
        pet=new CompanionDesktop(()=>!IsBusy&&canBegin());pet.OpenTask+=showTask;pet.CancelTask+=()=>Cancel();pet.DismissTask+=()=>{++generation;Publish("idle","");};pet.SubmitTask+=text=>{try{Submit(text);}catch(IOException e){Publish("awaitingConfirmation",e.Message);}};
        pet.PreferencesChanged+=()=>Publish(state,message);
        recorder.StateChanged+=value=>ui(()=>{var data=JsonSerializer.SerializeToElement(value);if(disposed||state!="listening"||MiaoCallContracts.Text(data,"requestId")!=voiceId)return;if(MiaoCallContracts.Text(data,"reason")=="limit")_=StopRecordingAsync();else if(MiaoCallContracts.Text(data,"reason")=="error")Finish("error","录音未能完成，请检查麦克风。");});
    }
    internal void ApplyTheme(string theme)=>pet.ApplyTheme(theme);
    internal object Status()=>new{enabled=hook!=null,state,message,transcript,physicalKeyCode=0x29,confirmBeforeSend=!options.TryGetProperty("confirmBeforeSend",out var confirm)||confirm.ValueKind!=JsonValueKind.False,agent="codex",supportedAgents=new[]{"codex"},taskId,request=request.ValueKind==JsonValueKind.Object?(object)request:new{},taskResult=result.ValueKind==JsonValueKind.Object?(object)result:new{},companion=pet.Preferences,voiceProvider=MiaoCallContracts.Text(profile,"provider"),platform="windows"};
    private void Publish(string phase,string text)
    {
        if(disposed)return;state=phase;message=text;var data=JsonSerializer.SerializeToElement(Status()).EnumerateObject().ToDictionary(x=>x.Name,x=>(object?)x.Value.Clone());data["event"]="miaoCall";data["type"]="state";emit(data);pet.State(phase,text,transcript);
    }
    private void Finish(string phase,string text)
    {
        Publish(phase,text);var token=generation;
        _=Task.Delay(12000).ContinueWith(_=>ui(()=>{if(token==generation&&!disposed)Publish("idle","");}));
    }
    private async Task<JsonElement> Query(string action,object payload)=>await Task.Run(()=>metadata.RunAsync(action,JsonSerializer.SerializeToElement(payload),_=>{},suppressDiagnostics:true));
    private async Task<JsonElement> RunSessionAsync(BackendSession worker,string action,object payload,Action<JsonElement> onEvent,bool interactive=true)
    {
        activeSessions.Add(worker);
        try{return await worker.RunAsync(action,payload,onEvent,interactive);}
        finally{activeSessions.Remove(worker);}
    }
    private void Available(){if(IsBusy||!canBegin())throw new IOException("请先完成或停止当前录音、任务或设备操作。");}
    internal async Task<object> HandleAsync(string action,JsonElement payload)
    {
        await Task.Yield(); // Native dialogs must run after the WebView callback returns.
        switch(action)
        {
            case "miaoCallStatus":
                var status=JsonSerializer.SerializeToElement(Status()).EnumerateObject().ToDictionary(x=>x.Name,x=>(object?)x.Value.Clone());status["customOutfits"]=pet.CustomOutfits();return status;
            case "miaoCallCodexInstall":
                Available();
                if(MessageBox.Show(owner,"将打开 PowerShell，从 OpenAI 官方地址下载并运行 Codex 独立安装器，只为当前 Windows 用户安装。\n不需要 Node.js 或 WSL；这条命令不更改系统的长期执行策略。\n\n来源："+MiaoCallContracts.InstallerUrl,"安装 Codex",MessageBoxButtons.OKCancel,MessageBoxIcon.Information)!=DialogResult.OK)return new{cancelled=true};
                var start=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell/v1.0/powershell.exe")){UseShellExecute=false};
                foreach(var arg in new[]{"-NoProfile","-NoExit","-ExecutionPolicy","Bypass","-Command","irm https://chatgpt.com/codex/install.ps1 | iex"})start.ArgumentList.Add(arg);
                Process.Start(start);return new{launched=true,message="请在安装窗口完成安装，再点击「检测连接」。"};
            case "miaoCallCodexCopyInstall":Clipboard.SetText(MiaoCallContracts.InstallerCommand);return new{copied=true};
            case "miaoCallCodexChoose":
                Available();using(var dialog=new OpenFileDialog{Title="选择官方原生 codex.exe（保留旁边的运行时文件）",Filter="Codex 原生程序|codex*.exe",CheckFileExists=true})
                {
                    if(dialog.ShowDialog(owner)!=DialogResult.OK)return new{cancelled=true};
                    return await Query("agentTaskConfigure",new{cliPath=dialog.FileName});
                }
            case "miaoCallCodexCheck":case "miaoCallCodexLogin":
                Available();var token=++generation;var connection=new BackendSession();session=connection;Publish("configuring",action.EndsWith("Login")?"正在打开 Codex 官方登录，请在浏览器完成。":"正在检测本机 Codex 安装与登录。");
                try
                {
                    var connected=await RunSessionAsync(connection,"codexConnectionWorker",new{mode=action.EndsWith("Login")?"login":"check"},e=>ui(()=>
                    {
                        if(token!=generation)return;
                        if(MiaoCallContracts.Text(e,"type")=="codexLogin")
                        {
                            var url=MiaoCallContracts.Text(e,"authUrl");if(!MiaoCallContracts.AuthUrl(url)){connection.Cancel();return;}
                            try{Process.Start(new ProcessStartInfo(url){UseShellExecute=true});}
                            catch(Exception e)when(e is System.ComponentModel.Win32Exception or InvalidOperationException){++generation;connection.Cancel();Finish("error","无法打开默认浏览器，请设置浏览器后重新登录。");}
                        }
                    }));
                    if(token==generation)Publish("idle",MiaoCallContracts.Text(connected,"message"));return connected;
                }
                catch(Exception e)when(e is IOException or InvalidOperationException or System.ComponentModel.Win32Exception)
                {if(token==generation)Finish("error",e is System.ComponentModel.Win32Exception?"Codex 连接未能启动，请检测安装后重试。":e.Message);throw;}
                finally{if(ReferenceEquals(session,connection))session=null;connection.Dispose();}
            case "miaoCallTaskList":
                var list=JsonSerializer.SerializeToElement(payload).EnumerateObject().ToDictionary(x=>x.Name,x=>(object?)x.Value.Clone());if(IsBusy&&taskId.Length>0)list["activeTaskId"]=taskId;return await Query("agentTaskList",list);
            case "miaoCallTaskRead":return await Query("agentTaskRead",payload);
            case "miaoCallTaskArchive":Available();return await Query("agentTaskArchive",payload);
            case "miaoCallTaskDelete":
                Available();if(MessageBox.Show(owner,"仅删除本机归档任务记录，不删除任务产物或 Codex 原会话。可先导出，删除后无法恢复。","删除归档记录",MessageBoxButtons.OKCancel,MessageBoxIcon.Warning)!=DialogResult.OK)return new{cancelled=true};
                return await Query("agentTaskDelete",payload);
            case "miaoCallTaskContext":return await Query("agentTaskContext",payload);
            case "miaoCallTaskConfigure":
                Available();return await Query("agentTaskConfigure",new{mode=MiaoCallContracts.Text(payload,"mode","read-only")});
            case "miaoCallTaskChooseFolder":
                Available();using(var dialog=new FolderBrowserDialog{Description="选择新任务的工作目录，默认仅查看。",UseDescriptionForTitle=true})
                {if(dialog.ShowDialog(owner)!=DialogResult.OK)return new{cancelled=true};return await Query("agentTaskConfigure",new{cwd=dialog.SelectedPath});}
            case "miaoCallTaskChooseFiles":
                Available();using(var dialog=new OpenFileDialog{Title="添加最多 8 个任务资料文件",Multiselect=true,CheckFileExists=true,RestoreDirectory=true})
                {if(dialog.ShowDialog(owner)!=DialogResult.OK)return new{cancelled=true};if(dialog.FileNames.Length>8)throw new IOException("最多添加 8 个文件。");foreach(var path in dialog.FileNames)selectedFiles.Add(path);return new{paths=dialog.FileNames};}
            case "miaoCallTaskReveal":
                var revealed=await Query("agentTaskReveal",payload);var target=MiaoCallContracts.Text(revealed,"path");
                var explorer=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows),"explorer.exe")){UseShellExecute=false};
                if(File.Exists(target))explorer.ArgumentList.Add("/select,");explorer.ArgumentList.Add(target);Process.Start(explorer);return new{revealed=true};
            case "miaoCallTaskExport":
                var exported=await Query("agentTaskExport",payload);using(var dialog=new SaveFileDialog{Title="导出本机任务记录",Filter="JSON|*.json",FileName=MiaoCallContracts.Text(exported,"fileName","task.json")})
                {if(dialog.ShowDialog(owner)!=DialogResult.OK)return new{cancelled=true};CompanionDesktop.Atomic(dialog.FileName,MiaoCallContracts.Value(exported,"json"));return new{exported=true};}
            case "miaoCallTaskDiagnostics":
                var diag=await Query("agentTaskDiagnostics",new{});Clipboard.SetText(diag.GetRawText());return new{copied=true};
            case "miaoCallTaskSelect":Available();taskId=MiaoCallContracts.Text(payload,"taskId");result=default;options=JsonSerializer.SerializeToElement(new{confirmBeforeSend=true});return Status();
            case "miaoCallRunTask":
                Available();taskId=MiaoCallContracts.Text(payload,"taskId");
                var attachments=MiaoCallContracts.Value(payload,"attachments");var files=attachments.ValueKind==JsonValueKind.Array?attachments.EnumerateArray().Select(x=>x.GetString()??"").Where(selectedFiles.Contains).Take(8).ToArray():[];
                options=JsonSerializer.SerializeToElement(new{confirmBeforeSend=true,attachments=files});state="awaitingConfirmation";Submit(MiaoCallContracts.Text(payload,"text"));return Status();
            case "miaoCallTaskRespond":
                var id=MiaoCallContracts.Text(payload,"id");if(id.Length==0||id!=MiaoCallContracts.Text(request,"id")||session==null)throw new IOException("这条请求已结束。");
                await session.SendAsync(new{type=MiaoCallContracts.Text(request,"kind")=="questions"?"answers":"approval",id,decision=MiaoCallContracts.Text(payload,"decision","decline"),answers=MiaoCallContracts.Value(payload,"answers")});request=default;Publish("thinking","已将你的答复交给 Codex。");return Status();
            case "miaoCallTaskSteer":
                if(state is not("connecting" or "thinking" or "acting")||session==null)throw new IOException("请在当前轮结果后继续追问。");
                await session.SendAsync(new{type="steer",text=MiaoCallContracts.Transcript(MiaoCallContracts.Text(payload,"text"))});return new{queued=true};
            case "miaoCallEnable":
                Available();options=payload;var enableToken=++generation;Publish("configuring","正在准备语音连接。");
                try{await LoadProfileAsync();if(enableToken!=generation||disposed)return Status();hook??=new MiaoCallHotkey(()=>IsBusy,key=>ui(()=>{if(key=="start")_=StartRecordingAsync();else if(key=="stop")_=StopRecordingAsync();else Cancel();}));Publish("idle","按键唤起已开启，按住 · 说话，松开识别。");return Status();}
                catch{if(enableToken==generation&&!disposed)Publish("idle","");throw;}
            case "miaoCallDisable":hook?.Dispose();hook=null;Cancel();return Status();
            case "miaoCallStartRecording":Available();options=payload;await StartRecordingAsync();return Status();
            case "miaoCallStopRecording":await StopRecordingAsync();return Status();
            case "miaoCallSubmit":Submit(MiaoCallContracts.Text(payload,"text"));return Status();
            case "miaoCallCancel":Cancel();return Status();
            case "miaoCallCompanionSave":Available();pet.Save(payload);return Status();
            case "miaoCallCompanionTest":
                Available();var p=pet.Preferences.EnumerateObject().ToDictionary(x=>x.Name,x=>(object?)x.Value.Clone());foreach(var key in new[]{"voice","volume"})if(payload.TryGetProperty(key,out var val))p[key]=val.Clone();
                pet.React(MiaoCallContracts.Text(payload,"zone","cheek"),MiaoCallContracts.Flag(payload,"sound"),pet.Validate(JsonSerializer.SerializeToElement(p)));return Status();
            case "miaoCallOutfitCancel":wardrobe?.Cancel();return new{cancelled=true};
            case "miaoCallImageSettings":case "miaoCallImageSave":case "miaoCallImageReveal":case "miaoCallOutfitGenerate":case "miaoCallOutfitDelete":
                Available();if(wardrobe!=null)throw new IOException("衣装生成正在进行，请先完成或取消。");
                var actions=new Dictionary<string,string>{{"miaoCallImageSettings","companionImageSettings"},{"miaoCallImageSave","companionImageSave"},{"miaoCallImageReveal","companionImageReveal"},{"miaoCallOutfitGenerate","companionOutfitGenerate"},{"miaoCallOutfitDelete","companionOutfitDelete"}};
                var image=new BackendSession();wardrobe=image;
                try
                {
                    var value=await RunSessionAsync(image,actions[action],payload,_=>{},interactive:false);
                    if(action=="miaoCallOutfitDelete"&&MiaoCallContracts.Text(payload,"id")==MiaoCallContracts.Text(pet.Preferences,"outfit"))
                    {var prefs=pet.Preferences.EnumerateObject().ToDictionary(x=>x.Name,x=>(object?)x.Value.Clone());prefs["outfit"]="sailor-short";pet.Save(JsonSerializer.SerializeToElement(prefs));}
                    return value;
                }
                finally{if(ReferenceEquals(wardrobe,image))wardrobe=null;image.Dispose();}
            default:throw new IOException("此 Windows 版本尚未提供此操作。");
        }
    }
    private async Task LoadProfileAsync()
    {var p=await Query("voiceSettings",new{});if(!MiaoCallContracts.Flag(p,"hasKey"))throw new IOException("请先在模型配置保存语音识别服务与 Key。");profile=p;}
    private async Task StartRecordingAsync()
    {
        if(IsBusy||!canBegin())return;int token=++generation;earlyRelease=false;Publish("preparing","正在准备麦克风，开始聆听后再说话。");
        try{await LoadProfileAsync();if(token!=generation)return;if(earlyRelease){Finish("cancelled","请按住 · 说完后再松开；此次没有录音。");return;}voiceId="miaocall-"+Guid.NewGuid().ToString("N");recorder.Start(voiceId);Publish("listening","正在听你说，松开后转成文字。");}
        catch(Exception e)when(e is IOException or InvalidOperationException){if(token==generation)Finish("error",e.Message);}
    }
    private async Task StopRecordingAsync()
    {
        if(state=="preparing"){earlyRelease=true;return;}if(state!="listening")return;int token=generation;
        try
        {
            var stopped=JsonSerializer.SerializeToElement(recorder.Stop(voiceId));var transcribe=new BackendSession();session=transcribe;
            Publish("transcribing","正在识别语音，音频只用于这次转写。");
            try
            {
                var value=await RunSessionAsync(transcribe,"transcribeVoice",new{requestId=voiceId,audio=MiaoCallContracts.Value(stopped,"audio"),expectedProvider=MiaoCallContracts.Text(profile,"provider"),expectedModel=MiaoCallContracts.Text(profile,"model"),expectedRegion=MiaoCallContracts.Text(profile,"region")},_=>{},interactive:false);
                if(token!=generation)return;transcript=MiaoCallContracts.Text(value,"text");if(transcript.Length==0)throw new IOException("没有识别到有效文字，请重新尝试。");Publish("awaitingConfirmation","确认文字后交给 Codex；可以先修改识别文字。");if(options.TryGetProperty("confirmBeforeSend",out var c)&&c.ValueKind==JsonValueKind.False)Submit(transcript);
            }
            finally{if(ReferenceEquals(session,transcribe))session=null;transcribe.Dispose();}
        }
        catch(Exception e)when(e is IOException or InvalidOperationException){if(token==generation)Finish("error",e.Message);}
    }
    private void Submit(string text)
    {
        if(state!="awaitingConfirmation")throw new IOException("当前没有等待确认的任务。");text=MiaoCallContracts.Transcript(text);transcript=text;int token=++generation;request=result=default;
        var worker=new BackendSession();session=worker;Publish("connecting","已交给 Codex，任务与结果保存在本机。");
        runningTask=RunTaskAsync(worker,token,text);
    }
    private async Task RunTaskAsync(BackendSession worker,int token,string text)
    {
        try
        {
            var value=await RunSessionAsync(worker,"miaoCallWorker",new{transcript=text,taskId=taskId.Length==0?null:taskId,attachments=options.TryGetProperty("attachments",out var files)&&files.ValueKind==JsonValueKind.Array?files:JsonSerializer.SerializeToElement(Array.Empty<string>()),tracks=Array.Empty<object>()},e=>ui(()=>
            {
                if(token!=generation||state=="cancelling")return;var identity=MiaoCallContracts.Text(e,"taskId");if(identity.Length>0)taskId=identity;
                var type=MiaoCallContracts.Text(e,"type");
                if(type=="request"){request=MiaoCallContracts.Value(e,"request");Publish(MiaoCallContracts.Text(request,"kind")=="questions"?"awaitingInput":"awaitingApproval","请在任务详情核对并答复；没有自动授权。");emit(e);}
                else if(type=="requestResolved"){request=default;emit(e);}
                else if(type=="state")
                {var phase=MiaoCallContracts.Text(e,"state");if(phase=="completed")Publish("acting","Codex 已结束，正在保存任务记录。");else if(phase is "connecting" or "thinking" or "acting"){Publish(phase,MiaoCallContracts.Text(e,"message"));emit(e);}}
                else emit(e);
            }));
            if(token!=generation)return;result=value;request=default;var id=MiaoCallContracts.Text(value,"taskId");if(id.Length>0)taskId=id;
            bool valid=MiaoCallContracts.Flag(value,"ok")&&MiaoCallContracts.Text(value,"status")=="completed"&&MiaoCallContracts.TaskId(taskId)&&(MiaoCallContracts.Text(value,"text").Length>0||(value.TryGetProperty("artifacts",out var a)&&a.ValueKind==JsonValueKind.Array&&a.GetArrayLength()>0));
            Finish(valid?"completed":MiaoCallContracts.Text(value,"status")=="cancelled"?"cancelled":"error",MiaoCallContracts.Text(value,"message",valid?MiaoCallContracts.Text(value,"text","Codex 已返回文件，请检查结果。"):"任务未返回完整结果，请检查后继续。"));
        }
        catch(Exception e)when(e is IOException or InvalidOperationException){if(token==generation)Finish(state=="cancelling"?"cancelled":"error",state=="cancelling"?"任务已停止，已发生的修改不会自动撤销。":e.Message);}
        finally{if(ReferenceEquals(session,worker))session=null;worker.Dispose();}
    }
    internal void Cancel()
    {
        if((state is "connecting" or "thinking" or "acting" or "awaitingApproval" or "awaitingInput" or "cancelling")&&session!=null){if(state!="cancelling"){Publish("cancelling","正在停止 Codex；已经发生的修改不会自动撤销。");session!.Cancel();}return;}
        ++generation;session?.Cancel();session=null;recorder.CancelAll();request=default;Finish("cancelled","本次操作已取消。");
    }
    internal void DisableShortcutAndCancel(){hook?.Dispose();hook=null;Cancel();}
    internal async Task StopForExitAsync()
    {
        DisableShortcutAndCancel();wardrobe?.Cancel();
        var active=activeSessions.ToArray();foreach(var worker in active)worker.Cancel();
        var pending=Task.WhenAll(active.Select(worker=>worker.Completion).Concat(runningTask==null?Array.Empty<Task>():new[]{runningTask}));
        if(await Task.WhenAny(pending,Task.Delay(10000))!=pending)throw new IOException("任务连接尚未停止，请等待几秒后再关闭。");
    }
    public void Dispose()
    {if(disposed)return;disposed=true;++generation;hook?.Dispose();hook=null;session?.Cancel();wardrobe?.Cancel();foreach(var worker in activeSessions)worker.Cancel();recorder.Dispose();metadata.Dispose();pet.Dispose();}
}
