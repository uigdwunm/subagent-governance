#!/usr/bin/env python3
"""Direct command-line transport for governance domain services."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import BinaryIO, TextIO

try:
    from scripts.governance_context import verify_context_manifest
    from scripts.governance_diagnostics import diagnose, diagnostic_output_bytes
    from scripts.governance_groups import read_group, upsert_group
    from scripts.governance_hook import handle_hook
    from scripts.governance_input import read_json_object
    from scripts.governance_lifecycle import apply_parent_disposition, prepare_communication, prepare_interrupt, reconcile_interrupted_attempt, record_terminal_notification
    from scripts.governance_prepared_store import PreparedContractStore
    from scripts.governance_protocol import prepare_dispatch, prepare_spawn_retry
    from scripts.governance_state_store import StateStore
    from scripts.governance_store_support import data_root_path, prepare_private_directory
except ModuleNotFoundError:
    from governance_context import verify_context_manifest
    from governance_diagnostics import diagnose, diagnostic_output_bytes
    from governance_groups import read_group, upsert_group
    from governance_hook import handle_hook
    from governance_input import read_json_object
    from governance_lifecycle import apply_parent_disposition, prepare_communication, prepare_interrupt, reconcile_interrupted_attempt, record_terminal_notification
    from governance_prepared_store import PreparedContractStore
    from governance_protocol import prepare_dispatch, prepare_spawn_retry
    from governance_state_store import StateStore
    from governance_store_support import data_root_path, prepare_private_directory


class NonExitingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None: raise ValueError(message)


def _parser() -> NonExitingArgumentParser:
    parser = NonExitingArgumentParser(add_help=False)
    for flag in ("diagnose", "prepare_dispatch", "verify_context_manifest", "authorize_final_retry", "prepare_communication", "prepare_interrupt", "reconcile_interrupted_attempt", "authorize_recovery", "record_terminal_notification", "parent_disposition", "upsert_group", "read_group"):
        parser.add_argument("--" + flag.replace("_", "-"), action="store_true")
    parser.add_argument("--prepare-spawn-retry"); parser.add_argument("--group-id")
    parser.add_argument("--session"); parser.add_argument("--data-root", type=Path)
    return parser


def _root(data_root: Path | None, *, write: bool) -> Path:
    root = data_root.expanduser() if data_root is not None else data_root_path(Path(__file__))
    return prepare_private_directory(root) if write else root


def _stores(data_root: Path | None) -> tuple[StateStore, PreparedContractStore]:
    root = _root(data_root, write=True)
    return StateStore(root / "sessions"), PreparedContractStore(root / "prepared")


def _emit(stdout: TextIO, value: object, *, pretty: bool = True) -> None:
    stdout.write(json.dumps(value, ensure_ascii=False, indent=2 if pretty else None, sort_keys=pretty) + "\n")


def _hook(stdin: BinaryIO, stdout: TextIO) -> int:
    try: payload = read_json_object(stdin)
    except Exception as exc:
        _emit(stdout, {"continue": True, "systemMessage": f"Subagent Governance 解析失败，已降级放行：{exc}"}, pretty=False); return 0
    try: result = handle_hook(payload)
    except Exception as exc:
        result = ({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": f"Subagent Governance 处理失败：{exc}"}} if payload.get("hook_event_name") == "PreToolUse" else {"continue": True, "systemMessage": f"Subagent Governance 运行失败，已降级放行：{exc}"})
    if result is not None: _emit(stdout, result, pretty=False)
    return 0


def main(arguments: list[str] | None = None, *, stdin: BinaryIO | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    stdin, stdout, stderr = stdin or sys.stdin.buffer, stdout or sys.stdout, stderr or sys.stderr
    try: args, unknown = _parser().parse_known_args(sys.argv[1:] if arguments is None else arguments)
    except ValueError as exc: print(str(exc), file=stderr); return 2
    if unknown: print(f"unsupported arguments: {unknown}", file=stderr); return 2
    modes = [args.prepare_dispatch, args.verify_context_manifest, args.prepare_spawn_retry is not None, args.prepare_communication, args.prepare_interrupt, args.reconcile_interrupted_attempt, args.record_terminal_notification, args.parent_disposition, args.upsert_group, args.read_group]
    if sum(bool(mode) for mode in modes) > 1 or (args.diagnose and any(modes)):
        print("--diagnose cannot be combined with another operation mode" if args.diagnose else "operation modes cannot be combined", file=stderr); return 2
    if args.authorize_final_retry and args.prepare_spawn_retry is None: print("--authorize-final-retry requires --prepare-spawn-retry", file=stderr); return 2
    if args.authorize_recovery and not args.prepare_communication: print("--authorize-recovery requires --prepare-communication", file=stderr); return 2
    if args.group_id is not None and not args.read_group: print("--group-id is only valid with --read-group", file=stderr); return 2
    if args.verify_context_manifest and (args.session or args.data_root): print("--verify-context-manifest does not accept --session or --data-root", file=stderr); return 2
    if not args.diagnose and not any(modes) and (args.session or args.data_root or args.group_id): print("--session and --data-root require --diagnose or an explicit operation mode", file=stderr); return 2
    if args.diagnose:
        document, code = diagnose(args.session, _root(args.data_root, write=False)); output = diagnostic_output_bytes(document)
        stdout.buffer.write(output) if hasattr(stdout, "buffer") else stdout.write(output.decode("utf-8")); return code
    if not any(modes): return _hook(stdin, stdout)
    requires_session = args.prepare_dispatch or args.prepare_spawn_retry is not None or args.prepare_communication or args.prepare_interrupt or args.reconcile_interrupted_attempt or args.record_terminal_notification or args.parent_disposition or args.upsert_group or args.read_group
    if requires_session and not args.session: print("operation requires --session", file=stderr); return 2
    if args.read_group and not args.group_id: print("--read-group requires --group-id", file=stderr); return 2
    try:
        if args.verify_context_manifest: result = verify_context_manifest(read_json_object(stdin))
        elif args.read_group: result = read_group(args.session, args.group_id, state_store=_stores(args.data_root)[0])
        else:
            value, (state, prepared) = read_json_object(stdin), _stores(args.data_root)
            if args.prepare_dispatch: result = prepare_dispatch(value, args.session, state_store=state, prepared_store=prepared)
            elif args.prepare_spawn_retry is not None: result = prepare_spawn_retry(value, args.session, args.prepare_spawn_retry, authorized=args.authorize_final_retry, state_store=state, prepared_store=prepared)
            elif args.prepare_communication: result = prepare_communication(value, args.session, authorized_recovery=args.authorize_recovery, state_store=state)
            elif args.prepare_interrupt: result = prepare_interrupt(value, args.session, state_store=state)
            elif args.reconcile_interrupted_attempt: result = reconcile_interrupted_attempt(value, args.session, state_store=state)
            elif args.record_terminal_notification: result = record_terminal_notification(value, args.session, state_store=state)
            elif args.parent_disposition: result = apply_parent_disposition(value, args.session, state_store=state)
            else: result = upsert_group(value, args.session, state_store=state)
    except Exception as exc: print(f"operation failed: {exc}", file=stderr); return 1
    _emit(stdout, result); return 0


__all__ = ["main"]
