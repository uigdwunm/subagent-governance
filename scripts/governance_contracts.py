"""Task-contract value objects shared by preparation and communication flows."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskFeatures:
    risk: str
    read_only: bool
    writes_files: bool
    destructive: bool
    production: bool
    concurrent_write: bool

    def to_record(self) -> dict[str, Any]:
        return {
            "risk": self.risk,
            "read_only": self.read_only,
            "writes_files": self.writes_files,
            "destructive": self.destructive,
            "production": self.production,
            "concurrent_write": self.concurrent_write,
        }


@dataclass(frozen=True)
class TaskContract:
    semantic_name: str
    requested_mode: str
    resolved_mode: str
    resolution_reason: str
    task_features: dict[str, Any] | None
    objective: str
    background: str
    work_scope: list[str]
    forbidden_scope: list[str]
    completion_conditions: list[str]
    evidence_requirements: list[str]
    relevant_files: list[str]
    context_manifest: dict[str, Any]
    current_state: str | None
    model: str | None
    reasoning_effort: str | None
    context_strategy: str
    context_turns: int | None
    context_reason: str | None

    def to_record(self) -> dict[str, Any]:
        return {
            "semantic_name": self.semantic_name,
            "requested_mode": self.requested_mode,
            "resolved_mode": self.resolved_mode,
            "resolution_reason": self.resolution_reason,
            "task_features": self.task_features,
            "objective": self.objective,
            "background": self.background,
            "work_scope": list(self.work_scope),
            "forbidden_scope": list(self.forbidden_scope),
            "completion_conditions": list(self.completion_conditions),
            "evidence_requirements": list(self.evidence_requirements),
            "relevant_files": list(self.relevant_files),
            "context_manifest": copy.deepcopy(self.context_manifest),
            "current_state": self.current_state,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "context_strategy": self.context_strategy,
            "context_turns": self.context_turns,
            "context_reason": self.context_reason,
        }
