# `task_name` claim 修复方案

- 日期：2026-09-07
- 状态：实现完成，已通过本地门禁，待提交、部署和真实验收

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

部署后需重启 Codex，并在独立的 `gpt-5.6-terra / high` 任务中重新验证真实 claim → confirm → 生命周期链路。
