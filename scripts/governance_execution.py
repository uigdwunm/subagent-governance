"""Pure canonical execution records and transitions.

This module deliberately owns no persistence and does not know about contracts,
context verification, dispatch orchestration, hooks, or the runtime facade.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

try:
    from scripts.governance_errors import StateConflictError, StateValidationError
    from scripts.governance_semantics import (
        OBSERVATION_SOURCES, PARENT_ACTIONS, PARENT_DISPOSITION_REASON_MAX_LENGTH,
    )
    from scripts.governance_state import initial_plane_records, parse_execution_key
except ModuleNotFoundError:
    from governance_errors import StateConflictError, StateValidationError
    from governance_semantics import (
        OBSERVATION_SOURCES, PARENT_ACTIONS, PARENT_DISPOSITION_REASON_MAX_LENGTH,
    )
    from governance_state import initial_plane_records, parse_execution_key


def _valid_close_reason(value: Any) -> bool:
    return bool(isinstance(value, str) and value.strip() and len(value) <= PARENT_DISPOSITION_REASON_MAX_LENGTH)


def _valid_closed_at(value: Any) -> bool:
    return bool(not isinstance(value, bool) and isinstance(value, int) and value >= 0)


def closure_has_complete_facts(closure: dict[str, Any]) -> bool:
    return _valid_close_reason(closure.get("reason")) and _valid_closed_at(closure.get("closed_at"))


def spawn_observation(execution: dict[str, Any]) -> str | None:
    return {"acknowledged": "success", "rejected": "failed", "indeterminate": "unknown"}.get(execution["dispatch_record"].get("dispatch_state"))


def execution_status(execution: dict[str, Any]) -> str:
    observation = execution["observation_record"]
    return (
        "running" if observation.get("observed_state") == "active" else
        "interrupted" if observation.get("terminal_status") == "interrupted" else
        "stopped" if observation.get("observed_state") == "terminal" else "not_started"
    )


def observation_is_bound(execution: dict[str, Any]) -> bool:
    dispatch, observation = execution.get("dispatch_record"), execution.get("observation_record")
    return bool(
        isinstance(dispatch, dict) and isinstance(observation, dict)
        and isinstance(dispatch.get("dispatch_target"), str) and dispatch["dispatch_target"]
        and observation.get("observed_state") in {"active", "terminal", "absent_at_check", "error", "unknown"}
    )


def identity_status(execution: dict[str, Any]) -> str:
    return "confirmed" if observation_is_bound(execution) else "unconfirmed"


def platform_observation(execution: dict[str, Any]) -> str | None:
    state = execution["observation_record"].get("observed_state")
    return "error" if state == "error" else "unknown" if state in {"unknown", "absent_at_check"} else "normal" if state in {"active", "terminal"} else None


def execution_is_closed(execution: dict[str, Any]) -> bool:
    return closure_has_complete_facts(execution["closure_record"])


def execution_close_reason(execution: dict[str, Any]) -> Any:
    return execution["closure_record"].get("reason")


def execution_closed_at(execution: dict[str, Any]) -> Any:
    return execution["closure_record"].get("closed_at")


def parent_action(execution: dict[str, Any]) -> Any:
    return execution["closure_record"].get("parent_action")


def dispatch_tool_use_id(execution: dict[str, Any]) -> Any:
    return execution["dispatch_record"].get("tool_use_id")


def dispatch_target(execution: dict[str, Any]) -> Any:
    return execution["dispatch_record"].get("dispatch_target")


def observation_checked_at(execution: dict[str, Any]) -> Any:
    return execution["observation_record"].get("observed_at")


def observation_source(execution: dict[str, Any]) -> Any:
    return execution["observation_record"].get("source")


def has_canonical_positive_execution_evidence(execution: dict[str, Any]) -> bool:
    if not observation_is_bound(execution):
        return False
    observation = execution.get("observation_record")
    if not isinstance(observation, dict) or isinstance(observation.get("observed_at"), bool) or not isinstance(observation.get("observed_at"), int):
        return False
    if observation.get("observed_state") == "active":
        return observation.get("source") == "list_agents"
    return bool(observation.get("observed_state") == "terminal" and observation.get("source") in {"list_agents", "terminal_notification"} and observation.get("terminal_status") in {"completed", "stopped", "interrupted"})


def dispatch_reliably_not_created(execution: dict[str, Any]) -> bool:
    return bool(isinstance(execution.get("dispatch_record"), dict) and execution["dispatch_record"].get("dispatch_state") == "rejected")


def _value_error(operation: str, expected: str) -> ValueError:
    return ValueError(f"canonical execution update {operation} 要求 {expected}")


def _nullable_text(value: Any, maximum: int | None = None) -> bool:
    return value is None or (isinstance(value, str) and value.strip() and (maximum is None or len(value) <= maximum))


def _nullable_timestamp(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


def _enum(value: Any, allowed: frozenset[str] | set[str], *, nullable: bool = False) -> bool:
    return bool((nullable and value is None) or (isinstance(value, str) and value in allowed))


def apply_canonical_execution_update(execution: dict[str, Any], operation: str, value: Any) -> None:
    """Apply the stable named-transition API without any I/O."""
    dispatch, observation, closure = execution["dispatch_record"], execution["observation_record"], execution["closure_record"]
    if operation == "dispatch_response":
        if not _enum(value, {"success", "failed", "unknown"}, nullable=True): raise _value_error(operation, "success、failed、unknown 或 null")
        dispatch["dispatch_state"] = {"success": "acknowledged", "failed": "rejected", "unknown": "indeterminate", None: "claimed" if dispatch.get("tool_use_id") else "prepared"}[value]
    elif operation == "dispatch_tool_use_id":
        if not _nullable_text(value): raise _value_error(operation, "非空字符串或 null")
        dispatch["tool_use_id"] = value
        if value is not None and dispatch.get("dispatch_state") == "prepared": dispatch["dispatch_state"] = "claimed"
    elif operation == "dispatch_target":
        if not _nullable_text(value): raise _value_error(operation, "非空字符串或 null")
        dispatch["dispatch_target"] = value
    elif operation == "observed_execution_status":
        if not _enum(value, {"running", "stopped", "interrupted", "not_started"}): raise _value_error(operation, "running、stopped、interrupted 或 not_started")
        observation.update({"observed_state": "active", "terminal_status": None} if value == "running" else {"observed_state": "terminal", "terminal_status": "interrupted" if value == "interrupted" else "stopped"} if value in {"stopped", "interrupted"} else {"observed_state": "not_observed", "terminal_status": None})
    elif operation == "observed_platform_state":
        if not _enum(value, {"error", "unknown"}): raise _value_error(operation, "error 或 unknown")
        observation["observed_state"] = value
    elif operation == "observation_observed_at":
        if not _nullable_timestamp(value): raise _value_error(operation, "非负整数时间戳或 null")
        observation["observed_at"] = value
    elif operation == "observation_source":
        if not _enum(value, OBSERVATION_SOURCES, nullable=True): raise _value_error(operation, "已知 observation source 或 null")
        observation["source"] = value
    elif operation == "observation_summary":
        if not _enum(value, {"completed", "stopped", "interrupted"}): raise _value_error(operation, "completed、stopped 或 interrupted")
        if not observation_is_bound(execution): raise _value_error(operation, "已精确绑定 dispatch target 的 observation")
        observation.update(observed_state="terminal", terminal_status=value)
    elif operation == "closure_parent_action":
        if not _enum(value, PARENT_ACTIONS, nullable=True): raise _value_error(operation, "已知 parent action 或 null")
        closure["parent_action"] = value
    elif operation == "closure_reason":
        if not _nullable_text(value, PARENT_DISPOSITION_REASON_MAX_LENGTH): raise _value_error(operation, f"不超过 {PARENT_DISPOSITION_REASON_MAX_LENGTH} 字符的非空字符串或 null")
        closure["reason"] = value
    elif operation == "closure_closed_at":
        if not _nullable_timestamp(value): raise _value_error(operation, "非负整数时间戳或 null")
        closure["closed_at"] = value
    else:
        raise ValueError(f"unknown canonical execution update: {operation}")


def task_record_for_attempt(state: dict[str, Any], task_id: str, attempt: int) -> dict[str, Any] | None:
    tasks = state.get("tasks")
    if not isinstance(tasks, dict): raise StateValidationError("治理状态缺少 tasks 对象")
    task = tasks.get(task_id)
    return canonical_execution_for_attempt(task, attempt) if isinstance(task, dict) and task.get("managed") is True else None


def iter_task_attempts(state: dict[str, Any]) -> list[tuple[str, int, dict[str, Any]]]:
    tasks = state.get("tasks")
    if not isinstance(tasks, dict): raise StateValidationError("治理状态缺少 tasks 对象")
    return [(str(task_id), attempt, execution) for task_id, task in tasks.items() if isinstance(task, dict) and task.get("managed") is True and isinstance(task.get("executions"), dict) for key, execution in task["executions"].items() if isinstance(execution, dict) and (attempt := parse_execution_key(key)) is not None]


def canonical_execution_for_attempt(task: dict[str, Any], attempt: int) -> dict[str, Any] | None:
    executions = task.get("executions") if isinstance(task, dict) else None
    execution = executions.get(str(attempt)) if isinstance(executions, dict) else None
    return execution if isinstance(execution, dict) else None


def task_attempt_records(state: dict[str, Any], task_id: str) -> list[tuple[int, dict[str, Any]]]:
    task = state.get("tasks", {}).get(task_id)
    executions = task.get("executions") if isinstance(task, dict) else None
    if not isinstance(executions, dict): return []
    return sorted((attempt, record) for key, record in executions.items() if isinstance(record, dict) and (attempt := parse_execution_key(key)) is not None)


def ensure_canonical_task_record(state: dict[str, Any], task_id: str) -> dict[str, Any]:
    tasks = state.get("tasks")
    task = tasks.get(task_id) if isinstance(tasks, dict) else None
    if not isinstance(task, dict) or task.get("managed") is not True: raise StateConflictError("找不到目标 managed task")
    if not isinstance(task.get("work_item"), dict) or not isinstance(task.get("executions"), dict): raise StateConflictError("managed task 缺少 canonical work_item/executions")
    return task


def record_has_target_provenance(record: dict[str, Any], target: str) -> bool:
    dispatch = record.get("dispatch_record")
    value = dispatch.get("dispatch_target") if isinstance(dispatch, dict) else None
    return bool(target.strip() and isinstance(value, str) and target.strip() == value.strip())


def retained_target_attempts(state: dict[str, Any], target: str) -> list[tuple[str, int, dict[str, Any]]]:
    return [candidate for candidate in iter_task_attempts(state) if record_has_target_provenance(candidate[2], target)]


@dataclass(frozen=True)
class ManagedTargetAdmission:
    disposition: str
    candidate: tuple[str, int, dict[str, Any]] | None
    reason: str


def managed_target_admission(state: dict[str, Any], target: str) -> ManagedTargetAdmission:
    agents = state.get("agents")
    if not isinstance(agents, dict): raise StateValidationError("治理状态缺少 agents 对象")
    mapping = agents.get(target)
    mapped = None
    if isinstance(mapping, dict) and isinstance(mapping.get("task_id"), str) and isinstance(mapping.get("attempt"), int) and not isinstance(mapping.get("attempt"), bool):
        record = task_record_for_attempt(state, mapping["task_id"], mapping["attempt"])
        if record is not None: mapped = (mapping["task_id"], mapping["attempt"], record)
    retained = retained_target_attempts(state, target)
    open_retained = [candidate for candidate in retained if not execution_is_closed(candidate[2])]
    if mapped is not None:
        if record_has_target_provenance(mapped[2], target) and not execution_is_closed(mapped[2]): return ManagedTargetAdmission("managed", mapped, "active index 与精确 retained provenance 一致")
        if not execution_is_closed(mapped[2]): return ManagedTargetAdmission("reconcile", None, "active index 指向未关闭 execution，但该 execution 不含精确 target provenance")
    if len(open_retained) == 1: return ManagedTargetAdmission("managed", open_retained[0], "唯一精确且未关闭的 retained provenance 可恢复 active index")
    if len(open_retained) > 1: return ManagedTargetAdmission("reconcile", None, "同一 target 存在多个精确且未关闭的 retained candidates")
    if retained: return ManagedTargetAdmission("closed", None, "target 仅匹配已可靠关闭的 provenance")
    return ManagedTargetAdmission("unmanaged", None, "target 没有 canonical provenance")


def repair_managed_target_index(state: dict[str, Any], target: str, admission: ManagedTargetAdmission) -> None:
    if admission.disposition != "managed" or admission.candidate is None: raise StateConflictError("target 尚未取得唯一 managed lifecycle admission")
    agents = state.get("agents")
    if not isinstance(agents, dict): raise StateValidationError("治理状态缺少 agents 对象")
    task_id, attempt, _record = admission.candidate
    agents[target] = {"task_id": task_id, "attempt": attempt}


def tombstone_record(record: dict[str, Any], reason: str, closed_at: int) -> dict[str, Any]:
    return {"task_ref": record.get("task_ref"), "dispatch_target": dispatch_target(record), "close_reason": reason, "closed_at": closed_at}


def close_attempt_record(state: dict[str, Any], task_id: str, attempt: int, record: dict[str, Any], reason: str, closed_at: int) -> None:
    apply_canonical_execution_update(record, "closure_reason", reason)
    apply_canonical_execution_update(record, "closure_closed_at", closed_at)
    apply_canonical_execution_update(record, "closure_parent_action", None)
    record.pop("pending_action", None); record.pop("last_lifecycle_operation", None)
    record["updated_at"] = closed_at
    state.setdefault("tombstones", {})[f"{task_id}:{attempt}"] = tombstone_record(record, reason, closed_at)
