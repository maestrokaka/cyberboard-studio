"""Local MiaoCall task records, distinct from lighting workspaces and credentials."""
from __future__ import annotations
import json
import os
import re
import time
import uuid
from pathlib import Path
from speech_input import atomic

ID = re.compile(r"task-[0-9a-f]{32}\Z")
MAX_RECORD = 1024 * 1024


class TaskStoreError(ValueError):
    pass


def require(value, message):
    if not value:
        raise TaskStoreError(message)


class TaskStore:
    def __init__(self, root):
        self.root = Path(root)
        self.folder = self.root / "agent-tasks"
        self.settings_file = self.root / "agent-task-settings.json"

    def _read(self, path, default=None):
        if not path.exists():
            return default
        require(path.is_file() and path.stat().st_size <= MAX_RECORD, "任务记录无法读取，请保留原文件并联系作者。")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise TaskStoreError("任务记录无法读取，请保留原文件并联系作者。") from None

    def path(self, identity):
        require(isinstance(identity, str) and ID.fullmatch(identity), "任务编号无效。")
        return self.folder / (identity + ".json")

    def context(self, payload=None):
        value = self._read(self.settings_file, {})
        require(isinstance(value, dict), "任务设置无法读取，请重新选择工作目录。")
        cwd = value.get("cwd") or str(self.root / "MiaoCallWorkspace")
        path = Path(cwd)
        if not value.get("cwd"):
            path.mkdir(parents=True, exist_ok=True)
        require(path.is_absolute() and path.is_dir(), "工作目录已不存在，请重新选择。")
        mode = value.get("mode", "read-only")
        require(mode in {"read-only", "workspace-write"}, "请选择有效的任务权限。")
        return {"cwd": str(path.resolve()), "mode": mode, "model": value.get("model") or None}

    def configure(self, payload):
        old = self.context()
        cwd = payload.get("cwd", old["cwd"])
        require(isinstance(cwd, str) and len(cwd) <= 4096, "请选择有效的工作目录。")
        path = Path(cwd)
        require(path.is_absolute() and path.is_dir(), "请选择存在的工作目录。")
        mode = payload.get("mode", old["mode"])
        require(mode in {"read-only", "workspace-write"}, "请选择有效的任务权限。")
        model = payload.get("model", old["model"])
        require(model is None or isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", model), "模型名称无效。")
        value = {"cwd": str(path.resolve()), "mode": mode, "model": model}
        atomic(self.settings_file, json.dumps(value, ensure_ascii=False).encode())
        return value

    def get(self, payload):
        identity = payload.get("taskId") if isinstance(payload, dict) else payload
        value = self._read(self.path(identity))
        require(isinstance(value, dict) and value.get("id") == identity, "任务记录不存在。")
        require(isinstance(value.get("cwd"), str) and isinstance(value.get("messages"), list) and isinstance(value.get("status"), str), "任务记录格式无效，请保留原文件。")
        return value

    def save(self, record):
        raw = json.dumps(record, ensure_ascii=False).encode()
        require(len(raw) <= MAX_RECORD, "任务记录已达到上限，请新建任务继续，原记录保留。")
        atomic(self.path(record["id"]), raw)
        return record

    def create(self, text):
        records = [self.get(p.stem) for p in self.folder.glob("task-*.json")]
        require(len(records) < 200, "最多保留 200 个任务，请导出后删除不需要的归档记录。")
        require(sum(not r.get("archived") for r in records) < 50, "最多保留 50 个未归档任务，请先归档记录。")
        context = self.context()
        now = time.time()
        return self.save({"id": "task-" + uuid.uuid4().hex, "title": text[:60], **context,
                          "createdAt": now, "updatedAt": now, "threadId": None, "status": "idle",
                          "archived": False, "messages": [], "steps": [], "artifacts": []})

    def begin(self, identity, text):
        record = self.get(identity) if identity else self.create(text)
        require(not record.get("archived"), "请先恢复归档任务。")
        require(len(record.get("messages", [])) < 60, "此任务已达到 30 轮上限，请新建任务继续，原记录保留。")
        require(Path(record["cwd"]).is_dir(), "任务工作目录已不存在，请先恢复目录。")
        record["messages"].append({"role": "user", "text": text, "at": time.time()})
        record.update(status="running", workerPid=os.getpid(), updatedAt=time.time(), steps=[], result="")
        return self.save(record)

    def list(self, payload=None):
        payload = payload or {}
        active = payload.get("activeTaskId")
        records = []
        for path in self.folder.glob("task-*.json"):
            try:
                r = self.get(path.stem)
                # A fresh host has no managed worker. Never leave an abandoned
                # operation looking as if it is still running after a restart.
                if r["status"] == "running" and r["id"] != active and not self.worker_alive(r):
                    r["status"] = "interrupted"
                    r["message"] = "上次任务连接已结束，可以检查结果后继续。"
                    self.save(r)
                records.append({key: r.get(key) for key in
                                ("id", "title", "cwd", "mode", "status", "archived", "updatedAt", "message")})
            except TaskStoreError:
                records.append({"id": path.stem, "title": "无法读取的任务记录", "status": "error", "archived": False})
        return {"tasks": sorted(records, key=lambda r: r.get("updatedAt") or 0, reverse=True), "context": self.context()}

    @staticmethod
    def worker_alive(record):
        pid = record.get("workerPid")
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def diagnostics(self, payload=None):
        import platform
        import subprocess
        from miao_call import find_cli, MiaoCallError
        report = {"feature": "MiaoCall Tasks Beta 3", "platform": platform.system(),
                  "taskStore": "ready", "scope": "no keys, paths, task text or account information"}
        try:
            cli = find_cli()
            version = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=8, check=True).stdout.strip()
            report["codexVersion"] = version[:100]
        except (MiaoCallError, OSError, subprocess.SubprocessError):
            report["codexVersion"] = "unavailable"
        try:
            records = self.list()["tasks"]
            report["tasks"] = {s: sum(r["status"] == s for r in records) for s in ("running", "completed", "error", "interrupted", "cancelled")}
            report["defaultPermission"] = self.context()["mode"]
        except (TaskStoreError, OSError):
            report["taskStore"] = "needs attention"
        return report

    def delete(self, payload):
        record = self.get(payload)
        require(record.get("archived") and record["status"] != "running", "仅可删除已归档且停止的任务记录。")
        self.path(record["id"]).unlink()
        return {"deleted": True}

    def archive(self, payload):
        record = self.get(payload)
        require(record["status"] != "running", "请先停止当前任务，再归档记录。")
        record["archived"] = payload.get("archived", True) is True
        self.save(record)
        return {"task": record}

    def reveal(self, payload):
        record = self.get(payload) if payload.get("taskId") else self.context()
        root = Path(record["cwd"]).resolve()
        target = payload.get("path") or str(root)
        require(isinstance(target, str), "文件位置无效。")
        path = Path(target).resolve()
        require(path == root or path.is_relative_to(root), "只能定位此任务工作目录中的文件。")
        require(path.exists(), "文件已不存在。")
        return {"path": str(path)}

    def export(self, payload):
        record = self.get(payload)
        return {"json": record, "fileName": record["id"] + ".json"}
