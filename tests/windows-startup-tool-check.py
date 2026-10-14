"""Offline source-contract checks; these do not execute Windows or prove startup."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "windows/diagnose-startup.cmd"


class StartupToolChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = TOOL.read_bytes()
        cls.source = cls.raw.decode("utf-8")
        start = cls.source.index("powershell.exe -NoLogo")
        cls.command_lines = cls.source[start:].splitlines()
        cls.command_lines = cls.command_lines[:next(
            i for i, line in enumerate(cls.command_lines) if not line.endswith("^")) + 1]
        cls.command = " ".join(line.removesuffix("^").strip() for line in cls.command_lines)
        cls.script = " ".join(re.findall(r'^\s*"([^"\r\n]*)"\s*\^?$',
                                          "\n".join(cls.command_lines[1:]), re.M))

    def test_portable_command_and_windows_encoding(self):
        self.assertIn(b"\r\n", self.raw)
        self.assertNotIn(b"\n", self.raw.replace(b"\r\n", b""))
        self.assertLess(len(self.command), 8191, "cmd.exe command length limit")
        self.assertIn('setlocal EnableExtensions DisableDelayedExpansion', self.source)
        self.assertIn('cd /d "%~dp0"', self.source)
        self.assertIn('set "CB_STUDIO_DIAG_ROOT=%~dp0"', self.source)
        self.assertIn("$root=$env:CB_STUDIO_DIAG_ROOT", self.script)
        self.assertIn("FilePath=$exe; WorkingDirectory=$root", self.script)
        self.assertIn("Join-Path $root 'Cyberboard Studio.exe'", self.script)
        self.assertIn("-NoProfile -NonInteractive -Command", self.command)
        self.assertNotRegex(self.source, r"(?i)(EncodedCommand|ExecutionPolicy|runas|Bypass)")
        self.assertNotIn("/Users/", self.source)

    def test_fixed_os_and_package_scope(self):
        self.assertIn("HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", self.script)
        for field in ("ProductName", "DisplayVersion", "CurrentBuildNumber", "UBR", "EditionID"):
            self.assertIn("'" + field + "'", self.script)
        self.assertIn("[Environment]::Is64BitOperatingSystem", self.script)
        self.assertIn("$env:PROCESSOR_ARCHITEW6432", self.script)
        self.assertIn("$env:PROCESSOR_ARCHITECTURE", self.script)
        for name in ("Cyberboard Studio.exe", "Cyberboard Studio.dll", "coreclr.dll",
                     "hostfxr.dll", "hostpolicy.dll", "WebView2Loader.dll"):
            self.assertIn("'" + name + "'", self.script)
        self.assertIn("Get-FileHash -LiteralPath $path -Algorithm SHA256", self.script)
        # Read operations are fixed metadata, package hashes, and a public manifest.
        self.assertEqual(re.findall(r"Get-Content\s+-LiteralPath\s+(\$\w+)", self.script), ["$manifest"])
        for forbidden in ("Get-ChildItem", "Get-WinEvent", "Get-EventLog", "Get-CimInstance",
                          "GetEnvironmentVariables", "$env:USERNAME", "$env:COMPUTERNAME",
                          "$env:USERPROFILE", "Invoke-WebRequest", "Invoke-RestMethod",
                          "Set-ItemProperty", "Remove-Item", "Stop-Process", "process.Kill"):
            self.assertNotIn(forbidden, self.script)
        self.assertNotRegex(self.script, r"(?i)(cyberboard\.cli|--execute|\bdetect\b|apiKey|DPAPI)")

    def test_unique_reports_and_transient_host_tracing(self):
        self.assertIn("Join-Path $env:TEMP $leaf", self.script)
        self.assertIn("[Guid]::NewGuid().ToString('N')", self.script)
        self.assertIn("New-Item -ItemType Directory -Path $report", self.script)
        self.assertNotIn("-Force", self.script)
        for prefix in ("DOTNET_HOST", "COREHOST"):
            self.assertIn(f"$env:{prefix}_TRACE='1'", self.script)
            self.assertIn(f"$env:{prefix}_TRACEFILE=$trace", self.script)
            self.assertIn(f"$env:{prefix}_TRACE_VERBOSITY='4'", self.script)
        for suffix in ("-host-trace.log", "-stdout.txt", "-stderr.txt"):
            self.assertIn("$label+'" + suffix + "'", self.script)
        self.assertIn("RedirectStandardOutput=$out; RedirectStandardError=$err", self.script)
        self.assertIn("summary.txt", self.script)

    def test_legacy_compatibility_and_bounded_process_wait(self):
        self.assertIn("($metadata.diagnosticStartup -is [bool]) -and $metadata.diagnosticStartup", self.script)
        self.assertIn("if ($probe) { $probeStatus=Launch 'probe' @('--diagnostic-startup')", self.script)
        self.assertIn("if ($probeStatus -eq 'exited-success') { $null=Launch 'app' @() } else", self.script)
        self.assertIn("Normal app startup skipped", self.script)
        self.assertRegex(self.script, r"Legacy package:.*?\$null=Launch 'app' @\(\) }")
        self.assertIn("$process.WaitForExit(15000)", self.script)
        self.assertIn("$null=$process.Handle", self.script)
        self.assertLess(self.script.index("$null=$process.Handle"),
                        self.script.index("$process.WaitForExit(15000)"))
        self.assertIn("$rawCode=$process.ExitCode", self.script)
        self.assertIn("if ($null -eq $rawCode)", self.script)
        self.assertIn("$launchStatus='unknown-exit'", self.script)
        self.assertIn("exit code could not be obtained", self.script)
        self.assertNotIn("[int]$process.ExitCode", self.script)
        self.assertLess(self.script.index("if ($null -eq $rawCode)"),
                        self.script.index("$code=[int]$rawCode"))
        self.assertIn("if ($code -eq 0) { $launchStatus='exited-success' } else", self.script)
        self.assertIn("return $launchStatus", self.script)
        self.assertIn("[BitConverter]::GetBytes($code)", self.script)
        self.assertIn("[ComponentModel.Win32Exception]", self.script)
        self.assertIn("NativeErrorCode", self.script)
        self.assertIn("Startup result is undetermined", self.script)
        self.assertIn("The process has been left running", self.script)
        self.assertIn("GUI/WebView2/USB are not verified", self.script)
        self.assertIn("does not certify Windows compatibility", self.script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
