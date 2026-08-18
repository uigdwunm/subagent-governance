# D5 决策诊断视图

## 1. 状态、范围与结论

- 工作项：D5「诊断与工作项决策视图」。
- 前置：D1 四层对象和不变量，D2 派发/交付契约，D3 outcome/disposition，D4 平台观察与恢复边界。
- 依据：重设计工作流地图、D1～D4、SG-F07/SG-F08、WP-07、governance semantics Schema，以及当前 Python 中只读 diagnose、action_required、recent_activity、group 实现。
- 本文只冻结设计；不修改运行时代码、Schema、测试、稳定发布源、运行缓存、Hook trust、外部对话或其他项目。

**结论**：诊断的一级输出应是 work item 决策视图，而不是完整内部状态或 attempt 列表转储。它向父 Agent显示：业务目标是否仍开放、哪些 execution 是实际候选、是否有可读 outcome、是否已有 disposition，以及当前机械不变量允许哪些入口。它不替父 Agent作业务选择、恢复、验收或关闭。

D1 的 work_item 是一级展示对象；execution 是候选事实；outcome 是结果材料；disposition 是父 Agent已写入的决定。Agent target、工具响应、Hook 事件和平台观察只属于 execution，不能成为业务目标结论。

## 2. 诊断边界

### 2.1 负责

诊断是稳定 JSON 的只读投影，负责：

1. 按稳定 task_id 汇总 current/prior execution、明确关闭事实和 tombstone。
2. 展示可直接读取的持久化事实、精确结果引用核对、字段问题和本次扫描完整度。
3. 将 D1～D4 不变量投影为有限的 allowed_actions，并给出触发事实。
4. 区分不受时间窗口影响的 action_required 与仅用于展示排序的 recent_activity。
5. 从 individual work item 实时派生轻量 group 信号，不建立组级状态机。

### 2.2 不负责

诊断不得创建目录、锁、Session、结果、tombstone 或 group，也不得回写、迁移、清理、重关联或修改时间戳。不得调用 spawn_agent、followup_task、interrupt_agent、list_agents；不等待、不自动恢复、不补交结果、不自动验收、选择或关闭。

它不读取完整对话、通信正文、完整平台响应、任意 worker thread 或外部系统。transport_opaque=true 是能力边界。它不得从 success/failed/unknown、沉默、时间、同名、最新 attempt、唯一候选、关键词、回复长度或文件提示推断业务结果、投递/阅读、Agent 存活或用户意图。

allowed_actions 不是推荐、待办排序、执行器或已执行动作，只表示当前已知机械不变量没有禁止的入口类别。诊断不生成用户业务摘要、AggregateResult、group disposition、DAG、batch、wave 或调度器。

读取失败不改变被诊断对象；仅以 issues、scan.complete=false 和既有退出语义报告边界。任务异常或待处置本身不使诊断命令失败。

## 3. 稳定工作项视图

### 3.1 容器与排序

D6 应保留 WP-07 的无副作用顶层扫描语义：data_root、data_root_exists、scope、requested_session、scan、issues、boundaries，以及 Session health/容量信息。每个 Session 增加 work_items；迁移期的 action_required/recent_activity AttemptSnapshot 可保留为兼容投影，但不是决策主入口。

逻辑形状如下，字段版本和落点留给 D6：

    WorkItemDecisionSnapshot
    ├── task_id
    ├── objective_summary
    ├── current_attempt
    ├── lifecycle
    ├── action_required
    ├── recent_activity
    ├── growth
    ├── execution_candidates[]
    ├── outcome_availability
    ├── disposition
    ├── allowed_actions[]
    ├── facts[]
    └── timestamps

objective_summary 只能取有界持久化契约摘要；缺失为 null 并生成 issue，不从 task name、prompt 或对话补写。数组按 attempt、再按精确 target 稳定排序；allowed_actions 按第 4 节顺序；不输出完整 StateStore、outcome/evidence/remaining、prompt 或平台对象。

### 3.2 work item 汇总

| 字段 | 机械来源与含义 | 不表示 |
| --- | --- | --- |
| task_id | 稳定业务身份。 | task name、Agent ID 或一次调用。 |
| current_attempt | 持久化的父选择；无法读取为 null + issue。 | 最大编号、最近活动或最早结果。 |
| lifecycle | open：存在未关闭 execution 或未完成 work-item disposition；tombstoned：全部相关 execution 有带原因关闭/tombstone；indeterminate：读取或关闭关系不可核实。 | 正在运行或业务成功。 |
| action_required | 任一未关闭 execution 满足 D1/WP-06 action-required，或目标没有完整处置；不受 recent window 影响。 | 已被授权 spawn 或业务优先级。 |
| recent_activity | 任一 execution 在 recent_activity 窗口内有 activity_at。 | 权威生命周期或未解决责任。 |
| growth | 从 canonical work_item 投影累计 attempt/replacement 次数、两个软增长 fact 和最近增长授权的有界 reason 摘要。 | action-required、业务预算、自动关闭或 spawn 授权。 |
| facts | 有界、可追溯标签，例如 duplicate_candidates、identity_unconfirmed、platform_unknown、platform_error、result_conflict、tombstoned、scan_incomplete。 | 根因推测。 |

lifecycle=tombstoned 必须只保留 attempt、关闭时间、关闭 reason 是否存在等最小引用。tombstone 有效期内的迟到事件仍只能拒绝；它不等于业务成功。

growth 的固定形状为：

    attempt_count: integer | null
    replacement_spawn_count: integer | null
    repeated_business_attempts: boolean
    repeated_replacements: boolean
    soft_warning: boolean
    facts: repeated_business_attempts | repeated_replacements 的有序集合
    latest_authorization: {
      action: resume_business | spawn_replacement | null,
      attempt: integer | null,
      reason_present: boolean | null,
      reason_summary: bounded string | null,
      recorded_at: integer | null
    }

canonical `work_item` 是累计次数和软增长事实的唯一来源；execution candidate 上的同名 `growth_facts[]` 不读取。runtime 用独立的 `work_item.last_growth_authorization` 保存最近增长授权，不与 accept/reject/select/close 的 `last_parent_disposition` 共用字段，也不建立事件日志。reason 摘要最多160字符，只来自已校验的 growth authorization；缺失、类型非法、空白或超过持久上限的旧 reason 输出 null 并产生 issue，不从 dispatch prompt、通信正文或 execution 猜测。

### 3.3 execution candidates

execution_candidates 不是第二份内部状态转储，而是决策所需的最小投影：

    attempt
    role: current | prior | duplicate_candidate | tombstoned
    target: {agent_id, canonical_task_path} | null
    identity: confirmed | unconfirmed | unknown
    execution: not_started | running | stopped | interrupted | unknown
    platform: normal | error | unknown | not_checked
    result: none | pending_review | available | unavailable | conflict
    closed: boolean
    action_required: boolean
    facts[]
    timestamps: {activity_at, platform_checked_at, result_stored_at, closed_at}

视图词必须机械投影：

- identity=unknown 仅用于身份字段缺失/非法或扫描不完整；正常 identity_status=unconfirmed 必须原样反映。
- execution=unknown 仅用于 execution_status 缺失/非法；spawn_observation=unknown 不能改写 execution。
- platform=unknown 表示已发生但不可确认的观察；not_checked 表示没有适用观察，二者不可互换。
- duplicate_candidate 只在持久化 duplicate 事实和未闭环候选成立时出现，不声称其一定产生业务副作用。
- tombstoned/closed 只来自精确关闭或 tombstone，绝不由 stopped、complete、failed、时间或空列表推导。

不展示 pending_action、last_lifecycle_operation 原对象、完整重试理由或所有内部计数。可显示有界的计数 facts（如 spawn_retry=1/2），但不得掩盖 unknown 或扩大授权。

### 3.4 outcome availability

outcome_availability 是当前可供父 Agent阅读/处置的材料摘要，不是新的 business_result 或验收结论：

    state: none | pending_review | available | unavailable | conflict | superseded_by_selection
    attempt: integer | null
    business_result: complete | blocked | failed | needs_decision | null
    reference: {readable, usable, sha256_matches} | null
    acceptance: pending | accepted | rejected | not_applicable | null
    reason_codes[]

| 原始事实 | 投影 |
| --- | --- |
| 无合法 outcome，且没有 exhausted/storage-unavailable 事实 | none；平台 unknown 不是结果缺失。 |
| 已选 current 为 complete、valid、available、pending，且无 duplicate/conflict | pending_review。 |
| 合法结果可读可用但非上述可验收 complete | available；blocked/failed/needs_decision 可读不等于关闭。 |
| result_protocol_status=exhausted，或 valid + storage=unavailable | unavailable，保留 D3 原因；不写业务 failed。 |
| result_conflict=true | conflict；第一份即使可读也不能自动验收/选择。 |
| 非 current 的可读结果在 duplicate/select 后不承担验收链 | superseded_by_selection；仍可只读，不删除。 |

多个未关闭 candidate 并存时，顶层只能显示 conflict 或 none 并分别列材料；不得按 attempt、结果类型或可读性挑选最佳 outcome。business_result 只复制机械核对后的枚举，绝不复制正文。

### 3.5 disposition 摘要

    status: none | pending_acceptance | accepted | rejected | close_recorded | selection_pending | indeterminate
    current_action: accept_result | reject_result | close_task | select_attempt | null
    attempt: integer | null
    reason_present: boolean | null

pending_acceptance 只是 complete 的 acceptance_status=pending。selection_pending 表示 duplicate 尚未收口，或已选择但仍有未选 running candidate 待中断对账。close_recorded 只表示存在带 reason 的 disposition/close/tombstone，不评判关闭理由。读取不完整输出 indeterminate，不能把未知伪装成 none。

F6 后该摘要只读 `last_parent_disposition`/`parent_disposition_record` 的 formal action；growth 区域只读 `last_growth_authorization`。二者具有不同对象名和 enum。`WorkItemDecisionSnapshot` 虽在 governance machine semantics 中有受控定义，仍是纯派生、非持久 record。

## 4. allowed_actions：由不变量机械派生

### 4.1 含义和顺序

固定顺序：

    wait
    reconcile
    retry_spawn
    request_result_correction
    review_result
    record_disposition
    select_attempt
    request_interrupt
    resume_business
    spawn_replacement
    inspect_tombstone

每项必须带 basis[]（有限字段路径或事实标签）和可选 targets[]（仅 confirmed 的精确 target/attempt）。没有精确 target 时不得出现 request_interrupt、同 Agent恢复或 business resume。parent_action 字符串不是充分前提，必须满足下表的完整机械条件。

| action | 全部机械前提 | 仍由父 Agent决定 |
| --- | --- | --- |
| wait | 有 confirmed running current，或 success/unknown 调用在精确对账链；未关闭。 | 等待时长、是否巡检。 |
| reconcile | unknown 调用/平台观察、unconfirmed identity、pending_init/读取不完整，或 interrupt unknown；未关闭。 | 采用哪个允许的只读观察，是否接受风险继续。 |
| retry_spawn | 可靠 spawn failed、确认未创建、同-attempt retry 有余额、无 unknown/confirmed identity。 | 是否立即重试、内容是否仍适用。 |
| request_result_correction | D3 5.2 全部成立：精确 stopped、未关闭、无 outcome、correction 有余额、无 duplicate/select/成功 interrupt 冲突。 | 是否请求补交及其内容。 |
| review_result | current selected 为 complete + valid + available + pending，且无 duplicate/conflict。 | 证据是否充分、accept/reject。 |
| record_disposition | 开放目标有 complete、blocked、failed、needs_decision、rejected、interrupted 或明确关闭意图；不把 unavailable 当 failed。 | accept/reject/close/继续/问用户的选择和理由。 |
| select_attempt | duplicate candidate 已精确识别，尚未全关闭。 | 选哪一个、是否接受副作用。 |
| request_interrupt | 已选择未选 running duplicate，或父/用户已提供精确 target 和中断意图；target confirmed 且未关闭。 | 是否中断、理由与授权。 |
| resume_business | `growth_authorization=resume_business` 已明确继续，旧 execution 的 blocked/failed/needs_decision/rejected 可读，可重新生成新 attempt 契约。 | 是否继续、范围/条件/Agent。 |
| spawn_replacement | 有 `growth_authorization=spawn_replacement` 和新 attempt 契约；旧项 unknown/running 时 transition 已明确接受重复风险。 | 是否接受风险、新 Agent与范围。 |
| inspect_tombstone | work item/execution 已 tombstoned，或迟到事件被其拒绝。 | 是否建立新 work item；不可复活旧项。 |

allowed_actions 不替业务选择。前提不足时宁可省略 action 并显示 fact/issue；allowed_actions=[] 不意味着目标完成。

### 4.2 边界情形

- duplicate：只列 select_attempt；选择已持久化且未选项 confirmed/running，才列该精确 request_interrupt。中断 failed/unknown 不关闭或清除 duplicate。
- unknown：列 reconcile，必要时 wait；不列 retry_spawn。replacement 仅在已有 growth authorization 和 duplicate-risk 记录后可列。
- blocked、failed：列 record_disposition；它们结束 execution，不自动关闭目标或自动 resume。
- needs_decision：列 record_disposition 与 user_decision_needed fact；绝不自动 recovery/replacement/close。
- result_unavailable：仅 D3 条件完整时列 request_result_correction；exhausted/storage unavailable 只列 record_disposition 或 reconcile（随事实），不伪装业务 failed。
- running：通常只有 wait，平台 unknown 时加 reconcile；不得因运行时长建议 follow-up/replacement/interrupt。
- tombstone：只有 inspect_tombstone；所有复活旧 execution 的操作均禁止。

## 5. action-required、recent_activity 与 group

### 5.1 work-item-first 迁移

当前 _action_required_records() 和 _recent_activity_records() 已从 current/prior attempt 构造记录：前者包括未关闭 parent_action、running、调用对账、unconfirmed success/unknown identity、duplicate 等责任，后者只用 12 小时 activity window。D5 保留事实规则但按 task_id 聚合：

- `work_items[].action_required` 是只读 snapshot 字段，不持久化在 canonical `work_item`；它等于任一 canonical candidate 的 action-required，current/prior execution、replacement reservation 与 duplicate candidate 使用同一 predicate。旧持久字段不参与决策，并在下一次 canonical 写入时移除。
- work_item.recent_activity = 任一 candidate.recent_activity，仅用于恢复摘要排序，不得覆盖 action_required、关闭或 tombstone。
- 迁移期保留 Session action_required/recent_activity 的 AttemptSnapshot 兼容字段并标作 secondary；新恢复摘要/消费者优先 work_items。
- 同一 attempt 同时位于两个旧列表时，新视图只保留一个 candidate，分别带两个布尔事实。

这只改变展示单位，不改变 D1 attempt、WP-06 派生规则或 retention；未解决项不能因不再 recent 而消失。

### 5.2 group

group 继续只持久化 group_id、objective_summary、members[{task_id,required}]、created_at、updated_at。GroupDecisionSnapshot 只读取 member 的 WorkItemDecisionSnapshot：

    group_id
    objective_summary
    members: [{task_id, required, exists, lifecycle, action_required, outcome_availability, growth}]
    summary_ready
    group_action_required

required 非空且每个 required 有可读正式结果材料或带 reason 的明确最终处置，summary_ready=true；它不等于成功、accepted 或组关闭。任一 required 仍 open、pending review、blocked、failed、needs_decision、unknown、duplicate、unavailable/conflict 或处置不完整，则 group_action_required=true。optional 不影响这两个聚合；缺失 member 是 issue，且该成员 action_required=true。

group 不计算 allowed_actions、不下发成员动作、不暂停/取消其他成员、不自动汇总或关闭。member.growth 只是同一 WorkItemDecisionSnapshot 的透传字段，不形成 group 级增长聚合或调度语义。父 Agent必须逐项读取 member 的 allowed_actions 并作业务判断。

## 6. omni-memo 类型抽象快照

仓库没有 omni-memo 的完整真实正文、原生响应或 Agent 身份。以下 W/A1/A2 都是抽象回放，不声称来自真实对话。

### A. unknown spawn，尚未替代

    {
      "task_id": "W", "current_attempt": 1, "lifecycle": "open",
      "action_required": true,
      "execution_candidates": [{"attempt": 1, "role": "current",
        "identity": "unconfirmed", "execution": "not_started",
        "platform": "unknown", "result": "none", "closed": false,
        "facts": ["spawn_unknown", "identity_unconfirmed"]}],
      "outcome_availability": {"state": "none", "attempt": null},
      "disposition": {"status": "none", "current_action": null},
      "allowed_actions": ["reconcile"]
    }

父 Agent可以等待或进行精确范围对账；不得自动 retry/spawn。若要 replacement，须先记录接受重复风险的 growth authorization/transition，再新建 A2，不能把 A1 改写成 failed。

### B. replacement 后重复候选

    {
      "task_id": "W", "current_attempt": 2, "lifecycle": "open",
      "action_required": true, "facts": ["duplicate_candidates"],
      "execution_candidates": [
        {"attempt": 1, "role": "duplicate_candidate", "identity": "confirmed",
         "execution": "running", "result": "none", "closed": false},
        {"attempt": 2, "role": "current", "identity": "confirmed",
         "execution": "stopped", "result": "available", "closed": false}
      ],
      "outcome_availability": {"state": "conflict", "attempt": null},
      "disposition": {"status": "selection_pending", "current_action": "select_attempt"},
      "allowed_actions": ["select_attempt"]
    }

父 Agent可显式选 A1 或 A2；诊断不能因 A2 有结果或编号更大而选择。选择持久化后，未选的 confirmed/running A1 才显示精确 request_interrupt；interrupt unknown/failed 前不得 tombstone 或清除 duplicate。

### C. complete 可读、尚待验收

    {
      "task_id": "W", "current_attempt": 2, "lifecycle": "open",
      "action_required": true,
      "execution_candidates": [{"attempt": 2, "role": "current",
        "identity": "confirmed", "execution": "stopped", "platform": "normal",
        "result": "pending_review", "closed": false}],
      "outcome_availability": {"state": "pending_review", "attempt": 2,
        "business_result": "complete",
        "reference": {"readable": true, "usable": true, "sha256_matches": true},
        "acceptance": "pending"},
      "disposition": {"status": "pending_acceptance", "current_action": null},
      "allowed_actions": ["review_result", "record_disposition"]
    }

父 Agent可核对 D2 交付契约和证据后显式 accept/reject；插件不能把可读 complete 当 accepted/closed。若还有未可靠关闭 candidate，review_result 不出现。

### D. needs_decision，等待外部选择

    {
      "task_id": "W", "current_attempt": 1, "lifecycle": "open",
      "action_required": true,
      "execution_candidates": [{"attempt": 1, "role": "current",
        "execution": "stopped", "result": "available", "closed": false}],
      "outcome_availability": {"state": "available", "attempt": 1,
        "business_result": "needs_decision", "acceptance": "not_applicable"},
      "disposition": {"status": "none", "current_action": null},
      "allowed_actions": ["record_disposition"]
    }

父 Agent可向用户呈现结构化 decision question，或在获得决定后创建新 business-resume attempt；不能自动续跑、改派或关闭。blocked/failed 同样是待处置而非自动关闭。

## 7. 迁移兼容关系

| 来源 | D5 继承 | D5 限制 |
| --- | --- | --- |
| D1 | 四层对象、attempt/unknown/tombstone/duplicate 不变量。 | work item 为主，不把 execution 字段包装成业务状态。 |
| D2 | task_id/current attempt、契约摘要、replacement/transition 显式。 | allowed_actions 不生成契约或授权范围/模型。 |
| D3 | protocol/storage 正交、result_unavailable、disposition、可读与验收分离。 | 只显示 availability/枚举，不输出正文或判证据。 |
| D4 | platform/execution/identity 三维、精确 target、恢复/replacement/interrupt/duplicate。 | 平台事实只作 action 前提，不自动恢复。 |
| WP-07/SG-F07 | 无副作用、稳定 JSON、issues/scan/容量、精确只读结果核对。 | Session/AttemptSnapshot 是兼容输入，不是最终决策 API。 |
| WP-07/SG-F08 | group 最小引用、实时 required/optional 派生。 | 不加 group 状态机、disposition、allowed_actions 或 AggregateResult。 |

当前 diagnose 的顶层 scan/health/issues/boundaries 和 Session counts 保持语义兼容。当前 action_required/recent_activity AttemptSnapshot 在迁移期继续提供，避免破坏恢复摘要和消费者；D6 新增 work_items，随后明确弃用旧主入口，不能静默改旧字段含义。

现有 AttemptSnapshot 的 execution_status、spawn_observation、identity_status、platform_observation、business_result、acceptance_status、result_protocol_status、result_storage_status、result_conflict、recovery_status、parent_action 和计数是 candidate 输入，不能原样宣称为新的 work-item API。当前实现已有只读核对/group 派生，但仍以 attempt 为一级列表，因此尚未实现 D5。

旧平面 status、裸状态/完整 result 输出、active count、按 recent 决定未解决、自动 repair/恢复和从自然语言推 transport 的路径与 D5 冲突；D6 应删除或隔离。

## 8. D6 落点与真实平台未决

### 8.1 Schema、实现、测试

D6 必须：

1. 决定 WorkItemDecisionSnapshot 是诊断输出约定还是 Schema，并冻结 lifecycle、candidate role/result/platform、outcome/disposition summary、allowed_actions/basis 字段和排序；result_unavailable 不得进入 business_result 枚举。
2. 制定从 current/prior attempts、tombstones、parent disposition、legacy records 到 work item 的精确兼容读取；缺失旧字段报 issue/indeterminate，不能默认 closed/failed/accepted。
3. 在既有纯只读 loader 上实现 task_id 聚合、候选去重、排序、容量截断、facts/basis 脱敏；不得调用会创建锁或改变状态的 StateStore/read reconciliation/cleanup 路径。
4. 将 SessionStart/CLI 恢复摘要切到 work-item-first，短期维持 AttemptSnapshot；Stop 仍直接用权威 action-required 规则，不读取新视图文字。
5. 让 group 读取 work-item 事实，测试 required/optional、缺失 member、tombstone、pending acceptance、unavailable 和 duplicate；不持久化组派生字段。
6. 新增 fixtures：complete pending/accepted、unknown、duplicate/select/interrupt unknown、blocked/failed/needs_decision、protocol exhausted/storage unavailable/conflict、running、tombstone/迟到拒绝、prior attempt action-required、recent 过期但开放、group 空 required、读取损坏/容量、以及无副作用 inode/mtime/hash。
7. 证明旧 diagnose JSON 在兼容期稳定并迁移消费者，再退役 active count、裸转储和将 attempt 列表误作 work-item 决策的测试/文档。

### 8.2 not_checked 的真实平台项

- spawn_agent、followup_task、interrupt_agent、list_agents 在真实 Provider 断流/重启下 success/failed/unknown、pending_init、空列表和乱序 SubagentStart 的完整形态。
- SubagentStop 对结构化 TaskResult 的投递、迟到、重复和正式结果文件时序。
- 精确 canonical target 查询与受限 thread-interrupted 只读证据的跨 Provider 可用性；D5 不假定可用。
- Hook trust、Plugin/Skill 加载、运行缓存版本，以及 Codex UI 对诊断 JSON、恢复摘要/group 展示的实际效果。
- 父 Agent在真实新对话中只根据该视图正确等待、对账、处置和汇总的端到端结果；本地 fixture 或缺失 omni-memo 正文不能替代。

## 9. 完成判定与验证声明

D5 已定义以 D1 四层为基础的 work-item 决策视图，明确无副作用/transport opaque/非自动化边界，给出汇总、candidate、availability、disposition、机械 allowed_actions，覆盖 duplicate、unknown、blocked、failed、needs_decision、result_unavailable、running、tombstone 和 group，说明旧 action/recent/diagnose JSON 迁移，提供四个抽象快照，并列出 D6 落点与真实平台未决项。

本项仅新增本设计文档。未执行单元测试、py_compile、Plugin validator、Skill validator 或真实平台/omni-memo 测试；设计文档完成不表示它们已经验证。
