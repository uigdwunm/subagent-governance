# D1 工作项收敛协议

## 1. 文档状态与范围

- 工作项：D1「工作项收敛协议、对象边界和状态不变量」。
- 依据：`docs/redesign-workstream-map.md`、`docs/project-function-inventory.md`、`docs/optimization-plan.md`、WP-01、WP-03、WP-05、WP-06，以及 `schemas/task-contract-v1.schema.json`、`schemas/task-result-v1.schema.json`、`schemas/governance-semantics.schema.json`。
- 本文冻结设计语义，不实现运行时状态机。
- 本文只修改开发仓库中的设计文档；不修改代码、Schema、测试、稳定发布源、运行缓存或外部对话。

当前重设计把一个业务目标和一次执行明确分开。`task_id` 标识稳定的业务目标，`attempt` 标识该目标的一次正式执行结果边界；Agent、工具调用和平台观察只是执行事实，不能取代业务对象。

## 2. 现状证据与问题

### 2.1 已确认的结构性问题

主盘点和 WP-01～WP-06 共同确认当前旧路径存在以下混合：

1. 一个平面 `status` 同时表达 Agent 是否运行、原生调用是否成功、子 Agent 业务结果和父任务下一步动作。
2. 自由文本、ACK/长度/关键词和任务 ID 被用于推断业务完成度；这越过插件的机械校验边界。
3. `spawn_agent` 的 success、failed、unknown 与身份确认被混为一件事，导致 unknown 被错误当成失败或成功，或因时间经过被删除。
4. `blocked`、`failed` 和 `complete` 被误作任务关闭；其中前两者只结束当前执行，complete 也还需要父 Agent 验收。
5. 迟到启动、旧 unknown attempt 和替代执行可能因弱匹配覆盖当前 attempt，无法解释重复副作用。
6. SessionEnd、时间窗口和通用裁剪可能删除仍需父 Agent处理的目标；明确关闭和 tombstone 的责任不清晰。

### 2.2 现行材料提供的稳定证据

- `governance-semantics.schema.json` 已固定 `execution_status`、`spawn_observation`、`identity_status`、`platform_observation`、`business_result`、`acceptance_status`、`result_protocol_status`、`result_storage_status`、`parent_action` 和三类计数。
- `task-contract-v1.schema.json` 把目标、背景、范围、完成条件、证据要求和上下文策略作为契约输入；不再把 `protocol`、自由文本 `mode` 或独立 `child_agents` 授权作为权威字段。
- `task-result-v1.schema.json` 把 `complete|blocked|failed|needs_decision` 作为结构化业务结果；blocked、failed、needs_decision 各有必需场景字段，`evidence[]` 可以为空。
- WP-03 要求 `task_id + attempt -> task_ref -> task_name` 的精确绑定，unknown 不得自动重派；替代执行必须新建 attempt 和新 task ref。
- WP-05 要求结果先独立文件原子写入、回读验证，再关联 StateStore；同一 attempt 的不同合法结果不得覆盖原结果。
- WP-06 要求 `action_required` 不受 recent-activity 时间窗口影响，明确关闭才生成 tombstone，tombstone 有效期间不得让迟到事件复活任务。

## 3. 四层对象模型

### 3.1 `work_item`：稳定的业务目标

`work_item` 是父 Agent希望最终解决的一个业务目标，不是某个 Agent、对话轮次或工具调用。

稳定身份和责任：

- 身份：`task_id`；不得因恢复、替代执行或会话重启改变。
- 内容：目标摘要、当前契约摘要（objective、work/forbidden scope、completion conditions、evidence requirements、resolved mode）和相关 task 引用。
- 关系：拥有一个或多个 `execution`；`current_attempt` 是父 Agent显式选择的当前执行，不等于“最新执行”。
- 业务收敛：由一个被接受的 complete 结果、父 Agent/用户明确关闭，或明确无法继续且已完成关闭处置实现。
- 持久性：未解决时持续保留；明确关闭后保留最小 tombstone，不能因超时、SessionEnd、容量或 unknown 自动消失。

`work_item` 不保存完整 dispatch prompt、完整对话、平台响应历史或所有通信正文，也不拥有 Agent DAG、batch、wave 或后台调度器。

### 3.2 `execution`：一次正式执行边界

`execution` 是一个 `work_item` 的 `task_id + attempt` 对应的一次正式执行。一次普通平台恢复在同一 attempt 内，不产生新 execution；业务继续、原 Agent无法继续或替代执行产生新 attempt。

核心字段分组：

| 维度 | 字段/事实 | 语义 |
| --- | --- | --- |
| 执行 | `execution_status` | `not_started | running | stopped | interrupted` |
| 派发 | `spawn_observation`、`spawn_retry_count` | 原生派发结果和有限的明确失败重派次数 |
| 身份 | `identity_status`、Agent ID、canonical path、task ref | 是否已精确绑定执行者 |
| 平台 | `platform_observation`、来源和时间 | 最近一次可观察的平台事实 |
| 业务 | `business_result` | 子 Agent提交的结构化业务结果，或 JSON `null` |
| 结果协议 | `result_protocol_status` | `null | needs_correction | valid | exhausted` |
| 结果存储 | `result_storage_status`、result reference/digest | 正式结果是否可可靠读取 |
| 验收 | `acceptance_status` | 仅 complete 结果使用：`null | pending | accepted | rejected` |
| 父动作 | `parent_action` | 根据已持久化事实派生的下一步，不表示动作已完成 |
| 其他 | `result_conflict`、`recovery_status`、三类计数 | 冲突、恢复授权和预算事实 |

新 execution 固定初值来自机器语义：`not_started/null/unconfirmed/null/null/null/null/false/null/null`，计数均为0。字段尚未发生时用 JSON `null`；调用已经发生但无法确认时才用 `unknown`。

### 3.3 `outcome`：execution 提交的业务结果

`outcome` 是子 Agent针对一个 execution 提交的结构化 `TaskResult`，唯一由子 Agent声明业务事实。基础字段为：

`task_id`、`attempt`、`business_result`、`result`、`evidence[]`、`remaining[]`、`suggested_parent_next_step`。

场景字段：

- `complete`：只提交结果，不附加父验收结论。
- `blocked`：`blocker`、`attempted[]`、`required_to_resume`。
- `failed`：`failure_reason`、`attempted[]`、`retry_conditions`。
- `needs_decision`：`decision_question`、`options[]`、`recommendation`。

插件只检查类型、枚举、长度、引用和基本组合。它不判断结果真实性、证据是否“充分”、建议是否正确，也不把平台错误伪装成业务 failed。

### 3.4 `disposition`：父 Agent 的显式处置

`disposition` 是父 Agent在读取 execution/outcome 后作出的业务决定，最小结构为 `task_id`、`attempt`、`action`、`reason`。允许：

- `accept_result`：接受合法 complete，并在同一原子处置中关闭 work item；不得留下“已接受但仍开放”的中间业务状态。
- `reject_result`：保留原结果，要求父 Agent决定继续、纠正或关闭。
- `select_attempt`：在重复执行候选中选择一个 current attempt，并关闭/处理中止其他候选。
- `close_task`：在没有 accepted complete 的其他显式放弃、取消或接受失败/阻塞场景中明确结束整个 work item，生成 tombstone；不是 `parent_action` 值，也不能只关闭某个 execution。

`parent_action` 是系统根据事实给出的待办提示，`disposition` 是父 Agent已经做出的决定；二者不可互换。`complete` 默认 `accept_result`，`blocked|failed` 默认 `decide_disposition`，`needs_decision` 默认 `ask_user`。

F6 实施后，formal outcome disposition 固定写入 `execution.parent_disposition_record` 和 `work_item.last_parent_disposition`。创建后续 execution 所需的业务增长授权是另一类对象：`growth_authorization` 只允许 `resume_business|spawn_replacement`，最近一条写入 `work_item.last_growth_authorization`；它不能代替 accept/reject/close/select。完整可执行字段以 governance Schema 为唯一锚点，盘点见 `F6-canonical-record-schema-implementation.md`。

## 4. 状态不变量

以下不变量是 D2-D6 的共同验收条件：

1. **身份不变量**：任何启动、结果或通信事件必须精确绑定 `task_id + attempt` 与 task ref/Agent target；不得按同名、最近时间、唯一候选或当前 attempt 猜测。
2. **执行不变量**：`execution_status=running` 只能由精确 `SubagentStart` 或允许该 operation 的精确启动证据产生；普通消息、弱身份和 interrupt 不授权启动。
3. **结果不变量**：`business_result` 只能由合法正式 outcome 写入；平台 success/failed/unknown、Agent stopped 或 list_agents 状态都不能代替 outcome。
4. **验收不变量**：只有合法 complete 使 `acceptance_status=pending`；blocked、failed、needs_decision 和无结果保持 `null`。complete 不自动等于 accepted。
5. **存储不变量**：`result_protocol_status=valid` 不保证存储成功；存储故障独立写 `result_storage_status=unavailable`。结果文件一旦成为权威，不得被不同内容覆盖。
6. **attempt 不变量**：同一 attempt 是单一正式结果边界；平台恢复保持 attempt，business resume 或替代执行递增 attempt。已关闭 attempt 的结果文件不可重新打开或覆盖。
7. **unknown 不变量**：unknown 只能由已发生但无法确认的调用/观察产生；不得自动映射为 success、failed、stopped、interrupted，不得因时间经过删除或重派。
8. **父动作不变量**：`parent_action` 只表示下一步，不表示调用、验收或关闭已完成；调用进行中由 `pending_action`/PreparedContract 表达。
9. **保留不变量**：action-required 不受 recent-activity 窗口影响；未解决 work item 不因会话结束、时间或容量静默清理。
10. **关闭不变量**：只有显式 disposition 或明确用户放弃/取消意图可以关闭；关闭必须与 tombstone、Agent映射清理和精确结果保留/清理在同一锁内完成。
11. **重复不变量**：迟到 unknown Agent 与其他候选冲突时记录 `duplicate_execution=true`，进入 `resolve_duplicate`；不得自动中断、自动选择或覆盖结果。
12. **单向不变量**：tombstone 有效期间迟到启动/结果只能被识别和拒绝，不能复活已关闭对象。

## 5. 关键状态与处置规则

### 5.1 success / failed / unknown 的统一解释

“success”只表示对应原生调用未明确失败；它不等于 Agent 已启动、消息已处理或业务已完成。“failed”只表示调用明确失败，是否可重试由具体 operation 和预算决定。“unknown”表示调用已发生但结果不可确认，必须保留对账责任。

| 观察 | execution | identity | parent action | 允许的下一步 |
| --- | --- | --- | --- | --- |
| 首次 spawn success，无身份 | `not_started` | `unconfirmed` | `reconcile` | 等待精确启动/身份 |
| 首次 spawn failed，确认未创建 | `not_started` | `unconfirmed` | `retry_spawn` | 有界同-attempt 重派 |
| spawn unknown | `not_started` | `unconfirmed` | `reconcile` | 禁止自动重派；迟到绑定或显式新 attempt |
| follow-up success | 保持原状态 | 保持 | `wait` 或 operation 固定动作 | 等待精确启动/结果 |
| follow-up failed | 保持原状态或关闭未启动 resume attempt | 保持 | `ask_user`/`decide_disposition` | 由预算和父处置决定 |
| follow-up unknown | 保持原状态 | 保持 | `reconcile` | 不重发，等待迟到证据 |

### 5.2 blocked、failed、needs_decision

- `blocked`：当前 execution 写 `stopped + business_result=blocked + parent_action=decide_disposition`，work item 仍未解决且进入 action-required。解除阻塞后必须由父 Agent显式创建新 attempt；汇报阻塞不等于关闭。
- `failed`：只结束当前 execution，不关闭 work item。父 Agent可接受失败并关闭、调整条件后创建新 attempt，或询问用户；不得把失败报告当成目标已处理。
- `needs_decision`：当前 execution 停止，`parent_action=ask_user`；用户选择前不得自动恢复、替换或关闭。用户决定继续时创建新 attempt，决定放弃时显式 close。
- `complete`：写入后 `stopped + acceptance_status=pending + parent_action=accept_result`。父 Agent验收 accepted 才能进入关闭路径；rejected 保留结果并进入 `decide_disposition`。

### 5.3 replacement 与重复执行

新 attempt 分为 business resume 与 replacement，两者都不是普通平台恢复的别名。已有 blocked/failed/needs_decision 或 rejected complete 后决定继续时属于 business resume，可在精确条件下沿用原 Agent；只有父 Agent/用户明确接受重复执行风险、原 Agent客观无法继续或无法接收 follow-up、用户明确要求更换、原 Agent方向错误，或身份冲突需要隔离时才属于 replacement。

规则：

1. 所有新 attempt 必须新建 task ref 和结果地址。business resume 可以通过精确 target + claimed lifecycle action 沿用原 Agent及其 origin task name；replacement 必须通过新的 `spawn_agent` 创建新 Agent和新 task name。两者都不得复用旧 attempt 的结果地址或身份映射。
2. 旧 unknown attempt 保留原绑定和结果边界；不得改写为 failed，也不得把新 attempt 的启动或结果写回旧 attempt。
3. 迟到 Agent 与其他未关闭候选并存时，全部候选分别保留，设置 duplicate 标记并进入人工 `select_attempt`；不自动中断任何候选。
4. `select_attempt` 原子切换 current attempt；已停止/中断/未确认的未选候选立即关闭并生成 tombstone，仍运行的候选只返回精确 interrupt target，待父 Agent成功中断后关闭。failed/unknown 中断不能提前关闭。
5. 只有全部未选候选可靠关闭后，才能清除 duplicate 标记，所选候选回到其正常等待/验收链。

### 5.4 关闭与 tombstone

关闭是 work item/execution 的显式业务处置，不是一个运行状态值，也不是 `parent_action=end`。可关闭来源包括：父 Agent接受 complete 后完成目标；父 Agent接受失败并放弃；用户放弃/取消；选定 attempt 后关闭未选候选；其他明确且有理由的父处置。

关闭事务必须：

- 在同一 StateStore 锁/CAS 内写关闭事实、清空 `parent_action`、处理身份映射和生成最小 tombstone。
- tombstone 保存 `task_id + attempt`、Agent ID/canonical path、task ref、最后状态、关闭原因和关闭时间。
- 保留7天；期间拒绝迟到事件导致的复活。到期只精确删除匹配结果和 tombstone，删除失败则保留 tombstone。
- 不为“超时”“沉默”“SessionEnd”“容量不足”自动生成关闭事实。

## 6. omni-memo 抽象回放场景

仓库只记录“本轮不修复 `omni-memo` 对话、不修改其任务状态”，没有该对话的完整 transcript。因此以下是可审查的抽象回放契约：它们复用已确认的平台事实类型，不声称补写缺失的对话细节。每个场景都应在后续 D2-D4/真实测试中用实际事件替换占位文本。

### 场景 A：正常完成但必须父验收

1. 父 Agent创建 `work_item W`，spawn attempt 1；PreToolUse 消费契约，SubagentStart 精确绑定，execution 进入 `running`。
2. 子 Agent提交合法 `outcome(business_result=complete)`，结果文件写入并回读成功。
3. execution 变为 `stopped + valid + available + acceptance_status=pending + parent_action=accept_result`。
4. 父 Agent核对证据后提交 `disposition=accept_result`；验收与关闭 work item 在同一原子处置中完成并生成 tombstone。
5. 若相同 outcome 重放，幂等接受；若内容不同，保留 A，设置 `result_conflict=true + manual_review`，不覆盖。

验收重点：complete 不自动关闭；结果协议和父验收分层；关闭必须可追溯。

### 场景 B：平台 unknown、迟到启动与 replacement

1. spawn 或 business resume 调用已发生但返回 unknown；attempt 保持 `not_started`（或原状态）、身份未确认、`parent_action=reconcile`，禁止自动重发。
2. 后续精确 `SubagentStart` 以 task ref/target 绑定旧 attempt，进入 `running`；若旧 Agent和父 Agent已授权的新 attempt 同时存在，设置 duplicate。
3. 父 Agent不能凭“最新”选择；提交 `select_attempt` 后，所选 attempt 保持正常链，未选运行候选返回精确 interrupt target，已停止/未确认候选生成 tombstone。
4. 若旧 unknown 永远无可靠身份，仍不得按时间删除；只有明确接受重复风险的 `growth_authorization=spawn_replacement` 和合法 transition 才能建立 replacement。

验收重点：unknown 不是失败；replacement 是新 attempt；迟到事件只能绑定自己的边界。

### 场景 C：blocked/failed 后业务继续或关闭

1. attempt 1 停止并提交 `blocked` 或 `failed` outcome；分别保存阻塞条件/失败原因，设置 `parent_action=decide_disposition`，work item 进入 action-required。
2. 父 Agent可选择：补充决策并创建 attempt 2（business resume/新 spawn）；接受失败并 `close_task`；或询问用户。任何选择都必须留下 disposition reason。
3. attempt 2 成功产生 complete 时，只对 attempt 2 做验收；attempt 1 的结果独立保留，不能被覆盖或重新打开。
4. 若业务继续调用 unknown，attempt 2 保持 reconcile；不得以“原任务已 blocked/failed”为理由关闭或自动再发。

验收重点：blocked/failed 结束执行而不结束目标；业务继续必须显式新边界；关闭与结果状态分离。

## 7. 与 WP-01～WP-08 的迁移关系

| 工作包 | D1 冻结的迁移接口 | 不得重新引入 |
| --- | --- | --- |
| WP-01 | 以三个 Schema 和机器语义作为枚举/字段单一来源；TaskContract、TaskResult、AttemptState 采用四层模型 | 平面 status、protocol 版本门禁、正文语义验收、自由 text result |
| WP-02 | StateStore 每 session 一份最小持久状态；按 attempt 保存上述维度、pending/结果引用/关闭事实；锁内 CAS | 任务数据库、完整事件历史、通用 terminal 裁剪、隐式关闭 |
| WP-03 | `task_id + attempt -> task_ref -> task_name`；PreparedContract 只短期存在；精确身份绑定 | 同名/同轮候选猜测、unknown 自动重派、独立 prepared_ref |
| WP-04 | operation type 与 pending_action 两阶段接口；恢复、纠正、business resume、interrupt 的 success/failed/unknown 分开 | 根据工具名/正文猜操作、跨操作消耗预算、unknown 自动重发 |
| WP-05 | `outcome` 独立 result 文件；先写结果再关联 StateStore；父 disposition/验收显式 | StateStore 内嵌完整结果、不同内容覆盖、complete 自动 accepted |
| WP-06 | action-required/recent-activity 派生视图；Session/Stop/等待/多 attempt/tombstone 使用 D1 不变量 | 时间驱动清理、blocked/failed 自动关闭、旧 attempt 复活 |
| WP-07 | 诊断只读派生四层对象；group 仅保存 task 引用和 required 关系，不拥有状态机 | 完整编排图、组级执行状态、诊断副作用 |
| WP-08 | 新主路径稳定后退役旧 status、自由文本、弱匹配、旧 fixture 和文档残留；记录真实平台 not_checked | 以本地测试代替真实平台证据，或提前发布稳定源/缓存 |

迁移原则是“新消费者先接管、旧消费者再原子退役”。在 D1 之后，D2-D4 只能实现接口，不得自行增设第四种业务对象、替代状态枚举或新的关闭动作。

## 8. D2-D4 接口约束

### D2：派发、交付物和重复预算

- 输入必须是结构化 TaskContract；输出必须包含 task_id、attempt、task_ref、task_name、首句和可验证完成条件。
- `requested_mode=auto` 只在生成阶段解析为 resolved mode；运行时不重新分类。
- 同-attempt spawn retry 只处理明确 failed 且确认未创建；unknown 不进入 retry。
- 每个交付物必须可映射到 outcome 基础字段或场景字段；不把 evidence 关键词、长度或卡片格式当验收规则。

### D3：结果与父处置

- outcome 是唯一业务结果来源；D3 不从平台观察、自由文本或 Stop 原因推断 business_result。
- 结果协议、结果存储、父验收和 disposition 必须分列；complete 只触发 pending acceptance。
- 结果冲突只保存冲突摘要和首次时间，不建立第二候选结果库；处置在同一锁内清理冲突标记。
- `accept_result` 必须原子完成 complete 验收与 work item 关闭；`close_task` 只处理其他明确结束整个 work item 的场景。二者都必须有明确 reason，并与 tombstone/结果清理规则一致。

### D4：平台观察、恢复和 replacement

- platform observation 只记录可观察事实；`unknown` 不得被重写成失败、停止或中断。
- platform recovery 保持同一 attempt；business resume/replacement 创建新 attempt；interrupt 只结束执行，不自动关闭目标。
- 只有精确 task ref、attempt、Agent target 和 pending/last lifecycle operation 能授权迟到启动绑定。
- list_agents、interrupt_agent、SubagentStart 的平台限制必须标为证据边界；插件不能声称修复桌面重启或平台投影。

## 9. 未决问题

以下问题不阻塞 D1 的语义冻结，但必须在相应阶段或真实测试中取得证据：

1. 真实 `spawn_agent` 是否接受 D2 生成器映射的原生参数，以及 SubagentStart 是否始终暴露可用 task name/task ref。
2. 真实 Agent ID/canonical path 和 `list_agents.agent_status` 的所有形态是否已由适配器覆盖，尤其是重启后的 `pending_init`、空列表和对象标签。
3. `business_resume` 在不同 Provider/上下文策略下是否可靠保持原 Agent上下文；若不能，何时必须 replacement。
4. 正式 TaskResult 如何从真实 SubagentStop/mailbox 到达，迟到结果与启动事件的顺序是否可稳定重放。
5. 父 Agent提交 disposition 的可靠入口、用户取消语义和 close reason 的最小审计要求是否需要平台级字段。
6. 多个未决 unknown 同时形成重复执行时，父 Agent展示和用户选择的最大候选数如何限定，而不改变业务权威模型。
7. `omni-memo` 原始三类对话回放材料尚未进入仓库；后续真实测试需补充脱敏事件序列和结果证据，不能以本文抽象场景冒充平台验收。
8. 开发仓库、稳定源和运行缓存的真实版本边界、Hook trust、Provider/Session 行为仍是 WP-08 的 `not_checked` 项。

## 10. D1 完成判定

D1 在以下条件满足时完成：

- 四层对象和字段责任已冻结，且与三个 Schema、WP-01、WP-03、WP-05、WP-06 的已确认语义一致。
- success、failed、unknown、blocked、replacement、重复执行和关闭路径均有明确规则。
- 三个 omni-memo 抽象回放覆盖正常完成、unknown/replacement、blocked/failed 继续或关闭，并明确证据缺口。
- WP-01～WP-08 迁移关系和 D2-D4 接口约束已写明，未决问题已列出。
- 本次仅新增本设计文档，未修改运行时代码、Schema、测试、稳定发布源、运行缓存或外部对话。

本文件是后续 D2、D3、D4 的语义前置；任何实现若与本文冲突，应先提出协议冲突并更新设计，不得在代码中静默发明新状态。
