#!/usr/bin/env python3
"""Reinstall the plugin while protecting only the actual previous cache."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Iterator

from check_installation import manifest_version, tree_digest


PLUGIN_NAME = "subagent-governance"
DEFAULT_MARKETPLACE = "subagent-governance"
SNAPSHOT_PREFIX = "rollover-"
SNAPSHOT_MANIFEST = "snapshot-manifest.json"
SNAPSHOT_CACHE_DIRECTORY = "cache"
TRANSACTION_FILE = "last-transaction.json"
LOCK_FILE = ".reinstall.lock"


def plugin_spec(marketplace: str) -> str:
    value = marketplace.strip()
    if not value or any(character in value for character in "@/\\"):
        raise ValueError(f"Marketplace 名称无效：{marketplace!r}")
    return f"{PLUGIN_NAME}@{value}"


def default_cache_parent(marketplace: str) -> Path:
    return Path.home() / ".codex/plugins/cache" / marketplace / PLUGIN_NAME


def _owned_by_current_user(metadata: os.stat_result) -> bool:
    getuid = getattr(os, "getuid", None)
    return getuid is None or getattr(metadata, "st_uid", getuid()) == getuid()


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ordinary_directory(path: Path, label: str, *, create: bool = False) -> None:
    if create and not path.exists():
        path.mkdir(parents=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"{label} 必须是普通目录且不能是符号链接：{path}")
    metadata = path.stat()
    if not _owned_by_current_user(metadata):
        raise PermissionError(f"{label} 必须由当前用户拥有：{path}")
    if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o022:
        raise PermissionError(f"{label} 不能允许组用户或其他用户写入：{path}")


def require_same_filesystem(cache_parent: Path, snapshot_parent: Path) -> None:
    if cache_parent.stat().st_dev != snapshot_parent.stat().st_dev:
        raise RuntimeError(
            "插件缓存父目录与缓存快照父目录必须位于同一文件系统："
            f"{cache_parent}；{snapshot_parent}"
        )


def validate_version_name(version: str, label: str) -> str:
    value = version.strip()
    if not value or value in {".", ".."} or Path(value).name != value:
        raise ValueError(f"{label} 必须是单个非空版本目录名：{version!r}")
    return value


def cache_directories(cache_parent: Path) -> list[Path]:
    caches: list[Path] = []
    for entry in sorted(cache_parent.iterdir(), key=lambda path: path.name):
        ordinary_directory(entry, "版本化缓存")
        tree_digest(entry)
        caches.append(entry)
    return caches


def select_previous_cache(
    caches: list[Path],
    previous_version: str | None,
) -> Path | None:
    if not caches:
        if previous_version is not None:
            raise RuntimeError(
                f"指定了升级前版本 {previous_version}，但插件缓存目录为空"
            )
        return None
    if previous_version is None:
        raise RuntimeError(
            "发现已有版本缓存；必须通过 --previous-version 传入升级前实际 installed/current 版本，"
            "不能按目录名或时间排序猜测上一版本"
        )
    expected = validate_version_name(previous_version, "升级前版本")
    matches = [cache for cache in caches if cache.name == expected]
    if not matches:
        raise RuntimeError(f"升级前版本缓存不存在：{expected}")
    return matches[0]


def retention_candidates(
    cache_parent: Path,
    target_version: str,
    previous_version: str | None,
) -> list[str]:
    retained = {validate_version_name(target_version, "目标版本")}
    if previous_version is not None:
        retained.add(validate_version_name(previous_version, "升级前版本"))
    return [
        path.name
        for path in cache_directories(cache_parent)
        if path.name not in retained
    ]


def write_json_atomic(path: Path, value: dict[str, object]) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError(f"事务记录必须是普通文件且不能是符号链接：{path}")
    if path.exists():
        metadata = path.stat()
        if not _owned_by_current_user(metadata):
            raise PermissionError(f"事务记录必须由当前用户拥有：{path}")
        if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o022:
            raise PermissionError(f"事务记录不能允许组用户或其他用户写入：{path}")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


@contextmanager
def operation_lock(snapshot_parent: Path) -> Iterator[Path]:
    lock_path = snapshot_parent / LOCK_FILE
    try:
        descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(
            f"检测到未释放的重装事务锁：{lock_path}；"
            "请先确认没有重装进程仍在运行并检查最后事务记录"
        ) from exc
    try:
        payload = json.dumps(
            {"pid": os.getpid(), "created_at": utc_now()},
            ensure_ascii=False,
            sort_keys=True,
        )
        os.write(descriptor, payload.encode("utf-8"))
        os.fsync(descriptor)
        yield lock_path
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def snapshot_cache_root(snapshot: Path) -> Path:
    manifest_path = snapshot / SNAPSHOT_MANIFEST
    structured_cache = snapshot / SNAPSHOT_CACHE_DIRECTORY
    if manifest_path.is_file():
        ordinary_directory(structured_cache, "缓存快照内容")
        return structured_cache
    if structured_cache.exists() or structured_cache.is_symlink():
        raise RuntimeError(f"缓存快照不完整，缺少完成 manifest：{snapshot}")
    return snapshot


def restore_snapshot(snapshot: Path, cache_parent: Path) -> list[str]:
    restored: list[str] = []
    cache_root = snapshot_cache_root(snapshot)
    for source in sorted(cache_root.iterdir(), key=lambda path: path.name):
        ordinary_directory(source, "缓存快照")
        target = cache_parent / source.name
        if target.exists() or target.is_symlink():
            ordinary_directory(target, "重装后的同名缓存")
            if tree_digest(source) != tree_digest(target):
                raise RuntimeError(
                    "缓存恢复发生同名内容冲突；"
                    f"快照已保留在：{snapshot}；冲突目标：{target}"
                )
            continue
        shutil.move(str(source), str(target))
        restored.append(source.name)
    return restored


def recover_stale_snapshots(snapshot_parent: Path, cache_parent: Path) -> list[str]:
    recovered: list[str] = []
    snapshots = [
        path
        for path in sorted(snapshot_parent.iterdir(), key=lambda path: path.name)
        if path.name.startswith(SNAPSHOT_PREFIX)
    ]
    for snapshot in snapshots:
        ordinary_directory(snapshot, "遗留缓存快照")
        recovered.extend(restore_snapshot(snapshot, cache_parent))
        shutil.rmtree(snapshot)
    return recovered


def reinstall(
    cache_parent: Path,
    snapshot_parent: Path,
    command: list[str],
    *,
    previous_version: str | None = None,
    target_version: str,
    transaction_file: Path | None = None,
    runner=None,
) -> tuple[int, dict[str, object]]:
    ordinary_directory(cache_parent, "插件缓存父目录")
    ordinary_directory(snapshot_parent, "缓存快照父目录", create=True)
    require_same_filesystem(cache_parent, snapshot_parent)
    target_version = validate_version_name(target_version, "目标版本")
    transaction_path = transaction_file or snapshot_parent / TRANSACTION_FILE
    transaction_path = transaction_path.absolute()
    if transaction_path.parent != snapshot_parent.absolute():
        raise RuntimeError(f"事务记录必须直接位于缓存快照父目录：{transaction_path}")

    with operation_lock(snapshot_parent):
        recovered = recover_stale_snapshots(snapshot_parent, cache_parent)
        caches = cache_directories(cache_parent)
        previous_cache = select_previous_cache(caches, previous_version)
        if previous_cache is not None and previous_cache.name == target_version:
            raise RuntimeError("目标版本必须不同于升级前实际版本")

        transaction_id = f"{SNAPSHOT_PREFIX}{os.getpid()}-{uuid.uuid4().hex}"
        snapshot = snapshot_parent / transaction_id
        snapshot.mkdir(mode=0o700)
        snapshot_caches = snapshot / SNAPSHOT_CACHE_DIRECTORY
        snapshot_caches.mkdir(mode=0o700)
        preserved = [] if previous_cache is None else [previous_cache.name]
        transaction: dict[str, object] = {
            "command": command,
            "created_at": utc_now(),
            "previous_version": previous_cache.name if previous_cache else None,
            "preserved_caches": preserved,
            "recovered_stale_caches": recovered,
            "snapshot_id": transaction_id,
            "snapshot_path": str(snapshot),
            "state": "snapshot_started",
            "target_version": target_version,
            "transaction_file": str(transaction_path),
            "transaction_id": transaction_id,
        }
        write_json_atomic(transaction_path, transaction)
        try:
            if previous_cache is not None:
                shutil.copytree(
                    previous_cache,
                    snapshot_caches / previous_cache.name,
                    copy_function=shutil.copy2,
                )
            snapshot_manifest = {
                "completed_at": utc_now(),
                "previous_version": previous_cache.name if previous_cache else None,
                "preserved_caches": preserved,
                "transaction_id": transaction_id,
            }
            write_json_atomic(snapshot / SNAPSHOT_MANIFEST, snapshot_manifest)
        except Exception as exc:
            transaction.update(
                state="snapshot_failed",
                failed_stage="snapshot",
                error=str(exc),
                updated_at=utc_now(),
            )
            write_json_atomic(transaction_path, transaction)
            raise RuntimeError(
                f"缓存快照阶段失败，未完成快照保留在：{snapshot}；原因：{exc}"
            ) from exc

        transaction.update(state="snapshot_complete", updated_at=utc_now())
        write_json_atomic(transaction_path, transaction)
        run_command = runner or subprocess.run
        command_error: str | None = None
        unexpected_error: Exception | None = None
        returncode = 2
        try:
            result = run_command(command, check=False)
            returncode = int(result.returncode)
        except OSError as exc:
            command_error = str(exc)
        except Exception as exc:  # Restore N-1 before preserving the original failure.
            unexpected_error = exc

        failed_stage: str | None = "codex_command" if returncode != 0 else None
        if returncode == 0 and not (cache_parent / target_version).is_dir():
            returncode = 2
            failed_stage = "post_install_cache"
            command_error = f"原生命令返回成功，但目标缓存不存在：{cache_parent / target_version}"

        try:
            restored = restore_snapshot(snapshot, cache_parent)
        except Exception as exc:
            transaction.update(
                state="cache_restore_failed",
                failed_stage="cache_restore",
                error=str(exc),
                updated_at=utc_now(),
            )
            write_json_atomic(transaction_path, transaction)
            raise RuntimeError(
                f"缓存恢复阶段失败，快照保留在：{snapshot}；原因：{exc}"
            ) from exc

        try:
            shutil.rmtree(snapshot)
        except OSError as exc:
            transaction.update(
                state="snapshot_cleanup_failed",
                failed_stage="snapshot_cleanup",
                error=str(exc),
                updated_at=utc_now(),
            )
            write_json_atomic(transaction_path, transaction)
            raise RuntimeError(
                f"缓存已经恢复，但快照清理失败：{snapshot}；原因：{exc}"
            ) from exc

        cleanup_candidates = retention_candidates(
            cache_parent,
            target_version,
            previous_cache.name if previous_cache else None,
        )
        if unexpected_error is not None:
            transaction.update(
                state="command_exception_previous_restored",
                failed_stage="codex_command",
                error=str(unexpected_error),
                restored_caches=restored,
                cleanup_candidates=cleanup_candidates,
                retention_cleanup_allowed=False,
                updated_at=utc_now(),
            )
            write_json_atomic(transaction_path, transaction)
            raise unexpected_error

        state = (
            "reinstall_succeeded_pending_acceptance"
            if returncode == 0
            else "reinstall_failed_previous_restored"
        )
        transaction.update(
            state=state,
            returncode=returncode,
            failed_stage=failed_stage,
            restored_caches=restored,
            cleanup_candidates=cleanup_candidates,
            retention_cleanup_allowed=False,
            updated_at=utc_now(),
        )
        if command_error:
            transaction["command_error"] = command_error
        write_json_atomic(transaction_path, transaction)
        return returncode, transaction


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--marketplace", default=DEFAULT_MARKETPLACE)
    parser.add_argument("--plugin-spec")
    parser.add_argument("--codex-command", default="codex")
    parser.add_argument(
        "--cache-parent",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--snapshot-parent",
        type=Path,
        default=Path.home() / ".codex/plugin-cache-rollover" / PLUGIN_NAME,
    )
    parser.add_argument(
        "--previous-version",
        help="重装前通过 Codex installed/current 状态确认的实际版本；已有缓存时必填",
    )
    parser.add_argument(
        "--target-version",
        help="目标完整 Manifest version；默认读取当前稳定脚本所在插件目录",
    )
    args = parser.parse_args()
    stable_root = Path(__file__).resolve().parents[1]
    try:
        resolved_plugin_spec = args.plugin_spec or plugin_spec(args.marketplace)
        resolved_cache_parent = args.cache_parent or default_cache_parent(args.marketplace)
        target_version = args.target_version or manifest_version(stable_root)
        returncode, report = reinstall(
            resolved_cache_parent.expanduser().absolute(),
            args.snapshot_parent.expanduser().absolute(),
            [args.codex_command, "plugin", "add", resolved_plugin_spec],
            previous_version=args.previous_version,
            target_version=target_version,
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
