#!/usr/bin/env python3
"""Transactionally project a clean Git worktree into a stable plugin source.

This intentionally has no defaults for the source, destination, transaction
parent, commit, or version.  The caller supplies all deployment facts so a
P10-A audit can reconstruct exactly what was switched.
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
from pathlib import Path

try:
    from scripts.check_installation import manifest_version, tree_digest
    from scripts.reinstall_plugin import (
        TRANSACTION_PREFIX,
        operation_lock,
        ordinary_directory,
        ordinary_file,
        utc_now,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from check_installation import manifest_version, tree_digest
    from reinstall_plugin import (
        TRANSACTION_PREFIX,
        operation_lock,
        ordinary_directory,
        ordinary_file,
        utc_now,
        write_json_atomic,
    )


PLUGIN_NAME = "subagent-governance"
SYNC_PREFIX = "stable-sync-"
SYNC_MANIFEST = "sync-manifest.json"
LAST_REPORT = "last-stable-sync.json"
STAGING_PREFIX = f".{PLUGIN_NAME}.staging-"
BACKUP_PREFIX = f".{PLUGIN_NAME}.backup-"
COMMIT_OID = re.compile(r"^[0-9a-f]{40,64}$")


def _failpoint(_stage: str) -> None:
    """An intentionally inert seam for fault-injection tests."""


def _git(source: Path, *arguments: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(source), *arguments], stderr=subprocess.PIPE
        ).decode("utf-8", "strict")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"Git source 校验失败：{source}；原因：{exc}") from exc


def _clean_head(source: Path, expected_head: str) -> str:
    if not COMMIT_OID.fullmatch(expected_head):
        raise ValueError("--expected-head 必须是完整 commit OID")
    if _git(source, "rev-parse", "--is-inside-work-tree").strip() != "true":
        raise RuntimeError(f"source root 不是 Git worktree：{source}")
    top_level = Path(_git(source, "rev-parse", "--show-toplevel").strip()).resolve()
    if top_level != source.resolve():
        raise RuntimeError(f"source root 必须是 Git worktree 根目录：{source}")
    actual = _git(source, "rev-parse", "HEAD").strip()
    if actual != expected_head:
        raise RuntimeError(f"Git HEAD 与 --expected-head 不一致：{actual}")
    status = _git(source, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise RuntimeError("Git source 必须是干净 worktree（含未跟踪文件）")
    return actual


def _tracked_paths(source: Path) -> list[Path]:
    raw = _git(source, "ls-files", "-z").encode("utf-8")
    entries = raw.split(b"\0")
    result: list[Path] = []
    seen: set[str] = set()
    for entry in entries:
        if not entry:
            continue
        try:
            name = entry.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise RuntimeError("Git tracked path 必须是 UTF-8") from exc
        candidate = Path(name)
        if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
            raise RuntimeError(f"Git tracked path 非法：{name!r}")
        if "__pycache__" in candidate.parts:
            raise RuntimeError(f"Git tracked path 不能包含 __pycache__：{name!r}")
        if name in seen:
            raise RuntimeError(f"Git tracked path 重复：{name!r}")
        seen.add(name)
        path = source / candidate
        try:
            path.relative_to(source)
        except ValueError as exc:
            raise RuntimeError(f"Git tracked path 超出 source root：{name!r}") from exc
        ordinary_file(path, "Git tracked source 文件")
        result.append(candidate)
    if not result:
        raise RuntimeError("Git tracked 文件集合不能为空")
    return result


def _safe_roots(source: Path, stable: Path, transaction_parent: Path) -> tuple[Path, Path, Path]:
    source = source.expanduser().absolute()
    stable = stable.expanduser().absolute()
    transaction_parent = transaction_parent.expanduser().absolute()
    ordinary_directory(source, "source root")
    ordinary_directory(stable.parent, "stable parent")
    ordinary_directory(transaction_parent, "transaction parent")
    if stable.name != PLUGIN_NAME:
        raise RuntimeError(f"stable root basename 必须是 {PLUGIN_NAME}：{stable}")
    if stable.is_symlink() or source.is_symlink():
        raise RuntimeError("source root 与 stable root 不能是符号链接")
    if stable.exists() and not stable.is_dir():
        raise RuntimeError(f"stable root 必须是普通目录：{stable}")
    source_real = source.resolve()
    stable_real = stable.resolve()
    transaction_real = transaction_parent.resolve()
    roots = {
        "source root": source_real,
        "stable root": stable_real,
        "transaction parent": transaction_real,
    }
    names = list(roots)
    for index, left_name in enumerate(names):
        for right_name in names[index + 1 :]:
            left, right = roots[left_name], roots[right_name]
            if left == right or left in right.parents or right in left.parents:
                raise RuntimeError(
                    f"{left_name} 与 {right_name} 不能重叠或互为父子目录"
                )
    return source, stable, transaction_parent


def _transaction_paths(stable: Path, transaction_parent: Path, transaction_id: str) -> tuple[Path, Path, Path]:
    transaction = transaction_parent / transaction_id
    staging = stable.parent / f"{STAGING_PREFIX}{transaction_id}"
    backup = stable.parent / f"{BACKUP_PREFIX}{transaction_id}"
    return transaction, staging, backup


def _report(
    *, transaction_id: str | None, source: Path, stable: Path,
    expected_head: str, expected_version: str, **updates: object,
) -> dict[str, object]:
    report: dict[str, object] = {
        "transaction_id": transaction_id,
        "state": "sync_started",
        "failed_stage": None,
        "source_root": str(source),
        "stable_root": str(stable),
        "expected_head": expected_head,
        "actual_head_before": None,
        "actual_head_after": None,
        "expected_version": expected_version,
        "source_projection_digest": None,
        "old_stable_digest": None,
        "new_stable_digest": None,
        "staging_path": None,
        "backup_path": None,
        "recovered_interrupted_transaction": False,
        "rollback_performed": False,
        "backup_removed": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    report.update(updates)
    return report


def _write_report(parent: Path, report: dict[str, object]) -> None:
    report["updated_at"] = utc_now()
    write_json_atomic(parent / LAST_REPORT, report)


def _read_manifest(transaction: Path) -> dict[str, object]:
    path = transaction / SYNC_MANIFEST
    ordinary_file(path, "stable sync transaction manifest")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"stable sync transaction manifest 无法读取：{path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"stable sync transaction manifest 必须是对象：{path}")
    return value


def _known_sync_transactions(parent: Path) -> list[Path]:
    return [path for path in parent.iterdir() if path.name.startswith(SYNC_PREFIX)]


def _unbound_switch_paths(stable: Path, expected: set[Path]) -> list[Path]:
    paths = []
    for path in stable.parent.iterdir():
        if path.name.startswith(STAGING_PREFIX) or path.name.startswith(BACKUP_PREFIX):
            if path not in expected:
                paths.append(path)
    return paths


def _remove_transaction(transaction: Path) -> None:
    ordinary_directory(transaction, "stable sync transaction")
    shutil.rmtree(transaction)


def _safe_remove_switch_dir(path: Path, prefix: str) -> None:
    if path.parent.name == "":
        raise RuntimeError(f"不安全的切换目录：{path}")
    if not path.name.startswith(prefix):
        raise RuntimeError(f"切换目录前缀不匹配：{path}")
    ordinary_directory(path, "事务切换目录")
    shutil.rmtree(path)


def _recover_one(stable: Path, parent: Path, transaction: Path) -> dict[str, object]:
    manifest = _read_manifest(transaction)
    transaction_id = manifest.get("transaction_id")
    if not isinstance(transaction_id, str) or transaction.name != transaction_id:
        raise RuntimeError(f"stable sync transaction id 不匹配：{transaction}")
    _, staging, backup = _transaction_paths(stable, parent, transaction_id)
    if manifest.get("staging_path") != str(staging) or manifest.get("backup_path") != str(backup):
        raise RuntimeError(f"stable sync transaction 路径无法唯一绑定：{transaction}")
    expected = {staging, backup}
    unbound = _unbound_switch_paths(stable, expected)
    if unbound:
        raise RuntimeError(f"发现无法绑定的 stable switch 目录：{unbound[0]}")
    old_digest = manifest.get("old_stable_digest")
    new_digest = manifest.get("source_projection_digest")
    version = manifest.get("expected_version")
    if not all(isinstance(value, str) for value in (old_digest, new_digest, version)):
        raise RuntimeError(f"stable sync transaction 缺少摘要或版本：{transaction}")
    stable_exists = stable.exists() or stable.is_symlink()
    backup_exists = backup.exists() or backup.is_symlink()
    state = str(manifest.get("state") or "")
    report = dict(manifest)
    report.update(recovered_interrupted_transaction=True, rollback_performed=False)
    if stable_exists and state in {
        "stable_activated",
        "sync_succeeded",
        "sync_succeeded_cleanup_required",
    }:
        ordinary_directory(stable, "恢复中的 stable root")
        if tree_digest(stable) == new_digest and manifest_version(stable) == version:
            if backup_exists:
                ordinary_directory(backup, "恢复中的 stable backup")
                if tree_digest(backup) != old_digest:
                    raise RuntimeError("恢复中的 stable backup 摘要不匹配")
                _safe_remove_switch_dir(backup, BACKUP_PREFIX)
            if staging.exists() or staging.is_symlink():
                _safe_remove_switch_dir(staging, STAGING_PREFIX)
            report.update(state="sync_succeeded", backup_removed=True, new_stable_digest=new_digest)
            _write_report(parent, report)
            _remove_transaction(transaction)
            return report
    if backup_exists:
        ordinary_directory(backup, "恢复中的 stable backup")
        if tree_digest(backup) != old_digest:
            raise RuntimeError("恢复中的 stable backup 摘要不匹配")
        if stable_exists:
            ordinary_directory(stable, "恢复中待回滚 stable root")
            if tree_digest(stable) != new_digest:
                raise RuntimeError("恢复中 stable root 无法与本事务的新投影绑定")
            _remove_active_stable(stable)
        os.replace(backup, stable)
        if tree_digest(stable) != old_digest:
            raise RuntimeError("恢复后的 stable root 摘要不匹配")
        if staging.exists() or staging.is_symlink():
            _safe_remove_switch_dir(staging, STAGING_PREFIX)
        report.update(state="sync_failed_rolled_back", rollback_performed=True, backup_removed=True)
        _write_report(parent, report)
        _remove_transaction(transaction)
        return report
    if state in {"sync_started", "stage_complete"} and stable_exists:
        ordinary_directory(stable, "恢复中的 stable root")
        if tree_digest(stable) != old_digest:
            raise RuntimeError("stage 恢复时 stable root 摘要不匹配")
        if staging.exists() or staging.is_symlink():
            _safe_remove_switch_dir(staging, STAGING_PREFIX)
        report.update(state="sync_failed_rolled_back", rollback_performed=True)
        _write_report(parent, report)
        _remove_transaction(transaction)
        return report
    raise RuntimeError(f"无法唯一恢复 stable sync transaction：{transaction}")


def _recover_interrupted(stable: Path, parent: Path) -> bool:
    transactions = _known_sync_transactions(parent)
    installer_transactions = [path for path in parent.iterdir() if path.name.startswith(TRANSACTION_PREFIX)]
    if installer_transactions:
        raise RuntimeError("存在未完成 install transaction，stable sync 拒绝并发恢复")
    if len(transactions) > 1:
        raise RuntimeError("存在多个未完成 stable sync transaction，拒绝按目录排序恢复")
    unbound = _unbound_switch_paths(stable, set())
    if not transactions:
        if unbound:
            raise RuntimeError(f"发现无法绑定的 stable switch 目录：{unbound[0]}")
        return False
    _recover_one(stable, parent, transactions[0])
    return True


def _copy_projection(source: Path, staging: Path) -> str:
    paths = _tracked_paths(source)
    staging.mkdir(mode=0o700)
    for relative in paths:
        origin = source / relative
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target, follow_symlinks=False)
        ordinary_file(target, "staging projection 文件")
        if stat.S_IMODE(origin.stat().st_mode) != stat.S_IMODE(target.stat().st_mode):
            raise RuntimeError(f"staging projection 文件 mode 不匹配：{relative}")
        if origin.read_bytes() != target.read_bytes():
            raise RuntimeError(f"staging projection 文件内容不匹配：{relative}")
    return tree_digest(staging)


def _remove_active_stable(stable: Path) -> None:
    ordinary_directory(stable, "待回滚的新 stable root")
    if stable.name != PLUGIN_NAME:
        raise RuntimeError(f"待回滚 stable root 名称不正确：{stable}")
    shutil.rmtree(stable)


def sync_stable_plugin(
    *, source_root: Path, stable_root: Path, transaction_parent: Path,
    expected_head: str, expected_version: str,
) -> tuple[int, dict[str, object]]:
    """Synchronize a stable root.  It is safe to call from tests with temp roots."""
    source = source_root.expanduser().absolute()
    stable = stable_root.expanduser().absolute()
    parent = transaction_parent.expanduser().absolute()
    report = _report(transaction_id=None, source=source, stable=stable,
                     expected_head=expected_head, expected_version=expected_version)
    lock_acquired = False
    try:
        source, stable, parent = _safe_roots(source, stable, parent)
        with operation_lock(parent):
            lock_acquired = True
            recovered = _recover_interrupted(stable, parent)
            ordinary_directory(stable, "stable root")
            actual_head = _clean_head(source, expected_head)
            if manifest_version(source) != expected_version:
                raise RuntimeError("source Manifest full version 与 --expected-version 不一致")
            old_digest = tree_digest(stable)
            transaction_id = f"{SYNC_PREFIX}{os.getpid()}-{uuid.uuid4().hex}"
            transaction, staging, backup = _transaction_paths(stable, parent, transaction_id)
            report = _report(
                transaction_id=transaction_id, source=source, stable=stable,
                expected_head=expected_head, expected_version=expected_version,
                actual_head_before=actual_head, old_stable_digest=old_digest,
                staging_path=str(staging), backup_path=str(backup),
                recovered_interrupted_transaction=recovered,
            )
            if _unbound_switch_paths(stable, {staging, backup}):
                raise RuntimeError("发现无法绑定的 stable switch 目录")
            transaction.mkdir(mode=0o700)
            write_json_atomic(transaction / SYNC_MANIFEST, report)
            try:
                projection_digest = _copy_projection(source, staging)
                if manifest_version(staging) != expected_version:
                    raise RuntimeError("staging Manifest full version 与 --expected-version 不一致")
                report.update(source_projection_digest=projection_digest, state="stage_complete")
                actual_after_stage = _clean_head(source, expected_head)
                report["actual_head_after"] = actual_after_stage
                write_json_atomic(transaction / SYNC_MANIFEST, report)
                _failpoint("after_stage")
                if tree_digest(stable) != old_digest:
                    raise RuntimeError("stable root 在 admission 后发生变化")
                os.replace(stable, backup)
                if tree_digest(backup) != old_digest:
                    raise RuntimeError("stable backup digest 与 admission 不一致")
                report.update(state="backup_activated")
                write_json_atomic(transaction / SYNC_MANIFEST, report)
                _failpoint("after_backup")
                os.replace(staging, stable)
                report.update(state="stable_activated")
                write_json_atomic(transaction / SYNC_MANIFEST, report)
                _failpoint("after_activate")
                ordinary_directory(stable, "新 stable root")
                new_digest = tree_digest(stable)
                if new_digest != projection_digest or manifest_version(stable) != expected_version:
                    raise RuntimeError("新 stable root 的 version 或 digest 校验失败")
                report.update(new_stable_digest=new_digest, actual_head_after=_clean_head(source, expected_head))
                report.update(state="sync_succeeded")
                write_json_atomic(transaction / SYNC_MANIFEST, report)
                try:
                    _safe_remove_switch_dir(backup, BACKUP_PREFIX)
                    report["backup_removed"] = True
                    _write_report(parent, report)
                    _remove_transaction(transaction)
                    return 0, report
                except Exception as exc:
                    report.update(state="sync_succeeded_cleanup_required", failed_stage="cleanup", error=str(exc))
                    _write_report(parent, report)
                    write_json_atomic(transaction / SYNC_MANIFEST, report)
                    return 2, report
            except Exception as exc:
                report.update(failed_stage=report.get("state"), error=str(exc))
                try:
                    if backup.exists() or backup.is_symlink():
                        ordinary_directory(backup, "stable backup")
                        if tree_digest(backup) != old_digest:
                            raise RuntimeError("stable backup digest 无法验证")
                        if stable.exists() or stable.is_symlink():
                            ordinary_directory(stable, "失败时的新 stable root")
                            if tree_digest(stable) != report.get("source_projection_digest"):
                                raise RuntimeError("失败时的新 stable root 无法绑定到本事务")
                            _remove_active_stable(stable)
                        os.replace(backup, stable)
                        if tree_digest(stable) != old_digest:
                            raise RuntimeError("回滚后的 stable digest 不匹配")
                        report.update(state="sync_failed_rolled_back", rollback_performed=True, backup_removed=True)
                    else:
                        report.update(state="sync_failed")
                    if staging.exists() or staging.is_symlink():
                        _safe_remove_switch_dir(staging, STAGING_PREFIX)
                    _write_report(parent, report)
                    _remove_transaction(transaction)
                    return 2, report
                except Exception as rollback_exc:
                    report.update(state="rollback_failed", failed_stage="rollback", rollback_performed=True, error=str(rollback_exc))
                    _write_report(parent, report)
                    write_json_atomic(transaction / SYNC_MANIFEST, report)
                    return 2, report
    except Exception as exc:
        report.update(state="sync_failed", failed_stage=report.get("failed_stage") or "admission", error=str(exc))
        try:
            if lock_acquired and parent.exists() and parent.is_dir() and not parent.is_symlink():
                _write_report(parent, report)
        except Exception:
            pass
        return 2, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--stable-root", type=Path, required=True)
    parser.add_argument("--transaction-parent", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()
    returncode, report = sync_stable_plugin(
        source_root=args.source_root, stable_root=args.stable_root,
        transaction_parent=args.transaction_parent, expected_head=args.expected_head,
        expected_version=args.expected_version,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
