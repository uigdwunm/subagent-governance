"""Atomic persistence for the single current-only state-v9 Session ledger."""

from __future__ import annotations

import json
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    from scripts.governance_errors import (
        StateCapacityError, StateConflictError, StateStoreError,
        StateValidationError, StateWriteError,
    )
    from scripts.governance_semantics import (
        MAX_STATE_BYTES, NEW_TASK_SOFT_LIMIT_BYTES, STATE_FORMAT_VERSION,
    )
    from scripts.governance_state import require_current_state_format
    from scripts.governance_storage import (
        PrivateStorageCapacityError, PrivateStorageError, PrivateStorageWriteError,
        atomic_write_bytes, locked_file, read_private_bytes,
    )
    from scripts.governance_store_support import (
        data_root_path, exclusive_file_lock, owned_by_current_user,
        prepare_private_directory, private_permissions_safe, restrict_descriptor,
        safe_filename, sync_directory,
    )
except ModuleNotFoundError:
    from governance_errors import StateCapacityError, StateConflictError, StateStoreError, StateValidationError, StateWriteError
    from governance_semantics import MAX_STATE_BYTES, NEW_TASK_SOFT_LIMIT_BYTES, STATE_FORMAT_VERSION
    from governance_state import require_current_state_format
    from governance_storage import PrivateStorageCapacityError, PrivateStorageError, PrivateStorageWriteError, atomic_write_bytes, locked_file, read_private_bytes
    from governance_store_support import data_root_path, exclusive_file_lock, owned_by_current_user, prepare_private_directory, private_permissions_safe, restrict_descriptor, safe_filename, sync_directory


def _empty_state(session_id: str) -> dict[str, Any]:
    return {"state_format_version": STATE_FORMAT_VERSION, "session_id": session_id, "tasks": {}}


def _paths(root: Path, session_id: str) -> tuple[Path, Path]:
    stem = safe_filename(session_id)
    return root / f"{stem}.json", root / f"{stem}.lock"


def _decode_state(raw: bytes, session_id: str, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise StateValidationError(
            f"治理状态文件不是有效 UTF-8 JSON，原文件已保留供人工恢复：{path}"
        ) from exc
    if not isinstance(value, dict) or value.get("session_id") != session_id:
        raise StateValidationError(f"治理状态文件与当前 session 不匹配：{path}")
    return require_current_state_format(value)


def read_ledger_readonly(root: Path, session_id: str) -> dict[str, Any] | None:
    """Read one exact Session without creating directories, locks, or files."""
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    try:
        metadata = root.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise StateValidationError(f"治理只读目录必须是普通目录且不能是符号链接：{root}")
    if not owned_by_current_user(metadata) or not private_permissions_safe(metadata):
        raise StateValidationError(f"治理只读目录 owner/permission 不安全：{root}")
    state_path, _lock_path = _paths(root, session_id)
    try:
        raw = read_private_bytes(
            state_path, label="治理状态文件", max_bytes=MAX_STATE_BYTES,
            owned_by_current_user=owned_by_current_user,
            private_permissions_safe=private_permissions_safe,
        )
    except FileNotFoundError:
        return None
    except PrivateStorageCapacityError as exc:
        raise StateCapacityError(str(exc)) from exc
    except PrivateStorageError as exc:
        raise StateValidationError(str(exc)) from exc
    return _decode_state(raw, session_id, state_path)


class StateStore:
    def __init__(self, root: Path | None = None):
        target = root if root is not None else data_root_path(Path(__file__)) / "sessions"
        self.root = prepare_private_directory(target)
        self.last_warning: str | None = None

    _empty_state = staticmethod(_empty_state)

    def _paths(self, session_id: str) -> tuple[Path, Path]:
        return _paths(self.root, session_id)

    @contextmanager
    def _lock(self, session_id: str) -> Iterator[Path]:
        state_path, lock_path = self._paths(session_id)
        try:
            with locked_file(
                lock_path, label="治理", exclusive_lock=exclusive_file_lock,
                restrict_descriptor=restrict_descriptor,
                owned_by_current_user=owned_by_current_user,
            ):
                yield state_path
        except PrivateStorageError as exc:
            raise StateValidationError(str(exc)) from exc

    def _read_path(self, path: Path, session_id: str) -> dict[str, Any]:
        try:
            raw = read_private_bytes(
                path, label="治理状态文件", max_bytes=MAX_STATE_BYTES,
                owned_by_current_user=owned_by_current_user,
                private_permissions_safe=private_permissions_safe,
            )
        except FileNotFoundError:
            return _empty_state(session_id)
        except PrivateStorageCapacityError as exc:
            raise StateCapacityError(str(exc)) from exc
        except PrivateStorageError as exc:
            raise StateValidationError(str(exc)) from exc
        return _decode_state(raw, session_id, path)

    @staticmethod
    def _encoded_state(state: dict[str, Any]) -> bytes:
        try:
            return (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise StateValidationError("治理状态包含无法序列化的值") from exc

    def _write_path(self, path: Path, session_id: str, state: dict[str, Any], *, admission: str) -> None:
        if state.get("session_id") != session_id:
            raise StateValidationError("治理状态 session_id 与写入目标不匹配")
        stored = require_current_state_format(state)
        encoded = self._encoded_state(stored)
        if admission not in {"existing", "new_task"}:
            raise StateValidationError("StateStore admission 必须是 existing 或 new_task")
        if admission == "new_task" and len(encoded) > NEW_TASK_SOFT_LIMIT_BYTES:
            raise StateCapacityError(f"新治理任务预计使状态超过 {NEW_TASK_SOFT_LIMIT_BYTES} 字节软准入线")
        if len(encoded) > MAX_STATE_BYTES:
            raise StateCapacityError(f"治理状态超过 {MAX_STATE_BYTES} 字节上限")
        try:
            atomic_write_bytes(
                path, encoded, label="治理状态", restrict_descriptor=restrict_descriptor,
                sync_directory=sync_directory,
            )
        except PrivateStorageWriteError as exc:
            raise StateWriteError(str(exc)) from exc
        try:
            verified = self._read_path(path, session_id)
        except StateStoreError as exc:
            raise StateWriteError(f"治理状态写入后回读失败：{path}") from exc
        if verified != stored:
            raise StateWriteError(f"治理状态写入后回读内容不一致：{path}")

    def compare_and_set(
        self, session_id: str, predicate: Callable[[dict[str, Any]], bool],
        callback: Callable[[dict[str, Any]], Any], *,
        required_fields: tuple[str, ...] = ("tasks",), admission: str = "existing",
    ) -> Any:
        del required_fields
        self.last_warning = None
        with self._lock(session_id) as state_path:
            state = self._read_path(state_path, session_id)
            if not predicate(state):
                raise StateConflictError(f"治理状态 compare-and-set 冲突：{session_id}")
            result = callback(state)
            self._write_path(state_path, session_id, state, admission=admission)
            return result

    def update(
        self, session_id: str, callback: Callable[[dict[str, Any]], Any], *,
        required_fields: tuple[str, ...] = ("tasks",), admission: str = "existing",
    ) -> Any:
        return self.compare_and_set(
            session_id, lambda _state: True, callback,
            required_fields=required_fields, admission=admission,
        )

    def read(self, session_id: str, *, required_fields: tuple[str, ...] = ("tasks",)) -> dict[str, Any]:
        del required_fields
        with self._lock(session_id) as state_path:
            return self._read_path(state_path, session_id)

    def delete(self, session_id: str) -> None:
        with self._lock(session_id) as state_path:
            try:
                state_path.unlink()
            except FileNotFoundError:
                return
            sync_directory(state_path.parent)

    def delete_if(
        self, session_id: str, predicate: Callable[[dict[str, Any]], bool], *,
        required_fields: tuple[str, ...] = ("tasks",),
    ) -> bool:
        del required_fields
        with self._lock(session_id) as state_path:
            state = self._read_path(state_path, session_id)
            if not predicate(state):
                return False
            try:
                state_path.unlink()
            except FileNotFoundError:
                return False
            sync_directory(state_path.parent)
            return True


class UnavailableStateStore:
    def __init__(self, error: Exception):
        self.error = error

    def _raise(self) -> None:
        raise OSError(str(self.error)) from self.error

    def compare_and_set(self, *args: Any, **kwargs: Any) -> Any:
        self._raise()

    def update(self, *args: Any, **kwargs: Any) -> Any:
        self._raise()

    def read(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._raise()


__all__ = ["StateStore", "UnavailableStateStore", "read_ledger_readonly"]
