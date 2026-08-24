#!/usr/bin/env python3
"""Adaptive Codex subagent lifecycle governance hook."""

from __future__ import annotations

import argparse
import copy
import getpass
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


if os.name == "nt":
    import msvcrt

    fcntl = None
else:
    import fcntl

    msvcrt = None


# The facade keeps the historical module-level names stable for hooks and
# tests while the low-coupling definitions live in dedicated modules.
try:
    from scripts.governance_semantics import *
    from scripts.governance_semantics import (
        _DECISION_ACTION_ORDER,
        _load_machine_semantics,
        _semantic_enum,
        _semantic_values,
    )
except ModuleNotFoundError:
    from governance_semantics import *
    from governance_semantics import (
        _DECISION_ACTION_ORDER,
        _load_machine_semantics,
        _semantic_enum,
        _semantic_values,
    )

try:
    from scripts.governance_errors import *
    from scripts.governance_errors import _state_store_exception_category
except ModuleNotFoundError:
    from governance_errors import *
    from governance_errors import _state_store_exception_category

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


@dataclass(frozen=True)
class TaskFeatures:
    risk: str
    read_only: bool
    writes_files: bool
    destructive: bool
    production: bool
    concurrent_write: bool

    def to_record(self) -> dict[str, Any]:
        return {
            "risk": self.risk,
            "read_only": self.read_only,
            "writes_files": self.writes_files,
            "destructive": self.destructive,
            "production": self.production,
            "concurrent_write": self.concurrent_write,
        }


@dataclass(frozen=True)
class TaskContract:
    semantic_name: str
    requested_mode: str
    resolved_mode: str
    resolution_reason: str
    task_features: dict[str, Any] | None
    objective: str
    background: str
    work_scope: list[str]
    forbidden_scope: list[str]
    completion_conditions: list[str]
    evidence_requirements: list[str]
    relevant_files: list[str]
    context_manifest: dict[str, Any]
    current_state: str | None
    model: str | None
    reasoning_effort: str | None
    context_strategy: str
    context_turns: int | None
    context_reason: str | None

    def to_record(self) -> dict[str, Any]:
        return {
            "semantic_name": self.semantic_name,
            "requested_mode": self.requested_mode,
            "resolved_mode": self.resolved_mode,
            "resolution_reason": self.resolution_reason,
            "task_features": self.task_features,
            "objective": self.objective,
            "background": self.background,
            "work_scope": list(self.work_scope),
            "forbidden_scope": list(self.forbidden_scope),
            "completion_conditions": list(self.completion_conditions),
            "evidence_requirements": list(self.evidence_requirements),
            "relevant_files": list(self.relevant_files),
            "context_manifest": copy.deepcopy(self.context_manifest),
            "current_state": self.current_state,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "context_strategy": self.context_strategy,
            "context_turns": self.context_turns,
            "context_reason": self.context_reason,
        }


def _initial_plane_records() -> dict[str, dict[str, Any]]:
    return {
        "dispatch_record": {
            "dispatch_state": "prepared",
            "tool_use_id": None,
            "dispatch_target": None,
        },
        "observation_record": {
            "source": None,
            "observed_state": "not_observed",
            "observed_at": None,
            "terminal_status": None,
        },
        "closure_record": {
            "reason": None,
            "closed_at": None,
            "parent_action": None,
        },
    }


def _legacy_dispatch_state(execution: dict[str, Any]) -> str:
    observation = execution.get("spawn_observation")
    if observation == "success":
        return "acknowledged"
    if observation == "failed":
        return "rejected"
    if observation == "unknown":
        return "indeterminate"
    if execution.get("spawn_tool_use_id") is not None:
        return "claimed"
    return "prepared"


def _legacy_observation_record(
    execution: dict[str, Any],
    dispatch: dict[str, Any],
) -> dict[str, Any]:
    observed_at = execution.get("platform_checked_at")
    if (
        isinstance(observed_at, bool)
        or not isinstance(observed_at, int)
        or observed_at < 0
    ):
        observed_at = None
    source = execution.get("platform_observation_source")
    summary = execution.get("platform_observation_summary")
    dispatch_target = dispatch.get("dispatch_target")
    legacy_target = execution.get("platform_observation_target")
    exact_target = bool(
        isinstance(dispatch_target, str)
        and dispatch_target
        and legacy_target == dispatch_target
    )
    terminal_status = None
    observed_state = "not_observed"
    normalized_source = None
    if (
        source == "list_agents"
        and exact_target
        and summary in {"completed", "stopped", "interrupted"}
    ):
        observed_state = "terminal"
        terminal_status = str(summary)
        normalized_source = "list_agents"
    elif execution.get("platform_observation") == "error" and exact_target:
        observed_state = "error"
        normalized_source = "list_agents" if source == "list_agents" else "session"
    elif execution.get("platform_observation") == "unknown" and exact_target:
        observed_state = "unknown"
        normalized_source = "list_agents" if source == "list_agents" else "session"
    if observed_state == "not_observed":
        observed_at = None
    return {
        "source": normalized_source,
        "observed_state": observed_state,
        "observed_at": observed_at,
        "terminal_status": terminal_status,
    }


def _legacy_closure_record(
    execution: dict[str, Any],
    task_id: str,
    attempt: int,
) -> dict[str, Any]:
    legacy_disposition = execution.get("parent_disposition_record")
    disposition = (
        legacy_disposition
        if isinstance(legacy_disposition, dict)
        and legacy_disposition.get("task_id") == task_id
        and legacy_disposition.get("attempt") == attempt
        else None
    )
    reason = execution.get("attempt_close_reason")
    if reason is None and isinstance(disposition, dict):
        reason = disposition.get("reason")
    closure = {
        "reason": reason if isinstance(reason, str) and reason.strip() else None,
        "closed_at": (
            execution.get("attempt_closed_at")
            if isinstance(execution.get("attempt_closed_at"), int)
            and not isinstance(execution.get("attempt_closed_at"), bool)
            else None
        ),
        "parent_action": _migrated_parent_action(execution.get("parent_action")),
    }
    _normalize_migrated_closure_facts(
        closure, claimed_closed=execution.get("attempt_closed") is True
    )
    return closure


def _migrated_parent_action(value: Any) -> str | None:
    if value in {"accept_result", "correct_result"}:
        return "decide_disposition"
    return str(value) if value in PARENT_ACTIONS else None


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


def _normalize_migrated_closure_facts(
    closure: dict[str, Any], *, claimed_closed: bool
) -> None:
    reason = closure.get("reason")
    closed_at = closure.get("closed_at")
    if _closure_has_complete_facts(closure):
        return
    if claimed_closed or reason is not None or closed_at is not None:
        closure["reason"] = None
        closure["closed_at"] = None
        closure["parent_action"] = "reconcile"


def _legacy_contract_text(
    value: Any, fallback: str, *, maximum: int
) -> str:
    if isinstance(value, str) and value.strip() and len(value) <= maximum:
        return value
    return fallback


def _migrate_contract_summary(
    execution: dict[str, Any], objective_summary: Any = None, *, task_id: str
) -> dict[str, Any]:
    raw = execution.get("contract_summary")
    summary = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    fallback_objective = _legacy_contract_text(
        objective_summary,
        f"Legacy managed task {task_id}",
        maximum=int(SEMANTIC_DEFINITIONS["short_text"]["maxLength"]),
    )
    objective = _legacy_contract_text(
        summary.get("objective"),
        fallback_objective,
        maximum=int(SEMANTIC_DEFINITIONS["short_text"]["maxLength"]),
    )
    model = summary.get("model")
    model = (
        model
        if model is None
        or (
            isinstance(model, str)
            and model.strip()
            and len(model) <= int(SEMANTIC_DEFINITIONS["model"]["maxLength"])
        )
        else None
    )
    return {
        "objective": objective,
        "model": model,
    }


def _migrate_legacy_execution_record(
    execution: dict[str, Any], *, task_id: str, attempt: int, objective_summary: Any = None
) -> dict[str, Any]:
    migrated = copy.deepcopy(execution)
    task_ref = migrated.get("task_ref")
    if not isinstance(task_ref, str) or not task_ref:
        raise StateValidationError("旧 managed execution 缺少可迁移的 task_ref")
    dispatch = {
        "dispatch_state": _legacy_dispatch_state(migrated),
        "tool_use_id": (
            migrated.get("spawn_tool_use_id")
            if isinstance(migrated.get("spawn_tool_use_id"), str)
            else None
        ),
        "dispatch_target": (
            migrated.get("spawn_observed_canonical_path")
            if isinstance(migrated.get("spawn_observed_canonical_path"), str)
            and migrated.get("spawn_observed_canonical_path")
            else None
        ),
    }
    observation = _legacy_observation_record(migrated, dispatch)
    closure = _legacy_closure_record(migrated, task_id, attempt)
    contract_summary = _migrate_contract_summary(
        migrated, objective_summary, task_id=task_id
    )
    migrated["contract_summary"] = contract_summary
    migrated.pop("task_id", None)
    migrated.pop("attempt", None)
    migrated.pop("deliverable_contract", None)
    for field_name in LEGACY_EXECUTION_PROJECTION_FIELDS:
        migrated.pop(field_name, None)
    migrated.update(
        dispatch_record=dispatch,
        observation_record=observation,
        closure_record=closure,
    )
    return migrated


def _validate_current_execution_planes(execution: dict[str, Any]) -> None:
    expected = {
        "dispatch_record": REQUIRED_DISPATCH_RECORD_FIELDS,
        "observation_record": REQUIRED_OBSERVATION_RECORD_FIELDS,
        "closure_record": REQUIRED_CLOSURE_RECORD_FIELDS,
    }
    for field_name, required in expected.items():
        record = execution.get(field_name)
        if not isinstance(record, dict):
            raise StateValidationError(f"managed execution 缺少 canonical plane {field_name}")
        missing = required - set(record)
        if missing:
            raise StateValidationError(
                f"canonical plane {field_name} 缺少字段 {', '.join(sorted(missing))}"
            )
        unknown = set(record) - required
        if unknown:
            raise StateValidationError(
                f"canonical plane {field_name} 包含未知字段 {', '.join(sorted(unknown))}"
            )

    task_ref = execution.get("task_ref")
    if not isinstance(task_ref, str) or not task_ref:
        raise StateValidationError("managed execution 的 task_ref 无效")

    dispatch = execution["dispatch_record"]
    observation = execution["observation_record"]
    closure = execution["closure_record"]

    enum_fields = (
        (dispatch, "dispatch_state", DISPATCH_STATES),
        (observation, "observed_state", OBSERVED_STATES),
    )
    for record, field_name, allowed in enum_fields:
        if record.get(field_name) not in allowed:
            raise StateValidationError(f"canonical plane 字段 {field_name} 使用未知枚举值")
    nullable_enums = (
        (observation, "source", OBSERVATION_SOURCES),
        (closure, "parent_action", PARENT_ACTIONS),
    )
    for record, field_name, allowed in nullable_enums:
        value = record.get(field_name)
        if value is not None and value not in allowed:
            raise StateValidationError(f"canonical plane 字段 {field_name} 使用未知枚举值")

    timestamp_fields = (
        (observation, "observed_at"),
        (closure, "closed_at"),
    )
    for record, field_name in timestamp_fields:
        value = record.get(field_name)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise StateValidationError(f"canonical plane 时间字段 {field_name} 无效")
    terminal_status = observation.get("terminal_status")
    if terminal_status is not None and terminal_status not in {
        "completed", "stopped", "interrupted"
    }:
        raise StateValidationError("observation_record.terminal_status 无效")
    if observation.get("observed_state") == "terminal" and terminal_status is None:
        raise StateValidationError("terminal observation 缺少 terminal_status")
    reason = closure.get("reason")
    closed_at = closure.get("closed_at")
    if reason is not None and not _valid_close_reason(reason):
        raise StateValidationError("closure_record.reason 无效")
    if (reason is None) != (closed_at is None):
        raise StateValidationError("closure_record 的 reason 与 closed_at 必须同时存在或同时为空")


def _promote_v4_parent_result_to_notification(execution: dict[str, Any]) -> None:
    result = execution.get("result_record")
    dispatch = execution.get("dispatch_record")
    observation = execution.get("observation_record")
    closure = execution.get("closure_record")
    if not all(isinstance(item, dict) for item in (result, dispatch, observation, closure)):
        return
    sender = result.get("sender_target")
    observed_at = result.get("submitted_at")
    if not (
        result.get("submission_provenance") == "parent_recorded_native_sender"
        and result.get("result_state") in {"valid", "conflict"}
        and isinstance(sender, str)
        and sender == dispatch.get("dispatch_target")
        and isinstance(observed_at, int)
        and not isinstance(observed_at, bool)
        and observed_at >= 0
    ):
        return
    observation.update(
        source="terminal_notification",
        observed_state="terminal",
        observed_at=observed_at,
        terminal_status="completed",
    )
    if not _execution_is_closed(execution):
        closure["parent_action"] = "decide_disposition"


def _retire_v4_result_state(execution: dict[str, Any]) -> None:
    _promote_v4_parent_result_to_notification(execution)
    execution.pop("result_record", None)
    execution.pop("correction_count", None)
    execution.pop("result_protocol_error", None)
    execution.pop("result_storage_error", None)
    for field_name in (
        "business_result",
        "business_decision_resolved",
        "acceptance_status",
        "result_protocol_status",
        "result_storage_status",
        "result_reference",
        "result_sha256",
        "result_stored_at",
        "result_conflict",
        "result_conflict_observed_at",
        "result_conflict_sender_target",
        "result_conflict_sha256",
    ):
        execution.pop(field_name, None)
    pending = execution.get("pending_action")
    if isinstance(pending, dict) and pending.get("operation_type") == "result_correction":
        if pending.get("phase") == "claimed":
            execution["closure_record"]["parent_action"] = "reconcile"
        execution.pop("pending_action", None)
    lifecycle = execution.get("last_lifecycle_operation")
    if isinstance(lifecycle, dict) and lifecycle.get("operation_type") == "result_correction":
        execution.pop("last_lifecycle_operation", None)
        execution["closure_record"]["parent_action"] = "reconcile"
    closure = execution.get("closure_record")
    if isinstance(closure, dict):
        disposition = closure.get("parent_disposition")
        if disposition in {"accept", "reject"} and not _execution_is_closed(execution):
            closure["parent_action"] = "decide_disposition"
        closure.pop("parent_disposition", None)
        closure.pop("disposition_recorded_at", None)
        closure["parent_action"] = _migrated_parent_action(closure.get("parent_action"))
    for field_name in LEGACY_EXECUTION_PROJECTION_FIELDS:
        execution.pop(field_name, None)


def _migrate_execution_records(
    executions: dict[str, Any],
    *,
    version: Any,
    task_id: str,
    objective_summary: Any,
) -> None:
    for attempt_key, execution in list(executions.items()):
        if not isinstance(execution, dict):
            continue
        attempt = _parse_execution_key(attempt_key)
        if attempt is None:
            raise StateValidationError(
                f"managed task {task_id} 包含非法 execution 键 {attempt_key}"
            )
        execution.pop("managed", None)
        execution.pop("task_id", None)
        execution.pop("attempt", None)
        execution.pop("spawn_task_name", None)
        execution.pop("origin_attempt", None)
        execution.pop("origin_task_name", None)
        execution.pop("dispatch_kind", None)
        execution.pop("transition", None)
        execution.pop("growth_authorization", None)
        execution.pop("deliverable_contract", None)
        execution.pop("semantic_name", None)
        execution.pop("requested_mode", None)
        execution.pop("resolution_reason", None)
        execution.pop("created_at", None)
        execution.pop("activity_at", None)
        execution.pop("recovery_status", None)
        execution.pop("terminal_reconciliation_reason", None)
        execution.pop("terminal_reconciled_at", None)
        execution.pop("reconciliation_reason", None)
        execution.pop("reconciled_thread_id", None)
        execution.pop("reconciled_thread_status", None)
        execution.pop("spawn_close_reason", None)
        pending = execution.get("pending_action")
        if isinstance(pending, dict):
            pending.pop("task_id", None)
            pending.pop("reason", None)
            pending.pop("transition", None)
            pending.pop("expires_at", None)
            pending.pop("resume_contract_summary", None)
            pending.pop("resume_contract_digest", None)
            pending.pop("resume_task_ref", None)
            pending.pop("growth_authorization", None)
            pending.pop("deliverable_contract", None)
            pending.pop("deliverable_contract_digest", None)
            pending.pop("start_observed_at", None)
            pending.pop("disposition", None)
            if not (
                pending.get("operation_type") == "platform_recovery"
                and execution.get("recovery_count") == 1
                and pending.get("authorized_recovery") is True
            ):
                pending.pop("authorized_recovery", None)
        lifecycle = execution.get("last_lifecycle_operation")
        if isinstance(lifecycle, dict):
            lifecycle.pop("target", None)
            lifecycle.pop("claimed_at", None)
            lifecycle.pop("completed_at", None)
            lifecycle.pop("reason", None)
            lifecycle.pop("native_status", None)
        has_canonical_planes = all(
            field_name in execution
            for field_name in (
                "dispatch_record", "observation_record", "closure_record"
            )
        )
        if has_canonical_planes:
            execution["contract_summary"] = _migrate_contract_summary(
                execution, objective_summary, task_id=task_id
            )
            dispatch_record = execution.get("dispatch_record")
            if isinstance(dispatch_record, dict):
                dispatch_record.pop("task_id", None)
                dispatch_record.pop("attempt", None)
                dispatch_record.pop("task_ref", None)
                dispatch_record.pop("claimed_at", None)
                dispatch_record.pop("response_observed_at", None)
                dispatch_record.pop("response_digest", None)
            observation_record = execution.get("observation_record")
            retired_observation_source = False
            if isinstance(observation_record, dict):
                retired_observation_source = (
                    observation_record.get("source") in RETIRED_OBSERVATION_SOURCES
                )
                legacy_subject_present = "subject" in observation_record
                legacy_subject = observation_record.pop("subject", None)
                legacy_binding_basis = observation_record.pop(
                    "binding_basis", None
                )
                dispatch_target = (
                    dispatch_record.get("dispatch_target")
                    if isinstance(dispatch_record, dict)
                    else None
                )
                legacy_binding_untrusted = bool(
                    (
                        legacy_subject_present
                        and legacy_subject != dispatch_target
                    )
                    or (
                        legacy_binding_basis is not None
                        and legacy_binding_basis != "exact_dispatch_target"
                    )
                )
                if retired_observation_source or (
                    legacy_binding_untrusted
                    and observation_record.get("observed_state")
                    != "not_observed"
                ):
                    observation_record.update(
                        source=None,
                        observed_state="not_observed",
                        observed_at=None,
                        terminal_status=None,
                    )
                observation_record.pop("bound_task_id", None)
                observation_record.pop("bound_attempt", None)
                observation_record.pop("runtime_alias", None)
                observation_record.pop("fresh_until", None)
                observation_record.pop("observation_id", None)
                observation_record.pop("subject_kind", None)
            closure_record = execution.get("closure_record")
            if isinstance(closure_record, dict):
                closure_record.pop("task_id", None)
                closure_record.pop("attempt", None)
                claimed_closed = closure_record.pop("closure_state", None) == "closed"
                _normalize_migrated_closure_facts(
                    closure_record, claimed_closed=claimed_closed
                )
                if retired_observation_source and not _execution_is_closed(execution):
                    closure_record["parent_action"] = "reconcile"
            _retire_v4_result_state(execution)
            _validate_current_execution_planes(execution)
            continue
        if version not in {None, 1}:
            raise StateValidationError(
                f"治理状态 format {version} 的 managed execution 缺少 canonical planes"
            )
        executions[attempt_key] = _migrate_legacy_execution_record(
            execution,
            task_id=task_id,
            attempt=attempt,
            objective_summary=objective_summary,
        )


def _migrate_managed_tasks(migrated: dict[str, Any], version: Any) -> None:
    tasks = migrated.get("tasks")
    if isinstance(tasks, dict):
        for task_key, task in tasks.items():
            if not isinstance(task, dict) or task.get("managed") is not True:
                continue
            task_id_errors = _validate_text(
                task_key,
                "task_id",
                maximum=int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"]),
            )
            if task_id_errors:
                raise StateValidationError("managed task 的 tasks 键不是合法 task_id")
            task_id = str(task_key)
            task.pop("task_id", None)
            task.pop("result_credentials", None)
            work_item = task.get("work_item")
            objective_summary = (
                work_item.get("objective_summary")
                if isinstance(work_item, dict)
                else None
            )
            if isinstance(work_item, dict):
                work_item.pop("objective_summary", None)
                work_item.pop("created_at", None)
                work_item.pop("updated_at", None)
                work_item.pop("attempt_count", None)
                work_item.pop("action_required", None)
                work_item.pop("last_growth_authorization", None)
                work_item.pop("repeated_business_attempts", None)
                work_item.pop("last_parent_disposition", None)
                work_item.pop("last_disposition", None)
            executions = task.get("executions")
            if not isinstance(executions, dict):
                continue
            _migrate_execution_records(
                executions,
                version=version,
                task_id=task_id,
                objective_summary=objective_summary,
            )


def _migrate_groups(migrated: dict[str, Any]) -> None:
    groups = migrated.get("groups")
    if isinstance(groups, dict):
        for group in groups.values():
            if isinstance(group, dict):
                group.pop("created_at", None)
                group.pop("updated_at", None)


def _migrate_tombstones(migrated: dict[str, Any]) -> None:
    tasks = migrated.get("tasks")
    tombstones = migrated.get("tombstones")
    if isinstance(tombstones, dict):
        for tombstone_key, tombstone in list(tombstones.items()):
            if not isinstance(tombstone, dict):
                continue
            identity = _parse_tombstone_key(tombstone_key)
            task = (
                tasks.get(identity[0])
                if identity is not None and isinstance(tasks, dict)
                else None
            )
            work_item = task.get("work_item") if isinstance(task, dict) else None
            execution = (
                _canonical_execution_for_attempt(task, identity[1])
                if isinstance(task, dict) and identity is not None
                else None
            )
            if (
                tombstone.get("close_reason") == "spawn_retry_exhausted"
                and isinstance(work_item, dict)
                and work_item.get("lifecycle") == "open"
                and isinstance(execution, dict)
                and not _execution_is_closed(execution)
                and _spawn_observation(execution) == "failed"
                and execution.get("spawn_retry_count") == RETRY_LIMITS["spawn"]
                and _parent_action(execution) == "decide_disposition"
            ):
                tombstones.pop(tombstone_key, None)
                continue
            dispatch_target = tombstone.get("dispatch_target")
            if not isinstance(dispatch_target, str) or not dispatch_target.strip():
                legacy_target = tombstone.get("canonical_task_path")
                if isinstance(legacy_target, str) and legacy_target.strip():
                    tombstone["dispatch_target"] = legacy_target
                else:
                    tombstone.pop("dispatch_target", None)
            tombstone.pop("agent_id", None)
            tombstone.pop("canonical_task_path", None)
            tombstone.pop("last_execution_status", None)
            tombstone.pop("task_id", None)
            tombstone.pop("attempt", None)


def _migrate_state_to_current(value: dict[str, Any]) -> dict[str, Any]:
    migrated = copy.deepcopy(value)
    version = migrated.get("state_format_version")
    if isinstance(version, bool) or version not in {None, 1, 2, 3, 4, STATE_FORMAT_VERSION}:
        raise StateValidationError(f"治理状态使用未知格式版本 {version}")
    migrated.pop("updated_at", None)
    _migrate_managed_tasks(migrated, version)
    _migrate_groups(migrated)
    _migrate_tombstones(migrated)
    migrated["state_format_version"] = STATE_FORMAT_VERSION
    return migrated


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


def _state_for_storage(value: dict[str, Any]) -> dict[str, Any]:
    return _migrate_state_to_current(value)


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


def _required_fields(value: Any, fields: list[str]) -> list[str]:
    if not isinstance(value, dict):
        return ["根节点必须是对象"]
    return [f"缺少字段 {field_name}" for field_name in fields if field_name not in value]


def _validate_text(
    value: Any,
    field_name: str,
    *,
    maximum: int,
    nullable: bool = False,
) -> list[str]:
    if value is None and nullable:
        return []
    if not isinstance(value, str):
        return [f"字段 {field_name} 必须是字符串" + ("或 null" if nullable else "")]
    if not value.strip():
        return [f"字段 {field_name} 不能为空"]
    if len(value) > maximum:
        return [f"字段 {field_name} 长度不能超过 {maximum}"]
    return []


def _validate_text_list(
    value: Any,
    field_name: str,
    *,
    minimum: int = 0,
) -> list[str]:
    definition = SEMANTIC_DEFINITIONS["text_list"]
    maximum_items = int(definition["maxItems"])
    item_maximum = int(definition["items"]["maxLength"])
    if not isinstance(value, list):
        return [f"字段 {field_name} 必须是数组"]
    errors: list[str] = []
    if len(value) < minimum:
        errors.append(f"字段 {field_name} 至少需要 {minimum} 项")
    if len(value) > maximum_items:
        errors.append(f"字段 {field_name} 不能超过 {maximum_items} 项")
    for index, item in enumerate(value):
        errors.extend(
            _validate_text(item, f"{field_name}[{index}]", maximum=item_maximum)
        )
    return errors


def _validate_context_manifest(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["字段 context_manifest 必须是对象"]
    mode = value.get("mode")
    if mode not in {"none", "declared"}:
        return ["字段 context_manifest.mode 必须是 none 或 declared"]
    if mode == "none":
        extras = sorted(set(value) - {"mode"})
        return (
            ["context_manifest.mode=none 时不能包含字段 " + "、".join(extras)]
            if extras
            else []
        )

    errors = _required_fields(
        value,
        ("mode", "workspace_root", "baseline", "required_paths"),
    )
    extras = sorted(
        set(value) - {"mode", "workspace_root", "baseline", "required_paths"}
    )
    if extras:
        errors.append("context_manifest 包含未知字段 " + "、".join(extras))
    workspace_root = value.get("workspace_root")
    if not isinstance(workspace_root, str) or not workspace_root.strip():
        errors.append("字段 context_manifest.workspace_root 必须是非空绝对路径")
    elif workspace_root != workspace_root.strip() or len(workspace_root) > 4000:
        errors.append(
            "字段 context_manifest.workspace_root 不能包含首尾空白且长度不能超过 4000"
        )
    elif not Path(workspace_root).is_absolute():
        errors.append("字段 context_manifest.workspace_root 必须是绝对路径")

    baseline = value.get("baseline")
    baseline_kind = baseline.get("kind") if isinstance(baseline, dict) else None
    if not isinstance(baseline, dict):
        errors.append("字段 context_manifest.baseline 必须是对象")
    else:
        baseline_extras = sorted(set(baseline) - {"kind", "revision"})
        if baseline_extras:
            errors.append(
                "context_manifest.baseline 包含未知字段 "
                + "、".join(baseline_extras)
            )
        missing = sorted({"kind", "revision"} - set(baseline))
        if missing:
            errors.append(
                "context_manifest.baseline 缺少字段 " + "、".join(missing)
            )
        kind = baseline_kind
        revision = baseline.get("revision")
        if kind == "working_tree":
            if revision is not None:
                errors.append("baseline.kind=working_tree 时 revision 必须是 null")
        elif kind == "git_commit":
            if not isinstance(revision, str) or re.fullmatch(
                r"(?:[a-f0-9]{40}|[a-f0-9]{64})", revision
            ) is None:
                errors.append("baseline.kind=git_commit 时 revision 必须是完整 commit OID")
        elif len(path_value) > 1000:
            errors.append(f"字段 {field_name}.path 长度不能超过 1000")
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
        else:
            path = path_value.strip()
            parts = path.split("/")
            if (
                path != path_value
                or path.startswith("/")
                or "\\" in path
                or any(part in {"", ".", ".."} for part in parts)
                or any(ord(character) < 32 for character in path)
            ):
                errors.append(
                    f"字段 {field_name}.path 必须是规范的 POSIX 相对路径，不能包含空段、.、.. 或控制字符"
                )
            elif path in seen:
                errors.append(f"字段 {field_name}.path 不能重复：{path}")
            else:
                seen.add(path)
        path_type = item.get("type")
        if path_type not in {"file", "directory"}:
            errors.append(f"字段 {field_name}.type 必须是 file 或 directory")
        elif baseline_kind == "working_tree" and path_type == "directory":
            errors.append(
                f"working_tree 不支持字段 {field_name}.type=directory；"
                "请逐文件声明，或改用 git_commit baseline"
            )
    return errors


def _validate_context_verification_record(
    manifest: Any,
    verification: Any,
) -> list[str]:
    if not isinstance(manifest, dict) or not isinstance(verification, dict):
        return ["context manifest/verification 必须是对象"]
    mode = manifest.get("mode")
    if verification.get("mode") != mode:
        return ["context manifest/verification 模式不一致"]
    if mode == "none":
        return [] if verification == {"mode": "none"} else [
            "none context verification 不能包含其他字段"
        ]
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
            errors.append(
                f"context verification required_paths[{index}] 路径或类型与契约不一致"
            )
            continue
        if baseline_kind == "git_commit":
            if set(verified) != {"path", "type", "object_id"} or not isinstance(
                verified.get("object_id"), str
            ) or re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", verified["object_id"]) is None:
                errors.append(
                    f"context verification required_paths[{index}] Git object ID 无效"
                )
        elif baseline_kind == "working_tree" and (
            set(verified) != {"path", "type", "sha256"}
            or not isinstance(verified.get("sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", verified["sha256"]) is None
        ):
            errors.append(
                f"context verification required_paths[{index}] SHA-256 无效"
            )
    return errors


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _run_git(workspace_root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace_root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or "").strip()
        suffix = f"：{detail[:600]}" if detail else ""
        raise ContextVerificationError(
            f"Git 上下文校验失败（{' '.join(arguments)}）{suffix}"
        ) from exc
    return result.stdout.strip()


def verify_context_manifest(value: Any) -> dict[str, Any]:
    errors = _validate_context_manifest(value)
    if errors:
        raise ContextVerificationError("；".join(errors))
    assert isinstance(value, dict)
    if value["mode"] == "none":
        return {"mode": "none"}

    workspace_root = Path(str(value["workspace_root"])).resolve()
    if not workspace_root.is_dir():
        raise ContextVerificationError(
            f"必需上下文工作区不存在或不是目录：{workspace_root}"
        )
    baseline = value["baseline"]
    assert isinstance(baseline, dict)
    baseline_kind = str(baseline["kind"])
    verified_paths: list[dict[str, Any]] = []

    if baseline_kind == "git_commit":
        repository_root = Path(
            _run_git(workspace_root, "rev-parse", "--show-toplevel")
        ).resolve()
        if repository_root != workspace_root:
            raise ContextVerificationError(
                "context_manifest.workspace_root 必须是 Git 仓库根目录："
                f"声明 {workspace_root}，实际 {repository_root}"
            )
        revision = str(baseline["revision"])
        _run_git(workspace_root, "cat-file", "-e", f"{revision}^{{commit}}")
        current_head = _run_git(workspace_root, "rev-parse", "--verify", "HEAD")
        if current_head != revision:
            raise ContextVerificationError(
                f"Git 工作区 HEAD 与声明 baseline 不一致：HEAD={current_head}，baseline={revision}"
            )
        for item in value["required_paths"]:
            path_value = str(item["path"])
            expected_type = str(item["type"])
            object_spec = f"{revision}:{path_value}"
            try:
                object_type = _run_git(workspace_root, "cat-file", "-t", object_spec)
                object_id = _run_git(workspace_root, "rev-parse", "--verify", object_spec)
            except ContextVerificationError as exc:
                raise ContextVerificationError(
                    f"Git baseline {revision} 缺少必需上下文 {path_value}"
                ) from exc
            expected_object_type = "blob" if expected_type == "file" else "tree"
            if object_type != expected_object_type:
                raise ContextVerificationError(
                    f"必需上下文类型不匹配：{path_value} 声明为 {expected_type}，"
                    f"Git 对象类型为 {object_type}"
                )
            dirty = _run_git(
                workspace_root,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                path_value,
            )
            if dirty:
                raise ContextVerificationError(
                    f"必需上下文工作区内容与 Git baseline 不一致：{path_value}"
                )
            verified_paths.append(
                {
                    "path": path_value,
                    "type": expected_type,
                    "object_id": object_id,
                }
            )
        verified_baseline = {"kind": "git_commit", "revision": revision}
    else:
        for item in value["required_paths"]:
            path_value = str(item["path"])
            expected_type = str(item["type"])
            candidate = (workspace_root / Path(path_value)).resolve()
            try:
                candidate.relative_to(workspace_root)
            except ValueError as exc:
                raise ContextVerificationError(
                    f"必需上下文路径逃出工作区：{path_value}"
                ) from exc
            if not candidate.exists():
                raise ContextVerificationError(f"必需上下文不存在：{path_value}")
            if not candidate.is_file():
                raise ContextVerificationError(f"必需上下文不是文件：{path_value}")
            verified: dict[str, Any] = {
                "path": path_value,
                "type": expected_type,
            }
            verified["sha256"] = _sha256_file(candidate)
            verified_paths.append(verified)
        verified_baseline = {"kind": "working_tree", "revision": None}

    result = {
        "mode": "declared",
        "workspace_root": str(workspace_root),
        "baseline": verified_baseline,
        "required_paths": verified_paths,
    }
    verification_errors = _validate_context_verification_record(value, result)
    if verification_errors:
        raise ContextVerificationError("；".join(verification_errors))
    return result


def _validate_task_features(value: Any, *, required: bool) -> list[str]:
    if value is None:
        return ["缺少字段 task_features"] if required else []
    if isinstance(value, TaskFeatures):
        value = value.to_record()
    if not isinstance(value, dict):
        return ["字段 task_features 必须是对象或 null"]
    required_fields = list(SEMANTIC_DEFINITIONS["task_features"]["required"])
    errors = _required_fields(value, required_fields)
    risk = value.get("risk")
    if risk not in RISKS:
        errors.append("字段 task_features.risk 必须是 low、medium 或 high")
    for field_name in required_fields[1:]:
        if not isinstance(value.get(field_name), bool):
            errors.append(f"字段 task_features.{field_name} 必须是布尔值")
    if value.get("read_only") is True and value.get("writes_files") is True:
        errors.append("task_features.read_only=true 与 writes_files=true 机械矛盾")
    return errors


def resolve_governance_mode(
    requested_mode: str,
    task_features: dict[str, Any] | TaskFeatures | None = None,
) -> tuple[str, str]:
    if requested_mode not in REQUESTED_MODES:
        raise ValueError("requested_mode 必须是 auto、light、standard 或 strict")
    if requested_mode in RESOLVED_MODES:
        return requested_mode, "explicit_request"
    errors = _validate_task_features(task_features, required=True)
    if errors:
        raise ValueError("；".join(errors))
    features = task_features.to_record() if isinstance(task_features, TaskFeatures) else task_features
    assert isinstance(features, dict)
    strict_signal = features.get("risk") in AUTO_RESOLUTION["strict_risks"] or any(
        features.get(field_name) is True
        for field_name in AUTO_RESOLUTION["strict_true_fields"]
    )
    if strict_signal:
        return "strict", "auto_strict"
    if all(features.get(field_name) == expected for field_name, expected in AUTO_RESOLUTION["light_match"].items()):
        return "light", "auto_light"
    return "standard", "auto_standard"


def validate_task_contract(value: Any) -> list[str]:
    required = [
        field_name
        for field_name in SEMANTIC_RULES["task_contract_fields"]
        if field_name not in TASK_CONTRACT_OPTIONAL_FIELDS
    ]
    errors = _required_fields(value, required)
    if not isinstance(value, dict):
        return errors

    semantic_name = value.get("semantic_name")
    semantic_definition = SEMANTIC_DEFINITIONS["semantic_name"]
    errors.extend(
        _validate_text(
            semantic_name,
            "semantic_name",
            maximum=int(semantic_definition["maxLength"]),
        )
    )
    if isinstance(semantic_name, str) and not re.fullmatch(semantic_definition["pattern"], semantic_name):
        errors.append("字段 semantic_name 只能使用小写字母、数字和单个下划线分隔")

    requested_mode = value.get("requested_mode")
    resolved_mode = value.get("resolved_mode")
    resolution_reason = value.get("resolution_reason")
    if requested_mode not in REQUESTED_MODES:
        errors.append("字段 requested_mode 枚举无效")
    if resolved_mode not in RESOLVED_MODES:
        errors.append("字段 resolved_mode 枚举无效")
    if resolution_reason not in RESOLUTION_REASONS:
        errors.append("字段 resolution_reason 枚举无效")

    features = value.get("task_features")
    errors.extend(_validate_task_features(features, required=True))
    if requested_mode in RESOLVED_MODES:
        if resolved_mode != requested_mode:
            errors.append("显式 requested_mode 的 resolved_mode 必须与请求值相同")
        if resolution_reason != "explicit_request":
            errors.append("显式 requested_mode 的 resolution_reason 必须是 explicit_request")
    elif requested_mode == "auto" and not _validate_task_features(features, required=True):
        try:
            expected_mode, expected_reason = resolve_governance_mode("auto", features)
        except ValueError:
            pass
        else:
            if resolved_mode != expected_mode:
                errors.append(f"auto 解析后的 resolved_mode 必须是 {expected_mode}")
            if resolution_reason != expected_reason:
                errors.append(f"auto 解析后的 resolution_reason 必须是 {expected_reason}")

    business_maximum = int(SEMANTIC_DEFINITIONS["business_text"]["maxLength"])
    errors.extend(_validate_text(value.get("objective"), "objective", maximum=business_maximum))
    errors.extend(_validate_text(value.get("background"), "background", maximum=business_maximum))
    errors.extend(_validate_text_list(value.get("work_scope"), "work_scope", minimum=1))
    mode_minimums = MODE_MINIMUMS.get(str(resolved_mode), {})
    errors.extend(
        _validate_text_list(
            value.get("forbidden_scope"),
            "forbidden_scope",
            minimum=int(mode_minimums.get("forbidden_scope", 0)),
        )
    )
    errors.extend(
        _validate_text_list(value.get("completion_conditions"), "completion_conditions", minimum=1)
    )
    evidence_minimum = int(mode_minimums.get("evidence_requirements", 0))
    errors.extend(
        _validate_text_list(
            value.get("evidence_requirements"),
            "evidence_requirements",
            minimum=evidence_minimum,
        )
    )
    errors.extend(_validate_text_list(value.get("relevant_files"), "relevant_files"))
    errors.extend(_validate_context_manifest(value.get("context_manifest")))
    errors.extend(
        _validate_text(
            value.get("current_state"),
            "current_state",
            maximum=business_maximum,
            nullable=True,
        )
    )

    if "model" in value:
        errors.extend(
            _validate_text(
                value.get("model"),
                "model",
                maximum=int(SEMANTIC_DEFINITIONS["model"]["maxLength"]),
                nullable=True,
            )
        )
    if "reasoning_effort" in value:
        effort = value.get("reasoning_effort")
        if effort is not None and effort not in REASONING_EFFORTS:
            errors.append("字段 reasoning_effort 枚举无效")

    strategy = value.get("context_strategy")
    turns = value.get("context_turns")
    reason = value.get("context_reason")
    if strategy not in CONTEXT_STRATEGIES:
        errors.append("字段 context_strategy 枚举无效")
    if strategy == "isolated":
        if turns is not None:
            errors.append("context_strategy=isolated 时 context_turns 必须是 null")
        errors.extend(_validate_text(reason, "context_reason", maximum=business_maximum, nullable=True))
    elif strategy == "limited":
        minimum = int(CONTEXT_TURNS["minimum"])
        maximum = int(CONTEXT_TURNS["maximum"])
        if isinstance(turns, bool) or not isinstance(turns, int) or not minimum <= turns <= maximum:
            errors.append(
                f"context_strategy=limited 时 context_turns 必须是 {minimum} 至 {maximum} 的整数"
            )
        errors.extend(_validate_text(reason, "context_reason", maximum=business_maximum))
    elif strategy == "full":
        if turns is not None:
            errors.append("context_strategy=full 时 context_turns 必须是 null")
        errors.extend(_validate_text(reason, "context_reason", maximum=business_maximum))
    return errors


def normalize_semantic_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", text)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "task"


def derive_task_ref(task_id: str, attempt: int, length: int) -> str:
    if length not in TASK_REF_LENGTHS:
        raise ValueError(f"task_ref 长度必须是 {', '.join(map(str, TASK_REF_LENGTHS))} 之一")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id 必须是非空字符串")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt 必须是正整数")
    digest = hashlib.sha256(f"{task_id}:{attempt}".encode("utf-8")).hexdigest()
    return digest[:length]


def select_task_ref(task_id: str, attempt: int, occupied_refs: set[str]) -> str | None:
    for length in TASK_REF_LENGTHS:
        candidate = derive_task_ref(task_id, attempt, length)
        if candidate not in occupied_refs:
            return candidate
    return None


def build_task_name(resolved_mode: str, semantic_name: str, task_ref: str) -> str:
    if resolved_mode not in RESOLVED_MODES:
        raise ValueError("resolved_mode 必须是 light、standard 或 strict")
    if len(task_ref) not in TASK_REF_LENGTHS or not re.fullmatch(r"[a-f0-9]+", task_ref):
        raise ValueError("task_ref 必须是允许长度的小写十六进制")
    normalized = normalize_semantic_name(semantic_name)
    fixed_length = len(f"sg_{resolved_mode}__t_{task_ref}")
    available = TASK_NAME_MAX_LENGTH - fixed_length
    if available < 1:
        raise ValueError("task_name 固定字段超过长度上限")
    semantic = normalized[:available].rstrip("_") or "task"[:available]
    task_name = f"sg_{resolved_mode}_{semantic}_t_{task_ref}"
    if len(task_name) > TASK_NAME_MAX_LENGTH or TASK_NAME_RE.fullmatch(task_name) is None:
        raise ValueError("无法生成合法且不超过64字符的 task_name")
    return task_name


def parse_task_name(task_name: Any) -> tuple[str, str, str] | None:
    if not isinstance(task_name, str) or len(task_name) > TASK_NAME_MAX_LENGTH:
        return None
    match = TASK_NAME_RE.fullmatch(task_name)
    if not match or len(match.group(3)) not in TASK_REF_LENGTHS:
        return None
    return match.group(1), match.group(2), match.group(3)


def _contract_from_input(value: Any) -> TaskContract:
    if isinstance(value, TaskContract):
        raw = value.to_record()
    elif isinstance(value, dict):
        raw = copy.deepcopy(value)
    else:
        raise ValueError("TaskContract 输入必须是对象")
    raw["semantic_name"] = normalize_semantic_name(raw.get("semantic_name"))
    features = raw.get("task_features")
    if isinstance(features, TaskFeatures):
        features = features.to_record()
        raw["task_features"] = features
    requested_mode = raw.get("requested_mode")
    resolved_mode, resolution_reason = resolve_governance_mode(requested_mode, features)
    supplied_mode = raw.get("resolved_mode")
    supplied_reason = raw.get("resolution_reason")
    if supplied_mode is not None and supplied_mode != resolved_mode:
        raise ValueError(f"resolved_mode 必须由生成器解析为 {resolved_mode}")
    if supplied_reason is not None and supplied_reason != resolution_reason:
        raise ValueError(f"resolution_reason 必须由生成器解析为 {resolution_reason}")
    raw["resolved_mode"] = resolved_mode
    raw["resolution_reason"] = resolution_reason
    errors = validate_task_contract(raw)
    if errors:
        raise ValueError("；".join(errors))
    field_names = TaskContract.__dataclass_fields__
    return TaskContract(**{field_name: raw.get(field_name) for field_name in field_names})


def _context_projection(contract: TaskContract) -> tuple[str, str]:
    if contract.context_strategy == "isolated":
        return "none", "否"
    if contract.context_strategy == "limited":
        assert contract.context_turns is not None
        return str(contract.context_turns), f"否（仅继承最近 {contract.context_turns} 轮）"
    return "all", "是"


def _render_list(values: list[str]) -> str:
    if not values:
        return "- 无"
    return "\n".join(f"- {value}" for value in values)


def _render_verified_context(verification: dict[str, Any]) -> str:
    if verification.get("mode") == "none":
        return "- 无"
    baseline = verification.get("baseline")
    if not isinstance(baseline, dict):
        raise ContextVerificationError("context verification 缺少 baseline")
    kind = baseline.get("kind")
    if kind == "git_commit":
        baseline_line = f"- 基线：git_commit {baseline.get('revision')}"
    else:
        baseline_line = "- 基线：working_tree（prepare 与 spawn 双重校验）"
    lines = [
        f"- 工作区：{verification.get('workspace_root')}",
        baseline_line,
    ]
    paths = verification.get("required_paths")
    if not isinstance(paths, list):
        raise ContextVerificationError("context verification 缺少 required_paths")
    lines.extend(
        f"- {item['path']}（{item['type']}，已验证）"
        for item in paths
        if isinstance(item, dict)
    )
    return "\n".join(lines)


def render_dispatch_prompt(
    contract: TaskContract,
    context_verification: dict[str, Any],
) -> str:
    current_state = contract.current_state or "无额外未落盘状态"
    context_reason = contract.context_reason or "默认隔离；任务背景已写入本首句"
    lines = [
            f"【治理等级】{contract.resolved_mode}",
            "【唯一当前目标】",
            contract.objective,
            "",
            "【背景】",
            contract.background,
            "",
            "【工作范围】",
            _render_list(contract.work_scope),
            "",
            "【禁止范围】",
            _render_list(contract.forbidden_scope),
            "",
            "【相关文件】",
            _render_list(contract.relevant_files),
            "",
            "【必需上下文】",
            _render_verified_context(context_verification),
            "",
            "【当前状态】",
            current_state,
            "",
            "【上下文策略】",
            f"{contract.context_strategy}：{context_reason}",
            "",
            "【完成条件】",
            _render_list(contract.completion_conditions),
            "",
            "【验收证据】",
            _render_list(contract.evidence_requirements),
            "",
            "【恢复与终态义务】",
            "完成、阻塞、失败或需要决策时，向父 Agent发送明确终态通知；不要只回复收到、明白或开始执行。",
            "平台或调用结果未知时如实报告，不得自行重派、伪造成功或覆盖其他 attempt。",
            "",
        ]
    return "\n".join(lines)


def render_dispatch_user_message(
    contract: TaskContract,
    context_verification: dict[str, Any],
) -> str:
    _native_context, context_display = _context_projection(contract)
    model_display = contract.model or "继承主 Agent（未显式覆盖）"
    effort_display = contract.reasoning_effort or "继承主 Agent 当前强度（未显式覆盖）"
    mode_line = f"治理等级：{contract.resolved_mode}"
    if contract.requested_mode == "auto":
        mode_line = (
            f"请求治理方式：auto；实际治理等级：{contract.resolved_mode}；"
            f"解析原因：{contract.resolution_reason}"
        )
    return "\n".join(
        (
            "【子 Agent 派发】",
            f"目标：{contract.objective}",
            mode_line,
            f"模型：{model_display}",
            f"强度：{effort_display}",
            f"是否继承主线程全部上下文：{context_display}",
            "必需上下文："
            + (
                "明确无材料依赖"
                if context_verification.get("mode") == "none"
                else f"已验证 {len(context_verification.get('required_paths', []))} 项"
            ),
            "工作范围：" + "；".join(contract.work_scope),
            "完成条件：" + "；".join(contract.completion_conditions),
            "回传要求：完成、阻塞或需要决策时，向父 Agent发送明确终态通知",
        )
    )


def _spawn_args(
    contract: TaskContract,
    task_name: str,
    context_verification: dict[str, Any],
) -> dict[str, Any]:
    fork_turns, _context_display = _context_projection(contract)
    result: dict[str, Any] = {
        "task_name": task_name,
        "message": render_dispatch_prompt(contract, context_verification),
        "fork_turns": fork_turns,
    }
    if contract.model is not None:
        result["model"] = contract.model
    if contract.reasoning_effort is not None:
        result["reasoning_effort"] = contract.reasoning_effort
    return result


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


def _current_uid() -> int | None:
    getuid = getattr(os, "getuid", None)
    return int(getuid()) if getuid is not None else None


def _owned_by_current_user(metadata: os.stat_result) -> bool:
    uid = _current_uid()
    return uid is None or getattr(metadata, "st_uid", uid) == uid


def _private_permissions_safe(metadata: os.stat_result) -> bool:
    return os.name == "nt" or stat.S_IMODE(metadata.st_mode) & 0o077 == 0


def _restrict_descriptor(descriptor: int, mode: int) -> None:
    fchmod = getattr(os, "fchmod", None)
    if fchmod is not None:
        fchmod(descriptor, mode)


def _restrict_path(path: Path, mode: int) -> None:
    if os.name != "nt":
        path.chmod(mode)


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _uses_windows_file_lock() -> bool:
    return os.name == "nt"


@contextmanager
def _exclusive_file_lock(lock_file):
    descriptor = lock_file.fileno()
    if _uses_windows_file_lock():
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write("\0")
            lock_file.flush()
            os.fsync(descriptor)
        lock_file.seek(0)
        assert msvcrt is not None
        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            lock_file.seek(0)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    assert fcntl is not None
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


def _user_storage_key() -> str:
    uid = _current_uid()
    if uid is not None:
        return str(uid)
    username = os.environ.get("USERNAME") or getpass.getuser() or "user"
    return hashlib.sha256(username.encode("utf-8")).hexdigest()[:12]


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


def _parse_tombstone_key(value: Any) -> tuple[str, int] | None:
    if not isinstance(value, str):
        return None
    task_id, separator, attempt_text = value.rpartition(":")
    if not separator or not task_id.strip() or re.fullmatch(r"[1-9][0-9]*", attempt_text) is None:
        return None
    return task_id, int(attempt_text)


def _parse_execution_key(value: Any) -> int | None:
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]*", value) is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _safe_name(value: str) -> str:
    raw = value or "unknown"
    prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")[:64] or "unknown"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _prepare_private_directory(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"治理状态目录必须是普通目录且不能是符号链接：{root}")
    if not _owned_by_current_user(metadata):
        raise PermissionError(f"治理状态目录不属于当前用户：{root}")
    _restrict_path(root, 0o700)
    return root


def _installed_plugin_data_root(script_path: Path | None = None) -> Path | None:
    resolved = (script_path or Path(__file__)).resolve(strict=False)
    parts = resolved.parts
    for index in range(len(parts) - 6):
        if parts[index : index + 2] != ("plugins", "cache"):
            continue
        marketplace = parts[index + 2]
        plugin_name = parts[index + 3]
        if (
            not marketplace
            or not plugin_name
            or parts[index + 5] != "scripts"
            or parts[index + 6] != "subagent_governance.py"
        ):
            continue
        codex_root = Path(*parts[:index])
        return (
            codex_root
            / "plugins"
            / "data"
            / f"{plugin_name}-{marketplace}"
            / "state-v1"
        )
    return None


def _data_root_path() -> Path:
    override = os.environ.get("SUBAGENT_GOVERNANCE_DATA")
    plugin_data = os.environ.get("PLUGIN_DATA")
    if override:
        root = Path(override).expanduser()
    elif plugin_data:
        root = Path(plugin_data).expanduser() / "state-v1"
    elif installed_root := _installed_plugin_data_root():
        root = installed_root
    else:
        root = Path(tempfile.gettempdir()) / f"subagent-governance-{_user_storage_key()}"
    return root


def _data_root() -> Path:
    return _prepare_private_directory(_data_root_path())


class StateStore:
    def __init__(self, root: Path | None = None):
        self.root = (
            _prepare_private_directory(root)
            if root is not None
            else _prepare_private_directory(_data_root() / "sessions")
        )
        self.last_warning: str | None = None

    @staticmethod
    def _empty_state(session_id: str) -> dict[str, Any]:
        return {
            "state_format_version": STATE_FORMAT_VERSION,
            "session_id": session_id,
            "tasks": {},
            "agents": {},
            "health": {"status": "ok"},
            "tombstones": {},
        }

    def _paths(self, session_id: str) -> tuple[Path, Path]:
        stem = _safe_name(session_id)
        return self.root / f"{stem}.json", self.root / f"{stem}.lock"

    @contextmanager
    def _lock(self, session_id: str):
        state_path, lock_path = self._paths(session_id)
        try:
            with locked_file(
                lock_path,
                label="治理",
                exclusive_lock=_exclusive_file_lock,
                restrict_descriptor=_restrict_descriptor,
                owned_by_current_user=_owned_by_current_user,
            ):
                yield state_path
        except PrivateStorageError as exc:
            raise StateValidationError(str(exc)) from exc

    @staticmethod
    def _validate_required_fields(
        value: dict[str, Any],
        required_fields: tuple[str, ...],
        path: Path,
    ) -> None:
        missing = [field_name for field_name in required_fields if field_name not in value]
        if missing:
            raise StateValidationError(
                f"治理状态缺少当前操作必需字段 {', '.join(missing)}：{path}"
            )
        for field_name in required_fields:
            if field_name in {"tasks", "agents", "health", "tombstones"} and not isinstance(
                value.get(field_name), dict
            ):
                raise StateValidationError(
                    f"治理状态字段 {field_name} 必须是对象：{path}"
                )

    @classmethod
    def _validate_state(
        cls,
        value: Any,
        session_id: str,
        path: Path,
        required_fields: tuple[str, ...],
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise StateValidationError(f"治理状态文件根节点必须是对象：{path}")
        if "session_id" not in value:
            raise StateValidationError(f"治理状态缺少当前操作必需字段 session_id：{path}")
        if value.get("session_id") != session_id:
            raise StateValidationError(f"治理状态文件与当前 session 不匹配：{path}")
        cls._validate_required_fields(value, required_fields, path)
        return value

    def _read_path(
        self,
        path: Path,
        session_id: str,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
    ) -> dict[str, Any]:
        try:
            raw = read_private_bytes(
                path,
                label="治理状态文件",
                max_bytes=MAX_STATE_BYTES,
                owned_by_current_user=_owned_by_current_user,
                private_permissions_safe=_private_permissions_safe,
            )
        except FileNotFoundError:
            state = self._empty_state(session_id)
            validated = self._validate_state(state, session_id, path, required_fields)
            return validated
        except PrivateStorageCapacityError as exc:
            raise StateCapacityError(str(exc)) from exc
        except PrivateStorageError as exc:
            raise StateValidationError(str(exc)) from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise StateValidationError(
                f"治理状态文件不是有效 UTF-8 JSON，原文件已保留供人工恢复：{path}"
            ) from exc
        validated = self._validate_state(value, session_id, path, required_fields)
        migrated = _migrate_state_to_current(validated)
        return migrated

    @staticmethod
    def _encoded_state(state: dict[str, Any]) -> bytes:
        try:
            content = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        except (TypeError, ValueError) as exc:
            raise StateValidationError("治理状态包含无法序列化的值") from exc
        return content.encode("utf-8")

    def _write_path(
        self,
        path: Path,
        session_id: str,
        state: dict[str, Any],
        *,
        required_fields: tuple[str, ...],
        admission: str,
    ) -> None:
        self._validate_state(state, session_id, path, required_fields)
        stored_state = _state_for_storage(state)
        encoded = self._encoded_state(stored_state)
        if admission not in {"existing", "new_task"}:
            raise StateValidationError("StateStore admission 必须是 existing 或 new_task")
        if admission == "new_task" and len(encoded) > NEW_TASK_SOFT_LIMIT_BYTES:
            raise StateCapacityError(
                f"新治理任务预计使状态超过 {NEW_TASK_SOFT_LIMIT_BYTES} 字节软准入线"
            )
        if len(encoded) > MAX_STATE_BYTES:
            raise StateCapacityError(f"治理状态超过 {MAX_STATE_BYTES} 字节上限")
        try:
            atomic_write_bytes(
                path,
                encoded,
                label="治理状态",
                restrict_descriptor=_restrict_descriptor,
                sync_directory=_sync_directory,
            )
        except PrivateStorageWriteError as exc:
            raise StateWriteError(str(exc)) from exc
        try:
            verified = self._read_path(
                path,
                session_id,
                required_fields,
            )
        except StateStoreError as exc:
            raise StateWriteError(f"治理状态写入后回读失败：{path}") from exc
        if verified != stored_state:
            raise StateWriteError(f"治理状态写入后回读内容不一致：{path}")

    def compare_and_set(
        self,
        session_id: str,
        predicate: Callable[[dict[str, Any]], bool],
        callback: Callable[[dict[str, Any]], Any],
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
        admission: str = "existing",
    ) -> Any:
        self.last_warning = None
        with self._lock(session_id) as state_path:
            state = self._read_path(state_path, session_id, required_fields)
            if not predicate(state):
                raise StateConflictError(f"治理状态 compare-and-set 冲突：{session_id}")
            result = callback(state)
            self._write_path(
                state_path,
                session_id,
                state,
                required_fields=required_fields,
                admission=admission,
            )
            return result

    def update(
        self,
        session_id: str,
        callback: Callable[[dict[str, Any]], Any],
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
        admission: str = "existing",
    ) -> Any:
        return self.compare_and_set(
            session_id,
            lambda _state: True,
            callback,
            required_fields=required_fields,
            admission=admission,
        )

    def read(
        self,
        session_id: str,
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
    ) -> dict[str, Any]:
        self.last_warning = None
        with self._lock(session_id) as state_path:
            return self._read_path(state_path, session_id, required_fields)

    def delete(self, session_id: str) -> None:
        self.delete_if(session_id, lambda _state: True)

    def delete_if(
        self,
        session_id: str,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
    ) -> bool:
        self.last_warning = None
        with self._lock(session_id) as state_path:
            state = self._read_path(state_path, session_id, required_fields)
            if not predicate(state):
                return False
            try:
                state_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise StateWriteError(f"治理状态删除失败：{state_path}") from exc
        return True

    def cleanup_expired_tombstones(
        self,
        session_id: str,
        *,
        now: int | None = None,
    ) -> list[tuple[str, int]]:
        current_time = _now() if now is None else now
        cutoff = current_time - int(RETENTION_SECONDS["tombstone"])

        def cleanup(state: dict[str, Any]) -> list[tuple[str, int]]:
            tombstones = state["tombstones"]
            expired: list[tuple[str, str, int]] = []
            for key, record in tombstones.items():
                if not isinstance(record, dict):
                    raise StateValidationError(f"tombstone {key} 必须是对象")
                missing = [
                    field_name
                    for field_name in ("close_reason", "closed_at")
                    if field_name not in record
                ]
                if missing:
                    raise StateValidationError(
                        f"tombstone {key} 缺少字段 {', '.join(missing)}"
                    )
                close_reason = record.get("close_reason")
                closed_at = record.get("closed_at")
                if not isinstance(close_reason, str) or not close_reason.strip():
                    raise StateValidationError(f"tombstone {key} 的 close_reason 无效")
                if isinstance(closed_at, bool) or not isinstance(closed_at, int):
                    raise StateValidationError(f"tombstone {key} 的 closed_at 无效")
                identity = _parse_tombstone_key(key)
                if identity is None:
                    raise StateValidationError(f"tombstone {key} 的身份键无效")
                task_id, attempt = identity
                if closed_at <= cutoff:
                    expired.append((str(key), task_id, attempt))
            for key, _task_id, _attempt in expired:
                tombstones.pop(key)
            return [(task_id, attempt) for _key, task_id, attempt in expired]

        return self.update(
            session_id,
            cleanup,
            required_fields=("tombstones",),
        )


class UnavailableStateStore:
    """Failing store used to preserve Hook behavior when state setup is unavailable."""

    def __init__(self, error: Exception):
        self.error = error
        self.last_warning = f"治理状态不可用，已降级放行：{error}"

    def _raise(self) -> None:
        raise OSError(str(self.error)) from self.error

    def compare_and_set(
        self,
        session_id: str,
        predicate: Callable[[dict[str, Any]], bool],
        callback: Callable[[dict[str, Any]], Any],
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
        admission: str = "existing",
    ) -> Any:
        self._raise()

    def update(
        self,
        session_id: str,
        callback: Callable[[dict[str, Any]], Any],
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
        admission: str = "existing",
    ) -> Any:
        self._raise()

    def read(
        self,
        session_id: str,
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
    ) -> dict[str, Any]:
        self._raise()

    def delete(self, session_id: str) -> None:
        self._raise()

    def delete_if(
        self,
        session_id: str,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
    ) -> bool:
        self._raise()

    def cleanup_expired_tombstones(
        self,
        session_id: str,
        *,
        now: int | None = None,
    ) -> list[tuple[str, int]]:
        self._raise()


class PreparedContractStore:
    def __init__(self, root: Path | None = None):
        target = root if root is not None else _data_root() / "prepared"
        self.root = _prepare_private_directory(target)

    def _paths(self, session_id: str, task_ref: str) -> tuple[Path, Path]:
        if len(task_ref) not in TASK_REF_LENGTHS or not re.fullmatch(r"[a-f0-9]+", task_ref):
            raise PreparedContractValidationError("task_ref 不是允许长度的小写十六进制")
        session_stem = _safe_name(session_id)
        return (
            self.root / f"{session_stem}--{task_ref}.json",
            self.root / f"{session_stem}.lock",
        )

    @contextmanager
    def _lock(self, session_id: str):
        _record_path, lock_path = self._paths(session_id, "0" * TASK_REF_LENGTHS[0])
        try:
            with locked_file(
                lock_path,
                label="PreparedContract",
                exclusive_lock=_exclusive_file_lock,
                restrict_descriptor=_restrict_descriptor,
                owned_by_current_user=_owned_by_current_user,
            ):
                yield
        except PrivateStorageError as exc:
            raise PreparedContractValidationError(str(exc)) from exc

    @staticmethod
    def _validate_record(value: Any, session_id: str, task_ref: str, path: Path) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise PreparedContractValidationError(f"PreparedContract 根节点必须是对象：{path}")
        required = (
            "session_id",
            "task_id",
            "attempt",
            "task_ref",
            "task_name",
            "resolved_mode",
            "contract",
            "contract_digest",
            "context_verification",
            "native_parameters",
            "created_at",
            "consumed",
            "tool_use_id",
            "claimed_at",
            "post_observed_at",
            "spawn_retry_count",
            "dispatch_operation",
        )
        missing = [field_name for field_name in required if field_name not in value]
        if missing:
            raise PreparedContractValidationError(
                f"PreparedContract 缺少字段 {', '.join(missing)}：{path}"
            )
        if value.get("session_id") != session_id or value.get("task_ref") != task_ref:
            raise PreparedContractValidationError(f"PreparedContract 引用与文件路径不匹配：{path}")
        if not isinstance(value.get("task_id"), str) or not value["task_id"].strip():
            raise PreparedContractValidationError(f"PreparedContract task_id 无效：{path}")
        attempt = value.get("attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise PreparedContractValidationError(f"PreparedContract attempt 无效：{path}")
        parsed = parse_task_name(value.get("task_name"))
        if parsed is None or parsed[0] != value.get("resolved_mode") or parsed[2] != task_ref:
            raise PreparedContractValidationError(f"PreparedContract task_name 无效：{path}")
        contract = value.get("contract")
        errors = validate_task_contract(contract)
        if errors:
            raise PreparedContractValidationError(
                f"PreparedContract TaskContract 无效：{'；'.join(errors)}"
            )
        if value.get("contract_digest") != contract_digest(_contract_from_input(contract)):
            raise PreparedContractValidationError(f"PreparedContract contract_digest 无效：{path}")
        context_verification_errors = _validate_context_verification_record(
            contract.get("context_manifest"),
            value.get("context_verification"),
        )
        if context_verification_errors:
            raise PreparedContractValidationError(
                "PreparedContract context_verification 无效："
                + "；".join(context_verification_errors)
                + f"：{path}"
            )
        if not isinstance(value.get("native_parameters"), dict):
            raise PreparedContractValidationError(f"PreparedContract native_parameters 无效：{path}")
        if isinstance(value.get("created_at"), bool) or not isinstance(value.get("created_at"), int):
            raise PreparedContractValidationError(f"PreparedContract created_at 无效：{path}")
        if not isinstance(value.get("consumed"), bool):
            raise PreparedContractValidationError(f"PreparedContract consumed 无效：{path}")
        for field_name in ("tool_use_id", "claimed_at", "post_observed_at"):
            field_value = value.get(field_name)
            if field_value is not None and (
                isinstance(field_value, bool)
                or not isinstance(field_value, (str, int))
                or (isinstance(field_value, str) and not field_value.strip())
            ):
                raise PreparedContractValidationError(
                    f"PreparedContract {field_name} 无效：{path}"
                )
        retry_count = value.get("spawn_retry_count")
        if isinstance(retry_count, bool) or not isinstance(retry_count, int) or not 0 <= retry_count <= 2:
            raise PreparedContractValidationError(f"PreparedContract spawn_retry_count 无效：{path}")
        if value["consumed"] and (value.get("tool_use_id") is None or value.get("claimed_at") is None):
            raise PreparedContractValidationError(f"已消费 PreparedContract 缺少 claim 字段：{path}")
        operation = value.get("dispatch_operation")
        if operation not in {"initial_spawn", "spawn_retry"}:
            raise PreparedContractValidationError(f"PreparedContract dispatch_operation 无效：{path}")
        if operation == "spawn_retry" and retry_count < 1:
            raise PreparedContractValidationError(
                f"spawn retry PreparedContract retry count 无效：{path}"
            )
        if operation == "initial_spawn" and attempt != 1:
            raise PreparedContractValidationError(
                f"initial PreparedContract attempt 必须为1：{path}"
            )
        if operation == "initial_spawn" and retry_count != 0:
            raise PreparedContractValidationError(
                f"非 retry PreparedContract retry count 必须为0：{path}"
            )
        return value

    def _read_path(self, path: Path, session_id: str, task_ref: str) -> dict[str, Any]:
        try:
            raw = read_private_bytes(
                path,
                label="PreparedContract",
                max_bytes=MAX_PREPARED_BYTES,
                owned_by_current_user=_owned_by_current_user,
                private_permissions_safe=_private_permissions_safe,
            )
        except FileNotFoundError as exc:
            raise PreparedContractValidationError(
                f"PreparedContract 不存在：session={session_id}, task_ref={task_ref}"
            ) from exc
        except PrivateStorageCapacityError as exc:
            raise PreparedContractValidationError(str(exc)) from exc
        except PrivateStorageError as exc:
            raise PreparedContractValidationError(str(exc)) from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PreparedContractValidationError(
                f"PreparedContract 不是有效 UTF-8 JSON：{path}"
            ) from exc
        return self._validate_record(value, session_id, task_ref, path)

    @staticmethod
    def _encoded(record: dict[str, Any]) -> bytes:
        try:
            raw = (json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise PreparedContractValidationError("PreparedContract 包含无法序列化的值") from exc
        if len(raw) > MAX_PREPARED_BYTES:
            raise PreparedContractValidationError("PreparedContract 超过大小上限")
        return raw

    def _write_path(self, path: Path, session_id: str, task_ref: str, record: dict[str, Any]) -> None:
        self._validate_record(record, session_id, task_ref, path)
        encoded = self._encoded(record)
        try:
            atomic_write_bytes(
                path,
                encoded,
                label="PreparedContract",
                restrict_descriptor=_restrict_descriptor,
                sync_directory=_sync_directory,
            )
        except PrivateStorageWriteError as exc:
            raise PreparedContractWriteError(str(exc)) from exc
        try:
            verified = self._read_path(path, session_id, task_ref)
        except PreparedContractError as exc:
            raise PreparedContractWriteError(
                f"PreparedContract 写入后回读失败：{path}"
            ) from exc
        if verified != record:
            raise PreparedContractWriteError(f"PreparedContract 写入后内容不一致：{path}")

    def create(self, record: dict[str, Any], *, replace: bool = False) -> None:
        session_id = str(record.get("session_id") or "")
        task_ref = str(record.get("task_ref") or "")
        path, _lock_path = self._paths(session_id, task_ref)
        with self._lock(session_id):
            if path.exists() and not replace:
                raise PreparedContractConflictError(f"PreparedContract 已存在：{task_ref}")
            self._write_path(path, session_id, task_ref, copy.deepcopy(record))

    def read(self, session_id: str, task_ref: str) -> dict[str, Any]:
        path, _lock_path = self._paths(session_id, task_ref)
        with self._lock(session_id):
            return self._read_path(path, session_id, task_ref)

    def compare_and_set(
        self,
        session_id: str,
        task_ref: str,
        predicate: Callable[[dict[str, Any]], bool],
        callback: Callable[[dict[str, Any]], Any],
    ) -> Any:
        path, _lock_path = self._paths(session_id, task_ref)
        with self._lock(session_id):
            record = self._read_path(path, session_id, task_ref)
            if not predicate(record):
                raise PreparedContractConflictError(f"PreparedContract compare-and-set 冲突：{task_ref}")
            result = callback(record)
            self._write_path(path, session_id, task_ref, record)
            return result

    def delete(self, session_id: str, task_ref: str, *, missing_ok: bool = True) -> bool:
        path, _lock_path = self._paths(session_id, task_ref)
        with self._lock(session_id):
            try:
                path.unlink()
            except FileNotFoundError:
                if missing_ok:
                    return False
                raise PreparedContractValidationError(f"PreparedContract 不存在：{task_ref}")
            except OSError as exc:
                raise PreparedContractWriteError(f"PreparedContract 删除失败：{path}") from exc
            return True

    def delete_if(
        self,
        session_id: str,
        task_ref: str,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        missing_ok: bool = True,
    ) -> bool:
        path, _lock_path = self._paths(session_id, task_ref)
        with self._lock(session_id):
            try:
                record = self._read_path(path, session_id, task_ref)
            except PreparedContractValidationError as exc:
                if missing_ok and isinstance(exc.__cause__, FileNotFoundError):
                    return False
                raise
            if not predicate(record):
                raise PreparedContractConflictError(
                    f"PreparedContract exact delete 冲突：{task_ref}"
                )
            try:
                path.unlink()
            except FileNotFoundError:
                if missing_ok:
                    return False
                raise PreparedContractValidationError(
                    f"PreparedContract 不存在：{task_ref}"
                )
            except OSError as exc:
                raise PreparedContractWriteError(
                    f"PreparedContract 删除失败：{path}"
                ) from exc
            return True

    def list_records(self, session_id: str) -> list[dict[str, Any]]:
        session_stem = _safe_name(session_id)
        with self._lock(session_id):
            records = []
            for path in sorted(self.root.glob(f"{session_stem}--*.json")):
                task_ref = path.stem.rsplit("--", 1)[-1]
                records.append(self._read_path(path, session_id, task_ref))
            return records

    def refs(self, session_id: str) -> set[str]:
        return {str(record["task_ref"]) for record in self.list_records(session_id)}

    def find_claimed(self, session_id: str, tool_use_id: str) -> dict[str, Any] | None:
        matches = [
            record
            for record in self.list_records(session_id)
            if record.get("consumed") is True and record.get("tool_use_id") == tool_use_id
        ]
        if len(matches) > 1:
            raise PreparedContractConflictError(
                f"同一 tool_use_id 映射到多个 PreparedContract：{tool_use_id}"
            )
        return matches[0] if matches else None


def _prepared_root_for_store(store: Any) -> Path:
    root = getattr(store, "root", None)
    if isinstance(root, Path):
        return (root.parent if root.name == "sessions" else root) / "prepared"
    return _data_root() / "prepared"


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
            "historical",
            None,
            "target 仅匹配已可靠关闭的 historical provenance",
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
    """Return a writable canonical task without migrating historical records."""
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
    _canonicalize_record_names(task)
    return task


def _canonicalize_record_names(task: dict[str, Any]) -> None:
    """Collapse pre-F6 names while a canonical task is already being written."""
    work_item = task.get("work_item")
    executions = task.get("executions")
    if not isinstance(work_item, dict) or not isinstance(executions, dict):
        return
    work_item.pop("created_at", None)
    work_item.pop("attempt_count", None)
    work_item.pop("last_disposition", None)
    work_item.pop("last_parent_disposition", None)
    for execution in executions.values():
        if not isinstance(execution, dict):
            continue
        pending = execution.get("pending_action")
        if isinstance(pending, dict):
            pending.pop("disposition", None)


def record_terminal_notification(
    envelope: Any,
    session_id: str,
    *,
    state_store: StateStore | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise NotificationObservationError("terminal notification envelope 必须是对象")
    required = {"sender_target", "task_id", "attempt", "terminal_status"}
    unknown = sorted(set(envelope) - required)
    missing = sorted(required - set(envelope))
    if unknown or missing:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unknown:
            details.append("unknown=" + ",".join(unknown))
        raise NotificationObservationError(
            "terminal notification envelope 字段无效：" + "；".join(details)
        )
    sender_target = envelope.get("sender_target")
    if (
        not isinstance(sender_target, str)
        or not sender_target
        or sender_target != sender_target.strip()
    ):
        raise NotificationObservationError(
            "sender_target 必须是原样非空 native Agent target"
        )
    task_id, attempt = _validate_task_identity(
        envelope.get("task_id"), envelope.get("attempt")
    )
    terminal_status = envelope.get("terminal_status")
    if terminal_status not in LIST_AGENTS_TERMINAL_STATUSES:
        raise NotificationObservationError(
            "terminal_status 必须是 completed、stopped 或 interrupted"
        )
    observed_at = _now() if now is None else now
    if isinstance(observed_at, bool) or not isinstance(observed_at, int) or observed_at < 0:
        raise NotificationObservationError("observed_at 必须是非负整数时间戳")
    store = state_store or StateStore()

    def record_notification(state: dict[str, Any]) -> dict[str, Any]:
        tasks = state.get("tasks")
        task = tasks.get(task_id) if isinstance(tasks, dict) else None
        if not isinstance(task, dict) or task.get("managed") is not True:
            raise NotificationObservationError("找不到精确 managed task")
        execution = _canonical_execution_for_attempt(task, attempt)
        if not isinstance(execution, dict):
            raise NotificationObservationError("找不到精确 managed task/attempt")
        dispatch = execution.get("dispatch_record")
        observation = execution.get("observation_record")
        closure = execution.get("closure_record")
        if not all(isinstance(item, dict) for item in (dispatch, observation, closure)):
            raise NotificationObservationError("managed execution 缺少 canonical planes")
        if dispatch.get("dispatch_target") != sender_target:
            raise NotificationObservationError("sender_target 与 dispatch target 不匹配")
        if _execution_is_closed(execution):
            return {
                "status": "historical_ignored",
                "task_id": task_id,
                "attempt": attempt,
                "terminal_status": terminal_status,
            }
        existing_status = observation.get("terminal_status")
        if (
            observation.get("observed_state") == "terminal"
            and existing_status is not None
            and existing_status != terminal_status
        ):
            closure["parent_action"] = "reconcile"
            execution["updated_at"] = observed_at
            return {
                "status": "conflict",
                "task_id": task_id,
                "attempt": attempt,
                "terminal_status": existing_status,
                "conflicting_terminal_status": terminal_status,
            }
        if (
            observation.get("source") == "terminal_notification"
            and observation.get("observed_state") == "terminal"
            and existing_status == terminal_status
            and _observation_is_bound(execution)
        ):
            return {
                "status": "idempotent",
                "task_id": task_id,
                "attempt": attempt,
                "terminal_status": terminal_status,
            }
        observation.update(
            source="terminal_notification",
            observed_state="terminal",
            observed_at=observed_at,
            terminal_status=terminal_status,
        )
        closure["parent_action"] = "decide_disposition"
        execution["updated_at"] = observed_at
        return {
            "status": "recorded",
            "task_id": task_id,
            "attempt": attempt,
            "terminal_status": terminal_status,
        }

    return store.update(session_id, record_notification)


def _attempt_interrupt_target(record: dict[str, Any]) -> str | None:
    observation = record.get("observation_record")
    dispatch = record.get("dispatch_record")
    if (
        not isinstance(observation, dict)
        or observation.get("observed_state") != "active"
        or not isinstance(dispatch, dict)
    ):
        return None
    value = dispatch.get("dispatch_target")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _running_interrupt_targets(
    records: list[tuple[int, dict[str, Any]]],
) -> list[str]:
    targets: list[str] = []
    for _attempt, record in records:
        if _execution_is_closed(record) is True:
            continue
        target = _attempt_interrupt_target(record)
        if target and target not in targets:
            targets.append(target)
    return targets


def _tombstone_record(record: dict[str, Any], reason: str, closed_at: int) -> dict[str, Any]:
    value = {
        "task_ref": record.get("task_ref"),
        "dispatch_target": _dispatch_target(record),
        "close_reason": reason,
        "closed_at": closed_at,
    }
    return {key: item for key, item in value.items() if item is not None}


def _close_attempt_record(
    state: dict[str, Any],
    task_id: str,
    attempt: int,
    record: dict[str, Any],
    reason: str,
    closed_at: int,
) -> None:
    _apply_canonical_execution_update(record, "closure_reason", reason)
    _apply_canonical_execution_update(record, "closure_closed_at", closed_at)
    _apply_canonical_execution_update(record, "closure_parent_action", None)
    record.pop("pending_action", None)
    record.pop("last_lifecycle_operation", None)
    record["updated_at"] = closed_at
    key = f"{task_id}:{attempt}"
    state.setdefault("tombstones", {})[key] = _tombstone_record(record, reason, closed_at)


def _validate_parent_disposition(value: Any) -> tuple[str, int, str, str]:
    if not isinstance(value, dict):
        raise ParentDispositionError("parent disposition 必须是对象")
    task_id_value = value.get("task_id")
    attempt_value = value.get("attempt")
    try:
        task_id, attempt = _validate_task_identity(task_id_value, attempt_value)
    except NotificationObservationError as exc:
        raise ParentDispositionError(str(exc)) from exc
    action = value.get("action")
    if action not in PARENT_DISPOSITIONS:
        raise ParentDispositionError("action 必须是 close_task")
    reason = value.get("reason")
    errors = _validate_text(reason, "reason", maximum=PARENT_DISPOSITION_REASON_MAX_LENGTH)
    if errors:
        raise ParentDispositionError("；".join(errors))
    return task_id, attempt, str(action), str(reason).strip()


def apply_parent_disposition(
    value: Any,
    session_id: str,
    *,
    state_store: StateStore | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    task_id, attempt, action, reason = _validate_parent_disposition(value)
    store = state_store or StateStore()
    current_time = _now() if now is None else now

    def apply(state: dict[str, Any]) -> dict[str, Any]:
        task = _ensure_canonical_task_record(state, task_id)
        work_item = task["work_item"]
        current_attempt = work_item.get("current_attempt")
        current = _canonical_execution_for_attempt(task, current_attempt)
        if not isinstance(current, dict):
            raise ParentDispositionConflict("work item 缺少 current execution")
        if current_attempt != attempt:
            raise ParentDispositionConflict(
                "父处置 attempt 与当前 attempt 不一致",
                current_attempt=current_attempt if isinstance(current_attempt, int) else None,
            )
        records = _task_attempt_records(state, task_id)
        running_targets = _running_interrupt_targets(records)
        if running_targets:
            raise ParentDispositionConflict(
                f"{action} 前必须先显式中断仍在运行的 attempt",
                interrupt_targets=running_targets,
                current_attempt=int(current_attempt) if isinstance(current_attempt, int) else None,
            )
        for candidate_attempt, candidate in records:
            _close_attempt_record(
                state,
                task_id,
                candidate_attempt,
                candidate,
                f"close_task:{reason}",
                current_time,
            )
        _apply_canonical_execution_update(current, "closure_parent_action", None)
        current["updated_at"] = current_time
        work_item["lifecycle"] = "tombstoned"
        return {
            "status": "closed",
            "task_id": task_id,
            "attempt": attempt,
            "interrupt_targets": [],
        }

    return store.update(session_id, apply, required_fields=("tasks", "agents", "tombstones"))


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


def _prepared_record(
    session_id: str,
    task_id: str,
    attempt: int,
    task_ref: str,
    task_name: str,
    contract: TaskContract,
    context_verification: dict[str, Any],
    spawn_args: dict[str, Any],
    *,
    created_at: int,
    spawn_retry_count: int,
    dispatch_operation: str,
) -> dict[str, Any]:
    native_parameters = {
        "task_name": task_name,
        "fork_turns": spawn_args["fork_turns"],
        "model": spawn_args.get("model"),
        "reasoning_effort": spawn_args.get("reasoning_effort"),
    }
    return {
        "session_id": session_id,
        "task_id": task_id,
        "attempt": attempt,
        "task_ref": task_ref,
        "task_name": task_name,
        "resolved_mode": contract.resolved_mode,
        "contract": contract.to_record(),
        "contract_digest": contract_digest(contract),
        "context_verification": copy.deepcopy(context_verification),
        "native_parameters": native_parameters,
        "created_at": created_at,
        "consumed": False,
        "tool_use_id": None,
        "claimed_at": None,
        "post_observed_at": None,
        "spawn_retry_count": spawn_retry_count,
        "dispatch_operation": dispatch_operation,
    }


def _contract_summary(contract: TaskContract) -> dict[str, Any]:
    return {
        "objective": contract.objective,
        "model": contract.model,
    }


def contract_digest(contract: TaskContract) -> str:
    encoded = json.dumps(
        contract.to_record(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
    active_state_store = state_store or StateStore()
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
        active_prepared_store.create(prepared)
        active_state_store.compare_and_set(
            session_id,
            lambda state: task_id not in state["tasks"] and not _task_ref_occupied(state, task_ref),
            lambda state: state["tasks"].update({task_id: copy.deepcopy(initial)}),
            required_fields=("tasks", "tombstones"),
            admission="new_task",
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
    active_state_store = state_store or StateStore()
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
        active_prepared_store.create(prepared, replace=True)
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

        active_state_store.update(
            session_id,
            validate_retry_state,
            required_fields=("tasks", "tombstones"),
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
            active_prepared_store.delete(session_id, task_ref, missing_ok=False)
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
                prepared_store.delete(session_id, task_ref)
                expired += 1
            continue
        claimed_at = prepared.get("claimed_at")
        if (
            isinstance(claimed_at, int)
            and prepared.get("post_observed_at") is None
            and claimed_at <= current_time - int(RETENTION_SECONDS["claimed_reconcile"])
        ):
            tool_use_id = prepared.get("tool_use_id")

            def predicate(state: dict[str, Any]) -> bool:
                record = _task_record_for_attempt(state, task_id, attempt)
                return bool(
                    record
                    and record.get("task_ref") == task_ref
                    and _dispatch_tool_use_id(record) == tool_use_id
                    and _spawn_observation(record) is None
                )

            def mark_unknown(state: dict[str, Any]) -> None:
                _ensure_canonical_task_record(state, task_id)
                record = _task_record_for_attempt(state, task_id, attempt)
                assert record is not None
                _apply_canonical_execution_update(record, "dispatch_response", "unknown")
                _apply_canonical_execution_update(record, "observed_execution_status", "not_started")
                _apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
                record["updated_at"] = current_time

            try:
                state_store.compare_and_set(session_id, predicate, mark_unknown)
            except StateConflictError:
                continue
            prepared_store.compare_and_set(
                session_id,
                task_ref,
                lambda value: value.get("tool_use_id") == tool_use_id,
                lambda value: value.update({"post_observed_at": current_time}),
            )
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


def _event_now(payload: dict[str, Any]) -> int:
    supplied = payload.get("now")
    if isinstance(supplied, int) and not isinstance(supplied, bool):
        return supplied
    return _now()


def _communication_fields(value: Any, *, interrupt: bool = False) -> tuple[str, dict[str, str]]:
    if not isinstance(value, dict):
        raise CommunicationPreparationError("通信输入必须是对象")
    target_value = value.get("target")
    if not isinstance(target_value, str) or not target_value.strip():
        raise CommunicationPreparationError("字段 target 必须是非空字符串")
    target = target_value.strip()
    if interrupt:
        return target, {}
    fields: dict[str, str] = {}
    for field_name, label in COMMUNICATION_FIELD_LABELS:
        field_value = value.get(field_name)
        if not isinstance(field_value, str) or not field_value.strip():
            raise CommunicationPreparationError(f"缺少字段 {field_name}（{label}）")
        normalized = " ".join(field_value.split())
        if len(normalized) > MAX_CONTRACT_TEXT:
            raise CommunicationPreparationError(
                f"字段 {field_name}（{label}）长度不能超过 {MAX_CONTRACT_TEXT} 个字符"
            )
        fields[field_name] = normalized
    if not interrupt and value.get("operation_type") not in OPERATION_TYPES:
        raise CommunicationPreparationError(
            "operation_type 必须是 normal_message、platform_recovery 或 business_resume"
        )
    return target, fields


def render_communication_user_message(
    target: str, fields: dict[str, str], *, interrupt: bool = False
) -> str:
    if interrupt:
        return "\n".join(("【子 Agent 中断】", f"对象：{target}"))
    return "\n".join(
        (
            "【子 Agent 通信】",
            f"对象：{target}",
            f"目的：{fields['purpose']}",
            f"原因：{fields['reason']}",
            f"期望结果：{fields['expected_result']}",
        )
    )


def render_communication_message(
    fields: dict[str, str],
    operation_type: str,
    *,
    resume_contract: TaskContract | None = None,
    resume_context_verification: dict[str, Any] | None = None,
) -> str:
    lines = [
        f"【通信目的】{fields['purpose']}",
        f"【通信原因】{fields['reason']}",
        f"【具体内容】{fields['content']}",
    ]
    if operation_type == "business_resume":
        if resume_contract is None:
            raise CommunicationPreparationError("business_resume 缺少重新验证的 TaskContract")
        if resume_context_verification is None:
            raise CommunicationPreparationError("business_resume 缺少必需上下文验证")
        lines.extend(
            (
                "【继续执行目标】",
                resume_contract.objective,
                "【工作范围】",
                _render_list(resume_contract.work_scope),
                "【禁止范围】",
                _render_list(resume_contract.forbidden_scope),
                "【完成条件】",
                _render_list(resume_contract.completion_conditions),
                "【验收证据】",
                _render_list(resume_contract.evidence_requirements),
                "【必需上下文】",
                _render_verified_context(resume_context_verification),
            )
        )
    lines.append(f"【期望结果】{fields['expected_result']}")
    return "\n".join(lines)


def _pending_action_matches_target(
    state: dict[str, Any], target: str
) -> list[tuple[str, int, dict[str, Any], dict[str, Any]]]:
    matches = []
    for task_id, attempt, record in _iter_task_attempts(state):
        pending = record.get("pending_action")
        if isinstance(pending, dict) and pending.get("target") == target:
            matches.append((task_id, attempt, record, pending))
    return matches


def _pending_action_matches_exact(
    state: dict[str, Any],
    target: str,
    task_id: str,
    attempt: int,
    expected_pending: dict[str, Any],
) -> bool:
    matches = _pending_action_matches_target(state, target)
    if len(matches) != 1:
        return False
    matched_task_id, matched_attempt, _record, pending = matches[0]
    return bool(
        matched_task_id == task_id
        and matched_attempt == attempt
        and pending == expected_pending
    )


def _claimed_action_for_tool_use(
    state: dict[str, Any], tool_use_id: str
) -> tuple[str, int, dict[str, Any], dict[str, Any]] | None:
    matches = []
    for task_id, attempt, record in _iter_task_attempts(state):
        pending = record.get("pending_action")
        if (
            isinstance(pending, dict)
            and pending.get("phase") == "claimed"
            and pending.get("tool_use_id") == tool_use_id
        ):
            matches.append((task_id, attempt, record, pending))
    if len(matches) > 1:
        raise StateConflictError(f"同一 tool_use_id 映射到多个 pending_action：{tool_use_id}")
    return matches[0] if matches else None


def _has_unresolved_lifecycle(record: dict[str, Any]) -> bool:
    last = record.get("last_lifecycle_operation")
    return isinstance(last, dict) and last.get("call_observation") in {"success", "unknown"}


def _pending_action_record(
    *,
    target: str,
    attempt: int,
    task_ref: str,
    operation_type: str,
    created_at: int,
    authorized_recovery: bool = False,
    resume_contract: TaskContract | None = None,
    resume_context_verification: dict[str, Any] | None = None,
    prepared_on_attempt: int | None = None,
) -> dict[str, Any]:
    pending: dict[str, Any] = {
        "target": target,
        "attempt": attempt,
        "task_ref": task_ref,
        "operation_type": operation_type,
        "phase": "prepared",
        "created_at": created_at,
        "tool_use_id": None,
        "claimed_at": None,
    }
    if authorized_recovery:
        pending["authorized_recovery"] = True
    if resume_contract is not None:
        pending["resume_contract"] = resume_contract.to_record()
        pending["resume_context_verification"] = copy.deepcopy(
            resume_context_verification
        )
        pending["prepared_on_attempt"] = prepared_on_attempt
    return pending


def _occupied_attempt_refs(state: dict[str, Any]) -> set[str]:
    occupied = {
        str(record["task_ref"])
        for _task_id, _attempt, record in _iter_task_attempts(state)
        if isinstance(record.get("task_ref"), str)
    }
    tombstones = state.get("tombstones")
    if isinstance(tombstones, dict):
        occupied.update(
            str(record["task_ref"])
            for record in tombstones.values()
            if isinstance(record, dict) and isinstance(record.get("task_ref"), str)
        )
    return occupied


def _business_resume_allowed(record: dict[str, Any]) -> bool:
    if (
        _execution_close_reason(record) == "resume_delivery_failed"
        and _parent_action(record) == "decide_disposition"
    ):
        return True
    observation = record.get("observation_record")
    return bool(
        _execution_is_closed(record) is not True
        and _parent_action(record) == "decide_disposition"
        and isinstance(observation, dict)
        and observation.get("source") == "terminal_notification"
        and observation.get("observed_state") == "terminal"
        and _observation_is_bound(record)
    )


def _native_tool_for_operation(operation_type: str) -> str:
    native_tool = OPERATION_NATIVE_TOOLS.get(operation_type)
    if not isinstance(native_tool, str) or not native_tool:
        raise CommunicationPreparationError(
            f"operation type 缺少原生工具映射：{operation_type}"
        )
    return native_tool


def _degraded_managed_action_result(
    *,
    target: str,
    fields: dict[str, Any],
    operation_type: str,
    native_tool: str,
    interrupt: bool,
    exc: Exception,
    detail: str,
) -> dict[str, Any]:
    message = "" if interrupt else render_communication_message(
        fields, "normal_message"
    )
    native_args = (
        {"target": target}
        if interrupt
        else {"target": target, "message": message}
    )
    return {
        "managed": False,
        "target": target,
        "operation_type": operation_type,
        "user_message": render_communication_user_message(
            target, fields, interrupt=interrupt
        ),
        "message": message,
        "native_args": native_args,
        "native_tool": native_tool,
        "degraded_warning": f"{detail}（unavailable）：{exc}",
    }


def _resolve_managed_action_attempt(
    value: dict[str, Any],
    state: dict[str, Any],
    *,
    target: str,
    task_id: str,
    attempt: int,
    record: dict[str, Any],
    operation_type: str,
    interrupt: bool,
    authorized_recovery: bool,
) -> tuple[int, dict[str, Any], int, str, TaskContract | None, bool]:
    task_current = state.get("tasks", {}).get(task_id)
    current_work_item = (
        task_current.get("work_item") if isinstance(task_current, dict) else None
    )
    current_attempt = (
        current_work_item.get("current_attempt")
        if isinstance(current_work_item, dict)
        else None
    )
    current_execution = (
        _canonical_execution_for_attempt(task_current, current_attempt)
        if isinstance(task_current, dict)
        and isinstance(current_attempt, int)
        and not isinstance(current_attempt, bool)
        else None
    )
    if (
        operation_type == "business_resume"
        and isinstance(task_current, dict)
        and isinstance(current_attempt, int)
        and current_attempt > attempt
        and isinstance(current_execution, dict)
        and _execution_close_reason(current_execution) != "resume_delivery_failed"
    ):
        raise CommunicationPreparationError(
            "前一 same-Agent business_resume attempt 仍未解决；unknown 替代执行必须使用新 spawn/new Agent"
        )
    if (
        operation_type == "business_resume"
        and isinstance(task_current, dict)
        and isinstance(current_attempt, int)
        and current_attempt > attempt
        and isinstance(current_execution, dict)
        and _execution_close_reason(current_execution) == "resume_delivery_failed"
    ):
        attempt = current_attempt
        record = current_execution
    if _pending_action_matches_target(state, target):
        raise CommunicationPreparationError(f"目标 {target} 已存在 pending_action")
    if not interrupt and operation_type == "normal_message" and _platform_observation(record) == "error":
        raise CommunicationPreparationError(
            "normal_message 不能绕过 platform_observation=error 的平台恢复流程"
        )
    if operation_type in LIFECYCLE_OPERATION_TYPES and _has_unresolved_lifecycle(record):
        raise CommunicationPreparationError(
            "当前 attempt 仍有 success/unknown lifecycle operation 待启动或人工对账"
        )
    resume_contract = None
    desired_attempt = attempt
    desired_task_ref = str(record.get("task_ref") or "")
    authorized_second_recovery = False
    if operation_type == "platform_recovery":
        observation_state = record.get("observation_record", {}).get("observed_state")
        if observation_state != "error":
            raise CommunicationPreparationError(
                "platform_recovery 只适用于 observation=error 的同一 attempt"
            )
        recovery_count = record.get("recovery_count")
        parent_action = _parent_action(record)
        if recovery_count == 0 and parent_action == "recover" and not authorized_recovery:
            pass
        elif recovery_count == 1 and parent_action == "ask_user" and authorized_recovery:
            authorized_second_recovery = True
        elif recovery_count == 1 and parent_action == "ask_user":
            raise CommunicationPreparationError("最后一次平台恢复需要用户明确授权")
        else:
            raise CommunicationPreparationError("当前 Agent/attempt 的平台恢复次数已经耗尽或状态不兼容")
    elif operation_type == "business_resume":
        if (
            record.get("observation_record", {}).get("observed_state") == "active"
            or not _business_resume_allowed(record)
        ):
            raise CommunicationPreparationError("当前 attempt 不满足 business_resume 的机械前置条件")
        if _parent_action(record) != "decide_disposition":
            raise CommunicationPreparationError("business_resume 必须以 decide_disposition 为前置处置闸门")
        raw_contract = value.get("task_contract")
        try:
            resume_contract = _contract_from_input(raw_contract)
        except (TypeError, ValueError) as exc:
            raise CommunicationPreparationError(f"business_resume TaskContract 无效：{exc}") from exc
        old_summary = record.get("contract_summary")
        old_model = old_summary.get("model") if isinstance(old_summary, dict) else None
        if resume_contract.model != old_model:
            raise CommunicationPreparationError(
                "同 Agent business_resume 不能改变 model；需要换模型时必须使用新 spawn"
            )
        desired_attempt = attempt + 1
        desired_task_ref = select_task_ref(task_id, desired_attempt, _occupied_attempt_refs(state)) or ""
        if not desired_task_ref:
            raise CommunicationPreparationError("新 attempt 无法取得唯一 task_ref")
    elif interrupt:
        if _execution_status(record) == "interrupted" or _execution_is_closed(record) is True:
            raise CommunicationPreparationError("当前 attempt 已中断或关闭，不能重复创建中断意图")
    return (
        attempt,
        record,
        desired_attempt,
        desired_task_ref,
        resume_contract,
        authorized_second_recovery,
    )


def _persist_managed_action(
    session_id: str,
    *,
    state_store: StateStore,
    target: str,
    fields: dict[str, Any],
    operation_type: str,
    native_tool: str,
    interrupt: bool,
    task_id: str,
    attempt: int,
    record: dict[str, Any],
    pending_owner_attempt: int,
    pending_owner_record: dict[str, Any],
    desired_attempt: int,
    desired_task_ref: str,
    resume_contract: TaskContract | None,
    authorized_second_recovery: bool,
    now: int,
) -> dict[str, Any]:
    resume_context_verification = None
    if resume_contract is not None:
        try:
            resume_context_verification = verify_context_manifest(
                resume_contract.context_manifest
            )
        except ContextVerificationError as exc:
            raise CommunicationPreparationError(
                f"business_resume 必需上下文验证失败：{exc}"
            ) from exc
    pending = _pending_action_record(
        target=target,
        attempt=desired_attempt,
        task_ref=desired_task_ref,
        operation_type=operation_type,
        created_at=now,
        authorized_recovery=authorized_second_recovery,
        resume_contract=resume_contract,
        resume_context_verification=resume_context_verification,
        prepared_on_attempt=attempt if resume_contract else None,
    )
    def predicate(current: dict[str, Any]) -> bool:
        current_admission = _managed_target_admission(current, target)
        current_mapped = current_admission.candidate
        if current_admission.disposition != "managed" or current_mapped is None:
            return False
        if current_mapped[:2] != (task_id, pending_owner_attempt):
            return False
        if _pending_action_matches_target(current, target):
            return False
        current_record = _task_record_for_attempt(current, task_id, attempt)
        current_owner = _task_record_for_attempt(
            current, task_id, pending_owner_attempt
        )
        return bool(
            isinstance(current_record, dict)
            and current_record.get("updated_at") == record.get("updated_at")
            and isinstance(current_owner, dict)
            and current_owner.get("updated_at")
            == pending_owner_record.get("updated_at")
        )

    def create(current: dict[str, Any]) -> None:
        current_admission = _managed_target_admission(current, target)
        if (
            current_admission.disposition != "managed"
            or current_admission.candidate is None
            or current_admission.candidate[:2]
            != (task_id, pending_owner_attempt)
        ):
            raise StateConflictError("target lifecycle admission 在锁内发生变化")
        _repair_managed_target_index(current, target, current_admission)
        current_record = _task_record_for_attempt(
            current, task_id, pending_owner_attempt
        )
        assert current_record is not None
        current_record["pending_action"] = copy.deepcopy(pending)
        current_record["updated_at"] = now

    try:
        state_store.compare_and_set(session_id, predicate, create)
    except StateConflictError as exc:
        raise CommunicationPreparationError(
            f"{operation_type} target admission 已变化，必须重新生成或对账：{exc}"
        ) from exc
    except Exception as exc:
        failure_category = _state_store_exception_category(exc, during_read=False)
        if failure_category == "unavailable" and (
            interrupt or operation_type == "normal_message"
        ):
            return _degraded_managed_action_result(
                target=target,
                fields=fields,
                operation_type=operation_type,
                native_tool=native_tool,
                interrupt=interrupt,
                detail="pending_action 无法可靠创建，本次操作未纳入治理",
                exc=exc,
            )
        raise CommunicationPreparationError(
            f"{operation_type} pending_action 无法原子创建"
            f"（{failure_category}）：{exc}"
        ) from exc
    message = "" if interrupt else render_communication_message(
        fields,
        operation_type,
        resume_contract=resume_contract,
        resume_context_verification=resume_context_verification,
    )
    return {
        "managed": True,
        "task_id": task_id,
        "attempt": desired_attempt,
        "task_ref": desired_task_ref,
        "target": target,
        "operation_type": operation_type,
        "user_message": render_communication_user_message(
            target, fields, interrupt=interrupt
        ),
        "message": message,
        "native_args": (
            {"target": target}
            if interrupt
            else {"target": target, "message": message}
        ),
        "native_tool": native_tool,
    }


def _prepare_managed_action(
    value: dict[str, Any],
    session_id: str,
    *,
    state_store: StateStore,
    interrupt: bool,
    authorized_recovery: bool,
    now: int,
) -> dict[str, Any]:
    target, fields = _communication_fields(value, interrupt=interrupt)
    operation_type = "interrupt" if interrupt else str(value["operation_type"])
    native_tool = _native_tool_for_operation(operation_type)

    try:
        reconcile_pending_actions(session_id, state_store=state_store, now=now)
        state = state_store.read(session_id)
    except Exception as exc:
        failure_category = _state_store_exception_category(exc, during_read=True)
        if failure_category == "unavailable" and (
            interrupt or operation_type == "normal_message"
        ):
            return _degraded_managed_action_result(
                target=target,
                fields=fields,
                operation_type=operation_type,
                native_tool=native_tool,
                interrupt=interrupt,
                exc=exc,
                detail="治理状态不可用，本次操作未可靠记录",
            )
        raise CommunicationPreparationError(
            f"{operation_type} StateStore 前置读取或对账失败"
            f"（{failure_category}）：{exc}"
        ) from exc
    admission = _managed_target_admission(state, target)
    if admission.disposition == "reconcile":
        raise CommunicationPreparationError(
            f"目标 {target} 的 managed lifecycle identity 需要对账：{admission.reason}"
        )
    if admission.disposition == "historical":
        raise CommunicationPreparationError(
            f"目标 {target} 仅匹配已可靠关闭的 historical provenance；"
            "不能复活 active index 或按 unmanaged 放行"
        )
    if admission.disposition != "managed" or admission.candidate is None:
        resume_contract = None
        resume_context_verification = None
        if operation_type == "business_resume":
            try:
                resume_contract = _contract_from_input(value.get("task_contract"))
                resume_context_verification = verify_context_manifest(
                    resume_contract.context_manifest
                )
            except (ContextVerificationError, TypeError, ValueError) as exc:
                raise CommunicationPreparationError(
                    f"business_resume TaskContract 无效：{exc}"
                ) from exc
        message = "" if interrupt else render_communication_message(
            fields,
            operation_type,
            resume_contract=resume_contract,
            resume_context_verification=resume_context_verification,
        )
        native_args = (
            {"target": target}
            if interrupt
            else {"target": target, "message": message}
        )
        return {
            "managed": False,
            "target": target,
            "operation_type": operation_type,
            "user_message": render_communication_user_message(
                target, fields, interrupt=interrupt
            ),
            "message": "" if interrupt else message,
            "native_args": native_args,
            "native_tool": native_tool,
            "degraded_warning": "通信目标没有 canonical provenance；按原生 unmanaged 路径处理。",
        }

    task_id, attempt, record = admission.candidate
    pending_owner_attempt = attempt
    pending_owner_record = record
    (
        attempt,
        record,
        desired_attempt,
        desired_task_ref,
        resume_contract,
        authorized_second_recovery,
    ) = _resolve_managed_action_attempt(
        value,
        state,
        target=target,
        task_id=task_id,
        attempt=attempt,
        record=record,
        operation_type=operation_type,
        interrupt=interrupt,
        authorized_recovery=authorized_recovery,
    )
    return _persist_managed_action(
        session_id,
        state_store=state_store,
        target=target,
        fields=fields,
        operation_type=operation_type,
        native_tool=native_tool,
        interrupt=interrupt,
        task_id=task_id,
        attempt=attempt,
        record=record,
        pending_owner_attempt=pending_owner_attempt,
        pending_owner_record=pending_owner_record,
        desired_attempt=desired_attempt,
        desired_task_ref=desired_task_ref,
        resume_contract=resume_contract,
        authorized_second_recovery=authorized_second_recovery,
        now=now,
    )


def prepare_communication(
    value: dict[str, Any],
    session_id: str,
    *,
    authorized_recovery: bool = False,
    state_store: StateStore | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    return _prepare_managed_action(
        value,
        session_id,
        state_store=state_store or StateStore(),
        interrupt=False,
        authorized_recovery=authorized_recovery,
        now=_now() if now is None else now,
    )


def prepare_interrupt(
    value: dict[str, Any],
    session_id: str,
    *,
    state_store: StateStore | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    return _prepare_managed_action(
        value,
        session_id,
        state_store=state_store or StateStore(),
        interrupt=True,
        authorized_recovery=False,
        now=_now() if now is None else now,
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


def _last_lifecycle_from_pending(
    pending: dict[str, Any], observation: dict[str, str | None]
) -> dict[str, Any]:
    value = {
        "operation_type": pending["operation_type"],
        "tool_use_id": pending.get("tool_use_id"),
        "call_observation": observation["call_observation"],
    }
    target_observation = observation.get("target_observation")
    if isinstance(target_observation, str) and target_observation:
        value["target_observation"] = target_observation
    return value


def _interrupt_not_found_confirms_inactive(
    record: dict[str, Any], pending: dict[str, Any]
) -> bool:
    target = pending.get("target")
    canonical_observation = record.get("observation_record")
    return bool(
        _identity_status(record) == "confirmed"
        and _spawn_observation(record) == "success"
        and isinstance(target, str)
        and target
        and _record_has_target_provenance(record, target)
        and isinstance(canonical_observation, dict)
        and canonical_observation.get("observed_state") == "absent_at_check"
        and canonical_observation.get("source") == "list_agents"
    )


def _legacy_call_observation(value: Any) -> dict[str, str | None]:
    observation = value if isinstance(value, str) else "unknown"
    if observation not in CALL_OBSERVATIONS:
        observation = "unknown"
    return {
        "call_observation": observation,
        "target_observation": None,
    }


def _apply_action_observation(
    record: dict[str, Any],
    pending: dict[str, Any],
    observation: dict[str, str | None],
    observed_at: int,
) -> None:
    operation_type = str(pending["operation_type"])
    call_observation = str(observation["call_observation"])
    target_observation = observation.get("target_observation")
    record.pop("pending_action", None)
    if operation_type == "normal_message":
        record["updated_at"] = observed_at
        return
    lifecycle = _last_lifecycle_from_pending(pending, observation)
    if operation_type == "platform_recovery":
        _apply_canonical_execution_update(record, "observed_execution_status", "stopped")
        _apply_canonical_execution_update(record, "observed_platform_state", "error")
        record["last_lifecycle_operation"] = lifecycle
        if call_observation == "success":
            _apply_canonical_execution_update(record, "closure_parent_action", "wait")
        elif call_observation == "unknown":
            _apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
        else:
            _apply_canonical_execution_update(record, "closure_parent_action", "ask_user")
    elif operation_type == "business_resume":
        if call_observation == "success":
            _apply_canonical_execution_update(record, "observed_execution_status", "not_started")
            _apply_canonical_execution_update(record, "closure_parent_action", "wait")
            record["last_lifecycle_operation"] = lifecycle
        elif call_observation == "unknown":
            _apply_canonical_execution_update(record, "observed_execution_status", "not_started")
            _apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
            record["last_lifecycle_operation"] = lifecycle
        else:
            _apply_canonical_execution_update(record, "observed_execution_status", "stopped")
            _apply_canonical_execution_update(record, "closure_reason", "resume_delivery_failed")
            _apply_canonical_execution_update(record, "closure_closed_at", observed_at)
            _apply_canonical_execution_update(record, "closure_parent_action", "decide_disposition")
            record.pop("last_lifecycle_operation", None)
    elif operation_type == "interrupt":
        terminal_status = (
            "interrupted"
            if target_observation in {"interrupted", "cancelled", "canceled"}
            else "stopped"
        )
        confirmed_inactive = target_observation in {
            "interrupted",
            "cancelled",
            "canceled",
            "stopped",
            "completed",
        } or (
            target_observation == "not_found"
            and _interrupt_not_found_confirms_inactive(record, pending)
        )
        if call_observation == "success" and confirmed_inactive:
            _apply_canonical_execution_update(record, "observed_execution_status", terminal_status)
            _apply_canonical_execution_update(record, "observation_observed_at", observed_at)
            _apply_canonical_execution_update(record, "observation_source", "session")
            _apply_canonical_execution_update(record, "closure_parent_action", "decide_disposition")
            record.pop("last_lifecycle_operation", None)
        elif call_observation in {"success", "unknown"}:
            record["last_lifecycle_operation"] = lifecycle
            _apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
        else:
            record["last_lifecycle_operation"] = lifecycle
    record["updated_at"] = observed_at


def reconcile_interrupted_attempt(
    value: Any,
    session_id: str,
    *,
    state_store: StateStore | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReconciliationError("reconciliation observation 必须是对象")
    required = {
        "task_id",
        "attempt",
    }
    unknown = sorted(set(value) - required)
    missing = sorted(required - set(value))
    if unknown or missing:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unknown:
            details.append("unknown=" + ",".join(unknown))
        raise ReconciliationError(
            "reconciliation observation 字段无效：" + "；".join(details)
        )
    try:
        task_id, attempt = _validate_task_identity(
            value.get("task_id"), value.get("attempt")
        )
    except NotificationObservationError as exc:
        raise ReconciliationError(str(exc)) from exc
    store = state_store or StateStore()
    observed_at = _now() if now is None else now

    def apply(state: dict[str, Any]) -> dict[str, Any]:
        _ensure_canonical_task_record(state, task_id)
        record = _task_record_for_attempt(state, task_id, attempt)
        if not isinstance(record, dict):
            raise ReconciliationError("找不到精确 managed task/attempt")
        if _identity_status(record) != "confirmed":
            raise ReconciliationError("attempt 身份尚未确认")
        if _spawn_observation(record) != "success":
            raise ReconciliationError("attempt 缺少成功派发先验")
        observed_state = record.get("observation_record", {}).get("observed_state")
        if observed_state not in {"active", "absent_at_check", "unknown"}:
            raise ReconciliationError("受控重启收口缺少可对账的 execution observation")
        target = record.get("dispatch_record", {}).get("dispatch_target")
        if not isinstance(target, str) or not target.startswith("/"):
            raise ReconciliationError("attempt 缺少已保存的精确 canonical target")
        if not (
            _platform_observation(record) == "unknown"
            and _observation_source(record) == "list_agents"
            and isinstance(_observation_checked_at(record), int)
        ):
            raise ReconciliationError("attempt 缺少既有 list_agents unknown 对账先验")
        mapped = _managed_target_attempt(state, target)
        if mapped is None or mapped[:2] != (task_id, attempt):
            raise ReconciliationError("target 没有精确映射到当前 task/attempt")
        lifecycle = record.get("last_lifecycle_operation")
        if not (
            isinstance(lifecycle, dict)
            and lifecycle.get("operation_type") == "interrupt"
            and isinstance(lifecycle.get("tool_use_id"), str)
            and bool(lifecycle.get("tool_use_id", "").strip())
            and (
                (
                    lifecycle.get("call_observation") == "success"
                    and lifecycle.get("target_observation") == "not_found"
                )
                or (
                    lifecycle.get("call_observation") == "unknown"
                    and lifecycle.get("target_observation") is None
                )
            )
        ):
            raise ReconciliationError("缺少与本次事实精确匹配的已认领 interrupt 记录")
        _apply_canonical_execution_update(record, "observed_execution_status", "interrupted")
        _apply_canonical_execution_update(record, "observation_observed_at", observed_at)
        _apply_canonical_execution_update(record, "observation_source", "session")
        _apply_canonical_execution_update(record, "closure_parent_action", "decide_disposition")
        record.pop("last_lifecycle_operation", None)
        record["updated_at"] = observed_at
        return {
            "status": "confirmed_inactive",
            "task_id": task_id,
            "attempt": attempt,
            "target": target,
            "execution_status": "interrupted",
            "parent_action": "decide_disposition",
        }

    return store.update(session_id, apply)


def reconcile_pending_actions(
    session_id: str,
    *,
    state_store: StateStore,
    now: int | None = None,
) -> dict[str, int]:
    current_time = _now() if now is None else now
    counts = {"expired": 0, "reconciled": 0}

    def reconcile(state: dict[str, Any]) -> None:
        pending_task_ids = {
            task_id
            for task_id, _attempt, record in _iter_task_attempts(state)
            if isinstance(record.get("pending_action"), dict)
        }
        for task_id in pending_task_ids:
            _ensure_canonical_task_record(state, task_id)
        for _task_id, _attempt, record in _iter_task_attempts(state):
            pending = record.get("pending_action")
            if not isinstance(pending, dict):
                continue
            if pending.get("phase") == "prepared":
                created_at = pending.get("created_at")
                if (
                    isinstance(created_at, int)
                    and not isinstance(created_at, bool)
                    and created_at
                    <= current_time - int(RETENTION_SECONDS["prepared_unclaimed"])
                ):
                    record.pop("pending_action", None)
                    record["updated_at"] = current_time
                    counts["expired"] += 1
                continue
            claimed_at = pending.get("claimed_at")
            if (
                pending.get("phase") == "claimed"
                and isinstance(claimed_at, int)
                and claimed_at <= current_time - int(RETENTION_SECONDS["claimed_reconcile"])
            ):
                _apply_action_observation(
                    record,
                    copy.deepcopy(pending),
                    _legacy_call_observation("unknown"),
                    current_time,
                )
                counts["reconciled"] += 1

    state_store.update(session_id, reconcile)
    return counts


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
            "Subagent Governance：无治理前缀，本次原生 spawn 按 unmanaged 兼容放行；不创建治理状态。",
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
            prepared_store.delete(session_id, task_ref)
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
    claim_snapshot: dict[str, Any] = {}
    try:
        claimed_prepared = _claim_prepared_spawn_contract(
            session_id,
            task_ref,
            tool_use_id,
            current_time,
            prepared,
            prepared_store,
        )

        def claim(current: dict[str, Any]) -> None:
            claim_snapshot["callback_entered"] = True
            task = _ensure_canonical_task_record(current, task_id)
            target = _task_record_for_attempt(current, task_id, attempt)
            if (
                target is None
                or target.get("task_ref") != task_ref
                or target.get("task_name") != task_name
                or target.get("resolved_mode") != mode
            ):
                raise StateConflictError(
                    "StateStore 中不存在匹配的 task/attempt/task_ref"
                )
            admission_error = _dispatch_admission_error(task, attempt)
            if admission_error:
                raise StateConflictError(admission_error)
            claim_snapshot["before_task"] = copy.deepcopy(task)

            if dispatch_operation == "spawn_retry":
                if not (
                    _spawn_observation(target) == "failed"
                    and _identity_status(target) == "unconfirmed"
                    and _dispatch_reliably_not_created(target)
                    and target.get("spawn_retry_count") == desired_retry_count - 1
                ):
                    raise StateConflictError("spawn retry 状态或计数不匹配")
            elif dispatch_operation == "initial_spawn":
                if (
                    _spawn_observation(target) is not None
                    or target.get("spawn_retry_count") != 0
                ):
                    raise StateConflictError("初始 spawn 状态已变化")
            else:
                raise StateConflictError(
                    f"未知 dispatch operation：{dispatch_operation}"
                )
            _apply_canonical_execution_update(target, "dispatch_tool_use_id", tool_use_id)
            target["spawn_retry_count"] = desired_retry_count
            _apply_canonical_execution_update(target, "dispatch_response", None)
            _apply_canonical_execution_update(
                target,
                "closure_parent_action",
                "retry_spawn" if dispatch_operation == "spawn_retry" else None,
            )
            target["updated_at"] = current_time
            claim_snapshot["claimed_task"] = copy.deepcopy(task)

        try:
            pre_update_state = store.read(
                session_id, required_fields=("tasks", "tombstones")
            )
            pre_update_task = pre_update_state.get("tasks", {}).get(task_id)
            if not isinstance(pre_update_task, dict):
                raise StateConflictError("StateStore 中不存在匹配的 claim task")
            claim_snapshot["pre_update_task"] = copy.deepcopy(pre_update_task)
            store.update(
                session_id,
                claim,
                required_fields=("tasks", "tombstones"),
            )
        except Exception as claim_exc:
            rollback_errors: list[str] = []
            claim_recovery = "not_observed"
            try:
                claim_recovery = _rollback_persisted_spawn_claim(
                    session_id, task_id, store, claim_snapshot
                )
                if claim_recovery == "not_observed":
                    expected_pre_update = claim_snapshot.get("pre_update_task")
                    current_state = store.read(
                        session_id, required_fields=("tasks", "tombstones")
                    )
                    if (
                        not isinstance(expected_pre_update, dict)
                        or current_state.get("tasks", {}).get(task_id)
                        != expected_pre_update
                    ):
                        raise StateConflictError(
                            "spawn claim 失败后 StateStore 已发生并发变化，无法安全恢复凭证"
                        )
            except Exception as rollback_exc:
                rollback_errors.append(f"StateStore claim 回滚失败：{rollback_exc}")
            if not rollback_errors:
                try:
                    _restore_prepared_spawn_claim(
                        session_id,
                        task_ref,
                        prepared_store,
                        prepared,
                        claimed_prepared,
                    )
                except Exception as rollback_exc:
                    rollback_errors.append(f"PreparedContract unclaim 失败：{rollback_exc}")
            reusable_prepared = claim_recovery in {"restored", "not_persisted"} or (
                claim_recovery == "not_observed"
                and claim_snapshot.get("callback_entered") is not True
            )
            if not rollback_errors and reusable_prepared:
                raise claim_exc
            if not rollback_errors and dispatch_operation == "spawn_retry":
                try:
                    prepared_store.delete(session_id, task_ref, missing_ok=False)
                except Exception as rollback_exc:
                    rollback_errors.append(
                        f"spawn retry PreparedContract 回滚失败：{rollback_exc}"
                    )
            elif not rollback_errors and dispatch_operation == "initial_spawn":
                try:
                    prepared_store.delete(session_id, task_ref, missing_ok=False)
                except Exception as rollback_exc:
                    rollback_errors.append(
                        f"initial PreparedContract 回滚失败：{rollback_exc}"
                    )
            if rollback_errors:
                raise StateConflictError(
                    f"{claim_exc}；治理状态 degraded：{'；'.join(rollback_errors)}"
                ) from claim_exc
            raise
    except Exception as exc:
        return _deny(f"子 Agent 派发被阻止：StateStore/PreparedContract 认领失败：{exc}")
    return _allow_updated(
        copy.deepcopy(tool_input),
        f"Subagent Governance 已消费 task_ref={task_ref} 的派发凭证并完成发送前双门禁。",
    )


def _create_resume_attempt(
    state: dict[str, Any],
    task_id: str,
    pending_owner_attempt: int,
    pending: dict[str, Any],
    claimed_at: int,
    tool_use_id: str,
) -> dict[str, Any]:
    task = _ensure_canonical_task_record(state, task_id)
    pending_owner = _canonical_execution_for_attempt(task, pending_owner_attempt)
    if pending_owner is None or pending_owner.get("pending_action") != pending:
        raise StateConflictError("business_resume prepared action 与 pending owner 不匹配")
    old_attempt = pending.get("prepared_on_attempt")
    if (
        isinstance(old_attempt, bool)
        or not isinstance(old_attempt, int)
        or old_attempt < 1
    ):
        raise StateConflictError("business_resume 缺少精确 prepared_on_attempt")
    old = _canonical_execution_for_attempt(task, old_attempt)
    if old is None:
        raise StateConflictError("business_resume source attempt 不存在")
    # This runs inside the PreToolUse StateStore CAS callback.  Check the
    # current locked state before moving the pending action or writing A(N+1).
    contract = _contract_from_input(pending.get("resume_contract"))
    try:
        current_context_verification = verify_context_manifest(
            contract.context_manifest
        )
    except ContextVerificationError as exc:
        raise StateConflictError(
            f"business_resume 必需上下文二次验证失败：{exc}"
        ) from exc
    if current_context_verification != pending.get("resume_context_verification"):
        raise StateConflictError(
            "business_resume 必需上下文在 prepare 与 followup 之间发生变化"
        )
    new_attempt = int(pending["attempt"])
    task_ref = str(pending["task_ref"])
    pending_owner.pop("pending_action", None)
    task_name = str(old.get("task_name") or "")
    created = _initial_task_record(
        new_attempt,
        task_ref,
        task_name,
        contract,
        claimed_at,
    )
    created_execution = created["executions"][str(new_attempt)]
    _apply_canonical_execution_update(created_execution, "observed_execution_status", "not_started")
    created_execution["task_name"] = None
    claimed = copy.deepcopy(pending)
    claimed.update(
        {
            "phase": "claimed",
            "tool_use_id": tool_use_id,
            "claimed_at": claimed_at,
        }
    )
    created_execution["pending_action"] = claimed
    task["executions"][str(new_attempt)] = created_execution
    task["work_item"]["current_attempt"] = new_attempt
    return created_execution


def _state_claim_commit_status(
    session_id: str,
    store: StateStore,
    before: dict[str, Any],
    committed: dict[str, Any],
) -> str:
    observed = store.read(session_id)
    if observed == committed:
        return "committed"
    if observed == before:
        return "not_persisted"
    return "ambiguous"


def _claim_pending_action(
    payload: dict[str, Any], store: StateStore, *, interrupt: bool = False
) -> dict[str, Any]:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return _deny("子 Agent 操作被阻止：工具参数不是对象。")
    target_value = tool_input.get("target")
    if not isinstance(target_value, str) or not target_value.strip():
        return _deny("子 Agent 操作被阻止：target 必须是非空字符串。")
    target = target_value.strip()
    session_id = str(payload.get("session_id") or "unknown")
    tool_use_id = str(payload.get("tool_use_id") or "")
    current_time = _event_now(payload)
    kind = _tool_kind(str(payload.get("tool_name") or ""))
    try:
        state = store.read(session_id)
    except Exception as exc:
        failure_category = _state_store_exception_category(exc, during_read=True)
        if failure_category == "unavailable" and (
            interrupt or kind == "communication"
        ):
            projected = {"target": target} if interrupt else copy.deepcopy(tool_input)
            return _allow_updated(
                projected,
                f"Subagent Governance 状态不可读，本次原生操作已 fail-open；治理状态未可靠记录：{exc}",
            )
        return _deny(
            "受治理 lifecycle 操作被阻止：StateStore 读取未取得可降级的存储故障"
            f"（{failure_category}）：{exc}"
        )
    state_before_claim = copy.deepcopy(state)
    matches = _pending_action_matches_target(state, target)
    if not matches:
        admission = _managed_target_admission(state, target)
        if admission.disposition == "reconcile":
            return _deny(
                f"managed target identity 需要人工对账，不能按 unmanaged 放行：{admission.reason}。"
            )
        if admission.disposition == "historical":
            return _deny(
                "target 仅匹配已可靠关闭的 historical provenance；"
                "不能复活 active index 或按 unmanaged 放行。"
            )
        if admission.disposition != "managed":
            return _allow_updated(
                copy.deepcopy(tool_input),
                "Subagent Governance：目标没有 canonical provenance，"
                "本次原生操作按 unmanaged 兼容放行。",
            )
        if interrupt:
            return _deny("managed interrupt 缺少由生成器创建的明确 pending_action。")
        if kind == "communication":
            return _deny("managed normal_message 缺少由生成器创建的唯一 prepared pending_action。")
        return _deny("managed followup_task 缺少唯一 prepared pending_action，不能猜测 operation type。")
    if len(matches) != 1:
        return _deny("同一 target 映射到多个 pending_action，已拒绝调用并要求人工对账。")
    if not tool_use_id:
        return _deny("子 Agent 操作被阻止：缺少 tool_use_id，无法认领 pending_action。")
    task_id, stored_attempt, _record, pending = matches[0]
    operation_type = str(pending.get("operation_type") or "")
    if interrupt != (operation_type == "interrupt"):
        return _deny("原生工具类型与 prepared operation type 不匹配。")
    if not interrupt:
        if kind == "communication":
            if operation_type != "normal_message":
                return _deny("send_message 只能认领 normal_message pending_action。")
        elif kind == "followup":
            if operation_type == "normal_message":
                return _deny("followup_task 不能认领 normal_message pending_action。")
        else:
            return _deny("通信 pending_action 与原生工具类型不匹配。")
    if pending.get("phase") != "prepared":
        return _deny("pending_action 已被认领，不能重复调用。")
    created_at = pending.get("created_at")
    if (
        isinstance(created_at, bool)
        or not isinstance(created_at, int)
        or created_at
        <= current_time - int(RETENTION_SECONDS["prepared_unclaimed"])
    ):
        try:
            def expired_predicate(current: dict[str, Any]) -> bool:
                current_record = _task_record_for_attempt(
                    current, task_id, stored_attempt
                )
                current_pending = (
                    current_record.get("pending_action")
                    if isinstance(current_record, dict)
                    else None
                )
                return bool(
                    isinstance(current_pending, dict)
                    and current_pending.get("phase") == "prepared"
                    and _pending_action_matches_exact(
                        current,
                        target,
                        task_id,
                        stored_attempt,
                        pending,
                    )
                )

            def expire(current: dict[str, Any]) -> None:
                current_record = _task_record_for_attempt(
                    current, task_id, stored_attempt
                )
                if not isinstance(current_record, dict):
                    raise StateConflictError("过期 pending_action owner 已不存在")
                current_record.pop("pending_action", None)

            store.compare_and_set(
                session_id,
                expired_predicate,
                expire,
            )
        except Exception as exc:
            return _deny(f"过期 pending_action 清理失败：{exc}")
        return _deny("pending_action 已超过5分钟，请重新生成本次操作。")

    def predicate(current: dict[str, Any]) -> bool:
        current_matches = _pending_action_matches_target(current, target)
        current_admission = _managed_target_admission(current, target)
        return bool(
            len(current_matches) == 1
            and current_matches[0][0] == task_id
            and current_matches[0][1] == stored_attempt
            and current_matches[0][3].get("phase") == "prepared"
            and current_matches[0][3].get("created_at") == pending.get("created_at")
            and current_admission.disposition == "managed"
            and current_admission.candidate is not None
            and current_admission.candidate[:2] == (task_id, stored_attempt)
        )

    claim_snapshot: dict[str, Any] = {}

    def claim(current: dict[str, Any]) -> None:
        current_admission = _managed_target_admission(current, target)
        if (
            current_admission.disposition != "managed"
            or current_admission.candidate is None
            or current_admission.candidate[:2] != (task_id, stored_attempt)
        ):
            raise StateConflictError(
                "target lifecycle admission 与 pending owner 不一致"
            )
        _repair_managed_target_index(current, target, current_admission)
        _ensure_canonical_task_record(current, task_id)
        current_record = _task_record_for_attempt(current, task_id, stored_attempt)
        assert current_record is not None
        current_pending = current_record["pending_action"]
        if operation_type == "business_resume":
            current_record = _create_resume_attempt(
                current,
                task_id,
                stored_attempt,
                copy.deepcopy(current_pending),
                current_time,
                tool_use_id,
            )
        else:
            current_pending["phase"] = "claimed"
            current_pending["tool_use_id"] = tool_use_id
            current_pending["claimed_at"] = current_time
        if operation_type == "platform_recovery":
            count = current_record.get("recovery_count")
            if isinstance(count, bool) or not isinstance(count, int) or count >= RETRY_LIMITS["recovery"]:
                raise StateConflictError("recovery_count 无效或已经耗尽")
            current_record["recovery_count"] = count + 1
            if current_record["recovery_count"] == 2:
                if pending.get("authorized_recovery") is not True:
                    raise StateConflictError("第二次平台恢复缺少用户授权")
        current_record["updated_at"] = current_time
        claim_snapshot["committed"] = copy.deepcopy(current)

    try:
        store.compare_and_set(session_id, predicate, claim)
    except Exception as exc:
        committed_state = claim_snapshot.get("committed")
        if isinstance(committed_state, dict):
            try:
                commit_status = _state_claim_commit_status(
                    session_id,
                    store,
                    state_before_claim,
                    committed_state,
                )
            except Exception as verification_exc:
                commit_status = "unavailable"
                verification_error = verification_exc
            else:
                verification_error = None
        else:
            commit_status = "not_persisted"
            verification_error = None
        if commit_status == "committed":
            pass
        elif commit_status == "ambiguous":
            return _deny(
                "受治理 lifecycle 操作认领结果无法确认，状态已发生并发变化，"
                f"已进入 degraded：{exc}"
            )
        else:
            failure_category = _state_store_exception_category(exc, during_read=False)
            if commit_status == "unavailable" and verification_error is not None:
                failure_category = _state_store_exception_category(
                    verification_error, during_read=True
                )
            if failure_category == "unavailable" and (
                interrupt or operation_type == "normal_message"
            ):
                operation_label = "中断" if interrupt else "normal_message"
                verification_suffix = (
                    f"；提交结果核验失败：{verification_error}"
                    if verification_error is not None
                    else ""
                )
                return _allow_updated(
                    {"target": target}
                    if interrupt
                    else {
                        "target": target,
                        "message": str(tool_input.get("message") or ""),
                    },
                    f"{operation_label} target 明确，但 StateStore 写入不可用；"
                    f"已 fail-open 调用原生操作，治理状态未可靠记录：{exc}{verification_suffix}",
                )
            verification_suffix = (
                f"；提交结果核验失败：{verification_error}"
                if verification_error is not None
                else ""
            )
            return _deny(
                "受治理 lifecycle 操作认领失败，pending 保留供对账或过期清理"
                f"（{failure_category}）：{exc}{verification_suffix}"
            )
    projected = {"target": target} if interrupt else {
        "target": target,
        "message": str(tool_input.get("message") or ""),
    }
    return _allow_updated(
        projected,
        f"Subagent Governance 已认领 {operation_type} pending_action 并绑定 tool_use_id。",
    )


def _handle_communication(payload: dict[str, Any], store: StateStore) -> dict[str, Any] | None:
    return _claim_pending_action(payload, store, interrupt=False)


def _handle_interrupt_pre(payload: dict[str, Any], store: StateStore) -> dict[str, Any] | None:
    return _claim_pending_action(payload, store, interrupt=True)


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


def _weak_list_agents_observation_preserves_terminal(
    record: dict[str, Any], observation: str
) -> bool:
    return bool(
        observation in {"absent", "pending_init", "unknown"}
        and _execution_status(record) in {"stopped", "interrupted"}
    )


def _record_exact_absence(
    state: dict[str, Any], target: str, observed_at: int
) -> None:
    mapped = _resolve_exact_dispatch_target_attempt(state, target)
    if mapped is None:
        return
    task_id, attempt, _record = mapped
    _ensure_canonical_task_record(state, task_id)
    record = _task_record_for_attempt(state, task_id, attempt)
    if not isinstance(record, dict):
        return
    if (
        _identity_status(record) != "confirmed"
        or _execution_is_closed(record) is True
        or _weak_list_agents_observation_preserves_terminal(record, "absent")
    ):
        return
    _apply_canonical_execution_update(record, "observation_observed_at", observed_at)
    _apply_canonical_execution_update(record, "observation_source", "list_agents")
    record["observation_record"]["observed_state"] = "absent_at_check"
    _apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
    record["updated_at"] = observed_at
    lifecycle = record.get("last_lifecycle_operation")
    if not (
        isinstance(lifecycle, dict)
        and lifecycle.get("operation_type") == "interrupt"
        and lifecycle.get("call_observation") == "success"
        and lifecycle.get("target_observation") == "not_found"
    ):
        return
    _apply_canonical_execution_update(record, "observed_execution_status", "stopped")
    _apply_canonical_execution_update(record, "closure_parent_action", "decide_disposition")
    record.pop("last_lifecycle_operation", None)


def _resolve_exact_dispatch_target_attempt(
    state: dict[str, Any], target: str
) -> tuple[str, int, dict[str, Any]] | None:
    matches = [
        (task_id, attempt, record)
        for task_id, attempt, record in _iter_task_attempts(state)
        if isinstance(record.get("dispatch_record"), dict)
        and record["dispatch_record"].get("dispatch_target") == target
    ]
    return matches[0] if len(matches) == 1 else None


def _identity_mapping(task_id: str, attempt: int) -> dict[str, Any]:
    return {"task_id": task_id, "attempt": attempt}


def _handle_post_tool_agent_status(
    payload: dict[str, Any], store: StateStore, session_id: str
) -> dict[str, Any] | None:
    response = payload.get("tool_response")
    entries = _agent_status_entries(response)
    if entries is None:
        return None
    exact_query_target = _list_agents_exact_target(payload.get("tool_input"))
    if exact_query_target is None:
        return None
    if not entries:
        try:
            store.update(
                session_id,
                lambda state: _record_exact_absence(
                    state, exact_query_target, _event_now(payload)
                ),
            )
        except (OSError, RuntimeError) as exc:
            return {"systemMessage": f"Subagent Governance 无法记录精确空 Agent 对账，已降级放行：{exc}"}
        return None

    if len(entries) != 1 or entries[0].get("agent_name") != exact_query_target:
        return None

    def reconcile(state: dict[str, Any]) -> None:
        for entry in entries:
            target = str(entry.get("agent_name") or "")
            resolved = _resolve_exact_dispatch_target_attempt(state, target)
            if resolved is None:
                continue
            task_id, mapped_attempt, _record = resolved
            _ensure_canonical_task_record(state, task_id)
            record = _task_record_for_attempt(state, task_id, mapped_attempt)
            if not isinstance(record, dict):
                continue
            platform_status, _platform_summary = _normalized_agent_status(
                entry.get("agent_status")
            )
            observed_at = _event_now(payload)
            if _execution_is_closed(record) is True:
                continue
            if _weak_list_agents_observation_preserves_terminal(
                record, platform_status
            ):
                continue
            _apply_canonical_execution_update(record, "observation_observed_at", observed_at)
            _apply_canonical_execution_update(record, "observation_source", "list_agents")
            if _execution_status(record) == "interrupted":
                record["updated_at"] = observed_at
                continue
            last = record.get("last_lifecycle_operation")
            interrupt_reconcile = bool(
                isinstance(last, dict)
                and last.get("operation_type") == "interrupt"
                and last.get("call_observation") in {"success", "unknown"}
            )
            recovery_error_reconcile = bool(
                isinstance(last, dict)
                and last.get("operation_type") == "platform_recovery"
                and last.get("call_observation") in {"success", "unknown"}
            )
            if platform_status == "error":
                execution_was_running = _execution_status(record) == "running"
                if (
                    execution_was_running
                    or recovery_error_reconcile
                ):
                    _apply_canonical_execution_update(record, "observed_execution_status", "stopped")
                    if interrupt_reconcile:
                        _apply_canonical_execution_update(record, "closure_parent_action", "ask_user")
                    else:
                        if recovery_error_reconcile:
                            record.pop("last_lifecycle_operation", None)
                        if record.get("recovery_count") == 0:
                            _apply_canonical_execution_update(record, "closure_parent_action", "recover")
                        else:
                            _apply_canonical_execution_update(record, "closure_parent_action", "ask_user")
                elif interrupt_reconcile:
                    _apply_canonical_execution_update(record, "closure_parent_action", "ask_user")
                _apply_canonical_execution_update(record, "observed_platform_state", "error")
                record["updated_at"] = observed_at
                continue
            if platform_status == "running":
                _apply_canonical_execution_update(record, "observed_execution_status", "running")
                if interrupt_reconcile:
                    _apply_canonical_execution_update(record, "closure_parent_action", "ask_user")
                else:
                    _apply_canonical_execution_update(record, "closure_parent_action", "wait")
            elif platform_status in {"stopped", "completed", "interrupted"}:
                _apply_canonical_execution_update(
                    record,
                    "observed_execution_status",
                    "interrupted" if platform_status == "interrupted" else "stopped",
                )
                _apply_canonical_execution_update(record, "observation_summary", platform_status)
                if interrupt_reconcile:
                    record.pop("last_lifecycle_operation", None)
                _apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
            elif platform_status == "pending_init":
                _apply_canonical_execution_update(record, "observed_platform_state", "unknown")
                _apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
            else:
                _apply_canonical_execution_update(record, "observed_platform_state", "unknown")
            record["updated_at"] = observed_at
    try:
        store.update(session_id, reconcile)
    except (OSError, RuntimeError) as exc:
        return {"systemMessage": f"Subagent Governance 无法对账 Agent 平台状态，已降级放行：{exc}"}
    return None


def _handle_post_tool_lifecycle(
    payload: dict[str, Any], store: StateStore, session_id: str
) -> dict[str, Any] | None:
    tool_use_id = str(payload.get("tool_use_id") or "")
    response = payload.get("tool_response")
    observed_at = _event_now(payload)
    try:
        state = store.read(session_id)
        claimed = _claimed_action_for_tool_use(state, tool_use_id)
    except Exception as exc:
        return {
            "systemMessage": (
                "Subagent Governance 无法读取 lifecycle claim；原生调用已经发生，"
                f"治理状态进入 degraded 并需人工对账：{exc}"
            )
        }
    if claimed is not None:
        task_id, attempt, _record, pending = claimed
        observation = adapt_call_response(response, str(pending.get("operation_type")))

        def predicate(current: dict[str, Any]) -> bool:
            target = _task_record_for_attempt(current, task_id, attempt)
            action = target.get("pending_action") if isinstance(target, dict) else None
            return bool(
                isinstance(action, dict)
                and action.get("phase") == "claimed"
                and action.get("tool_use_id") == tool_use_id
            )

        def apply(current: dict[str, Any]) -> None:
            _ensure_canonical_task_record(current, task_id)
            target = _task_record_for_attempt(current, task_id, attempt)
            assert target is not None
            current_pending = copy.deepcopy(target["pending_action"])
            _apply_action_observation(
                target,
                current_pending,
                observation,
                observed_at,
            )

        try:
            store.compare_and_set(session_id, predicate, apply)
        except Exception as exc:
            return {
                "systemMessage": (
                    "Subagent Governance 已观察到原生调用 "
                    f"{observation['call_observation']}，但状态写入失败；"
                    f"已消耗的预算或 attempt 不回滚，治理状态 degraded：{exc}"
                )
            }
        return None

    return None


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
            prepared_store.delete(session_id, task_ref)
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
    store = state_store or StateStore()

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
    store = state_store or StateStore()
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
            active_store = StateStore()
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
        return _migrate_state_to_current(value)
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
                    "task 记录不是当前 managed attempt 结构；旧记录不会进入执行状态机",
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
                        f"managed task 缺少 canonical {field_name} 对象；历史记录不会迁移或进入执行状态机",
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


class _NonExitingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _emit_diagnostic_cli_error(message: str, arguments: list[str]) -> None:
    root = _data_root_path()
    document = _diagnostic_base_document(_diagnostic_absolute_path(root), None)
    if "--session" in arguments:
        document["scope"] = "single_session"
    document["scan"]["complete"] = False
    document["issues"] = [
        _diagnostic_issue(
            "scan_incomplete",
            f"诊断 CLI 参数错误：{message}",
            fact="cli_argument_error",
        )
    ]
    sys.stdout.buffer.write(_diagnostic_output_bytes(document))


def _run_preparation_cli(args: argparse.Namespace) -> int:
    if not args.session:
        print("dispatch preparation requires --session", file=sys.stderr)
        return 2
    try:
        raw_contract = json.loads(sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1))
        base = _prepare_private_directory(args.data_root.expanduser()) if args.data_root else _data_root()
        state_store = StateStore(base / "sessions")
        prepared_store = PreparedContractStore(base / "prepared")
        if args.prepare_dispatch:
            result = prepare_dispatch(
                raw_contract,
                args.session,
                state_store=state_store,
                prepared_store=prepared_store,
            )
        elif args.prepare_spawn_retry is not None:
            result = prepare_spawn_retry(
                raw_contract,
                args.session,
                args.prepare_spawn_retry,
                authorized=args.authorize_final_retry,
                state_store=state_store,
                prepared_store=prepared_store,
            )
        elif args.prepare_communication:
            result = prepare_communication(
                raw_contract,
                args.session,
                authorized_recovery=args.authorize_recovery,
                state_store=state_store,
            )
        else:
            result = prepare_interrupt(
                raw_contract,
                args.session,
                state_store=state_store,
            )
    except Exception as exc:
        print(f"operation preparation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _run_context_verification_cli() -> int:
    try:
        raw_input = sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1)
        if len(raw_input.encode("utf-8")) > MAX_HOOK_INPUT_BYTES:
            raise ValueError(
                f"context manifest input exceeds {MAX_HOOK_INPUT_BYTES} bytes"
            )
        raw_manifest = json.loads(raw_input)
        result = verify_context_manifest(raw_manifest)
    except Exception as exc:
        print(f"context verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _run_reconciliation_cli(args: argparse.Namespace) -> int:
    if not args.session:
        print("interrupted attempt reconciliation requires --session", file=sys.stderr)
        return 2
    try:
        raw_observation = json.loads(sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1))
        base = _prepare_private_directory(args.data_root.expanduser()) if args.data_root else _data_root()
        result = reconcile_interrupted_attempt(
            raw_observation,
            args.session,
            state_store=StateStore(base / "sessions"),
        )
    except Exception as exc:
        print(f"interrupted attempt reconciliation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _run_lifecycle_cli(args: argparse.Namespace) -> int:
    if not args.session:
        print("lifecycle operations require --session", file=sys.stderr)
        return 2
    try:
        base = _prepare_private_directory(args.data_root.expanduser()) if args.data_root else _data_root()
        state_store = StateStore(base / "sessions")
        if args.record_terminal_notification:
            raw_notification = json.loads(sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1))
            result = record_terminal_notification(
                raw_notification,
                args.session,
                state_store=state_store,
            )
        else:
            raw_disposition = json.loads(sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1))
            result = apply_parent_disposition(
                raw_disposition,
                args.session,
                state_store=state_store,
            )
    except Exception as exc:
        print(f"lifecycle operation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _run_group_cli(args: argparse.Namespace) -> int:
    if not args.session:
        print("group operations require --session", file=sys.stderr)
        return 2
    if args.read_group and not args.group_id:
        print("--read-group requires --group-id", file=sys.stderr)
        return 2
    try:
        base = (
            _prepare_private_directory(args.data_root.expanduser())
            if args.data_root
            else _data_root()
        )
        state_store = StateStore(base / "sessions")
        if args.upsert_group:
            raw_group = json.loads(sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1))
            result = upsert_group(
                raw_group,
                args.session,
                state_store=state_store,
            )
        else:
            result = read_group(
                args.session,
                args.group_id,
                state_store=state_store,
            )
    except Exception as exc:
        print(f"group operation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _run_hook_cli() -> int:
    try:
        raw_input = sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1)
        if len(raw_input.encode("utf-8")) > MAX_HOOK_INPUT_BYTES:
            raise ValueError(f"hook input exceeds {MAX_HOOK_INPUT_BYTES} bytes")
        payload = json.loads(raw_input)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be a JSON object")
        result = handle(payload)
    except Exception as exc:
        event = locals().get("payload", {}).get("hook_event_name") if isinstance(locals().get("payload"), dict) else None
        if event == "PreToolUse":
            result = _deny(f"Subagent Governance 解析失败：{exc}")
        else:
            result = {"continue": True, "systemMessage": f"Subagent Governance 运行失败，已降级放行：{exc}"}
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


def main() -> int:
    parser = _NonExitingArgumentParser(add_help=False)
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--prepare-dispatch", action="store_true")
    parser.add_argument("--verify-context-manifest", action="store_true")
    parser.add_argument("--prepare-spawn-retry")
    parser.add_argument("--authorize-final-retry", action="store_true")
    parser.add_argument("--prepare-communication", action="store_true")
    parser.add_argument("--prepare-interrupt", action="store_true")
    parser.add_argument("--reconcile-interrupted-attempt", action="store_true")
    parser.add_argument("--authorize-recovery", action="store_true")
    parser.add_argument("--record-terminal-notification", action="store_true")
    parser.add_argument("--parent-disposition", action="store_true")
    parser.add_argument("--upsert-group", action="store_true")
    parser.add_argument("--read-group", action="store_true")
    parser.add_argument("--group-id")
    parser.add_argument("--session")
    parser.add_argument("--data-root", type=Path)
    raw_arguments = sys.argv[1:]
    diagnostic_requested = "--diagnose" in raw_arguments
    try:
        args, unknown = parser.parse_known_args()
    except ValueError as exc:
        if diagnostic_requested:
            _emit_diagnostic_cli_error(str(exc), raw_arguments)
        print(str(exc), file=sys.stderr)
        return 2
    if unknown:
        if args.diagnose:
            _emit_diagnostic_cli_error(f"unsupported arguments: {unknown}", raw_arguments)
        print(f"unsupported arguments: {unknown}", file=sys.stderr)
        return 2
    operation_modes = {
        "prepare_dispatch": args.prepare_dispatch,
        "verify_context_manifest": args.verify_context_manifest,
        "prepare_spawn_retry": args.prepare_spawn_retry is not None,
        "prepare_communication": args.prepare_communication,
        "prepare_interrupt": args.prepare_interrupt,
        "reconcile_interrupted_attempt": args.reconcile_interrupted_attempt,
        "record_terminal_notification": args.record_terminal_notification,
        "parent_disposition": args.parent_disposition,
        "upsert_group": args.upsert_group,
        "read_group": args.read_group,
    }
    preparation_mode = any(
        (
            args.prepare_dispatch,
            args.prepare_spawn_retry is not None,
            args.prepare_communication,
            args.prepare_interrupt,
        )
    )
    lifecycle_mode = any(
        operation_modes[name]
        for name in (
            "record_terminal_notification", "parent_disposition",
        )
    )
    group_mode = args.upsert_group or args.read_group
    reconciliation_mode = args.reconcile_interrupted_attempt
    if sum(bool(value) for value in operation_modes.values()) > 1:
        if args.diagnose:
            _emit_diagnostic_cli_error("operation modes cannot be combined", raw_arguments)
        print("operation modes cannot be combined", file=sys.stderr)
        return 2
    if args.diagnose and any(operation_modes.values()):
        _emit_diagnostic_cli_error(
            "--diagnose cannot be combined with another operation mode",
            raw_arguments,
        )
        print("--diagnose cannot be combined with another operation mode", file=sys.stderr)
        return 2
    diagnostic_selector_conflicts = [
        name
        for name, selected in (
            ("--group-id", args.group_id is not None),
            ("--authorize-final-retry", args.authorize_final_retry),
            ("--authorize-recovery", args.authorize_recovery),
        )
        if selected
    ]
    if args.diagnose and diagnostic_selector_conflicts:
        conflict_text = ", ".join(diagnostic_selector_conflicts)
        message = f"{conflict_text} cannot be combined with --diagnose"
        _emit_diagnostic_cli_error(message, raw_arguments)
        print(message, file=sys.stderr)
        return 2
    invalid_authorization_combinations = []
    if args.authorize_final_retry and args.prepare_spawn_retry is None:
        invalid_authorization_combinations.append(
            "--authorize-final-retry requires --prepare-spawn-retry"
        )
    if args.authorize_recovery and not args.prepare_communication:
        invalid_authorization_combinations.append(
            "--authorize-recovery requires --prepare-communication"
        )
    if args.group_id is not None and not args.read_group:
        invalid_authorization_combinations.append(
            "--group-id is only valid with --read-group"
        )
    if invalid_authorization_combinations:
        message = "; ".join(invalid_authorization_combinations)
        if args.diagnose:
            _emit_diagnostic_cli_error(message, raw_arguments)
        print(message, file=sys.stderr)
        return 2
    if args.verify_context_manifest and (
        args.session is not None or args.data_root is not None
    ):
        print(
            "--verify-context-manifest does not accept --session or --data-root",
            file=sys.stderr,
        )
        return 2
    if not args.diagnose and not any(operation_modes.values()) and (
        args.session is not None or args.data_root is not None or args.group_id is not None
    ):
        print("--session and --data-root require --diagnose or an explicit operation mode", file=sys.stderr)
        return 2
    if args.diagnose:
        return _diagnose(args.session, args.data_root)
    if args.verify_context_manifest:
        return _run_context_verification_cli()
    if preparation_mode:
        return _run_preparation_cli(args)
    if reconciliation_mode:
        return _run_reconciliation_cli(args)
    if lifecycle_mode:
        return _run_lifecycle_cli(args)
    if group_mode:
        return _run_group_cli(args)
    return _run_hook_cli()


if __name__ == "__main__":
    raise SystemExit(main())
