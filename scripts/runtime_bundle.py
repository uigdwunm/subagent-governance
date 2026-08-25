#!/usr/bin/env python3
"""Build and verify the explicit Subagent Governance runtime projection."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path, PurePosixPath


MANIFEST_RELATIVE = Path(".codex-plugin/runtime-bundle.json")
FORMAT_VERSION = 1


def _ordinary_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"{label} 必须是普通目录且不能是符号链接：{path}")
    metadata = path.stat()
    getuid = getattr(os, "getuid", None)
    if getuid is not None and metadata.st_uid != getuid():
        raise PermissionError(f"{label} 必须由当前用户拥有：{path}")
    if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o022:
        raise PermissionError(f"{label} 不能允许组用户或其他用户写入：{path}")


def _ordinary_file(path: Path, label: str) -> None:
    if path.is_symlink():
        raise RuntimeError(f"{label} 不能是符号链接：{path}")
    if not path.is_file():
        raise RuntimeError(f"{label} 必须是普通文件：{path}")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"{label} 必须是普通文件：{path}")
    getuid = getattr(os, "getuid", None)
    if getuid is not None and metadata.st_uid != getuid():
        raise PermissionError(f"{label} 必须由当前用户拥有：{path}")
    if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o022:
        raise PermissionError(f"{label} 不能允许组用户或其他用户写入：{path}")


def _canonical_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeError("runtime allowlist path 必须是非空 POSIX 相对路径")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"runtime allowlist path 非法：{value!r}")
    canonical = path.as_posix()
    if canonical != value:
        raise RuntimeError(f"runtime allowlist path 必须是 canonical POSIX path：{value!r}")
    return canonical


def runtime_files(root: Path) -> tuple[str, ...]:
    root = root.expanduser().absolute()
    _ordinary_directory(root, "runtime bundle source")
    manifest_path = root / MANIFEST_RELATIVE
    _ordinary_file(manifest_path, "runtime allowlist manifest")
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"runtime allowlist manifest 无法读取：{manifest_path}") from exc
    if not isinstance(value, dict) or set(value) != {"format_version", "files"}:
        raise RuntimeError("runtime allowlist manifest 字段集合无效")
    if value.get("format_version") != FORMAT_VERSION or isinstance(
        value.get("format_version"), bool
    ):
        raise RuntimeError(f"runtime allowlist 只支持 format_version={FORMAT_VERSION}")
    raw_files = value.get("files")
    if not isinstance(raw_files, list):
        raise RuntimeError("runtime allowlist files 必须是数组")
    files = tuple(_canonical_relative(item) for item in raw_files)
    if not files or files != tuple(sorted(files)) or len(set(files)) != len(files):
        raise RuntimeError("runtime allowlist files 必须非空、排序且唯一")
    if MANIFEST_RELATIVE.as_posix() not in files:
        raise RuntimeError("runtime allowlist 必须包含自身 manifest")
    for relative in files:
        path = root
        parts = Path(relative).parts
        for part in parts[:-1]:
            path = path / part
            _ordinary_directory(path, f"allowlisted runtime parent {path.relative_to(root)}")
        _ordinary_file(root / Path(relative), f"allowlisted runtime file {relative}")
    return files


def bundle_digest(root: Path) -> str:
    root = root.expanduser().absolute()
    files = runtime_files(root)
    digest = hashlib.sha256()
    for relative in files:
        path = root / Path(relative)
        metadata = path.stat()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(oct(stat.S_IMODE(metadata.st_mode)).encode("ascii"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def verify_runtime_bundle(root: Path) -> str:
    """Require an exact allowlisted projection with no extra filesystem entries."""
    root = root.expanduser().absolute()
    files = set(runtime_files(root))
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"runtime bundle 中不允许符号链接：{path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise RuntimeError(f"runtime bundle 中只允许普通文件和目录：{path}")
        actual.add(path.relative_to(root).as_posix())
    if actual != files:
        missing = sorted(files - actual)
        extra = sorted(actual - files)
        raise RuntimeError(
            f"runtime bundle 文件集合不精确：missing={missing}；extra={extra}"
        )
    return bundle_digest(root)


def stage_runtime_bundle(source_root: Path, target_root: Path) -> str:
    source = source_root.expanduser().absolute()
    target = target_root.expanduser().absolute()
    files = runtime_files(source)
    _ordinary_directory(target.parent, "runtime bundle target parent")
    if target.exists() or target.is_symlink():
        raise RuntimeError(f"runtime bundle target 必须不存在：{target}")
    target.mkdir(mode=0o700)
    try:
        for relative in files:
            origin = source / Path(relative)
            destination = target / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, destination, follow_symlinks=False)
            _ordinary_file(destination, f"staged runtime file {relative}")
            if origin.read_bytes() != destination.read_bytes():
                raise RuntimeError(f"staged runtime file 内容不匹配：{relative}")
            if stat.S_IMODE(origin.stat().st_mode) != stat.S_IMODE(
                destination.stat().st_mode
            ):
                raise RuntimeError(f"staged runtime file mode 不匹配：{relative}")
        source_digest = bundle_digest(source)
        target_digest = verify_runtime_bundle(target)
        if source_digest != target_digest:
            raise RuntimeError("staged runtime bundle digest 与 source 不一致")
        return target_digest
    except BaseException:
        if target.exists() and not target.is_symlink():
            shutil.rmtree(target)
        raise


__all__ = [
    "bundle_digest", "runtime_files", "stage_runtime_bundle",
    "verify_runtime_bundle",
]
