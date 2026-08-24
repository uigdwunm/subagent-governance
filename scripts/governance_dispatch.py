"""Dispatch transactions over StateStore and PreparedContractStore.

The two stores are intentionally not treated as an atomic transaction.  Every
operation records exact before/after snapshots and compensates only snapshots
written by that same operation.  Hook and CLI response formatting stay out of
this domain module.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable

try:
    from scripts.governance_errors import (
        PreparedContractConflictError, PreparedContractValidationError, StateConflictError, StateValidationError,
    )
    from scripts.governance_contracts import TaskContract, contract_digest, contract_from_input, contract_summary
    from scripts.governance_execution import (
        apply_canonical_execution_update, canonical_execution_for_attempt,
        close_attempt_record, dispatch_reliably_not_created, execution_is_closed, identity_status,
        spawn_observation,
    )
    from scripts.governance_semantics import RETENTION_SECONDS, RETRY_LIMITS
    from scripts.governance_state import initial_plane_records
    from scripts.governance_dispatch_identity import parse_task_name
except ModuleNotFoundError:
    from governance_errors import (
        PreparedContractConflictError, PreparedContractValidationError, StateConflictError, StateValidationError,
    )
    from governance_contracts import TaskContract, contract_digest, contract_from_input, contract_summary
    from governance_execution import (
        apply_canonical_execution_update, canonical_execution_for_attempt,
        close_attempt_record, dispatch_reliably_not_created, execution_is_closed, identity_status,
        spawn_observation,
    )
    from governance_semantics import RETENTION_SECONDS, RETRY_LIMITS
    from governance_state import initial_plane_records
    from governance_dispatch_identity import parse_task_name


@dataclass(frozen=True)
class DispatchCleanupResult:
    state_status: str
    prepared_status: str
    errors: tuple[str, ...] = ()


def merge_initial_rollback_health(health: dict[str, Any], marker: dict[str, Any]) -> None:
    """Record the newest rollback warning without downgrading worse health."""
    status_rank = {"ok": 0, "degraded": 1, "unavailable": 2}
    if status_rank.get(str(health.get("status")), 0) < status_rank["degraded"]:
        health["status"] = "degraded"
    field = "initial_preparation_rollback"
    existing = health.get(field)
    existing_at = existing.get("observed_at") if isinstance(existing, dict) else None
    observed_at = marker.get("observed_at")
    if field not in health or not isinstance(existing_at, int) or not isinstance(observed_at, int) or existing_at <= observed_at:
        health[field] = copy.deepcopy(marker)


def mark_initial_rollback_incomplete(
    session_id: str, prepared: dict[str, Any], state_store: Any, observed_task: dict[str, Any], *, error: str, now: int,
) -> bool:
    """Mark an exact divergent initial state for manual reconciliation."""
    task_id, attempt = str(prepared["task_id"]), int(prepared["attempt"])

    def mark(state: dict[str, Any]) -> None:
        task = state.get("tasks", {}).get(task_id)
        record = canonical_execution_for_attempt(task, attempt) if isinstance(task, dict) else None
        if not isinstance(task, dict) or not isinstance(record, dict):
            raise StateConflictError("rollback-incomplete task/attempt 已不存在，无法持久化 reconcile 标记")
        marker = {
            "status": "rollback_incomplete", "task_ref": str(prepared["task_ref"]),
            "observed_at": now, "error": str(error)[:600],
        }
        apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
        record["initial_preparation_rollback"] = copy.deepcopy(marker)
        previous = record.get("updated_at")
        record["updated_at"] = max(previous, now) if isinstance(previous, int) and not isinstance(previous, bool) else now
        health = state.get("health")
        if not isinstance(health, dict):
            raise StateValidationError("治理状态字段 health 必须是对象")
        merge_initial_rollback_health(health, marker)
        return True

    return state_store.compare_and_set(
        session_id, lambda state: state.get("tasks", {}).get(task_id) == observed_task,
        mark, required_fields=("tasks", "tombstones"),
    )


def cleanup_initial_attempt(
    session_id: str, prepared: dict[str, Any], state_store: Any, *, error_context: str, now: int,
) -> dict[str, Any]:
    """Compensate an initial prepare only when its complete post-state remains exact."""
    task_id, expected_task = str(prepared["task_id"]), initial_task_post_state(prepared)
    errors: list[str] = []
    try:
        state = state_store.read(session_id, required_fields=("tasks", "tombstones"))
    except Exception as exc:
        return {"safe_for_prepared_delete": False, "task_status": "unknown", "marked": False, "errors": [f"StateStore readback failure：{exc}"]}
    current_task = state.get("tasks", {}).get(task_id)
    if current_task is None:
        return {"safe_for_prepared_delete": True, "task_status": "absent", "marked": False, "errors": errors}
    if current_task == expected_task:
        try:
            state_store.compare_and_set(
                session_id, lambda value: value.get("tasks", {}).get(task_id) == expected_task,
                lambda value: value["tasks"].pop(task_id), required_fields=("tasks", "tombstones"),
            )
            return {"safe_for_prepared_delete": True, "task_status": "deleted", "marked": False, "errors": errors}
        except Exception as exc:
            errors.append(f"StateStore task cleanup failure：{exc}")
            try:
                state = state_store.read(session_id, required_fields=("tasks", "tombstones"))
            except Exception as readback_exc:
                errors.append(f"StateStore cleanup readback failure：{readback_exc}")
                return {"safe_for_prepared_delete": False, "task_status": "unknown", "marked": False, "errors": errors}
            current_task = state.get("tasks", {}).get(task_id)
            if current_task is None:
                return {"safe_for_prepared_delete": True, "task_status": "deleted_after_error", "marked": False, "errors": errors}
            if current_task != expected_task:
                errors.append("task cleanup 异常后完整 task 已发生并发变化")
    else:
        errors.append("完整 initial task post-state 不匹配，检测到并发变化")
    marked = False
    if isinstance(current_task, dict):
        try:
            marked = mark_initial_rollback_incomplete(
                session_id, prepared, state_store, copy.deepcopy(current_task),
                error=f"{error_context}；{'；'.join(errors)}", now=now,
            )
        except Exception as exc:
            errors.append(f"rollback-incomplete reconcile 标记失败：{exc}")
    return {"safe_for_prepared_delete": False, "task_status": "diverged" if current_task != expected_task else "retained", "marked": marked, "errors": errors}


def initial_task_record(
    attempt: int, task_ref: str, task_name: str, contract: TaskContract, created_at: int,
) -> dict[str, Any]:
    """Build the sole canonical initial post-state for an execution."""
    execution = {
        "task_ref": task_ref, "task_name": task_name,
        "resolved_mode": contract.resolved_mode, "contract_summary": contract_summary(contract),
        "contract_digest": contract_digest(contract), **initial_plane_records(),
        "spawn_retry_count": 0, "recovery_count": 0, "updated_at": created_at,
    }
    return {"managed": True, "work_item": {"lifecycle": "open", "current_attempt": attempt}, "executions": {str(attempt): execution}}


def initial_task_post_state(prepared: dict[str, Any]) -> dict[str, Any]:
    if prepared.get("dispatch_operation") != "initial_spawn":
        raise PreparedContractValidationError("只有 initial PreparedContract 可以重建 initial task post-state")
    contract = contract_from_input(prepared.get("contract"))
    expected = initial_task_record(int(prepared["attempt"]), str(prepared["task_ref"]), str(prepared["task_name"]), contract, int(prepared["created_at"]))
    execution = expected["executions"][str(prepared["attempt"])]
    if prepared.get("attempt") != 1 or prepared.get("resolved_mode") != execution.get("resolved_mode") or prepared.get("contract_digest") != execution.get("contract_digest"):
        raise PreparedContractValidationError("initial PreparedContract 无法确定性绑定 canonical task post-state")
    return expected


def dispatch_admission_error(task: dict[str, Any], source_attempt: int) -> str | None:
    work_item = task.get("work_item")
    if not isinstance(work_item, dict):
        return "managed task 缺少 canonical work_item"
    if work_item.get("lifecycle") != "open":
        return "work item 已关闭或 tombstoned，禁止新增或重派 execution"
    source = canonical_execution_for_attempt(task, source_attempt)
    if not isinstance(source, dict):
        return "来源 execution 不存在"
    if execution_is_closed(source):
        return "来源 execution 已关闭，禁止新增或重派 execution"
    return None


def _ensure_task(state: dict[str, Any], task_id: str) -> dict[str, Any]:
    tasks = state.get("tasks")
    task = tasks.get(task_id) if isinstance(tasks, dict) else None
    if not isinstance(task, dict) or task.get("managed") is not True:
        raise StateConflictError("找不到目标 managed task")
    return task


def _claim_prepared(
    session_id: str, task_ref: str, tool_use_id: str, claimed_at: int,
    prepared: dict[str, Any], prepared_store: Any,
) -> dict[str, Any]:
    claimed = copy.deepcopy(prepared)
    claimed.update(consumed=True, tool_use_id=tool_use_id, claimed_at=claimed_at)
    try:
        prepared_store.compare_and_set(
            session_id, task_ref, lambda value: value == prepared,
            lambda value: (value.clear(), value.update(copy.deepcopy(claimed))),
        )
    except Exception as exc:
        # A write can persist and then report an error.  Restore only if the
        # current record still is this exact claim; otherwise preserve the
        # newer evidence and surface degraded state to the caller.
        try:
            _restore_prepared(session_id, task_ref, prepared_store, prepared, claimed)
        except Exception as recovery_exc:
            raise PreparedContractConflictError(
                f"PreparedContract claim 失败且补偿未完成，治理状态 degraded：{recovery_exc}"
            ) from exc
        raise
    return claimed


def _restore_prepared(
    session_id: str, task_ref: str, prepared_store: Any,
    before: dict[str, Any], claimed: dict[str, Any],
) -> str:
    current = prepared_store.read(session_id, task_ref)
    if current == before:
        return "not_persisted"
    if current != claimed:
        raise PreparedContractConflictError("PreparedContract claim 后发生并发变化，无法安全恢复未消费状态")
    prepared_store.compare_and_set(
        session_id, task_ref, lambda value: value == claimed,
        lambda value: (value.clear(), value.update(copy.deepcopy(before))),
    )
    return "restored"


def _rollback_state_claim(
    session_id: str, task_id: str, state_store: Any,
    before_task: dict[str, Any] | None, claimed_task: dict[str, Any] | None,
) -> str:
    if not isinstance(before_task, dict) or not isinstance(claimed_task, dict):
        return "not_observed"
    current = state_store.read(session_id, required_fields=("tasks", "tombstones"))
    task = current.get("tasks", {}).get(task_id)
    if task == before_task:
        return "not_persisted"
    if task != claimed_task:
        raise StateConflictError("spawn claim 已持久化后发生并发变化，无法安全恢复 pre-claim 状态")
    state_store.compare_and_set(
        session_id, lambda state: state.get("tasks", {}).get(task_id) == claimed_task,
        lambda state: state["tasks"].update({task_id: copy.deepcopy(before_task)}),
        required_fields=("tasks", "tombstones"),
    )
    return "restored"


def claim_spawn(
    session_id: str, task_ref: str, tool_use_id: str, claimed_at: int,
    prepared: dict[str, Any], state_store: Any, prepared_store: Any,
) -> dict[str, Any]:
    """Claim both records for one native spawn or restore only exact snapshots."""
    task_id, attempt = str(prepared["task_id"]), int(prepared["attempt"])
    task_name, mode = str(prepared["task_name"]), str(prepared["resolved_mode"])
    desired_retry_count, operation = int(prepared["spawn_retry_count"]), str(prepared["dispatch_operation"])
    claimed_prepared = _claim_prepared(session_id, task_ref, tool_use_id, claimed_at, prepared, prepared_store)
    snapshots: dict[str, Any] = {}
    try:
        state_before = state_store.read(session_id, required_fields=("tasks", "tombstones"))
        before_task = state_before.get("tasks", {}).get(task_id)
        if not isinstance(before_task, dict):
            raise StateConflictError("StateStore 中不存在匹配的 claim task")
        snapshots["before_task"] = copy.deepcopy(before_task)

        def claim(state: dict[str, Any]) -> None:
            task = _ensure_task(state, task_id)
            target = canonical_execution_for_attempt(task, attempt)
            if not isinstance(target, dict) or target.get("task_ref") != task_ref or target.get("task_name") != task_name or target.get("resolved_mode") != mode:
                raise StateConflictError("StateStore 中不存在匹配的 task/attempt/task_ref")
            admission = dispatch_admission_error(task, attempt)
            if admission:
                raise StateConflictError(admission)
            if operation == "spawn_retry":
                if not (spawn_observation(target) == "failed" and identity_status(target) == "unconfirmed" and dispatch_reliably_not_created(target) and target.get("spawn_retry_count") == desired_retry_count - 1):
                    raise StateConflictError("spawn retry 状态或计数不匹配")
            elif operation == "initial_spawn":
                if spawn_observation(target) is not None or target.get("spawn_retry_count") != 0:
                    raise StateConflictError("初始 spawn 状态已变化")
            else:
                raise StateConflictError(f"未知 dispatch operation：{operation}")
            apply_canonical_execution_update(target, "dispatch_tool_use_id", tool_use_id)
            target["spawn_retry_count"] = desired_retry_count
            apply_canonical_execution_update(target, "dispatch_response", None)
            apply_canonical_execution_update(target, "closure_parent_action", "retry_spawn" if operation == "spawn_retry" else None)
            target["updated_at"] = claimed_at

        expected_state = copy.deepcopy(state_before)
        claim(expected_state)
        snapshots["claimed_task"] = copy.deepcopy(expected_state["tasks"].get(task_id))
        if not isinstance(snapshots["claimed_task"], dict):
            raise StateConflictError("spawn claim 无法构造 canonical task post-state")
        # StateStore.update retains the existing fault-injection and
        # persist-then-raise semantics.  `claim` itself revalidates the
        # canonical task under the store lock; compensation remains exact.
        state_store.update(session_id, claim, required_fields=("tasks", "tombstones"))
        after = state_store.read(session_id, required_fields=("tasks", "tombstones"))
        if after["tasks"].get(task_id) != snapshots["claimed_task"]:
            raise StateConflictError("spawn claim 写入后无法回读 canonical task")
        if prepared_store.read(session_id, task_ref) != claimed_prepared:
            raise PreparedContractConflictError("PreparedContract claim 写入后发生并发变化")
    except Exception as exc:
        errors: list[str] = []
        try:
            _rollback_state_claim(session_id, task_id, state_store, snapshots.get("before_task"), snapshots.get("claimed_task"))
        except Exception as rollback_exc:
            errors.append(f"StateStore claim 回滚失败：{rollback_exc}")
        if not errors:
            try:
                _restore_prepared(session_id, task_ref, prepared_store, prepared, claimed_prepared)
            except Exception as rollback_exc:
                errors.append(f"PreparedContract unclaim 失败：{rollback_exc}")
        if errors:
            raise StateConflictError(f"{exc}；治理状态 degraded：{'；'.join(errors)}") from exc
        if isinstance(exc, StateConflictError) and operation == "spawn_retry":
            cleanup = discard_retry_prepared_exact(session_id, prepared, prepared_store)
            if cleanup.errors:
                raise StateConflictError(
                    f"{exc}；governance degraded：retry exact cleanup failed：{'；'.join(cleanup.errors)}"
                ) from exc
        raise
    return claimed_prepared


def discard_retry_prepared_exact(session_id: str, prepared: dict[str, Any], prepared_store: Any) -> DispatchCleanupResult:
    """Compensate only the exact retry record created by this transaction."""
    try:
        deleted = prepared_store.delete_if(
            session_id, str(prepared["task_ref"]), lambda value: value == prepared
        )
    except Exception as exc:
        return DispatchCleanupResult("unchanged", "retained", (str(exc),))
    return DispatchCleanupResult("unchanged", "deleted" if deleted else "absent")


def observe_spawn_post_tool(
    session_id: str, prepared: dict[str, Any], observation: dict[str, Any],
    observed_at: int, state_store: Any, prepared_store: Any,
) -> str | None:
    """Persist a normalized spawn observation, then exactly shrink its credential."""
    task_id, attempt, task_ref = str(prepared["task_id"]), int(prepared["attempt"]), str(prepared["task_ref"])
    tool_use_id = prepared.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        raise PreparedContractConflictError("claimed PreparedContract 缺少 tool_use_id")
    reported = observation.get("observation")
    if reported not in {"success", "failed", "unknown"}:
        raise ValueError("normalized spawn observation 无效")
    resolution = {"positive_evidence_preserved": False}

    def predicate(state: dict[str, Any]) -> bool:
        record = canonical_execution_for_attempt(state.get("tasks", {}).get(task_id), attempt)
        return bool(record and record.get("task_ref") == task_ref and record["dispatch_record"].get("tool_use_id") == tool_use_id and spawn_observation(record) is None)

    def update(state: dict[str, Any]) -> None:
        task = _ensure_task(state, task_id)
        record = canonical_execution_for_attempt(task, attempt)
        assert record is not None
        positive = reported == "failed" and bool(
            record.get("dispatch_record", {}).get("dispatch_target")
            and record.get("observation_record", {}).get("observed_state") in {"active", "terminal"}
        )
        resolution["positive_evidence_preserved"] = positive
        actual = "unknown" if positive else reported
        apply_canonical_execution_update(record, "dispatch_response", actual)
        record["updated_at"] = observed_at
        if positive:
            apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
        elif actual == "failed":
            apply_canonical_execution_update(record, "observed_execution_status", "stopped" if record.get("spawn_retry_count") == RETRY_LIMITS["spawn"] else "not_started")
            retries = int(record.get("spawn_retry_count") or 0)
            apply_canonical_execution_update(record, "closure_parent_action", "retry_spawn" if retries == 0 else "ask_user" if retries == 1 else "decide_disposition")
        else:
            apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
            apply_canonical_execution_update(record, "dispatch_target", observation.get("canonical_path"))

    state_store.compare_and_set(session_id, predicate, update)
    if reported == "failed" and not resolution["positive_evidence_preserved"]:
        # This is deliberately an exact delete of the claimed record.  A
        # concurrently replaced/observed credential remains evidence.
        prepared_store.delete_if(session_id, task_ref, lambda value: value == prepared)
    else:
        prepared_store.compare_and_set(
            session_id, task_ref,
            lambda value: value == prepared,
            lambda value: value.update({"post_observed_at": observed_at}),
        )
    if resolution["positive_evidence_preserved"]:
        return "迟到 spawn failure 与已绑定的 canonical active/terminal 事实冲突；已保留 observation/identity，并进入 reconcile。"
    return None


def prepare_initial_transaction(
    session_id: str, prepared: dict[str, Any], task_id: str, initial_task: dict[str, Any],
    state_store: Any, prepared_store: Any, task_ref_is_occupied: Callable[[dict[str, Any]], bool],
) -> None:
    """Write initial credential then state, and read both exact records back."""
    task_ref = str(prepared["task_ref"])
    prepared_store.create(prepared)
    state_store.compare_and_set(
        session_id,
        lambda state: task_id not in state["tasks"] and not task_ref_is_occupied(state),
        lambda state: state["tasks"].update({task_id: copy.deepcopy(initial_task)}),
        required_fields=("tasks", "tombstones"), admission="new_task",
    )
    if prepared_store.read(session_id, task_ref) != prepared:
        raise PreparedContractConflictError("initial PreparedContract 写入后发生并发变化")
    state = state_store.read(session_id, required_fields=("tasks", "tombstones"))
    if state.get("tasks", {}).get(task_id) != initial_task:
        raise StateConflictError("initial StateStore 写入后发生并发变化")


def prepare_retry_transaction(
    session_id: str, prepared: dict[str, Any], state_store: Any, prepared_store: Any,
    verify_state: Callable[[dict[str, Any]], None],
) -> None:
    """Create a retry capability exclusively and compensate it exactly on failure."""
    task_ref = str(prepared["task_ref"])
    prepared_store.create(prepared)  # exclusive create; existing evidence wins
    try:
        state_store.update(session_id, verify_state, required_fields=("tasks", "tombstones"))
        if prepared_store.read(session_id, task_ref) != prepared:
            raise PreparedContractConflictError("spawn retry PreparedContract 写入后发生并发变化")
    except Exception:
        cleanup = discard_retry_prepared_exact(session_id, prepared, prepared_store)
        if cleanup.errors:
            raise PreparedContractConflictError(
                "spawn retry 准备失败且 exact PreparedContract 回滚不完整：" + "；".join(cleanup.errors)
            )
        raise


def reconcile_claimed_spawn(
    session_id: str, prepared: dict[str, Any], current_time: int,
    claimed_retention: int, state_store: Any, prepared_store: Any,
) -> bool:
    """Mark a stale claimed spawn unknown without overwriting newer facts.

    The StateStore CAS is committed first.  The prepared record is then
    changed only if it remains the exact claim snapshot, making replay and a
    racing PostTool observation safe.
    """
    claimed_at = prepared.get("claimed_at")
    if (
        not isinstance(claimed_at, int)
        or prepared.get("post_observed_at") is not None
        or claimed_at > current_time - claimed_retention
    ):
        return False
    task_id, attempt, task_ref = str(prepared["task_id"]), int(prepared["attempt"]), str(prepared["task_ref"])
    tool_use_id = prepared.get("tool_use_id")

    def predicate(state: dict[str, Any]) -> bool:
        record = canonical_execution_for_attempt(state.get("tasks", {}).get(task_id), attempt)
        return bool(record and record.get("task_ref") == task_ref and record["dispatch_record"].get("tool_use_id") == tool_use_id and spawn_observation(record) is None)

    def mark_unknown(state: dict[str, Any]) -> None:
        task = _ensure_task(state, task_id)
        record = canonical_execution_for_attempt(task, attempt)
        assert record is not None
        apply_canonical_execution_update(record, "dispatch_response", "unknown")
        apply_canonical_execution_update(record, "observed_execution_status", "not_started")
        apply_canonical_execution_update(record, "closure_parent_action", "reconcile")
        record["updated_at"] = current_time

    try:
        state_store.compare_and_set(session_id, predicate, mark_unknown)
    except StateConflictError:
        return False
    prepared_store.compare_and_set(
        session_id, task_ref, lambda value: value == prepared,
        lambda value: value.update({"post_observed_at": current_time}),
    )
    return True


def expired_unclaimed_initial_without_credential(task: Any, *, prepared_refs: set[str], cutoff: int) -> bool:
    """Prove an untouched initial state can no longer create a native Agent."""
    if not isinstance(task, dict) or task.get("managed") is not True:
        return False
    if task.get("work_item") != {"current_attempt": 1, "lifecycle": "open"}:
        return False
    executions = task.get("executions")
    if not isinstance(executions, dict) or set(executions) != {"1"}:
        return False
    execution = executions.get("1")
    if not isinstance(execution, dict):
        return False
    task_ref, updated_at = execution.get("task_ref"), execution.get("updated_at")
    if not isinstance(task_ref, str) or not task_ref or task_ref in prepared_refs or isinstance(updated_at, bool) or not isinstance(updated_at, int) or updated_at > cutoff:
        return False
    if execution.get("spawn_retry_count") != 0 or execution.get("recovery_count") != 0:
        return False
    if any(field in execution for field in ("pending_action", "last_lifecycle_operation", "initial_preparation_rollback")):
        return False
    if execution.get("dispatch_record") != {"dispatch_state": "prepared", "dispatch_target": None, "tool_use_id": None}:
        return False
    if execution.get("observation_record") != {"observed_at": None, "observed_state": "not_observed", "source": None, "terminal_status": None}:
        return False
    if execution.get("closure_record") != {"closed_at": None, "parent_action": None, "reason": None}:
        return False
    parsed = parse_task_name(execution.get("task_name"))
    return bool(parsed is not None and parsed[2] == task_ref)


def close_expired_unclaimed_initials_without_credentials(
    session_id: str, *, state_store: Any, prepared_store: Any, now: int,
) -> int:
    """Tombstone only untouched, expired initial attempts with no credential."""
    prepared_refs = prepared_store.refs(session_id)
    state = state_store.read(session_id, required_fields=("tasks", "tombstones"))
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        raise StateValidationError("治理状态缺少 tasks 对象")
    cutoff = now - int(RETENTION_SECONDS["prepared_unclaimed"])
    candidates = [(str(task_id), copy.deepcopy(task)) for task_id, task in tasks.items() if expired_unclaimed_initial_without_credential(task, prepared_refs=prepared_refs, cutoff=cutoff)]
    closed = 0
    for task_id, expected_task in sorted(candidates):
        def close(current: dict[str, Any]) -> None:
            task = current["tasks"][task_id]
            close_attempt_record(current, task_id, 1, task["executions"]["1"], "automatic_close:expired_unclaimed_dispatch", now)
            task["work_item"]["lifecycle"] = "tombstoned"
        try:
            state_store.compare_and_set(
                session_id, lambda current: current.get("tasks", {}).get(task_id) == expected_task,
                close, required_fields=("tasks", "tombstones"),
            )
        except StateConflictError:
            continue
        closed += 1
    return closed


__all__ = [
    "DispatchCleanupResult", "claim_spawn", "cleanup_initial_attempt",
    "close_expired_unclaimed_initials_without_credentials", "dispatch_admission_error",
    "discard_retry_prepared_exact", "expired_unclaimed_initial_without_credential",
    "initial_task_post_state", "initial_task_record", "mark_initial_rollback_incomplete",
    "merge_initial_rollback_health", "observe_spawn_post_tool", "prepare_initial_transaction",
    "prepare_retry_transaction", "reconcile_claimed_spawn",
]
