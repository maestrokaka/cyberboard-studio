#!/usr/bin/env python3
"""Import a trusted per-device CLI record offline; never open a serial port.

Development entry: windows/migrate-config.py.
Release entry: resources/backend/migrate-config.py beside bridge.py.
Only current.json and an existing meta.json are copied, with bytes and mtimes
preserved. History, operation plans, USB ports and source lock files are not
imported. CLI 0.1.2 does not emit config_sha256; when a source contains it, a
raw-file or bridge canonical-JSON SHA-256 must match before any destination edit.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import uuid
from pathlib import Path

MAX_CONFIG_BYTES = 32 * 1024 * 1024
MAX_META_BYTES = 1024 * 1024
DEVICE_RE = re.compile(r"^(?:AM01R6|CB[A-Z0-9_-]+)$")
HASH_RE = re.compile(r"^[a-fA-F0-9]{64}$")


class MigrationError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise MigrationError(message)


def load_bridge():
    directory = Path(__file__).resolve().parent
    candidates = (directory / "bridge.py", directory.parent / "backend" / "bridge.py")
    path = next((path for path in candidates if path.is_file()), None)
    require(path is not None, "后台校验组件缺失，请重新解压完整的应用文件夹。")
    spec = importlib.util.spec_from_file_location("migration_studio_bridge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_device(value):
    return isinstance(value, str) and bool(DEVICE_RE.fullmatch(value)) and "DONGLE" not in value


def reject_nonfinite(value):
    raise ValueError(f"非法 JSON 数值：{value}")


def read_source(path, maximum):
    require(path.is_file() and not path.is_symlink(), f"文件不存在或不是普通文件：{path}")
    before = path.stat()
    require(before.st_size <= maximum, f"文件过大，无法迁移：{path.name}")
    with path.open("rb") as stream:
        contents = stream.read(maximum + 1)
    after = path.stat()
    require(len(contents) <= maximum and (before.st_size, before.st_mtime_ns, before.st_ino) ==
            (after.st_size, after.st_mtime_ns, after.st_ino),
            "读取时原配置发生变化，请先关闭两端 App 和 CLI 后重试。")
    try:
        value = json.loads(contents.decode("utf-8"), parse_constant=reject_nonfinite)
    except (ValueError, UnicodeError) as error:
        raise MigrationError(f"{path.name} 不是有效的 UTF-8 JSON 文件。") from error
    require(isinstance(value, dict), f"{path.name} 需要是完整的 JSON 对象。")
    return contents, before, value


def stage_file(directory, name, contents, stat):
    staged = directory / f".{name}.{uuid.uuid4().hex}.migration.tmp"
    try:
        with staged.open("xb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.utime(staged, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        return staged
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def migrate(source, requested_device=None, *, bridge_module=None, cli=None):
    bridge = bridge_module or load_bridge()
    if cli is None:
        try:
            cli, _ = bridge.load_cli()
        except bridge.BridgeError as error:
            raise MigrationError(str(error)) from error
    source = Path(source).expanduser()
    require(not source.is_symlink(), "请选择原 CLI 设备目录或其中的 current.json 文件，不接受符号链接。")
    if source.is_file():
        require(source.name == "current.json", "请选择此前成功写入的 CLI 设备目录中的 current.json。")
        source = source.parent
    require(source.is_dir(), "原设备目录不存在，请检查路径。")
    raw, stat, config = read_source(source / "current.json", MAX_CONFIG_BYTES)
    metadata_path = source / "meta.json"
    meta_data = read_source(metadata_path, MAX_META_BYTES) if metadata_path.exists() else None
    meta = meta_data[2] if meta_data else None
    directory_device = source.name if valid_device(source.name) else None
    metadata_device = meta.get("product_id") if meta else None
    require(meta is None or valid_device(metadata_device), "meta.json 缺少有效的 CB 系列或 AM01R6 产品身份。")
    require(not directory_device or not metadata_device or directory_device == metadata_device,
            "设备目录名与 meta.json 产品身份不一致，未进行迁移。")
    device = metadata_device or directory_device
    require(device is not None, "无法确认原配置属于哪款键盘。请选择原 CLI 的设备目录并保留 meta.json。")
    require(requested_device is None or valid_device(requested_device), "--device 需要为 AM01R6 或大写 CB 系列产品 ID。")
    require(requested_device is None or requested_device == device, "指定的产品 ID 与原配置身份不一致。")
    if meta and "config_sha256" in meta:
        expected = meta["config_sha256"]
        require(isinstance(expected, str) and HASH_RE.fullmatch(expected), "原配置元数据中的 SHA-256 格式无效。")
        accepted = (hashlib.sha256(raw).hexdigest(), bridge.digest(config))
        require(expected.lower() in accepted, "原配置与 meta.json 的 SHA-256 不一致，未进行迁移。")
    try:
        plan = bridge.validate_config(config, cli)
        # A usable studio baseline must contain all three custom pages.
        for slot in (1, 2, 3):
            bridge.page_for(config, slot)
    except (bridge.BridgeError, ValueError, KeyError, TypeError, OverflowError) as error:
        raise MigrationError(f"原文件不是可安全同步的完整配置：{error}") from error

    # Only pure store path methods are used. Never call save_current,
    # record_seen, snapshot, device discovery or any serial action.
    destination = cli["cb_store"].device_dir(device)
    current = destination / "current.json"
    require(source.resolve() != destination.resolve(), "原配置目录就是当前库，无需迁移。")
    require(not current.exists(), "本机已经有这款键盘的完整配置记录。请先导出备份，本工具不会覆盖。")
    require(not destination.is_symlink(), "目标配置目录是符号链接，未进行迁移。")
    require(not (destination / ".lock").is_symlink(), "目标锁文件是符号链接，未进行迁移。")
    result = {"device": device, "directory": str(destination), "totalFrames": plan.total,
              "configSha256": hashlib.sha256(raw).hexdigest(), "usbTouched": False}
    staged, old_meta, meta_replaced = [], None, False
    destination.mkdir(parents=True, exist_ok=True)
    # Same lock file/byte protocol as CLI device_lock, without changing CLI
    # metadata. An empty directory/.lock is harmless if validation or I/O fails.
    with bridge.operation_lock(destination / ".lock"):
        require(not current.exists(), "另一进程已建立当前配置，本工具不会覆盖。")
        target_meta = destination / "meta.json"
        require(not current.is_symlink() and not target_meta.is_symlink(), "目标配置文件是符号链接，未进行迁移。")
        if target_meta.exists():
            old_meta = read_source(target_meta, MAX_META_BYTES)
            require(old_meta[2].get("product_id") == device, "已有本机元数据属于另一产品，未进行迁移。")
        try:
            new_current = stage_file(destination, "current.json", raw, stat)
            staged.append(new_current)
            new_meta = None
            if meta_data:
                new_meta = stage_file(destination, "meta.json", meta_data[0], meta_data[1])
                staged.append(new_meta)
            if new_meta:
                os.replace(new_meta, target_meta)
                meta_replaced = True
            # Commit current.json last: it is the marker for a usable baseline.
            # Both files are fully fsynced before this same-directory rename.
            os.replace(new_current, current)
        except BaseException:
            if meta_replaced:
                if old_meta:
                    restored = stage_file(destination, "meta.json", old_meta[0], old_meta[1])
                    staged.append(restored)
                    os.replace(restored, target_meta)
                else:
                    target_meta.unlink(missing_ok=True)
            raise
        finally:
            for path in staged:
                path.unlink(missing_ok=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线迁移此前成功写入同一把键盘的完整 CLI 配置记录。")
    parser.add_argument("--source", help="原 CLI 设备目录，或其中的 current.json 路径")
    parser.add_argument("--device", help="可选产品 ID 核对，例如 AM01R6、CB04；不能用于改写身份")
    args = parser.parse_args(argv)
    print("Cyberboard Studio · 迁移原配置")
    print("请使用这把键盘此前通过 CLI 成功写入后保存的设备目录。")
    print("需要 current.json，建议保留 meta.json。本工具只复制本机记录，不连接或写入 USB。")
    print("请先关闭 Cyberboard Studio 与正在运行的 CLI。历史和锁文件不会迁移。\n")
    try:
        source = args.source or input("粘贴原设备目录或 current.json 的完整路径（可带空格；空白取消）：\n> ").strip().strip('"').strip("'")
        if not source:
            print("已取消，配置未改变。")
            return 2
        result = migrate(source, args.device)
        print(f"\n迁移完成：{result['device']}")
        print(f"保存位置：{result['directory']}")
        print(f"完整配置编码检查通过：{result['totalFrames']} 个数据包。")
        print("原文件内容与时间已保留；键盘没有被写入。请重新打开 App。")
        return 0
    except (MigrationError, OSError, ValueError, TypeError, KeyError, ImportError) as error:
        print(f"\n迁移未完成：{error}", file=sys.stderr)
        print("本工具不会覆盖已有完整配置。请保留原文件，核对路径后重试。", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\n已取消，配置未改变。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
