# P10-B current-only 真实平台验证

日期：2026-08-24  
结论：`partial_validation_failed_at_v2`（真实 PreToolUse 可用，但 native Agent 工具的 PostToolUse/list observation 未写入 canonical state；没有热修、重装或绕过 Hook）

## 对象、授权边界与开始复核

- 这是安装后新建的独立 Codex 任务，执行配置为 `gpt-5.6-terra` / `high`。会话和本机路径按证据最小化原则省略。
- 开发 worktree 开始时干净，分支为 `codex/current-only-improvements`，HEAD 为 `68981ce218e832e45f0352fe7cda0f983deb18dd`（`chore: create clean redeploy cachebuster`）。
- 只读安装检查确认目标完整版本 `0.4.0-rc.13+codex.20260824090918`；stable/cache digest 均为 `89b025c1b5ea93a0ed17ff79d81be3a0bbdb95d1730e1e1d1f719255513fbd16`，`runtime_healthy`、`deployment_in_sync`、`development_rules_in_sync`、`single_current_cache`、`installation_paths_separated` 均为 true。
- `codex plugin list` 实际显示该目标版本为 `installed, enabled`。安装检查仍将 Codex registration 与 Hook trust 保持为 `not_checked`；没有从文件状态推断通过。
- 本任务没有修改 stable source、runtime cache、Hook trust、Marketplace、Registry、全局/项目 AGENTS、运行代码、测试、Schema、Skill 或 Manifest；没有重装、发布、push 或 tag。

## 真实平台证据与停止事实

- V1 的 unmanaged 原生 `spawn_agent` 使用隔离上下文、`gpt-5.6-terra` / `high`，精确 native target 为 `/root/p10_v1_unmanaged_probe`。Hook 在实际工具界面输出“无治理前缀，按 unmanaged 放行；不创建治理状态”，子 Agent 的原生终态回复为 `P10_V1_UNMANAGED_OK`。
- V2 由安装版 Skill 生成有效 TaskContract/PreparedContract：task `sg-a767f8c2d778137adcd1fca1ed8b6db0`、attempt `1`、ref `b0a436e25776`、contract digest `d310c1b0268f6c370e1b44505257e3ccb2152724a836a564275c11edc77d8991`。真实受治理 spawn 的 PreToolUse 输出确认已消费凭证并完成双门禁，native target 是 `/root/sg_light_p10_v2_managed_probe_t_b0a436e25776`，`list_agents` 返回 completed，且子 Agent 的原生终态回复为 `P10_V2_MANAGED_OK`。
- 但是，随后对 canonical state 的只读诊断仍将该 attempt 标为 `execution=not_started`、`identity=unconfirmed`、`platform=not_checked`。这表示真实 native tool 的 PostToolUse observation 没有被记录；终态通知可独立把它转为 confirmed，但不能代替 V2 所要求的 PostToolUse 观察。
- V5 的独立复现实例再次显示同一边界：受治理 long-running target 在 `list_agents` 中先为 running；`interrupt_agent` 实际返回 `{ "previous_status": "running" }`，一次真实 `wait_agent` 超时后，同一 exact target 在 `list_agents` 中为 interrupted。canonical state 仍为 `not_started/unconfirmed/not_checked`；`--reconcile-interrupted-attempt` 因 `attempt 身份尚未确认` 拒绝，没有伪造 inactive 或手工收口。
- 这是运行时/平台事件投递或 adapter 的正确性失败。按 P10 停止条件，未继续执行依赖该观察链的 V6/V7，也未修改安装环境。

## V1–V7 结果

| 场景 | 状态 | 实际证据、边界与未验证项 |
| --- | --- | --- |
| V1 插件/Hook 基线、unmanaged 放行 | `passed` | 实际 installed/enabled target、实际 PreToolUse allow/no-state 输出、native target 和原生终态标记均已取得。开始 V2 前的非 Agent 工具调用未产生 work item；未把文件存在或 Skill 可见性当作 Hook trust/registration 通过。 |
| V2 governed spawn、wait、exact identity | `failed` | PreparedContract、PreToolUse claim、exact native target、真实 `list_agents` completed 和原生终态均存在，但 PostToolUse/list observation 未写入 canonical attempt；仅靠后续终态记录才可确认 identity，不满足本场景的 Post observation 验收。 |
| V3 normal message、terminal notification、parent close | `not_checked` | 在识别 V2 failure 前已取得最小探索性信号：normal-message PreToolUse claim、attempt 1/2 的 exact terminal notification（重放 `idempotent`、错误 sender 拒绝）和 parent close/tombstone。但该信号不能弥补 V2 的 observation 缺失，故不作为通过证据。 |
| V4 business resume | `not_checked` | 在识别 V2 failure 前，真实 `followup_task` PreToolUse claim 将 source attempt 关闭、创建 attempt 2（ref `2768eccb7d81`），target 保持精确一致，子 Agent 回复 `P10_V4_RESUMED_OK`。同样不作为通过证据，因为 V2 的 Post/list observation 先验失败。 |
| V5 interrupt 与受控对账 | `failed` | 真实 interrupt 及 exact `list_agents=interrupted` 已取得，但 canonical attempt 缺少身份/成功派发/list observation 先验；受控 reconciliation 正确拒绝，未把 not-found 或外部 status 单独当作 inactive。 |
| V6 Stop、SessionStart、SessionEnd | `not_checked` | V2/V5 failure 后依 P10 停止；没有将当前任务的文件状态、Skill 加载或诊断输出冒充 Session event/UI 证据。 |
| V7 restart/compact 恢复 | `not_checked` | V2/V5 failure 后依 P10 停止，未请求或假定 UI restart/compact 已完成，也没有 fixture 替代。 |

## 后续与重新验证条件

本次不是 P10 完成，也不是 release-ready 结论。需要在新的开发修复任务中先复现并修复“真实 native Agent operation 的 PostToolUse/list observation 未进入 canonical state，导致 exact identity 和 interrupt reconciliation 无法收口”，完成相关 P1–P9 门禁；随后重新取得安装授权，并新建另一个独立 P10-B 任务，从 V1 重新执行 V1–V7。若届时 V7 需要 UI restart/compact，应由用户实际执行相应 UI 操作后再继续验证。
