namespace CyberboardStudio;

internal static class ResourcePolicy
{
    public const string Host = "studio.cyberboard.invalid";
    public const string Index = "https://studio.cyberboard.invalid/index.html";
    private static readonly HashSet<string> Extensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".html", ".js", ".css", ".json", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".mp3"
    };

    public static bool IsOrigin(string value) => Uri.TryCreate(value, UriKind.Absolute, out var uri) &&
        uri.Scheme == "https" && uri.Host == Host && uri.IsDefaultPort && string.IsNullOrEmpty(uri.UserInfo);

    public static bool IsDocument(string value) => IsOrigin(value) &&
        Uri.TryCreate(value, UriKind.Absolute, out var uri) && uri.AbsolutePath == "/index.html";

    public static bool IsAsset(string value)
    {
        if (!IsOrigin(value) || !Uri.TryCreate(value, UriKind.Absolute, out var uri)) return false;
        try
        {
            var relative = Uri.UnescapeDataString(uri.AbsolutePath).TrimStart('/');
            // No Windows ADS, drive-letter paths or path separators disguised in URL escapes.
            if (relative.Contains(':') || relative.Contains('\\') || relative.Contains('\0')) return false;
            var root = Path.GetFullPath(HostPaths.Web) + Path.DirectorySeparatorChar;
            var file = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!file.StartsWith(root, StringComparison.OrdinalIgnoreCase) || !Extensions.Contains(Path.GetExtension(file))) return false;
            if (Path.GetExtension(file).Equals(".html", StringComparison.OrdinalIgnoreCase) && relative != "index.html") return false;
            return File.Exists(file);
        }
        catch (Exception exception) when (exception is ArgumentException or IOException or NotSupportedException)
        { return false; }
    }

    public static bool IsExternalLink(string value) =>
        string.Equals(value, "mailto:maestrokaka@gmail.com", StringComparison.Ordinal) ||
        (Uri.TryCreate(value, UriKind.Absolute, out var uri) &&
        (uri.Scheme is "https" or "http") && !IsOrigin(value) && string.IsNullOrEmpty(uri.UserInfo));
}
