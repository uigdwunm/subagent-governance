# 平台验证摘要

更新时间：2026-08-18

## 当前结论

v5 本地实现以原生终态通知和三平面生命周期为边界。当前改动只更新开发仓库，尚未同步稳定源、Marketplace 或运行缓存，也未在新 Codex 对话中完成真实插件测试，因此不能宣称已完成发布级或真实平台验收。

## 已由本地测试覆盖

- PreparedContract 与 governed spawn 的发送前门禁。
- exact dispatch target identity 和 retained provenance。
- normal message、platform recovery、business resume 和 interrupt 的 pending/claim 对账。
- `list_agents` 顶层有限 adapter 与 exact target 绑定。
- 平台终态先到时进入 `await_notification`。
- 父 Agent 记录 exact terminal notification 后进入 `await_parent`。
- 通知重放幂等、sender mismatch 拒绝和 terminal status 冲突 reconcile。
- `close_task`、duplicate candidate 和 tombstone。
- Group required member 的 notification/closed 汇总。
- diagnose 不创建或扫描旧 `results/`。
- v4 状态向 v5 三平面降维迁移。

## 平台能力边界

- 插件不注册官方 `SubagentStart`、`SubagentStop`；它们保留在能力契约 fixture 中，但不参与运行时状态维护或终态通知处理。
- transcript、summary、final history 和未知 Hook 扩展不作为 correctness authority。
- list terminal observation 不替代原生 child notification。
- 插件不保存通知正文，不判断业务质量，不提供 accept/reject 状态。
- Stop 当前只给 advisory 并固定 fail-open。

## 尚待真实插件验证

- 新对话中真实 spawn、wait 和 native child notification 的可见性。
- 父线程取得 exact sender target 的稳定性。
- Hook trust、事件顺序和桌面 UI 展示。
- restart/compact 后 mailbox 与 retained target 的恢复表现。
- business resume 在真实 follow-up 工具响应中的状态转换。

真实测试必须遵循项目 `AGENTS.md`：先完成开发仓库验证，再更新用于测试的本地插件，并在当前项目新建独立对话；默认模型 `gpt-5.6-terra`、推理强度 `high`。未完成上述步骤前，本文件只报告本地可验证边界。
