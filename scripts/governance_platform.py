"""Pure normalization for opaque Codex platform responses.

This module deliberately performs no filesystem or network I/O.  A response
string is decoded as one JSON value at most once; nested strings and
transcript-like fields are never interpreted as provider facts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

try:
    from scripts.governance_semantics import (
        LIST_AGENTS_ACTIVE_STATUSES, LIST_AGENTS_ADVISORY_STATUSES,
        LIST_AGENTS_BOOLEAN_ERROR_FLAGS, LIST_AGENTS_ERROR_STATUSES,
        LIST_AGENTS_EXPLICIT_ERROR_FIELD, LIST_AGENTS_TERMINAL_STATUSES,
        LIST_AGENTS_WRAPPER_ERROR_STATUSES, LIST_AGENTS_WRAPPER_STATUS_FIELDS,
    )
except ModuleNotFoundError:
    from governance_semantics import (
        LIST_AGENTS_ACTIVE_STATUSES, LIST_AGENTS_ADVISORY_STATUSES,
        LIST_AGENTS_BOOLEAN_ERROR_FLAGS, LIST_AGENTS_ERROR_STATUSES,
        LIST_AGENTS_EXPLICIT_ERROR_FIELD, LIST_AGENTS_TERMINAL_STATUSES,
        LIST_AGENTS_WRAPPER_ERROR_STATUSES, LIST_AGENTS_WRAPPER_STATUS_FIELDS,
    )


@dataclass(frozen=True)
class SpawnCallObservation:
    observation: str
    canonical_target: str | None = None

    def to_record(self) -> dict[str, str | None]:
        return {"observation": self.observation, "canonical_path": self.canonical_target}


@dataclass(frozen=True)
class LifecycleCallObservation:
    observation: str
    target_observation: str | None = None

    def to_record(self) -> dict[str, str | None]:
        return {"call_observation": self.observation, "target_observation": self.target_observation}


@dataclass(frozen=True)
class AgentStatusObservation:
    target: str
    normalized_status: str
    bounded_summary: str | None = None


def _top_level_value(response: Any) -> Any:
    if not isinstance(response, str):
        return response
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return response


def _native_status(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip().lower() or None
    if not isinstance(value, dict) or len(value) != 1:
        return None
    name, detail = next(iter(value.items()))
    if not isinstance(name, str) or detail is None or detail is False:
        return None
    return name.strip().lower() or None


def _failed(value: dict[str, Any]) -> bool:
    if value.get("isError") is True or value.get("is_error") is True:
        return True
    status = _native_status(value.get("status") if "status" in value else value.get("state"))
    return status in {"error", "failed", "failure"}


def adapt_spawn_response(response: Any) -> SpawnCallObservation:
    value = _top_level_value(response)
    if not isinstance(value, dict):
        return SpawnCallObservation("unknown")
    # `structuredContent` is a documented top-level response envelope, not a
    # recursive search.  A top-level explicit error always wins.
    candidate = value.get("structuredContent") if isinstance(value.get("structuredContent"), dict) else value
    if _failed(value) or _failed(candidate):
        return SpawnCallObservation("failed")
    target = next((candidate[name].strip() for name in ("canonical_task_path", "canonical_path", "task_path", "task_name") if isinstance(candidate.get(name), str) and candidate[name].startswith("/")), None)
    status = _native_status(candidate.get("status") if "status" in candidate else candidate.get("state"))
    if candidate.get("success") is True or status in {"ok", "success", "succeeded", "accepted"} or target:
        return SpawnCallObservation("success", target)
    return SpawnCallObservation("unknown")


def adapt_lifecycle_response(response: Any, operation_type: str) -> LifecycleCallObservation:
    value = _top_level_value(response)
    if value is None or value == "" or value == {}:
        return LifecycleCallObservation("success")
    if not isinstance(value, dict):
        return LifecycleCallObservation("unknown")
    if _failed(value):
        return LifecycleCallObservation("failed")
    status = _native_status(value.get("status") if "status" in value else value.get("state"))
    if value.get("success") is True or status in {"ok", "success", "succeeded", "sent", "accepted"}:
        return LifecycleCallObservation("success")
    if operation_type == "interrupt":
        previous = _native_status(value.get("previous_status"))
        if previous == "running":
            return LifecycleCallObservation("success", "previously_running")
        # not-found is a delivery fact only; it never means inactive by itself.
        if previous == "not_found":
            return LifecycleCallObservation("success", "not_found")
        if previous in {"stopped", "completed", "interrupted", "cancelled", "canceled"}:
            return LifecycleCallObservation("success", previous)
        if status in {"interrupted", "cancelled", "canceled", "stopped", "completed"}:
            return LifecycleCallObservation("success", status)
    return LifecycleCallObservation("unknown")


def adapt_list_agents_response(tool_input: Any, response: Any) -> AgentStatusObservation | None:
    """Return one exact bound observation, or no canonical fact.

    Empty exact results are represented by ``normalized_status='absent'``.
    Non-empty responses require one exact queried agent and are intentionally
    rejected when they contain ambiguity.
    """
    if not isinstance(tool_input, dict):
        return None
    target = tool_input.get("path_prefix")
    if not isinstance(target, str) or not target.startswith("/"):
        return None
    value = _top_level_value(response)
    if not isinstance(value, dict):
        return None
    for flag in LIST_AGENTS_BOOLEAN_ERROR_FLAGS:
        if flag in value and (not isinstance(value[flag], bool) or value[flag]):
            return None
    if (
        LIST_AGENTS_EXPLICIT_ERROR_FIELD in value
        and value[LIST_AGENTS_EXPLICIT_ERROR_FIELD] is not None
        and value[LIST_AGENTS_EXPLICIT_ERROR_FIELD] is not False
    ):
        return None
    for field in LIST_AGENTS_WRAPPER_STATUS_FIELDS:
        if field in value:
            status = _native_status(value[field])
            if status is None or status in LIST_AGENTS_WRAPPER_ERROR_STATUSES:
                return None
    agents = value.get("agents")
    if not isinstance(agents, list) or not all(isinstance(item, dict) for item in agents):
        return None
    if not agents:
        return AgentStatusObservation(target, "absent")
    if len(agents) != 1 or agents[0].get("agent_name") != target:
        return None
    raw_status = agents[0].get("agent_status")
    status = _native_status(raw_status)
    if status in LIST_AGENTS_ACTIVE_STATUSES | LIST_AGENTS_ADVISORY_STATUSES | LIST_AGENTS_TERMINAL_STATUSES:
        return AgentStatusObservation(target, status, status)
    if status in LIST_AGENTS_ERROR_STATUSES:
        detail = raw_status.get(status) if isinstance(raw_status, dict) else status
        return AgentStatusObservation(target, "error", str(detail)[:600])
    return AgentStatusObservation(target, "unknown", status[:600] if status else None)


__all__ = [
    "AgentStatusObservation", "LifecycleCallObservation", "SpawnCallObservation",
    "adapt_lifecycle_response", "adapt_list_agents_response", "adapt_spawn_response",
]
