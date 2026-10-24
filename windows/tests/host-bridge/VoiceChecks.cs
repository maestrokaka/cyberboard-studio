using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using CyberboardStudio;

internal static class VoiceChecks
{
    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }
    private static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
    private static void Reject(Action action)
    {
        try { action(); } catch (IOException) { return; }
        throw new Exception("Expected voice rejection.");
    }
    private sealed class Capture : IVoiceCapture
    {
        internal readonly Queue<byte[]> Chunks = new();
        internal int Starts, Stops, Disposals;
        internal bool FailStart, FailRead;
        public void Start() { Starts++; if (FailStart) throw new IOException("synthetic start failure"); }
        public byte[] ReadAvailable()
        {
            if (FailRead) throw new IOException("synthetic capture failure");
            return Chunks.Count > 0 ? Chunks.Dequeue() : [];
        }
        public void Stop() { Stops++; }
        public void Dispose() { Disposals++; }
    }
    internal static void Lifecycle()
    {
        var devices = new List<Capture>();
        var time = TimeSpan.Zero;
        using var recorder = new VoiceRecorder(() => { var device = new Capture(); devices.Add(device); return device; }, () => time, schedulePolling: false);
        Check(devices.Count == 0, "Constructor created a recording device.");
        var start = Json(recorder.Start("one"));
        Check(start.GetProperty("recording").GetBoolean() && start.GetProperty("requestId").GetString() == "one", "Start response changed.");
        Reject(() => recorder.Start("two"));
        Reject(() => recorder.Stop("other"));
        Check(!Json(recorder.Cancel("other")).GetProperty("cancelled").GetBoolean() && devices[0].Disposals == 0, "Stale request released active device.");
        devices[0].Chunks.Enqueue(new byte[32000]);
        var stopped = Json(recorder.Stop("one"));
        var audio = stopped.GetProperty("audio");
        var url = audio.GetProperty("dataUrl").GetString()!;
        var bytes = Convert.FromBase64String(url["data:audio/wav;base64,".Length..]);
        Check(audio.GetProperty("durationMs").GetInt32() == 1000 && audio.GetProperty("sampleRate").GetInt32() == 16000 && bytes.Length == 32044, "WAV timing/format changed.");
        Check(Encoding.ASCII.GetString(bytes, 0, 4) == "RIFF" && BitConverter.ToInt32(bytes, 4) == bytes.Length - 8 && BitConverter.ToInt16(bytes, 22) == 1 && BitConverter.ToInt16(bytes, 34) == 16, "WAV header is not mono PCM16.");
        Check(recorder.RequestId is null && devices[0].Stops == 1 && devices[0].Disposals == 1, "Stop did not release capture.");
        Reject(() => recorder.Stop("one"));
        var states = new List<JsonElement>();
        recorder.StateChanged += value => states.Add(Json(value));
        recorder.Start("limit");
        devices[1].Chunks.Enqueue(new byte[64000]);
        time = TimeSpan.FromSeconds(60);
        recorder.Poll();
        Check(states.Count == 1 && states[0].GetProperty("reason").GetString() == "limit" && devices[1].Disposals == 1 && recorder.RequestId == "limit", "Limit did not release device and retain stop ownership.");
        Check(Json(recorder.Stop("limit")).GetProperty("audio").GetProperty("durationMs").GetInt32() == 2000, "Limit discarded captured data.");
        time = TimeSpan.Zero;
        recorder.Start("cancel");
        Check(Json(recorder.Cancel("cancel")).GetProperty("cancelled").GetBoolean() && devices[2].Disposals == 1 && recorder.RequestId is null, "Cancel retained audio/device.");
        recorder.Start("exit");
        recorder.CancelAll();
        Check(devices[3].Disposals == 1 && recorder.RequestId is null, "Exit/reload retained audio/device.");
        foreach (var payload in new[] { Json(new { }), Json(new { requestId = "bad id" }), Json(new { requestId = new string('a', 81) }), Json(new { requestId = 1 }) })
            Reject(() => VoiceRecorder.ReadRequestId(payload));
        Check(VoiceRecorder.ReadRequestId(Json(new { requestId = "voice-1_2" })) == "voice-1_2", "Valid voice request rejected.");
        Reject(() => VoiceRecorder.AudioFor([]));
        Reject(() => VoiceRecorder.AudioFor(new byte[3]));
        Reject(() => VoiceRecorder.AudioFor(new byte[VoiceRecorder.MaximumPcmBytes + 2]));
        Check(Json(VoiceRecorder.AudioFor(new byte[VoiceRecorder.MaximumPcmBytes])).GetProperty("durationMs").GetInt32() == 60000, "Exact 60 second audio rejected.");
    }
    internal static void Failures()
    {
        var failedStart = new Capture { FailStart = true };
        using (var recorder = new VoiceRecorder(() => failedStart, schedulePolling: false))
        {
            Reject(() => recorder.Start("start-failure"));
            Check(failedStart.Disposals == 1 && recorder.RequestId is null, "Start failure retained device/state.");
        }
        var failedRead = new Capture { FailRead = true };
        using (var recorder = new VoiceRecorder(() => failedRead, schedulePolling: false))
        {
            recorder.Start("read-failure");
            var events = new List<JsonElement>();
            recorder.StateChanged += value => events.Add(Json(value));
            recorder.Poll();
            Check(failedRead.Disposals == 1 && recorder.RequestId is null && events.Count == 1 && events[0].GetProperty("reason").GetString() == "error", "Read failure retained device or missed event.");
            Check(!events[0].GetRawText().Contains("synthetic"), "Device details leaked through progress.");
        }
        var excess = new Capture();
        using (var recorder = new VoiceRecorder(() => excess, schedulePolling: false))
        {
            recorder.Start("bounded");
            excess.Chunks.Enqueue(new byte[VoiceRecorder.MaximumPcmBytes + 32000]);
            recorder.Poll();
            Check(excess.Disposals == 1, "Byte upper bound did not release device.");
            Check(Json(recorder.Stop("bounded")).GetProperty("audio").GetProperty("durationMs").GetInt32() == 60000, "Upper bound crossed bridge or truncated at a partial sample.");
        }
    }

    private sealed class WaveApi : IWaveInApi
    {
        internal readonly List<IntPtr> Headers = new();
        internal readonly List<string> Calls = new();
        internal int FailAddAt = -1;
        private int additions;
        public uint Open(out IntPtr handle, ref WinMMVoiceCapture.WaveFormat format)
        {
            Check(format.FormatTag == 1 && format.Channels == 1 && format.SamplesPerSecond == 16000 && format.AverageBytesPerSecond == 32000 && format.BitsPerSample == 16, "Native wave format changed.");
            Calls.Add("open"); handle = new IntPtr(123); return 0;
        }
        public uint Prepare(IntPtr handle, IntPtr header, uint size) { Headers.Add(header); Calls.Add("prepare"); return 0; }
        public uint Add(IntPtr handle, IntPtr pointer, uint size)
        {
            Calls.Add("add");
            if (++additions == FailAddAt) return 1;
            var header = Marshal.PtrToStructure<WinMMVoiceCapture.WaveHeader>(pointer);
            header.Flags &= ~1u;
            Marshal.StructureToPtr(header, pointer, false);
            return 0;
        }
        public uint Start(IntPtr handle) { Calls.Add("start"); return 0; }
        public uint Reset(IntPtr handle)
        {
            Calls.Add("reset");
            foreach (var pointer in Headers)
            {
                var header = Marshal.PtrToStructure<WinMMVoiceCapture.WaveHeader>(pointer);
                if ((header.Flags & 1) == 0) header.BytesRecorded = 0;
                header.Flags |= 1u;
                Marshal.StructureToPtr(header, pointer, false);
            }
            return 0;
        }
        public uint Unprepare(IntPtr handle, IntPtr header, uint size) { Calls.Add("unprepare"); Headers.Remove(header); return 0; }
        public uint Close(IntPtr handle) { Calls.Add("close"); return 0; }
        internal void Complete(int index, byte value)
        {
            var pointer = Headers[index];
            var header = Marshal.PtrToStructure<WinMMVoiceCapture.WaveHeader>(pointer);
            Marshal.Copy(new byte[] { value, 0 }, 0, header.Data, 2);
            header.BytesRecorded = 2; header.Flags |= 1u;
            Marshal.StructureToPtr(header, pointer, false);
        }
    }
    internal static void NativeBuffers()
    {
        var api = new WaveApi();
        using (var device = new WinMMVoiceCapture(api))
        {
            device.Start();
            Check(api.Headers.Count == 4, "Expected four bounded capture buffers.");
            api.Complete(0, 1); api.Complete(1, 2);
            Check(device.ReadAvailable().SequenceEqual(new byte[] { 1, 0, 2, 0 }), "First audio buffers reordered.");
            api.Complete(2, 3); api.Complete(3, 4); api.Complete(0, 5); api.Complete(1, 6);
            Check(device.ReadAvailable().SequenceEqual(new byte[] { 3, 0, 4, 0, 5, 0, 6, 0 }), "Ring wrap reordered samples.");
            api.Complete(2, 7);
            device.Stop();
            Check(device.ReadAvailable().SequenceEqual(new byte[] { 7, 0 }), "Stop reset did not drain partial audio.");
            Check(device.ReadAvailable().Length == 0, "Stopped buffers replayed the same audio.");
        }
        Check(api.Headers.Count == 0 && api.Calls.Count(call => call == "unprepare") == 4 && api.Calls.Last() == "close", "Native headers or handle leaked.");
        Check(api.Calls.IndexOf("reset") < api.Calls.IndexOf("unprepare"), "Freed buffers before returning them from driver.");
        var failed = new WaveApi { FailAddAt = 2 };
        using (var device = new WinMMVoiceCapture(failed)) { Reject(device.Start); }
        Check(failed.Headers.Count == 0 && failed.Calls.Count(call => call == "unprepare") == 2 && failed.Calls.Last() == "close", "Partial start leaked prepared memory/handle.");
    }
}
