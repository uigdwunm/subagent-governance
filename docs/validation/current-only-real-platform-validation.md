# P10-B current-only 真实平台验证

日期：2026-08-24  
结论：`inconclusive_invalid_exact_list_procedure`（后续独立审计确认 spawn/interrupt PostToolUse 已写入；V2/V5 的 `list_agents` 实际未传 `path_prefix`，不能作为 exact observation；没有热修、重装或绕过 Hook）

## 后续独立审计勘误

原报告把 `execution=not_started`、`identity=unconfirmed`、`platform=not_checked` 直接解释为 PostToolUse 未写入，这是错误推断。对真实 session 的只读状态和 PreparedContract 复核确认：

- V2 spawn 已记录 `dispatch_state=acknowledged`、完整 `dispatch_target` 和 `post_observed_at`；真实返回 `{"task_name":"/root/..."}` 已被当前 adapter 接受。
- V5 spawn 同样为 `acknowledged`；interrupt 已记录 `call_observation=success`、`target_observation=previously_running`。
- V2/V5 的实际 `list_agents` tool input 均为 `{}`，返回的是多 Agent 列表；当前 adapter 按 exact-binding 契约拒绝落账是正确行为。
- 因此没有证据支持“native Agent PostToolUse 未投递”。能确认的是 P10 exact-list 操作步骤无效，导致 identity/list reconciliation 没有被真实验证。

以下保留原任务实际取得的证据，但 V2/V5 结论按勘误后的证据等级重新分类。

## 对象、授权边界与开始复核

- 这是安装后新建的独立 Codex 任务，执行配置为 `gpt-5.6-terra` / `high`。会话和本机路径按证据最小化原则省略。
- 开发 worktree 开始时干净，分支为 `codex/current-only-improvements`，HEAD 为 `68981ce218e832e45f0352fe7cda0f983deb18dd`（`chore: create clean redeploy cachebuster`）。
- 只读安装检查确认目标完整版本 `0.4.0-rc.13+codex.20260824090918`；stable/cache digest 均为 `89b025c1b5ea93a0ed17ff79d81be3a0bbdb95d1730e1e1d1f719255513fbd16`，`runtime_healthy`、`deployment_in_sync`、`development_rules_in_sync`、`single_current_cache`、`installation_paths_separated` 均为 true。
- `codex plugin list` 实际显示该目标版本为 `installed, enabled`。安装检查仍将 Codex registration 与 Hook trust 保持为 `not_checked`；没有从文件状态推断通过。
- 本任务没有修改 stable source、runtime cache、Hook trust、Marketplace、Registry、全局/项目 AGENTS、运行代码、测试、Schema、Skill 或 Manifest；没有重装、发布、push 或 tag。

## 真实平台证据与停止事实

- V1 的 unmanaged 原生 `spawn_agent` 使用隔离上下文、`gpt-5.6-terra` / `high`，精确 native target 为 `/root/p10_v1_unmanaged_probe`。Hook 在实际工具界面输出“无治理前缀，按 unmanaged 放行；不创建治理状态”，子 Agent 的原生终态回复为 `P10_V1_UNMANAGED_OK`。
- V2 由安装版 Skill 生成有效 TaskContract/PreparedContract：task `sg-a767f8c2d778137adcd1fca1ed8b6db0`、attempt `1`、ref `b0a436e25776`、contract digest `d310c1b0268f6c370e1b44505257e3ccb2152724a836a564275c11edc77d8991`。真实受治理 spawn 的 PreToolUse 输出确认已消费凭证并完成双门禁，native target 是 `/root/sg_light_p10_v2_managed_probe_t_b0a436e25776`，`list_agents` 返回 completed，且子 Agent 的原生终态回复为 `P10_V2_MANAGED_OK`。
- 随后的只读诊断将 attempt 标为 `execution=not_started`、`identity=unconfirmed`、`platform=not_checked`。独立审计确认这表示 spawn 已 acknowledged、但尚无精确 list/notification observation；它不表示 spawn PostToolUse 缺失。
- V5 中 `interrupt_agent` 实际返回 `{ "previous_status": "running" }`，canonical lifecycle 已记录 success/previously_running。之后的 `list_agents` 仍使用 `{}`，所以其 running/interrupted 全量列表结果没有 canonical 绑定；`--reconcile-interrupted-attempt` 因身份未确认而拒绝符合当前安全边界。
- 这是 P10 操作和诊断表达的验证缺口，不是已证实的平台事件投递故障。原任务停止后未继续 V6/V7，也未修改安装环境。

## V1–V7 结果

| 场景 | 状态 | 实际证据、边界与未验证项 |
| --- | --- | --- |
| V1 插件/Hook 基线、unmanaged 放行 | `passed` | 实际 installed/enabled target、实际 PreToolUse allow/no-state 输出、native target 和原生终态标记均已取得。开始 V2 前的非 Agent 工具调用未产生 work item；未把文件存在或 Skill 可见性当作 Hook trust/registration 通过。 |
| V2 governed spawn、wait、exact identity | `not_checked` | 操作步骤无效：PreparedContract、PreToolUse claim、spawn PostToolUse acknowledged、exact native target 和原生终态均存在；但 `list_agents` 实际输入为 `{}`，没有执行 exact list observation，不能据此判定 adapter 或平台失败。 |
| V3 normal message、terminal notification、parent close | `not_checked` | 在识别 V2 failure 前已取得最小探索性信号：normal-message PreToolUse claim、attempt 1/2 的 exact terminal notification（重放 `idempotent`、错误 sender 拒绝）和 parent close/tombstone。但该信号不能弥补 V2 的 observation 缺失，故不作为通过证据。 |
| V4 business resume | `not_checked` | 在识别 V2 failure 前，真实 `followup_task` PreToolUse claim 将 source attempt 关闭、创建 attempt 2（ref `2768eccb7d81`），target 保持精确一致，子 Agent 回复 `P10_V4_RESUMED_OK`。同样不作为通过证据，因为 V2 的 Post/list observation 先验失败。 |
| V5 interrupt 与受控对账 | `not_checked` | 操作步骤无效：spawn 和 interrupt PostToolUse 均已写入；interrupt response 为 previously-running。后续 list 输入仍为 `{}`，不是 exact observation，因此受控 reconciliation 缺少身份先验并正确拒绝。 |
| V6 Stop、SessionStart、SessionEnd | `not_checked` | V2/V5 failure 后依 P10 停止；没有将当前任务的文件状态、Skill 加载或诊断输出冒充 Session event/UI 证据。 |
| V7 restart/compact 恢复 | `not_checked` | V2/V5 failure 后依 P10 停止，未请求或假定 UI restart/compact 已完成，也没有 fixture 替代。 |

## 后续与重新验证条件

本次不是 P10 完成，也不是 release-ready 结论。应先增加 exact-list 操作护栏和诊断可见性，完成相关本地门禁；随后重新取得安装授权，并新建另一个独立 P10-B 任务，从 V1 重新执行 V1–V7。新的 V2/V5 必须显式调用 `list_agents({"path_prefix":"<完整 canonical target>"})` 并确认 `observation_record.source=list_agents`。若 V7 需要 UI restart/compact，应由用户实际执行相应 UI 操作后再继续验证。
