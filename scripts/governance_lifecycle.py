"""Minimal exact-identity lifecycle transitions for the state-v9 ledger."""

from __future__ import annotations

import copy
import time
from typing import Any

try:
    from scripts.governance_errors import StateConflictError
    from scripts.governance_semantics import (
        CALL_RESULTS,
        CLOSED_TASK_RETENTION,
        INTERRUPT_RESULTS,
        PLATFORM_OBSERVATION_STATUSES,
        PLATFORM_TERMINAL_STATUSES,
        TERMINAL_NOTIFICATION_STATUSES,
    )
except ModuleNotFoundError:
    from governance_errors import StateConflictError
    from governance_semantics import (
        CALL_RESULTS,
        CLOSED_TASK_RETENTION,
        INTERRUPT_RESULTS,
        PLATFORM_OBSERVATION_STATUSES,
        PLATFORM_TERMINAL_STATUSES,
        TERMINAL_NOTIFICATION_STATUSES,
    )


PRESERVED_FACT_FIELDS = (
    "task_ref",
    "contract_digest",
    "contract_summary",
    "created_at",
    "target",
    "bound_at",
    "platform_observation",
    "terminal_fact",
    "interrupt_fact",
)


def _now(value: int | None) -> int:
    result = int(time.time()) if value is None else value
    if isinstance(result, bool) or not isinstance(result, int) or result < 0:
        raise ValueError("timestamp 必须是非负整数")
    return result


def _text(value: Any, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and bool(value)
        and len(value) <= maximum
    )


def _exact_fields(value: Any, fields: set[str], operation: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{operation} 输入字段无效")
    return value


def _identity(value: dict[str, Any], *, target_field: str = "target") -> tuple[str, str, str]:
    task_id = value.get("task_id")
    task_ref = value.get("task_ref")
    target = value.get(target_field)
    invalid = []
    for name, item, maximum in (
        ("task_id", task_id, 256),
        ("task_ref", task_ref, 20),
        (target_field, target, 1024),
    ):
        if not _text(item, maximum):
            invalid.append(name)
    if invalid:
        raise ValueError("lifecycle identity 字段无效：" + "、".join(invalid))
    return task_id, task_ref, target


def _task_for_identity(
    state: dict[str, Any], task_id: str, task_ref: str, target: str
) -> dict[str, Any]:
    task = state["tasks"].get(task_id)
    if not isinstance(task, dict) or task.get("task_ref") != task_ref:
        raise StateConflictError("lifecycle task_id/task_ref 不匹配")
    if task.get("target") != target:
        raise StateConflictError("lifecycle exact target 与已绑定 target 不匹配")
    return task


def _preserved_facts(task: dict[str, Any]) -> dict[str, Any]:
    return {
        field: copy.deepcopy(task[field])
        for field in PRESERVED_FACT_FIELDS
        if field in task
    }


def enter_reconcile(task: dict[str, Any], code: str, observed_at: int) -> None:
    preserved = _preserved_facts(task)
    task.clear()
    task.update(
        preserved,
        phase="reconcile",
        updated_at=observed_at,
        reconcile={"code": code, "observed_at": observed_at},
    )


def prune_closed_tasks(state: dict[str, Any]) -> tuple[str, ...]:
    """Keep the newest fixed number of closed records during a real write."""
    closed = [
        (task.get("closed_at", -1), task.get("created_at", -1), task_id)
        for task_id, task in state["tasks"].items()
        if isinstance(task, dict) and task.get("phase") == "closed"
    ]
    excess = len(closed) - CLOSED_TASK_RETENTION
    if excess <= 0:
        return ()
    removed = tuple(item[2] for item in sorted(closed)[:excess])
    for task_id in removed:
        del state["tasks"][task_id]
    return removed


def _reconcile_outcome(
    task: dict[str, Any], task_id: str, task_ref: str
) -> dict[str, Any]:
    return {
        "result": "reconcile",
        "task_id": task_id,
        "task_ref": task_ref,
        "target": task.get("target"),
        "reason": task.get("reconcile", {}).get("code"),
    }


def record_platform_observation(
    session_id: str,
    value: Any,
    *,
    state_store: Any,
    now: int | None = None,
) -> dict[str, Any]:
    request = _exact_fields(
        value, {"task_id", "task_ref", "target", "status"},
        "record-platform-observation",
    )
    task_id, task_ref, target = _identity(request)
    status = request.get("status")
    if status not in PLATFORM_OBSERVATION_STATUSES:
        raise ValueError("platform observation status 无效")
    observed_at = _now(now)
    outcome: dict[str, Any] = {}

    def record(state: dict[str, Any]) -> None:
        task = _task_for_identity(state, task_id, task_ref, target)
        phase = task.get("phase")
        if phase == "reconcile":
            outcome.update(_reconcile_outcome(task, task_id, task_ref))
        elif phase == "terminal":
            terminal = task.get("terminal_fact", {})
            if status not in PLATFORM_TERMINAL_STATUSES:
                raise StateConflictError("terminal task 不接受 active/error platform observation")
            if terminal.get("status") != status:
                enter_reconcile(task, "terminal_status_conflict", observed_at)
                outcome.update(_reconcile_outcome(task, task_id, task_ref))
            elif task.get("platform_observation", {}).get("status") == status:
                outcome.update(
                    result="already_terminal", task_id=task_id,
                    task_ref=task_ref, target=target, status=status,
                )
            else:
                task["platform_observation"] = {
                    "status": status,
                    "observed_at": observed_at,
                }
                task["updated_at"] = observed_at
                outcome.update(
                    result="terminal_observed", task_id=task_id,
                    task_ref=task_ref, target=target, status=status,
                )
        elif phase != "bound":
            raise StateConflictError("platform observation 只接受 bound/terminal task")
        elif status == "unknown":
            enter_reconcile(task, "platform_observation_unknown", observed_at)
            outcome.update(_reconcile_outcome(task, task_id, task_ref))
        elif status in PLATFORM_TERMINAL_STATUSES:
            task["phase"] = "terminal"
            task["platform_observation"] = {
                "status": status,
                "observed_at": observed_at,
            }
            task["terminal_fact"] = {
                "source": "platform",
                "status": status,
                "observed_at": observed_at,
            }
            task["updated_at"] = observed_at
            outcome.update(
                result="terminal", task_id=task_id, task_ref=task_ref,
                target=target, status=status,
            )
        elif task.get("platform_observation", {}).get("status") == status:
            outcome.update(
                result="already_observed", task_id=task_id,
                task_ref=task_ref, target=target, status=status,
            )
        else:
            task["platform_observation"] = {
                "status": status,
                "observed_at": observed_at,
            }
            task["updated_at"] = observed_at
            outcome.update(
                result="recorded", task_id=task_id, task_ref=task_ref,
                target=target, status=status,
            )
        prune_closed_tasks(state)

    state_store.update(session_id, record)
    return outcome


def record_call_result(
    session_id: str,
    value: Any,
    *,
    state_store: Any,
    now: int | None = None,
) -> dict[str, Any]:
    request = _exact_fields(
        value, {"task_id", "task_ref", "target", "result"},
        "record-call-result",
    )
    task_id, task_ref, target = _identity(request)
    result = request.get("result")
    if result not in CALL_RESULTS:
        raise ValueError("normal call result 无效")
    if result != "unknown":
        state = state_store.read(session_id)
        task = _task_for_identity(state, task_id, task_ref, target)
        if task.get("phase") != "bound":
            raise StateConflictError("normal call result 只接受 bound task")
        return {
            "result": result,
            "persisted": False,
            "task_id": task_id,
            "task_ref": task_ref,
            "target": target,
        }

    observed_at = _now(now)
    outcome: dict[str, Any] = {}

    def record_unknown(state: dict[str, Any]) -> None:
        task = _task_for_identity(state, task_id, task_ref, target)
        if task.get("phase") == "reconcile":
            outcome.update(_reconcile_outcome(task, task_id, task_ref))
        elif task.get("phase") != "bound":
            raise StateConflictError("unknown normal call result 只接受 bound task")
        else:
            enter_reconcile(task, "delivery_unknown", observed_at)
            outcome.update(_reconcile_outcome(task, task_id, task_ref))
        prune_closed_tasks(state)

    state_store.update(session_id, record_unknown)
    return outcome


def record_terminal_notification(
    session_id: str,
    value: Any,
    *,
    state_store: Any,
    now: int | None = None,
) -> dict[str, Any]:
    request = _exact_fields(
        value, {"task_id", "task_ref", "sender", "status"},
        "record-terminal-notification",
    )
    task_id, task_ref, sender = _identity(request, target_field="sender")
    status = request.get("status")
    if status not in TERMINAL_NOTIFICATION_STATUSES:
        raise ValueError("terminal notification status 无效")
    observed_at = _now(now)
    outcome: dict[str, Any] = {}

    def record(state: dict[str, Any]) -> None:
        task = _task_for_identity(state, task_id, task_ref, sender)
        phase = task.get("phase")
        if phase == "reconcile":
            outcome.update(_reconcile_outcome(task, task_id, task_ref))
        elif phase == "terminal":
            terminal = task.get("terminal_fact", {})
            if terminal.get("status") == status:
                outcome.update(
                    result="already_terminal", task_id=task_id,
                    task_ref=task_ref, target=sender, status=status,
                )
            else:
                enter_reconcile(task, "terminal_status_conflict", observed_at)
                outcome.update(_reconcile_outcome(task, task_id, task_ref))
        elif phase != "bound":
            raise StateConflictError("terminal notification 只接受 bound/terminal task")
        else:
            task["phase"] = "terminal"
            task["terminal_fact"] = {
                "source": "notification",
                "status": status,
                "observed_at": observed_at,
            }
            task["updated_at"] = observed_at
            outcome.update(
                result="terminal", task_id=task_id, task_ref=task_ref,
                target=sender, status=status,
            )
        prune_closed_tasks(state)

    state_store.update(session_id, record)
    return outcome


def record_interrupt_result(
    session_id: str,
    value: Any,
    *,
    state_store: Any,
    now: int | None = None,
) -> dict[str, Any]:
    request = _exact_fields(
        value, {"task_id", "task_ref", "target", "result"},
        "record-interrupt-result",
    )
    task_id, task_ref, target = _identity(request)
    result = request.get("result")
    if result not in INTERRUPT_RESULTS:
        raise ValueError("interrupt result 无效")
    observed_at = _now(now)
    outcome: dict[str, Any] = {}

    def record(state: dict[str, Any]) -> None:
        task = _task_for_identity(state, task_id, task_ref, target)
        phase = task.get("phase")
        if phase == "reconcile":
            outcome.update(_reconcile_outcome(task, task_id, task_ref))
        elif result == "unknown":
            if phase != "bound":
                raise StateConflictError("unknown interrupt result 只接受 bound task")
            enter_reconcile(task, "interrupt_unknown", observed_at)
            outcome.update(_reconcile_outcome(task, task_id, task_ref))
        elif result == "failed":
            if phase != "bound":
                raise StateConflictError("failed interrupt result 只接受 bound task")
            if task.get("interrupt_fact", {}).get("result") == "failed":
                outcome.update(
                    result="already_recorded", task_id=task_id,
                    task_ref=task_ref, target=target,
                )
            else:
                task["interrupt_fact"] = {
                    "result": "failed",
                    "observed_at": observed_at,
                }
                task["updated_at"] = observed_at
                outcome.update(
                    result="failed", task_id=task_id, task_ref=task_ref,
                    target=target,
                )
        elif phase == "terminal":
            if task.get("interrupt_fact", {}).get("result") == "inactive":
                outcome.update(
                    result="already_terminal", task_id=task_id,
                    task_ref=task_ref, target=target,
                )
            else:
                task["interrupt_fact"] = {
                    "result": "inactive",
                    "observed_at": observed_at,
                }
                task["updated_at"] = observed_at
                outcome.update(
                    result="terminal_confirmed", task_id=task_id,
                    task_ref=task_ref, target=target,
                )
        elif phase != "bound":
            raise StateConflictError("inactive interrupt result 只接受 bound/terminal task")
        else:
            task["phase"] = "terminal"
            task["interrupt_fact"] = {
                "result": "inactive",
                "observed_at": observed_at,
            }
            task["terminal_fact"] = {
                "source": "interrupt",
                "status": "inactive",
                "observed_at": observed_at,
            }
            task["updated_at"] = observed_at
            outcome.update(
                result="terminal", task_id=task_id, task_ref=task_ref,
                target=target,
            )
        prune_closed_tasks(state)

    state_store.update(session_id, record)
    return outcome


def close_task(
    session_id: str,
    value: Any,
    *,
    state_store: Any,
    now: int | None = None,
) -> dict[str, Any]:
    request = _exact_fields(
        value, {"task_id", "task_ref", "reason"}, "close-task"
    )
    task_id = request.get("task_id")
    task_ref = request.get("task_ref")
    reason = request.get("reason")
    if not _text(task_id, 256) or not _text(task_ref, 20) or not _text(reason, 1024):
        raise ValueError("close-task 字段无效")
    closed_at = _now(now)
    outcome: dict[str, Any] = {}

    def close(state: dict[str, Any]) -> None:
        task = state["tasks"].get(task_id)
        if not isinstance(task, dict) or task.get("task_ref") != task_ref:
            raise StateConflictError("close-task task_id/task_ref 不匹配")
        if task.get("phase") == "closed":
            if task.get("close_reason") != reason:
                raise StateConflictError("closed task 的 close reason 已由首次 close 固定")
            outcome.update(
                result="already_closed", task_id=task_id, task_ref=task_ref,
                target=task.get("target"),
            )
        else:
            preserved = _preserved_facts(task)
            task.clear()
            task.update(
                preserved,
                phase="closed",
                updated_at=closed_at,
                close_reason=reason,
                closed_at=closed_at,
            )
            outcome.update(
                result="closed", task_id=task_id, task_ref=task_ref,
                target=task.get("target"),
            )
        outcome["pruned_task_ids"] = list(prune_closed_tasks(state))

    state_store.update(session_id, close)
    return outcome


__all__ = [
    "close_task",
    "enter_reconcile",
    "prune_closed_tasks",
    "record_call_result",
    "record_interrupt_result",
    "record_platform_observation",
    "record_terminal_notification",
]
