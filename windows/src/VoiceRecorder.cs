using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Timer = System.Threading.Timer;

namespace CyberboardStudio;

internal interface IVoiceCapture : IDisposable
{
    void Start();
    byte[] ReadAvailable();
    void Stop();
}

// The capture is created only by Start, following an explicit UI action. The
// timer and bridge calls share one lock, so stop/cancel cannot free a device
// while another thread is collecting its data.
internal sealed class VoiceRecorder : IDisposable
{
    internal const int SampleRate = 16000;
    internal const int MaximumSeconds = 60;
    internal const int MaximumBytes = 6 * 1024 * 1024;
    internal const int MaximumPcmBytes = SampleRate * 2 * MaximumSeconds;
    private readonly object gate = new();
    private readonly Func<IVoiceCapture> createCapture;
    private readonly Func<TimeSpan> elapsed;
    private readonly bool schedulePolling;
    private readonly Stopwatch watch = new();
    private IVoiceCapture? capture;
    private MemoryStream? pcm;
    private Timer? timer;
    private bool disposed;
    internal string? RequestId { get; private set; }
    internal event Action<object>? StateChanged;

    internal VoiceRecorder(Func<IVoiceCapture>? createCapture = null, Func<TimeSpan>? elapsed = null, bool schedulePolling = true)
    {
        this.createCapture = createCapture ?? (() => new WinMMVoiceCapture());
        this.elapsed = elapsed ?? (() => watch.Elapsed);
        this.schedulePolling = schedulePolling;
    }
    internal static string ReadRequestId(JsonElement payload)
    {
        if (!payload.TryGetProperty("requestId", out var value) || value.ValueKind != JsonValueKind.String ||
            !Regex.IsMatch(value.GetString() ?? "", "\\A[A-Za-z0-9_-]{1,80}\\z", RegexOptions.CultureInvariant))
            throw new IOException("语音请求编号无效。");
        return value.GetString()!;
    }
    internal object Start(string requestId)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (RequestId is not null) throw new IOException("已有录音正在进行，请先停止或取消。");
            // A driver error can leave a handle owned by this controller.
            // Retry its safe teardown before allowing a second capture.
            if (capture is not null) Clear();
            RequestId = requestId;
            pcm = new MemoryStream();
            try
            {
                capture = createCapture();
                capture.Start();
                watch.Restart();
                if (schedulePolling) timer = new Timer(_ => Poll(), null, 50, 50);
                return new { recording = true, requestId };
            }
            catch
            {
                try { Clear(); } catch { }
                throw new IOException("无法开始录音，请检查麦克风是否可用，并在 Windows 隐私设置中允许桌面应用使用麦克风。");
            }
        }
    }
    private void Add(byte[] bytes)
    {
        if (bytes.Length % 2 != 0) throw new IOException("录音数据无效，请重新录制。");
        var count = Math.Min(bytes.Length, MaximumPcmBytes - (int)pcm!.Length);
        if (count > 0) pcm.Write(bytes, 0, count);
    }
    private void FinishCapture()
    {
        timer?.Dispose(); timer = null;
        if (capture is null) return;
        var device = capture;
        try
        {
            device.Stop();
            Add(device.ReadAvailable());
        }
        finally { device.Dispose(); capture = null; watch.Stop(); }
    }
    internal void Poll()
    {
        object? state = null;
        lock (gate)
        {
            if (disposed || capture is null || RequestId is null) return;
            var requestId = RequestId;
            try
            {
                Add(capture.ReadAvailable());
                if (elapsed().TotalSeconds >= MaximumSeconds || pcm!.Length >= MaximumPcmBytes)
                {
                    FinishCapture();
                    state = new { @event = "voiceRecording", requestId, recording = false, reason = "limit" };
                }
            }
            catch
            {
                try { Clear(); } catch { }
                state = new { @event = "voiceRecording", requestId, recording = false, reason = "error", message = "录音未成功保存，请重新录制。" };
            }
        }
        if (state is not null) StateChanged?.Invoke(state);
    }
    internal object Stop(string requestId)
    {
        lock (gate)
        {
            if (RequestId != requestId) throw new IOException("此录音已结束或请求编号不匹配，请重新开始。");
            try
            {
                FinishCapture();
                var bytes = pcm!.ToArray();
                if (bytes.Length == 0) throw new IOException("录音为空，请重新录制。");
                return new { requestId, audio = AudioFor(bytes) };
            }
            catch (IOException) { throw; }
            catch { throw new IOException("录音未成功保存，请重新录制。"); }
            finally { Clear(); }
        }
    }
    internal static object AudioFor(byte[] pcm)
    {
        if (pcm.Length is < 2 or > MaximumPcmBytes || pcm.Length % 2 != 0)
            throw new IOException("录音为空或超过 60 秒，请重新录制。");
        using var stream = new MemoryStream(44 + pcm.Length);
        using (var writer = new BinaryWriter(stream, Encoding.ASCII, leaveOpen: true))
        {
            writer.Write(Encoding.ASCII.GetBytes("RIFF")); writer.Write(36 + pcm.Length);
            writer.Write(Encoding.ASCII.GetBytes("WAVEfmt ")); writer.Write(16);
            writer.Write((ushort)1); writer.Write((ushort)1); writer.Write(SampleRate);
            writer.Write(SampleRate * 2); writer.Write((ushort)2); writer.Write((ushort)16);
            writer.Write(Encoding.ASCII.GetBytes("data")); writer.Write(pcm.Length); writer.Write(pcm);
        }
        return new { dataUrl = "data:audio/wav;base64," + Convert.ToBase64String(stream.ToArray()),
            durationMs = pcm.Length * 1000 / (SampleRate * 2), sampleRate = SampleRate };
    }
    internal object Cancel(string requestId)
    {
        lock (gate)
        {
            var cancelled = RequestId == requestId;
            if (cancelled) Clear();
            return new { cancelled, requestId };
        }
    }
    internal void CancelAll() { lock (gate) { try { Clear(); } catch { } } }
    private void Clear()
    {
        timer?.Dispose(); timer = null;
        try { capture?.Dispose(); capture = null; }
        finally { pcm?.Dispose(); pcm = null; RequestId = null; watch.Stop(); }
    }
    public void Dispose() { lock (gate) { disposed = true; try { Clear(); } catch { } } }
}

// CALLBACK_NULL uses bounded polling. Native code never holds a managed
// callback pointer, and buffers are retained until reset has returned them.
internal sealed class WinMMVoiceCapture : IVoiceCapture
{
    [StructLayout(LayoutKind.Sequential)]
    internal struct WaveFormat
    {
        public ushort FormatTag, Channels;
        public uint SamplesPerSecond, AverageBytesPerSecond;
        public ushort BlockAlign, BitsPerSample, ExtraSize;
    }
    [StructLayout(LayoutKind.Sequential)]
    internal struct WaveHeader
    {
        public IntPtr Data;
        public uint BufferLength, BytesRecorded;
        public UIntPtr User;
        public uint Flags, Loops;
        public IntPtr Next;
        public UIntPtr Reserved;
    }
    private sealed class Buffer
    {
        internal IntPtr Data, Header;
        internal bool Prepared;
    }
    private readonly List<Buffer> buffers = new();
    private readonly IWaveInApi api;
    private IntPtr handle;
    private int next;
    private bool stopped;
    private const int BufferBytes = VoiceRecorder.SampleRate / 2; // 250 ms mono PCM16.
    private static readonly uint HeaderSize = (uint)Marshal.SizeOf<WaveHeader>();
    internal WinMMVoiceCapture(IWaveInApi? api = null) { this.api = api ?? new WaveInApi(); }
    private static void Check(uint result) { if (result != 0) throw new IOException("麦克风录音设备不可用。"); }
    public void Start()
    {
        if (handle != IntPtr.Zero) throw new IOException("录音设备已启动。");
        var format = new WaveFormat { FormatTag = 1, Channels = 1, SamplesPerSecond = VoiceRecorder.SampleRate,
            AverageBytesPerSecond = VoiceRecorder.SampleRate * 2, BlockAlign = 2, BitsPerSample = 16 };
        try
        {
            Check(api.Open(out handle, ref format));
            for (var index = 0; index < 4; index++)
            {
                var buffer = new Buffer();
                buffers.Add(buffer);
                buffer.Data = Marshal.AllocHGlobal(BufferBytes);
                buffer.Header = Marshal.AllocHGlobal((int)HeaderSize);
                Marshal.StructureToPtr(new WaveHeader { Data = buffer.Data, BufferLength = BufferBytes }, buffer.Header, false);
                Check(api.Prepare(handle, buffer.Header, HeaderSize));
                buffer.Prepared = true;
                Check(api.Add(handle, buffer.Header, HeaderSize));
            }
            Check(api.Start(handle));
        }
        catch { Dispose(); throw; }
    }
    public byte[] ReadAvailable()
    {
        using var collected = new MemoryStream();
        if (handle == IntPtr.Zero || buffers.Count == 0) return [];
        // Consume/requeue in submission order; a delayed poll must not reorder
        // audio when the buffer ring wraps around.
        for (var count = 0; count < buffers.Count; count++)
        {
            var buffer = buffers[next];
            var header = Marshal.PtrToStructure<WaveHeader>(buffer.Header);
            if ((header.Flags & 1) == 0) break; // WHDR_DONE.
            if (header.BytesRecorded > BufferBytes || header.BytesRecorded % 2 != 0)
                throw new IOException("录音数据无效。");
            var bytes = new byte[header.BytesRecorded];
            Marshal.Copy(buffer.Data, bytes, 0, bytes.Length);
            collected.Write(bytes);
            if (!stopped)
            {
                header.BytesRecorded = 0;
                Marshal.StructureToPtr(header, buffer.Header, false);
                Check(api.Add(handle, buffer.Header, HeaderSize));
            }
            else { header.Flags &= ~1u; Marshal.StructureToPtr(header, buffer.Header, false); }
            next = (next + 1) % buffers.Count;
        }
        return collected.ToArray();
    }
    public void Stop()
    {
        if (handle == IntPtr.Zero || stopped) return;
        Check(api.Reset(handle));
        stopped = true;
    }
    public void Dispose()
    {
        if (handle == IntPtr.Zero) return;
        // Reset returns all queued buffers. Never release any memory until the
        // driver has successfully unprepared it; failures remain retryable.
        Check(api.Reset(handle));
        stopped = true;
        foreach (var buffer in buffers)
        {
            if (buffer.Prepared)
            {
                Check(api.Unprepare(handle, buffer.Header, HeaderSize));
                buffer.Prepared = false;
            }
            if (buffer.Header != IntPtr.Zero) { Marshal.FreeHGlobal(buffer.Header); buffer.Header = IntPtr.Zero; }
            if (buffer.Data != IntPtr.Zero) { Marshal.FreeHGlobal(buffer.Data); buffer.Data = IntPtr.Zero; }
        }
        buffers.Clear();
        Check(api.Close(handle));
        handle = IntPtr.Zero;
    }
}

internal interface IWaveInApi
{
    uint Open(out IntPtr handle, ref WinMMVoiceCapture.WaveFormat format);
    uint Prepare(IntPtr handle, IntPtr header, uint size);
    uint Add(IntPtr handle, IntPtr header, uint size);
    uint Start(IntPtr handle);
    uint Reset(IntPtr handle);
    uint Unprepare(IntPtr handle, IntPtr header, uint size);
    uint Close(IntPtr handle);
}

internal sealed class WaveInApi : IWaveInApi
{
    public uint Open(out IntPtr handle, ref WinMMVoiceCapture.WaveFormat format) => waveInOpen(out handle, uint.MaxValue, ref format, UIntPtr.Zero, UIntPtr.Zero, 0);
    public uint Prepare(IntPtr handle, IntPtr header, uint size) => waveInPrepareHeader(handle, header, size);
    public uint Add(IntPtr handle, IntPtr header, uint size) => waveInAddBuffer(handle, header, size);
    public uint Start(IntPtr handle) => waveInStart(handle);
    public uint Reset(IntPtr handle) => waveInReset(handle);
    public uint Unprepare(IntPtr handle, IntPtr header, uint size) => waveInUnprepareHeader(handle, header, size);
    public uint Close(IntPtr handle) => waveInClose(handle);
    [DllImport("winmm.dll")] private static extern uint waveInOpen(out IntPtr handle, uint device, ref WinMMVoiceCapture.WaveFormat format, UIntPtr callback, UIntPtr instance, uint flags);
    [DllImport("winmm.dll")] private static extern uint waveInPrepareHeader(IntPtr handle, IntPtr header, uint size);
    [DllImport("winmm.dll")] private static extern uint waveInAddBuffer(IntPtr handle, IntPtr header, uint size);
    [DllImport("winmm.dll")] private static extern uint waveInStart(IntPtr handle);
    [DllImport("winmm.dll")] private static extern uint waveInReset(IntPtr handle);
    [DllImport("winmm.dll")] private static extern uint waveInUnprepareHeader(IntPtr handle, IntPtr header, uint size);
    [DllImport("winmm.dll")] private static extern uint waveInClose(IntPtr handle);
}
