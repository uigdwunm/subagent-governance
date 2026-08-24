"""Pure semantic dispatch identity construction and parsing."""

from __future__ import annotations

import hashlib
import re
from typing import Any

try:
    from scripts.governance_semantics import (
        RESOLVED_MODES,
        TASK_NAME_MAX_LENGTH,
        TASK_NAME_RE,
        TASK_REF_LENGTHS,
    )
except ModuleNotFoundError:
    from governance_semantics import (
        RESOLVED_MODES,
        TASK_NAME_MAX_LENGTH,
        TASK_NAME_RE,
        TASK_REF_LENGTHS,
    )


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
