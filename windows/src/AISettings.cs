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
    private readonly Action? beforeMetadataCommit;
    private bool lastModelMigration;
    private readonly Dictionary<string, AIConfiguration> profiles = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, string[]> Endpoints = new(StringComparer.Ordinal)
    {
        ["kimi-code"] = ["https://api.kimi.com/coding/v1", "https://api.kimi.ai/coding/v1"],
        ["kimi-open"] = ["https://api.moonshot.cn/v1", "https://api.moonshot.ai/v1"],
        ["minimax"] = ["https://api.minimax.cn/v1", "https://api.minimax.io/v1"],
        ["deepseek"] = ["https://api.deepseek.com", "https://api.deepseek.com/v1"]
    };
    private static readonly Dictionary<string, string> DefaultModels = new(StringComparer.Ordinal)
    { ["kimi-code"] = "k3", ["kimi-open"] = "kimi-k3", ["minimax"] = "MiniMax-M3", ["deepseek"] = "deepseek-flash" };
    internal static bool SupportsImages(AIConfiguration config) => config.Provider switch
    {
        "minimax" => config.Model is "MiniMax-M3" or "MiniMax-M3.1-Flash-Preview",
        "deepseek" => config.Model is "deepseek-flash" or "deepseek-v4-flash-vision-exp",
        _ => config.Provider is "kimi-code" or "kimi-open"
    };
    private static readonly Regex ModelPattern = new(@"\A[A-Za-z0-9._:-]{1,128}\z", RegexOptions.CultureInvariant);
    private static readonly Regex RequestPattern = new(@"\A[A-Za-z0-9_-]{1,80}\z", RegexOptions.CultureInvariant);

    public AISettings(string state, ICredentialVault? vault = null, Action? beforeMetadataCommit = null)
    {
        this.state = state;
        this.vault = vault ?? new LocalFileCredentialVault(Path.Combine(state, "ai-keys"));
        this.beforeMetadataCommit = beforeMetadataCommit;
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
        if (!Endpoints.TryGetValue(provider, out var endpoints)) throw new IOException("请选择受支持的模型服务。");
        var baseUrl = (Text(value, "baseUrl") ?? endpoints[0]).Trim().TrimEnd('/');
        if (!endpoints.Contains(baseUrl, StringComparer.Ordinal)) throw new IOException("API 地址必须为对应服务的官方 HTTPS 地址。");
        var model = (Text(value, "model") ?? DefaultModels[provider]).Trim();
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
            profiles[config.Provider] = config;
            File.WriteAllText(temporary, JsonSerializer.Serialize(new
            {
                provider = config.Provider, baseUrl = config.BaseUrl, model = config.Model, modelDefaultsVersion = 2,
                profilesVersion = 1, profiles = profiles.ToDictionary(p => p.Key, p => new
                { provider = p.Value.Provider, baseUrl = p.Value.BaseUrl, model = p.Value.Model })
            }, new JsonSerializerOptions { WriteIndented = true }), new UTF8Encoding(false));
            beforeMetadataCommit?.Invoke();
            File.Move(temporary, path, overwrite: true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    internal AIConfiguration LoadConfiguration()
    {
        lastModelMigration = false;
        profiles.Clear();
        var path = Path.Combine(state, "ai-settings.json");
        if (!File.Exists(path)) return Validate(JsonSerializer.SerializeToElement(new { }));
        try
        {
            if (new FileInfo(path).Length > 16384) throw new IOException();
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var value = document.RootElement;
            var config = Validate(value);
            if (value.TryGetProperty("profilesVersion", out var schema) && (!schema.TryGetInt32(out var schemaNumber) || schemaNumber != 1)) throw new IOException();
            if (value.TryGetProperty("profiles", out var stored))
            {
                if (stored.ValueKind != JsonValueKind.Object || stored.EnumerateObject().Count() > Endpoints.Count) throw new IOException();
                foreach (var item in stored.EnumerateObject())
                {
                    if (!Endpoints.ContainsKey(item.Name) || Text(item.Value, "provider") != item.Name || profiles.ContainsKey(item.Name)) throw new IOException();
                    profiles[item.Name] = Validate(item.Value);
                }
            }
            profiles[config.Provider] = config;
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

    private const string KeyReadError = "此服务的密钥无法读取，请重新输入并保存；其他服务可继续使用。";

    private object Public(AIConfiguration config, bool? hasKey, string? credentialError = null) => new
    {
        provider = config.Provider, baseUrl = config.BaseUrl, model = config.Model,
        hasKey, credentialError, credentialStore = "本机独立密钥文件", modelDefaultsVersion = 2, modelMigrated = lastModelMigration,
        supportsImages = SupportsImages(config), profiles = Endpoints.Keys.ToDictionary(provider => provider, provider =>
        {
            var profile = profiles.GetValueOrDefault(provider) ?? Validate(JsonSerializer.SerializeToElement(new { provider }));
            var item = new Dictionary<string, object?>
            { ["provider"] = provider, ["baseUrl"] = profile.BaseUrl, ["model"] = profile.Model, ["supportsImages"] = SupportsImages(profile) };
            if (provider == config.Provider)
            {
                item["hasKey"] = hasKey;
                if (credentialError is not null) item["credentialError"] = credentialError;
            }
            else
            {
                try { item["hasKey"] = !string.IsNullOrEmpty(vault.Read(provider)); }
                catch { item["hasKey"] = null; item["credentialError"] = KeyReadError; }
            }
            return item;
        })
    };

    public object Get()
    {
        lock (gate)
        {
            var config = LoadConfiguration();
            try { return Public(config, !string.IsNullOrEmpty(vault.Read(config.Provider))); }
            catch { return Public(config, null, KeyReadError); }
        }
    }

    public object RevealAIKey(JsonElement payload)
    {
        lock (gate)
        {
            var provider = Text(payload, "provider");
            if (provider is null || !Endpoints.ContainsKey(provider)) throw new IOException("请选择受支持的模型服务。");
            // Explicit local viewing returns only this provider's plain file;
            // it never switches active configuration or reads system storage.
            try { return new { apiKey = vault.Read(provider) ?? "" }; }
            catch { throw new IOException("无法读取已保存的 API Key，请重新输入并保存该服务。"); }
        }
    }

    public object Save(JsonElement payload)
    {
        lock (gate)
        {
            // Explicit saves recover invalid metadata while retaining every credential account.
            try { LoadConfiguration(); } catch { profiles.Clear(); }
            lastModelMigration = false;
            var config = Validate(payload);
            var key = Text(payload, "apiKey") ?? "";
            if (key.Contains('\r') || key.Contains('\n') || key.Length > 4096) throw new IOException("API Key 格式无效，请粘贴完整的单行密钥。");
            key = key.Trim();
            if (key.Any(c => c < 33 || c > 126)) throw new IOException("API Key 只能包含可打印的单行字符，不包含空格。");
            var remove = payload.TryGetProperty("removeKey", out var removeValue) && removeValue.ValueKind == JsonValueKind.True;
            if (remove && key.Length > 0) throw new IOException("删除密钥与设置新密钥不能同时进行。");
            // Preserve even malformed local bytes so an explicit replacement
            // can be rolled back atomically if the metadata commit fails.
            var files = vault as LocalFileCredentialVault;
            var snapshot = files?.Capture(config.Provider);
            string? previousKey;
            var unreadable = false;
            try { previousKey = vault.Read(config.Provider); }
            catch when (files is not null && (remove || key.Length > 0))
            {
                previousKey = null;
                unreadable = true;
            }
            var nextKey = remove ? null : (key.Length == 0 ? previousKey : key);
            profiles[config.Provider] = config;
            var prepared = Public(config, !string.IsNullOrEmpty(nextKey));
            var changesKey = unreadable || nextKey != previousKey;
            try
            {
                if (changesKey)
                {
                    if (nextKey is not null) vault.Write(config.Provider, nextKey);
                    else vault.Delete(config.Provider);
                }
                WriteMetadata(config);
            }
            catch
            {
                if (changesKey || files is not null)
                {
                    try
                    {
                        if (files is not null && snapshot is not null) files.Restore(config.Provider, snapshot);
                        else if (previousKey is not null) vault.Write(config.Provider, previousKey);
                        else vault.Delete(config.Provider);
                    }
                    catch { throw new IOException("模型配置未切换，但密钥恢复失败，当前密钥状态无法确认。请检查本机存储后重新保存该服务。"); }
                }
                throw new IOException("模型配置未保存，原配置和密钥已保留。请检查本机存储后重试。");
            }
            return prepared;
        }
    }

    public (JsonElement Payload, string Secret) Inject(JsonElement payload, bool allowInactive = false)
    {
        lock (gate)
        {
            var active = LoadConfiguration();
            var provider = Text(payload, "provider") ?? active.Provider;
            if (!Endpoints.ContainsKey(provider)) throw new IOException("请选择受支持的模型服务。");
            if (!allowInactive && provider != active.Provider) throw new IOException("当前模型配置已切换，请刷新后重新制作。");
            var config = provider == active.Provider ? active : profiles.GetValueOrDefault(provider) ?? Validate(JsonSerializer.SerializeToElement(new { provider }));
            string? secret;
            try { secret = vault.Read(config.Provider); }
            catch { throw new IOException(KeyReadError); }
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

internal sealed record LocalKeySnapshot(bool Exists, byte[] Bytes);

internal sealed class LocalFileCredentialVault(string directory, Action? beforeCommit = null) : ICredentialVault
{
    private static readonly UTF8Encoding Utf8 = new(false, true);

    private string PathFor(string provider)
    {
        if (provider is not ("kimi-code" or "kimi-open" or "minimax" or "deepseek")) throw new IOException("未知密钥服务。");
        return Path.Combine(directory, provider + ".key");
    }

    internal LocalKeySnapshot Capture(string provider)
    {
        var path = PathFor(provider);
        try
        {
            if (new FileInfo(path).Length > 65536) throw new IOException("密钥文件过大，请检查本机文件后重新保存。");
            return new(true, File.ReadAllBytes(path));
        }
        catch (FileNotFoundException) { return new(false, []); }
        catch (DirectoryNotFoundException) { return new(false, []); }
    }

    private void Commit(string provider, byte[] bytes)
    {
        var path = PathFor(provider);
        Directory.CreateDirectory(directory);
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllBytes(temporary, bytes);
            beforeCommit?.Invoke();
            File.Move(temporary, path, overwrite: true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    internal void Restore(string provider, LocalKeySnapshot snapshot)
    {
        var current = Capture(provider);
        if (current.Exists == snapshot.Exists && current.Bytes.SequenceEqual(snapshot.Bytes)) return;
        if (snapshot.Exists) Commit(provider, snapshot.Bytes);
        else File.Delete(PathFor(provider));
    }

    private static string? Key(string value)
    {
        if (value.Length == 0) return null;
        if (value.Length > 4096 || value.Any(c => c < 33 || c > 126)) throw new IOException("密钥文件格式无效，请重新输入并保存该服务。");
        return value;
    }

    public string? Read(string provider)
    {
        var snapshot = Capture(provider);
        if (snapshot.Exists)
        {
            if (snapshot.Bytes.Length > 4096) throw new IOException("密钥文件格式无效，请重新输入并保存该服务。");
            try { return Key(Utf8.GetString(snapshot.Bytes)); }
            catch (DecoderFallbackException) { throw new IOException("密钥文件格式无效，请重新输入并保存该服务。"); }
        }
        return null;
    }

    public void Write(string provider, string key)
    {
        if (Key(key) is null) throw new IOException("API Key 不能为空。");
        Commit(provider, Utf8.GetBytes(key));
    }

    // Empty files are explicit removals and remain absent after a restart.
    public void Delete(string provider) => Commit(provider, []);
}
