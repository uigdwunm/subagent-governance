"""Pure rendering of verified contract context into dispatch-facing output."""

from __future__ import annotations

from typing import Any

try:
    from scripts.governance_contracts import TaskContract
    from scripts.governance_errors import ContextVerificationError
except ModuleNotFoundError:
    from governance_contracts import TaskContract
    from governance_errors import ContextVerificationError


def context_projection(contract: TaskContract) -> tuple[str, str]:
    if contract.context_strategy == "isolated":
        return "none", "否"
    if contract.context_strategy == "limited":
        assert contract.context_turns is not None
        return str(contract.context_turns), f"否（仅继承最近 {contract.context_turns} 轮）"
    return "all", "是"


def render_list(values: list[str]) -> str:
    return "- 无" if not values else "\n".join(f"- {value}" for value in values)


def render_verified_context(verification: dict[str, Any]) -> str:
    if verification.get("mode") == "none":
        return "- 无"
    baseline = verification.get("baseline")
    if not isinstance(baseline, dict):
        raise ContextVerificationError("context verification 缺少 baseline")
    baseline_line = (
        f"- 基线：git_commit {baseline.get('revision')}"
        if baseline.get("kind") == "git_commit"
        else "- 基线：working_tree（prepare 与 spawn 双重校验）"
    )
    lines = [f"- 工作区：{verification.get('workspace_root')}", baseline_line]
    paths = verification.get("required_paths")
    if not isinstance(paths, list):
        raise ContextVerificationError("context verification 缺少 required_paths")
    lines.extend(f"- {item['path']}（{item['type']}，已验证）" for item in paths if isinstance(item, dict))
    return "\n".join(lines)


def render_dispatch_prompt(contract: TaskContract, context_verification: dict[str, Any]) -> str:
    current_state = contract.current_state or "无额外未落盘状态"
    context_reason = contract.context_reason or "默认隔离；任务背景已写入本首句"
    return "\n".join([
        f"【治理等级】{contract.resolved_mode}", "【唯一当前目标】", contract.objective, "",
        "【背景】", contract.background, "", "【工作范围】", render_list(contract.work_scope), "",
        "【禁止范围】", render_list(contract.forbidden_scope), "", "【相关文件】",
        render_list(contract.relevant_files), "", "【必需上下文】",
        render_verified_context(context_verification), "", "【当前状态】", current_state, "",
        "【上下文策略】", f"{contract.context_strategy}：{context_reason}", "", "【完成条件】",
        render_list(contract.completion_conditions), "", "【验收证据】",
        render_list(contract.evidence_requirements), "", "【恢复与终态义务】",
        "完成、阻塞、失败或需要决策时，向父 Agent发送明确终态通知；不要只回复收到、明白或开始执行。",
        "平台或调用结果未知时如实报告，不得自行重派、伪造成功或覆盖其他 attempt。", "",
    ])


def render_dispatch_user_message(contract: TaskContract, context_verification: dict[str, Any]) -> str:
    _native_context, context_display = context_projection(contract)
    model_display = contract.model or "继承主 Agent（未显式覆盖）"
    effort_display = contract.reasoning_effort or "继承主 Agent 当前强度（未显式覆盖）"
    mode_line = f"治理等级：{contract.resolved_mode}"
    if contract.requested_mode == "auto":
        mode_line = f"请求治理方式：auto；实际治理等级：{contract.resolved_mode}；解析原因：{contract.resolution_reason}"
    return "\n".join((
        "【子 Agent 派发】", f"目标：{contract.objective}", mode_line,
        f"模型：{model_display}", f"强度：{effort_display}",
        f"是否继承主线程全部上下文：{context_display}",
        "必需上下文：" + ("明确无材料依赖" if context_verification.get("mode") == "none" else f"已验证 {len(context_verification.get('required_paths', []))} 项"),
        "工作范围：" + "；".join(contract.work_scope),
        "完成条件：" + "；".join(contract.completion_conditions),
        "回传要求：完成、阻塞或需要决策时，向父 Agent发送明确终态通知",
    ))


def spawn_args(contract: TaskContract, task_name: str, context_verification: dict[str, Any]) -> dict[str, Any]:
    fork_turns, _context_display = context_projection(contract)
    result: dict[str, Any] = {
        "task_name": task_name,
        "message": render_dispatch_prompt(contract, context_verification),
        "fork_turns": fork_turns,
    }
    if contract.model is not None:
        result["model"] = contract.model
    if contract.reasoning_effort is not None:
        result["reasoning_effort"] = contract.reasoning_effort
    return result


_context_projection = context_projection
_render_list = render_list
_render_verified_context = render_verified_context
_spawn_args = spawn_args
