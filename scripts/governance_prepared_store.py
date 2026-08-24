"""PreparedContract records and private persistence store."""
from __future__ import annotations
import copy
import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator
try:
    from scripts.governance_context import validate_context_verification_record
    from scripts.governance_contracts import TaskContract, contract_digest, contract_from_input, validate_task_contract
    from scripts.governance_dispatch_identity import parse_task_name
    from scripts.governance_errors import PreparedContractConflictError, PreparedContractError, PreparedContractValidationError, PreparedContractWriteError
    from scripts.governance_semantics import MAX_PREPARED_BYTES, REASONING_EFFORTS, TASK_REF_LENGTHS
    from scripts.governance_storage import PrivateStorageCapacityError, PrivateStorageError, PrivateStorageWriteError, atomic_write_bytes, locked_file, read_private_bytes
    from scripts.governance_store_support import data_root_path, exclusive_file_lock, owned_by_current_user, prepare_private_directory, private_permissions_safe, restrict_descriptor, safe_filename, sync_directory
except ModuleNotFoundError:
    from governance_context import validate_context_verification_record
    from governance_contracts import TaskContract, contract_digest, contract_from_input, validate_task_contract
    from governance_dispatch_identity import parse_task_name
    from governance_errors import PreparedContractConflictError, PreparedContractError, PreparedContractValidationError, PreparedContractWriteError
    from governance_semantics import MAX_PREPARED_BYTES, REASONING_EFFORTS, TASK_REF_LENGTHS
    from governance_storage import PrivateStorageCapacityError, PrivateStorageError, PrivateStorageWriteError, atomic_write_bytes, locked_file, read_private_bytes
    from governance_store_support import data_root_path, exclusive_file_lock, owned_by_current_user, prepare_private_directory, private_permissions_safe, restrict_descriptor, safe_filename, sync_directory


def prepared_root_for_store(store: Any) -> Path:
    root = getattr(store, "root", None)
    if isinstance(root, Path):
        return (root.parent if root.name == "sessions" else root) / "prepared"
    return data_root_path(Path(__file__)) / "prepared"


def prepared_record(session_id: str, task_id: str, attempt: int, task_ref: str, task_name: str, contract: TaskContract, context_verification: dict[str, Any], spawn_args: dict[str, Any], *, created_at: int, spawn_retry_count: int, dispatch_operation: str) -> dict[str, Any]:
    return {
        "session_id": session_id, "task_id": task_id, "attempt": attempt, "task_ref": task_ref,
        "task_name": task_name, "resolved_mode": contract.resolved_mode, "contract": contract.to_record(),
        "contract_digest": contract_digest(contract), "context_verification": copy.deepcopy(context_verification),
        "native_parameters": {"task_name": task_name, "fork_turns": spawn_args["fork_turns"], "model": spawn_args.get("model"), "reasoning_effort": spawn_args.get("reasoning_effort")},
        "created_at": created_at, "consumed": False, "tool_use_id": None, "claimed_at": None,
        "post_observed_at": None, "spawn_retry_count": spawn_retry_count, "dispatch_operation": dispatch_operation,
    }


def _nullable_text(value: Any, maximum: int | None = None) -> bool:
    return value is None or (isinstance(value, str) and value.strip() and (maximum is None or len(value) <= maximum))
def _nullable_timestamp(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


class PreparedContractStore:
    def __init__(self, root: Path | None = None):
        self.root = prepare_private_directory(root if root is not None else prepared_root_for_store(None))
    def _paths(self, session_id: str, task_ref: str) -> tuple[Path, Path]:
        if len(task_ref) not in TASK_REF_LENGTHS or not re.fullmatch(r"[a-f0-9]+", task_ref):
            raise PreparedContractValidationError("task_ref 不是允许长度的小写十六进制")
        stem = safe_filename(session_id)
        return self.root / f"{stem}--{task_ref}.json", self.root / f"{stem}.lock"
    @contextmanager
    def _lock(self, session_id: str) -> Iterator[None]:
        _, lock_path = self._paths(session_id, "0" * TASK_REF_LENGTHS[0])
        try:
            with locked_file(lock_path, label="PreparedContract", exclusive_lock=exclusive_file_lock, restrict_descriptor=restrict_descriptor, owned_by_current_user=owned_by_current_user):
                yield
        except PrivateStorageError as exc:
            raise PreparedContractValidationError(str(exc)) from exc
    @staticmethod
    def _validate_record(value: Any, session_id: str, task_ref: str, path: Path) -> dict[str, Any]:
        required = ("session_id","task_id","attempt","task_ref","task_name","resolved_mode","contract","contract_digest","context_verification","native_parameters","created_at","consumed","tool_use_id","claimed_at","post_observed_at","spawn_retry_count","dispatch_operation")
        if not isinstance(value, dict): raise PreparedContractValidationError(f"PreparedContract 根节点必须是对象：{path}")
        missing = [field for field in required if field not in value]
        if missing: raise PreparedContractValidationError(f"PreparedContract 缺少字段 {', '.join(missing)}：{path}")
        unknown = sorted(set(value) - set(required))
        if unknown: raise PreparedContractValidationError(f"PreparedContract 包含未知字段 {', '.join(unknown)}：{path}")
        if value.get("session_id") != session_id or value.get("task_ref") != task_ref: raise PreparedContractValidationError(f"PreparedContract 引用与文件路径不匹配：{path}")
        if not isinstance(value.get("task_id"), str) or not value["task_id"].strip(): raise PreparedContractValidationError(f"PreparedContract task_id 无效：{path}")
        attempt = value.get("attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1: raise PreparedContractValidationError(f"PreparedContract attempt 无效：{path}")
        parsed = parse_task_name(value.get("task_name"))
        if parsed is None or parsed[0] != value.get("resolved_mode") or parsed[2] != task_ref: raise PreparedContractValidationError(f"PreparedContract task_name 无效：{path}")
        contract = value.get("contract"); errors = validate_task_contract(contract)
        if errors: raise PreparedContractValidationError(f"PreparedContract TaskContract 无效：{'；'.join(errors)}")
        if value.get("contract_digest") != contract_digest(contract_from_input(contract)): raise PreparedContractValidationError(f"PreparedContract contract_digest 无效：{path}")
        errors = validate_context_verification_record(contract.get("context_manifest"), value.get("context_verification"))
        if errors: raise PreparedContractValidationError("PreparedContract context_verification 无效：" + "；".join(errors) + f"：{path}")
        native = value.get("native_parameters")
        if not isinstance(native, dict) or set(native) != {"task_name","fork_turns","model","reasoning_effort"} or native.get("task_name") != value.get("task_name") or not isinstance(native.get("fork_turns"), str) or not native["fork_turns"].strip() or not _nullable_text(native.get("model"), 128) or (native.get("reasoning_effort") is not None and native.get("reasoning_effort") not in REASONING_EFFORTS): raise PreparedContractValidationError(f"PreparedContract native_parameters 无效：{path}")
        if isinstance(value.get("created_at"), bool) or not isinstance(value.get("created_at"), int): raise PreparedContractValidationError(f"PreparedContract created_at 无效：{path}")
        if not isinstance(value.get("consumed"), bool): raise PreparedContractValidationError(f"PreparedContract consumed 无效：{path}")
        if not _nullable_text(value.get("tool_use_id"), 1024): raise PreparedContractValidationError(f"PreparedContract tool_use_id 无效：{path}")
        for field in ("claimed_at","post_observed_at"):
            if not _nullable_timestamp(value.get(field)): raise PreparedContractValidationError(f"PreparedContract {field} 无效：{path}")
        retry = value.get("spawn_retry_count")
        if isinstance(retry, bool) or not isinstance(retry, int) or not 0 <= retry <= 2: raise PreparedContractValidationError(f"PreparedContract spawn_retry_count 无效：{path}")
        if value["consumed"] and (value.get("tool_use_id") is None or value.get("claimed_at") is None): raise PreparedContractValidationError(f"已消费 PreparedContract 缺少 claim 字段：{path}")
        operation = value.get("dispatch_operation")
        if operation not in {"initial_spawn","spawn_retry"}: raise PreparedContractValidationError(f"PreparedContract dispatch_operation 无效：{path}")
        if operation == "spawn_retry" and retry < 1: raise PreparedContractValidationError(f"spawn retry PreparedContract retry count 无效：{path}")
        if operation == "initial_spawn" and attempt != 1: raise PreparedContractValidationError(f"initial PreparedContract attempt 必须为1：{path}")
        if operation == "initial_spawn" and retry != 0: raise PreparedContractValidationError(f"非 retry PreparedContract retry count 必须为0：{path}")
        return value
    def _read_path(self, path: Path, session_id: str, task_ref: str) -> dict[str, Any]:
        try: raw = read_private_bytes(path, label="PreparedContract", max_bytes=MAX_PREPARED_BYTES, owned_by_current_user=owned_by_current_user, private_permissions_safe=private_permissions_safe)
        except FileNotFoundError as exc: raise PreparedContractValidationError(f"PreparedContract 不存在：session={session_id}, task_ref={task_ref}") from exc
        except (PrivateStorageCapacityError, PrivateStorageError) as exc: raise PreparedContractValidationError(str(exc)) from exc
        try: value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise PreparedContractValidationError(f"PreparedContract 不是有效 UTF-8 JSON：{path}") from exc
        return self._validate_record(value, session_id, task_ref, path)
    @staticmethod
    def _encoded(record: dict[str, Any]) -> bytes:
        try: raw = (json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc: raise PreparedContractValidationError("PreparedContract 包含无法序列化的值") from exc
        if len(raw) > MAX_PREPARED_BYTES: raise PreparedContractValidationError("PreparedContract 超过大小上限")
        return raw
    def _write_path(self, path: Path, session_id: str, task_ref: str, record: dict[str, Any]) -> None:
        self._validate_record(record, session_id, task_ref, path); encoded = self._encoded(record)
        try: atomic_write_bytes(path, encoded, label="PreparedContract", restrict_descriptor=restrict_descriptor, sync_directory=sync_directory)
        except PrivateStorageWriteError as exc: raise PreparedContractWriteError(str(exc)) from exc
        try: verified = self._read_path(path, session_id, task_ref)
        except PreparedContractError as exc: raise PreparedContractWriteError(f"PreparedContract 写入后回读失败：{path}") from exc
        if verified != record: raise PreparedContractWriteError(f"PreparedContract 写入后内容不一致：{path}")
    def create(self, record: dict[str, Any], *, replace: bool = False) -> None:
        session_id, task_ref = str(record.get("session_id") or ""), str(record.get("task_ref") or ""); path, _ = self._paths(session_id, task_ref)
        with self._lock(session_id):
            if path.exists() and not replace: raise PreparedContractConflictError(f"PreparedContract 已存在：{task_ref}")
            self._write_path(path, session_id, task_ref, copy.deepcopy(record))
    def read(self, session_id: str, task_ref: str) -> dict[str, Any]:
        path, _ = self._paths(session_id, task_ref)
        with self._lock(session_id): return self._read_path(path, session_id, task_ref)
    def compare_and_set(self, session_id: str, task_ref: str, predicate: Callable[[dict[str, Any]], bool], callback: Callable[[dict[str, Any]], Any]) -> Any:
        path, _ = self._paths(session_id, task_ref)
        with self._lock(session_id):
            record = self._read_path(path, session_id, task_ref)
            if not predicate(record): raise PreparedContractConflictError(f"PreparedContract compare-and-set 冲突：{task_ref}")
            result = callback(record); self._write_path(path, session_id, task_ref, record); return result
    def delete(self, session_id: str, task_ref: str, *, missing_ok: bool = True) -> bool:
        path, _ = self._paths(session_id, task_ref)
        with self._lock(session_id):
            try: path.unlink()
            except FileNotFoundError:
                if missing_ok: return False
                raise PreparedContractValidationError(f"PreparedContract 不存在：{task_ref}")
            except OSError as exc: raise PreparedContractWriteError(f"PreparedContract 删除失败：{path}") from exc
            return True
    def delete_if(self, session_id: str, task_ref: str, predicate: Callable[[dict[str, Any]], bool], *, missing_ok: bool = True) -> bool:
        path, _ = self._paths(session_id, task_ref)
        with self._lock(session_id):
            try: record = self._read_path(path, session_id, task_ref)
            except PreparedContractValidationError as exc:
                if missing_ok and isinstance(exc.__cause__, FileNotFoundError): return False
                raise
            if not predicate(record): raise PreparedContractConflictError(f"PreparedContract exact delete 冲突：{task_ref}")
            try: path.unlink()
            except FileNotFoundError:
                if missing_ok: return False
                raise PreparedContractValidationError(f"PreparedContract 不存在：{task_ref}")
            except OSError as exc: raise PreparedContractWriteError(f"PreparedContract 删除失败：{path}") from exc
            return True
    def list_records(self, session_id: str) -> list[dict[str, Any]]:
        stem = safe_filename(session_id)
        with self._lock(session_id):
            return [self._read_path(path, session_id, path.stem.rsplit("--", 1)[-1]) for path in sorted(self.root.glob(f"{stem}--*.json"))]
    def refs(self, session_id: str) -> set[str]: return {str(record["task_ref"]) for record in self.list_records(session_id)}
    def find_claimed(self, session_id: str, tool_use_id: str) -> dict[str, Any] | None:
        matches = [record for record in self.list_records(session_id) if record.get("consumed") is True and record.get("tool_use_id") == tool_use_id]
        if len(matches) > 1: raise PreparedContractConflictError(f"同一 tool_use_id 映射到多个 PreparedContract：{tool_use_id}")
        return matches[0] if matches else None


_prepared_record = prepared_record
_prepared_root_for_store = prepared_root_for_store
