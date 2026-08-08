#!/usr/bin/env python3
"""Check or atomically replace the managed subagent-governance AGENTS.md block."""

from __future__ import annotations

import argparse
import os
import stat
import tempfile
from pathlib import Path


START_MARKER = "<!-- subagent-governance:start -->"
END_MARKER = "<!-- subagent-governance:end -->"


def managed_span(text: str) -> tuple[int, int]:
    if text.count(START_MARKER) != 1 or text.count(END_MARKER) != 1:
        raise RuntimeError("AGENTS.md 必须包含且只能包含一对子 Agent 治理标记")
    start = text.index(START_MARKER)
    end = text.index(END_MARKER, start) + len(END_MARKER)
    return start, end


def atomic_write(path: Path, content: str) -> None:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"AGENTS.md 必须是普通文件且不能是符号链接：{path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, stat.S_IMODE(metadata.st_mode))
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--execute", action="store_true")
    parser.add_argument("--agents-file", type=Path, default=Path.home() / ".codex/AGENTS.md")
    parser.add_argument(
        "--asset",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "assets/agents-governance.md",
    )
    args = parser.parse_args()

    agents_path = args.agents_file.expanduser().absolute()
    asset_path = args.asset.expanduser().absolute()
    agents_text = agents_path.read_text(encoding="utf-8")
    asset_text = asset_path.read_text(encoding="utf-8").strip()
    start, end = managed_span(agents_text)
    managed_span(asset_text)
    current = agents_text[start:end].strip()
    if args.check:
        if current == asset_text:
            print("agents governance block matches asset")
            return 0
        print("agents governance block differs from asset")
        return 1

    replacement = agents_text[:start] + asset_text + agents_text[end:]
    atomic_write(agents_path, replacement)
    print(f"updated governance block: {agents_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
