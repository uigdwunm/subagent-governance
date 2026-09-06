"""Minimal Hook router: governed spawn Pre claim and read-only SessionStart."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from scripts.governance_dispatch import claim_spawn
    from scripts.governance_dispatch_identity import MESSAGE_PREFIX, parse_task_name, task_name_from_message
    from scripts.governance_errors import NativeInputMismatch, NativeInputUnavailable, StateConflictError
    from scripts.governance_semantics import NATIVE_SPAWN_TOOL_NAMES, SESSION_SUMMARY_CONTEXT_LIMIT, STATE_STORAGE_NAMESPACE
    from scripts.governance_state_store import StateStore, read_ledger_readonly
    from scripts.governance_store_support import data_root_path
except ModuleNotFoundError:
    from governance_dispatch import claim_spawn
    from governance_dispatch_identity import MESSAGE_PREFIX, parse_task_name, task_name_from_message
    from governance_errors import NativeInputMismatch, NativeInputUnavailable, StateConflictError
    from governance_semantics import NATIVE_SPAWN_TOOL_NAMES, SESSION_SUMMARY_CONTEXT_LIMIT, STATE_STORAGE_NAMESPACE
    from governance_state_store import StateStore, read_ledger_readonly
    from governance_store_support import data_root_path


def tool_kind(tool_name: str) -> str | None:
    return "spawn" if tool_name in NATIVE_SPAWN_TOOL_NAMES else None


def _allow(context: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
    }
    if context:
        value["additionalContext"] = context[:SESSION_SUMMARY_CONTEXT_LIMIT]
    return {"hookSpecificOutput": value}


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason[:SESSION_SUMMARY_CONTEXT_LIMIT],
        }
    }


def _pre(payload: dict[str, Any], state_store: Any | None) -> dict[str, Any] | None:
    tool_name = str(payload.get("tool_name") or "")
    if tool_kind(tool_name) != "spawn":
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    message = tool_input.get("message")
    explicit_name = tool_input.get("task_name")
    embedded_name = task_name_from_message(message)
    has_marker = isinstance(message, str) and message.startswith(MESSAGE_PREFIX)
    if explicit_name is None and not has_marker:
        return None
    if explicit_name is not None and not isinstance(explicit_name, str):
        return None
    if has_marker and embedded_name is None:
        return _deny("governed message 标记无效；必须由 prepare-dispatch 生成")
    if explicit_name is not None and embedded_name is not None and explicit_name != embedded_name:
        return _deny("governed task_name 与 message 标记不一致")
    task_name = explicit_name or embedded_name
    parsed = parse_task_name(task_name)
    if parsed is None:
        if not has_marker:
            return None
        return _deny("governed task_name 无效；必须由 prepare-dispatch 生成")
    _profile, _semantic_name, task_ref = parsed
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return _allow("Subagent Governance 无法验证 exact session_id；已 fail-open 且未 claim。")
    tool_use_id = payload.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not tool_use_id.strip():
        return _allow("Subagent Governance 无法验证 tool_use_id；已 fail-open 且未 claim。")
    try:
        store = state_store or StateStore()
        outcome = claim_spawn(
            session_id,
            task_ref,
            tool_use_id,
            tool_input,
            state_store=store,
            now=payload.get("now"),
        )
    except NativeInputUnavailable:
        return _allow("Subagent Governance 无法验证原生输入；已 fail-open 且未 claim。")
    except NativeInputMismatch as exc:
        return _deny(f"governed spawn native input 不一致：{exc}")
    except StateConflictError as exc:
        return _deny(f"governed spawn claim 冲突：{exc}")
    except Exception:
        return _allow("Subagent Governance 内部故障；已 fail-open 且未声称 claim。")
    return _allow(
        f"Subagent Governance 已在 {STATE_STORAGE_NAMESPACE} 单一 ledger 原子 claim task_ref={task_ref}（{outcome['result']}）。原生返回后立即 confirm exact target。"
    )


def _session_start(payload: dict[str, Any]) -> dict[str, Any] | None:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    cli_entrypoint = str(Path(__file__).resolve().with_name("subagent_governance.py"))
    lines = [
        f"Subagent Governance 当前 Hook 权威 exact session_id（JSON）：{json.dumps(session_id, ensure_ascii=False)}",
        f"当前 Hook 权威 governance CLI entrypoint（JSON）：{json.dumps(cli_entrypoint, ensure_ascii=False)}",
        "所有治理命令必须用上方 entrypoint，且 --session 必须逐字使用上方 session_id。",
        "<codex_delegation><source_thread_id> 仅表示来源任务，不是当前 session_id；不得用父任务、任务列表或其他 ID 替代。",
    ]
    root = data_root_path(Path(__file__)) / "sessions"
    try:
        state = read_ledger_readonly(root, session_id)
    except Exception:
        lines.append("当前治理状态摘要不可读取；不得因此猜测其他 Session identity。")
    else:
        open_tasks = (
            []
            if state is None
            else [
                (task_id, task)
                for task_id, task in sorted(state["tasks"].items())
                if task.get("phase") != "closed"
            ]
        )
        if open_tasks:
            lines.append(f"Subagent Governance {STATE_STORAGE_NAMESPACE} 当前 exact Session 未关闭任务：")
            for task_id, task in open_tasks[:8]:
                target = f" target={task['target']}" if task.get("target") else ""
                lines.append(
                    f"- task_id={task_id} task_ref={task['task_ref']} phase={task['phase']}{target}"
                )
        else:
            lines.append("当前 exact Session 没有可读的未关闭治理任务。")
    lines.append(
        "使用 status --session <上方 exact session_id> 获取只读详情；"
        "不得自动重派或推断 identity。"
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines)[:SESSION_SUMMARY_CONTEXT_LIMIT],
        }
    }


def handle_hook(payload: dict[str, Any], state_store: Any | None = None) -> dict[str, Any] | None:
    event = payload.get("hook_event_name")
    if event == "PreToolUse":
        return _pre(payload, state_store)
    if event == "SessionStart":
        return _session_start(payload)
    return None


__all__ = ["handle_hook", "tool_kind"]
