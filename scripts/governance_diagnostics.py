"""Lock-free, zero-write status and diagnostics for one exact state-v12 Session."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

try:
    from scripts.governance_errors import StateConflictError
    from scripts.governance_semantics import STATE_FORMAT_VERSION, TASK_REF_LENGTHS
    from scripts.governance_state_store import read_ledger_readonly
except ModuleNotFoundError:
    from governance_errors import StateConflictError
    from governance_semantics import STATE_FORMAT_VERSION, TASK_REF_LENGTHS
    from governance_state_store import read_ledger_readonly


NEXT_ACTIONS = {
    "prepared": "invoke_exact_spawn_args",
    "claimed": "confirm_exact_target",
    "bound": "observe_exact_target",
    "terminal": "parent_close",
    "closed": "none",
    "reconcile": "manual_reconcile",
}


def project_status(state: dict[str, Any], session_id: str) -> dict[str, Any]:
    return {
        "state_format_version": STATE_FORMAT_VERSION,
        "session_id": session_id,
        "tasks": [
            {
                "task_id": task_id,
                "task_ref": task["task_ref"],
                "native_interface": task["native_interface"],
                "phase": task["phase"],
                "objective": task["contract_summary"]["objective"],
                "target": task.get("target"),
                "platform_status": task.get("platform_observation", {}).get("status"),
                "terminal_status": task.get("terminal_fact", {}).get("status"),
                "interrupt_result": task.get("interrupt_fact", {}).get("result"),
                "reconcile_reason": task.get("reconcile", {}).get("code"),
                "unknown_facts": copy.deepcopy(task.get("unknown_facts", {})),
                "close_reason": task.get("close_reason"),
                "next_action": NEXT_ACTIONS[task["phase"]],
            }
            for task_id, task in sorted(state["tasks"].items())
        ],
    }


def status(
    session_id: str, data_root: Path, *, task_id: str | None = None, task_ref: str | None = None,
) -> dict[str, Any]:
    detail = task_id is not None or task_ref is not None
    if detail:
        if (not isinstance(task_id, str) or not task_id or task_id != task_id.strip()
                or len(task_id) > 256 or not isinstance(task_ref, str)
                or len(task_ref) not in TASK_REF_LENGTHS
                or re.fullmatch(r"[a-f0-9]+", task_ref) is None):
            raise ValueError("status 详情必须同时提供有效 task_id 和 task_ref")
    state = read_ledger_readonly(data_root / "sessions", session_id)
    if detail:
        task = None if state is None else state["tasks"].get(task_id)
        if task is None or task["task_ref"] != task_ref:
            raise StateConflictError("status 详情 task_id/task_ref 不存在于当前 exact Session 或不匹配")
        result = project_status({"tasks": {task_id: task}}, session_id)
        result["tasks"][0]["contract_summary"] = copy.deepcopy(task["contract_summary"])
        return result
    if state is None:
        return {"state_format_version": STATE_FORMAT_VERSION, "session_id": session_id, "tasks": []}
    return project_status(state, session_id)


def diagnose(session_id: str, data_root: Path) -> dict[str, Any]:
    try:
        current = status(session_id, data_root)
    except Exception as exc:
        return {
            "data_root": str(data_root),
            "status": None,
            "issues": [{"code": "unreadable", "message": str(exc)[:600]}],
        }
    return {"data_root": str(data_root), "status": current, "issues": []}


__all__ = ["diagnose", "project_status", "status"]
