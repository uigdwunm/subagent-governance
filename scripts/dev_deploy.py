#!/usr/bin/env python3
"""本机开发测试专用：原子部署 allowlisted runtime bundle 并管理双版本缓存。

This is the sole development deployment entry.  It does not modify
Marketplace configuration, Registry state, Hook trust, or global AGENTS.md.
Without ``--execute`` it is a strictly read-only dry run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    from scripts.runtime_bundle import (
        bundle_digest, stage_runtime_bundle, verify_runtime_bundle,
    )
except ModuleNotFoundError:
    from runtime_bundle import bundle_digest, stage_runtime_bundle, verify_runtime_bundle


if os.name == "nt":
    import msvcrt

    fcntl = None
else:
    import fcntl

    msvcrt = None


PLUGIN_NAME = "subagent-governance"
TRANSACTION_PREFIX = "transaction-"
TRANSACTION_MANIFEST = "transaction.json"
STABLE_SNAPSHOT = "stable"
CACHE_SNAPSHOT = "cache"
LOCK_FILE = ".dev-deploy.lock"
STAGING_PREFIX = f".{PLUGIN_NAME}.staging-"
BACKUP_PREFIX = f".{PLUGIN_NAME}.backup-"
RECOVERY_PREFIX = f".{PLUGIN_NAME}.recovery-"
COMMIT_OID = re.compile(r"^[0-9a-f]{40,64}$")


def _failpoint(_stage: str) -> None:
    """Inert fault-injection seam used only by repository tests."""


def _owned_by_current_user(metadata: os.stat_result) -> bool:
    getuid = getattr(os, "getuid", None)
    return getuid is None or getattr(metadata, "st_uid", getuid()) == getuid()


def _ordinary_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"{label} 必须是普通目录且不能是符号链接：{path}")
    metadata = path.stat()
    if not _owned_by_current_user(metadata):
        raise PermissionError(f"{label} 必须由当前用户拥有：{path}")
    if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o022:
        raise PermissionError(f"{label} 不能允许组用户或其他用户写入：{path}")


def _ordinary_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} 必须是普通文件且不能是符号链接：{path}")
    metadata = path.stat()
    if not _owned_by_current_user(metadata):
        raise PermissionError(f"{label} 必须由当前用户拥有：{path}")
    if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o022:
        raise PermissionError(f"{label} 不能允许组用户或其他用户写入：{path}")


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError(f"部署事务记录必须是普通文件：{path}")
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
def _operation_lock(transaction_parent: Path) -> Iterator[None]:
    lock_path = transaction_parent / LOCK_FILE
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not _owned_by_current_user(metadata):
            raise RuntimeError(f"部署事务锁必须是当前用户拥有的普通文件：{lock_path}")
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(f"已有开发部署事务正在运行：{lock_path}") from exc
        else:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if metadata.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError(f"已有开发部署事务正在运行：{lock_path}") from exc
        yield
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


def manifest_version(root: Path) -> str:
    path = root / ".codex-plugin/plugin.json"
    _ordinary_file(path, "plugin Manifest")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"plugin Manifest 无法读取：{path}") from exc
    version = value.get("version") if isinstance(value, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError(f"plugin Manifest version 无效：{path}")
    return _version_name(version.strip(), "Manifest version")


def _version_name(value: str, label: str) -> str:
    if not value or value in {".", ".."} or Path(value).name != value:
        raise ValueError(f"{label} 必须是单个非空版本目录名：{value!r}")
    return value


def _safe_tree_digest(root: Path) -> str:
    import hashlib

    _ordinary_directory(root, "插件树")
    digest = hashlib.sha256()
    files = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"插件树中不允许符号链接：{path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise RuntimeError(f"插件树中只允许普通文件和目录：{path}")
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(oct(stat.S_IMODE(path.stat().st_mode)).encode("ascii"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        files += 1
    if files == 0:
        raise RuntimeError(f"插件树不能为空：{root}")
    return digest.hexdigest()


def _git(source: Path, *arguments: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(source), *arguments], stderr=subprocess.PIPE
        ).decode("utf-8", "strict")
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Git source 校验失败：{source}") from exc


def _clean_exact_head(source: Path, expected_head: str) -> str:
    if COMMIT_OID.fullmatch(expected_head) is None:
        raise ValueError("--expected-head 必须是完整 commit OID")
    if _git(source, "rev-parse", "--is-inside-work-tree").strip() != "true":
        raise RuntimeError("source root 不是 Git worktree")
    if Path(_git(source, "rev-parse", "--show-toplevel").strip()).resolve() != source.resolve():
        raise RuntimeError("source root 必须是 Git worktree 根目录")
    actual = _git(source, "rev-parse", "HEAD").strip()
    if actual != expected_head:
        raise RuntimeError(f"Git HEAD 与 expected head 不一致：{actual}")
    if _git(source, "status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("Git source 必须是干净 worktree（含未跟踪文件）")
    return actual


def _marketplace_spec(marketplace: str) -> str:
    value = marketplace.strip()
    if not value or any(character in value for character in "@/\\"):
        raise ValueError(f"Marketplace 名称无效：{marketplace!r}")
    return f"{PLUGIN_NAME}@{value}"


def _safe_roots(
    source_root: Path,
    stable_root: Path,
    cache_parent: Path,
    transaction_parent: Path,
) -> tuple[Path, Path, Path, Path]:
    source = source_root.expanduser().absolute()
    stable = stable_root.expanduser().absolute()
    cache = cache_parent.expanduser().absolute()
    transactions = transaction_parent.expanduser().absolute()
    _ordinary_directory(source, "开发 source root")
    _ordinary_directory(stable.parent, "stable parent")
    if stable.exists() or stable.is_symlink():
        _ordinary_directory(stable, "stable root")
    _ordinary_directory(cache, "插件 cache parent")
    _ordinary_directory(transactions, "部署 transaction parent")
    if stable.name != PLUGIN_NAME:
        raise RuntimeError(f"stable root basename 必须是 {PLUGIN_NAME}")
    resolved = [source.resolve(), stable.resolve(), cache.resolve(), transactions.resolve()]
    for index, left in enumerate(resolved):
        for right in resolved[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise RuntimeError("source/stable/cache/transaction roots 必须互不重叠")
    if cache.stat().st_dev != transactions.stat().st_dev:
        raise RuntimeError("cache 与 transaction parent 必须位于同一文件系统")
    return source, stable, cache, transactions


def _cache_facts(cache_parent: Path) -> list[dict[str, str]]:
    facts: list[dict[str, str]] = []
    for entry in sorted(cache_parent.iterdir(), key=lambda path: path.name):
        _ordinary_directory(entry, "插件 cache")
        version = manifest_version(entry)
        if version != entry.name:
            raise RuntimeError(f"cache Manifest version 必须与目录名一致：{entry}")
        facts.append({"name": entry.name, "digest": _safe_tree_digest(entry)})
    return facts


def _select_previous(
    caches: list[dict[str, str]], previous_version: str | None,
    target_version: str,
) -> str | None:
    names = {item["name"] for item in caches}
    if target_version in names:
        raise RuntimeError(f"target version cache 在部署前已存在：{target_version}")
    if not caches:
        if previous_version is not None:
            raise RuntimeError("cache 为空时不能指定 previous version")
        return None
    if previous_version is None:
        raise RuntimeError(
            "发现已有 cache；必须显式传入从 codex plugin list 确认的 previous version"
        )
    previous = _version_name(previous_version, "previous version")
    if previous not in names:
        raise RuntimeError(f"previous version cache 不存在：{previous}")
    if previous == target_version:
        raise RuntimeError("target version 必须不同于 previous version")
    if len(caches) > 2:
        raise RuntimeError("安装前 cache 超过双版本边界")
    return previous


def _switch_paths(stable: Path, transaction_id: str) -> tuple[Path, Path, Path]:
    return (
        stable.parent / f"{STAGING_PREFIX}{transaction_id}",
        stable.parent / f"{BACKUP_PREFIX}{transaction_id}",
        stable.parent / f"{RECOVERY_PREFIX}{transaction_id}",
    )


def _safe_remove_tree(path: Path, parent: Path, prefix: str, label: str) -> None:
    if path.parent != parent or not path.name.startswith(prefix):
        raise RuntimeError(f"{label} 路径无法安全绑定：{path}")
    _safe_tree_digest(path)
    shutil.rmtree(path)


def _transaction_directories(parent: Path) -> list[Path]:
    return sorted(
        [path for path in parent.iterdir() if path.name.startswith(TRANSACTION_PREFIX)],
        key=lambda path: path.name,
    )


def _read_transaction(transaction: Path) -> dict[str, Any]:
    _ordinary_directory(transaction, "部署 transaction")
    path = transaction / TRANSACTION_MANIFEST
    _ordinary_file(path, "部署 transaction manifest")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"部署 transaction manifest 无法读取：{path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("部署 transaction manifest 必须是对象")
    return value


def _live_cache_matches(cache_parent: Path, expected: list[dict[str, str]]) -> bool:
    try:
        return _cache_facts(cache_parent) == expected
    except Exception:
        return False


def _restore_cache_snapshot(
    transaction: Path, cache_parent: Path, expected: list[dict[str, str]]
) -> None:
    snapshot = transaction / CACHE_SNAPSHOT
    _ordinary_directory(snapshot, "cache snapshot")
    snapshot_facts = _cache_facts(snapshot)
    if snapshot_facts != expected:
        raise RuntimeError("cache snapshot facts 与 transaction manifest 不一致")
    for entry in list(cache_parent.iterdir()):
        _ordinary_directory(entry, "回滚前 cache")
        _safe_tree_digest(entry)
        shutil.rmtree(entry)
    for fact in expected:
        source = snapshot / fact["name"]
        target = cache_parent / fact["name"]
        shutil.copytree(source, target, copy_function=shutil.copy2)
        if _safe_tree_digest(target) != fact["digest"]:
            raise RuntimeError(f"回滚后的 cache digest 不匹配：{target}")


def _restore_stable_snapshot(
    transaction: Path, manifest: dict[str, Any], stable: Path,
    backup: Path, recovery: Path,
) -> None:
    expected_old = manifest.get("pre_stable_digest")
    source_digest = manifest.get("source_bundle_digest")
    if not isinstance(expected_old, str) or not isinstance(source_digest, str):
        raise RuntimeError("transaction 缺少 stable digest")
    if not stable.exists() and not stable.is_symlink():
        if backup.exists() or backup.is_symlink():
            _ordinary_directory(backup, "stable backup")
            if _safe_tree_digest(backup) != expected_old:
                raise RuntimeError("stable backup digest 不匹配")
            os.replace(backup, stable)
            if _safe_tree_digest(stable) != expected_old:
                raise RuntimeError("恢复后的 stable digest 不匹配")
            return
        snapshot = transaction / STABLE_SNAPSHOT
        _ordinary_directory(snapshot, "stable snapshot")
        if _safe_tree_digest(snapshot) != expected_old:
            raise RuntimeError("stable snapshot digest 不匹配")
        shutil.copytree(snapshot, recovery, copy_function=shutil.copy2)
        os.replace(recovery, stable)
        if _safe_tree_digest(stable) != expected_old:
            raise RuntimeError("恢复后的 stable digest 不匹配")
        return
    current = _safe_tree_digest(stable)
    if current == expected_old:
        if backup.exists():
            _safe_remove_tree(backup, stable.parent, BACKUP_PREFIX, "stable backup")
        return
    if current != source_digest:
        raise RuntimeError("当前 stable tree 无法绑定到部署前或部署后 digest")
    if backup.exists() or backup.is_symlink():
        _ordinary_directory(backup, "stable backup")
        if _safe_tree_digest(backup) != expected_old:
            raise RuntimeError("stable backup digest 不匹配")
        shutil.rmtree(stable)
        os.replace(backup, stable)
    else:
        snapshot = transaction / STABLE_SNAPSHOT
        _ordinary_directory(snapshot, "stable snapshot")
        if _safe_tree_digest(snapshot) != expected_old:
            raise RuntimeError("stable snapshot digest 不匹配")
        if recovery.exists() or recovery.is_symlink():
            raise RuntimeError(f"recovery path 已存在：{recovery}")
        shutil.copytree(snapshot, recovery, copy_function=shutil.copy2)
        shutil.rmtree(stable)
        os.replace(recovery, stable)
    if _safe_tree_digest(stable) != expected_old:
        raise RuntimeError("恢复后的 stable digest 不匹配")


def _recover_transaction(
    transaction: Path, stable: Path, cache_parent: Path
) -> None:
    manifest = _read_transaction(transaction)
    transaction_id = manifest.get("transaction_id")
    if transaction_id != transaction.name:
        raise RuntimeError("transaction id 与目录名不匹配")
    if manifest.get("stable_root") != str(stable) or manifest.get("cache_parent") != str(cache_parent):
        raise RuntimeError("transaction roots 与当前部署目标不匹配")
    staging, backup, recovery = _switch_paths(stable, str(transaction_id))
    if (
        manifest.get("staging_path") != str(staging)
        or manifest.get("backup_path") != str(backup)
        or manifest.get("recovery_path") != str(recovery)
    ):
        raise RuntimeError("transaction switch paths 无法精确绑定")
    expected_caches = manifest.get("pre_caches")
    if not isinstance(expected_caches, list) or not all(
        isinstance(item, dict) and set(item) == {"name", "digest"}
        for item in expected_caches
    ):
        raise RuntimeError("transaction pre_caches 无效")

    state = manifest.get("state")
    if state == "snapshot_started":
        if _safe_tree_digest(stable) != manifest.get("pre_stable_digest") or not _live_cache_matches(cache_parent, expected_caches):
            raise RuntimeError("未完成 snapshot 且 live roots 已变化，拒绝猜测恢复")
    else:
        _restore_stable_snapshot(transaction, manifest, stable, backup, recovery)
        _restore_cache_snapshot(transaction, cache_parent, expected_caches)
    if staging.exists() or staging.is_symlink():
        _safe_remove_tree(staging, stable.parent, STAGING_PREFIX, "staging")
    if backup.exists() or backup.is_symlink():
        _safe_remove_tree(backup, stable.parent, BACKUP_PREFIX, "backup")
    if recovery.exists() or recovery.is_symlink():
        _safe_remove_tree(recovery, stable.parent, RECOVERY_PREFIX, "recovery")
    shutil.rmtree(transaction)


def _recover_interrupted(
    transaction_parent: Path, stable: Path, cache_parent: Path
) -> bool:
    transactions = _transaction_directories(transaction_parent)
    if len(transactions) > 1:
        raise RuntimeError("存在多个未完成 deployment transaction，拒绝按目录排序恢复")
    bound_switches: set[Path] = set()
    if transactions:
        manifest = _read_transaction(transactions[0])
        for field in ("staging_path", "backup_path", "recovery_path"):
            value = manifest.get(field)
            if isinstance(value, str):
                bound_switches.add(Path(value))
    for path in stable.parent.iterdir():
        if path.name.startswith((STAGING_PREFIX, BACKUP_PREFIX, RECOVERY_PREFIX)) and path not in bound_switches:
            raise RuntimeError(f"发现无法绑定的 deployment switch path：{path}")
    if not transactions:
        return False
    _recover_transaction(transactions[0], stable, cache_parent)
    return True


def _create_snapshot(
    transaction: Path, manifest: dict[str, Any], stable: Path,
    cache_parent: Path,
) -> None:
    transaction.mkdir(mode=0o700)
    _write_json_atomic(transaction / TRANSACTION_MANIFEST, manifest)
    stable_snapshot = transaction / STABLE_SNAPSHOT
    cache_snapshot = transaction / CACHE_SNAPSHOT
    shutil.copytree(stable, stable_snapshot, copy_function=shutil.copy2)
    if _safe_tree_digest(stable_snapshot) != manifest["pre_stable_digest"]:
        raise RuntimeError("stable snapshot digest 不匹配")
    cache_snapshot.mkdir(mode=0o700)
    for fact in manifest["pre_caches"]:
        source = cache_parent / fact["name"]
        target = cache_snapshot / fact["name"]
        shutil.copytree(source, target, copy_function=shutil.copy2)
        if _safe_tree_digest(target) != fact["digest"]:
            raise RuntimeError(f"cache snapshot digest 不匹配：{target}")
    manifest["state"] = "snapshot_complete"
    manifest["updated_at"] = _utc_now()
    _write_json_atomic(transaction / TRANSACTION_MANIFEST, manifest)


def _restore_previous(
    transaction: Path, cache_parent: Path, previous: str | None,
    pre_caches: list[dict[str, str]],
) -> bool:
    if previous is None:
        return False
    fact = next(item for item in pre_caches if item["name"] == previous)
    target = cache_parent / previous
    if target.exists() or target.is_symlink():
        _ordinary_directory(target, "previous cache")
        if _safe_tree_digest(target) != fact["digest"]:
            raise RuntimeError("previous cache 在 native install 后发生变化")
        return False
    source = transaction / CACHE_SNAPSHOT / previous
    _ordinary_directory(source, "previous cache snapshot")
    shutil.copytree(source, target, copy_function=shutil.copy2)
    if _safe_tree_digest(target) != fact["digest"]:
        raise RuntimeError("恢复后的 previous cache digest 不匹配")
    return True


def _base_report(
    *, source: Path, stable: Path, cache: Path, transactions: Path,
    expected_head: str, expected_version: str, execute: bool,
) -> dict[str, Any]:
    return {
        "state": "admission",
        "failed_stage": None,
        "execute": execute,
        "source_root": str(source),
        "stable_root": str(stable),
        "cache_parent": str(cache),
        "transaction_parent": str(transactions),
        "expected_head": expected_head,
        "expected_version": expected_version,
        "source_bundle_digest": None,
        "stable_bundle_digest": None,
        "target_cache_digest": None,
        "previous_cache_restored": False,
        "retained_previous_version": None,
        "removed_cache_entries": [],
        "recovered_interrupted_transaction": False,
        "codex_registration_checked": False,
        "hook_trust_checked": False,
        "warnings": ["codex_registration_not_checked", "hook_trust_not_checked"],
    }


def deploy(
    *,
    source_root: Path,
    stable_root: Path,
    cache_parent: Path,
    transaction_parent: Path,
    expected_head: str,
    expected_version: str,
    marketplace: str,
    previous_version: str | None,
    execute: bool,
    runner=None,
    codex_command: str = "codex",
) -> tuple[int, dict[str, Any]]:
    source = source_root.expanduser().absolute()
    stable = stable_root.expanduser().absolute()
    cache = cache_parent.expanduser().absolute()
    transactions = transaction_parent.expanduser().absolute()
    report = _base_report(
        source=source, stable=stable, cache=cache, transactions=transactions,
        expected_head=expected_head, expected_version=expected_version,
        execute=execute,
    )
    transaction: Path | None = None
    manifest: dict[str, Any] | None = None
    try:
        source, stable, cache, transactions = _safe_roots(
            source, stable, cache, transactions
        )
        _clean_exact_head(source, expected_head)
        expected_version = _version_name(expected_version, "expected version")
        if manifest_version(source) != expected_version:
            raise RuntimeError("source Manifest version 与 expected version 不一致")
        source_digest = bundle_digest(source)
        spec = _marketplace_spec(marketplace)
        pending = _transaction_directories(transactions)
        report["source_bundle_digest"] = source_digest
        if not execute:
            if pending:
                raise RuntimeError("存在未完成 transaction；dry-run 不执行恢复")
            pre_stable_digest = _safe_tree_digest(stable)
            pre_caches = _cache_facts(cache)
            previous = _select_previous(
                pre_caches, previous_version, expected_version,
            )
            report["retained_previous_version"] = previous
            report["state"] = "dry_run_passed"
            return 0, report

        with _operation_lock(transactions):
            recovered = _recover_interrupted(transactions, stable, cache)
            report["recovered_interrupted_transaction"] = recovered
            # Recovery can change live roots back to their exact pre-transaction facts.
            _clean_exact_head(source, expected_head)
            if bundle_digest(source) != source_digest:
                raise RuntimeError("source bundle 在 admission 后发生变化")
            pre_stable_digest = _safe_tree_digest(stable)
            pre_caches = _cache_facts(cache)
            previous = _select_previous(
                pre_caches, previous_version, expected_version,
            )
            report["retained_previous_version"] = previous
            transaction_id = f"{TRANSACTION_PREFIX}{os.getpid()}-{uuid.uuid4().hex}"
            transaction = transactions / transaction_id
            staging, backup, recovery_path = _switch_paths(stable, transaction_id)
            manifest = {
                "transaction_id": transaction_id,
                "state": "snapshot_started",
                "source_root": str(source),
                "stable_root": str(stable),
                "cache_parent": str(cache),
                "expected_head": expected_head,
                "expected_version": expected_version,
                "source_bundle_digest": source_digest,
                "pre_stable_digest": pre_stable_digest,
                "pre_caches": pre_caches,
                "previous_version": previous,
                "staging_path": str(staging),
                "backup_path": str(backup),
                "recovery_path": str(recovery_path),
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
            }
            _create_snapshot(transaction, manifest, stable, cache)
            _failpoint("after_snapshot")
            staged_digest = stage_runtime_bundle(source, staging)
            if staged_digest != source_digest or manifest_version(staging) != expected_version:
                raise RuntimeError("staged bundle version/digest 不匹配")
            manifest["state"] = "stage_complete"
            _write_json_atomic(transaction / TRANSACTION_MANIFEST, manifest)
            if _safe_tree_digest(stable) != pre_stable_digest:
                raise RuntimeError("stable root 在 snapshot 后发生变化")
            os.replace(stable, backup)
            _failpoint("after_stable_backup")
            os.replace(staging, stable)
            if verify_runtime_bundle(stable) != source_digest:
                raise RuntimeError("atomic activation 后 stable bundle digest 不匹配")
            manifest["state"] = "stable_activated"
            _write_json_atomic(transaction / TRANSACTION_MANIFEST, manifest)
            _failpoint("after_stable_activation")

            run_command = runner or subprocess.run
            result = run_command(
                [codex_command, "plugin", "add", spec], check=False
            )
            returncode = int(result.returncode)
            manifest["state"] = "native_install_returned"
            manifest["native_returncode"] = returncode
            _write_json_atomic(transaction / TRANSACTION_MANIFEST, manifest)
            if returncode != 0:
                report["failed_stage"] = "codex_command"
                raise RuntimeError(f"codex plugin add 返回 {returncode}")

            report["previous_cache_restored"] = _restore_previous(
                transaction, cache, previous, pre_caches
            )
            target = cache / expected_version
            if manifest_version(target) != expected_version:
                raise RuntimeError("target cache Manifest version 不匹配")
            target_digest = verify_runtime_bundle(target)
            stable_digest = verify_runtime_bundle(stable)
            if target_digest != source_digest or stable_digest != source_digest:
                report["failed_stage"] = "post_install_verification"
                raise RuntimeError("stable/target runtime bundle digest 不匹配")
            if bundle_digest(source) != source_digest or _clean_exact_head(source, expected_head) != expected_head:
                report["failed_stage"] = "source_post_install"
                raise RuntimeError("source 在 native install 期间发生变化")

            keep = {expected_version}
            if previous is not None:
                keep.add(previous)
            pre_names = {item["name"] for item in pre_caches}
            report["removed_cache_entries"] = sorted(pre_names - keep)
            for entry in list(cache.iterdir()):
                _ordinary_directory(entry, "安装后 cache")
                if entry.name not in keep:
                    _safe_tree_digest(entry)
                    shutil.rmtree(entry)
            remaining = _cache_facts(cache)
            if {item["name"] for item in remaining} != keep or len(remaining) != len(keep):
                report["failed_stage"] = "cache_retention"
                raise RuntimeError("安装后 cache 未精确收敛为 target + exact previous")
            if previous is not None:
                previous_fact = next(item for item in pre_caches if item["name"] == previous)
                current_previous = next(item for item in remaining if item["name"] == previous)
                if current_previous["digest"] != previous_fact["digest"]:
                    report["failed_stage"] = "cache_retention"
                    raise RuntimeError("retained previous cache digest 不匹配")

            _safe_remove_tree(backup, stable.parent, BACKUP_PREFIX, "stable backup")
            shutil.rmtree(transaction)
            report.update(
                state="deploy_succeeded",
                stable_bundle_digest=stable_digest,
                target_cache_digest=target_digest,
                retained_previous_version=previous,
            )
            return 0, report
    except Exception as exc:
        if report.get("failed_stage") is None:
            report["failed_stage"] = "admission" if transaction is None else str(
                manifest.get("state") if manifest else "transaction"
            )
        report["error"] = str(exc)
        if transaction is not None and transaction.exists():
            try:
                _recover_transaction(transaction, stable, cache)
                report["state"] = "deploy_failed_rolled_back"
            except Exception as rollback_exc:
                report["state"] = "rollback_failed"
                report["rollback_error"] = str(rollback_exc)
        else:
            report["state"] = "deploy_failed"
        return 2, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--stable-root", type=Path, required=True)
    parser.add_argument("--cache-parent", type=Path, required=True)
    parser.add_argument("--transaction-parent", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--marketplace", required=True)
    parser.add_argument("--previous-version")
    parser.add_argument("--codex-command", default="codex")
    parser.add_argument(
        "--execute", action="store_true",
        help="执行 stable/cache/Codex 写入；省略时严格 dry-run",
    )
    args = parser.parse_args(argv)
    code, report = deploy(
        source_root=args.source_root,
        stable_root=args.stable_root,
        cache_parent=args.cache_parent,
        transaction_parent=args.transaction_parent,
        expected_head=args.expected_head,
        expected_version=args.expected_version,
        marketplace=args.marketplace,
        previous_version=args.previous_version,
        execute=args.execute,
        codex_command=args.codex_command,
    )
    stream = sys.stdout if code == 0 else sys.stderr
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), file=stream)
    return code


__all__ = ["deploy", "main", "manifest_version"]


if __name__ == "__main__":
    raise SystemExit(main())
