# 平台验证摘要

## 当前结论

本地实现以原生终态通知和三平面生命周期为边界。仓库验证不能证明稳定源、Marketplace、运行缓存、Hook trust 或真实平台事件投递。

### P9 local acceptance（2026-08-24）

- 精确目标 `937edbd75404dacca4439e03012245acc7bc8193`（`codex/current-only-improvements`，父提交 `424a2ff042df177b6c4119ff9228673d1dc6e53e`）的三套完整 unittest（Python 3.9、3.11、3.12，各 284 tests）、三套编译、development/精确 archive preflight、Plugin/Skill validator、`git diff --check` 和 212-test P9 A–F focused suite 均通过。
- P10 installer 的空/单/多 cache、明确 previous/current、完整 cache 快照/恢复、遗留 transaction、lock、same-filesystem 与所有安全边界已在本地 suite 覆盖。对正确 Manifest/version 但 target 缺文件、额外文件、模式变化的三次直接重放全部在 `post_install_verification` 失败并完整恢复；稳定源命令期间变化同样失败并恢复。事务报告有界保留 expected/actual stable/target digest 与失败阶段。
- `ruff` 与 `coverage` 不在验收环境 PATH，未安装、未运行，未记为通过。精确 archive preflight 的通过只证明提交 archive gate；没有安装、发布或真实平台验证，故不作 release-ready 结论。
- 这仍是本地验证。当时真实 native spawn/wait/notification、Hook trust、事件顺序、桌面 UI、restart/compact 恢复及真实 business-resume 都是 `not_checked`；P10 后续状态见下节。

### P10-B 全新真实平台复验（2026-08-24）

- 独立 `gpt-5.6-terra` / `high` 任务的 checkout 为 `37a3c9a02712fc5bc4ff026d31fcb24b892e3e61`，目标完整版本为 `0.4.0-rc.13+codex.20260824114902`。只读安装检查确认 stable/cache digest 都为 `8d4f05e2b61bf62af6bb86c55d0f1b7ec05febbe33c4c50ed7df9204b4e1f004`，路径隔离和 single-current-cache 均通过，且 `codex plugin list` 显示 installed/enabled。
- 新任务从 V1 重新取证：unmanaged native spawn 实际收到 Hook allow/no-state、exact target 和 child terminal。V2 的 governed spawn 实际收到 PreToolUse claim，并完成真实 wait 及完整 target 的 `list_agents({"path_prefix":"<完整 canonical target>"})`；但安装版诊断仍显示 `dispatch.state=claimed`、`post_observed=false`、`target_bound=false`，且 observation source 为空。
- 因此 V2 为 `failed`，其 raw list 不能冒充 canonical observation，也不以 child terminal 反推 PostToolUse 或 exact-list 成功。依 P10 停止 V3–V7；V4 business-resume、interrupt、Session event 与 restart/compact 均未执行。
- Skill 实际从目标 runtime cache 路径读取。Hook trust 和 Codex registration 的独立状态仍为 `not_checked`：PreToolUse Hook 实际工作不等于已确认 trust，`installed/enabled` 也不等于 Registry 结论。详见 `docs/validation/current-only-real-platform-validation.md`。

### P11 本地修复（已重新安装；真实复验在 V2 失败）

- 开发仓库将 current state 升级为严格 `state_format_version=8` / `state-v8`；旧 `state-v6` 和 `state-v7` 不读取、迁移或修复。
- 同一 target 的已关闭 resume source 不再遮蔽 current/open attempt；adapter 已接受但 canonical route 不安全时返回有界 route reason，且不写 observation。
- PostToolUse 以私有 current-namespace claimed-ID 索引先筛选 `session_id + tool_use_id`；命中后才构造 StateStore 并重验 canonical claimed pending。未知工具名命中仅记录 `unrecognized` 分类。receipt 的 expected/received ID 必须相等，先持久化 receipt 时刻的 parent-action 枚举/null、再可重入地执行 lifecycle transition；重试会先恢复该动作，随后由 operation-specific 规则覆盖。中间失败保留 receipt、claimed/reconcile 证据，完成后的重复 Post inert。索引发布/重建使用当前时间，过期 canonical claim 不会重新发布。receipt 不保存 message、原始工具名、contract、response values、child final、transcript 或 summary；无 ID、未命中和无关 catch-all 事件不构造 StateStore 且无输出。
- 这些仍是本地单元测试结论。目标测试版已重新安装并在新任务从 V1 开始复验；V2 已实际暴露 PostToolUse / target binding 未收口，故 V3–V7（含 P11 重点 V4）均未执行。真实 Post 投递、Hook matcher 行为和桌面 UI 仍未获得通过证据。

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

- 修复并重新安装后，从 V1 开始先重新验证 V2 governed spawn 的 PostToolUse receipt、target binding 与 exact-list canonical observation；只有此前置通过，才可继续 P11 重点 V4 follow-up receipt 与 attempt-2 exact-list binding。
- V3 normal message/terminal/close，随后 V5 interrupt/controlled reconciliation、V6 Stop/SessionStart/SessionEnd 及 V7 restart/compact 后的 mailbox/retained-target 恢复。
- Hook trust、Codex registration 与桌面 UI 的独立实际状态。

真实 correctness failure 后必须在开发仓库新任务复现和修复，重新完成相应本地门禁、重新获得安装授权并创建另一个全新 P10-B 任务；不得在当前验证环境热修后继续验收。

真实测试必须遵循项目 `AGENTS.md`：先完成开发仓库验收，取得安装授权并更新用于测试的本地插件，然后新建独立任务。未完成上述步骤时只能报告本地可验证边界。
