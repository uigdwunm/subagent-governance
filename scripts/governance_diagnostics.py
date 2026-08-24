"""Strictly read-only diagnostics for current v7 state files.

No StateStore is imported here: diagnostics must not create a lock, directory,
or state file as a side effect of inspection.
"""
from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from typing import Any

try:
    from scripts.governance_errors import DiagnosticReadError
    from scripts.governance_groups import derive_group_snapshot, validate_group_value
    from scripts.governance_semantics import DIAGNOSTIC_ATTEMPT_LIMIT, DIAGNOSTIC_GROUP_LIMIT, DIAGNOSTIC_ISSUE_LIMIT, DIAGNOSTIC_OUTPUT_BYTES, DIAGNOSTIC_SESSION_LIMIT, MAX_STATE_BYTES, STATE_FORMAT_VERSION
    from scripts.governance_state import validate_current_state_format
    from scripts.governance_storage import PrivateStorageError, read_private_bytes
    from scripts.governance_store_support import owned_by_current_user, private_permissions_safe, safe_filename
    from scripts.governance_views import action_required_records, recent_activity_records, work_item_views
except ModuleNotFoundError:
    from governance_errors import DiagnosticReadError
    from governance_groups import derive_group_snapshot, validate_group_value
    from governance_semantics import DIAGNOSTIC_ATTEMPT_LIMIT, DIAGNOSTIC_GROUP_LIMIT, DIAGNOSTIC_ISSUE_LIMIT, DIAGNOSTIC_OUTPUT_BYTES, DIAGNOSTIC_SESSION_LIMIT, MAX_STATE_BYTES, STATE_FORMAT_VERSION
    from governance_state import validate_current_state_format
    from governance_storage import PrivateStorageError, read_private_bytes
    from governance_store_support import owned_by_current_user, private_permissions_safe, safe_filename
    from governance_views import action_required_records, recent_activity_records, work_item_views


def diagnostic_issue(code: str, message: str, **context: Any) -> dict[str, Any]:
    allowed = {key: (value[:600] if isinstance(value, str) else value) for key, value in context.items() if key in {"session_id", "path", "field", "task_id", "attempt", "group_id", "fact"} and isinstance(value, (str, int, bool))}
    return {"code": code, "message": str(message)[:600], "context": allowed}


def _issue_key(issue: dict[str, Any]) -> tuple[Any, ...]:
    context = issue.get("context") if isinstance(issue.get("context"), dict) else {}
    return (str(issue.get("code") or ""), str(context.get("session_id") or ""), str(context.get("task_id") or ""), int(context.get("attempt") or 0), str(context.get("group_id") or ""), str(context.get("field") or ""), str(context.get("path") or ""))


def _read_session_file_read_only(path: Path, *, requested_session: str | None = None) -> dict[str, Any]:
    codes = {"symlink": ("session_symlink", "Session 状态文件是符号链接"), "not_regular": ("session_not_regular", "Session 状态目标不是普通文件"), "owner_mismatch": ("session_owner_mismatch", "Session 状态文件所有者不安全"), "permissions_unsafe": ("session_permissions_unsafe", "Session 状态文件权限向 group/other 开放"), "oversized": ("session_oversized", f"Session 状态文件超过 {MAX_STATE_BYTES} 字节上限"), "unreadable": ("session_unreadable", "Session 状态文件无法安全读取")}
    def factory(code: str, _message: str) -> Exception:
        mapped = codes.get(code, codes["unreadable"]); return DiagnosticReadError(mapped[0], mapped[1], context={"path": str(path)})
    try:
        raw = read_private_bytes(path, label="Session 状态文件", max_bytes=MAX_STATE_BYTES, owned_by_current_user=owned_by_current_user, private_permissions_safe=private_permissions_safe, error_factory=factory)
    except FileNotFoundError as exc: raise DiagnosticReadError("session_missing", "请求的 Session 状态文件不存在", context={"path": str(path)}) from exc
    except DiagnosticReadError: raise
    except PrivateStorageError as exc: raise DiagnosticReadError("session_unreadable", "Session 状态文件无法安全读取", context={"path": str(path)}) from exc
    try: value = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc: raise DiagnosticReadError("session_non_utf8", "Session 状态文件不是有效 UTF-8", context={"path": str(path)}) from exc
    except json.JSONDecodeError as exc: raise DiagnosticReadError("session_json_invalid", "Session 状态文件不是有效 JSON", context={"path": str(path)}) from exc
    if not isinstance(value, dict): raise DiagnosticReadError("session_root_invalid", "Session 状态文件根节点不是对象", context={"path": str(path)})
    stored = value.get("session_id")
    if not isinstance(stored, str) or not stored.strip(): raise DiagnosticReadError("session_root_invalid", "Session 状态缺少有效 session_id", context={"path": str(path), "field": "session_id"})
    if requested_session is not None and stored != requested_session: raise DiagnosticReadError("session_root_invalid", "Session 状态中的 session_id 与请求不匹配", context={"path": str(path), "session_id": stored})
    # v5 and every historical format are deliberately unsupported.  We do not
    # construct a partial current model from them.
    if value.get("state_format_version") != STATE_FORMAT_VERSION:
        raise DiagnosticReadError("unsupported_format", "仅支持当前 state-v7 格式；历史状态不会被解释或迁移", context={"path": str(path), "session_id": stored})
    violations = validate_current_state_format(value)
    if violations:
        paths = ", ".join(str(issue.path) for issue in violations[:8])
        raise DiagnosticReadError("current_format_invalid", "当前 v7 状态格式非法：" + paths, context={"path": str(path), "session_id": stored})
    return value


def _session_snapshot(state: dict[str, Any], *, path: Path, now: int) -> tuple[dict[str, Any], bool, int]:
    session_id = str(state["session_id"])
    views, issues, incomplete = work_item_views(state, session_id=session_id, now=now)
    views = views[:DIAGNOSTIC_ATTEMPT_LIMIT]
    omitted = max(0, len(work_item_views(state, session_id=session_id, now=now)[0]) - len(views))
    groups, raw_groups = [], state.get("groups") if isinstance(state.get("groups"), dict) else {}
    for group_id, group in sorted(raw_groups.items(), key=lambda pair: str(pair[0]))[:DIAGNOSTIC_GROUP_LIMIT]:
        try:
            snapshot, group_issues, group_incomplete = derive_group_snapshot(state, validate_group_value(group, expected_group_id=str(group_id)), session_id=session_id)
            groups.append(snapshot); issues.extend(group_issues); incomplete = incomplete or group_incomplete
        except Exception as exc:
            issues.append(diagnostic_issue("current_required_field_invalid", f"group 记录非法：{exc}", session_id=session_id, group_id=str(group_id), field="groups")); incomplete = True
    omitted += max(0, len(raw_groups) - len(groups))
    for record in action_required_records(state):
        if record.get("attempt"):
            # The view already validates transition shape; this is an actionable
            # cross-field fact, not a repair attempt.
            if record.get("_status") == "unknown": issues.append(diagnostic_issue("identity_or_execution_indeterminate", "action-required attempt 缺少确认 execution state", session_id=session_id, task_id=record["task_id"], attempt=record["attempt"]))
    health = state.get("health") if isinstance(state.get("health"), dict) else {}
    if health.get("status") != "ok": issues.append(diagnostic_issue("health_not_ok", "persisted health 不是 ok", session_id=session_id, field="health.status"))
    issues.sort(key=_issue_key)
    if len(issues) > DIAGNOSTIC_ISSUE_LIMIT:
        omitted += len(issues) - DIAGNOSTIC_ISSUE_LIMIT; issues = issues[:DIAGNOSTIC_ISSUE_LIMIT]
    return {"session_id": session_id, "component_health": {"status": health.get("status", "unknown"), "source": "persisted_health"}, "counts": {"tasks": len(state.get("tasks", {})), "work_items": len(views), "attempts": sum(len((task or {}).get("executions", {})) for task in state.get("tasks", {}).values() if isinstance(task, dict)), "action_required": len(action_required_records(state)), "recent_activity": len(recent_activity_records(state, now=now)), "groups": len(raw_groups), "tombstones": len(state.get("tombstones", {}))}, "work_items": views, "groups": groups, "issues": issues}, incomplete or bool(omitted), omitted


def _base(root: Path, session_id: str | None) -> dict[str, Any]:
    return {"data_root": str(root), "data_root_exists": bool(root.exists() or root.is_symlink()), "scope": "single_session" if session_id is not None else "all_sessions", "requested_session": session_id, "scan": {"requested": 0, "checked": 0, "succeeded": 0, "failed": 0, "omitted": 0, "complete": True}, "sessions": [], "issues": [], "boundaries": {"transport_opaque": True, "provider_status": "not_checked", "hook_trust": "not_checked", "repairs_state": False, "writes_files": False}}


def diagnostic_output_bytes(document: dict[str, Any]) -> bytes: return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_diagnostic_document(session_id: str | None, data_root: Path) -> tuple[dict[str, Any], int]:
    # abspath preserves the lexical input path and never substitutes a symlink
    # target into user-visible diagnostics.
    root = Path(os.path.abspath(os.fspath(data_root.expanduser())))
    document, scan, incomplete = _base(root, session_id), None, False
    scan = document["scan"]
    sessions_root = root / "sessions"
    try:
        root_metadata = root.lstat(); sessions_metadata = sessions_root.lstat()
        if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(sessions_metadata.st_mode) or not stat.S_ISDIR(sessions_metadata.st_mode): raise OSError("not a regular directory")
    except FileNotFoundError:
        if session_id is None: return document, 0
        path = sessions_root / f"{safe_filename(session_id)}.json"; scan.update({"requested": 1, "checked": 1, "failed": 1, "complete": False}); document["issues"].append(diagnostic_issue("session_missing", "请求的 Session 状态文件不存在", session_id=session_id, path=str(path))); return document, 1
    except OSError:
        scan["complete"] = False; document["issues"].append(diagnostic_issue("scan_incomplete", "数据根或 sessions 目录不是可扫描的普通目录", path=str(sessions_root))); return document, 1
    if session_id is not None: paths = [sessions_root / f"{safe_filename(session_id)}.json"]
    else:
        try:
            with os.scandir(sessions_root) as iterator: paths = sorted([Path(entry.path) for entry in iterator if entry.name.endswith(".json")], key=lambda path: path.name)
        except OSError as exc: document["issues"].append(diagnostic_issue("scan_incomplete", f"sessions 目录无法列举：{exc}", path=str(sessions_root))); scan["complete"] = False; return document, 1
    scan["requested"] = len(paths)
    if len(paths) > DIAGNOSTIC_SESSION_LIMIT: scan["omitted"] += len(paths) - DIAGNOSTIC_SESSION_LIMIT; paths = paths[:DIAGNOSTIC_SESSION_LIMIT]; incomplete = True
    snapshots = []
    for path in paths:
        scan["checked"] += 1
        try: state = _read_session_file_read_only(path, requested_session=session_id)
        except DiagnosticReadError as exc:
            scan["failed"] += 1; incomplete = True; document["issues"].append(diagnostic_issue(exc.code, str(exc), **exc.context)); continue
        snapshot, partial, omitted = _session_snapshot(state, path=path, now=int(time.time()))
        snapshots.append((snapshot, path.name)); scan["succeeded"] += 1; scan["omitted"] += omitted; incomplete = incomplete or partial
    document["sessions"] = [item for item, _ in sorted(snapshots, key=lambda pair: (pair[0]["session_id"], pair[1]))]
    document["issues"].sort(key=_issue_key); scan["complete"] = not incomplete and scan["failed"] == 0 and scan["omitted"] == 0
    while len(diagnostic_output_bytes(document)) > DIAGNOSTIC_OUTPUT_BYTES and document["sessions"]:
        document["sessions"].pop(); scan["succeeded"] -= 1; scan["omitted"] += 1; scan["complete"] = False
    if len(diagnostic_output_bytes(document)) > DIAGNOSTIC_OUTPUT_BYTES:
        document["issues"] = [diagnostic_issue("scan_incomplete", "诊断输出超过体积上限，详细问题未展开", fact=f"output_limit={DIAGNOSTIC_OUTPUT_BYTES}")]
        scan["omitted"] += 1; scan["complete"] = False
    return document, 0 if scan["complete"] else 1


def diagnose(session_id: str | None, data_root: Path) -> tuple[dict[str, Any], int]:
    """Return the diagnostic document and status without performing output."""
    return build_diagnostic_document(session_id, data_root)
