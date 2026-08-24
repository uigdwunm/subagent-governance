# 平台验证摘要

## 当前结论

本地实现以原生终态通知和三平面生命周期为边界。仓库验证不能证明稳定源、Marketplace、运行缓存、Hook trust 或真实平台事件投递。

### P9 local acceptance（2026-08-24）

- 精确目标 `937edbd75404dacca4439e03012245acc7bc8193`（`codex/current-only-improvements`，父提交 `424a2ff042df177b6c4119ff9228673d1dc6e53e`）的三套完整 unittest（Python 3.9、3.11、3.12，各 284 tests）、三套编译、development/精确 archive preflight、Plugin/Skill validator、`git diff --check` 和 212-test P9 A–F focused suite 均通过。
- P10 installer 的空/单/多 cache、明确 previous/current、完整 cache 快照/恢复、遗留 transaction、lock、same-filesystem 与所有安全边界已在本地 suite 覆盖。对正确 Manifest/version 但 target 缺文件、额外文件、模式变化的三次直接重放全部在 `post_install_verification` 失败并完整恢复；稳定源命令期间变化同样失败并恢复。事务报告有界保留 expected/actual stable/target digest 与失败阶段。
- `ruff` 与 `coverage` 不在验收环境 PATH，未安装、未运行，未记为通过。精确 archive preflight 的通过只证明提交 archive gate；没有安装、发布或真实平台验证，故不作 release-ready 结论。
- 这仍是本地验证。当时真实 native spawn/wait/notification、Hook trust、事件顺序、桌面 UI、restart/compact 恢复及真实 business-resume 都是 `not_checked`；P10 后续状态见下节。

### P10-B 新任务真实平台尝试（2026-08-24）

- P10-B 已在安装后新建的独立 `gpt-5.6-terra` / `high` 任务中开始。开始时目标完整版本 `0.4.0-rc.13+codex.20260824081325`、stable/cache digest `a447a01694e88c1263970f1e7029d53bcd3a6be9c5e0d5b5e362b8991d7924d8`、路径隔离和 single-current-cache 均由安装检查实际通过；`codex plugin list` 也显示插件为 enabled。
- V1 的真实 unmanaged native `spawn_agent` 没有获得 fail-open：PreToolUse 实际尝试运行不存在的 cache `0.4.0-rc.14+codex.20260824014336/scripts/subagent_governance.py`，而唯一实际 cache 是目标 `rc.13`，导致调用被阻断且未创建 target/tool-use/state-v6 session。这是已取得的真实平台失败证据，不是 Hook fixture。
- 因此 P10-B 按方案停止，V2–V6 仍为 `not_checked`，V7 为 `not_checked_platform_unavailable`；没有把安装文件、Skill 可见性或本地测试冒充 Hook trust、registration、事件投递、wait/notification 或 business-resume 的通过证据。详见 `docs/validation/current-only-real-platform-validation.md`。

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

在修复当前已见的 stale Hook cache-version 路径不一致后，必须由另一个新 P10-B 任务重新执行全部真实场景；本次失败任务不得在热修改安装环境后继续充当验收。

真实测试必须遵循项目 `AGENTS.md`：先完成开发仓库验收，取得安装授权并更新用于测试的本地插件，然后新建独立任务。未完成上述步骤时只能报告本地可验证边界。
