"""JSON-lines test subprocess. No cyberboard import, device enumeration or USB."""
import argparse
import json
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--action", required=True)
parser.add_argument("--state-dir", required=True)
parser.add_argument("--resource-dir", required=True)
args = parser.parse_args()
payload = json.load(sys.stdin)


def emit(value):
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)


if args.action == "error":
    print("中文错误诊断：拒绝模拟操作", file=sys.stderr, flush=True)
    emit({"error": {"code": "simulated", "message": "模拟失败：没有触碰键盘"}})
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
    emit({"event": "started", "中文": "等待取消"})
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
