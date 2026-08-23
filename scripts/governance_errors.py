"""Exception hierarchy shared by governance runtime components."""

from __future__ import annotations

from typing import Any


class StateStoreError(RuntimeError):
    """Base class for explicit StateStore failures."""


class StateValidationError(StateStoreError):
    """The existing state or requested write is structurally unsafe."""


class StateCapacityError(StateStoreError):
    """The requested state exceeds a configured admission boundary."""


class StateConflictError(StateStoreError):
    """A compare-and-set predicate did not match the locked state."""


class StateWriteError(StateStoreError):
    """The state could not be atomically written and verified."""


def _state_store_exception_category(exc: Exception, *, during_read: bool) -> str:
    if isinstance(exc, StateConflictError):
        return "conflict"
    if isinstance(exc, (StateWriteError, OSError)):
        return "unavailable"
    cause = exc.__cause__
    while cause is not None:
        if isinstance(cause, OSError):
            return "unavailable"
        cause = cause.__cause__
    if during_read and isinstance(exc, StateStoreError):
        return "unavailable"
    return "unsafe"


class PreparedContractError(RuntimeError):
    """Base class for PreparedContract persistence and validation failures."""


class PreparedContractValidationError(PreparedContractError):
    """A PreparedContract is missing required mechanical facts or is unsafe."""


class PreparedContractConflictError(PreparedContractError):
    """A PreparedContract compare-and-set predicate did not match."""


class PreparedContractWriteError(PreparedContractError):
    """A PreparedContract could not be atomically written and verified."""


class DispatchPreparationError(RuntimeError):
    """The deterministic dispatch package could not pass both hard gates."""


class ContextVerificationError(RuntimeError):
    """Declared context dependencies are invalid, unavailable, or changed."""


class CommunicationPreparationError(RuntimeError):
    """A communication or interrupt package could not pass mechanical gates."""


class ReconciliationError(RuntimeError):
    """A parent-supplied lifecycle reconciliation is incomplete or unsafe."""


class NotificationObservationError(RuntimeError):
    """A parent-observed native terminal notification is invalid or conflicts."""


class ParentDispositionError(RuntimeError):
    """A parent disposition request failed mechanical validation."""


class ParentDispositionConflict(ParentDispositionError):
    """A parent disposition conflicts with the current persisted task facts."""

    def __init__(
        self,
        message: str,
        *,
        interrupt_targets: list[str] | None = None,
        current_attempt: int | None = None,
    ):
        super().__init__(message)
        self.interrupt_targets = list(interrupt_targets or [])
        self.current_attempt = current_attempt


class GroupValidationError(RuntimeError):
    """A lightweight group request or persisted group is mechanically invalid."""


class GroupNotFoundError(GroupValidationError):
    """The requested lightweight group does not exist in the Session."""


class DiagnosticReadError(RuntimeError):
    """A read-only diagnostic target could not be normalized."""

    def __init__(self, code: str, message: str, *, context: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})
