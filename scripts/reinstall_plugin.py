#!/usr/bin/env python3
"""Install the current plugin with transaction-scoped failure rollback."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

try:
    from scripts.check_installation import manifest_version, tree_digest
except ModuleNotFoundError:
    from check_installation import manifest_version, tree_digest


if os.name == "nt":
    import msvcrt

    fcntl = None
else:
    import fcntl

    msvcrt = None


PLUGIN_NAME = "subagent-governance"
DEFAULT_MARKETPLACE = "subagent-governance"
TRANSACTION_PREFIX = "transaction-"
SNAPSHOT_MANIFEST = "snapshot-manifest.json"
SNAPSHOT_CACHE_DIRECTORY = "cache"
TRANSACTION_FILE = "last-transaction.json"
LOCK_FILE = ".install.lock"


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
            "插件缓存父目录与事务快照父目录必须位于同一文件系统："
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
        ordinary_directory(entry, "插件缓存")
        tree_digest(entry)
        caches.append(entry)
    return caches


def select_current_cache(caches: list[Path]) -> Path | None:
    if len(caches) > 1:
        names = ", ".join(cache.name for cache in caches)
        raise RuntimeError(f"检测到多个插件缓存，当前安装只允许一个：{names}")
    return caches[0] if caches else None


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
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def operation_lock(snapshot_parent: Path) -> Iterator[Path]:
    lock_path = snapshot_parent / LOCK_FILE
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise RuntimeError(f"安装事务锁无法安全打开：{lock_path}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"安装事务锁必须是普通文件：{lock_path}")
        if not _owned_by_current_user(metadata):
            raise PermissionError(f"安装事务锁必须由当前用户拥有：{lock_path}")
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(f"已有安装事务正在运行：{lock_path}") from exc
        else:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if metadata.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError(f"已有安装事务正在运行：{lock_path}") from exc
        yield lock_path
    finally:
        try:
            if os.name != "nt":
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            else:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        os.close(descriptor)


def read_snapshot_manifest(snapshot: Path) -> dict[str, object]:
    manifest_path = snapshot / SNAPSHOT_MANIFEST
    cache_root = snapshot / SNAPSHOT_CACHE_DIRECTORY
    if not manifest_path.is_file() or not cache_root.is_dir():
        raise RuntimeError(f"事务快照不完整：{snapshot}")
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"事务快照 manifest 无法读取：{manifest_path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"事务快照 manifest 必须是对象：{manifest_path}")
    current_cache = value.get("current_cache")
    if current_cache is not None:
        validate_version_name(str(current_cache), "快照 current_cache")
        digest = value.get("current_cache_digest")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise RuntimeError(f"事务快照缺少有效 current_cache_digest：{manifest_path}")
    validate_version_name(str(value.get("target_version") or ""), "快照 target_version")
    return value


def remove_cache(path: Path) -> None:
    ordinary_directory(path, "待删除插件缓存")
    tree_digest(path)
    shutil.rmtree(path)


def restore_snapshot(snapshot: Path, cache_parent: Path) -> str | None:
    manifest = read_snapshot_manifest(snapshot)
    current_name = manifest.get("current_cache")
    source: Path | None = None
    if current_name is not None:
        source = snapshot / SNAPSHOT_CACHE_DIRECTORY / str(current_name)
        ordinary_directory(source, "事务快照缓存")
        if tree_digest(source) != manifest["current_cache_digest"]:
            raise RuntimeError(f"事务快照缓存摘要不匹配：{source}")
    for cache in cache_directories(cache_parent):
        remove_cache(cache)
    if current_name is None:
        return None
    assert source is not None
    target = cache_parent / str(current_name)
    shutil.move(str(source), str(target))
    return str(current_name)


def recover_interrupted_transaction(
    snapshot_parent: Path, cache_parent: Path
) -> str | None:
    transactions = [
        path
        for path in sorted(snapshot_parent.iterdir(), key=lambda path: path.name)
        if path.name.startswith(TRANSACTION_PREFIX)
    ]
    if len(transactions) > 1:
        names = ", ".join(path.name for path in transactions)
        raise RuntimeError(f"检测到多个未完成安装事务，无法确定恢复顺序：{names}")
    if not transactions:
        return None
    snapshot = transactions[0]
    ordinary_directory(snapshot, "未完成事务快照")
    restored = restore_snapshot(snapshot, cache_parent)
    shutil.rmtree(snapshot)
    return restored


def install(
    cache_parent: Path,
    snapshot_parent: Path,
    command: list[str],
    *,
    target_version: str,
    transaction_file: Path | None = None,
    runner=None,
) -> tuple[int, dict[str, object]]:
    ordinary_directory(cache_parent, "插件缓存父目录")
    ordinary_directory(snapshot_parent, "事务快照父目录", create=True)
    require_same_filesystem(cache_parent, snapshot_parent)
    target_version = validate_version_name(target_version, "目标版本")
    transaction_path = (transaction_file or snapshot_parent / TRANSACTION_FILE).absolute()
    if transaction_path.parent != snapshot_parent.absolute():
        raise RuntimeError(f"事务记录必须直接位于事务快照父目录：{transaction_path}")

    with operation_lock(snapshot_parent):
        recovered_cache = recover_interrupted_transaction(
            snapshot_parent, cache_parent
        )
        current_cache = select_current_cache(cache_directories(cache_parent))
        transaction_id = f"{TRANSACTION_PREFIX}{os.getpid()}-{uuid.uuid4().hex}"
        snapshot = snapshot_parent / transaction_id
        snapshot.mkdir(mode=0o700)
        snapshot_caches = snapshot / SNAPSHOT_CACHE_DIRECTORY
        snapshot_caches.mkdir(mode=0o700)
        transaction: dict[str, object] = {
            "command": command,
            "created_at": utc_now(),
            "current_cache": current_cache.name if current_cache else None,
            "recovered_interrupted_cache": recovered_cache,
            "snapshot_id": transaction_id,
            "snapshot_path": str(snapshot),
            "state": "snapshot_started",
            "target_version": target_version,
            "transaction_file": str(transaction_path),
            "transaction_id": transaction_id,
        }
        write_json_atomic(transaction_path, transaction)
        try:
            current_cache_digest: str | None = None
            if current_cache is not None:
                shutil.copytree(
                    current_cache,
                    snapshot_caches / current_cache.name,
                    copy_function=shutil.copy2,
                )
                current_cache_digest = tree_digest(
                    snapshot_caches / current_cache.name
                )
            write_json_atomic(
                snapshot / SNAPSHOT_MANIFEST,
                {
                    "completed_at": utc_now(),
                    "current_cache": current_cache.name if current_cache else None,
                    "current_cache_digest": current_cache_digest,
                    "target_version": target_version,
                    "transaction_id": transaction_id,
                },
            )
        except Exception as exc:
            transaction.update(
                state="snapshot_failed",
                failed_stage="snapshot",
                error=str(exc),
                updated_at=utc_now(),
            )
            write_json_atomic(transaction_path, transaction)
            raise RuntimeError(
                f"事务快照阶段失败，未完成快照保留在：{snapshot}；原因：{exc}"
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
        except Exception as exc:
            unexpected_error = exc

        failed_stage: str | None = "codex_command" if returncode != 0 else None
        target_cache = cache_parent / target_version
        if returncode == 0 and not target_cache.is_dir():
            returncode = 2
            failed_stage = "post_install_cache"
            command_error = f"原生命令返回成功，但目标缓存不存在：{target_cache}"

        restored_cache: str | None = None
        removed_cache_entries: list[str] = []
        if returncode == 0:
            for cache in cache_directories(cache_parent):
                if cache != target_cache:
                    removed_cache_entries.append(cache.name)
                    remove_cache(cache)
        else:
            try:
                restored_cache = restore_snapshot(snapshot, cache_parent)
            except Exception as exc:
                transaction.update(
                    state="rollback_failed",
                    failed_stage="rollback",
                    error=str(exc),
                    updated_at=utc_now(),
                )
                write_json_atomic(transaction_path, transaction)
                raise RuntimeError(
                    f"安装失败且事务回滚失败，快照保留在：{snapshot}；原因：{exc}"
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
            raise RuntimeError(f"事务快照清理失败：{snapshot}；原因：{exc}") from exc

        if unexpected_error is not None:
            transaction.update(
                state="command_exception_rolled_back",
                failed_stage="codex_command",
                error=str(unexpected_error),
                restored_cache=restored_cache,
                updated_at=utc_now(),
            )
            write_json_atomic(transaction_path, transaction)
            raise unexpected_error

        transaction.update(
            state="install_succeeded" if returncode == 0 else "install_failed_rolled_back",
            returncode=returncode,
            failed_stage=failed_stage,
            restored_cache=restored_cache,
            removed_cache_entries=removed_cache_entries,
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
    parser.add_argument("--cache-parent", type=Path, default=None)
    parser.add_argument(
        "--snapshot-parent",
        type=Path,
        default=Path.home() / ".codex/plugin-install-transactions" / PLUGIN_NAME,
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
        returncode, report = install(
            resolved_cache_parent.expanduser().absolute(),
            args.snapshot_parent.expanduser().absolute(),
            [args.codex_command, "plugin", "add", resolved_plugin_spec],
            target_version=target_version,
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
