"""Strict v6 StateStore persistence, independent of the runtime entrypoint."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    from scripts.governance_errors import (
        StateCapacityError,
        StateConflictError,
        StateStoreError,
        StateValidationError,
        StateWriteError,
    )
    from scripts.governance_semantics import (
        MAX_STATE_BYTES,
        NEW_TASK_SOFT_LIMIT_BYTES,
        RETENTION_SECONDS,
        STATE_FORMAT_VERSION,
    )
    from scripts.governance_state import (
        parse_tombstone_key,
        require_current_state_format,
    )
    from scripts.governance_storage import (
        PrivateStorageCapacityError,
        PrivateStorageError,
        PrivateStorageWriteError,
        atomic_write_bytes,
        locked_file,
        read_private_bytes,
    )
    from scripts.governance_store_support import (
        data_root_path,
        exclusive_file_lock,
        owned_by_current_user,
        prepare_private_directory,
        private_permissions_safe,
        restrict_descriptor,
        safe_filename,
        sync_directory,
    )
except ModuleNotFoundError:
    from governance_errors import (
        StateCapacityError,
        StateConflictError,
        StateStoreError,
        StateValidationError,
        StateWriteError,
    )
    from governance_semantics import (
        MAX_STATE_BYTES,
        NEW_TASK_SOFT_LIMIT_BYTES,
        RETENTION_SECONDS,
        STATE_FORMAT_VERSION,
    )
    from governance_state import parse_tombstone_key, require_current_state_format
    from governance_storage import (
        PrivateStorageCapacityError,
        PrivateStorageError,
        PrivateStorageWriteError,
        atomic_write_bytes,
        locked_file,
        read_private_bytes,
    )
    from governance_store_support import (
        data_root_path,
        exclusive_file_lock,
        owned_by_current_user,
        prepare_private_directory,
        private_permissions_safe,
        restrict_descriptor,
        safe_filename,
        sync_directory,
    )


def _now() -> int:
    return int(time.time())


class StateStore:
    def __init__(self, root: Path | None = None):
        target = root if root is not None else data_root_path(Path(__file__)) / "sessions"
        self.root = prepare_private_directory(target)
        self.last_warning: str | None = None

    @staticmethod
    def _empty_state(session_id: str) -> dict[str, Any]:
        return {
            "state_format_version": STATE_FORMAT_VERSION,
            "session_id": session_id,
            "tasks": {},
            "agents": {},
            "health": {"status": "ok"},
            "tombstones": {},
            "groups": {},
        }

    def _paths(self, session_id: str) -> tuple[Path, Path]:
        stem = safe_filename(session_id)
        return self.root / f"{stem}.json", self.root / f"{stem}.lock"

    @contextmanager
    def _lock(self, session_id: str) -> Iterator[Path]:
        state_path, lock_path = self._paths(session_id)
        try:
            with locked_file(
                lock_path,
                label="治理",
                exclusive_lock=exclusive_file_lock,
                restrict_descriptor=restrict_descriptor,
                owned_by_current_user=owned_by_current_user,
            ):
                yield state_path
        except PrivateStorageError as exc:
            raise StateValidationError(str(exc)) from exc

    @staticmethod
    def _validate_required_fields(
        value: dict[str, Any], required_fields: tuple[str, ...], path: Path
    ) -> None:
        missing = [field_name for field_name in required_fields if field_name not in value]
        if missing:
            raise StateValidationError(
                f"治理状态缺少当前操作必需字段 {', '.join(missing)}：{path}"
            )
        for field_name in required_fields:
            if field_name in {"tasks", "agents", "health", "tombstones", "groups"} and not isinstance(value.get(field_name), dict):
                raise StateValidationError(f"治理状态字段 {field_name} 必须是对象：{path}")

    @classmethod
    def _validate_state(
        cls, value: Any, session_id: str, path: Path, required_fields: tuple[str, ...]
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
        self, path: Path, session_id: str, required_fields: tuple[str, ...] = ("tasks", "agents")
    ) -> dict[str, Any]:
        try:
            raw = read_private_bytes(
                path,
                label="治理状态文件",
                max_bytes=MAX_STATE_BYTES,
                owned_by_current_user=owned_by_current_user,
                private_permissions_safe=private_permissions_safe,
            )
        except FileNotFoundError:
            return self._validate_state(self._empty_state(session_id), session_id, path, required_fields)
        except PrivateStorageCapacityError as exc:
            raise StateCapacityError(str(exc)) from exc
        except PrivateStorageError as exc:
            raise StateValidationError(str(exc)) from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise StateValidationError(
                f"治理状态文件不是有效 UTF-8 JSON，原文件已保留供人工恢复：{path}"
            ) from exc
        return require_current_state_format(
            self._validate_state(value, session_id, path, required_fields)
        )

    @staticmethod
    def _encoded_state(state: dict[str, Any]) -> bytes:
        try:
            content = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        except (TypeError, ValueError) as exc:
            raise StateValidationError("治理状态包含无法序列化的值") from exc
        return content.encode("utf-8")

    def _write_path(
        self, path: Path, session_id: str, state: dict[str, Any], *, required_fields: tuple[str, ...], admission: str
    ) -> None:
        stored_state = require_current_state_format(
            self._validate_state(state, session_id, path, required_fields)
        )
        encoded = self._encoded_state(stored_state)
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
            verified = self._read_path(path, session_id, required_fields)
        except StateStoreError as exc:
            raise StateWriteError(f"治理状态写入后回读失败：{path}") from exc
        if verified != stored_state:
            raise StateWriteError(f"治理状态写入后回读内容不一致：{path}")

    def compare_and_set(
        self, session_id: str, predicate: Callable[[dict[str, Any]], bool], callback: Callable[[dict[str, Any]], Any], *,
        required_fields: tuple[str, ...] = ("tasks", "agents"), admission: str = "existing",
    ) -> Any:
        self.last_warning = None
        with self._lock(session_id) as state_path:
            state = self._read_path(state_path, session_id, required_fields)
            if not predicate(state):
                raise StateConflictError(f"治理状态 compare-and-set 冲突：{session_id}")
            result = callback(state)
            self._write_path(state_path, session_id, state, required_fields=required_fields, admission=admission)
            return result

    def update(self, session_id: str, callback: Callable[[dict[str, Any]], Any], *, required_fields: tuple[str, ...] = ("tasks", "agents"), admission: str = "existing") -> Any:
        return self.compare_and_set(session_id, lambda _state: True, callback, required_fields=required_fields, admission=admission)

    def read(self, session_id: str, *, required_fields: tuple[str, ...] = ("tasks", "agents")) -> dict[str, Any]:
        self.last_warning = None
        with self._lock(session_id) as state_path:
            return self._read_path(state_path, session_id, required_fields)

    def delete(self, session_id: str) -> None:
        self.delete_if(session_id, lambda _state: True)

    def delete_if(self, session_id: str, predicate: Callable[[dict[str, Any]], bool], *, required_fields: tuple[str, ...] = ("tasks", "agents")) -> bool:
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

    def cleanup_expired_tombstones(self, session_id: str, *, now: int | None = None) -> list[tuple[str, int]]:
        cutoff = (self._now() if now is None else now) - int(RETENTION_SECONDS["tombstone"])

        def cleanup(state: dict[str, Any]) -> list[tuple[str, int]]:
            tombstones = state["tombstones"]
            expired: list[tuple[str, str, int]] = []
            for key, record in tombstones.items():
                if not isinstance(record, dict):
                    raise StateValidationError(f"tombstone {key} 必须是对象")
                missing = [field_name for field_name in ("close_reason", "closed_at") if field_name not in record]
                if missing:
                    raise StateValidationError(f"tombstone {key} 缺少字段 {', '.join(missing)}")
                close_reason, closed_at = record.get("close_reason"), record.get("closed_at")
                if not isinstance(close_reason, str) or not close_reason.strip():
                    raise StateValidationError(f"tombstone {key} 的 close_reason 无效")
                if isinstance(closed_at, bool) or not isinstance(closed_at, int):
                    raise StateValidationError(f"tombstone {key} 的 closed_at 无效")
                identity = parse_tombstone_key(key)
                if identity is None:
                    raise StateValidationError(f"tombstone {key} 的身份键无效")
                task_id, attempt = identity
                if closed_at <= cutoff:
                    expired.append((str(key), task_id, attempt))
            for key, _task_id, _attempt in expired:
                tombstones.pop(key)
            return [(task_id, attempt) for _key, task_id, attempt in expired]

        return self.update(session_id, cleanup, required_fields=("tombstones",))

    _now = staticmethod(_now)


class UnavailableStateStore:
    """Failing store used to preserve Hook behavior when state setup is unavailable."""

    def __init__(self, error: Exception):
        self.error = error
        self.last_warning = f"治理状态不可用，已降级放行：{error}"

    def _raise(self) -> None:
        raise OSError(str(self.error)) from self.error

    def compare_and_set(self, session_id: str, predicate: Callable[[dict[str, Any]], bool], callback: Callable[[dict[str, Any]], Any], *, required_fields: tuple[str, ...] = ("tasks", "agents"), admission: str = "existing") -> Any:
        self._raise()

    def update(self, session_id: str, callback: Callable[[dict[str, Any]], Any], *, required_fields: tuple[str, ...] = ("tasks", "agents"), admission: str = "existing") -> Any:
        self._raise()

    def read(self, session_id: str, *, required_fields: tuple[str, ...] = ("tasks", "agents")) -> dict[str, Any]:
        self._raise()

    def delete(self, session_id: str) -> None:
        self._raise()

    def delete_if(self, session_id: str, predicate: Callable[[dict[str, Any]], bool], *, required_fields: tuple[str, ...] = ("tasks", "agents")) -> bool:
        self._raise()

    def cleanup_expired_tombstones(self, session_id: str, *, now: int | None = None) -> list[tuple[str, int]]:
        self._raise()
