"""Strict validation for the only supported persisted state format."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

try:
    from scripts.governance_errors import StateValidationError
    from scripts.governance_semantics import (
        DISPATCH_STATES, OBSERVATION_SOURCES, OBSERVED_STATES, PARENT_ACTIONS,
        PARENT_DISPOSITION_REASON_MAX_LENGTH, REQUIRED_CLOSURE_RECORD_FIELDS,
        REQUIRED_DISPATCH_RECORD_FIELDS, REQUIRED_EXECUTION_FIELDS,
        REQUIRED_OBSERVATION_RECORD_FIELDS, REQUIRED_TASK_CONTAINER_FIELDS,
        REQUIRED_WORK_ITEM_FIELDS, SEMANTIC_DEFINITIONS, SEMANTIC_RULES,
        STATE_FORMAT_VERSION,
    )
except ModuleNotFoundError:
    from governance_errors import StateValidationError
    from governance_semantics import (
        DISPATCH_STATES, OBSERVATION_SOURCES, OBSERVED_STATES, PARENT_ACTIONS,
        PARENT_DISPOSITION_REASON_MAX_LENGTH, REQUIRED_CLOSURE_RECORD_FIELDS,
        REQUIRED_DISPATCH_RECORD_FIELDS, REQUIRED_EXECUTION_FIELDS,
        REQUIRED_OBSERVATION_RECORD_FIELDS, REQUIRED_TASK_CONTAINER_FIELDS,
        REQUIRED_WORK_ITEM_FIELDS, SEMANTIC_DEFINITIONS, SEMANTIC_RULES,
        STATE_FORMAT_VERSION,
    )


@dataclass(frozen=True)
class StateFormatIssue:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def initial_plane_records() -> dict[str, dict[str, Any]]:
    return {
        "dispatch_record": {"dispatch_state": "prepared", "tool_use_id": None, "dispatch_target": None},
        "observation_record": {"source": None, "observed_state": "not_observed", "observed_at": None, "terminal_status": None},
        "closure_record": {"reason": None, "closed_at": None, "parent_action": None},
    }


def _execution_key(value: Any) -> int | None:
    return int(value) if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value) else None


def _timestamp(value: Any, *, nullable: bool = False) -> bool:
    return (nullable and value is None) or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


def _text(value: Any, maximum: int, *, nullable: bool = False) -> bool:
    return (nullable and value is None) or (isinstance(value, str) and bool(value.strip()) and len(value) <= maximum)


def _fields(issues: list[StateFormatIssue], value: Any, path: str, required: set[str], allowed: set[str] | None = None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        issues.append(StateFormatIssue(path, "必须是对象"))
        return None
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - (allowed if allowed is not None else required))
    if missing:
        issues.append(StateFormatIssue(path, "缺少字段 " + ", ".join(missing)))
    if unknown:
        issues.append(StateFormatIssue(path, "包含未知字段 " + ", ".join(unknown)))
    return value


def _validate_planes(issues: list[StateFormatIssue], execution: dict[str, Any], path: str) -> None:
    dispatch = _fields(issues, execution.get("dispatch_record"), f"{path}.dispatch_record", set(REQUIRED_DISPATCH_RECORD_FIELDS))
    observation = _fields(issues, execution.get("observation_record"), f"{path}.observation_record", set(REQUIRED_OBSERVATION_RECORD_FIELDS))
    closure = _fields(issues, execution.get("closure_record"), f"{path}.closure_record", set(REQUIRED_CLOSURE_RECORD_FIELDS))
    if dispatch is not None:
        if dispatch.get("dispatch_state") not in DISPATCH_STATES:
            issues.append(StateFormatIssue(f"{path}.dispatch_record.dispatch_state", "使用未知枚举值"))
        for field in ("tool_use_id", "dispatch_target"):
            if not _text(dispatch.get(field), 1024, nullable=True):
                issues.append(StateFormatIssue(f"{path}.dispatch_record.{field}", "必须是非空字符串或 null"))
    if observation is not None:
        if observation.get("source") is not None and observation.get("source") not in OBSERVATION_SOURCES:
            issues.append(StateFormatIssue(f"{path}.observation_record.source", "使用未知枚举值"))
        if observation.get("observed_state") not in OBSERVED_STATES:
            issues.append(StateFormatIssue(f"{path}.observation_record.observed_state", "使用未知枚举值"))
        if not _timestamp(observation.get("observed_at"), nullable=True):
            issues.append(StateFormatIssue(f"{path}.observation_record.observed_at", "必须是非负整数或 null"))
        terminal = observation.get("terminal_status")
        if terminal not in {None, "completed", "stopped", "interrupted"}:
            issues.append(StateFormatIssue(f"{path}.observation_record.terminal_status", "无效"))
        if observation.get("observed_state") == "terminal" and terminal is None:
            issues.append(StateFormatIssue(f"{path}.observation_record.terminal_status", "terminal observation 必须提供终态"))
    if closure is not None:
        if closure.get("parent_action") is not None and closure.get("parent_action") not in PARENT_ACTIONS:
            issues.append(StateFormatIssue(f"{path}.closure_record.parent_action", "使用未知枚举值"))
        reason, closed_at = closure.get("reason"), closure.get("closed_at")
        if not _text(reason, PARENT_DISPOSITION_REASON_MAX_LENGTH, nullable=True):
            issues.append(StateFormatIssue(f"{path}.closure_record.reason", "必须是非空字符串或 null"))
        if not _timestamp(closed_at, nullable=True):
            issues.append(StateFormatIssue(f"{path}.closure_record.closed_at", "必须是非负整数或 null"))
        if (reason is None) != (closed_at is None):
            issues.append(StateFormatIssue(f"{path}.closure_record", "reason 与 closed_at 必须同时存在或同时为空"))


def _validate_task_contract(issues: list[StateFormatIssue], value: Any, path: str) -> None:
    contract = _fields(issues, value, path, set(SEMANTIC_RULES["task_contract_fields"]))
    if contract is None:
        return
    features = _fields(issues, contract.get("task_features"), f"{path}.task_features", {"risk", "read_only", "writes_files", "destructive", "production", "concurrent_write"})
    if features is not None:
        if features.get("risk") not in SEMANTIC_DEFINITIONS["risk"]["enum"]:
            issues.append(StateFormatIssue(f"{path}.task_features.risk", "使用未知枚举值"))
        for field in set(features) - {"risk"}:
            if not isinstance(features.get(field), bool):
                issues.append(StateFormatIssue(f"{path}.task_features.{field}", "必须是布尔值"))
    for field in ("objective", "background"):
        if not _text(contract.get(field), int(SEMANTIC_DEFINITIONS["business_text"]["maxLength"])):
            issues.append(StateFormatIssue(f"{path}.{field}", "必须是非空文本"))


def _validate_pending(issues: list[StateFormatIssue], value: Any, path: str) -> None:
    base = {"target", "attempt", "task_ref", "operation_type", "phase", "created_at", "tool_use_id", "claimed_at"}
    pending = _fields(issues, value, path, base, base | {"authorized_recovery", "resume_contract", "resume_contract_digest", "resume_context_verification", "prepared_on_attempt"})
    if pending is None:
        return
    operation = pending.get("operation_type")
    if operation not in {"normal_message", "interrupt", "platform_recovery", "business_resume"}:
        issues.append(StateFormatIssue(f"{path}.operation_type", "使用未知 operation type"))
    if pending.get("phase") not in {"prepared", "claimed"}:
        issues.append(StateFormatIssue(f"{path}.phase", "使用未知 phase"))
    if not _text(pending.get("target"), 1024) or not _timestamp(pending.get("created_at")):
        issues.append(StateFormatIssue(path, "target 或 created_at 无效"))
    if isinstance(pending.get("attempt"), bool) or not isinstance(pending.get("attempt"), int) or pending.get("attempt", 0) < 1:
        issues.append(StateFormatIssue(f"{path}.attempt", "必须是正整数"))
    if not isinstance(pending.get("task_ref"), str) or re.fullmatch(r"[a-f0-9]{12}(?:[a-f0-9]{4}){0,5}", pending["task_ref"]) is None:
        issues.append(StateFormatIssue(f"{path}.task_ref", "无效"))
    if not _text(pending.get("tool_use_id"), 1024, nullable=True) or not _timestamp(pending.get("claimed_at"), nullable=True):
        issues.append(StateFormatIssue(path, "claim 字段无效"))
    if pending.get("phase") == "claimed" and (pending.get("tool_use_id") is None or pending.get("claimed_at") is None):
        issues.append(StateFormatIssue(path, "claimed action 缺少 claim 字段"))
    if operation == "business_resume":
        for field in ("resume_contract", "resume_contract_digest", "resume_context_verification", "prepared_on_attempt"):
            if field not in pending:
                issues.append(StateFormatIssue(path, f"business_resume 缺少字段 {field}"))
        _validate_task_contract(issues, pending.get("resume_contract"), f"{path}.resume_contract")
        if not isinstance(pending.get("resume_contract_digest"), str) or re.fullmatch(r"[a-f0-9]{64}", pending["resume_contract_digest"]) is None:
            issues.append(StateFormatIssue(f"{path}.resume_contract_digest", "无效"))
        if not isinstance(pending.get("resume_context_verification"), dict):
            issues.append(StateFormatIssue(f"{path}.resume_context_verification", "必须是对象"))


def validate_current_execution_planes(execution: dict[str, Any]) -> None:
    """Compatibility helper for bounded diagnostics of one canonical execution."""
    issues: list[StateFormatIssue] = []
    _validate_planes(issues, execution, "execution")
    if issues:
        raise StateValidationError("invalid_current_execution: " + "; ".join(map(str, issues)))


def validate_current_state_format(value: Any) -> list[StateFormatIssue]:
    """Return path-specific current-format violations without writing state."""
    issues: list[StateFormatIssue] = []
    root = _fields(issues, value, "$", {"state_format_version", "session_id", "tasks", "agents", "health", "tombstones", "groups"})
    if root is None:
        return issues
    if root.get("state_format_version") != STATE_FORMAT_VERSION or isinstance(root.get("state_format_version"), bool):
        issues.append(StateFormatIssue("$.state_format_version", f"当前仅支持 {STATE_FORMAT_VERSION}"))
    if not _text(root.get("session_id"), 4000):
        issues.append(StateFormatIssue("$.session_id", "必须是非空字符串"))
    tasks = root.get("tasks")
    if not isinstance(tasks, dict):
        issues.append(StateFormatIssue("$.tasks", "必须是对象"))
    else:
        task_max = int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"])
        for task_id, task in tasks.items():
            task_path = f"$.tasks.{task_id!r}"
            if not _text(task_id, task_max):
                issues.append(StateFormatIssue(task_path, "task key 无效"))
            container = _fields(issues, task, task_path, set(REQUIRED_TASK_CONTAINER_FIELDS))
            if container is None:
                continue
            if container.get("managed") is not True:
                issues.append(StateFormatIssue(f"{task_path}.managed", "current-state 只允许 true"))
            work_item = _fields(issues, container.get("work_item"), f"{task_path}.work_item", set(REQUIRED_WORK_ITEM_FIELDS))
            executions = container.get("executions")
            if not isinstance(executions, dict) or not executions:
                issues.append(StateFormatIssue(f"{task_path}.executions", "必须是非空对象"))
                continue
            if work_item is not None:
                current_attempt = work_item.get("current_attempt")
                if work_item.get("lifecycle") not in {"open", "tombstoned"}:
                    issues.append(StateFormatIssue(f"{task_path}.work_item.lifecycle", "无效"))
                if isinstance(current_attempt, bool) or not isinstance(current_attempt, int) or current_attempt < 1 or str(current_attempt) not in executions:
                    issues.append(StateFormatIssue(f"{task_path}.work_item.current_attempt", "必须关联 canonical execution"))
            for key, execution in executions.items():
                execution_path = f"{task_path}.executions.{key!r}"
                if _execution_key(key) is None:
                    issues.append(StateFormatIssue(execution_path, "execution key 无效"))
                record = _fields(issues, execution, execution_path, set(REQUIRED_EXECUTION_FIELDS), set(REQUIRED_EXECUTION_FIELDS) | {"pending_action", "last_lifecycle_operation", "initial_preparation_rollback"})
                if record is None:
                    continue
                if not isinstance(record.get("task_ref"), str) or re.fullmatch(r"[a-f0-9]{12}(?:[a-f0-9]{4}){0,5}", record["task_ref"]) is None:
                    issues.append(StateFormatIssue(f"{execution_path}.task_ref", "无效"))
                if record.get("task_name") is not None and not _text(record.get("task_name"), 64):
                    issues.append(StateFormatIssue(f"{execution_path}.task_name", "必须是非空字符串或 null"))
                elif record.get("task_name") is not None and re.fullmatch(SEMANTIC_RULES["task_name"]["pattern"], record["task_name"]) is None:
                    issues.append(StateFormatIssue(f"{execution_path}.task_name", "不符合 task name 格式"))
                if record.get("resolved_mode") not in SEMANTIC_DEFINITIONS["resolved_mode"]["enum"]:
                    issues.append(StateFormatIssue(f"{execution_path}.resolved_mode", "无效"))
                summary = _fields(issues, record.get("contract_summary"), f"{execution_path}.contract_summary", {"objective", "model"})
                if summary is not None and (not _text(summary.get("objective"), 600) or not _text(summary.get("model"), 128, nullable=True)):
                    issues.append(StateFormatIssue(f"{execution_path}.contract_summary", "无效"))
                if not isinstance(record.get("contract_digest"), str) or re.fullmatch(r"[a-f0-9]{64}", record["contract_digest"]) is None:
                    issues.append(StateFormatIssue(f"{execution_path}.contract_digest", "无效"))
                for field in ("spawn_retry_count", "recovery_count", "updated_at"):
                    if not _timestamp(record.get(field)):
                        issues.append(StateFormatIssue(f"{execution_path}.{field}", "必须是非负整数"))
                for field in ("spawn_retry_count", "recovery_count"):
                    if isinstance(record.get(field), int) and not isinstance(record.get(field), bool) and record[field] > 2:
                        issues.append(StateFormatIssue(f"{execution_path}.{field}", "不能超过 2"))
                _validate_planes(issues, record, execution_path)
                if "pending_action" in record:
                    _validate_pending(issues, record["pending_action"], f"{execution_path}.pending_action")
                if "last_lifecycle_operation" in record:
                    lifecycle = _fields(issues, record["last_lifecycle_operation"], f"{execution_path}.last_lifecycle_operation", {"operation_type", "tool_use_id", "call_observation"}, {"operation_type", "tool_use_id", "call_observation", "target_observation"})
                    if lifecycle is not None and lifecycle.get("operation_type") not in {"platform_recovery", "business_resume", "interrupt"}:
                        issues.append(StateFormatIssue(f"{execution_path}.last_lifecycle_operation.operation_type", "无效"))
                    if lifecycle is not None and (not _text(lifecycle.get("tool_use_id"), 1024) or lifecycle.get("call_observation") not in {"success", "failed", "unknown"}):
                        issues.append(StateFormatIssue(f"{execution_path}.last_lifecycle_operation", "字段无效"))
                if "initial_preparation_rollback" in record:
                    marker = _fields(issues, record["initial_preparation_rollback"], f"{execution_path}.initial_preparation_rollback", {"status", "task_ref", "observed_at", "error"})
                    if marker is not None and (marker.get("status") != "rollback_incomplete" or not isinstance(marker.get("task_ref"), str) or re.fullmatch(r"[a-f0-9]{12}(?:[a-f0-9]{4}){0,5}", marker["task_ref"]) is None or not _timestamp(marker.get("observed_at")) or not _text(marker.get("error"), 600)):
                        issues.append(StateFormatIssue(f"{execution_path}.initial_preparation_rollback", "rollback marker 无效"))
    agents = root.get("agents")
    if not isinstance(agents, dict):
        issues.append(StateFormatIssue("$.agents", "必须是对象"))
    else:
        for target, identity in agents.items():
            item = _fields(issues, identity, f"$.agents.{target!r}", {"task_id", "attempt"})
            if not _text(target, 1024):
                issues.append(StateFormatIssue(f"$.agents.{target!r}", "agent target 无效"))
            if item is not None and (not _text(item.get("task_id"), int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"])) or isinstance(item.get("attempt"), bool) or not isinstance(item.get("attempt"), int) or item["attempt"] < 1):
                issues.append(StateFormatIssue(f"$.agents.{target!r}", "canonical identity 无效"))
    tombstones = root.get("tombstones")
    if not isinstance(tombstones, dict):
        issues.append(StateFormatIssue("$.tombstones", "必须是对象"))
    else:
        for key, tombstone in tombstones.items():
            item = _fields(issues, tombstone, f"$.tombstones.{key!r}", {"task_ref", "dispatch_target", "close_reason", "closed_at"})
            if not isinstance(key, str) or re.fullmatch(r".+:[1-9][0-9]*", key) is None:
                issues.append(StateFormatIssue(f"$.tombstones.{key!r}", "tombstone key 无效"))
            if item is not None:
                if not isinstance(item.get("task_ref"), str) or re.fullmatch(r"[a-f0-9]{12}(?:[a-f0-9]{4}){0,5}", item["task_ref"]) is None:
                    issues.append(StateFormatIssue(f"$.tombstones.{key!r}.task_ref", "无效"))
                if not _text(item.get("dispatch_target"), 1024, nullable=True) or not _text(item.get("close_reason"), PARENT_DISPOSITION_REASON_MAX_LENGTH) or not _timestamp(item.get("closed_at")):
                    issues.append(StateFormatIssue(f"$.tombstones.{key!r}", "tombstone 字段无效"))
    groups = root.get("groups")
    if not isinstance(groups, dict):
        issues.append(StateFormatIssue("$.groups", "必须是对象"))
    else:
        for group_id, group in groups.items():
            item = _fields(issues, group, f"$.groups.{group_id!r}", {"group_id", "objective_summary", "members"})
            if not _text(group_id, 128):
                issues.append(StateFormatIssue(f"$.groups.{group_id!r}", "group key 无效"))
            if item is None:
                continue
            if item.get("group_id") != group_id or not _text(item.get("objective_summary"), 600):
                issues.append(StateFormatIssue(f"$.groups.{group_id!r}", "group identity 或 objective 无效"))
            members = item.get("members")
            if not isinstance(members, list) or len(members) > 128:
                issues.append(StateFormatIssue(f"$.groups.{group_id!r}.members", "必须是不超过128项的数组"))
            elif len({member.get("task_id") for member in members if isinstance(member, dict)}) != len(members):
                issues.append(StateFormatIssue(f"$.groups.{group_id!r}.members", "task_id 不得重复"))
            elif any(_fields(issues, member, f"$.groups.{group_id!r}.members[{index}]", {"task_id", "required"}) is None or not _text(member.get("task_id"), int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"])) or not isinstance(member.get("required"), bool) for index, member in enumerate(members)):
                issues.append(StateFormatIssue(f"$.groups.{group_id!r}.members", "member 无效"))
    health = _fields(issues, root.get("health"), "$.health", {"status"}, {"status", "initial_preparation_rollback"})
    if health is not None and health.get("status") not in {"ok", "degraded", "unavailable"}:
        issues.append(StateFormatIssue("$.health.status", "无效"))
    if health is not None and "initial_preparation_rollback" in health:
        marker = _fields(issues, health["initial_preparation_rollback"], "$.health.initial_preparation_rollback", {"status", "task_ref", "observed_at", "error"})
        if marker is not None and (marker.get("status") != "rollback_incomplete" or not isinstance(marker.get("task_ref"), str) or re.fullmatch(r"[a-f0-9]{12}(?:[a-f0-9]{4}){0,5}", marker["task_ref"]) is None or not _timestamp(marker.get("observed_at")) or not _text(marker.get("error"), 600)):
            issues.append(StateFormatIssue("$.health.initial_preparation_rollback", "rollback marker 无效"))
    return issues


def require_current_state_format(value: dict[str, Any]) -> dict[str, Any]:
    issues = validate_current_state_format(value)
    if issues:
        raise StateValidationError("invalid_current_state: " + "; ".join(str(issue) for issue in issues[:16]))
    return value
