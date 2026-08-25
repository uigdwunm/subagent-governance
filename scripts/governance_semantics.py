"""Machine-readable constants for the current-only state-v9 runtime."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

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

STATE_FORMAT_VERSION = int(SEMANTIC_RULES["state_format_version"])
STATE_STORAGE_NAMESPACE = str(SEMANTIC_RULES["state_storage_namespace"])
TASK_CONTRACT_WIRE_VERSION = int(SEMANTIC_RULES["task_contract_wire_version"])
TASK_CONTRACT_FIELDS = tuple(SEMANTIC_RULES["task_contract_fields"])
TASK_CONTRACT_REQUIRED_INPUT_FIELDS = tuple(
    SEMANTIC_RULES["task_contract_required_input_fields"]
)
PROFILES = frozenset(SEMANTIC_RULES["profiles"])
PHASES = frozenset(SEMANTIC_RULES["phases"])
TASK_REF_LENGTHS = tuple(int(value) for value in SEMANTIC_RULES["task_ref_lengths"])
PREPARED_EXPIRY_SECONDS = int(SEMANTIC_RULES["prepared_expiry_seconds"])

MAX_HOOK_INPUT_BYTES = int(SEMANTIC_RULES["max_hook_input_bytes"])
MAX_PREPARED_BYTES = MAX_HOOK_INPUT_BYTES
NEW_TASK_SOFT_LIMIT_BYTES = int(SEMANTIC_RULES["new_task_soft_limit_bytes"])
MAX_STATE_BYTES = int(SEMANTIC_RULES["max_state_bytes"])

TASK_NAME_MAX_LENGTH = 64
TASK_NAME_PATTERN = r"^sg_(standard|strict)_([a-z0-9]+(?:_[a-z0-9]+)*)_t_([a-f0-9]{12}|[a-f0-9]{20})$"
TASK_NAME_RE = re.compile(TASK_NAME_PATTERN)
REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max", "ultra"})
MAX_CONTRACT_TEXT = int(SEMANTIC_DEFINITIONS["short_text"]["maxLength"])
MAX_BUSINESS_TEXT = int(SEMANTIC_DEFINITIONS["nonempty_text"]["maxLength"])
MAX_TASKS_PER_SESSION = int(
    SEMANTIC_DEFINITIONS["session_ledger"]["properties"]["tasks"]["maxProperties"]
)
SESSION_SUMMARY_RECORD_LIMIT = 8
SESSION_SUMMARY_CONTEXT_LIMIT = 1800

RECONCILE_CODES = frozenset(
    SEMANTIC_DEFINITIONS["reconcile_fact"]["properties"]["code"]["enum"]
)

__all__ = [
    "MACHINE_SEMANTICS",
    "MAX_BUSINESS_TEXT",
    "MAX_CONTRACT_TEXT",
    "MAX_HOOK_INPUT_BYTES",
    "MAX_PREPARED_BYTES",
    "MAX_STATE_BYTES",
    "MAX_TASKS_PER_SESSION",
    "NEW_TASK_SOFT_LIMIT_BYTES",
    "PHASES",
    "PREPARED_EXPIRY_SECONDS",
    "PROFILES",
    "REASONING_EFFORTS",
    "RECONCILE_CODES",
    "SEMANTIC_DEFINITIONS",
    "SEMANTIC_RULES",
    "SESSION_SUMMARY_CONTEXT_LIMIT",
    "SESSION_SUMMARY_RECORD_LIMIT",
    "STATE_FORMAT_VERSION",
    "STATE_STORAGE_NAMESPACE",
    "TASK_CONTRACT_FIELDS",
    "TASK_CONTRACT_REQUIRED_INPUT_FIELDS",
    "TASK_CONTRACT_WIRE_VERSION",
    "TASK_NAME_MAX_LENGTH",
    "TASK_NAME_PATTERN",
    "TASK_NAME_RE",
    "TASK_REF_LENGTHS",
]
