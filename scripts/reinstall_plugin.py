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


def ordinary_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} 必须是普通文件且不能是符号链接：{path}")
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


def select_previous_cache(
    caches: list[Path], previous_version: str | None
) -> Path | None:
    """Validate the operator-provided installed/current cache identity.

    Cache names are not an ordering mechanism.  When caches exist, the exact
    registered version observed in `codex plugin list` must be supplied.
    """
    if not caches:
        if previous_version is not None:
            raise RuntimeError(
                f"指定了升级前版本 {previous_version}，但插件缓存目录为空"
            )
        return None
    if previous_version is None:
        raise RuntimeError(
            "发现已有插件缓存；必须通过 --previous-version 传入从 "
            "codex plugin list 确认的实际 installed/current 版本，"
            "不能按目录名或时间排序猜测当前版本"
        )
    expected = validate_version_name(previous_version, "升级前版本")
    for cache in caches:
        if cache.name == expected:
            return cache
    raise RuntimeError(f"升级前版本缓存不存在：{expected}")


def cache_entries(caches: list[Path]) -> list[dict[str, str]]:
    return [{"name": cache.name, "digest": tree_digest(cache)} for cache in caches]


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
    if not manifest_path.exists() or not cache_root.exists():
        raise RuntimeError(f"事务快照不完整：{snapshot}")
    ordinary_file(manifest_path, "事务快照 manifest")
    ordinary_directory(cache_root, "事务快照缓存根目录")
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"事务快照 manifest 无法读取：{manifest_path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"事务快照 manifest 必须是对象：{manifest_path}")
    entries = value.get("pre_install_caches")
    if not isinstance(entries, list):
        raise RuntimeError(f"事务快照缺少完整 pre_install_caches：{manifest_path}")
    names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError(f"事务快照缓存条目必须是对象：{manifest_path}")
        name = entry.get("name")
        digest = entry.get("digest")
        if not isinstance(name, str):
            raise RuntimeError(f"事务快照缓存条目缺少名称：{manifest_path}")
        validate_version_name(name, "快照缓存版本")
        if name in names:
            raise RuntimeError(f"事务快照缓存版本重复：{manifest_path}")
        names.add(name)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise RuntimeError(f"事务快照缓存条目缺少有效摘要：{manifest_path}")
    previous_version = value.get("previous_version")
    if previous_version is not None:
        if not isinstance(previous_version, str):
            raise RuntimeError(f"事务快照 previous_version 无效：{manifest_path}")
        validate_version_name(previous_version, "快照升级前版本")
        if previous_version not in names:
            raise RuntimeError(f"事务快照 previous_version 不在缓存集合中：{manifest_path}")
    validate_version_name(str(value.get("target_version") or ""), "快照 target_version")
    snapshot_names = [cache.name for cache in cache_directories(cache_root)]
    if snapshot_names != sorted(names):
        raise RuntimeError(f"事务快照缓存集合与 manifest 不一致：{manifest_path}")
    return value


def remove_cache(path: Path) -> None:
    ordinary_directory(path, "待删除插件缓存")
    tree_digest(path)
    shutil.rmtree(path)


def restore_snapshot(snapshot: Path, cache_parent: Path) -> list[str]:
    manifest = read_snapshot_manifest(snapshot)
    entries = manifest["pre_install_caches"]
    assert isinstance(entries, list)
    sources: list[tuple[Path, str]] = []
    for entry in entries:
        assert isinstance(entry, dict)
        name = str(entry["name"])
        source = snapshot / SNAPSHOT_CACHE_DIRECTORY / name
        ordinary_directory(source, "事务快照缓存")
        if tree_digest(source) != entry["digest"]:
            raise RuntimeError(f"事务快照缓存摘要不匹配：{source}")
        sources.append((source, name))
    for cache in cache_directories(cache_parent):
        remove_cache(cache)
    restored: list[str] = []
    for source, name in sources:
        target = cache_parent / name
        shutil.copytree(source, target, copy_function=shutil.copy2)
        expected_digest = next(
            str(entry["digest"])
            for entry in entries
            if isinstance(entry, dict) and entry["name"] == name
        )
        if tree_digest(target) != expected_digest:
            raise RuntimeError(f"已恢复插件缓存摘要不匹配：{target}")
        restored.append(name)
    return restored


def snapshot_cache_entry(snapshot: Path, version: str) -> dict[str, object]:
    """Return the exact cache fact recorded before the native add command."""
    manifest = read_snapshot_manifest(snapshot)
    entries = manifest["pre_install_caches"]
    assert isinstance(entries, list)
    for entry in entries:
        assert isinstance(entry, dict)
        if entry["name"] == version:
            return entry
    raise RuntimeError(f"事务快照中缺少升级前版本缓存：{version}")


def verified_snapshot_cache(snapshot: Path, version: str) -> tuple[Path, dict[str, object]]:
    entry = snapshot_cache_entry(snapshot, version)
    source = snapshot / SNAPSHOT_CACHE_DIRECTORY / version
    ordinary_directory(source, "事务快照缓存")
    if tree_digest(source) != entry["digest"]:
        raise RuntimeError(f"事务快照缓存摘要不匹配：{source}")
    return source, entry


def restore_previous_cache(
    snapshot: Path, cache_parent: Path, previous_version: str | None
) -> tuple[Path | None, bool, str | None]:
    """Restore or verify the precise registered/current cache from the snapshot.

    The native command may delete every old cache.  Only the operator-provided
    previous identity is retained; no directory ordering is used to infer it.
    """
    if previous_version is None:
        return None, False, None
    source, entry = verified_snapshot_cache(snapshot, previous_version)
    expected_digest = str(entry["digest"])

    target = cache_parent / previous_version
    restored = False
    if target.exists() or target.is_symlink():
        ordinary_directory(target, "升级前插件缓存")
        if tree_digest(target) != expected_digest:
            raise RuntimeError(f"升级前插件缓存摘要在原生命令后发生变化：{target}")
    else:
        shutil.copytree(source, target, copy_function=shutil.copy2)
        restored = True

    ordinary_directory(target, "恢复后的升级前插件缓存")
    if manifest_version(target) != previous_version:
        raise RuntimeError(f"升级前插件缓存 Manifest version 不匹配：{target}")
    if tree_digest(target) != expected_digest:
        raise RuntimeError(f"恢复后的升级前插件缓存摘要不匹配：{target}")
    return target, restored, expected_digest


def recover_interrupted_transaction(
    snapshot_parent: Path, cache_parent: Path
) -> list[str]:
    transactions = [
        path
        for path in sorted(snapshot_parent.iterdir(), key=lambda path: path.name)
        if path.name.startswith(TRANSACTION_PREFIX)
    ]
    if len(transactions) > 1:
        names = ", ".join(path.name for path in transactions)
        raise RuntimeError(f"检测到多个未完成安装事务，无法确定恢复顺序：{names}")
    if not transactions:
        return []
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
    previous_version: str | None = None,
    target_version: str,
    confirm_previous_sessions_restarted: bool = False,
    source_root: Path | None = None,
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

    stable_source = (
        source_root or Path(__file__).resolve().parents[1]
    ).expanduser().absolute()

    with operation_lock(snapshot_parent):
        recovered_caches = recover_interrupted_transaction(
            snapshot_parent, cache_parent
        )
        caches = cache_directories(cache_parent)
        previous_cache = select_previous_cache(caches, previous_version)
        if previous_cache is not None and previous_cache.name == target_version:
            raise RuntimeError("目标版本必须不同于升级前实际版本")
        if len(caches) > 1 and not confirm_previous_sessions_restarted:
            raise RuntimeError(
                "安装前已有 retained previous compatibility cache；必须显式传入 "
                "--confirm-previous-sessions-restarted，确认依赖更早版本的会话已重启或关闭"
            )
        pre_install_caches = cache_entries(caches)
        ordinary_directory(stable_source, "稳定测试源")
        if manifest_version(stable_source) != target_version:
            raise RuntimeError("目标版本必须与稳定测试源 Manifest version 精确一致")
        if previous_cache is not None and manifest_version(previous_cache) != previous_cache.name:
            raise RuntimeError("升级前插件缓存 Manifest version 必须与目录名一致")
        expected_stable_tree_digest = tree_digest(stable_source)
        transaction_id = f"{TRANSACTION_PREFIX}{os.getpid()}-{uuid.uuid4().hex}"
        snapshot = snapshot_parent / transaction_id
        snapshot.mkdir(mode=0o700)
        snapshot_caches = snapshot / SNAPSHOT_CACHE_DIRECTORY
        snapshot_caches.mkdir(mode=0o700)
        transaction: dict[str, object] = {
            "actual_stable_tree_digest": None,
            "actual_target_tree_digest": None,
            "created_at": utc_now(),
            "expected_stable_tree_digest": expected_stable_tree_digest,
            "pre_install_caches": pre_install_caches,
            "previous_version": previous_cache.name if previous_cache else None,
            "previous_cache_restored": False,
            "recovered_interrupted_caches": recovered_caches,
            "retained_previous_cache": None,
            "retained_previous_digest": None,
            "retained_previous_version": previous_cache.name if previous_cache else None,
            "snapshot_id": transaction_id,
            "snapshot_path": str(snapshot),
            "state": "snapshot_started",
            "stable_source_path": str(stable_source),
            "target_version": target_version,
            "transaction_file": str(transaction_path),
            "transaction_id": transaction_id,
        }
        write_json_atomic(transaction_path, transaction)
        try:
            for cache in caches:
                shutil.copytree(
                    cache,
                    snapshot_caches / cache.name,
                    copy_function=shutil.copy2,
                )
                snapshot_digest = tree_digest(snapshot_caches / cache.name)
                expected_digest = next(
                    entry["digest"]
                    for entry in pre_install_caches
                    if entry["name"] == cache.name
                )
                if snapshot_digest != expected_digest:
                    raise RuntimeError(
                        f"事务快照缓存摘要不匹配：{snapshot_caches / cache.name}"
                    )
            write_json_atomic(
                snapshot / SNAPSHOT_MANIFEST,
                {
                    "completed_at": utc_now(),
                    "pre_install_caches": pre_install_caches,
                    "previous_version": previous_cache.name if previous_cache else None,
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
        failed_stage: str | None = None
        try:
            ordinary_directory(stable_source, "稳定测试源")
            source_digest_before_command = tree_digest(stable_source)
            transaction["stable_tree_digest_before_command"] = source_digest_before_command
            if source_digest_before_command != expected_stable_tree_digest:
                command_error = "稳定测试源在事务快照后发生变化"
                failed_stage = "source_pre_command"
        except Exception as exc:
            command_error = f"调用原生命令前稳定测试源无效：{stable_source}；原因：{exc}"
            failed_stage = "source_pre_command"
        if failed_stage is None:
            try:
                if previous_cache is not None:
                    _, previous_snapshot_entry = verified_snapshot_cache(
                        snapshot, previous_cache.name
                    )
                    if tree_digest(previous_cache) != previous_snapshot_entry["digest"]:
                        raise RuntimeError("升级前插件缓存摘要在调用原生命令前发生变化")
                result = run_command(command, check=False)
                returncode = int(result.returncode)
                if returncode != 0:
                    failed_stage = "codex_command"
            except OSError as exc:
                command_error = str(exc)
                failed_stage = "codex_command"
            except Exception as exc:
                unexpected_error = exc
                failed_stage = "codex_command"

        write_json_atomic(transaction_path, transaction)
        target_cache = cache_parent / target_version
        target_valid = False
        if returncode == 0:
            try:
                retained_previous, previous_restored, previous_digest = restore_previous_cache(
                    snapshot, cache_parent, previous_cache.name if previous_cache else None
                )
                transaction.update(
                    retained_previous_cache=(str(retained_previous) if retained_previous else None),
                    previous_cache_restored=previous_restored,
                    retained_previous_digest=previous_digest,
                )
            except Exception as exc:
                returncode = 2
                failed_stage = "restore_previous"
                command_error = f"升级前缓存恢复或复核失败：{exc}"
        if returncode == 0:
            verification_errors: list[str] = []
            actual_target_version: str | None = None
            try:
                ordinary_directory(target_cache, "目标插件缓存")
                transaction["actual_target_tree_digest"] = tree_digest(target_cache)
                actual_target_version = manifest_version(target_cache)
            except Exception as exc:
                verification_errors.append(f"目标缓存无效：{target_cache}；原因：{exc}")
            try:
                ordinary_directory(stable_source, "稳定测试源")
                transaction["actual_stable_tree_digest"] = tree_digest(stable_source)
            except Exception as exc:
                verification_errors.append(f"稳定测试源无效：{stable_source}；原因：{exc}")
            actual_target_digest = transaction["actual_target_tree_digest"]
            actual_stable_digest = transaction["actual_stable_tree_digest"]
            if actual_target_version != target_version:
                verification_errors.append("目标缓存 Manifest version 与目标版本不一致")
            if actual_stable_digest != expected_stable_tree_digest:
                verification_errors.append("稳定测试源在原生命令期间发生变化")
            if actual_target_digest != expected_stable_tree_digest:
                verification_errors.append("目标缓存 tree digest 与稳定测试源不一致")
            if not verification_errors:
                target_valid = True
            else:
                command_error = "原生命令返回成功，但安装后验证失败：" + "；".join(
                    verification_errors
                )
        if returncode == 0 and not target_valid:
            returncode = 2
            failed_stage = "post_install_verification"

        restored_caches: list[str] = []
        removed_cache_entries: list[str] = []
        if returncode == 0:
            try:
                keep = {target_version}
                if previous_cache is not None:
                    keep.add(previous_cache.name)
                for cache in cache_directories(cache_parent):
                    if cache.name not in keep:
                        remove_cache(cache)
                remaining = cache_directories(cache_parent)
                if {cache.name for cache in remaining} != keep or len(remaining) != len(keep):
                    raise RuntimeError("安装后缓存收敛未精确保留目标和升级前版本")
                removed_cache_entries = [
                    str(entry["name"])
                    for entry in pre_install_caches
                    if entry["name"] not in keep
                ]
            except Exception as exc:
                returncode = 2
                failed_stage = "cleanup"
                command_error = f"安装后缓存收敛失败：{exc}"
        else:
            pass
        if returncode != 0:
            try:
                restored_caches = restore_snapshot(snapshot, cache_parent)
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
                restored_caches=restored_caches,
                updated_at=utc_now(),
            )
            write_json_atomic(transaction_path, transaction)
            raise unexpected_error

        transaction.update(
            state="install_succeeded" if returncode == 0 else "install_failed_rolled_back",
            returncode=returncode,
            failed_stage=failed_stage,
            restored_caches=restored_caches,
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
    parser.add_argument(
        "--previous-version",
        help="安装前从 codex plugin list 确认的实际 installed/current 完整版本；已有 cache 时必填",
    )
    parser.add_argument(
        "--confirm-previous-sessions-restarted",
        action="store_true",
        help="已有 compatibility cache 时，确认依赖更早版本的会话已经重启或关闭",
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
            previous_version=args.previous_version,
            target_version=target_version,
            confirm_previous_sessions_restarted=args.confirm_previous_sessions_restarted,
            source_root=stable_root,
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
