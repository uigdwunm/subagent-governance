"""Private, bounded claimed-PostToolUse index for catch-all routing.

The index is an acceleration and admission hint, never canonical authority.
Every hit is rechecked against the current StateStore claimed pending before a
receipt or lifecycle transition is written.  Lookup is read-only and does not
create directories, locks, or StateStore instances.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

try:
    from scripts.governance_storage import PrivateStorageError, atomic_write_bytes, read_private_bytes
    from scripts.governance_store_support import (
        data_root_path, owned_by_current_user, prepare_private_directory,
        private_permissions_safe, restrict_descriptor, sync_directory,
    )
except ModuleNotFoundError:
    from governance_storage import PrivateStorageError, atomic_write_bytes, read_private_bytes
    from governance_store_support import (
        data_root_path, owned_by_current_user, prepare_private_directory,
        private_permissions_safe, restrict_descriptor, sync_directory,
    )


INDEX_FORMAT_VERSION = 1
INDEX_DIRECTORY = "claimed-post-tool-ids"
INDEX_TTL_SECONDS = 20 * 60
MAX_INDEX_RECORDS = 512


def index_root_for_store(store: Any | None) -> Path:
    root = getattr(store, "root", None)
    if isinstance(root, Path):
        # StateStore.root is the selected current-only state namespace, even
        # when a developer passes an explicit data root.
        return root / INDEX_DIRECTORY
    return data_root_path(Path(__file__)) / INDEX_DIRECTORY


def _filename(session_id: str, tool_use_id: str) -> str:
    digest = hashlib.sha256(f"{session_id}\0{tool_use_id}".encode("utf-8")).hexdigest()
    return f"{digest}.json"


def _valid_record(value: Any, *, session_id: str, tool_use_id: str, now: int) -> dict[str, Any] | None:
    if not isinstance(value, dict) or set(value) != {
        "index_format_version", "session_id", "tool_use_id", "task_id", "attempt",
        "task_ref", "operation_type", "claimed_at", "expires_at",
    }:
        return None
    if value.get("index_format_version") != INDEX_FORMAT_VERSION:
        return None
    if value.get("session_id") != session_id or value.get("tool_use_id") != tool_use_id:
        return None
    if not (
        isinstance(value.get("session_id"), str)
        and value["session_id"].strip()
        and len(value["session_id"]) <= 4000
        and isinstance(value.get("tool_use_id"), str)
        and value["tool_use_id"].strip()
        and len(value["tool_use_id"]) <= 1024
    ):
        return None
    if not (
        isinstance(value.get("task_id"), str)
        and value["task_id"].strip()
        and len(value["task_id"]) <= 128
        and isinstance(value.get("task_ref"), str)
        and re.fullmatch(r"[a-f0-9]{12}(?:[a-f0-9]{4}){0,5}", value["task_ref"])
        and value.get("operation_type") in {
            "normal_message", "platform_recovery", "business_resume", "interrupt",
        }
    ):
        return None
    if isinstance(value.get("attempt"), bool) or not isinstance(value.get("attempt"), int) or value["attempt"] < 1:
        return None
    if any(isinstance(value.get(field), bool) or not isinstance(value.get(field), int) or value[field] < 0 for field in ("claimed_at", "expires_at")):
        return None
    if value["expires_at"] < value["claimed_at"] or value["expires_at"] < now:
        return None
    return value


class ClaimedPostIndex:
    def __init__(self, root: Path):
        self.root = root

    def lookup(self, session_id: str, tool_use_id: str, *, now: int | None = None) -> dict[str, Any] | None:
        """Return an exact, unexpired claim hint without creating storage."""
        if not session_id or not tool_use_id or not self.root.is_dir():
            return None
        path = self.root / _filename(session_id, tool_use_id)
        current = int(time.time()) if now is None else now
        try:
            raw = read_private_bytes(
                path, label="PostToolUse claimed-ID index", max_bytes=4096,
                owned_by_current_user=owned_by_current_user,
                private_permissions_safe=private_permissions_safe,
            )
            value = json.loads(raw.decode("utf-8"))
        except (FileNotFoundError, PrivateStorageError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return _valid_record(value, session_id=session_id, tool_use_id=tool_use_id, now=current)

    def record_claim(self, value: dict[str, Any], *, now: int | None = None) -> None:
        """Atomically publish a bounded exact claim after canonical claim CAS."""
        session_id, tool_use_id = value.get("session_id"), value.get("tool_use_id")
        claimed_at = value.get("claimed_at") if isinstance(value, dict) else None
        current = int(time.time()) if now is None else now
        valid = _valid_record(value, session_id=session_id, tool_use_id=tool_use_id, now=current) if isinstance(session_id, str) and isinstance(tool_use_id, str) and isinstance(claimed_at, int) else None
        if valid is None:
            raise ValueError("claimed PostToolUse index record invalid")
        prepare_private_directory(self.root)
        self.cleanup_expired(now=current)
        destination = self.root / _filename(session_id, tool_use_id)
        if not destination.exists() and sum(1 for path in self.root.glob("*.json") if path.is_file()) >= MAX_INDEX_RECORDS:
            raise PrivateStorageError("PostToolUse claimed-ID index 达到有界容量")
        encoded = (json.dumps(valid, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        atomic_write_bytes(
            destination, encoded,
            label="PostToolUse claimed-ID index",
            restrict_descriptor=restrict_descriptor,
            sync_directory=sync_directory,
        )

    def remove(self, session_id: str, tool_use_id: str) -> None:
        """Best-effort exact cleanup after a completed lifecycle transition."""
        path = self.root / _filename(session_id, tool_use_id)
        try:
            # The filename is a derived digest and the directory is created
            # only through prepare_private_directory.  Do not chase arbitrary
            # caller-controlled paths during best-effort cleanup.
            path.unlink()
        except FileNotFoundError:
            return

    def cleanup_expired(self, *, now: int | None = None) -> int:
        """Remove only valid expired records during explicit maintenance/writes.

        Catch-all lookup remains read-only.  Cleanup is deliberately confined
        to maintenance and claim publication, scans at most the fixed index
        capacity, and leaves malformed/private-boundary failures untouched for
        diagnosis rather than treating them as authority to delete.
        """
        if not self.root.is_dir():
            return 0
        current = int(time.time()) if now is None else now
        removed = 0
        for path in list(self.root.glob("*.json"))[:MAX_INDEX_RECORDS]:
            try:
                raw = read_private_bytes(
                    path, label="PostToolUse claimed-ID index", max_bytes=4096,
                    owned_by_current_user=owned_by_current_user,
                    private_permissions_safe=private_permissions_safe,
                )
                value = json.loads(raw.decode("utf-8"))
                valid_at_origin = _valid_record(
                    value, session_id=value.get("session_id"),
                    tool_use_id=value.get("tool_use_id"), now=0,
                ) if isinstance(value, dict) else None
                if valid_at_origin is None or valid_at_origin["expires_at"] >= current:
                    continue
                path.unlink()
                removed += 1
            except (FileNotFoundError, PrivateStorageError, UnicodeDecodeError, json.JSONDecodeError, OSError):
                continue
        return removed


def claim_index_record(
    session_id: str, task_id: str, attempt: int, pending: dict[str, Any]
) -> dict[str, Any]:
    claimed_at = pending.get("claimed_at")
    tool_use_id = pending.get("tool_use_id")
    if not isinstance(claimed_at, int) or isinstance(claimed_at, bool) or not isinstance(tool_use_id, str) or not tool_use_id:
        raise ValueError("claimed pending lacks indexable tool_use_id")
    return {
        "index_format_version": INDEX_FORMAT_VERSION,
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "task_id": task_id,
        "attempt": attempt,
        "task_ref": pending["task_ref"],
        "operation_type": pending["operation_type"],
        "claimed_at": claimed_at,
        "expires_at": claimed_at + INDEX_TTL_SECONDS,
    }


__all__ = [
    "ClaimedPostIndex", "INDEX_DIRECTORY", "INDEX_FORMAT_VERSION", "INDEX_TTL_SECONDS", "MAX_INDEX_RECORDS",
    "claim_index_record", "index_root_for_store",
]
