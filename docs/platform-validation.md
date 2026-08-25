# 平台验证摘要（历史 v8 证据；v9 尚未部署）

> 本文保留导致减法收口决策的历史平台证据，不描述当前 state-v9 runtime 能力。
> state-v9 第一纵向切片只有本地验证，尚未安装、发布或在重启后的新任务中真实复验。

## 当前结论

以下结论属于减法收口前实现。仓库验证不能证明稳定源、Marketplace、运行缓存、Hook trust 或真实平台事件投递。

### P9 local acceptance（2026-08-24）

- 精确目标 `937edbd75404dacca4439e03012245acc7bc8193`（`codex/current-only-improvements`，父提交 `424a2ff042df177b6c4119ff9228673d1dc6e53e`）的三套完整 unittest（Python 3.9、3.11、3.12，各 284 tests）、三套编译、development/精确 archive preflight、Plugin/Skill validator、`git diff --check` 和 212-test P9 A–F focused suite 均通过。
- P10 installer 的空/单/多 cache、明确 previous/current、完整 cache 快照/恢复、遗留 transaction、lock、same-filesystem 与所有安全边界已在本地 suite 覆盖。对正确 Manifest/version 但 target 缺文件、额外文件、模式变化的三次直接重放全部在 `post_install_verification` 失败并完整恢复；稳定源命令期间变化同样失败并恢复。事务报告有界保留 expected/actual stable/target digest 与失败阶段。
- `ruff` 与 `coverage` 不在验收环境 PATH，未安装、未运行，未记为通过。精确 archive preflight 的通过只证明提交 archive gate；没有安装、发布或真实平台验证，故不作 release-ready 结论。
- 这仍是本地验证。当时真实 native spawn/wait/notification、Hook trust、事件顺序、桌面 UI、restart/compact 恢复及真实 business-resume 都是 `not_checked`；P10 后续状态见下节。

### P10-B 全新真实平台复验（2026-08-24）

- 独立 `gpt-5.6-terra` / `high` 任务的 checkout 为 `37a3c9a02712fc5bc4ff026d31fcb24b892e3e61`，目标完整版本为 `0.4.0-rc.13+codex.20260824114902`。当时的只读安装检查确认 stable/cache digest 都为 `8d4f05e2b61bf62af6bb86c55d0f1b7ec05febbe33c4c50ed7df9204b4e1f004`，路径隔离和当时的单缓存规则均通过，且 `codex plugin list` 显示 installed/enabled；P13 后的检查语义为 current + 可选 retained previous compatibility cache。
- 新任务从 V1 重新取证：unmanaged native spawn 实际收到 Hook allow/no-state、exact target 和 child terminal。V2 的 governed spawn 实际收到 PreToolUse claim，并完成真实 wait 及完整 target 的 `list_agents({"path_prefix":"<完整 canonical target>"})`；但安装版诊断仍显示 `dispatch.state=claimed`、`post_observed=false`、`target_bound=false`，且 observation source 为空。
- 因此 V2 为 `failed`，其 raw list 不能冒充 canonical observation，也不以 child terminal 反推 PostToolUse 或 exact-list 成功。依 P10 停止 V3–V7；V4 business-resume、interrupt、Session event 与 restart/compact 均未执行。
- Skill 实际从目标 runtime cache 路径读取。Hook trust 和 Codex registration 的独立状态仍为 `not_checked`：PreToolUse Hook 实际工作不等于已确认 trust，`installed/enabled` 也不等于 Registry 结论。详见 `docs/validation/current-only-real-platform-validation.md`。

### P11 本地修复（已重新安装；真实复验在 V2 失败）

- 开发仓库将 current state 升级为严格 `state_format_version=8` / `state-v8`；旧 `state-v6` 和 `state-v7` 不读取、迁移或修复。
- 同一 target 的已关闭 resume source 不再遮蔽 current/open attempt；adapter 已接受但 canonical route 不安全时返回有界 route reason，且不写 observation。
- PostToolUse 以私有 current-namespace claimed-ID 索引先筛选 `session_id + tool_use_id`；命中后才构造 StateStore 并重验 canonical claimed pending。未知工具名命中仅记录 `unrecognized` 分类。receipt 的 expected/received ID 必须相等，先持久化 receipt 时刻的 parent-action 枚举/null、再可重入地执行 lifecycle transition；重试会先恢复该动作，随后由 operation-specific 规则覆盖。中间失败保留 receipt、claimed/reconcile 证据，完成后的重复 Post inert。索引发布/重建使用当前时间，过期 canonical claim 不会重新发布。receipt 不保存 message、原始工具名、contract、response values、child final、transcript 或 summary；无 ID、未命中和无关 catch-all 事件不构造 StateStore 且无输出。
- 这些仍是本地单元测试结论。目标测试版已重新安装并在新任务从 V1 开始复验；V2 已实际暴露 PostToolUse / target binding 未收口，故 V3–V7（含 P11 重点 V4）均未执行。真实 Post 投递、Hook matcher 行为和桌面 UI 仍未获得通过证据。

### P12-A 新重启任务中的最小 Post 诊断及 cleanup（2026-08-24）

- 新的 `gpt-5.6-terra` / `high` 任务在 `188a63142cc563dba520a36c95d64bdcb70cf823` 上只读复核后，实际加载版本为 `0.4.0-rc.13+codex.20260824133045`；stable/cache digest 均为 `4f881c261e7fbcc8d23ed1313bccafee64d2c67cd795662874cff460ab8a0775`。当前 cache 与 development/stable 规则一致，rolling two-version cache 健康；独立 Hook trust/registration 仍为 `not_checked`。
- 三次彼此独立的最小 governed spawn 均完成 Pre marker 发布并实际创建 child。每次 sidecar diagnose 都没有保存关联 receipt，且 canonical attempt 仍是 Pre claim 基线，未发生 recognized legacy Post transition。没有记录 tool-use ID、原始工具名、prompt、response、message、child final 或完整 envelope。
- 这只证明插件没有保存关联到这些 claim 的 Post 事实；它不证明平台没有投递，也不定位工具名、ID、router 或 handler 阶段。根据 P12-A 矩阵，P12-B 保持冻结，不能实施 matcher-only 或 storage/handler 修复，也不得以 list、时间、task name 或 child terminal 推断 owner。
- 后续的独立 P12-A probe cleanup 已在开发仓库完成本地门禁：临时 marker/receipt storage、claim 后发布、sidecar admission、diagnostics/view 投影、固定 probe reason 和专用测试均已删除；历史 probe 目录不读取、不迁移、不清理、不重写。没有安装或真实复验。下一步只能经用户重新授权 P10-A 安装、等待重启后在新的独立任务从 V1 验证不含 probe 的环境。详见 `docs/validation/current-only-real-platform-validation.md`。

### P12-A probe cleanup 安装后重启复验（2026-08-25）

- 当前运行版本为 `0.4.0-rc.13+codex.20260825004015`；开发 checkout 为 `dbad9eb903c188614d5739f21b0bd291e5db80fa`，包含 cleanup `4c2567e`。stable/current digest 均为 `7c6409be936130bcd9e384203273ed5e7cb6a6b30a9fa80ab37aa884e74eea92`，双缓存健康且保留一个兼容缓存。实际加载 Skill 与 installed/enabled 版本一致。
- V1 unmanaged spawn 再次证明 fail-open/no-state 和独立终态；V2 的 fresh light/isolated governed spawn 成功完成 prepare、Pre claim、原生派发、wait 与 exact list，但 canonical 仍是 `claimed`、没有 Post receipt/target/observation source。严格记为 **Post/canonical identity 未闭环**，不推断平台未投递、ID/tool drift 或 handler/storage 原因。
- current runtime 已无 probe module 或 probe runtime references，diagnose 无 `spawn_post_probes` 投影；历史 probe 目录只做前后元数据摘要，未读取或改写。P12-B 继续冻结，V3–V7 仍未执行。详见 `docs/validation/current-only-real-platform-validation.md`。

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

- P12-B 的 activation evidence 仍未取得，保持冻结；尽管 cleanup 后安装、重启、新任务 V1–V2 基线复验已完成，V2 的 Post/canonical identity 未闭环仍须在开发仓库以有界事实另行处理。
- V3 normal message/terminal/close，随后 V5 interrupt/controlled reconciliation、V6 Stop/SessionStart/SessionEnd 及 V7 restart/compact 后的 mailbox/retained-target 恢复。
- Hook trust、Codex registration 与桌面 UI 的独立实际状态。

真实 correctness failure 后必须在开发仓库新任务复现和修复，重新完成相应本地门禁、重新获得安装授权并创建另一个全新 P10-B 任务；不得在当前验证环境热修后继续验收。

真实测试必须遵循项目 `AGENTS.md`：先完成开发仓库验收，取得安装授权并更新用于测试的本地插件，然后新建独立任务。未完成上述步骤时只能报告本地可验证边界。
