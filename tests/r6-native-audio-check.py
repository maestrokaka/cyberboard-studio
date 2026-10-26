#!/usr/bin/env python3
"""Compile production audio helpers against fake capture/permission handles.

No system audio enumeration, microphone permission, capture, playback, USB or
network is used. Swift is run on macOS; pass --dotnet to also exercise the
Windows recorder and the production Windows silence WAV builder offline.
"""
from pathlib import Path
import argparse
import os
import platform
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build/r6-native-audio-check"


def method(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    index = opening + 1
    while depth:
        depth += (source[index] == "{") - (source[index] == "}")
        index += 1
    return source[start:index]


SWIFT_TEST = r'''
func check(_ condition: @autoclosure () throws -> Bool, _ message: String) throws {
    if try !condition() { throw VoiceRecordingController.failure(message) }
}
func u(_ bytes: Data, _ at: Int, _ width: Int) -> Int {
    (0..<width).reduce(0) { $0 | (Int(bytes[at + $1]) << (8 * $1)) }
}
let silent = StudioAudioDevices.silence()
try check(silent.count == 192044 && u(silent, 4, 4) + 8 == silent.count, "Wrong WAV length")
try check(String(decoding: silent[0..<4], as: UTF8.self) == "RIFF" && String(decoding: silent[8..<16], as: UTF8.self) == "WAVEfmt ", "Wrong WAV header")
try check(u(silent, 20, 2) == 1 && u(silent, 22, 2) == 2 && u(silent, 24, 4) == 48000 && u(silent, 28, 4) == 192000 && u(silent, 32, 2) == 4 && u(silent, 34, 2) == 16, "Calibration must be 48k stereo PCM16")
try check(u(silent, 40, 4) == 192000 && silent.dropFirst(44).allSatisfy { $0 == 0 }, "Calibration stream must be exactly one second of silence")
print("PASS macOS production calibration WAV: one second, 48kHz stereo PCM16, all-zero samples")

func wave() -> Data {
    var data = Data("RIFF".utf8)
    func n(_ value: Int, _ count: Int) { for index in 0..<count { data.append(UInt8((value >> (8 * index)) & 255)) } }
    n(32036, 4); data.append(Data("WAVEfmt ".utf8)); n(16, 4); n(1, 2); n(1, 2)
    n(16000, 4); n(32000, 4); n(2, 2); n(16, 2); data.append(Data("data".utf8)); n(32000, 4)
    data.append(Data(repeating: 0, count: 32000)); return data
}
final class FakeCapture: VoiceCaptureHandle {
    let url: URL
    var currentTime: TimeInterval = 1
    var stops = 0, duration: TimeInterval = 0
    init(_ url: URL) { self.url = url }
    func prepareToRecord() -> Bool { true }
    func record(forDuration value: TimeInterval) -> Bool { duration = value; return true }
    func stop() { stops += 1; try! wave().write(to: url) }
}
let directory = FileManager.default.temporaryDirectory.appendingPathComponent("r6-offline-" + UUID().uuidString)
try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(at: directory) }
func empty() throws -> Bool { try FileManager.default.contentsOfDirectory(atPath: directory.path).isEmpty }
var callbacks: [(Bool) -> Void] = [], captures: [FakeCapture] = [], events: [[String: Any]] = []
var route = "expected", validates = 0, rejected = 0
let recorder = VoiceRecordingController(temporaryDirectory: directory, requestPermission: { callbacks.append($0) }, createRecorder: { url in
    let capture = FakeCapture(url); captures.append(capture); return capture
})
recorder.maximumDuration = 30
recorder.beforeRecording = { validates += 1; if route != "expected" { throw VoiceRecordingController.failure("Input changed") } }
recorder.onState = { events.append($0) }
try check(callbacks.isEmpty && captures.isEmpty && validates == 0, "Construction requested audio access")
recorder.start("route-change") { if case .failure = $0 { rejected += 1 } }
route = "other"
callbacks[0](true)
try check(validates == 1 && rejected == 1 && captures.isEmpty && recorder.requestID == nil && empty(), "Input changed during permission prompt still created a recording")
print("PASS macOS input revalidation after permission, with no capture/file on changed route")

route = "expected"
recorder.start("cancel-permission") { _ in }
recorder.cancelAll()
callbacks[1](true)
try check(validates == 1 && captures.isEmpty && empty(), "Reload/close cancellation allowed late permission to start capture")
recorder.start("at-limit") { _ in }
callbacks[2](true)
try check(captures.count == 1 && captures[0].duration == 30, "R6 test recorder did not apply native 30-second bound")
recorder.finishAtLimit("stale")
try check(captures[0].stops == 0, "Stale deadline stopped current audio")
recorder.finishAtLimit("at-limit")
try check(captures[0].stops == 1 && empty() && events.count == 1 && events[0]["reason"] as? String == "limit", "Native limit did not stop/delete/notify")
let reply = try recorder.stop("at-limit")
try check((reply["audio"] as? [String: Any])?["durationMs"] as? Int == 1000 && recorder.requestID == nil && empty(), "Limit result was lost or leaked")
print("PASS macOS native 30-second bound, stale deadline isolation, limit event and temporary-file cleanup")

recorder.start("cancel-active") { _ in }; callbacks[3](true)
recorder.cancelAll()
try check(captures[1].stops == 1 && recorder.requestID == nil && empty(), "Active cancel leaked recording")
recorder.start("denied") { _ in }; callbacks[4](false)
try check(captures.count == 2 && empty() && recorder.requestID == nil, "Denied request created audio")
print("PASS macOS cancellation and permission denial release capture and private WAV files")
'''


CS_TEST = r'''
using System.Text.Json;
using CyberboardStudio;
static class Check {
    internal static void That(bool ok,string message){if(!ok)throw new Exception(message);}
    static void Main() {
        using var wav=AudioDevices.Silence();var bytes=wav.ToArray();
        That(bytes.Length==192044&&BitConverter.ToInt32(bytes,4)+8==bytes.Length,"WAV length");
        That(System.Text.Encoding.ASCII.GetString(bytes,0,4)=="RIFF"&&System.Text.Encoding.ASCII.GetString(bytes,8,8)=="WAVEfmt ","WAV header");
        That(BitConverter.ToInt16(bytes,20)==1&&BitConverter.ToInt16(bytes,22)==2&&BitConverter.ToInt32(bytes,24)==48000&&BitConverter.ToInt32(bytes,28)==192000&&BitConverter.ToInt16(bytes,32)==4&&BitConverter.ToInt16(bytes,34)==16,"PCM format");
        That(BitConverter.ToInt32(bytes,40)==192000&&bytes.Skip(44).All(x=>x==0),"Silence samples");
        Console.WriteLine("PASS Windows production calibration WAV: one second, 48kHz stereo PCM16, all-zero samples");
        var elapsed=TimeSpan.Zero;var capture=new FakeCapture();var events=new List<JsonElement>();
        using var recorder=new VoiceRecorder(()=>capture,()=>elapsed,false,maximumSeconds:30);
        recorder.StateChanged+=value=>events.Add(JsonSerializer.SerializeToElement(value));
        recorder.Start("thirty-second-limit");elapsed=TimeSpan.FromSeconds(30);recorder.Poll();
        That(capture.Stops==1&&capture.Disposes==1&&events.Count==1&&events[0].GetProperty("reason").GetString()=="limit","Native 30s deadline");
        var audio=JsonSerializer.SerializeToElement(recorder.Stop("thirty-second-limit")).GetProperty("audio");
        That(audio.GetProperty("durationMs").GetInt32()==1000&&recorder.RequestId==null,"Limit stop result");
        var huge=new FakeCapture{Chunk=new byte[32_000*31]};using var bounded=new VoiceRecorder(()=>huge,()=>TimeSpan.Zero,false,maximumSeconds:30);
        bounded.Start("pcm-bound");bounded.Poll();
        var boundedAudio=JsonSerializer.SerializeToElement(bounded.Stop("pcm-bound")).GetProperty("audio");
        That(boundedAudio.GetProperty("durationMs").GetInt32()==30_000&&huge.Stops==1&&huge.Disposes==1,"Capture byte bound did not clamp to30s");
        Console.WriteLine("PASS Windows 30-second wall and PCM-byte bounds release fake capture and retain stop result");
        var cancelled=new FakeCapture();using var cancelling=new VoiceRecorder(()=>cancelled,()=>TimeSpan.Zero,false,maximumSeconds:30);
        cancelling.Start("cancel");cancelling.CancelAll();That(cancelled.Disposes==1&&cancelling.RequestId==null,"Cancel leaked capture");
        foreach(var value in new[]{0,61}){var rejected=false;try{using var invalid=new VoiceRecorder(maximumSeconds:value);}catch(ArgumentOutOfRangeException){rejected=true;}That(rejected,"Invalid duration accepted");}
        Console.WriteLine("PASS Windows cancellation and invalid duration protection");
    }
}
sealed class FakeCapture:IVoiceCapture {
    internal int Stops,Disposes;internal byte[] Chunk=new byte[32_000];private bool read;
    public void Start(){}
    public byte[] ReadAvailable(){if(read)return [];read=true;return Chunk;}
    public void Stop(){Stops++;}
    public void Dispose(){Disposes++;}
}
'''


def run_swift(directory):
    source = (ROOT / "native/Studio.swift").read_text()
    controller = source[source.index("protocol VoiceCaptureHandle"):source.index("struct AICredentialAccess")]
    silence = method(source, "static func silence() -> Data")
    harness = directory / "main.swift"
    harness.write_text("import Foundation\nimport AVFoundation\nenum StudioAudioDevices {\n" + silence + "\n}\n" + controller + SWIFT_TEST)
    cache = ROOT / "build/swift-module-cache"
    cache.mkdir(parents=True, exist_ok=True)
    executable = directory / "r6-audio-check"
    subprocess.run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-module-cache-path", str(cache),
                    "-framework", "AVFoundation", str(harness), "-o", str(executable)], check=True, timeout=60)
    subprocess.run([str(executable)], check=True, timeout=15)


def run_windows(directory, dotnet):
    silence = method((ROOT / "windows/src/AudioDevices.cs").read_text(), "internal static MemoryStream Silence()")
    (directory / "AudioDevices.cs").write_text("namespace CyberboardStudio;\ninternal static class AudioDevices {\n" + silence + "\n}\n")
    shutil.copy2(ROOT / "windows/src/VoiceRecorder.cs", directory / "VoiceRecorder.cs")
    (directory / "Program.cs").write_text(CS_TEST)
    (directory / "check.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
    (directory / "NuGet.config").write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    env = {**os.environ, "DOTNET_CLI_HOME": str(BUILD / "dotnet-home"), "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
           "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1", "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false"}
    subprocess.run([dotnet, "run", "--project", str(directory / "check.csproj"), "--verbosity", "quiet"], env=env, check=True, timeout=90)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dotnet", default=os.environ.get("STUDIO_TEST_DOTNET") or shutil.which("dotnet"))
    args = parser.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="offline-", dir=BUILD) as temp:
        directory = Path(temp)
        if platform.system() == "Darwin":
            run_swift(directory)
        else:
            print("SKIP macOS harness: requires Swift + AVFoundation")
        if args.dotnet:
            run_windows(directory, str(Path(args.dotnet).resolve()))
        else:
            print("SKIP Windows harness: pass --dotnet or set STUDIO_TEST_DOTNET")


if __name__ == "__main__":
    main()
