# D6 迁移、兼容与纵向切片

> 2026-08-14 状态：本文保留为前期迁移设计。涉及 SubagentStart 强身份、
> transcript route 或 SubagentStop 自定义结果字段的规则已被平台能力切片 1
> supersede；当前机器边界见 `schemas/codex-hook-events-v1.contract.json`。

## 1. 状态、范围与总裁决

- 工作项：D6「迁移、兼容和实施切片」。前置为 D1～D5；它把五份设计冻结为可逐片实施的迁移契约，不重新讨论产品方向。
- 本文唯一交付物是本文件。本文不修改运行时代码、三个 Schema、测试、Skill、稳定发布源、运行缓存、Hook trust、Marketplace、Registry、外部对话或其他项目。
- `docs/optimization-plan.md` 与 WP-01～WP-08 记录的是既有 attempt-first 本地实现及其验证历史；不能因为它们曾完成就把 D1～D5 的 work-item-first 语义视为已实现。本迁移以 D1～D5 为最终设计，以 WP 的函数、测试和安全措施为可复用输入。

**总裁决**：迁移采用「新语义先在同一 StateStore 锁内形成一个完整闭环，旧字段只作受控兼容投影；新消费者全部切换后再原子退役」的方式。禁止一次性重写 Hook、派发、结果、会话、诊断和 group，也禁止让旧/新两套字段同时作为权威。

最先要证明的不是完整平台恢复，而是以下最小本地闭环：

```text
创建 work_item/execution
  -> 提交合法 outcome
  -> complete 进入 pending acceptance
  -> 显式 disposition=accept_result
  -> 同锁关闭 + tombstone
```

这一闭环必须同时证明 `blocked|failed|needs_decision` 只结束 execution、不会隐式关闭 work item。平台响应、真实 Hook 投递和真实对话均不属于该闭环的本地证明。

## 2. D1～D5 的冲突清单与统一裁决

以下表格是编码前的唯一裁决；实施切片不得把其中任何一项重新留给函数作者决定。

| 编号 | 看似冲突 | 统一裁决 | 实施后可观察效果 |
| --- | --- | --- | --- |
| C1 | D1 称 `accept_result` 与关闭在同一原子处置；D3 文字又出现 `accepted` 后进入 close 路径；D5 允许显示 `accepted`。 | `accept_result` 是单一事务：只有 current complete 可读、无 conflict/duplicate 且所有其他 execution 可安全关闭时，才同时写 accepted、work-item close 和 tombstone。若存在 running 未选候选，操作失败并返回精确 interrupt targets，**不得**留下 accepted/open 中间态。D5 的 `accepted` 仅可出现在已记录 close/tombstone 的历史投影。 | 不能出现“accepted 但 work item open”。 |
| C2 | D2 的 transition 有 `authorized_by=mechanical_rule`，D4 说 business resume/replacement 只能经 disposition。 | `mechanical_rule` 只允许同 attempt 的 `confirmed_spawn_failure_retry`。所有 business resume、replacement 和 reviewer 派发均须先有父/用户显式 disposition；不得由计时、`parent_action`、诊断或 Hook 自动创建。 | 新 attempt 都可回指一条 disposition 或可靠 spawn failed。 |
| C3 | D2 允许 same-Agent business resume 新 `task_ref` 但保留 `origin_task_name`；D4 强调不能用旧 task name 身份绑定。 | `origin_task_name` 只是不变的 provenance/display 字段。新 execution 的唯一身份为新 `(task_id, attempt, task_ref)`；same-Agent resume 的启动授权只能用「已确认 target + claimed `business_resume` pending action/last lifecycle operation 中的新 task_ref」，绝不从 task name、时间或 current attempt 推断。 | 同一 Agent 可顺序承载 A1、A2；迟到事件不会靠名称写错 A2。 |
| C4 | D3 说合法 outcome 存储关联失败时 `business_result=null`；D1 说 outcome 是唯一业务结果。 | “合法候选 payload 已机械验证”与“可读取的权威 outcome”分开。写入/回读/关联任一失败时，StateStore 的权威 `business_result` 仍为 `null`，`result_protocol_status=valid`、`result_storage_status=unavailable`；只保留 digest/错误摘要。只有可回读并成功关联后才写 business result。 | 存储故障不是 business failed，也不会凭内存 payload 完成验收。 |
| C5 | D1/D3 说 duplicate 要 `select_attempt`；D5 对多个候选的顶层 availability 有 `conflict|none` 投影。 | `duplicate_execution` 是执行并存事实；`result_conflict` 是同一 attempt 两份不同 outcome 的事实，二者不能互换。任何 duplicate 未收口时禁止 `accept_result`/`review_result`，顶层只显示 `selection_pending`；每个 candidate 仍各自显示其 outcome availability。 | 不会因较新 attempt 或可读 complete 自动胜出。 |
| C6 | D2 说 business resume/replacement 不设固定次数；D1 的目标要求防止 Agent 无限制增加。 | 使用组合控制而非业务编排预算：见第 5 节。硬限制并发/未收口 candidate，resume/replacement 均须 growth authorization；只对累计新 attempt/replacement 提供软告警和原因审计，不设自动业务终止次数。 | 插件不会自行决定“任务最多重做 N 次”，但同一 work item 不会无限并行生 Agent。 |
| C7 | D2 把 `deliverable_contract` 描述为逻辑信封，D5 要冻结 diagnostics 形状；现有三个 Schema 未含二者。 | 不新增第四份 wire Schema 或协议版本门禁。`TaskContract` 仍是用户输入，`TaskResult` 仍是子 Agent outcome；`deliverable_contract`、transition、disposition、work-item record 和诊断快照作为 `governance-semantics` 的 `$defs`/`x-semantics` 逻辑 Schema，并由 Python validator/确定性测试消费。 | 新字段有单一机器语义来源，却不要求外部 payload 携带版本号。 |
| C8 | D4 的 `business_resume` 调用明确 failed 可关闭新未启动 attempt；D1 说只有 disposition 能关闭。 | 这是唯一的机械 execution close：已认领的 same-Agent resume 被可靠证实未投递、该新 execution 未启动且无 outcome 时，写 `attempt_close_reason=resume_delivery_failed`，但 work item 仍 open、`parent_action=decide_disposition`。work-item tombstone 仍只来自 disposition。 | delivery failed 不被伪造为业务 failed 或 task close。 |
| C9 | D5 说 allowed actions 可列 `resume_business`/`spawn_replacement`；D1/D4 说这些必须显式授权。 | diagnostics 只显示“此动作在已有 growth authorization/新契约齐备时可执行”，不能生成授权或 pending action。没有已持久化增长授权时只显示仍需父任务决定的 formal disposition/action facts。 | 诊断是只读建议，不能变成调度器。 |

## 3. 冻结的最终逻辑 Schema 与落点

### 3.1 四层对象和权威位置

| 对象 | 稳定身份 | 权威持久化位置 | 不进入的位置 |
| --- | --- | --- | --- |
| `work_item` | `task_id` | `StateStore.tasks[task_id].work_item` 与该 task 的 executions | Agent mapping、task name、结果文件名 |
| `execution` | `task_id + attempt`，其 transport ref 为 `task_ref` | `StateStore.tasks[task_id].executions["<attempt>"]` | 完整 prompt、平台原始响应 |
| `outcome` | outcome 内的 `task_id + attempt` | 确定性 result 文件；StateStore 只存 reference/digest/派生事实 | parent disposition、平台调用 observation |
| `disposition` | `task_id + attempt + action`，以同锁提交时间区分审计事实 | `work_item.last_parent_disposition` 与目标 execution 的 `parent_disposition_record` | TaskResult、子 Agent message、growth authorization |

顶层 `tasks` 继续以 `task_id` 为键，避免把数据迁入第二个数据库。它的**最终**逻辑形状为：

```text
tasks[task_id] = {
  managed: true,
  task_id,
  work_item: {
    objective_summary, lifecycle: open|tombstoned,
    current_attempt,
    created_at, updated_at,
    attempt_count, replacement_spawn_count,
    last_parent_disposition: ParentDispositionRecord | null,
    last_growth_authorization: GrowthAuthorization | null
  },
  executions: { "1": ExecutionRecord, "2": ExecutionRecord, ... }
}
```

`ExecutionRecord` 包含 D1 的十四个 attempt-state 字段、`task_ref`、`dispatch_kind`、`task_name`/`origin_task_name`、精确 identity、contract/deliverable digest 与摘要、transition、pending/last lifecycle、结果引用、close facts 和 timestamps。`attempt_count` 是事实统计，不能拿来自动拒绝业务继续。

为避免“十四个字段”在编码时再次产生歧义，最终 `ExecutionRecord` 的逻辑字段分组固定如下：

```text
identity: task_id, attempt, task_ref, task_name, origin_task_name,
          agent_id, canonical_task_path, identity_status
contract: task_contract_summary, deliverable_contract, contract_digest
dispatch: dispatch_kind, transition, spawn_observation, spawn_retry_count
execution: execution_status, platform_observation, recovery_status,
           recovery_count, pending_action, last_lifecycle_operation
outcome: business_result, result_protocol_status, result_storage_status,
         result_reference, result_sha256, result_stored_at,
         result_conflict, result_conflict_sha256, result_conflict_first_seen_at
review: acceptance_status, parent_action, parent_disposition_record,
        attempt_close_reason, attempt_closed, attempt_closed_at
facts: duplicate_execution, correction_count, created_at, updated_at,
       activity_at, platform_checked_at, start_observed_at
```

`growth_authorization` 是 execution/pending 上的显式增长授权；formal `parent_disposition_record` 是结果验收/关闭/选择事实。两者不得共用对象名或 action enum。`action_required` 从 canonical executions 只读派生，不再持久化在 work item。

其中 `null` 表示该事实尚未发生，`unknown` 只表示已发生但不可确认；`execution_status`、`spawn_observation`、`identity_status`、`platform_observation`、`business_result`、`acceptance_status`、`result_protocol_status`、`result_storage_status`、`recovery_status`、`parent_action` 和三类计数继续复用现有 machine semantics 的枚举/上限。`close_reason` 不是新的状态枚举，必须伴随显式 disposition 或唯一的 `resume_delivery_failed` execution-close 事实。

现有 root current attempt 和 `prior_attempts` 不是最终权威模型。迁移期它们是由 `executions + work_item.current_attempt` 在同一 CAS 内生成的**兼容投影**；任何尚未迁移的读取者只能读该投影，不能独立写它。这样既允许逐片替换旧消费者，也不允许双写漂移。

### 3.2 三份既有 Schema 的最终职责

| 文件 | 冻结后的职责 | 本次以后允许的变化 | 明确禁止 |
| --- | --- | --- | --- |
| `schemas/task-contract-v1.schema.json` | 一次 execution 的业务输入。 | 保持现有 TaskContract 字段；可通过 `$ref` 引用 machine semantics 的当前定义。 | 加入 `task_id`、attempt、disposition、平台结果或 protocol version；把交付物质量变成机器判断。 |
| `schemas/task-result-v1.schema.json` | 子 Agent提交的 outcome wire payload。 | 保持四种 `business_result` 与条件字段；继续允许未知额外字段。 | 写 acceptance/close、storage 状态、delivery 状态或第二份结果修订历史。 |
| `schemas/governance-semantics.schema.json` | 唯一机器语义锚点。 | 维护受控 canonical container/work-item/execution/transition/growth/disposition/operation/closure/identity 与只读 decision snapshot `$defs`；Python 字段集/枚举必须双向一致。 | 用 `version`/migration version 阻断旧记录，把 `result_unavailable` 变成 `business_result`，或让受控核心退化为任意 object。 |

最终的 `deliverable_contract` 由已验证的 TaskContract **确定性生成**，而非要求父 Agent再写一份同义输入：

```text
outcome_required=true
completion_condition_refs=[本 contract 的稳定索引]
evidence_requirement_refs=[本 contract 的稳定索引]
artifact_expectations=[{label, kind, location_hint, required}]
outcome_guidance={complete, blocked, failed, needs_decision}
review_required=true
```

它与 TaskContract 一起计算 `contract_digest`。索引以 0 起始并按原数组顺序解释；以后不得改成自然语言模糊匹配。`artifact_expectations.kind` 只允许 `document|source_change|command_output|decision|other`，只作报告提示，不授权扫描或验收外部资源。

### 3.3 disposition、诊断与 group 的固定边界

`parent_disposition_record` 固定为：

```json
{"task_id":"…","attempt":1,"action":"accept_result|reject_result|close_task|select_attempt","reason":"…","recorded_at":0}
```

`reason` 非空、长度继承已有 600 上限。没有“自动 close”“自动 accept”“retry” disposition。D5 的 `WorkItemDecisionSnapshot` 不是又一份持久状态：它是从上述对象纯读取派生的固定 diagnose JSON 合约，字段、排序和 `allowed_actions[].basis[]` 写进 governance semantics 的逻辑定义与 fixture 断言；不需要单独发布 Schema 文件。

`growth_authorization` 固定为 `{attempt, action: resume_business|spawn_replacement, reason, recorded_at}`（可附 `authorized_by`），分别写入 execution/pending 和 `work_item.last_growth_authorization`。它不是 formal disposition。F6 已按第 3.1～3.3 节实现可执行 Schema、runtime fixture validation 和旧名 compatibility-read/converge-on-write；详情见 `F6-canonical-record-schema-implementation.md`。

group 仍只保存 `{group_id, objective_summary, members[{task_id,required}], created_at, updated_at}`。它读取 work-item decision snapshots；没有 group disposition、group retry、reviewer 队列或 aggregate outcome。

## 4. same-Agent business resume 与 replacement 的身份契约

### 4.1 同一 Agent 的新 execution

业务继续不是原 attempt 的 follow-up，也不是 platform recovery。它只可在 blocked、failed、已解决的 needs_decision、rejected complete 或 `resume_delivery_failed` 后，先记录“继续”的 disposition，再创建 `attempt=N+1`。

新 execution 必须同时写入：

```text
identity.task_id             = 原 work item 的 task_id
identity.attempt             = N + 1
identity.task_ref            = hash(task_id + ":" + (N + 1)) 的唯一前缀
identity.dispatch_kind       = business_resume
identity.origin_attempt      = N
identity.origin_task_name    = origin execution 的初次 spawn task_name
identity.spawn_task_name     = null
identity.target              = 已确认的同一 Agent ID/canonical path
transition.from_attempt      = N
transition.reason_code       = blocker_resolved|decision_received|result_rejected|scope_or_conditions_changed
```

同一 CAS 中，在 **origin execution** 创建一个 claimed `pending_action`：

```text
operation_type=business_resume
target=<confirmed target>
task_id=<same>
attempt=N+1
task_ref=<new ref>
origin_attempt=N
origin_task_name=<immutable provenance>
resume_contract_digest=<new digest>
deliverable_contract_digest=<new digest>
phase=prepared|claimed
```

`followup_task` 调用只可消费此 pending action。success 令 A(N+1) 保持 `not_started + wait`；reliable failed 仅机械关闭 A(N+1) 为 `resume_delivery_failed`；unknown 令 A(N+1) 为 `not_started + reconcile`。精确 `SubagentStart` 只有通过这个 pending 或保存的同 target/same ref lifecycle record 才能将 A(N+1) 写为 running，并更新 target 的 active-attempt pointer。旧 A(N) 保留自己的 target/provenance/result，不把 `origin_task_name` 当作新 identity。

因此 Agent mapping 从单值暗示改为最小索引：`agents[target]={task_id, active_attempt, origin_task_name, canonical_task_path}`；每个 execution 自己保存 identity。mapping 只辅助当前 target 查找，永远不能按其值把无凭证迟到事件写入 execution。

### 4.2 replacement 是新的 native spawn

replacement 也递增 attempt，但固定不同点为：

```text
dispatch_kind=replacement_spawn
task_ref=<new>
task_name=sg_<resolved_mode>_<semantic_name>_t_<new ref>
identity.target=null（直到精确绑定）
transition.reason_code=unknown_duplicate_risk_accepted|agent_unavailable|
  user_requested_replacement|direction_invalid|identity_or_duplicate_conflict
transition.duplicate_risk_accepted=true（旧 execution 是 unknown/running 时必需）
```

它使用新的 PreparedContract 和新的 `spawn_agent`，绝不复用旧 Agent mapping、old task name、result path 或 business-resume pending action。迟到的 A(N) Start/outcome 仍按 A(N) 的 ref/payload 收口；A(N) 与 replacement 可能同时存在时写 `duplicate_execution=true`，仅 `select_attempt` 可以选择 current。

platform recovery 与 result correction 始终是同 Agent、同 attempt，不能创建上述 identity/transition；普通消息也不得创建 execution。

## 5. execution 增长控制裁决

插件不应决定业务“可以重试几次”，但必须阻止自身把一个 work item 膨胀成无限并发 Agent。最终采用以下组合：

1. **硬并发 candidate 预算**：一个 work item 最多有两个未关闭、可能仍执行业务的 candidates；正常情况下仅一个 current。第二个只允许是旧 unknown/running candidate 与一个已 growth authorization 授权的 replacement。存在两个未收口 candidates 时，拒绝第三个 spawn/replacement，也拒绝新的 business resume，返回 `resolve_duplicate`/`select_attempt`。这限制 live Agent 数量而不规定业务总尝试次数。
2. **硬身份串行性**：同一 confirmed target 同时最多一个 pending lifecycle action；same-Agent resume 未完成对账前不得再对该 target 创建 resume/recovery/correction。
3. **显式增长授权闸门**：每次 business resume 和 replacement 都须 reason-bearing `growth_authorization` 和合法 transition；formal disposition 仅用于 accept/reject/close/select。`parent_action`、elapsed time、diagnose action、结果建议和 reviewer 建议都不足以创建新的 execution。
4. **软告警而非硬业务预算**：从 attempt 4 起加入 `repeated_business_attempts` fact；第二次及以后 replacement spawn 加入 `repeated_replacements` fact。canonical output vocabulary 固定使用这两个名称；不再使用设计早期的单数 `repeated_replacement`。WorkItemDecisionSnapshot 从 canonical work item 投影累计次数和最近增长授权的有界 reason 摘要，diagnose/group member/SessionStart 共同消费该字段。它要求父 Agent在下一 disposition 中说明仍继续的理由，但不改变 action-required，不阻止 Stop/SessionEnd，也不自动拒绝、关闭或 spawn。
5. **reviewer 不派发增长**：reviewer 是父 Agent职责标签。插件从不为 review 自动 spawn Agent；如果父 Agent要委派审查，它必须创建一个独立 work item，并由父 Agent自行管理其关联，不把 reviewer Agent 记入被审任务的 execution candidates。

这一组合防止并发 Agent 无限制增长，同时允许用户明确要求的长业务恢复，不引入 DAG、batch、wave、队列、后台 scheduler 或“总重试次数”业务编排规则。

## 6. 兼容、迁移和原子退役

### 6.1 StateStore 与历史 records

迁移期 StateStore 的读写规则如下：

| 材料 | 兼容读取 | 新写入 | 原子退役条件 |
| --- | --- | --- | --- |
| 现有 `tasks[task_id]` root current + `prior_attempts` | 只读 adapter 生成 in-memory work-item/executions；字段缺失产出 issue/`indeterminate`，不默认 complete/closed。 | 首次修改该 task 时，同一 CAS 写 canonical `work_item + executions`，并生成旧 root/prior projection。 | 所有 Hook、CLI、Session/Stop、diagnose/group 都读取 canonical executions 后，删除 projection writer 和旧 reader。 |
| 现有 `agents` mapping | 只读为已知 target 事实；旧字符串或不精确 mapping 仅告警。 | 写最小 `{task_id,active_attempt,origin_task_name,canonical_task_path}` pointer；execution 保留自身 identity。 | 所有绑定都经 ref/pending/target 精确验证，删除旧映射形状兼容。 |
| `tombstones` | 读取既有最小 tombstone；不据此补业务结果。 | 使用 task/attempt/ref/target/last facts/close reason/time 的同一最小形状。 | 7 天精确清理与迟到拒绝均消费 canonical work item。 |
| `pending_action` / lifecycle | 现有字段作为 D4 兼容事实；缺失为 unresolved/issue。 | business resume 增加新 attempt/ref/origin binding，其他 operation 不改变 attempt。 | 所有 operation 写入 typed execution record，删除 root-only lookup。 |

不做批量离线重写，不把历史 JSON 标记为“旧版本”而拒绝读取，也不静默填充缺失字段。每个历史 task 在第一次需要写入时才在原锁内转换；纯 diagnose 永不转换、更不创建 lock。历史非-managed 记录继续是兼容/诊断事实，不能被提升为 governed work item。

### 6.2 PreparedContract、结果文件和 diagnose JSON

| 材料 | 迁移处理 |
| --- | --- |
| PreparedContract | initial/replacement spawn 继续短期保存完整 validated TaskContract、确定性 deliverable contract、digest、task ref/name 和 native args；确认 identity 后把摘要写入 execution 再删除。spawn unknown 保留至迟到绑定、可靠 failed retry、replacement 或 explicit close。same-Agent resume 不新建 spawn PreparedContract，而由 typed pending action 短期保存新契约/digest。 |
| result 文件 | 文件名与 canonical JSON/digest 规则不变；result payload 不加入 disposition。新 StateStore execution 只关联 reference/digest/time。旧孤儿文件只能通过精确 `(task_id,attempt)` reassociate，不扫描推断。不同内容继续只记 conflict digest。 |
| diagnose JSON | 顶层 `scan/health/issues/boundaries`、Session counts 在兼容期保留原含义，`work_items[].growth` 从 canonical work item 输出有界累计次数、软 facts 和最近增长授权摘要。candidate 上不存在第二份 growth authority。SessionStart 只消费同一 growth snapshot；Stop 继续直接使用权威 action-required 函数而非解析 JSON。 |
| group | group 输入保持不变；派生器读取 canonical work-item decision snapshot。不存在的/不完整 member 产生 issue 和 action-required，不能隐式关闭或创建 member；growth 只透传到 member，不产生 group 调度语义。 |

F4 收口后，canonical `work_item` 不再持久化 `action_required`；历史同名字段仅作为未知扩展兼容读取，纯 diagnose 不回写，下一次 canonical execution 同锁写入时移除。S6 已退役顶层 attempt-first 数组；当前 `work_items[].execution_candidates[].action_required`、`work_items[].action_required` 与 group 聚合统一来自 canonical candidate predicate，Stop/SessionEnd 直接调用同一派生链，不解析 diagnose JSON。

F5/F6 收口后，`work_item.attempt_count`、`replacement_spawn_count`、`repeated_business_attempts`、`repeated_replacements` 和单条 `last_growth_authorization` 是增长投影的唯一持久来源。`last_parent_disposition` 独立保存 formal outcome disposition；`last_growth_authorization` 只保留最近一次增长授权的 action/attempt/reason/recorded_at，不建立事件日志。旧记录缺失或带非法 reason 时，诊断输出 null + issue，不猜测正文或从 execution candidate 补造。

### 6.3 Hook 事件的迁移边界

| Hook/调用 | 新职责 | 成功 | failed | unknown |
| --- | --- | --- | --- |
| PreToolUse spawn | 认领 canonical execution 或 PreparedContract；初始/replacement 都先落盘。 | 只授权 native call。 | 前置验证失败时不调用。 | 不适用。 |
| PostToolUse spawn | 写 call observation，不写业务结果。 | 无身份时仍 `not_started/reconcile`。 | 仅确认未创建时允许同-attempt retry。 | 保留 ref，对账，禁止 retry。 |
| Pre/Post followup | 只消费 typed pending action。 | operation-specific，resume 新 execution 等 Start。 | recovery/correction 按预算；resume 只关闭未启动 execution。 | reconcile，不重发。 |
| SubagentStart | 用 exact ref 或 exact target + lifecycle 绑定 execution。 | 写 `running/confirmed`。 | 不适用。 | 无足够凭证则拒绝/记录未关联。 |
| SubagentStop / CLI submit | 只接受 TaskResult，按 D3 写文件再关联。 | 派生 complete pending 或其他 action-required。 | 无合法 outcome 走 correction/diagnostic，不编造 business failed。 | 平台观察未知不替代 outcome。 |
| SessionStart/End、Stop、list_agents、interrupt | 保留 D4/WP-06 的观察和保护边界，逐步改读 canonical execution。 | 只确认已观察事实。 | 不关闭 work item。 | reconcile，保留事实。 |

## 7. 最小纵向实施切片

所有切片遵守“先让新增测试失败，再做最小实现；成功、failed、unknown 都由持久化事实证明；真实平台一律单列 `not_checked`”。切片之间不合并发布/安装动作。

### S1：四层最小闭环（首个实施切片）

**目的**：在不改 Hook transport 的前提下，使新建记录能完成 work_item → execution → outcome → disposition 的本地闭环。

| 项目 | 规定 |
| --- | --- |
| 文件/函数范围 | `schemas/governance-semantics.schema.json`（逻辑 defs/字段锚点）；`scripts/subagent_governance.py` 的 `StateStore`、`_initial_task_record`、`_task_record_for_attempt`、`_iter_task_attempts`、`submit_task_result`、`apply_parent_disposition`、tombstone helpers；`tests/test_state_store.py`、`tests/test_formal_result_parent_closure.py`，新增最小 fixture。暂不改 hooks.json、Skill、诊断。 |
| 先行失败测试 | 新 record 写 canonical `work_item/executions`；complete 只能 pending；accept 同锁 close+tombstone；blocked/failed/needs_decision 留 open；同一结果重放幂等、不同结果 conflict；storage unavailable 保持 business_result null。 |
| 状态转换 | initial `open/A1`; TaskResult complete → `A1.stopped + valid/available + pending + accept_result`; accept → `accepted + task tombstoned`; blocked/failed → `stopped + decide_disposition`; needs_decision → `stopped + ask_user`; close_task 只在显式处置。 |
| success/failed/unknown | 本切片的 success 是 CAS+结果回读+状态回读成功；failed 是校验/CAS/文件错误并保持上次权威状态；unknown 不由本地 result API 生成，只保留已有 platform observation，不借此关闭。 |
| 退出条件 | 新记录无 root/prior 作为权威；至少上述四种 outcome 和 accept/close 可在纯本地测试重放；旧 attempt-first 测试仍通过兼容投影。 |
| 验证命令 | `python3 -m unittest -v tests.test_state_store tests.test_formal_result_parent_closure`; `python3 -m unittest discover -s tests -v`; `python3 -m py_compile scripts/subagent_governance.py`; Plugin validator；`git diff --check`。 |
| 真实平台 `not_checked` | SubagentStop 是否能送达结构化 payload；Hook 是否在目标插件版本加载。 |

### S2：契约、initial/replacement 派发与精确身份

**目的**：让新 execution 的 TaskContract/deliverable、ref、PreparedContract 与 Start 绑定全部进入 canonical execution，不改变 S1 outcome 语义。

| 项目 | 规定 |
| --- | --- |
| 文件/函数范围 | `governance-semantics` defs；`scripts/subagent_governance.py` 的 `TaskContract`/render helpers、`_prepared_record`、`_contract_summary`、`prepare_dispatch`、`prepare_spawn_retry`、`_handle_spawn`、`_handle_post_tool`、`_assign_starting_agent`、`_handle_subagent_start`、identity helpers；`tests/test_dispatch_identity.py`、`tests/test_hook_fixtures.py`。 |
| 先行失败测试 | deliverable refs/digest 确定性；initial/replacement 写 execution；spawn success 无 Start 不写 running；failed+未创建只同 attempt retry；unknown 保留 ref；迟到 Start 精确绑定旧 ref；新 replacement 不复用 old task name/result address。 |
| 状态转换 | Prepared → claimed → PostToolUse `success|failed|unknown`；Start 才 `running/confirmed`。replacement 为 new A(N+1)，旧 A(N) 不改写；出现并存可能性时标记 duplicate。 |
| success/failed/unknown | success 仅 call observation；failed 只有可靠未创建才 retry；unknown 进入 reconcile，禁止自动新 spawn。 |
| 退出条件 | 所有新 spawn/replacement 都有 canonical execution+digest；任何绑定均经 ref/精确 target；正文、名称相似和最新 attempt 无法绑定。 |
| 验证命令 | `python3 -m unittest -v tests.test_dispatch_identity tests.test_hook_fixtures`; 全量 unittest、py_compile、Plugin validator、`git diff --check`。 |
| 真实平台 `not_checked` | 原生 spawn 响应和 SubagentStart 实际携带 task name/ref/target 的形状；真实上下文参数映射。 |

### S3：same-Agent business resume、replacement 与增长护栏

**目的**：落地第 4、5 节的 identity 与 candidate 控制；这是唯一创建新 attempt 的业务继续入口。

| 项目 | 规定 |
| --- | --- |
| 文件/函数范围 | `scripts/subagent_governance.py` 的 `_business_resume_allowed`、`_prepare_managed_action`、`_pending_action_record`、`_create_resume_attempt`、`_claim_pending_action`、`_apply_action_observation`、`_bind_identity_target`、duplicate/select helpers；`tests/test_communication_lifecycle.py`、`tests/test_formal_result_parent_closure.py`、新 `tests/fixtures/work-item-resume-v1.json`。 |
| 先行失败测试 | resume 的新 ref/attempt/origin name/pending binding；同 target Start 只经 claimed resume 进入新 attempt；resume failed 只 close new A；unknown 不重发；replacement 要 growth authorization+risk acceptance；第三 live candidate 被拒绝；第四 attempt/第二 replacement 只出现 soft fact。 |
| 状态转换 | blocked/failed/rejected/已决 needs_decision → disposition continue → A(N+1) prepared; resume success → wait; failed → A(N+1) `resume_delivery_failed`, W open; unknown → reconcile; replacement → new spawn / potential duplicate。 |
| success/failed/unknown | 依 D4 的 native call 三值，均不填 business result；unknown 保留 pending/lifecycle 并禁止 retry。 |
| 退出条件 | same-Agent 与 new-Agent 两条路径不会共享 task_ref、result path 或身份规则；硬 candidate 限制与软告警有测试；插件从不派发 reviewer。 |
| 验证命令 | `python3 -m unittest -v tests.test_communication_lifecycle tests.test_formal_result_parent_closure`; 全量 unittest、py_compile、Plugin validator、`git diff --check`。 |
| 真实平台 `not_checked` | followup success/unknown 与 SubagentStart 的乱序、同一 target 跨 attempt 的真实可识别性。 |

### S4：平台观察、等待、重复收口与会话闭环

**目的**：将 D4 与现有 WP-06 的可靠观察迁到 canonical executions，不改变业务处置决定权。

| 项目 | 规定 |
| --- | --- |
| 文件/函数范围 | `scripts/subagent_governance.py` 的 `reconcile_prepared_dispatches`、`reconcile_pending_actions`、`reconcile_interrupted_attempt`、`reconcile_terminal_attempt`、list-agent handlers、`_action_required_records`、`_recent_activity_records`、`_handle_session_start`、`_handle_session_end`、`_handle_stop`、tombstone cleanup；`tests/test_communication_lifecycle.py`、`tests/test_wait_recovery_session_closure.py`、fixtures。 |
| 先行失败测试 | pending_init/空列表不覆盖 running；20 分钟 claimed 变 unknown；recovery/correction 两个独立预算；duplicate select 后 running 未选项只返回 interrupt target；interrupt failed/unknown 不 tombstone；SessionEnd 不丢 action-required。 |
| 状态转换 | D4 的 platform/execution/identity 三维矩阵原样写 canonical execution；all unselected candidates reliably closed 后才清 duplicate；仅 disposition 关闭 work item。 |
| success/failed/unknown | 每个 native operation 继续三值建模；unknown 永不变 terminal；failed 只按该 operation 的既定预算/显式处置推进。 |
| 退出条件 | 旧 root/prior action-required/recent/Stop consumers 已换为 canonical adapters；tombstone 迟到拒绝和 7 天精确清理都有回归。 |
| 验证命令 | `python3 -m unittest -v tests.test_communication_lifecycle tests.test_wait_recovery_session_closure`; 全量 unittest、py_compile、Plugin validator、`git diff --check`。 |
| 真实平台 `not_checked` | Provider 重启、断流、pending_init、精确空列表、interrupt 实际终态与 Session Hook 时序。 |

### S5：work-item-first diagnostics 与 group

**目的**：按 D5 切换只读决策视图，保持旧 diagnose JSON 的兼容字段，不让诊断反向驱动状态。

| 项目 | 规定 |
| --- | --- |
| 文件/函数范围 | `governance-semantics` diagnostics defs；`scripts/subagent_governance.py` 的 `_diagnostic_*`、`_diagnostic_session_snapshot`、`_derive_group_snapshot`、`read_group`、`_session_start_context`；`tests/test_minimal_diagnostics_lightweight_groups.py`，新增 D5 全部 fixture。 |
| 先行失败测试 | work_items 稳定排序、`indeterminate` 而非猜测；pending-review/unknown/duplicate/unavailable/tombstone 投影；allowed_actions+basis；读取前后 inode/mtime/hash 不变；group required/optional/缺失 member。 |
| 状态转换 | 无；只读取 S1～S4 事实。旧 attempt arrays 为 secondary 兼容输出，不改其语义。 |
| success/failed/unknown | diagnose 成功只代表完整或部分可读；扫描失败产出 issue/exit code，不把 unreadable 写为 failed/unknown business result。 |
| 退出条件 | SessionStart 文本优先使用 work_items；group 消费 work-item snapshot；Stop 仍不解析 diagnose；所有诊断纯只读。 |
| 验证命令 | `python3 -m unittest -v tests.test_minimal_diagnostics_lightweight_groups`; 全量 unittest、py_compile、Plugin validator、`git diff --check`。 |
| 真实平台 `not_checked` | Codex UI/恢复摘要的展示、父 Agent在真实任务中依此等待和处置。 |

### S6：兼容投影退役与发布准备（不发布）

**目的**：只在 S1～S5 有新消费者和全量回归后，删除旧 root/prior writer/reader、attempt-first 主入口和相应历史 fixture；此切片不安装或发布。

| 项目 | 规定 |
| --- | --- |
| 文件/函数范围 | `scripts/subagent_governance.py` 的 legacy adapters/projection writers/readers、相应 tests/fixtures、`docs/project-function-inventory.md`、`docs/optimization-plan.md`、发布准备文档；必要时三个 Schema 的不再使用 defs。Skill/hook 只有实际 runtime boundary 改变时才改。 |
| 先行失败测试 | AST/行为测试证明旧投影没有 runtime consumer；canonical records 经所有 Hook/CLI/diagnose/group 路径；历史 record 只读诊断仍明确；release preflight 不误称已安装。 |
| 状态转换 | 无新业务转换；仅移除已被 canonical path 覆盖的兼容层。 |
| success/failed/unknown | success 是删除后本地全量通过；failed 是任一残留消费者，停止删除并恢复到 S5 兼容层；unknown 仅是平台验收尚未发生，不能用本地删除推断。 |
| 退出条件 | 无旧字段权威消费者；当前文档标明开发仓库完成与平台未验收；稳定源/缓存未写。 |
| 验证命令 | 全量 unittest、py_compile、Plugin validator、Skill validator（若 Skill 改动）、release-tool tests、Schema/fixture checks、`git diff --check`、只读路径/hash 检查。 |
| 真实平台 `not_checked` | 见第 8 节的完整矩阵；本切片不把任何项目改为 passed。 |

依赖顺序固定为：

```text
S1 四层最小闭环
  -> S2 派发与身份
  -> S3 resume/replacement/增长护栏
  -> S4 平台恢复、等待、关闭
  -> S5 诊断与 group
  -> S6 兼容退役与发布准备
```

S2 不得跳过 S1；S3 必须同时依赖 S1/S2；S4 不得用旧 attempt-first 规则替代 S3 duplicate；S5 只读消费前四片；S6 不得与任何新主路径实现合并。

## 8. omni-memo 抽象回放的本地 fixture 与真实验证矩阵

仓库没有 omni-memo 的完整正文、真实 response 或时间线。D1 的三类抽象回放应先成为三个独立的本地 fixture 基类：A「正常 complete 但必须父验收」、B「unknown/迟到启动/replacement」、C「blocked/failed 后继续或关闭」。D3～D5 的冲突、诊断和平台观察只是在这三类基类上增加确定性变体，不能凭空补写真实对话。以下 fixture 只编码 D1～D5 已知的抽象事件，不使用 `omni-memo` task id、消息正文、Agent ID 或平台断言。

| fixture 类 | 本地回放 | 覆盖的裁决 |
| --- | --- | --- |
| `work-item-complete-v1`（D1-A） | A1 result complete → pending → accept → tombstone；result replay/conflict。 | outcome/disposition 分离、C1、存储顺序。 |
| `work-item-unknown-replacement-v1`（D1-B） | A1 spawn unknown；显式 risk acceptance 后 A2 replacement；A1 迟到 Start/result。 | unknown、duplicate、select，不能按最新选择。 |
| `work-item-disposition-v1`（D1-C） | blocked、failed、needs_decision，各自继续或 close。 | execution terminal 不等于 work-item close。 |
| `work-item-resume-v1` | A1 blocked；same Agent A2 新 ref + origin name + pending；分别重放 success/failed/unknown/Start。 | C3、C8、硬 target 串行性。 |
| `work-item-platform-v1` | pending_init、error recovery、interrupt unknown、精确 terminal list。 | D4 三维观察和有限预算。 |
| `work-item-diagnostic-v1` | pending review、unavailable、prior stale action-required、tombstone、group required/optional。 | D5 无副作用投影与不完整读取。 |

fixture 应分布在现有 `tests/fixtures/`，每个包含 `assumptions`（仅抽象事实）、events、expected canonical state/decision snapshot；不保存 prompt、真实错误文本、对话正文或外部路径。针对存储、diagnose 的测试还必须维持现有 inode/mtime/hash 无副作用断言。

真实新对话必须在开发仓库本地验证完成、用户另行授权测试插件更新后才做；项目规则要求新对话默认 `gpt-5.6-terra` + `high`。在当前轮及 S1～S6 实现前，全部均为 `not_checked`：

| 场景 | 真实目标 | 当前状态 |
| --- | --- | --- |
| initial spawn success/failed/unknown | response、task ref、迟到 Start 的真实形状。 | not_checked |
| same-Agent business resume | followup 投递与同 target 新 attempt Start 关联。 | not_checked |
| replacement/duplicate/select/interrupt | 旧 Agent迟到、精确中断和关闭时序。 | not_checked |
| platform recovery | 断流/重启、pending_init、list empty、两次恢复限制。 | not_checked |
| structured outcome | SubagentStop/CLI payload、文件回读和父 accept/reject。 | not_checked |
| Session/Stop/diagnose/group | compact/resume/SessionEnd、UI 展示和父 Agent正确使用 snapshot。 | not_checked |
| N/N-1 | 新版本加载、Hook trust、回滚与缓存保留。 | not_checked |

本地 fixture 通过只证明逻辑和本地 Hook handler，不能替代任何一项。

## 9. 开发、稳定源、运行缓存与发布授权边界

- 唯一修改源始终是当前开发仓库根目录。S1～S6 的代码、Schema、测试、Skill 或文档修改只能发生在此目录。
- 稳定发布源 `~/plugins/subagent-governance`、`~/.codex/plugins/cache/personal/subagent-governance`、Hook trust、Marketplace、Codex Manager Registry 和任何外部对话都不属于迁移写入目标。
- 真实平台测试前必须先在开发仓库完成对应切片的本地验证；若用户授权更新用于测试的本地插件，必须从开发仓库同步，并在新对话测试。那是后续受控测试，不等于发布稳定版。
- 本轮 D6 以及其建议的首个 S1 都不执行安装、发布、cachebuster、复制稳定源、修改 Hook trust、stage、commit、push 或外部对话操作。只有用户明确授权“发布、安装或更新稳定版”后，才能按发布流程另行开始。

## 10. 完成判定与主任务下一步

D6 完成的条件是：C1～C9 已有唯一裁决；逻辑 Schema/落点、same-Agent identity、增长控制、兼容策略、六个纵向切片、fixture/真实矩阵和外部写入边界均已明确；没有把缺失的 omni-memo 或平台事实补写为真实证据。

主任务完成 D6 后应启动的第一个实施切片是 **S1「四层最小闭环」**。它的第一项动作必须是先在 `tests/test_state_store.py` 与 `tests/test_formal_result_parent_closure.py` 写入上述 canonical work-item、complete pending/atomic accept、三种非 complete 留 open、存储 unavailable 的失败测试；测试失败后才修改 Schema 语义锚点和最小 StateStore/result/disposition 函数。

本文仅完成设计文档。未执行单元测试、`py_compile`、Plugin validator、Skill validator、发布工具、安装、真实新对话或真实平台验证；它们均属于后续相应实施/授权阶段。
