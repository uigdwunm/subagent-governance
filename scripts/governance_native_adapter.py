"""Pure adapters for the explicitly selected native spawn interfaces."""

from __future__ import annotations

import copy
from typing import Any

try:
    from scripts.governance_dispatch_identity import task_name_from_message
    from scripts.governance_errors import NativeInputMismatch, NativeInputUnavailable
    from scripts.governance_semantics import NATIVE_INTERFACES
except ModuleNotFoundError:
    from governance_dispatch_identity import task_name_from_message
    from governance_errors import NativeInputMismatch, NativeInputUnavailable
    from governance_semantics import NATIVE_INTERFACES


_EXPECTED_FIELDS = {"task_name", "message", "fork_turns", "model", "reasoning_effort"}
_TURN_FIELDS = {"task_name", "message", "fork_turns", "model", "reasoning_effort"}
_CONTEXT_FIELDS = {"message", "fork_context", "model", "reasoning_effort"}


def _interface(native_interface: str) -> None:
    if native_interface not in NATIVE_INTERFACES:
        raise ValueError("native_interface 必须是 collaboration_turns 或 fork_context")


def _fork_turns(value: Any) -> str:
    if not isinstance(value, str) or value not in {"none", "all"} and not (
        value.isdigit() and value[0] != "0" and len(value) <= 12
    ):
        raise ValueError("spawn.fork_turns 必须是 none、all 或 1-12 位正整数字符串")
    return value


def validate_native_spawn(native_interface: str, spawn: dict[str, Any]) -> None:
    """Validate semantic spawn configuration for one frozen native interface."""
    _interface(native_interface)
    if not isinstance(spawn, dict):
        raise ValueError("spawn 必须是对象")
    turns = _fork_turns(spawn.get("fork_turns"))
    model, effort = spawn.get("model"), spawn.get("reasoning_effort")
    if native_interface == "collaboration_turns" and turns == "all" and (
        model is not None or effort is not None
    ):
        raise ValueError("collaboration_turns 在 fork_turns=all 时不允许 model 或 reasoning_effort 覆盖")
    if native_interface == "fork_context" and turns not in {"none", "all"}:
        raise ValueError("fork_context 不支持有限 fork_turns")


def render_native_spawn(native_interface: str, expected: dict[str, Any]) -> dict[str, Any]:
    """Render immutable semantic expectations into the selected native shape."""
    _interface(native_interface)
    if not isinstance(expected, dict) or set(expected) != _EXPECTED_FIELDS:
        raise ValueError("expected_native_parameters 字段集合无效")
    validate_native_spawn(native_interface, expected)
    if native_interface == "collaboration_turns":
        native = {key: expected[key] for key in ("message", "task_name", "fork_turns", "model", "reasoning_effort")}
    else:
        native = {
            "message": expected["message"],
            "fork_context": expected["fork_turns"] == "all",
            "model": expected["model"],
            "reasoning_effort": expected["reasoning_effort"],
        }
    return {key: copy.deepcopy(value) for key, value in native.items() if value is not None}


def normalize_native_spawn(native_interface: str, tool_input: Any) -> dict[str, Any]:
    """Return a fully comparable semantic spawn input without mutating it."""
    _interface(native_interface)
    if not isinstance(tool_input, dict):
        raise NativeInputUnavailable("spawn_agent tool_input 不可验证")
    allowed = _TURN_FIELDS if native_interface == "collaboration_turns" else _CONTEXT_FIELDS
    unknown = set(tool_input) - allowed
    if unknown:
        raise NativeInputUnavailable("spawn_agent tool_input 包含未知字段")
    message = tool_input.get("message")
    if not isinstance(message, str):
        raise NativeInputUnavailable("spawn_agent message 不可验证")
    for field in ("model", "reasoning_effort"):
        if field in tool_input and tool_input[field] is None:
            raise NativeInputUnavailable(f"spawn_agent {field} 的 null 形态不可验证")
    if native_interface == "collaboration_turns":
        task_name = tool_input.get("task_name")
        if not isinstance(task_name, str):
            raise NativeInputUnavailable("spawn_agent task_name 不可验证")
        embedded = task_name_from_message(message)
        if embedded is not None and embedded != task_name:
            raise NativeInputMismatch("task_name 与 message 治理标记不一致")
        turns = tool_input.get("fork_turns", "all")
        try:
            _fork_turns(turns)
        except ValueError as exc:
            raise NativeInputMismatch(str(exc)) from exc
    else:
        context = tool_input.get("fork_context", False)
        if not isinstance(context, bool):
            raise NativeInputMismatch("fork_context 必须是布尔值")
        task_name = task_name_from_message(message)
        turns = "all" if context else "none"
    return {
        "task_name": task_name,
        "message": message,
        "fork_turns": turns,
        "model": tool_input.get("model"),
        "reasoning_effort": tool_input.get("reasoning_effort"),
    }


__all__ = ["normalize_native_spawn", "render_native_spawn", "validate_native_spawn"]
