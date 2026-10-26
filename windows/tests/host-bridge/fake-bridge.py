"""JSON-lines test subprocess. No cyberboard import, device enumeration or USB."""
import argparse
import os
import json
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--action", required=True)
parser.add_argument("--state-dir", required=True)
parser.add_argument("--resource-dir", required=True)
args = parser.parse_args()
if args.action == "miaoCallWorker":
    payload=json.loads(sys.stdin.readline())
    def stream(value):print(json.dumps(value),flush=True)
    if payload.get("mode") == "malformed-live":
        stream({"event":"miaoCall","workerPid":os.getpid()})
        print("{broken JSON",flush=True)
        time.sleep(60)
    elif payload.get("mode") == "malformed":
        print("{broken JSON", flush=True)
        stream({"result": {"ok": True}})
    elif payload.get("mode") == "nonzero":
        stream({"result": {"ok": True}})
        raise SystemExit(7)
    elif payload.get("mode") == "partial":
        print(json.dumps({"result": {"ok": True}}), end="", flush=True)
    elif payload.get("mode") == "duplicate":
        stream({"result": {"ok": True}})
        stream({"result": {"ok": True}})
    elif payload.get("mode") == "after-final":
        stream({"result": {"ok": True}})
        stream({"event": "miaoCall", "type": "state", "state": "thinking"})
    elif payload.get("mode") == "unknown":
        stream({"unrecognized": "fixture"})
        stream({"result": {"ok": True}})
    elif payload.get("mode")=="child":
        import subprocess
        child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        stream({"result":{"ok":True,"status":"completed","childPid":child.pid}})
    else:
        stream({"event":"miaoCall","type":"request","request":{"id":"request-1","kind":"approval"}})
        message=json.loads(sys.stdin.readline())
        if payload.get("mode")=="cancel":
            assert message["type"]=="cancel"
            stream({"result":{"ok":False,"status":"cancelled"}})
        else:
            assert message["type"]=="approval" and message["decision"]=="accept"
            stream({"result":{"ok":True,"status":"completed","text":"fixture"}})
    raise SystemExit(0)
payload = json.load(sys.stdin)


def emit(value):
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)


if args.action == "error":
    print("中文错误诊断：拒绝模拟操作", file=sys.stderr, flush=True)
    emit({"error": {"code": "simulated", "message": "模拟失败：没有触碰键盘"}})
elif args.action == "error-value":
    # Exercise failures from the production process/JSON parser, including
    # malformed payloads and hostile AI echoes, without opening real devices.
    print("模拟诊断：" + str(payload.get("diagnostic", "无敏感内容")), file=sys.stderr, flush=True)
    emit({"error": payload.get("error")})
elif args.action == "malformed":
    print("{broken JSON", flush=True)
    emit({"result": {"ok": True}})
elif args.action == "wrong-record":
    emit(["not an object"])
    emit({"result": {"ok": True}})
elif args.action == "exit":
    emit({"result": {"ok": True}})
    sys.exit(7)
elif args.action == "empty":
    sys.exit(0)
elif args.action == "cancel":
    emit({"event": "started", "中文": "等待取消", "workerPid": os.getpid()})
    time.sleep(120)
    emit({"result": {"unexpected": True}})
else:
    start = time.monotonic_ns()
    emit({"event": "progress", "current": 1, "label": "顶部屏幕"})
    emit({"type": "event", "current": 2, "label": "轴灯"})
    if args.action == "queue":
        time.sleep(0.18)
    if args.action == "diagnostic-tail":
        print("前缀" + "诊断" * 40000 + "保留结尾", file=sys.stderr, flush=True)
    else:
        print("中文 stderr：只是模拟消息", file=sys.stderr, flush=True)
    emit({"result": {"message": "测试成功：中文与路径", "payload": payload,
        "action": args.action, "state": args.state_dir, "resource": args.resource_dir,
        "start": start, "end": time.monotonic_ns()}})
