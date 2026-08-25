"""Pure rendering for TaskContract v2 and native spawn parameters."""

from __future__ import annotations

from typing import Any

try:
    from scripts.governance_contracts import TaskContract
except ModuleNotFoundError:
    from governance_contracts import TaskContract


def _list(values: list[str]) -> str:
    return "- 无" if not values else "\n".join(f"- {value}" for value in values)


def render_dispatch_prompt(contract: TaskContract, verification: dict[str, Any] | None) -> str:
    verified = "无"
    if verification is not None:
        verified = f"{verification['workspace_root']}（{len(verification['required_paths'])} 项已验证材料）"
    return "\n".join(
        [
            f"【治理 profile】{contract.profile}",
            "【唯一当前目标】", contract.objective, "",
            "【上下文摘要】", contract.context["summary"] or "无", "",
            "【工作范围】", _list(contract.scope), "",
            "【禁止范围】", _list(contract.forbidden_scope), "",
            "【定位路径】", _list(contract.context["paths"]), "",
            "【已验证材料】", verified, "",
            "【完成条件】", _list(contract.completion), "",
            "【验收证据】", _list(contract.evidence), "",
            "【终态义务】",
            "完成、阻塞、失败或需要决策时，向父 Agent 发送明确终态通知。",
            "不要从 task name、时间、list_agents、summary、transcript 或 child final 推断治理身份。",
        ]
    )


def render_dispatch_user_message(contract: TaskContract, verification: dict[str, Any] | None) -> str:
    model = contract.spawn["model"] or "继承父 Agent"
    effort = contract.spawn["reasoning_effort"] or "继承父 Agent"
    return "\n".join(
        [
            "【子 Agent 派发】",
            f"目标：{contract.objective}",
            f"治理 profile：{contract.profile}",
            f"模型：{model}",
            f"推理强度：{effort}",
            f"fork_turns：{contract.spawn['fork_turns']}",
            "范围：" + "；".join(contract.scope),
            "完成条件：" + "；".join(contract.completion),
            "已验证上下文：" + ("无" if verification is None else f"{len(verification['required_paths'])} 项"),
            "原生 spawn 返回后必须立即 confirm exact target；confirm 前中断保持 claimed/unbound。",
        ]
    )


def expected_native_parameters(
    contract: TaskContract, task_name: str, verification: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "task_name": task_name,
        "message": render_dispatch_prompt(contract, verification),
        "fork_turns": contract.spawn["fork_turns"],
        "model": contract.spawn["model"],
        "reasoning_effort": contract.spawn["reasoning_effort"],
    }


def spawn_args(contract: TaskContract, task_name: str, verification: dict[str, Any] | None) -> dict[str, Any]:
    expected = expected_native_parameters(contract, task_name, verification)
    return {key: value for key, value in expected.items() if value is not None}


__all__ = ["expected_native_parameters", "render_dispatch_prompt", "render_dispatch_user_message", "spawn_args"]
