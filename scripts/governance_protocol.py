"""Composition services for prepared dispatches.

These services join validated contracts, the two persistence stores, and the
dispatch transaction owner.  They are deliberately independent from Hook and
CLI transports.
"""
from __future__ import annotations

import copy
import secrets
import time
from typing import Any, Callable

try:
    from scripts.governance_context import verify_context_manifest
    from scripts.governance_contracts import contract_digest, contract_from_input
    from scripts.governance_dispatch import (
        cleanup_initial_attempt, dispatch_admission_error, initial_task_record, prepare_initial_transaction,
        prepare_retry_transaction,
    )
    from scripts.governance_dispatch_identity import build_task_name, parse_task_name, select_task_ref
    from scripts.governance_dispatch_rendering import render_dispatch_user_message, spawn_args
    from scripts.governance_errors import ContextVerificationError, DispatchPreparationError, StateConflictError
    from scripts.governance_execution import canonical_execution_for_attempt, dispatch_reliably_not_created, identity_status, spawn_observation
    from scripts.governance_prepared_store import PreparedContractStore, prepared_record, prepared_root_for_store
    from scripts.governance_state_store import StateStore
except ModuleNotFoundError:
    from governance_context import verify_context_manifest
    from governance_contracts import contract_digest, contract_from_input
    from governance_dispatch import cleanup_initial_attempt, dispatch_admission_error, initial_task_record, prepare_initial_transaction, prepare_retry_transaction
    from governance_dispatch_identity import build_task_name, parse_task_name, select_task_ref
    from governance_dispatch_rendering import render_dispatch_user_message, spawn_args
    from governance_errors import ContextVerificationError, DispatchPreparationError, StateConflictError
    from governance_execution import canonical_execution_for_attempt, dispatch_reliably_not_created, identity_status, spawn_observation
    from governance_prepared_store import PreparedContractStore, prepared_record, prepared_root_for_store
    from governance_state_store import StateStore


def _stores(state_store: StateStore | None, prepared_store: PreparedContractStore | None) -> tuple[StateStore, PreparedContractStore]:
    state = state_store or StateStore()
    return state, prepared_store or PreparedContractStore(prepared_root_for_store(state))


def _occupied_refs(session_id: str, state_store: StateStore, prepared_store: PreparedContractStore) -> set[str]:
    occupied = set(prepared_store.refs(session_id))
    state = state_store.read(session_id, required_fields=("tasks", "tombstones"))
    for task in state.get("tasks", {}).values():
        if not isinstance(task, dict):
            continue
        for record in (task.get("executions") or {}).values():
            if isinstance(record, dict) and isinstance(record.get("task_ref"), str):
                occupied.add(record["task_ref"])
    for record in state.get("tombstones", {}).values():
        if isinstance(record, dict) and isinstance(record.get("task_ref"), str):
            occupied.add(record["task_ref"])
    return occupied


def _result(task_id: str, attempt: int, task_ref: str, task_name: str, contract: Any, verification: dict[str, Any], native: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task_id, "attempt": attempt, "task_ref": task_ref,
        "task_name": task_name, "contract": contract.to_record(),
        "contract_digest": contract_digest(contract),
        "context_verification": copy.deepcopy(verification),
        "user_message": render_dispatch_user_message(contract, verification),
        "dispatch_prompt": native["message"], "spawn_args": native,
    }


def _exception_chain_text(error: BaseException) -> str:
    messages: list[str] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if str(current) and str(current) not in messages:
            messages.append(str(current))
        current = current.__cause__ or current.__context__
    return "；caused by：".join(messages)


def prepare_dispatch(contract_value: Any, session_id: str, *, state_store: StateStore | None = None, prepared_store: PreparedContractStore | None = None, task_id_factory: Callable[[], str] | None = None, now: int | None = None) -> dict[str, Any]:
    if not isinstance(session_id, str) or not session_id.strip():
        raise DispatchPreparationError("session_id 必须是非空字符串")
    contract = contract_from_input(contract_value)
    try:
        verification = verify_context_manifest(contract.context_manifest)
    except ContextVerificationError as exc:
        raise DispatchPreparationError(f"必需上下文验证失败：{exc}") from exc
    state, prepared_store = _stores(state_store, prepared_store)
    created_at = int(time.time()) if now is None else now
    factory = task_id_factory or (lambda: "sg-" + secrets.token_hex(16))
    occupied = _occupied_refs(session_id, state, prepared_store)
    task_id = ""
    task_ref = None
    for _attempt in range(2):
        candidate = factory()
        if not isinstance(candidate, str) or not candidate.strip():
            raise DispatchPreparationError("task_id_factory 必须返回非空字符串")
        candidate_ref = select_task_ref(candidate, 1, occupied)
        if candidate_ref is not None:
            task_id, task_ref = candidate, candidate_ref
            break
    if task_ref is None:
        raise DispatchPreparationError("两个新 task_id 均无法取得唯一 task_ref")
    task_name = build_task_name(contract.resolved_mode, contract.semantic_name, task_ref)
    native = spawn_args(contract, task_name, verification)
    prepared = prepared_record(session_id, task_id, 1, task_ref, task_name, contract, verification, native, created_at=created_at, spawn_retry_count=0, dispatch_operation="initial_spawn")
    initial = initial_task_record(1, task_ref, task_name, contract, created_at)
    try:
        prepare_initial_transaction(session_id, prepared, task_id, initial, state, prepared_store, lambda current: any(record.get("task_ref") == task_ref for task in current.get("tasks", {}).values() if isinstance(task, dict) for record in (task.get("executions") or {}).values() if isinstance(record, dict)))
    except Exception as exc:
        original_error = _exception_chain_text(exc)
        cleanup = cleanup_initial_attempt(
            session_id, prepared, state, error_context=original_error, now=created_at,
        )
        cleanup_errors = list(cleanup["errors"])
        prepared_cleanup_failed = False
        if cleanup["safe_for_prepared_delete"]:
            try:
                prepared_store.delete_if(session_id, task_ref, lambda value: value == prepared)
            except Exception as cleanup_exc:
                prepared_cleanup_failed = True
                cleanup_errors.append(
                    f"PreparedContract cleanup failure：{cleanup_exc}；task 已安全 absent，orphan PreparedContract retained"
                )
        if not cleanup["safe_for_prepared_delete"]:
            marker_status = "rollback-incomplete 已持久化为 action-required" if cleanup["marked"] else "rollback-incomplete 无法持久化 reconcile 标记"
            details = "；".join(cleanup_errors) or "无法确认 canonical task post-state"
            raise DispatchPreparationError(
                "受治理派发准备失败，治理状态 degraded / rollback-incomplete；"
                f"原始错误：{original_error}；{details}；{marker_status}；"
                "PreparedContract retained，可由显式 reconcile/expiry 重试"
            ) from exc
        if cleanup_errors:
            status = "治理状态 degraded / rollback-incomplete" if prepared_cleanup_failed else "治理状态 degraded，exact rollback 已完成但 cleanup error 可见"
            raise DispatchPreparationError(
                f"受治理派发准备失败，{status}；原始错误：{original_error}；{'；'.join(cleanup_errors)}"
            ) from exc
        if isinstance(exc, DispatchPreparationError):
            raise
        raise DispatchPreparationError(
            "受治理派发准备失败，exact rollback 已完成，未允许原生 spawn：" + original_error
        ) from exc
    return _result(task_id, 1, task_ref, task_name, contract, verification, native)


def prepare_spawn_retry(contract_value: Any, session_id: str, task_id: str, *, authorized: bool = False, state_store: StateStore | None = None, prepared_store: PreparedContractStore | None = None, now: int | None = None) -> dict[str, Any]:
    state, prepared_store = _stores(state_store, prepared_store)
    current = state.read(session_id, required_fields=("tasks", "tombstones"))
    task = current.get("tasks", {}).get(task_id)
    if not isinstance(task, dict) or task.get("managed") is not True:
        raise DispatchPreparationError(f"找不到受治理任务：{task_id}")
    work_item = task.get("work_item")
    attempt = work_item.get("current_attempt") if isinstance(work_item, dict) else None
    if not isinstance(attempt, int):
        raise DispatchPreparationError("canonical retry execution 不可读或不允许重派")
    admission = dispatch_admission_error(task, attempt)
    record = canonical_execution_for_attempt(task, attempt)
    if admission:
        raise DispatchPreparationError(admission)
    if not isinstance(record, dict):
        raise DispatchPreparationError("canonical retry execution 不可读或不允许重派")
    if spawn_observation(record) != "failed" or identity_status(record) != "unconfirmed" or not dispatch_reliably_not_created(record):
        raise DispatchPreparationError("只有明确 failed 且身份未确认的 spawn 才能同 attempt 重派")
    count = record.get("spawn_retry_count")
    desired = 1 if count == 0 else 2 if count == 1 and authorized else None
    if desired is None:
        raise DispatchPreparationError("最后一次同 attempt 重派需要用户明确授权或次数已经耗尽")
    contract = contract_from_input(contract_value)
    if contract_digest(contract) != record.get("contract_digest"):
        raise DispatchPreparationError("重派 TaskContract 与原 attempt 的完整契约不一致")
    try:
        verification = verify_context_manifest(contract.context_manifest)
    except ContextVerificationError as exc:
        raise DispatchPreparationError(f"重派必需上下文验证失败：{exc}") from exc
    task_ref, task_name = str(record.get("task_ref") or ""), str(record.get("task_name") or "")
    if parse_task_name(task_name) is None:
        raise DispatchPreparationError("原 attempt 缺少合法 task_name/task_ref")
    native = spawn_args(contract, task_name, verification)
    created_at = int(time.time()) if now is None else now
    prepared = prepared_record(session_id, task_id, attempt, task_ref, task_name, contract, verification, native, created_at=created_at, spawn_retry_count=desired, dispatch_operation="spawn_retry")
    baseline = record.get("updated_at")
    def verify(current_state: dict[str, Any]) -> None:
        fresh = canonical_execution_for_attempt(current_state.get("tasks", {}).get(task_id), attempt)
        if not isinstance(fresh, dict) or fresh.get("updated_at") != baseline or fresh.get("spawn_retry_count") != count:
            raise StateConflictError("spawn retry 前置状态已变化")
    try:
        prepare_retry_transaction(session_id, prepared, state, prepared_store, verify)
    except Exception as exc:
        raise DispatchPreparationError(f"spawn retry PreparedContract 写入失败：{exc}") from exc
    return _result(task_id, attempt, task_ref, task_name, contract, verification, native)


__all__ = ["prepare_dispatch", "prepare_spawn_retry"]
