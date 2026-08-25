"""Lock-free, zero-write status and diagnostics for one exact state-v9 Session."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from scripts.governance_state_store import read_ledger_readonly
except ModuleNotFoundError:
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
        "state_format_version": 9,
        "session_id": session_id,
        "tasks": [
            {
                "task_id": task_id,
                "task_ref": task["task_ref"],
                "phase": task["phase"],
                "objective": task["contract_summary"]["objective"],
                "target": task.get("target"),
                "platform_status": task.get("platform_observation", {}).get("status"),
                "terminal_status": task.get("terminal_fact", {}).get("status"),
                "interrupt_result": task.get("interrupt_fact", {}).get("result"),
                "reconcile_reason": task.get("reconcile", {}).get("code"),
                "close_reason": task.get("close_reason"),
                "next_action": NEXT_ACTIONS[task["phase"]],
            }
            for task_id, task in sorted(state["tasks"].items())
        ],
    }


def status(session_id: str, data_root: Path) -> dict[str, Any]:
    state = read_ledger_readonly(data_root / "sessions", session_id)
    if state is None:
        return {"state_format_version": 9, "session_id": session_id, "tasks": []}
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
