"""Context manifest structure and verification protocol.

Structure validators are pure.  Only ``verify_context_manifest`` performs
filesystem or Git work.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any

try:
    from scripts.governance_errors import ContextVerificationError
    from scripts.governance_validation import required_fields
except ModuleNotFoundError:
    from governance_errors import ContextVerificationError
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def run_git(workspace_root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(["git", "-C", str(workspace_root), *arguments], check=True, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        detail = (exc.stderr or exc.stdout or "").strip() if isinstance(exc, subprocess.CalledProcessError) else ""
        suffix = f"：{detail[:600]}" if detail else ""
        raise ContextVerificationError(f"Git 上下文校验失败（{' '.join(arguments)}）{suffix}") from exc
    return result.stdout.strip()


def verify_context_manifest(value: Any) -> dict[str, Any]:
    errors = validate_context_manifest(value)
    if errors:
        raise ContextVerificationError("；".join(errors))
    assert isinstance(value, dict)
    if value["mode"] == "none":
        return {"mode": "none"}
    workspace_root = Path(str(value["workspace_root"])).resolve()
    if not workspace_root.is_dir():
        raise ContextVerificationError(f"必需上下文工作区不存在或不是目录：{workspace_root}")
    baseline = value["baseline"]
    assert isinstance(baseline, dict)
    baseline_kind = str(baseline["kind"])
    verified_paths: list[dict[str, Any]] = []
    if baseline_kind == "git_commit":
        repository_root = Path(run_git(workspace_root, "rev-parse", "--show-toplevel")).resolve()
        if repository_root != workspace_root:
            raise ContextVerificationError("context_manifest.workspace_root 必须是 Git 仓库根目录：" f"声明 {workspace_root}，实际 {repository_root}")
        revision = str(baseline["revision"])
        run_git(workspace_root, "cat-file", "-e", f"{revision}^{{commit}}")
        current_head = run_git(workspace_root, "rev-parse", "--verify", "HEAD")
        if current_head != revision:
            raise ContextVerificationError(f"Git 工作区 HEAD 与声明 baseline 不一致：HEAD={current_head}，baseline={revision}")
        for item in value["required_paths"]:
            path_value, expected_type = str(item["path"]), str(item["type"])
            object_spec = f"{revision}:{path_value}"
            try:
                object_type = run_git(workspace_root, "cat-file", "-t", object_spec)
                object_id = run_git(workspace_root, "rev-parse", "--verify", object_spec)
            except ContextVerificationError as exc:
                raise ContextVerificationError(f"Git baseline {revision} 缺少必需上下文 {path_value}") from exc
            expected_object_type = "blob" if expected_type == "file" else "tree"
            if object_type != expected_object_type:
                raise ContextVerificationError(f"必需上下文类型不匹配：{path_value} 声明为 {expected_type}，Git 对象类型为 {object_type}")
            dirty = run_git(workspace_root, "status", "--porcelain=v1", "--untracked-files=all", "--", path_value)
            if dirty:
                raise ContextVerificationError(f"必需上下文工作区内容与 Git baseline 不一致：{path_value}")
            verified_paths.append({"path": path_value, "type": expected_type, "object_id": object_id})
        verified_baseline = {"kind": "git_commit", "revision": revision}
    else:
        for item in value["required_paths"]:
            path_value, expected_type = str(item["path"]), str(item["type"])
            candidate = (workspace_root / Path(path_value)).resolve()
            try:
                candidate.relative_to(workspace_root)
            except ValueError as exc:
                raise ContextVerificationError(f"必需上下文路径逃出工作区：{path_value}") from exc
            if not candidate.exists():
                raise ContextVerificationError(f"必需上下文不存在：{path_value}")
            if not candidate.is_file():
                raise ContextVerificationError(f"必需上下文不是文件：{path_value}")
            verified_paths.append({"path": path_value, "type": expected_type, "sha256": sha256_file(candidate)})
        verified_baseline = {"kind": "working_tree", "revision": None}
    result = {"mode": "declared", "workspace_root": str(workspace_root), "baseline": verified_baseline, "required_paths": verified_paths}
    verification_errors = validate_context_verification_record(value, result)
    if verification_errors:
        raise ContextVerificationError("；".join(verification_errors))
    return result


_validate_context_manifest = validate_context_manifest
_validate_context_verification_record = validate_context_verification_record
_sha256_file = sha256_file
_run_git = run_git
