Offline native bridge protocol checks
====================================

The net10.0 console project links the production BackendClient.cs and
ResourcePolicy.cs unchanged. HostPaths/HostLog are test-only shims. It launches
fake-bridge.py with the local project Python in a temporary directory containing
Chinese characters and spaces. The subprocess imports no cyberboard modules
and accesses no USB or serial ports.

NuGet.config clears all package sources. Restore uses only the .NET SDK's
installed net10.0 reference framework; no package download is needed.

From the project root, using the already prepared private .NET SDK:

DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_GENERATE_ASPNET_CERTIFICATE=false
DOTNET_CLI_HOME=.tools/windows-build/dotnet-home
NUGET_PACKAGES=.tools/windows-build/nuget
.tools/windows-build/dotnet/dotnet restore cyberboard-studio/windows/tests/host-bridge/HostBridge.Check.csproj --configfile cyberboard-studio/windows/tests/host-bridge/NuGet.config
.tools/windows-build/dotnet/dotnet run --no-restore --project cyberboard-studio/windows/tests/host-bridge/HostBridge.Check.csproj -- .tools/cyberboard-cli/bin/python

These tests prove C# process/JSON bridge behavior and path policy execution on
the Mac build host. They do not verify Windows WebView2 UI, Windows process
launch, serial driver behavior or actual USB communication.
