# F6 canonical record Schema 实施记录

## 1. 范围与结论

F6 只修复整体架构复核的 P2-4。`schemas/governance-semantics.schema.json` 现在是 runtime canonical work-item、execution、transition、operation、result/closure facts、formal disposition 和只读 decision snapshot 的唯一可执行机器语义锚点；`task-contract-v1.schema.json` 与 `task-result-v1.schema.json` 继续只负责 wire contract/outcome，不承载 acceptance、platform、storage 或 closure 状态。

本切片没有新增状态机、事件日志、DAG、scheduler 或业务重试预算，也没有改变 Hook 既有 fail-open/fail-closed 边界。Schema 约束由开发期/测试期 validator 执行；未知扩展字段继续前向兼容，受控核心字段的 required、enum 和组合约束则不能任意化。

## 2. 真实 record inventory

以下 inventory 来自 runtime constructors/writers/readers 和实际生成 fixture。表中的“required”是 canonical core；“optional”是按阶段出现的受控事实。Schema 允许其他未知扩展字段，不把 provider/debug 的偶然字段冻结为必需。

| record | required core | nullable / optional | enum 与组合约束 | writers / readers | 真实生成阶段 |
| --- | --- | --- | --- | --- | --- |
| 持久 task container | `managed, task_id, work_item, executions` | 未知扩展 | `managed=true`；`executions` 至少一项且 key 为正整数 attempt，每项是 `execution_record` | `_initial_task_record`, `_ensure_canonical_task_record`, `_task_record_for_attempt`, `_iter_task_attempts` | initial 创建；后续所有 canonical CAS/write |
| canonical state | `session_id, tasks, agents, health, tombstones, updated_at` | 未知顶层扩展 | `tasks/agents/tombstones` 的 value 分别受控；不以 version gate 拒绝旧记录 | `StateStore`, diagnose 的只读 loader | Session 初始化、Hook/CLI 状态写入、diagnose 只读 |
| `work_item` | `objective_summary, lifecycle, current_attempt, created_at, updated_at, attempt_count, replacement_spawn_count, last_parent_disposition, last_growth_authorization` | 两个 `last_*` 可为 null；`repeated_business_attempts`, `repeated_replacements` 按增长阶段出现 | `lifecycle=open|tombstoned`；`attempt_count>=1`；退役的 `action_required`、`last_disposition` 不允许成为新 canonical 字段 | `_initial_task_record`, `_sync_canonical_work_item`, growth/parent disposition writers；`_canonical_work_item_view`, `_work_item_allowed_actions`, `_work_item_growth_projection` | initial；resume/replacement claim；accept/reject/close/select；tombstone |
| `execution_record` | Python `CANONICAL_EXECUTION_FIELDS` 对应的 36 个核心字段：身份/contract/dispatch、状态维度、三个预算、spawn claim/observation、timestamps | `transition`、多个 observation/status 可为 null；result reference/conflict、pending/lifecycle、reservation、growth/disposition、duplicate、closure、activity/platform/start facts 按阶段出现 | 核心 enum 由 `$defs` 控制；available 必须有 reference/digest/stored_at 且 protocol valid；unavailable 不得有 business result/acceptance；conflict 必须有 digest/time；closure 必须有 reason/time；claimed replacement/resume 必须有 transition/growth facts | `_initial_task_record`, `_create_resume_attempt`, spawn/lifecycle/identity/result/disposition/closure helpers；所有 Hook/CLI 与 decision snapshot readers | initial prepared/claimed/PostTool/Start；retry；replacement reserved/claimed；business resume；recovery/correction/interrupt；formal result；parent closure |
| `dispatch_transition` | `from_attempt, reason_code, reason, authorized_by` | replacement 的 `duplicate_risk_accepted` | retry/resume/replacement reason code 分组受控；replacement 只允许 parent/user；unknown duplicate risk 必须接受；resume 由 parent 授权 | `prepare_spawn_retry`, `prepare_replacement_dispatch`, `prepare_communication`; PreparedContract 和 claim readers | retry preparation；replacement reservation/claim；business-resume prepare/claim |
| `growth_authorization` | `attempt, action, reason, recorded_at` | `authorized_by=parent|user` 可选 | action 仅 `resume_business|spawn_replacement`；不能验证成 formal disposition | replacement/resume prepare+claim；`_work_item_growth_authorization`, `_work_item_growth_projection` | replacement claim；business-resume claim；work-item 最近增长投影 |
| formal `parent_disposition_record` | `task_id, attempt, action, reason, recorded_at` | 只允许未知扩展 | action 仅 `accept_result|reject_result|close_task|select_attempt`；与 growth enum、字段名完全分离 | `apply_parent_disposition`, `_execution_parent_disposition`, `_work_item_parent_disposition`, closure/select helpers | complete accept/reject；blocked/failed/needs_decision close；duplicate select |
| `pending_action` | `target, task_id, attempt, task_ref, operation_type, phase, created_at, expires_at, tool_use_id, claimed_at, reason, authorized_recovery, start_observed_at` | prepared 时 tool/claim/start 可为 null；business resume 另有 contract/digest/ref/transition/growth facts | operation 为 `normal_message|platform_recovery|result_correction|business_resume|interrupt`；claimed 必须有非空 tool ID 和 claim time；business resume 必须有完整 resume 组合；旧 `disposition` 被拒绝 | `prepare_communication`, `prepare_interrupt`, `_claim_pending_action`, `reconcile_pending_actions`, `_handle_post_tool`, `_handle_subagent_start` | communication/interrupt prepared、claimed、Start/PostTool 对账 |
| `lifecycle_operation` | `operation_type, target, tool_use_id, call_observation, claimed_at, completed_at, reason` | `target_observation`, `native_status` | operation 不含 normal message；call observation 仅受控三态 | `_apply_action_observation`; recovery/result correction/resume/interrupt readers | PostToolUse 后保存最小无 TTL lifecycle observation |
| `replacement_reservation` | `reservation_id, source_attempt, task_ref, created_at, reservation_snapshot_sha256` | 只允许未知扩展 | ID 为 24 位 hex、snapshot digest 为 SHA-256；reservation 尚不是 growth commit | `prepare_replacement_dispatch`, claim/rollback/expiry reconciliation | replacement prepared 到成功 claim 或精确回滚/过期 |
| result reference/storage/protocol/acceptance facts | execution core 的 `business_result, acceptance_status, result_protocol_status, result_storage_status, result_conflict`；available/conflict 时出现相应引用事实 | `result_reference, result_sha256, result_stored_at, result_conflict_sha256, result_conflict_first_seen_at` | business result 仅四种 TaskResult outcome；platform error、protocol failure、storage unavailable 都不能生成它；available/unavailable/conflict 组合见 execution Schema | `submit_task_result`, `_associate_result_record`, `_mark_result_storage_unavailable`, `_mark_result_protocol_gap_record`, `_inspect_formal_result_read_only` | complete/blocked/failed/needs_decision；result correction；storage failure；conflicting replay |
| closure facts | execution 的 `attempt_closed=true, attempt_close_reason, attempt_closed_at`；work item 的 lifecycle/current disposition | Agent mapping 清理按精确 target；未知扩展不参与 closure | `attempt_closed` 出现时 reason/time 必须同时存在；formal close 与 duplicate-unselected close 不伪造业务结果 | `_close_attempt_record`, `_close_unselected_duplicate_attempt`, `apply_parent_disposition`, `_attempt_has_reasoned_close` | accept/close/select；interrupt 成功或可靠 terminal 后关闭未选 duplicate |
| `tombstone_record` | `task_id, attempt, close_reason, closed_at` | `task_ref, agent_id, canonical_task_path, last_execution_status` | 不以缺少尚未观察的可选身份事实拒绝；保留期和精确清理仍由 runtime semantics 控制 | `_tombstone_record`, closure helpers, `cleanup_expired_tombstones`; Stop/Start/result/diagnose readers | task close、未选 duplicate close、7 天精确清理 |
| `agent_identity_mapping` | `task_id, attempt` | mapping key 本身是 target；未知扩展允许 | 只作 active target index；execution retained provenance 仍是迟到事件权威，mapping 不拥有业务状态 | `_bind_identity_target`, `_assign_starting_agent`, Start/Stop/list/interrupt/closure readers | SubagentStart/精确 identity 绑定；resume 切换 active attempt；关闭清理 |
| `work_item_decision_snapshot` | `task_id, objective_summary, current_attempt, lifecycle, action_required, recent_activity, growth, execution_candidates, outcome_availability, disposition, allowed_actions, facts, timestamps` | 子结构中的 nullable/optional 由相应 `$defs` 控制 | 只读、非持久；unknown/indeterminate 不补造事实；allowed actions 和 growth 仅从 canonical sources 派生 | `_build_work_item_decision_snapshot`, `_canonical_work_item_view`, diagnose/group/SessionStart readers | diagnose、group member projection、SessionStart 摘要 |

核心字段的完整逐项定义和所有 enum 只维护在 governance Schema；本表记录责任与生成阶段，不复制第二份可执行 Schema。

## 3. 命名与兼容裁决

F6 将两个不同概念永久分名：

```text
formal outcome disposition:
  execution.parent_disposition_record
  work_item.last_parent_disposition
  accept_result | reject_result | close_task | select_attempt

growth authorization:
  execution.growth_authorization
  pending_action.growth_authorization
  work_item.last_growth_authorization
  resume_business | spawn_replacement
```

新 writer/API 使用 `growth_authorization`。旧 canonical `work_item.last_disposition`、execution 的 `parent_disposition` 及 reason/time companions、pending `disposition`，以及短期 replacement authorization 中的旧 `parent_disposition` 只允许 compatibility read。合并按三态执行：canonical 字段 absent 或 JSON `null` 都表示尚未观察，可由通过完整核心字段校验的 legacy observed fact 填充；canonical non-null 表示已观察，值相同则幂等删除旧名，值不同则抛出 `StateConflictError` 或 `PreparedContractValidationError`。非法 action、类型错误或缺 attempt/reason/time 的旧值不会提升为 canonical。纯 diagnose 通过只读 accessor 理解合法旧名，不回写；work-item formal legacy 缺少其旧形状未持久化的 `task_id` 时，只能从当前 canonical task container 的精确 key 补齐，不能猜测其他身份。没有长期双字段权威、attempt-first/root authority 或 version/migration gate。

## 4. Schema 与 validator 实施

- governance Schema 新增或收紧 `canonical_state`、`canonical_task_container`、`work_item`、`execution_record`、`dispatch_transition`、`growth_authorization`、`parent_disposition_record`、`pending_action`、`lifecycle_operation`、`replacement_reservation`、`tombstone_record`、`agent_identity_mapping` 和 decision snapshot 相关 `$defs`。
- 受控核心字段使用 required/enum/const 和 `if/then`/`allOf` 组合约束；未知前向扩展仍由 `additionalProperties: true` 接纳。已经退役且会造成双权威的已知字段显式为 `false`。
- 新增 `tests/schema_validation.py`。当前环境没有第三方 `jsonschema`，helper 明确实现本仓库使用的 Draft 2020-12 子集，并在发现不支持的 assertion keyword 时失败，不静默跳过。
- `tests/test_canonical_record_schema.py` 用实际 runtime writers 生成阶段记录并验证，同时双向比较 Python enum/core field sets 与 Schema enum/required/properties，防止任一侧单独漂移。

## 5. 失败先行与 fixture 覆盖

首次实现前固定运行 5 个 F6 测试，结果为 2 failures、2 errors：缺少 canonical task-container/record `$defs`、execution required 过薄、没有独立 growth authorization，且 runtime 真实 container 无法作为完整受控对象验证。父任务验收发现 null merge 数据丢失后，先把 F6 扩展到 20 项：首次运行稳定出现 3 failures，分别命中 work-item growth null、work-item formal null、execution/pending null；随后对非法但 action 合法的不完整 legacy 做聚焦测试，又稳定得到 2 个失败 subtests。最终只读审计再以 1 个稳定 `TypeError` 证明 work-item formal compatibility accessor 未接收 task context。修复后 21/21 通过，覆盖 absent/null 填充、相同 non-null 幂等、冲突 non-null 拒绝、execution/pending/prepared merge、非法 legacy 不提升、只读 formal legacy context，以及原有非法 enum/required/组合/forward-extension/runtime stage cases。

runtime fixture 覆盖：

1. initial prepared/claimed/PostTool success/SubagentStart；
2. initial failed 与同-attempt retry claim；
3. replacement reserved/claimed、duplicate-risk transition 与 growth authorization；
4. business-resume prepared/claimed/Start；
5. platform recovery、result correction、interrupt 的 pending/lifecycle observations；
6. complete/blocked/failed/needs_decision 正式结果；
7. accept/reject/close/select formal disposition；
8. duplicate 未选项中断关闭、tombstone、agent identity mapping、canonical state 和只读 decision snapshot。

## 6. 验证

F6 定向和 F1-F6/S6 跨切片回归在实施期间通过；最终全量与静态/validator 结果以本切片结束时的命令输出为准。规定命令为：

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
Plugin validator
Skill validator
全部 JSON 解析
git diff --check
```

本轮兼容修正后的实际结果：F1-F6/S6 定向跨切片回归通过；父侧验收另补一项 validator 自证测试，固定“未支持的 assertion keyword 必须拒绝、`x-*` 注解扩展允许”的边界。最终全量 349 tests 中 347 passed，只有两个既有 D6 host-specific path errors：`test_current_development_tree_passes_with_supported_ref` 和 `test_release_requires_manifest_tag_and_marketplace_ref_to_match`。`scripts/*.py` 编译、Plugin validator、Skill validator、全部仓库 JSON 解析和 `git diff --check` 均通过；没有 F6 新失败。

## 7. not_checked、remaining 与父任务下一步

`not_checked`：真实 Hook/Skill 加载、Provider response shape、SubagentStart/SubagentStop payload、真实投递/乱序/重启/interrupt、UI diagnose 展示、N/N-1 安装升级回滚均未验证。本切片按授权不安装、不发布、不写稳定源/缓存、不修改 trust/Marketplace/Registry，也不新建真实插件对话。

`remaining`：P3 legacy/dead-code/doc cleanup 仍属于独立切片；两个 D6 host-specific path 基线错误保持原状。前向未知扩展的业务含义仍不由 Schema推断。

父任务下一步：验收本地 F6 diff 和上述完整验证证据；随后单独规划 P3。若以后按“外部问题修复与真实测试”流程验证插件，应先同步本开发仓库内容，再用新对话和规定模型配置测试，不能把本轮本地 Schema 结果冒充真实平台验收。
