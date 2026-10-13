namespace CyberboardStudio;

internal static class HostPaths
{
    public static string Resources { get; set; } = "";
    public static string Web => Path.Combine(Resources, "web");
    public static string State { get; set; } = "";
    public static string Python { get; set; } = "";
    public static string Backend => Path.Combine(Resources, "backend", "假桥接.py");
}

internal static class HostLog
{
    private static readonly object Gate = new();
    public static readonly List<(string Category, string Message)> Messages = new();
    public static void Write(string category, string message)
    {
        lock (Gate) Messages.Add((category, message));
    }
}
