#!/usr/bin/env python3
"""Command-line adapter for the governance runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, BinaryIO

try:
    from scripts.governance_semantics import MAX_HOOK_INPUT_BYTES
except ModuleNotFoundError:
    from governance_semantics import MAX_HOOK_INPUT_BYTES


class NonExitingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _base(runtime: ModuleType, data_root: Path | None) -> Path:
    if data_root is None:
        return runtime._data_root()
    return runtime._prepare_private_directory(data_root.expanduser())


def _emit_diagnostic_cli_error(
    runtime: ModuleType, message: str, arguments: list[str]
) -> None:
    root = runtime._data_root_path()
    document = runtime._diagnostic_base_document(
        runtime._diagnostic_absolute_path(root), None
    )
    if "--session" in arguments:
        document["scope"] = "single_session"
    document["scan"]["complete"] = False
    document["issues"] = [
        runtime._diagnostic_issue(
            "scan_incomplete",
            f"诊断 CLI 参数错误：{message}",
            fact="cli_argument_error",
        )
    ]
    sys.stdout.buffer.write(runtime._diagnostic_output_bytes(document))


def _read_json(
    stream: BinaryIO, *, limit: int = MAX_HOOK_INPUT_BYTES
) -> dict[str, Any]:
    raw_input = stream.read(limit + 1)
    if len(raw_input) > limit:
        raise ValueError(f"JSON input exceeds {limit} bytes")
    value = json.loads(raw_input.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON input must be a JSON object")
    return value


def _print_result(result: object) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def _run_preparation(runtime: ModuleType, args: argparse.Namespace) -> int:
    if not args.session:
        print("dispatch preparation requires --session", file=sys.stderr)
        return 2
    try:
        value = _read_json(sys.stdin.buffer)
        base = _base(runtime, args.data_root)
        state_store = runtime.StateStore(base / "sessions")
        prepared_store = runtime.PreparedContractStore(base / "prepared")
        if args.prepare_dispatch:
            result = runtime.prepare_dispatch(
                value,
                args.session,
                state_store=state_store,
                prepared_store=prepared_store,
            )
        elif args.prepare_spawn_retry is not None:
            result = runtime.prepare_spawn_retry(
                value,
                args.session,
                args.prepare_spawn_retry,
                authorized=args.authorize_final_retry,
                state_store=state_store,
                prepared_store=prepared_store,
            )
        elif args.prepare_communication:
            result = runtime.prepare_communication(
                value,
                args.session,
                authorized_recovery=args.authorize_recovery,
                state_store=state_store,
            )
        else:
            result = runtime.prepare_interrupt(
                value,
                args.session,
                state_store=state_store,
            )
    except Exception as exc:
        print(f"operation preparation failed: {exc}", file=sys.stderr)
        return 1
    _print_result(result)
    return 0


def _run_context_verification(runtime: ModuleType) -> int:
    try:
        result = runtime.verify_context_manifest(_read_json(sys.stdin.buffer))
    except Exception as exc:
        print(f"context verification failed: {exc}", file=sys.stderr)
        return 1
    _print_result(result)
    return 0


def _run_reconciliation(runtime: ModuleType, args: argparse.Namespace) -> int:
    if not args.session:
        print("interrupted attempt reconciliation requires --session", file=sys.stderr)
        return 2
    try:
        value = _read_json(sys.stdin.buffer)
        result = runtime.reconcile_interrupted_attempt(
            value,
            args.session,
            state_store=runtime.StateStore(_base(runtime, args.data_root) / "sessions"),
        )
    except Exception as exc:
        print(f"interrupted attempt reconciliation failed: {exc}", file=sys.stderr)
        return 1
    _print_result(result)
    return 0


def _run_lifecycle(runtime: ModuleType, args: argparse.Namespace) -> int:
    if not args.session:
        print("lifecycle operations require --session", file=sys.stderr)
        return 2
    try:
        value = _read_json(sys.stdin.buffer)
        state_store = runtime.StateStore(_base(runtime, args.data_root) / "sessions")
        if args.record_terminal_notification:
            result = runtime.record_terminal_notification(
                value, args.session, state_store=state_store
            )
        else:
            result = runtime.apply_parent_disposition(
                value, args.session, state_store=state_store
            )
    except Exception as exc:
        print(f"lifecycle operation failed: {exc}", file=sys.stderr)
        return 1
    _print_result(result)
    return 0


def _run_group(runtime: ModuleType, args: argparse.Namespace) -> int:
    if not args.session:
        print("group operations require --session", file=sys.stderr)
        return 2
    if args.read_group and not args.group_id:
        print("--read-group requires --group-id", file=sys.stderr)
        return 2
    try:
        value = _read_json(sys.stdin.buffer) if args.upsert_group else None
        state_store = runtime.StateStore(_base(runtime, args.data_root) / "sessions")
        if args.upsert_group:
            result = runtime.upsert_group(
                value, args.session, state_store=state_store
            )
        else:
            result = runtime.read_group(
                args.session, args.group_id, state_store=state_store
            )
    except Exception as exc:
        print(f"group operation failed: {exc}", file=sys.stderr)
        return 1
    _print_result(result)
    return 0


def _run_hook(runtime: ModuleType) -> int:
    try:
        payload = _read_json(sys.stdin.buffer)
        result = runtime.handle(payload)
    except Exception as exc:
        event = (
            payload.get("hook_event_name")
            if isinstance(locals().get("payload"), dict)
            else None
        )
        if event == "PreToolUse":
            result = runtime._deny(f"Subagent Governance 解析失败：{exc}")
        else:
            result = {
                "continue": True,
                "systemMessage": f"Subagent Governance 运行失败，已降级放行：{exc}",
            }
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


def _parser() -> NonExitingArgumentParser:
    parser = NonExitingArgumentParser(add_help=False)
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--prepare-dispatch", action="store_true")
    parser.add_argument("--verify-context-manifest", action="store_true")
    parser.add_argument("--prepare-spawn-retry")
    parser.add_argument("--authorize-final-retry", action="store_true")
    parser.add_argument("--prepare-communication", action="store_true")
    parser.add_argument("--prepare-interrupt", action="store_true")
    parser.add_argument("--reconcile-interrupted-attempt", action="store_true")
    parser.add_argument("--authorize-recovery", action="store_true")
    parser.add_argument("--record-terminal-notification", action="store_true")
    parser.add_argument("--parent-disposition", action="store_true")
    parser.add_argument("--upsert-group", action="store_true")
    parser.add_argument("--read-group", action="store_true")
    parser.add_argument("--group-id")
    parser.add_argument("--session")
    parser.add_argument("--data-root", type=Path)
    return parser


def main(runtime: ModuleType, arguments: list[str] | None = None) -> int:
    raw_arguments = sys.argv[1:] if arguments is None else arguments
    diagnostic_requested = "--diagnose" in raw_arguments
    try:
        args, unknown = _parser().parse_known_args(raw_arguments)
    except ValueError as exc:
        if diagnostic_requested:
            _emit_diagnostic_cli_error(runtime, str(exc), raw_arguments)
        print(str(exc), file=sys.stderr)
        return 2
    if unknown:
        if args.diagnose:
            _emit_diagnostic_cli_error(
                runtime, f"unsupported arguments: {unknown}", raw_arguments
            )
        print(f"unsupported arguments: {unknown}", file=sys.stderr)
        return 2

    operation_modes = {
        "prepare_dispatch": args.prepare_dispatch,
        "verify_context_manifest": args.verify_context_manifest,
        "prepare_spawn_retry": args.prepare_spawn_retry is not None,
        "prepare_communication": args.prepare_communication,
        "prepare_interrupt": args.prepare_interrupt,
        "reconcile_interrupted_attempt": args.reconcile_interrupted_attempt,
        "record_terminal_notification": args.record_terminal_notification,
        "parent_disposition": args.parent_disposition,
        "upsert_group": args.upsert_group,
        "read_group": args.read_group,
    }
    if sum(bool(value) for value in operation_modes.values()) > 1:
        message = "operation modes cannot be combined"
        if args.diagnose:
            _emit_diagnostic_cli_error(runtime, message, raw_arguments)
        print(message, file=sys.stderr)
        return 2
    if args.diagnose and any(operation_modes.values()):
        message = "--diagnose cannot be combined with another operation mode"
        _emit_diagnostic_cli_error(runtime, message, raw_arguments)
        print(message, file=sys.stderr)
        return 2

    conflicts = [
        name
        for name, selected in (
            ("--group-id", args.group_id is not None),
            ("--authorize-final-retry", args.authorize_final_retry),
            ("--authorize-recovery", args.authorize_recovery),
        )
        if args.diagnose and selected
    ]
    if conflicts:
        message = f"{', '.join(conflicts)} cannot be combined with --diagnose"
        _emit_diagnostic_cli_error(runtime, message, raw_arguments)
        print(message, file=sys.stderr)
        return 2

    invalid = []
    if args.authorize_final_retry and args.prepare_spawn_retry is None:
        invalid.append("--authorize-final-retry requires --prepare-spawn-retry")
    if args.authorize_recovery and not args.prepare_communication:
        invalid.append("--authorize-recovery requires --prepare-communication")
    if args.group_id is not None and not args.read_group:
        invalid.append("--group-id is only valid with --read-group")
    if invalid:
        message = "; ".join(invalid)
        print(message, file=sys.stderr)
        return 2
    if args.verify_context_manifest and (args.session or args.data_root):
        print(
            "--verify-context-manifest does not accept --session or --data-root",
            file=sys.stderr,
        )
        return 2
    if not args.diagnose and not any(operation_modes.values()) and (
        args.session is not None
        or args.data_root is not None
        or args.group_id is not None
    ):
        print(
            "--session and --data-root require --diagnose or an explicit operation mode",
            file=sys.stderr,
        )
        return 2

    if args.diagnose:
        return runtime._diagnose(args.session, args.data_root)
    if args.verify_context_manifest:
        return _run_context_verification(runtime)
    if any(
        (
            args.prepare_dispatch,
            args.prepare_spawn_retry is not None,
            args.prepare_communication,
            args.prepare_interrupt,
        )
    ):
        return _run_preparation(runtime, args)
    if args.reconcile_interrupted_attempt:
        return _run_reconciliation(runtime, args)
    if args.record_terminal_notification or args.parent_disposition:
        return _run_lifecycle(runtime, args)
    if args.upsert_group or args.read_group:
        return _run_group(runtime, args)
    return _run_hook(runtime)
