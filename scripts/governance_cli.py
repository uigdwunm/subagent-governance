#!/usr/bin/env python3
"""Thin CLI transport for the current state-v9 dispatch slice."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import BinaryIO, TextIO

try:
    from scripts.governance_dispatch import confirm_dispatch, record_dispatch_result
    from scripts.governance_diagnostics import diagnose, status
    from scripts.governance_hook import handle_hook
    from scripts.governance_input import read_json_object
    from scripts.governance_protocol import prepare_dispatch
    from scripts.governance_state_store import StateStore
    from scripts.governance_store_support import data_root_path
except ModuleNotFoundError:
    from governance_dispatch import confirm_dispatch, record_dispatch_result
    from governance_diagnostics import diagnose, status
    from governance_hook import handle_hook
    from governance_input import read_json_object
    from governance_protocol import prepare_dispatch
    from governance_state_store import StateStore
    from governance_store_support import data_root_path


class NonExitingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _parser() -> NonExitingArgumentParser:
    parser = NonExitingArgumentParser(add_help=False)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare-dispatch", action="store_true")
    modes.add_argument("--confirm-dispatch", action="store_true")
    modes.add_argument("--record-dispatch-result", action="store_true")
    modes.add_argument("--status", action="store_true")
    modes.add_argument("--diagnose", action="store_true")
    parser.add_argument("--session")
    parser.add_argument("--data-root", type=Path)
    return parser


def _data_root(value: Path | None) -> Path:
    return value.expanduser() if value is not None else data_root_path(Path(__file__))


def _store(value: Path | None) -> StateStore:
    return StateStore(_data_root(value) / "sessions")


def _emit(stdout: TextIO, value: object, *, pretty: bool = True) -> None:
    stdout.write(json.dumps(value, ensure_ascii=False, indent=2 if pretty else None, sort_keys=pretty) + "\n")


def _hook(stdin: BinaryIO, stdout: TextIO) -> int:
    try:
        payload = read_json_object(stdin)
    except Exception as exc:
        _emit(stdout, {"continue": True, "systemMessage": f"Subagent Governance 输入解析失败，已 fail-open：{exc}"}, pretty=False)
        return 0
    try:
        result = handle_hook(payload)
    except Exception as exc:
        if payload.get("hook_event_name") == "PreToolUse":
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"governed spawn Hook 失败：{exc}",
                }
            }
        else:
            result = None
    if result is not None:
        _emit(stdout, result, pretty=False)
    return 0


def main(
    arguments: list[str] | None = None,
    *,
    stdin: BinaryIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdin, stdout, stderr = stdin or sys.stdin.buffer, stdout or sys.stdout, stderr or sys.stderr
    try:
        args, unknown = _parser().parse_known_args(sys.argv[1:] if arguments is None else arguments)
    except ValueError as exc:
        print(str(exc), file=stderr)
        return 2
    if unknown:
        print(f"unsupported arguments: {unknown}", file=stderr)
        return 2
    selected = any((args.prepare_dispatch, args.confirm_dispatch, args.record_dispatch_result, args.status, args.diagnose))
    if not selected:
        if args.session or args.data_root:
            print("--session/--data-root require an explicit command", file=stderr)
            return 2
        return _hook(stdin, stdout)
    if not args.session:
        print("operation requires --session", file=stderr)
        return 2
    root = _data_root(args.data_root)
    try:
        if args.status:
            result = status(args.session, root)
        elif args.diagnose:
            result = diagnose(args.session, root)
        else:
            value = read_json_object(stdin)
            store = _store(args.data_root)
            if args.prepare_dispatch:
                result = prepare_dispatch(value, args.session, state_store=store)
            elif args.confirm_dispatch:
                result = confirm_dispatch(args.session, value, state_store=store)
            else:
                result = record_dispatch_result(args.session, value, state_store=store)
    except Exception as exc:
        print(f"operation failed: {exc}", file=stderr)
        return 1
    _emit(stdout, result)
    return 0


__all__ = ["main"]
