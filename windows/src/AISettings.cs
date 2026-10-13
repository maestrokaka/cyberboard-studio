using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace CyberboardStudio;

internal interface ICredentialVault
{
    string? Read(string provider);
    void Write(string provider, string key);
    void Delete(string provider);
}

internal sealed record AIConfiguration(string Provider, string BaseUrl, string Model);

internal sealed class AISettings
{
    private readonly string state;
    private readonly ICredentialVault vault;
    private readonly object gate = new();
    private bool lastModelMigration;
    private static readonly Dictionary<string, string[]> Endpoints = new(StringComparer.Ordinal)
    {
        ["kimi-code"] = ["https://api.kimi.com/coding/v1", "https://api.kimi.ai/coding/v1"],
        ["kimi-open"] = ["https://api.moonshot.cn/v1", "https://api.moonshot.ai/v1"]
    };
    private static readonly Regex ModelPattern = new(@"\A[A-Za-z0-9._:-]{1,128}\z", RegexOptions.CultureInvariant);
    private static readonly Regex RequestPattern = new(@"\A[A-Za-z0-9_-]{1,80}\z", RegexOptions.CultureInvariant);

    public AISettings(string state, ICredentialVault? vault = null)
    {
        this.state = state;
        this.vault = vault ?? new DPAPICredentialVault(Path.Combine(state, "credentials"));
    }

    internal static string RequestId(JsonElement payload)
    {
        var id = Text(payload, "requestId");
        if (id is null || !RequestPattern.IsMatch(id)) throw new IOException("AI 请求编号无效。");
        return id;
    }

    private static string? Text(JsonElement value, string key) =>
        value.TryGetProperty(key, out var item) && item.ValueKind == JsonValueKind.String ? item.GetString() : null;

    internal static AIConfiguration Validate(JsonElement value)
    {
        var provider = Text(value, "provider") ?? "kimi-code";
        if (!Endpoints.TryGetValue(provider, out var endpoints)) throw new IOException("请选择 Kimi Code 或 Kimi 开放平台。");
        var baseUrl = (Text(value, "baseUrl") ?? endpoints[0]).Trim().TrimEnd('/');
        if (!endpoints.Contains(baseUrl, StringComparer.Ordinal)) throw new IOException("API 地址必须为对应服务的官方 HTTPS 地址。");
        var model = (Text(value, "model") ?? (provider == "kimi-code" ? "k3" : "kimi-k3")).Trim();
        if (!ModelPattern.IsMatch(model)) throw new IOException("模型名称只能包含字母、数字、点、横线、下划线或冒号，最多 128 个字符。");
        return new AIConfiguration(provider, baseUrl, model);
    }

    private void WriteMetadata(AIConfiguration config)
    {
        Directory.CreateDirectory(state);
        var path = Path.Combine(state, "ai-settings.json");
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllText(temporary, JsonSerializer.Serialize(new
            {
                provider = config.Provider, baseUrl = config.BaseUrl, model = config.Model, modelDefaultsVersion = 2
            }, new JsonSerializerOptions { WriteIndented = true }), new UTF8Encoding(false));
            File.Move(temporary, path, overwrite: true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    internal AIConfiguration LoadConfiguration()
    {
        lastModelMigration = false;
        var path = Path.Combine(state, "ai-settings.json");
        if (!File.Exists(path)) return Validate(JsonSerializer.SerializeToElement(new { }));
        try
        {
            if (new FileInfo(path).Length > 16384) throw new IOException();
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var value = document.RootElement;
            var config = Validate(value);
            var version = value.TryGetProperty("modelDefaultsVersion", out var marker) && marker.TryGetInt32(out var number) ? number : 0;
            if (version < 2)
            {
                if (config.Provider == "kimi-code" && config.Model == "kimi-for-coding")
                {
                    config = config with { Model = "k3" };
                    lastModelMigration = true;
                }
                WriteMetadata(config);
            }
            return config;
        }
        catch { throw new IOException("模型配置文件无法读取，请在模型配置中重新保存服务配置。"); }
    }

    private object Public(AIConfiguration config, bool hasKey) => new
    {
        provider = config.Provider, baseUrl = config.BaseUrl, model = config.Model,
        hasKey, credentialStore = "Windows DPAPI（当前用户）", modelDefaultsVersion = 2, modelMigrated = lastModelMigration
    };

    public object Get()
    {
        lock (gate)
        {
            var config = LoadConfiguration();
            return Public(config, !string.IsNullOrEmpty(vault.Read(config.Provider)));
        }
    }

    public object Save(JsonElement payload)
    {
        lock (gate)
        {
            lastModelMigration = false;
            var config = Validate(payload);
            var key = Text(payload, "apiKey") ?? "";
            if (key.Contains('\r') || key.Contains('\n') || key.Length > 4096) throw new IOException("API Key 格式无效，请粘贴完整的单行密钥。");
            key = key.Trim();
            var remove = payload.TryGetProperty("removeKey", out var removeValue) && removeValue.ValueKind == JsonValueKind.True;
            if (remove && key.Length > 0) throw new IOException("删除密钥与设置新密钥不能同时进行。");
            Directory.CreateDirectory(state);
            if (remove) vault.Delete(config.Provider);
            else if (key.Length > 0) vault.Write(config.Provider, key);
            WriteMetadata(config);
            return Public(config, !string.IsNullOrEmpty(vault.Read(config.Provider)));
        }
    }

    public (JsonElement Payload, string Secret) Inject(JsonElement payload)
    {
        lock (gate)
        {
            var config = LoadConfiguration();
            var secret = vault.Read(config.Provider);
            if (string.IsNullOrEmpty(secret)) throw new IOException("请先在模型配置中保存 API Key。");
            var values = payload.EnumerateObject().Where(p => p.Name != "ai")
                .ToDictionary(p => p.Name, p => (object?)p.Value.Clone());
            values["ai"] = new { provider = config.Provider, baseUrl = config.BaseUrl, model = config.Model, apiKey = secret };
            return (JsonSerializer.SerializeToElement(values), secret);
        }
    }

    internal static JsonElement Redact(JsonElement value, string secret)
    {
        if (string.IsNullOrEmpty(secret)) return value.Clone();
        object? Scrub(JsonElement item) => item.ValueKind switch
        {
            JsonValueKind.Object => item.EnumerateObject().Where(p => p.Name != "apiKey")
                .ToDictionary(p => p.Name, p => Scrub(p.Value)),
            JsonValueKind.Array => item.EnumerateArray().Select(Scrub).ToArray(),
            JsonValueKind.String => item.GetString()!.Replace(secret, "[已隐藏]", StringComparison.Ordinal),
            JsonValueKind.Number => item.Clone(), JsonValueKind.True => true, JsonValueKind.False => false, _ => null
        };
        return JsonSerializer.SerializeToElement(Scrub(value));
    }
}

internal sealed class DPAPICredentialVault(string directory) : ICredentialVault
{
    [StructLayout(LayoutKind.Sequential)]
    private struct Blob { public int Length; public IntPtr Data; }
    [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(ref Blob input, string? description, IntPtr entropy, IntPtr reserved, IntPtr prompt, int flags, out Blob output);
    [DllImport("crypt32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptUnprotectData(ref Blob input, IntPtr description, IntPtr entropy, IntPtr reserved, IntPtr prompt, int flags, out Blob output);
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr pointer);
    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string descriptor, uint revision, out IntPtr security, out uint size);
    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetFileSecurity(string path, uint information, IntPtr security);

    private string PathFor(string provider)
    {
        if (provider is not ("kimi-code" or "kimi-open")) throw new IOException("未知凭据服务。");
        return Path.Combine(directory, provider + ".dpapi");
    }

    private static byte[] Transform(byte[] bytes, bool protect)
    {
        var input = new Blob { Length = bytes.Length, Data = Marshal.AllocHGlobal(bytes.Length) };
        Blob output = default;
        try
        {
            Marshal.Copy(bytes, 0, input.Data, bytes.Length);
            // CRYPTPROTECT_UI_FORBIDDEN; no machine scope flag: bound to this Windows user.
            var success = protect
                ? CryptProtectData(ref input, "Cyberboard Studio.Kimi", IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 1, out output)
                : CryptUnprotectData(ref input, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 1, out output);
            if (!success || output.Length < 1 || output.Length > 65536) throw new IOException("Windows 无法访问加密凭据，请重新保存 API Key。");
            var result = new byte[output.Length];
            Marshal.Copy(output.Data, result, 0, result.Length);
            return result;
        }
        finally
        {
            for (var i = 0; i < input.Length; i++) Marshal.WriteByte(input.Data, i, 0);
            Marshal.FreeHGlobal(input.Data);
            if (output.Data != IntPtr.Zero)
            {
                for (var i = 0; i < output.Length; i++) Marshal.WriteByte(output.Data, i, 0);
                LocalFree(output.Data);
            }
        }
    }

    private static void RestrictToCurrentUser(string path)
    {
        if (!OperatingSystem.IsWindows()) throw new IOException("加密凭据仅可在 Windows 当前用户中保存。");
        var sid = WindowsIdentity.GetCurrent().User?.Value ?? throw new IOException("无法确定 Windows 当前用户。");
        if (!ConvertStringSecurityDescriptorToSecurityDescriptor($"D:P(A;;FA;;;{sid})", 1, out var descriptor, out _))
            throw new IOException("无法保护凭据文件访问权限。");
        try
        {
            if (!SetFileSecurity(path, 0x00000004, descriptor)) throw new IOException("无法保护凭据文件访问权限。");
        }
        finally { LocalFree(descriptor); }
    }

    public string? Read(string provider)
    {
        var path = PathFor(provider);
        if (!File.Exists(path)) return null;
        if (new FileInfo(path).Length > 65536) throw new IOException("加密凭据文件无效，请重新保存 API Key。");
        var plain = Transform(File.ReadAllBytes(path), protect: false);
        try { return Encoding.UTF8.GetString(plain); }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    public void Write(string provider, string key)
    {
        var plain = Encoding.UTF8.GetBytes(key);
        byte[] encrypted;
        try { encrypted = Transform(plain, protect: true); }
        finally { CryptographicOperations.ZeroMemory(plain); }
        Directory.CreateDirectory(directory);
        var path = PathFor(provider);
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllBytes(temporary, encrypted);
            RestrictToCurrentUser(temporary);
            File.Move(temporary, path, overwrite: true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    public void Delete(string provider) => File.Delete(PathFor(provider));
}
