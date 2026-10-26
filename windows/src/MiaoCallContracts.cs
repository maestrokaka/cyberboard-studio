using System.Text.Json;
using System.Text;
using System.Text.RegularExpressions;
namespace CyberboardStudio;

internal static class MiaoCallContracts
{
    public const string InstallerUrl = "https://chatgpt.com/codex/install.ps1";
    public const string InstallerCommand = "powershell -NoProfile -ExecutionPolicy Bypass -Command \"irm https://chatgpt.com/codex/install.ps1 | iex\"";
    public static string Text(JsonElement value, string key, string fallback = "") => value.ValueKind == JsonValueKind.Object && value.TryGetProperty(key,out var x) && x.ValueKind==JsonValueKind.String ? x.GetString()??fallback : fallback;
    public static bool Flag(JsonElement value,string key) => value.ValueKind==JsonValueKind.Object && value.TryGetProperty(key,out var x) && x.ValueKind==JsonValueKind.True;
    public static JsonElement Value(JsonElement value,string key) => value.ValueKind==JsonValueKind.Object && value.TryGetProperty(key,out var x) ? x.Clone() : JsonSerializer.SerializeToElement(new {});
    public static string Transcript(string value)
    {
        value=value.Trim();if(value.EnumerateRunes().Count() is <1 or >2000)throw new IOException("请填写 1–2000 字的任务。");return value;
    }
    public static bool AuthUrl(string value) => Uri.TryCreate(value,UriKind.Absolute,out var u) && u.Scheme=="https" && u.IsDefaultPort && u.UserInfo.Length==0 && (u.Host=="auth.openai.com" || u.Host=="chatgpt.com");
    public static bool TaskId(string value)=>Regex.IsMatch(value,"\\Atask-[0-9a-f]{32}\\z");
    public static readonly HashSet<string> Busy = new(StringComparer.Ordinal) {"configuring","preparing","listening","transcribing","awaitingConfirmation","connecting","thinking","acting","awaitingApproval","awaitingInput","cancelling"};
}
internal sealed class MiaoCallKeyGate
{
    internal bool Held {get;private set;}
    internal string? Consume(int scan,bool down,bool modified,bool busy)
    {
        if(scan!=0x29)return null;
        if(!down){if(!Held)return null;Held=false;return "stop";}
        if(Held)return "consume";
        if(modified)return null;
        Held=true;return busy ? "consume" : "start";
    }
    internal void Reset()=>Held=false;
}
