"""TaskContract v2 normalization, validation, and separated digests."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

try:
    from scripts.governance_context import validate_context_manifest
    from scripts.governance_semantics import (
        MAX_BUSINESS_TEXT, MAX_CONTRACT_TEXT, PROFILES, REASONING_EFFORTS,
        TASK_CONTRACT_FIELDS,
    )
except ModuleNotFoundError:
    from governance_context import validate_context_manifest
    from governance_semantics import MAX_BUSINESS_TEXT, MAX_CONTRACT_TEXT, PROFILES, REASONING_EFFORTS, TASK_CONTRACT_FIELDS


@dataclass(frozen=True)
class TaskContract:
    profile: str
    objective: str
    scope: list[str]
    forbidden_scope: list[str]
    completion: list[str]
    evidence: list[str]
    context: dict[str, Any]
    spawn: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "objective": self.objective,
            "scope": list(self.scope),
            "forbidden_scope": list(self.forbidden_scope),
            "completion": list(self.completion),
            "evidence": list(self.evidence),
            "context": copy.deepcopy(self.context),
            "spawn": copy.deepcopy(self.spawn),
        }

    def business_record(self) -> dict[str, Any]:
        value = self.to_record()
        value.pop("spawn")
        return value


def _text(value: Any, field: str, *, maximum: int) -> list[str]:
    if not isinstance(value, str):
        return [f"字段 {field} 必须是字符串"]
    if not value.strip():
        return [f"字段 {field} 不能为空"]
    if value != value.strip():
        return [f"字段 {field} 不能包含首尾空白"]
    if len(value) > maximum:
        return [f"字段 {field} 长度不能超过 {maximum}"]
    return []


def _text_list(value: Any, field: str, *, minimum: int = 0) -> list[str]:
    if not isinstance(value, list):
        return [f"字段 {field} 必须是数组"]
    errors: list[str] = []
    if len(value) < minimum:
        errors.append(f"字段 {field} 至少需要 {minimum} 项")
    if len(value) > 64:
        errors.append(f"字段 {field} 不能超过 64 项")
    for index, item in enumerate(value):
        errors.extend(_text(item, f"{field}[{index}]", maximum=MAX_CONTRACT_TEXT))
    return errors


def _validate_paths(value: Any) -> list[str]:
    errors = _text_list(value, "context.paths")
    if not isinstance(value, list):
        return errors
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or _text(item, f"context.paths[{index}]", maximum=1000):
            continue
        parts = item.split("/")
        if item.startswith("/") or "\\" in item or any(
            part in {"", ".", ".."} for part in parts
        ) or any(ord(character) < 32 for character in item):
            errors.append(f"字段 context.paths[{index}] 必须是规范 POSIX 相对路径")
        if item in seen:
            errors.append(f"字段 context.paths[{index}] 不能重复")
        seen.add(item)
    return errors


def validate_task_contract(value: Any) -> list[str]:
    if isinstance(value, TaskContract):
        value = value.to_record()
    if not isinstance(value, dict):
        return ["TaskContract v2 必须是对象"]
    required = set(TASK_CONTRACT_FIELDS)
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    errors = [f"缺少字段 {field}" for field in missing]
    if unknown:
        errors.append("TaskContract v2 unknown fields: " + "、".join(unknown))
    if missing:
        return errors

    profile = value.get("profile")
    if profile not in PROFILES:
        errors.append("字段 profile 必须是 standard 或 strict")
    errors.extend(_text(value.get("objective"), "objective", maximum=MAX_BUSINESS_TEXT))
    errors.extend(_text_list(value.get("scope"), "scope", minimum=1))
    errors.extend(_text_list(value.get("forbidden_scope"), "forbidden_scope"))
    errors.extend(_text_list(value.get("completion"), "completion", minimum=1))
    errors.extend(_text_list(value.get("evidence"), "evidence"))
    if profile == "strict":
        if not value.get("forbidden_scope"):
            errors.append("strict profile 要求非空 forbidden_scope")
        if not value.get("evidence"):
            errors.append("strict profile 要求非空 evidence")

    context = value.get("context")
    if not isinstance(context, dict):
        errors.append("字段 context 必须是对象")
    else:
        context_fields = {"summary", "paths", "verified"}
        context_unknown = sorted(set(context) - context_fields)
        context_missing = sorted(context_fields - set(context))
        if context_unknown:
            errors.append("context unknown fields: " + "、".join(context_unknown))
        errors.extend(f"context 缺少字段 {field}" for field in context_missing)
        summary = context.get("summary")
        if not isinstance(summary, str) or len(summary) > MAX_BUSINESS_TEXT:
            errors.append(f"字段 context.summary 必须是长度不超过 {MAX_BUSINESS_TEXT} 的字符串")
        errors.extend(_validate_paths(context.get("paths")))
        verified = context.get("verified")
        if verified is not None:
            verification_errors = validate_context_manifest(verified)
            errors.extend(f"context.verified: {error}" for error in verification_errors)
            if isinstance(verified, dict) and verified.get("mode") != "declared":
                errors.append("context.verified 只接受 declared verified materials")

    spawn = value.get("spawn")
    if not isinstance(spawn, dict):
        errors.append("字段 spawn 必须是对象")
    else:
        spawn_fields = {"fork_turns", "model", "reasoning_effort"}
        spawn_unknown = sorted(set(spawn) - spawn_fields)
        spawn_missing = sorted(spawn_fields - set(spawn))
        if spawn_unknown:
            errors.append("spawn unknown fields: " + "、".join(spawn_unknown))
        errors.extend(f"spawn 缺少字段 {field}" for field in spawn_missing)
        fork_turns = spawn.get("fork_turns")
        if not isinstance(fork_turns, str) or re.fullmatch(r"(?:none|all|[1-9][0-9]*)", fork_turns) is None:
            errors.append("字段 spawn.fork_turns 必须是 none、all 或正整数字符串")
        model = spawn.get("model")
        if model is not None:
            errors.extend(_text(model, "spawn.model", maximum=MAX_CONTRACT_TEXT))
        effort = spawn.get("reasoning_effort")
        if effort is not None and effort not in REASONING_EFFORTS:
            errors.append("字段 spawn.reasoning_effort 枚举无效")
    return errors


def contract_from_input(value: Any) -> TaskContract:
    if isinstance(value, TaskContract):
        raw = value.to_record()
    elif isinstance(value, dict):
        raw = copy.deepcopy(value)
    else:
        raise ValueError("TaskContract v2 输入必须是对象")
    unknown = sorted(set(raw) - set(TASK_CONTRACT_FIELDS))
    if unknown:
        raise ValueError("TaskContract v2 unknown fields: " + "、".join(unknown))

    raw.setdefault("profile", "standard")
    raw.setdefault("forbidden_scope", [])
    raw.setdefault("evidence", [])
    raw.setdefault("context", {})
    raw.setdefault("spawn", {})
    if isinstance(raw["context"], dict):
        raw["context"].setdefault("summary", "")
        raw["context"].setdefault("paths", [])
        raw["context"].setdefault("verified", None)
    if isinstance(raw["spawn"], dict):
        raw["spawn"].setdefault("fork_turns", "none")
        raw["spawn"].setdefault("model", None)
        raw["spawn"].setdefault("reasoning_effort", None)

    errors = validate_task_contract(raw)
    if errors:
        raise ValueError("；".join(errors))
    return TaskContract(**{field: raw[field] for field in TASK_CONTRACT_FIELDS})


def _digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def contract_digest(contract: TaskContract) -> str:
    return _digest(contract.business_record())


def spawn_digest(contract: TaskContract) -> str:
    return _digest(contract.spawn)


def contract_summary(contract: TaskContract) -> dict[str, str]:
    return {"profile": contract.profile, "objective": contract.objective}


__all__ = ["TaskContract", "contract_digest", "contract_from_input", "contract_summary", "spawn_digest", "validate_task_contract"]
