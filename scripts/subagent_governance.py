#!/usr/bin/env python3
"""Stable executable facade for the current state-v9 governance runtime."""

from __future__ import annotations

try:
    from scripts.governance_cli import main as cli_main
    from scripts.governance_contracts import TaskContract
    from scripts.governance_diagnostics import diagnose, status
    from scripts.governance_dispatch import (
        claim_spawn, confirm_dispatch, record_dispatch_result,
    )
    from scripts.governance_errors import (
        DispatchPreparationError, StateConflictError, StateValidationError,
    )
    from scripts.governance_hook import handle_hook
    from scripts.governance_protocol import prepare_dispatch
    from scripts.governance_state_store import StateStore, UnavailableStateStore
except ModuleNotFoundError:
    from governance_cli import main as cli_main
    from governance_contracts import TaskContract
    from governance_diagnostics import diagnose, status
    from governance_dispatch import claim_spawn, confirm_dispatch, record_dispatch_result
    from governance_errors import DispatchPreparationError, StateConflictError, StateValidationError
    from governance_hook import handle_hook
    from governance_protocol import prepare_dispatch
    from governance_state_store import StateStore, UnavailableStateStore


def handle(payload: dict, state_store: object | None = None):
    return handle_hook(payload, state_store)


def main() -> int:
    return cli_main()


__all__ = [
    "DispatchPreparationError", "StateConflictError", "StateStore",
    "StateValidationError", "TaskContract", "UnavailableStateStore",
    "claim_spawn", "confirm_dispatch", "diagnose", "handle",
    "handle_hook", "main", "prepare_dispatch", "record_dispatch_result", "status",
]


if __name__ == "__main__":
    raise SystemExit(main())
