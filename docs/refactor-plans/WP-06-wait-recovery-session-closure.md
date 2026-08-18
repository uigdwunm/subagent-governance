# WP-06 等待、恢复和会话闭环详细改造方案

## 一、状态、唯一目标与权威边界

- 工作包：WP-06「等待、恢复和会话闭环」。
- 权威来源：`docs/project-function-inventory.md`，重点是 U-05～U-09、SG-F05、SG-F06 的闭环项、第十三节、会话恢复链和第十六～十八节；`docs/optimization-plan.md` 只提供阶段顺序，不覆盖主盘点裁决。
- 前置依赖：WP-01 的机器语义与多维状态；WP-02 的稳定锁、CAS、原子替换、回读验证和 `cleanup_expired_tombstones()`；WP-03 的 PreparedContract、确定性 task ref、spawn 三态和精确 Agent 映射；WP-04 的 pending lifecycle、5/20 分钟 reconcile、有限恢复、interrupt 三态与 `last_lifecycle_operation`；WP-05 的正式结果、父处置、`select_attempt` 保存事实和确定性 result 地址。
- 唯一目标：建立 `action_required` 与 `recent_activity` 两个独立派生视图，完成父 Agent 20 分钟等待契约、Stop 三次读取机械保护、SessionStart/SessionEnd 恢复与保留、select 后未选运行 attempt 的显式中断闭环、duplicate 最终解除，以及 task/Session tombstone 与正式结果的精确清理。
- 实施方式：本文先行写完整方案；随后先增加稳定失败测试，再实施、同步开发 Skill/运行边界、全量验证，并在本文末尾回填实际结果与 WP-07 交接。

本阶段不引入后台 scheduler、Hook 定时器或第二套编排平台；父 Agent/Skill 才能实际调用 `wait_agent`、`list_agents`、`followup_task` 和 `interrupt_agent`。Hook/运行时只保存显式事实、准备或校验操作、派生视图、处理观察并保护 Stop/Session。

## 二、修改前现状与可复现失败基线

### 2.1 当前代码事实

1. `_recent_records(state, statuses)` 只遍历顶层 current task，固定使用最近 12 小时，并把展示窗口与权威活跃状态混为一体。
2. `_active_records()` 仍是 legacy recent 列表；`_diagnose()` 消费它。WP-07 才负责诊断模型全面改写，因此 WP-06 只能提供兼容桥，不能提前实施规范化诊断。
3. `_managed_action_required_records()` 只遍历 `tasks.values()` 的 current attempt，不能发现 `prior_attempts` 中运行、待对账、待中断或待验收的 attempt。
4. `_stop_blocking_records()` 直接拼接 recent legacy 与全部 managed action-required，使 complete pending、blocked、failed、needs-decision、恢复授权/耗尽和结果纠正耗尽等“允许当前回复向用户报告”的状态也可能机械阻止 Stop。
5. `_handle_stop()` 只读一次 StateStore，读取失败时 fail-open；不满足首次读取加两次短重试、三次失败后即时阻止和要求用户决策的裁决。
6. `_handle_session_start()` 只调用 prepared/pending reconcile 后生成混合摘要；没有 tombstone/result 精确清理，没有 action-required 优先和 recent-activity 次级展示，也不能显示 prior attempt。
7. `_handle_session_end()` 只 reconcile prepared dispatch，使用旧 preserved 列表决定删除；没有 pending lifecycle reconcile、有效 tombstone 保留、精确 result 清理和多 attempt 未闭环判断。
8. `StateStore.cleanup_expired_tombstones()` 已提供正确的锁内顺序：先调用精确 result cleanup，回调全部成功后才删除 tombstone 并原子写回；回调失败会保留 tombstone。WP-06 应复用而不是新建清理器。
9. `result_file_path()` 与 `_read_result_path()` 已能按 `task_id + attempt` 计算并机械核对正式结果；当前没有“只在文件存在时精确删除”的回调。
10. `apply_parent_disposition(select_attempt)` 已把未选 attempt 标记为 `duplicate_not_selected` 并写选择关闭意图，非运行未选 attempt 立即关闭，运行未选 attempt 返回精确 `interrupt_targets`；WP-06 不重写这些事实。
11. `_apply_action_observation()` 的 interrupt success 目前只写 `interrupted + decide_disposition`；未识别选择关闭意图，因此不会关闭精确未选 attempt、生成 tombstone、清 Agent/lifecycle 映射或解除 selected attempt 的 duplicate。
12. interrupt unknown 后的 `list_agents` 已有 running/error/stopped 基础对账，但 stopped 分支同样缺少 select 后关闭与 duplicate 最终收口。

### 2.2 修改前失败基线设计

先新增 `tests/test_wait_recovery_session_closure.py`，在运行时代码修改前执行并确认稳定失败。失败点至少覆盖：

- action-required 遍历 current 与 prior attempts，且不受 12 小时过滤；recent-activity 独立受 12 小时限制。
- complete pending/blocked/failed 等保留在 action-required，但不阻止 Stop；running、spawn/claimed 对账、身份未确认和可恢复平台错误仍阻止。
- Stop 首次读取失败后重试，总共最多三次；三次失败不再 fail-open。
- SessionStart 先 reconcile/cleanup，再按 action-required 优先、recent-activity 次级生成有界摘要，并在读取失败时明确 degraded。
- SessionEnd 在 action-required 或有效 tombstone 存在时保留 JSON；全部清空后只删除 JSON，不删除稳定 `.lock`。
- 到期 tombstone 只删除精确匹配的正式结果；result 删除失败时 tombstone 保留。
- select 后 interrupt success/stopped observation 关闭精确未选 attempt、清映射并最终解除 duplicate；failed/unknown 不伪造关闭。

实际失败基线：新增首批 13 项定向测试后，在修改运行时代码前执行：

```text
python3 -m unittest tests.test_wait_recovery_session_closure -v
  Ran 13 tests
  FAILED (failures=3, errors=10)
```

10 个 error 分别证明 `_action_required_records()`/`_recent_activity_records()` 尚不存在、Stop 不接受可注入短重试、SessionStart 不执行 tombstone/result 清理、select 后 interrupt success/stopped observation 不关闭未选 attempt；3 个 failure 证明 complete pending 被旧 Stop 错误阻止、到期结果未清理、interrupt failed 未进入明确父决策。失败均落在 WP-06 已确认缺口，没有暴露测试装配或 WP-01～WP-05 稳定接口冲突。

## 三、允许与禁止范围

### 3.1 允许修改

- `scripts/subagent_governance.py` 中 WP-06 派生视图、Stop/Session handlers、精确结果清理辅助和 select/interrupt 闭环。
- `tests/test_wait_recovery_session_closure.py` 及直接受新权威语义影响的既有测试。
- `skills/subagent-governance/SKILL.md` 与 `skills/subagent-governance/references/runtime-boundaries.md` 中 20 分钟等待、恢复、Stop/Session、select 后处置和 tombstone 边界。
- `schemas/governance-semantics.schema.json` 仅在现有机器语义缺少 WP-06 可确定锚点时做最小补充；不重新解释 WP-01～WP-05 字段。
- 本方案文档。

### 3.2 明确禁止

- 不调用或实现自动 `wait_agent/list_agents/followup_task/interrupt_agent`，不建设 Hook 定时器、后台线程、scheduler 或主线程唤醒器。
- 不读取代码、Git、日志或测试状态猜测子 Agent 进度；不从 mailbox、summary、自然语言或工具错误文本生成业务结果。
- 不覆盖或建立第二份正式 result，不修改 WP-05 的唯一结果语义。
- 不新增 `close_attempt` action，不自动选择、自动接受结果、自动恢复或自动中断 Agent。
- 不实施 WP-07 的规范化诊断/group；不实施 WP-08 的全面 legacy 退役、README/发布总收口、安装或真实平台验收。
- 不修改第三方 Skill、稳定发布源、Marketplace、运行缓存、Hook trust 或 Registry；不 stage、commit、push、发布或安装。
- 不重置、恢复、清理或格式化用户已有工作树修改。

## 四、旧消费者盘点与替换顺序

### 4.1 当前消费者

- `_recent_records()`：被 `_active_records()`、`_stop_blocking_records()` 和 `_session_restore_records()` 间接或直接消费。
- `_active_records()`：被 `_diagnose()` 用于 legacy `active` 计数。
- `_managed_action_required_records()`：被 Stop、SessionStart、SessionEnd 旧桥消费。
- `_stop_blocking_records()`：只由 `_handle_stop()` 消费。
- `_session_restore_records()`：只由 `_handle_session_start()` 消费。
- `_session_end_preserved_records()`：由 `_handle_session_end()` 及部分 legacy 诊断/测试直接消费。

### 4.2 原子替换顺序

1. 先建立统一 attempt 投影视图，复用 `_iter_task_attempts()` 遍历 current 与 prior attempts，并给每个投影保留 `task_id`、`attempt`、是否 current 和原 record 引用。
2. 新增 `_recent_activity_records()` 与 `_action_required_records()`；先让新测试直接验证二者，不改 handler。
3. 把 `_stop_blocking_records()` 改为独立机械阻断谓词，不再等同 action-required。
4. 把 SessionStart/End 切到新派生视图和 tombstone 生命周期。
5. 保留 `_active_records()` 与 `_session_end_preserved_records()` 作为 WP-07/WP-08 兼容桥，但让其从新视图派生，避免继续维护旧权威列表。
6. 最后删除不再有消费者的 `_recent_records()`/旧 managed action-required 实现；如 legacy 测试仍直接依赖函数名，则保留薄包装但不保留旧算法。

此顺序避免先删除 legacy 保护后没有消费者，也避免让 recent 12 小时窗口继续影响 managed 权威状态。

## 五、attempt 投影、recent_activity 与 action_required

### 5.1 attempt 投影

新视图复用 `_iter_task_attempts(state)`，每个 current/prior attempt 单独产生一个有界机械条目。条目至少包含：

- `task_id`、`attempt`、`current`。
- 原 attempt record 的机械状态字段与 `parent_action`。
- 精确 target：优先 canonical path，其次 agent ID；没有则为 null/unmapped 展示值。
- activity timestamp：按 `updated_at`、`platform_checked_at`、`spawn_post_observed_at`、生命周期观察时间等既有 `_activity_timestamp()` 规则取最大有效整数；无效时间不成为 action-required 排除条件。

不得按 task name、同轮、最新 attempt 或唯一候选猜测 attempt。

### 5.2 recent_activity 精确算法

`_recent_activity_records(state, now=None)`：

1. 遍历 managed current/prior attempts；legacy 顶层记录通过显式兼容分支投影，不混入 managed 多维判定。
2. 只保留 activity timestamp 大于等于 `now - retention.recent_activity` 的条目。
3. 按 activity timestamp 降序、task ID、attempt 确定性排序。
4. 可标记条目是否 stale，但窗口只控制展示；绝不关闭、删除、隐藏 action-required 或改变 parent action。
5. `_active_records()` 暂时返回 recent activity 中符合 legacy ACTIVE_STATUSES 的记录，供 WP-07 前的诊断计数兼容使用；该值明确不是权威未解决任务数。

### 5.3 action_required 精确算法

`_action_required_records(state)` 不接受 12 小时窗口，并对所有 attempt 应用稳定主规则：

1. record 是 managed 且尚未明确关闭；关闭事实以 `closed_at`/tombstone 对应精确 attempt 为准。
2. 以下任一成立即进入：
   - `parent_action != null`；
   - `execution_status=running`；
   - spawn 已认领/消费但仍缺少 PostToolUse 观察；
   - `pending_action.phase=prepared|claimed`；
   - `identity_status=unconfirmed` 且 `spawn_observation=success|unknown`；
   - 其他现有权威调用事实明确仍进行中，例如 claimed lifecycle 或 unknown interrupt/list reconciliation。
3. legacy 记录通过独立兼容判定保留 U-05～U-09 所需的 running、pending、dispatched、retry-required、platform-error、protocol-error/decision 状态，但不得覆盖 managed 多维状态。
4. 结果自然覆盖 `retry_spawn/reconcile/recover/correct_result/business_resume/accept_result/ask_user/manual_review/resolve_duplicate/decide_disposition`，以及 platform error、恢复/纠正耗尽、result unavailable/conflict、blocked/failed/needs-decision、complete pending、未关闭 interrupted、duplicate-not-selected。
5. 附加状态枚举只用于不变量测试和 legacy bridge，不作为 managed action-required 唯一权威来源。
6. 按处置优先级、activity timestamp 降序、task ID、attempt 确定性排序；stale 条目永远保留到显式处置。

### 5.4 关闭判断与多 attempt

- 每个 attempt 独立判断；current 没有 action 不代表 prior 已闭环。
- tombstone 只表示对应 `task_id + attempt` 已明确关闭，不得让一个 attempt 的 tombstone 隐藏其他 attempt。
- task 的 action-required 是其全部 attempt 条目的并集；Session 保留与 duplicate 解除也使用同一全集。

## 六、5分钟 prepared 与20分钟 claimed reconcile

### 6.1 复用既有函数

SessionStart/SessionEnd 在读取派生视图前依次调用：

1. `reconcile_prepared_dispatches(session_id, state_store, PreparedContractStore, now)`：
   - 未认领 prepared 超过 5 分钟时精确清除初始 attempt 和 PreparedContract；
   - 已消费/claimed spawn 超过 20 分钟且无 PostToolUse 时转 `spawn_observation=unknown + parent_action=reconcile`。
2. `reconcile_pending_actions(session_id, state_store, now)`：
   - `pending_action.phase=prepared` 超过 5 分钟时释放；
   - `phase=claimed` 超过 20 分钟时按 operation type 写 unknown 对账事实。

不复制计时逻辑，不在读取函数内重写状态机，不建设定时器。普通 `StateStore.read()` 本身保持只读；“读取路径 reconcile”具体落在 SessionStart/End 等显式生命周期入口和现有 CLI/恢复调用路径。

### 6.2 失败边界

- reconcile 任一步失败时 SessionStart 返回 degraded，不能继续输出“没有任务”。
- SessionEnd reconcile 失败时保留 Session JSON并返回明确清理失败；不能在事实未知时删除。
- unknown 只由既有 20 分钟边界或显式工具观察产生，不能自动改成 failed/complete/interrupted/closed。

## 七、Stop 三次读取与机械结束保护

### 7.1 读取实现

新增可测试的 `_read_state_for_stop(store, session_id, attempts=3, retry_delay=..., sleeper=...)` 或等价辅助：

1. 同一次 Stop 首次立即读取。
2. 仅捕获 StateStore/OSError/RuntimeError 类瞬时读取错误，进行两次短重试；总读取次数最多 3。
3. 任一次成功立即返回真实状态，不再继续重试。
4. 短间隔使用可注入 sleeper；单元测试传入 no-op，运行时只使用短毫秒级等待，不得长 sleep。
5. 三次均失败时返回聚合但有界的最后错误上下文；不尝试依赖不可用 StateStore 写 needs-decision。

### 7.2 block 条件

Stop 机械阻止仅覆盖若直接结束可能丢失权威运行/调用事实的条目：

- managed `execution_status=running`。
- spawn tool 已 claim/消费但仍无 PostToolUse，或身份未确认且 spawn success/unknown。
- lifecycle `pending_action.phase=claimed`；prepared 若已过期应由显式 reconcile 收缩，未过期 prepared 仍防止绕过已准备调用。
- 明确 spawn failed 且仍为 `retry_spawn`/恢复链要求处理。
- 明确 `platform_observation=error` 且仍处于可执行 recover/reconcile 状态。
- interrupt unknown 等必须先 list-agents 对账的调用状态。
- legacy 只保留等价的 running/pending/dispatched/retry-required/platform-error 核心保护，不让 legacy 混合状态覆盖 managed 事实。

### 7.3 allow 条件

以下状态仍在 action-required，但允许本次父回复结束，以便报告、验收或请求用户决策：

- complete pending/accept-result、blocked、failed、business needs-decision。
- recovery awaiting-authorization 或 exhausted、spawn/recovery/correction 已耗尽。
- result needs-correction/exhausted、storage unavailable、result conflict/manual review。
- 已停止或已中断且只待父处置、duplicate-not-selected 的 failed interrupt 需要用户/父决定。

允许 Stop 不关闭、不删除这些任务，也不清 parent action。

### 7.4 三次失败与 Stop hook recursion

- 三次读取失败返回 `decision=block`，reason 明确“无法确认是否仍有运行或调用对账任务，需要用户决定强制结束，或先诊断/修复/恢复状态”。
- 若 `stop_hook_active=true`，不再次返回 block，避免机械无限触发；返回 continue + 同一即时决策提示。用户仍需显式选择后续动作。
- Stop 只保护机械生命周期，不代替父 Agent验收业务结果。

## 八、SessionStart 恢复摘要

### 8.1 顺序

对 `startup|resume|clear|compact` 统一：

1. prepared dispatch reconcile。
2. pending lifecycle reconcile。
3. 调用 `cleanup_expired_tombstones()`，传入 WP-05 精确 result cleanup 回调。
4. 读取 StateStore。
5. 派生 action-required 与 recent-activity。
6. 生成有界恢复摘要；不调用任何 Agent 工具，不自动恢复/验收/选择/中断。

### 8.2 摘要排序与字段

- 第一段“需要处理”：action-required 全量候选，按 parent-action/机械风险优先级、时间、task/attempt 排序。
- 第二段“最近活动”：只显示不在第一段且最近 12 小时的条目。
- 每项至少显示 task ID、attempt、精确 Agent target（如有）、目标摘要、机械状态组合和 `parent_action`。
- 目标摘要优先 `contract_summary.objective`；legacy 使用已有限的 objective/task-name。
- 对 `result_storage_status=available` 的条目，可通过 `read_task_result()` 精确读取并仅展示 `business_result`、有界 result 摘要或 decision question 等少量关键字段；读取失败显示 result degraded，不把完整 result/evidence/remaining 写回 StateStore或摘要。
- 摘要受 `SESSION_SUMMARY_RECORD_LIMIT` 与 `SESSION_SUMMARY_CONTEXT_LIMIT` 双边界，分别报告“需要处理未展开数”和“最近活动未展开数”。截断不得删除 footer。
- footer 明确提醒：compact/resume 后不要重复创建已有 Agent；按精确 target 等待、对账或恢复。

### 8.3 degraded

- StateStore/reconcile/cleanup/result 关键读取失败时明确 `degraded` 与失败阶段。
- StateStore 不可读时绝不返回空摘要或“没有任务”；使用 `systemMessage`/SessionStart additional context 提醒无法确认任务，需要先诊断/恢复状态。
- 单个 result 关键字段读取失败不应隐藏 attempt；条目仍显示机械状态并标 result unavailable/degraded。

## 九、SessionEnd 保留与安全删除

### 9.1 保留条件

同一 Session 在任一条件成立时保留 JSON：

- action-required 非空，不受 12 小时过滤。
- 存在运行、spawn/lifecycle/interrupt 调用对账事实。
- 存在未闭环的多 attempt/duplicate/select 状态。
- tombstones 中存在仍在 7 天保留期的记录，或到期 tombstone 因 result cleanup 失败而保留。

主会话结束不等于子任务解决，不创建 archive/archived，不按时长自动关闭 unresolved 任务。

### 9.2 删除顺序

1. 与 SessionStart 相同地先执行 prepared/pending reconcile。
2. 在稳定 Session 锁内执行到期 tombstone + result 精确清理。
3. 使用 `StateStore.delete_if()` 在同一稳定锁边界重新读取并检查：action-required 为空且 tombstones 为空。
4. 条件满足才删除 Session JSON；稳定 `.lock` 永远不删。

如 cleanup、读取或 predicate 失败，保留 JSON 并返回明确错误。不得先根据锁外快照判断再删除。

## 十、tombstone 与正式结果精确清理

### 10.1 精确 result cleanup 回调

新增 `_cleanup_task_result_file(results_root, task_id, attempt)` 或等价函数：

1. 用 `result_file_path(results_root, task_id, attempt)` 计算唯一地址。
2. 文件不存在视为已经无结果可清理，幂等成功。
3. 文件存在时调用 `_read_result_path(path, task_id, attempt)`，重新核对普通文件、所有者/权限/大小/UTF-8/Schema、文件内 task/attempt 和 canonical 摘要。
4. 核对成功后只 unlink 该精确文件，并 fsync results 目录；不 glob、不按年龄/数量/12小时窗口删除。
5. 核对或删除失败抛出有定位但不敏感的错误。

### 10.2 事务与失败恢复

- `cleanup_expired_tombstones()` 已在 Session 锁内先执行所有 result callbacks，再删除 tombstone，再原子写回；WP-06 直接复用该顺序。
- 任一 result 删除失败时 callback 抛错，StateStore 写入不发生，所有本轮 tombstone 均保留以便重试。
- 已经成功删除的前序 result 若后续 callback 失败，下一轮不存在文件视为幂等成功，仍可安全完成；不会出现 tombstone 已删除但结果未处理。
- 只清理 `closed_at <= now - 604800` 的明确关闭 attempt；不影响其他 attempt、unresolved/stale task、PreparedContract 或稳定 `.lock`。
- 正常 StateStore 写入路径的“顺带清理”以 SessionStart、SessionEnd 和本阶段实际关闭 attempt 的处置路径为最小范围，不在每次只读或每个 Hook 上扫描。

## 十一、select_attempt 后的运行处置与 duplicate 收口

### 11.1 权威事实复用

- `apply_parent_disposition(select_attempt)` 保存的 `duplicate_not_selected`、选择关闭意图、selected current、prior attempts 和 `interrupt_targets` 是唯一选择事实。
- 父 Agent必须对每个返回 target 显式执行 `prepare_interrupt` 并调用原生 `interrupt_agent`；Hook/运行时不得代调。

### 11.2 interrupt success

在 `_apply_action_observation()` 的精确 attempt 锁内分支中：

1. 若 attempt 已有 `duplicate_not_selected=true` 和选择关闭意图，则把该精确 attempt 写为 interrupted，随后复用 `_close_attempt_record()` 关闭并生成 tombstone。
2. 清理指向该 `task_id + attempt` 的 Agent ID/canonical path 映射、`pending_action`、匹配的 interrupt/lifecycle 临时事实；保留 result reference 和正式 result 文件到 tombstone 到期。
3. 不关闭 selected/current attempt，不修改其结果。
4. 在同一事务重新扫描 task 全部 attempts；只有所有未选 attempt 均已可靠关闭，才清 selected 的 `duplicate_execution`/resolve-duplicate 状态。
5. 使用 `_restore_selected_parent_action(selected)` 根据 selected 自身状态恢复下一步，例如 complete pending → `accept_result`、running → `wait`、result conflict → `manual_review`。

### 11.3 interrupt failed

- 保持未选 attempt 未关闭和 `duplicate_not_selected`/选择关闭意图。
- 不自动重试 interrupt，不清 duplicate。
- 写精确 parent action/摘要，要求父 Agent或用户决定再次尝试、对账或其他显式处置。

### 11.4 interrupt unknown 与 list_agents 对账

- unknown 保持 attempt 未关闭、保留原 execution 状态与 duplicate，写 `parent_action=reconcile`。
- 后续 `list_agents`：
  - running：保持运行和 duplicate，继续要求显式中断/等待；不能倒推 interrupt failed/success。
  - error：进入 WP-04 平台错误/恢复链，仍不关闭 duplicate attempt。
  - stopped/interrupted 的明确观察：按与 interrupt success 相同的选择关闭事务收口，但只把平台明确 stopped 作为执行已停止事实，不伪造工具 success。
- list_agents 失败或状态含糊时保持 unknown/reconcile，继续等待，不能重建或关闭。

### 11.5 原子不变量

- duplicate 清除、未选 attempt 关闭、tombstone、Agent映射清理和 selected parent action 恢复必须在同一 StateStore update/CAS 中完成。
- 任一持久化失败不得留下“duplicate 已清但未选 attempt 仍活跃”的半状态。
- 成功中断/明确 stopped 后迟到 SubagentStart 不能复活已关闭未选 attempt；精确映射已清理，terminal/closed 检查继续拒绝重绑定。
- unknown 后替代执行只能新 attempt；旧 attempt 不改写成 failed。

## 十二、父 Agent 20分钟等待运行契约

开发 `skills/subagent-governance/SKILL.md` 与 `references/runtime-boundaries.md` 规范化为同一流程：

1. 派发后保存目标 Agent ID 与 canonical path，以 `timeout_ms=1200000` 调用 `wait_agent`。
2. 正常 mailbox update、终态通知或用户输入会提前唤醒；立即按新证据继续。
3. mailbox 明确报告 `stream disconnected`、`errored` 或平台执行失败时，立即对该目标范围调用 `list_agents`，不等待20分钟。
4. 只有正常等待满20分钟超时才做一次目标范围 `list_agents`；使用 canonical path 的 `path_prefix`（平台支持时），不扫描无关 Agent。
5. 若仍明确 running，静默再次 `wait_agent(timeout_ms=1200000)`；不输出进度、不读代码/Git/日志/测试、不发心跳或追问。
6. timeout、沉默、测试耗时、上下文压缩不是异常证据。`list_agents` 失败或状态含糊时不打断、不重建，继续等待并在下一轮重查。
7. 只有明确 errored 才进入 WP-04 platform recovery。同 task 普通 platform-error 自动恢复一次；再次平台错误进入用户授权/needs-decision，授权后第二次也是最后一次；不无限恢复。
8. 不按错误文本建立 provider 解密/解码特殊生命周期；所有文本只作为有界 platform-error 说明，生命周期由显式平台状态决定。
9. Hook 无定时器，不自动调用任何 Agent 工具；“主线程沉睡后检查唤醒”仅是 Skill 行为规则。

`assets/agents-governance.md` 保持按需加载的最小入口，不复制整套等待协议；只有现有入口与新 Skill 术语不一致时做最小修正。

## 十三、新旧路径切换与 legacy 兼容桥

- managed current/prior attempt 全部切到 `_action_required_records()` 与 `_recent_activity_records()`。
- legacy `_recent_records()` 可保留薄包装供旧测试/诊断，但只表达 recent activity；不得再决定 Session 删除或 managed Stop。
- `_active_records()` 在 WP-07 前继续给 `_diagnose()` 输出 recent legacy-compatible active count，并明确它不是 action-required。
- `_session_end_preserved_records()` 保留函数名供测试/调用兼容，但内部返回 action-required attempt 加有效 tombstone/未闭环 task 的投影，不使用 12 小时窗口。
- managed 与 legacy Stop 判定分开；legacy status 不覆盖 managed 多维字段，managed 也不从 legacy `status/result_document` 推断业务结果。
- WP-08 才删除无消费者的 legacy status、旧 summary/diagnose bridge 和兼容 fixture；WP-06 不提前退役。

## 十四、测试与验证计划

### 14.1 定向测试

新增 `tests/test_wait_recovery_session_closure.py`，至少覆盖：

1. current/prior attempt 的 action-required 与 stale 保留。
2. recent-activity 12 小时边界、排序和不影响权威状态。
3. action-required 主规则和调用进行中附加事实。
4. Stop block/allow 状态矩阵、三次读取、注入 sleeper、stop-hook-active 防循环。
5. prepared 5 分钟与 claimed 20 分钟在 SessionStart/End 复用既有 reconcile。
6. SessionStart 两段排序、字段、target、attempt、omitted、context limit 和 degraded。
7. SessionEnd action-required/tombstone 保留、空 Session JSON 删除、`.lock` 保留。
8. tombstone 精确 result 删除、不误删其他 attempt、校验失败/删除失败保留 tombstone。
9. select 后 interrupt success/failed/unknown 与 list-agents running/error/stopped。
10. duplicate 全部解除后 selected parent action 恢复，以及持久化失败不产生半闭环。

必要时调整 `tests/test_governance.py` 中与旧 Stop/Session 语义直接冲突的断言，但不削弱 legacy 分流测试。

### 14.2 全量验证

至少执行并记录：

```text
python3 -m unittest tests.test_wait_recovery_session_closure -v
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
python3 $HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 $HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
git diff --check
```

另执行确定性脚本检查：

- `schemas/governance-semantics.schema.json`、`task-contract-v1.schema.json`、`task-result-v1.schema.json` 均为合法 JSON。
- 相对 `$ref` 与 JSON Pointer 可解析。
- Schema regex 可编译，WP-06 retention/parent-action/状态锚点与运行时一致。
- Hook fixture、相关 WP-03～WP-05 fixture 不因新 Session/Stop 语义失真。
- 开发 Skill、runtime-boundaries 与 asset 最小入口术语一致，不修改安装缓存。

### 14.3 not_checked

以下真实平台行为无法由本地测试证明，最终必须标记 `not_checked`：

- 真实 `wait_agent(timeout_ms=1200000)` 的超时、提前 mailbox 唤醒和用户输入唤醒。
- 真实 `list_agents` canonical path 目标范围、平台 running/errored/stopped 形状与 stream disconnected 展示。
- 真实 `followup_task` 同 Agent恢复、`interrupt_agent` success/failed/unknown 与迟到事件顺序。
- 真实 compact/resume/clear/startup 的 Hook 调用时序和 SessionStart 上下文展示。
- 真实 SessionEnd、Stop hook recursion、Hook trust 与 Provider 断流行为。
- 真实平台是否向 SubagentStop 传递 WP-05 `task_result`。

## 十五、风险、回滚与失败处理

- 风险最高的是 Stop 误阻断、Session JSON 误删、duplicate 半清和 result/tombstone 半清。所有这些转换必须基于锁内精确 attempt，并用单元测试注入写入/删除失败。
- 任何读取不确定性都不解释为空状态；任何 unknown 都不改写成明确失败/停止/关闭。
- result 清理只复用 WP-05 安全读取并删除精确地址；发现引用/文件不一致即保留 tombstone并报告，不尝试扫描修复。
- 如果实现中发现主盘点与 WP-01～WP-05 稳定字段存在无法兼容的实质冲突，停止实施并在阶段终态标记“需要决策”，分别说明两边作用；不得静默修改权威裁决。
- 本阶段不通过 Git reset/checkout/restore 回滚；如测试暴露问题，只用最小 `apply_patch` 修正本阶段文件。

## 十六、退出条件与 WP-07/WP-08 交接

WP-06 只有同时满足以下条件才可退出：

1. 方案、失败基线、实现和验证证据全部回填。
2. action-required/recent-activity 已独立且覆盖 current/prior attempts。
3. Stop 三读与 block/allow 矩阵通过测试；StateStore 三读失败不再 fail-open。
4. SessionStart/End 完成 reconcile、恢复摘要、tombstone/result 精确清理和安全删除。
5. select 后未选运行 attempt 的 success/failed/unknown 与 list 后续对账闭环，duplicate 仅在全部可靠关闭后清除。
6. Skill 20 分钟等待规则与运行边界一致，Hook 没有自动工具调用。
7. 定向、全量、编译、Plugin/Skill validator、Schema/fixture/语义锚点和 diff check 全部通过；未验证真实平台行为明确列入 not_checked。

WP-07 接收的稳定接口应包括：

- current/prior attempt 的 `_action_required_records()` 与 `_recent_activity_records()` 派生视图。
- 精确 attempt 投影、机械状态/target/activity 字段和 Session degraded 事实，供规范化诊断使用。
- `_active_records()`/`_session_end_preserved_records()` 的临时 legacy bridge 及其非权威边界。
- result/tombstone 精确清理与 duplicate/select 闭环状态，避免 WP-07 诊断再次推断。

WP-08 接收 legacy consumers 清单、保留理由和可删除条件；本阶段不执行全面退役或发布。

## 十七、实施结果与交接（实施后回填）

### 17.1 实际修改

已完成，且未发现主盘点与 WP-01～WP-05 稳定接口之间需要用户裁决的实质冲突。

1. `scripts/subagent_governance.py`
   - 新增 current/prior attempt 统一投影、`_action_required_records()` 与 `_recent_activity_records()`；action-required 不使用12小时过滤，recent-activity 只用于展示。
   - legacy `_recent_records()`、`_active_records()`、`_managed_action_required_records()`、`_session_end_preserved_records()` 保留为薄兼容桥，managed 权威判断不再依赖旧12小时列表。
   - Stop 改为首次读取加两次短重试，使用机器语义 `stop_read_attempts=3`；任一次成功立即按真实状态判断，三次失败阻止本次 Stop并即时要求用户选择强制结束或诊断/恢复。complete pending、blocked/failed/needs-decision、恢复/结果耗尽等仍在 action-required 但不机械阻止当前回复。
   - SessionStart 复用 WP-03/WP-04 的5分钟 prepared 与20分钟 claimed reconcile，随后执行精确 tombstone/result 清理；摘要分“需要处理”和“最近活动”，显示 task/attempt、机械状态、parent action、目标和精确 target，保持记录数/上下文边界与 omitted 数，读取失败明确 degraded。
   - SessionEnd 同样先 reconcile 和精确清理，再在 `delete_if()` 锁内重新检查 action-required 与 tombstones；仅二者都为空时删除 Session JSON，稳定 `.lock` 保留。
   - 新增 `_cleanup_task_result_file()`：只使用 WP-05 确定性地址，先按文件内 task/attempt、Schema、canonical bytes 和权限重新核对，再精确删除并 fsync；文件不存在幂等，校验/删除失败由 `cleanup_expired_tombstones()` 保留 tombstone。
   - select 后的未选运行 attempt 在显式 interrupt success 时复用 `duplicate_not_selected` 事实关闭、生成 tombstone、清精确 Agent映射/lifecycle；failed 保持未关闭并 `ask_user`，unknown 保持未关闭并 `reconcile`；后续 list-agents 明确 stopped 执行同一关闭收口。
   - duplicate 只在全部其他 attempt 均已可靠关闭后清除；随后复用 `_restore_selected_parent_action()`，使所选 complete pending 回到 `accept_result`、running 回到 `wait`，不关闭或改写所选 attempt。
   - managed `SubagentStart` 增加 `attempt_closed` 机械保护，关闭 attempt 不因迟到启动复活。
2. `schemas/governance-semantics.schema.json`
   - 增加 `wait_timeout_ms=1200000`、`stop_read_attempts=3` 和 action-required/recent-activity 派生视图机器锚点；既有 retention、状态枚举和 WP-05 正式结果语义未改写。
3. `skills/subagent-governance/SKILL.md`
   - 规范化20分钟 wait、mailbox 明确平台错误立即目标 list、正常超时才巡检、running 静默继续等待、list 失败/含糊继续等待、明确 errored 才进入有限恢复。
   - 新增派生视图、Stop 三读、SessionStart/End、tombstone/result 精确清理和 select 后显式 interrupt 闭环规则；明确 Hook 无定时器且不自动调用 Agent 工具。
4. `skills/subagent-governance/references/runtime-boundaries.md`
   - 将 WP-06 从“待实现”边界切换为已落地运行边界，保留真实平台 not-checked 声明。
5. `tests/test_wait_recovery_session_closure.py`
   - 最终 18 项，覆盖多 attempt 派生视图、机器锚点、Stop block/allow/三读、5/20分钟 Session reconcile、两段摘要/degraded、SessionEnd/.lock、精确 result 清理、select 实际保存事实、显式 prepare-interrupt、三态与 list stopped 收口、Skill/边界一致性。

`assets/agents-governance.md` 未修改：其现有按需加载入口已满足“最小入口、不复制整套协议”的裁决。

### 17.2 失败基线与验证证据

失败基线：

```text
python3 -m unittest tests.test_wait_recovery_session_closure -v
  Ran 13 tests
  FAILED (failures=3, errors=10)
```

最终验证：

```text
python3 -m unittest tests.test_wait_recovery_session_closure -v
  Ran 18 tests in 0.035s
  OK

python3 -m unittest discover -s tests -v
  Ran 253 tests in 3.055s
  OK

python3 -m py_compile scripts/subagent_governance.py
  exit 0

python3 $HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
  Plugin validation passed

python3 $HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
  Skill is valid!

git diff --check
  exit 0
```

三 Schema、相对 `$ref`、JSON Pointer、正则、fixture 与 WP-06 锚点确定性检查：

```text
schemas=3 refs=35 patterns=10 fixtures=5 wp06_anchors=ok
```

该检查确认：三个 Schema 均为合法 JSON；35 个相对/内部引用和 JSON Pointer 可解析；10 个 pattern 可编译；5 个 Hook fixture 可解析；5/20分钟、12小时、7天、20分钟 wait、Stop 三读和派生视图锚点一致。

### 17.3 not_checked

- 真实 `wait_agent(timeout_ms=1200000)` 是否在20分钟超时、mailbox 更新、终态通知或用户输入时按预期唤醒。
- 真实 `list_agents` 是否稳定支持 canonical task path 目标范围，以及 running/errored/stopped、stream disconnected 的实际返回和 mailbox 展示形状。
- 真实 `followup_task` 同 Agent恢复、`interrupt_agent` success/failed/unknown、迟到 SubagentStart/PostToolUse/list-agents 的平台事件顺序。
- 真实 startup/resume/clear/compact 的 SessionStart Hook 时序、摘要注入与上下文压缩恢复展示。
- 真实 Stop hook recursion、SessionEnd 触发、Hook trust、Provider 断流和 Codex App终止行为。
- 真实平台是否在当前原生子 Agent 终态通知中稳定向父 Agent 提供完整 TaskResult 与精确 sender target；官方 `SubagentStop` 不承诺自定义 `task_result`，当前方案也不要求子 Agent 调用结果 CLI。

以上均未用本地 fixture 冒充通过。

### 17.4 退出结论

WP-06 退出条件已满足：两个派生视图独立并覆盖 current/prior attempts；Stop 三读和机械 block/allow 通过；SessionStart/End 完成 reconcile、恢复摘要、精确清理与安全删除；select 后显式 interrupt/list 对账可可靠关闭未选 attempt并最终解除 duplicate；Skill 与运行边界一致；全部本地验证通过。

本阶段未使用子 Agent、未创建新 Codex 任务、未自动调用 Agent 工具、未 stage/commit/push、未发布/安装，也未写稳定源、Marketplace、运行缓存、Hook trust 或 Registry。未开始 WP-07。

### 17.5 WP-07 交接

- 稳定派生视图：`_action_required_records(state)` 和 `_recent_activity_records(state, now=...)` 均返回按 attempt 投影的确定性有界机械记录；前者无时间过滤，后者只表示12小时展示。
- 多 attempt/target：投影含 `task_id`、`attempt`、`activity_at`，并保留机械状态、parent action、Agent ID/canonical path 与最小 contract summary；current attempt 直接由 `work_item.current_attempt` 判定，WP-07 不应重新扫描 current-only 或按 task name 猜测。
- Session/Stop degraded：StateStore/reconcile/cleanup 失败已产生明确即时 degraded 文案；WP-07 可读取和规范化这些可观察事实，但不得根据错误文字推断 delivery/execution/orchestration 根因。
- result/tombstone：`_cleanup_task_result_file()` 与 `StateStore.cleanup_expired_tombstones()` 形成精确 task/attempt 清理边界；WP-07 诊断只读，不得触发该清理或转储完整 result/evidence。
- duplicate/select：关闭事实、tombstone、Agent映射清理和 selected parent action 已是持久化权威；诊断只展示，不自动选择、中断或恢复。
- legacy bridge：`_recent_records()`、`_active_records()`、`_managed_action_required_records()`、`_session_end_preserved_records()` 暂留；其中 `_active_records()` 仍只为旧诊断 recent active count 服务，不是 action-required 权威。WP-07 应让新规范化诊断直接消费两个新视图，WP-08 再删除无消费者旧桥。
- 下一阶段边界：WP-07 仅实现无副作用规范化诊断和已裁决的轻量 group，不改写本阶段等待/Stop/Session/tombstone 状态机，不开始发布或 legacy 总退役。
