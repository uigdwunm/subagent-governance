# 平台验证摘要

## 当前结论

本地实现以原生终态通知和三平面生命周期为边界。仓库验证不能证明稳定源、Marketplace、运行缓存、Hook trust 或真实平台事件投递。

### P9 local acceptance（2026-08-24）

- 精确目标 `f6a72aed07554c2473b502f1d6ad19613005bd02`（`codex/current-only-improvements`，父提交 `37774b12269124076a8297f08e7803a1b3903b9d`）的三套完整 unittest（Python 3.9、3.11、3.12，各 280 tests）、三套编译、development/精确 archive preflight、Plugin/Skill validator、`git diff --check` 和 208-test P9 A–F focused suite 均通过。
- P9 本地综合结论为 `failed`：P10 installer 对 target 只计算、却不校验预期 digest；Manifest/version 正确但内容不同的 target 会以 `install_succeeded` 收敛，并删除完整 pre-install cache 集合而不回滚。详见 `docs/validation/current-only-local-acceptance.md`。
- `ruff` 与 `coverage` 不在验收环境 PATH，未安装、未运行，未记为通过。发现正确性问题后验收停止，报告更新后没有再次复跑完整门禁。
- 这仍是本地验证。真实 native spawn/wait/notification、Hook trust、事件顺序、桌面 UI、restart/compact 恢复及真实 business-resume 都是 `not_checked`；P10 安装与真实平台验证均不得在本失败结论下进行。

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

真实测试必须遵循项目 `AGENTS.md`：先修复并重新完成开发仓库验收，取得安装授权并更新用于测试的本地插件，然后新建独立任务。未完成上述步骤时只能报告本地可验证边界。
