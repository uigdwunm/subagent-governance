# S4 平台观察、等待、重复收口与会话闭环实施记录

## 范围

本切片实现 D6 S4 在开发仓库内的最小本地闭环：把平台观察、等待中的调用对账、
重复执行收口、Stop 保护以及 SessionStart/SessionEnd 清理迁移到 canonical
`tasks[task_id].work_item + executions[attempt]`。`root` current 与
`prior_attempts` 仅作为兼容投影，由同锁 projection writer 刷新。

本切片不实现 S5 work-item diagnostics/group，也不做 S6 compatibility retirement
或 release preparation；不写稳定发布源、运行缓存、Hook trust、Marketplace 或
Registry。

## 失败先行基线

修改运行时代码前，新增 canonical 反例后定向基线为 `66 tests`，其中以下行为稳定
失败：

- canonical stale prior 的 `action_required` 被旧 root/prior 遗漏；
- canonical `running` 未阻止 Stop；
- canonical action-required 被 SessionEnd 误删；
- 精确空 `list_agents` 与 5 分钟 prepared 清理只写 execution，未刷新 root 投影；
- legacy managed task 在 list_agents、pending reconcile 和首次 SubagentStop 写入时
  未惰性迁移到 canonical。

这些失败证明旧 attempt-first/root-first 消费路径不能作为 S4 完成依据。

## 实现摘要

- `_view_attempt_records()` 通过 `_iter_task_attempts()` 遍历 canonical executions，
  并依据 `work_item.current_attempt` 标记 current；因此 `action_required`、
  `recent_activity`、Stop、SessionStart 和 SessionEnd 使用同一权威 adapter。
- `reconcile_pending_actions()` 在处理 legacy pending action 前惰性迁移 canonical；
  5 分钟未认领 prepared 精确清理且不消耗 operation 预算，20 分钟已认领调用只写
  `unknown + reconcile`，保留 operation 预算、canonical attempt 和审计事实。完成后
  同锁刷新 root/prior 投影。
- `list_agents` 保持平台三值边界：`pending_init`、精确空列表和弱/含糊观察只能写
  `unknown`/受限摘要，不能推断 `not_started`、terminal 或 running，也不能覆盖已确认
  terminal。只有精确 target、确认身份和相符平台事实才允许收口。精确 `running` 会把
  execution 写回 `running + normal`；无 unresolved interrupt 时清理 stale recovery 状态并
  回到 `wait`，有 interrupt 时保留 lifecycle/duplicate 并维持人工对账边界。
- `completed|stopped` 在有合法 TaskResult 时保留验收状态；无结果时只进入
  `needs_correction + correct_result`，补交额度耗尽后为 `exhausted + manual_review`，
  不从 summary 或自由文本生成业务结果。精确 `interrupted` 进入
  `interrupted + decide_disposition`。
- platform recovery 与 result correction 使用独立预算；同一 Agent/attempt 在使用第二次
  recovery 前进入 `awaiting_authorization + ask_user`，只有用户明确授权才可使用最后一次
  recovery，unknown 不自动重发。
- recovery 调用的 `success|unknown` 不是 Agent 已恢复的证据；如果同一 canonical target
  随后被 exact `list_agents` 直接报告 `errored`，即使中间没有 Start/running，也会清除
  该 unresolved recovery lifecycle，并按 `recovery_count=1|2` 分别进入
  `awaiting_authorization|exhausted`。
- duplicate `select_attempt` 后，运行中的未选 candidate 只返回精确 interrupt target。
  interrupt failed/unknown 保持未关闭、未 tombstone、duplicate 未清；可靠 success 或
  精确 terminal 后才关闭，全部未选 candidate 可靠关闭后才恢复所选 parent action。
- `action_required` 遍历全部 canonical executions，不使用 12 小时窗口；
  `recent_activity` 仅作最近活动展示。SessionStart 先做 prepared/claimed reconcile，
  再按 action-required 优先、recent 次之生成摘要，并提醒 compact/resume 不要重建已有
  Agent。
- Stop 最多读取三次 StateStore。running、claimed/pending call、身份未确认成功/unknown
  和可恢复平台错误阻止当前结束；complete pending、blocked、failed、needs_decision 或
  correction exhausted 允许当前回复结束，但仍保留 action-required。三次读取失败机械
  阻止并要求用户选择强制结束或先诊断/恢复。
- SessionEnd 只有 action-required 为空且无 7 天保留 tombstone 才删除 Session JSON；
  稳定 `.lock` 不删除。tombstone/result 只按精确 task/attempt/ref 清理；result 删除
  失败时保留 tombstone。

## 状态矩阵

| 场景 | canonical 结果 | 父动作/收口 |
| --- | --- | --- |
| `pending_init`、精确空列表、弱观察 | `platform_observation=unknown`，不改既有 confirmed terminal | `reconcile` 或保留既有状态 |
| 精确 `running`，无 unresolved interrupt | `execution_status=running + platform_observation=normal`，清 stale recovery 状态 | `wait`；不消费 lifecycle/Start 凭证 |
| 精确 `running`，有 unresolved interrupt | 写 `running + normal`，保留 interrupt lifecycle/duplicate | `ask_user`；不关闭、不 tombstone |
| claimed 超过 20 分钟 | operation observation `unknown` | `reconcile`，不重发 |
| prepared 超过 5 分钟且未认领 | 精确移除 pending action | 不消耗 operation 预算 |
| 第二次 platform recovery 前 | `awaiting_authorization` | `ask_user`，需明确授权 |
| recovery success/unknown 后直接 exact errored | 清除旧 recovery lifecycle；按已用次数进入 `awaiting_authorization|exhausted` | `ask_user`，不会因缺少中间 running 卡死 |
| result correction 无结果 | `stopped + needs_correction` | `correct_result` |
| result correction 耗尽 | 保留无业务结果 | `manual_review` |
| 精确 terminal `interrupted` | `interrupted` | `decide_disposition` |
| duplicate interrupt failed/unknown | execution 未关闭，duplicate 保留 | 继续 `resolve_duplicate` |
| Stop 仅有 reportable action-required | 不改状态 | 当前回复可结束，状态保留 |
| SessionEnd 有 action-required/tombstone | Session JSON 保留，lock 保留 | SessionStart 继续恢复 |

业务结果仍只来自合法结构化 TaskResult；平台、协议和存储事实不伪造
`complete|blocked|failed|needs_decision`。

## Canonical 迁移与兼容接线

所有本轮写路径都在同一 StateStore 锁内先确保 canonical execution，再更新该 execution
和 `work_item`，最后调用 projection writer 刷新 root/prior。覆盖路径包括 pending
reconcile、精确空列表、normal list_agents、terminal reconciliation、duplicate interrupt
收口和 managed SubagentStop 协议缺口。未适配的历史记录仅在实际写入时惰性迁移；读取
路径优先 canonical，不通过整 task 扁平替换破坏其他 executions。

本轮没有新增 machine 状态或字段，因此没有新增 Schema 定义；现有 platform observation、
pending action、result protocol、tombstone 和 canonical work-item fixture 足够覆盖本片。

## 验证

已运行并通过：

- `python3 -m unittest -v tests.test_communication_lifecycle tests.test_wait_recovery_session_closure`：`73 tests OK`；
- `python3 -m unittest -v tests.test_state_store tests.test_dispatch_identity tests.test_formal_result_parent_closure tests.test_hook_fixtures`：`92 tests OK`。

- `python3 -m unittest discover -s tests -v`：`268 tests` 中 `266` 通过；仅保留两个
  既有 `release_preflight` errors，均来自 `docs/redesign/D6-migration-and-slices.md` 的
  host-specific path，不在本切片修复范围；
- `python3 -m py_compile scripts/subagent_governance.py`、Plugin validator、Skill
  validator、全部变更 JSON 的 `python3 -m json.tool` 和 `git diff --check`：通过。

## Not checked / 剩余事项

以下需要真实 Codex 平台或新对话验证，本轮均未执行：Provider 重启/断流、`pending_init`、
精确空列表的真实返回、interrupt 原生终态、Session Hook 实际时序、真实 SubagentStop
结构化 payload、Hook trust、缓存加载以及真实恢复/等待顺序。本轮未做真实插件测试。

后续 S5 负责只读 diagnostics/group；S6 才能在所有 canonical consumers 验收后退役兼容
投影并准备发布。本轮无范围外代码、稳定源或缓存改动，也未安装、发布、stage、commit、
push 或创建 PR。
