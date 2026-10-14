Offline native bridge protocol checks
====================================

The net10.0 console project links the production BackendClient.cs and
ResourcePolicy.cs and StartupDiagnostics.cs unchanged. HostPaths/HostLog are test-only shims. It launches
fake-bridge.py with the local project Python in a temporary directory containing
Chinese characters and spaces. The subprocess imports no cyberboard modules
and accesses no USB or serial ports.

NuGet.config clears all package sources. Restore uses only the .NET SDK's
installed net10.0 reference framework; no package download is needed.

From the repository root, using .NET 10 SDK and a local project Python:

DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_GENERATE_ASPNET_CERTIFICATE=false
DOTNET_CLI_HOME=.tools/windows-build/dotnet-home
NUGET_PACKAGES=.tools/windows-build/nuget
dotnet restore windows/tests/host-bridge/HostBridge.Check.csproj --configfile windows/tests/host-bridge/NuGet.config
dotnet run --no-restore --project windows/tests/host-bridge/HostBridge.Check.csproj -- .tools/macos-build/bin/python

An external SDK path may replace dotnet; DOTNET_CLI_HOME and NUGET_PACKAGES can
point to the already prepared build cache. The Python argument must be a local
interpreter executable (python.exe on Windows).

These tests prove C# process/JSON bridge behavior and path policy execution on
the Mac build host. They do not verify Windows WebView2 UI, Windows process
launch, serial driver behavior or actual USB communication.

The startup probe is tested with absent and synthetic fixed package files in
Unicode paths. It distinguishes a managed-runtime entry from a missing package,
does not launch those files and does not access the normal user state or logs.
