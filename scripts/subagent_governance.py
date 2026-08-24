#!/usr/bin/env python3
"""Stable public entrypoint for the governance plugin.

Domain implementations live in their owning modules.  This file deliberately
contains only the executable transports and a small, explicit public facade.
"""
from __future__ import annotations

import sys

try:
    from scripts.governance_cli import main as cli_main
    from scripts.governance_contracts import TaskContract
    from scripts.governance_errors import (
        CommunicationPreparationError, DispatchPreparationError,
        NotificationObservationError, StateConflictError, StateValidationError,
    )
    from scripts.governance_groups import read_group, upsert_group
    from scripts.governance_hook import handle_hook
    from scripts.governance_lifecycle import (
        apply_parent_disposition, prepare_communication, prepare_interrupt,
        reconcile_interrupted_attempt, reconcile_pending_actions,
        record_terminal_notification,
    )
    from scripts.governance_prepared_store import PreparedContractStore
    from scripts.governance_protocol import prepare_dispatch, prepare_spawn_retry
    from scripts.governance_sessions import reconcile_prepared_dispatches
    from scripts.governance_state_store import StateStore, UnavailableStateStore
except ModuleNotFoundError:
    from governance_cli import main as cli_main
    from governance_contracts import TaskContract
    from governance_errors import CommunicationPreparationError, DispatchPreparationError, NotificationObservationError, StateConflictError, StateValidationError
    from governance_groups import read_group, upsert_group
    from governance_hook import handle_hook
    from governance_lifecycle import apply_parent_disposition, prepare_communication, prepare_interrupt, reconcile_interrupted_attempt, reconcile_pending_actions, record_terminal_notification
    from governance_prepared_store import PreparedContractStore
    from governance_protocol import prepare_dispatch, prepare_spawn_retry
    from governance_sessions import reconcile_prepared_dispatches
    from governance_state_store import StateStore, UnavailableStateStore


def handle(payload: dict, state_store: object | None = None):
    """Compatibility spelling for the public Hook router."""
    return handle_hook(payload, state_store)


def main() -> int:
    return cli_main()


__all__ = [
    "CommunicationPreparationError", "DispatchPreparationError",
    "NotificationObservationError", "PreparedContractStore", "StateConflictError",
    "StateStore", "StateValidationError", "TaskContract", "UnavailableStateStore",
    "apply_parent_disposition", "handle", "handle_hook", "main",
    "prepare_communication", "prepare_dispatch", "prepare_interrupt",
    "prepare_spawn_retry", "read_group", "reconcile_interrupted_attempt",
    "reconcile_pending_actions", "reconcile_prepared_dispatches",
    "record_terminal_notification", "upsert_group",
]


if __name__ == "__main__":
    raise SystemExit(main())
