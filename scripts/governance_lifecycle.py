"""Managed lifecycle transactions over validated StateStore records.

This domain module owns state mutation for communication, recovery, interrupt,
resume, normalized observations, terminal notices, and parent disposition.  It
does not import the runtime facade or render Hook allow/deny envelopes.
"""

from __future__ import annotations

import copy
import time
from typing import Any

try:
    from scripts.governance_communication import (
        native_args, native_tool_for_operation, parse_communication_request,
        parse_interrupt_request, render_message, render_user_message,
    )
    from scripts.governance_context import verify_context_manifest
    from scripts.governance_contracts import TaskContract, contract_digest, contract_from_input
    from scripts.governance_dispatch import initial_task_record
    from scripts.governance_dispatch_identity import select_task_ref
    from scripts.governance_dispatch_rendering import render_list as _render_list, render_verified_context as _render_verified_context
    from scripts.governance_platform import adapt_lifecycle_response, lifecycle_response_shape
    from scripts.governance_errors import (
        CommunicationPreparationError, ContextVerificationError,
        NotificationObservationError, ParentDispositionConflict,
        ParentDispositionError, ReconciliationError, StateConflictError,
        StateValidationError, _state_store_exception_category,
    )
    from scripts.governance_execution import (
        apply_canonical_execution_update as _apply_canonical_execution_update,
        canonical_execution_for_attempt as _canonical_execution_for_attempt,
        close_attempt_record as _close_attempt_record,
        dispatch_target as _dispatch_target, execution_close_reason as _execution_close_reason,
        execution_is_closed as _execution_is_closed, execution_status as _execution_status,
        identity_status as _identity_status, iter_task_attempts as _iter_task_attempts,
        managed_target_admission as _managed_target_admission,
        observation_is_bound as _observation_is_bound,
        observation_checked_at as _observation_checked_at, observation_source as _observation_source,
        parent_action as _parent_action, record_has_target_provenance as _record_has_target_provenance,
        repair_managed_target_index as _repair_managed_target_index,
        task_attempt_records as _task_attempt_records,
        task_record_for_attempt as _task_record_for_attempt,
        ensure_canonical_task_record as _ensure_canonical_task_record,
        platform_observation as _platform_observation, spawn_observation as _spawn_observation,
    )
    from scripts.governance_semantics import (
        CALL_OBSERVATIONS, LIFECYCLE_OPERATION_TYPES, LIST_AGENTS_TERMINAL_STATUSES,
        MAX_CONTRACT_TEXT, OPERATION_NATIVE_TOOLS,
        OPERATION_TYPES, PARENT_DISPOSITION_REASON_MAX_LENGTH, PARENT_DISPOSITIONS,
        RETENTION_SECONDS, RETRY_LIMITS, SEMANTIC_DEFINITIONS,
    )
    from scripts.governance_state_store import StateStore
except ModuleNotFoundError:
    from governance_communication import native_args, native_tool_for_operation, parse_communication_request, parse_interrupt_request, render_message, render_user_message
    from governance_context import verify_context_manifest
    from governance_contracts import TaskContract, contract_digest, contract_from_input
    from governance_dispatch import initial_task_record
    from governance_dispatch_identity import select_task_ref
    from governance_dispatch_rendering import render_list as _render_list, render_verified_context as _render_verified_context
    from governance_platform import adapt_lifecycle_response, lifecycle_response_shape
    from governance_errors import CommunicationPreparationError, ContextVerificationError, NotificationObservationError, ParentDispositionConflict, ParentDispositionError, ReconciliationError, StateConflictError, StateValidationError, _state_store_exception_category
    from governance_execution import apply_canonical_execution_update as _apply_canonical_execution_update, canonical_execution_for_attempt as _canonical_execution_for_attempt, close_attempt_record as _close_attempt_record, dispatch_target as _dispatch_target, execution_close_reason as _execution_close_reason, execution_is_closed as _execution_is_closed, execution_status as _execution_status, identity_status as _identity_status, iter_task_attempts as _iter_task_attempts, managed_target_admission as _managed_target_admission, observation_is_bound as _observation_is_bound, observation_checked_at as _observation_checked_at, observation_source as _observation_source, parent_action as _parent_action, record_has_target_provenance as _record_has_target_provenance, repair_managed_target_index as _repair_managed_target_index, task_attempt_records as _task_attempt_records, task_record_for_attempt as _task_record_for_attempt, ensure_canonical_task_record as _ensure_canonical_task_record, platform_observation as _platform_observation, spawn_observation as _spawn_observation
    from governance_semantics import CALL_OBSERVATIONS, LIFECYCLE_OPERATION_TYPES, LIST_AGENTS_TERMINAL_STATUSES, MAX_CONTRACT_TEXT, OPERATION_NATIVE_TOOLS, OPERATION_TYPES, PARENT_DISPOSITION_REASON_MAX_LENGTH, PARENT_DISPOSITIONS, RETENTION_SECONDS, RETRY_LIMITS, SEMANTIC_DEFINITIONS
    from governance_state_store import StateStore


def _now() -> int:
    return int(time.time())


def _default_state_store() -> StateStore:
    return StateStore()


def _admission_denied(reason: str) -> dict[str, Any]:
    """Compatibility result for the runtime adapter; rendering stays at the edge."""
    return {"decision": "deny", "reason": reason}


def _admission_allowed(updated_input: dict[str, Any], context: str | None = None) -> dict[str, Any]:
    return {"decision": "allow", "updated_input": updated_input, "context": context}


def _bounded(value: Any, fallback: str = "") -> str:
    return str(value or fallback).strip()[:MAX_CONTRACT_TEXT]


def _validate_text(value: Any, label: str, *, maximum: int) -> list[str]:
    return [] if isinstance(value, str) and value.strip() and len(value.strip()) <= maximum else [f"{label} 必须是非空且长度不超过 {maximum} 的字符串"]


def _validate_task_identity(task_id: Any, attempt: Any) -> tuple[str, int]:
    maximum = int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"])
    if _validate_text(task_id, "task_id", maximum=maximum):
        raise NotificationObservationError(f"task_id 必须是非空且长度不超过 {maximum} 的字符串")
    minimum = int(SEMANTIC_DEFINITIONS["attempt"]["minimum"])
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < minimum:
        raise NotificationObservationError(f"attempt 必须是大于等于 {minimum} 的整数")
    return str(task_id), attempt


def _identity_mapping(task_id: str, attempt: int) -> dict[str, Any]:
    return {"task_id": task_id, "attempt": attempt}


def _managed_target_attempt(
    state: dict[str, Any], target: str
) -> tuple[str, int, dict[str, Any]] | None:
    mapping = state.get("agents", {}).get(target)
    if not isinstance(mapping, dict):
        return None
    task_id, attempt = mapping.get("task_id"), mapping.get("attempt")
    if not isinstance(task_id, str) or not isinstance(attempt, int) or isinstance(attempt, bool):
        return None
    record = _task_record_for_attempt(state, task_id, attempt)
    return (task_id, attempt, record) if isinstance(record, dict) else None


_contract_from_input = contract_from_input
_initial_task_record = initial_task_record


def _event_now(payload: dict[str, Any]) -> int:
    value = payload.get("now")
    return value if isinstance(value, int) and not isinstance(value, bool) else _now()


def _communication_fields(value: Any, *, interrupt: bool = False) -> tuple[str, dict[str, str]]:
    if interrupt:
        return parse_interrupt_request(value), {}
    parsed = parse_communication_request(value)
    return parsed.target, parsed.fields


def render_communication_user_message(target: str, fields: dict[str, str], *, interrupt: bool = False) -> str:
    return render_user_message(target, fields, interrupt=interrupt)


def render_communication_message(
    fields: dict[str, str], operation_type: str, *, resume_contract: TaskContract | None = None,
    resume_context_verification: dict[str, Any] | None = None, resume_identity: dict[str, Any] | None = None,
) -> str:
    return render_message(fields, operation_type, resume_contract=resume_contract,
                          resume_context_verification=resume_context_verification,
                          resume_identity=resume_identity)


def _tool_kind(tool_name: str) -> str | None:
    if tool_name.endswith("followup_task"):
        return "followup"
    if tool_name.endswith("send_message") and not tool_name.endswith("send_message_to_thread"):
        return "communication"
    if tool_name.endswith("interrupt_agent"):
        return "interrupt"
    return None


# Extracted lifecycle implementation follows.
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
    store = state_store or _default_state_store()

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
                "status": "closed_ignored",
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
    return {
        "task_ref": record.get("task_ref"),
        "dispatch_target": _dispatch_target(record),
        "close_reason": reason,
        "closed_at": closed_at,
    }


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
    store = state_store or _default_state_store()
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
        # The agents index is only a current identity index.  Delete mappings
        # that still point at this work item, but never infer ownership from a
        # target name or remove a mapping concurrently transferred elsewhere.
        agents = state.get("agents")
        if not isinstance(agents, dict):
            raise StateValidationError("治理状态缺少 agents 对象")
        for target, mapping in list(agents.items()):
            if isinstance(mapping, dict) and mapping.get("task_id") == task_id:
                agents.pop(target, None)
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
        pending["resume_contract_digest"] = contract_digest(resume_contract)
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
            raise CommunicationPreparationError("当前 Agent/attempt 的平台恢复次数已经耗尽或状态不匹配")
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
        resume_identity=(
            {"task_id": task_id, "attempt": desired_attempt, "task_ref": desired_task_ref, "target": target}
            if operation_type == "business_resume" else None
        ),
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
    if admission.disposition == "closed":
        raise CommunicationPreparationError(
            f"目标 {target} 仅匹配已可靠关闭的 provenance；"
            "不能复活 active index 或按 unmanaged 放行"
        )
    if admission.disposition != "managed" or admission.candidate is None:
        if operation_type == "business_resume":
            raise CommunicationPreparationError(
                "business_resume 必须具有唯一 managed canonical identity，不能按 unmanaged 发送"
            )
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
        state_store=state_store or _default_state_store(),
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
        state_store=state_store or _default_state_store(),
        interrupt=True,
        authorized_recovery=False,
        now=_now() if now is None else now,
    )


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


def _unknown_call_observation(value: Any) -> dict[str, str | None]:
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
            _apply_canonical_execution_update(record, "dispatch_response", "success")
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
    store = state_store or _default_state_store()
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
                    and created_at <= current_time - int(RETENTION_SECONDS["prepared_unclaimed"])
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
                    record, copy.deepcopy(pending), _unknown_call_observation("unknown"), current_time
                )
                counts["reconciled"] += 1

    state_store.update(session_id, reconcile)
    return counts


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
    work_item = task.get("work_item")
    if not isinstance(work_item, dict) or work_item.get("current_attempt") != old_attempt:
        raise StateConflictError("business_resume source 不是 current attempt")
    if not _execution_is_closed(old):
        _close_attempt_record(
            state, task_id, old_attempt, old, "business_resume", claimed_at
        )
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
    _apply_canonical_execution_update(created_execution, "dispatch_target", pending["target"])
    _apply_canonical_execution_update(created_execution, "dispatch_tool_use_id", tool_use_id)
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
    agents = state.get("agents")
    if not isinstance(agents, dict):
        raise StateValidationError("治理状态缺少 agents 对象")
    agents[str(pending["target"])] = _identity_mapping(task_id, new_attempt)
    work_item["current_attempt"] = new_attempt
    return created_execution


def _state_claim_commit_status(
    session_id: str,
    store: StateStore,
    before: dict[str, Any],
    committed: dict[str, Any],
    *,
    task_id: str,
    target: str,
) -> str:
    def projection(state: dict[str, Any]) -> dict[str, Any]:
        tombstones = state.get("tombstones")
        return {
            "task": copy.deepcopy(state.get("tasks", {}).get(task_id)),
            "agent": copy.deepcopy(state.get("agents", {}).get(target)),
            "tombstones": {
                key: copy.deepcopy(value)
                for key, value in (tombstones.items() if isinstance(tombstones, dict) else [])
                if key.startswith(f"{task_id}:")
            },
        }
    observed = store.read(session_id)
    if projection(observed) == projection(committed):
        return "committed"
    if projection(observed) == projection(before):
        return "not_persisted"
    return "ambiguous"


def _claim_pending_action(
    payload: dict[str, Any], store: StateStore, *, interrupt: bool = False
) -> dict[str, Any]:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return _admission_denied("子 Agent 操作被阻止：工具参数不是对象。")
    target_value = tool_input.get("target")
    if not isinstance(target_value, str) or not target_value.strip():
        return _admission_denied("子 Agent 操作被阻止：target 必须是非空字符串。")
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
            return _admission_allowed(
                projected,
                f"Subagent Governance 状态不可读，本次原生操作已 fail-open；治理状态未可靠记录：{exc}",
            )
        return _admission_denied(
            "受治理 lifecycle 操作被阻止：StateStore 读取未取得可降级的存储故障"
            f"（{failure_category}）：{exc}"
        )
    state_before_claim = copy.deepcopy(state)
    matches = _pending_action_matches_target(state, target)
    if not matches:
        admission = _managed_target_admission(state, target)
        if admission.disposition == "reconcile":
            return _admission_denied(
                f"managed target identity 需要人工对账，不能按 unmanaged 放行：{admission.reason}。"
            )
        if admission.disposition == "closed":
            return _admission_denied(
                "target 仅匹配已可靠关闭的 provenance；"
                "不能复活 active index 或按 unmanaged 放行。"
            )
        if admission.disposition != "managed":
            return _admission_allowed(
                copy.deepcopy(tool_input),
                "Subagent Governance：目标没有 canonical provenance，"
                "本次原生操作按 unmanaged 放行。",
            )
        if interrupt:
            return _admission_denied("managed interrupt 缺少由生成器创建的明确 pending_action。")
        if kind == "communication":
            return _admission_denied("managed normal_message 缺少由生成器创建的唯一 prepared pending_action。")
        return _admission_denied("managed followup_task 缺少唯一 prepared pending_action，不能猜测 operation type。")
    if len(matches) != 1:
        return _admission_denied("同一 target 映射到多个 pending_action，已拒绝调用并要求人工对账。")
    if not tool_use_id:
        return _admission_denied("子 Agent 操作被阻止：缺少 tool_use_id，无法认领 pending_action。")
    task_id, stored_attempt, _record, pending = matches[0]
    operation_type = str(pending.get("operation_type") or "")
    if interrupt != (operation_type == "interrupt"):
        return _admission_denied("原生工具类型与 prepared operation type 不匹配。")
    if not interrupt:
        if kind == "communication":
            if operation_type != "normal_message":
                return _admission_denied("send_message 只能认领 normal_message pending_action。")
        elif kind == "followup":
            if operation_type == "normal_message":
                return _admission_denied("followup_task 不能认领 normal_message pending_action。")
        else:
            return _admission_denied("通信 pending_action 与原生工具类型不匹配。")
    if pending.get("phase") != "prepared":
        return _admission_denied("pending_action 已被认领，不能重复调用。")
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
            return _admission_denied(f"过期 pending_action 清理失败：{exc}")
        return _admission_denied("pending_action 已超过5分钟，请重新生成本次操作。")

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
                    task_id=task_id,
                    target=target,
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
            return _admission_denied(
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
                return _admission_allowed(
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
            return _admission_denied(
                "受治理 lifecycle 操作认领失败，pending 保留供对账或过期清理"
                f"（{failure_category}）：{exc}{verification_suffix}"
            )
    projected = {"target": target} if interrupt else {
        "target": target,
        "message": str(tool_input.get("message") or ""),
    }
    return _admission_allowed(
        projected,
        f"Subagent Governance 已认领 {operation_type} pending_action 并绑定 tool_use_id。",
    )


def _handle_communication(payload: dict[str, Any], store: StateStore) -> dict[str, Any] | None:
    return _claim_pending_action(payload, store, interrupt=False)


def _handle_interrupt_pre(payload: dict[str, Any], store: StateStore) -> dict[str, Any] | None:
    return _claim_pending_action(payload, store, interrupt=True)




def _weak_list_agents_observation_preserves_terminal(
    record: dict[str, Any], observation: str
) -> bool:
    return bool(
        observation in {"absent", "pending_init", "unknown"}
        and _execution_status(record) in {"stopped", "interrupted"}
    )


def _record_exact_absence(
    state: dict[str, Any], mapped: tuple[str, int, dict[str, Any]], observed_at: int
) -> None:
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


def resolve_exact_list_observation_target(
    state: dict[str, Any], target: str
) -> tuple[tuple[str, int, dict[str, Any]] | None, str | None]:
    """Route an adapter-proven exact list result to one current execution.

    Historical closed attempts deliberately retain their dispatch target.  They
    are therefore not candidates for a new list observation; active identity
    and open provenance are the only authority here.
    """
    admission = _managed_target_admission(state, target)
    if admission.disposition == "managed" and admission.candidate is not None:
        task_id, attempt, record = admission.candidate
        if _execution_is_closed(record):
            return None, "closed_provenance_only"
        if _dispatch_target(record) != target:
            return None, "active_index_provenance_mismatch"
        return (task_id, attempt, record), None
    if admission.disposition == "closed":
        return None, "closed_provenance_only"
    if admission.disposition == "unmanaged":
        return None, "unmanaged_target"
    open_retained = [
        candidate
        for candidate in _iter_task_attempts(state)
        if _record_has_target_provenance(candidate[2], target)
        and not _execution_is_closed(candidate[2])
    ]
    if len(open_retained) > 1:
        return None, "current_identity_ambiguous"
    return None, "active_index_provenance_mismatch"


def _mark_exact_list_route_reconcile(state: dict[str, Any], target: str) -> None:
    """Record only the safe lifecycle consequence of an inconsistent route."""
    mapping = state.get("agents", {}).get(target) if isinstance(state.get("agents"), dict) else None
    candidates = [
        candidate
        for candidate in _iter_task_attempts(state)
        if _record_has_target_provenance(candidate[2], target)
        and not _execution_is_closed(candidate[2])
    ]
    if isinstance(mapping, dict):
        mapped = _task_record_for_attempt(state, mapping.get("task_id"), mapping.get("attempt"))
        if isinstance(mapped, dict) and not _execution_is_closed(mapped):
            candidates.append((str(mapping.get("task_id")), int(mapping.get("attempt")), mapped))
    seen: set[tuple[str, int]] = set()
    for task_id, attempt, record in candidates:
        if (task_id, attempt) in seen:
            continue
        seen.add((task_id, attempt))
        _apply_canonical_execution_update(record, "closure_parent_action", "reconcile")


def _identity_mapping(task_id: str, attempt: int) -> dict[str, Any]:
    return {"task_id": task_id, "attempt": attempt}


def observe_agent_status_post_tool(
    payload: dict[str, Any], store: StateStore, session_id: str, observation: Any
) -> dict[str, Any] | None:
    """Persist one adapter-proven exact list_agents observation."""
    target = getattr(observation, "target", None)
    platform_status = getattr(observation, "normalized_status", None)
    if not isinstance(target, str) or not isinstance(platform_status, str):
        return None
    route: dict[str, str | None] = {"reason": None}

    def reconcile(state: dict[str, Any]) -> None:
        resolved, reason = resolve_exact_list_observation_target(state, target)
        if resolved is None:
            route["reason"] = reason or "current_identity_unavailable"
            if reason in {"current_identity_ambiguous", "active_index_provenance_mismatch"}:
                _mark_exact_list_route_reconcile(state, target)
            return
        if platform_status == "absent":
            _record_exact_absence(state, resolved, _event_now(payload))
            return
        task_id, mapped_attempt, _record = resolved
        _ensure_canonical_task_record(state, task_id)
        record = _task_record_for_attempt(state, task_id, mapped_attempt)
        if not isinstance(record, dict):
            return
        if True:
            observed_at = _event_now(payload)
            if _execution_is_closed(record) is True:
                return
            if _weak_list_agents_observation_preserves_terminal(
                record, platform_status
            ):
                return
            _apply_canonical_execution_update(record, "observation_observed_at", observed_at)
            _apply_canonical_execution_update(record, "observation_source", "list_agents")
            if _execution_status(record) == "interrupted":
                record["updated_at"] = observed_at
                return
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
                return
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
    if route["reason"] is not None:
        return {
            "systemMessage": (
                "Subagent Governance：list_agents adapter 已接受，但 canonical route 被拒绝"
                f"（{route['reason']}），未写入 canonical observation。"
            )
        }
    return None


def _receipt_for_tool_use(state: dict[str, Any], tool_use_id: str) -> dict[str, Any] | None:
    matches = [
        receipt
        for _task_id, _attempt, record in _iter_task_attempts(state)
        if isinstance((receipt := record.get("post_receipt")), dict)
        and receipt.get("received_tool_use_id") == tool_use_id
    ]
    if len(matches) > 1:
        raise StateConflictError(f"同一 tool_use_id 映射到多个 post_receipt：{tool_use_id}")
    return matches[0] if matches else None


def _receipt_from_claim(
    session_id: str,
    task_id: str,
    attempt: int,
    pending: dict[str, Any],
    tool_use_id: str,
    observation: dict[str, str | None],
    response_shape: str,
    observed_at: int,
) -> dict[str, Any]:
    operation_type = str(pending["operation_type"])
    family = "interrupt" if operation_type == "interrupt" else "communication" if operation_type == "normal_message" else "followup"
    return {
        "session_id": session_id,
        "task_id": task_id,
        "attempt": attempt,
        "task_ref": pending["task_ref"],
        "target": pending["target"],
        "expected_tool_use_id": pending["tool_use_id"],
        "received_tool_use_id": tool_use_id,
        "id_match": True,
        "tool_family": family,
        "operation_type": operation_type,
        "response_shape": response_shape,
        "processing_result": observation["call_observation"],
        "recorded_at": observed_at,
    }


def observe_lifecycle_post_tool(
    payload: dict[str, Any], store: StateStore, session_id: str, *, report_unmatched: bool = False
) -> dict[str, Any] | None:
    """Receipt and reconcile a claimed lifecycle PostToolUse exactly once.

    The receipt is written in the same CAS mutation before the lifecycle
    transition, so it contains no body or response values and cannot be
    detached from the current pending owner.
    """
    tool_use_id = str(payload.get("tool_use_id") or "")
    observed_at = _event_now(payload)
    if not tool_use_id:
        return {"systemMessage": "Subagent Governance：followup PostToolUse 未提供 tool_use_id（post_tool_use_id_missing），未写入状态。"} if report_unmatched else None
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
        operation_type = pending.get("operation_type")
        if not isinstance(operation_type, str):
            return {"systemMessage": "Subagent Governance 收到无效 claimed pending operation，已降级放行。"}
        observation = adapt_lifecycle_response(
            payload.get("tool_response"), operation_type
        ).to_record()
        if observation.get("call_observation") not in CALL_OBSERVATIONS:
            return {"systemMessage": "Subagent Governance 收到无效 lifecycle adapter 观察，已降级放行。"}
        response_shape = lifecycle_response_shape(payload.get("tool_response"))

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
            target["post_receipt"] = _receipt_from_claim(
                session_id, task_id, attempt, current_pending, tool_use_id,
                observation, response_shape, observed_at,
            )
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
                    f"post_receipt_write_failed，已消耗的预算或 attempt 不回滚，治理状态 degraded：{exc}"
                )
            }
        return None
    try:
        duplicate = _receipt_for_tool_use(state, tool_use_id)
    except Exception as exc:
        return {"systemMessage": f"Subagent Governance 无法检查 lifecycle receipt，已降级放行：{exc}"}
    if duplicate is not None:
        return None
    return {"systemMessage": "Subagent Governance：followup PostToolUse 的 tool_use_id 未关联 claimed pending（post_tool_use_id_unclaimed），未写入状态。"} if report_unmatched else None
