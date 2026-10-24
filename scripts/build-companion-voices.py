#!/usr/bin/env python3
"""Explicit, bounded generation of the fixed companion phrases. No personal voice cloning."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from speech_input import SpeechSettings

parser = argparse.ArgumentParser()
parser.add_argument("--state-dir", type=Path, required=True)
parser.add_argument("--generate", action="store_true")
args = parser.parse_args()
catalog = json.loads((ROOT / "web/assets/companion/catalog.json").read_text())
jobs = [(voice, zone) for voice in catalog["voices"] for zone in catalog["zones"]]
if not args.generate:
    print(json.dumps({"plannedRequests": len(jobs), "requiresExplicitGenerate": True})); raise SystemExit(0)
settings = SpeechSettings(args.state_dir)
key = settings.key("minimax-asr")
if not key: raise SystemExit("A saved MiniMax voice key is required.")
region = settings.get()["profiles"]["minimax-asr"]["region"]
endpoint = "https://api.minimax.cn/v1/t2a_v2" if region == "china" else "https://api.minimax.io/v1/t2a_v2"

def generate(job):
    voice, zone = job
    path = ROOT / f"web/assets/companion/audio/{voice['id']}/{zone['id']}.mp3"
    if path.exists(): return {"voice": voice["id"], "zone": zone["id"], "ok": True, "reused": True}
    time.sleep(5.1)
    payload = {"model": "speech-2.8-turbo", "text": zone["text"], "stream": False,
               "language_boost": "Chinese", "output_format": "hex",
               "voice_setting": {"voice_id": voice["voiceId"], "speed": voice["speed"], "vol": 1, "pitch": voice["pitch"]},
               "audio_setting": {"sample_rate": 24000, "bitrate": 64000, "format": "mp3", "channel": 1}}
    try:
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(),
                                         headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=45) as response: raw = response.read(2_000_001)
        if len(raw) > 2_000_000: raise ValueError()
        reply = json.loads(raw)
        code = reply.get("base_resp", {}).get("status_code")
        if code != 0: return {"voice": voice["id"], "zone": zone["id"], "ok": False, "statusCode": code}
        audio = bytes.fromhex(reply["data"]["audio"])
        if not (1000 <= len(audio) <= 500_000): raise ValueError()
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(audio)
        return {"voice": voice["id"], "zone": zone["id"], "ok": True, "bytes": len(audio)}
    except Exception as error:
        return {"voice": voice["id"], "zone": zone["id"], "ok": False, "exception": type(error).__name__}

with ThreadPoolExecutor(max_workers=1) as pool: results = list(pool.map(generate, jobs))
report = {"provider": "MiniMax official system voices", "cloning": False, "results": results,
          "passed": sum(item["ok"] for item in results), "total": len(results)}
folder = ROOT / "build/companion-private-20261024"; folder.mkdir(parents=True, exist_ok=True)
(folder / "voice-generation.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: report[k] for k in ("provider", "cloning", "passed", "total")}))
if report["passed"] != report["total"]: raise SystemExit(1)
