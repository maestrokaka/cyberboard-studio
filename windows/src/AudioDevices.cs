using System.Runtime.InteropServices;
using System.Media;

namespace CyberboardStudio;

// Enumerates endpoints without opening capture, changing defaults, or asking
// for microphone access. Recording continues to use the explicit system default.
internal static class AudioDevices
{
    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] private class Enumerator { }
    [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IEnumerator
    {
        [PreserveSig] int EnumAudioEndpoints(int flow, uint states, out ICollection collection);
        [PreserveSig] int GetDefaultAudioEndpoint(int flow, int role, out IDevice device);
        [PreserveSig] int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IDevice device);
        [PreserveSig] int RegisterEndpointNotificationCallback(INotifications callback);
        [PreserveSig] int UnregisterEndpointNotificationCallback(INotifications callback);
    }
    [ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-C0A3C7A2A164"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface ICollection
    {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int Item(uint index, out IDevice device);
    }
    [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IDevice
    {
        [PreserveSig] int Activate(ref Guid iid, uint context, IntPtr parameters, out IntPtr instance);
        [PreserveSig] int OpenPropertyStore(uint access, out IProperties properties);
        [PreserveSig] int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
        [PreserveSig] int GetState(out uint state);
    }
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IProperties
    {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int GetAt(uint index, out PropertyKey key);
        [PreserveSig] int GetValue(ref PropertyKey key, out Variant value);
    }
    [StructLayout(LayoutKind.Sequential)] internal struct PropertyKey { internal Guid Format; internal uint Id; }
    [Guid("7991EEC9-7E89-4D85-8390-6C703CEC60C0"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface INotifications
    {
        [PreserveSig] int OnDeviceStateChanged([MarshalAs(UnmanagedType.LPWStr)] string id, uint state);
        [PreserveSig] int OnDeviceAdded([MarshalAs(UnmanagedType.LPWStr)] string id);
        [PreserveSig] int OnDeviceRemoved([MarshalAs(UnmanagedType.LPWStr)] string id);
        [PreserveSig] int OnDefaultDeviceChanged(int flow, int role, [MarshalAs(UnmanagedType.LPWStr)] string? id);
        [PreserveSig] int OnPropertyValueChanged([MarshalAs(UnmanagedType.LPWStr)] string id, PropertyKey key);
    }
    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    internal sealed class RouteGuard : INotifications, IDisposable
    {
        private readonly IEnumerator enumerator=(IEnumerator)new Enumerator();
        private readonly string expected;
        private int changed;
        private bool registered;
        internal bool Changed => Volatile.Read(ref changed)!=0;
        internal RouteGuard()
        {
            ValidateCalibrationOutput();expected=(string)Snapshot()["defaultOutputId"];
            Marshal.ThrowExceptionForHR(enumerator.RegisterEndpointNotificationCallback(this));registered=true;
            if((string)Snapshot()["defaultOutputId"]!=expected)Interlocked.Exchange(ref changed,1);
        }
        public int OnDeviceStateChanged(string id,uint state){if(id==expected&&state!=1)Interlocked.Exchange(ref changed,1);return 0;}
        public int OnDeviceAdded(string id)=>0;
        public int OnDeviceRemoved(string id){if(id==expected)Interlocked.Exchange(ref changed,1);return 0;}
        public int OnDefaultDeviceChanged(int flow,int role,string? id){if(flow==0&&role==0&&id!=expected)Interlocked.Exchange(ref changed,1);return 0;}
        public int OnPropertyValueChanged(string id,PropertyKey key)=>0;
        public void Dispose(){if(registered){enumerator.UnregisterEndpointNotificationCallback(this);registered=false;Release(enumerator);}}
    }
    [StructLayout(LayoutKind.Explicit, Size=24)] private struct Variant { [FieldOffset(0)] internal ushort Type; [FieldOffset(8)] internal IntPtr Pointer; }
    [DllImport("ole32.dll")] private static extern int PropVariantClear(ref Variant value);
    private static void Release(object? value) { if(value!=null && Marshal.IsComObject(value)) Marshal.ReleaseComObject(value); }
    private static string Id(IDevice device) { Marshal.ThrowExceptionForHR(device.GetId(out var id)); return id; }
    private static string Name(IDevice device)
    {
        Marshal.ThrowExceptionForHR(device.OpenPropertyStore(0,out var properties));
        try { var key=new PropertyKey{Format=new Guid("a45c254e-df1c-4efd-8020-67d146a850e0"),Id=14}; Marshal.ThrowExceptionForHR(properties.GetValue(ref key,out var value));
            try { return value.Type==31 ? Marshal.PtrToStringUni(value.Pointer)??"音频设备" : "音频设备"; } finally { PropVariantClear(ref value); }
        } finally { Release(properties); }
    }
    internal static Dictionary<string,object> Snapshot()
    {
        var enumerator=(IEnumerator)new Enumerator();
        try
        {
            (List<object> rows,string selected) List(int flow)
            {
                var selected=""; if(enumerator.GetDefaultAudioEndpoint(flow,0,out var current)>=0){try{selected=Id(current);}finally{Release(current);}}
                Marshal.ThrowExceptionForHR(enumerator.EnumAudioEndpoints(flow,1,out var devices));
                try { Marshal.ThrowExceptionForHR(devices.GetCount(out var count)); var rows=new List<object>();
                    for(uint i=0;i<count;i++){Marshal.ThrowExceptionForHR(devices.Item(i,out var device));try{var id=Id(device);rows.Add(new Dictionary<string,object>{{"id",id},{"name",Name(device)},{"isDefault",id==selected}});}finally{Release(device);}}
                    return(rows,selected);
                } finally {Release(devices);}
            }
            var input=List(1); var output=List(0);
            return new(){{"inputs",input.rows},{"outputs",output.rows},{"defaultInputId",input.selected},{"defaultOutputId",output.selected},{"selectionMode","system-default"}};
        } finally {Release(enumerator);}
    }
    internal static void ValidateInput(string? id)
    {
        var snapshot=Snapshot(); if(string.IsNullOrEmpty(id)||id!=(string)snapshot["defaultInputId"])throw new IOException("默认输入已改变或不可用，请在系统声音设置中选择后刷新。");
    }
    internal static void ValidateCalibrationOutput()
    {
        var snapshot=Snapshot();var outputs=(List<object>)snapshot["outputs"];
        if(!outputs.Cast<Dictionary<string,object>>().Any(x=>(bool)x["isDefault"]&&((string)x["name"]).Contains("AIROHAChat",StringComparison.OrdinalIgnoreCase)))
            throw new IOException("请先在系统声音设置将默认输出切换为 AIROHAChat，再开始校准。");
    }
    internal static MemoryStream Silence()
    {
        var stream=new MemoryStream();using(var writer=new BinaryWriter(stream,System.Text.Encoding.ASCII,true)){
            writer.Write("RIFF"u8);writer.Write(192036);writer.Write("WAVEfmt "u8);writer.Write(16);writer.Write((short)1);writer.Write((short)2);writer.Write(48000);writer.Write(192000);writer.Write((short)4);writer.Write((short)16);writer.Write("data"u8);writer.Write(192000);writer.Write(new byte[192000]);}
        stream.Position=0;return stream;
    }
}
