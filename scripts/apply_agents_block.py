#!/usr/bin/env python3
"""Check or atomically replace the managed subagent-governance AGENTS.md block."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import os
import stat
import sys
import tempfile
from pathlib import Path

START_MARKER = "<!-- subagent-governance:start -->"
END_MARKER = "<!-- subagent-governance:end -->"


def managed_span(text: str, label: str = "AGENTS.md") -> tuple[int, int]:
    if text.count(START_MARKER) != 1 or text.count(END_MARKER) != 1:
        raise RuntimeError(f"{label}必须包含且只能包含一对子 Agent 治理标记")
    start = text.index(START_MARKER)
    end_start = text.index(END_MARKER)
    if end_start < start:
        raise RuntimeError(f"{label}的结束标记必须位于开始标记之后")
    end = end_start + len(END_MARKER)
    return start, end


def content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _reject_unsafe_permissions(metadata: os.stat_result, label: str, path: Path) -> None:
    if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o022:
        raise PermissionError(f"{label}不能允许组用户或其他用户写入：{path}")


def _owned_by_current_user(metadata: os.stat_result) -> bool:
    getuid = getattr(os, "getuid", None)
    return getuid is None or getattr(metadata, "st_uid", getuid()) == getuid()


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _owned_directory(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label}不存在：{path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"{label}必须是普通目录且不能是符号链接：{path}")
    if not _owned_by_current_user(metadata):
        raise PermissionError(f"{label}不属于当前用户：{path}")
    _reject_unsafe_permissions(metadata, label, path)
    return metadata


def _owned_regular_file(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label}不存在：{path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"{label}必须是普通文件且不能是符号链接：{path}")
    if not _owned_by_current_user(metadata):
        raise PermissionError(f"{label}不属于当前用户：{path}")
    _reject_unsafe_permissions(metadata, label, path)
    return metadata


def atomic_write(path: Path, content: str, expected_digest: str | None = None) -> None:
    parent_metadata = _owned_directory(path.parent, "AGENTS.md 父目录")
    metadata = _owned_regular_file(path, "AGENTS.md")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        fchmod = getattr(os, "fchmod", None)
        if fchmod is not None:
            fchmod(descriptor, stat.S_IMODE(metadata.st_mode))
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        _owned_regular_file(path, "AGENTS.md")
        current_parent_metadata = _owned_directory(path.parent, "AGENTS.md 父目录")
        if (
            current_parent_metadata.st_dev != parent_metadata.st_dev
            or current_parent_metadata.st_ino != parent_metadata.st_ino
        ):
            raise RuntimeError(f"AGENTS.md 父目录在读取后发生变化，已停止覆盖：{path.parent}")
        if expected_digest is not None:
            current = path.read_text(encoding="utf-8")
            if content_digest(current) != expected_digest:
                raise RuntimeError(f"AGENTS.md 在读取后发生变化，已停止覆盖：{path}")
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _managed_block(text: str, label: str, require_entire_file: bool = False) -> str:
    start, end = managed_span(text, label)
    if require_entire_file and (text[:start].strip() or text[end:].strip()):
        raise RuntimeError(f"{label}只能包含治理标记区间，不能包含额外内容")
    return text[start:end].strip()


def _print_check_diagnostics(agents_path: Path, asset_path: Path, current: str, expected: str) -> None:
    print(f"agents_file: {agents_path}")
    print(f"asset_file: {asset_path}")
    current_digest = content_digest(current)
    expected_digest = content_digest(expected)
    if current_digest == expected_digest:
        print(f"managed_sha256: {current_digest}")
    else:
        print(f"agents_managed_sha256: {current_digest}")
        print(f"asset_managed_sha256: {expected_digest}")


def _print_managed_diff(current: str, expected: str) -> None:
    difference = difflib.unified_diff(
        current.splitlines(keepends=True),
        expected.splitlines(keepends=True),
        fromfile="current managed block",
        tofile="asset managed block",
    )
    rendered = "".join(difference)
    if rendered:
        print(rendered, end="" if rendered.endswith("\n") else "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--execute", action="store_true")
    action.add_argument("--remove", action="store_true")
    parser.add_argument("--diff", action="store_true", help="显示受管理区间的 unified diff")
    parser.add_argument("--agents-file", type=Path, default=Path.home() / ".codex/AGENTS.md")
    parser.add_argument(
        "--asset",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "assets/agents-governance.md",
    )
    args = parser.parse_args()

    agents_path = args.agents_file.expanduser().absolute()
    asset_path = args.asset.expanduser().absolute()
    try:
        _owned_directory(agents_path.parent, "AGENTS.md 父目录")
        _owned_directory(asset_path.parent, "治理规则资产父目录")
        _owned_regular_file(asset_path, "治理规则资产")
        asset_text = asset_path.read_text(encoding="utf-8").strip()
        expected = _managed_block(asset_text, "资产文件", require_entire_file=True)
        if not agents_path.exists():
            if args.check or args.remove:
                print(f"AGENTS.md does not contain the governance block: {agents_path}")
                return 1 if args.check else 0
            descriptor = os.open(agents_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(expected + "\n")
                output.flush()
                os.fsync(output.fileno())
            _sync_directory(agents_path.parent)
            print(f"initialized governance block: {agents_path}")
            return 0

        _owned_regular_file(agents_path, "AGENTS.md")
        agents_text = agents_path.read_text(encoding="utf-8")
        marker_count = agents_text.count(START_MARKER) + agents_text.count(END_MARKER)
        if marker_count == 0:
            if args.check or args.remove:
                print(f"AGENTS.md does not contain the governance block: {agents_path}")
                return 1 if args.check else 0
            separator = "" if not agents_text else ("" if agents_text.endswith("\n\n") else "\n" if agents_text.endswith("\n") else "\n\n")
            atomic_write(
                agents_path,
                agents_text + separator + expected + "\n",
                expected_digest=content_digest(agents_text),
            )
            print(f"initialized governance block: {agents_path}")
            return 0

        start, end = managed_span(agents_text)
        current = agents_text[start:end].strip()
        if args.remove:
            before = agents_text[:start].rstrip("\n")
            after = agents_text[end:].lstrip("\n")
            remaining = "\n\n".join(part for part in (before, after) if part)
            if remaining:
                remaining += "\n"
            atomic_write(
                agents_path,
                remaining,
                expected_digest=content_digest(agents_text),
            )
            print(f"removed governance block: {agents_path}")
            return 0
        matches = current == expected
        if args.check:
            print("agents governance block matches asset" if matches else "agents governance block differs from asset")
            _print_check_diagnostics(agents_path, asset_path, current, expected)
            if args.diff and not matches:
                _print_managed_diff(current, expected)
            return 0 if matches else 1

        if matches:
            print(f"governance block already matches asset: {agents_path}")
            return 0
        if args.diff:
            _print_managed_diff(current, expected)
        replacement = agents_text[:start] + expected + agents_text[end:]
        atomic_write(agents_path, replacement, expected_digest=content_digest(agents_text))
        print(f"updated governance block: {agents_path}")
        return 0
    except (OSError, RuntimeError, UnicodeError) as exc:
        print(f"apply_agents_block failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
