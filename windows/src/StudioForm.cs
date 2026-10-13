using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace CyberboardStudio;

internal sealed class StudioForm : Form
{
    private readonly WebView2 web = new() { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.FromArgb(14, 16, 21) };
    private readonly BackendClient backend = new();
    private readonly BackendClient aiBackend = new();
    private readonly AISettings aiSettings = new(HostPaths.State);
    private CancellationTokenSource? aiCancellation;
    private string? activeAIRequestId;
    private readonly Label loading = new()
    {
        Dock = DockStyle.Fill, Text = "正在载入 Cyberboard Studio…", TextAlign = ContentAlignment.MiddleCenter,
        ForeColor = Color.FromArgb(238, 241, 247), BackColor = Color.FromArgb(14, 16, 21), Font = new Font("Segoe UI", 12)
    };
    private bool deviceWritePending;
    private int navigationGeneration;
    private static readonly HashSet<string> BackendActions = new(StringComparer.Ordinal)
    { "bootstrap", "detect", "plan", "execute", "history", "keymap", "setTime", "restorePlan", "saveWorkspace" };
    private static readonly HashSet<string> DeviceWriteActions = new(StringComparer.Ordinal) { "execute", "setTime" };
    private static readonly JsonSerializerOptions PrettyJson = new() { WriteIndented = true, MaxDepth = 256 };

    private const string Adapter = """
        (() => {
          if (window.top !== window || location.origin !== 'https://studio.cyberboard.invalid') return;
          Object.defineProperty(window, 'StudioNative', {value: Object.freeze({
            platform: 'windows',
            postMessage(message) { window.chrome.webview.postMessage(message); }
          }), writable: false, configurable: false});
          window.chrome.webview.addEventListener('message', event => {
            const message = event.data;
            if (!message || !['receive', 'event'].includes(message.method)) return;
            window.StudioBridge?.[message.method]?.(message.value);
          });
          document.addEventListener('DOMContentLoaded', () => {
            document.documentElement.dataset.platform = 'windows';
          }, {once: true});
        })();
        """;

    public StudioForm()
    {
        Text = "Cyberboard Studio";
        BackColor = Color.FromArgb(14, 16, 21);
        MinimumSize = new Size(1100, 740);
        ClientSize = new Size(1440, 940);
        StartPosition = FormStartPosition.CenterScreen;
        KeyPreview = true;
        var area = Screen.PrimaryScreen?.WorkingArea ?? new Rectangle(0, 0, 1440, 940);
        Size = new Size(Math.Min(Width, area.Width), Math.Min(Height, area.Height));
        var icon = Path.Combine(AppContext.BaseDirectory, "AppIcon.ico");
        if (File.Exists(icon)) Icon = new Icon(icon);
        var menu = BuildMenu();
        MainMenuStrip = menu;
        Controls.Add(web);
        Controls.Add(loading);
        Controls.Add(menu);
        Shown += async (_, _) => await InitializeAsync();
        FormClosing += OnClosing;
        FormClosed += (_, _) => { aiCancellation?.Cancel(); aiBackend.Dispose(); backend.Dispose(); };
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        try
        {
            var enabled = 1;
            DwmSetWindowAttribute(Handle, 20, ref enabled, sizeof(int));
        }
        catch (DllNotFoundException) { }
        catch (EntryPointNotFoundException) { }
    }

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

    private async Task InitializeAsync()
    {
        try
        {
            if (!File.Exists(Path.Combine(HostPaths.Web, "index.html")))
                throw new IOException("应用资源缺失。请完整解压安装包后再运行，保留 resources 文件夹。");
            Directory.CreateDirectory(HostPaths.Profile);
            var fixedRuntime = Path.Combine(HostPaths.Resources, "webview2");
            var browserPath = File.Exists(Path.Combine(fixedRuntime, "msedgewebview2.exe")) ? fixedRuntime : null;
            var environment = await CoreWebView2Environment.CreateAsync(browserPath, HostPaths.Profile);
            await web.EnsureCoreWebView2Async(environment);
            var core = web.CoreWebView2;
            core.Settings.IsWebMessageEnabled = true;
            core.Settings.AreHostObjectsAllowed = false;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.AreDevToolsEnabled = false;
            core.Settings.IsZoomControlEnabled = false;
            core.Settings.AreBrowserAcceleratorKeysEnabled = false;
            core.SetVirtualHostNameToFolderMapping(ResourcePolicy.Host, HostPaths.Web, CoreWebView2HostResourceAccessKind.Deny);
            core.NavigationStarting += OnNavigationStarting;
            core.FrameNavigationStarting += (_, args) => args.Cancel = true;
            core.NewWindowRequested += (_, args) =>
            {
                args.Handled = true;
                if (args.IsUserInitiated) OpenExternalLink(args.Uri);
            };
            core.WebMessageReceived += OnWebMessageReceived;
            core.PermissionRequested += (_, args) => args.State = CoreWebView2PermissionState.Deny;
            core.DownloadStarting += (_, args) => args.Cancel = true;
            core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += (_, args) =>
            {
                if (ResourcePolicy.IsAsset(args.Request.Uri)) return;
                args.Response = environment.CreateWebResourceResponse(null, 403, "Forbidden", "Content-Type: text/plain; charset=utf-8");
            };
            core.NavigationCompleted += (_, args) =>
            {
                if (!args.IsSuccess)
                {
                    loading.Text = "工作台载入失败：" + args.WebErrorStatus;
                    loading.Visible = true;
                    return;
                }
                loading.Visible = false;
                SendEvent(new { @event = "nativeReady", app = "Cyberboard Studio", version = "0.1.0", platform = "windows" });
            };
            core.ProcessFailed += (_, args) =>
            {
                HostLog.Write("webview", args.ProcessFailedKind.ToString());
                loading.Text = deviceWritePending
                    ? "预览组件发生错误。设备操作仍在进行，请等待同步完成后重新载入。"
                    : "预览组件发生错误。请从「视图」菜单重新载入。";
                loading.Visible = true;
            };
            web.KeyDown += (_, args) =>
            {
                if (args.KeyCode == Keys.F5 || (args.Control && args.KeyCode == Keys.R))
                {
                    args.Handled = true;
                    args.SuppressKeyPress = true;
                    // WebView2 forwards accelerator keys through WinForms KeyDown. Queue the
                    // reload after its synchronous browser input callback has returned.
                    BeginInvoke(ReloadWorkbench);
                }
            };
            await core.AddScriptToExecuteOnDocumentCreatedAsync(Adapter);
            core.Navigate(ResourcePolicy.Index);
        }
        catch (WebView2RuntimeNotFoundException exception)
        {
            HostLog.Write("startup", exception.ToString());
            loading.Text = "缺少 Microsoft Edge WebView2 Runtime。\n" +
                "请手动运行应用文件夹中的 Dependencies\\MicrosoftEdgeWebview2Setup.exe，\n" +
                "按微软安装向导完成安装后，重新打开 Cyberboard Studio。";
            MessageBox.Show(this, loading.Text, "Cyberboard Studio", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception exception)
        {
            HostLog.Write("startup", exception.ToString());
            loading.Text = "无法载入工作台：\n" + exception.Message;
        }
    }

    private MenuStrip BuildMenu()
    {
        var menu = new MenuStrip
        {
            BackColor = Color.FromArgb(22, 25, 31), ForeColor = Color.FromArgb(238, 241, 247),
            Renderer = new ToolStripProfessionalRenderer(new DarkMenuColors())
        };
        var file = new ToolStripMenuItem("文件");
        file.DropDownItems.Add(MenuItem("导入 JSON…", Keys.Control | Keys.I, () => SendEvent(new { @event = "menu", action = "importJSON" })));
        file.DropDownItems.Add(MenuItem("导出 JSON…", Keys.Control | Keys.E, () => SendEvent(new { @event = "menu", action = "exportJSON" })));
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add(MenuItem("退出", Keys.Alt | Keys.F4, Close));
        var edit = new ToolStripMenuItem("编辑");
        foreach (var item in new[] { ("撤销", "undo", Keys.Control | Keys.Z), ("剪切", "cut", Keys.Control | Keys.X),
            ("复制", "copy", Keys.Control | Keys.C), ("粘贴", "paste", Keys.Control | Keys.V), ("全选", "selectAll", Keys.Control | Keys.A) })
            edit.DropDownItems.Add(MenuItem(item.Item1, Keys.None, async () =>
            {
                if (web.CoreWebView2 is not null && ResourcePolicy.IsDocument(web.Source?.AbsoluteUri ?? ""))
                    await web.CoreWebView2.ExecuteScriptAsync($"document.execCommand('{item.Item2}');");
            }, item.Item3.ToString().Replace("Control", "Ctrl").Replace(", ", "+")));
        var view = new ToolStripMenuItem("视图");
        view.DropDownItems.Add(MenuItem("重新载入", Keys.Control | Keys.R, ReloadWorkbench));
        var help = new ToolStripMenuItem("帮助");
        help.DropDownItems.Add(MenuItem("关于 Cyberboard Studio", Keys.None, () => MessageBox.Show(this,
            "Cyberboard Studio 0.2.1\nWindows 桌面版\n\nAI 灯效创作、整机预览、JSON 导入导出与本地 USB 同步。",
            "关于 Cyberboard Studio", MessageBoxButtons.OK, MessageBoxIcon.Information)));
        menu.Items.AddRange([file, edit, view, help]);
        return menu;
    }

    private static ToolStripMenuItem MenuItem(string title, Keys shortcut, Action action, string? display = null)
    {
        var item = new ToolStripMenuItem(title) { ShortcutKeys = shortcut };
        if (display is not null) item.ShortcutKeyDisplayString = display;
        item.Click += (_, _) => action();
        return item;
    }

    private void ReloadWorkbench()
    {
        if (deviceWritePending) { ShowWriteInProgress(); return; }
        aiCancellation?.Cancel();
        if (web.CoreWebView2 is not null) web.CoreWebView2.Reload();
    }

    private void OnNavigationStarting(object? sender, CoreWebView2NavigationStartingEventArgs args)
    {
        if (deviceWritePending) { args.Cancel = true; return; }
        if (ResourcePolicy.IsDocument(args.Uri)) { aiCancellation?.Cancel(); navigationGeneration++; return; }
        args.Cancel = true;
        if (args.IsUserInitiated) OpenExternalLink(args.Uri);
    }

    private void OpenExternalLink(string value)
    {
        if (!ResourcePolicy.IsExternalLink(value)) return;
        try { Process.Start(new ProcessStartInfo(value) { UseShellExecute = true }); }
        catch (Exception exception) { HostLog.Write("external link", exception.Message); }
    }

    private async void OnWebMessageReceived(object? sender, CoreWebView2WebMessageReceivedEventArgs args)
    {
        if (!ResourcePolicy.IsDocument(args.Source) || !ResourcePolicy.IsDocument(web.Source?.AbsoluteUri ?? "")) return;
        JsonElement id;
        JsonElement payload;
        string action;
        try
        {
            using var document = JsonDocument.Parse(args.WebMessageAsJson, new JsonDocumentOptions { MaxDepth = 256 });
            var message = document.RootElement;
            if (message.ValueKind != JsonValueKind.Object || !message.TryGetProperty("id", out var requestId) ||
                requestId.ValueKind is not (JsonValueKind.String or JsonValueKind.Number) ||
                !message.TryGetProperty("action", out var actionValue) || actionValue.ValueKind != JsonValueKind.String) return;
            id = requestId.Clone();
            action = actionValue.GetString()!;
            payload = message.TryGetProperty("payload", out var value) && value.ValueKind == JsonValueKind.Object
                ? value.Clone() : JsonSerializer.SerializeToElement(new { });
        }
        catch (JsonException) { return; }
        var generation = navigationGeneration;
        var writesDevice = DeviceWriteActions.Contains(action);
        try
        {
            switch (action)
            {
                case "importJSON": await ImportJsonAsync(id, generation); return;
                case "exportJSON": await ExportJsonAsync(id, payload, generation); return;
                case "importAIImages": await ImportAIImagesAsync(id, generation); return;
                case "getAISettings":
                    Reply(id, await Task.Run(aiSettings.Get), generation); return;
                case "saveAISettings":
                    if (activeAIRequestId is not null) throw new IOException("AI 请求正在进行，请先取消或等待完成再修改模型配置。");
                    Reply(id, await Task.Run(() => aiSettings.Save(payload)), generation); return;
                case "testAIConnection":
                case "generateAI": await RunAIAsync(id, action, payload, generation); return;
                case "cancelAI":
                    var cancelId = AISettings.RequestId(payload);
                    var cancelled = activeAIRequestId == cancelId;
                    if (cancelled) aiCancellation?.Cancel();
                    Reply(id, new { cancelled, requestId = cancelId }, generation); return;
            }
            if (!BackendActions.Contains(action)) { ReplyError(id, "不支持的操作：" + action, generation); return; }
            if (writesDevice && (deviceWritePending || activeAIRequestId is not null))
            {
                ReplyError(id, "设备操作或 AI 请求正在进行，请等待完成后再试。", generation);
                return;
            }
            if (writesDevice) deviceWritePending = true;
            try
            {
                // Keep subprocess I/O and JSON parsing off the UI thread; marshal only events and replies.
                var result = await Task.Run(() => backend.RunAsync(action, payload, record =>
                {
                    var values = record.EnumerateObject().ToDictionary(property => property.Name, property => (object?)property.Value.Clone());
                    values.TryAdd("id", id);
                    PostToUi(() => SendEvent(values, generation));
                }));
                Reply(id, result, generation);
            }
            finally { if (writesDevice) deviceWritePending = false; }
        }
        catch (OperationCanceledException) { }
        catch (Exception exception)
        {
            if (action is "getAISettings" or "saveAISettings" or "testAIConnection" or "generateAI" or "cancelAI" or "importAIImages")
                HostLog.Write("AI request", exception.GetType().Name);
            else HostLog.Write("request " + action, exception.ToString());
            ReplyError(id, exception.Message, generation);
        }
    }

    private async Task ImportAIImagesAsync(JsonElement id, int generation)
    {
        using var dialog = new OpenFileDialog
        {
            Filter = "参考图 (*.png;*.jpg;*.jpeg;*.webp;*.gif)|*.png;*.jpg;*.jpeg;*.webp;*.gif",
            Title = "选择最多 3 张参考图，每张最多 20 MB", Multiselect = true,
            CheckFileExists = true, RestoreDirectory = true
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) { Reply(id, new { cancelled = true }, generation); return; }
        var paths = dialog.FileNames;
        if (paths.Length is < 1 or > 3) throw new IOException("一次最多选择 3 张参考图。");
        foreach (var path in paths)
        {
            long length;
            try { length = new FileInfo(path).Length; }
            catch { throw new IOException("无法读取所选参考图，请重新选择。"); }
            if (length is < 1 or > 20L * 1024 * 1024) throw new IOException("参考图必须为有效文件，且每张不超过 20 MB。");
        }
        // Native-selected paths are passed only on stdin, never exposed to the web bridge or diagnostics.
        var result = await Task.Run(() => backend.RunAsync("prepareAIImages", JsonSerializer.SerializeToElement(new { paths }), _ => { }, secret: ""));
        Reply(id, result, generation);
    }

    private async Task RunAIAsync(JsonElement id, string action, JsonElement payload, int generation)
    {
        if (deviceWritePending) throw new IOException("设备写入正在进行，请等待完成后再使用 AI。");
        if (activeAIRequestId is not null) throw new IOException("已有 AI 请求正在进行，请先取消或等待完成。");
        var requestId = action == "generateAI" || payload.TryGetProperty("requestId", out _)
            ? AISettings.RequestId(payload) : Guid.NewGuid().ToString("N");
        using var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(360));
        activeAIRequestId = requestId;
        aiCancellation = cancellation;
        try
        {
            var injected = await Task.Run(() => aiSettings.Inject(payload), cancellation.Token);
            var result = await Task.Run(() => aiBackend.RunAsync(action, injected.Payload, record =>
            {
                var values = record.EnumerateObject().ToDictionary(p => p.Name, p => (object?)p.Value.Clone());
                values.TryAdd("id", id);
                values["requestId"] = requestId;
                PostToUi(() => SendEvent(values, generation));
            }, cancellation.Token, injected.Secret), cancellation.Token);
            Reply(id, result, generation);
        }
        catch (OperationCanceledException)
        {
            Reply(id, new { cancelled = true, requestId }, generation);
        }
        finally
        {
            if (ReferenceEquals(aiCancellation, cancellation))
            {
                aiCancellation = null;
                activeAIRequestId = null;
            }
        }
    }

    private async Task ImportJsonAsync(JsonElement id, int generation)
    {
        using var dialog = new OpenFileDialog
        {
            Filter = "Cyberboard JSON (*.json)|*.json", Title = "选择 Cyberboard 灯效或完整配置 JSON",
            Multiselect = false, CheckFileExists = true, RestoreDirectory = true
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) { Reply(id, new { cancelled = true }, generation); return; }
        var path = dialog.FileName;
        var json = await Task.Run(async () =>
        {
            if (new FileInfo(path).Length > 256L * 1024 * 1024) throw new IOException("这个 JSON 文件过大（超过 256 MB）。");
            await using var stream = File.OpenRead(path);
            using var document = await JsonDocument.ParseAsync(stream, new JsonDocumentOptions { MaxDepth = 256 });
            return document.RootElement.Clone();
        });
        Reply(id, new { fileName = Path.GetFileName(path), json }, generation);
    }

    private async Task ExportJsonAsync(JsonElement id, JsonElement payload, int generation)
    {
        if (!payload.TryGetProperty("json", out var json) || json.ValueKind is not (JsonValueKind.Object or JsonValueKind.Array))
            throw new IOException("没有可导出的有效 JSON。");
        var fileName = payload.TryGetProperty("fileName", out var value) && value.ValueKind == JsonValueKind.String
            ? Path.GetFileName(value.GetString()) : "Cyberboard-design.json";
        if (string.IsNullOrWhiteSpace(fileName) || fileName.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0) fileName = "Cyberboard-design.json";
        using var dialog = new SaveFileDialog
        {
            Filter = "Cyberboard JSON (*.json)|*.json", DefaultExt = "json", AddExtension = true,
            FileName = fileName, OverwritePrompt = true, RestoreDirectory = true, Title = "导出 Cyberboard JSON"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) { Reply(id, new { cancelled = true }, generation); return; }
        var path = dialog.FileName;
        await Task.Run(async () =>
        {
            var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                await File.WriteAllTextAsync(temporary, JsonSerializer.Serialize(json, PrettyJson), new UTF8Encoding(false));
                File.Move(temporary, path, overwrite: true);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        });
        Reply(id, new { fileName = Path.GetFileName(path), path }, generation);
    }

    private void Reply(JsonElement id, object result, int generation) => Send("receive", new { id, result }, generation);
    private void ReplyError(JsonElement id, string error, int generation) => Send("receive", new { id, error }, generation);
    private void SendEvent(object value, int? generation = null) => Send("event", value, generation ?? navigationGeneration);
    private void Send(string method, object value, int generation)
    {
        if (IsDisposed || generation != navigationGeneration || web.CoreWebView2 is null || !ResourcePolicy.IsDocument(web.Source?.AbsoluteUri ?? "")) return;
        web.CoreWebView2.PostWebMessageAsJson(JsonSerializer.Serialize(new { method, value }));
    }

    private void PostToUi(Action action)
    {
        if (IsDisposed || !IsHandleCreated) return;
        try { BeginInvoke(action); }
        catch (InvalidOperationException) { }
    }

    private void OnClosing(object? sender, FormClosingEventArgs args)
    {
        if (!deviceWritePending) { aiCancellation?.Cancel(); return; }
        args.Cancel = true;
        ShowWriteInProgress();
    }

    private void ShowWriteInProgress() => MessageBox.Show(this,
        "请等待同步完成后再退出或重新载入 Cyberboard Studio。", "设备操作正在进行",
        MessageBoxButtons.OK, MessageBoxIcon.Information);
}

internal sealed class DarkMenuColors : ProfessionalColorTable
{
    public override Color ToolStripDropDownBackground => Color.FromArgb(27, 30, 37);
    public override Color MenuItemSelected => Color.FromArgb(52, 57, 69);
    public override Color MenuItemSelectedGradientBegin => MenuItemSelected;
    public override Color MenuItemSelectedGradientEnd => MenuItemSelected;
    public override Color MenuItemPressedGradientBegin => MenuItemSelected;
    public override Color MenuItemPressedGradientEnd => MenuItemSelected;
    public override Color ImageMarginGradientBegin => ToolStripDropDownBackground;
    public override Color ImageMarginGradientMiddle => ToolStripDropDownBackground;
    public override Color ImageMarginGradientEnd => ToolStripDropDownBackground;
}
