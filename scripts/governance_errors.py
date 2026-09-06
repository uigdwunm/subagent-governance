"""Exception hierarchy for the current state-v10 runtime."""


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


class NativeInputUnavailable(RuntimeError):
    """The Hook input cannot be safely compared to a governed capability."""


class NativeInputMismatch(RuntimeError):
    """A known native input differs from the frozen governed capability."""


class ContextVerificationError(RuntimeError):
    """Explicit verified context is invalid, unavailable, or changed."""


class ContextMaterialConflictError(ContextVerificationError):
    """Declared verified material no longer matches its frozen baseline."""


class DiagnosticReadError(RuntimeError):
    """A read-only exact Session ledger could not be interpreted."""


__all__ = [
    "ContextMaterialConflictError", "ContextVerificationError", "DiagnosticReadError", "DispatchPreparationError",
    "StateCapacityError", "StateConflictError", "StateStoreError",
    "NativeInputMismatch", "NativeInputUnavailable", "StateValidationError", "StateWriteError",
]
