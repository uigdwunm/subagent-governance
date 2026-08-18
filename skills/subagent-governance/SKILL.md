---
name: subagent-governance
description: 为 Codex 原生子 Agent 选择 light、standard、strict 或 auto 治理方式，并规范任务派发、通信、等待、恢复、中断、终态通知和生命周期关闭。用于用户要求规划、派发、加强、诊断或治理子 Agent，准备调用 spawn_agent、send_message、followup_task 或 interrupt_agent，任务需要上下文隔离、完成确认、失败恢复或并发协调时。不要因为普通任务碰巧包含子 Agent 字样就主动引入重型流程。
---

# 子 Agent 治理

保持 Codex 原生 `spawn_agent`、`send_message`、`followup_task`、`wait_agent` 和 `interrupt_agent` 为执行通道。本 Skill 负责统一任务契约和生命周期操作；插件只校验机械事实，不替父 Agent 判断业务质量、真实性或证据充分性。

## 使用边界

- 普通任务不需要加载本 Skill，也不要仅因任务可以拆分就主动创建子 Agent。
- 准备规划、派发、通信、等待、恢复、中断或关闭原生子 Agent 时，先完整读取本 Skill。
- 子 Agent 相关自然语言说明使用中文；模型名、参数、命令、路径、Agent 标识和状态枚举可保留原文。
- 不引入第二套编排平台，不扫描 transcript、summary 或历史 final text 推断任务事实。

## 任务契约

所有治理等级使用同一 TaskContract：

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

生成器补充 `resolved_mode` 和 `resolution_reason`。`task_features` 只在 auto 时必填；`model`、`reasoning_effort` 和允许为空的文本可为 JSON `null`。空值不伪造继承参数。

## 治理等级

- `light`：边界清楚、只读、短时、低影响。
- `standard`：普通编码、诊断、研究和 Review。
- `strict`：安全、迁移、生产、破坏性操作、并发写入或复杂协作任务。
- 显式等级不自动升降；`auto` 只按结构化 `task_features` 解析。
- 任一 strict 信号成立则解析为 strict；`risk=low + read_only=true + writes_files=false` 且无 strict 信号时为 light；其余合法组合为 standard。
- standard 至少一项证据要求；strict 至少一项禁止范围和一项证据要求。

完整边界见 [references/governance-levels.md](references/governance-levels.md)。

## 上下文

- `isolated`：默认，不继承上下文，`context_turns=null`。
- `limited`：继承最近 1 至 100 轮，必须提供 `context_turns` 和理由。
- `full`：完整继承，`context_turns=null`，理由必填。

## 派发

1. 填写 TaskContract，通过标准输入调用 `scripts/subagent_governance.py --prepare-dispatch --session <session_id>`。
2. 生成器先原子保存 PreparedContract，再创建 StateStore 初始 task；任一门禁失败都不调用原生 `spawn_agent`。
3. task name 固定为 `sg_<resolved_mode>_<semantic_name>_t_<task_ref>`。PreToolUse 只从未加密 task name 解析 ref，不读取业务正文。
4. 先向用户展示生成的 `user_message`，再把 `spawn_args` 原样交给原生 `spawn_agent`。
5. dispatch prompt 包含唯一目标、背景、范围、禁止事项、完成条件、证据要求和终态通知义务，不包含结果存储协议。

明确 failed 后使用 `--prepare-spawn-retry <task_id>`；第二次也是最后一次 retry 需 `--authorize-final-retry`。任何一次 observation 为 unknown 都禁止复用同一 attempt 重派。

initial 和 retry 在 preparation 与 PreToolUse claim 两处都要求 work item open 且来源 execution 未关闭。

## 批量派发与 Group

并行派发前用一张表格说明每个 Agent 的目标、治理等级、模型、强度、上下文、范围和完成条件。每个 Agent 仍对应一次独立原生 `spawn_agent`。

只有父 Agent 明确需要关联多个 work item 时才使用 `--upsert-group`。Group 只保存 `group_id`、`objective_summary` 和 `members=[{task_id, required}]`。

- `--read-group` 实时读取成员状态。
- `summary_ready` 要求 required 非空，且每个 required 成员已收到精确终态通知或已明确关闭。
- `group_action_required` 只聚合 required 成员的 individual action-required。
- optional 成员不影响两个 required 聚合信号。
- 插件不生成聚合业务结论，不暂停其他成员，不建立 DAG、batch、wave 或组级状态机。

## 通信

通信必须显式提供 `operation_type`：

- `normal_message`
- `platform_recovery`
- `business_resume`

使用 `--prepare-communication` 生成通信；主动中断使用 `--prepare-interrupt`。Managed target 不得绕过生成器直接发送。

- `pending_action` 初始为 prepared，5分钟内由匹配 target 的 PreToolUse 原子认领为 claimed 并绑定 `tool_use_id`。
- PostToolUse 只按 `tool_use_id` 对账 success、failed 或 unknown。claimed 后20分钟仍无 PostToolUse，才在后续显式读取中记 unknown。
- normal message 只补充上下文，不改变生命周期。
- platform recovery 只适用于精确 observation error，同一 attempt 最多一次自动恢复和一次用户授权恢复。
- business resume 只在精确终态通知已到且父动作是 `decide_disposition`，或前一次 resume delivery failed 时创建新 attempt。它必须提供重新校验的 TaskContract。
- business resume success/unknown 不通过 SubagentStart 猜测 running；unknown 后不得向同一 Agent 重发。需要继续业务时必须按 business resume 的新 attempt 流程派发。
- normal message 在 StateStore unavailable 时可告警 fail-open；受治理的 recovery 和 resume 前置事实不可可靠写入时拒绝。

`agents[target]` 只是 active index。索引缺失时只有唯一精确且未关闭的 retained provenance 才能恢复；多候选、索引冲突或 historical closed target 必须对账，不能按 unmanaged 放行。

## 等待、巡检和中断

- 派发后保存 Agent ID 和 canonical task path，以 `timeout_ms: 1200000` 调用 `wait_agent`。
- 正常等待超时后做一次精确目标巡检；平台明确报错时立即巡检。
- 精确 running 时继续等待，不读取代码、日志或测试猜进度，不发送心跳。
- `list_agents` adapter 只读取顶层 `agents`，不扫描 `content`、summary、history 或 transcript。
- completed、stopped、interrupted 的 list observation 只证明平台终态，不替代原生终态通知，也不生成业务结果。
- 已看到平台终态但通知未到时，closure 为 `await_notification`，父动作是 `reconcile`。
- `interrupt_agent` 只有可靠 inactive 事实才关闭 attempt；unknown 保持 reconcile。

重启后若外部只读事实精确确认 worker interrupted，可使用 `--reconcile-interrupted-attempt`。已持久化的精确 list terminal fact 会直接派生 closure 状态，不需要额外补账入口。

## 终态通知与父处置

子 Agent 完成、阻塞、失败或需要决策时，通过原生最终回复向父 Agent 说明实际结果、验证证据和剩余事项。插件不规定 JSON 结果结构，不保存通知正文，也不审查业务内容。

父 Agent 收到当前原生 child notification 后，记录最小观察：

```bash
python3 scripts/subagent_governance.py --record-terminal-notification --session <session_id>
```

stdin：

```json
{
  "sender_target": "/root/<exact-native-agent-target>",
  "task_id": "<task_id>",
  "attempt": 1,
  "terminal_status": "completed"
}
```

- `sender_target` 必须原样等于该 execution 的 `dispatch_record.dispatch_target`。
- 相同通知重放幂等；terminal status 冲突保留首个事实并进入 reconcile。
- 只记录 sender、task、attempt、terminal status 和观察时间，不创建 `results/`，不保存正文、摘要或 SHA。
- 父 Agent 直接阅读原生通知并自行判断业务是否满足目标。

父处置通过 `--parent-disposition --session <session_id>` 提交 `{task_id, attempt, action, reason}`，action 只有：

- `close_task`：关闭全部非运行 attempts；仍明确 running 的 attempt 返回精确 interrupt targets，不自动中断。

插件不提供 accept/reject 业务验收状态。关闭只表示父 Agent 已完成自己的判断并结束治理生命周期。

## 三平面状态

每个 execution 只有三个 canonical plane：

- `dispatch_record`：派发准备、claim 和原生响应关联。
- `observation_record`：精确 target 的平台或终态通知观察。
- `closure_record`：等待观察、等待通知、等待父处置或已关闭。

StateStore 还保存有限 identity、恢复计数、pending operation 和 tombstone。它不保存业务结果正文、验收状态、结果文件引用或结果冲突。

`parent_action` 只表达生命周期下一步：`wait|reconcile|retry_spawn|recover|decide_disposition|ask_user` 或 JSON `null`。

`action_required` 和 `recent_activity` 是独立只读派生视图。前者覆盖未关闭父动作、running、未决调用和身份未确认；后者只控制最近活动展示。

## Session 与诊断

- SessionStart 复用 prepared/claimed reconcile，清理到期 tombstone，并显示 action-required 和 recent activity。
- Stop 最多读取 StateStore 三次，当前只给 advisory 且固定 fail-open，不替父 Agent 判断业务结果。
- SessionEnd 仅在 action-required 为空且没有保留期 tombstone 时删除 Session JSON；稳定 `.lock` 永不删除。
- tombstone 保留7天。v5 不读取或删除旧 `results/` 文件；历史文件由用户自行清理。
- `--diagnose [--session <session_id>] [--data-root <root>]` 使用无锁只读路径，不创建目录、锁或临时文件，不 reconcile、修复或回写状态。
- 诊断输出 work item、execution candidate、通知状态、group 和有界 issue；不扫描旧结果目录，不转储业务正文。

完整边界见 [references/runtime-boundaries.md](references/runtime-boundaries.md)。

## 与其他 Skill 的关系

不要修改或要求现有 Skill 采用本协议。任何 Agent 真正调用 `spawn_agent` 时，都作为一次新的独立派发进入同一治理链；插件不建立父子权限图。
