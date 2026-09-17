"""Context manifest structure and verification protocol.

Structure validators are pure.  Only ``verify_context_manifest`` performs
filesystem or Git work.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

try:
    from scripts.governance_errors import ContextMaterialConflictError, ContextVerificationError
    from scripts.governance_validation import required_fields
except ModuleNotFoundError:
    from governance_errors import ContextMaterialConflictError, ContextVerificationError
    from governance_validation import required_fields


def validate_context_manifest(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["字段 context_manifest 必须是对象"]
    mode = value.get("mode")
    if mode not in {"none", "declared"}:
        return ["字段 context_manifest.mode 必须是 none 或 declared"]
    if mode == "none":
        extras = sorted(set(value) - {"mode"})
        return (["context_manifest.mode=none 时不能包含字段 " + "、".join(extras)] if extras else [])

    errors = required_fields(value, ("mode", "workspace_root", "baseline", "required_paths"))
    extras = sorted(set(value) - {"mode", "workspace_root", "baseline", "required_paths"})
    if extras:
        errors.append("context_manifest 包含未知字段 " + "、".join(extras))
    workspace_root = value.get("workspace_root")
    if not isinstance(workspace_root, str) or not workspace_root.strip():
        errors.append("字段 context_manifest.workspace_root 必须是非空绝对路径")
    elif workspace_root != workspace_root.strip() or len(workspace_root) > 4000:
        errors.append("字段 context_manifest.workspace_root 不能包含首尾空白且长度不能超过 4000")
    elif not Path(workspace_root).is_absolute():
        errors.append("字段 context_manifest.workspace_root 必须是绝对路径")

    baseline = value.get("baseline")
    baseline_kind = baseline.get("kind") if isinstance(baseline, dict) else None
    if not isinstance(baseline, dict):
        errors.append("字段 context_manifest.baseline 必须是对象")
    else:
        baseline_extras = sorted(set(baseline) - {"kind", "revision"})
        if baseline_extras:
            errors.append("context_manifest.baseline 包含未知字段 " + "、".join(baseline_extras))
        missing = sorted({"kind", "revision"} - set(baseline))
        if missing:
            errors.append("context_manifest.baseline 缺少字段 " + "、".join(missing))
        revision = baseline.get("revision")
        if baseline_kind == "working_tree":
            if revision is not None:
                errors.append("baseline.kind=working_tree 时 revision 必须是 null")
        elif baseline_kind == "git_commit":
            if not isinstance(revision, str) or re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", revision) is None:
                errors.append("baseline.kind=git_commit 时 revision 必须是完整 commit OID")
        else:
            errors.append("字段 context_manifest.baseline.kind 必须是 working_tree 或 git_commit")

    required_paths = value.get("required_paths")
    if not isinstance(required_paths, list):
        errors.append("字段 context_manifest.required_paths 必须是数组")
        return errors
    if not required_paths:
        errors.append("context_manifest.mode=declared 时 required_paths 至少需要 1 项")
    if len(required_paths) > 64:
        errors.append("字段 context_manifest.required_paths 不能超过 64 项")
    seen: set[str] = set()
    for index, item in enumerate(required_paths):
        field_name = f"context_manifest.required_paths[{index}]"
        if not isinstance(item, dict):
            errors.append(f"字段 {field_name} 必须是对象")
            continue
        missing = sorted({"path", "type"} - set(item))
        extras = sorted(set(item) - {"path", "type"})
        if missing:
            errors.append(f"字段 {field_name} 缺少 " + "、".join(missing))
        if extras:
            errors.append(f"字段 {field_name} 包含未知字段 " + "、".join(extras))
        path_value = item.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            errors.append(f"字段 {field_name}.path 必须是非空字符串")
        elif len(path_value) > 1000:
            errors.append(f"字段 {field_name}.path 长度不能超过 1000")
        else:
            path = path_value.strip()
            parts = path.split("/")
            if path != path_value or path.startswith("/") or "\\" in path or any(part in {"", ".", ".."} for part in parts) or any(ord(character) < 32 for character in path):
                errors.append(f"字段 {field_name}.path 必须是规范的 POSIX 相对路径，不能包含空段、.、.. 或控制字符")
            elif path in seen:
                errors.append(f"字段 {field_name}.path 不能重复：{path}")
            else:
                seen.add(path)
        path_type = item.get("type")
        if path_type not in {"file", "directory"}:
            errors.append(f"字段 {field_name}.type 必须是 file 或 directory")
        elif baseline_kind == "working_tree" and path_type == "directory":
            errors.append(f"working_tree 不支持字段 {field_name}.type=directory；请逐文件声明，或改用 git_commit baseline")
    return errors


def validate_context_verification_record(manifest: Any, verification: Any) -> list[str]:
    if not isinstance(manifest, dict) or not isinstance(verification, dict):
        return ["context manifest/verification 必须是对象"]
    mode = manifest.get("mode")
    if verification.get("mode") != mode:
        return ["context manifest/verification 模式不一致"]
    if mode == "none":
        return [] if verification == {"mode": "none"} else ["none context verification 不能包含其他字段"]
    required = {"mode", "workspace_root", "baseline", "required_paths"}
    if set(verification) != required:
        return ["declared context verification 字段集合无效"]
    root = verification.get("workspace_root")
    if not isinstance(root, str) or not root or not Path(root).is_absolute():
        return ["declared context verification workspace_root 无效"]
    baseline = manifest.get("baseline")
    verified_baseline = verification.get("baseline")
    if not isinstance(baseline, dict) or verified_baseline != baseline:
        return ["declared context verification baseline 与契约不一致"]
    declared_paths = manifest.get("required_paths")
    verified_paths = verification.get("required_paths")
    if not isinstance(declared_paths, list) or not isinstance(verified_paths, list):
        return ["declared context verification required_paths 无效"]
    if len(declared_paths) != len(verified_paths):
        return ["declared context verification required_paths 数量不一致"]
    errors: list[str] = []
    baseline_kind = baseline.get("kind")
    for index, (declared, verified) in enumerate(zip(declared_paths, verified_paths)):
        if not isinstance(declared, dict) or not isinstance(verified, dict):
            errors.append(f"context verification required_paths[{index}] 必须是对象")
            continue
        if verified.get("path") != declared.get("path") or verified.get("type") != declared.get("type"):
            errors.append(f"context verification required_paths[{index}] 路径或类型与契约不一致")
            continue
        if baseline_kind == "git_commit":
            if set(verified) != {"path", "type", "object_id"} or not isinstance(verified.get("object_id"), str) or re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", verified["object_id"]) is None:
                errors.append(f"context verification required_paths[{index}] Git object ID 无效")
        elif baseline_kind == "working_tree":
            if set(verified) != {"path", "type", "sha256"} or not isinstance(verified.get("sha256"), str) or re.fullmatch(r"[a-f0-9]{64}", verified["sha256"]) is None:
                errors.append(f"context verification required_paths[{index}] SHA-256 无效")
    return errors


VERIFICATION_BUDGET_SECONDS = 5.0


def verification_deadline() -> float:
    return time.monotonic() + VERIFICATION_BUDGET_SECONDS


def remaining_time(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ContextVerificationError("声明材料校验时间预算耗尽，未完成验证")
    return remaining


def _file_identity(value: os.stat_result, *, include_ctime: bool = True) -> tuple[int, ...]:
    identity = (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    return identity + (value.st_ctime_ns,) if include_ctime else identity


def _file_digest(path: Path, deadline: float, *, git_algorithm: str | None = None) -> str:
    """Read regular files and detect observable changes; no lock or hard I/O deadline."""
    remaining_time(deadline)
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        with os.fdopen(os.open(path, flags), "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ContextMaterialConflictError(f"必需上下文不是普通文件：{path}")
            digest = hashlib.new(git_algorithm or "sha256")
            if git_algorithm:
                digest.update(f"blob {before.st_size}\0".encode("ascii"))
            while True:
                remaining_time(deadline)
                chunk = handle.read(1024 * 1024)
                remaining_time(deadline)
                if not chunk:
                    break
                digest.update(chunk)
            after = os.fstat(handle.fileno())
            current = path.stat()
            if not stat.S_ISREG(current.st_mode):
                raise ContextMaterialConflictError(f"必需上下文实际类型不再是普通文件：{path}")
            # Windows Python 3.12 stat uses creation time for ctime, while fstat
            # can report change time. Keep the full descriptor-to-descriptor check.
            include_ctime = os.name != "nt"
            if (_file_identity(before) != _file_identity(after)
                    or _file_identity(after, include_ctime=include_ctime)
                    != _file_identity(current, include_ctime=include_ctime)):
                raise ContextVerificationError(f"读取期间必需上下文发生变化，无法完成验证：{path}")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as exc:
        raise ContextMaterialConflictError(f"必需上下文实际文件缺失：{path}") from exc
    except OSError as exc:
        # A special file may replace the candidate between stat and open/read.
        # Recheck once: errno alone does not prove a material conflict. Do not
        # follow a newly introduced symlink or replace the original I/O cause.
        try:
            remaining_time(deadline)
            current = path.lstat()
            remaining_time(deadline)
        except (FileNotFoundError, NotADirectoryError):
            raise ContextMaterialConflictError(f"必需上下文实际文件缺失：{path}") from exc
        except (OSError, ContextVerificationError):
            raise ContextVerificationError(f"必需上下文无法读取：{path}") from exc
        if not (stat.S_ISREG(current.st_mode) or stat.S_ISLNK(current.st_mode)):
            raise ContextMaterialConflictError(f"必需上下文实际类型不再是普通文件：{path}") from exc
        raise ContextVerificationError(f"必需上下文无法读取：{path}") from exc
    remaining_time(deadline)
    return digest.hexdigest()


def sha256_file(path: Path, *, deadline: float | None = None) -> str:
    return _file_digest(path, verification_deadline() if deadline is None else deadline)


def run_git(workspace_root: Path, *arguments: str, deadline: float | None = None) -> str:
    deadline = verification_deadline() if deadline is None else deadline
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "--no-replace-objects", "--literal-pathspecs", "-C", str(workspace_root), *arguments],
            check=True, capture_output=True,
            timeout=remaining_time(deadline),
        )
    except subprocess.TimeoutExpired as exc:
        raise ContextVerificationError("声明材料校验时间预算耗尽，Git 验证未完成") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        operation = arguments[0] if arguments else "unknown"
        raise ContextVerificationError(f"Git 上下文校验无法完成（{operation}）") from exc
    remaining_time(deadline)
    return os.fsdecode(result.stdout)


def _git_candidate(root: Path, relative: str, object_type: str, deadline: float) -> Path:
    candidate = root
    try:
        for part in relative.split("/"):
            remaining_time(deadline)
            candidate = candidate / part
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ContextVerificationError(f"git_commit 不支持符号链接材料：{relative}")
        if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
            raise ContextVerificationError(f"git_commit 不支持非普通文件材料：{relative}")
        actual_type = stat.S_ISREG(metadata.st_mode) if object_type == "blob" else stat.S_ISDIR(metadata.st_mode)
        if not actual_type:
            raise ContextMaterialConflictError(f"必需上下文实际类型与 Git baseline 不一致：{relative}")
        if object_type == "tree":
            # Check directory readability without enumerating ignored/untracked contents.
            with os.scandir(candidate):
                remaining_time(deadline)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise ContextMaterialConflictError(f"必需上下文实际路径缺失：{relative}") from exc
    except OSError as exc:
        raise ContextVerificationError(f"必需上下文无法读取：{relative}") from exc
    return candidate


def _verify_git(root: Path, baseline: dict[str, Any], paths: list[dict[str, Any]],
                deadline: float) -> list[dict[str, Any]]:
    repository_root = Path(run_git(root, "rev-parse", "--show-toplevel", deadline=deadline).rstrip("\n")).resolve()
    if repository_root != root:
        raise ContextVerificationError("context_manifest.workspace_root 必须是 Git 仓库根目录")
    revision = str(baseline["revision"])
    run_git(root, "cat-file", "-e", f"{revision}^{{commit}}", deadline=deadline)
    if run_git(root, "rev-parse", "--verify", "HEAD", deadline=deadline).strip() != revision:
        raise ContextMaterialConflictError("Git 工作区 HEAD 与声明 baseline 不一致")
    names = [item["path"] for item in paths]
    # NUL records preserve special filenames. Only selected subtrees and their
    # ancestor tree entries are listed, not the entire repository.
    listing = run_git(root, "ls-tree", "-r", "-t", "-z", "--full-tree", revision, "--", *names,
                      deadline=deadline)
    entries: dict[str, tuple[str, str, str]] = {}
    for record in listing.split("\0"):
        remaining_time(deadline)
        if record:
            metadata, path = record.split("\t", 1)
            mode, object_type, oid = metadata.split(" ")
            entries[path] = (mode, object_type, oid)
    verified = []
    for item in paths:
        remaining_time(deadline)
        path, expected = item["path"], item["type"]
        entry = entries.get(path)
        if entry is None:
            raise ContextMaterialConflictError(f"Git baseline 缺少必需上下文：{path}")
        if entry[0] in {"120000", "160000"}:
            raise ContextVerificationError(f"git_commit 不支持符号链接或子模块材料：{path}")
        if entry[1] != ("blob" if expected == "file" else "tree"):
            raise ContextMaterialConflictError(f"必需上下文类型与 Git baseline 不一致：{path}")
        verified.append({"path": path, "type": expected, "object_id": entry[2]})
    directories = [item["path"] + "/" for item in paths if item["type"] == "directory"]
    for path, (mode, object_type, oid) in entries.items():
        remaining_time(deadline)
        if path not in names and not any(path.startswith(prefix) for prefix in directories):
            continue
        if mode not in {"100644", "100755", "040000"} or object_type not in {"blob", "tree"}:
            raise ContextVerificationError(f"git_commit 不支持符号链接或子模块材料：{path}")
        candidate = _git_candidate(root, path, object_type, deadline)
        if object_type == "blob":
            algorithm = "sha1" if len(oid) == 40 else "sha256"
            if _file_digest(candidate, deadline, git_algorithm=algorithm) != oid:
                raise ContextMaterialConflictError(f"必需上下文工作区内容与 Git baseline 不一致：{path}")
    # Retain staged/mode changes and non-ignored untracked additions as conflicts.
    # Status alone cannot prove availability or bytes (skip-worktree, filters).
    if run_git(root, "status", "--porcelain=v1", "--untracked-files=all", "--", *names, deadline=deadline):
        raise ContextMaterialConflictError("必需上下文工作区内容与 Git baseline 不一致")
    if run_git(root, "rev-parse", "--verify", "HEAD", deadline=deadline).strip() != revision:
        raise ContextMaterialConflictError("校验期间 Git 工作区 HEAD 与声明 baseline 不一致")
    return verified


def verify_context_manifest(value: Any, *, deadline: float | None = None) -> dict[str, Any]:
    # Prepare reports all verification failures without creating a capability.
    # Claim alone converts confirmed material conflicts to a deny decision.
    try:
        return _verify_context_manifest(value, deadline=deadline)
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as exc:
        raise ContextMaterialConflictError("必需上下文路径缺失或类型不匹配") from exc
    except OSError as exc:
        raise ContextVerificationError("必需上下文无法读取") from exc


def _verify_context_manifest(value: Any, *, deadline: float | None = None) -> dict[str, Any]:
    errors = validate_context_manifest(value)
    if errors:
        raise ContextVerificationError("；".join(errors))
    assert isinstance(value, dict)
    if value["mode"] == "none":
        return {"mode": "none"}
    deadline = verification_deadline() if deadline is None else deadline
    remaining_time(deadline)
    workspace_root = Path(str(value["workspace_root"])).resolve()
    if not stat.S_ISDIR(workspace_root.stat().st_mode):
        raise ContextMaterialConflictError(f"必需上下文工作区不存在或不是目录：{workspace_root}")
    baseline = value["baseline"]
    assert isinstance(baseline, dict)
    baseline_kind = str(baseline["kind"])
    verified_paths: list[dict[str, Any]] = []
    if baseline_kind == "git_commit":
        verified_paths = _verify_git(workspace_root, baseline, value["required_paths"], deadline)
        verified_baseline = {"kind": "git_commit", "revision": str(baseline["revision"])}
    else:
        for item in value["required_paths"]:
            remaining_time(deadline)
            path_value, expected_type = str(item["path"]), str(item["type"])
            candidate = (workspace_root / Path(path_value)).resolve()
            try:
                candidate.relative_to(workspace_root)
            except ValueError as exc:
                raise ContextVerificationError(f"必需上下文路径逃出工作区：{path_value}") from exc
            if not stat.S_ISREG(candidate.stat().st_mode):
                raise ContextMaterialConflictError(f"必需上下文不是文件：{path_value}")
            verified_paths.append({"path": path_value, "type": expected_type, "sha256": sha256_file(candidate, deadline=deadline)})
        verified_baseline = {"kind": "working_tree", "revision": None}
    result = {"mode": "declared", "workspace_root": str(workspace_root), "baseline": verified_baseline, "required_paths": verified_paths}
    verification_errors = validate_context_verification_record(value, result)
    if verification_errors:
        raise ContextVerificationError("；".join(verification_errors))
    remaining_time(deadline)
    return result


_validate_context_manifest = validate_context_manifest
_validate_context_verification_record = validate_context_verification_record
_sha256_file = sha256_file
_run_git = run_git
