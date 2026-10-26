using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
namespace CyberboardStudio;

// JSONL session with a bounded output, private stderr, explicit cancellation,
// and a Windows job that owns only this worker and its descendants.
internal sealed class BackendSession : IDisposable
{
    private readonly SemaphoreSlim inputGate=new(1,1);
    private Process? process;
    private int cancelled, started;
    private bool interactiveMode;
    private readonly TaskCompletionSource completion=new(TaskCreationOptions.RunContinuationsAsynchronously);
    internal Task Completion=>completion.Task;
    public async Task SendAsync(object payload)
    {
        await inputGate.WaitAsync();
        try { var child=process;if(child is {HasExited:false}) {await child.StandardInput.WriteLineAsync(JsonSerializer.Serialize(payload));await child.StandardInput.FlushAsync();} }
        catch(IOException) { }
        catch(InvalidOperationException) { }
        finally {inputGate.Release();}
    }
    public void Cancel()
    {
        if(Interlocked.Exchange(ref cancelled,1)!=0||Completion.IsCompleted)return;
        _=CancelAsync();
    }
    private async Task CancelAsync()
    {
        var child=process;
        if(interactiveMode)
        {
            _=SendAsync(new {type="cancel"}); // The grace deadline must also cover a blocked stdin write.
            if(await Task.WhenAny(Completion,Task.Delay(6500))==Completion)return;
        }
        try{if(child is {HasExited:false})child.Kill(entireProcessTree:true);}catch(InvalidOperationException){}catch(System.ComponentModel.Win32Exception){}
    }
    public async Task<JsonElement> RunAsync(string action,object payload,Action<JsonElement> onEvent,bool interactive=true)
    {
        if(Interlocked.Exchange(ref started,1)!=0)throw new InvalidOperationException("任务连接不能重复使用。");
        try{return await RunCoreAsync(action,payload,onEvent,interactive);}
        catch(System.ComponentModel.Win32Exception){throw new IOException("任务后台未能启动或停止，请重新打开软件后再试。");}
        catch(UnauthorizedAccessException){throw new IOException("无法访问本机任务目录或程序，请检查文件权限后再试。");}
        finally{completion.TrySetResult();}
    }
    private async Task<JsonElement> RunCoreAsync(string action,object payload,Action<JsonElement> onEvent,bool interactive)
    {
        interactiveMode=interactive;
        if(Volatile.Read(ref cancelled)!=0)return CancelledResult();
        if(!File.Exists(HostPaths.Python)||!File.Exists(HostPaths.Backend))throw new IOException("后台组件缺失，请完整解压软件包。");
        Directory.CreateDirectory(HostPaths.State);
        var start=new ProcessStartInfo(HostPaths.Python){WorkingDirectory=HostPaths.Resources,UseShellExecute=false,CreateNoWindow=true,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardInputEncoding=new UTF8Encoding(false),StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8};
        foreach(var a in new[]{"-X","utf8","-u",HostPaths.Backend,"--action",action,"--state-dir",HostPaths.State,"--resource-dir",HostPaths.Resources})start.ArgumentList.Add(a);
        start.Environment.Remove("PYTHONHOME");start.Environment.Remove("PYTHONPATH");start.Environment["PYTHONIOENCODING"]="utf-8";
        using var child=new Process{StartInfo=start};process=child;
        using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(action=="miaoCallWorker"?1830:action=="codexConnectionWorker"?650:145));
        using var kill=timeout.Token.Register(()=>{try{if(!child.HasExited)child.Kill(entireProcessTree:true);}catch(InvalidOperationException){}catch(System.ComponentModel.Win32Exception){}});
        OwnedProcessJob? job=null;
        try
        {
            if(!child.Start())throw new IOException("后台未能启动。");
            if(OperatingSystem.IsWindows()){job=new OwnedProcessJob();job.Assign(child);}
            var stderr=DrainAsync(child.StandardError,timeout.Token);
            await inputGate.WaitAsync();
            try
            {
                await child.StandardInput.WriteAsync(JsonSerializer.Serialize(payload)+(interactive?"\n":""));await child.StandardInput.FlushAsync();
                if(!interactive)child.StandardInput.Close();
            }
            finally{inputGate.Release();}
            if(Volatile.Read(ref cancelled)!=0){if(interactive)await SendAsync(new {type="cancel"});else child.Kill(entireProcessTree:true);}
            JsonElement? final=null;
            var buffer=new char[4096];var line=new StringBuilder();long total=0;int count;
            while((count=await child.StandardOutput.ReadAsync(buffer,timeout.Token))>0)
            {
                total+=count;if(total>16*1024*1024)throw new IOException("任务返回超过读取上限，已停止。");
                for(int i=0;i<count;i++)
                {
                    if(buffer[i]=='\n')
                    {
                        if(line.Length>0)
                        {
                            using var d=JsonDocument.Parse(line.ToString(),new JsonDocumentOptions{MaxDepth=128});var r=d.RootElement;
                            if(r.ValueKind!=JsonValueKind.Object||final.HasValue)throw new IOException("任务返回格式无效。");
                            if(r.TryGetProperty("event",out _))onEvent(r.Clone());
                            else if(r.TryGetProperty("result",out _)||r.TryGetProperty("error",out _))final=r.Clone();
                            else throw new IOException("任务返回格式无效。");
                        }
                        line.Clear();
                    }
                    else {line.Append(buffer[i]);if(line.Length>12*1024*1024)throw new IOException("单条任务消息过大，已停止。");}
                }
            }
            await child.WaitForExitAsync(timeout.Token);await stderr;
            if(line.ToString().Trim().Length!=0)throw new IOException("任务没有完整结束。");
            if(final is { } reply)
            {
                if(reply.TryGetProperty("error",out var error))throw new BackendReplyException(error);
                if(child.ExitCode==0 && reply.TryGetProperty("result",out var result))return result.Clone();
            }
            if(Volatile.Read(ref cancelled)!=0)return CancelledResult();
            throw new IOException("任务连接已结束，未收到完整结果。");
        }
        catch(OperationCanceledException){throw new IOException("任务连接等待超时，已停止。");}
        catch(JsonException){throw new IOException("任务返回格式无效，已停止。");}
        finally
        {
            try{if(!child.HasExited)child.Kill(entireProcessTree:true);}catch(InvalidOperationException){}catch(System.ComponentModel.Win32Exception){}
            job?.Dispose();process=null;
        }
    }
    private static JsonElement CancelledResult()=>JsonSerializer.SerializeToElement(new {ok=false,status="cancelled",message="任务已停止，已发生的操作不会自动撤销。"});
    private static async Task DrainAsync(StreamReader reader,CancellationToken token)
    {var buffer=new char[4096];while(await reader.ReadAsync(buffer,token)>0){} }
    public void Dispose()=>Cancel();
}
internal sealed class OwnedProcessJob : IDisposable
{
    private readonly SafeFileHandle handle;
    internal OwnedProcessJob()
    {
        handle=CreateJobObject(IntPtr.Zero,null);if(handle.IsInvalid)throw new IOException("无法建立任务进程边界。");
        var info=new ExtendedLimit{BasicLimit=new BasicLimit{LimitFlags=0x2000}}; // KILL_ON_JOB_CLOSE
        if(!SetInformationJobObject(handle,9,ref info,(uint)Marshal.SizeOf<ExtendedLimit>())){handle.Dispose();throw new IOException("无法配置任务进程边界。");}
    }
    internal void Assign(Process process)
    {if(!AssignProcessToJobObject(handle,process.Handle))throw new IOException("无法管理任务进程，请重新打开软件或联系设备管理员。");}
    public void Dispose()=>handle.Dispose();
    [StructLayout(LayoutKind.Sequential)] private struct BasicLimit {public long PerProcessUserTime,PerJobUserTime;public uint LimitFlags;public UIntPtr MinWorkingSet,MaxWorkingSet;public uint ActiveProcessLimit;public UIntPtr Affinity;public uint PriorityClass,SchedulingClass;}
    [StructLayout(LayoutKind.Sequential)] private struct IoCounters {public ulong ReadOperations,WriteOperations,OtherOperations,ReadBytes,WriteBytes,OtherBytes;}
    [StructLayout(LayoutKind.Sequential)] private struct ExtendedLimit {public BasicLimit BasicLimit;public IoCounters IoInfo;public UIntPtr ProcessMemoryLimit,JobMemoryLimit,PeakProcessMemory,PeakJobMemory;}
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] private static extern SafeFileHandle CreateJobObject(IntPtr attributes,string? name);
    [DllImport("kernel32.dll",SetLastError=true)] private static extern bool SetInformationJobObject(SafeFileHandle job,int infoClass,ref ExtendedLimit info,uint length);
    [DllImport("kernel32.dll",SetLastError=true)] private static extern bool AssignProcessToJobObject(SafeFileHandle job,IntPtr process);
}
