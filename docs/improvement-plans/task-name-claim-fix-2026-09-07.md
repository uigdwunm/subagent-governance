# `task_name` claim 修复方案

- 日期：2026-09-07
- 状态：已提交、部署；2026-09-09 重新信任 Hook 后，独立真实验收核心链路通过，中断回执保留平台 unknown 边界

## 目标

修复真实 Codex 派发中 Agent 已创建但 ledger 仍停留在 `prepared` 的问题。

## 实现决策

当前 `collaboration.spawn_agent` 以 `task_name` 作为治理身份，以 `fork_turns`、model 和 reasoning_effort 作为派发配置。Hook claim 使用这些稳定字段定位并校验 prepared task，不再把平台可能重构的 `message` 作为跨阶段逐字匹配条件。`confirm` 仍只接受原生返回的 exact target，不根据 task name 猜测 target。

本次实现保留现有适配模块和状态格式，只修改 claim 比较边界，避免把历史参数形状重新引入当前流程。

## 验收

- message 被平台重写时，task_name claim 仍成功；
- task_name 或派发配置冲突时仍拒绝；
- confirm 没有 claim 时仍进入 reconcile；
- unmanaged spawn 保持零状态；
- 全量 unittest、compileall、Plugin validator、Skill validator 和 diff 检查通过。

部署、重启及独立 `gpt-5.6-terra / high` 验收已完成。首次复验缺少 claim；只读 Hook 检查发现 PreToolUse 定义为 modified，用户重新信任后 claim → confirm → 生命周期链路通过。完整证据与未覆盖范围见 [state-v10 真实验收](../validation/state-v10-hook-trust-2026-09-09.md)。本次验收不证明加密正文与 prepare 明文完全一致。
