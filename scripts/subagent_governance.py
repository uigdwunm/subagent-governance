#!/usr/bin/env python3
"""Adaptive Codex subagent lifecycle governance hook."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Shared definitions live in dedicated modules and are exposed by this runtime.
try:
    from scripts.governance_semantics import (
        _DECISION_ACTION_ORDER,
        AUTO_RESOLUTION,
        CALL_OBSERVATIONS,
        CONTEXT_STRATEGIES,
        CONTEXT_TURNS,
        DIAGNOSTIC_ATTEMPT_LIMIT,
        DIAGNOSTIC_GROUP_LIMIT,
        DIAGNOSTIC_ISSUE_LIMIT,
        DIAGNOSTIC_OUTPUT_BYTES,
        DIAGNOSTIC_SESSION_LIMIT,
        EXECUTION_STATUSES,
        GROUP_ID_MAX_LENGTH,
        GROUP_MEMBER_LIMIT,
        GROUP_OBJECTIVE_MAX_LENGTH,
        IDENTITY_STATUSES,
        LIFECYCLE_OPERATION_TYPES,
        LIST_AGENTS_ACTIVE_STATUSES,
        LIST_AGENTS_ADVISORY_STATUSES,
        LIST_AGENTS_BOOLEAN_ERROR_FLAGS,
        LIST_AGENTS_ERROR_STATUSES,
        LIST_AGENTS_EXPLICIT_ERROR_FIELD,
        LIST_AGENTS_TERMINAL_STATUSES,
        LIST_AGENTS_WRAPPER_ERROR_STATUSES,
        LIST_AGENTS_WRAPPER_STATUS_FIELDS,
        MAX_CONTRACT_TEXT,
        MAX_PREPARED_BYTES,
        MAX_STATE_BYTES,
        MODE_MINIMUMS,
        NEW_TASK_SOFT_LIMIT_BYTES,
        OBSERVATION_SOURCES,
        OPERATION_NATIVE_TOOLS,
        OPERATION_TYPES,
        PARENT_ACTIONS,
        PARENT_DISPOSITION_REASON_MAX_LENGTH,
        PARENT_DISPOSITIONS,
        PLATFORM_OBSERVATIONS,
        REASONING_EFFORTS,
        REQUESTED_MODES,
        RESOLUTION_REASONS,
        RESOLVED_MODES,
        RETENTION_SECONDS,
        RETRY_LIMITS,
        RISKS,
        SEMANTIC_DEFINITIONS,
        SEMANTIC_RULES,
        SESSION_SUMMARY_CONTEXT_LIMIT,
        SESSION_SUMMARY_FIELD_LIMIT,
        SESSION_SUMMARY_RECORD_LIMIT,
        STATE_FORMAT_VERSION,
        STOP_READ_ATTEMPTS,
        STOP_READ_RETRY_DELAY_SECONDS,
        TASK_CONTRACT_OPTIONAL_FIELDS,
        TASK_NAME_MAX_LENGTH,
        TASK_NAME_RE,
        TASK_REF_LENGTHS,
    )
except ModuleNotFoundError:
    from governance_semantics import (
        _DECISION_ACTION_ORDER,
        AUTO_RESOLUTION,
        CALL_OBSERVATIONS,
        CONTEXT_STRATEGIES,
        CONTEXT_TURNS,
        DIAGNOSTIC_ATTEMPT_LIMIT,
        DIAGNOSTIC_GROUP_LIMIT,
        DIAGNOSTIC_ISSUE_LIMIT,
        DIAGNOSTIC_OUTPUT_BYTES,
        DIAGNOSTIC_SESSION_LIMIT,
        EXECUTION_STATUSES,
        GROUP_ID_MAX_LENGTH,
        GROUP_MEMBER_LIMIT,
        GROUP_OBJECTIVE_MAX_LENGTH,
        IDENTITY_STATUSES,
        LIFECYCLE_OPERATION_TYPES,
        LIST_AGENTS_ACTIVE_STATUSES,
        LIST_AGENTS_ADVISORY_STATUSES,
        LIST_AGENTS_BOOLEAN_ERROR_FLAGS,
        LIST_AGENTS_ERROR_STATUSES,
        LIST_AGENTS_EXPLICIT_ERROR_FIELD,
        LIST_AGENTS_TERMINAL_STATUSES,
        LIST_AGENTS_WRAPPER_ERROR_STATUSES,
        LIST_AGENTS_WRAPPER_STATUS_FIELDS,
        MAX_CONTRACT_TEXT,
        MAX_PREPARED_BYTES,
        MAX_STATE_BYTES,
        MODE_MINIMUMS,
        NEW_TASK_SOFT_LIMIT_BYTES,
        OBSERVATION_SOURCES,
        OPERATION_NATIVE_TOOLS,
        OPERATION_TYPES,
        PARENT_ACTIONS,
        PARENT_DISPOSITION_REASON_MAX_LENGTH,
        PARENT_DISPOSITIONS,
        PLATFORM_OBSERVATIONS,
        REASONING_EFFORTS,
        REQUESTED_MODES,
        RESOLUTION_REASONS,
        RESOLVED_MODES,
        RETENTION_SECONDS,
        RETRY_LIMITS,
        RISKS,
        SEMANTIC_DEFINITIONS,
        SEMANTIC_RULES,
        SESSION_SUMMARY_CONTEXT_LIMIT,
        SESSION_SUMMARY_FIELD_LIMIT,
        SESSION_SUMMARY_RECORD_LIMIT,
        STATE_FORMAT_VERSION,
        STOP_READ_ATTEMPTS,
        STOP_READ_RETRY_DELAY_SECONDS,
        TASK_CONTRACT_OPTIONAL_FIELDS,
        TASK_NAME_MAX_LENGTH,
        TASK_NAME_RE,
        TASK_REF_LENGTHS,
    )

try:
    from scripts.governance_errors import (
        CommunicationPreparationError,
        ContextVerificationError,
        DiagnosticReadError,
        DispatchPreparationError,
        GroupNotFoundError,
        GroupValidationError,
        NotificationObservationError,
        ParentDispositionConflict,
        ParentDispositionError,
        PreparedContractConflictError,
        PreparedContractError,
        PreparedContractValidationError,
        PreparedContractWriteError,
        ReconciliationError,
        StateCapacityError,
        StateConflictError,
        StateStoreError,
        StateValidationError,
        StateWriteError,
        _state_store_exception_category,
    )
except ModuleNotFoundError:
    from governance_errors import (
        CommunicationPreparationError,
        ContextVerificationError,
        DiagnosticReadError,
        DispatchPreparationError,
        GroupNotFoundError,
        GroupValidationError,
        NotificationObservationError,
        ParentDispositionConflict,
        ParentDispositionError,
        PreparedContractConflictError,
        PreparedContractError,
        PreparedContractValidationError,
        PreparedContractWriteError,
        ReconciliationError,
        StateCapacityError,
        StateConflictError,
        StateStoreError,
        StateValidationError,
        StateWriteError,
        _state_store_exception_category,
    )

try:
    from scripts.governance_contracts import TaskContract, TaskFeatures
except ModuleNotFoundError:
    from governance_contracts import TaskContract, TaskFeatures

try:
    from scripts.governance_storage import (
        PrivateStorageCapacityError,
        PrivateStorageError,
        PrivateStorageWriteError,
        atomic_write_bytes,
        locked_file,
        read_private_bytes,
    )
except ModuleNotFoundError:
    from governance_storage import (
        PrivateStorageCapacityError,
        PrivateStorageError,
        PrivateStorageWriteError,
        atomic_write_bytes,
        locked_file,
        read_private_bytes,
    )

try:
    from scripts.governance_state import (
        initial_plane_records as _initial_plane_records,
    )
    from scripts.governance_state import (
        require_current_state_format as _require_current_state_format,
    )
    from scripts.governance_state import (
        validate_current_state_format,
    )
    from scripts.governance_state import (
        validate_current_execution_planes as _validate_current_execution_planes,
    )
except ModuleNotFoundError:
    from governance_state import (
        initial_plane_records as _initial_plane_records,
    )
    from governance_state import (
        require_current_state_format as _require_current_state_format,
    )
    from governance_state import (
        validate_current_state_format,
    )
    from governance_state import (
        validate_current_execution_planes as _validate_current_execution_planes,
    )


require_current_state_format = _require_current_state_format
# Transitional compatibility alias; validation remains owned by governance_state.
_state_for_storage = _require_current_state_format


def _valid_close_reason(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and value.strip()
        and len(value) <= PARENT_DISPOSITION_REASON_MAX_LENGTH
    )


def _valid_closed_at(value: Any) -> bool:
    return bool(not isinstance(value, bool) and isinstance(value, int) and value >= 0)


def _closure_has_complete_facts(closure: dict[str, Any]) -> bool:
    return _valid_close_reason(closure.get("reason")) and _valid_closed_at(
        closure.get("closed_at")
    )


def _spawn_observation(execution: dict[str, Any]) -> str | None:
    dispatch = execution["dispatch_record"]
    return {
        "acknowledged": "success",
        "rejected": "failed",
        "indeterminate": "unknown",
    }.get(dispatch.get("dispatch_state"))


def _execution_status(execution: dict[str, Any]) -> str:
    observation = execution["observation_record"]
    observed_state = observation.get("observed_state")
    terminal_status = observation.get("terminal_status")
    return (
        "running"
        if observed_state == "active"
        else "interrupted"
        if terminal_status == "interrupted"
        else "stopped"
        if observed_state == "terminal"
        else "not_started"
    )


def _identity_status(execution: dict[str, Any]) -> str:
    return (
        "confirmed"
        if _observation_is_bound(execution)
        else "unconfirmed"
    )


def _platform_observation(execution: dict[str, Any]) -> str | None:
    observed_state = execution["observation_record"].get("observed_state")
    return (
        "error"
        if observed_state == "error"
        else "unknown"
        if observed_state in {"unknown", "absent_at_check"}
        else "normal"
        if observed_state in {"active", "terminal"}
        else None
    )


def _execution_is_closed(execution: dict[str, Any]) -> bool:
    return _closure_has_complete_facts(execution["closure_record"])


def _execution_close_reason(execution: dict[str, Any]) -> Any:
    return execution["closure_record"].get("reason")


def _execution_closed_at(execution: dict[str, Any]) -> Any:
    return execution["closure_record"].get("closed_at")


def _parent_action(execution: dict[str, Any]) -> Any:
    return execution["closure_record"].get("parent_action")


def _dispatch_tool_use_id(execution: dict[str, Any]) -> Any:
    return execution["dispatch_record"].get("tool_use_id")


def _dispatch_target(execution: dict[str, Any]) -> Any:
    return execution["dispatch_record"].get("dispatch_target")


def _observation_checked_at(execution: dict[str, Any]) -> Any:
    return execution["observation_record"].get("observed_at")


def _observation_source(execution: dict[str, Any]) -> Any:
    return execution["observation_record"].get("source")


def _observation_is_bound(execution: dict[str, Any]) -> bool:
    dispatch = execution.get("dispatch_record")
    observation = execution.get("observation_record")
    if not isinstance(dispatch, dict) or not isinstance(observation, dict):
        return False
    dispatch_target = dispatch.get("dispatch_target")
    return bool(
        isinstance(dispatch_target, str)
        and dispatch_target
        and observation.get("observed_state")
        in {"active", "terminal", "absent_at_check", "error", "unknown"}
    )


def _has_canonical_positive_execution_evidence(execution: dict[str, Any]) -> bool:
    """Recognize already-bound positive execution facts without inferring identity."""
    if not _observation_is_bound(execution):
        return False
    observation = execution.get("observation_record")
    if not isinstance(observation, dict):
        return False
    observed_at = observation.get("observed_at")
    if isinstance(observed_at, bool) or not isinstance(observed_at, int):
        return False
    observed_state = observation.get("observed_state")
    source = observation.get("source")
    if observed_state == "active":
        return source == "list_agents"
    if observed_state == "terminal":
        return bool(
            source in {"list_agents", "terminal_notification"}
            and observation.get("terminal_status")
            in {"completed", "stopped", "interrupted"}
        )
    return False


def _dispatch_reliably_not_created(execution: dict[str, Any]) -> bool:
    dispatch = execution.get("dispatch_record")
    return bool(
        isinstance(dispatch, dict)
        and dispatch.get("dispatch_state") == "rejected"
    )


def _canonical_update_value_error(operation: str, expected: str) -> ValueError:
    return ValueError(f"canonical execution update {operation} 要求 {expected}")


def _is_nullable_nonempty_text(value: Any, *, maximum: int | None = None) -> bool:
    if value is None:
        return True
    return bool(
        isinstance(value, str)
        and value.strip()
        and (maximum is None or len(value) <= maximum)
    )


def _is_nullable_timestamp(value: Any) -> bool:
    return bool(
        value is None
        or (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        )
    )


def _is_enum_value(
    value: Any, allowed: frozenset[str] | set[str], *, nullable: bool = False
) -> bool:
    return bool(
        (nullable and value is None)
        or (isinstance(value, str) and value in allowed)
    )


def _apply_canonical_execution_update(
    execution: dict[str, Any], operation: str, value: Any
) -> None:
    """Apply one named transition directly to the canonical execution planes."""
    dispatch = execution["dispatch_record"]
    observation = execution["observation_record"]
    closure = execution["closure_record"]
    if operation == "dispatch_response":
        if not _is_enum_value(
            value, {"success", "failed", "unknown"}, nullable=True
        ):
            raise _canonical_update_value_error(
                operation, "success、failed、unknown 或 null"
            )
        dispatch["dispatch_state"] = {
            "success": "acknowledged",
            "failed": "rejected",
            "unknown": "indeterminate",
            None: "claimed" if dispatch.get("tool_use_id") else "prepared",
        }[value]
    elif operation == "dispatch_tool_use_id":
        if not _is_nullable_nonempty_text(value):
            raise _canonical_update_value_error(operation, "非空字符串或 null")
        dispatch["tool_use_id"] = value
        if value is not None and dispatch.get("dispatch_state") == "prepared":
            dispatch["dispatch_state"] = "claimed"
    elif operation == "dispatch_target":
        if not _is_nullable_nonempty_text(value):
            raise _canonical_update_value_error(operation, "非空字符串或 null")
        dispatch["dispatch_target"] = value
    elif operation == "observed_execution_status":
        if not _is_enum_value(
            value, {"running", "stopped", "interrupted", "not_started"}
        ):
            raise _canonical_update_value_error(
                operation, "running、stopped、interrupted 或 not_started"
            )
        if value == "running":
            observation["observed_state"] = "active"
            observation["terminal_status"] = None
        elif value in {"stopped", "interrupted"}:
            observation["observed_state"] = "terminal"
            observation["terminal_status"] = (
                "interrupted" if value == "interrupted" else "stopped"
            )
        elif value == "not_started":
            observation["observed_state"] = "not_observed"
            observation["terminal_status"] = None
    elif operation == "observed_platform_state":
        if not _is_enum_value(value, {"error", "unknown"}):
            raise _canonical_update_value_error(operation, "error 或 unknown")
        if value == "error":
            observation["observed_state"] = "error"
        else:
            observation["observed_state"] = "unknown"
    elif operation == "observation_observed_at":
        if not _is_nullable_timestamp(value):
            raise _canonical_update_value_error(operation, "非负整数时间戳或 null")
        observation["observed_at"] = value
    elif operation == "observation_source":
        if not _is_enum_value(value, OBSERVATION_SOURCES, nullable=True):
            raise _canonical_update_value_error(operation, "已知 observation source 或 null")
        observation["source"] = value
    elif operation == "observation_summary":
        if not _is_enum_value(value, {"completed", "stopped", "interrupted"}):
            raise _canonical_update_value_error(
                operation, "completed、stopped 或 interrupted"
            )
        if not _observation_is_bound(execution):
            raise _canonical_update_value_error(
                operation, "已精确绑定 dispatch target 的 observation"
            )
        observation["observed_state"] = "terminal"
        observation["terminal_status"] = value
    elif operation == "closure_parent_action":
        if not _is_enum_value(value, PARENT_ACTIONS, nullable=True):
            raise _canonical_update_value_error(operation, "已知 parent action 或 null")
        closure["parent_action"] = value
    elif operation == "closure_reason":
        if not _is_nullable_nonempty_text(
            value, maximum=PARENT_DISPOSITION_REASON_MAX_LENGTH
        ):
            raise _canonical_update_value_error(
                operation,
                f"不超过 {PARENT_DISPOSITION_REASON_MAX_LENGTH} 字符的非空字符串或 null",
            )
        closure["reason"] = value
    elif operation == "closure_closed_at":
        if not _is_nullable_timestamp(value):
            raise _canonical_update_value_error(operation, "非负整数时间戳或 null")
        closure["closed_at"] = value
    else:
        raise ValueError(f"unknown canonical execution update: {operation}")


def adapt_spawn_response(response: Any) -> dict[str, Any]:
    value = _json_value(response)
    if not isinstance(value, dict):
        return {"observation": "unknown", "agent_id": None, "canonical_path": None}
    candidate = value
    structured = value.get("structuredContent")
    if isinstance(structured, dict):
        candidate = structured

    failed = (
        value.get("isError") is True
        or value.get("is_error") is True
        or candidate.get("isError") is True
        or candidate.get("is_error") is True
    )
    status_source = candidate if candidate is not value else value
    status_value = (
        status_source.get("status")
        if "status" in status_source
        else status_source.get("state")
    )
    status = status_value.lower() if isinstance(status_value, str) else None
    if status in {"error", "failed", "failure"}:
        failed = True

    agent_id = None
    for field_name in ("agent_id", "agentId"):
        field_value = candidate.get(field_name)
        if isinstance(field_value, str) and field_value.strip():
            agent_id = field_value.strip()
            break
    canonical_path = None
    for field_name in ("canonical_task_path", "canonical_path", "task_path", "task_name"):
        field_value = candidate.get(field_name)
        if isinstance(field_value, str) and field_value.startswith("/"):
            canonical_path = field_value
            break
    if failed and (agent_id or canonical_path):
        return {"observation": "unknown", "agent_id": None, "canonical_path": None}
    if failed:
        return {"observation": "failed", "agent_id": None, "canonical_path": None}
    if agent_id or canonical_path:
        return {
            "observation": "success",
            "agent_id": agent_id,
            "canonical_path": canonical_path,
        }
    if status in {"ok", "success", "succeeded", "created"}:
        return {"observation": "success", "agent_id": None, "canonical_path": None}
    return {"observation": "unknown", "agent_id": None, "canonical_path": None}


def _now() -> int:
    return int(time.time())


# Canonical execution semantics are owned by the pure P5 kernel.  The aliases
# keep the public/runtime compatibility surface stable while later lifecycle
# plans finish moving their callers out of this facade.
try:
    from scripts import governance_execution as _execution
    from scripts import governance_dispatch as _dispatch
except ModuleNotFoundError:
    import governance_execution as _execution
    import governance_dispatch as _dispatch

_closure_has_complete_facts = _execution.closure_has_complete_facts
_spawn_observation = _execution.spawn_observation
_execution_status = _execution.execution_status
_identity_status = _execution.identity_status
_platform_observation = _execution.platform_observation
_execution_is_closed = _execution.execution_is_closed
_execution_close_reason = _execution.execution_close_reason
_execution_closed_at = _execution.execution_closed_at
_parent_action = _execution.parent_action
_dispatch_tool_use_id = _execution.dispatch_tool_use_id
_dispatch_target = _execution.dispatch_target
_observation_checked_at = _execution.observation_checked_at
_observation_source = _execution.observation_source
_observation_is_bound = _execution.observation_is_bound
_has_canonical_positive_execution_evidence = _execution.has_canonical_positive_execution_evidence
_dispatch_reliably_not_created = _execution.dispatch_reliably_not_created
_apply_canonical_execution_update = _execution.apply_canonical_execution_update


try:
    from scripts.governance_state_store import StateStore, UnavailableStateStore
    from scripts.governance_store_support import (
        data_root_path as _resolve_data_root_path,
        exclusive_file_lock as _exclusive_file_lock,
        installed_plugin_data_root as _installed_plugin_data_root_for_module,
        owned_by_current_user as _owned_by_current_user,
        prepare_private_directory as _prepare_private_directory,
        private_permissions_safe as _private_permissions_safe,
        restrict_descriptor as _restrict_descriptor,
        safe_filename as _safe_name,
        sync_directory as _sync_directory,
    )
    from scripts.governance_state import (
        parse_execution_key as _parse_execution_key,
        parse_tombstone_key as _parse_tombstone_key,
    )
except ModuleNotFoundError:
    from governance_state_store import StateStore, UnavailableStateStore
    from governance_store_support import (
        data_root_path as _resolve_data_root_path,
        exclusive_file_lock as _exclusive_file_lock,
        installed_plugin_data_root as _installed_plugin_data_root_for_module,
        owned_by_current_user as _owned_by_current_user,
        prepare_private_directory as _prepare_private_directory,
        private_permissions_safe as _private_permissions_safe,
        restrict_descriptor as _restrict_descriptor,
        safe_filename as _safe_name,
        sync_directory as _sync_directory,
    )
    from governance_state import (
        parse_execution_key as _parse_execution_key,
        parse_tombstone_key as _parse_tombstone_key,
    )


def _activity_timestamp(record: dict[str, Any]) -> int:
    timestamps = []
    for value in (
        record.get("updated_at"),
        record.get("observation_record", {}).get("observed_at"),
        record.get("closure_record", {}).get("closed_at"),
    ):
        try:
            timestamps.append(int(value or 0))
        except (TypeError, ValueError):
            continue
    pending = record.get("pending_action")
    if isinstance(pending, dict):
        for field in ("claimed_at", "created_at"):
            try:
                timestamps.append(int(pending.get(field) or 0))
            except (TypeError, ValueError):
                continue
    return max(timestamps, default=0)


def _installed_plugin_data_root(script_path: Path | None = None) -> Path | None:
    """Compatibility facade for the path-only store support resolver."""
    return _installed_plugin_data_root_for_module(script_path or Path(__file__))


def _data_root_path() -> Path:
    """Compatibility facade that resolves the runtime module's location."""
    return _resolve_data_root_path(Path(__file__))


def _data_root() -> Path:
    return _prepare_private_directory(_data_root_path())


def _default_state_store() -> StateStore:
    return StateStore(_data_root() / "sessions")


def _task_record_for_attempt(
    state: dict[str, Any], task_id: str, attempt: int
) -> dict[str, Any] | None:
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        raise StateValidationError("治理状态缺少 tasks 对象")
    record = tasks.get(task_id)
    if not isinstance(record, dict) or record.get("managed") is not True:
        return None
    return _canonical_execution_for_attempt(record, attempt)


def _iter_task_attempts(
    state: dict[str, Any],
) -> list[tuple[str, int, dict[str, Any]]]:
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        raise StateValidationError("治理状态缺少 tasks 对象")
    attempts: list[tuple[str, int, dict[str, Any]]] = []
    for task_id, task in tasks.items():
        if not isinstance(task, dict) or task.get("managed") is not True:
            continue
        executions = task.get("executions")
        if not isinstance(executions, dict):
            continue
        for attempt_key, execution in executions.items():
            attempt = _parse_execution_key(attempt_key)
            if isinstance(execution, dict) and attempt is not None:
                attempts.append((str(task_id), attempt, execution))
    return attempts


def _managed_target_attempt(
    state: dict[str, Any], target: str
) -> tuple[str, int, dict[str, Any]] | None:
    agents = state.get("agents")
    if not isinstance(agents, dict):
        raise StateValidationError("治理状态缺少 agents 对象")
    mapping = agents.get(target)
    if not isinstance(mapping, dict):
        return None
    task_id = mapping.get("task_id")
    attempt = mapping.get("attempt")
    if (
        not isinstance(task_id, str)
        or not task_id
        or isinstance(attempt, bool)
        or not isinstance(attempt, int)
    ):
        return None
    record = _task_record_for_attempt(state, task_id, attempt)
    if not isinstance(record, dict):
        return None
    return task_id, attempt, record


def _record_has_target_provenance(record: dict[str, Any], target: str) -> bool:
    """Resolve only an exact canonical dispatch target."""
    normalized = target.strip()
    dispatch = record.get("dispatch_record")
    dispatch_target = dispatch.get("dispatch_target") if isinstance(dispatch, dict) else None
    return bool(
        normalized
        and isinstance(dispatch_target, str)
        and normalized == dispatch_target.strip()
    )


def _retained_target_attempts(
    state: dict[str, Any], target: str
) -> list[tuple[str, int, dict[str, Any]]]:
    """Find executions by their retained identity, never by the active index."""
    return [
        (task_id, attempt, record)
        for task_id, attempt, record in _iter_task_attempts(state)
        if _record_has_target_provenance(record, target)
    ]


@dataclass(frozen=True)
class ManagedTargetAdmission:
    disposition: str
    candidate: tuple[str, int, dict[str, Any]] | None
    reason: str


def _managed_target_admission(
    state: dict[str, Any], target: str
) -> ManagedTargetAdmission:
    """Classify one native target without treating the active index as identity."""
    agents = state.get("agents")
    if not isinstance(agents, dict):
        raise StateValidationError("治理状态缺少 agents 对象")
    mapped = _managed_target_attempt(state, target)
    retained = _retained_target_attempts(state, target)
    open_retained = [
        candidate
        for candidate in retained
        if not _execution_is_closed(candidate[2])
    ]

    if mapped is not None:
        mapped_exact = _record_has_target_provenance(mapped[2], target)
        mapped_open = not _execution_is_closed(mapped[2])
        if mapped_exact and mapped_open:
            return ManagedTargetAdmission(
                "managed",
                mapped,
                "active index 与精确 retained provenance 一致",
            )
        if mapped_open:
            return ManagedTargetAdmission(
                "reconcile",
                None,
                "active index 指向未关闭 execution，但该 execution 不含精确 target provenance",
            )

    if len(open_retained) == 1:
        candidate = open_retained[0]
        return ManagedTargetAdmission(
            "managed",
            candidate,
            "唯一精确且未关闭的 retained provenance 可恢复 active index",
        )
    if len(open_retained) > 1:
        return ManagedTargetAdmission(
            "reconcile",
            None,
            "同一 target 存在多个精确且未关闭的 retained candidates",
        )
    if retained:
        return ManagedTargetAdmission(
            "closed",
            None,
            "target 仅匹配已可靠关闭的 provenance",
        )
    return ManagedTargetAdmission(
        "unmanaged",
        None,
        "target 没有 canonical provenance",
    )


def _repair_managed_target_index(
    state: dict[str, Any], target: str, admission: ManagedTargetAdmission
) -> None:
    if admission.disposition != "managed" or admission.candidate is None:
        raise StateConflictError("target 尚未取得唯一 managed lifecycle admission")
    agents = state.get("agents")
    if not isinstance(agents, dict):
        raise StateValidationError("治理状态缺少 agents 对象")
    task_id, attempt, _record = admission.candidate
    agents[target] = _identity_mapping(task_id, attempt)


def _validate_task_identity(task_id: Any, attempt: Any) -> tuple[str, int]:
    task_errors = _validate_text(
        task_id,
        "task_id",
        maximum=int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"]),
    )
    minimum = int(SEMANTIC_DEFINITIONS["attempt"]["minimum"])
    if task_errors:
        raise NotificationObservationError("；".join(task_errors))
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < minimum:
        raise NotificationObservationError(f"attempt 必须是大于等于 {minimum} 的整数")
    return str(task_id), attempt


def _task_attempt_records(
    state: dict[str, Any], task_id: str
) -> list[tuple[int, dict[str, Any]]]:
    current = state.get("tasks", {}).get(task_id)
    if not isinstance(current, dict):
        return []
    executions = current.get("executions")
    if not isinstance(executions, dict):
        return []
    records = {
        attempt: record
        for key, record in executions.items()
        if isinstance(record, dict)
        and (attempt := _parse_execution_key(key)) is not None
    }
    return sorted(records.items())


def _canonical_execution_for_attempt(
    task: dict[str, Any], attempt: int
) -> dict[str, Any] | None:
    executions = task.get("executions")
    if not isinstance(executions, dict):
        return None
    execution = executions.get(str(attempt))
    return execution if isinstance(execution, dict) else None


def _ensure_canonical_task_record(
    state: dict[str, Any], task_id: str
) -> dict[str, Any]:
    """Return a writable task that already matches the current state model."""
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        raise StateValidationError("治理状态缺少 tasks 对象")
    task = tasks.get(task_id)
    if not isinstance(task, dict) or task.get("managed") is not True:
        raise StateConflictError("找不到目标 managed task")
    work_item = task.get("work_item")
    executions = task.get("executions")
    if not isinstance(work_item, dict) or not isinstance(executions, dict):
        raise StateConflictError("managed task 缺少 canonical work_item/executions")
    return task


# State traversal, retained identity admission, and close/tombstone mutations
# are also canonical kernel operations.  Keep legacy private spellings as a
# compatibility facade until P6 removes the remaining lifecycle callers.
_task_record_for_attempt = _execution.task_record_for_attempt
_iter_task_attempts = _execution.iter_task_attempts
_task_attempt_records = _execution.task_attempt_records
_canonical_execution_for_attempt = _execution.canonical_execution_for_attempt
_ensure_canonical_task_record = _execution.ensure_canonical_task_record
_record_has_target_provenance = _execution.record_has_target_provenance
_retained_target_attempts = _execution.retained_target_attempts
_managed_target_admission = _execution.managed_target_admission
_repair_managed_target_index = _execution.repair_managed_target_index
_tombstone_record = _execution.tombstone_record
_close_attempt_record = _execution.close_attempt_record
ManagedTargetAdmission = _execution.ManagedTargetAdmission












_tombstone_record = _execution.tombstone_record
_close_attempt_record = _execution.close_attempt_record






def _task_ref_occupied(state: dict[str, Any], task_ref: str) -> bool:
    tasks = state.get("tasks")
    if isinstance(tasks, dict):
        for task_id in tasks:
            for _attempt, record in _task_attempt_records(state, str(task_id)):
                if record.get("task_ref") == task_ref:
                    return True
    tombstones = state.get("tombstones")
    if isinstance(tombstones, dict):
        for record in tombstones.values():
            if isinstance(record, dict) and record.get("task_ref") == task_ref:
                return True
    return False


def _new_task_id() -> str:
    return "sg-" + secrets.token_hex(16)


def _initial_task_record(
    attempt: int,
    task_ref: str,
    task_name: str,
    contract: TaskContract,
    created_at: int,
) -> dict[str, Any]:
    execution = {
        "task_ref": task_ref,
        "task_name": task_name,
        "resolved_mode": contract.resolved_mode,
        "contract_summary": _contract_summary(contract),
        "contract_digest": contract_digest(contract),
        **_initial_plane_records(),
        "spawn_retry_count": 0,
        "recovery_count": 0,
        "updated_at": created_at,
    }
    record = {
        "managed": True,
        "work_item": {
            "lifecycle": "open",
            "current_attempt": attempt,
        },
        "executions": {str(attempt): execution},
    }
    return record


def _initial_task_post_state(prepared: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the sole canonical initial post-state from the validated contract."""
    if prepared.get("dispatch_operation") != "initial_spawn":
        raise PreparedContractValidationError(
            "只有 initial PreparedContract 可以重建 initial task post-state"
        )
    contract = _contract_from_input(prepared.get("contract"))
    expected = _initial_task_record(
        int(prepared["attempt"]),
        str(prepared["task_ref"]),
        str(prepared["task_name"]),
        contract,
        int(prepared["created_at"]),
    )
    execution = expected["executions"][str(prepared["attempt"])]
    if (
        prepared.get("attempt") != 1
        or prepared.get("resolved_mode") != execution.get("resolved_mode")
        or prepared.get("contract_digest") != execution.get("contract_digest")
    ):
        raise PreparedContractValidationError(
            "initial PreparedContract 无法确定性绑定 canonical task post-state"
        )
    return expected


_initial_task_record = _dispatch.initial_task_record
_initial_task_post_state = _dispatch.initial_task_post_state


def _exception_chain_text(error: BaseException) -> str:
    messages: list[str] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current)
        if message and message not in messages:
            messages.append(message)
        current = current.__cause__ or current.__context__
    return "；caused by：".join(messages)


def _merge_initial_rollback_health(
    health: dict[str, Any], marker: dict[str, Any]
) -> None:
    status = health.get("status")
    status_rank = {"ok": 0, "degraded": 1, "unavailable": 2}
    if status in status_rank and status_rank[str(status)] < status_rank["degraded"]:
        health["status"] = "degraded"

    marker_field = "initial_preparation_rollback"
    if marker_field not in health:
        health[marker_field] = copy.deepcopy(marker)
        return
    current_marker = health.get(marker_field)
    current_observed_at = (
        current_marker.get("observed_at")
        if isinstance(current_marker, dict)
        else None
    )
    next_observed_at = marker.get("observed_at")
    if (
        isinstance(current_observed_at, int)
        and not isinstance(current_observed_at, bool)
        and isinstance(next_observed_at, int)
        and not isinstance(next_observed_at, bool)
        and current_observed_at <= next_observed_at
    ):
        health[marker_field] = copy.deepcopy(marker)


def _mark_initial_rollback_incomplete(
    session_id: str,
    prepared: dict[str, Any],
    state_store: StateStore,
    observed_task: dict[str, Any],
    *,
    error: str,
    now: int,
) -> bool:
    task_id = str(prepared["task_id"])
    attempt = int(prepared["attempt"])

    def same_observed_task(state: dict[str, Any]) -> bool:
        return state.get("tasks", {}).get(task_id) == observed_task

    def mark(state: dict[str, Any]) -> bool:
        task = state["tasks"].get(task_id)
        record = (
            _canonical_execution_for_attempt(task, attempt)
            if isinstance(task, dict)
            else None
        )
        if not isinstance(task, dict) or not isinstance(record, dict):
            raise StateConflictError(
                "rollback-incomplete task/attempt 已不存在，无法持久化 reconcile 标记"
            )
        marker = {
            "status": "rollback_incomplete",
            "task_ref": str(prepared["task_ref"]),
            "observed_at": now,
            "error": _bounded(error),
        }
        _apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
        record["initial_preparation_rollback"] = copy.deepcopy(marker)
        record_updated_at = record.get("updated_at")
        record["updated_at"] = (
            max(record_updated_at, now)
            if isinstance(record_updated_at, int)
            and not isinstance(record_updated_at, bool)
            else now
        )
        health = state.get("health")
        if not isinstance(health, dict):
            raise StateValidationError("治理状态字段 health 必须是对象")
        _merge_initial_rollback_health(health, marker)
        return True

    return state_store.compare_and_set(
        session_id,
        same_observed_task,
        mark,
        required_fields=("tasks", "tombstones"),
    )


def _cleanup_initial_attempt(
    session_id: str,
    prepared: dict[str, Any],
    state_store: StateStore,
    *,
    error_context: str,
    now: int,
) -> dict[str, Any]:
    """Delete only the complete initial post-state and report every uncertain edge."""
    task_id = str(prepared["task_id"])
    expected_task = _initial_task_post_state(prepared)
    errors: list[str] = []
    try:
        state = state_store.read(
            session_id, required_fields=("tasks", "tombstones")
        )
    except Exception as exc:
        return {
            "safe_for_prepared_delete": False,
            "task_status": "unknown",
            "marked": False,
            "errors": [f"StateStore readback failure：{exc}"],
        }
    current_task = state.get("tasks", {}).get(task_id)
    if current_task is None:
        return {
            "safe_for_prepared_delete": True,
            "task_status": "absent",
            "marked": False,
            "errors": errors,
        }
    if current_task != expected_task:
        errors.append("完整 initial task post-state 不匹配，检测到并发变化")
    else:
        try:
            state_store.compare_and_set(
                session_id,
                lambda value: value.get("tasks", {}).get(task_id) == expected_task,
                lambda value: value["tasks"].pop(task_id),
                required_fields=("tasks", "tombstones"),
            )
            return {
                "safe_for_prepared_delete": True,
                "task_status": "deleted",
                "marked": False,
                "errors": errors,
            }
        except Exception as exc:
            errors.append(f"StateStore task cleanup failure：{exc}")
            try:
                state = state_store.read(
                    session_id, required_fields=("tasks", "tombstones")
                )
            except Exception as readback_exc:
                errors.append(f"StateStore cleanup readback failure：{readback_exc}")
                return {
                    "safe_for_prepared_delete": False,
                    "task_status": "unknown",
                    "marked": False,
                    "errors": errors,
                }
            current_task = state.get("tasks", {}).get(task_id)
            if current_task is None:
                return {
                    "safe_for_prepared_delete": True,
                    "task_status": "deleted_after_error",
                    "marked": False,
                    "errors": errors,
                }
            if current_task != expected_task:
                errors.append("task cleanup 异常后完整 task 已发生并发变化")

    marked = False
    if isinstance(current_task, dict):
        try:
            marked = _mark_initial_rollback_incomplete(
                session_id,
                prepared,
                state_store,
                copy.deepcopy(current_task),
                error=f"{error_context}；{'；'.join(errors)}",
                now=now,
            )
        except Exception as mark_exc:
            errors.append(f"rollback-incomplete reconcile 标记失败：{mark_exc}")
    return {
        "safe_for_prepared_delete": False,
        "task_status": "diverged" if current_task != expected_task else "retained",
        "marked": marked,
        "errors": errors,
    }


def _dispatch_admission_error(
    task: dict[str, Any], source_attempt: int
) -> str | None:
    work_item = task.get("work_item")
    if not isinstance(work_item, dict):
        return "managed task 缺少 canonical work_item"
    if work_item.get("lifecycle") != "open":
        return "work item 已关闭或 tombstoned，禁止新增或重派 execution"
    source = _canonical_execution_for_attempt(task, source_attempt)
    if not isinstance(source, dict):
        return "来源 execution 不存在"
    if _execution_is_closed(source) is True:
        return "来源 execution 已关闭，禁止新增或重派 execution"
    return None


_dispatch_admission_error = _dispatch.dispatch_admission_error


def _restore_prepared_spawn_claim(
    session_id: str,
    task_ref: str,
    prepared_store: PreparedContractStore,
    before_claim: dict[str, Any],
    claimed: dict[str, Any],
) -> str:
    current = prepared_store.read(session_id, task_ref)
    if current == before_claim:
        return "not_persisted"
    if current != claimed:
        raise PreparedContractConflictError(
            "PreparedContract claim 后发生并发变化，无法安全恢复未消费状态"
        )

    def restore(value: dict[str, Any]) -> None:
        value.clear()
        value.update(copy.deepcopy(before_claim))

    try:
        prepared_store.compare_and_set(
            session_id,
            task_ref,
            lambda value: value == claimed,
            restore,
        )
    except Exception as restore_exc:
        try:
            recovered = prepared_store.read(session_id, task_ref)
        except Exception as readback_exc:
            raise PreparedContractConflictError(
                "PreparedContract claim 补偿失败且无法回读实际状态："
                f"{restore_exc}；{readback_exc}"
            ) from restore_exc
        if recovered == before_claim:
            return "restored"
        raise PreparedContractConflictError(
            "PreparedContract claim 补偿失败且实际状态未恢复："
            f"{restore_exc}"
        ) from restore_exc
    return "restored"


def _claim_prepared_spawn_contract(
    session_id: str,
    task_ref: str,
    tool_use_id: str,
    claimed_at: int,
    prepared: dict[str, Any],
    prepared_store: PreparedContractStore,
) -> dict[str, Any]:
    before_claim = copy.deepcopy(prepared)
    claimed = copy.deepcopy(prepared)
    claimed.update(
        {
            "consumed": True,
            "tool_use_id": tool_use_id,
            "claimed_at": claimed_at,
        }
    )

    def apply_claim(value: dict[str, Any]) -> None:
        value.clear()
        value.update(copy.deepcopy(claimed))

    try:
        prepared_store.compare_and_set(
            session_id,
            task_ref,
            lambda value: value == before_claim,
            apply_claim,
        )
    except Exception as claim_exc:
        try:
            _restore_prepared_spawn_claim(
                session_id,
                task_ref,
                prepared_store,
                before_claim,
                claimed,
            )
        except Exception as recovery_exc:
            raise PreparedContractConflictError(
                "PreparedContract claim 失败且补偿未完成，治理状态 degraded："
                f"{recovery_exc}"
            ) from claim_exc
        raise
    return claimed


def _rollback_persisted_spawn_claim(
    session_id: str,
    task_id: str,
    state_store: StateStore,
    claim_snapshot: dict[str, Any],
) -> str:
    """Restore one claim only when the persisted task is exactly this claim's post-state."""
    before_task = claim_snapshot.get("before_task")
    claimed_task = claim_snapshot.get("claimed_task")
    if not isinstance(before_task, dict) or not isinstance(claimed_task, dict):
        return "not_observed"
    state = state_store.read(session_id, required_fields=("tasks", "tombstones"))
    current_task = state.get("tasks", {}).get(task_id)
    if current_task == before_task:
        return "not_persisted"
    if current_task != claimed_task:
        raise StateConflictError(
            "spawn claim 已持久化后发生并发变化，无法安全恢复 pre-claim 状态"
        )

    def matches_claimed_task(current: dict[str, Any]) -> bool:
        return current.get("tasks", {}).get(task_id) == claimed_task

    def restore(current: dict[str, Any]) -> None:
        current["tasks"][task_id] = copy.deepcopy(before_task)

    state_store.compare_and_set(
        session_id,
        matches_claimed_task,
        restore,
        required_fields=("tasks", "tombstones"),
    )
    return "restored"


def _cleanup_unclaimed_prepared_dispatch(
    session_id: str,
    prepared: dict[str, Any],
    state_store: StateStore,
) -> bool:
    operation = prepared.get("dispatch_operation")
    if operation == "initial_spawn":
        return _cleanup_initial_attempt(
            session_id,
            prepared,
            state_store,
            error_context="unclaimed initial PreparedContract expiry",
            now=_now(),
        )
    if operation == "spawn_retry":
        return False
    raise PreparedContractConflictError(
        f"未知 PreparedContract dispatch operation：{operation}"
    )


def _occupied_task_refs(
    session_id: str,
    state_store: StateStore,
    prepared_store: PreparedContractStore,
) -> set[str]:
    state = state_store.read(session_id, required_fields=("tasks", "tombstones"))
    occupied = prepared_store.refs(session_id)
    tasks = state.get("tasks", {})
    tombstones = state.get("tombstones", {})
    for collection in (tasks, tombstones):
        if isinstance(collection, dict):
            if collection is tasks:
                for task_id in tasks:
                    for _attempt, record in _task_attempt_records(state, str(task_id)):
                        if isinstance(record.get("task_ref"), str):
                            occupied.add(record["task_ref"])
            else:
                for record in collection.values():
                    if isinstance(record, dict) and isinstance(record.get("task_ref"), str):
                        occupied.add(record["task_ref"])
    return occupied


def prepare_dispatch(
    contract_value: Any,
    session_id: str,
    *,
    state_store: StateStore | None = None,
    prepared_store: PreparedContractStore | None = None,
    task_id_factory: Callable[[], str] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    if not isinstance(session_id, str) or not session_id.strip():
        raise DispatchPreparationError("session_id 必须是非空字符串")
    active_state_store = state_store or _default_state_store()
    active_prepared_store = prepared_store or PreparedContractStore(
        _prepared_root_for_store(active_state_store)
    )
    contract = _contract_from_input(contract_value)
    try:
        context_verification = verify_context_manifest(contract.context_manifest)
    except ContextVerificationError as exc:
        raise DispatchPreparationError(f"必需上下文验证失败：{exc}") from exc
    factory = task_id_factory or _new_task_id
    created_at = _now() if now is None else now
    occupied = _occupied_task_refs(session_id, active_state_store, active_prepared_store)
    selected: tuple[str, str] | None = None
    for _generation in range(2):
        task_id = factory()
        if not isinstance(task_id, str) or not task_id.strip():
            raise DispatchPreparationError("task_id_factory 必须返回非空字符串")
        task_ref = select_task_ref(task_id, 1, occupied)
        if task_ref is not None:
            selected = task_id, task_ref
            break
    if selected is None:
        raise DispatchPreparationError("两个新 task_id 均无法在32位内取得唯一 task_ref")
    task_id, task_ref = selected
    task_name = build_task_name(contract.resolved_mode, contract.semantic_name, task_ref)
    spawn_args = _spawn_args(contract, task_name, context_verification)
    prepared = _prepared_record(
        session_id,
        task_id,
        1,
        task_ref,
        task_name,
        contract,
        context_verification,
        spawn_args,
        created_at=created_at,
        spawn_retry_count=0,
        dispatch_operation="initial_spawn",
    )
    initial = _initial_task_record(
        1,
        task_ref,
        task_name,
        contract,
        created_at,
    )
    try:
        _dispatch.prepare_initial_transaction(
            session_id, prepared, task_id, initial, active_state_store,
            active_prepared_store,
            lambda state: _task_ref_occupied(state, task_ref),
        )
        verified_prepared = active_prepared_store.read(session_id, task_ref)
        verified_state = active_state_store.read(session_id, required_fields=("tasks", "tombstones"))
        verified_task = _task_record_for_attempt(verified_state, task_id, 1)
        if (
            verified_prepared.get("task_name") != task_name
            or verified_prepared.get("resolved_mode") != contract.resolved_mode
            or verified_prepared.get("contract_digest") != contract_digest(contract)
            or verified_task is None
            or verified_task.get("task_ref") != task_ref
            or verified_task.get("resolved_mode") != contract.resolved_mode
            or verified_task.get("contract_digest") != contract_digest(contract)
        ):
            raise DispatchPreparationError("PreparedContract 与 StateStore 双门禁回读不一致")
    except Exception as exc:
        original_error = _exception_chain_text(exc)
        cleanup = _cleanup_initial_attempt(
            session_id,
            prepared,
            active_state_store,
            error_context=original_error,
            now=created_at,
        )
        cleanup_errors = list(cleanup["errors"])
        prepared_cleanup_failed = False
        if cleanup["safe_for_prepared_delete"]:
            try:
                active_prepared_store.delete_if(
                    session_id,
                    task_ref,
                    lambda value: value == prepared,
                )
            except Exception as cleanup_exc:
                prepared_cleanup_failed = True
                cleanup_errors.append(
                    f"PreparedContract cleanup failure：{cleanup_exc}；"
                    "task 已安全 absent，orphan PreparedContract retained"
                )
        if not cleanup["safe_for_prepared_delete"]:
            marker_status = (
                "rollback-incomplete 已持久化为 action-required"
                if cleanup["marked"]
                else "rollback-incomplete 无法持久化 reconcile 标记"
            )
            details = "；".join(cleanup_errors) or "无法确认 canonical task post-state"
            raise DispatchPreparationError(
                "受治理派发准备失败，治理状态 degraded / rollback-incomplete；"
                f"原始错误：{original_error}；{details}；{marker_status}；"
                "PreparedContract retained，可由显式 reconcile/expiry 重试"
            ) from exc
        if cleanup_errors:
            status = (
                "治理状态 degraded / rollback-incomplete"
                if prepared_cleanup_failed
                else "治理状态 degraded，exact rollback 已完成但 cleanup error 可见"
            )
            raise DispatchPreparationError(
                f"受治理派发准备失败，{status}；原始错误：{original_error}；"
                f"{'；'.join(cleanup_errors)}"
            ) from exc
        if isinstance(exc, DispatchPreparationError):
            raise
        raise DispatchPreparationError(
            "受治理派发准备失败，exact rollback 已完成，未允许原生 spawn："
            f"{original_error}"
        ) from exc
    return {
        "task_id": task_id,
        "attempt": 1,
        "task_ref": task_ref,
        "task_name": task_name,
        "contract": contract.to_record(),
        "contract_digest": contract_digest(contract),
        "context_verification": copy.deepcopy(context_verification),
        "user_message": render_dispatch_user_message(contract, context_verification),
        "dispatch_prompt": spawn_args["message"],
        "spawn_args": spawn_args,
    }


def prepare_spawn_retry(
    contract_value: Any,
    session_id: str,
    task_id: str,
    *,
    authorized: bool = False,
    state_store: StateStore | None = None,
    prepared_store: PreparedContractStore | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    active_state_store = state_store or _default_state_store()
    active_prepared_store = prepared_store or PreparedContractStore(
        _prepared_root_for_store(active_state_store)
    )
    state = active_state_store.read(session_id)
    task = state.get("tasks", {}).get(task_id)
    if not isinstance(task, dict) or task.get("managed") is not True:
        raise DispatchPreparationError(f"找不到受治理任务：{task_id}")
    # Retry preparation only accepts the persisted canonical work-item shape.
    try:
        canonical_task = _ensure_canonical_task_record(state, task_id)
        current_attempt = canonical_task["work_item"].get("current_attempt")
        record = _canonical_execution_for_attempt(canonical_task, int(current_attempt))
    except (KeyError, TypeError, ValueError, StateStoreError) as exc:
        raise DispatchPreparationError(f"canonical retry execution 不可读：{exc}") from exc
    if not isinstance(record, dict):
        raise DispatchPreparationError("canonical work_item 缺少当前 retry execution")
    admission_error = _dispatch_admission_error(canonical_task, int(current_attempt))
    if admission_error:
        raise DispatchPreparationError(admission_error)
    if (
        _spawn_observation(record) != "failed"
        or _identity_status(record) != "unconfirmed"
        or not _dispatch_reliably_not_created(record)
    ):
        raise DispatchPreparationError("只有明确 failed 且身份未确认的 spawn 才能同 attempt 重派")
    current_count = record.get("spawn_retry_count")
    if current_count == 0:
        desired_count = 1
    elif current_count == 1 and authorized:
        desired_count = 2
    elif current_count == 1:
        raise DispatchPreparationError("最后一次同 attempt 重派需要用户明确授权")
    else:
        raise DispatchPreparationError("同 attempt spawn 重派次数已经耗尽")
    contract = _contract_from_input(contract_value)
    if contract_digest(contract) != record.get("contract_digest"):
        raise DispatchPreparationError("重派 TaskContract 与原 attempt 的完整契约不一致")
    try:
        context_verification = verify_context_manifest(contract.context_manifest)
    except ContextVerificationError as exc:
        raise DispatchPreparationError(f"重派必需上下文验证失败：{exc}") from exc
    task_ref = str(record.get("task_ref") or "")
    task_name = str(record.get("task_name") or "")
    if parse_task_name(task_name) is None:
        raise DispatchPreparationError("原 attempt 缺少合法 task_name/task_ref")
    prepared_at = _now() if now is None else now
    retry_attempt = int(current_attempt)
    spawn_args = _spawn_args(contract, task_name, context_verification)
    prepared = _prepared_record(
        session_id,
        task_id,
        retry_attempt,
        task_ref,
        task_name,
        contract,
        context_verification,
        spawn_args,
        created_at=prepared_at,
        spawn_retry_count=desired_count,
        dispatch_operation="spawn_retry",
    )
    try:
        def validate_retry_state(current: dict[str, Any]) -> None:
            retry_task = _ensure_canonical_task_record(current, task_id)
            retry_execution = _canonical_execution_for_attempt(
                retry_task, retry_attempt
            )
            if (
                retry_execution is None
                or retry_execution.get("updated_at") != record.get("updated_at")
                or retry_execution.get("spawn_retry_count") != current_count
            ):
                raise StateConflictError("spawn retry 前置状态已变化")

        _dispatch.prepare_retry_transaction(
            session_id, prepared, active_state_store, active_prepared_store,
            validate_retry_state,
        )
        verified_prepared = active_prepared_store.read(session_id, task_ref)
        verified_state = active_state_store.read(session_id)
        verified_task = _task_record_for_attempt(
            verified_state,
            task_id,
            retry_attempt,
        )
        if (
            verified_prepared != prepared
            or verified_task is None
            or verified_task.get("task_ref") != task_ref
            or verified_task.get("task_name") != task_name
            or verified_task.get("resolved_mode") != contract.resolved_mode
            or verified_task.get("contract_digest") != contract_digest(contract)
        ):
            raise DispatchPreparationError(
                "spawn retry PreparedContract 与 StateStore 双门禁回读不一致"
            )
    except Exception as exc:
        rollback_errors: list[str] = []
        try:
            active_prepared_store.delete_if(
                session_id,
                task_ref,
                lambda value: value == prepared,
                missing_ok=False,
            )
        except Exception as cleanup_exc:
            rollback_errors.append(f"PreparedContract 回滚失败：{cleanup_exc}")
        if rollback_errors:
            raise DispatchPreparationError(
                "spawn retry 准备失败且回滚不完整：" + "；".join(rollback_errors)
            ) from exc
        if isinstance(exc, DispatchPreparationError):
            raise
        raise DispatchPreparationError(f"spawn retry PreparedContract 写入失败：{exc}") from exc
    return {
        "task_id": task_id,
        "attempt": retry_attempt,
        "task_ref": task_ref,
        "task_name": task_name,
        "contract": contract.to_record(),
        "contract_digest": contract_digest(contract),
        "context_verification": copy.deepcopy(context_verification),
        "user_message": render_dispatch_user_message(contract, context_verification),
        "dispatch_prompt": spawn_args["message"],
        "spawn_args": spawn_args,
    }


def _expired_unclaimed_initial_without_credential(
    task: Any,
    *,
    prepared_refs: set[str],
    cutoff: int,
) -> bool:
    """Prove that one initial dispatch can no longer create a native Agent."""
    if not isinstance(task, dict) or task.get("managed") is not True:
        return False
    work_item = task.get("work_item")
    executions = task.get("executions")
    if (
        work_item != {"current_attempt": 1, "lifecycle": "open"}
        or not isinstance(executions, dict)
        or set(executions) != {"1"}
    ):
        return False
    execution = executions.get("1")
    if not isinstance(execution, dict):
        return False
    task_ref = execution.get("task_ref")
    updated_at = execution.get("updated_at")
    if (
        not isinstance(task_ref, str)
        or not task_ref
        or task_ref in prepared_refs
        or isinstance(updated_at, bool)
        or not isinstance(updated_at, int)
        or updated_at > cutoff
    ):
        return False
    if execution.get("spawn_retry_count") != 0 or execution.get("recovery_count") != 0:
        return False
    if any(
        field_name in execution
        for field_name in (
            "pending_action",
            "last_lifecycle_operation",
            "initial_preparation_rollback",
        )
    ):
        return False
    if execution.get("dispatch_record") != {
        "dispatch_state": "prepared",
        "dispatch_target": None,
        "tool_use_id": None,
    }:
        return False
    if execution.get("observation_record") != {
        "observed_at": None,
        "observed_state": "not_observed",
        "source": None,
        "terminal_status": None,
    }:
        return False
    if execution.get("closure_record") != {
        "closed_at": None,
        "parent_action": None,
        "reason": None,
    }:
        return False
    parsed_name = parse_task_name(execution.get("task_name"))
    return bool(parsed_name is not None and parsed_name[2] == task_ref)


def _close_expired_unclaimed_initials_without_credentials(
    session_id: str,
    *,
    state_store: StateStore,
    prepared_store: PreparedContractStore,
    now: int,
) -> int:
    prepared_refs = prepared_store.refs(session_id)
    cutoff = now - int(RETENTION_SECONDS["prepared_unclaimed"])
    state = state_store.read(
        session_id,
        required_fields=("tasks", "tombstones"),
    )
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        raise StateValidationError("治理状态缺少 tasks 对象")
    candidates = [
        (str(task_id), copy.deepcopy(task))
        for task_id, task in tasks.items()
        if _expired_unclaimed_initial_without_credential(
            task,
            prepared_refs=prepared_refs,
            cutoff=cutoff,
        )
    ]
    closed = 0
    reason = "automatic_close:expired_unclaimed_dispatch"
    for task_id, expected_task in sorted(candidates):
        def predicate(current: dict[str, Any]) -> bool:
            return current.get("tasks", {}).get(task_id) == expected_task

        def close(current: dict[str, Any]) -> None:
            task = current["tasks"][task_id]
            execution = task["executions"]["1"]
            _close_attempt_record(
                current,
                task_id,
                1,
                execution,
                reason,
                now,
            )
            task["work_item"]["lifecycle"] = "tombstoned"

        try:
            state_store.compare_and_set(
                session_id,
                predicate,
                close,
                required_fields=("tasks", "tombstones"),
            )
        except StateConflictError:
            continue
        closed += 1
    return closed


def reconcile_prepared_dispatches(
    session_id: str,
    *,
    state_store: StateStore,
    prepared_store: PreparedContractStore,
    now: int | None = None,
) -> dict[str, int]:
    current_time = _now() if now is None else now
    expired = 0
    reconciled = 0
    for prepared in prepared_store.list_records(session_id):
        task_id = str(prepared["task_id"])
        attempt = int(prepared["attempt"])
        task_ref = str(prepared["task_ref"])
        if prepared["consumed"] is False:
            if prepared["created_at"] <= current_time - int(RETENTION_SECONDS["prepared_unclaimed"]):
                if prepared.get("dispatch_operation") == "initial_spawn":
                    cleanup = _cleanup_initial_attempt(
                        session_id,
                        prepared,
                        state_store,
                        error_context="unclaimed initial PreparedContract expiry",
                        now=current_time,
                    )
                    if not cleanup["safe_for_prepared_delete"]:
                        marker_status = (
                            "rollback-incomplete 已持久化为 action-required"
                            if cleanup["marked"]
                            else "rollback-incomplete 无法持久化 reconcile 标记"
                        )
                        details = "；".join(cleanup["errors"])
                        raise PreparedContractConflictError(
                            "过期 initial PreparedContract 清理进入 degraded / "
                            f"rollback-incomplete：{details}；{marker_status}；"
                            "PreparedContract retained，可由显式 reconcile/expiry 重试；"
                            f"task_id={task_id}, attempt={attempt}"
                        )
                    try:
                        prepared_store.delete_if(
                            session_id,
                            task_ref,
                            lambda value: value == prepared,
                        )
                    except Exception as cleanup_exc:
                        raise PreparedContractConflictError(
                            "过期 initial PreparedContract 清理进入 degraded / "
                            "rollback-incomplete：PreparedContract cleanup failure："
                            f"{cleanup_exc}；task 已安全 absent，orphan PreparedContract retained；"
                            f"task_id={task_id}, attempt={attempt}"
                        ) from cleanup_exc
                    if cleanup["errors"]:
                        raise PreparedContractConflictError(
                            "过期 initial PreparedContract exact rollback 已完成，"
                            "但 cleanup error 可见："
                            f"{'；'.join(cleanup['errors'])}；"
                            f"task_id={task_id}, attempt={attempt}"
                        )
                    expired += 1
                    continue
                try:
                    _cleanup_unclaimed_prepared_dispatch(
                        session_id, prepared, state_store
                    )
                except (StateConflictError, PreparedContractConflictError) as exc:
                    raise PreparedContractConflictError(
                        "过期 PreparedContract 对应 execution 已发生并发变化，"
                        f"无法安全回滚：task_id={task_id}, attempt={attempt}"
                    ) from exc
                prepared_store.delete_if(
                    session_id, task_ref, lambda value: value == prepared
                )
                expired += 1
            continue
        if _dispatch.reconcile_claimed_spawn(
            session_id, prepared, current_time,
            int(RETENTION_SECONDS["claimed_reconcile"]), state_store, prepared_store,
        ):
            reconciled += 1
    expired += _close_expired_unclaimed_initials_without_credentials(
        session_id,
        state_store=state_store,
        prepared_store=prepared_store,
        now=current_time,
    )
    return {"expired": expired, "reconciled": reconciled}


COMMUNICATION_FIELD_LABELS = (
    ("purpose", "通信目的"),
    ("reason", "通信原因"),
    ("content", "具体内容"),
    ("expected_result", "期望结果"),
)






































def _native_status_tag(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized or None
    if not isinstance(value, dict) or len(value) != 1:
        return None
    status, detail = next(iter(value.items()))
    if not isinstance(status, str) or detail is None or detail is False:
        return None
    normalized = status.strip().lower()
    return normalized or None


def adapt_call_response(response: Any, operation_type: str) -> dict[str, str | None]:
    def adapted(
        call_observation: str,
        *,
        target_observation: str | None = None,
    ) -> dict[str, str | None]:
        return {
            "call_observation": call_observation,
            "target_observation": target_observation,
        }

    value = _json_value(response)
    if value is None or value == "" or value == {}:
        return adapted("success")
    if not isinstance(value, dict):
        return adapted("unknown")
    if value.get("isError") is True or value.get("is_error") is True:
        return adapted("failed")
    status_value = value.get("status") if "status" in value else value.get("state")
    status = _native_status_tag(status_value)
    if status in {"error", "failed", "failure"}:
        return adapted("failed")
    if value.get("success") is True or status in {"ok", "success", "succeeded", "sent", "accepted"}:
        return adapted("success")
    if operation_type == "interrupt":
        previous_value = value.get("previous_status")
        previous_status = _native_status_tag(previous_value)
        if previous_status == "running":
            return adapted(
                "success",
                target_observation="previously_running",
            )
        if previous_status == "not_found":
            return adapted(
                "success",
                target_observation="not_found",
            )
        if previous_status in {"stopped", "completed", "interrupted", "cancelled", "canceled"}:
            return adapted(
                "success",
                target_observation=previous_status,
            )
        if status in {"interrupted", "cancelled", "canceled", "stopped", "completed"}:
            return adapted(
                "success",
                target_observation=status,
            )
    return adapted("unknown")














def _tool_kind(tool_name: str) -> str | None:
    if tool_name == "Agent" or tool_name.endswith("spawn_agent"):
        return "spawn"
    if tool_name.endswith("followup_task"):
        return "followup"
    if tool_name.endswith("send_message") and not tool_name.endswith("send_message_to_thread"):
        return "communication"
    if tool_name.endswith("interrupt_agent"):
        return "interrupt"
    if tool_name.endswith("list_agents"):
        return "agent_status"
    return None


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _allow_updated(updated_input: dict[str, Any], context: str | None = None) -> dict[str, Any]:
    output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "updatedInput": updated_input,
    }
    if context:
        output["additionalContext"] = context
    return {"hookSpecificOutput": output}


def _bounded(value: Any, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    return text[:MAX_CONTRACT_TEXT]


def _handle_spawn(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return _deny("子 Agent 派发被阻止：spawn_agent 参数不是对象。")
    task_name_value = tool_input.get("task_name")
    task_name = task_name_value if isinstance(task_name_value, str) else ""
    if not task_name.startswith("sg_"):
        return _allow_updated(
            copy.deepcopy(tool_input),
            "Subagent Governance：无治理前缀，本次原生 spawn 按 unmanaged 放行；不创建治理状态。",
        )
    parsed = parse_task_name(task_name)
    if parsed is None:
        return _deny(
            "子 Agent 派发被阻止：governed task_name 必须符合 "
            "sg_<resolved_mode>_<semantic_name>_t_<task_ref>，总长度不超过64字符。"
        )
    mode, _semantic_name, task_ref = parsed
    session_id = str(payload.get("session_id") or "unknown")
    try:
        prepared_store = PreparedContractStore(_prepared_root_for_store(store))
        prepared = prepared_store.read(session_id, task_ref)
    except Exception as exc:
        return _deny(f"子 Agent 派发被阻止：PreparedContract 硬门禁失败：{exc}")
    if prepared.get("consumed") is True:
        return _deny("子 Agent 派发被阻止：PreparedContract 已被消费，不能重复调用原生 spawn。")
    current_time = _now()
    if prepared.get("created_at", 0) <= current_time - int(RETENTION_SECONDS["prepared_unclaimed"]):
        try:
            _cleanup_unclaimed_prepared_dispatch(session_id, prepared, store)
            prepared_store.delete_if(
                session_id, task_ref, lambda value: value == prepared
            )
        except Exception as exc:
            return _deny(f"子 Agent 派发被阻止：过期 PreparedContract 清理失败：{exc}")
        return _deny("子 Agent 派发被阻止：PreparedContract 已超过5分钟，请重新生成派发。")
    expected_native = prepared["native_parameters"]
    mismatches = []
    if prepared.get("task_name") != task_name or prepared.get("resolved_mode") != mode:
        mismatches.append("task_name/resolved_mode")
    for field_name in ("fork_turns", "model", "reasoning_effort"):
        actual = tool_input.get(field_name)
        expected = expected_native.get(field_name)
        if actual != expected:
            mismatches.append(field_name)
    if mismatches:
        return _deny(
            "子 Agent 派发被阻止：原生可观察参数与 PreparedContract 不一致："
            + "、".join(mismatches)
        )
    try:
        prepared_contract = _contract_from_input(prepared["contract"])
        current_context_verification = verify_context_manifest(
            prepared_contract.context_manifest
        )
    except (ContextVerificationError, TypeError, ValueError) as exc:
        return _deny(f"子 Agent 派发被阻止：必需上下文二次验证失败：{exc}")
    if current_context_verification != prepared.get("context_verification"):
        return _deny(
            "子 Agent 派发被阻止：必需上下文在 prepare 与 spawn 之间发生变化，"
            "请重新生成派发。"
        )
    task_id = str(prepared["task_id"])
    attempt = int(prepared["attempt"])
    desired_retry_count = int(prepared["spawn_retry_count"])
    dispatch_operation = str(prepared["dispatch_operation"])
    tool_use_id = str(payload.get("tool_use_id") or "")
    if not tool_use_id:
        return _deny("子 Agent 派发被阻止：缺少 tool_use_id，无法单次消费 PreparedContract。")
    try:
        _dispatch.claim_spawn(
            session_id, task_ref, tool_use_id, current_time, prepared,
            store, prepared_store,
        )
    except Exception as exc:
        return _deny(f"子 Agent 派发被阻止：StateStore/PreparedContract 认领失败：{exc}")
    return _allow_updated(
        copy.deepcopy(tool_input),
        f"Subagent Governance 已消费 task_ref={task_ref} 的派发凭证并完成发送前双门禁。",
    )












def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _agent_status_entries(response: Any) -> list[dict[str, Any]] | None:
    """Adapt only the evidenced top-level list_agents response container."""
    value = _json_value(response)
    if not isinstance(value, dict):
        return None
    for error_flag in LIST_AGENTS_BOOLEAN_ERROR_FLAGS:
        if error_flag not in value:
            continue
        flag_value = value[error_flag]
        if not isinstance(flag_value, bool) or flag_value:
            return None
    if (
        LIST_AGENTS_EXPLICIT_ERROR_FIELD in value
        and value[LIST_AGENTS_EXPLICIT_ERROR_FIELD] is not None
        and value[LIST_AGENTS_EXPLICIT_ERROR_FIELD] is not False
    ):
        return None
    for status_field in LIST_AGENTS_WRAPPER_STATUS_FIELDS:
        if status_field not in value:
            continue
        wrapper_status = _native_status_tag(value[status_field])
        if wrapper_status is None:
            return None
        if wrapper_status in LIST_AGENTS_WRAPPER_ERROR_STATUSES:
            return None
    agents = value.get("agents")
    if not isinstance(agents, list) or not all(
        isinstance(entry, dict) for entry in agents
    ):
        return None
    return agents


def _list_agents_exact_target(tool_input: Any) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    value = tool_input.get("path_prefix")
    if not isinstance(value, str):
        return None
    return value if value.startswith("/") else None


def _normalized_agent_status(value: Any) -> tuple[str, str | None]:
    status = _native_status_tag(value)
    if status is not None:
        if status in (
            LIST_AGENTS_ACTIVE_STATUSES
            | LIST_AGENTS_ADVISORY_STATUSES
            | LIST_AGENTS_TERMINAL_STATUSES
        ):
            return status, status
        if status in LIST_AGENTS_ERROR_STATUSES:
            detail = value.get(status) if isinstance(value, dict) else status
            return "error", _bounded(detail, status)
        return "unknown", status or None
    return "unknown", None














def _handle_post_tool_spawn(
    payload: dict[str, Any], store: StateStore, session_id: str
) -> dict[str, Any] | None:
    tool_use_id = str(payload.get("tool_use_id") or "")
    response = payload.get("tool_response")
    try:
        prepared_store = PreparedContractStore(_prepared_root_for_store(store))
        prepared = prepared_store.find_claimed(session_id, tool_use_id)
    except Exception as exc:
        return {"systemMessage": f"Subagent Governance 无法读取派发凭证，需人工对账：{exc}"}
    if prepared is None:
        return None
    observation = adapt_spawn_response(response)
    task_id = str(prepared["task_id"])
    attempt = int(prepared["attempt"])
    task_ref = str(prepared["task_ref"])
    observed_at = _now()

    def predicate(state: dict[str, Any]) -> bool:
        record = _task_record_for_attempt(state, task_id, attempt)
        return bool(
            record
            and record.get("task_ref") == task_ref
            and _dispatch_tool_use_id(record) == tool_use_id
            and _spawn_observation(record) is None
        )

    post_resolution = {"positive_evidence_preserved": False}

    def update_spawn(state: dict[str, Any]) -> None:
        _ensure_canonical_task_record(state, task_id)
        record = _task_record_for_attempt(state, task_id, attempt)
        assert record is not None
        reported_spawn_observation = str(observation["observation"])
        positive_evidence_preserved = bool(
            reported_spawn_observation == "failed"
            and _has_canonical_positive_execution_evidence(record)
        )
        post_resolution["positive_evidence_preserved"] = positive_evidence_preserved
        spawn_observation = (
            "unknown" if positive_evidence_preserved else reported_spawn_observation
        )
        _apply_canonical_execution_update(record, "dispatch_response", spawn_observation)
        record["updated_at"] = observed_at
        if positive_evidence_preserved:
            _apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
        elif spawn_observation == "failed":
            _apply_canonical_execution_update(
                record,
                "observed_execution_status",
                "stopped"
                if record.get("spawn_retry_count") == RETRY_LIMITS["spawn"]
                else "not_started",
            )
            retry_count = int(record.get("spawn_retry_count") or 0)
            if retry_count == 0:
                _apply_canonical_execution_update(record, "closure_parent_action", "retry_spawn")
            elif retry_count == 1:
                _apply_canonical_execution_update(record, "closure_parent_action", "ask_user")
            else:
                _apply_canonical_execution_update(record, "closure_parent_action", "decide_disposition")
        else:
            # The response is a dispatch observation only. Lifecycle hooks do
            # not provide a stable correlation key for execution identity.
            _apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
            _apply_canonical_execution_update(
                record,
                "dispatch_target",
                observation.get("canonical_path"),
            )

    try:
        store.compare_and_set(session_id, predicate, update_spawn)
    except StateConflictError:
        return {
            "systemMessage": (
                "Subagent Governance 派发结果与当前 claim 不匹配，已保留较新状态并要求人工对账。"
            )
        }
    except (OSError, RuntimeError) as exc:
        return {"systemMessage": f"Subagent Governance 无法记录派发生命周期，已降级放行：{exc}"}
    delete_prepared = bool(
        observation["observation"] == "failed"
        and not post_resolution["positive_evidence_preserved"]
    )
    warning = (
        "迟到 spawn failure 与已绑定的 canonical active/terminal 事实冲突；"
        "已保留 observation/identity，并进入 reconcile。"
        if post_resolution["positive_evidence_preserved"]
        else None
    )
    try:
        if delete_prepared:
            prepared_store.delete_if(
                session_id, task_ref, lambda value: value == prepared
            )
        else:
            prepared_store.compare_and_set(
                session_id,
                task_ref,
                lambda value: value.get("tool_use_id") == tool_use_id,
                lambda value: value.update({"post_observed_at": observed_at}),
            )
    except Exception as exc:
        warning = f"派发状态已记录，但 PreparedContract 收缩失败：{exc}"
    if warning or getattr(store, "last_warning", None):
        return {"systemMessage": warning or str(store.last_warning)}
    return None


def _handle_post_tool_spawn(
    payload: dict[str, Any], store: StateStore, session_id: str
) -> dict[str, Any] | None:
    """Hook adapter: normalize platform output and format dispatch-domain facts."""
    tool_use_id = str(payload.get("tool_use_id") or "")
    try:
        prepared_store = PreparedContractStore(_prepared_root_for_store(store))
        prepared = prepared_store.find_claimed(session_id, tool_use_id)
    except Exception as exc:
        return {"systemMessage": f"Subagent Governance 无法读取派发凭证，需人工对账：{exc}"}
    if prepared is None:
        return None
    try:
        warning = _dispatch.observe_spawn_post_tool(
            session_id, prepared, adapt_spawn_response(payload.get("tool_response")),
            _now(), store, prepared_store,
        )
    except StateConflictError:
        return {"systemMessage": "Subagent Governance 派发结果与当前 claim 不匹配，已保留较新状态并要求人工对账。"}
    except (OSError, RuntimeError) as exc:
        return {"systemMessage": f"Subagent Governance 无法记录派发生命周期，已降级放行：{exc}"}
    except Exception as exc:
        return {"systemMessage": f"派发状态已记录或保留，但 PreparedContract 收缩失败：{exc}"}
    if warning or getattr(store, "last_warning", None):
        return {"systemMessage": warning or str(store.last_warning)}
    return None


def _handle_post_tool(payload: dict[str, Any], store: StateStore) -> dict[str, Any] | None:
    session_id = str(payload.get("session_id") or "unknown")
    kind = _tool_kind(str(payload.get("tool_name") or ""))
    if kind == "agent_status":
        return _handle_post_tool_agent_status(payload, store, session_id)
    if kind in {"communication", "followup", "interrupt"}:
        return _handle_post_tool_lifecycle(payload, store, session_id)
    if kind == "spawn":
        return _handle_post_tool_spawn(payload, store, session_id)
    return None


# P6 lifecycle APIs are owned by the transaction module.  The runtime keeps
# only the Hook transport adapter surface; these explicit aliases preserve the
# existing public facade without a proxy or a second public implementation.
try:
    from scripts import governance_lifecycle as _lifecycle
except ModuleNotFoundError:
    import governance_lifecycle as _lifecycle

record_terminal_notification = _lifecycle.record_terminal_notification
apply_parent_disposition = _lifecycle.apply_parent_disposition
prepare_communication = _lifecycle.prepare_communication
prepare_interrupt = _lifecycle.prepare_interrupt
reconcile_interrupted_attempt = _lifecycle.reconcile_interrupted_attempt
reconcile_pending_actions = _lifecycle.reconcile_pending_actions
_business_resume_allowed = _lifecycle._business_resume_allowed
_last_lifecycle_from_pending = _lifecycle._last_lifecycle_from_pending
_pending_action_record = _lifecycle._pending_action_record


def _hook_lifecycle_result(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("decision") == "allow":
        return _allow_updated(value["updated_input"], value.get("context"))
    return _deny(str(value.get("reason") or "受治理 lifecycle 操作被拒绝"))


def _handle_communication(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    return _hook_lifecycle_result(_lifecycle._claim_pending_action(payload, store, interrupt=False))


def _handle_interrupt_pre(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    return _hook_lifecycle_result(_lifecycle._claim_pending_action(payload, store, interrupt=True))


def _handle_post_tool_agent_status(payload: dict[str, Any], store: StateStore, session_id: str) -> dict[str, Any] | None:
    return _lifecycle._handle_post_tool_agent_status(payload, store, session_id)


def _handle_post_tool_lifecycle(payload: dict[str, Any], store: StateStore, session_id: str) -> dict[str, Any] | None:
    return _lifecycle._handle_post_tool_lifecycle(payload, store, session_id)


def _attempt_projection(
    task_id: str,
    attempt: int,
    record: dict[str, Any],
) -> dict[str, Any]:
    projected = copy.copy(record)
    projected["task_id"] = task_id
    projected["attempt"] = attempt
    projected["activity_at"] = _activity_timestamp(record)
    return projected


def _view_attempt_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        raise StateValidationError("治理状态缺少派生视图所需的 tasks 对象")
    for task_id, attempt, record in _iter_task_attempts(state):
        records.append(_attempt_projection(task_id, attempt, record))
    return records


def _attempt_closed(state: dict[str, Any], record: dict[str, Any]) -> bool:
    if _execution_is_closed(record) is True:
        return True
    tombstones = state.get("tombstones")
    key = f"{record.get('task_id')}:{record.get('attempt')}"
    return isinstance(tombstones, dict) and isinstance(tombstones.get(key), dict)


def _managed_call_in_progress(record: dict[str, Any]) -> bool:
    spawn_call = (
        _dispatch_tool_use_id(record) is not None
        and _spawn_observation(record) is None
    )
    pending = record.get("pending_action")
    pending_call = isinstance(pending, dict) and pending.get("phase") in {
        "prepared",
        "claimed",
    }
    lifecycle = record.get("last_lifecycle_operation")
    unresolved_lifecycle = (
        isinstance(lifecycle, dict)
        and lifecycle.get("call_observation") in {"success", "unknown"}
    )
    return spawn_call or pending_call or unresolved_lifecycle


def _canonical_action_required_candidate(
    state: dict[str, Any], record: dict[str, Any]
) -> bool:
    if _attempt_closed(state, record):
        return False
    return bool(
        _parent_action(record) is not None
        or _execution_status(record) == "running"
        or _managed_call_in_progress(record)
        or (
            _identity_status(record) == "unconfirmed"
            and _spawn_observation(record) in {"success", "unknown"}
        )
    )


def _action_priority(record: dict[str, Any]) -> int:
    parent_action = _parent_action(record)
    priority = {
        "recover": 0,
        "reconcile": 1,
        "retry_spawn": 2,
        "ask_user": 3,
        "decide_disposition": 4,
        "wait": 5,
    }
    if parent_action in priority:
        return priority[str(parent_action)]
    return 99


def _action_required_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for record in _view_attempt_records(state):
        if _canonical_action_required_candidate(state, record):
            records.append(record)
    records.sort(
        key=lambda record: (
            _action_priority(record),
            -int(record.get("activity_at") or 0),
            str(record.get("task_id") or ""),
            int(record.get("attempt") or 0),
        )
    )
    return records


def _recent_activity_records(
    state: dict[str, Any], *, now: int | None = None
) -> list[dict[str, Any]]:
    current_time = _now() if now is None else now
    cutoff = current_time - int(RETENTION_SECONDS["recent_activity"])
    records = [
        record
        for record in _view_attempt_records(state)
        if int(record.get("activity_at") or 0) >= cutoff
    ]
    records.sort(
        key=lambda record: (
            -int(record.get("activity_at") or 0),
            str(record.get("task_id") or ""),
            int(record.get("attempt") or 0),
        )
    )
    return records


def _validate_group_value(
    value: Any,
    *,
    expected_group_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GroupValidationError("group 必须是对象")
    group_id = value.get("group_id")
    if (
        not isinstance(group_id, str)
        or not group_id.strip()
        or len(group_id) > GROUP_ID_MAX_LENGTH
    ):
        raise GroupValidationError(
            f"group_id 必须是 1 至 {GROUP_ID_MAX_LENGTH} 字符的非空字符串"
        )
    group_id = group_id.strip()
    if expected_group_id is not None and group_id != expected_group_id:
        raise GroupValidationError("group_id 与 StateStore 键不一致")
    objective = value.get("objective_summary")
    if (
        not isinstance(objective, str)
        or not objective.strip()
        or len(objective) > GROUP_OBJECTIVE_MAX_LENGTH
    ):
        raise GroupValidationError(
            "objective_summary 必须是非空且长度不超过 "
            f"{GROUP_OBJECTIVE_MAX_LENGTH} 的字符串"
        )
    members = value.get("members")
    if not isinstance(members, list):
        raise GroupValidationError("members 必须是数组")
    if len(members) > GROUP_MEMBER_LIMIT:
        raise GroupValidationError(f"members 不能超过 {GROUP_MEMBER_LIMIT} 项")
    normalized_members: list[dict[str, Any]] = []
    seen: set[str] = set()
    task_id_max = int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"])
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            raise GroupValidationError(f"members[{index}] 必须是对象")
        task_id = member.get("task_id")
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or len(task_id) > task_id_max
        ):
            raise GroupValidationError(f"members[{index}].task_id 无效")
        task_id = task_id.strip()
        required = member.get("required")
        if not isinstance(required, bool):
            raise GroupValidationError(f"members[{index}].required 必须是布尔值")
        if task_id in seen:
            raise GroupValidationError(f"group 中存在重复 task_id：{task_id}")
        seen.add(task_id)
        normalized_members.append({"task_id": task_id, "required": required})
    normalized = {
        "group_id": group_id,
        "objective_summary": objective.strip(),
        "members": normalized_members,
    }
    return normalized


def upsert_group(
    value: Any,
    session_id: str,
    *,
    state_store: StateStore | None = None,
) -> dict[str, Any]:
    normalized = _validate_group_value(value)
    store = state_store or _default_state_store()

    def upsert(state: dict[str, Any]) -> dict[str, Any]:
        tasks = state.get("tasks")
        if not isinstance(tasks, dict):
            raise GroupValidationError("治理状态缺少 group 引用所需的 tasks 对象")
        missing = [
            member["task_id"]
            for member in normalized["members"]
            if not isinstance(tasks.get(member["task_id"]), dict)
        ]
        if missing:
            raise GroupValidationError(f"group 引用的 task 不存在：{', '.join(missing)}")
        groups = state.get("groups")
        if groups is None:
            groups = {}
            state["groups"] = groups
        elif not isinstance(groups, dict):
            raise GroupValidationError("治理状态 groups 字段必须是对象")
        existing = groups.get(normalized["group_id"])
        if existing is not None and not isinstance(existing, dict):
            raise GroupValidationError("已有 group 记录必须是对象")
        status = "updated" if isinstance(existing, dict) else "created"
        groups[normalized["group_id"]] = normalized
        return {
            "status": status,
            "group_id": normalized["group_id"],
        }

    return store.update(session_id, upsert, required_fields=("tasks", "agents"))


def _diagnostic_issue(code: str, message: str, **context: Any) -> dict[str, Any]:
    allowed_context = {}
    for key in (
        "session_id",
        "path",
        "field",
        "task_id",
        "attempt",
        "group_id",
        "fact",
    ):
        value = context.get(key)
        if value is None:
            continue
        if isinstance(value, (str, int, bool)):
            allowed_context[key] = value if not isinstance(value, str) else value[:600]
    return {
        "code": code,
        "message": str(message)[:600],
        "context": allowed_context,
    }


def _diagnostic_issue_sort_key(issue: dict[str, Any]) -> tuple[Any, ...]:
    context = issue.get("context") if isinstance(issue.get("context"), dict) else {}
    return (
        str(issue.get("code") or ""),
        str(context.get("session_id") or ""),
        str(context.get("task_id") or ""),
        int(context.get("attempt") or 0),
        str(context.get("group_id") or ""),
        str(context.get("field") or ""),
        str(context.get("path") or ""),
    )


def _attempt_has_reasoned_close(
    state: dict[str, Any], task_id: str, attempt: int, record: dict[str, Any]
) -> bool:
    if not _attempt_closed(
        state,
        {"task_id": task_id, "attempt": attempt, **record},
    ):
        return False
    tombstones = state.get("tombstones")
    tombstone = (
        tombstones.get(f"{task_id}:{attempt}")
        if isinstance(tombstones, dict)
        else None
    )
    reasons = (
        _execution_close_reason(record),
        tombstone.get("close_reason") if isinstance(tombstone, dict) else None,
    )
    return any(isinstance(reason, str) and reason.strip() for reason in reasons)


def _canonical_work_item_view(
    state: dict[str, Any], task_id: str
) -> tuple[dict[str, Any] | None, list[tuple[int, dict[str, Any]]]]:
    tasks = state.get("tasks")
    task = tasks.get(task_id) if isinstance(tasks, dict) else None
    if not isinstance(task, dict) or task.get("managed") is not True:
        return None, []
    work_item = task.get("work_item")
    executions = task.get("executions")
    if isinstance(work_item, dict) and isinstance(executions, dict):
        records = [
            (attempt, record)
            for key, record in executions.items()
            if isinstance(record, dict)
            and (attempt := _parse_execution_key(key)) is not None
        ]
        return work_item, sorted(records)
    return None, []


def _decision_candidate_snapshot(
    state: dict[str, Any],
    record: dict[str, Any],
    *,
    current_attempt: int | None,
    action_required: bool,
) -> dict[str, Any]:
    attempt = record.get("attempt")
    closed = _attempt_closed(state, record)
    if closed:
        role = "tombstoned"
    elif attempt == current_attempt:
        role = "current"
    else:
        role = "prior"
    identity = _identity_status(record)
    identity = identity if identity in IDENTITY_STATUSES else "unknown"
    execution = _execution_status(record)
    execution = execution if execution in EXECUTION_STATUSES else "unknown"
    platform = _platform_observation(record)
    platform = platform if platform in PLATFORM_OBSERVATIONS else "not_checked"
    observation = record.get("observation_record")
    notification_observed = bool(
        isinstance(observation, dict)
        and observation.get("source") == "terminal_notification"
        and observation.get("observed_state") == "terminal"
        and _observation_is_bound(record)
    )
    timestamps = {
        name: value
        for name, value in (
            ("activity_at", record.get("activity_at")),
            ("platform_checked_at", _observation_checked_at(record)),
            ("attempt_closed_at", _execution_closed_at(record)),
        )
        if isinstance(value, int) and not isinstance(value, bool)
    }
    dispatch_target = _dispatch_target(record)
    target = (
        {"dispatch_target": dispatch_target}
        if isinstance(dispatch_target, str)
        else None
    )
    return {
        "attempt": attempt if isinstance(attempt, int) and not isinstance(attempt, bool) else None,
        "role": role,
        "target": target,
        "identity": identity,
        "execution": execution,
        "platform": platform,
        "notification": {
            "observed": notification_observed,
            "source": observation.get("source") if isinstance(observation, dict) else None,
            "terminal_status": (
                observation.get("terminal_status") if isinstance(observation, dict) else None
            ),
        },
        "action_required": action_required,
        "timestamps": timestamps,
    }


def _work_item_allowed_actions(
    records: list[tuple[int, dict[str, Any]]],
    *,
    current_attempt: int | None,
    lifecycle: str,
) -> list[str]:
    if lifecycle == "tombstoned":
        return ["inspect_tombstone"]
    if lifecycle == "indeterminate":
        return ["reconcile"]
    current = next(
        (record for attempt, record in records if attempt == current_attempt), None
    )
    if not isinstance(current, dict):
        return ["reconcile"]
    actions: list[str] = []
    execution = _execution_status(current)
    platform = _platform_observation(current)
    identity = _identity_status(current)
    spawn = _spawn_observation(current)
    observation = current.get("observation_record")
    notification_observed = bool(
        isinstance(observation, dict)
        and observation.get("source") == "terminal_notification"
        and observation.get("observed_state") == "terminal"
    )
    if execution == "running" and identity == "confirmed":
        actions.append("wait")
    if (
        platform == "unknown"
        or spawn == "unknown"
        or identity != "confirmed"
        or _parent_action(current) == "reconcile"
    ):
        actions.append("reconcile")
    if (
        spawn == "failed"
        and _dispatch_reliably_not_created(current)
        and int(current.get("spawn_retry_count") or 0) < int(RETRY_LIMITS["spawn"])
        and identity == "unconfirmed"
    ):
        actions.append("retry_spawn")
    if notification_observed or execution == "interrupted":
        actions.append("close_task")
    contract_ready = bool(current.get("contract_digest") and current.get("contract_summary"))
    if contract_ready and _business_resume_allowed(current):
        actions.append("resume_business")
    order = {name: index for index, name in enumerate(_DECISION_ACTION_ORDER)}
    return sorted(set(actions), key=order.__getitem__)


def _build_work_item_decision_snapshot(
    state: dict[str, Any],
    task_id: str,
    *,
    session_id: str | None = None,
    now: int | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], bool]:
    work_item, records = _canonical_work_item_view(state, task_id)
    if not isinstance(work_item, dict) or not records:
        return None, [
            _diagnostic_issue(
                "current_required_field_invalid",
                "managed work item 缺少可读取 execution",
                session_id=session_id,
                task_id=task_id,
                field="work_item/executions",
            )
        ], True
    issues: list[dict[str, Any]] = []
    incomplete = False
    current_attempt = work_item.get("current_attempt")
    if (
        isinstance(current_attempt, bool)
        or not isinstance(current_attempt, int)
        or current_attempt not in {attempt for attempt, _record in records}
    ):
        current_attempt = None
        incomplete = True
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "work_item.current_attempt 无法关联 canonical execution",
                session_id=session_id,
                task_id=task_id,
                field="work_item.current_attempt",
            )
        )
    current_time = _now() if now is None else now
    cutoff = current_time - int(RETENTION_SECONDS["recent_activity"])
    candidates = []
    work_item_recent_activity = False
    for attempt, source_record in records:
        record = _attempt_projection(task_id, attempt, source_record)
        action_required = _canonical_action_required_candidate(state, record)
        work_item_recent_activity = (
            work_item_recent_activity or int(record.get("activity_at") or 0) >= cutoff
        )
        candidates.append(
            _decision_candidate_snapshot(
                state,
                record,
                current_attempt=current_attempt,
                action_required=action_required,
            )
        )
    persisted_lifecycle = work_item.get("lifecycle")
    all_reasoned_closed = all(
        _attempt_has_reasoned_close(state, task_id, attempt, record)
        for attempt, record in records
    )
    if persisted_lifecycle == "tombstoned" and all_reasoned_closed:
        lifecycle = "tombstoned"
    elif (
        persisted_lifecycle == "open"
        and current_attempt is not None
        and not all_reasoned_closed
    ):
        lifecycle = "open"
    else:
        lifecycle = "indeterminate"
        incomplete = True
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "work-item lifecycle 与 execution close facts 不完整",
                session_id=session_id,
                task_id=task_id,
                field="work_item.lifecycle",
            )
        )
    current_record = next(
        (record for attempt, record in records if attempt == current_attempt), None
    )
    current_candidate = next(
        (candidate for candidate in candidates if candidate.get("attempt") == current_attempt), None
    )
    if isinstance(current_candidate, dict):
        notification = current_candidate.get("notification")
        notification = notification if isinstance(notification, dict) else {}
        notification_state = "observed" if notification.get("observed") is True else "pending"
        notification_attempt = current_attempt
        notification_source = notification.get("source")
        terminal_status = notification.get("terminal_status")
    else:
        notification_state = "unknown"
        notification_attempt = None
        notification_source = None
        terminal_status = None
    allowed_actions = _work_item_allowed_actions(
        records,
        current_attempt=current_attempt,
        lifecycle=lifecycle,
    )
    summary = (
        current_record.get("contract_summary")
        if isinstance(current_record, dict)
        and isinstance(current_record.get("contract_summary"), dict)
        else {}
    )
    objective = summary.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        objective = None
        issues.append(
            _diagnostic_issue(
                "current_required_field_missing",
                "current execution 缺少有界 contract objective",
                session_id=session_id,
                task_id=task_id,
                field="execution.contract_summary.objective",
            )
        )
        incomplete = True
    action_required = any(candidate.get("action_required") is True for candidate in candidates)
    snapshot = {
        "task_id": task_id,
        "objective_summary": str(objective)[:600] if objective is not None else None,
        "current_attempt": current_attempt,
        "lifecycle": lifecycle,
        "action_required": action_required,
        "recent_activity": work_item_recent_activity,
        "execution_candidates": candidates,
        "terminal_notification": {
            "state": notification_state,
            "attempt": notification_attempt,
            "source": notification_source,
            "terminal_status": terminal_status,
        },
        "allowed_actions": allowed_actions,
    }
    return snapshot, issues, incomplete


def _derive_group_snapshot(
    state: dict[str, Any],
    group: dict[str, Any],
    *,
    session_id: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    validated = _validate_group_value(
        group,
        expected_group_id=str(group.get("group_id") or ""),
    )
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        raise GroupValidationError("治理状态缺少 group 派生所需的 tasks 对象")
    issues: list[dict[str, Any]] = []
    incomplete = False
    members = []
    required_material_ready: list[bool] = []
    required_action_required: list[bool] = []
    for member in validated["members"]:
        task_id = member["task_id"]
        current = tasks.get(task_id)
        exists = isinstance(current, dict)
        decision = None
        if exists:
            decision, decision_issues, decision_incomplete = (
                _build_work_item_decision_snapshot(
                    state,
                    task_id,
                    session_id=session_id,
                )
            )
            issues.extend(decision_issues)
            incomplete = incomplete or decision_incomplete
        current_attempt = decision.get("current_attempt") if isinstance(decision, dict) else None
        disposition_complete = bool(
            isinstance(decision, dict) and decision.get("lifecycle") == "tombstoned"
        )
        notification = (
            decision.get("terminal_notification") if isinstance(decision, dict) else None
        )
        notification_state = notification.get("state") if isinstance(notification, dict) else None
        summary_material_ready = bool(disposition_complete or notification_state == "observed")
        individual_action_required = bool(
            not exists
            or not isinstance(decision, dict)
            or decision.get("action_required") is True
        )
        if not exists:
            issues.append(
                _diagnostic_issue(
                    "current_required_field_invalid",
                    "group 引用的 task 在当前 Session 中不存在",
                    session_id=session_id,
                    task_id=task_id,
                    group_id=validated["group_id"],
                    field="members.task_id",
                )
            )
            incomplete = True
            individual_action_required = True
        if member["required"]:
            required_material_ready.append(summary_material_ready)
            required_action_required.append(individual_action_required)
        members.append(
            {
                "task_id": task_id,
                "required": member["required"],
                "exists": exists,
                "current_attempt": current_attempt if isinstance(current_attempt, int) else None,
                "lifecycle": decision.get("lifecycle") if isinstance(decision, dict) else "indeterminate",
                "action_required": individual_action_required,
                "terminal_notification": notification,
            }
        )
    snapshot = {
        "group_id": validated["group_id"],
        "objective_summary": validated["objective_summary"],
        "members": members,
        "summary_ready": bool(required_material_ready)
        and all(required_material_ready),
        "group_action_required": bool(required_action_required)
        and any(required_action_required),
    }
    return snapshot, issues, incomplete


def read_group(
    session_id: str,
    group_id: str,
    *,
    state_store: StateStore | None = None,
) -> dict[str, Any]:
    if not isinstance(group_id, str) or not group_id.strip():
        raise GroupValidationError("group_id 必须是非空字符串")
    store = state_store or _default_state_store()
    state = store.read(session_id)
    groups = state.get("groups")
    if not isinstance(groups, dict) or not isinstance(groups.get(group_id), dict):
        raise GroupNotFoundError(f"group 不存在：{group_id}")
    snapshot, _issues, _incomplete = _derive_group_snapshot(
        state,
        groups[group_id],
        session_id=session_id,
    )
    return snapshot


def _session_next_action(record: dict[str, Any]) -> str:
    parent_action = _parent_action(record)
    if parent_action:
        return str(parent_action)
    if _spawn_observation(record) is None:
        return "派发调用仍在对账期；不要重复派发"
    return "等待原 Agent并按规则巡检"


def _session_summary_line(record: dict[str, Any]) -> str:
    task_id = _bounded(record.get("task_id"), "unknown")[:SESSION_SUMMARY_FIELD_LIMIT]
    attempt = record.get("attempt")
    mode = _bounded(record.get("resolved_mode"), "unknown")[:SESSION_SUMMARY_FIELD_LIMIT]
    status = _bounded(_execution_status(record), "unknown")[:SESSION_SUMMARY_FIELD_LIMIT]
    summary = record.get("contract_summary") if isinstance(record.get("contract_summary"), dict) else {}
    objective = _bounded(summary.get("objective") or record.get("task_name"), "未命名任务")[:SESSION_SUMMARY_FIELD_LIMIT]
    target = _bounded(
        record.get("dispatch_record", {}).get("dispatch_target"),
        "unmapped",
    )[:SESSION_SUMMARY_FIELD_LIMIT]
    next_action = _session_next_action(record)
    parent_action = _bounded(_parent_action(record), "null")[:SESSION_SUMMARY_FIELD_LIMIT]
    mechanical = "/".join(
        str(value)
        for value in (
            _execution_status(record),
            _identity_status(record),
            _platform_observation(record),
            record.get("observation_record", {}).get("source"),
            record.get("observation_record", {}).get("terminal_status"),
        )
        if value is not None
    ) or status
    return (
        f"- 任务 ID：{task_id}｜attempt：{attempt}｜治理等级：{mode}｜状态：{status}｜"
        f"机械状态：{mechanical[:SESSION_SUMMARY_FIELD_LIMIT]}｜parent_action：{parent_action}｜"
        f"目标：{objective}｜恢复对象：{target}｜下一步：{next_action}"
    )


def _session_start_context(
    action_required: list[dict[str, Any]],
    recent_activity: list[dict[str, Any]],
) -> str:
    header = "Subagent Governance 会话恢复摘要："
    footer = (
        "不要因 compact/resume 重复创建已有 Agent；使用精确恢复对象继续等待、对账或恢复。\n"
        "不要因上下文压缩重复创建这些子 Agent；按状态等待、恢复原 Agent或继续已有用户决策。"
    )

    required_keys = {
        (str(record.get("task_id")), int(record.get("attempt") or 0))
        for record in action_required
    }
    recent_only = [
        record
        for record in recent_activity
        if (str(record.get("task_id")), int(record.get("attempt") or 0)) not in required_keys
    ]

    def render(required_lines: list[str], recent_lines: list[str]) -> str:
        lines = [header]
        if action_required:
            lines.append("【需要处理】")
            lines.extend(required_lines)
            omitted_required = len(action_required) - len(required_lines)
            if omitted_required > 0:
                lines.append(f"还有 {omitted_required} 个待处理任务未展开。")
        if recent_only:
            lines.append("【最近活动】")
            lines.extend(recent_lines)
            omitted_recent = len(recent_only) - len(recent_lines)
            if omitted_recent > 0:
                lines.append(f"还有 {omitted_recent} 个最近活动未展开。")
        lines.append(footer)
        return "\n".join(lines)

    required_lines: list[str] = []
    recent_lines: list[str] = []
    for record in action_required:
        if len(required_lines) + len(recent_lines) >= SESSION_SUMMARY_RECORD_LIMIT:
            break
        candidate = [*required_lines, _session_summary_line(record)]
        if len(render(candidate, recent_lines)) > SESSION_SUMMARY_CONTEXT_LIMIT:
            break
        required_lines.append(candidate[-1])
    for record in recent_only:
        if len(required_lines) + len(recent_lines) >= SESSION_SUMMARY_RECORD_LIMIT:
            break
        candidate = [*recent_lines, _session_summary_line(record)]
        if len(render(required_lines, candidate)) > SESSION_SUMMARY_CONTEXT_LIMIT:
            break
        recent_lines.append(candidate[-1])
    context = render(required_lines, recent_lines)
    while len(context) > SESSION_SUMMARY_CONTEXT_LIMIT and recent_lines:
        recent_lines.pop()
        context = render(required_lines, recent_lines)
    while len(context) > SESSION_SUMMARY_CONTEXT_LIMIT and required_lines:
        required_lines.pop()
        context = render(required_lines, recent_lines)
    return context


def _session_work_item_summary_line(snapshot: dict[str, Any]) -> str:
    task_id = _bounded(snapshot.get("task_id"), "unknown")[:SESSION_SUMMARY_FIELD_LIMIT]
    current_attempt = snapshot.get("current_attempt")
    lifecycle = _bounded(snapshot.get("lifecycle"), "indeterminate")[:SESSION_SUMMARY_FIELD_LIMIT]
    objective = _bounded(snapshot.get("objective_summary"), "未记录")[:SESSION_SUMMARY_FIELD_LIMIT]
    candidates = snapshot.get("execution_candidates")
    candidates = candidates if isinstance(candidates, list) else []
    candidate_text = "、".join(
        f"{candidate.get('attempt')}({candidate.get('execution')}/{candidate.get('identity')}/"
        f"notification={bool((candidate.get('notification') or {}).get('observed'))})"
        for candidate in candidates
    )[:SESSION_SUMMARY_FIELD_LIMIT]
    actions = snapshot.get("allowed_actions")
    actions = actions if isinstance(actions, list) else []
    action_text = ",".join(action for action in actions if isinstance(action, str)) or "none"
    notification = snapshot.get("terminal_notification")
    notification_state = (
        notification.get("state") if isinstance(notification, dict) else "unknown"
    )
    return (
        f"- 工作项 ID：{task_id}｜current attempt：{current_attempt}｜lifecycle：{lifecycle}｜"
        f"notification：{notification_state}｜allowed_actions：{action_text[:SESSION_SUMMARY_FIELD_LIMIT]}｜"
        f"目标：{objective}｜候选 executions：{candidate_text or 'none'}"
    )


def _session_start_work_item_context(work_items: list[dict[str, Any]]) -> str:
    header = "Subagent Governance 会话恢复摘要（work-item 决策视图）："
    footer = (
        "不要因 compact/resume 重复创建已有 Agent；使用精确 execution/target 继续等待、对账或处置。\n"
        "诊断摘要只展示持久化事实与允许入口，不代表业务授权、验收或自动调度。"
    )
    required = [item for item in work_items if item.get("action_required") is True]
    recent_only = [
        item
        for item in work_items
        if item.get("action_required") is not True and item.get("recent_activity") is True
    ]

    def render(
        required_lines: list[str],
        recent_lines: list[str],
    ) -> str:
        lines = [header]
        if required:
            lines.append("【需要处理】")
            lines.extend(required_lines)
            if len(required) > len(required_lines):
                lines.append(f"还有 {len(required) - len(required_lines)} 个待处理 work item 未展开。")
        if recent_only:
            lines.append("【最近活动】")
            lines.extend(recent_lines)
            if len(recent_only) > len(recent_lines):
                lines.append(f"还有 {len(recent_only) - len(recent_lines)} 个最近 work item 未展开。")
        lines.append(footer)
        return "\n".join(lines)

    required_lines: list[str] = []
    recent_lines: list[str] = []
    for snapshot in required:
        if len(required_lines) + len(recent_lines) >= SESSION_SUMMARY_RECORD_LIMIT:
            break
        line = _session_work_item_summary_line(snapshot)
        if len(render([*required_lines, line], recent_lines)) > SESSION_SUMMARY_CONTEXT_LIMIT:
            break
        required_lines.append(line)
    for snapshot in recent_only:
        if len(required_lines) + len(recent_lines) >= SESSION_SUMMARY_RECORD_LIMIT:
            break
        line = _session_work_item_summary_line(snapshot)
        if len(render(required_lines, [*recent_lines, line])) > SESSION_SUMMARY_CONTEXT_LIMIT:
            break
        recent_lines.append(line)
    return render(required_lines, recent_lines)


def _handle_stop(
    payload: dict[str, Any],
    store: StateStore,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    state = None
    errors: list[str] = []
    for read_attempt in range(STOP_READ_ATTEMPTS):
        try:
            state = store.read(session_id)
            break
        except (OSError, RuntimeError) as exc:
            errors.append(_bounded(exc, "unknown read error"))
            if read_attempt < STOP_READ_ATTEMPTS - 1:
                sleeper(STOP_READ_RETRY_DELAY_SECONDS)
    if state is None:
        return {
            "continue": True,
            "systemMessage": (
                "Subagent Governance 连续三次无法读取 StateStore；当前没有可靠正向证据可用于"
                "阻止 parent Stop，已降级放行。"
                f"最后错误：{errors[-1] if errors else 'unknown'}"
            ),
        }
    advisory = _action_required_records(state)
    warning = getattr(store, "last_warning", None)
    if not advisory:
        result = {"continue": True}
        if warning:
            result["systemMessage"] = str(warning)
        return result
    summary = "、".join(
        f"{record.get('task_id')}#{record.get('attempt')}"
        f"({_execution_status(record)})"
        for record in advisory[:6]
    )
    omitted = len(advisory) - 6
    if omitted > 0:
        summary += f"，另有 {omitted} 个"
    message = (
        "仍有 action-required 治理子任务："
        f"{summary}。当前没有可靠 active freshness 或 parent Stop hard-gate 证据；"
        "以上仅作 advisory，未阻止 parent Stop。"
    )
    if warning:
        message += f" StateStore 同时报告：{warning}"
    return {"continue": True, "systemMessage": message}


def _handle_session_start(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    try:
        if callable(getattr(store, "update", None)):
            reconcile_prepared_dispatches(
                session_id,
                state_store=store,
                prepared_store=PreparedContractStore(_prepared_root_for_store(store)),
            )
            reconcile_pending_actions(session_id, state_store=store)
        if callable(getattr(store, "cleanup_expired_tombstones", None)):
            store.cleanup_expired_tombstones(session_id)
        state = store.read(session_id)
        action_required = _action_required_records(state)
        recent_activity = _recent_activity_records(state)
        work_items = []
        tasks = state.get("tasks")
        if isinstance(tasks, dict):
            for task_id in sorted(str(key) for key in tasks):
                snapshot, _issues, _incomplete = (
                    _build_work_item_decision_snapshot(
                        state,
                        task_id,
                        session_id=session_id,
                    )
                )
                if isinstance(snapshot, dict):
                    work_items.append(snapshot)
    except Exception as exc:
        return {
            "continue": True,
            "systemMessage": (
                "Subagent Governance SessionStart degraded：状态恢复链不可用，无法确认是否存在待处理任务；"
                f"请先诊断或恢复 StateStore。错误：{_bounded(exc)}"
            ),
        }
    warning = getattr(store, "last_warning", None)
    if not work_items and not action_required and not recent_activity:
        result = {"continue": True}
        if warning:
            result["systemMessage"] = str(warning)
        return result
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                _session_start_work_item_context(work_items)
                if work_items
                else _session_start_context(action_required, recent_activity)
            ),
        }
    }


def _handle_session_end(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    preserved: list[dict[str, Any]] = []
    retained_tombstones = 0

    def can_delete(state: dict[str, Any]) -> bool:
        nonlocal preserved, retained_tombstones
        preserved = _action_required_records(state)
        tombstones = state.get("tombstones")
        retained_tombstones = len(tombstones) if isinstance(tombstones, dict) else 0
        return not preserved and retained_tombstones == 0

    try:
        if callable(getattr(store, "update", None)):
            reconcile_prepared_dispatches(
                session_id,
                state_store=store,
                prepared_store=PreparedContractStore(_prepared_root_for_store(store)),
            )
            reconcile_pending_actions(session_id, state_store=store)
        if callable(getattr(store, "cleanup_expired_tombstones", None)):
            store.cleanup_expired_tombstones(session_id)
        deleted = store.delete_if(session_id, can_delete)
    except Exception as exc:
        return {"continue": True, "systemMessage": f"Subagent Governance 会话状态清理失败：{exc}"}
    warning = getattr(store, "last_warning", None)
    if not deleted:
        summary = "、".join(
            f"{_bounded(record.get('task_id'), 'unknown')[:SESSION_SUMMARY_FIELD_LIMIT]}"
            f"({_bounded(_execution_status(record), 'unknown')[:SESSION_SUMMARY_FIELD_LIMIT]})"
            for record in preserved[:6]
        )
        omitted = len(preserved) - 6
        if omitted > 0:
            summary += f"，另有 {omitted} 个"
        if retained_tombstones:
            tombstone_summary = f"仍有 {retained_tombstones} 个 tombstone 处于7天保留期"
            summary = f"{summary}；{tombstone_summary}" if summary else tombstone_summary
        message = (
            f"Subagent Governance 检测到仍需恢复或决策的治理任务，已保留治理状态：{summary}。"
            "SessionEnd 不会终止子 Agent；恢复同一会话后按 SessionStart 摘要继续处理。"
        )
        if warning:
            message += f" {warning}"
        return {"continue": True, "systemMessage": message}
    if warning:
        return {"continue": True, "systemMessage": str(warning)}
    return {"continue": True}


def handle(payload: dict[str, Any], store: StateStore | None = None) -> dict[str, Any] | None:
    if store is not None:
        active_store = store
    else:
        try:
            active_store = _default_state_store()
        except (OSError, RuntimeError) as exc:
            active_store = UnavailableStateStore(exc)
    event = str(payload.get("hook_event_name") or "")
    if event == "PreToolUse":
        kind = _tool_kind(str(payload.get("tool_name") or ""))
        if kind == "spawn":
            return _handle_spawn(payload, active_store)
        if kind in {"communication", "followup"}:
            return _handle_communication(payload, active_store)
        if kind == "interrupt":
            return _handle_interrupt_pre(payload, active_store)
        return None
    if event == "PostToolUse":
        return _handle_post_tool(payload, active_store)
    if event == "Stop":
        return _handle_stop(payload, active_store)
    if event == "SessionStart":
        return _handle_session_start(payload, active_store)
    if event == "SessionEnd":
        return _handle_session_end(payload, active_store)
    return None


def _diagnostic_absolute_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _diagnostic_base_document(
    root: Path,
    session_id: str | None,
) -> dict[str, Any]:
    return {
        "data_root": str(_diagnostic_absolute_path(root)),
        "data_root_exists": bool(root.exists() or root.is_symlink()),
        "scope": "single_session" if session_id is not None else "all_sessions",
        "requested_session": session_id,
        "scan": {
            "requested": 0,
            "checked": 0,
            "succeeded": 0,
            "failed": 0,
            "omitted": 0,
            "complete": True,
        },
        "sessions": [],
        "issues": [],
        "boundaries": {
            "transport_opaque": True,
            "provider_status": "not_checked",
            "hook_trust": "not_checked",
            "repairs_state": False,
            "writes_files": False,
        },
    }


def _read_session_file_read_only(
    path: Path,
    *,
    requested_session: str | None = None,
) -> dict[str, Any]:
    diagnostic_codes = {
        "symlink": "session_symlink",
        "not_regular": "session_not_regular",
        "owner_mismatch": "session_owner_mismatch",
        "permissions_unsafe": "session_permissions_unsafe",
        "oversized": "session_oversized",
        "unreadable": "session_unreadable",
    }
    diagnostic_messages = {
        "symlink": "Session 状态文件是符号链接",
        "not_regular": "Session 状态目标不是普通文件",
        "owner_mismatch": "Session 状态文件所有者不安全",
        "permissions_unsafe": "Session 状态文件权限向 group/other 开放",
        "oversized": f"Session 状态文件超过 {MAX_STATE_BYTES} 字节上限",
        "unreadable": "Session 状态文件无法安全读取",
    }

    def diagnostic_storage_error(code: str, _message: str) -> Exception:
        normalized_code = code if code in diagnostic_codes else "unreadable"
        return DiagnosticReadError(
            diagnostic_codes[normalized_code],
            diagnostic_messages[normalized_code],
            context={"path": str(path)},
        )

    try:
        raw = read_private_bytes(
            path,
            label="Session 状态文件",
            max_bytes=MAX_STATE_BYTES,
            owned_by_current_user=_owned_by_current_user,
            private_permissions_safe=_private_permissions_safe,
            error_factory=diagnostic_storage_error,
        )
    except FileNotFoundError as exc:
        raise DiagnosticReadError(
            "session_missing",
            "请求的 Session 状态文件不存在",
            context={"path": str(path)},
        ) from exc
    except DiagnosticReadError:
        raise
    except PrivateStorageCapacityError as exc:
        raise DiagnosticReadError(
            "session_oversized",
            f"Session 状态文件超过 {MAX_STATE_BYTES} 字节上限",
            context={"path": str(path)},
        ) from exc
    except PrivateStorageError as exc:
        raise DiagnosticReadError(
            "session_unreadable",
            "Session 状态文件无法安全读取",
            context={"path": str(path)},
        ) from exc
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiagnosticReadError(
            "session_non_utf8",
            "Session 状态文件不是有效 UTF-8",
            context={"path": str(path)},
        ) from exc
    try:
        value = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise DiagnosticReadError(
            "session_json_invalid",
            "Session 状态文件不是有效 JSON",
            context={"path": str(path)},
        ) from exc
    if not isinstance(value, dict):
        raise DiagnosticReadError(
            "session_root_invalid",
            "Session 状态文件根节点不是对象",
            context={"path": str(path)},
        )
    stored_session = value.get("session_id")
    if not isinstance(stored_session, str) or not stored_session.strip():
        raise DiagnosticReadError(
            "session_root_invalid",
            "Session 状态缺少有效 session_id",
            context={"path": str(path), "field": "session_id"},
        )
    if requested_session is not None and stored_session != requested_session:
        raise DiagnosticReadError(
            "session_root_invalid",
            "Session 状态中的 session_id 与请求不匹配",
            context={"path": str(path), "session_id": stored_session},
        )
    try:
        return _require_current_state_format(value)
    except StateValidationError as exc:
        raise DiagnosticReadError(
            "session_format_unknown",
            str(exc),
            context={"path": str(path), "session_id": stored_session},
        ) from exc


def _diagnostic_validate_attempt(
    record: dict[str, Any],
    *,
    session_id: str,
    task_id: str,
    attempt: int,
) -> tuple[list[dict[str, Any]], bool, bool]:
    issues: list[dict[str, Any]] = []
    incomplete = False
    identity_valid = True
    try:
        _validate_task_identity(task_id, attempt)
    except NotificationObservationError:
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "managed attempt 的 task_id/attempt 非法",
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                field="task_id/attempt",
            )
        )
        incomplete = True
        identity_valid = False
    try:
        _validate_current_execution_planes(record)
    except StateValidationError as exc:
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                str(exc),
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                field="canonical_execution_planes",
            )
        )
        incomplete = True
    for field_name in ("spawn_retry_count", "recovery_count"):
        value = record.get(field_name)
        if field_name not in record:
            code = "current_required_field_missing"
        elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
            code = "current_required_field_invalid"
        else:
            continue
        issues.append(
            _diagnostic_issue(
                code,
                f"managed attempt 的 {field_name} 缺失或非法",
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                field=field_name,
            )
        )
        incomplete = True
    return issues, incomplete, identity_valid


def _diagnostic_skipped_attempt_issues(
    tasks: dict[str, Any],
    *,
    session_id: str,
) -> tuple[list[dict[str, Any]], bool]:
    issues: list[dict[str, Any]] = []
    for task_key, task in sorted(tasks.items(), key=lambda item: str(item[0])):
        task_id = str(task_key)
        task_key_errors = _validate_text(
            task_key,
            "task_id",
            maximum=int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"]),
        )
        if task_key_errors:
            issues.append(
                _diagnostic_issue(
                    "current_required_field_invalid",
                    "tasks 键不是合法 task_id",
                    session_id=session_id,
                    task_id=task_id,
                    field="tasks.<task_id>",
                )
            )
        if not isinstance(task, dict):
            issues.append(
                _diagnostic_issue(
                    "current_required_field_invalid",
                    "Session task 记录必须是对象",
                    session_id=session_id,
                    task_id=task_id,
                    field="tasks",
                )
            )
            continue
        if task.get("managed") is not True:
            issues.append(
                _diagnostic_issue(
                    (
                        "current_required_field_missing"
                        if "managed" not in task
                        else "current_required_field_invalid"
                    ),
                    "task 记录不是当前 managed attempt 结构；该记录不会进入执行状态机",
                    session_id=session_id,
                    task_id=task_id,
                    field="managed",
                )
            )
            continue
        for field_name in ("work_item", "executions"):
            if not isinstance(task.get(field_name), dict):
                issues.append(
                    _diagnostic_issue(
                        (
                            "current_required_field_missing"
                            if field_name not in task
                            else "current_required_field_invalid"
                        ),
                        f"managed task 缺少 canonical {field_name} 对象；该记录不会进入执行状态机",
                        session_id=session_id,
                        task_id=task_id,
                        field=field_name,
                    )
                )
    return issues, bool(issues)


def _diagnostic_normalize_session_shape(
    state: dict[str, Any],
    *,
    path: Path,
    session_id: str,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    incomplete = False
    for field_name in ("tasks", "agents", "health", "tombstones"):
        if field_name not in state:
            issues.append(
                _diagnostic_issue(
                    "current_required_field_missing",
                    f"Session snapshot 缺少 {field_name}",
                    session_id=session_id,
                    path=str(path),
                    field=field_name,
                )
            )
            incomplete = True
    tasks = state.get("tasks")
    agents = state.get("agents")
    health = state.get("health")
    tombstones = state.get("tombstones")
    if not isinstance(tasks, dict):
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "Session tasks 必须是对象",
                session_id=session_id,
                field="tasks",
            )
        )
        tasks = {}
        incomplete = True
    if not isinstance(agents, dict):
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "Session agents 必须是对象",
                session_id=session_id,
                field="agents",
            )
        )
        incomplete = True
    health_status = "unknown"
    if isinstance(health, dict) and health.get("status") in {"ok", "degraded", "unavailable"}:
        health_status = str(health["status"])
    else:
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "Session health.status 缺失或非法",
                session_id=session_id,
                field="health.status",
            )
        )
        incomplete = True
    if not isinstance(tombstones, dict):
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "Session tombstones 必须是对象",
                session_id=session_id,
                field="tombstones",
            )
        )
        tombstones = {}
        incomplete = True
    normalized_state = dict(state)
    normalized_state["tasks"] = tasks
    normalized_state["agents"] = agents if isinstance(agents, dict) else {}
    normalized_state["tombstones"] = tombstones
    skipped_attempt_issues, skipped_attempt_incomplete = (
        _diagnostic_skipped_attempt_issues(tasks, session_id=session_id)
    )
    issues.extend(skipped_attempt_issues)
    incomplete = incomplete or skipped_attempt_incomplete
    return {
        "state": normalized_state,
        "tasks": tasks,
        "tombstones": tombstones,
        "health_status": health_status,
        "issues": issues,
        "incomplete": incomplete,
    }


def _diagnostic_collect_attempts(
    normalized_state: dict[str, Any],
    *,
    session_id: str,
    now: int,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    incomplete = False
    omitted = 0
    all_attempts = _view_attempt_records(normalized_state)
    all_attempts.sort(
        key=lambda record: (
            str(record.get("task_id") or ""),
            int(record.get("attempt") or 0),
        )
    )
    attempts_by_task: dict[str, list[dict[str, Any]]] = {}
    for record in all_attempts:
        attempts_by_task.setdefault(str(record.get("task_id") or ""), []).append(record)
    allowed_attempts: list[dict[str, Any]] = []
    allowed_task_ids: list[str] = []
    for task_id in sorted(attempts_by_task):
        task_attempts = attempts_by_task[task_id]
        if len(allowed_attempts) + len(task_attempts) > DIAGNOSTIC_ATTEMPT_LIMIT:
            omitted += len(task_attempts)
            continue
        allowed_task_ids.append(task_id)
        allowed_attempts.extend(task_attempts)
    action_all = _action_required_records(normalized_state)
    recent_all = _recent_activity_records(normalized_state, now=now)
    for record in allowed_attempts:
        task_id = str(record.get("task_id") or "")
        attempt = int(record.get("attempt") or 0)
        attempt_issues, attempt_incomplete, _identity_valid = _diagnostic_validate_attempt(
            record,
            session_id=session_id,
            task_id=task_id,
            attempt=attempt,
        )
        issues.extend(attempt_issues)
        incomplete = incomplete or attempt_incomplete
        if (
            not _attempt_closed(normalized_state, record)
            and _identity_status(record) == "unconfirmed"
        ):
            issues.append(
                _diagnostic_issue(
                    "identity_unconfirmed",
                    "managed attempt 的 Agent 身份尚未确认",
                    session_id=session_id,
                    task_id=task_id,
                    attempt=attempt,
                )
            )
        if _platform_observation(record) == "error":
            issues.append(
                _diagnostic_issue(
                    "platform_error",
                    "持久化 platform_observation=error",
                    session_id=session_id,
                    task_id=task_id,
                    attempt=attempt,
                )
            )
    return {
        "all_attempts": all_attempts,
        "attempts_by_task": attempts_by_task,
        "allowed_task_ids": allowed_task_ids,
        "issues": issues,
        "incomplete": incomplete,
        "omitted": omitted,
        "action_required": len(action_all),
        "recent_activity": len(recent_all),
    }


def _diagnostic_collect_work_items(
    normalized_state: dict[str, Any],
    allowed_task_ids: list[str],
    *,
    session_id: str,
    now: int,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    incomplete = False
    work_item_snapshots: list[dict[str, Any]] = []
    for task_id in allowed_task_ids:
        work_item_snapshot, work_item_issues, work_item_incomplete = (
            _build_work_item_decision_snapshot(
                normalized_state,
                task_id,
                session_id=session_id,
                now=now,
            )
        )
        issues.extend(work_item_issues)
        incomplete = incomplete or work_item_incomplete
        if isinstance(work_item_snapshot, dict):
            work_item_snapshots.append(work_item_snapshot)
    work_item_snapshots.sort(key=lambda item: str(item.get("task_id") or ""))

    return {
        "snapshots": work_item_snapshots,
        "issues": issues,
        "incomplete": incomplete,
    }


def _diagnostic_collect_groups(
    state: dict[str, Any],
    normalized_state: dict[str, Any],
    *,
    session_id: str,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    incomplete = False
    omitted = 0
    groups_value = state.get("groups")
    group_snapshots: list[dict[str, Any]] = []
    if groups_value is None:
        groups_items: list[tuple[str, Any]] = []
    elif not isinstance(groups_value, dict):
        groups_items = []
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "Session groups 必须是对象",
                session_id=session_id,
                field="groups",
            )
        )
        incomplete = True
    else:
        groups_items = sorted(groups_value.items(), key=lambda item: str(item[0]))
    omitted += max(0, len(groups_items) - DIAGNOSTIC_GROUP_LIMIT)
    for group_key, group_value in groups_items[:DIAGNOSTIC_GROUP_LIMIT]:
        try:
            validated_group = _validate_group_value(
                group_value,
                expected_group_id=str(group_key),
            )
            snapshot, group_issues, group_incomplete = _derive_group_snapshot(
                normalized_state,
                validated_group,
                session_id=session_id,
            )
        except GroupValidationError as exc:
            issues.append(
                _diagnostic_issue(
                    "current_required_field_invalid",
                    f"group 记录非法：{exc}",
                    session_id=session_id,
                    group_id=str(group_key),
                    field="groups",
                )
            )
            incomplete = True
            continue
        group_snapshots.append(snapshot)
        issues.extend(group_issues)
        incomplete = incomplete or group_incomplete
    group_snapshots.sort(key=lambda group: str(group.get("group_id") or ""))

    return {
        "snapshots": group_snapshots,
        "count": len(groups_items),
        "issues": issues,
        "incomplete": incomplete,
        "omitted": omitted,
    }


def _diagnostic_finalize_session_issues(
    issues: list[dict[str, Any]],
    incomplete: bool,
    omitted: int,
    *,
    session_id: str,
) -> tuple[list[dict[str, Any]], bool, int]:
    if omitted:
        incomplete = True
        issues.append(
            _diagnostic_issue(
                "scan_incomplete",
                "Session snapshot 因诊断数量上限存在未展开记录",
                session_id=session_id,
                fact=f"omitted={omitted}",
            )
        )
    issues.sort(key=_diagnostic_issue_sort_key)
    if len(issues) > DIAGNOSTIC_ISSUE_LIMIT:
        omitted_issues = len(issues) - DIAGNOSTIC_ISSUE_LIMIT
        omitted += omitted_issues
        incomplete = True
        issues = issues[: DIAGNOSTIC_ISSUE_LIMIT - 1]
        issues.append(
            _diagnostic_issue(
                "scan_incomplete",
                "Session issues 因诊断数量上限存在未展开记录",
                session_id=session_id,
                fact=f"omitted_issues={omitted_issues}",
            )
        )
        issues.sort(key=_diagnostic_issue_sort_key)
    return issues, incomplete, omitted


def _diagnostic_session_snapshot(
    state: dict[str, Any],
    *,
    path: Path,
    now: int,
) -> tuple[dict[str, Any], bool, int]:
    session_id = str(state.get("session_id") or "")
    normalized = _diagnostic_normalize_session_shape(
        state,
        path=path,
        session_id=session_id,
    )
    normalized_state = normalized["state"]
    tasks = normalized["tasks"]
    tombstones = normalized["tombstones"]
    issues = list(normalized["issues"])
    incomplete = bool(normalized["incomplete"])
    attempts = _diagnostic_collect_attempts(
        normalized_state,
        session_id=session_id,
        now=now,
    )
    issues.extend(attempts["issues"])
    incomplete = incomplete or bool(attempts["incomplete"])
    work_items = _diagnostic_collect_work_items(
        normalized_state,
        attempts["allowed_task_ids"],
        session_id=session_id,
        now=now,
    )
    issues.extend(work_items["issues"])
    incomplete = incomplete or bool(work_items["incomplete"])
    groups = _diagnostic_collect_groups(
        state,
        normalized_state,
        session_id=session_id,
    )
    issues.extend(groups["issues"])
    incomplete = incomplete or bool(groups["incomplete"])
    omitted = int(attempts["omitted"]) + int(groups["omitted"])
    issues, incomplete, omitted = _diagnostic_finalize_session_issues(
        issues,
        incomplete,
        omitted,
        session_id=session_id,
    )
    return (
        {
            "session_id": session_id,
            "component_health": {
                "status": normalized["health_status"],
                "source": "persisted_health",
            },
            "counts": {
                "tasks": len(tasks),
                "work_items": len(attempts["attempts_by_task"]),
                "attempts": len(attempts["all_attempts"]),
                "action_required": attempts["action_required"],
                "recent_activity": attempts["recent_activity"],
                "groups": groups["count"],
                "tombstones": len(tombstones),
            },
            "work_items": work_items["snapshots"],
            "groups": groups["snapshots"],
            "issues": issues,
        },
        incomplete,
        omitted,
    )

def _diagnostic_output_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _build_diagnostic_document(
    session_id: str | None,
    data_root: Path | None = None,
) -> tuple[dict[str, Any], int]:
    root_input = data_root if data_root is not None else _data_root_path()
    root = Path(os.path.abspath(os.fspath(root_input.expanduser())))
    document = _diagnostic_base_document(root, session_id)
    scan = document["scan"]
    incomplete = False
    try:
        root_metadata = root.lstat()
    except FileNotFoundError:
        if session_id is not None:
            scan.update({"requested": 1, "checked": 1, "failed": 1, "complete": False})
            document["issues"].append(
                _diagnostic_issue(
                    "session_missing",
                    "请求的 Session 数据根不存在",
                    session_id=session_id,
                    path=str(root / "sessions" / f"{_safe_name(session_id)}.json"),
                )
            )
            return document, 1
        return document, 0
    document["data_root_exists"] = True
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        scan["complete"] = False
        document["issues"].append(
            _diagnostic_issue(
                "scan_incomplete",
                "数据根不是可扫描的普通目录",
                path=str(root),
                fact="data_root_symlink_or_not_directory",
            )
        )
        return document, 1
    sessions_root = root / "sessions"
    try:
        sessions_metadata = sessions_root.lstat()
    except FileNotFoundError:
        if session_id is not None:
            scan.update({"requested": 1, "checked": 1, "failed": 1, "complete": False})
            document["issues"].append(
                _diagnostic_issue(
                    "session_missing",
                    "请求的 Session 状态文件不存在",
                    session_id=session_id,
                    path=str(sessions_root / f"{_safe_name(session_id)}.json"),
                )
            )
            return document, 1
        return document, 0
    if stat.S_ISLNK(sessions_metadata.st_mode) or not stat.S_ISDIR(sessions_metadata.st_mode):
        scan["complete"] = False
        document["issues"].append(
            _diagnostic_issue(
                "scan_incomplete",
                "sessions 目标不是可扫描的普通目录",
                path=str(sessions_root),
                fact="sessions_root_symlink_or_not_directory",
            )
        )
        return document, 1
    if session_id is not None:
        paths = [sessions_root / f"{_safe_name(session_id)}.json"]
    else:
        try:
            with os.scandir(sessions_root) as entries:
                paths = sorted(
                    [Path(entry.path) for entry in entries if entry.name.endswith(".json")],
                    key=lambda path: path.name,
                )
        except OSError as exc:
            scan["complete"] = False
            document["issues"].append(
                _diagnostic_issue(
                    "scan_incomplete",
                    f"sessions 目录无法列举：{exc}",
                    path=str(sessions_root),
                    fact="sessions_root_unreadable",
                )
            )
            return document, 1
    scan["requested"] = len(paths)
    if len(paths) > DIAGNOSTIC_SESSION_LIMIT:
        scan["omitted"] += len(paths) - DIAGNOSTIC_SESSION_LIMIT
        paths = paths[:DIAGNOSTIC_SESSION_LIMIT]
        incomplete = True
        document["issues"].append(
            _diagnostic_issue(
                "scan_incomplete",
                "全局 Session 数量超过诊断上限",
                path=str(sessions_root),
                fact=f"limit={DIAGNOSTIC_SESSION_LIMIT}",
            )
        )
    now = _now()
    snapshots = []
    for path in paths:
        scan["checked"] += 1
        try:
            state = _read_session_file_read_only(
                path,
                requested_session=session_id,
            )
        except DiagnosticReadError as exc:
            scan["failed"] += 1
            incomplete = True
            context = dict(exc.context)
            if session_id is not None:
                context["session_id"] = session_id
            document["issues"].append(
                _diagnostic_issue(exc.code, str(exc), **context)
            )
            continue
        snapshot, session_incomplete, session_omitted = _diagnostic_session_snapshot(
            state,
            path=path,
            now=now,
        )
        snapshots.append((snapshot, path.name))
        scan["succeeded"] += 1
        scan["omitted"] += session_omitted
        incomplete = incomplete or session_incomplete
    document["sessions"] = [
        snapshot
        for snapshot, _path_name in sorted(
            snapshots,
            key=lambda item: (str(item[0].get("session_id") or ""), item[1]),
        )
    ]
    document["issues"].sort(key=_diagnostic_issue_sort_key)
    if len(document["issues"]) > DIAGNOSTIC_ISSUE_LIMIT:
        omitted_issues = len(document["issues"]) - DIAGNOSTIC_ISSUE_LIMIT
        scan["omitted"] += omitted_issues
        incomplete = True
        document["issues"] = document["issues"][: DIAGNOSTIC_ISSUE_LIMIT - 1]
        document["issues"].append(
            _diagnostic_issue(
                "scan_incomplete",
                "顶层 issues 因诊断数量上限存在未展开记录",
                fact=f"omitted_issues={omitted_issues}",
            )
        )
        document["issues"].sort(key=_diagnostic_issue_sort_key)
    scan["complete"] = not incomplete and scan["failed"] == 0 and scan["omitted"] == 0
    if incomplete and not any(issue.get("code") == "scan_incomplete" for issue in document["issues"]):
        document["issues"].append(
            _diagnostic_issue(
                "scan_incomplete",
                "本次诊断未能完整扫描全部请求事实",
            )
        )
        document["issues"].sort(key=_diagnostic_issue_sort_key)
    while len(_diagnostic_output_bytes(document)) > DIAGNOSTIC_OUTPUT_BYTES and document["sessions"]:
        document["sessions"].pop()
        scan["succeeded"] = max(0, int(scan["succeeded"]) - 1)
        scan["omitted"] += 1
        scan["complete"] = False
        incomplete = True
    if len(_diagnostic_output_bytes(document)) > DIAGNOSTIC_OUTPUT_BYTES:
        document["issues"] = [
            _diagnostic_issue(
                "scan_incomplete",
                "诊断输出超过体积上限，详细问题未展开",
                fact=f"output_limit={DIAGNOSTIC_OUTPUT_BYTES}",
            )
        ]
        scan["omitted"] += 1
        scan["complete"] = False
        incomplete = True
    return document, 0 if scan["complete"] else 1


def _diagnose(session_id: str | None, data_root: Path | None = None) -> int:
    document, exit_code = _build_diagnostic_document(session_id, data_root)
    sys.stdout.buffer.write(_diagnostic_output_bytes(document))
    return exit_code


# P4 public facade.  Protocol implementations are owned by their dedicated
# modules; these explicit imports preserve direct-script and package consumers.
try:
    from scripts.governance_validation import _required_fields, _validate_text, _validate_text_list
    from scripts.governance_context import (
        _run_git, _sha256_file, _validate_context_manifest,
        _validate_context_verification_record, verify_context_manifest,
    )
    from scripts.governance_contracts import (
        TaskContract, TaskFeatures, _contract_from_input, _contract_summary,
        _validate_task_features, contract_digest, resolve_governance_mode,
        validate_task_contract,
    )
    from scripts.governance_dispatch_identity import (
        build_task_name, derive_task_ref, normalize_semantic_name,
        parse_task_name, select_task_ref,
    )
    from scripts.governance_dispatch_rendering import (
        _context_projection, _render_list, _render_verified_context, _spawn_args,
        render_dispatch_prompt, render_dispatch_user_message,
    )
    from scripts.governance_prepared_store import (
        PreparedContractStore, _prepared_record, _prepared_root_for_store,
    )
except ModuleNotFoundError:
    from governance_validation import _required_fields, _validate_text, _validate_text_list
    from governance_context import _run_git, _sha256_file, _validate_context_manifest, _validate_context_verification_record, verify_context_manifest
    from governance_contracts import TaskContract, TaskFeatures, _contract_from_input, _contract_summary, _validate_task_features, contract_digest, resolve_governance_mode, validate_task_contract
    from governance_dispatch_identity import build_task_name, derive_task_ref, normalize_semantic_name, parse_task_name, select_task_ref
    from governance_dispatch_rendering import _context_projection, _render_list, _render_verified_context, _spawn_args, render_dispatch_prompt, render_dispatch_user_message
    from governance_prepared_store import PreparedContractStore, _prepared_record, _prepared_root_for_store


def main() -> int:
    try:
        from scripts.governance_cli import main as cli_main
    except ModuleNotFoundError:
        from governance_cli import main as cli_main
    return cli_main(sys.modules[__name__])


if __name__ == "__main__":
    raise SystemExit(main())
