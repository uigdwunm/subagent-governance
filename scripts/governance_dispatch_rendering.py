"""Pure rendering for TaskContract v2 and native spawn parameters."""

from __future__ import annotations

from typing import Any

try:
    from scripts.governance_contracts import TaskContract
    from scripts.governance_native_adapter import render_native_spawn
except ModuleNotFoundError:
    from governance_contracts import TaskContract
    from governance_native_adapter import render_native_spawn


def _list(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values)


def render_dispatch_prompt(contract: TaskContract, verification: dict[str, Any] | None) -> str:
    sections = [
        ("唯一当前目标", contract.objective),
        ("上下文摘要", contract.context["summary"]),
        ("工作范围", _list(contract.scope)),
        ("禁止范围", _list(contract.forbidden_scope)),
        ("定位路径", _list(contract.context["paths"])),
    ]
    if verification is not None:
        sections.append((
            "已验证材料",
            "\n".join([
                f"工作区：{verification['workspace_root']}",
                "基线：" + verification["baseline"]["kind"]
                + (f" {verification['baseline']['revision']}" if verification["baseline"]["revision"] else ""),
                *[f"- {item['path']} ({item['type']})" for item in verification["required_paths"]],
                "仅覆盖校验时点的声明材料；不保证执行期间不变，不提供工作区隔离。",
            ]),
        ))
    sections.extend([
        ("完成条件", _list(contract.completion)),
        ("验收证据", _list(contract.evidence)),
        ("终态义务", (
            "普通问题、补充信息请求和方案对齐使用进行中消息，"
            "不因此宣称本次执行结束；继续不依赖该决定的工作。\n"
            "完成交付、明确停止，或确实无法继续且需要交还控制时，"
            "向父 Agent 发送明确终态通知，说明结果、验证证据、剩余事项和所需决定。"
        )),
    ])
    return "\n\n".join(
        f"【{title}】\n{value}" for title, value in sections if value
    )


def render_dispatch_user_message(contract: TaskContract, verification: dict[str, Any] | None) -> str:
    model = contract.spawn["model"] or "未覆盖，按原生配置解析"
    effort = contract.spawn["reasoning_effort"] or "未覆盖，按原生配置解析"
    turns = contract.spawn["fork_turns"]
    context = {"none": "隔离", "all": "完整继承"}.get(turns, f"有限继承 {turns} 轮")
    lines = [
        f"子 Agent 目标：{contract.objective}",
        "范围：" + "；".join(contract.scope) + "；完成条件：" + "；".join(contract.completion),
        f"配置：模型 {model}；推理 {effort}；上下文{context}（fork_turns={turns}）；治理 {contract.profile}。",
    ]
    if verification is not None:
        lines.append(f"已验证材料：{len(verification['required_paths'])} 项。")
    return "\n".join(lines)


def expected_native_parameters(
    contract: TaskContract, task_name: str, verification: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "task_name": task_name,
        "message": f"[subagent-governance:{task_name}]\n" + render_dispatch_prompt(contract, verification),
        "fork_turns": contract.spawn["fork_turns"],
        "model": contract.spawn["model"],
        "reasoning_effort": contract.spawn["reasoning_effort"],
    }


def spawn_args(contract: TaskContract, task_name: str, verification: dict[str, Any] | None, *, native_interface: str) -> dict[str, Any]:
    expected = expected_native_parameters(contract, task_name, verification)
    return render_native_spawn(native_interface, expected)


__all__ = ["expected_native_parameters", "render_dispatch_prompt", "render_dispatch_user_message", "spawn_args"]
