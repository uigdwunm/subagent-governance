#!/usr/bin/env python3
"""Adaptive Codex subagent lifecycle governance hook."""

from __future__ import annotations

import argparse
import copy
import getpass
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


if os.name == "nt":
    import msvcrt

    fcntl = None
else:
    import fcntl

    msvcrt = None


SEMANTICS_PATH = Path(__file__).resolve().parents[1] / "schemas/governance-semantics.schema.json"


def _load_machine_semantics() -> dict[str, Any]:
    try:
        value = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取治理机器语义源：{SEMANTICS_PATH}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("$defs"), dict):
        raise RuntimeError(f"治理机器语义源缺少 $defs：{SEMANTICS_PATH}")
    if not isinstance(value.get("x-semantics"), dict):
        raise RuntimeError(f"治理机器语义源缺少 x-semantics：{SEMANTICS_PATH}")
    return value


MACHINE_SEMANTICS = _load_machine_semantics()
SEMANTIC_DEFINITIONS = MACHINE_SEMANTICS["$defs"]
SEMANTIC_RULES = MACHINE_SEMANTICS["x-semantics"]


def _semantic_enum(name: str) -> frozenset[str]:
    definition = SEMANTIC_DEFINITIONS.get(name)
    values = definition.get("enum") if isinstance(definition, dict) else None
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise RuntimeError(f"治理机器语义源中的枚举 {name} 无效")
    return frozenset(values)


REQUESTED_MODES = _semantic_enum("requested_mode")
RESOLVED_MODES = _semantic_enum("resolved_mode")
VALID_MODES = set(REQUESTED_MODES)
RESOLUTION_REASONS = _semantic_enum("resolution_reason")
RISKS = _semantic_enum("risk")
REASONING_EFFORTS = _semantic_enum("reasoning_effort")
CONTEXT_STRATEGIES = _semantic_enum("context_strategy")
OPERATION_TYPES = _semantic_enum("operation_type")
EXECUTION_STATUSES = _semantic_enum("execution_status")
SPAWN_OBSERVATIONS = _semantic_enum("spawn_observation")
IDENTITY_STATUSES = _semantic_enum("identity_status")
PLATFORM_OBSERVATIONS = _semantic_enum("platform_observation")
BUSINESS_RESULTS = _semantic_enum("business_result")
ACCEPTANCE_STATUSES = _semantic_enum("acceptance_status")
RESULT_PROTOCOL_STATUSES = _semantic_enum("result_protocol_status")
RESULT_STORAGE_STATUSES = _semantic_enum("result_storage_status")
RECOVERY_STATUSES = _semantic_enum("recovery_status")
PARENT_ACTIONS = _semantic_enum("parent_action")
PARENT_DISPOSITIONS = _semantic_enum("parent_disposition")
CALL_OBSERVATIONS = _semantic_enum("call_observation")
LIFECYCLE_OPERATION_TYPES = _semantic_enum("lifecycle_operation_type")
RETRY_LIMITS = dict(SEMANTIC_RULES["retry_limits"])
RETENTION_SECONDS = dict(SEMANTIC_RULES["retention_seconds"])
OPERATION_NATIVE_TOOLS = dict(SEMANTIC_RULES["operation_native_tools"])
BUSINESS_RESULT_PARENT_ACTION = dict(SEMANTIC_RULES["business_result_parent_action"])
AUTO_RESOLUTION = dict(SEMANTIC_RULES["auto_resolution"])
MODE_MINIMUMS = dict(SEMANTIC_RULES["mode_minimums"])
CONTEXT_TURNS = dict(SEMANTIC_RULES["context_turns"])
TASK_CONTRACT_OPTIONAL_FIELDS = tuple(SEMANTIC_RULES["task_contract_optional_fields"])
TASK_RESULT_BASE_REQUIRED_FIELDS = tuple(SEMANTIC_RULES["task_result_base_required_fields"])
TASK_RESULT_SCENARIO_FIELDS = dict(SEMANTIC_RULES["task_result_scenario_fields"])
INITIAL_ATTEMPT_STATE = dict(SEMANTIC_RULES["initial_attempt_state"])
FORMAL_RESULT_STORAGE = dict(SEMANTIC_RULES["formal_result_storage"])
DIAGNOSTIC_LIMITS = dict(SEMANTIC_RULES["diagnostic_limits"])
GROUP_SEMANTICS = dict(SEMANTIC_RULES["group"])
PARENT_DISPOSITION_REASON_MAX_LENGTH = int(
    SEMANTIC_RULES["parent_disposition_reason_max_length"]
)
TASK_NAME_PATTERN = str(SEMANTIC_RULES["task_name"]["pattern"])
TASK_NAME_MAX_LENGTH = int(SEMANTIC_RULES["task_name"]["max_length"])
TASK_REF_LENGTHS = tuple(int(value) for value in SEMANTIC_RULES["task_name"]["task_ref_lengths"])
TASK_NAME_RE = re.compile(
    r"^sg_(light|standard|strict)_([a-z0-9]+(?:_[a-z0-9]+)*)_t_([a-f0-9]{12,32})$"
)

MAX_HOOK_INPUT_BYTES = 2 * 1024 * 1024
MAX_PREPARED_BYTES = MAX_HOOK_INPUT_BYTES
NEW_TASK_SOFT_LIMIT_BYTES = 3 * 1024 * 1024
MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_RESULT_BYTES = MAX_HOOK_INPUT_BYTES
MAX_CONTRACT_TEXT = int(SEMANTIC_DEFINITIONS["short_text"]["maxLength"])
SESSION_SUMMARY_RECORD_LIMIT = 8
SESSION_SUMMARY_CONTEXT_LIMIT = 1800
SESSION_SUMMARY_FIELD_LIMIT = 96
STOP_READ_ATTEMPTS = int(SEMANTIC_RULES["stop_read_attempts"])
STOP_READ_RETRY_DELAY_SECONDS = 0.05
DIAGNOSTIC_SESSION_LIMIT = int(DIAGNOSTIC_LIMITS["sessions"])
DIAGNOSTIC_ATTEMPT_LIMIT = int(DIAGNOSTIC_LIMITS["attempts_per_session"])
DIAGNOSTIC_GROUP_LIMIT = int(DIAGNOSTIC_LIMITS["groups_per_session"])
DIAGNOSTIC_ISSUE_LIMIT = int(DIAGNOSTIC_LIMITS["issues"])
DIAGNOSTIC_OUTPUT_BYTES = int(DIAGNOSTIC_LIMITS["output_bytes"])
GROUP_MEMBER_LIMIT = int(GROUP_SEMANTICS["members_max_items"])
GROUP_ID_MAX_LENGTH = int(GROUP_SEMANTICS["group_id_max_length"])
GROUP_OBJECTIVE_MAX_LENGTH = int(GROUP_SEMANTICS["objective_summary_max_length"])


class StateStoreError(RuntimeError):
    """Base class for explicit StateStore failures."""


class StateValidationError(StateStoreError):
    """The existing state or requested write is structurally unsafe."""


class StateCapacityError(StateStoreError):
    """The requested state exceeds a configured admission boundary."""


class StateConflictError(StateStoreError):
    """A compare-and-set predicate did not match the locked state."""


class StateWriteError(StateStoreError):
    """The state could not be atomically written and verified."""


class PreparedContractError(RuntimeError):
    """Base class for PreparedContract persistence and validation failures."""


class PreparedContractValidationError(PreparedContractError):
    """A PreparedContract is missing required mechanical facts or is unsafe."""


class PreparedContractConflictError(PreparedContractError):
    """A PreparedContract compare-and-set predicate did not match."""


class PreparedContractWriteError(PreparedContractError):
    """A PreparedContract could not be atomically written and verified."""


class DispatchPreparationError(RuntimeError):
    """The deterministic dispatch package could not pass both hard gates."""


class CommunicationPreparationError(RuntimeError):
    """A communication or interrupt package could not pass mechanical gates."""


class ResultSubmissionError(RuntimeError):
    """A formal TaskResult could not be safely submitted or associated."""


class ResultStorageError(ResultSubmissionError):
    """A mechanically valid TaskResult could not be stored or read back."""


class ParentDispositionError(RuntimeError):
    """A parent disposition request failed mechanical validation."""


class ParentDispositionConflict(ParentDispositionError):
    """A parent disposition conflicts with the current persisted task facts."""

    def __init__(
        self,
        message: str,
        *,
        interrupt_targets: list[str] | None = None,
        current_attempt: int | None = None,
    ):
        super().__init__(message)
        self.interrupt_targets = list(interrupt_targets or [])
        self.current_attempt = current_attempt


class GroupValidationError(RuntimeError):
    """A lightweight group request or persisted group is mechanically invalid."""


class GroupNotFoundError(GroupValidationError):
    """The requested lightweight group does not exist in the Session."""


class DiagnosticReadError(RuntimeError):
    """A read-only diagnostic target could not be normalized."""

    def __init__(self, code: str, message: str, *, context: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})


@dataclass(frozen=True)
class TaskFeatures:
    risk: str
    read_only: bool
    writes_files: bool
    destructive: bool
    production: bool
    concurrent_write: bool
    multi_stage_acceptance: bool
    allows_child_agents: bool | None = None

    def to_record(self) -> dict[str, Any]:
        record = {
            "risk": self.risk,
            "read_only": self.read_only,
            "writes_files": self.writes_files,
            "destructive": self.destructive,
            "production": self.production,
            "concurrent_write": self.concurrent_write,
            "multi_stage_acceptance": self.multi_stage_acceptance,
        }
        if self.allows_child_agents is not None:
            record["allows_child_agents"] = self.allows_child_agents
        return record


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
            "current_state": self.current_state,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "context_strategy": self.context_strategy,
            "context_turns": self.context_turns,
            "context_reason": self.context_reason,
        }


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    attempt: int
    business_result: str
    result: str
    evidence: list[str]
    remaining: list[str]
    suggested_parent_next_step: str
    blocker: str | None = None
    attempted: list[str] | None = None
    required_to_resume: str | None = None
    failure_reason: str | None = None
    retry_conditions: str | None = None
    decision_question: str | None = None
    options: list[str] | None = None
    recommendation: str | None = None

    def to_record(self) -> dict[str, Any]:
        record = {
            "task_id": self.task_id,
            "attempt": self.attempt,
            "business_result": self.business_result,
            "result": self.result,
            "evidence": list(self.evidence),
            "remaining": list(self.remaining),
            "suggested_parent_next_step": self.suggested_parent_next_step,
        }
        for field_name in (
            "blocker",
            "attempted",
            "required_to_resume",
            "failure_reason",
            "retry_conditions",
            "decision_question",
            "options",
            "recommendation",
        ):
            value = getattr(self, field_name)
            if value is not None:
                record[field_name] = list(value) if isinstance(value, list) else value
        return record


@dataclass(frozen=True)
class AttemptState:
    execution_status: str = INITIAL_ATTEMPT_STATE["execution_status"]
    spawn_observation: str | None = INITIAL_ATTEMPT_STATE["spawn_observation"]
    identity_status: str = INITIAL_ATTEMPT_STATE["identity_status"]
    platform_observation: str | None = INITIAL_ATTEMPT_STATE["platform_observation"]
    business_result: str | None = INITIAL_ATTEMPT_STATE["business_result"]
    acceptance_status: str | None = INITIAL_ATTEMPT_STATE["acceptance_status"]
    result_protocol_status: str | None = INITIAL_ATTEMPT_STATE["result_protocol_status"]
    result_storage_status: str | None = INITIAL_ATTEMPT_STATE["result_storage_status"]
    result_conflict: bool = INITIAL_ATTEMPT_STATE["result_conflict"]
    recovery_status: str | None = INITIAL_ATTEMPT_STATE["recovery_status"]
    parent_action: str | None = INITIAL_ATTEMPT_STATE["parent_action"]
    spawn_retry_count: int = INITIAL_ATTEMPT_STATE["spawn_retry_count"]
    recovery_count: int = INITIAL_ATTEMPT_STATE["recovery_count"]
    correction_count: int = INITIAL_ATTEMPT_STATE["correction_count"]

    def to_record(self) -> dict[str, Any]:
        return {
            "execution_status": self.execution_status,
            "spawn_observation": self.spawn_observation,
            "identity_status": self.identity_status,
            "platform_observation": self.platform_observation,
            "business_result": self.business_result,
            "acceptance_status": self.acceptance_status,
            "result_protocol_status": self.result_protocol_status,
            "result_storage_status": self.result_storage_status,
            "result_conflict": self.result_conflict,
            "recovery_status": self.recovery_status,
            "parent_action": self.parent_action,
            "spawn_retry_count": self.spawn_retry_count,
            "recovery_count": self.recovery_count,
            "correction_count": self.correction_count,
        }


def _required_fields(value: Any, fields: list[str]) -> list[str]:
    if not isinstance(value, dict):
        return ["根节点必须是对象"]
    return [f"缺少字段 {field_name}" for field_name in fields if field_name not in value]


def _validate_text(
    value: Any,
    field_name: str,
    *,
    maximum: int,
    nullable: bool = False,
) -> list[str]:
    if value is None and nullable:
        return []
    if not isinstance(value, str):
        return [f"字段 {field_name} 必须是字符串" + ("或 null" if nullable else "")]
    if not value.strip():
        return [f"字段 {field_name} 不能为空"]
    if len(value) > maximum:
        return [f"字段 {field_name} 长度不能超过 {maximum}"]
    return []


def _validate_text_list(
    value: Any,
    field_name: str,
    *,
    minimum: int = 0,
) -> list[str]:
    definition = SEMANTIC_DEFINITIONS["text_list"]
    maximum_items = int(definition["maxItems"])
    item_maximum = int(definition["items"]["maxLength"])
    if not isinstance(value, list):
        return [f"字段 {field_name} 必须是数组"]
    errors: list[str] = []
    if len(value) < minimum:
        errors.append(f"字段 {field_name} 至少需要 {minimum} 项")
    if len(value) > maximum_items:
        errors.append(f"字段 {field_name} 不能超过 {maximum_items} 项")
    for index, item in enumerate(value):
        errors.extend(
            _validate_text(item, f"{field_name}[{index}]", maximum=item_maximum)
        )
    return errors


def _validate_task_features(value: Any, *, required: bool) -> list[str]:
    if value is None:
        return ["requested_mode=auto 时缺少字段 task_features"] if required else []
    if isinstance(value, TaskFeatures):
        value = value.to_record()
    if not isinstance(value, dict):
        return ["字段 task_features 必须是对象或 null"]
    required_fields = list(SEMANTIC_DEFINITIONS["task_features"]["required"])
    errors = _required_fields(value, required_fields)
    risk = value.get("risk")
    if risk not in RISKS:
        errors.append("字段 task_features.risk 必须是 low、medium 或 high")
    for field_name in required_fields[1:]:
        if not isinstance(value.get(field_name), bool):
            errors.append(f"字段 task_features.{field_name} 必须是布尔值")
    if "allows_child_agents" in value and not isinstance(value.get("allows_child_agents"), bool):
        errors.append("字段 task_features.allows_child_agents 必须是布尔值")
    if value.get("read_only") is True and value.get("writes_files") is True:
        errors.append("task_features.read_only=true 与 writes_files=true 机械矛盾")
    return errors


def resolve_governance_mode(
    requested_mode: str,
    task_features: dict[str, Any] | TaskFeatures | None = None,
) -> tuple[str, str]:
    if requested_mode not in REQUESTED_MODES:
        raise ValueError("requested_mode 必须是 auto、light、standard 或 strict")
    if requested_mode in RESOLVED_MODES:
        return requested_mode, "explicit_request"
    errors = _validate_task_features(task_features, required=True)
    if errors:
        raise ValueError("；".join(errors))
    features = task_features.to_record() if isinstance(task_features, TaskFeatures) else task_features
    assert isinstance(features, dict)
    strict_signal = features.get("risk") in AUTO_RESOLUTION["strict_risks"] or any(
        features.get(field_name) is True
        for field_name in AUTO_RESOLUTION["strict_true_fields"]
    )
    if strict_signal:
        return "strict", "auto_strict"
    if all(features.get(field_name) == expected for field_name, expected in AUTO_RESOLUTION["light_match"].items()):
        return "light", "auto_light"
    return "standard", "auto_standard"


def validate_task_contract(value: Any) -> list[str]:
    required = [
        field_name
        for field_name in SEMANTIC_RULES["task_contract_fields"]
        if field_name not in TASK_CONTRACT_OPTIONAL_FIELDS
    ]
    errors = _required_fields(value, required)
    if not isinstance(value, dict):
        return errors

    semantic_name = value.get("semantic_name")
    semantic_definition = SEMANTIC_DEFINITIONS["semantic_name"]
    errors.extend(
        _validate_text(
            semantic_name,
            "semantic_name",
            maximum=int(semantic_definition["maxLength"]),
        )
    )
    if isinstance(semantic_name, str) and not re.fullmatch(semantic_definition["pattern"], semantic_name):
        errors.append("字段 semantic_name 只能使用小写字母、数字和单个下划线分隔")

    requested_mode = value.get("requested_mode")
    resolved_mode = value.get("resolved_mode")
    resolution_reason = value.get("resolution_reason")
    if requested_mode not in REQUESTED_MODES:
        errors.append("字段 requested_mode 枚举无效")
    if resolved_mode not in RESOLVED_MODES:
        errors.append("字段 resolved_mode 枚举无效")
    if resolution_reason not in RESOLUTION_REASONS:
        errors.append("字段 resolution_reason 枚举无效")

    features = value.get("task_features")
    errors.extend(_validate_task_features(features, required=requested_mode == "auto"))
    if requested_mode in RESOLVED_MODES:
        if resolved_mode != requested_mode:
            errors.append("显式 requested_mode 的 resolved_mode 必须与请求值相同")
        if resolution_reason != "explicit_request":
            errors.append("显式 requested_mode 的 resolution_reason 必须是 explicit_request")
    elif requested_mode == "auto" and not _validate_task_features(features, required=True):
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
    errors.extend(_validate_text(value.get("objective"), "objective", maximum=business_maximum))
    errors.extend(_validate_text(value.get("background"), "background", maximum=business_maximum))
    errors.extend(_validate_text_list(value.get("work_scope"), "work_scope", minimum=1))
    mode_minimums = MODE_MINIMUMS.get(str(resolved_mode), {})
    errors.extend(
        _validate_text_list(
            value.get("forbidden_scope"),
            "forbidden_scope",
            minimum=int(mode_minimums.get("forbidden_scope", 0)),
        )
    )
    errors.extend(
        _validate_text_list(value.get("completion_conditions"), "completion_conditions", minimum=1)
    )
    evidence_minimum = int(mode_minimums.get("evidence_requirements", 0))
    errors.extend(
        _validate_text_list(
            value.get("evidence_requirements"),
            "evidence_requirements",
            minimum=evidence_minimum,
        )
    )
    errors.extend(_validate_text_list(value.get("relevant_files"), "relevant_files"))
    errors.extend(
        _validate_text(
            value.get("current_state"),
            "current_state",
            maximum=business_maximum,
            nullable=True,
        )
    )

    if "model" in value:
        errors.extend(
            _validate_text(
                value.get("model"),
                "model",
                maximum=int(SEMANTIC_DEFINITIONS["model"]["maxLength"]),
                nullable=True,
            )
        )
    if "reasoning_effort" in value:
        effort = value.get("reasoning_effort")
        if effort is not None and effort not in REASONING_EFFORTS:
            errors.append("字段 reasoning_effort 枚举无效")

    strategy = value.get("context_strategy")
    turns = value.get("context_turns")
    reason = value.get("context_reason")
    if strategy not in CONTEXT_STRATEGIES:
        errors.append("字段 context_strategy 枚举无效")
    if strategy == "isolated":
        if turns is not None:
            errors.append("context_strategy=isolated 时 context_turns 必须是 null")
        errors.extend(_validate_text(reason, "context_reason", maximum=business_maximum, nullable=True))
    elif strategy == "limited":
        minimum = int(CONTEXT_TURNS["minimum"])
        maximum = int(CONTEXT_TURNS["maximum"])
        if isinstance(turns, bool) or not isinstance(turns, int) or not minimum <= turns <= maximum:
            errors.append(
                f"context_strategy=limited 时 context_turns 必须是 {minimum} 至 {maximum} 的整数"
            )
        errors.extend(_validate_text(reason, "context_reason", maximum=business_maximum))
    elif strategy == "full":
        if turns is not None:
            errors.append("context_strategy=full 时 context_turns 必须是 null")
        errors.extend(_validate_text(reason, "context_reason", maximum=business_maximum))
    return errors


def validate_task_result(value: Any) -> list[str]:
    required = list(TASK_RESULT_BASE_REQUIRED_FIELDS)
    errors = _required_fields(value, required)
    if not isinstance(value, dict):
        return errors
    errors.extend(
        _validate_text(
            value.get("task_id"),
            "task_id",
            maximum=int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"]),
        )
    )
    attempt = value.get("attempt")
    attempt_minimum = int(SEMANTIC_DEFINITIONS["attempt"]["minimum"])
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < attempt_minimum:
        errors.append(f"字段 attempt 必须是大于等于 {attempt_minimum} 的整数")
    business_result = value.get("business_result")
    if business_result not in BUSINESS_RESULTS:
        errors.append("字段 business_result 枚举无效")
    errors.extend(
        _validate_text(
            value.get("result"),
            "result",
            maximum=int(SEMANTIC_DEFINITIONS["result_text"]["maxLength"]),
        )
    )
    errors.extend(_validate_text_list(value.get("evidence"), "evidence"))
    errors.extend(_validate_text_list(value.get("remaining"), "remaining"))
    errors.extend(
        _validate_text(
            value.get("suggested_parent_next_step"),
            "suggested_parent_next_step",
            maximum=int(SEMANTIC_DEFINITIONS["business_text"]["maxLength"]),
        )
    )

    scenario_fields = TASK_RESULT_SCENARIO_FIELDS
    for field_name in scenario_fields.get(str(business_result), ()):
        if field_name not in value:
            errors.append(f"business_result={business_result} 时缺少字段 {field_name}")
            continue
        if field_name in {"attempted", "options"}:
            minimum = 1 if field_name == "options" else 0
            errors.extend(_validate_text_list(value.get(field_name), field_name, minimum=minimum))
        else:
            errors.extend(
                _validate_text(
                    value.get(field_name),
                    field_name,
                    maximum=int(SEMANTIC_DEFINITIONS["business_text"]["maxLength"]),
                )
            )
    for field_name in (
        "blocker",
        "required_to_resume",
        "failure_reason",
        "retry_conditions",
        "decision_question",
        "recommendation",
    ):
        if field_name in value and field_name not in scenario_fields.get(str(business_result), ()):
            errors.extend(
                _validate_text(
                    value.get(field_name),
                    field_name,
                    maximum=int(SEMANTIC_DEFINITIONS["business_text"]["maxLength"]),
                )
            )
    for field_name in ("attempted", "options"):
        if field_name in value and field_name not in scenario_fields.get(str(business_result), ()):
            minimum = 1 if field_name == "options" else 0
            errors.extend(_validate_text_list(value.get(field_name), field_name, minimum=minimum))
    return errors


def normalize_semantic_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", text)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "task"


def derive_task_ref(task_id: str, attempt: int, length: int) -> str:
    if length not in TASK_REF_LENGTHS:
        raise ValueError(f"task_ref 长度必须是 {', '.join(map(str, TASK_REF_LENGTHS))} 之一")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id 必须是非空字符串")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt 必须是正整数")
    digest = hashlib.sha256(f"{task_id}:{attempt}".encode("utf-8")).hexdigest()
    return digest[:length]


def select_task_ref(task_id: str, attempt: int, occupied_refs: set[str]) -> str | None:
    for length in TASK_REF_LENGTHS:
        candidate = derive_task_ref(task_id, attempt, length)
        if candidate not in occupied_refs:
            return candidate
    return None


def build_task_name(resolved_mode: str, semantic_name: str, task_ref: str) -> str:
    if resolved_mode not in RESOLVED_MODES:
        raise ValueError("resolved_mode 必须是 light、standard 或 strict")
    if len(task_ref) not in TASK_REF_LENGTHS or not re.fullmatch(r"[a-f0-9]+", task_ref):
        raise ValueError("task_ref 必须是允许长度的小写十六进制")
    normalized = normalize_semantic_name(semantic_name)
    fixed_length = len(f"sg_{resolved_mode}__t_{task_ref}")
    available = TASK_NAME_MAX_LENGTH - fixed_length
    if available < 1:
        raise ValueError("task_name 固定字段超过长度上限")
    semantic = normalized[:available].rstrip("_") or "task"[:available]
    task_name = f"sg_{resolved_mode}_{semantic}_t_{task_ref}"
    if len(task_name) > TASK_NAME_MAX_LENGTH or TASK_NAME_RE.fullmatch(task_name) is None:
        raise ValueError("无法生成合法且不超过64字符的 task_name")
    return task_name


def parse_task_name(task_name: Any) -> tuple[str, str, str] | None:
    if not isinstance(task_name, str) or len(task_name) > TASK_NAME_MAX_LENGTH:
        return None
    match = TASK_NAME_RE.fullmatch(task_name)
    if not match or len(match.group(3)) not in TASK_REF_LENGTHS:
        return None
    return match.group(1), match.group(2), match.group(3)


def _contract_from_input(value: Any) -> TaskContract:
    if isinstance(value, TaskContract):
        raw = value.to_record()
    elif isinstance(value, dict):
        raw = copy.deepcopy(value)
    else:
        raise ValueError("TaskContract 输入必须是对象")
    raw["semantic_name"] = normalize_semantic_name(raw.get("semantic_name"))
    features = raw.get("task_features")
    if isinstance(features, TaskFeatures):
        features = features.to_record()
        raw["task_features"] = features
    requested_mode = raw.get("requested_mode")
    resolved_mode, resolution_reason = resolve_governance_mode(requested_mode, features)
    supplied_mode = raw.get("resolved_mode")
    supplied_reason = raw.get("resolution_reason")
    if supplied_mode is not None and supplied_mode != resolved_mode:
        raise ValueError(f"resolved_mode 必须由生成器解析为 {resolved_mode}")
    if supplied_reason is not None and supplied_reason != resolution_reason:
        raise ValueError(f"resolution_reason 必须由生成器解析为 {resolution_reason}")
    raw["resolved_mode"] = resolved_mode
    raw["resolution_reason"] = resolution_reason
    raw.setdefault("task_features", None)
    raw.setdefault("model", None)
    raw.setdefault("reasoning_effort", None)
    errors = validate_task_contract(raw)
    if errors:
        raise ValueError("；".join(errors))
    field_names = TaskContract.__dataclass_fields__
    return TaskContract(**{field_name: raw.get(field_name) for field_name in field_names})


def _context_projection(contract: TaskContract) -> tuple[str, str]:
    if contract.context_strategy == "isolated":
        return "none", "否"
    if contract.context_strategy == "limited":
        assert contract.context_turns is not None
        return str(contract.context_turns), f"否（仅继承最近 {contract.context_turns} 轮）"
    return "all", "是"


def _render_list(values: list[str]) -> str:
    if not values:
        return "- 无"
    return "\n".join(f"- {value}" for value in values)


def render_dispatch_prompt(contract: TaskContract) -> str:
    current_state = contract.current_state or "无额外未落盘状态"
    context_reason = contract.context_reason or "默认隔离；任务背景已写入本首句"
    return "\n".join(
        (
            f"【治理等级】{contract.resolved_mode}",
            "【唯一当前目标】",
            contract.objective,
            "",
            "【背景】",
            contract.background,
            "",
            "【工作范围】",
            _render_list(contract.work_scope),
            "",
            "【禁止范围】",
            _render_list(contract.forbidden_scope),
            "",
            "【相关文件】",
            _render_list(contract.relevant_files),
            "",
            "【当前状态】",
            current_state,
            "",
            "【上下文策略】",
            f"{contract.context_strategy}：{context_reason}",
            "",
            "【完成条件】",
            _render_list(contract.completion_conditions),
            "",
            "【验收证据】",
            _render_list(contract.evidence_requirements),
            "",
            "【恢复与终态义务】",
            "完成、阻塞、失败或需要决策时，向父 Agent发送明确终态通知；不要只回复收到、明白或开始执行。",
            "平台或调用结果未知时如实报告，不得自行重派、伪造成功或覆盖其他 attempt。",
        )
    )


def render_dispatch_user_message(contract: TaskContract) -> str:
    _native_context, context_display = _context_projection(contract)
    model_display = contract.model or "继承主 Agent（未显式覆盖）"
    effort_display = contract.reasoning_effort or "继承主 Agent 当前强度（未显式覆盖）"
    mode_line = f"治理等级：{contract.resolved_mode}"
    if contract.requested_mode == "auto":
        mode_line = (
            f"请求治理方式：auto；实际治理等级：{contract.resolved_mode}；"
            f"解析原因：{contract.resolution_reason}"
        )
    return "\n".join(
        (
            "【子 Agent 派发】",
            f"目标：{contract.objective}",
            mode_line,
            f"模型：{model_display}",
            f"强度：{effort_display}",
            f"是否继承主线程全部上下文：{context_display}",
            "工作范围：" + "；".join(contract.work_scope),
            "完成条件：" + "；".join(contract.completion_conditions),
            "回传要求：完成、阻塞或需要决策时，向父 Agent发送明确终态通知",
        )
    )


def _spawn_args(contract: TaskContract, task_name: str) -> dict[str, Any]:
    fork_turns, _context_display = _context_projection(contract)
    result: dict[str, Any] = {
        "task_name": task_name,
        "message": render_dispatch_prompt(contract),
        "fork_turns": fork_turns,
    }
    if contract.model is not None:
        result["model"] = contract.model
    if contract.reasoning_effort is not None:
        result["reasoning_effort"] = contract.reasoning_effort
    return result


def adapt_spawn_response(response: Any) -> dict[str, Any]:
    value = _json_value(response)
    if not isinstance(value, dict):
        return {"observation": "unknown", "agent_id": None, "canonical_path": None}
    candidate = value
    structured = value.get("structuredContent")
    if isinstance(structured, dict):
        candidate = structured

    failed = (
        value.get("isError") is True
        or value.get("is_error") is True
        or candidate.get("isError") is True
        or candidate.get("is_error") is True
    )
    status_source = candidate if candidate is not value else value
    status_value = (
        status_source.get("status")
        if "status" in status_source
        else status_source.get("state")
    )
    status = status_value.lower() if isinstance(status_value, str) else None
    if status in {"error", "failed", "failure"}:
        failed = True

    agent_id = None
    for field_name in ("agent_id", "agentId"):
        field_value = candidate.get(field_name)
        if isinstance(field_value, str) and field_value.strip():
            agent_id = field_value.strip()
            break
    canonical_path = None
    for field_name in ("canonical_task_path", "canonical_path", "task_path", "task_name"):
        field_value = candidate.get(field_name)
        if isinstance(field_value, str) and field_value.startswith("/"):
            canonical_path = field_value
            break
    if failed and (agent_id or canonical_path):
        return {"observation": "unknown", "agent_id": None, "canonical_path": None}
    if failed:
        return {"observation": "failed", "agent_id": None, "canonical_path": None}
    if agent_id or canonical_path:
        return {
            "observation": "success",
            "agent_id": agent_id,
            "canonical_path": canonical_path,
        }
    if status in {"ok", "success", "succeeded", "created"}:
        return {"observation": "success", "agent_id": None, "canonical_path": None}
    return {"observation": "unknown", "agent_id": None, "canonical_path": None}


def _now() -> int:
    return int(time.time())


def _current_uid() -> int | None:
    getuid = getattr(os, "getuid", None)
    return int(getuid()) if getuid is not None else None


def _owned_by_current_user(metadata: os.stat_result) -> bool:
    uid = _current_uid()
    return uid is None or getattr(metadata, "st_uid", uid) == uid


def _private_permissions_safe(metadata: os.stat_result) -> bool:
    return os.name == "nt" or stat.S_IMODE(metadata.st_mode) & 0o077 == 0


def _restrict_descriptor(descriptor: int, mode: int) -> None:
    fchmod = getattr(os, "fchmod", None)
    if fchmod is not None:
        fchmod(descriptor, mode)


def _restrict_path(path: Path, mode: int) -> None:
    if os.name != "nt":
        path.chmod(mode)


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _uses_windows_file_lock() -> bool:
    return os.name == "nt"


@contextmanager
def _exclusive_file_lock(lock_file):
    descriptor = lock_file.fileno()
    if _uses_windows_file_lock():
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write("\0")
            lock_file.flush()
            os.fsync(descriptor)
        lock_file.seek(0)
        assert msvcrt is not None
        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            lock_file.seek(0)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    assert fcntl is not None
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


def _user_storage_key() -> str:
    uid = _current_uid()
    if uid is not None:
        return str(uid)
    username = os.environ.get("USERNAME") or getpass.getuser() or "user"
    return hashlib.sha256(username.encode("utf-8")).hexdigest()[:12]


def _activity_timestamp(record: dict[str, Any]) -> int:
    timestamps = []
    for field in (
        "updated_at",
        "platform_checked_at",
        "spawn_post_observed_at",
        "spawn_claimed_at",
        "attempt_closed_at",
        "created_at",
    ):
        try:
            timestamps.append(int(record.get(field) or 0))
        except (TypeError, ValueError):
            continue
    for container_name in ("pending_action", "last_lifecycle_operation"):
        container = record.get(container_name)
        if not isinstance(container, dict):
            continue
        for field in ("completed_at", "claimed_at", "created_at", "start_observed_at"):
            try:
                timestamps.append(int(container.get(field) or 0))
            except (TypeError, ValueError):
                continue
    return max(timestamps, default=0)


def _safe_name(value: str) -> str:
    raw = value or "unknown"
    prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")[:64] or "unknown"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _prepare_private_directory(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"治理状态目录必须是普通目录且不能是符号链接：{root}")
    if not _owned_by_current_user(metadata):
        raise PermissionError(f"治理状态目录不属于当前用户：{root}")
    _restrict_path(root, 0o700)
    return root


def _installed_plugin_data_root(script_path: Path | None = None) -> Path | None:
    resolved = (script_path or Path(__file__)).resolve(strict=False)
    parts = resolved.parts
    for index in range(len(parts) - 6):
        if parts[index : index + 2] != ("plugins", "cache"):
            continue
        marketplace = parts[index + 2]
        plugin_name = parts[index + 3]
        if (
            not marketplace
            or not plugin_name
            or parts[index + 5] != "scripts"
            or parts[index + 6] != "subagent_governance.py"
        ):
            continue
        codex_root = Path(*parts[:index])
        return (
            codex_root
            / "plugins"
            / "data"
            / f"{plugin_name}-{marketplace}"
            / "state-v1"
        )
    return None


def _data_root_path() -> Path:
    override = os.environ.get("SUBAGENT_GOVERNANCE_DATA")
    plugin_data = os.environ.get("PLUGIN_DATA")
    if override:
        root = Path(override).expanduser()
    elif plugin_data:
        root = Path(plugin_data).expanduser() / "state-v1"
    elif installed_root := _installed_plugin_data_root():
        root = installed_root
    else:
        root = Path(tempfile.gettempdir()) / f"subagent-governance-{_user_storage_key()}"
    return root


def _data_root() -> Path:
    return _prepare_private_directory(_data_root_path())


class StateStore:
    def __init__(self, root: Path | None = None):
        self.root = (
            _prepare_private_directory(root)
            if root is not None
            else _prepare_private_directory(_data_root() / "sessions")
        )
        self.last_warning: str | None = None

    @staticmethod
    def _empty_state(session_id: str) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "tasks": {},
            "agents": {},
            "health": {"status": "ok"},
            "tombstones": {},
            "updated_at": _now(),
        }

    @staticmethod
    def initial_attempt_state() -> dict[str, Any]:
        return copy.deepcopy(AttemptState().to_record())

    def _paths(self, session_id: str) -> tuple[Path, Path]:
        stem = _safe_name(session_id)
        return self.root / f"{stem}.json", self.root / f"{stem}.lock"

    @contextmanager
    def _lock(self, session_id: str):
        state_path, lock_path = self._paths(session_id)
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise StateValidationError(f"治理锁文件无法安全打开：{lock_path}") from exc
        with os.fdopen(descriptor, "a+", encoding="utf-8") as lock_file:
            metadata = os.fstat(lock_file.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise StateValidationError(f"治理锁文件必须是普通文件：{lock_path}")
            if not _owned_by_current_user(metadata):
                raise StateValidationError(f"治理锁文件不属于当前用户：{lock_path}")
            _restrict_descriptor(lock_file.fileno(), 0o600)
            with _exclusive_file_lock(lock_file):
                yield state_path

    @staticmethod
    def _validate_required_fields(
        value: dict[str, Any],
        required_fields: tuple[str, ...],
        path: Path,
    ) -> None:
        missing = [field_name for field_name in required_fields if field_name not in value]
        if missing:
            raise StateValidationError(
                f"治理状态缺少当前操作必需字段 {', '.join(missing)}：{path}"
            )
        for field_name in required_fields:
            if field_name in {"tasks", "agents", "health", "tombstones"} and not isinstance(
                value.get(field_name), dict
            ):
                raise StateValidationError(
                    f"治理状态字段 {field_name} 必须是对象：{path}"
                )

    @classmethod
    def _validate_state(
        cls,
        value: Any,
        session_id: str,
        path: Path,
        required_fields: tuple[str, ...],
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise StateValidationError(f"治理状态文件根节点必须是对象：{path}")
        if "session_id" not in value:
            raise StateValidationError(f"治理状态缺少当前操作必需字段 session_id：{path}")
        if value.get("session_id") != session_id:
            raise StateValidationError(f"治理状态文件与当前 session 不匹配：{path}")
        cls._validate_required_fields(value, required_fields, path)
        return value

    def _read_path(
        self,
        path: Path,
        session_id: str,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
    ) -> dict[str, Any]:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            state = self._empty_state(session_id)
            return self._validate_state(state, session_id, path, required_fields)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise StateValidationError(f"治理状态文件必须是普通文件且不能是符号链接：{path}")
        if not _owned_by_current_user(metadata):
            raise StateValidationError(f"治理状态文件不属于当前用户：{path}")
        if not _private_permissions_safe(metadata):
            raise StateValidationError(f"治理状态文件权限必须限制为当前用户可访问：{path}")
        if metadata.st_size > MAX_STATE_BYTES:
            raise StateCapacityError(f"治理状态文件超过 {MAX_STATE_BYTES} 字节上限：{path}")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise StateValidationError(f"治理状态文件无法安全打开，原文件已保留：{path}") from exc
        try:
            with os.fdopen(descriptor, "rb") as state_file:
                opened_metadata = os.fstat(state_file.fileno())
                if not stat.S_ISREG(opened_metadata.st_mode):
                    raise StateValidationError(f"治理状态文件必须是普通文件：{path}")
                if not _owned_by_current_user(opened_metadata):
                    raise StateValidationError(f"治理状态文件不属于当前用户：{path}")
                if not _private_permissions_safe(opened_metadata):
                    raise StateValidationError(
                        f"治理状态文件权限必须限制为当前用户可访问：{path}"
                    )
                raw = state_file.read(MAX_STATE_BYTES + 1)
        except OSError as exc:
            raise StateValidationError(f"治理状态文件无法读取，原文件已保留：{path}") from exc
        if len(raw) > MAX_STATE_BYTES:
            raise StateCapacityError(f"治理状态文件超过 {MAX_STATE_BYTES} 字节上限：{path}")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise StateValidationError(
                f"治理状态文件不是有效 UTF-8 JSON，原文件已保留供人工恢复：{path}"
            ) from exc
        return self._validate_state(value, session_id, path, required_fields)

    @staticmethod
    def _encoded_state(state: dict[str, Any]) -> bytes:
        try:
            content = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        except (TypeError, ValueError) as exc:
            raise StateValidationError("治理状态包含无法序列化的值") from exc
        return content.encode("utf-8")

    def _write_path(
        self,
        path: Path,
        session_id: str,
        state: dict[str, Any],
        *,
        required_fields: tuple[str, ...],
        admission: str,
    ) -> None:
        state["updated_at"] = _now()
        self._validate_state(state, session_id, path, required_fields)
        encoded = self._encoded_state(state)
        if admission not in {"existing", "new_task"}:
            raise StateValidationError("StateStore admission 必须是 existing 或 new_task")
        if admission == "new_task" and len(encoded) > NEW_TASK_SOFT_LIMIT_BYTES:
            raise StateCapacityError(
                f"新治理任务预计使状态超过 {NEW_TASK_SOFT_LIMIT_BYTES} 字节软准入线"
            )
        if len(encoded) > MAX_STATE_BYTES:
            raise StateCapacityError(f"治理状态超过 {MAX_STATE_BYTES} 字节上限")
        try:
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        except OSError as exc:
            raise StateWriteError(f"无法在状态目录创建临时文件：{path.parent}") from exc
        temporary = Path(temporary_name)
        descriptor_open = True
        try:
            try:
                _restrict_descriptor(descriptor, 0o600)
                temporary_stream = os.fdopen(descriptor, "wb")
                descriptor_open = False
                with temporary_stream as temporary_file:
                    temporary_file.write(encoded)
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())
                os.replace(temporary, path)
                _sync_directory(path.parent)
            except OSError as exc:
                raise StateWriteError(f"治理状态原子替换失败：{path}") from exc
            try:
                verified = self._read_path(path, session_id, required_fields)
            except StateStoreError as exc:
                raise StateWriteError(f"治理状态写入后回读失败：{path}") from exc
            if verified != state:
                raise StateWriteError(f"治理状态写入后回读内容不一致：{path}")
        finally:
            if descriptor_open:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def compare_and_set(
        self,
        session_id: str,
        predicate: Callable[[dict[str, Any]], bool],
        callback: Callable[[dict[str, Any]], Any],
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
        admission: str = "existing",
    ) -> Any:
        self.last_warning = None
        with self._lock(session_id) as state_path:
            state = self._read_path(state_path, session_id, required_fields)
            if not predicate(state):
                raise StateConflictError(f"治理状态 compare-and-set 冲突：{session_id}")
            result = callback(state)
            self._write_path(
                state_path,
                session_id,
                state,
                required_fields=required_fields,
                admission=admission,
            )
            return result

    def update(
        self,
        session_id: str,
        callback: Callable[[dict[str, Any]], Any],
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
        admission: str = "existing",
    ) -> Any:
        return self.compare_and_set(
            session_id,
            lambda _state: True,
            callback,
            required_fields=required_fields,
            admission=admission,
        )

    def read(
        self,
        session_id: str,
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
    ) -> dict[str, Any]:
        self.last_warning = None
        with self._lock(session_id) as state_path:
            return self._read_path(state_path, session_id, required_fields)

    def delete(self, session_id: str) -> None:
        self.delete_if(session_id, lambda _state: True)

    def delete_if(
        self,
        session_id: str,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
    ) -> bool:
        self.last_warning = None
        with self._lock(session_id) as state_path:
            state = self._read_path(state_path, session_id, required_fields)
            if not predicate(state):
                return False
            try:
                state_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise StateWriteError(f"治理状态删除失败：{state_path}") from exc
        return True

    def cleanup_expired_tombstones(
        self,
        session_id: str,
        *,
        now: int | None = None,
        result_cleanup: Callable[[str, int], None] | None = None,
    ) -> list[tuple[str, int]]:
        current_time = _now() if now is None else now
        cutoff = current_time - int(RETENTION_SECONDS["tombstone"])

        def cleanup(state: dict[str, Any]) -> list[tuple[str, int]]:
            tombstones = state["tombstones"]
            expired: list[tuple[str, str, int]] = []
            for key, record in tombstones.items():
                if not isinstance(record, dict):
                    raise StateValidationError(f"tombstone {key} 必须是对象")
                missing = [
                    field_name
                    for field_name in ("task_id", "attempt", "close_reason", "closed_at")
                    if field_name not in record
                ]
                if missing:
                    raise StateValidationError(
                        f"tombstone {key} 缺少字段 {', '.join(missing)}"
                    )
                task_id = record.get("task_id")
                attempt = record.get("attempt")
                close_reason = record.get("close_reason")
                closed_at = record.get("closed_at")
                if not isinstance(task_id, str) or not task_id.strip():
                    raise StateValidationError(f"tombstone {key} 的 task_id 无效")
                if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
                    raise StateValidationError(f"tombstone {key} 的 attempt 无效")
                if not isinstance(close_reason, str) or not close_reason.strip():
                    raise StateValidationError(f"tombstone {key} 的 close_reason 无效")
                if isinstance(closed_at, bool) or not isinstance(closed_at, int):
                    raise StateValidationError(f"tombstone {key} 的 closed_at 无效")
                if str(key) != f"{task_id}:{attempt}":
                    raise StateValidationError(
                        f"tombstone {key} 与 task_id={task_id}, attempt={attempt} 不匹配"
                    )
                if closed_at <= cutoff:
                    expired.append((str(key), task_id, attempt))
            if result_cleanup is not None:
                for _key, task_id, attempt in expired:
                    try:
                        result_cleanup(task_id, attempt)
                    except Exception as exc:
                        raise StateWriteError(
                            f"精确结果清理失败：task_id={task_id}, attempt={attempt}"
                        ) from exc
            for key, _task_id, _attempt in expired:
                tombstones.pop(key)
            return [(task_id, attempt) for _key, task_id, attempt in expired]

        return self.update(
            session_id,
            cleanup,
            required_fields=("tombstones",),
        )


class UnavailableStateStore:
    """Failing store used to preserve Hook behavior when state setup is unavailable."""

    def __init__(self, error: Exception):
        self.error = error
        self.last_warning = f"治理状态不可用，已降级放行：{error}"

    def _raise(self) -> None:
        raise OSError(str(self.error)) from self.error

    @staticmethod
    def initial_attempt_state() -> dict[str, Any]:
        return copy.deepcopy(AttemptState().to_record())

    def compare_and_set(
        self,
        session_id: str,
        predicate: Callable[[dict[str, Any]], bool],
        callback: Callable[[dict[str, Any]], Any],
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
        admission: str = "existing",
    ) -> Any:
        self._raise()

    def update(
        self,
        session_id: str,
        callback: Callable[[dict[str, Any]], Any],
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
        admission: str = "existing",
    ) -> Any:
        self._raise()

    def read(
        self,
        session_id: str,
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
    ) -> dict[str, Any]:
        self._raise()

    def delete(self, session_id: str) -> None:
        self._raise()

    def delete_if(
        self,
        session_id: str,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        required_fields: tuple[str, ...] = ("tasks", "agents"),
    ) -> bool:
        self._raise()

    def cleanup_expired_tombstones(
        self,
        session_id: str,
        *,
        now: int | None = None,
        result_cleanup: Callable[[str, int], None] | None = None,
    ) -> list[tuple[str, int]]:
        self._raise()


class PreparedContractStore:
    def __init__(self, root: Path | None = None):
        target = root if root is not None else _data_root() / "prepared"
        self.root = _prepare_private_directory(target)

    def _paths(self, session_id: str, task_ref: str) -> tuple[Path, Path]:
        if len(task_ref) not in TASK_REF_LENGTHS or not re.fullmatch(r"[a-f0-9]+", task_ref):
            raise PreparedContractValidationError("task_ref 不是允许长度的小写十六进制")
        session_stem = _safe_name(session_id)
        return (
            self.root / f"{session_stem}--{task_ref}.json",
            self.root / f"{session_stem}.lock",
        )

    @contextmanager
    def _lock(self, session_id: str):
        _record_path, lock_path = self._paths(session_id, "0" * TASK_REF_LENGTHS[0])
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise PreparedContractValidationError(
                f"PreparedContract 锁文件无法安全打开：{lock_path}"
            ) from exc
        with os.fdopen(descriptor, "a+", encoding="utf-8") as lock_file:
            metadata = os.fstat(lock_file.fileno())
            if not stat.S_ISREG(metadata.st_mode) or not _owned_by_current_user(metadata):
                raise PreparedContractValidationError(
                    f"PreparedContract 锁文件必须是当前用户拥有的普通文件：{lock_path}"
                )
            _restrict_descriptor(lock_file.fileno(), 0o600)
            with _exclusive_file_lock(lock_file):
                yield

    @staticmethod
    def _validate_record(value: Any, session_id: str, task_ref: str, path: Path) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise PreparedContractValidationError(f"PreparedContract 根节点必须是对象：{path}")
        required = (
            "session_id",
            "task_id",
            "attempt",
            "task_ref",
            "task_name",
            "resolved_mode",
            "contract",
            "native_parameters",
            "created_at",
            "consumed",
            "tool_use_id",
            "claimed_at",
            "post_observed_at",
            "spawn_retry_count",
        )
        missing = [field_name for field_name in required if field_name not in value]
        if missing:
            raise PreparedContractValidationError(
                f"PreparedContract 缺少字段 {', '.join(missing)}：{path}"
            )
        if value.get("session_id") != session_id or value.get("task_ref") != task_ref:
            raise PreparedContractValidationError(f"PreparedContract 引用与文件路径不匹配：{path}")
        if not isinstance(value.get("task_id"), str) or not value["task_id"].strip():
            raise PreparedContractValidationError(f"PreparedContract task_id 无效：{path}")
        attempt = value.get("attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise PreparedContractValidationError(f"PreparedContract attempt 无效：{path}")
        parsed = parse_task_name(value.get("task_name"))
        if parsed is None or parsed[0] != value.get("resolved_mode") or parsed[2] != task_ref:
            raise PreparedContractValidationError(f"PreparedContract task_name 无效：{path}")
        contract = value.get("contract")
        errors = validate_task_contract(contract)
        if errors:
            raise PreparedContractValidationError(
                f"PreparedContract TaskContract 无效：{'；'.join(errors)}"
            )
        if not isinstance(value.get("native_parameters"), dict):
            raise PreparedContractValidationError(f"PreparedContract native_parameters 无效：{path}")
        if isinstance(value.get("created_at"), bool) or not isinstance(value.get("created_at"), int):
            raise PreparedContractValidationError(f"PreparedContract created_at 无效：{path}")
        if not isinstance(value.get("consumed"), bool):
            raise PreparedContractValidationError(f"PreparedContract consumed 无效：{path}")
        for field_name in ("tool_use_id", "claimed_at", "post_observed_at"):
            field_value = value.get(field_name)
            if field_value is not None and (
                isinstance(field_value, bool)
                or not isinstance(field_value, (str, int))
                or (isinstance(field_value, str) and not field_value.strip())
            ):
                raise PreparedContractValidationError(
                    f"PreparedContract {field_name} 无效：{path}"
                )
        retry_count = value.get("spawn_retry_count")
        if isinstance(retry_count, bool) or not isinstance(retry_count, int) or not 0 <= retry_count <= 2:
            raise PreparedContractValidationError(f"PreparedContract spawn_retry_count 无效：{path}")
        if value["consumed"] and (value.get("tool_use_id") is None or value.get("claimed_at") is None):
            raise PreparedContractValidationError(f"已消费 PreparedContract 缺少 claim 字段：{path}")
        return value

    def _read_path(self, path: Path, session_id: str, task_ref: str) -> dict[str, Any]:
        try:
            metadata = path.lstat()
        except FileNotFoundError as exc:
            raise PreparedContractValidationError(
                f"PreparedContract 不存在：session={session_id}, task_ref={task_ref}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise PreparedContractValidationError(f"PreparedContract 必须是普通文件：{path}")
        if not _owned_by_current_user(metadata) or not _private_permissions_safe(metadata):
            raise PreparedContractValidationError(f"PreparedContract 所有者或权限不安全：{path}")
        if metadata.st_size > MAX_PREPARED_BYTES:
            raise PreparedContractValidationError(f"PreparedContract 超过大小上限：{path}")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise PreparedContractValidationError(f"PreparedContract 无法读取：{path}") from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PreparedContractValidationError(f"PreparedContract 不是有效 UTF-8 JSON：{path}") from exc
        return self._validate_record(value, session_id, task_ref, path)

    @staticmethod
    def _encoded(record: dict[str, Any]) -> bytes:
        try:
            raw = (json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise PreparedContractValidationError("PreparedContract 包含无法序列化的值") from exc
        if len(raw) > MAX_PREPARED_BYTES:
            raise PreparedContractValidationError("PreparedContract 超过大小上限")
        return raw

    def _write_path(self, path: Path, session_id: str, task_ref: str, record: dict[str, Any]) -> None:
        self._validate_record(record, session_id, task_ref, path)
        encoded = self._encoded(record)
        try:
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        except OSError as exc:
            raise PreparedContractWriteError("无法创建 PreparedContract 临时文件") from exc
        temporary = Path(temporary_name)
        descriptor_open = True
        try:
            try:
                _restrict_descriptor(descriptor, 0o600)
                stream = os.fdopen(descriptor, "wb")
                descriptor_open = False
                with stream as temporary_file:
                    temporary_file.write(encoded)
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())
                os.replace(temporary, path)
                _sync_directory(path.parent)
            except OSError as exc:
                raise PreparedContractWriteError(f"PreparedContract 原子替换失败：{path}") from exc
            try:
                verified = self._read_path(path, session_id, task_ref)
            except PreparedContractError as exc:
                raise PreparedContractWriteError(f"PreparedContract 写入后回读失败：{path}") from exc
            if verified != record:
                raise PreparedContractWriteError(f"PreparedContract 写入后内容不一致：{path}")
        finally:
            if descriptor_open:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def create(self, record: dict[str, Any], *, replace: bool = False) -> None:
        session_id = str(record.get("session_id") or "")
        task_ref = str(record.get("task_ref") or "")
        path, _lock_path = self._paths(session_id, task_ref)
        with self._lock(session_id):
            if path.exists() and not replace:
                raise PreparedContractConflictError(f"PreparedContract 已存在：{task_ref}")
            self._write_path(path, session_id, task_ref, copy.deepcopy(record))

    def read(self, session_id: str, task_ref: str) -> dict[str, Any]:
        path, _lock_path = self._paths(session_id, task_ref)
        with self._lock(session_id):
            return self._read_path(path, session_id, task_ref)

    def compare_and_set(
        self,
        session_id: str,
        task_ref: str,
        predicate: Callable[[dict[str, Any]], bool],
        callback: Callable[[dict[str, Any]], Any],
    ) -> Any:
        path, _lock_path = self._paths(session_id, task_ref)
        with self._lock(session_id):
            record = self._read_path(path, session_id, task_ref)
            if not predicate(record):
                raise PreparedContractConflictError(f"PreparedContract compare-and-set 冲突：{task_ref}")
            result = callback(record)
            self._write_path(path, session_id, task_ref, record)
            return result

    def delete(self, session_id: str, task_ref: str, *, missing_ok: bool = True) -> bool:
        path, _lock_path = self._paths(session_id, task_ref)
        with self._lock(session_id):
            try:
                path.unlink()
            except FileNotFoundError:
                if missing_ok:
                    return False
                raise PreparedContractValidationError(f"PreparedContract 不存在：{task_ref}")
            except OSError as exc:
                raise PreparedContractWriteError(f"PreparedContract 删除失败：{path}") from exc
            return True

    def list_records(self, session_id: str) -> list[dict[str, Any]]:
        session_stem = _safe_name(session_id)
        with self._lock(session_id):
            records = []
            for path in sorted(self.root.glob(f"{session_stem}--*.json")):
                task_ref = path.stem.rsplit("--", 1)[-1]
                records.append(self._read_path(path, session_id, task_ref))
            return records

    def refs(self, session_id: str) -> set[str]:
        return {str(record["task_ref"]) for record in self.list_records(session_id)}

    def find_claimed(self, session_id: str, tool_use_id: str) -> dict[str, Any] | None:
        matches = [
            record
            for record in self.list_records(session_id)
            if record.get("consumed") is True and record.get("tool_use_id") == tool_use_id
        ]
        if len(matches) > 1:
            raise PreparedContractConflictError(
                f"同一 tool_use_id 映射到多个 PreparedContract：{tool_use_id}"
            )
        return matches[0] if matches else None


def _prepared_root_for_store(store: Any) -> Path:
    root = getattr(store, "root", None)
    if isinstance(root, Path):
        return (root.parent if root.name == "sessions" else root) / "prepared"
    return _data_root() / "prepared"


def _results_root_for_store(store: Any) -> Path:
    root = getattr(store, "root", None)
    if isinstance(root, Path):
        return (root.parent if root.name == "sessions" else root) / FORMAL_RESULT_STORAGE["directory"]
    return _data_root() / FORMAL_RESULT_STORAGE["directory"]


def _task_record_for_attempt(
    state: dict[str, Any], task_id: str, attempt: int
) -> dict[str, Any] | None:
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        raise StateValidationError("治理状态缺少 tasks 对象")
    record = tasks.get(task_id)
    if not isinstance(record, dict):
        return None
    if record.get("attempt") == attempt:
        return record
    prior_attempts = record.get("prior_attempts")
    if isinstance(prior_attempts, dict):
        prior = prior_attempts.get(str(attempt))
        if isinstance(prior, dict) and prior.get("attempt") == attempt:
            return prior
    return None


def _iter_task_attempts(
    state: dict[str, Any],
) -> list[tuple[str, int, dict[str, Any]]]:
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        raise StateValidationError("治理状态缺少 tasks 对象")
    attempts: list[tuple[str, int, dict[str, Any]]] = []
    for task_id, current in tasks.items():
        if not isinstance(current, dict):
            continue
        attempt = current.get("attempt")
        if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt >= 1:
            attempts.append((str(task_id), attempt, current))
        prior_attempts = current.get("prior_attempts")
        if not isinstance(prior_attempts, dict):
            continue
        for prior in prior_attempts.values():
            prior_attempt = prior.get("attempt") if isinstance(prior, dict) else None
            if (
                isinstance(prior, dict)
                and isinstance(prior_attempt, int)
                and not isinstance(prior_attempt, bool)
                and prior_attempt >= 1
            ):
                attempts.append((str(task_id), prior_attempt, prior))
    return attempts


def _managed_target_attempt(
    state: dict[str, Any], target: str
) -> tuple[str, int, dict[str, Any]] | None:
    agents = state.get("agents")
    if not isinstance(agents, dict):
        raise StateValidationError("治理状态缺少 agents 对象")
    mapping = agents.get(target)
    if not isinstance(mapping, dict):
        return None
    task_id = mapping.get("task_id")
    attempt = mapping.get("attempt")
    if (
        not isinstance(task_id, str)
        or not task_id
        or isinstance(attempt, bool)
        or not isinstance(attempt, int)
    ):
        return None
    record = _task_record_for_attempt(state, task_id, attempt)
    if not isinstance(record, dict) or record.get("managed") is not True:
        return None
    return task_id, attempt, record


def _validate_task_identity(task_id: Any, attempt: Any) -> tuple[str, int]:
    task_errors = _validate_text(
        task_id,
        "task_id",
        maximum=int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"]),
    )
    minimum = int(SEMANTIC_DEFINITIONS["attempt"]["minimum"])
    if task_errors:
        raise ResultSubmissionError("；".join(task_errors))
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < minimum:
        raise ResultSubmissionError(f"attempt 必须是大于等于 {minimum} 的整数")
    return str(task_id), attempt


def result_file_path(results_root: Path, task_id: str, attempt: int) -> Path:
    normalized_task_id, normalized_attempt = _validate_task_identity(task_id, attempt)
    digest = hashlib.sha256(normalized_task_id.encode("utf-8")).hexdigest()
    return Path(results_root) / f"result-{digest}-attempt-{normalized_attempt}.json"


def _prepare_results_directory(results_root: Path) -> Path:
    try:
        return _prepare_private_directory(Path(results_root))
    except (OSError, RuntimeError) as exc:
        raise ResultStorageError(f"正式结果目录不可用：{results_root}") from exc


def _canonical_result_bytes(value: dict[str, Any]) -> bytes:
    try:
        content = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
    except (TypeError, ValueError) as exc:
        raise ResultSubmissionError("TaskResult 包含无法序列化的值") from exc
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_RESULT_BYTES:
        raise ResultSubmissionError(f"TaskResult 超过 {MAX_RESULT_BYTES} 字节上限")
    return encoded


@contextmanager
def _result_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ResultStorageError(f"正式结果锁文件无法安全打开：{lock_path}") from exc
    with os.fdopen(descriptor, "a+", encoding="utf-8") as lock_file:
        metadata = os.fstat(lock_file.fileno())
        if not stat.S_ISREG(metadata.st_mode) or not _owned_by_current_user(metadata):
            raise ResultStorageError(f"正式结果锁文件不安全：{lock_path}")
        _restrict_descriptor(lock_file.fileno(), 0o600)
        with _exclusive_file_lock(lock_file):
            yield


def _read_result_path(
    path: Path,
    task_id: str,
    attempt: int,
) -> tuple[dict[str, Any], bytes, str]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ResultStorageError(f"正式结果文件不存在：{path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ResultStorageError(f"正式结果文件必须是普通文件且不能是符号链接：{path}")
    if not _owned_by_current_user(metadata):
        raise ResultStorageError(f"正式结果文件不属于当前用户：{path}")
    if not _private_permissions_safe(metadata):
        raise ResultStorageError(f"正式结果文件权限必须限制为当前用户可访问：{path}")
    if metadata.st_size > MAX_RESULT_BYTES:
        raise ResultStorageError(f"正式结果文件超过 {MAX_RESULT_BYTES} 字节上限：{path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as result_file:
            opened = os.fstat(result_file.fileno())
            if not stat.S_ISREG(opened.st_mode) or not _owned_by_current_user(opened):
                raise ResultStorageError(f"正式结果文件打开后安全校验失败：{path}")
            raw = result_file.read(MAX_RESULT_BYTES + 1)
    except ResultStorageError:
        raise
    except OSError as exc:
        raise ResultStorageError(f"正式结果文件无法安全读取：{path}") from exc
    if len(raw) > MAX_RESULT_BYTES:
        raise ResultStorageError(f"正式结果文件超过 {MAX_RESULT_BYTES} 字节上限：{path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResultStorageError(f"正式结果文件不是有效 UTF-8 JSON：{path}") from exc
    errors = validate_task_result(value)
    if errors:
        raise ResultStorageError(f"正式结果文件协议校验失败：{'；'.join(errors)}")
    if value.get("task_id") != task_id or value.get("attempt") != attempt:
        raise ResultStorageError("正式结果文件的 task_id/attempt 与确定性地址不匹配")
    canonical = _canonical_result_bytes(value)
    if raw != canonical:
        raise ResultStorageError("正式结果文件不是规范 canonical JSON")
    return value, raw, hashlib.sha256(raw).hexdigest()


def _cleanup_task_result_file(results_root: Path, task_id: str, attempt: int) -> None:
    path = result_file_path(Path(results_root), task_id, attempt)
    try:
        path.lstat()
    except FileNotFoundError:
        return
    with _result_lock(path):
        try:
            path.lstat()
        except FileNotFoundError:
            return
        _read_result_path(path, task_id, attempt)
        try:
            path.unlink()
            _sync_directory(path.parent)
        except OSError as exc:
            raise ResultStorageError(
                f"正式结果精确删除失败：task_id={task_id}, attempt={attempt}"
            ) from exc


def _write_or_read_authoritative_result(
    results_root: Path,
    value: dict[str, Any],
) -> tuple[str, dict[str, Any], str, str]:
    task_id = str(value["task_id"])
    attempt = int(value["attempt"])
    root = _prepare_results_directory(results_root)
    path = result_file_path(root, task_id, attempt)
    desired = _canonical_result_bytes(value)
    desired_sha256 = hashlib.sha256(desired).hexdigest()
    with _result_lock(path):
        if path.exists() or path.is_symlink():
            existing, _raw, existing_sha256 = _read_result_path(path, task_id, attempt)
            status = "same" if existing_sha256 == desired_sha256 else "different"
            return status, existing, existing_sha256, desired_sha256
        try:
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=root)
        except OSError as exc:
            raise ResultStorageError(f"无法在正式结果目录创建临时文件：{root}") from exc
        temporary = Path(temporary_name)
        descriptor_open = True
        try:
            try:
                _restrict_descriptor(descriptor, 0o600)
                stream = os.fdopen(descriptor, "wb")
                descriptor_open = False
                with stream as result_file:
                    result_file.write(desired)
                    result_file.flush()
                    os.fsync(result_file.fileno())
                os.replace(temporary, path)
                _sync_directory(root)
            except OSError as exc:
                raise ResultStorageError(f"正式结果原子写入失败：{path}") from exc
            written, _raw, written_sha256 = _read_result_path(path, task_id, attempt)
            if written_sha256 != desired_sha256 or written != value:
                raise ResultStorageError(f"正式结果写入后回读内容不一致：{path}")
        finally:
            if descriptor_open:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return "new", value, desired_sha256, desired_sha256


def _task_attempt_records(
    state: dict[str, Any], task_id: str
) -> list[tuple[int, dict[str, Any]]]:
    current = state.get("tasks", {}).get(task_id)
    if not isinstance(current, dict):
        return []
    records: dict[int, dict[str, Any]] = {}
    current_attempt = current.get("attempt")
    if isinstance(current_attempt, int) and not isinstance(current_attempt, bool):
        records[current_attempt] = current
    prior_attempts = current.get("prior_attempts")
    if isinstance(prior_attempts, dict):
        for value in prior_attempts.values():
            attempt = value.get("attempt") if isinstance(value, dict) else None
            if isinstance(attempt, int) and not isinstance(attempt, bool):
                records[attempt] = value
    return sorted(records.items())


def _clear_result_conflict(record: dict[str, Any]) -> None:
    record["result_conflict"] = False
    record.pop("result_conflict_sha256", None)
    record.pop("result_conflict_first_seen_at", None)


def _consume_result_correction(record: dict[str, Any]) -> None:
    pending = record.get("pending_action")
    if isinstance(pending, dict) and pending.get("operation_type") == "result_correction":
        record.pop("pending_action", None)
    lifecycle = record.get("last_lifecycle_operation")
    if isinstance(lifecycle, dict) and lifecycle.get("operation_type") == "result_correction":
        record.pop("last_lifecycle_operation", None)


def _parent_action_for_result(business_result: str) -> str:
    action = BUSINESS_RESULT_PARENT_ACTION.get(business_result)
    if action not in PARENT_ACTIONS:
        raise ResultSubmissionError(f"business_result={business_result} 缺少机器父动作映射")
    return str(action)


def _associate_result_record(
    record: dict[str, Any],
    value: dict[str, Any],
    result_sha256: str,
    result_reference: str,
    stored_at: int,
) -> None:
    business_result = str(value["business_result"])
    record["execution_status"] = "stopped"
    record["business_result"] = business_result
    record["result_protocol_status"] = "valid"
    record["result_storage_status"] = "available"
    record["acceptance_status"] = "pending" if business_result == "complete" else None
    record["parent_action"] = _parent_action_for_result(business_result)
    record["result_reference"] = result_reference
    record["result_sha256"] = result_sha256
    record["result_stored_at"] = stored_at
    _consume_result_correction(record)
    record["updated_at"] = stored_at


def _mark_duplicate_for_late_result(
    state: dict[str, Any], task_id: str, result_attempt: int
) -> None:
    current = state.get("tasks", {}).get(task_id)
    if not isinstance(current, dict) or current.get("attempt") == result_attempt:
        return
    other_open = any(
        attempt != result_attempt and record.get("attempt_closed") is not True
        for attempt, record in _task_attempt_records(state, task_id)
    )
    if other_open:
        current["duplicate_execution"] = True
        current["parent_action"] = "resolve_duplicate"


def _mark_result_storage_unavailable(
    session_id: str,
    task_id: str,
    attempt: int,
    *,
    state_store: StateStore,
    now: int,
    error: Exception,
) -> None:
    def mark(state: dict[str, Any]) -> None:
        record = _task_record_for_attempt(state, task_id, attempt)
        if not isinstance(record, dict) or record.get("managed") is not True:
            raise StateConflictError("无法为不存在的 managed task/attempt 标记结果存储故障")
        if record.get("result_storage_status") == "available":
            return
        if record.get("attempt_closed") is True or record.get("execution_status") == "interrupted":
            raise StateConflictError("已关闭或已中断 attempt 不能改写为结果存储故障")
        record["execution_status"] = "stopped"
        record["result_protocol_status"] = "valid"
        record["result_storage_status"] = "unavailable"
        record["business_result"] = None
        record["acceptance_status"] = None
        record["parent_action"] = "manual_review"
        record["result_storage_error"] = _bounded(str(error))
        _consume_result_correction(record)
        record["updated_at"] = now
        health = state.setdefault("health", {})
        health["status"] = "degraded"
        health["result_storage_error"] = _bounded(str(error))
        health["result_storage_error_at"] = now

    state_store.update(session_id, mark)


def submit_task_result(
    value: Any,
    session_id: str,
    *,
    agent_target: str,
    state_store: StateStore | None = None,
    results_root: Path | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    errors = validate_task_result(value)
    if errors:
        raise ResultSubmissionError(f"TaskResult 协议校验失败：{'；'.join(errors)}")
    assert isinstance(value, dict)
    task_id, attempt = _validate_task_identity(value.get("task_id"), value.get("attempt"))
    if not isinstance(agent_target, str) or not agent_target.strip():
        raise ResultSubmissionError("agent_target 必须是精确 Agent ID 或 canonical task path")
    target = agent_target.strip()
    current_time = _now() if now is None else now
    store = state_store or StateStore()
    root = Path(results_root) if results_root is not None else _results_root_for_store(store)
    result_path = result_file_path(root, task_id, attempt)
    desired_sha256 = hashlib.sha256(_canonical_result_bytes(value)).hexdigest()
    file_observed = False

    def submit(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal file_observed
        mapped = _managed_target_attempt(state, target)
        if mapped is None or mapped[:2] != (task_id, attempt):
            raise ResultSubmissionError("Agent target 未精确映射到 TaskResult 的 task_id + attempt")
        record = mapped[2]
        terminal_reason = None
        if record.get("attempt_closed") is True:
            terminal_reason = "已关闭 attempt 拒绝新的正式结果"
        elif record.get("execution_status") == "interrupted":
            terminal_reason = "成功中断后的 attempt 拒绝新的正式结果"
        if terminal_reason is not None:
            if (
                record.get("result_storage_status") == "available"
                and record.get("result_reference") == result_path.name
                and record.get("result_sha256") == desired_sha256
            ):
                try:
                    _existing, _raw, existing_sha256 = _read_result_path(
                        result_path, task_id, attempt
                    )
                except ResultStorageError as exc:
                    raise ResultSubmissionError(
                        f"{terminal_reason}，且既有权威结果无法重新校验：{exc}"
                    ) from exc
                if existing_sha256 == desired_sha256:
                    return {
                        "status": "idempotent",
                        "task_id": task_id,
                        "attempt": attempt,
                        "result_reference": result_path.name,
                    }
            raise ResultSubmissionError(terminal_reason)
        file_status, authoritative, authoritative_sha256, conflict_sha256 = (
            _write_or_read_authoritative_result(root, value)
        )
        file_observed = True
        reference = result_path.name
        if file_status == "different":
            if record.get("result_storage_status") != "available":
                _associate_result_record(
                    record,
                    authoritative,
                    authoritative_sha256,
                    reference,
                    current_time,
                )
            elif (
                record.get("result_reference") != reference
                or record.get("result_sha256") != authoritative_sha256
            ):
                raise ResultSubmissionError("StateStore 的权威结果引用与确定性结果文件不一致")
            if record.get("result_conflict") is not True:
                record["result_conflict"] = True
                record["result_conflict_sha256"] = conflict_sha256
                record["result_conflict_first_seen_at"] = current_time
            record["parent_action"] = "manual_review"
            record["updated_at"] = current_time
            _mark_duplicate_for_late_result(state, task_id, attempt)
            return {
                "status": "conflict",
                "task_id": task_id,
                "attempt": attempt,
                "result_reference": reference,
                "conflict_sha256": conflict_sha256,
            }
        if record.get("result_storage_status") == "available":
            if (
                record.get("result_reference") != reference
                or record.get("result_sha256") != authoritative_sha256
            ):
                raise ResultSubmissionError("StateStore 已关联另一个权威结果摘要")
            _mark_duplicate_for_late_result(state, task_id, attempt)
            return {
                "status": "idempotent",
                "task_id": task_id,
                "attempt": attempt,
                "result_reference": reference,
            }
        _associate_result_record(
            record,
            authoritative,
            authoritative_sha256,
            reference,
            current_time,
        )
        record.pop("result_storage_error", None)
        _mark_duplicate_for_late_result(state, task_id, attempt)
        return {
            "status": "stored" if file_status == "new" else "reassociated",
            "task_id": task_id,
            "attempt": attempt,
            "result_reference": reference,
        }

    try:
        return store.update(session_id, submit)
    except ResultStorageError as exc:
        try:
            _mark_result_storage_unavailable(
                session_id,
                task_id,
                attempt,
                state_store=store,
                now=current_time,
                error=exc,
            )
        except Exception as mark_exc:
            raise ResultStorageError(
                f"正式结果未可靠保存，且存储故障状态无法写入：{mark_exc}"
            ) from exc
        return {
            "status": "storage_unavailable",
            "task_id": task_id,
            "attempt": attempt,
            "result_reference": result_path.name if result_path.exists() else None,
            "error": str(exc),
        }
    except ResultSubmissionError:
        raise
    except (StateStoreError, OSError) as exc:
        if not file_observed and not isinstance(exc, ResultStorageError):
            raise ResultSubmissionError(f"正式结果提交前状态操作失败：{exc}") from exc
        try:
            _mark_result_storage_unavailable(
                session_id,
                task_id,
                attempt,
                state_store=store,
                now=current_time,
                error=exc,
            )
        except Exception as mark_exc:
            raise ResultStorageError(
                f"正式结果未可靠关联，且存储故障状态无法写入：{mark_exc}"
            ) from exc
        return {
            "status": "storage_unavailable",
            "task_id": task_id,
            "attempt": attempt,
            "result_reference": result_path.name if result_path.exists() else None,
            "error": str(exc),
        }


def read_task_result(
    session_id: str,
    task_id: str,
    attempt: int,
    *,
    state_store: StateStore | None = None,
    results_root: Path | None = None,
) -> dict[str, Any]:
    normalized_task_id, normalized_attempt = _validate_task_identity(task_id, attempt)
    store = state_store or StateStore()
    root = Path(results_root) if results_root is not None else _results_root_for_store(store)
    state = store.read(session_id)
    record = _task_record_for_attempt(state, normalized_task_id, normalized_attempt)
    if not isinstance(record, dict) or record.get("managed") is not True:
        raise ResultSubmissionError("找不到精确 managed task/attempt")
    if record.get("result_protocol_status") != "valid" or record.get("result_storage_status") != "available":
        raise ResultStorageError("正式结果尚未处于 valid + available 状态")
    path = result_file_path(root, normalized_task_id, normalized_attempt)
    if record.get("result_reference") != path.name:
        raise ResultStorageError("StateStore 的 result_reference 与确定性地址不匹配")
    value, _raw, digest = _read_result_path(path, normalized_task_id, normalized_attempt)
    if record.get("result_sha256") != digest:
        raise ResultStorageError("StateStore 的 result_sha256 与正式结果文件不匹配")
    return value


def reassociate_task_result(
    session_id: str,
    task_id: str,
    attempt: int,
    *,
    state_store: StateStore | None = None,
    results_root: Path | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    normalized_task_id, normalized_attempt = _validate_task_identity(task_id, attempt)
    store = state_store or StateStore()
    root = Path(results_root) if results_root is not None else _results_root_for_store(store)
    current_time = _now() if now is None else now
    path = result_file_path(root, normalized_task_id, normalized_attempt)

    def reassociate(state: dict[str, Any]) -> dict[str, Any]:
        record = _task_record_for_attempt(state, normalized_task_id, normalized_attempt)
        if not isinstance(record, dict) or record.get("managed") is not True:
            raise ResultSubmissionError("找不到精确 managed task/attempt")
        if record.get("attempt_closed") is True or record.get("execution_status") == "interrupted":
            raise ResultSubmissionError("已关闭或已中断 attempt 不能重新关联结果")
        value, _raw, digest = _read_result_path(path, normalized_task_id, normalized_attempt)
        if record.get("result_storage_status") == "available":
            if record.get("result_reference") != path.name or record.get("result_sha256") != digest:
                raise ResultSubmissionError("已有权威结果关联与孤立文件不一致")
            return {
                "status": "idempotent",
                "task_id": normalized_task_id,
                "attempt": normalized_attempt,
            }
        _associate_result_record(record, value, digest, path.name, current_time)
        record.pop("result_storage_error", None)
        _mark_duplicate_for_late_result(state, normalized_task_id, normalized_attempt)
        return {
            "status": "reassociated",
            "task_id": normalized_task_id,
            "attempt": normalized_attempt,
            "result_reference": path.name,
        }

    return store.update(session_id, reassociate)


def _attempt_interrupt_target(record: dict[str, Any]) -> str | None:
    if record.get("identity_status") != "confirmed" or record.get("execution_status") != "running":
        return None
    for field_name in ("agent_id", "canonical_task_path"):
        value = record.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _running_interrupt_targets(
    records: list[tuple[int, dict[str, Any]]],
) -> list[str]:
    targets: list[str] = []
    for _attempt, record in records:
        if record.get("attempt_closed") is True:
            continue
        target = _attempt_interrupt_target(record)
        if target and target not in targets:
            targets.append(target)
    return targets


def _tombstone_record(record: dict[str, Any], reason: str, closed_at: int) -> dict[str, Any]:
    value = {
        "task_id": str(record["task_id"]),
        "attempt": int(record["attempt"]),
        "task_ref": record.get("task_ref"),
        "agent_id": record.get("agent_id"),
        "canonical_task_path": record.get("canonical_task_path"),
        "last_execution_status": record.get("execution_status"),
        "close_reason": reason,
        "closed_at": closed_at,
    }
    return {key: item for key, item in value.items() if item is not None}


def _close_attempt_record(
    state: dict[str, Any],
    record: dict[str, Any],
    reason: str,
    closed_at: int,
) -> None:
    record["attempt_closed"] = True
    record["attempt_close_reason"] = reason
    record["attempt_closed_at"] = closed_at
    record["parent_action"] = None
    record.pop("pending_action", None)
    record.pop("last_lifecycle_operation", None)
    record["updated_at"] = closed_at
    key = f"{record['task_id']}:{record['attempt']}"
    state.setdefault("tombstones", {})[key] = _tombstone_record(record, reason, closed_at)


def _remove_attempt_agent_mappings(
    state: dict[str, Any], task_id: str, attempt: int
) -> None:
    agents = state.get("agents")
    if not isinstance(agents, dict):
        raise StateValidationError("治理状态缺少 Agent 映射清理所需的 agents 对象")
    for target, mapping in list(agents.items()):
        if (
            isinstance(mapping, dict)
            and mapping.get("task_id") == task_id
            and mapping.get("attempt") == attempt
        ):
            agents.pop(target, None)


def _finalize_selected_duplicate_if_resolved(
    state: dict[str, Any], task_id: str, observed_at: int
) -> None:
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        raise StateValidationError("治理状态缺少 duplicate 收口所需的 tasks 对象")
    selected = tasks.get(task_id)
    if not isinstance(selected, dict) or selected.get("managed") is not True:
        return
    selected_attempt = selected.get("attempt")
    unresolved_unselected = [
        record
        for attempt, record in _task_attempt_records(state, task_id)
        if attempt != selected_attempt
        and record.get("attempt_closed") is not True
    ]
    if unresolved_unselected:
        selected["duplicate_execution"] = True
        selected["parent_action"] = "resolve_duplicate"
        selected["updated_at"] = observed_at
        return
    selected.pop("duplicate_execution", None)
    _restore_selected_parent_action(selected)
    selected["updated_at"] = observed_at


def _close_unselected_duplicate_attempt(
    state: dict[str, Any],
    record: dict[str, Any],
    *,
    reason: str,
    observed_at: int,
    execution_status: str,
) -> bool:
    if record.get("duplicate_not_selected") is not True:
        return False
    if record.get("attempt_closed") is True:
        _finalize_selected_duplicate_if_resolved(
            state, str(record["task_id"]), observed_at
        )
        return True
    task_id = str(record["task_id"])
    attempt = int(record["attempt"])
    record["execution_status"] = execution_status
    record["platform_observation"] = "normal"
    _close_attempt_record(state, record, reason, observed_at)
    _remove_attempt_agent_mappings(state, task_id, attempt)
    _finalize_selected_duplicate_if_resolved(state, task_id, observed_at)
    return True


def _validate_parent_disposition(value: Any) -> tuple[str, int, str, str]:
    if not isinstance(value, dict):
        raise ParentDispositionError("parent disposition 必须是对象")
    task_id_value = value.get("task_id")
    attempt_value = value.get("attempt")
    try:
        task_id, attempt = _validate_task_identity(task_id_value, attempt_value)
    except ResultSubmissionError as exc:
        raise ParentDispositionError(str(exc)) from exc
    action = value.get("action")
    if action not in PARENT_DISPOSITIONS:
        raise ParentDispositionError("action 必须是 accept_result、reject_result、close_task 或 select_attempt")
    reason = value.get("reason")
    errors = _validate_text(reason, "reason", maximum=PARENT_DISPOSITION_REASON_MAX_LENGTH)
    if errors:
        raise ParentDispositionError("；".join(errors))
    return task_id, attempt, str(action), str(reason).strip()


def _restore_selected_parent_action(record: dict[str, Any]) -> None:
    if record.get("attempt_closed") is True:
        record["parent_action"] = None
    elif record.get("result_conflict") is True:
        record["parent_action"] = "manual_review"
    elif record.get("result_storage_status") == "available" and record.get("business_result") in BUSINESS_RESULTS:
        business_result = str(record["business_result"])
        if business_result == "complete" and record.get("acceptance_status") == "rejected":
            record["parent_action"] = "decide_disposition"
        elif business_result == "complete" and record.get("acceptance_status") == "accepted":
            record["parent_action"] = None
        else:
            record["parent_action"] = _parent_action_for_result(business_result)
    elif record.get("result_protocol_status") == "needs_correction":
        record["parent_action"] = "correct_result"
    elif record.get("result_protocol_status") == "exhausted" or record.get("result_storage_status") == "unavailable":
        record["parent_action"] = "manual_review"
    elif record.get("execution_status") == "running":
        record["parent_action"] = "wait"
    elif record.get("execution_status") == "interrupted":
        record["parent_action"] = "decide_disposition"
    else:
        record["parent_action"] = "reconcile"


def _replace_current_attempt(
    state: dict[str, Any], task_id: str, selected_attempt: int
) -> dict[str, Any]:
    records = _task_attempt_records(state, task_id)
    selected = next((record for attempt, record in records if attempt == selected_attempt), None)
    if selected is None:
        raise ParentDispositionConflict("select_attempt 指向的 attempt 不属于该 task")
    snapshots: dict[int, dict[str, Any]] = {}
    for attempt, record in records:
        snapshot = copy.deepcopy(record)
        snapshot.pop("prior_attempts", None)
        snapshots[attempt] = snapshot
    new_current = snapshots.pop(selected_attempt)
    new_current["prior_attempts"] = {str(attempt): record for attempt, record in snapshots.items()}
    state["tasks"][task_id] = new_current
    return new_current


def apply_parent_disposition(
    value: Any,
    session_id: str,
    *,
    state_store: StateStore | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    task_id, attempt, action, reason = _validate_parent_disposition(value)
    store = state_store or StateStore()
    current_time = _now() if now is None else now

    def apply(state: dict[str, Any]) -> dict[str, Any]:
        current = state.get("tasks", {}).get(task_id)
        if not isinstance(current, dict) or current.get("managed") is not True:
            raise ParentDispositionConflict("找不到目标 managed task")
        current_attempt = current.get("attempt")
        if action != "select_attempt" and current_attempt != attempt:
            raise ParentDispositionConflict(
                "父处置 attempt 与当前 attempt 不一致",
                current_attempt=current_attempt if isinstance(current_attempt, int) else None,
            )
        records = _task_attempt_records(state, task_id)
        if action == "select_attempt":
            if current.get("duplicate_execution") is not True:
                raise ParentDispositionConflict("select_attempt 只适用于尚未解决的重复执行")
            if not any(candidate_attempt == attempt for candidate_attempt, _record in records):
                raise ParentDispositionConflict("select_attempt 指向的 attempt 不属于该 task")
            selected = _replace_current_attempt(state, task_id, attempt)
            selected["parent_disposition"] = "select_attempt"
            selected["parent_disposition_reason"] = reason
            selected["parent_disposition_at"] = current_time
            interrupt_targets: list[str] = []
            for candidate_attempt, candidate in _task_attempt_records(state, task_id):
                if candidate_attempt == attempt or candidate.get("attempt_closed") is True:
                    continue
                candidate["duplicate_not_selected"] = True
                target = _attempt_interrupt_target(candidate)
                if target:
                    if target not in interrupt_targets:
                        interrupt_targets.append(target)
                    continue
                _close_attempt_record(
                    state,
                    candidate,
                    f"select_attempt:{reason}",
                    current_time,
                )
            selected["duplicate_execution"] = bool(interrupt_targets)
            if interrupt_targets:
                selected["parent_action"] = "resolve_duplicate"
            else:
                _restore_selected_parent_action(selected)
            selected["updated_at"] = current_time
            return {
                "status": "selected",
                "task_id": task_id,
                "attempt": attempt,
                "interrupt_targets": interrupt_targets,
            }

        if action in {"accept_result", "reject_result"}:
            if current.get("duplicate_execution") is True:
                raise ParentDispositionConflict("重复执行未解决，不能验收 complete 结果")
            if (
                current.get("business_result") != "complete"
                or current.get("result_protocol_status") != "valid"
                or current.get("result_storage_status") != "available"
                or current.get("acceptance_status") != "pending"
            ):
                prior_action = current.get("parent_disposition")
                prior_reason = current.get("parent_disposition_reason")
                if action == "accept_result" and current.get("acceptance_status") == "accepted" and prior_action == action and prior_reason == reason:
                    return {"status": "accepted", "task_id": task_id, "attempt": attempt, "interrupt_targets": []}
                if action == "reject_result" and current.get("acceptance_status") == "rejected" and prior_action == action and prior_reason == reason:
                    return {"status": "rejected", "task_id": task_id, "attempt": attempt}
                raise ParentDispositionConflict(
                    f"{action} 只允许 current complete + valid + available + pending"
                )
        if action == "reject_result":
            current["acceptance_status"] = "rejected"
            current["parent_action"] = "decide_disposition"
            current["parent_disposition"] = action
            current["parent_disposition_reason"] = reason
            current["parent_disposition_at"] = current_time
            _clear_result_conflict(current)
            current["updated_at"] = current_time
            return {"status": "rejected", "task_id": task_id, "attempt": attempt}

        running_targets = _running_interrupt_targets(records)
        if running_targets:
            raise ParentDispositionConflict(
                f"{action} 前必须先显式中断仍在运行的 attempt",
                interrupt_targets=running_targets,
                current_attempt=int(current_attempt) if isinstance(current_attempt, int) else None,
            )
        if action == "accept_result":
            current["acceptance_status"] = "accepted"
        for candidate_attempt, candidate in records:
            close_reason = (
                f"accept_result:{reason}"
                if action == "accept_result" and candidate_attempt == attempt
                else f"{action}:{reason}"
            )
            _clear_result_conflict(candidate)
            _close_attempt_record(state, candidate, close_reason, current_time)
        current["parent_disposition"] = action
        current["parent_disposition_reason"] = reason
        current["parent_disposition_at"] = current_time
        current["parent_action"] = None
        current["updated_at"] = current_time
        return {
            "status": "accepted" if action == "accept_result" else "closed",
            "task_id": task_id,
            "attempt": attempt,
            "interrupt_targets": [],
        }

    return store.update(session_id, apply, required_fields=("tasks", "agents", "tombstones"))


def _task_ref_occupied(state: dict[str, Any], task_ref: str) -> bool:
    tasks = state.get("tasks")
    if isinstance(tasks, dict):
        for record in tasks.values():
            if isinstance(record, dict) and record.get("task_ref") == task_ref:
                return True
    tombstones = state.get("tombstones")
    if isinstance(tombstones, dict):
        for record in tombstones.values():
            if isinstance(record, dict) and record.get("task_ref") == task_ref:
                return True
    return False


def _new_task_id() -> str:
    return "sg-" + secrets.token_hex(16)


def _prepared_record(
    session_id: str,
    task_id: str,
    attempt: int,
    task_ref: str,
    task_name: str,
    contract: TaskContract,
    spawn_args: dict[str, Any],
    *,
    created_at: int,
    spawn_retry_count: int,
) -> dict[str, Any]:
    native_parameters = {
        "task_name": task_name,
        "fork_turns": spawn_args["fork_turns"],
        "model": spawn_args.get("model"),
        "reasoning_effort": spawn_args.get("reasoning_effort"),
        "message_sha256": hashlib.sha256(spawn_args["message"].encode("utf-8")).hexdigest(),
    }
    return {
        "session_id": session_id,
        "task_id": task_id,
        "attempt": attempt,
        "task_ref": task_ref,
        "task_name": task_name,
        "resolved_mode": contract.resolved_mode,
        "contract": contract.to_record(),
        "native_parameters": native_parameters,
        "created_at": created_at,
        "consumed": False,
        "tool_use_id": None,
        "claimed_at": None,
        "post_observed_at": None,
        "spawn_retry_count": spawn_retry_count,
    }


def _contract_summary(contract: TaskContract) -> dict[str, Any]:
    return {
        "objective": contract.objective,
        "background": _bounded(contract.background),
        "work_scope": list(contract.work_scope),
        "forbidden_scope": list(contract.forbidden_scope),
        "completion_conditions": list(contract.completion_conditions),
        "evidence_requirements": list(contract.evidence_requirements),
        "relevant_files": list(contract.relevant_files),
        "current_state": contract.current_state,
        "context_strategy": contract.context_strategy,
        "context_turns": contract.context_turns,
        "context_reason": contract.context_reason,
        "model": contract.model,
        "reasoning_effort": contract.reasoning_effort,
    }


def _initial_task_record(
    task_id: str,
    attempt: int,
    task_ref: str,
    task_name: str,
    contract: TaskContract,
    created_at: int,
) -> dict[str, Any]:
    return {
        "managed": True,
        "task_id": task_id,
        "attempt": attempt,
        "task_ref": task_ref,
        "task_name": task_name,
        "semantic_name": contract.semantic_name,
        "requested_mode": contract.requested_mode,
        "resolved_mode": contract.resolved_mode,
        "resolution_reason": contract.resolution_reason,
        "contract_summary": _contract_summary(contract),
        **AttemptState().to_record(),
        "spawn_tool_use_id": None,
        "spawn_claimed_at": None,
        "spawn_post_observed_at": None,
        "agent_id": None,
        "canonical_task_path": None,
        "created_at": created_at,
        "updated_at": created_at,
    }


def _cleanup_initial_attempt(
    session_id: str,
    task_id: str,
    attempt: int,
    task_ref: str,
    state_store: StateStore,
) -> bool:
    def predicate(state: dict[str, Any]) -> bool:
        record = _task_record_for_attempt(state, task_id, attempt)
        if record is None:
            return True
        initial = AttemptState().to_record()
        return (
            record.get("task_ref") == task_ref
            and record.get("spawn_tool_use_id") is None
            and all(record.get(field_name) == expected for field_name, expected in initial.items())
        )

    def remove(state: dict[str, Any]) -> bool:
        record = _task_record_for_attempt(state, task_id, attempt)
        if record is None:
            return False
        state["tasks"].pop(task_id, None)
        return True

    return state_store.compare_and_set(session_id, predicate, remove)


def _occupied_task_refs(
    session_id: str,
    state_store: StateStore,
    prepared_store: PreparedContractStore,
) -> set[str]:
    state = state_store.read(session_id, required_fields=("tasks", "tombstones"))
    occupied = prepared_store.refs(session_id)
    tasks = state.get("tasks", {})
    tombstones = state.get("tombstones", {})
    for collection in (tasks, tombstones):
        if isinstance(collection, dict):
            for record in collection.values():
                if isinstance(record, dict) and isinstance(record.get("task_ref"), str):
                    occupied.add(record["task_ref"])
    return occupied


def prepare_dispatch(
    contract_value: Any,
    session_id: str,
    *,
    state_store: StateStore | None = None,
    prepared_store: PreparedContractStore | None = None,
    task_id_factory: Callable[[], str] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    if not isinstance(session_id, str) or not session_id.strip():
        raise DispatchPreparationError("session_id 必须是非空字符串")
    active_state_store = state_store or StateStore()
    active_prepared_store = prepared_store or PreparedContractStore(
        _prepared_root_for_store(active_state_store)
    )
    contract = _contract_from_input(contract_value)
    factory = task_id_factory or _new_task_id
    created_at = _now() if now is None else now
    occupied = _occupied_task_refs(session_id, active_state_store, active_prepared_store)
    selected: tuple[str, str] | None = None
    for _generation in range(2):
        task_id = factory()
        if not isinstance(task_id, str) or not task_id.strip():
            raise DispatchPreparationError("task_id_factory 必须返回非空字符串")
        task_ref = select_task_ref(task_id, 1, occupied)
        if task_ref is not None:
            selected = task_id, task_ref
            break
    if selected is None:
        raise DispatchPreparationError("两个新 task_id 均无法在32位内取得唯一 task_ref")
    task_id, task_ref = selected
    task_name = build_task_name(contract.resolved_mode, contract.semantic_name, task_ref)
    spawn_args = _spawn_args(contract, task_name)
    prepared = _prepared_record(
        session_id,
        task_id,
        1,
        task_ref,
        task_name,
        contract,
        spawn_args,
        created_at=created_at,
        spawn_retry_count=0,
    )
    initial = _initial_task_record(task_id, 1, task_ref, task_name, contract, created_at)
    try:
        active_prepared_store.create(prepared)
        try:
            active_state_store.compare_and_set(
                session_id,
                lambda state: task_id not in state["tasks"] and not _task_ref_occupied(state, task_ref),
                lambda state: state["tasks"].update({task_id: copy.deepcopy(initial)}),
                required_fields=("tasks", "tombstones"),
                admission="new_task",
            )
        except Exception:
            active_prepared_store.delete(session_id, task_ref)
            raise
        verified_prepared = active_prepared_store.read(session_id, task_ref)
        verified_state = active_state_store.read(session_id, required_fields=("tasks", "tombstones"))
        verified_task = _task_record_for_attempt(verified_state, task_id, 1)
        if (
            verified_prepared.get("task_name") != task_name
            or verified_prepared.get("resolved_mode") != contract.resolved_mode
            or verified_task is None
            or verified_task.get("task_ref") != task_ref
            or verified_task.get("resolved_mode") != contract.resolved_mode
        ):
            raise DispatchPreparationError("PreparedContract 与 StateStore 双门禁回读不一致")
    except Exception as exc:
        try:
            _cleanup_initial_attempt(session_id, task_id, 1, task_ref, active_state_store)
        except Exception:
            pass
        try:
            active_prepared_store.delete(session_id, task_ref)
        except Exception:
            pass
        if isinstance(exc, DispatchPreparationError):
            raise
        raise DispatchPreparationError(f"受治理派发准备失败，未允许原生 spawn：{exc}") from exc
    return {
        "task_id": task_id,
        "attempt": 1,
        "task_ref": task_ref,
        "task_name": task_name,
        "contract": contract.to_record(),
        "user_message": render_dispatch_user_message(contract),
        "dispatch_prompt": spawn_args["message"],
        "spawn_args": spawn_args,
    }


def prepare_spawn_retry(
    contract_value: Any,
    session_id: str,
    task_id: str,
    *,
    authorized: bool = False,
    state_store: StateStore | None = None,
    prepared_store: PreparedContractStore | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    active_state_store = state_store or StateStore()
    active_prepared_store = prepared_store or PreparedContractStore(
        _prepared_root_for_store(active_state_store)
    )
    state = active_state_store.read(session_id)
    record = state.get("tasks", {}).get(task_id)
    if not isinstance(record, dict) or record.get("managed") is not True:
        raise DispatchPreparationError(f"找不到受治理任务：{task_id}")
    if record.get("spawn_observation") != "failed" or record.get("identity_status") != "unconfirmed":
        raise DispatchPreparationError("只有明确 failed 且身份未确认的 spawn 才能同 attempt 重派")
    current_count = record.get("spawn_retry_count")
    if current_count == 0:
        desired_count = 1
    elif current_count == 1 and authorized:
        desired_count = 2
    elif current_count == 1:
        raise DispatchPreparationError("最后一次同 attempt 重派需要用户明确授权")
    else:
        raise DispatchPreparationError("同 attempt spawn 重派次数已经耗尽")
    contract = _contract_from_input(contract_value)
    if (
        contract.resolved_mode != record.get("resolved_mode")
        or contract.semantic_name != record.get("semantic_name")
        or contract.requested_mode != record.get("requested_mode")
        or contract.resolution_reason != record.get("resolution_reason")
        or _contract_summary(contract) != record.get("contract_summary")
    ):
        raise DispatchPreparationError("重派 TaskContract 与原 attempt 的持久化契约摘要不一致")
    task_ref = str(record.get("task_ref") or "")
    task_name = str(record.get("task_name") or "")
    if parse_task_name(task_name) is None:
        raise DispatchPreparationError("原 attempt 缺少合法 task_name/task_ref")
    spawn_args = _spawn_args(contract, task_name)
    prepared = _prepared_record(
        session_id,
        task_id,
        int(record["attempt"]),
        task_ref,
        task_name,
        contract,
        spawn_args,
        created_at=_now() if now is None else now,
        spawn_retry_count=desired_count,
    )
    try:
        active_prepared_store.create(prepared, replace=True)
        verified_prepared = active_prepared_store.read(session_id, task_ref)
        verified_state = active_state_store.read(session_id)
        verified_task = _task_record_for_attempt(
            verified_state,
            task_id,
            int(record["attempt"]),
        )
        if (
            verified_prepared != prepared
            or verified_task is None
            or verified_task.get("task_ref") != task_ref
            or verified_task.get("task_name") != task_name
            or verified_task.get("resolved_mode") != contract.resolved_mode
        ):
            raise DispatchPreparationError(
                "spawn retry PreparedContract 与 StateStore 双门禁回读不一致"
            )
    except Exception as exc:
        try:
            active_prepared_store.delete(session_id, task_ref)
        except Exception:
            pass
        if isinstance(exc, DispatchPreparationError):
            raise
        raise DispatchPreparationError(f"spawn retry PreparedContract 写入失败：{exc}") from exc
    return {
        "task_id": task_id,
        "attempt": record["attempt"],
        "task_ref": task_ref,
        "task_name": task_name,
        "contract": contract.to_record(),
        "user_message": render_dispatch_user_message(contract),
        "dispatch_prompt": spawn_args["message"],
        "spawn_args": spawn_args,
    }


def reconcile_prepared_dispatches(
    session_id: str,
    *,
    state_store: StateStore,
    prepared_store: PreparedContractStore,
    now: int | None = None,
) -> dict[str, int]:
    current_time = _now() if now is None else now
    expired = 0
    reconciled = 0
    for prepared in prepared_store.list_records(session_id):
        task_id = str(prepared["task_id"])
        attempt = int(prepared["attempt"])
        task_ref = str(prepared["task_ref"])
        if prepared["consumed"] is False:
            if prepared["created_at"] <= current_time - int(RETENTION_SECONDS["prepared_unclaimed"]):
                try:
                    _cleanup_initial_attempt(session_id, task_id, attempt, task_ref, state_store)
                except StateConflictError:
                    continue
                prepared_store.delete(session_id, task_ref)
                expired += 1
            continue
        claimed_at = prepared.get("claimed_at")
        if (
            isinstance(claimed_at, int)
            and prepared.get("post_observed_at") is None
            and claimed_at <= current_time - int(RETENTION_SECONDS["claimed_reconcile"])
        ):
            tool_use_id = prepared.get("tool_use_id")

            def predicate(state: dict[str, Any]) -> bool:
                record = _task_record_for_attempt(state, task_id, attempt)
                return bool(
                    record
                    and record.get("task_ref") == task_ref
                    and record.get("spawn_tool_use_id") == tool_use_id
                    and record.get("spawn_observation") is None
                )

            def mark_unknown(state: dict[str, Any]) -> None:
                record = _task_record_for_attempt(state, task_id, attempt)
                assert record is not None
                record["spawn_observation"] = "unknown"
                record["identity_status"] = "unconfirmed"
                record["execution_status"] = "not_started"
                record["parent_action"] = "reconcile"
                record["spawn_post_observed_at"] = current_time
                record["updated_at"] = current_time

            try:
                state_store.compare_and_set(session_id, predicate, mark_unknown)
            except StateConflictError:
                continue
            prepared_store.compare_and_set(
                session_id,
                task_ref,
                lambda value: value.get("tool_use_id") == tool_use_id,
                lambda value: value.update({"post_observed_at": current_time}),
            )
            reconciled += 1
    return {"expired": expired, "reconciled": reconciled}


COMMUNICATION_FIELD_LABELS = (
    ("purpose", "通信目的"),
    ("reason", "通信原因"),
    ("content", "具体内容"),
    ("expected_result", "期望结果"),
)


def _event_now(payload: dict[str, Any]) -> int:
    supplied = payload.get("now")
    if isinstance(supplied, int) and not isinstance(supplied, bool):
        return supplied
    return _now()


def _communication_fields(value: Any, *, interrupt: bool = False) -> tuple[str, dict[str, str]]:
    if not isinstance(value, dict):
        raise CommunicationPreparationError("通信输入必须是对象")
    target_value = value.get("target")
    if not isinstance(target_value, str) or not target_value.strip():
        raise CommunicationPreparationError("字段 target 必须是非空字符串")
    target = target_value.strip()
    fields: dict[str, str] = {}
    for field_name, label in COMMUNICATION_FIELD_LABELS:
        field_value = value.get(field_name)
        if not isinstance(field_value, str) or not field_value.strip():
            raise CommunicationPreparationError(f"缺少字段 {field_name}（{label}）")
        normalized = " ".join(field_value.split())
        if len(normalized) > MAX_CONTRACT_TEXT:
            raise CommunicationPreparationError(
                f"字段 {field_name}（{label}）长度不能超过 {MAX_CONTRACT_TEXT} 个字符"
            )
        fields[field_name] = normalized
    if not interrupt and value.get("operation_type") not in OPERATION_TYPES:
        raise CommunicationPreparationError(
            "operation_type 必须是 normal_message、platform_recovery、result_correction 或 business_resume"
        )
    return target, fields


def render_communication_user_message(target: str, fields: dict[str, str]) -> str:
    return "\n".join(
        (
            "【子 Agent 通信】",
            f"对象：{target}",
            f"目的：{fields['purpose']}",
            f"原因：{fields['reason']}",
            f"期望结果：{fields['expected_result']}",
        )
    )


def render_communication_message(
    fields: dict[str, str],
    operation_type: str,
    *,
    resume_contract: TaskContract | None = None,
) -> str:
    lines = [
        f"【通信目的】{fields['purpose']}",
        f"【通信原因】{fields['reason']}",
        f"【具体内容】{fields['content']}",
    ]
    if operation_type == "result_correction":
        lines.append("【执行边界】只补交机械合法的结构化结果，不重做业务任务，不修改既有业务成果。")
    if operation_type == "business_resume":
        if resume_contract is None:
            raise CommunicationPreparationError("business_resume 缺少重新验证的 TaskContract")
        lines.extend(
            (
                "【继续执行目标】",
                resume_contract.objective,
                "【工作范围】",
                _render_list(resume_contract.work_scope),
                "【禁止范围】",
                _render_list(resume_contract.forbidden_scope),
                "【完成条件】",
                _render_list(resume_contract.completion_conditions),
                "【验收证据】",
                _render_list(resume_contract.evidence_requirements),
            )
        )
    lines.append(f"【期望结果】{fields['expected_result']}")
    return "\n".join(lines)


def _pending_action_matches_target(
    state: dict[str, Any], target: str
) -> list[tuple[str, int, dict[str, Any], dict[str, Any]]]:
    matches = []
    for task_id, attempt, record in _iter_task_attempts(state):
        pending = record.get("pending_action")
        if isinstance(pending, dict) and pending.get("target") == target:
            matches.append((task_id, attempt, record, pending))
    return matches


def _claimed_action_for_tool_use(
    state: dict[str, Any], tool_use_id: str
) -> tuple[str, int, dict[str, Any], dict[str, Any]] | None:
    matches = []
    for task_id, attempt, record in _iter_task_attempts(state):
        pending = record.get("pending_action")
        if (
            isinstance(pending, dict)
            and pending.get("phase") == "claimed"
            and pending.get("tool_use_id") == tool_use_id
        ):
            matches.append((task_id, attempt, record, pending))
    if len(matches) > 1:
        raise StateConflictError(f"同一 tool_use_id 映射到多个 pending_action：{tool_use_id}")
    return matches[0] if matches else None


def _has_unresolved_lifecycle(record: dict[str, Any]) -> bool:
    last = record.get("last_lifecycle_operation")
    return isinstance(last, dict) and last.get("call_observation") in {"success", "unknown"}


def _pending_action_record(
    *,
    target: str,
    task_id: str,
    attempt: int,
    task_ref: str,
    operation_type: str,
    fields: dict[str, str],
    created_at: int,
    authorized_recovery: bool = False,
    resume_contract: TaskContract | None = None,
    resume_task_ref: str | None = None,
    prepared_on_attempt: int | None = None,
) -> dict[str, Any]:
    pending: dict[str, Any] = {
        "target": target,
        "task_id": task_id,
        "attempt": attempt,
        "task_ref": task_ref,
        "operation_type": operation_type,
        "phase": "prepared",
        "created_at": created_at,
        "expires_at": created_at + int(RETENTION_SECONDS["prepared_unclaimed"]),
        "tool_use_id": None,
        "claimed_at": None,
        "reason": fields["reason"],
        "authorized_recovery": authorized_recovery,
        "start_observed_at": None,
    }
    if resume_contract is not None:
        pending["resume_contract"] = resume_contract.to_record()
        pending["resume_contract_summary"] = _contract_summary(resume_contract)
        pending["resume_task_ref"] = resume_task_ref
        pending["prepared_on_attempt"] = prepared_on_attempt
    return pending


def _occupied_attempt_refs(state: dict[str, Any]) -> set[str]:
    occupied = {
        str(record["task_ref"])
        for _task_id, _attempt, record in _iter_task_attempts(state)
        if isinstance(record.get("task_ref"), str)
    }
    tombstones = state.get("tombstones")
    if isinstance(tombstones, dict):
        occupied.update(
            str(record["task_ref"])
            for record in tombstones.values()
            if isinstance(record, dict) and isinstance(record.get("task_ref"), str)
        )
    return occupied


def _business_resume_allowed(record: dict[str, Any]) -> bool:
    business_result = record.get("business_result")
    if business_result in {"blocked", "failed"}:
        return True
    if business_result == "needs_decision" and record.get("business_decision_resolved") is True:
        return True
    if business_result == "complete" and record.get("acceptance_status") == "rejected":
        return True
    return (
        record.get("attempt_close_reason") == "resume_delivery_failed"
        and record.get("parent_action") == "decide_disposition"
    )


def _native_tool_for_operation(operation_type: str) -> str:
    native_tool = OPERATION_NATIVE_TOOLS.get(operation_type)
    if not isinstance(native_tool, str) or not native_tool:
        raise CommunicationPreparationError(
            f"operation type 缺少原生工具映射：{operation_type}"
        )
    return native_tool


def _prepare_managed_action(
    value: dict[str, Any],
    session_id: str,
    *,
    state_store: StateStore,
    interrupt: bool,
    authorized_recovery: bool,
    now: int,
) -> dict[str, Any]:
    target, fields = _communication_fields(value, interrupt=interrupt)
    operation_type = "interrupt" if interrupt else str(value["operation_type"])
    native_tool = _native_tool_for_operation(operation_type)
    try:
        reconcile_pending_actions(session_id, state_store=state_store, now=now)
        state = state_store.read(session_id)
    except Exception as exc:
        if interrupt or operation_type == "normal_message":
            message = render_communication_message(fields, "normal_message")
            native_args = {"target": target} if interrupt else {"target": target, "message": message}
            return {
                "managed": False,
                "target": target,
                "operation_type": operation_type,
                "user_message": render_communication_user_message(target, fields),
                "message": "" if interrupt else message,
                "native_args": native_args,
                "native_tool": native_tool,
                "degraded_warning": f"治理状态不可用，本次操作未可靠记录：{exc}",
            }
        raise CommunicationPreparationError(
            f"{operation_type} 需要可靠 StateStore 前置写入：{exc}"
        ) from exc
    mapped = _managed_target_attempt(state, target)
    if mapped is None:
        resume_contract = None
        if operation_type == "business_resume":
            try:
                resume_contract = _contract_from_input(value.get("task_contract"))
            except (TypeError, ValueError) as exc:
                raise CommunicationPreparationError(
                    f"business_resume TaskContract 无效：{exc}"
                ) from exc
        message = "" if interrupt else render_communication_message(
            fields,
            operation_type,
            resume_contract=resume_contract,
        )
        native_args = {"target": target} if interrupt else {"target": target, "message": message}
        return {
            "managed": False,
            "target": target,
            "operation_type": operation_type,
            "user_message": render_communication_user_message(target, fields),
            "message": "" if interrupt else message,
            "native_args": native_args,
            "native_tool": native_tool,
            "degraded_warning": "通信目标未映射到 managed task；按原生 unmanaged 路径处理。",
        }
    task_id, attempt, record = mapped
    task_current = state.get("tasks", {}).get(task_id)
    if (
        operation_type == "business_resume"
        and isinstance(task_current, dict)
        and task_current.get("managed") is True
        and isinstance(task_current.get("attempt"), int)
        and task_current.get("attempt") > attempt
        and task_current.get("attempt_close_reason") != "resume_delivery_failed"
    ):
        raise CommunicationPreparationError(
            "前一 same-Agent business_resume attempt 仍未解决；unknown 替代执行必须使用新 spawn/new Agent"
        )
    if (
        operation_type == "business_resume"
        and isinstance(task_current, dict)
        and task_current.get("managed") is True
        and isinstance(task_current.get("attempt"), int)
        and task_current.get("attempt") > attempt
        and task_current.get("attempt_close_reason") == "resume_delivery_failed"
    ):
        attempt = int(task_current["attempt"])
        record = task_current
    if _pending_action_matches_target(state, target):
        raise CommunicationPreparationError(f"目标 {target} 已存在 pending_action")
    if not interrupt and operation_type == "normal_message" and record.get("platform_observation") == "error":
        raise CommunicationPreparationError(
            "normal_message 不能绕过 platform_observation=error 的平台恢复流程"
        )
    if operation_type in LIFECYCLE_OPERATION_TYPES and _has_unresolved_lifecycle(record):
        raise CommunicationPreparationError(
            "当前 attempt 仍有 success/unknown lifecycle operation 待启动或人工对账"
        )
    resume_contract = None
    desired_attempt = attempt
    desired_task_ref = str(record.get("task_ref") or "")
    if operation_type == "platform_recovery":
        if (
            record.get("execution_status") != "stopped"
            or record.get("platform_observation") != "error"
            or record.get("business_result") is not None
        ):
            raise CommunicationPreparationError(
                "platform_recovery 只适用于 stopped/error 且没有正式业务结果的同一 attempt"
            )
        recovery_count = record.get("recovery_count")
        recovery_status = record.get("recovery_status")
        if recovery_count == 0 and recovery_status is None and not authorized_recovery:
            pass
        elif recovery_count == 1 and recovery_status == "awaiting_authorization" and authorized_recovery:
            pass
        elif recovery_count == 1 and recovery_status == "awaiting_authorization":
            raise CommunicationPreparationError("最后一次平台恢复需要用户明确授权")
        else:
            raise CommunicationPreparationError("当前 Agent/attempt 的平台恢复次数已经耗尽或状态不兼容")
    elif operation_type == "result_correction":
        if (
            record.get("execution_status") != "stopped"
            or record.get("business_result") is not None
            or record.get("result_protocol_status") != "needs_correction"
        ):
            raise CommunicationPreparationError(
                "result_correction 只适用于 stopped、无业务结果且 needs_correction 的同一 attempt"
            )
        correction_count = record.get("correction_count")
        if isinstance(correction_count, bool) or not isinstance(correction_count, int) or not 0 <= correction_count < RETRY_LIMITS["correction"]:
            raise CommunicationPreparationError("结果补交次数已经耗尽或 correction_count 无效")
    elif operation_type == "business_resume":
        if record.get("execution_status") not in {"stopped", "interrupted"} or not _business_resume_allowed(record):
            raise CommunicationPreparationError("当前 attempt 不满足 business_resume 的机械前置条件")
        raw_contract = value.get("task_contract")
        try:
            resume_contract = _contract_from_input(raw_contract)
        except (TypeError, ValueError) as exc:
            raise CommunicationPreparationError(f"business_resume TaskContract 无效：{exc}") from exc
        old_summary = record.get("contract_summary")
        old_model = old_summary.get("model") if isinstance(old_summary, dict) else None
        if resume_contract.model != old_model:
            raise CommunicationPreparationError(
                "同 Agent business_resume 不能改变 model；需要换模型时必须使用新 spawn"
            )
        desired_attempt = attempt + 1
        desired_task_ref = select_task_ref(task_id, desired_attempt, _occupied_attempt_refs(state)) or ""
        if not desired_task_ref:
            raise CommunicationPreparationError("新 attempt 无法取得唯一 task_ref")
    elif interrupt:
        if record.get("execution_status") == "interrupted" or record.get("attempt_closed") is True:
            raise CommunicationPreparationError("当前 attempt 已中断或关闭，不能重复创建中断意图")

    pending = _pending_action_record(
        target=target,
        task_id=task_id,
        attempt=desired_attempt,
        task_ref=desired_task_ref,
        operation_type=operation_type,
        fields=fields,
        created_at=now,
        authorized_recovery=authorized_recovery,
        resume_contract=resume_contract,
        resume_task_ref=desired_task_ref if resume_contract else None,
        prepared_on_attempt=attempt if resume_contract else None,
    )

    def predicate(current: dict[str, Any]) -> bool:
        current_mapped = _managed_target_attempt(current, target)
        if current_mapped is None:
            return False
        if current_mapped[:2] != (task_id, attempt):
            current_task = current.get("tasks", {}).get(task_id)
            if not (
                operation_type == "business_resume"
                and isinstance(current_task, dict)
                and current_task.get("attempt") == attempt
                and current_task.get("attempt_close_reason") == "resume_delivery_failed"
            ):
                return False
        if _pending_action_matches_target(current, target):
            return False
        current_record = _task_record_for_attempt(current, task_id, attempt)
        return isinstance(current_record, dict) and current_record.get("updated_at") == record.get("updated_at")

    def create(current: dict[str, Any]) -> None:
        current_record = _task_record_for_attempt(current, task_id, attempt)
        assert current_record is not None
        current_record["pending_action"] = copy.deepcopy(pending)
        current_record["updated_at"] = now

    try:
        state_store.compare_and_set(session_id, predicate, create)
    except Exception as exc:
        if interrupt or operation_type == "normal_message":
            message = render_communication_message(fields, "normal_message")
            native_args = {"target": target} if interrupt else {"target": target, "message": message}
            return {
                "managed": False,
                "target": target,
                "operation_type": operation_type,
                "user_message": render_communication_user_message(target, fields),
                "message": "" if interrupt else message,
                "native_args": native_args,
                "native_tool": native_tool,
                "degraded_warning": f"pending_action 无法可靠创建，本次操作未纳入治理：{exc}",
            }
        raise CommunicationPreparationError(
            f"{operation_type} pending_action 无法原子创建：{exc}"
        ) from exc
    message = "" if interrupt else render_communication_message(
        fields,
        operation_type,
        resume_contract=resume_contract,
    )
    return {
        "managed": True,
        "task_id": task_id,
        "attempt": desired_attempt,
        "task_ref": desired_task_ref,
        "target": target,
        "operation_type": operation_type,
        "user_message": render_communication_user_message(target, fields),
        "message": message,
        "native_args": {"target": target} if interrupt else {"target": target, "message": message},
        "native_tool": native_tool,
    }


def prepare_communication(
    value: dict[str, Any],
    session_id: str,
    *,
    authorized_recovery: bool = False,
    state_store: StateStore | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    return _prepare_managed_action(
        value,
        session_id,
        state_store=state_store or StateStore(),
        interrupt=False,
        authorized_recovery=authorized_recovery,
        now=_now() if now is None else now,
    )


def prepare_interrupt(
    value: dict[str, Any],
    session_id: str,
    *,
    state_store: StateStore | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    return _prepare_managed_action(
        value,
        session_id,
        state_store=state_store or StateStore(),
        interrupt=True,
        authorized_recovery=False,
        now=_now() if now is None else now,
    )


def adapt_call_response(response: Any, operation_type: str) -> str:
    value = _json_value(response)
    if value is None or value == "" or value == {}:
        return "success"
    if not isinstance(value, dict):
        return "unknown"
    if value.get("isError") is True or value.get("is_error") is True:
        return "failed"
    status_value = value.get("status") if "status" in value else value.get("state")
    status = status_value.lower() if isinstance(status_value, str) else None
    if status in {"error", "failed", "failure"}:
        return "failed"
    if value.get("success") is True or status in {"ok", "success", "succeeded", "sent", "accepted"}:
        return "success"
    if operation_type == "interrupt" and status in {"interrupted", "cancelled", "canceled"}:
        return "success"
    return "unknown"


def _last_lifecycle_from_pending(
    pending: dict[str, Any], observation: str, completed_at: int
) -> dict[str, Any]:
    return {
        "operation_type": pending["operation_type"],
        "target": pending["target"],
        "tool_use_id": pending.get("tool_use_id"),
        "call_observation": observation,
        "claimed_at": pending.get("claimed_at"),
        "completed_at": completed_at,
        "reason": _bounded(pending.get("reason")),
    }


def _apply_action_observation(
    record: dict[str, Any],
    pending: dict[str, Any],
    observation: str,
    observed_at: int,
    *,
    state: dict[str, Any] | None = None,
) -> None:
    operation_type = str(pending["operation_type"])
    start_observed = isinstance(pending.get("start_observed_at"), int)
    record.pop("pending_action", None)
    if operation_type == "normal_message":
        record["updated_at"] = observed_at
        return
    lifecycle = _last_lifecycle_from_pending(pending, observation, observed_at)
    if operation_type == "platform_recovery":
        if start_observed and observation in {"success", "unknown"}:
            record["last_lifecycle_operation"] = lifecycle
            record.pop("last_lifecycle_operation", None)
            record["execution_status"] = "running"
            record["platform_observation"] = "normal"
            record["recovery_status"] = None
            record["parent_action"] = "wait"
        elif start_observed and observation == "failed":
            record["last_lifecycle_operation"] = lifecycle
            record["parent_action"] = "reconcile"
        else:
            record["execution_status"] = "stopped"
            record["platform_observation"] = "error"
            record["last_lifecycle_operation"] = lifecycle
            if observation == "success":
                record["recovery_status"] = None
                record["parent_action"] = "wait"
            elif observation == "unknown":
                record["recovery_status"] = None
                record["parent_action"] = "reconcile"
            elif record.get("recovery_count") == 1:
                record["recovery_status"] = "awaiting_authorization"
                record["parent_action"] = "ask_user"
            else:
                record["recovery_status"] = "exhausted"
                record["parent_action"] = "ask_user"
    elif operation_type == "result_correction":
        record["last_lifecycle_operation"] = lifecycle
        if start_observed and observation in {"success", "unknown"}:
            record.pop("last_lifecycle_operation", None)
            record["execution_status"] = "running"
            record["parent_action"] = "wait"
        elif start_observed and observation == "failed":
            record["parent_action"] = "reconcile"
        else:
            record["execution_status"] = "stopped"
            if observation == "success":
                record["parent_action"] = "wait"
            elif observation == "unknown":
                record["parent_action"] = "reconcile"
            elif record.get("correction_count") == 1:
                record["parent_action"] = "correct_result"
            else:
                record["result_protocol_status"] = "exhausted"
                record["parent_action"] = "manual_review"
    elif operation_type == "business_resume":
        if start_observed and observation in {"success", "unknown"}:
            record["execution_status"] = "running"
            record["platform_observation"] = "normal"
            record["parent_action"] = "wait"
            record.pop("last_lifecycle_operation", None)
        elif start_observed and observation == "failed":
            record["last_lifecycle_operation"] = lifecycle
            record["parent_action"] = "reconcile"
        elif observation == "success":
            record["execution_status"] = "not_started"
            record["parent_action"] = "wait"
            record["last_lifecycle_operation"] = lifecycle
        elif observation == "unknown":
            record["execution_status"] = "not_started"
            record["parent_action"] = "reconcile"
            record["last_lifecycle_operation"] = lifecycle
        else:
            record["execution_status"] = "stopped"
            record["attempt_closed"] = True
            record["attempt_close_reason"] = "resume_delivery_failed"
            record["attempt_closed_at"] = observed_at
            record["parent_action"] = "decide_disposition"
            record.pop("last_lifecycle_operation", None)
    elif operation_type == "interrupt":
        if observation == "success":
            if state is not None and _close_unselected_duplicate_attempt(
                state,
                record,
                reason="select_attempt_interrupt_success",
                observed_at=observed_at,
                execution_status="interrupted",
            ):
                return
            record["execution_status"] = "interrupted"
            record["parent_action"] = "decide_disposition"
            record.pop("last_lifecycle_operation", None)
        elif observation == "unknown":
            record["last_lifecycle_operation"] = lifecycle
            record["parent_action"] = "reconcile"
        else:
            record["last_lifecycle_operation"] = lifecycle
            if record.get("duplicate_not_selected") is True:
                record["parent_action"] = "ask_user"
    record["updated_at"] = observed_at


def reconcile_pending_actions(
    session_id: str,
    *,
    state_store: StateStore,
    now: int | None = None,
) -> dict[str, int]:
    current_time = _now() if now is None else now
    counts = {"expired": 0, "reconciled": 0}

    def reconcile(state: dict[str, Any]) -> None:
        for _task_id, _attempt, record in _iter_task_attempts(state):
            pending = record.get("pending_action")
            if not isinstance(pending, dict):
                continue
            if pending.get("phase") == "prepared":
                expires_at = pending.get("expires_at")
                if isinstance(expires_at, int) and expires_at <= current_time:
                    record.pop("pending_action", None)
                    record["updated_at"] = current_time
                    counts["expired"] += 1
                continue
            claimed_at = pending.get("claimed_at")
            if (
                pending.get("phase") == "claimed"
                and isinstance(claimed_at, int)
                and claimed_at <= current_time - int(RETENTION_SECONDS["claimed_reconcile"])
            ):
                _apply_action_observation(
                    record,
                    copy.deepcopy(pending),
                    "unknown",
                    current_time,
                    state=state,
                )
                counts["reconciled"] += 1

    state_store.update(session_id, reconcile)
    return counts


def _tool_kind(tool_name: str) -> str | None:
    if tool_name == "Agent" or tool_name.endswith("spawn_agent"):
        return "spawn"
    if tool_name.endswith("followup_task"):
        return "followup"
    if tool_name.endswith("send_message") and not tool_name.endswith("send_message_to_thread"):
        return "communication"
    if tool_name.endswith("interrupt_agent"):
        return "interrupt"
    if tool_name.endswith("list_agents"):
        return "agent_status"
    return None


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _allow_updated(updated_input: dict[str, Any], context: str | None = None) -> dict[str, Any]:
    output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "updatedInput": updated_input,
    }
    if context:
        output["additionalContext"] = context
    return {"hookSpecificOutput": output}


def _bounded(value: Any, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    return text[:MAX_CONTRACT_TEXT]


def _handle_spawn(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return _deny("子 Agent 派发被阻止：spawn_agent 参数不是对象。")
    task_name_value = tool_input.get("task_name")
    task_name = task_name_value if isinstance(task_name_value, str) else ""
    if not task_name.startswith("sg_"):
        return _allow_updated(
            copy.deepcopy(tool_input),
            "Subagent Governance：无治理前缀，本次原生 spawn 按 unmanaged 兼容放行；不创建治理状态。",
        )
    parsed = parse_task_name(task_name)
    if parsed is None:
        return _deny(
            "子 Agent 派发被阻止：governed task_name 必须符合 "
            "sg_<resolved_mode>_<semantic_name>_t_<task_ref>，总长度不超过64字符。"
        )
    mode, _semantic_name, task_ref = parsed
    session_id = str(payload.get("session_id") or "unknown")
    try:
        prepared_store = PreparedContractStore(_prepared_root_for_store(store))
        prepared = prepared_store.read(session_id, task_ref)
    except Exception as exc:
        return _deny(f"子 Agent 派发被阻止：PreparedContract 硬门禁失败：{exc}")
    if prepared.get("consumed") is True:
        return _deny("子 Agent 派发被阻止：PreparedContract 已被消费，不能重复调用原生 spawn。")
    current_time = _now()
    if prepared.get("created_at", 0) <= current_time - int(RETENTION_SECONDS["prepared_unclaimed"]):
        try:
            _cleanup_initial_attempt(
                session_id,
                str(prepared["task_id"]),
                int(prepared["attempt"]),
                task_ref,
                store,
            )
            prepared_store.delete(session_id, task_ref)
        except Exception as exc:
            return _deny(f"子 Agent 派发被阻止：过期 PreparedContract 清理失败：{exc}")
        return _deny("子 Agent 派发被阻止：PreparedContract 已超过5分钟，请重新生成派发。")
    expected_native = prepared["native_parameters"]
    mismatches = []
    if prepared.get("task_name") != task_name or prepared.get("resolved_mode") != mode:
        mismatches.append("task_name/resolved_mode")
    for field_name in ("fork_turns", "model", "reasoning_effort"):
        actual = tool_input.get(field_name)
        expected = expected_native.get(field_name)
        if actual != expected:
            mismatches.append(field_name)
    if mismatches:
        return _deny(
            "子 Agent 派发被阻止：原生可观察参数与 PreparedContract 不一致："
            + "、".join(mismatches)
        )
    task_id = str(prepared["task_id"])
    attempt = int(prepared["attempt"])
    desired_retry_count = int(prepared["spawn_retry_count"])
    tool_use_id = str(payload.get("tool_use_id") or "")
    if not tool_use_id:
        return _deny("子 Agent 派发被阻止：缺少 tool_use_id，无法单次消费 PreparedContract。")
    try:
        state = store.read(session_id)
        record = _task_record_for_attempt(state, task_id, attempt)
        if (
            record is None
            or record.get("task_ref") != task_ref
            or record.get("task_name") != task_name
            or record.get("resolved_mode") != mode
        ):
            raise StateValidationError("StateStore 中不存在匹配的 task/attempt/task_ref")
        if desired_retry_count == 0:
            if record.get("spawn_observation") is not None or record.get("spawn_retry_count") != 0:
                raise StateConflictError("初始 spawn 状态已变化")
        elif not (
            record.get("spawn_observation") == "failed"
            and record.get("identity_status") == "unconfirmed"
            and record.get("spawn_retry_count") == desired_retry_count - 1
        ):
            raise StateConflictError("spawn retry 状态或计数不匹配")

        prepared_store.compare_and_set(
            session_id,
            task_ref,
            lambda value: value.get("consumed") is False,
            lambda value: value.update(
                {"consumed": True, "tool_use_id": tool_use_id, "claimed_at": current_time}
            ),
        )

        def state_predicate(current: dict[str, Any]) -> bool:
            target = _task_record_for_attempt(current, task_id, attempt)
            if target is None or target.get("task_ref") != task_ref:
                return False
            if desired_retry_count == 0:
                return target.get("spawn_observation") is None and target.get("spawn_retry_count") == 0
            return (
                target.get("spawn_observation") == "failed"
                and target.get("identity_status") == "unconfirmed"
                and target.get("spawn_retry_count") == desired_retry_count - 1
            )

        def claim(current: dict[str, Any]) -> None:
            target = _task_record_for_attempt(current, task_id, attempt)
            assert target is not None
            target["spawn_tool_use_id"] = tool_use_id
            target["spawn_claimed_at"] = current_time
            target["spawn_retry_count"] = desired_retry_count
            target["spawn_observation"] = None
            target["parent_action"] = "retry_spawn" if desired_retry_count else None
            target["updated_at"] = current_time

        try:
            store.compare_and_set(session_id, state_predicate, claim)
        except Exception:
            prepared_store.compare_and_set(
                session_id,
                task_ref,
                lambda value: value.get("tool_use_id") == tool_use_id,
                lambda value: value.update(
                    {"consumed": False, "tool_use_id": None, "claimed_at": None}
                ),
            )
            raise
    except Exception as exc:
        return _deny(f"子 Agent 派发被阻止：StateStore/PreparedContract 认领失败：{exc}")
    return _allow_updated(
        copy.deepcopy(tool_input),
        f"Subagent Governance 已消费 task_ref={task_ref} 的派发凭证并完成发送前双门禁。",
    )


def _create_resume_attempt(
    state: dict[str, Any],
    task_id: str,
    old_attempt: int,
    pending: dict[str, Any],
    claimed_at: int,
    tool_use_id: str,
) -> dict[str, Any]:
    old = _task_record_for_attempt(state, task_id, old_attempt)
    if old is None or old.get("pending_action") != pending:
        raise StateConflictError("business_resume prepared action 与旧 attempt 不匹配")
    contract = _contract_from_input(pending.get("resume_contract"))
    new_attempt = int(pending["attempt"])
    task_ref = str(pending["resume_task_ref"])
    prior_attempts = copy.deepcopy(old.get("prior_attempts")) if isinstance(old.get("prior_attempts"), dict) else {}
    _clear_result_conflict(old)
    old_snapshot = copy.deepcopy(old)
    old_snapshot.pop("prior_attempts", None)
    old_snapshot.pop("pending_action", None)
    prior_attempts[str(old_attempt)] = old_snapshot
    task_name = str(old.get("task_name") or "")
    created = _initial_task_record(
        task_id,
        new_attempt,
        task_ref,
        task_name,
        contract,
        claimed_at,
    )
    created["identity_status"] = "confirmed"
    created["execution_status"] = "not_started"
    created["agent_id"] = old.get("agent_id")
    created["canonical_task_path"] = old.get("canonical_task_path")
    created["prior_attempts"] = prior_attempts
    claimed = copy.deepcopy(pending)
    claimed.update(
        {
            "phase": "claimed",
            "tool_use_id": tool_use_id,
            "claimed_at": claimed_at,
        }
    )
    created["pending_action"] = claimed
    state["tasks"][task_id] = created
    return created


def _claim_pending_action(
    payload: dict[str, Any], store: StateStore, *, interrupt: bool = False
) -> dict[str, Any]:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return _deny("子 Agent 操作被阻止：工具参数不是对象。")
    target_value = tool_input.get("target")
    if not isinstance(target_value, str) or not target_value.strip():
        return _deny("子 Agent 操作被阻止：target 必须是非空字符串。")
    target = target_value.strip()
    session_id = str(payload.get("session_id") or "unknown")
    tool_use_id = str(payload.get("tool_use_id") or "")
    current_time = _event_now(payload)
    kind = _tool_kind(str(payload.get("tool_name") or ""))
    try:
        state = store.read(session_id)
    except Exception as exc:
        if interrupt or kind == "communication":
            projected = {"target": target} if interrupt else copy.deepcopy(tool_input)
            return _allow_updated(
                projected,
                f"Subagent Governance 状态不可读，本次原生操作已 fail-open；治理状态未可靠记录：{exc}",
            )
        return _deny(f"受治理 lifecycle 操作被阻止：StateStore 不可读：{exc}")
    matches = _pending_action_matches_target(state, target)
    if not matches:
        mapped = _managed_target_attempt(state, target)
        if mapped is None:
            return _allow_updated(
                copy.deepcopy(tool_input),
                "Subagent Governance：目标未映射到 managed task，本次原生操作按 unmanaged 兼容放行。",
            )
        if interrupt:
            return _deny("managed interrupt 缺少由生成器创建的明确 pending_action。")
        if kind == "communication":
            return _deny("managed normal_message 缺少由生成器创建的唯一 prepared pending_action。")
        return _deny("managed followup_task 缺少唯一 prepared pending_action，不能猜测 operation type。")
    if len(matches) != 1:
        return _deny("同一 target 映射到多个 pending_action，已拒绝调用并要求人工对账。")
    if not tool_use_id:
        return _deny("子 Agent 操作被阻止：缺少 tool_use_id，无法认领 pending_action。")
    task_id, stored_attempt, _record, pending = matches[0]
    operation_type = str(pending.get("operation_type") or "")
    if interrupt != (operation_type == "interrupt"):
        return _deny("原生工具类型与 prepared operation type 不匹配。")
    if not interrupt:
        if kind == "communication":
            if operation_type != "normal_message":
                return _deny("send_message 只能认领 normal_message pending_action。")
        elif kind == "followup":
            if operation_type == "normal_message":
                return _deny("followup_task 不能认领 normal_message pending_action。")
        else:
            return _deny("通信 pending_action 与原生工具类型不匹配。")
    if pending.get("phase") != "prepared":
        return _deny("pending_action 已被认领，不能重复调用。")
    expires_at = pending.get("expires_at")
    if not isinstance(expires_at, int) or expires_at <= current_time:
        try:
            store.update(
                session_id,
                lambda current: _task_record_for_attempt(current, task_id, stored_attempt).pop("pending_action", None),
            )
        except Exception as exc:
            return _deny(f"过期 pending_action 清理失败：{exc}")
        return _deny("pending_action 已超过5分钟，请重新生成本次操作。")

    def predicate(current: dict[str, Any]) -> bool:
        current_matches = _pending_action_matches_target(current, target)
        return bool(
            len(current_matches) == 1
            and current_matches[0][0] == task_id
            and current_matches[0][1] == stored_attempt
            and current_matches[0][3].get("phase") == "prepared"
            and current_matches[0][3].get("created_at") == pending.get("created_at")
        )

    def claim(current: dict[str, Any]) -> None:
        current_record = _task_record_for_attempt(current, task_id, stored_attempt)
        assert current_record is not None
        current_pending = current_record["pending_action"]
        if operation_type == "business_resume":
            current_record = _create_resume_attempt(
                current,
                task_id,
                stored_attempt,
                copy.deepcopy(current_pending),
                current_time,
                tool_use_id,
            )
        else:
            current_pending["phase"] = "claimed"
            current_pending["tool_use_id"] = tool_use_id
            current_pending["claimed_at"] = current_time
        if operation_type == "platform_recovery":
            count = current_record.get("recovery_count")
            if isinstance(count, bool) or not isinstance(count, int) or count >= RETRY_LIMITS["recovery"]:
                raise StateConflictError("recovery_count 无效或已经耗尽")
            current_record["recovery_count"] = count + 1
            if current_record["recovery_count"] == 2:
                if pending.get("authorized_recovery") is not True:
                    raise StateConflictError("第二次平台恢复缺少用户授权")
                current_record["recovery_status"] = None
        elif operation_type == "result_correction":
            count = current_record.get("correction_count")
            if isinstance(count, bool) or not isinstance(count, int) or count >= RETRY_LIMITS["correction"]:
                raise StateConflictError("correction_count 无效或已经耗尽")
            current_record["correction_count"] = count + 1
        current_record["updated_at"] = current_time

    try:
        store.compare_and_set(session_id, predicate, claim)
    except Exception as exc:
        if interrupt:
            return _allow_updated(
                {"target": target},
                f"中断 target 明确，但治理认领失败；已 fail-open 调用原生中断，状态需人工对账：{exc}",
            )
        return _deny(f"受治理 lifecycle 操作认领失败：{exc}")
    projected = {"target": target} if interrupt else {
        "target": target,
        "message": str(tool_input.get("message") or ""),
    }
    return _allow_updated(
        projected,
        f"Subagent Governance 已认领 {operation_type} pending_action 并绑定 tool_use_id。",
    )


def _handle_communication(payload: dict[str, Any], store: StateStore) -> dict[str, Any] | None:
    return _claim_pending_action(payload, store, interrupt=False)


def _handle_interrupt_pre(payload: dict[str, Any], store: StateStore) -> dict[str, Any] | None:
    return _claim_pending_action(payload, store, interrupt=True)


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _agent_status_entries(response: Any) -> list[dict[str, Any]]:
    value = _json_value(response)
    if not isinstance(value, dict) or not isinstance(value.get("agents"), list):
        return []
    return [entry for entry in value["agents"] if isinstance(entry, dict)]


def _resolve_task_id(state: dict[str, Any], target: str) -> str | None:
    """Resolve only exact native Agent ID/canonical path mappings."""
    if not target:
        return None
    agents = state.get("agents")
    tasks = state.get("tasks")
    if not isinstance(agents, dict) or not isinstance(tasks, dict):
        raise StateValidationError("治理状态缺少任务解析所需的 tasks 或 agents 对象")
    mapped = agents.get(target)
    if isinstance(mapped, dict):
        task_id = mapped.get("task_id")
        mapped_attempt = mapped.get("attempt")
        if (
            isinstance(task_id, str)
            and isinstance(mapped_attempt, int)
            and not isinstance(mapped_attempt, bool)
        ):
            record = _task_record_for_attempt(state, task_id, mapped_attempt)
            if isinstance(record, dict) and record.get("managed") is True:
                return task_id
    return None


def _identity_mapping(task_id: str, attempt: int) -> dict[str, Any]:
    return {"task_id": task_id, "attempt": attempt}


def _bind_identity_target(
    state: dict[str, Any],
    record: dict[str, Any],
    target: str | None,
) -> None:
    if not target:
        return
    agents = state.get("agents")
    if not isinstance(agents, dict):
        raise StateValidationError("治理状态缺少 agents 对象")
    desired = _identity_mapping(str(record["task_id"]), int(record["attempt"]))
    existing = agents.get(target)
    if existing is not None and existing != desired:
        raise StateConflictError(f"Agent target 已绑定到其他 task/attempt：{target}")
    agents[target] = desired


def _handle_post_tool(payload: dict[str, Any], store: StateStore) -> dict[str, Any] | None:
    session_id = str(payload.get("session_id") or "unknown")
    kind = _tool_kind(str(payload.get("tool_name") or ""))
    tool_use_id = str(payload.get("tool_use_id") or "")
    response = payload.get("tool_response")

    if kind == "agent_status":
        entries = _agent_status_entries(response)
        if not entries:
            return None

        def reconcile(state: dict[str, Any]) -> None:
            for entry in entries:
                target = str(entry.get("agent_name") or "")
                task_id = _resolve_task_id(state, target)
                mapped = state.get("agents", {}).get(target)
                mapped_attempt = mapped.get("attempt") if isinstance(mapped, dict) else None
                record = (
                    _task_record_for_attempt(state, task_id, int(mapped_attempt))
                    if task_id and isinstance(mapped_attempt, int)
                    else state.get("tasks", {}).get(task_id) if task_id else None
                )
                if not isinstance(record, dict):
                    continue
                platform_status = entry.get("agent_status")
                observed_at = _event_now(payload)
                record["platform_checked_at"] = observed_at
                record["platform_observation_source"] = "list_agents"
                last = record.get("last_lifecycle_operation")
                interrupt_unknown = bool(
                    isinstance(last, dict)
                    and last.get("operation_type") == "interrupt"
                    and last.get("call_observation") == "unknown"
                )
                if isinstance(platform_status, dict) and platform_status.get("errored"):
                    record["platform_observation"] = "error"
                    record["platform_observation_summary"] = _bounded(platform_status.get("errored"))
                    if record.get("execution_status") == "running":
                        record["execution_status"] = "stopped"
                        if interrupt_unknown:
                            record["parent_action"] = "ask_user"
                        elif record.get("recovery_count") == 0:
                            record["recovery_status"] = None
                            record["parent_action"] = "recover"
                        elif record.get("recovery_count") == 1:
                            record["recovery_status"] = "awaiting_authorization"
                            record["parent_action"] = "ask_user"
                        else:
                            record["recovery_status"] = "exhausted"
                            record["parent_action"] = "ask_user"
                    elif interrupt_unknown:
                        record["parent_action"] = "ask_user"
                    record["updated_at"] = observed_at
                    continue
                if isinstance(platform_status, dict):
                    if platform_status.get("running") is True:
                        record["platform_observation"] = "normal"
                        if interrupt_unknown:
                            record["parent_action"] = "ask_user"
                    elif platform_status.get("stopped") is True or platform_status.get("completed") is True:
                        if record.get("execution_status") != "interrupted":
                            record["execution_status"] = "stopped"
                        record["platform_observation"] = "normal"
                        if interrupt_unknown and _close_unselected_duplicate_attempt(
                            state,
                            record,
                            reason="select_attempt_platform_stopped",
                            observed_at=observed_at,
                            execution_status="stopped",
                        ):
                            continue
                        if interrupt_unknown:
                            record["parent_action"] = "decide_disposition"
                    else:
                        record["platform_observation"] = "unknown"
                else:
                    record["platform_observation"] = "unknown"
                record["updated_at"] = observed_at

        try:
            store.update(session_id, reconcile)
        except (OSError, RuntimeError) as exc:
            return {"systemMessage": f"Subagent Governance 无法对账 Agent 平台状态，已降级放行：{exc}"}
        return None

    if kind in {"communication", "followup", "interrupt"}:
        observed_at = _event_now(payload)
        try:
            state = store.read(session_id)
            claimed = _claimed_action_for_tool_use(state, tool_use_id)
        except Exception as exc:
            return {
                "systemMessage": (
                    "Subagent Governance 无法读取 lifecycle claim；原生调用已经发生，"
                    f"治理状态进入 degraded 并需人工对账：{exc}"
                )
            }
        if claimed is not None:
            task_id, attempt, _record, pending = claimed
            observation = adapt_call_response(response, str(pending.get("operation_type")))

            def predicate(current: dict[str, Any]) -> bool:
                target = _task_record_for_attempt(current, task_id, attempt)
                action = target.get("pending_action") if isinstance(target, dict) else None
                return bool(
                    isinstance(action, dict)
                    and action.get("phase") == "claimed"
                    and action.get("tool_use_id") == tool_use_id
                )

            def apply(current: dict[str, Any]) -> None:
                target = _task_record_for_attempt(current, task_id, attempt)
                assert target is not None
                current_pending = copy.deepcopy(target["pending_action"])
                _apply_action_observation(
                    target,
                    current_pending,
                    observation,
                    observed_at,
                    state=current,
                )

            try:
                store.compare_and_set(session_id, predicate, apply)
            except Exception as exc:
                return {
                    "systemMessage": (
                        f"Subagent Governance 已观察到原生调用 {observation}，但状态写入失败；"
                        f"已消耗的预算或 attempt 不回滚，治理状态 degraded：{exc}"
                    )
                }
            return None

        return None

    if kind != "spawn":
        return None
    try:
        prepared_store = PreparedContractStore(_prepared_root_for_store(store))
        prepared = prepared_store.find_claimed(session_id, tool_use_id)
    except Exception as exc:
        return {"systemMessage": f"Subagent Governance 无法读取派发凭证，需人工对账：{exc}"}
    if prepared is None:
        return None
    observation = adapt_spawn_response(response)
    task_id = str(prepared["task_id"])
    attempt = int(prepared["attempt"])
    task_ref = str(prepared["task_ref"])
    observed_at = _now()

    def predicate(state: dict[str, Any]) -> bool:
        record = _task_record_for_attempt(state, task_id, attempt)
        return bool(
            record
            and record.get("task_ref") == task_ref
            and record.get("spawn_tool_use_id") == tool_use_id
            and record.get("spawn_observation") is None
        )

    def update_spawn(state: dict[str, Any]) -> None:
        record = _task_record_for_attempt(state, task_id, attempt)
        assert record is not None
        spawn_observation = str(observation["observation"])
        record["spawn_observation"] = spawn_observation
        record["spawn_post_observed_at"] = observed_at
        record["updated_at"] = observed_at
        if spawn_observation == "failed":
            record["identity_status"] = "unconfirmed"
            record["execution_status"] = (
                "stopped" if record.get("spawn_retry_count") == RETRY_LIMITS["spawn"] else "not_started"
            )
            retry_count = int(record.get("spawn_retry_count") or 0)
            if retry_count == 0:
                record["parent_action"] = "retry_spawn"
            elif retry_count == 1:
                record["parent_action"] = "ask_user"
            else:
                record["parent_action"] = "decide_disposition"
                record["spawn_close_reason"] = "spawn_retry_exhausted"
                state["tombstones"][f"{task_id}:{attempt}"] = {
                    "task_id": task_id,
                    "attempt": attempt,
                    "task_ref": task_ref,
                    "close_reason": "spawn_retry_exhausted",
                    "closed_at": observed_at,
                }
            return
        agent_id = observation.get("agent_id")
        canonical_path = observation.get("canonical_path")
        if spawn_observation == "success" and (agent_id or canonical_path):
            _bind_identity_target(state, record, agent_id)
            _bind_identity_target(state, record, canonical_path)
            record["agent_id"] = agent_id
            record["canonical_task_path"] = canonical_path
            record["identity_status"] = "confirmed"
            record["execution_status"] = "running"
            record["platform_observation"] = "normal"
            record["platform_checked_at"] = observed_at
            record["platform_observation_source"] = "spawn_response"
            record["recovery_status"] = None
            record["parent_action"] = "wait"
            return
        record["identity_status"] = "unconfirmed"
        record["execution_status"] = "not_started"
        record["parent_action"] = "reconcile"

    try:
        store.compare_and_set(session_id, predicate, update_spawn)
    except StateConflictError:
        return {
            "systemMessage": (
                "Subagent Governance 派发结果与当前 claim 不匹配，已保留较新状态并要求人工对账。"
            )
        }
    except (OSError, RuntimeError) as exc:
        return {"systemMessage": f"Subagent Governance 无法记录派发生命周期，已降级放行：{exc}"}
    delete_prepared = observation["observation"] == "failed" or bool(
        observation.get("agent_id") or observation.get("canonical_path")
    )
    warning = None
    try:
        if delete_prepared:
            prepared_store.delete(session_id, task_ref)
        else:
            prepared_store.compare_and_set(
                session_id,
                task_ref,
                lambda value: value.get("tool_use_id") == tool_use_id,
                lambda value: value.update({"post_observed_at": observed_at}),
            )
    except Exception as exc:
        warning = f"派发状态已记录，但 PreparedContract 收缩失败：{exc}"
    if warning or getattr(store, "last_warning", None):
        return {"systemMessage": warning or str(store.last_warning)}
    return None


def _mapped_attempt(
    state: dict[str, Any], target: str
) -> tuple[str, int, dict[str, Any]] | None:
    agents = state.get("agents")
    tasks = state.get("tasks")
    if not isinstance(agents, dict) or not isinstance(tasks, dict):
        raise StateValidationError("治理状态缺少启动绑定所需的 tasks 或 agents 对象")
    existing = agents.get(target)
    if isinstance(existing, dict):
        task_id = existing.get("task_id")
        mapped_attempt = existing.get("attempt")
        if (
            isinstance(task_id, str)
            and isinstance(mapped_attempt, int)
            and not isinstance(mapped_attempt, bool)
        ):
            record = _task_record_for_attempt(state, task_id, mapped_attempt)
            if isinstance(record, dict):
                return task_id, mapped_attempt, record
    return None


def _event_task_name(payload: dict[str, Any]) -> str | None:
    for field_name in ("task_name", "canonical_task_path", "agent_name"):
        value = payload.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip("/").rsplit("/", 1)[-1]
    return None


def _assign_starting_agent(
    state: dict[str, Any],
    agent_id: str,
    canonical_path: str | None,
    task_name: str | None,
) -> tuple[str, int, str] | None:
    targets = [target for target in (agent_id, canonical_path) if target]
    lifecycle_candidates: list[tuple[str, int, dict[str, Any], str]] = []
    failed_lifecycle_candidates: list[tuple[str, int, dict[str, Any]]] = []
    for task_id, attempt, candidate in _iter_task_attempts(state):
        pending = candidate.get("pending_action")
        if isinstance(pending, dict) and pending.get("target") in targets and pending.get("phase") == "claimed":
            operation_type = str(pending.get("operation_type") or "")
            if operation_type in {"platform_recovery", "result_correction", "business_resume"}:
                lifecycle_candidates.append((task_id, attempt, candidate, "pending"))
        last = candidate.get("last_lifecycle_operation")
        if isinstance(last, dict) and last.get("target") in targets:
            operation_type = str(last.get("operation_type") or "")
            observation = last.get("call_observation")
            if operation_type in {"platform_recovery", "result_correction", "business_resume"}:
                if observation in {"success", "unknown"}:
                    lifecycle_candidates.append((task_id, attempt, candidate, "last"))
                elif observation == "failed":
                    failed_lifecycle_candidates.append((task_id, attempt, candidate))
    unique_lifecycle = {
        (task_id, attempt, source): (task_id, attempt, candidate, source)
        for task_id, attempt, candidate, source in lifecycle_candidates
    }
    if len(unique_lifecycle) > 1:
        raise StateConflictError("SubagentStart 匹配到多个 lifecycle operation")
    lifecycle_authorization = next(iter(unique_lifecycle.values()), None)
    lifecycle_operation_type = None
    if lifecycle_authorization is not None:
        _lifecycle_task, _lifecycle_attempt, lifecycle_record, source = lifecycle_authorization
        lifecycle_value = (
            lifecycle_record.get("pending_action")
            if source == "pending"
            else lifecycle_record.get("last_lifecycle_operation")
        )
        if isinstance(lifecycle_value, dict):
            lifecycle_operation_type = lifecycle_value.get("operation_type")
    resolved: tuple[str, int, dict[str, Any]] | None = None
    for target in targets:
        mapped = _mapped_attempt(state, target)
        if mapped is not None:
            if resolved is not None and mapped[:2] != resolved[:2]:
                raise StateConflictError("SubagentStart 的 Agent ID 与 canonical path 映射冲突")
            resolved = mapped
    if lifecycle_authorization is not None:
        lifecycle_task, lifecycle_attempt, lifecycle_record, _source = lifecycle_authorization
        if resolved is not None and resolved[0] != lifecycle_task:
            raise StateConflictError("SubagentStart 的 Agent 映射与 lifecycle task 冲突")
        resolved = (lifecycle_task, lifecycle_attempt, lifecycle_record)
    parsed = parse_task_name(task_name) if task_name else None
    if resolved is not None and parsed is not None:
        mapped_record = resolved[2]
        business_resume_name_matches = bool(
            lifecycle_operation_type == "business_resume"
            and mapped_record.get("task_name") == task_name
        )
        if mapped_record.get("managed") is True and not business_resume_name_matches and (
            mapped_record.get("task_name") != task_name
            or mapped_record.get("task_ref") != parsed[2]
            or mapped_record.get("resolved_mode") != parsed[0]
        ):
            raise StateConflictError(
                "SubagentStart 的已确认 Agent 映射与事件 task_name/task_ref 冲突"
            )
    if resolved is None and parsed is not None:
        _mode, _semantic_name, task_ref = parsed
        matches = [
            (str(task_id), int(record.get("attempt", 0)), record)
            for task_id, record in state.get("tasks", {}).items()
            if isinstance(record, dict)
            and record.get("managed") is True
            and record.get("task_ref") == task_ref
            and record.get("task_name") == task_name
        ]
        if len(matches) == 1:
            resolved = matches[0]
    if resolved is None:
        return None
    task_id, attempt, record = resolved
    if record.get("managed") is not True:
        return task_id, attempt, "historical"
    if record.get("attempt_closed") is True:
        return task_id, attempt, "closed"
    last_operation = record.get("last_lifecycle_operation")
    if isinstance(last_operation, dict) and last_operation.get("operation_type") == "interrupt":
        return task_id, attempt, "closed"
    if record.get("business_result") is not None or record.get("execution_status") == "interrupted":
        return task_id, attempt, "closed"
    if record.get("spawn_observation") == "failed":
        return task_id, attempt, "closed"
    spawn_start_authorized = bool(
        parsed is not None
        and record.get("task_ref") == parsed[2]
        and record.get("identity_status") == "unconfirmed"
        and record.get("spawn_observation") in {None, "success", "unknown"}
    )
    if (
        record.get("execution_status") in {"stopped", "not_started"}
        and lifecycle_authorization is None
        and not spawn_start_authorized
    ):
        if any(candidate[:2] == (task_id, attempt) for candidate in failed_lifecycle_candidates):
            record["parent_action"] = "reconcile"
            record["updated_at"] = _now()
        return task_id, attempt, "closed"
    if not targets:
        return None
    for target in targets:
        desired = _identity_mapping(task_id, attempt)
        existing = state["agents"].get(target)
        if existing is not None and existing != desired:
            if not (
                lifecycle_authorization is not None
                and isinstance(existing, dict)
                and existing.get("task_id") == task_id
            ):
                raise StateConflictError(f"Agent target 已绑定到其他 task/attempt：{target}")
            state["agents"][target] = desired
        else:
            _bind_identity_target(state, record, target)
    if agent_id:
        record["agent_id"] = agent_id
    if canonical_path:
        record["canonical_task_path"] = canonical_path
    record["identity_status"] = "confirmed"
    record["execution_status"] = "running"
    record["platform_observation"] = "normal"
    record["platform_checked_at"] = _now()
    record["platform_observation_source"] = "subagent_start"
    record["recovery_status"] = None
    record["parent_action"] = "wait"
    record["updated_at"] = _now()
    if lifecycle_authorization is not None:
        _task_id, _attempt, _candidate, source = lifecycle_authorization
        if source == "pending":
            pending = record.get("pending_action")
            if isinstance(pending, dict):
                pending["start_observed_at"] = _now()
        else:
            record.pop("last_lifecycle_operation", None)
    return task_id, attempt, "managed"


def _subagent_start_context(
    task_id: str | None,
    record: dict[str, Any],
    warning: str | None,
) -> str:
    mapped = bool(task_id and record)
    lifecycle_status = record.get("execution_status") or "unknown"
    mode = record.get("resolved_mode") or "unknown"
    lines = [
        "【Subagent Governance 启动上下文】",
        f"治理任务 ID：{task_id}" if mapped else "治理任务 ID：未映射",
        f"治理状态：{lifecycle_status}" if mapped else "治理状态：unmanaged",
        f"治理等级：{mode}" if mapped else "治理等级：unmanaged",
        "契约来源：StateStore 最小摘要；本启动上下文不复制完整 dispatch prompt。",
        "执行要求：本次派发消息是唯一当前任务；旧 ACK、旧任务和父线程历史不得覆盖本次目标。",
        "执行要求：必须实际执行任务，不要只回复收到、明白或准备开始。",
        "终态要求：完成、阻塞、失败或需要决策时提交结构化业务结果；自然语言摘要不替代正式结果。",
        "证据要求：不得为了满足格式伪造测试、文件修改或检查证据。",
    ]
    if warning:
        lines.append(f"状态告警：{_bounded(warning)}")
    return "\n".join(lines)


def _handle_subagent_start(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    agent_id = str(payload.get("agent_id") or "")
    canonical_path_value = payload.get("canonical_task_path")
    canonical_path = (
        canonical_path_value
        if isinstance(canonical_path_value, str) and canonical_path_value.startswith("/")
        else None
    )
    event_task_name = _event_task_name(payload)
    task_id = None
    attempt = None
    binding_kind = None
    record: dict[str, Any] = {}
    warning = None
    try:
        assigned = store.update(
            session_id,
            lambda state: _assign_starting_agent(
                state,
                agent_id,
                canonical_path,
                event_task_name,
            ),
        ) if (agent_id or canonical_path) else None
        if assigned is not None:
            task_id, attempt, binding_kind = assigned
        if task_id:
            record = store.read(session_id).get("tasks", {}).get(task_id, {})
        if binding_kind == "historical":
            warning = (
                "检测到历史或非 managed Agent 映射；当前事件按 unmanaged 边界放行，"
                "不会执行旧生命周期状态机。"
            )
            task_id = None
            attempt = None
            record = {}
        warning = warning or getattr(store, "last_warning", None)
    except (OSError, RuntimeError) as exc:
        warning = f"治理状态不可读，当前子 Agent 使用通用执行边界：{exc}"
    if task_id and binding_kind == "managed" and isinstance(record.get("task_ref"), str):
        try:
            PreparedContractStore(_prepared_root_for_store(store)).delete(
                session_id,
                record["task_ref"],
            )
        except Exception as exc:
            warning = f"身份已确认，但 PreparedContract 删除失败：{exc}"
    context = _subagent_start_context(task_id, record, warning)
    return {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": context,
        }
    }


def _record_managed_result_protocol_gap(
    session_id: str,
    agent_target: str,
    task_id: str,
    attempt: int,
    store: StateStore,
    *,
    observed_at: int,
    detail: str,
) -> str:
    def mark(state: dict[str, Any]) -> str:
        mapped = _managed_target_attempt(state, agent_target)
        if mapped is None or mapped[:2] != (task_id, attempt):
            raise StateConflictError("SubagentStop 的 Agent 映射在协议纠正前发生变化")
        record = mapped[2]
        if record.get("attempt_closed") is True or record.get("execution_status") == "interrupted":
            return "ignored_terminal"
        if record.get("result_protocol_status") == "valid" and record.get("result_storage_status") == "available":
            return "already_valid"
        record["execution_status"] = "stopped"
        record["platform_observation"] = "normal"
        record["business_result"] = None
        record["acceptance_status"] = None
        record["result_storage_status"] = None
        correction_count = record.get("correction_count")
        if isinstance(correction_count, bool) or not isinstance(correction_count, int):
            raise StateValidationError("correction_count 必须是非负整数")
        if correction_count < RETRY_LIMITS["correction"]:
            record["result_protocol_status"] = "needs_correction"
            record["parent_action"] = "correct_result"
            status = "needs_correction"
        else:
            record["result_protocol_status"] = "exhausted"
            record["parent_action"] = "manual_review"
            status = "exhausted"
        record["result_protocol_error"] = _bounded(detail)
        _consume_result_correction(record)
        record["updated_at"] = observed_at
        return status

    return store.update(session_id, mark)


def _handle_subagent_stop(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    agent_id = str(payload.get("agent_id") or "")
    try:
        state = store.read(session_id)
    except (OSError, RuntimeError) as exc:
        return {"continue": True, "systemMessage": f"Subagent Governance 状态不可读，终态验收已降级放行：{exc}"}
    warning = getattr(store, "last_warning", None)
    mapping = state.get("agents", {}).get(agent_id)
    if not mapping:
        result = {"continue": True}
        if warning:
            result["systemMessage"] = str(warning)
        return result
    task_id = str(mapping.get("task_id")) if isinstance(mapping, dict) else str(mapping)
    mapped_attempt = mapping.get("attempt") if isinstance(mapping, dict) else None
    record = (
        _task_record_for_attempt(state, task_id, int(mapped_attempt))
        if isinstance(mapped_attempt, int) and not isinstance(mapped_attempt, bool)
        else state.get("tasks", {}).get(task_id)
    )
    if not isinstance(record, dict):
        def clean_stale_mapping(current: dict[str, Any]) -> bool:
            agents = current.get("agents")
            tasks = current.get("tasks")
            if not isinstance(agents, dict) or not isinstance(tasks, dict):
                raise StateValidationError(
                    "治理状态缺少失效映射清理所需的 tasks 或 agents 对象"
                )
            if agents.get(agent_id) != mapping or isinstance(tasks.get(task_id), dict):
                return False
            agents.pop(agent_id, None)
            return True

        try:
            cleaned = store.update(session_id, clean_stale_mapping)
        except (OSError, RuntimeError) as exc:
            return {
                "continue": True,
                "systemMessage": f"Subagent Governance 无法清理失效映射，终态已降级放行：{exc}",
            }
        message_text = "Subagent Governance 已清理失效映射，当前 Agent 按 unmanaged 终态放行。"
        if not cleaned:
            message_text = "Subagent Governance 检测到终态映射在检查期间发生变化，已放行并交给父任务对账。"
        return {"continue": True, "systemMessage": message_text}

    if record.get("managed") is True:
        attempt = record.get("attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int):
            return {
                "continue": True,
                "systemMessage": "Subagent Governance managed attempt 缺少有效 attempt，已保留状态并要求人工对账。",
            }
        task_result = payload.get("task_result")
        protocol_errors = validate_task_result(task_result) if isinstance(task_result, dict) else ["缺少显式 task_result 对象"]
        if not protocol_errors and isinstance(task_result, dict):
            if task_result.get("task_id") != task_id or task_result.get("attempt") != attempt:
                protocol_errors.append("task_result 的 task_id/attempt 与精确 Agent 映射不匹配")
        if protocol_errors:
            try:
                protocol_status = _record_managed_result_protocol_gap(
                    session_id,
                    agent_id,
                    task_id,
                    attempt,
                    store,
                    observed_at=_event_now(payload),
                    detail="；".join(protocol_errors),
                )
            except (OSError, RuntimeError) as exc:
                return {
                    "continue": True,
                    "systemMessage": f"Subagent Governance 无法可靠记录结果协议缺口：{exc}",
                }
            messages = {
                "needs_correction": "managed attempt 已停止但没有合法结构化结果；应使用 result_correction 补交本次结果。",
                "exhausted": "managed attempt 两次结果补交额度已耗尽，业务结果保持为空并进入人工检查。",
                "already_valid": "managed attempt 已有合法正式结果，本次无结果 Stop 按幂等事件处理。",
                "ignored_terminal": "managed attempt 已关闭或已成功中断，本次 Stop 不改写治理事实。",
            }
            result = {"continue": True, "systemMessage": messages[protocol_status]}
        else:
            try:
                submitted = submit_task_result(
                    task_result,
                    session_id,
                    agent_target=agent_id,
                    state_store=store,
                    results_root=_results_root_for_store(store),
                    now=_event_now(payload),
                )
            except ResultSubmissionError as exc:
                result = {
                    "continue": True,
                    "systemMessage": f"managed TaskResult 未被可靠接受，治理状态未伪造成功：{exc}",
                }
            else:
                result = {
                    "continue": True,
                    "systemMessage": f"managed TaskResult 正式提交状态：{submitted['status']}。",
                }
        if warning:
            result["systemMessage"] += f" {warning}"
        return result

    result = {
        "continue": True,
        "systemMessage": (
            "Subagent Governance 检测到历史或非 managed Agent 映射；"
            "当前 Stop 按 unmanaged 边界放行，不从自由文本生成正式结果，也不执行旧生命周期状态机。"
        ),
    }
    if warning:
        result["systemMessage"] += f" {warning}"
    return result


def _attempt_projection(
    task_id: str,
    attempt: int,
    record: dict[str, Any],
    *,
    current: bool,
) -> dict[str, Any]:
    projected = copy.copy(record)
    projected.pop("prior_attempts", None)
    projected["task_id"] = task_id
    projected["attempt"] = attempt
    projected["is_current_attempt"] = current
    projected["activity_at"] = _activity_timestamp(record)
    return projected


def _view_attempt_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        raise StateValidationError("治理状态缺少派生视图所需的 tasks 对象")
    records: list[dict[str, Any]] = []
    for task_id, current in tasks.items():
        if not isinstance(current, dict) or current.get("managed") is not True:
            continue
        current_attempt = current.get("attempt")
        if not isinstance(current_attempt, int) or isinstance(current_attempt, bool):
            continue
        records.append(
            _attempt_projection(str(task_id), current_attempt, current, current=True)
        )
        prior_attempts = current.get("prior_attempts")
        if isinstance(prior_attempts, dict):
            for prior in prior_attempts.values():
                prior_attempt = prior.get("attempt") if isinstance(prior, dict) else None
                if (
                    isinstance(prior, dict)
                    and isinstance(prior_attempt, int)
                    and not isinstance(prior_attempt, bool)
                ):
                    records.append(
                        _attempt_projection(
                            str(task_id), prior_attempt, prior, current=False
                        )
                    )
    return records


def _attempt_closed(state: dict[str, Any], record: dict[str, Any]) -> bool:
    if record.get("attempt_closed") is True:
        return True
    tombstones = state.get("tombstones")
    key = f"{record.get('task_id')}:{record.get('attempt')}"
    return isinstance(tombstones, dict) and isinstance(tombstones.get(key), dict)


def _managed_call_in_progress(record: dict[str, Any]) -> bool:
    spawn_call = (
        record.get("spawn_tool_use_id") is not None
        and record.get("spawn_observation") is None
    )
    pending = record.get("pending_action")
    pending_call = isinstance(pending, dict) and pending.get("phase") in {
        "prepared",
        "claimed",
    }
    lifecycle = record.get("last_lifecycle_operation")
    unresolved_lifecycle = (
        isinstance(lifecycle, dict)
        and lifecycle.get("call_observation") in {"success", "unknown"}
    )
    return spawn_call or pending_call or unresolved_lifecycle


def _managed_action_required(state: dict[str, Any], record: dict[str, Any]) -> bool:
    if _attempt_closed(state, record):
        return False
    return bool(
        record.get("parent_action") is not None
        or record.get("execution_status") == "running"
        or _managed_call_in_progress(record)
        or (
            record.get("identity_status") == "unconfirmed"
            and record.get("spawn_observation") in {"success", "unknown"}
        )
        or record.get("duplicate_execution") is True
        or record.get("duplicate_not_selected") is True
    )


def _action_priority(record: dict[str, Any]) -> int:
    parent_action = record.get("parent_action")
    priority = {
        "recover": 0,
        "reconcile": 1,
        "retry_spawn": 2,
        "resolve_duplicate": 3,
        "correct_result": 4,
        "accept_result": 5,
        "ask_user": 6,
        "manual_review": 7,
        "decide_disposition": 8,
        "business_resume": 9,
        "wait": 10,
    }
    if parent_action in priority:
        return priority[str(parent_action)]
    return 99


def _action_required_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for record in _view_attempt_records(state):
        if _managed_action_required(state, record):
            records.append(record)
    records.sort(
        key=lambda record: (
            _action_priority(record),
            -int(record.get("activity_at") or 0),
            str(record.get("task_id") or ""),
            int(record.get("attempt") or 0),
        )
    )
    return records


def _recent_activity_records(
    state: dict[str, Any], *, now: int | None = None
) -> list[dict[str, Any]]:
    current_time = _now() if now is None else now
    cutoff = current_time - int(RETENTION_SECONDS["recent_activity"])
    records = [
        record
        for record in _view_attempt_records(state)
        if int(record.get("activity_at") or 0) >= cutoff
    ]
    records.sort(
        key=lambda record: (
            -int(record.get("activity_at") or 0),
            str(record.get("task_id") or ""),
            int(record.get("attempt") or 0),
        )
    )
    return records


def _managed_stop_blocking(record: dict[str, Any]) -> bool:
    pending = record.get("pending_action")
    lifecycle = record.get("last_lifecycle_operation")
    if record.get("execution_status") == "running":
        return True
    if (
        record.get("spawn_tool_use_id") is not None
        and record.get("spawn_observation") is None
    ):
        return True
    if isinstance(pending, dict) and pending.get("phase") in {"prepared", "claimed"}:
        return True
    if (
        record.get("identity_status") == "unconfirmed"
        and record.get("spawn_observation") in {"success", "unknown"}
    ):
        return True
    if (
        isinstance(lifecycle, dict)
        and lifecycle.get("call_observation") in {"success", "unknown"}
    ):
        return True
    if record.get("spawn_observation") == "failed" and record.get("parent_action") == "retry_spawn":
        return True
    if (
        record.get("platform_observation") == "error"
        and record.get("parent_action") in {"recover", "reconcile"}
    ):
        return True
    return False


def _stop_blocking_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for record in _view_attempt_records(state):
        if _attempt_closed(state, record):
            continue
        if _managed_stop_blocking(record):
            records.append(record)
    records.sort(
        key=lambda record: (
            -int(record.get("activity_at") or 0),
            str(record.get("task_id") or ""),
            int(record.get("attempt") or 0),
        )
    )
    return records


def _validate_group_value(
    value: Any,
    *,
    expected_group_id: str | None = None,
    persisted: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GroupValidationError("group 必须是对象")
    group_id = value.get("group_id")
    if (
        not isinstance(group_id, str)
        or not group_id.strip()
        or len(group_id) > GROUP_ID_MAX_LENGTH
    ):
        raise GroupValidationError(
            f"group_id 必须是 1 至 {GROUP_ID_MAX_LENGTH} 字符的非空字符串"
        )
    group_id = group_id.strip()
    if expected_group_id is not None and group_id != expected_group_id:
        raise GroupValidationError("group_id 与 StateStore 键不一致")
    objective = value.get("objective_summary")
    if (
        not isinstance(objective, str)
        or not objective.strip()
        or len(objective) > GROUP_OBJECTIVE_MAX_LENGTH
    ):
        raise GroupValidationError(
            "objective_summary 必须是非空且长度不超过 "
            f"{GROUP_OBJECTIVE_MAX_LENGTH} 的字符串"
        )
    members = value.get("members")
    if not isinstance(members, list):
        raise GroupValidationError("members 必须是数组")
    if len(members) > GROUP_MEMBER_LIMIT:
        raise GroupValidationError(f"members 不能超过 {GROUP_MEMBER_LIMIT} 项")
    normalized_members: list[dict[str, Any]] = []
    seen: set[str] = set()
    task_id_max = int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"])
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            raise GroupValidationError(f"members[{index}] 必须是对象")
        task_id = member.get("task_id")
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or len(task_id) > task_id_max
        ):
            raise GroupValidationError(f"members[{index}].task_id 无效")
        task_id = task_id.strip()
        required = member.get("required")
        if not isinstance(required, bool):
            raise GroupValidationError(f"members[{index}].required 必须是布尔值")
        if task_id in seen:
            raise GroupValidationError(f"group 中存在重复 task_id：{task_id}")
        seen.add(task_id)
        normalized_members.append({"task_id": task_id, "required": required})
    normalized = {
        "group_id": group_id,
        "objective_summary": objective.strip(),
        "members": normalized_members,
    }
    if persisted:
        for field_name in ("created_at", "updated_at"):
            timestamp = value.get(field_name)
            if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
                raise GroupValidationError(f"group.{field_name} 必须是非负整数")
            normalized[field_name] = timestamp
    return normalized


def upsert_group(
    value: Any,
    session_id: str,
    *,
    state_store: StateStore | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    normalized = _validate_group_value(value)
    store = state_store or StateStore()
    observed_at = _now() if now is None else now

    def upsert(state: dict[str, Any]) -> dict[str, Any]:
        tasks = state.get("tasks")
        if not isinstance(tasks, dict):
            raise GroupValidationError("治理状态缺少 group 引用所需的 tasks 对象")
        missing = [
            member["task_id"]
            for member in normalized["members"]
            if not isinstance(tasks.get(member["task_id"]), dict)
        ]
        if missing:
            raise GroupValidationError(f"group 引用的 task 不存在：{', '.join(missing)}")
        groups = state.get("groups")
        if groups is None:
            groups = {}
            state["groups"] = groups
        elif not isinstance(groups, dict):
            raise GroupValidationError("治理状态 groups 字段必须是对象")
        existing = groups.get(normalized["group_id"])
        if existing is not None and not isinstance(existing, dict):
            raise GroupValidationError("已有 group 记录必须是对象")
        created_at = observed_at
        status = "created"
        if isinstance(existing, dict):
            validated_existing = _validate_group_value(
                existing,
                expected_group_id=normalized["group_id"],
                persisted=True,
            )
            created_at = int(validated_existing["created_at"])
            status = "updated"
        record = {
            **normalized,
            "created_at": created_at,
            "updated_at": observed_at,
        }
        groups[normalized["group_id"]] = record
        return {
            "status": status,
            "group_id": normalized["group_id"],
            "created_at": created_at,
            "updated_at": observed_at,
        }

    return store.update(session_id, upsert, required_fields=("tasks", "agents"))


def _diagnostic_issue(code: str, message: str, **context: Any) -> dict[str, Any]:
    allowed_context = {}
    for key in (
        "session_id",
        "path",
        "field",
        "task_id",
        "attempt",
        "group_id",
        "fact",
    ):
        value = context.get(key)
        if value is None:
            continue
        if isinstance(value, (str, int, bool)):
            allowed_context[key] = value if not isinstance(value, str) else value[:600]
    return {
        "code": code,
        "message": str(message)[:600],
        "context": allowed_context,
    }


def _diagnostic_issue_sort_key(issue: dict[str, Any]) -> tuple[Any, ...]:
    context = issue.get("context") if isinstance(issue.get("context"), dict) else {}
    return (
        str(issue.get("code") or ""),
        str(context.get("session_id") or ""),
        str(context.get("task_id") or ""),
        int(context.get("attempt") or 0),
        str(context.get("group_id") or ""),
        str(context.get("field") or ""),
        str(context.get("path") or ""),
    )


def _inspect_formal_result_read_only(
    record: dict[str, Any],
    task_id: str,
    attempt: int,
    results_root: Path,
    *,
    session_id: str | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], bool]:
    reference = record.get("result_reference")
    storage_status = record.get("result_storage_status")
    if storage_status != "available" and not (
        isinstance(reference, str) and reference.strip()
    ):
        return None, [], False
    issues: list[dict[str, Any]] = []
    incomplete = False
    path = result_file_path(results_root, task_id, attempt)
    metadata = {
        "reference": reference if isinstance(reference, str) else None,
        "readable": False,
        "usable": False,
        "sha256_matches": None,
        "business_result": None,
        "result_chars": None,
        "evidence_count": None,
        "remaining_count": None,
    }
    try:
        results_metadata = results_root.lstat()
    except FileNotFoundError:
        results_metadata = None
    if results_metadata is not None and (
        stat.S_ISLNK(results_metadata.st_mode)
        or not stat.S_ISDIR(results_metadata.st_mode)
        or not _owned_by_current_user(results_metadata)
    ):
        issues.append(
            _diagnostic_issue(
                "result_invalid",
                "正式结果目录不是当前用户拥有的普通目录",
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                path=str(results_root),
            )
        )
        return metadata, issues, True
    if not isinstance(reference, str) or not reference.strip():
        issues.append(
            _diagnostic_issue(
                "current_required_field_missing",
                "available 正式结果缺少 result_reference",
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                field="result_reference",
            )
        )
        incomplete = True
    elif reference != path.name:
        issues.append(
            _diagnostic_issue(
                "result_invalid",
                "result_reference 与确定性结果地址不一致",
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                field="result_reference",
            )
        )
        incomplete = True
    try:
        path.lstat()
    except FileNotFoundError:
        issues.append(
            _diagnostic_issue(
                "result_missing",
                "精确正式结果文件不存在",
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                path=str(path),
            )
        )
        return metadata, issues, True
    try:
        value, raw, digest = _read_result_path(path, task_id, attempt)
    except ResultStorageError as exc:
        issues.append(
            _diagnostic_issue(
                "result_invalid",
                f"精确正式结果文件无法机械复验：{exc}",
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                path=str(path),
            )
        )
        return metadata, issues, True
    metadata["readable"] = True
    metadata["business_result"] = value.get("business_result")
    metadata["result_chars"] = len(str(value.get("result") or ""))
    metadata["evidence_count"] = len(value.get("evidence") or [])
    metadata["remaining_count"] = len(value.get("remaining") or [])
    stored_digest = record.get("result_sha256")
    if not isinstance(stored_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", stored_digest):
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "available 正式结果的 result_sha256 缺失或非法",
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                field="result_sha256",
            )
        )
        incomplete = True
    else:
        metadata["sha256_matches"] = stored_digest == digest
        if stored_digest != digest:
            issues.append(
                _diagnostic_issue(
                    "result_invalid",
                    "StateStore 的 result_sha256 与正式结果文件不一致",
                    session_id=session_id,
                    task_id=task_id,
                    attempt=attempt,
                    field="result_sha256",
                )
            )
            incomplete = True
    if record.get("business_result") not in {None, value.get("business_result")}:
        issues.append(
            _diagnostic_issue(
                "result_invalid",
                "StateStore business_result 与正式结果文件不一致",
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                field="business_result",
            )
        )
        incomplete = True
    metadata["usable"] = bool(
        metadata["readable"]
        and reference == path.name
        and metadata["sha256_matches"] is True
        and storage_status == "available"
        and record.get("result_protocol_status") == "valid"
    )
    return metadata, issues, incomplete


def _attempt_has_reasoned_close(
    state: dict[str, Any], task_id: str, attempt: int, record: dict[str, Any]
) -> bool:
    if not _attempt_closed(
        state,
        {"task_id": task_id, "attempt": attempt, **record},
    ):
        return False
    tombstones = state.get("tombstones")
    tombstone = (
        tombstones.get(f"{task_id}:{attempt}")
        if isinstance(tombstones, dict)
        else None
    )
    reasons = (
        record.get("attempt_close_reason"),
        record.get("parent_disposition_reason"),
        tombstone.get("close_reason") if isinstance(tombstone, dict) else None,
    )
    return any(isinstance(reason, str) and reason.strip() for reason in reasons)


def _task_disposition_complete(state: dict[str, Any], task_id: str) -> bool:
    records = _task_attempt_records(state, task_id)
    return bool(records) and all(
        _attempt_has_reasoned_close(state, task_id, attempt, record)
        for attempt, record in records
    )


def _derive_group_snapshot(
    state: dict[str, Any],
    group: dict[str, Any],
    *,
    results_root: Path,
    session_id: str | None = None,
    result_cache: dict[tuple[str, int], dict[str, Any] | None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    validated = _validate_group_value(
        group,
        expected_group_id=str(group.get("group_id") or ""),
        persisted=True,
    )
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        raise GroupValidationError("治理状态缺少 group 派生所需的 tasks 对象")
    action_task_ids = {
        str(record.get("task_id")) for record in _action_required_records(state)
    }
    issues: list[dict[str, Any]] = []
    incomplete = False
    members = []
    for member in validated["members"]:
        task_id = member["task_id"]
        current = tasks.get(task_id)
        exists = isinstance(current, dict)
        current_attempt = current.get("attempt") if exists else None
        formal_result = None
        if exists and isinstance(current_attempt, int) and not isinstance(current_attempt, bool):
            cache_key = (task_id, current_attempt)
            if result_cache is not None and cache_key in result_cache:
                formal_result = result_cache[cache_key]
            else:
                formal_result, result_issues, result_incomplete = (
                    _inspect_formal_result_read_only(
                        current,
                        task_id,
                        current_attempt,
                        results_root,
                        session_id=session_id,
                    )
                )
                issues.extend(result_issues)
                incomplete = incomplete or result_incomplete
                if result_cache is not None:
                    result_cache[cache_key] = formal_result
        disposition_complete = exists and _task_disposition_complete(state, task_id)
        summary_material_ready = bool(
            (isinstance(formal_result, dict) and formal_result.get("usable") is True)
            or disposition_complete
        )
        individual_action_required = bool(
            task_id in action_task_ids or (exists and not disposition_complete)
        )
        if not exists:
            issues.append(
                _diagnostic_issue(
                    "current_required_field_invalid",
                    "group 引用的 task 在当前 Session 中不存在",
                    session_id=session_id,
                    task_id=task_id,
                    group_id=validated["group_id"],
                    field="members.task_id",
                )
            )
            incomplete = True
            individual_action_required = True
        members.append(
            {
                "task_id": task_id,
                "required": member["required"],
                "exists": exists,
                "current_attempt": current_attempt if isinstance(current_attempt, int) else None,
                "individual_action_required": individual_action_required,
                "disposition_complete": bool(disposition_complete),
                "summary_material_ready": summary_material_ready,
                "formal_result": formal_result,
            }
        )
    required_members = [member for member in members if member["required"]]
    snapshot = {
        "group_id": validated["group_id"],
        "objective_summary": validated["objective_summary"],
        "members": members,
        "created_at": validated["created_at"],
        "updated_at": validated["updated_at"],
        "summary_ready": bool(required_members)
        and all(member["summary_material_ready"] for member in required_members),
        "group_action_required": bool(required_members)
        and any(not member["disposition_complete"] for member in required_members),
    }
    return snapshot, issues, incomplete


def read_group(
    session_id: str,
    group_id: str,
    *,
    state_store: StateStore | None = None,
    results_root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(group_id, str) or not group_id.strip():
        raise GroupValidationError("group_id 必须是非空字符串")
    store = state_store or StateStore()
    state = store.read(session_id)
    groups = state.get("groups")
    if not isinstance(groups, dict) or not isinstance(groups.get(group_id), dict):
        raise GroupNotFoundError(f"group 不存在：{group_id}")
    root = Path(results_root) if results_root is not None else _results_root_for_store(store)
    snapshot, _issues, _incomplete = _derive_group_snapshot(
        state,
        groups[group_id],
        results_root=root,
        session_id=session_id,
    )
    return snapshot


def _session_next_action(record: dict[str, Any]) -> str:
    parent_action = record.get("parent_action")
    if parent_action:
        return str(parent_action)
    if record.get("managed") is True and record.get("spawn_observation") is None:
        return "派发调用仍在对账期；不要重复派发"
    return "等待原 Agent并按规则巡检"


def _session_summary_line(record: dict[str, Any]) -> str:
    task_id = _bounded(record.get("task_id"), "unknown")[:SESSION_SUMMARY_FIELD_LIMIT]
    attempt = record.get("attempt")
    mode = _bounded(record.get("resolved_mode"), "unknown")[:SESSION_SUMMARY_FIELD_LIMIT]
    status = _bounded(record.get("execution_status"), "unknown")[:SESSION_SUMMARY_FIELD_LIMIT]
    summary = record.get("contract_summary") if isinstance(record.get("contract_summary"), dict) else {}
    objective = _bounded(summary.get("objective") or record.get("task_name"), "未命名任务")[:SESSION_SUMMARY_FIELD_LIMIT]
    completion_values = summary.get("completion_conditions")
    completion_text = "；".join(completion_values) if isinstance(completion_values, list) else None
    completion = _bounded(completion_text, "未记录")[:SESSION_SUMMARY_FIELD_LIMIT]
    target = _bounded(record.get("canonical_task_path") or record.get("agent_id"), "unmapped")[:SESSION_SUMMARY_FIELD_LIMIT]
    next_action = _session_next_action(record)
    parent_action = _bounded(record.get("parent_action"), "null")[:SESSION_SUMMARY_FIELD_LIMIT]
    mechanical = "/".join(
        str(value)
        for value in (
            record.get("execution_status"),
            record.get("identity_status"),
            record.get("platform_observation"),
            record.get("business_result"),
            record.get("result_protocol_status"),
            record.get("acceptance_status"),
        )
        if value is not None
    ) or status
    return (
        f"- 任务 ID：{task_id}｜attempt：{attempt}｜治理等级：{mode}｜状态：{status}｜"
        f"机械状态：{mechanical[:SESSION_SUMMARY_FIELD_LIMIT]}｜parent_action：{parent_action}｜"
        f"目标：{objective}｜完成条件：{completion}｜恢复对象：{target}｜下一步：{next_action}"
    )


def _session_start_context(
    action_required: list[dict[str, Any]],
    recent_activity: list[dict[str, Any]],
) -> str:
    header = "Subagent Governance 会话恢复摘要："
    footer = (
        "不要因 compact/resume 重复创建已有 Agent；使用精确恢复对象继续等待、对账或恢复。\n"
        "不要因上下文压缩重复创建这些子 Agent；按状态等待、恢复原 Agent或继续已有用户决策。"
    )

    required_keys = {
        (str(record.get("task_id")), int(record.get("attempt") or 0))
        for record in action_required
    }
    recent_only = [
        record
        for record in recent_activity
        if (str(record.get("task_id")), int(record.get("attempt") or 0)) not in required_keys
    ]

    def render(required_lines: list[str], recent_lines: list[str]) -> str:
        lines = [header]
        if action_required:
            lines.append("【需要处理】")
            lines.extend(required_lines)
            omitted_required = len(action_required) - len(required_lines)
            if omitted_required > 0:
                lines.append(f"还有 {omitted_required} 个待处理任务未展开。")
        if recent_only:
            lines.append("【最近活动】")
            lines.extend(recent_lines)
            omitted_recent = len(recent_only) - len(recent_lines)
            if omitted_recent > 0:
                lines.append(f"还有 {omitted_recent} 个最近活动未展开。")
        lines.append(footer)
        return "\n".join(lines)

    required_lines: list[str] = []
    recent_lines: list[str] = []
    for record in action_required:
        if len(required_lines) + len(recent_lines) >= SESSION_SUMMARY_RECORD_LIMIT:
            break
        candidate = [*required_lines, _session_summary_line(record)]
        if len(render(candidate, recent_lines)) > SESSION_SUMMARY_CONTEXT_LIMIT:
            break
        required_lines.append(candidate[-1])
    for record in recent_only:
        if len(required_lines) + len(recent_lines) >= SESSION_SUMMARY_RECORD_LIMIT:
            break
        candidate = [*recent_lines, _session_summary_line(record)]
        if len(render(required_lines, candidate)) > SESSION_SUMMARY_CONTEXT_LIMIT:
            break
        recent_lines.append(candidate[-1])
    context = render(required_lines, recent_lines)
    while len(context) > SESSION_SUMMARY_CONTEXT_LIMIT and recent_lines:
        recent_lines.pop()
        context = render(required_lines, recent_lines)
    while len(context) > SESSION_SUMMARY_CONTEXT_LIMIT and required_lines:
        required_lines.pop()
        context = render(required_lines, recent_lines)
    return context


def _handle_stop(
    payload: dict[str, Any],
    store: StateStore,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    state = None
    errors: list[str] = []
    for read_attempt in range(STOP_READ_ATTEMPTS):
        try:
            state = store.read(session_id)
            break
        except (OSError, RuntimeError) as exc:
            errors.append(_bounded(exc, "unknown read error"))
            if read_attempt < STOP_READ_ATTEMPTS - 1:
                sleeper(STOP_READ_RETRY_DELAY_SECONDS)
    if state is None:
        reason = (
            "Subagent Governance 连续三次无法读取 StateStore，无法确认是否仍有运行中或调用对账任务；"
            "需要用户决策：选择强制结束，或先诊断、修复并恢复治理状态。"
            f"最后错误：{errors[-1] if errors else 'unknown'}"
        )
        if payload.get("stop_hook_active"):
            return {"continue": True, "systemMessage": reason}
        return {"decision": "block", "reason": reason}
    blocking = _stop_blocking_records(state)
    warning = getattr(store, "last_warning", None)
    if not blocking:
        result = {"continue": True}
        if warning:
            result["systemMessage"] = str(warning)
        return result
    summary = "、".join(
        f"{record.get('task_id')}#{record.get('attempt')}"
        f"({record.get('execution_status') or record.get('status')})"
        for record in blocking[:6]
    )
    omitted = len(blocking) - 6
    if omitted > 0:
        summary += f"，另有 {omitted} 个"
    reason = f"仍有运行中或待恢复的治理子任务：{summary}。等待现有子 Agent 或处理其协议状态，不要重复派发。"
    if payload.get("stop_hook_active"):
        return {"continue": True, "systemMessage": reason}
    return {"decision": "block", "reason": reason}


def _handle_session_start(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    try:
        if callable(getattr(store, "update", None)):
            reconcile_prepared_dispatches(
                session_id,
                state_store=store,
                prepared_store=PreparedContractStore(_prepared_root_for_store(store)),
            )
            reconcile_pending_actions(session_id, state_store=store)
        if callable(getattr(store, "cleanup_expired_tombstones", None)):
            store.cleanup_expired_tombstones(
                session_id,
                result_cleanup=lambda task_id, attempt: _cleanup_task_result_file(
                    _results_root_for_store(store), task_id, attempt
                ),
            )
        state = store.read(session_id)
        action_required = _action_required_records(state)
        recent_activity = _recent_activity_records(state)
    except Exception as exc:
        return {
            "continue": True,
            "systemMessage": (
                "Subagent Governance SessionStart degraded：状态恢复链不可用，无法确认是否存在待处理任务；"
                f"请先诊断或恢复 StateStore。错误：{_bounded(exc)}"
            ),
        }
    warning = getattr(store, "last_warning", None)
    if not action_required and not recent_activity:
        result = {"continue": True}
        if warning:
            result["systemMessage"] = str(warning)
        return result
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": _session_start_context(
                action_required,
                recent_activity,
            ),
        }
    }


def _handle_session_end(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    preserved: list[dict[str, Any]] = []
    retained_tombstones = 0

    def can_delete(state: dict[str, Any]) -> bool:
        nonlocal preserved, retained_tombstones
        preserved = _action_required_records(state)
        tombstones = state.get("tombstones")
        retained_tombstones = len(tombstones) if isinstance(tombstones, dict) else 0
        return not preserved and retained_tombstones == 0

    try:
        if callable(getattr(store, "update", None)):
            reconcile_prepared_dispatches(
                session_id,
                state_store=store,
                prepared_store=PreparedContractStore(_prepared_root_for_store(store)),
            )
            reconcile_pending_actions(session_id, state_store=store)
        if callable(getattr(store, "cleanup_expired_tombstones", None)):
            store.cleanup_expired_tombstones(
                session_id,
                result_cleanup=lambda task_id, attempt: _cleanup_task_result_file(
                    _results_root_for_store(store), task_id, attempt
                ),
            )
        deleted = store.delete_if(session_id, can_delete)
    except Exception as exc:
        return {"continue": True, "systemMessage": f"Subagent Governance 会话状态清理失败：{exc}"}
    warning = getattr(store, "last_warning", None)
    if not deleted:
        summary = "、".join(
            f"{_bounded(record.get('task_id'), 'unknown')[:SESSION_SUMMARY_FIELD_LIMIT]}"
            f"({_bounded(record.get('execution_status'), 'unknown')[:SESSION_SUMMARY_FIELD_LIMIT]})"
            for record in preserved[:6]
        )
        omitted = len(preserved) - 6
        if omitted > 0:
            summary += f"，另有 {omitted} 个"
        if retained_tombstones:
            tombstone_summary = f"仍有 {retained_tombstones} 个 tombstone 处于7天保留期"
            summary = f"{summary}；{tombstone_summary}" if summary else tombstone_summary
        message = (
            f"Subagent Governance 检测到仍需恢复或决策的治理任务，已保留治理状态：{summary}。"
            "SessionEnd 不会终止子 Agent；恢复同一会话后按 SessionStart 摘要继续处理。"
        )
        if warning:
            message += f" {warning}"
        return {"continue": True, "systemMessage": message}
    if warning:
        return {"continue": True, "systemMessage": str(warning)}
    return {"continue": True}


def handle(payload: dict[str, Any], store: StateStore | None = None) -> dict[str, Any] | None:
    if store is not None:
        active_store = store
    else:
        try:
            active_store = StateStore()
        except (OSError, RuntimeError) as exc:
            active_store = UnavailableStateStore(exc)
    event = str(payload.get("hook_event_name") or "")
    if event == "PreToolUse":
        kind = _tool_kind(str(payload.get("tool_name") or ""))
        if kind == "spawn":
            return _handle_spawn(payload, active_store)
        if kind in {"communication", "followup"}:
            return _handle_communication(payload, active_store)
        if kind == "interrupt":
            return _handle_interrupt_pre(payload, active_store)
        return None
    if event == "PostToolUse":
        return _handle_post_tool(payload, active_store)
    if event == "SubagentStart":
        return _handle_subagent_start(payload, active_store)
    if event == "SubagentStop":
        return _handle_subagent_stop(payload, active_store)
    if event == "Stop":
        return _handle_stop(payload, active_store)
    if event == "SessionStart":
        return _handle_session_start(payload, active_store)
    if event == "SessionEnd":
        return _handle_session_end(payload, active_store)
    return None


def _diagnostic_absolute_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _diagnostic_base_document(
    root: Path,
    session_id: str | None,
) -> dict[str, Any]:
    return {
        "data_root": str(_diagnostic_absolute_path(root)),
        "data_root_exists": bool(root.exists() or root.is_symlink()),
        "scope": "single_session" if session_id is not None else "all_sessions",
        "requested_session": session_id,
        "scan": {
            "requested": 0,
            "checked": 0,
            "succeeded": 0,
            "failed": 0,
            "omitted": 0,
            "complete": True,
        },
        "sessions": [],
        "issues": [],
        "boundaries": {
            "transport_opaque": True,
            "provider_status": "not_checked",
            "hook_trust": "not_checked",
            "repairs_state": False,
            "writes_files": False,
        },
    }


def _read_session_file_read_only(
    path: Path,
    *,
    requested_session: str | None = None,
) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise DiagnosticReadError(
            "session_missing",
            "请求的 Session 状态文件不存在",
            context={"path": str(path)},
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise DiagnosticReadError(
            "session_symlink",
            "Session 状态文件是符号链接",
            context={"path": str(path)},
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise DiagnosticReadError(
            "session_not_regular",
            "Session 状态目标不是普通文件",
            context={"path": str(path)},
        )
    if not _owned_by_current_user(metadata):
        raise DiagnosticReadError(
            "session_owner_mismatch",
            "Session 状态文件不属于当前用户",
            context={"path": str(path)},
        )
    if not _private_permissions_safe(metadata):
        raise DiagnosticReadError(
            "session_permissions_unsafe",
            "Session 状态文件权限向 group/other 开放",
            context={"path": str(path)},
        )
    if metadata.st_size > MAX_STATE_BYTES:
        raise DiagnosticReadError(
            "session_oversized",
            f"Session 状态文件超过 {MAX_STATE_BYTES} 字节上限",
            context={"path": str(path)},
        )
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as state_file:
            opened = os.fstat(state_file.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise DiagnosticReadError(
                    "session_not_regular",
                    "Session 状态文件打开后不是普通文件",
                    context={"path": str(path)},
                )
            if not _owned_by_current_user(opened):
                raise DiagnosticReadError(
                    "session_owner_mismatch",
                    "Session 状态文件打开后所有者异常",
                    context={"path": str(path)},
                )
            raw = state_file.read(MAX_STATE_BYTES + 1)
    except DiagnosticReadError:
        raise
    except OSError as exc:
        raise DiagnosticReadError(
            "session_unreadable",
            "Session 状态文件无法安全读取",
            context={"path": str(path)},
        ) from exc
    if len(raw) > MAX_STATE_BYTES:
        raise DiagnosticReadError(
            "session_oversized",
            f"Session 状态文件超过 {MAX_STATE_BYTES} 字节上限",
            context={"path": str(path)},
        )
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiagnosticReadError(
            "session_non_utf8",
            "Session 状态文件不是有效 UTF-8",
            context={"path": str(path)},
        ) from exc
    try:
        value = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise DiagnosticReadError(
            "session_json_invalid",
            "Session 状态文件不是有效 JSON",
            context={"path": str(path)},
        ) from exc
    if not isinstance(value, dict):
        raise DiagnosticReadError(
            "session_root_invalid",
            "Session 状态文件根节点不是对象",
            context={"path": str(path)},
        )
    stored_session = value.get("session_id")
    if not isinstance(stored_session, str) or not stored_session.strip():
        raise DiagnosticReadError(
            "session_root_invalid",
            "Session 状态缺少有效 session_id",
            context={"path": str(path), "field": "session_id"},
        )
    if requested_session is not None and stored_session != requested_session:
        raise DiagnosticReadError(
            "session_root_invalid",
            "Session 状态中的 session_id 与请求不匹配",
            context={"path": str(path), "session_id": stored_session},
        )
    return value


def _diagnostic_validate_attempt(
    record: dict[str, Any],
    *,
    session_id: str,
    task_id: str,
    attempt: int,
) -> tuple[list[dict[str, Any]], bool, bool]:
    if record.get("managed") is not True:
        return [], False, True
    issues: list[dict[str, Any]] = []
    incomplete = False
    identity_valid = True
    try:
        _validate_task_identity(task_id, attempt)
    except ResultSubmissionError:
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "managed attempt 的 task_id/attempt 非法",
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                field="task_id/attempt",
            )
        )
        incomplete = True
        identity_valid = False
    enum_fields: dict[str, tuple[frozenset[str], bool]] = {
        "execution_status": (EXECUTION_STATUSES, False),
        "spawn_observation": (SPAWN_OBSERVATIONS, True),
        "identity_status": (IDENTITY_STATUSES, False),
        "platform_observation": (PLATFORM_OBSERVATIONS, True),
        "business_result": (BUSINESS_RESULTS, True),
        "acceptance_status": (ACCEPTANCE_STATUSES, True),
        "result_protocol_status": (RESULT_PROTOCOL_STATUSES, True),
        "result_storage_status": (RESULT_STORAGE_STATUSES, True),
        "recovery_status": (RECOVERY_STATUSES, True),
        "parent_action": (PARENT_ACTIONS, True),
    }
    for field_name, (allowed, nullable) in enum_fields.items():
        if field_name not in record:
            issues.append(
                _diagnostic_issue(
                    "current_required_field_missing",
                    f"managed attempt 缺少 {field_name}",
                    session_id=session_id,
                    task_id=task_id,
                    attempt=attempt,
                    field=field_name,
                )
            )
            incomplete = True
            continue
        value = record.get(field_name)
        if value is None and nullable:
            continue
        if value not in allowed:
            issues.append(
                _diagnostic_issue(
                    "current_required_field_invalid",
                    f"managed attempt 的 {field_name} 非法",
                    session_id=session_id,
                    task_id=task_id,
                    attempt=attempt,
                    field=field_name,
                )
            )
            incomplete = True
    if "result_conflict" not in record:
        issues.append(
            _diagnostic_issue(
                "current_required_field_missing",
                "managed attempt 缺少 result_conflict",
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                field="result_conflict",
            )
        )
        incomplete = True
    elif not isinstance(record.get("result_conflict"), bool):
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "managed attempt 的 result_conflict 必须是布尔值",
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                field="result_conflict",
            )
        )
        incomplete = True
    for field_name in ("spawn_retry_count", "recovery_count", "correction_count"):
        value = record.get(field_name)
        if field_name not in record:
            code = "current_required_field_missing"
        elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
            code = "current_required_field_invalid"
        else:
            continue
        issues.append(
            _diagnostic_issue(
                code,
                f"managed attempt 的 {field_name} 缺失或非法",
                session_id=session_id,
                task_id=task_id,
                attempt=attempt,
                field=field_name,
            )
        )
        incomplete = True
    return issues, incomplete, identity_valid


def _diagnostic_skipped_attempt_issues(
    tasks: dict[str, Any],
    *,
    session_id: str,
) -> tuple[list[dict[str, Any]], bool]:
    issues: list[dict[str, Any]] = []
    attempt_minimum = int(SEMANTIC_DEFINITIONS["attempt"]["minimum"])
    task_id_maximum = int(SEMANTIC_DEFINITIONS["task_id"]["maxLength"])
    for task_key, current in sorted(tasks.items(), key=lambda item: str(item[0])):
        task_id = str(task_key)
        if not isinstance(current, dict):
            issues.append(
                _diagnostic_issue(
                    "current_required_field_invalid",
                    "Session task 记录必须是对象",
                    session_id=session_id,
                    task_id=task_id,
                    field="tasks",
                )
            )
            continue
        if current.get("managed") is not True:
            issues.append(
                _diagnostic_issue(
                    (
                        "current_required_field_missing"
                        if "managed" not in current
                        else "current_required_field_invalid"
                    ),
                    "task 记录不是当前 managed attempt 结构；旧记录不会进入执行状态机",
                    session_id=session_id,
                    task_id=task_id,
                    field="managed",
                )
            )
            continue
        stored_task_id = current.get("task_id")
        if "task_id" not in current:
            task_id_code = "current_required_field_missing"
        elif (
            not isinstance(stored_task_id, str)
            or not stored_task_id.strip()
            or len(stored_task_id) > task_id_maximum
            or stored_task_id != task_id
        ):
            task_id_code = "current_required_field_invalid"
        else:
            task_id_code = None
        if task_id_code is not None:
            issues.append(
                _diagnostic_issue(
                    task_id_code,
                    "managed current attempt 的 task_id 缺失、非法或与 tasks 键不一致",
                    session_id=session_id,
                    task_id=task_id,
                    field="task_id",
                )
            )
        current_attempt = current.get("attempt")
        if "attempt" not in current:
            attempt_code = "current_required_field_missing"
        elif (
            isinstance(current_attempt, bool)
            or not isinstance(current_attempt, int)
            or current_attempt < attempt_minimum
        ):
            attempt_code = "current_required_field_invalid"
        else:
            attempt_code = None
        if attempt_code is not None:
            issues.append(
                _diagnostic_issue(
                    attempt_code,
                    "managed current attempt 的 attempt 缺失或非法",
                    session_id=session_id,
                    task_id=task_id,
                    field="attempt",
                )
            )
        prior_attempts = current.get("prior_attempts")
        if prior_attempts is None:
            continue
        if not isinstance(prior_attempts, dict):
            issues.append(
                _diagnostic_issue(
                    "current_required_field_invalid",
                    "managed task 的 prior_attempts 必须是对象",
                    session_id=session_id,
                    task_id=task_id,
                    field="prior_attempts",
                )
            )
            continue
        for prior_key, prior in sorted(
            prior_attempts.items(), key=lambda item: str(item[0])
        ):
            if not isinstance(prior, dict):
                issues.append(
                    _diagnostic_issue(
                        "current_required_field_invalid",
                        "managed prior attempt 记录必须是对象",
                        session_id=session_id,
                        task_id=task_id,
                        field=f"prior_attempts.{prior_key}",
                    )
                )
                continue
            prior_attempt = prior.get("attempt")
            if "attempt" not in prior:
                prior_code = "current_required_field_missing"
            elif (
                isinstance(prior_attempt, bool)
                or not isinstance(prior_attempt, int)
                or prior_attempt < attempt_minimum
            ):
                prior_code = "current_required_field_invalid"
            else:
                prior_code = None
            if prior_code is not None:
                issues.append(
                    _diagnostic_issue(
                        prior_code,
                        "managed prior attempt 的 attempt 缺失或非法",
                        session_id=session_id,
                        task_id=task_id,
                        field=f"prior_attempts.{prior_key}.attempt",
                    )
                )
    return issues, bool(issues)


def _diagnostic_attempt_snapshot(
    state: dict[str, Any],
    record: dict[str, Any],
    *,
    now: int,
    action_keys: set[tuple[str, int]],
    recent_keys: set[tuple[str, int]],
    formal_result: dict[str, Any] | None,
) -> dict[str, Any]:
    task_id = str(record.get("task_id") or "")
    attempt = int(record.get("attempt") or 0)
    summary = record.get("contract_summary")
    summary = summary if isinstance(summary, dict) else {}
    completion = summary.get("completion_conditions")
    completion = [
        str(value)[:600]
        for value in completion
        if isinstance(value, str) and value.strip()
    ] if isinstance(completion, list) else []
    timestamp_fields = (
        "created_at",
        "updated_at",
        "platform_checked_at",
        "spawn_claimed_at",
        "spawn_post_observed_at",
        "result_stored_at",
        "attempt_closed_at",
    )
    timestamps = {
        field_name: record[field_name]
        for field_name in timestamp_fields
        if isinstance(record.get(field_name), int)
        and not isinstance(record.get(field_name), bool)
    }
    key = (task_id, attempt)
    activity_at = int(record.get("activity_at") or 0)
    return {
        "task_id": task_id,
        "attempt": attempt,
        "is_current_attempt": bool(record.get("is_current_attempt")),
        "agent_id": record.get("agent_id") if isinstance(record.get("agent_id"), str) else None,
        "canonical_task_path": (
            record.get("canonical_task_path")
            if isinstance(record.get("canonical_task_path"), str)
            else None
        ),
        "execution_status": record.get("execution_status"),
        "spawn_observation": record.get("spawn_observation"),
        "identity_status": record.get("identity_status"),
        "platform_observation": record.get("platform_observation"),
        "business_result": record.get("business_result"),
        "acceptance_status": record.get("acceptance_status"),
        "result_protocol_status": record.get("result_protocol_status"),
        "result_storage_status": record.get("result_storage_status"),
        "result_conflict": record.get("result_conflict") if isinstance(record.get("result_conflict"), bool) else None,
        "recovery_status": record.get("recovery_status"),
        "parent_action": record.get("parent_action"),
        "spawn_retry_count": record.get("spawn_retry_count") if isinstance(record.get("spawn_retry_count"), int) else None,
        "recovery_count": record.get("recovery_count") if isinstance(record.get("recovery_count"), int) else None,
        "correction_count": record.get("correction_count") if isinstance(record.get("correction_count"), int) else None,
        "activity_at": activity_at or None,
        "timestamps": timestamps,
        "contract_summary": {
            "resolved_mode": record.get("resolved_mode") if isinstance(record.get("resolved_mode"), str) else None,
            "objective": str(summary.get("objective") or "")[:600] or None,
            "completion_conditions": completion[:3],
            "omitted_completion_conditions": max(0, len(completion) - 3),
        },
        "stale": activity_at < now - int(RETENTION_SECONDS["recent_activity"]),
        "action_required": key in action_keys,
        "recent_activity": key in recent_keys,
        "closed": _attempt_closed(state, record),
        "formal_result": formal_result,
    }


def _diagnostic_session_snapshot(
    state: dict[str, Any],
    *,
    path: Path,
    results_root: Path,
    now: int,
) -> tuple[dict[str, Any], bool, int]:
    session_id = str(state.get("session_id") or "")
    issues: list[dict[str, Any]] = []
    incomplete = False
    omitted = 0
    for field_name in ("tasks", "agents", "health", "tombstones", "updated_at"):
        if field_name not in state:
            issues.append(
                _diagnostic_issue(
                    "current_required_field_missing",
                    f"Session snapshot 缺少 {field_name}",
                    session_id=session_id,
                    path=str(path),
                    field=field_name,
                )
            )
            incomplete = True
    tasks = state.get("tasks")
    agents = state.get("agents")
    health = state.get("health")
    tombstones = state.get("tombstones")
    if not isinstance(tasks, dict):
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "Session tasks 必须是对象",
                session_id=session_id,
                field="tasks",
            )
        )
        tasks = {}
        incomplete = True
    if not isinstance(agents, dict):
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "Session agents 必须是对象",
                session_id=session_id,
                field="agents",
            )
        )
        incomplete = True
    health_status = "unknown"
    if isinstance(health, dict) and health.get("status") in {"ok", "degraded", "unavailable"}:
        health_status = str(health["status"])
    else:
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "Session health.status 缺失或非法",
                session_id=session_id,
                field="health.status",
            )
        )
        incomplete = True
    if not isinstance(tombstones, dict):
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "Session tombstones 必须是对象",
                session_id=session_id,
                field="tombstones",
            )
        )
        tombstones = {}
        incomplete = True
    updated_at = state.get("updated_at")
    if isinstance(updated_at, bool) or not isinstance(updated_at, int):
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "Session updated_at 必须是整数",
                session_id=session_id,
                field="updated_at",
            )
        )
        updated_at = None
        incomplete = True

    normalized_state = dict(state)
    normalized_state["tasks"] = tasks
    normalized_state["agents"] = agents if isinstance(agents, dict) else {}
    normalized_state["tombstones"] = tombstones
    skipped_attempt_issues, skipped_attempt_incomplete = (
        _diagnostic_skipped_attempt_issues(tasks, session_id=session_id)
    )
    issues.extend(skipped_attempt_issues)
    incomplete = incomplete or skipped_attempt_incomplete
    all_attempts = _view_attempt_records(normalized_state)
    all_attempts.sort(
        key=lambda record: (
            str(record.get("task_id") or ""),
            int(record.get("attempt") or 0),
        )
    )
    allowed_attempts = all_attempts[:DIAGNOSTIC_ATTEMPT_LIMIT]
    omitted += max(0, len(all_attempts) - len(allowed_attempts))
    allowed_keys = {
        (str(record.get("task_id") or ""), int(record.get("attempt") or 0))
        for record in allowed_attempts
    }
    action_all = _action_required_records(normalized_state)
    recent_all = _recent_activity_records(normalized_state, now=now)
    action_keys = {
        (str(record.get("task_id") or ""), int(record.get("attempt") or 0))
        for record in action_all
    }
    recent_keys = {
        (str(record.get("task_id") or ""), int(record.get("attempt") or 0))
        for record in recent_all
    }
    result_cache: dict[tuple[str, int], dict[str, Any] | None] = {}
    snapshots: dict[tuple[str, int], dict[str, Any]] = {}
    for record in allowed_attempts:
        task_id = str(record.get("task_id") or "")
        attempt = int(record.get("attempt") or 0)
        attempt_issues, attempt_incomplete, identity_valid = _diagnostic_validate_attempt(
            record,
            session_id=session_id,
            task_id=task_id,
            attempt=attempt,
        )
        issues.extend(attempt_issues)
        incomplete = incomplete or attempt_incomplete
        if identity_valid:
            formal_result, result_issues, result_incomplete = (
                _inspect_formal_result_read_only(
                    record,
                    task_id,
                    attempt,
                    results_root,
                    session_id=session_id,
                )
            )
        else:
            formal_result, result_issues, result_incomplete = None, [], True
        result_cache[(task_id, attempt)] = formal_result
        issues.extend(result_issues)
        incomplete = incomplete or result_incomplete
        if (
            record.get("managed") is True
            and not _attempt_closed(normalized_state, record)
            and record.get("identity_status") == "unconfirmed"
        ):
            issues.append(
                _diagnostic_issue(
                    "identity_unconfirmed",
                    "managed attempt 的 Agent 身份尚未确认",
                    session_id=session_id,
                    task_id=task_id,
                    attempt=attempt,
                )
            )
        if record.get("platform_observation") == "error":
            issues.append(
                _diagnostic_issue(
                    "platform_error",
                    "持久化 platform_observation=error",
                    session_id=session_id,
                    task_id=task_id,
                    attempt=attempt,
                )
            )
        if record.get("result_conflict") is True:
            issues.append(
                _diagnostic_issue(
                    "result_conflict",
                    "StateStore 已记录同一 attempt 的正式结果冲突",
                    session_id=session_id,
                    task_id=task_id,
                    attempt=attempt,
                )
            )
        snapshots[(task_id, attempt)] = _diagnostic_attempt_snapshot(
            normalized_state,
            record,
            now=now,
            action_keys=action_keys,
            recent_keys=recent_keys,
            formal_result=formal_result,
        )

    groups_value = state.get("groups")
    group_snapshots: list[dict[str, Any]] = []
    if groups_value is None:
        groups_items: list[tuple[str, Any]] = []
    elif not isinstance(groups_value, dict):
        groups_items = []
        issues.append(
            _diagnostic_issue(
                "current_required_field_invalid",
                "Session groups 必须是对象",
                session_id=session_id,
                field="groups",
            )
        )
        incomplete = True
    else:
        groups_items = sorted(groups_value.items(), key=lambda item: str(item[0]))
    omitted += max(0, len(groups_items) - DIAGNOSTIC_GROUP_LIMIT)
    for group_key, group_value in groups_items[:DIAGNOSTIC_GROUP_LIMIT]:
        try:
            validated_group = _validate_group_value(
                group_value,
                expected_group_id=str(group_key),
                persisted=True,
            )
            snapshot, group_issues, group_incomplete = _derive_group_snapshot(
                normalized_state,
                validated_group,
                results_root=results_root,
                session_id=session_id,
                result_cache=result_cache,
            )
        except GroupValidationError as exc:
            issues.append(
                _diagnostic_issue(
                    "current_required_field_invalid",
                    f"group 记录非法：{exc}",
                    session_id=session_id,
                    group_id=str(group_key),
                    field="groups",
                )
            )
            incomplete = True
            continue
        group_snapshots.append(snapshot)
        issues.extend(group_issues)
        incomplete = incomplete or group_incomplete
    group_snapshots.sort(key=lambda group: str(group.get("group_id") or ""))

    if omitted:
        incomplete = True
        issues.append(
            _diagnostic_issue(
                "scan_incomplete",
                "Session snapshot 因诊断数量上限存在未展开记录",
                session_id=session_id,
                fact=f"omitted={omitted}",
            )
        )
    issues.sort(key=_diagnostic_issue_sort_key)
    if len(issues) > DIAGNOSTIC_ISSUE_LIMIT:
        omitted_issues = len(issues) - DIAGNOSTIC_ISSUE_LIMIT
        omitted += omitted_issues
        incomplete = True
        issues = issues[: DIAGNOSTIC_ISSUE_LIMIT - 1]
        issues.append(
            _diagnostic_issue(
                "scan_incomplete",
                "Session issues 因诊断数量上限存在未展开记录",
                session_id=session_id,
                fact=f"omitted_issues={omitted_issues}",
            )
        )
        issues.sort(key=_diagnostic_issue_sort_key)
    action_snapshots = [
        snapshots[key]
        for key in [
            (str(record.get("task_id") or ""), int(record.get("attempt") or 0))
            for record in action_all
        ]
        if key in allowed_keys and key in snapshots
    ]
    recent_snapshots = [
        snapshots[key]
        for key in [
            (str(record.get("task_id") or ""), int(record.get("attempt") or 0))
            for record in recent_all
        ]
        if key in allowed_keys and key in snapshots
    ]
    return (
        {
            "session_id": session_id,
            "component_health": {
                "status": health_status,
                "source": "persisted_health",
            },
            "updated_at": updated_at,
            "counts": {
                "tasks": len(tasks),
                "attempts": len(all_attempts),
                "action_required": len(action_all),
                "recent_activity": len(recent_all),
                "groups": len(groups_items),
                "tombstones": len(tombstones),
            },
            "action_required": action_snapshots,
            "recent_activity": recent_snapshots,
            "groups": group_snapshots,
            "issues": issues,
        },
        incomplete,
        omitted,
    )


def _diagnostic_output_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _build_diagnostic_document(
    session_id: str | None,
    data_root: Path | None = None,
) -> tuple[dict[str, Any], int]:
    root_input = data_root if data_root is not None else _data_root_path()
    root = Path(os.path.abspath(os.fspath(root_input.expanduser())))
    document = _diagnostic_base_document(root, session_id)
    scan = document["scan"]
    incomplete = False
    try:
        root_metadata = root.lstat()
    except FileNotFoundError:
        if session_id is not None:
            scan.update({"requested": 1, "checked": 1, "failed": 1, "complete": False})
            document["issues"].append(
                _diagnostic_issue(
                    "session_missing",
                    "请求的 Session 数据根不存在",
                    session_id=session_id,
                    path=str(root / "sessions" / f"{_safe_name(session_id)}.json"),
                )
            )
            return document, 1
        return document, 0
    document["data_root_exists"] = True
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        scan["complete"] = False
        document["issues"].append(
            _diagnostic_issue(
                "scan_incomplete",
                "数据根不是可扫描的普通目录",
                path=str(root),
                fact="data_root_symlink_or_not_directory",
            )
        )
        return document, 1
    sessions_root = root / "sessions"
    try:
        sessions_metadata = sessions_root.lstat()
    except FileNotFoundError:
        if session_id is not None:
            scan.update({"requested": 1, "checked": 1, "failed": 1, "complete": False})
            document["issues"].append(
                _diagnostic_issue(
                    "session_missing",
                    "请求的 Session 状态文件不存在",
                    session_id=session_id,
                    path=str(sessions_root / f"{_safe_name(session_id)}.json"),
                )
            )
            return document, 1
        return document, 0
    if stat.S_ISLNK(sessions_metadata.st_mode) or not stat.S_ISDIR(sessions_metadata.st_mode):
        scan["complete"] = False
        document["issues"].append(
            _diagnostic_issue(
                "scan_incomplete",
                "sessions 目标不是可扫描的普通目录",
                path=str(sessions_root),
                fact="sessions_root_symlink_or_not_directory",
            )
        )
        return document, 1
    if session_id is not None:
        paths = [sessions_root / f"{_safe_name(session_id)}.json"]
    else:
        try:
            with os.scandir(sessions_root) as entries:
                paths = sorted(
                    [Path(entry.path) for entry in entries if entry.name.endswith(".json")],
                    key=lambda path: path.name,
                )
        except OSError as exc:
            scan["complete"] = False
            document["issues"].append(
                _diagnostic_issue(
                    "scan_incomplete",
                    f"sessions 目录无法列举：{exc}",
                    path=str(sessions_root),
                    fact="sessions_root_unreadable",
                )
            )
            return document, 1
    scan["requested"] = len(paths)
    if len(paths) > DIAGNOSTIC_SESSION_LIMIT:
        scan["omitted"] += len(paths) - DIAGNOSTIC_SESSION_LIMIT
        paths = paths[:DIAGNOSTIC_SESSION_LIMIT]
        incomplete = True
        document["issues"].append(
            _diagnostic_issue(
                "scan_incomplete",
                "全局 Session 数量超过诊断上限",
                path=str(sessions_root),
                fact=f"limit={DIAGNOSTIC_SESSION_LIMIT}",
            )
        )
    now = _now()
    results_root = root / FORMAL_RESULT_STORAGE["directory"]
    snapshots = []
    for path in paths:
        scan["checked"] += 1
        try:
            state = _read_session_file_read_only(
                path,
                requested_session=session_id,
            )
        except DiagnosticReadError as exc:
            scan["failed"] += 1
            incomplete = True
            context = dict(exc.context)
            if session_id is not None:
                context["session_id"] = session_id
            document["issues"].append(
                _diagnostic_issue(exc.code, str(exc), **context)
            )
            continue
        snapshot, session_incomplete, session_omitted = _diagnostic_session_snapshot(
            state,
            path=path,
            results_root=results_root,
            now=now,
        )
        snapshots.append((snapshot, path.name))
        scan["succeeded"] += 1
        scan["omitted"] += session_omitted
        incomplete = incomplete or session_incomplete
    document["sessions"] = [
        snapshot
        for snapshot, _path_name in sorted(
            snapshots,
            key=lambda item: (str(item[0].get("session_id") or ""), item[1]),
        )
    ]
    document["issues"].sort(key=_diagnostic_issue_sort_key)
    if len(document["issues"]) > DIAGNOSTIC_ISSUE_LIMIT:
        omitted_issues = len(document["issues"]) - DIAGNOSTIC_ISSUE_LIMIT
        scan["omitted"] += omitted_issues
        incomplete = True
        document["issues"] = document["issues"][: DIAGNOSTIC_ISSUE_LIMIT - 1]
        document["issues"].append(
            _diagnostic_issue(
                "scan_incomplete",
                "顶层 issues 因诊断数量上限存在未展开记录",
                fact=f"omitted_issues={omitted_issues}",
            )
        )
        document["issues"].sort(key=_diagnostic_issue_sort_key)
    scan["complete"] = not incomplete and scan["failed"] == 0 and scan["omitted"] == 0
    if incomplete and not any(issue.get("code") == "scan_incomplete" for issue in document["issues"]):
        document["issues"].append(
            _diagnostic_issue(
                "scan_incomplete",
                "本次诊断未能完整扫描全部请求事实",
            )
        )
        document["issues"].sort(key=_diagnostic_issue_sort_key)
    while len(_diagnostic_output_bytes(document)) > DIAGNOSTIC_OUTPUT_BYTES and document["sessions"]:
        document["sessions"].pop()
        scan["succeeded"] = max(0, int(scan["succeeded"]) - 1)
        scan["omitted"] += 1
        scan["complete"] = False
        incomplete = True
    if len(_diagnostic_output_bytes(document)) > DIAGNOSTIC_OUTPUT_BYTES:
        document["issues"] = [
            _diagnostic_issue(
                "scan_incomplete",
                "诊断输出超过体积上限，详细问题未展开",
                fact=f"output_limit={DIAGNOSTIC_OUTPUT_BYTES}",
            )
        ]
        scan["omitted"] += 1
        scan["complete"] = False
        incomplete = True
    return document, 0 if scan["complete"] else 1


def _diagnose(session_id: str | None, data_root: Path | None = None) -> int:
    document, exit_code = _build_diagnostic_document(session_id, data_root)
    sys.stdout.buffer.write(_diagnostic_output_bytes(document))
    return exit_code


class _NonExitingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _emit_diagnostic_cli_error(message: str, arguments: list[str]) -> None:
    root = _data_root_path()
    document = _diagnostic_base_document(_diagnostic_absolute_path(root), None)
    if "--session" in arguments:
        document["scope"] = "single_session"
    document["scan"]["complete"] = False
    document["issues"] = [
        _diagnostic_issue(
            "scan_incomplete",
            f"诊断 CLI 参数错误：{message}",
            fact="cli_argument_error",
        )
    ]
    sys.stdout.buffer.write(_diagnostic_output_bytes(document))


def main() -> int:
    parser = _NonExitingArgumentParser(add_help=False)
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--prepare-dispatch", action="store_true")
    parser.add_argument("--prepare-spawn-retry")
    parser.add_argument("--authorize-final-retry", action="store_true")
    parser.add_argument("--prepare-communication", action="store_true")
    parser.add_argument("--prepare-interrupt", action="store_true")
    parser.add_argument("--authorize-recovery", action="store_true")
    parser.add_argument("--submit-result", action="store_true")
    parser.add_argument("--read-result", action="store_true")
    parser.add_argument("--reassociate-result", action="store_true")
    parser.add_argument("--parent-disposition", action="store_true")
    parser.add_argument("--upsert-group", action="store_true")
    parser.add_argument("--read-group", action="store_true")
    parser.add_argument("--group-id")
    parser.add_argument("--agent-target")
    parser.add_argument("--task-id")
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--session")
    parser.add_argument("--data-root", type=Path)
    raw_arguments = sys.argv[1:]
    diagnostic_requested = "--diagnose" in raw_arguments
    try:
        args, unknown = parser.parse_known_args()
    except ValueError as exc:
        if diagnostic_requested:
            _emit_diagnostic_cli_error(str(exc), raw_arguments)
        print(str(exc), file=sys.stderr)
        return 2
    if unknown:
        if args.diagnose:
            _emit_diagnostic_cli_error(f"unsupported arguments: {unknown}", raw_arguments)
        print(f"unsupported arguments: {unknown}", file=sys.stderr)
        return 2
    operation_modes = {
        "prepare_dispatch": args.prepare_dispatch,
        "prepare_spawn_retry": args.prepare_spawn_retry is not None,
        "prepare_communication": args.prepare_communication,
        "prepare_interrupt": args.prepare_interrupt,
        "submit_result": args.submit_result,
        "read_result": args.read_result,
        "reassociate_result": args.reassociate_result,
        "parent_disposition": args.parent_disposition,
        "upsert_group": args.upsert_group,
        "read_group": args.read_group,
    }
    preparation_mode = any(
        (
            args.prepare_dispatch,
            args.prepare_spawn_retry is not None,
            args.prepare_communication,
            args.prepare_interrupt,
        )
    )
    formal_result_mode = any(
        operation_modes[name]
        for name in ("submit_result", "read_result", "reassociate_result", "parent_disposition")
    )
    group_mode = args.upsert_group or args.read_group
    if sum(bool(value) for value in operation_modes.values()) > 1:
        if args.diagnose:
            _emit_diagnostic_cli_error("operation modes cannot be combined", raw_arguments)
        print("operation modes cannot be combined", file=sys.stderr)
        return 2
    if args.diagnose and any(operation_modes.values()):
        _emit_diagnostic_cli_error(
            "--diagnose cannot be combined with another operation mode",
            raw_arguments,
        )
        print("--diagnose cannot be combined with another operation mode", file=sys.stderr)
        return 2
    diagnostic_selector_conflicts = [
        name
        for name, selected in (
            ("--group-id", args.group_id is not None),
            ("--agent-target", args.agent_target is not None),
            ("--task-id", args.task_id is not None),
            ("--attempt", args.attempt is not None),
            ("--authorize-final-retry", args.authorize_final_retry),
            ("--authorize-recovery", args.authorize_recovery),
        )
        if selected
    ]
    if args.diagnose and diagnostic_selector_conflicts:
        conflict_text = ", ".join(diagnostic_selector_conflicts)
        message = f"{conflict_text} cannot be combined with --diagnose"
        _emit_diagnostic_cli_error(message, raw_arguments)
        print(message, file=sys.stderr)
        return 2
    if not args.diagnose and not any(operation_modes.values()) and (
        args.session is not None or args.data_root is not None or args.group_id is not None
    ):
        print("--session and --data-root require --diagnose or an explicit operation mode", file=sys.stderr)
        return 2
    if args.diagnose:
        return _diagnose(args.session, args.data_root)
    if preparation_mode:
        if not args.session:
            print("dispatch preparation requires --session", file=sys.stderr)
            return 2
        try:
            raw_contract = json.loads(sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1))
            base = _prepare_private_directory(args.data_root.expanduser()) if args.data_root else _data_root()
            state_store = StateStore(base / "sessions")
            prepared_store = PreparedContractStore(base / "prepared")
            if args.prepare_dispatch:
                result = prepare_dispatch(
                    raw_contract,
                    args.session,
                    state_store=state_store,
                    prepared_store=prepared_store,
                )
            elif args.prepare_spawn_retry is not None:
                result = prepare_spawn_retry(
                    raw_contract,
                    args.session,
                    args.prepare_spawn_retry,
                    authorized=args.authorize_final_retry,
                    state_store=state_store,
                    prepared_store=prepared_store,
                )
            elif args.prepare_communication:
                result = prepare_communication(
                    raw_contract,
                    args.session,
                    authorized_recovery=args.authorize_recovery,
                    state_store=state_store,
                )
            else:
                result = prepare_interrupt(
                    raw_contract,
                    args.session,
                    state_store=state_store,
                )
        except Exception as exc:
            print(f"operation preparation failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if formal_result_mode:
        if not args.session:
            print("formal result operations require --session", file=sys.stderr)
            return 2
        if args.submit_result and not args.agent_target:
            print("--submit-result requires --agent-target", file=sys.stderr)
            return 2
        if (args.read_result or args.reassociate_result) and (
            not args.task_id or args.attempt is None
        ):
            print("result read/reassociation requires --task-id and --attempt", file=sys.stderr)
            return 2
        try:
            base = _prepare_private_directory(args.data_root.expanduser()) if args.data_root else _data_root()
            state_store = StateStore(base / "sessions")
            results_root = base / "results"
            if args.submit_result:
                raw_result = json.loads(sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1))
                result = submit_task_result(
                    raw_result,
                    args.session,
                    agent_target=args.agent_target,
                    state_store=state_store,
                    results_root=results_root,
                )
            elif args.read_result:
                result = read_task_result(
                    args.session,
                    args.task_id,
                    args.attempt,
                    state_store=state_store,
                    results_root=results_root,
                )
            elif args.reassociate_result:
                result = reassociate_task_result(
                    args.session,
                    args.task_id,
                    args.attempt,
                    state_store=state_store,
                    results_root=results_root,
                )
            else:
                raw_disposition = json.loads(sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1))
                result = apply_parent_disposition(
                    raw_disposition,
                    args.session,
                    state_store=state_store,
                )
        except Exception as exc:
            print(f"formal result operation failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if group_mode:
        if not args.session:
            print("group operations require --session", file=sys.stderr)
            return 2
        if args.read_group and not args.group_id:
            print("--read-group requires --group-id", file=sys.stderr)
            return 2
        if args.upsert_group and args.group_id is not None:
            print("--group-id is only valid with --read-group", file=sys.stderr)
            return 2
        try:
            base = (
                _prepare_private_directory(args.data_root.expanduser())
                if args.data_root
                else _data_root()
            )
            state_store = StateStore(base / "sessions")
            if args.upsert_group:
                raw_group = json.loads(sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1))
                result = upsert_group(
                    raw_group,
                    args.session,
                    state_store=state_store,
                )
            else:
                result = read_group(
                    args.session,
                    args.group_id,
                    state_store=state_store,
                    results_root=base / FORMAL_RESULT_STORAGE["directory"],
                )
        except Exception as exc:
            print(f"group operation failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    try:
        raw_input = sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1)
        if len(raw_input.encode("utf-8")) > MAX_HOOK_INPUT_BYTES:
            raise ValueError(f"hook input exceeds {MAX_HOOK_INPUT_BYTES} bytes")
        payload = json.loads(raw_input)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be a JSON object")
        result = handle(payload)
    except Exception as exc:
        event = locals().get("payload", {}).get("hook_event_name") if isinstance(locals().get("payload"), dict) else None
        if event == "PreToolUse":
            result = _deny(f"Subagent Governance 解析失败：{exc}")
        else:
            result = {"continue": True, "systemMessage": f"Subagent Governance 运行失败，已降级放行：{exc}"}
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
