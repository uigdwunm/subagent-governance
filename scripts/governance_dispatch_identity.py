"""Pure derived identity helpers for TaskContract v2 dispatches."""

from __future__ import annotations

import hashlib
import re
from typing import Any

try:
    from scripts.governance_semantics import (
        PROFILES,
        TASK_NAME_MAX_LENGTH,
        TASK_NAME_RE,
        TASK_REF_LENGTHS,
    )
except ModuleNotFoundError:
    from governance_semantics import PROFILES, TASK_NAME_MAX_LENGTH, TASK_NAME_RE, TASK_REF_LENGTHS


def normalize_semantic_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", normalized).strip("_") or "task"


def derive_task_ref(task_id: str, length: int) -> str:
    if length not in TASK_REF_LENGTHS:
        raise ValueError("task_ref 长度无效")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id 必须是非空字符串")
    return hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:length]


def select_task_ref(task_id: str, occupied_refs: set[str]) -> str | None:
    for length in TASK_REF_LENGTHS:
        candidate = derive_task_ref(task_id, length)
        if candidate not in occupied_refs:
            return candidate
    return None


def build_task_name(profile: str, semantic_name: str, task_ref: str) -> str:
    if profile not in PROFILES:
        raise ValueError("profile 必须是 standard 或 strict")
    if len(task_ref) not in TASK_REF_LENGTHS or re.fullmatch(r"[a-f0-9]+", task_ref) is None:
        raise ValueError("task_ref 无效")
    normalized = normalize_semantic_name(semantic_name)
    available = TASK_NAME_MAX_LENGTH - len(f"sg_{profile}__t_{task_ref}")
    semantic = normalized[:available].rstrip("_") or "task"
    value = f"sg_{profile}_{semantic}_t_{task_ref}"
    if TASK_NAME_RE.fullmatch(value) is None:
        raise ValueError("无法生成合法 governed task_name")
    return value


def parse_task_name(value: Any) -> tuple[str, str, str] | None:
    if not isinstance(value, str) or len(value) > TASK_NAME_MAX_LENGTH:
        return None
    match = TASK_NAME_RE.fullmatch(value)
    return None if match is None else (match.group(1), match.group(2), match.group(3))


__all__ = ["build_task_name", "derive_task_ref", "normalize_semantic_name", "parse_task_name", "select_task_ref"]
