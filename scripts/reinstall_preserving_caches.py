#!/usr/bin/env python3
"""Reinstall the plugin without breaking tasks pinned to older runtime caches."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from check_installation import tree_digest


PLUGIN_NAME = "subagent-governance"
PLUGIN_SPEC = f"{PLUGIN_NAME}@personal"


def ordinary_directory(path: Path, label: str, *, create: bool = False) -> None:
    if create and not path.exists():
        path.mkdir(parents=True)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"{label} 必须是普通目录且不能是符号链接：{path}")


def cache_directories(cache_parent: Path) -> list[Path]:
    caches: list[Path] = []
    for entry in sorted(cache_parent.iterdir(), key=lambda path: path.name):
        if entry.is_symlink() or not entry.is_dir():
            raise RuntimeError(f"缓存父目录中存在不安全条目：{entry}")
        tree_digest(entry)
        caches.append(entry)
    return caches


def restore_snapshot(snapshot: Path, cache_parent: Path) -> list[str]:
    restored: list[str] = []
    for source in sorted(snapshot.iterdir(), key=lambda path: path.name):
        ordinary_directory(source, "缓存快照")
        target = cache_parent / source.name
        if target.exists() or target.is_symlink():
            ordinary_directory(target, "重装后的同名缓存")
            if tree_digest(source) != tree_digest(target):
                raise RuntimeError(f"缓存恢复发生同名内容冲突，快照已保留：{target}")
            continue
        shutil.move(str(source), str(target))
        restored.append(source.name)
    return restored


def recover_stale_snapshots(snapshot_parent: Path, cache_parent: Path) -> list[str]:
    recovered: list[str] = []
    for snapshot in sorted(snapshot_parent.iterdir(), key=lambda path: path.name):
        ordinary_directory(snapshot, "遗留缓存快照")
        recovered.extend(restore_snapshot(snapshot, cache_parent))
        shutil.rmtree(snapshot)
    return recovered


def reinstall(
    cache_parent: Path,
    snapshot_parent: Path,
    command: list[str],
    *,
    runner=None,
) -> tuple[int, dict[str, object]]:
    ordinary_directory(cache_parent, "插件缓存父目录")
    ordinary_directory(snapshot_parent, "缓存快照父目录", create=True)
    recovered = recover_stale_snapshots(snapshot_parent, cache_parent)
    snapshot = snapshot_parent / f"rollover-{os.getpid()}-{uuid.uuid4().hex}"
    snapshot.mkdir()
    caches = cache_directories(cache_parent)
    preserved = [path.name for path in caches]
    for cache in caches:
        shutil.copytree(cache, snapshot / cache.name, copy_function=shutil.copy2)

    run_command = runner or subprocess.run
    command_error: str | None = None
    returncode = 2
    try:
        result = run_command(command, check=False)
        returncode = int(result.returncode)
    except OSError as exc:
        command_error = str(exc)
    restored = restore_snapshot(snapshot, cache_parent)
    shutil.rmtree(snapshot)

    report: dict[str, object] = {
        "command": command,
        "returncode": returncode,
        "preserved_caches": preserved,
        "restored_caches": restored,
        "recovered_stale_caches": recovered,
        "snapshot_parent": str(snapshot_parent),
    }
    if command_error:
        report["command_error"] = command_error
    return returncode, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-spec", default=PLUGIN_SPEC)
    parser.add_argument("--codex-command", default="codex")
    parser.add_argument(
        "--cache-parent",
        type=Path,
        default=Path.home() / ".codex/plugins/cache/personal" / PLUGIN_NAME,
    )
    parser.add_argument(
        "--snapshot-parent",
        type=Path,
        default=Path.home() / ".codex/plugin-cache-rollover" / PLUGIN_NAME,
    )
    args = parser.parse_args()
    try:
        returncode, report = reinstall(
            args.cache_parent.expanduser().absolute(),
            args.snapshot_parent.expanduser().absolute(),
            [args.codex_command, "plugin", "add", args.plugin_spec],
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
