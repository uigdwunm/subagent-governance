#!/usr/bin/env python3
"""Adaptive Codex subagent lifecycle governance hook."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


PROTOCOL = "subagent-governance-v1"
RESULT_PROTOCOL = "subagent-result-v1"
VALID_MODES = {"auto", "light", "standard", "strict"}
ACTIVE_STATUSES = {"pending", "dispatched", "running", "retry_required"}
TERMINAL_STATUSES = {
    "complete", "blocked", "needs_decision", "protocol_error", "failed", "interrupted", "platform_error",
}
MAX_HOOK_INPUT_BYTES = 2 * 1024 * 1024
MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_TERMINAL_RECORDS = 200
TERMINAL_RETENTION_SECONDS = 30 * 24 * 60 * 60
MAX_CONTRACT_TEXT = 600
MAX_PLATFORM_RECOVERIES = 1
STATE_VERSION = 2
MODE_RE = re.compile(r"【治理等级】\s*(?:[:：]\s*)?(auto|light|standard|strict)\b", re.I)
TASK_NAME_MODE_RE = re.compile(r"^sg_(auto|light|standard|strict)_(.+)$")
OPAQUE_MESSAGE_RE = re.compile(r"^[A-Za-z0-9_-]{80,}={0,2}$")
TASK_ID_RE = re.compile(r"(?:【任务 ID】|任务 ID[：:]|\[SG[^\]]*task=)(sg-[a-f0-9]{12})", re.I)
FIELD_RE_TEMPLATE = r"【%s】\s*(?:[:：]\s*)?([^\n]+)"
STRICT_FIELDS = ("目标", "工作范围", "禁止范围", "完成条件", "验收证据", "上下文策略", "下级子 Agent")
STRICT_TERMINAL_FIELDS = ("状态", "目标", "结果", "验证", "剩余事项", "父任务下一步")
ACK_ONLY = {
    "收到", "明白", "好的", "已收到", "了解", "开始执行", "我会处理", "ack",
    "acknowledged", "got it", "understood", "ok", "okay", "done",
}
EVIDENCE_MARKERS = (
    "验证", "测试", "检查", "命令", "文件", "代码", "结果", "发现", "通过", "失败",
    "未修改", "已修改", "read", "test", "check", "command", "file", "result", "found",
)
HIGH_RISK_MARKERS = (
    "安全", "认证", "授权", "迁移", "生产", "删除", "凭证", "密钥", "数据丢失", "并发写",
    "高风险", "security", "auth", "migration", "production", "delete", "credential", "secret",
    "data loss", "concurrent write",
)
READ_ONLY_MARKERS = (
    "只读", "搜索", "调研", "检查", "审查", "复核", "总结", "分析", "定位", "read-only",
    "search", "research", "inspect", "review", "summarize", "analyze",
)
WRITE_MARKERS = (
    "修改", "编辑", "实现", "修复", "创建", "删除", "提交", "写入", "部署", "install", "edit",
    "implement", "fix", "create", "delete", "commit", "write", "deploy",
)
NEGATION_MARKERS = (
    "不要", "不得", "禁止", "无需", "不应", "不能", "不可", "避免", "不修改", "不删除",
    "without", "do not", "don't", "must not", "never", "no edits", "read-only",
)


@dataclass(frozen=True)
class TaskContract:
    protocol: str
    task_id: str
    mode: str
    requested_mode: str
    mode_reason: str
    objective: str
    scope: str
    forbidden: str
    completion: str
    evidence: str
    context_policy: str
    child_agents: str
    model: str
    reasoning_effort: str
    fork_turns: Any
    message_visibility: str

    def to_record(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "task_id": self.task_id,
            "mode": self.mode,
            "requested_mode": self.requested_mode,
            "mode_reason": self.mode_reason,
            "objective": self.objective,
            "scope": self.scope,
            "forbidden": self.forbidden,
            "completion": self.completion,
            "evidence": self.evidence,
            "context_policy": self.context_policy,
            "child_agents": self.child_agents,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "fork_turns": self.fork_turns,
            "message_visibility": self.message_visibility,
        }


def _now() -> int:
    return int(time.time())


def _safe_name(value: str) -> str:
    raw = value or "unknown"
    prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")[:64] or "unknown"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _prepare_private_directory(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"治理状态目录必须是普通目录且不能是符号链接：{root}")
    if metadata.st_uid != os.getuid():
        raise PermissionError(f"治理状态目录不属于当前用户：{root}")
    root.chmod(0o700)
    return root


def _data_root() -> Path:
    override = os.environ.get("SUBAGENT_GOVERNANCE_DATA")
    plugin_data = os.environ.get("PLUGIN_DATA")
    if override:
        root = Path(override).expanduser()
    elif plugin_data:
        root = Path(plugin_data).expanduser() / "state-v1"
    else:
        root = Path(tempfile.gettempdir()) / f"subagent-governance-{os.getuid()}"
    return _prepare_private_directory(root)


class StateStore:
    def __init__(self, root: Path | None = None):
        self.root = _prepare_private_directory(root) if root is not None else _data_root()
        self.last_warning: str | None = None

    @staticmethod
    def _empty_state(session_id: str) -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "session_id": session_id,
            "tasks": {},
            "agents": {},
            "health": {"status": "ok"},
            "updated_at": _now(),
        }

    def _paths(self, session_id: str) -> tuple[Path, Path]:
        stem = _safe_name(session_id)
        return self.root / f"{stem}.json", self.root / f"{stem}.lock"

    @contextmanager
    def _locked(self, session_id: str):
        state_path, lock_path = self._paths(session_id)
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, flags, 0o600)
        with os.fdopen(descriptor, "a+", encoding="utf-8") as lock_file:
            os.fchmod(lock_file.fileno(), 0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            state = self._read_path(state_path, session_id)
            yield state
            self._write_path(state_path, state)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read_path(self, path: Path, session_id: str) -> dict[str, Any]:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return self._empty_state(session_id)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"治理状态文件必须是普通文件且不能是符号链接：{path}")
        if metadata.st_uid != os.getuid():
            raise PermissionError(f"治理状态文件不属于当前用户：{path}")
        if metadata.st_size > MAX_STATE_BYTES:
            raise RuntimeError(f"治理状态文件超过 {MAX_STATE_BYTES} 字节上限：{path}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            quarantine = path.with_name(f"{path.name}.corrupt-{_now()}-{secrets.token_hex(3)}")
            try:
                path.replace(quarantine)
            except OSError as quarantine_error:
                raise RuntimeError(f"治理状态文件损坏且无法隔离：{path}") from quarantine_error
            self.last_warning = f"治理状态已降级恢复，损坏文件已隔离到 {quarantine}"
            recovered = self._empty_state(session_id)
            recovered["health"] = {
                "status": "degraded",
                "reason": "corrupt-state-recovered",
                "quarantine": str(quarantine),
                "updated_at": _now(),
            }
            return recovered
        if not isinstance(value, dict):
            raise RuntimeError(f"治理状态文件根节点必须是对象：{path}")
        if value.get("session_id") not in (None, session_id):
            raise RuntimeError(f"治理状态文件与当前 session 不匹配：{path}")
        value["version"] = STATE_VERSION
        value.setdefault("tasks", {})
        value.setdefault("agents", {})
        value.setdefault("health", {"status": "ok"})
        if not isinstance(value["tasks"], dict) or not isinstance(value["agents"], dict):
            raise RuntimeError(f"治理状态 tasks 和 agents 必须是对象：{path}")
        return value

    @staticmethod
    def _prune_state(state: dict[str, Any]) -> None:
        tasks = state.get("tasks")
        agents = state.get("agents")
        if not isinstance(tasks, dict) or not isinstance(agents, dict):
            return
        cutoff = _now() - TERMINAL_RETENTION_SECONDS
        terminal = [
            record for record in tasks.values()
            if isinstance(record, dict) and record.get("status") in TERMINAL_STATUSES
        ]
        terminal.sort(key=lambda record: int(record.get("updated_at") or record.get("created_at") or 0), reverse=True)
        keep_terminal_ids = {
            str(record.get("task_id")) for record in terminal[:MAX_TERMINAL_RECORDS]
            if int(record.get("updated_at") or record.get("created_at") or 0) >= cutoff
        }
        remove_ids = [
            task_id for task_id, record in tasks.items()
            if isinstance(record, dict)
            and record.get("status") in TERMINAL_STATUSES
            and task_id not in keep_terminal_ids
        ]
        for task_id in remove_ids:
            tasks.pop(task_id, None)
        valid_ids = set(tasks)
        for agent, task_id in list(agents.items()):
            if task_id not in valid_ids:
                agents.pop(agent, None)

    @classmethod
    def _write_path(cls, path: Path, state: dict[str, Any]) -> None:
        cls._prune_state(state)
        state["updated_at"] = _now()
        content = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_STATE_BYTES:
            raise RuntimeError(f"治理状态超过 {MAX_STATE_BYTES} 字节上限")
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(encoded)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
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

    def update(self, session_id: str, callback: Callable[[dict[str, Any]], Any]) -> Any:
        self.last_warning = None
        with self._locked(session_id) as state:
            return callback(state)

    def read(self, session_id: str) -> dict[str, Any]:
        self.last_warning = None
        state_path, lock_path = self._paths(session_id)
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, flags, 0o600)
        with os.fdopen(descriptor, "a+", encoding="utf-8") as lock_file:
            os.fchmod(lock_file.fileno(), 0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            state = self._read_path(state_path, session_id)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return state

    def delete(self, session_id: str) -> None:
        state_path, lock_path = self._paths(session_id)
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, flags, 0o600)
        with os.fdopen(descriptor, "a+", encoding="utf-8") as lock_file:
            os.fchmod(lock_file.fileno(), 0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                state_path.unlink()
            except FileNotFoundError:
                pass
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class UnavailableStateStore:
    """Failing store used to preserve Hook behavior when state setup is unavailable."""

    def __init__(self, error: Exception):
        self.error = error
        self.last_warning = f"治理状态不可用，已降级放行：{error}"

    def _raise(self) -> None:
        raise OSError(str(self.error)) from self.error

    def update(self, session_id: str, callback: Callable[[dict[str, Any]], Any]) -> Any:
        self._raise()

    def read(self, session_id: str) -> dict[str, Any]:
        self._raise()

    def delete(self, session_id: str) -> None:
        self._raise()


def _field(message: str, label: str) -> str | None:
    match = re.search(FIELD_RE_TEMPLATE % re.escape(label), message)
    return match.group(1).strip() if match and match.group(1).strip() else None


def _tool_kind(tool_name: str) -> str | None:
    if tool_name == "Agent" or tool_name.endswith("spawn_agent"):
        return "spawn"
    if tool_name.endswith("followup_task"):
        return "followup"
    if tool_name.endswith("send_message") and not tool_name.endswith("send_message_to_thread"):
        return "communication"
    if tool_name.endswith("interrupt_agent"):
        return "interrupt"
    if tool_name.endswith("list_agents"):
        return "agent_status"
    return None


def _message_visibility(message: str) -> str:
    stripped = message.strip()
    return "opaque" if OPAQUE_MESSAGE_RE.fullmatch(stripped) else "plaintext"


def _task_name_mode(task_name: str) -> str | None:
    match = TASK_NAME_MODE_RE.fullmatch(task_name)
    return match.group(1) if match else None


def _requested_mode(message: str, task_name: str = "") -> tuple[str, str]:
    task_mode = _task_name_mode(task_name)
    if task_mode:
        return task_mode, "task-name"
    match = MODE_RE.search(message)
    if match:
        return match.group(1).lower(), "message"
    return "auto", "default"


def _classification_text(message: str) -> str:
    lines = []
    for line in message.splitlines():
        lowered = line.lower()
        if "【禁止范围】" in line or any(marker in lowered for marker in NEGATION_MARKERS):
            continue
        lines.append(line)
    return "\n".join(lines).lower()


def _resolved_mode(requested: str, source: str, message: str, visibility: str) -> tuple[str, str]:
    if requested in {"light", "standard", "strict"}:
        return requested, f"explicit:{source}:{requested};message:{visibility}"
    if visibility == "opaque":
        return "standard", "auto:opaque-message-default"
    lowered = message.lower()
    classification = _classification_text(message)
    write_scan = lowered
    for phrase in (
        "不修改", "不得修改", "不要修改", "无需修改", "不编辑", "不得编辑", "不写入",
        "without modifying", "do not modify", "don't modify", "no edits", "read-only",
    ):
        write_scan = write_scan.replace(phrase, "")
    child_agents = _field(message, "下级子 Agent") or ""
    if child_agents.startswith("允许"):
        return "strict", "auto:child-agents"
    high_risk = next((marker for marker in HIGH_RISK_MARKERS if marker in classification), None)
    if high_risk:
        return "strict", f"auto:high-risk:{high_risk}"
    if any(marker in lowered for marker in READ_ONLY_MARKERS) and not any(marker in write_scan for marker in WRITE_MARKERS):
        return "light", "auto:read-only"
    return "standard", "auto:default"


def _task_id(payload: dict[str, Any]) -> str:
    seed = "|".join(
        str(payload.get(key, "")) for key in ("session_id", "turn_id", "tool_use_id")
    )
    if not seed.strip("|"):
        return "sg-" + secrets.token_hex(6)
    return "sg-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _allow_updated(updated_input: dict[str, Any], context: str | None = None) -> dict[str, Any]:
    output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "updatedInput": updated_input,
    }
    if context:
        output["additionalContext"] = context
    return {"hookSpecificOutput": output}


def _governance_envelope(task_id: str, mode: str, requested_mode: str, mode_reason: str) -> str:
    lines = [
        "【Subagent Governance】",
        f"协议：{PROTOCOL}",
        f"任务 ID：{task_id}",
        f"治理等级：{mode}",
        f"选择原因：{mode_reason}",
        "本次派发是唯一当前任务；父线程历史、旧 ACK 和旧任务只能作为背景，不得覆盖本次目标。",
        "必须实际执行任务；不要只回复收到、明白或准备开始。",
        "完成、阻塞或需要决策时，说明实际结果、验证或证据、剩余事项，并在终态中保留任务 ID。",
    ]
    if mode == "strict" and requested_mode == "strict":
        lines.append("严格模式必须使用【子 Agent 终态】卡并完整填写状态、目标、结果、验证、剩余事项和父任务下一步。")
    elif mode == "strict":
        lines.append("本任务由 auto 提升为严格证据要求；必须给出真实结果和验证，但不强制固定终态模板。")
    return "\n".join(lines)


def _bounded(value: Any, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    return text[:MAX_CONTRACT_TEXT]


def _task_name_objective(task_name: str) -> str:
    match = TASK_NAME_MODE_RE.fullmatch(task_name)
    raw = match.group(2) if match else task_name
    return _bounded(raw.replace("_", " "), "未命名子任务")


def _fallback_objective(message: str, task_name: str, visibility: str) -> str:
    if visibility == "opaque":
        return _task_name_objective(task_name)
    for line in message.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("【治理等级】") or stripped.startswith("【"):
            continue
        return _bounded(stripped, "未命名子任务")
    return "未命名子任务"


def _context_policy(fork_turns: Any) -> str:
    if fork_turns == "none":
        return "隔离上下文"
    if fork_turns == "all" or fork_turns is None:
        return "完整继承"
    return f"有限继承最近 {fork_turns} 轮"


def _task_contract(
    message: str,
    tool_input: dict[str, Any],
    task_id: str,
    requested_mode: str,
    mode: str,
    mode_reason: str,
    message_visibility: str,
) -> TaskContract:
    child_value = _field(message, "下级子 Agent") or ""
    child_agents = "allow" if child_value.startswith("允许") else "deny"
    fork_turns = tool_input.get("fork_turns", "all")
    return TaskContract(
        protocol=PROTOCOL,
        task_id=task_id,
        mode=mode,
        requested_mode=requested_mode,
        mode_reason=mode_reason,
        objective=_bounded(
            _field(message, "目标") if message_visibility == "plaintext" else None,
            _fallback_objective(message, str(tool_input.get("task_name") or ""), message_visibility),
        ),
        scope=_bounded(_field(message, "工作范围"), "派发消息所述范围"),
        forbidden=_bounded(_field(message, "禁止范围")),
        completion=_bounded(_field(message, "完成条件"), "给出实际结果、验证或证据和剩余事项"),
        evidence=_bounded(_field(message, "验收证据")),
        context_policy=_bounded(_field(message, "上下文策略"), _context_policy(fork_turns)),
        child_agents=child_agents,
        model=_bounded(tool_input.get("model")),
        reasoning_effort=_bounded(tool_input.get("reasoning_effort")),
        fork_turns=fork_turns,
        message_visibility=message_visibility,
    )


def _validate_strict(message: str, fork_turns: Any) -> list[str]:
    missing = [label for label in STRICT_FIELDS if _field(message, label) is None]
    errors = ["缺少严格模式字段：" + "、".join(missing)] if missing else []
    context = _field(message, "上下文策略") or ""
    if fork_turns in (None, "all") and not ("完整继承" in context and ("理由" in context or len(context) >= 12)):
        errors.append("严格模式使用完整上下文继承时，【上下文策略】必须写明完整继承的理由")
    return errors


def _handle_spawn(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return _deny("子 Agent 派发被阻止：spawn_agent 参数不是对象。")
    message = tool_input.get("message")
    if not isinstance(message, str) or len(message.strip()) < 8:
        return _deny("子 Agent 派发被阻止：任务说明为空或过短，无法形成可执行目标。")

    task_name = str(tool_input.get("task_name") or "")
    visibility = _message_visibility(message)
    requested, mode_source = _requested_mode(message, task_name)
    if requested not in VALID_MODES:
        return _deny("子 Agent 派发被阻止：治理等级必须是 auto、light、standard 或 strict。")
    mode, mode_reason = _resolved_mode(requested, mode_source, message, visibility)
    if mode == "strict" and requested == "strict" and visibility == "plaintext":
        errors = _validate_strict(message, tool_input.get("fork_turns", "all"))
        if errors:
            return _deny("子 Agent 严格治理校验失败：" + "；".join(errors) + "。")

    task_id = _task_id(payload)
    contract = _task_contract(message, tool_input, task_id, requested, mode, mode_reason, visibility)
    message = message.rstrip() + "\n\n" + _governance_envelope(task_id, mode, requested, mode_reason) + "\n"
    updated_input = copy.deepcopy(tool_input)
    updated_input["message"] = message

    session_id = str(payload.get("session_id") or "unknown")
    record = {
        **contract.to_record(),
        "tool_use_id": str(payload.get("tool_use_id") or ""),
        "turn_id": str(payload.get("turn_id") or ""),
        "task_name": task_name,
        "status": "pending",
        "created_at": _now(),
        "updated_at": _now(),
        "retry_count": 0,
        "recovery_count": 0,
    }

    def save(state: dict[str, Any]) -> None:
        state["tasks"][task_id] = record

    warning = None
    try:
        store.update(session_id, save)
        warning = getattr(store, "last_warning", None)
    except (OSError, RuntimeError) as exc:
        warning = f"治理状态不可写，已降级放行且本次任务仅依赖消息中的任务 ID：{exc}"
    context = f"Subagent Governance 已选择 {mode} 模式并分配任务 ID {task_id}。"
    if visibility == "opaque":
        context += "\n派发正文在 Hook 层不可见；治理等级来自 task_name 或使用 standard 兼容默认值。"
    if warning:
        context += "\n" + str(warning)
    return _allow_updated(updated_input, context)


def _handle_communication(payload: dict[str, Any], store: StateStore) -> dict[str, Any] | None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return _deny("子 Agent 通信被阻止：工具参数不是对象。")
    message = tool_input.get("message")
    if not isinstance(message, str) or not message.strip():
        return _deny("子 Agent 通信被阻止：消息不能为空。")
    target = str(tool_input.get("target") or "")
    session_id = str(payload.get("session_id") or "unknown")
    try:
        state = store.read(session_id)
    except (OSError, RuntimeError) as exc:
        return {"systemMessage": f"Subagent Governance 状态不可读，通信已降级放行：{exc}"}
    warning = getattr(store, "last_warning", None)
    task_id = state.get("agents", {}).get(target)
    kind = _tool_kind(str(payload.get("tool_name") or ""))
    if kind == "followup" and task_id:
        def require_platform_decision(current: dict[str, Any]) -> bool:
            record = current.get("tasks", {}).get(task_id)
            if not isinstance(record, dict):
                return False
            if (
                record.get("status") == "platform_error"
                and int(record.get("recovery_count") or 0) >= MAX_PLATFORM_RECOVERIES
            ):
                record["status"] = "needs_decision"
                record["decision_reason"] = "platform_recovery_limit"
                record["updated_at"] = _now()
                return True
            return False

        try:
            platform_limit_reached = bool(store.update(session_id, require_platform_decision))
        except (OSError, RuntimeError) as exc:
            return {"systemMessage": f"Subagent Governance 无法检查平台恢复上限，通信已降级放行：{exc}"}
        if platform_limit_reached:
            return _deny(
                "同一子 Agent 的平台执行错误在一次恢复后再次出现，已停止自动重试并记录为 needs_decision。"
                "请父任务向用户请求是否切换 provider、模型或稍后重新派发。"
            )
    if task_id and task_id not in message:
        updated = copy.deepcopy(tool_input)
        updated["message"] = message.rstrip() + f"\n\n【治理任务 ID】{task_id}\n"
        return _allow_updated(updated, f"通信已关联治理任务 {task_id}。")
    if warning:
        return {"systemMessage": str(warning)}
    return None


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _agent_status_entries(response: Any) -> list[dict[str, Any]]:
    value = _json_value(response)
    if not isinstance(value, dict) or not isinstance(value.get("agents"), list):
        return []
    return [entry for entry in value["agents"] if isinstance(entry, dict)]


def _extract_values(value: Any, keys: set[str]) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys and isinstance(child, str) and child:
                found.append(child)
            found.extend(_extract_values(child, keys))
    elif isinstance(value, list):
        for child in value:
            found.extend(_extract_values(child, keys))
    return found


def _response_failed(response: Any, depth: int = 0) -> bool:
    if depth > 24:
        return False
    if isinstance(response, dict):
        if response.get("isError") is True or response.get("is_error") is True:
            return True
        status = str(response.get("status") or response.get("state") or "").lower()
        if status in {"error", "failed", "failure"}:
            return True
        return any(_response_failed(child, depth + 1) for child in response.values())
    if isinstance(response, list):
        return any(_response_failed(child, depth + 1) for child in response)
    if isinstance(response, str):
        return re.match(r"^\s*(?:error|failed|failure)\b", response, re.I) is not None
    return False


def _handle_post_tool(payload: dict[str, Any], store: StateStore) -> dict[str, Any] | None:
    session_id = str(payload.get("session_id") or "unknown")
    kind = _tool_kind(str(payload.get("tool_name") or ""))
    tool_use_id = str(payload.get("tool_use_id") or "")
    response = payload.get("tool_response")
    agent_ids = _extract_values(response, {"agent_id", "agentId"})
    canonical_paths = [
        value for value in _extract_values(
            response,
            {"canonical_task_path", "canonical_path", "canonical_task_name", "task_path", "task_name"},
        )
        if value.startswith("/")
    ]
    failed = _response_failed(response)

    if kind == "agent_status":
        entries = _agent_status_entries(response)
        if not entries:
            return None

        def reconcile(state: dict[str, Any]) -> None:
            for entry in entries:
                target = str(entry.get("agent_name") or "")
                task_id = state.get("agents", {}).get(target)
                record = state.get("tasks", {}).get(task_id) if task_id else None
                if not isinstance(record, dict):
                    continue
                platform_status = entry.get("agent_status")
                record["platform_status"] = platform_status
                record["platform_checked_at"] = _now()
                if isinstance(platform_status, dict) and platform_status.get("errored"):
                    record["status"] = "platform_error"
                    record["platform_error"] = _bounded(platform_status.get("errored"))
                    record["updated_at"] = _now()

        try:
            store.update(session_id, reconcile)
        except (OSError, RuntimeError) as exc:
            return {"systemMessage": f"Subagent Governance 无法对账 Agent 平台状态，已降级放行：{exc}"}
        return None

    if kind == "followup":
        tool_input = payload.get("tool_input")
        target = str(tool_input.get("target") or "") if isinstance(tool_input, dict) else ""
        if failed or not target:
            return None

        def recover(state: dict[str, Any]) -> None:
            task_id = state.get("agents", {}).get(target)
            record = state.get("tasks", {}).get(task_id) if task_id else None
            if not isinstance(record, dict):
                return
            record["recovery_count"] = int(record.get("recovery_count") or 0) + 1
            record["status"] = "retry_required"
            record["updated_at"] = _now()

        try:
            store.update(session_id, recover)
        except (OSError, RuntimeError) as exc:
            return {"systemMessage": f"Subagent Governance 无法记录恢复尝试，已降级放行：{exc}"}
        return None

    if kind == "interrupt":
        tool_input = payload.get("tool_input")
        target = str(tool_input.get("target") or "") if isinstance(tool_input, dict) else ""
        if failed or not target:
            return None

        def interrupt(state: dict[str, Any]) -> None:
            task_id = state.get("agents", {}).get(target)
            record = state.get("tasks", {}).get(task_id) if task_id else None
            if not isinstance(record, dict) or record.get("status") not in ACTIVE_STATUSES:
                return
            record["status"] = "interrupted"
            record["updated_at"] = _now()
            record["interrupt_tool_use_id"] = tool_use_id

        try:
            store.update(session_id, interrupt)
        except (OSError, RuntimeError) as exc:
            return {"systemMessage": f"Subagent Governance 无法记录中断状态，已降级放行：{exc}"}
        if getattr(store, "last_warning", None):
            return {"systemMessage": str(store.last_warning)}
        return None

    if kind != "spawn":
        return None

    def update(state: dict[str, Any]) -> None:
        matches = [record for record in state["tasks"].values() if record.get("tool_use_id") == tool_use_id]
        if len(matches) != 1:
            return
        record = matches[0]
        record["updated_at"] = _now()
        if failed:
            record["status"] = "failed"
            return
        record["status"] = "running"
        if agent_ids:
            record["agent_id"] = agent_ids[0]
            state["agents"][agent_ids[0]] = record["task_id"]
        if canonical_paths:
            record["canonical_task_path"] = canonical_paths[0]
            state["agents"][canonical_paths[0]] = record["task_id"]

    try:
        store.update(session_id, update)
    except (OSError, RuntimeError) as exc:
        return {"systemMessage": f"Subagent Governance 无法记录派发生命周期，已降级放行：{exc}"}
    if getattr(store, "last_warning", None):
        return {"systemMessage": str(store.last_warning)}
    return None


def _assign_starting_agent(state: dict[str, Any], agent_id: str) -> str | None:
    existing = state.get("agents", {}).get(agent_id)
    if existing:
        record = state.get("tasks", {}).get(existing)
        if isinstance(record, dict) and record.get("status") != "complete":
            record["status"] = "running"
            record["updated_at"] = _now()
        return existing
    candidates = [
        record for record in state.get("tasks", {}).values()
        if record.get("status") in {"pending", "dispatched", "running"} and not record.get("agent_id")
    ]
    candidates.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    if len(candidates) == 1:
        record = candidates[0]
        record["agent_id"] = agent_id
        record["status"] = "running"
        record["updated_at"] = _now()
        state["agents"][agent_id] = record["task_id"]
        return record["task_id"]
    return None


def _handle_subagent_start(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    agent_id = str(payload.get("agent_id") or "")
    task_id = None
    record: dict[str, Any] = {}
    warning = None
    try:
        task_id = store.update(session_id, lambda state: _assign_starting_agent(state, agent_id)) if agent_id else None
        if task_id:
            record = store.read(session_id).get("tasks", {}).get(task_id, {})
        warning = getattr(store, "last_warning", None)
    except (OSError, RuntimeError) as exc:
        warning = f"治理状态不可读，当前子 Agent 使用通用执行边界：{exc}"
    task_line = f"当前治理任务 ID：{task_id}。" if task_id else "如果派发中包含治理任务 ID，请在终态中原样保留。"
    objective_line = f"\n当前目标：{record.get('objective')}。" if record.get("objective") else ""
    completion_line = f"\n完成条件：{record.get('completion')}。" if record.get("completion") else ""
    context = (
        "你是由 Codex 原生机制启动的子 Agent。" + task_line + objective_line + completion_line + "\n"
        "本次派发消息是唯一当前任务；旧 ACK、旧任务和父线程历史不得覆盖本次目标。\n"
        "必须实际执行任务，不要只回复收到、明白或准备开始。\n"
        "完成、阻塞或需要决策时，用中文说明实际结果、验证或证据、剩余事项。\n"
        "不要为了满足格式伪造测试、文件修改或检查证据。"
    )
    if warning:
        context += "\n" + str(warning)
    return {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": context,
        }
    }


def _normalized_message(message: str) -> str:
    return re.sub(r"[\s\W_]+", " ", message.strip().lower()).strip()


def _terminal_field(message: str, label: str) -> str | None:
    match = re.search(rf"(?m)^\s*{re.escape(label)}\s*[:：]\s*([^\n]+)", message)
    return match.group(1).strip() if match and match.group(1).strip() else None


def _terminal_errors(message: Any, mode: str, requested_mode: str, task_id: str | None) -> list[str]:
    if not isinstance(message, str) or not message.strip():
        return ["没有最终回复"]
    normalized = _normalized_message(message)
    if normalized in ACK_ONLY or (len(normalized) < 24 and any(token in normalized for token in ACK_ONLY)):
        return ["最终回复只有确认或准备开始，没有实际结果"]
    errors: list[str] = []
    if task_id and mode in {"standard", "strict"} and task_id not in message:
        errors.append(f"缺少治理任务 ID {task_id}")
    if mode in {"standard", "strict"}:
        if len(message.strip()) < 40:
            errors.append("最终回复过短，无法证明实际执行")
        if not any(marker in message.lower() for marker in EVIDENCE_MARKERS):
            errors.append("缺少验证、检查、文件、命令或结论证据")
    if mode == "strict" and requested_mode == "strict":
        if "【子 Agent 终态】" not in message:
            errors.append("缺少【子 Agent 终态】标题")
        missing = [label for label in STRICT_TERMINAL_FIELDS if _terminal_field(message, label) is None]
        if missing:
            errors.append("缺少终态字段：" + "、".join(missing))
        status = _terminal_field(message, "状态") or ""
        if not any(status.startswith(value) for value in ("完成", "阻塞", "需要决策")):
            errors.append("状态必须是完成、阻塞或需要决策")
    return errors


def _reported_status(message: str) -> str:
    status = _terminal_field(message, "状态") or ""
    english_status = _terminal_field(message, "Status") or ""
    normalized = (status or english_status).strip().lower().replace("_", " ")
    if normalized.startswith("需要决策") or normalized.startswith("needs decision"):
        return "needs_decision"
    if normalized.startswith("阻塞") or normalized.startswith("blocked"):
        return "blocked"
    return "complete"


def _handle_subagent_stop(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    agent_id = str(payload.get("agent_id") or "")
    message = payload.get("last_assistant_message")
    try:
        state = store.read(session_id)
    except (OSError, RuntimeError) as exc:
        return {"continue": True, "systemMessage": f"Subagent Governance 状态不可读，终态验收已降级放行：{exc}"}
    warning = getattr(store, "last_warning", None)
    task_id = state.get("agents", {}).get(agent_id)
    if not task_id:
        result = {"continue": True}
        if warning:
            result["systemMessage"] = str(warning)
        return result
    record = state.get("tasks", {}).get(task_id, {}) if task_id else {}
    mode = str(record.get("mode") or "light")
    requested_mode = str(record.get("requested_mode") or mode)
    errors = _terminal_errors(message, mode, requested_mode, task_id)
    max_retries = 1 if mode == "light" else 2

    if not errors:
        def complete(current: dict[str, Any]) -> None:
            if task_id and task_id in current["tasks"]:
                status = _reported_status(str(message))
                current["tasks"][task_id]["status"] = status
                current["tasks"][task_id]["updated_at"] = _now()
                current["tasks"][task_id]["result_document"] = {
                    "protocol": RESULT_PROTOCOL,
                    "task_id": task_id,
                    "status": status,
                    "result": _bounded(message, "已完成"),
                    "evidence": [],
                    "remaining": [],
                }
        try:
            store.update(session_id, complete)
        except (OSError, RuntimeError) as exc:
            return {"continue": True, "systemMessage": f"Subagent Governance 无法保存终态，已降级放行：{exc}"}
        return {"continue": True}

    retry_count = int(record.get("retry_count") or 0)
    reason = "子 Agent 终态需要补充：" + "；".join(errors) + "。请继续同一任务并给出真实执行结果，不要仅调整措辞。"
    if retry_count >= max_retries:
        def exhaust(current: dict[str, Any]) -> None:
            if task_id and task_id in current["tasks"]:
                current["tasks"][task_id]["status"] = "protocol_error"
                current["tasks"][task_id]["protocol_errors"] = errors
                current["tasks"][task_id]["updated_at"] = _now()
        try:
            store.update(session_id, exhaust)
        except (OSError, RuntimeError) as exc:
            return {"continue": True, "systemMessage": f"Subagent Governance 无法保存协议错误，已降级放行：{exc}"}
        return {
            "continue": True,
            "systemMessage": reason + "已达到纠错上限，记录为 protocol_error 并交给父任务处理。",
        }

    def retry(current: dict[str, Any]) -> None:
        if task_id and task_id in current["tasks"]:
            current["tasks"][task_id]["retry_count"] = retry_count + 1
            current["tasks"][task_id]["status"] = "retry_required"
            current["tasks"][task_id]["updated_at"] = _now()
    try:
        store.update(session_id, retry)
    except (OSError, RuntimeError) as exc:
        return {"continue": True, "systemMessage": f"Subagent Governance 无法保存重试状态，已降级放行：{exc}"}
    return {"decision": "block", "reason": reason}


def _active_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    cutoff = _now() - 12 * 60 * 60
    return [
        record for record in state.get("tasks", {}).values()
        if record.get("status") in ACTIVE_STATUSES and int(record.get("updated_at") or record.get("created_at") or 0) >= cutoff
    ]


def _handle_stop(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    try:
        active = _active_records(store.read(session_id))
    except (OSError, RuntimeError) as exc:
        return {"continue": True, "systemMessage": f"Subagent Governance 状态不可读，父任务结束检查已降级放行：{exc}"}
    warning = getattr(store, "last_warning", None)
    if not active:
        result = {"continue": True}
        if warning:
            result["systemMessage"] = str(warning)
        return result
    summary = "、".join(f"{record.get('task_id')}({record.get('status')})" for record in active[:6])
    reason = f"仍有未终态的治理子任务：{summary}。等待现有子 Agent 或处理其协议状态，不要重复派发。"
    if payload.get("stop_hook_active"):
        return {"continue": True, "systemMessage": reason}
    return {"decision": "block", "reason": reason}


def _handle_session_start(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    try:
        active = _active_records(store.read(session_id))
    except (OSError, RuntimeError) as exc:
        return {"continue": True, "systemMessage": f"Subagent Governance 状态不可读，恢复提示已降级：{exc}"}
    warning = getattr(store, "last_warning", None)
    if not active:
        result = {"continue": True}
        if warning:
            result["systemMessage"] = str(warning)
        return result
    lines = ["Subagent Governance 恢复了以下活跃任务："]
    for record in active[:8]:
        target = record.get("canonical_task_path") or record.get("agent_id") or "unmapped"
        lines.append(
            f"- {record.get('task_id')} | {record.get('mode')} | {record.get('status')} | "
            f"{record.get('objective') or record.get('task_name') or 'unnamed'} | "
            f"完成条件：{record.get('completion') or '未记录'} | 恢复对象：{target}"
        )
    lines.append("不要因上下文压缩重复创建这些子 Agent；优先等待或恢复原 Agent。")
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }


def _handle_session_end(payload: dict[str, Any], store: StateStore) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "unknown")
    try:
        store.delete(session_id)
    except (OSError, RuntimeError) as exc:
        return {"continue": True, "systemMessage": f"Subagent Governance 会话状态清理失败：{exc}"}
    return {"continue": True}


def handle(payload: dict[str, Any], store: StateStore | None = None) -> dict[str, Any] | None:
    if store is not None:
        active_store = store
    else:
        try:
            active_store = StateStore()
        except (OSError, RuntimeError) as exc:
            active_store = UnavailableStateStore(exc)
    event = str(payload.get("hook_event_name") or "")
    if event == "PreToolUse":
        kind = _tool_kind(str(payload.get("tool_name") or ""))
        if kind == "spawn":
            return _handle_spawn(payload, active_store)
        if kind in {"communication", "followup"}:
            return _handle_communication(payload, active_store)
        return None
    if event == "PostToolUse":
        return _handle_post_tool(payload, active_store)
    if event == "SubagentStart":
        return _handle_subagent_start(payload, active_store)
    if event == "SubagentStop":
        return _handle_subagent_stop(payload, active_store)
    if event == "Stop":
        return _handle_stop(payload, active_store)
    if event == "SessionStart":
        return _handle_session_start(payload, active_store)
    if event == "SessionEnd":
        return _handle_session_end(payload, active_store)
    return None


def _diagnose(session_id: str | None, data_root: Path | None = None) -> int:
    root = _prepare_private_directory(data_root.expanduser()) if data_root is not None else _data_root()
    if session_id:
        state = StateStore(root).read(session_id)
        print(json.dumps({"data_root": str(root.resolve()), "session": state}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    paths = sorted(root.glob("*.json"))
    summary = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        summary.append({
            "session_id": value.get("session_id"),
            "active": len(_active_records(value)),
            "tasks": len(value.get("tasks", {})),
            "health": value.get("health", {"status": "unknown"}),
            "updated_at": value.get("updated_at"),
        })
    print(json.dumps({"data_root": str(root.resolve()), "sessions": summary}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--session")
    parser.add_argument("--data-root", type=Path)
    args, unknown = parser.parse_known_args()
    if args.diagnose:
        return _diagnose(args.session, args.data_root)
    if unknown:
        print(f"unsupported arguments: {unknown}", file=sys.stderr)
        return 2
    try:
        raw_input = sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1)
        if len(raw_input.encode("utf-8")) > MAX_HOOK_INPUT_BYTES:
            raise ValueError(f"hook input exceeds {MAX_HOOK_INPUT_BYTES} bytes")
        payload = json.loads(raw_input)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be a JSON object")
        result = handle(payload)
    except Exception as exc:
        event = locals().get("payload", {}).get("hook_event_name") if isinstance(locals().get("payload"), dict) else None
        if event == "PreToolUse":
            result = _deny(f"Subagent Governance 解析失败：{exc}")
        else:
            result = {"continue": True, "systemMessage": f"Subagent Governance 运行失败，已降级放行：{exc}"}
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
