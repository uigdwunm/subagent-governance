"""Composition service for preparing a state-v9 governed native dispatch."""

from __future__ import annotations

import copy
import secrets
import time
from typing import Any, Callable

try:
    from scripts.governance_context import verify_context_manifest
    from scripts.governance_contracts import contract_digest, contract_from_input
    from scripts.governance_dispatch import initial_task_record
    from scripts.governance_dispatch_identity import (
        build_task_name, normalize_semantic_name, select_task_ref,
    )
    from scripts.governance_dispatch_rendering import (
        render_dispatch_user_message, spawn_args,
    )
    from scripts.governance_errors import DispatchPreparationError
    from scripts.governance_lifecycle import prune_closed_tasks
    from scripts.governance_semantics import PREPARED_EXPIRY_SECONDS
    from scripts.governance_state_store import StateStore
except ModuleNotFoundError:
    from governance_context import verify_context_manifest
    from governance_contracts import contract_digest, contract_from_input
    from governance_dispatch import initial_task_record
    from governance_dispatch_identity import build_task_name, normalize_semantic_name, select_task_ref
    from governance_dispatch_rendering import render_dispatch_user_message, spawn_args
    from governance_errors import DispatchPreparationError
    from governance_lifecycle import prune_closed_tasks
    from governance_semantics import PREPARED_EXPIRY_SECONDS
    from governance_state_store import StateStore


def prepare_dispatch(
    contract_value: Any,
    session_id: str,
    *,
    state_store: StateStore | None = None,
    task_id_factory: Callable[[], str] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    if not isinstance(session_id, str) or session_id != session_id.strip() or not session_id or len(session_id) > 1024:
        raise DispatchPreparationError("session_id 必须是非空、无首尾空白且不超过 1024 字符的字符串")
    try:
        contract = contract_from_input(contract_value)
    except ValueError as exc:
        raise DispatchPreparationError(f"TaskContract v2 无效：{exc}") from exc
    manifest = contract.context.get("verified")
    try:
        verification = verify_context_manifest(manifest) if manifest is not None else None
    except Exception as exc:
        raise DispatchPreparationError(f"verified context 校验失败：{exc}") from exc
    created_at = int(time.time()) if now is None else now
    if isinstance(created_at, bool) or not isinstance(created_at, int) or created_at < 0:
        raise DispatchPreparationError("now 必须是非负整数")
    store = state_store or StateStore()
    factory = task_id_factory or (lambda: "sg-" + secrets.token_hex(16))
    result: dict[str, Any] = {}

    def insert(state: dict[str, Any]) -> None:
        prune_closed_tasks(state)
        occupied_refs = {
            task["task_ref"] for task in state["tasks"].values() if isinstance(task, dict)
        }
        task_id = ""
        task_ref = None
        for _ in range(2):
            candidate = factory()
            if not isinstance(candidate, str) or candidate != candidate.strip() or not candidate or len(candidate) > 256:
                raise DispatchPreparationError("task_id_factory 必须返回不超过 256 字符的非空规范字符串")
            if candidate in state["tasks"]:
                continue
            candidate_ref = select_task_ref(candidate, occupied_refs)
            if candidate_ref is not None:
                task_id, task_ref = candidate, candidate_ref
                break
        if task_ref is None:
            raise DispatchPreparationError("无法生成唯一 task_id/task_ref")
        semantic_name = normalize_semantic_name(contract.objective)
        task_name = build_task_name(contract.profile, semantic_name, task_ref)
        record = initial_task_record(
            task_ref, contract, task_name, verification, created_at,
            expires_at=created_at + PREPARED_EXPIRY_SECONDS,
        )
        state["tasks"][task_id] = record
        native = spawn_args(contract, task_name, verification)
        result.update(
            task_id=task_id,
            task_ref=task_ref,
            task_name=task_name,
            contract=contract.to_record(),
            contract_digest=contract_digest(contract),
            context_verification=copy.deepcopy(verification),
            user_message=render_dispatch_user_message(contract, verification),
            dispatch_prompt=native["message"],
            spawn_args=native,
        )

    try:
        store.update(session_id, insert, admission="new_task")
    except DispatchPreparationError:
        raise
    except Exception as exc:
        # A replace can commit before a readback error is reported.  Recover
        # only this exact newly prepared task; never search or infer by time.
        try:
            state = store.read(session_id)
            task_id = result.get("task_id")
            task = state["tasks"].get(task_id) if isinstance(task_id, str) else None
            if (
                isinstance(task, dict)
                and task.get("phase") == "prepared"
                and task.get("task_ref") == result.get("task_ref")
                and task.get("contract_digest") == result.get("contract_digest")
                and task.get("prepared", {}).get("expected_native_parameters")
                == {
                    "task_name": result.get("spawn_args", {}).get("task_name"),
                    "message": result.get("spawn_args", {}).get("message"),
                    "fork_turns": result.get("spawn_args", {}).get("fork_turns"),
                    "model": result.get("spawn_args", {}).get("model"),
                    "reasoning_effort": result.get("spawn_args", {}).get("reasoning_effort"),
                }
            ):
                result["warning"] = "prepare write reported an error after exact committed readback"
                return result
        except Exception:
            pass
        raise DispatchPreparationError(f"prepare-dispatch 单一 ledger 写入失败：{exc}") from exc
    return result


__all__ = ["prepare_dispatch"]
