"""Shared private-file primitives for governance persistence stores."""

from __future__ import annotations

import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator


class PrivateStorageError(RuntimeError):
    """A private persistence operation failed its filesystem boundary."""


class PrivateStorageCapacityError(PrivateStorageError):
    """A private persistence file exceeded its byte admission limit."""


class PrivateStorageWriteError(PrivateStorageError):
    """A private persistence file could not be atomically written."""


@contextmanager
def locked_file(
    lock_path: Path,
    *,
    label: str,
    exclusive_lock: Callable,
    restrict_descriptor: Callable[[int, int], None],
    owned_by_current_user: Callable,
) -> Iterator[None]:
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise PrivateStorageError(f"{label} 锁文件无法安全打开：{lock_path}") from exc
    with os.fdopen(descriptor, "a+", encoding="utf-8") as lock_file:
        metadata = os.fstat(lock_file.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise PrivateStorageError(f"{label} 锁文件必须是普通文件：{lock_path}")
        if not owned_by_current_user(metadata):
            raise PrivateStorageError(f"{label} 锁文件不属于当前用户：{lock_path}")
        restrict_descriptor(lock_file.fileno(), 0o600)
        with exclusive_lock(lock_file):
            yield


def read_private_bytes(
    path: Path,
    *,
    label: str,
    max_bytes: int,
    owned_by_current_user: Callable,
    private_permissions_safe: Callable,
    error_factory: Callable[[str, str], Exception] | None = None,
) -> bytes:
    def storage_error(code: str, message: str, *, capacity: bool = False) -> Exception:
        if error_factory is not None:
            return error_factory(code, message)
        return PrivateStorageCapacityError(message) if capacity else PrivateStorageError(message)

    try:
        metadata = path.lstat()
    except FileNotFoundError:
        raise
    if stat.S_ISLNK(metadata.st_mode):
        raise storage_error("symlink", f"{label} 必须是普通文件且不能是符号链接：{path}")
    if not stat.S_ISREG(metadata.st_mode):
        raise storage_error("not_regular", f"{label} 必须是普通文件：{path}")
    if not owned_by_current_user(metadata):
        raise storage_error("owner_mismatch", f"{label} 所有者不安全：{path}")
    if not private_permissions_safe(metadata):
        raise storage_error("permissions_unsafe", f"{label} 权限不安全：{path}")
    if metadata.st_size > max_bytes:
        raise storage_error("oversized", f"{label} 超过大小上限：{path}", capacity=True)

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise storage_error("unreadable", f"{label} 无法安全打开：{path}") from exc
    descriptor_open = True
    try:
        try:
            with os.fdopen(descriptor, "rb") as private_file:
                descriptor_open = False
                opened_metadata = os.fstat(private_file.fileno())
                if stat.S_ISLNK(opened_metadata.st_mode):
                    raise storage_error("symlink", f"{label} 必须是普通文件且不能是符号链接：{path}")
                if not stat.S_ISREG(opened_metadata.st_mode):
                    raise storage_error("not_regular", f"{label} 必须是普通文件：{path}")
                if not owned_by_current_user(opened_metadata):
                    raise storage_error("owner_mismatch", f"{label} 所有者不安全：{path}")
                if not private_permissions_safe(opened_metadata):
                    raise storage_error("permissions_unsafe", f"{label} 权限不安全：{path}")
                raw = private_file.read(max_bytes + 1)
        except OSError as exc:
            raise storage_error("unreadable", f"{label} 无法读取：{path}") from exc
    finally:
        if descriptor_open:
            os.close(descriptor)
    if len(raw) > max_bytes:
        raise storage_error("oversized", f"{label} 超过大小上限：{path}", capacity=True)
    return raw


def atomic_write_bytes(
    path: Path,
    encoded: bytes,
    *,
    label: str,
    restrict_descriptor: Callable[[int, int], None],
    sync_directory: Callable[[Path], None],
) -> None:
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
    except OSError as exc:
        raise PrivateStorageWriteError(
            f"无法在 {label} 目录创建临时文件：{path.parent}"
        ) from exc
    temporary = Path(temporary_name)
    descriptor_open = True
    try:
        try:
            restrict_descriptor(descriptor, 0o600)
            temporary_stream = os.fdopen(descriptor, "wb")
            descriptor_open = False
            with temporary_stream as temporary_file:
                temporary_file.write(encoded)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary, path)
            sync_directory(path.parent)
        except OSError as exc:
            raise PrivateStorageWriteError(f"{label} 原子替换失败：{path}") from exc
    finally:
        if descriptor_open:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
