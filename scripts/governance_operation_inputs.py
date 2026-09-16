"""Pure stdin projections for common existing CLI operations."""

from __future__ import annotations

from typing import Any


def operation_inputs(task_id: str, task: dict[str, Any]) -> dict[str, Any]:
    """Use an exact transaction/status record, never infer identity or new facts.

    These partial inputs are conveniences, not evidence or permission. The caller
    must supply the current authoritative CLI/Session and actual target/status/
    reason. Existing CLI validation remains authoritative on submission.
    """
    identity = {"task_id": task_id, "task_ref": task["task_ref"]}
    phase = task["phase"]
    if phase in {"prepared", "claimed"}:
        return {"--confirm-dispatch": identity}
    if phase == "closed":
        return {}
    if phase not in {"bound", "terminal", "reconcile"}:
        raise ValueError("operation inputs require a current lifecycle phase")
    result = {}
    if phase == "bound":
        result["--record-terminal-notification"] = {**identity, "sender": task["target"]}
        result["--record-platform-observation"] = {**identity, "target": task["target"]}
    # Close still requires a parent decision; reconcile only permits ending
    # tracking while preserving the conflict. No success/reason is supplied.
    result["--close-task"] = identity
    return result


__all__ = ["operation_inputs"]
