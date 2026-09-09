# state-v10 Hook 重新信任后的真实验收

日期：2026-09-09。运行版本：`0.4.0+codex.20260907104316`，对应提交 `15b9640`（claim 修复为 `2fb8291`）。本次只补真实验证与文档，不改运行时代码、不重新部署。

结论：`passed_with_platform_unknowns`。重新信任后的 claim/bind、普通消息、followup、等待终态及 parent close 均通过；中断调用回执的 unknown 边界按协议处理，后续列表独立显示 interrupted，但未收到该目标的终态通知。

## Hook 状态与失败解释

2026-09-07 的独立任务 `01a07a56-c576-73b2-95c5-27fecb041a8a` 在原生 spawn 成功后，confirm 返回 `reconcile`，原因为 `dispatch_claim_missing`。这条历史记录不改写或补绑。

2026-09-09 通过本机 Codex `0.153.4` app-server 的只读 `hooks/list` 检查，PreToolUse 为 enabled/modified，SessionStart 为 enabled/trusted。PreToolUse 当前定义哈希为 `sha256:e9ec71bb3c0ccb81dbb1d0ef0eb80bbf6f99ca1df880dc56909fa6b98bf14010`，信任记录仍对应旧哈希 `sha256:22ae579f77878dd9e405b95207177c5a9f0d74ed63d94f2549c0e025d96f1916`。

用户重新信任后，同一只读接口确认两个 Hook 均为 enabled/trusted，且无加载错误。SessionStart 正常不能替代 PreToolUse 的独立信任检查。当前状态与复验支持信任未更新是本次派发检查未生效的原因；未保存 9 月 7 日调用当时的 Hook 输入，不把当前查询冒充当时的直接运行日志。

## 独立验收配置与核心链路

验收任务：`01a085b7-968c-7583-bb3e-c49bef648427`。创建请求显式指定 `gpt-5.6-terra/high`，本地 rollout 的两轮 `turn_context` 均记录 `model=gpt-5.6-terra`、`effort=high`。这是 Codex 运行配置证据，不证明 provider 内部路由。治理 session/CLI 由验收任务自身的 SessionStart 提供。

| 项目 | 结果 | 证据与边界 |
| --- | --- | --- |
| 初始状态与 unmanaged spawn | passed | 初始账本为空；unmanaged 子 Agent 完成后账本仍为空。 |
| prepare、Pre claim、exact-target confirm | passed | task `sg-a3c4676002ecca051c97a9af93bc5aac`、ref `179fa6049810`；原生返回 target `/root/sg_standard_agent_agent_follow_up_t_179fa6049810`，立即 confirm 为 bound。 |
| 普通消息与一次 followup | passed | 普通消息获得继续等待确认；followup 在终态前发送，随后收到明确 completed 通知。 |
| 终态与 parent close | passed | 精确 sender 的终态已记录；最终 phase=closed、terminal_status=completed、next_action=none，diagnose issues=[]。 |
| 第一轮等待 | timeout 路径已验证 | 终态先于 wait 抵达，不能作为 wait 捕获终态的证据。 |

## 补充场景

原已关闭生命周期未恢复，也未重复 unmanaged 或普通消息测试。两个补充场景各使用一个新 governed 子 Agent，均立即以本次原生返回的 target confirm 为 bound。

| 场景 | task_id / task_ref | 原生返回 target | 结果 |
| --- | --- | --- | --- |
| 等待终态 | `sg-dc04177e57abdd5d1506cb412a543ae0` / `5484b823367c` | `/root/sg_standard_agent_25_completed_t_5484b823367c` | passed |
| 主动中断 | `sg-11d0d93a0b01b78ef6355be764315171` / `c6efb6783b04` | `/root/sg_standard_agent_45_agent_t_c6efb6783b04` | passed_unknown_boundary |

等待调用返回 `{"message":"Wait completed.","timed_out":false}`，并收到 exact sender 的明确 completed 终态。等待返回本身不作为 terminal fact；结合明确终态证据记录平台观察后，终态通知写入幂等返回 already_terminal。最终 closed，platform_status 与 terminal_status 均为 completed。

中断调用返回 `{"previous_status":"running"}`，只证明操作前状态。`record-interrupt-result unknown` 返回 `reconcile / interrupt_unknown`。随后仅对已 bound target 做一次列表观察，平台显示 interrupted；提交该观察仍返回 reconcile，没有将原中断调用倒改成成功。未收到独立终态通知，未伪造 terminal；父任务明确停止跟踪并 close。

最终三个治理任务均为 closed、next_action=none，diagnose issues=[]。中断任务关闭后的摘要中 interrupt_result、platform_status、terminal_status、reconcile_reason 均为 null；因此不能单凭最终无问题摘要宣称中断回执已确定，中间 unknown 与列表观察证据以上述记录为准。

## 验证范围

本次不覆盖真实 compact/restart 恢复、strict 材料校验或另一套原生参数接口；不以历史 state-v9 报告替代 state-v10 的新证据。

收尾时只读核对安装状态：原生 `codex plugin list` 显示 `subagent-governance@personal` 为 installed/enabled，版本仍为 `0.4.0+codex.20260907104316`。开发源的 `bundle_digest` 与稳定源、当前运行缓存的 `verify_runtime_bundle` 均为 `ece85e6a157b9290957e63a8c94956ddd165711202cebcbfd9c1d0f593652111`，三个根目录彼此独立。当前运行内容与开发仓库一致，验收文档不进入 runtime allowlist，因此本轮文档收尾不需要再次部署。
