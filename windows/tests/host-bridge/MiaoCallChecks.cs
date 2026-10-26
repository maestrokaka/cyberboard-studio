using System.Diagnostics;
using System.Text.Json;
using CyberboardStudio;

internal static class MiaoCallChecks
{
    private static void Check(bool ok, string text) { if (!ok) throw new Exception(text); }
    private static void CleanFixtureChild(int pid)
    {
        // The fixture reports only the PID of its own synthetic 60-second sleeper.
        try { using var child = Process.GetProcessById(pid); if (!child.HasExited) child.Kill(entireProcessTree: true); }
        catch (ArgumentException) { }
        catch (InvalidOperationException) { }
    }
    internal static async Task RunAsync()
    {
        Check(MiaoCallContracts.AuthUrl("https://auth.openai.com/fixture"), "Official login URL rejected");
        foreach (var url in new[] { "http://auth.openai.com", "https://user@chatgpt.com/", "https://auth.openai.com.evil.test/", "file:///tmp/a", "https://auth.openai.com:444/" })
            Check(!MiaoCallContracts.AuthUrl(url), "Untrusted login URL accepted");
        var gate = new MiaoCallKeyGate();
        Check(gate.Consume(0x29, true, true, false) == null, "Modifier chord intercepted");
        Check(gate.Consume(0x29, true, false, false) == "start", "Physical hold did not start");
        Check(gate.Consume(0x29, true, false, true) == "consume", "Repeat launched task");
        Check(gate.Consume(0x29, false, false, true) == "stop", "Hold release lost");
        gate.Reset(); Check(!gate.Held, "Hook release failed");
        try { MiaoCallContracts.Transcript(new string('中', 2001)); throw new Exception("Overlong task allowed"); }
        catch (IOException) { }
        using (var session = new BackendSession())
        {
            var waiting = new TaskCompletionSource();
            var pending = session.RunAsync("miaoCallWorker", new { mode = "approval" }, e => { if (MiaoCallContracts.Text(e, "type") == "request") waiting.TrySetResult(); });
            await waiting.Task.WaitAsync(TimeSpan.FromSeconds(10));
            await session.SendAsync(new { type = "approval", id = "request-1", decision = "accept" });
            var result = await pending.WaitAsync(TimeSpan.FromSeconds(10));
            Check(MiaoCallContracts.Flag(result, "ok"), "Interactive approval/result failed");
            try { await session.RunAsync("miaoCallWorker", new { mode = "approval" }, _ => { }); throw new Exception("Completed session was reusable"); }
            catch (InvalidOperationException) { }
        }
        using (var session = new BackendSession())
        {
            var waiting = new TaskCompletionSource();
            var pending = session.RunAsync("miaoCallWorker", new { mode = "cancel" }, _ => waiting.TrySetResult());
            await waiting.Task.WaitAsync(TimeSpan.FromSeconds(10)); session.Cancel();
            var result = await pending.WaitAsync(TimeSpan.FromSeconds(10));
            Check(MiaoCallContracts.Text(result, "status") == "cancelled", "Cancellation returned success");
        }
        using (var session = new BackendSession())
        {
            session.Cancel(); bool emitted = false;
            var result = await session.RunAsync("miaoCallWorker", new { mode = "approval" }, _ => emitted = true).WaitAsync(TimeSpan.FromSeconds(3));
            Check(!emitted && MiaoCallContracts.Text(result, "status") == "cancelled", "Cancelled session launched its worker");
        }
        using (var session = new BackendSession())
        {
            var waiting = new TaskCompletionSource();
            var pending = session.RunAsync("cancel", new { }, _ => waiting.TrySetResult(), interactive: false);
            await waiting.Task.WaitAsync(TimeSpan.FromSeconds(10)); session.Cancel();
            var result = await pending.WaitAsync(TimeSpan.FromSeconds(10));
            Check(MiaoCallContracts.Text(result, "status") == "cancelled", "Noninteractive cancellation stalled or returned success");
        }
        using (var session = new BackendSession())
        {
            int workerPid = 0;
            try
            {
                await session.RunAsync("miaoCallWorker", new { mode = "malformed-live" }, e =>
                { workerPid = e.GetProperty("workerPid").GetInt32(); }).WaitAsync(TimeSpan.FromSeconds(10));
                throw new Exception("Malformed live worker was accepted.");
            }
            catch (IOException) { }
            Program.CheckWorkerExited(workerPid);
        }
        foreach (var mode in new[] { "malformed", "nonzero", "partial", "duplicate", "after-final", "unknown" })
        {
            using var session = new BackendSession();
            try { await session.RunAsync("miaoCallWorker", new { mode }, _ => { }).WaitAsync(TimeSpan.FromSeconds(10)); throw new Exception("Invalid final response accepted: " + mode); }
            catch (IOException) { }
        }
        Console.WriteLine("PASS MiaoCall official URL/physical key contracts, interactive approve/cancel, pre-start cancellation, single use, noninteractive cancellation and incomplete-result rejection");
        if (OperatingSystem.IsWindows())
        {
            using var session = new BackendSession();
            var result = await session.RunAsync("miaoCallWorker", new { mode = "child" }, _ => { }).WaitAsync(TimeSpan.FromSeconds(10));
            int pid = result.GetProperty("childPid").GetInt32();
            try { Program.CheckWorkerExited(pid); }
            finally { CleanFixtureChild(pid); }
            Console.WriteLine("PASS Windows native Job Object terminates owned descendant after session completion");
        }
        else Console.WriteLine("SKIP Windows native Job Object: this host is not Windows; Windows CI is required");
    }
}
