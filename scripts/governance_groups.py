"""Strict v7 group persistence and read projections."""
from __future__ import annotations

from typing import Any

try:
    from scripts.governance_errors import GroupNotFoundError, GroupValidationError
    from scripts.governance_semantics import GROUP_ID_MAX_LENGTH, GROUP_MEMBER_LIMIT, GROUP_OBJECTIVE_MAX_LENGTH, SEMANTIC_DEFINITIONS
    from scripts.governance_state_store import StateStore
    from scripts.governance_views import work_item_view
except ModuleNotFoundError:
    from governance_errors import GroupNotFoundError, GroupValidationError
    from governance_semantics import GROUP_ID_MAX_LENGTH, GROUP_MEMBER_LIMIT, GROUP_OBJECTIVE_MAX_LENGTH, SEMANTIC_DEFINITIONS
    from governance_state_store import StateStore
    from governance_views import work_item_view


def _default_state_store() -> StateStore:
    return StateStore()


def validate_group_value(value: Any, *, expected_group_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict): raise GroupValidationError("group 必须是对象")
    required = {"group_id", "objective_summary", "members"}
    if set(value) != required:
        raise GroupValidationError("group 字段必须精确为 group_id、objective_summary、members")
    group_id = value["group_id"]
    objective = value["objective_summary"]
    if not isinstance(group_id, str) or not group_id.strip() or len(group_id.strip()) > GROUP_ID_MAX_LENGTH:
        raise GroupValidationError(f"group_id 必须是 1 至 {GROUP_ID_MAX_LENGTH} 字符的非空字符串")
    group_id = group_id.strip()
    if expected_group_id is not None and group_id != expected_group_id.strip(): raise GroupValidationError("group_id 与 StateStore 键不一致")
    if not isinstance(objective, str) or not objective.strip() or len(objective.strip()) > GROUP_OBJECTIVE_MAX_LENGTH:
        raise GroupValidationError(f"objective_summary 必须是非空且长度不超过 {GROUP_OBJECTIVE_MAX_LENGTH} 的字符串")
    members = value["members"]
    if not isinstance(members, list) or len(members) > GROUP_MEMBER_LIMIT: raise GroupValidationError(f"members 必须是不超过 {GROUP_MEMBER_LIMIT} 项的数组")
    normalized, seen = [], set()
    maximum = int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"])
    for index, member in enumerate(members):
        if not isinstance(member, dict) or set(member) != {"task_id", "required"}:
            raise GroupValidationError(f"members[{index}] 字段必须精确为 task_id、required")
        task_id, required_flag = member["task_id"], member["required"]
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id.strip()) > maximum:
            raise GroupValidationError(f"members[{index}].task_id 无效")
        task_id = task_id.strip()
        if not isinstance(required_flag, bool): raise GroupValidationError(f"members[{index}].required 必须是布尔值")
        if task_id in seen: raise GroupValidationError(f"group 中存在重复 task_id：{task_id}")
        seen.add(task_id); normalized.append({"task_id": task_id, "required": required_flag})
    return {"group_id": group_id, "objective_summary": objective.strip(), "members": normalized}


def upsert_group(value: Any, session_id: str, *, state_store: StateStore | None = None) -> dict[str, Any]:
    normalized, store = validate_group_value(value), state_store or _default_state_store()
    def update(state: dict[str, Any]) -> dict[str, Any]:
        tasks, groups = state.get("tasks"), state.get("groups")
        if not isinstance(tasks, dict): raise GroupValidationError("治理状态缺少 group 引用所需的 tasks 对象")
        # v7 always contains a groups root.  Do not repair a missing root.
        if not isinstance(groups, dict): raise GroupValidationError("治理状态 groups 字段必须是对象")
        missing = [item["task_id"] for item in normalized["members"] if not isinstance(tasks.get(item["task_id"]), dict)]
        if missing: raise GroupValidationError(f"group 引用的 task 不存在：{', '.join(missing)}")
        old = groups.get(normalized["group_id"])
        if old is not None and not isinstance(old, dict): raise GroupValidationError("已有 group 记录必须是对象")
        groups[normalized["group_id"]] = normalized
        return {"status": "updated" if old is not None else "created", "group_id": normalized["group_id"]}
    return store.update(session_id, update, required_fields=("tasks", "agents", "groups"))


def derive_group_snapshot(state: dict[str, Any], group: dict[str, Any], *, session_id: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    validated = validate_group_value(group, expected_group_id=str(group.get("group_id") or ""))
    tasks = state.get("tasks")
    if not isinstance(tasks, dict): raise GroupValidationError("治理状态缺少 group 派生所需的 tasks 对象")
    members, issues, incomplete, ready_flags, required_actions = [], [], False, [], []
    for member in validated["members"]:
        task_id, required = member["task_id"], member["required"]
        view = None
        if isinstance(tasks.get(task_id), dict):
            view, item_issues, item_incomplete = work_item_view(state, task_id, session_id=session_id)
            issues.extend(item_issues); incomplete = incomplete or item_incomplete
        else:
            issues.append({"code": "group_member_missing", "message": "group member task 不存在", "context": {"session_id": session_id, "task_id": task_id, "group_id": validated["group_id"]}}); incomplete = True
        notification = view.get("terminal_notification") if isinstance(view, dict) else {}
        tombstoned = isinstance(view, dict) and view.get("lifecycle") == "tombstoned"
        material_ready = tombstoned or bool(isinstance(notification, dict) and notification.get("state") == "observed")
        action = bool(isinstance(view, dict) and view.get("action_required") is True)
        members.append({"task_id": task_id, "required": required, "exists": view is not None, "lifecycle": view.get("lifecycle") if view else "indeterminate", "action_required": action, "terminal_notification": notification if view else {"state": "unknown", "attempt": None, "source": None, "terminal_status": None}, "allowed_actions": view.get("allowed_actions", ["reconcile"]) if view else ["reconcile"]})
        if required: ready_flags.append(material_ready); required_actions.append(action)
    return {"group_id": validated["group_id"], "objective_summary": validated["objective_summary"], "members": members, "summary_ready": bool(ready_flags) and all(ready_flags), "group_action_required": bool(required_actions) and any(required_actions)}, issues, incomplete


def read_group(session_id: str, group_id: str, *, state_store: StateStore | None = None) -> dict[str, Any]:
    if not isinstance(group_id, str) or not group_id.strip(): raise GroupValidationError("group_id 必须是非空字符串")
    group_id, store = group_id.strip(), state_store or _default_state_store()
    state = store.read(session_id, required_fields=("tasks", "agents", "groups"))
    groups = state.get("groups")
    if not isinstance(groups, dict) or not isinstance(groups.get(group_id), dict): raise GroupNotFoundError(f"group 不存在：{group_id}")
    return derive_group_snapshot(state, groups[group_id], session_id=session_id)[0]
