"""Exception hierarchy for the current state-v9 runtime."""


class StateStoreError(RuntimeError):
    """Base class for explicit StateStore failures."""


class StateValidationError(StateStoreError):
    """Persisted state or a requested write is structurally unsafe."""


class StateCapacityError(StateStoreError):
    """A state read or write exceeded its bounded capacity."""


class StateConflictError(StateStoreError):
    """A locked transition did not match the current canonical facts."""


class StateWriteError(StateStoreError):
    """An atomic write or its readback verification failed."""


class DispatchPreparationError(RuntimeError):
    """TaskContract v2 could not be prepared in the single ledger."""


class ContextVerificationError(RuntimeError):
    """Explicit verified context is invalid, unavailable, or changed."""


class DiagnosticReadError(RuntimeError):
    """A read-only exact Session ledger could not be interpreted."""


__all__ = [
    "ContextVerificationError", "DiagnosticReadError", "DispatchPreparationError",
    "StateCapacityError", "StateConflictError", "StateStoreError",
    "StateValidationError", "StateWriteError",
]
