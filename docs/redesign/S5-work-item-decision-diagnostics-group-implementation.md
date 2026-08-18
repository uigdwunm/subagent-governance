# S5 work-item 决策诊断与 group 实施记录

## 范围

本切片在开发仓库内实现 D6 S5：diagnose 新增 work-item-first 决策快照，group 实时读取同一快照，SessionStart 优先显示 work-item 决策摘要。旧 `action_required` / `recent_activity` attempt 数组继续作为 secondary 兼容字段；Stop 仍直接调用 S4 权威函数，不解析诊断 JSON 或摘要文本。

本轮没有修改稳定发布源、运行缓存、Hook trust、Marketplace、Registry、外部对话或其他项目；没有安装、发布、同步缓存、stage、commit、push 或 PR，也没有开始 S6 兼容退役。

## 失败先行基线

修改运行时代码前，在 `tests/test_minimal_diagnostics_lightweight_groups.py` 与 `tests/test_wait_recovery_session_closure.py` 增加 S5 反例，并运行：

```text
python3 -m unittest -v tests.test_minimal_diagnostics_lightweight_groups tests.test_wait_recovery_session_closure
Ran 51 tests
FAILED (failures=1, errors=13)
```

其中 9 个 errors 直接来自 SessionSnapshot 缺少 `work_items`；group 反例显示 stale root `attempt=1` 覆盖 canonical `work_item.current_attempt=2`；SessionStart 仍逐 attempt 输出旧 `任务 ID` 文本。最初另有 4 个 errors 来自测试 fixture 预先伪造 available 结果后再次调用正式结果提交，触发 S1 防覆盖门禁；修正 fixture 后，剩余失败只对应上述 S5 缺口。

## 输出形状

每个 Session 新增稳定排序的 `work_items[]`，每项仅包含有界决策事实：

```text
task_id
objective_summary
current_attempt
lifecycle: open | tombstoned | indeterminate
action_required
recent_activity
execution_candidates[]
outcome_availability
disposition
allowed_actions[]
facts[]
timestamps
```

`execution_candidates[]` 聚合 canonical `executions`，包含最小 identity/execution/platform/result/closed/action/recent facts；不输出完整 result、evidence、remaining、prompt、pending action、lifecycle 原对象或平台响应。duplicate candidate 分别保留，不按 attempt、时间或结果可读性自动选择。顶层 duplicate 使用 `selection_pending`，同一 attempt 两份 outcome 才使用 `conflict`。

结果引用继续使用 WP-07 的精确只读复验。StateStore 声称 `valid + available` 但文件缺失、损坏或 digest 不符时，work item 投影为 `unavailable`，不暴露 `review_result`，也不回写 storage 状态或重关联文件。

容量继续复用每 Session 256 executions 的既有上限，但按完整 work item 边界纳入：若加入某个 work item 会超过上限，则省略该 work item 的全部 candidates，并产生 `scan_incomplete`；不会输出半个 work item。

## allowed actions

固定顺序来自 `governance-semantics`：

```text
wait, reconcile, retry_spawn, request_result_correction,
review_result, record_disposition, select_attempt, request_interrupt,
resume_business, spawn_replacement, inspect_tombstone
```

每项必须有非空 `basis[]`；`request_interrupt` 只带 confirmed 精确 target。主要矩阵如下：

| 持久化事实 | allowed actions |
| --- | --- |
| confirmed running current | `wait`；观察/身份 unknown 时另有 `reconcile` |
| reliable spawn failed + not-created + retry 余额 | `retry_spawn` |
| stopped + needs_correction + 余额 | `request_result_correction` |
| complete + valid/readable/available + pending | `review_result`, `record_disposition` |
| blocked / failed / needs_decision / rejected / interrupted | `record_disposition` |
| protocol exhausted / storage unavailable / result unreadable或 conflict | `record_disposition`，不伪造 failed |
| duplicate 未选择 | `select_attempt` |
| 已选择且未选 candidate confirmed/running | `request_interrupt` + exact target |
| unknown / legacy lifecycle 不完整 | `reconcile`，不变成 failed/retry |
| tombstoned | `inspect_tombstone` |

`parent_action=business_resume` 或普通建议不构成授权。只有 persisted disposition、current attempt 精确关联和新 contract/deliverable digest 都存在时，才可能显示 growth action；S3 已创建的新 execution 只进入自己的 wait/reconcile 链，不因历史 disposition 重复暴露 resume/replacement。diagnostics 不创建 disposition、PreparedContract、pending action、reviewer 或新 Agent。

## group 聚合

group 持久化结构保持五字段：`group_id`、`objective_summary`、`members[{task_id,required}]`、`created_at`、`updated_at`。read/diagnose group 实时调用 work-item decision snapshot，不再读取 root current/prior 投影。

- `summary_ready=true`：required 非空，且每个 required 的 current work-item 材料为 `pending_review|available|superseded_by_selection`，或 lifecycle 已 reasoned tombstoned。
- `group_action_required=true`：任一 required 尚未完成 individual disposition；pending review、blocked、failed、needs_decision、unknown、duplicate、unavailable/conflict 和 open lifecycle 都保持 true。
- optional 只展示，不影响两个聚合信号；required 为空时两个信号均为 false。
- group 不生成 AggregateResult、allowed actions、组级 disposition，也不调度、暂停、取消或中断成员。

成员输出以 `lifecycle/action_required/outcome_availability` 为核心；旧 `individual_action_required`、`disposition_complete`、`summary_material_ready` 暂留兼容，S6 前不删除。

## canonical 与兼容接线

- `_canonical_work_item_view()` 优先读取 `work_item + executions`；root current / `prior_attempts` 冲突时不参与决策。legacy managed record 只生成内存 adapter，不迁移、不回写，lifecycle 缺失投影为 `indeterminate + scan_incomplete + reconcile`。
- diagnose 的旧 attempt 数组仍复用 `_action_required_records()` / `_recent_activity_records()`，字段含义不变。
- SessionStart 在完成 S4 的 prepared/claimed reconcile 与 tombstone cleanup 后，从 canonical state 构造 work-item 摘要，并保留 compact/resume 不得重复创建 Agent 的提示。
- Stop、SessionEnd 和平台 handler 不读取诊断文本；Stop 仍直接消费 `_stop_blocking_records()`，SessionEnd 仍直接消费 `_action_required_records()`。

## Schema

`schemas/governance-semantics.schema.json` 新增逻辑 defs：

- `decision_allowed_action`
- `decision_execution_candidate`
- `decision_outcome_availability`
- `work_item_decision_snapshot`

`x-semantics.work_item_decision_snapshot` 固定 work item 主单位、canonical sources、完整边界容量、action 顺序、growth gate、duplicate/result-conflict 区分和不输出完整结果；group 增加 work-item decision source、无 AggregateResult、无调度/取消锚点。没有新增 protocol version、wire payload 或第四份 Schema。

## 验证

失败基线后的最终验证：

- `python3 -m unittest -v tests.test_minimal_diagnostics_lightweight_groups tests.test_wait_recovery_session_closure`：`52 tests OK`。
- `python3 -m unittest -v tests.test_state_store tests.test_dispatch_identity tests.test_communication_lifecycle tests.test_formal_result_parent_closure tests.test_semantic_baseline tests.test_hook_fixtures`：`158 tests OK`。
- 加入 semantic baseline 的最终定向：diagnostics、Session/Stop 与 semantic baseline 共 `65 tests OK`。
- `python3 -m unittest discover -s tests -v`：`279 tests` 中 `277` 通过；仅两个既有 `release_preflight` errors，均来自 `docs/redesign/D6-migration-and-slices.md` 的 host-specific path，未新增 S5 failure。
- `python3 -m py_compile scripts/subagent_governance.py`：通过。
- Plugin validator：通过。
- Skill validator：通过。
- 修改 JSON 的 `python3 -m json.tool` 与 `git diff --check`：通过。

中间兼容回归也曾将上述八个 S1-S5 模块合并运行，结果为 `209 tests OK`。

## not_checked 与剩余事项

本轮明确未验证：

- 已安装插件中的真实 diagnose CLI 与真实 Session 数据；
- Codex UI 中真实 SessionStart work-item 摘要展示、长度和可读性；
- 真实 group 多任务创建、等待、迟到结果和成员生命周期；
- Provider 断流/重启、真实 SubagentStart/SubagentStop、Hook trust 和运行缓存加载。

这些项目需要后续按项目“外部问题修复与真实测试”流程，在开发仓库本地验收后另行授权同步测试插件并新建对话。本轮不做真实插件测试。S6 仍负责 compatibility retirement/release preparation；本切片不删除 root/prior projection、旧 attempt arrays 或其他兼容消费者。
