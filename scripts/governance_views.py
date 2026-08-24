"""Read-only, privacy-trimmed projections of canonical governance work items.

This module deliberately accepts persisted state dictionaries and returns new,
small dictionaries.  It never mutates state and never copies an execution as a
whole: contracts, context verification, pending messages and business output
are not part of this public decision model.
"""
from __future__ import annotations

import time
from typing import Any

try:
    from scripts.governance_execution import (
        dispatch_reliably_not_created, dispatch_target, execution_close_reason,
        execution_closed_at, execution_is_closed, execution_status,
        identity_status, observation_checked_at, observation_is_bound,
        parent_action, platform_observation, spawn_observation,
    )
    from scripts.governance_lifecycle import _business_resume_allowed
    from scripts.governance_semantics import (
        _DECISION_ACTION_ORDER, EXECUTION_STATUSES, IDENTITY_STATUSES,
        PLATFORM_OBSERVATIONS, RETENTION_SECONDS, RETRY_LIMITS,
    )
except ModuleNotFoundError:
    from governance_execution import dispatch_reliably_not_created, dispatch_target, execution_close_reason, execution_closed_at, execution_is_closed, execution_status, identity_status, observation_checked_at, observation_is_bound, parent_action, platform_observation, spawn_observation
    from governance_lifecycle import _business_resume_allowed
    from governance_semantics import _DECISION_ACTION_ORDER, EXECUTION_STATUSES, IDENTITY_STATUSES, PLATFORM_OBSERVATIONS, RETENTION_SECONDS, RETRY_LIMITS


class ViewIssue(ValueError):
    """Stable error used when a stored work item cannot be projected."""


def _now() -> int:
    return int(time.time())


def activity_at(record: dict[str, Any]) -> int:
    values: list[int] = []
    for value in (record.get("updated_at"), execution_closed_at(record), observation_checked_at(record)):
        if isinstance(value, int) and not isinstance(value, bool):
            values.append(value)
    pending = record.get("pending_action")
    if isinstance(pending, dict):
        for key in ("created_at", "claimed_at"):
            value = pending.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                values.append(value)
    return max(values, default=0)


def _attempt_closed(state: dict[str, Any], task_id: str, attempt: int, record: dict[str, Any]) -> bool:
    if execution_is_closed(record):
        return True
    tombstones = state.get("tombstones")
    return isinstance(tombstones, dict) and isinstance(tombstones.get(f"{task_id}:{attempt}"), dict)


def _reasoned_closed(state: dict[str, Any], task_id: str, attempt: int, record: dict[str, Any]) -> bool:
    if not _attempt_closed(state, task_id, attempt, record):
        return False
    tombstone = state.get("tombstones", {}).get(f"{task_id}:{attempt}") if isinstance(state.get("tombstones"), dict) else None
    return bool(execution_close_reason(record) or (tombstone or {}).get("close_reason"))


def _call_in_progress(record: dict[str, Any]) -> bool:
    dispatch = record.get("dispatch_record") if isinstance(record.get("dispatch_record"), dict) else {}
    spawn = dispatch.get("tool_use_id") is not None and spawn_observation(record) is None
    pending = record.get("pending_action")
    pending_call = isinstance(pending, dict) and pending.get("phase") in {"prepared", "claimed"}
    lifecycle = record.get("last_lifecycle_operation")
    unresolved = isinstance(lifecycle, dict) and lifecycle.get("call_observation") in {"success", "unknown"}
    return spawn or pending_call or unresolved


def attempt_action_required(state: dict[str, Any], task_id: str, attempt: int, record: dict[str, Any]) -> bool:
    # A failed delivery is reliably closed at attempt level, but its persisted
    # open work item still needs a parent decision; it is intentionally not
    # filtered by the ordinary closed-attempt fast path.
    failed_resume = execution_close_reason(record) == "resume_delivery_failed"
    if _attempt_closed(state, task_id, attempt, record) and not failed_resume:
        return False
    return bool(
        failed_resume
        or parent_action(record) is not None
        or execution_status(record) == "running"
        or _call_in_progress(record)
        or (identity_status(record) == "unconfirmed" and spawn_observation(record) in {"success", "unknown"})
    )


def action_priority(record: dict[str, Any]) -> int:
    return {"recover": 0, "reconcile": 1, "retry_spawn": 2, "ask_user": 3, "decide_disposition": 4, "wait": 5}.get(str(parent_action(record)), 99)


def _records_for_task(state: dict[str, Any], task_id: str) -> tuple[dict[str, Any], list[tuple[int, dict[str, Any]]]]:
    task = state.get("tasks", {}).get(task_id) if isinstance(state.get("tasks"), dict) else None
    if not isinstance(task, dict) or task.get("managed") is not True:
        raise ViewIssue("managed task 不存在")
    work_item, executions = task.get("work_item"), task.get("executions")
    if not isinstance(work_item, dict) or not isinstance(executions, dict) or not executions:
        raise ViewIssue("managed work item 缺少 canonical execution")
    records: list[tuple[int, dict[str, Any]]] = []
    for key, value in executions.items():
        if isinstance(key, str) and key.isdecimal() and int(key) > 0 and isinstance(value, dict):
            records.append((int(key), value))
    if not records:
        raise ViewIssue("managed work item 缺少可读取 execution")
    return work_item, sorted(records)


def _candidate(state: dict[str, Any], task_id: str, attempt: int, record: dict[str, Any], current_attempt: int | None) -> dict[str, Any]:
    dispatch = record.get("dispatch_record") if isinstance(record.get("dispatch_record"), dict) else {}
    observation = record.get("observation_record") if isinstance(record.get("observation_record"), dict) else {}
    lifecycle = record.get("last_lifecycle_operation") if isinstance(record.get("last_lifecycle_operation"), dict) else None
    receipt = record.get("post_receipt") if isinstance(record.get("post_receipt"), dict) else None
    notification = bool(observation.get("source") == "terminal_notification" and observation.get("observed_state") == "terminal" and observation_is_bound(record))
    closed = _attempt_closed(state, task_id, attempt, record)
    return {
        "attempt": attempt,
        "role": "tombstoned" if closed else "current" if attempt == current_attempt else "prior",
        "dispatch": {
            "state": dispatch.get("dispatch_state"),
            "post_observed": dispatch.get("dispatch_state") in {"acknowledged", "rejected", "indeterminate"},
            "target_bound": bool(isinstance(dispatch.get("dispatch_target"), str) and dispatch["dispatch_target"]),
        },
        "target": ({"dispatch_target": dispatch_target(record)} if isinstance(dispatch_target(record), str) else None),
        "identity": identity_status(record) if identity_status(record) in IDENTITY_STATUSES else "unknown",
        "execution": execution_status(record) if execution_status(record) in EXECUTION_STATUSES else "unknown",
        "platform": platform_observation(record) if platform_observation(record) in PLATFORM_OBSERVATIONS else "not_checked",
        "notification": {"observed": notification, "source": observation.get("source"), "terminal_status": observation.get("terminal_status")},
        "last_lifecycle_observation": ({
            "operation_type": lifecycle.get("operation_type"),
            "call_observation": lifecycle.get("call_observation"),
            **({"target_observation": lifecycle.get("target_observation")} if isinstance(lifecycle.get("target_observation"), str) else {}),
        } if lifecycle is not None else None),
        "post_receipt": ({
            "recorded_at": receipt.get("recorded_at"),
            "id_match": receipt.get("id_match"),
            "tool_family": receipt.get("tool_family"),
            "tool_name_classification": receipt.get("tool_name_classification"),
            "operation_type": receipt.get("operation_type"),
            "response_shape": receipt.get("response_shape"),
            "processing_result": receipt.get("processing_result"),
            "target_observation": receipt.get("target_observation"),
            "transition_state": receipt.get("transition_state"),
        } if receipt is not None else None),
        "action_required": attempt_action_required(state, task_id, attempt, record),
        "timestamps": {key: value for key, value in (("activity_at", activity_at(record)), ("platform_checked_at", observation_checked_at(record)), ("attempt_closed_at", execution_closed_at(record))) if isinstance(value, int) and not isinstance(value, bool)},
    }


def _allowed_actions(records: list[tuple[int, dict[str, Any]]], current_attempt: int | None, lifecycle: str) -> list[str]:
    if lifecycle == "tombstoned":
        return ["inspect_tombstone"]
    if lifecycle != "open" or current_attempt is None:
        return ["reconcile"]
    current = next((record for attempt, record in records if attempt == current_attempt), None)
    if not isinstance(current, dict):
        return ["reconcile"]
    actions: set[str] = set()
    failed_resume = execution_close_reason(current) == "resume_delivery_failed"
    observation = current.get("observation_record") if isinstance(current.get("observation_record"), dict) else {}
    notified = observation.get("source") == "terminal_notification" and observation.get("observed_state") == "terminal" and observation_is_bound(current)
    if execution_status(current) == "running" and identity_status(current) == "confirmed":
        actions.add("wait")
    if platform_observation(current) == "unknown" or spawn_observation(current) == "unknown" or identity_status(current) != "confirmed" or parent_action(current) == "reconcile":
        actions.add("reconcile")
    if spawn_observation(current) == "failed" and dispatch_reliably_not_created(current) and int(current.get("spawn_retry_count") or 0) < int(RETRY_LIMITS["spawn"]) and identity_status(current) == "unconfirmed":
        actions.add("retry_spawn")
    if notified or execution_status(current) == "interrupted" or failed_resume:
        actions.add("close_task")
    if bool(current.get("contract_digest") and current.get("contract_summary")) and (_business_resume_allowed(current) or failed_resume):
        actions.add("resume_business")
    order = {action: index for index, action in enumerate(_DECISION_ACTION_ORDER)}
    return sorted(actions, key=lambda action: order.get(action, 99))


def work_item_view(state: dict[str, Any], task_id: str, *, session_id: str | None = None, now: int | None = None) -> tuple[dict[str, Any] | None, list[dict[str, Any]], bool]:
    """Return the only public decision projection for a managed work item."""
    issues: list[dict[str, Any]] = []
    try:
        work_item, records = _records_for_task(state, task_id)
    except ViewIssue as exc:
        return None, [{"code": "current_required_field_invalid", "message": str(exc), "context": {"session_id": session_id, "task_id": task_id, "field": "work_item/executions"}}], True
    attempts = {attempt for attempt, _ in records}
    raw_current = work_item.get("current_attempt")
    current_attempt = raw_current if isinstance(raw_current, int) and not isinstance(raw_current, bool) and raw_current in attempts else None
    incomplete = current_attempt is None
    if incomplete:
        issues.append({"code": "current_required_field_invalid", "message": "work_item.current_attempt 无法关联 canonical execution", "context": {"session_id": session_id, "task_id": task_id, "field": "work_item.current_attempt"}})
    persisted = work_item.get("lifecycle")
    all_closed = all(_reasoned_closed(state, task_id, attempt, record) for attempt, record in records)
    # Exact current existence is sufficient for open.  In particular, an open
    # item survives a reliable resume delivery failure of that current attempt.
    if persisted == "tombstoned" and all_closed:
        lifecycle = "tombstoned"
    elif persisted == "open" and current_attempt is not None:
        lifecycle = "open"
    else:
        lifecycle, incomplete = "indeterminate", True
        issues.append({"code": "current_required_field_invalid", "message": "work-item lifecycle 与 execution close facts 不一致", "context": {"session_id": session_id, "task_id": task_id, "field": "work_item.lifecycle"}})
    candidates = [_candidate(state, task_id, attempt, record, current_attempt) for attempt, record in records]
    current = next((record for attempt, record in records if attempt == current_attempt), None)
    current_candidate = next((item for item in candidates if item["attempt"] == current_attempt), None)
    notification = current_candidate.get("notification", {}) if isinstance(current_candidate, dict) else {}
    summary = current.get("contract_summary") if isinstance(current, dict) and isinstance(current.get("contract_summary"), dict) else {}
    objective = summary.get("objective") if isinstance(summary.get("objective"), str) and summary.get("objective").strip() else None
    if objective is None:
        incomplete = True
        issues.append({"code": "current_required_field_missing", "message": "current execution 缺少有界 contract objective", "context": {"session_id": session_id, "task_id": task_id, "field": "execution.contract_summary.objective"}})
    current_time = _now() if now is None else now
    return {
        "task_id": task_id, "objective_summary": objective[:600] if objective else None,
        "current_attempt": current_attempt, "lifecycle": lifecycle,
        "action_required": lifecycle == "indeterminate" or any(item["action_required"] for item in candidates),
        "recent_activity": any(item["timestamps"].get("activity_at", 0) >= current_time - int(RETENTION_SECONDS["recent_activity"]) for item in candidates),
        "execution_candidates": candidates,
        "terminal_notification": {"state": "observed" if notification.get("observed") else "pending" if current_attempt is not None else "unknown", "attempt": current_attempt, "source": notification.get("source"), "terminal_status": notification.get("terminal_status")},
        "allowed_actions": _allowed_actions(records, current_attempt, lifecycle),
    }, issues, incomplete


def work_item_views(state: dict[str, Any], *, session_id: str | None = None, now: int | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    results, issues, incomplete = [], [], False
    tasks = state.get("tasks") if isinstance(state.get("tasks"), dict) else {}
    for task_id in sorted(key for key, value in tasks.items() if isinstance(key, str) and isinstance(value, dict) and value.get("managed") is True):
        view, item_issues, item_incomplete = work_item_view(state, task_id, session_id=session_id, now=now)
        issues.extend(item_issues); incomplete = incomplete or item_incomplete
        if view is not None: results.append(view)
    return results, issues, incomplete


def work_item_decision_snapshot(state: dict[str, Any], task_id: str, *, session_id: str | None = None, now: int | None = None) -> tuple[dict[str, Any] | None, list[dict[str, Any]], bool]:
    """Return one P7 work-item projection for composition callers."""
    return work_item_view(state, task_id, session_id=session_id, now=now)


def action_required_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for task_id, task in (state.get("tasks") or {}).items():
        if not isinstance(task_id, str) or not isinstance(task, dict) or task.get("managed") is not True: continue
        for attempt, record in _records_for_task(state, task_id)[1]:
            if attempt_action_required(state, task_id, attempt, record):
                records.append({"task_id": task_id, "attempt": attempt, "activity_at": activity_at(record), "resolved_mode": record.get("resolved_mode"), "contract_summary": {"objective": (record.get("contract_summary") or {}).get("objective")} if isinstance(record.get("contract_summary"), dict) else {}, "dispatch_record": {"dispatch_target": dispatch_target(record)}, "observation_record": {"source": (record.get("observation_record") or {}).get("source"), "terminal_status": (record.get("observation_record") or {}).get("terminal_status")}, "_priority": action_priority(record), "_status": execution_status(record)})
    records.sort(key=lambda item: (item.pop("_priority"), -int(item.get("activity_at") or 0), item["task_id"], item["attempt"]))
    return records


def recent_activity_records(state: dict[str, Any], *, now: int | None = None) -> list[dict[str, Any]]:
    cutoff = (_now() if now is None else now) - int(RETENTION_SECONDS["recent_activity"])
    records: list[dict[str, Any]] = []
    for task_id, task in (state.get("tasks") or {}).items():
        if not isinstance(task_id, str) or not isinstance(task, dict) or task.get("managed") is not True: continue
        for attempt, record in _records_for_task(state, task_id)[1]:
            if activity_at(record) >= cutoff:
                records.append({"task_id": task_id, "attempt": attempt, "activity_at": activity_at(record), "resolved_mode": record.get("resolved_mode"), "contract_summary": {"objective": (record.get("contract_summary") or {}).get("objective")} if isinstance(record.get("contract_summary"), dict) else {}, "dispatch_record": {"dispatch_target": dispatch_target(record)}, "observation_record": {"source": (record.get("observation_record") or {}).get("source"), "terminal_status": (record.get("observation_record") or {}).get("terminal_status")}})
    return sorted(records, key=lambda item: (-int(item["activity_at"]), item["task_id"], item["attempt"]))
