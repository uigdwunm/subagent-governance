"""Safe, transient Hook diagnostics; never serialize exception text or inputs."""
from __future__ import annotations

try:
    from scripts.governance_errors import (
        ClaimFailure,
        ContextMaterialConflictError,
        ContextVerificationError,
        NativeInputMismatch,
        NativeInputUnavailable,
        PreparedCapabilityExpired,
        StateConflictError,
        StateStoreError,
    )
except ModuleNotFoundError:
    from governance_errors import (
        ClaimFailure,
        ContextMaterialConflictError,
        ContextVerificationError,
        NativeInputMismatch,
        NativeInputUnavailable,
        PreparedCapabilityExpired,
        StateConflictError,
        StateStoreError,
    )


_REASONS = {
    "input_unavailable": "原生输入无法验证，不能确定治理检查通过",
    "session_unavailable": "exact session_id 无法验证",
    "call_id_unavailable": "tool_use_id 无法验证",
    "marker_conflict": "治理标记无效或与 task_name 不一致，请核对 prepare-dispatch 输出",
    "native_conflict": "已知原生参数形态或身份不一致",
    "claim_conflict": "任务引用、阶段、capability 或冻结参数冲突",
    "preparation_expired": "派发准备已过期；核对本次原生调用回执和 exact Session 状态后处置",
    "material_conflict": "声明材料冲突：与冻结基线不一致",
    "material_unavailable": "声明材料校验无法完成",
    "state_unavailable": "账本访问或校验无法完成",
    "claim_commit_unknown": "claim 提交结果无法确认",
    "internal_error": "Hook 内部处理无法完成",
    "input_parse_error": "Hook 输入解析失败，无法判定治理意图",
    "claimed": "claim 已确认",
    "already_claimed": "同一原生调用的 claim 已确认",
    "claimed_after_write_error": "写入报错后精确回读确认同一 claim",
}
_CLAIMS = {
    "not_attempted": "本次未尝试 claim，不推断既有账本事实",
    "unconfirmed": "本次未确认 claim，不代表账本中不存在 claim",
    "unknown": "claim 结果不确定，不能声称未提交",
    "confirmed": "仅确认 claim，不证明原生创建或业务成功",
}


def diagnostic(code: str, *, stage: str, claim: str, action: str) -> str:
    """Arguments are internal constants, never provider text or exception strings."""
    decision = {"allow": "Hook 返回允许（fail-open）", "deny": "Hook 返回拒绝",
                "continue": "Hook 返回继续（fail-open）", "claimed": "Hook 返回允许"}[action]
    if claim == "confirmed":
        next_step = "依据本次原生返回的 exact target 执行 confirm。"
    elif code == "preparation_expired" and action == "deny":
        next_step = (
            "核对同一次原生工具回执和 exact task 状态；仅在回执明确 PreToolUse 阻止原生执行"
            "且任务仍为 prepared 时登记 failed。是否重新派发依据用户明确授权和上层流程；"
            "否则不得推断 Agent 未创建。"
        )
    elif action == "deny":
        next_step = "处理已确认冲突；不猜身份、不自动重派，不据此推断平台已经中止。"
    else:
        next_step = (
            "核对可取得的本次原生回执和 exact-session 状态；缺 claim 的 confirm 进入 reconcile；"
            "不猜身份、不自动重派，不将降级视为检查通过。"
        )
    return (
        f"Subagent Governance code={code} stage={stage} claim={claim}：{_REASONS[code]}。"
        f"{decision}；{_CLAIMS[claim]}。原生执行结果须以实际回执为准。{next_step}"
    )


def classify_failure(exc: Exception) -> tuple[str, str, str, str]:
    """Return code, stage, claim evidence, action without parsing error messages."""
    stage = "claim"
    if isinstance(exc, ClaimFailure):
        stage = exc.stage
        if stage == "commit":
            return "claim_commit_unknown", stage, "unknown", "allow"
        exc = exc.__cause__ or exc
    if isinstance(exc, NativeInputUnavailable):
        code, action = "input_unavailable", "allow"
    elif isinstance(exc, NativeInputMismatch):
        code, action = "native_conflict", "deny"
    elif isinstance(exc, PreparedCapabilityExpired):
        code, action = "preparation_expired", "deny"
    elif isinstance(exc, StateConflictError):
        code = "material_conflict" if isinstance(exc.__cause__, ContextMaterialConflictError) else "claim_conflict"
        action = "deny"
    elif isinstance(exc, ContextVerificationError) or stage == "material":
        code, action = "material_unavailable", "allow"
    elif isinstance(exc, (StateStoreError, OSError)):
        code, action = "state_unavailable", "allow"
    else:
        code, action = "internal_error", "allow"
    return code, stage, "unconfirmed", action
