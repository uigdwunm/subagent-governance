"""Strict, state-free communication request parsing and rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from scripts.governance_contracts import TaskContract
    from scripts.governance_dispatch_rendering import render_list, render_verified_context
    from scripts.governance_errors import CommunicationPreparationError
    from scripts.governance_semantics import MAX_CONTRACT_TEXT, OPERATION_NATIVE_TOOLS, OPERATION_TYPES
except ModuleNotFoundError:
    from governance_contracts import TaskContract
    from governance_dispatch_rendering import render_list, render_verified_context
    from governance_errors import CommunicationPreparationError
    from governance_semantics import MAX_CONTRACT_TEXT, OPERATION_NATIVE_TOOLS, OPERATION_TYPES


COMMUNICATION_FIELD_LABELS = (
    ("purpose", "通信目的"),
    ("reason", "通信原因"),
    ("content", "具体内容"),
    ("expected_result", "期望结果"),
)


@dataclass(frozen=True)
class CommunicationRequest:
    target: str
    operation_type: str
    fields: dict[str, str]
    task_contract: Any | None


def _target(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CommunicationPreparationError("字段 target 必须是非空字符串")
    return value.strip()


def parse_communication_request(value: Any) -> CommunicationRequest:
    if not isinstance(value, dict):
        raise CommunicationPreparationError("通信输入必须是对象")
    allowed = {"target", "operation_type", "task_contract", *(name for name, _ in COMMUNICATION_FIELD_LABELS)}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CommunicationPreparationError("通信输入含未知字段：" + ",".join(unknown))
    operation_type = value.get("operation_type")
    if operation_type not in OPERATION_TYPES:
        raise CommunicationPreparationError("operation_type 必须是 normal_message、platform_recovery 或 business_resume")
    if operation_type == "business_resume":
        if "task_contract" not in value:
            raise CommunicationPreparationError("business_resume 缺少 task_contract")
    elif "task_contract" in value:
        raise CommunicationPreparationError(f"{operation_type} 不得携带 task_contract")
    fields: dict[str, str] = {}
    for name, label in COMMUNICATION_FIELD_LABELS:
        raw = value.get(name)
        if not isinstance(raw, str) or not raw.strip():
            raise CommunicationPreparationError(f"缺少字段 {name}（{label}）")
        normalized = " ".join(raw.split())
        if len(normalized) > MAX_CONTRACT_TEXT:
            raise CommunicationPreparationError(f"字段 {name}（{label}）长度不能超过 {MAX_CONTRACT_TEXT} 个字符")
        fields[name] = normalized
    return CommunicationRequest(_target(value.get("target")), str(operation_type), fields, value.get("task_contract"))


def parse_interrupt_request(value: Any) -> str:
    if not isinstance(value, dict):
        raise CommunicationPreparationError("中断输入必须是对象")
    unknown = sorted(set(value) - {"target"})
    if unknown:
        raise CommunicationPreparationError("中断输入含未知字段：" + ",".join(unknown))
    return _target(value.get("target"))


def native_tool_for_operation(operation_type: str) -> str:
    tool = OPERATION_NATIVE_TOOLS.get(operation_type)
    if not isinstance(tool, str) or not tool:
        raise CommunicationPreparationError(f"operation type 缺少原生工具映射：{operation_type}")
    return tool


def render_user_message(target: str, fields: dict[str, str], *, interrupt: bool = False) -> str:
    if interrupt:
        return "\n".join(("【子 Agent 中断】", f"对象：{target}"))
    return "\n".join((
        "【子 Agent 通信】", f"对象：{target}", f"目的：{fields['purpose']}",
        f"原因：{fields['reason']}", f"期望结果：{fields['expected_result']}",
    ))


def render_message(
    fields: dict[str, str], operation_type: str, *, resume_contract: TaskContract | None = None,
    resume_context_verification: dict[str, Any] | None = None,
    resume_identity: dict[str, Any] | None = None,
) -> str:
    lines = [f"【通信目的】{fields['purpose']}", f"【通信原因】{fields['reason']}", f"【具体内容】{fields['content']}"]
    if operation_type == "business_resume":
        if resume_contract is None or resume_context_verification is None or resume_identity is None:
            raise CommunicationPreparationError("business_resume 缺少已验证的契约、上下文或新 attempt 身份")
        lines.extend((
            "【本次恢复身份】",
            f"task_id：{resume_identity['task_id']}", f"attempt：{resume_identity['attempt']}",
            f"task_ref：{resume_identity['task_ref']}", f"target：{resume_identity['target']}",
            "完成、阻塞或需要决策时，请使用以上 task_id、attempt、target 发送终态通知；不得沿用旧 attempt。",
            "【继续执行目标】", resume_contract.objective, "【工作范围】", render_list(resume_contract.work_scope),
            "【禁止范围】", render_list(resume_contract.forbidden_scope), "【完成条件】", render_list(resume_contract.completion_conditions),
            "【验收证据】", render_list(resume_contract.evidence_requirements), "【必需上下文】",
            render_verified_context(resume_context_verification),
        ))
    lines.append(f"【期望结果】{fields['expected_result']}")
    return "\n".join(lines)


def native_args(target: str, message: str, *, interrupt: bool = False) -> dict[str, str]:
    return {"target": target} if interrupt else {"target": target, "message": message}
