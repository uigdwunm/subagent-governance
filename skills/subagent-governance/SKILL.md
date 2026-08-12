---
name: subagent-governance
description: 为 Codex 原生子 Agent 选择 light、standard、strict 或 auto 治理方式，并规范结构化任务契约、通信、等待、恢复、中断和正式结果验收。用于用户要求规划、派发、加强、诊断或治理子 Agent，准备调用 spawn_agent、send_message、followup_task 或 interrupt_agent，任务需要上下文隔离、完成验收、失败恢复或并发协调时。不要因为普通任务碰巧包含子 Agent 字样就主动引入重型流程。
---

# 子 Agent 治理

保持 Codex 原生 `spawn_agent`、`send_message`、`followup_task` 和 `interrupt_agent` 为执行通道。本 Skill 负责帮助 AI 生成业务内容和选择治理参数；插件只做字段存在、类型、长度、枚举、引用和基本组合校验，不替父 Agent判断业务风险、结果真实性或证据充分性。

## 使用范围与全局入口

- 普通任务不需要加载本 Skill，也不要仅因任务可以拆分就主动创建子 Agent。
- 准备规划、派发、通信、等待、恢复、中断或验收原生子 Agent 时，先完整读取本 Skill。
- 全局 `AGENTS.md` 只保留指向 `$subagent-governance` 的短入口；完整协作规则在本 Skill 中维护。
- 子 Agent 相关自然语言说明使用中文；模型名、强度值、命令、代码、路径、Agent ID、canonical task path 和状态枚举等技术标识可以保留原文。

## 统一任务契约

所有实际治理等级共用一套任务契约。AI 提供或确认以下字段：

- `semantic_name`
- `requested_mode`
- `task_features`
- `objective`
- `background`
- `work_scope[]`
- `forbidden_scope[]`
- `completion_conditions[]`
- `evidence_requirements[]`
- `relevant_files[]`
- `current_state`
- `model`
- `reasoning_effort`
- `context_strategy`
- `context_turns`
- `context_reason`

生成器补充 `resolved_mode` 和 `resolution_reason`。业务上的下级 Agent 允许或禁止写入 `work_scope[]` 或 `forbidden_scope[]`；不设置独立 `child_agents` 权限字段。`task_features.allows_child_agents` 只是 auto 解析的可选复杂度信号，不代表插件授予权限。

`objective`、`background`、`work_scope[]`、`forbidden_scope[]`、`completion_conditions[]`、`evidence_requirements[]`、`relevant_files[]`、`current_state` 和三个上下文字段对所有等级固定存在，其中允许为空的数组仍使用空数组、可空文本使用 JSON `null`。`task_features` 仅在 auto 时必填；`model` 和 `reasoning_effort` 可以为 JSON `null` 或省略。空模型或强度不伪造继承值，原生调用省略相应参数。

## 选择治理等级

- `requested_mode=light`：适合边界清楚、只读、短时、失败影响低的任务。
- `requested_mode=standard`：适合普通编码、诊断、研究和 Review。
- `requested_mode=strict`：适合安全、迁移、生产、破坏性操作、并发写入、多阶段验收或复杂协作。
- 显式 `light|standard|strict` 不由生成器二次提升、降低或拒绝；`resolved_mode` 与请求值相同，`resolution_reason=explicit_request`。
- `requested_mode=auto` 时必须提供结构化 `task_features`：`risk`、`read_only`、`writes_files`、`destructive`、`production`、`concurrent_write`、`multi_stage_acceptance`，以及可选的 `allows_child_agents`。
- auto 只按固定结构化规则解析：任一 strict 信号成立则 `resolved_mode=strict`；`risk=low + read_only=true + writes_files=false` 且没有 strict 信号时为 `light`；其余合法组合为 `standard`。
- `read_only=true` 与 `writes_files=true` 是机械矛盾。插件不读取任务正文中的风险词，也不建立风险评分。
- standard 至少提供一项 `evidence_requirements[]`；strict 至少提供一项 `forbidden_scope[]` 和一项 `evidence_requirements[]`；light 可以为空。

完整等级边界见 [references/governance-levels.md](references/governance-levels.md)。

## 上下文策略

- `context_strategy=isolated`：默认选择；`context_turns=null`，`context_reason` 可空。映射为原生不继承上下文，用户说明显示“否”。
- `context_strategy=limited`：`context_turns` 必须是 1 至 100 的整数，`context_reason` 必填。映射为继承最近 N 轮，用户说明显示“否（仅继承最近 N 轮）”。
- `context_strategy=full`：`context_turns=null`，`context_reason` 必填。映射为完整继承，用户说明显示“是”。
- 上下文理由由 AI 根据真实任务生成；脚本只检查字段和数值边界，不评价理由是否充分。

## 生成派发

1. 先填写统一任务契约并完成机械校验；不要用自由文本代替结构化字段。
2. 生成器根据 `requested_mode` 和 `task_features` 产生 `resolved_mode`、稳定的 `resolution_reason`、完整 dispatch prompt 和用户说明。
3. 目标 `task_name` 使用 `sg_<resolved_mode>_<semantic_name>_t_<task_ref>`。`semantic_name` 只使用小写字母、数字和下划线；task ref 由 `task_id + attempt` 确定性派生。主对话不展示 task ref。
4. 用户可见说明只展示目标、请求/实际治理等级、解析原因（auto 时）、模型、强度、上下文、范围和完成条件，不倾倒内部状态。
5. dispatch prompt 包含唯一当前目标、相关背景和裁决、工作与禁止范围、相关文件和当前状态、完成条件、证据要求、恢复和正式结果义务。AI 负责内容完整性，脚本不通过关键词或评分判断正文质量。
6. 调用 `scripts/subagent_governance.py --prepare-dispatch --session <session_id>`，通过标准输入提交 TaskContract JSON。生成器先原子写入并回读 `prepared/` 中的 PreparedContract，再以 `admission="new_task"` 创建并回读初始 StateStore；任一门禁失败都不得调用原生 `spawn_agent`。
7. 生成器输出 `user_message`、`dispatch_prompt` 和 `spawn_args`。先向用户展示 `user_message`，再把 `spawn_args` 原样用于原生 `spawn_agent`；不要自行重写 task name、上下文、model 或 reasoning effort。
8. PreToolUse 只从未加密 task name 解析 task ref，核对 PreparedContract、StateStore、resolved mode 和可观察原生参数并单次认领。它不读取、分类或改写业务正文；正文即使在 Hook 层呈 opaque 形态也不能触发等级或身份猜测。

明确 failed 后的同 attempt spawn retry 使用 `--prepare-spawn-retry <task_id>`；第一次 retry 可直接准备，第二次也是最后一次 retry 还必须提供 `--authorize-final-retry`。任何一次结果为 `unknown` 时禁止继续复用该 attempt 重派。

用户说明中的模型和强度：

- `model=null` 或省略：显示“继承主 Agent（未显式覆盖）”。
- `reasoning_effort=null` 或省略：显示“继承主 Agent 当前强度（未显式覆盖）”。
- 显式 `reasoning_effort` 只使用 `low|medium|high|xhigh|max|ultra`。

## 批量派发透明度与轻量 group

批量并行派发时，先在主对话使用一张用户可见表格逐项说明；表格只是透明度载体，不是调度计划，每个 Agent 仍使用一次独立原生 `spawn_agent`：

| Agent | 目标 | 治理等级 | 模型 | 强度 | 上下文 | 范围 | 完成条件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `<标识>` | `<唯一目标>` | `<light|standard|strict>` | `<显式值或继承说明>` | `<显式值或继承说明>` | `<否/最近 N 轮/是>` | `<工作范围>` | `<可验证条件>` |

只有父 Agent 明确需要把多个 individual task 关联到同一目标时，才通过 `--upsert-group --session <session_id>` 创建或更新 group。stdin 只提供 `group_id`、`objective_summary` 和 `members=[{task_id, required}]`；插件保存 created/updated 时间，不复制成员目标、Agent target、结果、失败原因、恢复状态或父动作，也不根据同一 Session、同一轮或并行派发自动成组。

- `--read-group --session <session_id> --group-id <group_id>` 实时读取 individual task，派生 `summary_ready` 与 `group_action_required`。
- `summary_ready` 只看 required 成员：required 非空且每项已有可读取正式结果，或已经形成带原因的明确最终处置时为 true。它不表示全部成功或组已闭环。
- `group_action_required` 只看 required 成员是否全部完成 individual 明确处置；待验收、blocked、failed、needs_decision、平台/协议/存储问题、结果冲突、重复执行和其他未关闭状态都会保持 true。
- required 为空时 `summary_ready=false`、`group_action_required=false`；optional 成员可展示 individual 摘要，但不影响两个 required 聚合信号。
- 一个成员失败只处理该 individual task，不暂停、取消或中断其他成员。每个成员继续使用自己的等待、恢复、正式结果和父处置链。
- 父 Agent在材料齐备后自行读取 individual 正式结果并生成用户摘要；插件不生成 AggregateResult、不自动裁决冲突、不建立组级状态机、DAG、batch、wave 或调度器。

## 子 Agent 通信

通信必须显式提供 `operation_type`，不能根据工具名、当前状态或正文猜测用途：

- `normal_message`
- `platform_recovery`
- `result_correction`
- `business_resume`

四类操作共享 AI 生成的对象、目的、原因、具体内容和期望结果。用户说明保持简洁；给子 Agent 的实际消息只包含其需要理解的业务指令，不注入内部协议版本或机械 ID。

调用 `scripts/subagent_governance.py --prepare-communication --session <session_id>` 生成通信；主动中断使用 `--prepare-interrupt`。生成器输出固定用户说明、原生工具名和原生参数，并在精确 managed target 上创建单目标唯一的 `pending_action`。先展示用户说明，再原样调用输出指定的原生工具；不要绕过生成器直接向 managed target 发送消息或 follow-up。

- `pending_action` 初始为 `prepared`，5分钟内必须由匹配 target 的 PreToolUse 原子认领为 `claimed` 并绑定 `tool_use_id`。平台恢复和结果补交次数、business resume 新 attempt 都在原生调用前的同一认领边界消耗或创建。
- PostToolUse 只通过 `tool_use_id` 对账 `success|failed|unknown`。claimed 后20分钟仍缺少 PostToolUse 才在后续显式读取/恢复时记为 unknown；不建设后台 scheduler，不自动重发。
- `normal_message` 在 StateStore 暂不可用时可以明确告警后 fail-open；受治理的 `platform_recovery`、`result_correction` 和 `business_resume` 在前置状态无法可靠写入时必须拒绝。明确 target 的主动中断是安全例外，可以告警后 fail-open，但不得声称治理状态已记录。
- success/unknown lifecycle 操作的最小 `last_lifecycle_operation` 不使用时间 TTL；精确 `SubagentStart` 可以消费匹配的恢复、纠正或 business resume 授权。failed 操作和 interrupt 永不授权 stopped/not_started attempt 重新 running。

- `normal_message` 只补充上下文、修正方向或请求信息，不改变生命周期状态或恢复次数。
- `platform_recovery` 只在目标范围 `list_agents` 明确报告 Agent errored 后使用，保持原 attempt。
- `result_correction` 只补交结构化结果，不重新执行业务任务。
- `business_resume` 在已有 blocked、failed、业务 needs_decision 或 complete 被拒绝后创建新 attempt，再继续原目标。
- `business_resume` 的原生调用 success/unknown 都保持新 attempt 为 `not_started`，必须等精确 `SubagentStart` 才进入 running；unknown 后不得对同一 Agent重发，替代执行必须走新的 spawn/new Agent。
- 普通主动中断 success 写 `interrupted + decide_disposition`；若目标是 `select_attempt` 已标记的运行中未选 attempt，则在同一锁内关闭该精确 attempt、生成 tombstone、清 Agent映射，并仅在全部未选 attempt 都可靠关闭后解除 duplicate。failed 保持未关闭并要求父 Agent或用户决定，unknown 保持原执行状态并进入 `reconcile`。后续只按显式 `list_agents` running/error/stopped 事实继续处置。

## 等待、状态对账与恢复

- 派发后保存 Agent ID 和 canonical task path，以 `timeout_ms: 1200000` 调用 `wait_agent`。
- mailbox 正常更新、完成通知或用户输入会提前结束等待；立即按新证据继续。
- mailbox 明确报告 `stream disconnected`、`errored` 或其他平台执行失败时，立即对该目标范围调用 `list_agents`，不等待20分钟；只有 20 分钟正常等待超时才做一次目标巡检。
- 目标巡检优先使用已保存的 canonical task path 作为 `path_prefix`（平台支持时），不得扫描或分析无关 Agent。
- 目标仍明确正常 running 时不输出进度说明，立即再次 `wait_agent(timeout_ms=1200000)`；不读取代码、Git、日志或测试猜测进度，不发送心跳或追问。
- 超时、沉默、测试耗时或上下文压缩不是失败证据。
- `list_agents` 失败或状态含糊时不得中断、重建或猜测终态；继续等待，并在下一轮20分钟超时后重新检查。
- `list_agents` 明确 errored 才记录 `platform_observation=error`。所有错误文本使用同一有界恢复规则，不解析 Provider、加密或解码关键词改变语义。
- 同一 Agent、同一 attempt 允许一次自动平台恢复；再次需要恢复时进入 `recovery_status=awaiting_authorization + parent_action=ask_user`。用户明确授权后只允许第二次也是最后一次恢复。
- 调用结果 unknown 时进入 `parent_action=reconcile`，不自动重发，不伪造 failed、running、interrupted 或 closed。
- Hook 没有后台定时器，不会自动调用 `wait_agent`、`list_agents`、`followup_task` 或 `interrupt_agent`。

## 派生视图与会话闭环

- `action_required` 与 `recent_activity` 是独立派生视图。二者都遍历 current 与 prior attempts；`action_required` 无12小时过滤，主规则是“attempt 未关闭且 `parent_action != null`，或仍有权威运行/调用事实”，`recent_activity` 只用于最近12小时展示，不能关闭、删除或隐藏未解决任务。
- `action_required` 还必须覆盖 running、spawn/claimed 调用对账、身份未确认 success/unknown、platform error、恢复/纠正耗尽、result unavailable/conflict、complete pending、blocked/failed/needs-decision、未关闭 interrupted 和 duplicate/select 未闭环。
- SessionStart 的 startup/resume/clear/compact 先复用既有5分钟 prepared 与20分钟 claimed reconcile，再精确清理到期 tombstone/result；摘要先显示 action-required，再显示未重复的 recent-activity，并提醒不要因 compact/resume 重复创建已有 Agent。读取失败必须明确 degraded，不能写成没有任务。
- Stop 同一次处理最多读取 StateStore 三次（首次加两次短重试）。三次都失败时机械阻止本次 Stop并即时要求用户选择强制结束或先诊断/恢复状态；Stop 不替父 Agent验收业务结果。running、调用对账、身份未确认和可恢复平台错误阻止结束；complete pending、blocked、failed、needs-decision、恢复/结果耗尽等允许当前回复结束，但继续留在 action-required。
- SessionEnd 只有在 action-required 为空且没有仍在7天保留期的 tombstone 时才在稳定锁内删除 Session JSON；稳定 `.lock` 永不删除。主会话结束不自动关闭 task，不创建 archive，也不按12小时窗口删除 unresolved 状态。
- tombstone 固定保留7天，只在显式 StateStore/Session 锁内路径顺带清理。正式结果必须用确定性地址和文件内 `task_id + attempt` 精确核对后删除；result 删除失败时 tombstone 保留，不使用 glob、目录年龄或数量批量清理。

## 正式结果与父任务验收

结构化结果是唯一正式业务结果。所有等级共用以下基础字段：

- `task_id`
- `attempt`
- `business_result=complete|blocked|failed|needs_decision`
- `result`
- `evidence[]`
- `remaining[]`
- `suggested_parent_next_step`

分场景字段：

- blocked：`blocker`、`attempted[]`、`required_to_resume`。
- failed：`failure_reason`、`attempted[]`、`retry_conditions`。
- needs_decision：`decision_question`、`options[]`、`recommendation`。

`evidence[]` 必须存在但允许为空；是否满足契约证据要求由父 Agent验收。`suggested_parent_next_step` 只是子 Agent建议，不能覆盖 StateStore 的权威 `parent_action`。

- `complete` 只表示子 Agent声明完成；父 Agent验收前仍是 `acceptance_status=pending + parent_action=accept_result`。
- blocked 和 failed 结束当前 attempt，但任务仍需显式处置。
- 只有子 Agent提交合法业务问题时才写 `business_result=needs_decision`；平台、协议或存储故障不能伪造业务结果。
- strict 可以从同一结构化结果渲染固定中文终态卡，但 Hook 不解析卡片措辞，也不因缺少标题或关键词阻断合法结构化结果。
- 所有等级最多进行两次 `result_correction`；该次数与 spawn retry、platform recovery 分开。

正式结果按 `task_id + attempt` 唯一保存到 governance data 根的 `results/result-<sha256(task_id)>-attempt-<attempt>.json`。文件先原子写入并回读验证，再关联 StateStore；StateStore 只保存引用、摘要和状态，不复制完整结果正文。提交与读取入口：

- `scripts/subagent_governance.py --submit-result --session <session_id> --agent-target <agent_id|canonical_path>`：stdin 接收 TaskResult JSON。
- `scripts/subagent_governance.py --read-result --session <session_id> --task-id <task_id> --attempt <n>`：按精确 attempt 重新校验并读取权威结果。
- `scripts/subagent_governance.py --reassociate-result --session <session_id> --task-id <task_id> --attempt <n>`：只重关联已存在且通过机械校验的孤立文件。

managed `SubagentStop` 只在 payload 显式包含对象字段 `task_result` 时调用同一提交路径；不从原生自由文本推断或生成正式结果，`last_assistant_message`、summary、终态卡和 lifecycle response 都不是正式结果来源。没有合法结果时按 `correction_count` 写 `needs_correction + correct_result` 或 `exhausted + manual_review`，不编造业务结果。

同内容重放幂等；不同合法内容不覆盖已有文件，只记录冲突摘要和首次发现时间并进入 `manual_review`。合法旧 attempt 结果仍写回原 attempt；若形成重复执行，只记录 `duplicate_execution + resolve_duplicate`，不自动选择或中断。

父 Agent验收或处置必须把 `{task_id, attempt, action, reason}` 通过 stdin 交给 `--parent-disposition --session <session_id>`。固定 action 为 `accept_result|reject_result|close_task|select_attempt`：

- accept 只允许 current complete/valid/available/pending，且没有未解决重复执行或仍运行 attempt；成功后写 accepted，并与整 task 的非运行 attempt 一起原子关闭和 tombstone。
- reject 只允许同一待验收 complete，保留权威结果并写 rejected + decide_disposition。
- close 按 expected current attempt 关闭整 task；存在 confirmed running attempt 时只返回精确中断 targets，不自动中断。
- select 只处理显式重复执行选择；立即关闭非运行的未选 attempt，运行中的未选 attempt 只标记并返回精确中断 targets。父 Agent对每个 target 显式执行 `--prepare-interrupt` 与原生 `interrupt_agent`；success 或后续明确 stopped 才关闭该未选 attempt，failed/unknown 不清 duplicate。全部未选 attempt 可靠关闭后，所选 attempt 才按自身结果/执行状态恢复正确 `parent_action`。

真实 Codex 是否会向 `SubagentStop` 提供自定义 `task_result`、子 Agent是否能直接调用提交 CLI，以及 Hook trust/展示行为仍必须通过真实平台验证。

## 状态与父动作边界

- 观察尚未发生时使用 JSON `null`；只有实际观察发生但结果无法确认时使用 `unknown`。
- 业务结果只来自合法结构化结果，不由派发、平台错误、中断、协议耗尽或存储故障生成。
- `parent_action` 是状态机给父 Agent的权威下一步：`wait|reconcile|retry_spawn|recover|correct_result|decide_disposition|business_resume|accept_result|ask_user|manual_review|resolve_duplicate`，或 JSON `null`。
- 明确关闭通过父处置和 tombstone 表达，不增加 `end`、`closed` 或 `archive` 动作。
- 未知额外字段兼容忽略；缺少当前操作所需字段时明确列出，不读取协议版本，不静默迁移或补造业务事实。

## 运行与诊断边界

- `scripts/subagent_governance.py --diagnose [--session <session_id>] [--data-root <root>]` 使用专用无锁只读路径：不创建数据根、sessions/results/prepared、锁、临时或隔离文件，不 chmod/chown，不 reconcile、清理、修复或回写 StateStore。
- 全局与单 Session 输出相同的稳定 JSON snapshot，直接消费 `_action_required_records()` 与 `_recent_activity_records()`；不转储完整 StateStore、dispatch prompt、通信正文、平台响应或完整 result/evidence/remaining。
- 诊断只按精确 `task_id + attempt` 只读复验已有正式结果引用，展示可读性、引用、SHA-256 匹配和有界元数据；失败不重关联、不修改 `result_storage_status`。
- 诊断 exit 0 只表示请求扫描完整，exit 1 表示不存在、损坏、不可读或容量遗漏，exit 2 表示 CLI 参数错误；任务异常、action-required 或 result conflict 本身不改变退出码。
- `transport_opaque` 只是能力边界；诊断不使用 `delivery-suspected`、`execution`、`orchestration` 或 Provider/加密/解密/stream 关键词推断根因。

- 无治理前缀或未映射任务的原生调用按 unmanaged 兼容边界处理，不创建半套治理状态。
- 以 `sg_` 开头但缺少合法 task ref、PreparedContract 或匹配 StateStore 的调用是无效 governed spawn，必须在原生调用前拒绝，不能降级为 unmanaged。
- PostToolUse 只通过已认领的 `tool_use_id` 关联 spawn；有限响应适配器只读取已知顶层或单层结构化字段。success 无可靠身份和 unknown 都保持 `not_started + unconfirmed + reconcile`。
- Agent ID 和 canonical task path 只精确绑定到 `{task_id, attempt}`。`SubagentStart` 只接受已有精确 Agent 映射或事件携带的合法 task ref，不使用同名、同轮、唯一候选或任意候选。
- Hook 只处理可观察事实，不把身份未确认推断为消息未送达，不把缺少终态推断为任务漂移或父 Agent编排错误。
- `SubagentStop` 放行只表示不再阻止当前停止，不表示父任务已收到正式结果或完成业务验收。
- 真实平台投递、Provider 恢复、mailbox 展示、Hook trust 和上下文参数映射必须通过真实 Codex 验证；本地 fixture 不能替代。

完整边界见 [references/runtime-boundaries.md](references/runtime-boundaries.md)。

## 与其他 Skill 的关系

不要修改或要求现有 Skill 采用本协议。任何 Agent 真正调用 `spawn_agent` 时，都作为一次新的独立派发进入相同治理链；插件不建立父子权限图或完整多 Agent 编排系统。
