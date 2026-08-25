"""Minimal Hook router: governed spawn Pre claim and read-only SessionStart."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

try:
    from scripts.governance_dispatch import claim_spawn
    from scripts.governance_dispatch_identity import parse_task_name
    from scripts.governance_semantics import SESSION_SUMMARY_CONTEXT_LIMIT
    from scripts.governance_state_store import StateStore, read_ledger_readonly
    from scripts.governance_store_support import data_root_path
except ModuleNotFoundError:
    from governance_dispatch import claim_spawn
    from governance_dispatch_identity import parse_task_name
    from governance_semantics import SESSION_SUMMARY_CONTEXT_LIMIT
    from governance_state_store import StateStore, read_ledger_readonly
    from governance_store_support import data_root_path


def tool_kind(tool_name: str) -> str | None:
    leaf = tool_name.rsplit(".", 1)[-1]
    return "spawn" if leaf in {"Agent", "spawn_agent"} else None


def _allow(updated_input: dict[str, Any], context: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "updatedInput": updated_input,
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
    if tool_kind(str(payload.get("tool_name") or "")) != "spawn":
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    task_name = tool_input.get("task_name")
    if not isinstance(task_name, str) or not task_name.startswith("sg_"):
        return None
    parsed = parse_task_name(task_name)
    if parsed is None:
        return _deny("governed task_name 无效；必须由 prepare-dispatch 生成")
    _profile, _semantic_name, task_ref = parsed
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return _deny("governed spawn 缺少 exact session_id")
    tool_use_id = payload.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not tool_use_id.strip():
        return _deny("governed spawn 缺少 tool_use_id，无法原子 claim")
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
    except Exception as exc:
        return _deny(f"governed spawn claim 失败：{exc}")
    return _allow(
        copy.deepcopy(tool_input),
        f"Subagent Governance 已在 state-v9 单一 ledger 原子 claim task_ref={task_ref}（{outcome['result']}）。原生返回后立即 confirm exact target。",
    )


def _session_start(payload: dict[str, Any]) -> dict[str, Any] | None:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    root = data_root_path(Path(__file__)) / "sessions"
    try:
        state = read_ledger_readonly(root, session_id)
    except Exception:
        return None
    if state is None:
        return None
    open_tasks = [
        (task_id, task)
        for task_id, task in sorted(state["tasks"].items())
        if task.get("phase") != "closed"
    ]
    if not open_tasks:
        return None
    lines = ["Subagent Governance state-v9 exact Session 未关闭任务："]
    for task_id, task in open_tasks[:8]:
        target = f" target={task['target']}" if task.get("target") else ""
        lines.append(
            f"- task_id={task_id} task_ref={task['task_ref']} phase={task['phase']}{target}"
        )
    lines.append("使用 status --session <exact-session-id> 获取只读详情；不得自动重派或推断 identity。")
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
