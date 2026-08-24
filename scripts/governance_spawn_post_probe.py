"""Private, bounded P12-A diagnostics for governed spawn PostToolUse.

Probe records are deliberately separate from canonical state and P11's
lifecycle claimed-ID index.  Lookups are read-only admission hints; callers
must still recheck the current PreparedContract and StateStore before recording
any diagnostic receipt.
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


PROBE_INDEX_FORMAT_VERSION = 1
PROBE_FORMAT_VERSION = 1
MARKER_DIRECTORY = "spawn-post-probe-ids-v1"
RECEIPT_DIRECTORY = "spawn-post-probes-v1"
MARKER_TTL_SECONDS = 20 * 60
RECEIPT_TTL_SECONDS = 24 * 60 * 60
MAX_PROBE_RECORDS = 256
_TASK_REF = re.compile(r"[a-f0-9]{12}(?:[a-f0-9]{4}){0,5}")
_OPERATIONS = {"initial_spawn", "spawn_retry"}
_CLAIM_CHECKS = {"not_checked", "matched", "prepared_missing", "state_mismatch", "validation_failed"}
_SHAPES = {"not_checked", "empty", "top_level_object", "non_object", "json_decode_failed", "explicit_error"}
_STAGES = {"received", "claim_checked", "shape_classified", "completed", "handler_failed"}


def probe_root_for_store(store: Any | None) -> Path:
    root = getattr(store, "root", None)
    if isinstance(root, Path):
        return (root.parent if root.name == "sessions" else root)
    return data_root_path(Path(__file__))


def _filename(session_id: str, tool_use_id: str) -> str:
    digest = hashlib.sha256(f"{session_id}\0{tool_use_id}".encode("utf-8")).hexdigest()
    return f"{digest}.json"


def _valid_identity(value: dict[str, Any]) -> bool:
    return (
        isinstance(value.get("session_id"), str) and bool(value["session_id"].strip()) and len(value["session_id"]) <= 4000
        and isinstance(value.get("task_id"), str) and bool(value["task_id"].strip()) and len(value["task_id"]) <= 128
        and isinstance(value.get("attempt"), int) and not isinstance(value["attempt"], bool) and value["attempt"] >= 1
        and isinstance(value.get("task_ref"), str) and bool(_TASK_REF.fullmatch(value["task_ref"]))
        and value.get("dispatch_operation") in _OPERATIONS
        and isinstance(value.get("spawn_retry_count"), int) and not isinstance(value["spawn_retry_count"], bool)
        and 0 <= value["spawn_retry_count"] <= 2
    )


def _valid_marker(value: Any, *, session_id: str, tool_use_id: str, now: int) -> dict[str, Any] | None:
    fields = {"probe_index_format_version", "session_id", "tool_use_id", "task_id", "attempt", "task_ref", "dispatch_operation", "spawn_retry_count", "claimed_at", "expires_at"}
    if not isinstance(value, dict) or set(value) != fields or value.get("probe_index_format_version") != PROBE_INDEX_FORMAT_VERSION:
        return None
    if value.get("session_id") != session_id or value.get("tool_use_id") != tool_use_id or not isinstance(tool_use_id, str) or not tool_use_id.strip() or len(tool_use_id) > 1024:
        return None
    if not _valid_identity(value):
        return None
    if any(isinstance(value.get(field), bool) or not isinstance(value.get(field), int) or value[field] < 0 for field in ("claimed_at", "expires_at")):
        return None
    if value["expires_at"] < value["claimed_at"] or value["expires_at"] < now:
        return None
    return value


def _valid_receipt(value: Any, *, session_id: str, tool_use_id: str, now: int) -> dict[str, Any] | None:
    fields = {"probe_format_version", "session_id", "tool_use_id_match", "task_id", "attempt", "task_ref", "dispatch_operation", "spawn_retry_count", "tool_name_classification", "admission_source", "claim_check", "response_shape", "handler_stage", "recorded_at", "updated_at"}
    if not isinstance(value, dict) or set(value) != fields or value.get("probe_format_version") != PROBE_FORMAT_VERSION:
        return None
    # tool_use_id itself intentionally never enters the receipt body.  The
    # digest filename is its only on-disk locator.
    if value.get("session_id") != session_id or not isinstance(tool_use_id, str) or not tool_use_id.strip() or len(tool_use_id) > 1024 or not _valid_identity(value):
        return None
    if value.get("tool_use_id_match") is not True or value.get("tool_name_classification") not in {"recognized", "unrecognized"} or value.get("admission_source") not in {"recognized_prepared", "exact_probe_marker"}:
        return None
    if value.get("claim_check") not in _CLAIM_CHECKS or value.get("response_shape") not in _SHAPES or value.get("handler_stage") not in _STAGES:
        return None
    if any(isinstance(value.get(field), bool) or not isinstance(value.get(field), int) or value[field] < 0 for field in ("recorded_at", "updated_at")):
        return None
    if value["updated_at"] < value["recorded_at"] or value["recorded_at"] + RECEIPT_TTL_SECONDS < now:
        return None
    return value


def marker_record(session_id: str, tool_use_id: str, task_id: str, attempt: int, task_ref: str, dispatch_operation: str, spawn_retry_count: int, *, claimed_at: int) -> dict[str, Any]:
    return {
        "probe_index_format_version": PROBE_INDEX_FORMAT_VERSION, "session_id": session_id,
        "tool_use_id": tool_use_id, "task_id": task_id, "attempt": attempt, "task_ref": task_ref,
        "dispatch_operation": dispatch_operation, "spawn_retry_count": spawn_retry_count,
        "claimed_at": claimed_at, "expires_at": claimed_at + MARKER_TTL_SECONDS,
    }


def receipt_record(marker: dict[str, Any], tool_name_classification: str, admission_source: str, *, recorded_at: int) -> dict[str, Any]:
    return {
        "probe_format_version": PROBE_FORMAT_VERSION, "session_id": marker["session_id"], "tool_use_id_match": True,
        "task_id": marker["task_id"], "attempt": marker["attempt"], "task_ref": marker["task_ref"],
        "dispatch_operation": marker["dispatch_operation"], "spawn_retry_count": marker["spawn_retry_count"],
        "tool_name_classification": tool_name_classification, "admission_source": admission_source,
        "claim_check": "not_checked", "response_shape": "not_checked", "handler_stage": "received",
        "recorded_at": recorded_at, "updated_at": recorded_at,
    }


class SpawnPostProbeStore:
    """Exact marker and receipt persistence; reads never create filesystem state."""
    def __init__(self, root: Path):
        self.root = root
        self.markers_root = root / MARKER_DIRECTORY
        self.receipts_root = root / RECEIPT_DIRECTORY

    @staticmethod
    def _read(path: Path, label: str) -> Any:
        raw = read_private_bytes(path, label=label, max_bytes=4096, owned_by_current_user=owned_by_current_user, private_permissions_safe=private_permissions_safe)
        return json.loads(raw.decode("utf-8"))

    @staticmethod
    def _write(root: Path, path: Path, record: dict[str, Any], label: str) -> None:
        prepare_private_directory(root)
        raw = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        atomic_write_bytes(path, raw, label=label, restrict_descriptor=restrict_descriptor, sync_directory=sync_directory)

    @staticmethod
    def _cleanup(root: Path, validator: Any, *, now: int, expiry: str) -> int:
        if not root.is_dir():
            return 0
        removed = 0
        for path in list(root.glob("*.json"))[:MAX_PROBE_RECORDS]:
            try:
                value = SpawnPostProbeStore._read(path, "spawn PostToolUse probe")
                session_id = value.get("session_id") if isinstance(value, dict) else None
                tool_use_id = value.get("tool_use_id") if expiry == "expires_at" and isinstance(value, dict) else "receipt-locator"
                valid = validator(value, session_id=session_id, tool_use_id=tool_use_id, now=0) if isinstance(session_id, str) else None
                if valid is not None:
                    expired_at = valid[expiry] + RECEIPT_TTL_SECONDS if expiry == "updated_at" else valid[expiry]
                else:
                    expired_at = None
                if expired_at is not None and expired_at < now:
                    path.unlink()
                    removed += 1
            except (FileNotFoundError, PrivateStorageError, UnicodeDecodeError, json.JSONDecodeError, OSError, AttributeError):
                continue
        return removed

    def lookup_marker(self, session_id: str, tool_use_id: str, *, now: int | None = None) -> dict[str, Any] | None:
        if not session_id or not tool_use_id or not self.markers_root.is_dir():
            return None
        try:
            value = self._read(self.markers_root / _filename(session_id, tool_use_id), "spawn PostToolUse probe marker")
        except (FileNotFoundError, PrivateStorageError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return _valid_marker(value, session_id=session_id, tool_use_id=tool_use_id, now=int(time.time()) if now is None else now)

    def lookup_receipt(self, session_id: str, tool_use_id: str, *, now: int | None = None) -> dict[str, Any] | None:
        if not session_id or not tool_use_id or not self.receipts_root.is_dir():
            return None
        try:
            value = self._read(self.receipts_root / _filename(session_id, tool_use_id), "spawn PostToolUse probe receipt")
        except (FileNotFoundError, PrivateStorageError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return _valid_receipt(value, session_id=session_id, tool_use_id=tool_use_id, now=int(time.time()) if now is None else now)

    def record_marker(self, record: dict[str, Any], *, now: int | None = None) -> None:
        current = int(time.time()) if now is None else now
        session_id, tool_use_id = record.get("session_id"), record.get("tool_use_id")
        valid = _valid_marker(record, session_id=session_id, tool_use_id=tool_use_id, now=current) if isinstance(session_id, str) and isinstance(tool_use_id, str) else None
        if valid is None:
            raise ValueError("spawn PostToolUse probe marker invalid")
        prepare_private_directory(self.markers_root)
        self._cleanup(self.markers_root, _valid_marker, now=current, expiry="expires_at")
        destination = self.markers_root / _filename(session_id, tool_use_id)
        if not destination.exists() and sum(1 for path in self.markers_root.glob("*.json") if path.is_file()) >= MAX_PROBE_RECORDS:
            raise PrivateStorageError("spawn PostToolUse probe marker capacity reached")
        if destination.exists():
            try:
                existing = _valid_marker(
                    self._read(destination, "spawn PostToolUse probe marker"),
                    session_id=session_id, tool_use_id=tool_use_id, now=0,
                )
            except (PrivateStorageError, UnicodeDecodeError, json.JSONDecodeError):
                existing = None
            owner_fields = ("task_id", "attempt", "task_ref", "dispatch_operation", "spawn_retry_count", "claimed_at")
            if existing is None or any(existing[field] != valid[field] for field in owner_fields):
                raise PrivateStorageError("spawn PostToolUse probe marker owner mismatch")
        self._write(self.markers_root, destination, valid, "spawn PostToolUse probe marker")

    def record_receipt(self, record: dict[str, Any], *, now: int | None = None, tool_use_id: str | None = None) -> None:
        current = int(time.time()) if now is None else now
        session_id = record.get("session_id")
        locator = tool_use_id or ""
        if not isinstance(session_id, str) or not isinstance(locator, str) or not locator:
            raise ValueError("spawn PostToolUse probe receipt requires an exact locator")
        valid = _valid_receipt(record, session_id=session_id, tool_use_id=locator, now=current)
        if valid is None:
            raise ValueError("spawn PostToolUse probe receipt invalid")
        prepare_private_directory(self.receipts_root)
        self._cleanup(self.receipts_root, _valid_receipt, now=current, expiry="updated_at")
        destination = self.receipts_root / _filename(session_id, locator)
        if not destination.exists() and sum(1 for path in self.receipts_root.glob("*.json") if path.is_file()) >= MAX_PROBE_RECORDS:
            raise PrivateStorageError("spawn PostToolUse probe receipt capacity reached")
        if destination.exists():
            try:
                existing = _valid_receipt(
                    self._read(destination, "spawn PostToolUse probe receipt"),
                    session_id=session_id, tool_use_id=locator, now=0,
                )
            except (PrivateStorageError, UnicodeDecodeError, json.JSONDecodeError):
                existing = None
            owner_fields = ("task_id", "attempt", "task_ref", "dispatch_operation", "spawn_retry_count")
            if existing is None or any(existing[field] != valid[field] for field in owner_fields):
                raise PrivateStorageError("spawn PostToolUse probe receipt owner mismatch")
        self._write(self.receipts_root, destination, valid, "spawn PostToolUse probe receipt")

    def remove_marker(self, session_id: str, tool_use_id: str) -> None:
        """Explicit exact cleanup only; lookup never repairs or removes records."""
        try:
            (self.markers_root / _filename(session_id, tool_use_id)).unlink()
        except FileNotFoundError:
            return

    def cleanup_expired_markers(self, *, now: int | None = None) -> int:
        return self._cleanup(self.markers_root, _valid_marker, now=int(time.time()) if now is None else now, expiry="expires_at")

    def cleanup_expired_receipts(self, *, now: int | None = None) -> int:
        return self._cleanup(self.receipts_root, _valid_receipt, now=int(time.time()) if now is None else now, expiry="updated_at")

    def list_receipts(self, session_id: str, *, now: int | None = None) -> list[dict[str, Any]]:
        if not session_id or not self.receipts_root.is_dir():
            return []
        current = int(time.time()) if now is None else now
        values = []
        for path in list(self.receipts_root.glob("*.json"))[:MAX_PROBE_RECORDS]:
            try:
                value = self._read(path, "spawn PostToolUse probe receipt")
                valid = _valid_receipt(value, session_id=session_id, tool_use_id="receipt-locator", now=current)
                if valid is not None:
                    values.append(valid)
            except (PrivateStorageError, UnicodeDecodeError, json.JSONDecodeError, FileNotFoundError):
                continue
        return sorted(values, key=lambda value: (value["updated_at"], value["task_id"], value["attempt"]))


__all__ = [
    "MARKER_DIRECTORY", "MARKER_TTL_SECONDS", "MAX_PROBE_RECORDS", "PROBE_FORMAT_VERSION",
    "PROBE_INDEX_FORMAT_VERSION", "RECEIPT_DIRECTORY", "RECEIPT_TTL_SECONDS", "SpawnPostProbeStore",
    "marker_record", "probe_root_for_store", "receipt_record",
]
