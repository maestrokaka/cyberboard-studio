using System.Diagnostics;
using System.Text.Json;
using CyberboardStudio;

internal static class Program
{
    private static int passed;
    private static string temp = "";

    private static JsonElement Payload(object value) => JsonSerializer.SerializeToElement(value);
    private static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }
    private static async Task Run(string name, Func<Task> test)
    {
        await test();
        passed++;
        Console.WriteLine("PASS " + name);
    }
    private static async Task<IOException> Fails(Func<Task> test, string expected)
    {
        try { await test(); }
        catch (IOException error)
        {
            Check(error.Message.Contains(expected, StringComparison.Ordinal), "Wrong error: " + error.Message);
            return error;
        }
        throw new Exception("Expected IOException containing " + expected);
    }

    private static async Task Main(string[] args)
    {
        if (args.Length != 1 || !File.Exists(args[0])) throw new Exception("Pass a real Python interpreter path.");
        temp = Path.Combine(Path.GetTempPath(), "Cyberboard 模拟 空格 " + Guid.NewGuid().ToString("N"));
        HostPaths.Resources = Path.Combine(temp, "资源 files");
        HostPaths.State = Path.Combine(temp, "用户 状态");
        HostPaths.Python = Path.GetFullPath(args[0]);
        Directory.CreateDirectory(Path.GetDirectoryName(HostPaths.Backend)!);
        Directory.CreateDirectory(HostPaths.Web);
        File.Copy(Path.Combine(AppContext.BaseDirectory, "fake-bridge.py"), HostPaths.Backend);
        try
        {
            await Run("multiple progress records, cloned JSON, Chinese stdout/stderr and paths", async () =>
            {
                using var client = new BackendClient();
                var events = new List<JsonElement>();
                var result = await client.RunAsync("echo", Payload(new { 文本 = "你好猫爪", count = 2 }), events.Add);
                Check(events.Count == 2, "Both event protocol forms must be delivered.");
                Check(events[0].GetProperty("label").GetString() == "顶部屏幕", "Event clone must outlive parser document.");
                Check(result.GetProperty("payload").GetProperty("文本").GetString() == "你好猫爪", "Unicode payload changed.");
                Check(result.GetProperty("state").GetString() == HostPaths.State, "Space/Unicode state argv changed.");
                Check(result.GetProperty("resource").GetString() == HostPaths.Resources, "Space/Unicode resource argv changed.");
                Check(HostLog.Messages.Last().Message.Contains("中文 stderr"), "Unicode stderr was not logged.");
            });
            await Run("payload and action shell characters remain literal, no command execution", async () =>
            {
                using var client = new BackendClient();
                var sentinel = Path.Combine(temp, "shell-must-not-run.txt");
                var text = "$(touch '" + sentinel + "') `touch '" + sentinel + "'` ; & | > < %PATH% \"\\ \n猫爪";
                var action = "literal ; $(touch '" + sentinel + "')";
                var result = await client.RunAsync(action, Payload(new { text }), _ => { });
                Check(result.GetProperty("payload").GetProperty("text").GetString() == text, "Shell-character payload modified.");
                Check(result.GetProperty("action").GetString() == action, "Action arguments were split/interpreted.");
                Check(!File.Exists(sentinel), "Payload/action executed through a shell.");
            });
            await Run("large Unicode stdin is written without pipe deadlock", async () =>
            {
                using var client = new BackendClient();
                var text = new string('灯', 250000);
                var result = await client.RunAsync("echo", Payload(new { text }), _ => { }).WaitAsync(TimeSpan.FromSeconds(15));
                Check(result.GetProperty("payload").GetProperty("text").GetString() == text, "Large payload truncated.");
            });
            await Run("error JSON is rejected and preserves Chinese message", async () =>
            {
                using var client = new BackendClient();
                await Fails(async () => await client.RunAsync("error", Payload(new { }), _ => { }), "模拟失败");
            });
            await Run("malformed JSON cannot be hidden by a later successful result", async () =>
            {
                using var client = new BackendClient();
                await Fails(async () => await client.RunAsync("malformed", Payload(new { }), _ => { }), "不是有效的 JSON");
            });
            await Run("non-object protocol record is rejected", async () =>
            {
                using var client = new BackendClient();
                await Fails(async () => await client.RunAsync("wrong-record", Payload(new { }), _ => { }), "无法识别的数据");
            });
            await Run("nonzero exit cannot return success, empty stdout reports no result", async () =>
            {
                using var client = new BackendClient();
                await Fails(async () => await client.RunAsync("exit", Payload(new { }), _ => { }), "（7）");
                await Fails(async () => await client.RunAsync("empty", Payload(new { }), _ => { }), "没有返回操作结果");
            });
            await Run("queued operations run serially and retain individual payloads", async () =>
            {
                using var client = new BackendClient();
                var first = client.RunAsync("queue", Payload(new { id = 1 }), _ => { });
                var second = client.RunAsync("queue", Payload(new { id = 2 }), _ => { });
                var results = await Task.WhenAll(first, second);
                Check(results[0].GetProperty("payload").GetProperty("id").GetInt32() == 1, "First request payload crossed.");
                Check(results[1].GetProperty("payload").GetProperty("id").GetInt32() == 2, "Second request payload crossed.");
                Check(results[1].GetProperty("start").GetInt64() >= results[0].GetProperty("end").GetInt64(), "Subprocess operations overlapped.");
            });
            await Run("failed operation releases the queue for the next request", async () =>
            {
                using var client = new BackendClient();
                var failed = Fails(async () => await client.RunAsync("exit", Payload(new { }), _ => { }), "（7）");
                var next = client.RunAsync("echo", Payload(new { after = true }), _ => { });
                await failed;
                Check((await next).GetProperty("payload").GetProperty("after").GetBoolean(), "Queue did not recover.");
            });
            await Run("large stderr is drained and capped to its final 65536 characters", async () =>
            {
                using var client = new BackendClient();
                await client.RunAsync("diagnostic-tail", Payload(new { }), _ => { }).WaitAsync(TimeSpan.FromSeconds(15));
                var tail = HostLog.Messages.Last().Message;
                Check(tail.Length == 65536, "Diagnostic tail size was not bounded.");
                Check(tail.Contains("保留结尾") && !tail.StartsWith("前缀"), "Diagnostic tail lost its ending.");
            });
            await Run("dispose cancels active child and queued request promptly", async () =>
            {
                var client = new BackendClient();
                var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                var active = client.RunAsync("cancel", Payload(new { }), _ => started.TrySetResult());
                await started.Task.WaitAsync(TimeSpan.FromSeconds(5));
                var queued = client.RunAsync("echo", Payload(new { }), _ => throw new Exception("Queued request executed after disposal."));
                var stopwatch = Stopwatch.StartNew();
                client.Dispose();
                foreach (var task in new[] { active, queued })
                {
                    try { await task.WaitAsync(TimeSpan.FromSeconds(5)); throw new Exception("Expected cancellation."); }
                    catch (OperationCanceledException) { }
                }
                Check(stopwatch.Elapsed < TimeSpan.FromSeconds(5), "Child cancellation was not prompt.");
            });
            await Run("resource origin, document and external-link policy", () =>
            {
                foreach (var url in new[] { ResourcePolicy.Index, "https://studio.cyberboard.invalid:443/index.html?x=1#ok" })
                    Check(ResourcePolicy.IsDocument(url), "Expected document rejected: " + url);
                foreach (var url in new[] { "http://studio.cyberboard.invalid/index.html", "https://studio.cyberboard.invalid:444/index.html", "https://user@studio.cyberboard.invalid/index.html", "https://studio.cyberboard.invalid.evil/index.html", "https://studio.cyberboard.invalid./index.html", "file:///index.html", "data:text/html,ok" })
                    Check(!ResourcePolicy.IsOrigin(url), "Unexpected origin accepted: " + url);
                Check(!ResourcePolicy.IsDocument("https://studio.cyberboard.invalid/other.html"), "Unexpected document accepted.");
                Check(ResourcePolicy.IsExternalLink("https://example.org/help") && ResourcePolicy.IsExternalLink("http://example.org/help"), "External web links rejected.");
                Check(!ResourcePolicy.IsExternalLink(ResourcePolicy.Index) && !ResourcePolicy.IsExternalLink("https://user@example.org/help") && !ResourcePolicy.IsExternalLink("file:///tmp/a") && !ResourcePolicy.IsExternalLink("javascript:alert(1)"), "Unsafe external link accepted.");
                return Task.CompletedTask;
            });
            await Run("asset allowlist, traversal, encoded separators, ADS and Unicode URL paths", () =>
            {
                Directory.CreateDirectory(Path.Combine(HostPaths.Web, "assets"));
                File.WriteAllText(Path.Combine(HostPaths.Web, "index.html"), "index");
                File.WriteAllText(Path.Combine(HostPaths.Web, "assets", "猫爪 logo.png"), "image");
                File.WriteAllText(Path.Combine(HostPaths.Web, "other.html"), "other");
                File.WriteAllText(Path.Combine(HostPaths.Web, "secret.exe"), "executable");
                File.WriteAllText(Path.Combine(HostPaths.Resources, "outside.png"), "outside");
                Check(ResourcePolicy.IsAsset(ResourcePolicy.Index), "Index asset rejected.");
                Check(ResourcePolicy.IsAsset("https://studio.cyberboard.invalid/assets/%E7%8C%AB%E7%88%AA%20logo.png?version=1"), "Unicode/space asset URL rejected.");
                foreach (var path in new[] { "/missing.png", "/other.html", "/secret.exe", "/assets/%2e%2e/%2e%2e/outside.png", "/assets%2f..%2f..%2foutside.png", "/assets%5c..%5coutside.png", "/index.html%3aevil.png", "/%00.png", "/C%3a/secret.png" })
                    Check(!ResourcePolicy.IsAsset("https://studio.cyberboard.invalid" + path), "Unexpected asset accepted: " + path);
                Check(!ResourcePolicy.IsAsset("https://example.org/index.html"), "External asset origin accepted.");
                return Task.CompletedTask;
            });
            Console.WriteLine($"\n{passed} host bridge/resource checks passed. Native source linked unchanged; fake Python only, no USB.");
        }
        finally { Directory.Delete(temp, recursive: true); }
    }
}
