using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace CyberboardStudio;

// One request starts one Python process. No payload is interpolated into a shell command.
internal sealed class BackendClient : IDisposable
{
    private readonly SemaphoreSlim queue = new(1, 1);
    private readonly CancellationTokenSource shutdown = new();
    private const int DiagnosticLimit = 65536;

    public async Task<JsonElement> RunAsync(string action, JsonElement payload, Action<JsonElement> onEvent,
        CancellationToken cancellationToken = default, string? secret = null)
    {
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(shutdown.Token, cancellationToken);
        var cancellation = linked.Token;
        await queue.WaitAsync(cancellation);
        try
        {
            if (!File.Exists(HostPaths.Backend)) throw new IOException("后台组件缺失，请重新解压完整的应用文件夹。");
            if (!File.Exists(HostPaths.Python)) throw new IOException("Python CLI 组件缺失，请重新解压完整的应用文件夹。");
            Directory.CreateDirectory(HostPaths.State);

            var start = new ProcessStartInfo(HostPaths.Python)
            {
                WorkingDirectory = HostPaths.Resources,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardInputEncoding = new UTF8Encoding(false),
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8
            };
            start.ArgumentList.Add("-X");
            start.ArgumentList.Add("utf8");
            start.ArgumentList.Add("-u");
            start.ArgumentList.Add(HostPaths.Backend);
            start.ArgumentList.Add("--action");
            start.ArgumentList.Add(action);
            start.ArgumentList.Add("--state-dir");
            start.ArgumentList.Add(HostPaths.State);
            start.ArgumentList.Add("--resource-dir");
            start.ArgumentList.Add(HostPaths.Resources);
            start.Environment["PYTHONUNBUFFERED"] = "1";
            start.Environment["PYTHONIOENCODING"] = "utf-8";
            // Embedded Python is self-contained; inherited Python paths must not change its imports.
            start.Environment.Remove("PYTHONHOME");
            start.Environment.Remove("PYTHONPATH");

            using var process = new Process { StartInfo = start };
            try
            {
                if (!process.Start()) throw new IOException("无法启动后台组件。");
                using var registration = cancellation.Register(() =>
                {
                    try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
                    catch (InvalidOperationException) { }
                    catch (System.ComponentModel.Win32Exception) { }
                });
                var diagnostics = DrainDiagnosticsAsync(process.StandardError, cancellation);
                var input = WriteInputAsync(process.StandardInput, payload, cancellation);
                JsonElement? final = null;
                string? parseError = null;
                while (await process.StandardOutput.ReadLineAsync(cancellation) is { } line)
                {
                    if (string.IsNullOrWhiteSpace(line)) continue;
                    try
                    {
                        using var document = JsonDocument.Parse(line, new JsonDocumentOptions { MaxDepth = 256 });
                        var record = document.RootElement;
                        if (record.ValueKind != JsonValueKind.Object)
                        {
                            parseError = "后台返回了无法识别的数据。";
                            continue;
                        }
                        if (record.TryGetProperty("event", out _) ||
                            (record.TryGetProperty("type", out var type) && type.ValueKind == JsonValueKind.String && type.GetString() == "event"))
                            onEvent(secret is null ? record.Clone() : AISettings.Redact(record, secret));
                        else if (record.TryGetProperty("result", out _) || record.TryGetProperty("error", out _))
                            final = record.Clone();
                        else parseError = "后台返回的数据缺少结果字段。";
                    }
                    catch (JsonException) { parseError = "后台返回的数据不是有效的 JSON。"; }
                }
                await process.WaitForExitAsync(cancellation);
                await input;
                var diagnosticText = await diagnostics;
                // AI subprocess diagnostics are never copied to host logs: SDK/network errors may contain credentials.
                if (secret is null && !string.IsNullOrWhiteSpace(diagnosticText)) HostLog.Write("backend " + action, diagnosticText);
                if (parseError is not null) throw new IOException(parseError);
                if (final is null) throw new IOException($"后台没有返回操作结果（{process.ExitCode}）。");
                var safeFinal = secret is null ? final.Value : AISettings.Redact(final.Value, secret);
                if (safeFinal.TryGetProperty("error", out var error))
                    throw new IOException(error.ValueKind == JsonValueKind.String ? error.GetString() : error.GetRawText());
                if (process.ExitCode != 0) throw new IOException($"后台操作未成功完成（{process.ExitCode}）。");
                return safeFinal.GetProperty("result").Clone();
            }
            catch
            {
                try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
                catch (InvalidOperationException) { }
                catch (System.ComponentModel.Win32Exception) { }
                throw;
            }
        }
        finally { queue.Release(); }
    }

    private static async Task WriteInputAsync(StreamWriter stream, JsonElement payload, CancellationToken cancellation)
    {
        try
        {
            await stream.WriteAsync(payload.GetRawText().AsMemory(), cancellation);
            await stream.FlushAsync(cancellation);
        }
        catch (IOException) { /* A process that exits early can close stdin before receiving its payload. */ }
        finally { stream.Close(); }
    }

    private static async Task<string> DrainDiagnosticsAsync(StreamReader stream, CancellationToken cancellation)
    {
        var tail = new StringBuilder();
        var buffer = new char[4096];
        int count;
        while ((count = await stream.ReadAsync(buffer.AsMemory(), cancellation)) != 0)
        {
            tail.Append(buffer, 0, count);
            if (tail.Length > DiagnosticLimit) tail.Remove(0, tail.Length - DiagnosticLimit);
        }
        return tail.ToString();
    }

    public void Dispose() => shutdown.Cancel();
}
