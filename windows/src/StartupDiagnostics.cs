using System.Runtime.InteropServices;
using System.Text.Json;

namespace CyberboardStudio;

internal static class StartupDiagnostics
{
    internal static readonly string[] RequiredFiles =
    {
        "Cyberboard Studio.dll", "hostfxr.dll", "hostpolicy.dll", "coreclr.dll",
        "WebView2Loader.dll", "resources/web/index.html", "resources/python/python.exe"
    };

    internal static Dictionary<string, bool> PackageFiles(string baseDirectory) => RequiredFiles.ToDictionary(
        name => name, name => File.Exists(Path.Combine(baseDirectory, name.Replace('/', Path.DirectorySeparatorChar))));

    internal static int Run(string baseDirectory)
    {
        var files = PackageFiles(baseDirectory);
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            phase = "managed-runtime-started",
            version = typeof(StartupDiagnostics).Assembly.GetName().Version?.ToString(3),
            runtime = RuntimeInformation.FrameworkDescription,
            processArchitecture = RuntimeInformation.ProcessArchitecture.ToString(),
            operatingSystem = Environment.OSVersion.VersionString,
            packageFiles = files,
            uiStarted = false,
            credentialsRead = false,
            usbAccessed = false
        }));
        return files.Values.All(present => present) ? 0 : 2;
    }

    internal static void Stage(string stage)
    {
        // Fixed startup milestones are safe to include in a fresh diagnostic
        // capture; never serialize settings, requests or user workspace data.
        Console.WriteLine("Cyberboard Studio startup: " + stage);
        HostLog.Write("startup", stage);
    }
}
