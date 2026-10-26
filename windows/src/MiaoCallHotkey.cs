using System.Diagnostics;
using System.Runtime.InteropServices;
namespace CyberboardStudio;
internal sealed class MiaoCallHotkey : IDisposable
{
    private readonly MiaoCallKeyGate gate=new();
    private readonly Func<bool> busy;
    private readonly Action<string> action;
    private readonly Hook callback;
    private IntPtr handle;
    internal MiaoCallHotkey(Func<bool> busy,Action<string> action)
    {
        this.busy=busy;this.action=action;callback=OnKey;
        using var current=Process.GetCurrentProcess();
        handle=SetWindowsHookEx(13,callback,GetModuleHandle(current.MainModule?.ModuleName),0);
        if(handle==IntPtr.Zero)throw new IOException("无法监听按键。请使用普通用户打开本软件；若被企业策略阻止，可使用页内按住说话。");
    }
    private IntPtr OnKey(int code,IntPtr wParam,IntPtr lParam)
    {
        if(code>=0)
        {
            var key=Marshal.PtrToStructure<KeyInfo>(lParam);bool down=wParam.ToInt64() is 0x100 or 0x104;
            bool up=wParam.ToInt64() is 0x101 or 0x105;
            if((key.Flags & 0x10)==0 && (down||up))
            {
                if(key.Key==27 && down && busy()){action("cancel");return new IntPtr(1);}
                bool modifiers=new[]{0x10,0x11,0x12,0x5b,0x5c}.Any(k=>(GetAsyncKeyState(k)&0x8000)!=0);
                var result=gate.Consume((int)key.Scan,down,modifiers,busy());
                if(result!=null){if(result!="consume")action(result);return new IntPtr(1);}
            }
        }
        return CallNextHookEx(handle,code,wParam,lParam);
    }
    public void Dispose(){if(handle!=IntPtr.Zero){UnhookWindowsHookEx(handle);handle=IntPtr.Zero;}gate.Reset();}
    private delegate IntPtr Hook(int code,IntPtr wParam,IntPtr lParam);
    [StructLayout(LayoutKind.Sequential)] private struct KeyInfo{public uint Key,Scan,Flags,Time;public UIntPtr Extra;}
    [DllImport("user32.dll",SetLastError=true)]private static extern IntPtr SetWindowsHookEx(int id,Hook callback,IntPtr module,uint thread);
    [DllImport("user32.dll")]private static extern bool UnhookWindowsHookEx(IntPtr hook);
    [DllImport("user32.dll")]private static extern IntPtr CallNextHookEx(IntPtr hook,int code,IntPtr wParam,IntPtr lParam);
    [DllImport("user32.dll")]private static extern short GetAsyncKeyState(int key);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)]private static extern IntPtr GetModuleHandle(string? module);
}
