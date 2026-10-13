using System.Diagnostics;
using System.Text.Json;
using CyberboardStudio;

internal static class Program
{
    private sealed class MemoryVault : ICredentialVault
    {
        public Dictionary<string, string> Keys { get; } = new();
        public string? Read(string provider) => Keys.GetValueOrDefault(provider);
        public void Write(string provider, string key) => Keys[provider] = key;
        public void Delete(string provider) => Keys.Remove(provider);
    }
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
            await Run("AI official endpoint and model policies reject credential redirection", async () =>
            {
                var code = AISettings.Validate(Payload(new { }));
                Check(code.Provider == "kimi-code" && code.Model == "k3", "Incorrect Code defaults.");
                var open = AISettings.Validate(Payload(new { provider = "kimi-open" }));
                Check(open.Model == "kimi-k3", "Incorrect open-platform default.");
                Check(AISettings.Validate(Payload(new { baseUrl = "https://api.kimi.ai/coding/v1/", model = "kimi:code-v1.0" })).BaseUrl == "https://api.kimi.ai/coding/v1", "Global Code endpoint rejected.");
                foreach (var endpoint in new[] { "http://api.kimi.com/coding/v1", "https://api.kimi.com.evil/coding/v1", "https://user@api.kimi.com/coding/v1", "https://api.kimi.com/coding/v1?key=x", "https://api.moonshot.cn/v1", "https://127.0.0.1/v1" })
                    await Fails(() => { AISettings.Validate(Payload(new { baseUrl = endpoint })); return Task.CompletedTask; }, "官方 HTTPS");
                foreach (var model in new[] { "evil\nheader", "模型", new string('a', 129), "../../model" })
                    await Fails(() => { AISettings.Validate(Payload(new { model })); return Task.CompletedTask; }, "模型名称");
                await Fails(() => { AISettings.RequestId(Payload(new { requestId = "bad request" })); return Task.CompletedTask; }, "请求编号");
            });
            await Run("AI metadata never stores or returns secrets; blank retains and delete is provider scoped", async () =>
            {
                var vault = new MemoryVault();
                var settings = new AISettings(Path.Combine(temp, "AI 用户配置"), vault);
                var secret = "sk-offline-check-secret";
                var saved = JsonSerializer.Serialize(settings.Save(Payload(new { apiKey = "  " + secret + "  " })));
                Check(!saved.Contains(secret) && saved.Contains("hasKey"), "Save returned secret.");
                var metadata = File.ReadAllText(Path.Combine(temp, "AI 用户配置", "ai-settings.json"));
                Check(!metadata.Contains(secret) && !metadata.Contains("apiKey"), "Metadata stored a plaintext credential.");
                settings.Save(Payload(new { apiKey = "" }));
                Check(vault.Read("kimi-code") == secret, "Empty key erased an existing credential.");
                settings.Save(Payload(new { provider = "kimi-open", apiKey = "open-secret" }));
                settings.Save(Payload(new { provider = "kimi-open", removeKey = true }));
                Check(vault.Read("kimi-open") is null && vault.Read("kimi-code") == secret, "Removal crossed provider accounts.");
                settings.Save(Payload(new { provider = "kimi-code" }));
                var injected = settings.Inject(Payload(new { brief = "雨", ai = new { apiKey = "untrusted", baseUrl = "https://evil" } }));
                Check(injected.Payload.GetProperty("ai").GetProperty("apiKey").GetString() == secret, "Untrusted frontend credential replaced the vault.");
                Check(injected.Payload.GetProperty("ai").GetProperty("baseUrl").GetString() == "https://api.kimi.com/coding/v1", "Untrusted frontend endpoint persisted.");
                await Fails(() => { settings.Save(Payload(new { apiKey = "key\r\nheader" })); return Task.CompletedTask; }, "单行密钥");
                await Fails(() => { settings.Save(Payload(new { apiKey = new string('a', 4097) })); return Task.CompletedTask; }, "单行密钥");
            });
            await Run("legacy Code default migrates once while explicit and open models remain selected", () =>
            {
                var directory = Path.Combine(temp, "模型迁移 isolated");
                Directory.CreateDirectory(directory);
                var path = Path.Combine(directory, "ai-settings.json");
                var settings = new AISettings(directory, new MemoryVault());
                File.WriteAllText(path, JsonSerializer.Serialize(new { provider = "kimi-code", model = "kimi-for-coding" }));
                var first = JsonSerializer.SerializeToElement(settings.Get());
                Check(first.GetProperty("model").GetString() == "k3" && first.GetProperty("modelMigrated").GetBoolean(), "First read did not report default migration.");
                Check(settings.LoadConfiguration().Model == "k3", "Legacy default was not migrated.");
                using (var document = JsonDocument.Parse(File.ReadAllText(path)))
                {
                    Check(document.RootElement.GetProperty("modelDefaultsVersion").GetInt32() == 2, "Migration marker missing.");
                    Check(!document.RootElement.TryGetProperty("apiKey", out _), "Migration persisted a credential.");
                }
                Check(settings.LoadConfiguration().Model == "k3", "Migration was not stable.");
                settings.Save(Payload(new { model = "kimi-for-coding" }));
                Check(settings.LoadConfiguration().Model == "kimi-for-coding", "Explicit legacy alias migrated again.");
                File.WriteAllText(path, JsonSerializer.Serialize(new { provider = "kimi-code", model = "k3-256k" }));
                Check(settings.LoadConfiguration().Model == "k3-256k", "Custom model replaced.");
                File.WriteAllText(path, JsonSerializer.Serialize(new { provider = "kimi-open", model = "kimi-k3" }));
                Check(settings.LoadConfiguration().Model == "kimi-k3", "Open platform model replaced.");
                var result = JsonSerializer.SerializeToElement(settings.Get());
                Check(result.GetProperty("modelDefaultsVersion").GetInt32() == 2 && !result.GetProperty("modelMigrated").GetBoolean(), "Migration status wrong.");
                return Task.CompletedTask;
            });
            await Run("AI child stdout and diagnostics cannot expose the credential", async () =>
            {
                using var client = new BackendClient();
                var events = new List<JsonElement>();
                var secret = "sk-stdout-test-secret";
                var before = HostLog.Messages.Count;
                var result = await client.RunAsync("echo", Payload(new { apiKey = secret, nested = new { note = "prefix:" + secret, apiKey = secret } }), events.Add, secret: secret);
                Check(!result.GetRawText().Contains(secret) && !result.GetRawText().Contains("apiKey"), "Result exposed a credential.");
                Check(events.All(e => !e.GetRawText().Contains(secret)), "Progress exposed a credential.");
                Check(HostLog.Messages.Count == before, "AI stderr reached host logs.");
            });
            await Run("request cancellation stops AI child while the independent device lane completes", async () =>
            {
                using var ai = new BackendClient();
                using var device = new BackendClient();
                using var cancellation = new CancellationTokenSource();
                var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                var active = ai.RunAsync("cancel", Payload(new { }), _ => started.TrySetResult(), cancellation.Token, "offline-secret");
                await started.Task.WaitAsync(TimeSpan.FromSeconds(5));
                var other = device.RunAsync("queue", Payload(new { lane = "device" }), _ => { });
                cancellation.Cancel();
                try { await active.WaitAsync(TimeSpan.FromSeconds(5)); throw new Exception("Expected AI cancellation."); }
                catch (OperationCanceledException) { }
                Check((await other).GetProperty("payload").GetProperty("lane").GetString() == "device", "AI cancellation interrupted the unrelated backend.");
                var next = await ai.RunAsync("echo", Payload(new { after = true }), _ => { });
                Check(next.GetProperty("payload").GetProperty("after").GetBoolean(), "AI lane was unusable after cancellation.");
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
