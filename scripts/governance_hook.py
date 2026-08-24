"""Thin Hook transport router for governance domains.

The router classifies an external payload, constructs storage only once a
governance fact is required, and maps domain results to Hook JSON.  It owns no
persisted-state transition and never interprets raw platform responses.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any

try:
    from scripts.governance_context import verify_context_manifest
    from scripts.governance_contracts import contract_from_input
    from scripts.governance_dispatch import claim_spawn, observe_spawn_post_tool
    from scripts.governance_dispatch_identity import parse_task_name
    from scripts.governance_lifecycle import (
        _claim_pending_action, claimed_post_index_lookup, observe_agent_status_post_tool,
        observe_lifecycle_post_tool,
    )
    from scripts.governance_platform import (
        adapt_list_agents_response_result,
        adapt_spawn_response, spawn_response_shape,
    )
    from scripts.governance_prepared_store import PreparedContractStore, prepared_root_for_store
    from scripts.governance_spawn_post_probe import SpawnPostProbeStore, marker_record, probe_root_for_store, receipt_record
    from scripts.governance_execution import canonical_execution_for_attempt, spawn_observation
    from scripts.governance_semantics import RETENTION_SECONDS
    from scripts.governance_sessions import session_end, session_start, stop_advisory
    from scripts.governance_state_store import StateStore, UnavailableStateStore
except ModuleNotFoundError:
    from governance_context import verify_context_manifest
    from governance_contracts import contract_from_input
    from governance_dispatch import claim_spawn, observe_spawn_post_tool
    from governance_dispatch_identity import parse_task_name
    from governance_lifecycle import _claim_pending_action, claimed_post_index_lookup, observe_agent_status_post_tool, observe_lifecycle_post_tool
    from governance_platform import adapt_list_agents_response_result, adapt_spawn_response, spawn_response_shape
    from governance_prepared_store import PreparedContractStore, prepared_root_for_store
    from governance_spawn_post_probe import SpawnPostProbeStore, marker_record, probe_root_for_store, receipt_record
    from governance_execution import canonical_execution_for_attempt, spawn_observation
    from governance_semantics import RETENTION_SECONDS
    from governance_sessions import session_end, session_start, stop_advisory
    from governance_state_store import StateStore, UnavailableStateStore


def tool_kind(tool_name: str) -> str | None:
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
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


def _allow(updated_input: dict[str, Any], context: str | None = None) -> dict[str, Any]:
    output: dict[str, Any] = {"hookEventName": "PreToolUse", "permissionDecision": "allow", "updatedInput": updated_input}
    if context:
        output["additionalContext"] = context
    return {"hookSpecificOutput": output}


def _continue(message: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"continue": True}
    if message:
        result["systemMessage"] = message[:1800]
    return result


def _session_id(payload: dict[str, Any]) -> str:
    return str(payload.get("session_id") or "unknown")


def _store_or_unavailable() -> StateStore | UnavailableStateStore:
    try:
        return StateStore()
    except Exception as exc:
        return UnavailableStateStore(exc)


def _hook_lifecycle_result(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("decision") == "allow":
        updated = value.get("updated_input")
        return _allow(updated if isinstance(updated, dict) else {}, value.get("context"))
    return _deny(str(value.get("reason") or "受治理 lifecycle 操作被拒绝"))


def _handle_governed_spawn(payload: dict[str, Any], store: Any, task_name: str, parsed: tuple[str, str, str]) -> dict[str, Any]:
    tool_input = payload.get("tool_input")
    assert isinstance(tool_input, dict)
    if isinstance(store, UnavailableStateStore):
        return _deny("子 Agent 派发被阻止：PreparedContract 硬门禁不可用。")
    mode, _semantic_name, task_ref = parsed
    session_id = _session_id(payload)
    try:
        prepared_store = PreparedContractStore(prepared_root_for_store(store))
        prepared = prepared_store.read(session_id, task_ref)
        if prepared.get("consumed") is True:
            return _deny("子 Agent 派发被阻止：PreparedContract 已被消费，不能重复调用原生 spawn。")
        now = int(time.time())
        if prepared.get("created_at", 0) <= now - int(RETENTION_SECONDS["prepared_unclaimed"]):
            return _deny("子 Agent 派发被阻止：PreparedContract 已超过5分钟，请重新生成派发。")
        expected = prepared["native_parameters"]
        mismatches = [name for name in ("fork_turns", "model", "reasoning_effort") if tool_input.get(name) != expected.get(name)]
        if prepared.get("task_name") != task_name or prepared.get("resolved_mode") != mode:
            mismatches.append("task_name/resolved_mode")
        if mismatches:
            return _deny("子 Agent 派发被阻止：原生可观察参数与 PreparedContract 不一致：" + "、".join(mismatches))
        contract = contract_from_input(prepared["contract"])
        if verify_context_manifest(contract.context_manifest) != prepared.get("context_verification"):
            return _deny("子 Agent 派发被阻止：必需上下文在 prepare 与 spawn 之间发生变化，请重新生成派发。")
        tool_use_id = str(payload.get("tool_use_id") or "")
        if not tool_use_id:
            return _deny("子 Agent 派发被阻止：缺少 tool_use_id，无法单次消费 PreparedContract。")
        claim_spawn(session_id, task_ref, tool_use_id, now, prepared, store, prepared_store)
    except Exception as exc:
        return _deny(f"子 Agent 派发被阻止：PreparedContract 硬门禁失败：{exc}")
    context = f"Subagent Governance 已消费 task_ref={task_ref} 的派发凭证并完成发送前双门禁。"
    if getattr(store, "last_spawn_post_probe_warning", None) == "spawn_post_probe_unavailable":
        context += " spawn_post_probe_unavailable"
    return _allow(copy.deepcopy(tool_input), context)


def _spawn_probe_marker(payload: dict[str, Any], store: Any | None) -> dict[str, Any] | None:
    """Read an exact marker without creating any private directory or StateStore."""
    session_id = str(payload.get("session_id") or "")
    tool_use_id = str(payload.get("tool_use_id") or "")
    if not session_id or not tool_use_id:
        return None
    return SpawnPostProbeStore(probe_root_for_store(store)).lookup_marker(
        session_id, tool_use_id, now=int(payload.get("now") or time.time()),
    )


def _probe_marker_from_prepared(prepared: dict[str, Any]) -> dict[str, Any]:
    return marker_record(
        str(prepared["session_id"]), str(prepared["tool_use_id"]), str(prepared["task_id"]),
        int(prepared["attempt"]), str(prepared["task_ref"]), str(prepared["dispatch_operation"]),
        int(prepared["spawn_retry_count"]), claimed_at=int(prepared["claimed_at"]),
    )


def _record_spawn_probe_post(
    payload: dict[str, Any], state_store: Any | None, *, marker: dict[str, Any],
    tool_name_classification: str, admission_source: str,
) -> str | None:
    """Persist only P12-A mechanical diagnostics; canonical execution is read-only."""
    session_id, tool_use_id = str(payload.get("session_id") or ""), str(payload.get("tool_use_id") or "")
    now = int(payload.get("now") or time.time())
    probe_store = SpawnPostProbeStore(probe_root_for_store(state_store))
    try:
        receipt = receipt_record(marker, tool_name_classification, admission_source, recorded_at=now)
        probe_store.record_receipt(receipt, now=now, tool_use_id=tool_use_id)
    except Exception:
        return "spawn_post_probe_handler_failed"

    def advance(**changes: Any) -> bool:
        receipt.update(changes)
        receipt["updated_at"] = now
        try:
            probe_store.record_receipt(receipt, now=now, tool_use_id=tool_use_id)
            return True
        except Exception:
            return False

    try:
        prepared = PreparedContractStore(prepared_root_for_store(state_store)).find_claimed(session_id, tool_use_id)
        if prepared is None:
            if not advance(claim_check="prepared_missing", handler_stage="claim_checked"):
                return "spawn_post_probe_handler_failed"
            return None if advance(handler_stage="completed") else "spawn_post_probe_handler_failed"
        expected = _probe_marker_from_prepared(prepared)
        marker_fields = ("session_id", "tool_use_id", "task_id", "attempt", "task_ref", "dispatch_operation", "spawn_retry_count", "claimed_at")
        if any(marker.get(field) != expected.get(field) for field in marker_fields):
            if not advance(claim_check="validation_failed", handler_stage="claim_checked"):
                return "spawn_post_probe_handler_failed"
            return None if advance(handler_stage="completed") else "spawn_post_probe_handler_failed"
        store = state_store if state_store is not None else _store_or_unavailable()
        if isinstance(store, UnavailableStateStore):
            if not advance(claim_check="validation_failed", handler_stage="claim_checked"):
                return "spawn_post_probe_handler_failed"
            return None if advance(handler_stage="completed") else "spawn_post_probe_handler_failed"
        state = store.read(session_id, required_fields=("tasks", "tombstones"))
        execution = canonical_execution_for_attempt(state.get("tasks", {}).get(marker["task_id"]), marker["attempt"])
        exact = bool(
            isinstance(execution, dict) and execution.get("task_ref") == marker["task_ref"]
            and execution.get("spawn_retry_count") == marker["spawn_retry_count"]
            and execution.get("dispatch_record", {}).get("tool_use_id") == tool_use_id
            and execution.get("dispatch_record", {}).get("dispatch_state") == "claimed"
            and spawn_observation(execution) is None
        )
        if not exact:
            if not advance(claim_check="state_mismatch", handler_stage="claim_checked"):
                return "spawn_post_probe_handler_failed"
            return None if advance(handler_stage="completed") else "spawn_post_probe_handler_failed"
        if not advance(claim_check="matched", handler_stage="claim_checked"):
            return "spawn_post_probe_handler_failed"
        if not advance(response_shape=spawn_response_shape(payload.get("tool_response")), handler_stage="shape_classified"):
            return "spawn_post_probe_handler_failed"
        return None if advance(handler_stage="completed") else "spawn_post_probe_handler_failed"
    except Exception:
        # Retain no exception text; the last successful receipt stage is the
        # sole persisted fact.  The raw native call has already completed.
        advance(claim_check="validation_failed", handler_stage="handler_failed")
        return "spawn_post_probe_handler_failed"


def _pre(payload: dict[str, Any], state_store: Any | None) -> dict[str, Any] | None:
    kind = tool_kind(str(payload.get("tool_name") or ""))
    if kind is None:
        return None
    tool_input = payload.get("tool_input")
    if kind == "spawn":
        # This classification happens before any persistence construction.
        if not isinstance(tool_input, dict):
            return _deny("子 Agent 派发被阻止：spawn_agent 参数不是对象。")
        task_name = tool_input.get("task_name") if isinstance(tool_input.get("task_name"), str) else ""
        if not task_name.startswith("sg_"):
            return _allow(copy.deepcopy(tool_input), "Subagent Governance：无治理前缀，本次原生 spawn 按 unmanaged 放行；不创建治理状态。")
        parsed = parse_task_name(task_name)
        if parsed is None:
            return _deny("子 Agent 派发被阻止：governed task_name 必须符合 sg_<resolved_mode>_<semantic_name>_t_<task_ref>，总长度不超过64字符。")
        return _handle_governed_spawn(payload, state_store if state_store is not None else _store_or_unavailable(), task_name, parsed)
    if kind not in {"communication", "followup", "interrupt"}:
        return None
    store = state_store if state_store is not None else _store_or_unavailable()
    try:
        return _hook_lifecycle_result(_claim_pending_action(payload, store, interrupt=kind == "interrupt"))
    except Exception as exc:
        # Parsed PreToolUse errors are a deny unless the domain's explicit
        # normal/interrupt unavailable policy already returned allow.
        return _deny(f"受治理 lifecycle 操作处理失败：{exc}")


def _post(payload: dict[str, Any], state_store: Any | None) -> dict[str, Any] | None:
    kind = tool_kind(str(payload.get("tool_name") or ""))
    if kind is None:
        marker = _spawn_probe_marker(payload, state_store)
        if marker is not None:
            warning = _record_spawn_probe_post(
                payload, state_store, marker=marker, tool_name_classification="unrecognized",
                admission_source="exact_probe_marker",
            )
            return _continue(warning) if warning else None
        # The catch-all first reads only the bounded claimed-ID index.  A miss
        # remains completely inert: no StateStore construction, output, or
        # state write.  A hit is only an admission hint and is rechecked by the
        # lifecycle domain against canonical claimed pending state.
        if claimed_post_index_lookup(payload, state_store) is None:
            return None
        store = state_store if state_store is not None else _store_or_unavailable()
        return _post_result(
            observe_lifecycle_post_tool(
                payload, store, _session_id(payload),
                tool_name_classification="unrecognized",
            )
        )
    session_id = _session_id(payload)
    try:
        if kind == "spawn":
            # First admission is a private same-ID marker.  A recognized-name
            # miss may only use the one exact current PreparedContract fallback;
            # both paths enter the same diagnostic-only handler.
            store = state_store if state_store is not None else _store_or_unavailable()
            if isinstance(store, UnavailableStateStore):
                return _continue("Subagent Governance 无法记录派发生命周期，原生调用已发生，已降级放行。")
            prepared_store = PreparedContractStore(prepared_root_for_store(store))
            tool_use_id = str(payload.get("tool_use_id") or "")
            prepared = prepared_store.find_claimed(session_id, tool_use_id) if tool_use_id else None
            marker = _spawn_probe_marker(payload, store)
            admission_source = "exact_probe_marker"
            if marker is None:
                if prepared is not None:
                    marker = _probe_marker_from_prepared(prepared)
                    admission_source = "recognized_prepared"
            probe_warning = _record_spawn_probe_post(
                payload, store, marker=marker, tool_name_classification="recognized",
                admission_source=admission_source,
            ) if marker is not None else None
            # P12-A is a sidecar only: recognized spawn retains the established
            # PreparedContract exact lookup, adapter, and canonical transition.
            if prepared is None:
                return _continue(probe_warning) if probe_warning else None
            warning = observe_spawn_post_tool(
                session_id, prepared, adapt_spawn_response(payload.get("tool_response")).to_record(),
                int(payload.get("now") or time.time()), store, prepared_store,
            )
            combined = probe_warning or warning or getattr(store, "last_warning", None)
            return _continue(combined) if combined else None
        if kind == "agent_status":
            store = state_store if state_store is not None else _store_or_unavailable()
            adaptation = adapt_list_agents_response_result(
                payload.get("tool_input"), payload.get("tool_response")
            )
            if adaptation.observation is None:
                reason = adaptation.rejection_reason or "response_shape_unrecognized"
                return _continue(
                    "Subagent Governance：list_agents observation 未绑定"
                    f"（{reason}），未写入 canonical observation；原生只读调用结果保持可用。"
                )
            return _post_result(
                observe_agent_status_post_tool(
                    payload, store, session_id, adaptation.observation
                )
            )
        if kind in {"communication", "followup", "interrupt"}:
            store = state_store if state_store is not None else _store_or_unavailable()
            return _post_result(
                observe_lifecycle_post_tool(
                    payload, store, session_id, tool_name_classification="recognized"
                )
            )
    except Exception as exc:
        return _continue(f"Subagent Governance PostToolUse 记录失败，原生调用已发生，已降级放行：{exc}")
    return None


def _session_result(event: str, value: dict[str, Any]) -> dict[str, Any]:
    result = _continue(value.get("system_message"))
    if event == "SessionStart" and value.get("additional_context"):
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": str(value["additional_context"])[:1800]}}
    return result


def _post_result(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """PostToolUse has already executed; never turn a record error into deny."""
    if value is None:
        return None
    return _continue(str(value.get("systemMessage") or "Subagent Governance PostToolUse 记录失败，已降级放行。"))


def handle_hook(payload: dict[str, Any], state_store: Any | None = None) -> dict[str, Any] | None:
    """Route an already-parsed external payload; unknown events are inert."""
    event = payload.get("hook_event_name")
    if event == "PreToolUse":
        return _pre(payload, state_store)
    if event == "PostToolUse":
        return _post(payload, state_store)
    if event not in {"Stop", "SessionStart", "SessionEnd"}:
        return None
    store = state_store if state_store is not None else _store_or_unavailable()
    try:
        if event == "Stop":
            return _session_result(event, stop_advisory(payload, store))
        if event == "SessionStart":
            return _session_result(event, session_start(payload, store))
        return _session_result(event, session_end(payload, store))
    except Exception as exc:
        return _continue(f"Subagent Governance {event} 处理失败，已降级放行：{exc}")


__all__ = ["handle_hook", "tool_kind"]
