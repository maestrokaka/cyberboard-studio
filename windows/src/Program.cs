using System.Runtime.CompilerServices;

namespace CyberboardStudio;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        var diagnostic = args.Length == 1 && args[0] == "--diagnostic-startup";
        try
        {
            // This branch loads only the managed runtime and reads fixed package
            // file names. It never constructs the UI, credentials or CLI bridge.
            if (diagnostic) return StartupDiagnostics.Run(AppContext.BaseDirectory);
            StartupDiagnostics.Stage("main-entered");
            return RunDesktop();
        }
        catch (Exception exception)
        {
            if (diagnostic) Console.Error.WriteLine("Managed startup probe failed: " + exception.GetType().Name + ": " + exception.Message);
            else ShowFailure(exception);
            return 1;
        }
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int RunDesktop()
    {
        StartupDiagnostics.Stage("winforms-initializing");
        Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (_, args) => ShowFailure(args.Exception);
        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
        {
            if (args.ExceptionObject is Exception exception) HostLog.Write("unhandled", exception.ToString());
        };

        using var instance = new Mutex(true, @"Local\CyberboardStudioDesktop", out var firstInstance);
        if (!firstInstance)
        {
            MessageBox.Show("Cyberboard Studio 已经在运行。请使用已打开的窗口。", "Cyberboard Studio",
                MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 0;
        }
        using var form = new StudioForm();
        StartupDiagnostics.Stage("window-created");
        Application.Run(form);
        return 0;
    }

    private static void ShowFailure(Exception exception)
    {
        HostLog.Write("host", exception.ToString());
        Console.Error.WriteLine("Desktop startup/application failure: " + exception.GetType().Name + ": " + exception.Message);
        MessageBox.Show("应用遇到错误：\n" + exception.Message, "Cyberboard Studio",
            MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
}

internal static class HostPaths
{
    public static string Resources => Path.Combine(AppContext.BaseDirectory, "resources");
    public static string Web => Path.Combine(Resources, "web");
    public static string State => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Cyberboard Studio");
    public static string Profile => Path.Combine(State, "WebView2");
    public static string Python => Path.Combine(Resources, "python", "python.exe");
    public static string Backend => Path.Combine(Resources, "backend", "bridge.py");
}

internal static class HostLog
{
    private static readonly object Gate = new();
    public static void Write(string category, string message)
    {
        try
        {
            lock (Gate)
            {
                var directory = Path.Combine(HostPaths.State, "logs");
                Directory.CreateDirectory(directory);
                var path = Path.Combine(directory, "host.log");
                if (File.Exists(path) && new FileInfo(path).Length > 1024 * 1024)
                    File.Move(path, path + ".previous", true);
                File.AppendAllText(path, $"[{DateTimeOffset.Now:O}] {category}: {message}\n");
            }
        }
        catch { /* Diagnostics must never interrupt a USB operation. */ }
    }
}
