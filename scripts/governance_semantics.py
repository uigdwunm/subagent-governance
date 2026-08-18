"""Machine-readable governance semantics and derived constants.

This module is intentionally data-oriented.  Runtime handlers import these
values, while the schema remains the single source of truth for semantics.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SEMANTICS_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas/governance-semantics.schema.json"
)


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


def _semantic_values(name: str) -> tuple[str, ...]:
    definition = SEMANTIC_DEFINITIONS.get(name)
    values = definition.get("enum") if isinstance(definition, dict) else None
    if not isinstance(values, list) or not all(
        isinstance(value, str) for value in values
    ):
        raise RuntimeError(f"治理机器语义源中的枚举 {name} 无效")
    return tuple(values)


def _semantic_enum(name: str) -> frozenset[str]:
    return frozenset(_semantic_values(name))


REQUESTED_MODES = _semantic_enum("requested_mode")
RESOLVED_MODES = _semantic_enum("resolved_mode")
RESOLUTION_REASONS = _semantic_enum("resolution_reason")
RISKS = _semantic_enum("risk")
REASONING_EFFORTS = _semantic_enum("reasoning_effort")
CONTEXT_STRATEGIES = _semantic_enum("context_strategy")
OPERATION_TYPES = _semantic_enum("operation_type")
DISPATCH_STATES = _semantic_enum("dispatch_state")
OBSERVATION_SOURCES = _semantic_enum("observation_source")
RETIRED_OBSERVATION_SOURCES = frozenset({"post_tool", "wait"})
OBSERVED_STATES = _semantic_enum("observed_state")
EXECUTION_STATUSES = _semantic_enum("execution_status")
IDENTITY_STATUSES = _semantic_enum("identity_status")
PLATFORM_OBSERVATIONS = _semantic_enum("platform_observation")
PARENT_ACTIONS = _semantic_enum("parent_action")
PARENT_DISPOSITIONS = _semantic_enum("parent_disposition")
CALL_OBSERVATIONS = _semantic_enum("call_observation")
LIFECYCLE_OPERATION_TYPES = _semantic_enum("lifecycle_operation_type")
_DECISION_ACTION_ORDER = _semantic_values("decision_allowed_action")
RETRY_LIMITS = dict(SEMANTIC_RULES["retry_limits"])
RETENTION_SECONDS = dict(SEMANTIC_RULES["retention_seconds"])
OPERATION_NATIVE_TOOLS = dict(SEMANTIC_RULES["operation_native_tools"])
AUTO_RESOLUTION = dict(SEMANTIC_RULES["auto_resolution"])
MODE_MINIMUMS = dict(SEMANTIC_RULES["mode_minimums"])
CONTEXT_TURNS = dict(SEMANTIC_RULES["context_turns"])
TASK_CONTRACT_OPTIONAL_FIELDS = tuple(
    SEMANTIC_RULES["task_contract_optional_fields"]
)
DIAGNOSTIC_LIMITS = dict(SEMANTIC_RULES["diagnostic_limits"])
GROUP_SEMANTICS = dict(SEMANTIC_RULES["group"])
PLATFORM_OBSERVATION_ADAPTER = dict(
    SEMANTIC_RULES["platform_observation_adapter"]
)
LIST_AGENTS_ACTIVE_STATUSES = frozenset(
    PLATFORM_OBSERVATION_ADAPTER["active_statuses"]
)
LIST_AGENTS_ADVISORY_STATUSES = frozenset(
    PLATFORM_OBSERVATION_ADAPTER["advisory_statuses"]
)
LIST_AGENTS_TERMINAL_STATUSES = frozenset(
    PLATFORM_OBSERVATION_ADAPTER["terminal_statuses"]
)
LIST_AGENTS_ERROR_STATUSES = frozenset(
    PLATFORM_OBSERVATION_ADAPTER["error_statuses"]
)
LIST_AGENTS_BOOLEAN_ERROR_FLAGS = tuple(
    PLATFORM_OBSERVATION_ADAPTER["boolean_error_flags"]
)
LIST_AGENTS_EXPLICIT_ERROR_FIELD = str(
    PLATFORM_OBSERVATION_ADAPTER["explicit_error_field"]
)
LIST_AGENTS_WRAPPER_STATUS_FIELDS = tuple(
    PLATFORM_OBSERVATION_ADAPTER["wrapper_status_fields"]
)
LIST_AGENTS_WRAPPER_ERROR_STATUSES = frozenset(
    PLATFORM_OBSERVATION_ADAPTER["wrapper_error_statuses"]
)
LIST_AGENTS_WRAPPER_STATUS_PARSE_POLICY = str(
    PLATFORM_OBSERVATION_ADAPTER["wrapper_status_parse_policy"]
)
LIST_AGENTS_MALFORMED_WRAPPER_POLICY = str(
    PLATFORM_OBSERVATION_ADAPTER["malformed_or_explicit_error"]
)
if LIST_AGENTS_WRAPPER_STATUS_PARSE_POLICY != "present_must_be_single_native_tag":
    raise RuntimeError("unsupported list_agents wrapper status parse policy")
if LIST_AGENTS_MALFORMED_WRAPPER_POLICY != "no_exact_bound_fact":
    raise RuntimeError("unsupported malformed list_agents wrapper policy")
PARENT_DISPOSITION_REASON_MAX_LENGTH = int(
    SEMANTIC_RULES["parent_disposition_reason_max_length"]
)
TASK_NAME_PATTERN = str(SEMANTIC_RULES["task_name"]["pattern"])
TASK_NAME_MAX_LENGTH = int(SEMANTIC_RULES["task_name"]["max_length"])
TASK_REF_LENGTHS = tuple(
    int(value) for value in SEMANTIC_RULES["task_name"]["task_ref_lengths"]
)
TASK_NAME_RE = re.compile(TASK_NAME_PATTERN)

MAX_HOOK_INPUT_BYTES = 2 * 1024 * 1024
MAX_PREPARED_BYTES = MAX_HOOK_INPUT_BYTES
NEW_TASK_SOFT_LIMIT_BYTES = 3 * 1024 * 1024
MAX_STATE_BYTES = 4 * 1024 * 1024
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
STATE_FORMAT_VERSION = int(SEMANTIC_RULES["canonical_record"]["state_format_version"])
REQUIRED_TASK_CONTAINER_FIELDS = frozenset({"managed", "work_item", "executions"})
REQUIRED_WORK_ITEM_FIELDS = frozenset({"lifecycle", "current_attempt"})
REQUIRED_EXECUTION_FIELDS = frozenset(
    {
        "task_ref",
        "task_name",
        "resolved_mode",
        "contract_summary",
        "contract_digest",
        "dispatch_record",
        "observation_record",
        "closure_record",
        "spawn_retry_count",
        "recovery_count",
        "updated_at",
    }
)
REQUIRED_DISPATCH_RECORD_FIELDS = frozenset(
    {"dispatch_state", "tool_use_id", "dispatch_target"}
)
REQUIRED_OBSERVATION_RECORD_FIELDS = frozenset(
    {"source", "observed_state", "observed_at", "terminal_status"}
)
REQUIRED_CLOSURE_RECORD_FIELDS = frozenset(
    {"reason", "closed_at", "parent_action"}
)
LEGACY_EXECUTION_PROJECTION_FIELDS = frozenset(
    {
        "execution_status",
        "spawn_observation",
        "identity_status",
        "platform_observation",
        "parent_action",
        "parent_disposition_record",
        "spawn_tool_use_id",
        "spawn_claimed_at",
        "spawn_post_observed_at",
        "spawn_observed_agent_id",
        "spawn_observed_canonical_path",
        "spawn_result_credential_id",
        "agent_id",
        "canonical_task_path",
        "platform_checked_at",
        "platform_observation_source",
        "platform_observation_summary",
        "platform_observation_target",
        "start_observed_at",
        "attempt_closed",
        "attempt_close_reason",
        "attempt_closed_at",
        "parent_disposition",
        "parent_disposition_reason",
        "parent_disposition_at",
        "spawn_not_created",
    }
)
REQUIRED_PENDING_ACTION_FIELDS = frozenset(
    {
        "target",
        "attempt",
        "task_ref",
        "operation_type",
        "phase",
        "created_at",
        "tool_use_id",
        "claimed_at",
    }
)
REQUIRED_LIFECYCLE_OPERATION_FIELDS = frozenset(
    {"operation_type", "tool_use_id", "call_observation"}
)
