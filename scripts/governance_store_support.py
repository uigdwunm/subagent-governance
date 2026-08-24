"""Filesystem-only support for governance persistence stores.

This module deliberately has no task, activity, lifecycle, or runtime-entrypoint
dependencies.  Importing it is side-effect free; constructors call
``prepare_private_directory`` when they are ready to create storage.
"""

from __future__ import annotations

import getpass
import hashlib
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping, TextIO

try:
    from scripts.governance_semantics import STATE_STORAGE_NAMESPACE
except ModuleNotFoundError:
    from governance_semantics import STATE_STORAGE_NAMESPACE

if os.name == "nt":
    import msvcrt

    fcntl = None
else:
    import fcntl

    msvcrt = None


def current_uid() -> int | None:
    getuid = getattr(os, "getuid", None)
    return int(getuid()) if getuid is not None else None


def owned_by_current_user(metadata: os.stat_result) -> bool:
    uid = current_uid()
    return uid is None or getattr(metadata, "st_uid", uid) == uid


def private_permissions_safe(metadata: os.stat_result) -> bool:
    return os.name == "nt" or stat.S_IMODE(metadata.st_mode) & 0o077 == 0


def restrict_descriptor(descriptor: int, mode: int) -> None:
    fchmod = getattr(os, "fchmod", None)
    if fchmod is not None:
        fchmod(descriptor, mode)


def restrict_path(path: Path, mode: int) -> None:
    if os.name != "nt":
        path.chmod(mode)


def sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def uses_windows_file_lock() -> bool:
    return os.name == "nt"


@contextmanager
def exclusive_file_lock(lock_file: TextIO) -> Iterator[None]:
    descriptor = lock_file.fileno()
    if uses_windows_file_lock():
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write("\0")
            lock_file.flush()
            os.fsync(descriptor)
        lock_file.seek(0)
        assert msvcrt is not None
        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            lock_file.seek(0)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    assert fcntl is not None
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


def user_storage_key() -> str:
    uid = current_uid()
    if uid is not None:
        return str(uid)
    username = os.environ.get("USERNAME") or getpass.getuser() or "user"
    return hashlib.sha256(username.encode("utf-8")).hexdigest()[:12]


def safe_filename(value: str) -> str:
    raw = value or "unknown"
    prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")[:64] or "unknown"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def prepare_private_directory(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"治理状态目录必须是普通目录且不能是符号链接：{root}")
    if not owned_by_current_user(metadata):
        raise PermissionError(f"治理状态目录不属于当前用户：{root}")
    restrict_path(root, 0o700)
    return root


def installed_plugin_data_root(module_path: Path | str) -> Path | None:
    """Resolve a cache-installed plugin module without relying on its filename."""
    resolved = Path(module_path).resolve(strict=False)
    parts = resolved.parts
    for index in range(len(parts) - 5):
        if parts[index : index + 2] != ("plugins", "cache"):
            continue
        marketplace, plugin_name, _version, scripts_directory = parts[
            index + 2 : index + 6
        ]
        if not marketplace or not plugin_name or not _version or scripts_directory != "scripts":
            continue
        return (
            Path(*parts[:index])
            / "plugins"
            / "data"
            / f"{plugin_name}-{marketplace}"
            / STATE_STORAGE_NAMESPACE
        )
    return None


def is_developer_module(module_path: Path | str) -> bool:
    resolved = Path(module_path).resolve(strict=False)
    scripts_root = resolved.parent
    repository_root = scripts_root.parent
    return (
        scripts_root.name == "scripts"
        and (repository_root / "AGENTS.md").is_file()
        and (repository_root / "schemas").is_dir()
    )


def data_root_path(
    module_path: Path | str,
    *,
    environment: Mapping[str, str] | None = None,
    temporary_directory: Path | str | None = None,
) -> Path:
    """Choose the sole current-state namespace without creating it.

    Environment roots take priority.  Otherwise a cache-installed plugin receives
    its plugin data root, while developer and uninstalled modules use an isolated
    per-user temporary root.  No legacy namespace is inspected or selected.
    """
    source = os.environ if environment is None else environment
    override = source.get("SUBAGENT_GOVERNANCE_DATA")
    plugin_data = source.get("PLUGIN_DATA")
    if override:
        return Path(override).expanduser()
    if plugin_data:
        return Path(plugin_data).expanduser() / STATE_STORAGE_NAMESPACE
    installed_root = installed_plugin_data_root(module_path)
    if installed_root is not None:
        return installed_root
    temporary_root = (
        Path(tempfile.gettempdir())
        if temporary_directory is None
        else Path(temporary_directory)
    )
    temporary_data_root = (
        temporary_root
        / f"subagent-governance-{user_storage_key()}"
        / STATE_STORAGE_NAMESPACE
    )
    # Developer repositories deliberately retain the same isolated temporary
    # layout as an uninstalled module; they are never mistaken for a cache.
    if is_developer_module(module_path):
        return temporary_data_root
    return temporary_data_root
