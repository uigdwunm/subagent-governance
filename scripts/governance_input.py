"""P2 UTF-8 byte-bounded JSON object reader shared by every stdin mode."""
from __future__ import annotations

import json
from typing import Any, BinaryIO

try:
    from scripts.governance_semantics import MAX_HOOK_INPUT_BYTES
except ModuleNotFoundError:
    from governance_semantics import MAX_HOOK_INPUT_BYTES


def read_json_object(stream: BinaryIO, *, limit: int = MAX_HOOK_INPUT_BYTES) -> dict[str, Any]:
    raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"JSON input exceeds {limit} bytes")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON input must be a JSON object")
    return value


__all__ = ["read_json_object"]
