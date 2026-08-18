# D2 派发与交付物契约

## 1. 状态、范围与结论

- 工作项：D2「派发契约、交付物契约和重复执行预算」。
- 前置：D1 的 `work_item -> execution -> outcome -> disposition` 四层模型及其不变量。
- 依据：`docs/redesign-workstream-map.md`、D1、项目功能盘点、优化计划、WP-03、WP-04、`task-contract-v1.schema.json` 和 `governance-semantics.schema.json`。
- 本文冻结 D2 的逻辑契约和迁移接口；不修改运行时代码、Schema、测试、稳定发布源、运行缓存、Hook trust 或外部对话。

**结论**：受治理派发必须把「稳定业务目标」「本次执行边界」「子 Agent 应交付什么」和「为何继续或替换」分成可独立核对的字段组。现有 `TaskContract v1` 继续描述一次 execution 的业务输入；D2 在其外定义一个逻辑 `DispatchDeliverableContract` 信封。该信封不是新的业务对象、不是第二套调度器，也不替代 D3 的 `outcome` 或父 Agent 的 `disposition`。

`deliverable_contract` 约束子 Agent 应提交的结果形状和父 Agent 应检查的声明性条件；它不让插件根据正文关键词、文件存在性、测试名称或回复长度判定业务成功。

## 2. D1 四层中的职责边界

| 层 | D2 固定的内容 | 不负责的内容 |
| --- | --- | --- |
| `work_item` | `task_id`、稳定目标摘要、当前/历史 execution 引用以及何时允许新增 execution | 保存完整 prompt、完整对话、Agent DAG，或把平台调用当作业务目标 |
| `execution` | `attempt`、派发方式、身份关联、TaskContract 快照、预算消费和 transition reason | 从 native success/failed/unknown 推导业务结果 |
| `outcome` | 交付物必须投影为合法 `TaskResult`，并能关联本 execution 的 `deliverable_contract` | 自动接受 complete、根据交付物描述判断证据真实 |
| `disposition` | reviewer/父 Agent 对 complete、失败、重复候选的显式处置入口 | 替用户或业务 reviewer 作判断，或从 `parent_action` 推导已经处置 |

原生 `spawn_agent`、`followup_task`、Agent ID、canonical path、tool response 和 `SubagentStart` 都是 execution 的观察或关联事实。它们不能创建、关闭或验收 `work_item`，也不能替代正式 `outcome`。

### 2.1 最小角色

| 角色 | 可以做什么 | 不可以做什么 |
| --- | --- | --- |
| dispatching parent | 创建 work item、生成/验证契约、请求 spawn 或 follow-up、提交 disposition | 把工具 success 写成 business result，或凭同名/最近候选绑定身份 |
| executing child | 按首句和 TaskContract 执行，提交一个结构化 outcome | 验收自己的 complete，改写其他 attempt 的结果 |
| reviewer（通常是父 Agent） | 对 `complete` 核对 `deliverable_contract` 所引用的条件和证据，提交 accept/reject | 以格式卡片、字数或关键词代替业务审核；审核 blocked/failed 为 accepted |
| user / decision owner | 在 `needs_decision`、最后一次 retry、重复执行风险或范围实质变化时给出需要的授权 | 由插件臆测其授权 |
| plugin | 机械校验字段、引用、枚举、预算和状态组合 | 评估产物质量、证据充分性、真实副作用或下级 Agent 权限 |

`reviewer` 是父 Agent 的职责标签，不是必需新增一个 Agent，也不建立多人审批工作流。没有显式 reviewer disposition 时，`complete` 仍只是 `acceptance_status=pending`。

## 3. 逻辑契约结构

### 3.1 逻辑字段组与存储边界

以下是 D2 的**逻辑结构**。实施切片可把其中的字段分别放入 PreparedContract、StateStore、pending action 或结果引用；在 D6 决定落点前，不修改现有 JSON Schema。

```text
DispatchDeliverableContract
├── work_item
├── execution
├── task_contract              # 现有 TaskContract v1
├── deliverable_contract
└── transition                 # 仅 retry/resume/replacement
```

#### `work_item`

| 字段 | 规则 |
| --- | --- |
| `task_id` | 非空、稳定业务身份；恢复、retry、resume、replacement 和会话重启均不改变。 |
| `objective_summary` | 从 TaskContract 的 `objective` 得到的有界摘要，只供恢复/诊断；不是第二份业务目标。 |
| `current_attempt` | 父 Agent 显式选择的 execution。它不是最新编号，也不能由迟到事件改变。 |

#### `execution`

| 字段 | 规则 |
| --- | --- |
| `attempt` | 从 1 开始递增；同一 execution 的唯一正式 outcome 边界。 |
| `dispatch_kind` | `initial_spawn`、`spawn_retry`、`business_resume`、`replacement_spawn` 四选一。平台恢复、结果补交和普通消息不是新的 execution。 |
| `task_ref` | `sha256("<task_id>:<attempt>")` 的会话内唯一前缀；长度按 12/16/20/24/28/32 扩展。它精确关联该 execution，不由 display name 或时间推测。 |
| `task_name` / `origin_task_name` | 新 spawn 的 name 为 `sg_<resolved_mode>_<semantic_name>_t_<task_ref>`，最多 64 字符。business resume 沿用原 Agent 时没有新的原生 task name，应保留初次 spawn 的 `origin_task_name`；新 attempt 仍有自己的 `task_ref`，由精确 target + claimed pending action / last lifecycle operation 关联。 |
| `identity_target` | 已确认后为 Agent ID 和/或 canonical path，并精确映射到 `task_id + attempt`；未确认时为 `null`，不能猜测。 |
| `contract_digest` | 规范化 TaskContract 与 deliverable contract 的摘要，用于跨存储一致性检查；不把完整首句长期留在 StateStore。 |

#### `task_contract`

`task_contract` 是现有 `schemas/task-contract-v1.schema.json` 的完整、规范化快照，属于一次 execution，而不是永久附着在 work item 上。其权威业务字段是：

- `semantic_name`、`requested_mode`、`resolved_mode`、`resolution_reason`；
- `objective`、`background`、`work_scope`、`forbidden_scope`、`completion_conditions`、`evidence_requirements`、`relevant_files`、`current_state`；
- `model`、`reasoning_effort`、`context_strategy`、`context_turns`、`context_reason`。

`auto` 只在生成时解析；之后所有 task name、prompt、Hook 和结果路径只使用 `resolved_mode`。显式 `model`/`reasoning_effort` 为空时省略原生参数，而不是写入假定继承值。resume 到同一 Agent 时不得通过新 TaskContract 假装改变模型或 Provider；此类要求必须走 `replacement_spawn`。

#### `deliverable_contract`

`deliverable_contract` 是 TaskContract 的可交付投影，必须随 execution 固定。它应使用以下最小字段：

| 字段 | 机械约束与含义 |
| --- | --- |
| `outcome_required` | 固定为 `true`；子 Agent 必须提交能通过 TaskResult Schema 的正式 outcome，不能只交中文结论。 |
| `completion_condition_refs` | 非空、按顺序引用本次 `completion_conditions` 的索引或稳定摘要；不能另写无法回溯的成功标准。 |
| `evidence_requirement_refs` | 按顺序引用 `evidence_requirements`；light 可为空，standard/strict 遵从现有 mode minimum。引用存在不表示插件评估了证据。 |
| `artifact_expectations` | 可为空的声明列表，每项只含 `label`、`kind`、`location_hint`、`required`。`kind` 仅描述交付类别（例如 document、source_change、command_output、decision），不建立文件扫描或强制路径存在性检查。 |
| `outcome_guidance` | `complete`、`blocked`、`failed`、`needs_decision` 四种结果均允许；对每种适用状态给出应填的 TaskResult 场景字段。它不预先承诺会 complete。 |
| `review_required` | 固定 `true`，表示 complete 必须走父 Agent验收；不新增自动验收例外。 |

`completion_condition_refs` 和 `evidence_requirement_refs` 是结构一致性约束：生成器检查索引/摘要存在且顺序稳定；reviewer 判断实际交付是否满足它们。`artifact_expectations` 仅帮助子 Agent 明确如何报告，不成为插件读取工作区、联网系统或外部对话的授权。

#### `transition`

首次 `initial_spawn` 没有 `transition`。其余派发必须有如下最小记录：

| 字段 | 规则 |
| --- | --- |
| `from_attempt` | retry 时等于当前 attempt；resume/replacement 时为前一个被处置或待对账的 attempt。 |
| `reason_code` | 使用本节定义的固定枚举。 |
| `reason` | 有界、非空的人类可读理由；说明已知事实，不补写平台或业务细节。 |
| `authorized_by` | `parent`、`user` 或 `mechanical_rule`；仅明确失败的自动第一次 retry 可以是 `mechanical_rule`。 |
| `duplicate_risk_accepted` | 仅 replacement 针对旧 unknown 时必为 `true`；它记录风险已被明确接受，而不是宣称旧调用未发生。 |

`reason_code`：

- `confirmed_spawn_failure_retry`：同一 attempt 的可靠 failed retry；
- `blocker_resolved`、`decision_received`、`result_rejected`、`scope_or_conditions_changed`：business resume；
- `unknown_duplicate_risk_accepted`、`agent_unavailable`、`user_requested_replacement`、`direction_invalid`、`identity_or_duplicate_conflict`：replacement spawn。

这组 reason 记录进入新 execution 的来源，不改变旧 execution 的 `business_result`、`spawn_observation` 或 result 地址。

F6 将 transition 与授权对象进一步分离：transition 说明“从哪个 attempt、为什么、由谁”进入新边界；`growth_authorization` 只机械授权 `resume_business|spawn_replacement`。formal `parent_disposition_record` 仍只允许 accept/reject/close/select，不能再用名为 disposition 的字段保存增长授权。字段和组合约束只在 governance Schema 维护。

### 3.2 机械一致性规则

1. `task_id + attempt` 在 session 内唯一；每个新 attempt 都有新 task ref 和新结果地址。
2. `task_ref` 可从 `task_id + attempt` 重新计算。新 spawn 的 task name 必须能解析为同一 ref 和 resolved mode；相同 attempt retry 不换 ref/name。
3. `contract_digest` 必须覆盖本 attempt 的 TaskContract 与 deliverable contract。PreparedContract、StateStore 摘要和 claimed operation 有不同摘要时，拒绝调用，不降级为 unmanaged。
4. `deliverable_contract` 的引用只能指向本 attempt TaskContract 的完成条件/证据要求；它不得引用旧 attempt、父对话正文或未受控外部状态。
5. business resume 与 replacement 都重新解析并验证 TaskContract，允许范围、完成条件、证据和 resolved mode 变化；变化必须由 `transition.reason_code` 可解释。
6. execution 尚未产生合法 outcome 时，不能用首句、交付物清单、native response 或 `SubagentStop` 填充 `business_result`。

## 4. 首句、上下文与交付物防漂移

### 4.1 固定信息顺序

生成器必须从结构化字段按固定顺序渲染首句，不从自由文本再次抽取或分类。首句至少包含：

1. 唯一 objective 和本次 execution 的工作范围；
2. 当前状态及与本次有关的历史裁决/transition reason；
3. `work_scope`、`forbidden_scope`、相关文件和必要背景；
4. `deliverable_contract` 所引用的完成条件、证据要求及 artifact expectations；
5. 可提交的 TaskResult 结果种类，及 blocked/failed/needs_decision 时必须说明的场景字段；
6. 不得自行扩大范围、复用其他 attempt 结果，和需要结构化终态交付的义务。

首句不包含 `task_id`、`attempt`、`task_ref`、内部存储路径、prepared ref、协议版本或 StateStore 内容。原生 `task_name` 是 spawn 时唯一允许携带的机械查找引用；follow-up 则通过已经精确确认的 target 和 pending action 关联。

这保证一个孤立子 Agent 看到足够业务上下文，同时不会把短 ID 变成业务约束或让正文可见性成为身份恢复的前提。

### 4.2 上下文策略

| 策略 | 原生映射 | 使用条件 | 首句义务 |
| --- | --- | --- | --- |
| `isolated` | `fork_turns="none"` | 默认；背景可被当前契约充分压缩 | 必须携带执行所需完整背景，不能依赖父线程隐含历史。 |
| `limited` | `fork_turns="N"`，1-100 | 只依赖最近有限裁决，且 `context_reason` 说明原因 | 仍需携带目标、范围、完成条件和交付物；继承内容只作补充。 |
| `full` | `fork_turns="all"` | 连续对话细节无法可靠压缩、用户明确要求或确有未落盘状态 | `context_reason` 必填；首句仍必须消除本次范围和交付物歧义。 |

上下文继承不改变 `task_id`、attempt、结果边界或 reviewer 责任。完整继承不能用来绕过 TaskContract 缺失、transition reason 缺失或 deliverable contract 缺失。

### 4.3 交付与验收边界

子 Agent 的交付路径是：`deliverable_contract` -> 合法 `TaskResult` -> D3 的 outcome 存储/协议检查 -> reviewer disposition。格式正确的 TaskResult 仅证明可被处理；它不证明 artifact 已生成、证据可靠或业务目标完成。相反，父 Agent也不得因自然语言终态卡看起来合理而跳过正式 outcome。

## 5. active execution、replacement 与预算

### 5.1 活跃执行的最小约束

一个 work item 默认只能有一个由父 Agent选择的 `current_attempt`。这不是「全局最多一个 Agent」规则：旧 unknown execution 必须继续保留迟到绑定边界，因此经明确授权后可与 replacement 并存。

| 约束 | 机械规则 |
| --- | --- |
| 常规派发 | 创建 initial spawn 前，不得存在同一 work item 未处置的正常 active candidate。 |
| 目标串行性 | 同一个 confirmed target 同时至多一个 `pending_action`；由 WP-04 的 `prepared/claimed` 记录保证。 |
| duplicate | 旧 unknown 与 replacement 都可能执行时，所有候选保留，各自的结果独立；写 `duplicate_execution=true + parent_action=resolve_duplicate`。 |
| 选择 | 只有显式 `select_attempt` 能改变 `current_attempt`。不能按 attempt 最大、最新 Agent 或最早结果自动选择。 |
| 非当前结果 | 非 current attempt 可以提交独立 outcome，但不能自动进入 work item 的验收链或覆盖当前结果。 |

### 5.2 replacement 与 business resume 的分界

| 情形 | execution | 原生操作 | 目标/身份 | 必需 transition |
| --- | --- | --- | --- | --- |
| 明确 spawn failed retry | 同一 attempt | `spawn_agent` | 同 task ref/name；尚未创建身份 | `confirmed_spawn_failure_retry` |
| 平台恢复 | 同一 attempt | `followup_task` | 同一 confirmed target | 不创建 D2 transition；由 WP-04 recovery 记录 |
| 结果补交 | 同一 attempt | `followup_task` | 同一 confirmed target | 不创建 D2 transition；只补交 outcome |
| business resume | 新 attempt | 默认 `followup_task` | 同一 Agent 可继续；新 task ref、无新 task name | blocker/decision/rejection/范围变化原因 |
| replacement | 新 attempt | 新 `spawn_agent` | 新 Agent、新 task ref、新 task name | replacement reason，旧 unknown 时还需接受重复风险 |

replacement 不是 failed retry 的同义词，也不是 platform recovery 的后备自动路径。新 attempt 从不复用旧 attempt 的结果地址或 identity mapping；旧 unknown 不能被改写为 failed 以方便 replacement。

### 5.3 三类预算和不相互消费

现有机器语义固定三类独立计数：`spawn_retry_count`、`recovery_count`、`correction_count`，每类上限为 2。D2 只定义其与派发/交付物的边界：

| 预算 | 消费时点 | 上限后的事实 | 不得影响 |
| --- | --- | --- | --- |
| spawn retry | 同-attempt retry 在原生 spawn 前被原子认领时 | 第二次 retry 再可靠 failed：关闭该 execution，work item `decide_disposition` | recovery、correction、business resume 次数或 business result |
| platform recovery | WP-04 在同一 execution 的 follow-up 前认领 | 同 target/same attempt 不再恢复 | spawn retry、correction、attempt 编号 |
| result correction | WP-04 对无合法 outcome 的同一 execution follow-up 前认领 | `result_protocol_status=exhausted + manual_review` | spawn/recovery 预算或 business failed |

首次 spawn 不消耗 retry。调用前校验/CAS 失败不消耗任何预算。已经认领的 native 调用即使返回 failed 或 unknown 也不回退预算。business resume 和 replacement 不另设固定次数上限：它们需要明确 transition reason 和父 Agent处置；未知调用的 replacement 每次都要重新明确接受重复风险。

## 6. success、failed、unknown 与 follow-up

调用观察描述的是原生调用，不是业务结果。`unknown` 只在调用已经发生但无法确认结果时使用；`null` 表示尚未观察到调用。任何表中写的 `parent_action` 都是待办提示，不能代替 disposition。

| 场景 | success | failed | unknown |
| --- | --- | --- | --- |
| initial spawn / retry | 有精确身份才可 running；无身份为 `not_started + reconcile` | 仅可靠确认未创建时进入同-attempt retry；预算耗尽后停止该 execution，不写 business failed | `not_started + unconfirmed + reconcile`；保留 ref，禁止同 attempt 重发/关闭 |
| normal follow-up | 清理通信 pending，不改 execution 或预算 | 同左，仅记录最小调用事实 | 同左；不推导 delivery/读取/处理状态 |
| platform recovery follow-up | 保持 stopped/error，等待精确启动 | 按 recovery 预算进入授权/耗尽状态 | reconcile，禁止自动重发 |
| result-correction follow-up | 只授权补交结果，等待启动或合法 outcome | 按 correction 预算重试或 manual review | reconcile，禁止自动重发 |
| business-resume follow-up | 新 attempt `not_started + wait`，仍等精确启动 | 新 attempt 标为 `resume_delivery_failed` 后关闭；work item `decide_disposition`，不写 business failed | 新 attempt `not_started + reconcile`；不关闭、不重发 |

`spawn failed` 必须来自有限响应适配器的可靠失败事实，并确认没有 Agent 被创建；不能从报错文本、静默、超时或缺失 PostToolUse 推断。`spawn unknown` 既不允许 retry，也不允许把任务视为无效。follow-up 的 `failed`/`unknown` 同样不证明子 Agent没有收到、没有处理或没有产生迟到 outcome。

## 7. 抽象回放：omni-memo 类型的未知派发后业务继续

仓库资料只说明本轮不修复 `omni-memo` 对话，未提供完整真实 transcript、Agent ID、调用响应或任务正文。以下回放是一个**抽象契约案例**，用于检验 D2，不声称描述实际对话。

1. 父 Agent 为抽象 work item `W` 生成 attempt 1。其 TaskContract 指定目标、范围、禁止范围、完成条件和证据；deliverable contract 要求正式 outcome，并引用这些条件。生成 `task_ref=R1` 与带 R1 的 task name。
2. `spawn_agent` 调用已发生，但 PostToolUse 没有可确认响应。20 分钟对账后，attempt 1 为 `not_started + spawn_observation=unknown + identity_status=unconfirmed + parent_action=reconcile`。这不是 failed，R1 和完整 PreparedContract 必须保留用于迟到绑定。
3. 父 Agent 因业务时效决定继续，明确记录 `transition={from_attempt:1, reason_code:unknown_duplicate_risk_accepted, authorized_by:parent, duplicate_risk_accepted:true}`。它创建 attempt 2，重新验证新的 TaskContract/deliverable contract，生成 R2 和新 task name，通过新 Agent replacement spawn。
4. attempt 2 启动后，attempt 1 的迟到 `SubagentStart` 以 R1 到达。系统将其绑定回 attempt 1，而不是当前 attempt 2，并设置 duplicate；两个 Agent的可能副作用和 outcome 都保留。
5. reviewer 不能凭「attempt 2 较新」选择。父 Agent显式 `select_attempt`，对仍运行的未选 attempt 仅返回精确 interrupt target；中断 unknown/failed 时不提前 tombstone。最终被选 attempt 的 complete 仍需 reviewer accept，才可 close work item。

该案例验证：派发 unknown、replacement 原因、task ref、交付物和父验收各自有独立证据边界。它没有假定缺失的原始对话内容或任何实际业务结果。

## 8. 与现有工作包的迁移关系

| 来源 | D2 采用/收敛 | D2 不改变或留给后续 |
| --- | --- | --- |
| D1 | 四层对象、unknown/attempt/duplicate/关闭不变量 | 不新增第五层对象或新的关闭动作 |
| WP-03 | TaskContract 生成、task ref/name、PreparedContract、精确 spawn 身份绑定 | 不恢复正文解析、同名/唯一候选匹配或 unknown 自动 retry |
| WP-04 | operation type、pending action、business resume、同 target 串行和三类预算 | 具体 Hook 事件转换、20 分钟对账和 interrupt 收口由实施/D4 完成 |
| WP-05 / D3 | TaskResult、结果文件、冲突保护、accept/reject/close | 正式 outcome 存储、验收状态机和 disposition API 的细节由 D3 冻结 |
| WP-06 / D4 | replacement 是新 attempt、unknown 保留、duplicate 后显式选择 | 平台观察、等待、reconcile、tombstone 和多 attempt 关闭时序由 D4 冻结 |
| D5 / D6 | 可显示 contract digest、transition、预算和交付物引用 | 诊断视图格式、兼容策略和分批实施顺序由 D5/D6 决定 |

迁移时应先让新 dispatch generator 产生此逻辑信封，再让 StateStore/PreparedContract 消费其最小字段。旧平面 `status`、自由文本 mode、正文 ID 要求和以 ACK/长度判定完成的路径不能作为兼容输入重新进入主路径。

## 9. 未决问题与验证边界

### 未决问题

1. `deliverable_contract` 最终是 TaskContract Schema 的受控嵌套字段、独立 Schema，还是仅由生成器/StateStore 共享的规范化投影，留给 D6 基于 D3 的 outcome 接口决定。无论落点如何，不能重复定义 TaskResult 或引入版本字符串作为业务门禁。
2. `completion_condition_refs` / `evidence_requirement_refs` 应使用数组索引还是规范化文本摘要，需在实施前根据契约编辑和兼容迁移风险决定；两者都必须可稳定回指本 attempt 的原字段。
3. business resume 的新 `task_ref` 与「沿用原 Agent task name」的双重关系需在 D4 的事件关联设计中落到明确数据结构：新 spawn 用 task name ref，same-Agent resume 用 target + claimed action 的 `resume_task_ref`，不得把 origin task name 错当新 attempt 身份。
4. reviewer 是否需要在 disposition 中记录人类/Agent 标识、以及 artifact expectation 的 `kind` 是否需要固定小枚举，属于审计展示而非 D2 的最小机械边界。

### 未执行验证

本文是设计文档交付，未修改运行时代码、Schema 或测试。因此未执行单元测试、`py_compile`、Plugin validator、Skill validator 或真实插件对话测试。完成后只需进行本地文件回读与变更范围检查；运行时验证应在 D6 定义实施切片后执行。
