# 平台验证摘要

## 当前结论

本地实现以原生终态通知和三平面生命周期为边界。仓库验证不能证明稳定源、Marketplace、运行缓存、Hook trust 或真实平台事件投递。

### P9 local acceptance（2026-08-24）

- 对 `codex/current-only-improvements` 的 `57f270e489f16158efd0e8f94479509465ec9030`，三套最终工作树完整 unittest（Python 3.9、3.11、3.12）均通过，各 267 tests；三版本编译、development preflight、Plugin/Skill validator、当前 P9 报告白名单/未知 validation 文档拒绝门禁和 archive preflight 均通过。
- P9 本地综合结论仍为 `failed`：独立 mutation matrix 发现 canonical execution `task_name="bad name"` 被 runtime 按严格语义拒绝，却被 JSON Schema 接受。详见 `docs/validation/current-only-local-acceptance.md`。P9 不修改 Schema、实现或测试，因此停止于失败报告。
- runtime/Schema 的 producer corpus 仍同时接受；33/33 定义必填字段删除、7/7 未知字段注入及 5/6 非法 enum/count/digest/ref/name mutation 得到两者共同拒绝。唯一不一致即 execution `task_name` 格式。
- `ruff` 与 `coverage` 在验收环境中不存在，未安装，故相应可选命令未运行；这不代表它们通过。
- 这仍是本地验证。真实 native spawn/wait/notification、Hook trust、事件顺序、桌面 UI、restart/compact 恢复及真实 business-resume 都是 `not_checked`；只有在 P10 获得安装授权后，以新 task 单独验证。

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
