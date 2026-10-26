using System.Diagnostics;

// Windows filesystem filters can briefly retain directory handles even after
// every owned worker has exited. Only retry native sharing/lock violations;
// repeated locks and every other failure must still fail the check run.
internal static class FixtureCleanup
{
    internal static async Task DeleteAsync(string path, Action<string>? delete = null,
                                          Func<TimeSpan, Task>? delay = null, bool? isWindows = null)
    {
        delete ??= directory => Directory.Delete(directory, recursive: true);
        delay ??= duration => Task.Delay(duration);
        var elapsed = Stopwatch.StartNew();
        var budget = TimeSpan.FromSeconds(3);
        for (int attempt = 0; ; attempt++)
        {
            try { delete(path); return; }
            catch (IOException error) when (IsTransientLock(error, isWindows ?? OperatingSystem.IsWindows()) && attempt < 29 && elapsed.Elapsed < budget)
            {
                var remaining = budget - elapsed.Elapsed;
                if (remaining <= TimeSpan.Zero) throw;
                await delay(remaining < TimeSpan.FromMilliseconds(100) ? remaining : TimeSpan.FromMilliseconds(100));
            }
        }
    }

    private static bool IsTransientLock(IOException error, bool isWindows) =>
        isWindows && (error.HResult & 0xffff) is 32 or 33;

    internal static async Task CheckAsync()
    {
        // Inject the Windows classification so all hosts exercise these cases;
        // the normal cleanup call always uses its real operating system.
        int calls = 0, delays = 0;
        var sharing = new IOException("synthetic sharing violation", unchecked((int)0x80070020));
        await DeleteAsync("synthetic", _ => { if (++calls < 3) throw sharing; }, _ => { delays++; return Task.CompletedTask; }, isWindows: true);
        if (calls != 3 || delays != 2) throw new Exception("Transient directory lock was not retried exactly.");
        calls = delays = 0;
        try
        {
            await DeleteAsync("synthetic", _ => { calls++; throw sharing; }, _ => { delays++; return Task.CompletedTask; }, isWindows: true);
            throw new Exception("Persistent directory lock was ignored.");
        }
        catch (IOException error) when (ReferenceEquals(error, sharing)) { }
        if (calls != 30 || delays != 29) throw new Exception("Directory lock cleanup exceeded its retry bound.");
        calls = delays = 0;
        var other = new IOException("synthetic non-lock failure", unchecked((int)0x80070005));
        try
        {
            await DeleteAsync("synthetic", _ => { calls++; throw other; }, _ => { delays++; return Task.CompletedTask; }, isWindows: true);
            throw new Exception("Non-lock cleanup failure was ignored.");
        }
        catch (IOException error) when (ReferenceEquals(error, other)) { }
        if (calls != 1 || delays != 0) throw new Exception("Non-lock cleanup failure was retried.");
    }
}
