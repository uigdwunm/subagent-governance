"""TaskContract parsing, validation, canonical serialization, and digest."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

try:
    from scripts.governance_context import validate_context_manifest
    from scripts.governance_dispatch_identity import normalize_semantic_name
    from scripts.governance_semantics import (
        AUTO_RESOLUTION, CONTEXT_STRATEGIES, CONTEXT_TURNS, MODE_MINIMUMS,
        REASONING_EFFORTS, REQUESTED_MODES, RESOLUTION_REASONS, RESOLVED_MODES,
        RISKS, SEMANTIC_DEFINITIONS, SEMANTIC_RULES, TASK_CONTRACT_OPTIONAL_FIELDS,
    )
    from scripts.governance_validation import required_fields, validate_text, validate_text_list
except ModuleNotFoundError:
    from governance_context import validate_context_manifest
    from governance_dispatch_identity import normalize_semantic_name
    from governance_semantics import (
        AUTO_RESOLUTION, CONTEXT_STRATEGIES, CONTEXT_TURNS, MODE_MINIMUMS,
        REASONING_EFFORTS, REQUESTED_MODES, RESOLUTION_REASONS, RESOLVED_MODES,
        RISKS, SEMANTIC_DEFINITIONS, SEMANTIC_RULES, TASK_CONTRACT_OPTIONAL_FIELDS,
    )
    from governance_validation import required_fields, validate_text, validate_text_list


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


def validate_task_features(value: Any, *, required: bool) -> list[str]:
    if value is None:
        return ["缺少字段 task_features"] if required else []
    if isinstance(value, TaskFeatures):
        value = value.to_record()
    if not isinstance(value, dict):
        return ["字段 task_features 必须是对象或 null"]
    fields = list(SEMANTIC_DEFINITIONS["task_features"]["required"])
    errors = required_fields(value, fields)
    if value.get("risk") not in RISKS:
        errors.append("字段 task_features.risk 必须是 low、medium 或 high")
    for field_name in fields[1:]:
        if not isinstance(value.get(field_name), bool):
            errors.append(f"字段 task_features.{field_name} 必须是布尔值")
    if value.get("read_only") is True and value.get("writes_files") is True:
        errors.append("task_features.read_only=true 与 writes_files=true 机械矛盾")
    return errors


def resolve_governance_mode(requested_mode: str, task_features: dict[str, Any] | TaskFeatures | None = None) -> tuple[str, str]:
    if requested_mode not in REQUESTED_MODES:
        raise ValueError("requested_mode 必须是 auto、light、standard 或 strict")
    if requested_mode in RESOLVED_MODES:
        return requested_mode, "explicit_request"
    errors = validate_task_features(task_features, required=True)
    if errors:
        raise ValueError("；".join(errors))
    features = task_features.to_record() if isinstance(task_features, TaskFeatures) else task_features
    assert isinstance(features, dict)
    if features.get("risk") in AUTO_RESOLUTION["strict_risks"] or any(features.get(field_name) is True for field_name in AUTO_RESOLUTION["strict_true_fields"]):
        return "strict", "auto_strict"
    if all(features.get(field_name) == expected for field_name, expected in AUTO_RESOLUTION["light_match"].items()):
        return "light", "auto_light"
    return "standard", "auto_standard"


def validate_task_contract(value: Any) -> list[str]:
    required = [field for field in SEMANTIC_RULES["task_contract_fields"] if field not in TASK_CONTRACT_OPTIONAL_FIELDS]
    errors = required_fields(value, required)
    if not isinstance(value, dict):
        return errors
    unknown = sorted(set(value) - set(SEMANTIC_RULES["task_contract_fields"]))
    if unknown:
        errors.append("TaskContract 包含未知字段 " + "、".join(unknown))
    semantic_name = value.get("semantic_name")
    semantic_definition = SEMANTIC_DEFINITIONS["semantic_name"]
    errors.extend(validate_text(semantic_name, "semantic_name", maximum=int(semantic_definition["maxLength"])))
    if isinstance(semantic_name, str) and not re.fullmatch(semantic_definition["pattern"], semantic_name):
        errors.append("字段 semantic_name 只能使用小写字母、数字和单个下划线分隔")
    requested_mode, resolved_mode, resolution_reason = value.get("requested_mode"), value.get("resolved_mode"), value.get("resolution_reason")
    if requested_mode not in REQUESTED_MODES:
        errors.append("字段 requested_mode 枚举无效")
    if resolved_mode not in RESOLVED_MODES:
        errors.append("字段 resolved_mode 枚举无效")
    if resolution_reason not in RESOLUTION_REASONS:
        errors.append("字段 resolution_reason 枚举无效")
    features = value.get("task_features")
    errors.extend(validate_task_features(features, required=True))
    if requested_mode in RESOLVED_MODES:
        if resolved_mode != requested_mode:
            errors.append("显式 requested_mode 的 resolved_mode 必须与请求值相同")
        if resolution_reason != "explicit_request":
            errors.append("显式 requested_mode 的 resolution_reason 必须是 explicit_request")
    elif requested_mode == "auto" and not validate_task_features(features, required=True):
        try:
            expected_mode, expected_reason = resolve_governance_mode("auto", features)
        except ValueError:
            pass
        else:
            if resolved_mode != expected_mode:
                errors.append(f"auto 解析后的 resolved_mode 必须是 {expected_mode}")
            if resolution_reason != expected_reason:
                errors.append(f"auto 解析后的 resolution_reason 必须是 {expected_reason}")
    business_maximum = int(SEMANTIC_DEFINITIONS["business_text"]["maxLength"])
    errors.extend(validate_text(value.get("objective"), "objective", maximum=business_maximum))
    errors.extend(validate_text(value.get("background"), "background", maximum=business_maximum))
    errors.extend(validate_text_list(value.get("work_scope"), "work_scope", minimum=1))
    mode_minimums = MODE_MINIMUMS.get(str(resolved_mode), {})
    errors.extend(validate_text_list(value.get("forbidden_scope"), "forbidden_scope", minimum=int(mode_minimums.get("forbidden_scope", 0))))
    errors.extend(validate_text_list(value.get("completion_conditions"), "completion_conditions", minimum=1))
    errors.extend(validate_text_list(value.get("evidence_requirements"), "evidence_requirements", minimum=int(mode_minimums.get("evidence_requirements", 0))))
    errors.extend(validate_text_list(value.get("relevant_files"), "relevant_files"))
    errors.extend(validate_context_manifest(value.get("context_manifest")))
    errors.extend(validate_text(value.get("current_state"), "current_state", maximum=business_maximum, nullable=True))
    if "model" in value:
        errors.extend(validate_text(value.get("model"), "model", maximum=int(SEMANTIC_DEFINITIONS["model"]["maxLength"]), nullable=True))
    if "reasoning_effort" in value:
        effort = value.get("reasoning_effort")
        if effort is not None and effort not in REASONING_EFFORTS:
            errors.append("字段 reasoning_effort 枚举无效")
    strategy, turns, reason = value.get("context_strategy"), value.get("context_turns"), value.get("context_reason")
    if strategy not in CONTEXT_STRATEGIES:
        errors.append("字段 context_strategy 枚举无效")
    if strategy == "isolated":
        if turns is not None:
            errors.append("context_strategy=isolated 时 context_turns 必须是 null")
        errors.extend(validate_text(reason, "context_reason", maximum=business_maximum, nullable=True))
    elif strategy == "limited":
        minimum, maximum = int(CONTEXT_TURNS["minimum"]), int(CONTEXT_TURNS["maximum"])
        if isinstance(turns, bool) or not isinstance(turns, int) or not minimum <= turns <= maximum:
            errors.append(f"context_strategy=limited 时 context_turns 必须是 {minimum} 至 {maximum} 的整数")
        errors.extend(validate_text(reason, "context_reason", maximum=business_maximum))
    elif strategy == "full":
        if turns is not None:
            errors.append("context_strategy=full 时 context_turns 必须是 null")
        errors.extend(validate_text(reason, "context_reason", maximum=business_maximum))
    return errors


def contract_from_input(value: Any) -> TaskContract:
    if isinstance(value, TaskContract):
        raw = value.to_record()
    elif isinstance(value, dict):
        raw = copy.deepcopy(value)
    else:
        raise ValueError("TaskContract 输入必须是对象")
    unknown = sorted(set(raw) - set(SEMANTIC_RULES["task_contract_fields"]))
    if unknown:
        raise ValueError("TaskContract 包含未知字段 " + "、".join(unknown))
    raw["semantic_name"] = normalize_semantic_name(raw.get("semantic_name"))
    features = raw.get("task_features")
    if isinstance(features, TaskFeatures):
        features = features.to_record()
        raw["task_features"] = features
    resolved_mode, resolution_reason = resolve_governance_mode(raw.get("requested_mode"), features)
    if raw.get("resolved_mode") is not None and raw["resolved_mode"] != resolved_mode:
        raise ValueError(f"resolved_mode 必须由生成器解析为 {resolved_mode}")
    if raw.get("resolution_reason") is not None and raw["resolution_reason"] != resolution_reason:
        raise ValueError(f"resolution_reason 必须由生成器解析为 {resolution_reason}")
    raw["resolved_mode"], raw["resolution_reason"] = resolved_mode, resolution_reason
    errors = validate_task_contract(raw)
    if errors:
        raise ValueError("；".join(errors))
    return TaskContract(**{field: raw.get(field) for field in TaskContract.__dataclass_fields__})


def contract_summary(contract: TaskContract) -> dict[str, Any]:
    return {"objective": contract.objective, "model": contract.model}


def contract_digest(contract: TaskContract) -> str:
    encoded = json.dumps(contract.to_record(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_validate_task_features = validate_task_features
_contract_from_input = contract_from_input
_contract_summary = contract_summary
