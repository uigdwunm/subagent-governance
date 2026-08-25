# 平台验证摘要（state-v9 真实验证；历史 v8 证据）

> 本文保留导致减法收口决策的历史 v8 证据，并记录当前 state-v9 的独立重启后真实验证。历史结果不描述或替代 state-v9 runtime 能力。

## 当前结论

state-v9 当前实现、精确 Hook allowlist、runtime 禁写 bytecode 与 retained-previous 精确校验已提交为 `a6da1d2278d11b5a83ebf5a6d66b332052d60571`，并部署为 `0.4.0-rc.13+codex.20260825073554`。source、stable、current runtime projection digest 均为 `50e1e2b3b26fd8eec37c4cbe0227a6f796b24028dd328b90a5f0685f590d8fc4`；本地门禁见 [本地验收](validation/current-only-local-acceptance.md)，完整真实矩阵见 [当前真实验收](validation/current-only-real-platform-validation.md)。

独立 exact session `01a03800-6f1b-7ae0-b4aa-d2afe0423cf3` 以显式 `gpt-5.6-terra` / `high` 配置完成 V1–V7；rollout model provenance 为 `gpt-5.6-terra`。未发现 runtime correctness failure，最终所有 governed lifecycle closed、diagnose `issues=[]`。V4 消息与 V5 interrupt 缺少可判定平台回执，分别保守记录为 `delivery_unknown` 与 `interrupt_unknown`，不宣称平台动作成功。P12-B 已由 reduction ADR 正式 rejected/archived，不是后续待办；以下旧失败只保留为历史证据。

### 最新 state-v9 V1–V7 真实验证（2026-08-25）

- V1 unmanaged 证明 fail-open 与零治理状态；V2 仅以 native spawn 机械返回的 exact target `/root/sg_strict_exact_target_t_020c311e2725` 完成 `prepared → claimed → bound`；V3 对该 bound target 完成 bounded wait 与 completed observation。
- V4 对独立 bound target 实际调用 normal message；机械结果不可判定时准确进入 `delivery_unknown → reconcile`，exact sender terminal 不覆盖 unknown。V5 对独立 bound target 实际调用 interrupt；仅有 `previous_status=running` 时准确进入 `interrupt_unknown → reconcile`。二者均显式 close 并验证幂等 replay。
- V6 证明 exact-session status/diagnose 前后 ledger hash、mtime、size 不变。V7 由用户在同一任务 UI 触发真实 Compact，SessionStart 准确恢复 prepared anchor `85141d355bc8`；anchor 随后显式 close。
- app-server `hooks/list` 只加载当前插件的 PreToolUse 与 SessionStart，二者均 `enabled=true`、`trustStatus=trusted`。app-server `plugin/list` 报告 `subagent-governance@personal` 为 installed、enabled、available，local version 与运行 cache 一致；桌面插件页的视觉渲染未另行截图。
- 验收后已删除 5 个退役插件 Hook 的 trust sections，并将三个历史 reconcile ledger 以可恢复方式移出 state-v9 运行目录。当前成功验收 ledger 与 runtime/cache 未被清理。

### 历史：较早的 state-v9 独立重启后真实验证（2026-08-25）

- 最新安装版 `0.4.0-rc.13+codex.20260825062527` 的 exact session `01a037ae-a8ac-7ff3-a80b-85c2c0764973` 已完成 governed prepare/claim、exact target bind、一次 wait、exact completed observation、terminal notification 与 parent close；最终 ledger closed、diagnose `issues=[]`，只读检查零写入。父任务实际为 `gpt-5.6-sol` / `high`，不符合项目规定的真实测试任务 `gpt-5.6-terra` / `high`；详见当前真实验证记录。
- 该轮未执行 V1 unmanaged、V4 normal message、V5 interrupt、V6 SessionStart/status 事件恢复或 V7 restart/compact。不得把已通过的主链外推为这些场景已通过。
- 验证任务的开发 checkout 为 `87f03570eafd6a1cd435f2bb92dfeb560e2a94e2`，实际加载版本为 `0.4.0-rc.13+codex.20260825035757`；当前加载的 Skill 路径与该版本 runtime cache 一致。`codex plugin list` 仅显示 installed/enabled，不能替代 Hook trust 或 Codex registration 的独立结论。
- exact session identity 为 `01a03722-0244-7c32-82e7-0a2f52b52d3b`。V1 原生 unmanaged spawn 返回 exact target 且收到独立终态；前后只读 status/diagnose 都显示当前 v9 ledger 零 task，故 V1 为 `passed`。child final 不作为治理 identity authority。
- V2 先由当前 runtime prepare，再把本次 native `spawn_agent` 返回的 exact target 原样立即提交 `confirm-dispatch`。该命令返回 `reconcile`；只读 diagnose 显示 `phase=reconcile`、`reconcile_reason=dispatch_identity_mismatch`、`target=null`。后续开发仓库诊断确认 task id/ref 与 exact target 形状均正确；该旧 reason 实际来自 confirm 时 task 不在 `claimed` 的共用分支，而不是 target identity 不匹配。
- 同一诊断中的只读 `hooks/list` 显示当前 PreToolUse handler 的 `currentHash=sha256:307fb66cae3e00fbcec4eb69f5227cb5f993a8583698df6bc6829330f9465081`，配置保留的 `trusted_hash=sha256:d2eedfe914bd63b8e1ebc1c872ee51f1a6ee221b4fa62a062dec61e602c95aff`，平台 trust status 为 `modified`。因此原报告中的“governed Pre claim”不能作为 exact ledger durable claim 已成立的证据；当前证据只支持 native spawn 已执行、confirm 前 exact task 仍未形成 durable claim。
- 开发仓库已将 `prepared` 上的 exact confirm 单独分类为 `dispatch_claim_missing` 并保持 reconcile/no-bind；真实 task/ref 不匹配仍为 `dispatch_identity_mismatch`，claimed 上的 exact target 仍遵守 first-bind-wins。这是本地修复，尚未部署或真实复验。
- 随后的已授权部署准备中，当前 PreToolUse 与只读 SessionStart 的 exact current hash 已通过 Codex app-server 写入并回读为 `trusted`；该证据不替代修复部署后的 V1–V7 重新验证，也不证明 Codex registration 或桌面 UI 状态。
- 修复部署并重启后的第二次独立验证中，V1 通过，V2 以新 reason `dispatch_claim_missing` 严格失败。后续开发诊断只读确认 Hook trust 仍为 `trusted`，并定位到 router 未识别 MultiAgent V2 flattened `collaborationspawn_agent`；本地兼容修复同时保留 V2 opaque-message 边界和 V1 完整明文比较，尚未部署或真实复验。详见当前真实验证记录。
- 依停止策略，按当前最终矩阵，V3（wait/已 bound exact-target observation）、V4（normal message/terminal）、V5（interrupt/close）、V6（exact-session SessionStart/status）和 V7（restart/compact）均为 `not_checked`。当时 Hook trust 确认为 `modified`，Codex registration 和桌面 UI 仍为 `not_checked`；这些外部状态与 exact session identity 分别记录，不纳入 V1–V7 编号，也不由 installed/enabled 或文件存在替代。

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

## 历史 v8 当时由本地测试覆盖

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

## 历史 v8 当时的平台能力边界

- 插件不注册官方 `SubagentStart`、`SubagentStop`；它们保留在能力契约 fixture 中，但不参与运行时状态维护或终态通知处理。
- transcript、summary、final history 和未知 Hook 扩展不作为 correctness authority。
- list terminal observation 不替代原生 child notification。
- 插件不保存通知正文，不判断业务质量，不提供 accept/reject 状态。
- Stop 当时只给 advisory 并固定 fail-open；state-v9 已删除 Stop Hook。

## 当前真实验证边界

- V1–V7 已在显式 `gpt-5.6-terra` / `high` 独立任务完成；stable/current digest、Hook trust 与 app-server 注册后端均有机械证据。
- V4 message 的实际投递/回执和 V5 interrupt 的实际 inactive 结果仍为平台 `unknown`。当前产品 invariant 是保守保存 unknown 且不自动重发、不猜终态；本轮已验证该 invariant，不把它们升级为平台成功证据。
- 桌面插件页没有单独截图；`plugin/list` 已证明当前 UI 后端返回 installed/enabled/available。需要视觉回归时应另作 UI 验证，不把视觉截图作为 runtime correctness 前置。

P12-B 已 rejected/archived，不恢复 PostToolUse authority、receipt/index 或 matcher-only 实验。

真实 correctness failure 后必须在开发仓库新任务复现和修复，重新完成相应本地门禁、重新获得安装授权并创建另一个全新 P10-B 任务；不得在当前验证环境热修后继续验收。

真实测试必须遵循项目 `AGENTS.md`：先完成开发仓库验收，取得安装授权并更新用于测试的本地插件，然后新建独立任务。未完成上述步骤时只能报告本地可验证边界。
