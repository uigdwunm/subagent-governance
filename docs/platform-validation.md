# 平台验证摘要

## 当前结论

本地实现以原生终态通知和三平面生命周期为边界。仓库验证不能证明稳定源、Marketplace、运行缓存、Hook trust 或真实平台事件投递。

### P9 local acceptance（2026-08-24）

- 精确目标 `166fa492c5f6a053d25a791f9033f748ca84bded`（`codex/current-only-improvements`）的 archive preflight、三套完整 unittest（Python 3.9、3.11、3.12，各 271 tests）、三套编译、development preflight、Plugin/Skill validator 与 P9 A–F 180-test focused suite 均通过。
- P9 本地综合结论为 `passed`。task-name 修复已独立复验：execution 接受合法 initial 名与 `null` same-Agent resume；空格、错误 mode/semantic/ref/长度/字符和超长值同时被 runtime/Schema 拒绝；Prepared/native 同时拒绝非法值和 `null`。详见 `docs/validation/current-only-local-acceptance.md`。
- `ruff` 与 `coverage` 在验收环境中不存在，未安装；相关可选命令未运行，未被记为通过。该环境事实不改变本地 P9 结论。
- 这仍是本地验证。真实 native spawn/wait/notification、Hook trust、事件顺序、桌面 UI、restart/compact 恢复及真实 business-resume 都是 `not_checked`；只有在 P10 获得安装授权后，才可在新 task 中单独验证。

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
- diagnose 不创建或修改运行状态。
- StateStore 只接受当前格式，其他版本原样拒绝。

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

真实测试必须遵循项目 `AGENTS.md`：先完成开发仓库验证，再取得安装授权并更新用于测试的本地插件，然后新建独立任务。未完成上述步骤时只能报告本地可验证边界。
