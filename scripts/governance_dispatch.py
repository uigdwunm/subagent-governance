"""Single-ledger prepare/claim/confirm dispatch transitions for state-v9."""

from __future__ import annotations

import copy
import time
from typing import Any

try:
    from scripts.governance_context import verify_context_manifest
    from scripts.governance_contracts import (
        TaskContract, contract_digest, contract_from_input, contract_summary,
        spawn_digest,
    )
    from scripts.governance_dispatch_rendering import expected_native_parameters
    from scripts.governance_errors import StateConflictError
    from scripts.governance_lifecycle import enter_reconcile, prune_closed_tasks
except ModuleNotFoundError:
    from governance_context import verify_context_manifest
    from governance_contracts import TaskContract, contract_digest, contract_from_input, contract_summary, spawn_digest
    from governance_dispatch_rendering import expected_native_parameters
    from governance_errors import StateConflictError
    from governance_lifecycle import enter_reconcile, prune_closed_tasks


def _now(value: int | None) -> int:
    result = int(time.time()) if value is None else value
    if isinstance(result, bool) or not isinstance(result, int) or result < 0:
        raise ValueError("timestamp 必须是非负整数")
    return result


def initial_task_record(
    task_ref: str,
    contract: TaskContract,
    task_name: str,
    context_verification: dict[str, Any] | None,
    created_at: int,
    *,
    expires_at: int,
) -> dict[str, Any]:
    return {
        "task_ref": task_ref,
        "phase": "prepared",
        "contract_digest": contract_digest(contract),
        "contract_summary": contract_summary(contract),
        "created_at": created_at,
        "updated_at": created_at,
        "prepared": {
            "contract": contract.to_record(),
            "context_verification": copy.deepcopy(context_verification),
            "expected_native_parameters": expected_native_parameters(
                contract, task_name, context_verification
            ),
            "spawn_digest": spawn_digest(contract),
            "expires_at": expires_at,
        },
    }


def _find_by_ref(state: dict[str, Any], task_ref: str) -> tuple[str, dict[str, Any]]:
    matches = [
        (task_id, task)
        for task_id, task in state["tasks"].items()
        if isinstance(task, dict) and task.get("task_ref") == task_ref
    ]
    if len(matches) != 1:
        raise StateConflictError("当前 Session 不存在唯一匹配的 task_ref")
    return matches[0]


def _normalized_tool_input(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StateConflictError("spawn_agent tool_input 必须是对象")
    return {
        "task_name": value.get("task_name"),
        "message": value.get("message"),
        "fork_turns": value.get("fork_turns"),
        "model": value.get("model"),
        "reasoning_effort": value.get("reasoning_effort"),
    }


def claim_spawn(
    session_id: str,
    task_ref: str,
    tool_use_id: str,
    tool_input: dict[str, Any],
    *,
    state_store: Any,
    now: int | None = None,
) -> dict[str, Any]:
    claimed_at = _now(now)
    if not isinstance(tool_use_id, str) or not tool_use_id.strip() or len(tool_use_id) > 1024:
        raise StateConflictError("governed spawn 缺少有效 tool_use_id")
    outcome: dict[str, Any] = {}

    def claim(state: dict[str, Any]) -> None:
        prune_closed_tasks(state)
        task_id, task = _find_by_ref(state, task_ref)
        if task.get("phase") == "claimed":
            if task.get("claimed_tool_use_id") == tool_use_id:
                expected = task.get("prepared", {}).get("expected_native_parameters")
                if _normalized_tool_input(tool_input) != expected:
                    raise StateConflictError("重复 claim 的 native parameters 不一致")
                outcome.update(result="already_claimed", task_id=task_id, task_ref=task_ref)
                return
            raise StateConflictError("prepared capability 已被另一个原生调用消费")
        if task.get("phase") != "prepared":
            raise StateConflictError("只有 prepared task 可以被原生 spawn claim")
        capability = task.get("prepared")
        if not isinstance(capability, dict):
            raise StateConflictError("prepared task 缺少 capability")
        if capability.get("expires_at", -1) <= claimed_at:
            raise StateConflictError("prepared capability 已过期，请重新 prepare")
        if _normalized_tool_input(tool_input) != capability.get("expected_native_parameters"):
            raise StateConflictError("原生 spawn 参数与 prepared capability 不一致")
        contract = contract_from_input(capability.get("contract"))
        manifest = contract.context.get("verified")
        if manifest is not None:
            verification = verify_context_manifest(manifest)
            if verification != capability.get("context_verification"):
                raise StateConflictError("verified context 在 prepare 与 claim 之间发生变化")
        task["phase"] = "claimed"
        task["claimed_tool_use_id"] = tool_use_id
        task["claimed_at"] = claimed_at
        task["updated_at"] = claimed_at
        outcome.update(result="claimed", task_id=task_id, task_ref=task_ref)

    try:
        state_store.update(session_id, claim)
    except Exception:
        # Atomic replace can succeed before a readback/fsync error is reported.
        # Only the exact same claim is safe to treat as committed; otherwise the
        # governed native call remains denied.
        try:
            state = state_store.read(session_id)
            task_id, task = _find_by_ref(state, task_ref)
            expected = task.get("prepared", {}).get("expected_native_parameters")
            if (
                task.get("phase") == "claimed"
                and task.get("claimed_tool_use_id") == tool_use_id
                and expected == _normalized_tool_input(tool_input)
            ):
                outcome.update(
                    result="claimed_after_write_error",
                    task_id=task_id,
                    task_ref=task_ref,
                )
                return outcome
        except Exception:
            pass
        raise
    return outcome


def _validate_confirmation(value: Any) -> tuple[str, str, str]:
    if not isinstance(value, dict) or set(value) != {"task_id", "task_ref", "target"}:
        raise ValueError("confirm-dispatch 输入必须精确包含 task_id、task_ref、target")
    fields: list[str] = []
    for name, maximum in (("task_id", 256), ("task_ref", 20), ("target", 1024)):
        item = value.get(name)
        if not isinstance(item, str) or item != item.strip() or not item or len(item) > maximum:
            fields.append(name)
    if fields:
        raise ValueError("confirm-dispatch 字段无效：" + "、".join(fields))
    return value["task_id"], value["task_ref"], value["target"]


def confirm_dispatch(
    session_id: str,
    value: Any,
    *,
    state_store: Any,
    now: int | None = None,
) -> dict[str, Any]:
    task_id, task_ref, target = _validate_confirmation(value)
    observed_at = _now(now)
    outcome: dict[str, Any] = {}

    def confirm(state: dict[str, Any]) -> None:
        prune_closed_tasks(state)
        task = state["tasks"].get(task_id)
        if not isinstance(task, dict):
            raise StateConflictError("confirm-dispatch task_id 不存在于 exact Session")
        if task.get("task_ref") != task_ref:
            enter_reconcile(task, "dispatch_identity_mismatch", observed_at)
            outcome.update(result="reconcile", task_id=task_id, task_ref=task.get("task_ref"))
            return
        phase = task.get("phase")
        if phase == "bound":
            if task.get("target") == target:
                outcome.update(result="already_bound", task_id=task_id, task_ref=task_ref, target=target)
                return
            enter_reconcile(task, "dispatch_target_conflict", observed_at)
            outcome.update(result="reconcile", task_id=task_id, task_ref=task_ref, target=task.get("target"))
            return
        if phase == "reconcile":
            outcome.update(result="reconcile", task_id=task_id, task_ref=task_ref, target=task.get("target"))
            return
        if phase != "claimed":
            enter_reconcile(task, "dispatch_identity_mismatch", observed_at)
            outcome.update(result="reconcile", task_id=task_id, task_ref=task_ref)
            return
        common = {
            name: copy.deepcopy(task[name])
            for name in (
                "task_ref", "contract_digest", "contract_summary", "created_at"
            )
        }
        task.clear()
        task.update(
            common,
            phase="bound",
            updated_at=observed_at,
            target=target,
            bound_at=observed_at,
        )
        outcome.update(result="bound", task_id=task_id, task_ref=task_ref, target=target)

    state_store.update(session_id, confirm)
    return outcome


def record_dispatch_result(
    session_id: str,
    value: Any,
    *,
    state_store: Any,
    now: int | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"task_id", "task_ref", "result"}:
        raise ValueError("record-dispatch-result 输入字段无效")
    task_id = value.get("task_id")
    task_ref = value.get("task_ref")
    if not _text_identity(task_id, 256) or not _text_identity(task_ref, 20):
        raise ValueError("record-dispatch-result task_id/task_ref 无效")
    result = value.get("result")
    if result not in {"failed", "unknown"}:
        raise ValueError("record-dispatch-result 只接受 failed 或 unknown；success 使用 confirm-dispatch")
    observed_at = _now(now)
    outcome: dict[str, Any] = {}

    def record(state: dict[str, Any]) -> None:
        prune_closed_tasks(state)
        task = state["tasks"].get(task_id)
        if not isinstance(task, dict) or task.get("task_ref") != task_ref:
            raise StateConflictError("dispatch result task identity 不匹配")
        if task.get("phase") != "claimed":
            raise StateConflictError("dispatch result 只接受 claimed task")
        common = {
            name: copy.deepcopy(task[name])
            for name in ("task_ref", "contract_digest", "contract_summary", "created_at")
        }
        task.clear()
        if result == "failed":
            task.update(
                common, phase="closed", updated_at=observed_at,
                close_reason="dispatch_failed_not_created", closed_at=observed_at,
            )
        else:
            task.update(
                common, phase="reconcile", updated_at=observed_at,
                reconcile={"code": "dispatch_result_unknown", "observed_at": observed_at},
            )
        outcome.update(result=task["phase"], task_id=task_id, task_ref=task_ref)

    state_store.update(session_id, record)
    return outcome


def _text_identity(value: Any, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and bool(value)
        and len(value) <= maximum
    )


__all__ = ["claim_spawn", "confirm_dispatch", "initial_task_record", "record_dispatch_result"]
