"""Strict runtime validation for the sole supported state-v9 Session ledger."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

try:
    from scripts.governance_context import validate_context_verification_record
    from scripts.governance_contracts import (
        contract_digest, contract_from_input, contract_summary, spawn_digest,
    )
    from scripts.governance_errors import StateValidationError
    from scripts.governance_semantics import (
        MAX_TASKS_PER_SESSION, PHASES, RECONCILE_CODES, STATE_FORMAT_VERSION,
        TASK_REF_LENGTHS,
    )
except ModuleNotFoundError:
    from governance_context import validate_context_verification_record
    from governance_contracts import contract_digest, contract_from_input, contract_summary, spawn_digest
    from governance_errors import StateValidationError
    from governance_semantics import MAX_TASKS_PER_SESSION, PHASES, RECONCILE_CODES, STATE_FORMAT_VERSION, TASK_REF_LENGTHS


@dataclass(frozen=True)
class StateFormatIssue:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


COMMON_FIELDS = {
    "task_ref", "phase", "contract_digest", "contract_summary", "created_at", "updated_at"
}
PHASE_FIELDS = {
    "prepared": {"prepared"},
    "claimed": {"prepared", "claimed_tool_use_id", "claimed_at"},
    "bound": {"target", "bound_at"},
    "terminal": {"target", "bound_at", "terminal_fact"},
    "closed": {"close_reason", "closed_at"},
    "reconcile": {"reconcile"},
}
OPTIONAL_PHASE_FIELDS = {
    "closed": {"target", "bound_at", "terminal_fact"},
    "reconcile": {"target", "bound_at", "terminal_fact"},
}


def _timestamp(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _text(value: Any, maximum: int = 1024) -> bool:
    return isinstance(value, str) and value == value.strip() and bool(value) and len(value) <= maximum


def _digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _task_ref(value: Any) -> bool:
    return isinstance(value, str) and len(value) in TASK_REF_LENGTHS and re.fullmatch(r"[a-f0-9]+", value) is not None


def _issue(issues: list[StateFormatIssue], path: str, message: str) -> None:
    issues.append(StateFormatIssue(path, message))


def _validate_terminal_fact(value: Any, path: str, issues: list[StateFormatIssue]) -> None:
    fields = {"source", "status", "observed_at"}
    if not isinstance(value, dict) or set(value) != fields:
        _issue(issues, path, "terminal_fact 字段集合无效")
        return
    if value.get("source") not in {"platform", "notification", "interrupt"}:
        _issue(issues, f"{path}.source", "terminal source 无效")
    if value.get("status") not in {"completed", "failed", "stopped", "interrupted", "inactive"}:
        _issue(issues, f"{path}.status", "terminal status 无效")
    if not _timestamp(value.get("observed_at")):
        _issue(issues, f"{path}.observed_at", "必须是非负整数")


def _validate_prepared(value: Any, path: str, issues: list[StateFormatIssue]) -> None:
    fields = {"contract", "context_verification", "expected_native_parameters", "spawn_digest", "expires_at"}
    if not isinstance(value, dict) or set(value) != fields:
        _issue(issues, path, "prepared capability 字段集合无效")
        return
    try:
        contract = contract_from_input(value.get("contract"))
    except ValueError as exc:
        _issue(issues, f"{path}.contract", str(exc))
        return
    if value.get("spawn_digest") != spawn_digest(contract):
        _issue(issues, f"{path}.spawn_digest", "与 canonical spawn config 不一致")
    verification = value.get("context_verification")
    manifest = contract.context.get("verified")
    if manifest is None:
        if verification is not None:
            _issue(issues, f"{path}.context_verification", "无 verified context 时必须是 null")
    elif verification is None:
        _issue(issues, f"{path}.context_verification", "verified context 缺少校验记录")
    else:
        for error in validate_context_verification_record(manifest, verification):
            _issue(issues, f"{path}.context_verification", error)
    expected = value.get("expected_native_parameters")
    expected_fields = {"task_name", "message", "fork_turns", "model", "reasoning_effort"}
    if not isinstance(expected, dict) or set(expected) != expected_fields:
        _issue(issues, f"{path}.expected_native_parameters", "字段集合无效")
    else:
        if not _text(expected.get("task_name"), 64) or not _text(expected.get("message"), 65536):
            _issue(issues, f"{path}.expected_native_parameters", "task_name/message 无效")
        spawn = contract.spawn
        for field in ("fork_turns", "model", "reasoning_effort"):
            if expected.get(field) != spawn.get(field):
                _issue(issues, f"{path}.expected_native_parameters.{field}", "与 contract spawn 不一致")
    if not _timestamp(value.get("expires_at")):
        _issue(issues, f"{path}.expires_at", "必须是非负整数")


def _validate_task(task_id: str, value: Any, path: str, issues: list[StateFormatIssue]) -> None:
    if not _text(task_id, 256):
        _issue(issues, path, "task key 无效")
    if not isinstance(value, dict):
        _issue(issues, path, "task 必须是对象")
        return
    phase = value.get("phase")
    if phase not in PHASES:
        _issue(issues, f"{path}.phase", "phase 无效")
        return
    required = COMMON_FIELDS | PHASE_FIELDS[phase]
    allowed = required | OPTIONAL_PHASE_FIELDS.get(phase, set())
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        _issue(issues, path, "缺少字段 " + "、".join(missing))
    if unknown:
        _issue(issues, path, "包含未知字段 " + "、".join(unknown))
    if not _task_ref(value.get("task_ref")):
        _issue(issues, f"{path}.task_ref", "task_ref 无效")
    if not _digest(value.get("contract_digest")):
        _issue(issues, f"{path}.contract_digest", "digest 无效")
    summary = value.get("contract_summary")
    if not isinstance(summary, dict) or set(summary) != {"profile", "objective"}:
        _issue(issues, f"{path}.contract_summary", "summary 字段集合无效")
    else:
        if summary.get("profile") not in {"standard", "strict"} or not _text(summary.get("objective"), 8192):
            _issue(issues, f"{path}.contract_summary", "summary 内容无效")
    created_at, updated_at = value.get("created_at"), value.get("updated_at")
    if not _timestamp(created_at) or not _timestamp(updated_at) or (
        _timestamp(created_at) and _timestamp(updated_at) and updated_at < created_at
    ):
        _issue(issues, path, "created_at/updated_at 无效")

    if phase in {"prepared", "claimed"}:
        _validate_prepared(value.get("prepared"), f"{path}.prepared", issues)
        prepared = value.get("prepared")
        if isinstance(prepared, dict):
            try:
                contract = contract_from_input(prepared.get("contract"))
            except ValueError:
                pass
            else:
                if value.get("contract_digest") != contract_digest(contract):
                    _issue(issues, f"{path}.contract_digest", "与 capability business contract 不一致")
                if value.get("contract_summary") != contract_summary(contract):
                    _issue(issues, f"{path}.contract_summary", "与 capability contract 不一致")
    if phase == "claimed":
        if not _text(value.get("claimed_tool_use_id")) or not _timestamp(value.get("claimed_at")):
            _issue(issues, path, "claimed facts 无效")
    if phase in {"bound", "terminal"} or "target" in value:
        if not _text(value.get("target")) or not _timestamp(value.get("bound_at")):
            _issue(issues, path, "bound identity facts 无效")
    if phase == "terminal" or "terminal_fact" in value:
        _validate_terminal_fact(value.get("terminal_fact"), f"{path}.terminal_fact", issues)
    if phase == "closed":
        if not _text(value.get("close_reason")) or not _timestamp(value.get("closed_at")):
            _issue(issues, path, "close facts 无效")
    if phase == "reconcile":
        reconcile = value.get("reconcile")
        if not isinstance(reconcile, dict) or set(reconcile) != {"code", "observed_at"}:
            _issue(issues, f"{path}.reconcile", "reconcile 字段集合无效")
        else:
            if reconcile.get("code") not in RECONCILE_CODES or not _timestamp(reconcile.get("observed_at")):
                _issue(issues, f"{path}.reconcile", "reconcile 内容无效")


def validate_current_state_format(value: Any) -> list[StateFormatIssue]:
    issues: list[StateFormatIssue] = []
    if not isinstance(value, dict):
        return [StateFormatIssue("$", "Session ledger 必须是对象")]
    expected = {"state_format_version", "session_id", "tasks"}
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unknown = sorted(set(value) - expected)
        if missing:
            _issue(issues, "$", "缺少字段 " + "、".join(missing))
        if unknown:
            _issue(issues, "$", "包含未知字段 " + "、".join(unknown))
    if value.get("state_format_version") != STATE_FORMAT_VERSION or isinstance(value.get("state_format_version"), bool):
        _issue(issues, "$.state_format_version", f"当前仅支持 state_format_version={STATE_FORMAT_VERSION}")
    if not _text(value.get("session_id")):
        _issue(issues, "$.session_id", "session_id 无效")
    tasks = value.get("tasks")
    if not isinstance(tasks, dict):
        _issue(issues, "$.tasks", "tasks 必须是对象")
        return issues
    if len(tasks) > MAX_TASKS_PER_SESSION:
        _issue(issues, "$.tasks", f"tasks 不能超过 {MAX_TASKS_PER_SESSION} 项")
    refs: set[str] = set()
    for task_id, task in tasks.items():
        _validate_task(task_id, task, f"$.tasks[{task_id!r}]", issues)
        if isinstance(task, dict) and isinstance(task.get("task_ref"), str):
            if task["task_ref"] in refs:
                _issue(issues, f"$.tasks[{task_id!r}].task_ref", "task_ref 在 Session 内重复")
            refs.add(task["task_ref"])
    return issues


def require_current_state_format(value: Any) -> dict[str, Any]:
    issues = validate_current_state_format(value)
    if issues:
        raise StateValidationError("；".join(str(issue) for issue in issues[:12]))
    assert isinstance(value, dict)
    return value


__all__ = ["StateFormatIssue", "require_current_state_format", "validate_current_state_format"]
