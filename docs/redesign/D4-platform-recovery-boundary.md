# D4 平台观察、恢复与 replacement 边界

> 2026-08-14 状态：本文保留为前期设计证据，其中由精确 SubagentStart
> 建立 running/confirmed 的规则已被平台能力切片 1 supersede。当前 Start
> 仅是 unbound advisory observation，不得作为 correctness authority。

## 1. 状态、范围与前提

- 工作项：D4「平台观察、恢复和 replacement 边界」。
- 前置设计：`docs/redesign-workstream-map.md`、D1、主功能盘点、优化计划、WP-04、WP-06、`docs/restart-interruption-reconciliation.md` 和 `schemas/governance-semantics.schema.json`。
- 本文冻结 D1 四层模型下的平台观察、身份确认、恢复和重复执行语义；它不是运行时实现方案，也不修改现有 Schema。
- 本次只新增本开发仓库的本文件。不修改运行时代码、Schema、测试、稳定发布源、运行缓存、Hook trust、外部对话或其他项目。

本文只使用仓库已记录的事实类型。特别是 `omni-memo` 没有完整可复核的对话正文、平台调用响应或事件时序；本文的回放是抽象契约，不补写或推定缺失的真实对话事实。

## 2. D1 四层模型中的责任边界

```text
work_item    稳定业务目标；决定是否仍需解决
execution    task_id + attempt 的一次正式执行边界
outcome      子 Agent 提交的结构化业务结果
disposition  父 Agent 的显式验收、选择或关闭决定
```

平台工具、Hook 事件、Agent ID、canonical path 和调用响应只为 `execution` 提供可观察事实。它们不得生成 `outcome`，不得替代 `disposition`，也不得因“看起来已结束”关闭 `work_item`。

### 2.1 三个相互独立的维度

| 维度 | 权威含义 | 可写入的字段 | 明确不表示 |
| --- | --- | --- | --- |
| platform observation | 某次原生调用或目标范围查询所能确认的平台事实 | `spawn_observation`、`platform_observation`、`last_lifecycle_operation.call_observation`、最小来源/时间/目标摘要 | Agent 已真正开始、消息已处理、业务完成、业务失败 |
| execution status | 已被精确证据确认的执行生命周期投影 | `execution_status=not_started|running|stopped|interrupted` | 业务目标是否已解决，或某个调用是否成功 |
| identity status | 事件或工具 target 是否精确归属某个 `task_id + attempt` | `identity_status=unconfirmed|confirmed`、`task_ref`、Agent ID、canonical path、精确映射 | 目标正在运行、目标存在、事件一定是最新 attempt |

`business_result` 只由合法正式 `outcome` 写入；`acceptance_status` 只由 complete outcome 和父处置推进。平台异常始终保持 `business_result=null`，不能伪造 `failed` 或 `needs_decision`。

### 2.2 证据强度和禁止推断

1. `success` 表示对应原生调用没有明确失败，不能推出投递、启动、停止或业务结果。
2. `failed` 表示调用明确失败；它不能回写为 Agent 不存在、已有工作已丢失或业务失败。
3. `unknown` 表示调用已经发生或观察尝试已经发生，但不能确认结果。它保留对账责任，不能因超时、重启、空列表或新 attempt 自动变成任一确定状态。
4. `SubagentStart` 只有在精确身份映射或精确 lifecycle 凭证授权时，才确认 `running`；普通消息、同名 Agent、最近时间或唯一候选不构成启动证据。
5. `list_agents` 的单次投影只说明其查询范围内的观察。`pending_init`、错误、缺项或空列表不自动推出 `not_started`、`stopped`、`interrupted`、调用失败或没有副作用。
6. `interrupt_agent.previous_status=running` 只确认调用前目标被观察为运行；`not_found` 只确认调用时精确 target 不存在。二者都不单独确认中断已经完成。

插件可记录、关联和提示这些事实，不能修复 Codex 进程重启、thread rollout 中断、原生活动列表投影、消息投递或任意 worker thread 的持久化终态。

## 3. 最小持久化契约

### 3.1 execution 的平台事实

每个 execution 至少保留 D1 已定义的字段，并为每次需要对账的生命周期操作保留一条有界 `pending_action` 或 `last_lifecycle_operation`。必要字段由现有 machine semantics 提供：

| 对象 | 最小字段 | 用途 |
| --- | --- | --- |
| 初始派发 | `task_id`、`attempt`、`task_ref`、`spawn_observation`、`identity_status`、`execution_status`、`spawn_retry_count` | 把一次 spawn 观察与稳定 execution 绑定 |
| 精确身份 | Agent ID/canonical path、`agents[target]={task_id,attempt}`、`task_ref` | 限制后续事件只写回同一 attempt |
| pending action | `target`、`task_id`、`attempt`、`task_ref`、`operation_type`、`phase`、`tool_use_id`、时间、reason | 将发送前授权与 PostToolUse/迟到启动精确关联 |
| lifecycle 记录 | `operation_type`、`target`、`tool_use_id`、`call_observation`、`target_observation`、`native_status`、时间、reason | 让 success/failed/unknown 在 pending 清理后仍可对账 |
| list 观察 | 查询 target/range、适配后的有限状态、来源和时间 | 记录观察，而非将原始响应或完整 Agent 列表作为业务状态 |
| tombstone | `task_id`、`attempt`、task ref、已知 target、最后机械状态、关闭原因、关闭时间 | 阻止关闭后的迟到事件复活对象，并支持精确清理 |

不保存完整平台响应、消息正文、对话转录、投递/阅读状态或未经校验的错误文本。无发生事实用 JSON `null`；调用已发生但无法确认才写 `unknown`。

### 3.2 关联前提

任何会改变 execution 投影的事件必须满足以下之一：

1. 事件 target 与已确认的 Agent ID/canonical path 映射精确相等；或
2. 事件携带的 `task_ref`、`task_id + attempt` 与同 target 的 claimed `pending_action` 精确相等；或
3. pending 已在 PostToolUse 后清理，但同 target、同 task/attempt 的 `last_lifecycle_operation` 仍存在且 operation 允许该事件。

否则只可记录为未关联平台观察或拒绝，不能改写任何 execution。`current_attempt`、任务名相似性、时间接近和“当前只有一个候选”均不是关联规则。

## 4. 操作与观察状态矩阵

以下矩阵的“状态变化”只写 execution/platform/identity 投影；不隐含业务结果或关闭。调用前的 pending action 均须原子认领，计数在认领时消费，PostToolUse 不回退预算。

### 4.1 `spawn_agent`

| 观察 | execution / identity | platform 与下一步 | 禁止行为 |
| --- | --- | --- | --- |
| success，尚无精确启动 | `not_started` / `unconfirmed` | `spawn_observation=success`，`parent_action=reconcile` 或等待启动 | 不写 running，不假定 Agent ID 已确认 |
| failed，确认本次未创建 | `not_started` / `unconfirmed` | `spawn_observation=failed`，在 `spawn_retry_count < 2` 时 `retry_spawn` | 不写 business failed；不得重用已不确定的 task ref |
| unknown | `not_started` / `unconfirmed` | `spawn_observation=unknown`，`parent_action=reconcile` | 不自动重派，不把 attempt 删除或关闭 |
| 精确迟到 `SubagentStart` | `running` / `confirmed` | 正常观察，消费可消费的 spawn 凭证 | 不因先前 unknown 拒绝绑定 |

`spawn_retry_count` 上限为 2，仅适用于明确 failed 且可确认未创建的同一 attempt 派发重试。spawn unknown 绝不消耗为“可安全重试”的失败，也不能被重试覆盖；需要继续时走显式 replacement 新 attempt。

### 4.2 `followup_task` 的三种受治理用途

`followup_task` 的 native success 不决定操作类型；操作类型只来自已认领的 pending action。

| operation | 前提和预算 | success | failed | unknown |
| --- | --- | --- | --- | --- |
| `platform_recovery` | 同 Agent、同 attempt；`stopped + platform_observation=error`；最多 2 次 | 保持 `stopped/error`，等待精确启动 | 第 1 次 `awaiting_authorization + ask_user`；第 2 次 `exhausted + ask_user` | 保持 `stopped/error`，`reconcile`，保留 lifecycle；禁止重发 |
| `result_correction` | 同 attempt、无业务结果、协议要求补交；最多 2 次 | 保持 stopped，等待结果或启动 | 第 1 次 `correct_result`；第 2 次 `exhausted + manual_review` | 保持原状态，`reconcile`，禁止重发 |
| `business_resume` | 父处置已决定继续；创建新 attempt 和新 task ref；不变更原结果 | 新 attempt `not_started + wait`，等待精确启动 | 新 attempt 标为 `resume_delivery_failed` 的关闭事实，work item `decide_disposition` | 新 attempt `not_started + reconcile`，禁止对同 Agent自动重发 |

仅 `platform_recovery` 是“同 Agent、同 attempt”恢复平台执行通道。它在精确 `SubagentStart` 到达前不可写 `running/normal`。`result_correction` 只请求原 execution 补交结构化结果，不重新执行业务。`business_resume` 是已完成父处置后的业务继续，即便尝试原 Agent，也必须是新 execution。

### 4.3 `interrupt_agent`

interrupt 必须由父 Agent/用户提供精确 target，且受治理 target 须有先前认领的 interrupt 意图；无法可靠持久化时可以为安全而原生 fail-open，但必须报告治理记录不可靠。

| 观察或后续证据 | execution | parent action | 约束 |
| --- | --- | --- | --- |
| 调用 success 且适配器确认 target 已中断 | `interrupted` | `decide_disposition` | 不生成业务结果、不关闭 work item、不倒推出用户意图 |
| 调用 failed | 保持原状态 | 保持原动作或要求显式决定 | 不自动重试，不授权迟到启动 |
| 调用 unknown | 保持原状态 | `reconcile` | 保留 interrupt lifecycle；不写 interrupted |
| `previous_status=running` | 保持原状态 | `reconcile` | 是调用前观察，不是停止确认 |
| `previous_status=not_found` + 确认身份 + 既有精确空列表 + 已认领 interrupt | 可写 `stopped` | `decide_disposition` | 只在全部事实都相符时收口；不宣称 interrupt success |
| 后续精确 list 为 stopped/completed | `stopped` | `decide_disposition` 或正式结果链 | 不倒推 interrupt success |
| 后续精确 list 为 interrupted | `interrupted` | `decide_disposition` | 不关闭目标 |

interrupt 永远不授权 `SubagentStart`。已关闭或 tombstoned attempt 的迟到启动必须拒绝；unknown interrupt 后的 running/list error 只触发对账或显式决定，不创建自动恢复。

### 4.4 `list_agents` 和 `pending_init`/空列表

`list_agents` 是目标范围内的观察通道，不是创建、取消或业务完成通道。必须保存查询范围；只有 canonical target 或其他精确身份约束下的单一目标观察，才可影响该 attempt。

| 适配结果 | 可写事实 | 不可推断 |
| --- | --- | --- |
| running | 精确 attempt 可保持/写 `running`；`platform_observation=normal` | 之前 unknown 调用是 success，或业务仍健康 |
| errored | 已确认运行或已绑定 attempt 可写 `stopped + error`，按恢复预算进入 `recover`/`ask_user` | Provider 根因、业务失败、必须 replacement |
| stopped/completed | `execution_status=stopped`；有有效 outcome 则保留，无 outcome 进入结果协议缺口或 `decide_disposition` | complete outcome、已关闭、消息已投递 |
| interrupted/cancelled | `execution_status=interrupted`，`decide_disposition` | 谁导致中断，或业务失败 |
| `pending_init` | `platform_observation=unknown`，保留已有 execution 先验，`reconcile` | `not_started`、可重派、目标不存在 |
| 精确 target 空 `agents=[]` | 记录 target 当前 absent；结合已认领 interrupt 等严格条件可收口为 stopped | 未创建、已关闭、没有副作用，或 spawn/interrupt 的确定结果 |
| 查询失败、状态多标签/未知形状、非精确范围空列表 | `platform_observation=unknown` 或 error 的有限调用事实 | 任何 execution 终态或身份变化 |

重启后出现 `pending_init` 或精确空列表时，已有 `running/confirmed` 先验必须保留。平台投影不会撤销已记录的副作用风险；父 Agent只能继续等待/对账、使用受限重启恢复入口核验外部只读事实，或作出显式业务处置。

### 4.5 `SubagentStart`

| 匹配凭证 | 是否可写 `running` | 后续变化 |
| --- | --- | --- |
| 已确认精确 Agent target | 可以 | `identity_status=confirmed`；平台可写 normal；保持同一 attempt |
| claimed pending 的成功/unknown `platform_recovery`、`result_correction`、`business_resume` | 可以 | 记录 `start_observed_at`，待 PostToolUse 对账后消费凭证 |
| 已清理 pending，但精确 success/unknown lifecycle 记录 | 可以 | 消费相同 task/attempt/target 的 lifecycle 记录 |
| spawn success/unknown 的精确 task ref | 可以 | 完成身份绑定；unknown 不妨碍迟到启动 |
| failed lifecycle、interrupt、关闭 attempt、tombstone、弱匹配 | 不可以 | 保持原状态并标记 `reconcile`/拒绝；绝不复活 |

这套规则处理 PostToolUse 和 `SubagentStart` 乱序：启动先到时只在同一 claimed action 记录时间并写真实 running；PostToolUse 后仍保留调用观察。反之，success/unknown lifecycle 在被启动消费前不得因时间、重启或 SessionEnd 丢失。

## 5. 恢复、业务继续与 replacement

### 5.1 三种动作不是同义词

| 动作 | 条件 | Agent / attempt | 预算 | 结果边界 |
| --- | --- | --- | --- |
| platform recovery | 精确平台 error，原 execution 无业务终态 | 同 Agent、同 attempt | 每 attempt 最多 2；第 2 次须用户显式授权 | 保留同一结果边界；只恢复平台执行 |
| business resume | blocked/failed/已决 needs_decision/rejected complete 后，父任务明确决定继续 | 可先尝试同 Agent，但必须新 attempt、新 task ref | 不使用 spawn/recovery/correction 预算；每次需 `growth_authorization=resume_business` | 原 attempt 的 outcome 保留，新 attempt 独立产出 outcome |
| replacement | 原 Agent客观不可继续/不可接收、身份冲突、旧 unknown 需隔离、用户要求更换或父 Agent接受重复执行风险 | 新 Agent、新 attempt、新 task ref | 不绕过任何已耗尽预算；需 `growth_authorization=spawn_replacement` 和重复风险 transition | 与旧 execution 永不合并，等待 duplicate 对账/选择 |

platform recovery 的第 1 次可由既定流程自动执行；第二次只能在明确用户授权后认领。调用 unknown 已消费预算却不等于失败，不得再发。恢复调用 success/unknown 也不证明 Agent 已恢复；同一 canonical target 后续 exact `list_agents=errored` 会解决该 lifecycle，即使期间没有 Start/running，也按已消耗次数进入下一次授权或 exhausted。插件不解析错误文本来添加特殊 Provider 分支。

business resume 和 replacement 都递增 `attempt`，即使父 Agent选择同一 Agent。这避免把新业务工作、旧结果、迟到启动和副作用合并到一个结果边界。它们只能经显式 `growth_authorization` 与合法 transition 创建，不能因 `list_agents` 空、调用超时或普通消息自动发生。accept/reject/close/select 的 formal `parent_disposition_record` 是另一对象，不能承载这两个增长 action。

### 5.2 replacement 的最小授权记录

创建 replacement 前，增长授权与 transition 至少需要记录：

- 保持不变的 `task_id`，旧 attempt 与拟建新 attempt；
- 选择 replacement 的原因和可观察事实（例如明确 exhausted、目标不可接收、身份冲突），并区分事实与判断；
- 是否已知旧 execution 可能仍运行或已产生副作用；
- 父 Agent/用户对重复执行风险的明确接受；
- 新 task ref、新 target/Agent 的独立身份契约，以及旧 attempt 的 parent action。

当旧 attempt 仍为 unknown 或 running 时，新 attempt 与其并存，必须设置 `duplicate_execution=true + parent_action=resolve_duplicate`。这不是失败，也不是授权插件代为中断。父 Agent必须显式 `select_attempt`；未选且仍运行的 candidate 返回精确 interrupt target，成功或明确 terminal 观察后才可关闭。

## 6. 重启、迟到事件、重复执行与 tombstone

### 6.1 重启对账

应用重启、session 恢复、缺失 PostToolUse 和状态读取失败是观察不完整，不是业务终态。恢复时按以下顺序处理：

1. 保留未闭环 execution、pending/last lifecycle 和已确认 identity；不使用 recent-activity 时间窗口删除它们。
2. 5 分钟未认领 prepared action 仅可精确删除，不消耗预算；20 分钟 claimed 无 PostToolUse 写 `unknown` 并保留已消费预算和 lifecycle 事实。
3. 父 Agent等待或只对精确 target 调用 `list_agents`；明确运行继续等待，明确 errored 才进入同 Agent恢复预算。
4. `pending_init`、空列表、读取失败或不兼容形状进入 `reconcile`，不派发 replacement。
5. 对已有 `running/confirmed` 且具备受限外部只读 thread interrupted 证据的事故场景，可使用专门 reconciliation 入口核验已保存的 target、interrupt、list 和 thread 事实；成功只写 `interrupted + normal + decide_disposition`，不生成 outcome 或替代 Agent。

该入口是受控的本地事实核验，不让插件读取任意 worker 的 thread 状态，也不宣称恢复平台内部消息或执行。

### 6.2 迟到与幂等

| 事件 | 对账规则 |
| --- | --- |
| 相同精确事件重放 | 对相同字段与同一 task/attempt 幂等；不再次消费计数或创建 attempt |
| 同一 attempt 的不同平台观察 | 追加/替换最近最小 observation，不能覆盖正式 outcome、父处置或关闭事实 |
| 同一 attempt 的不同合法 outcome | 保留第一份权威结果，记录 conflict，进入 `manual_review`；不能按时间覆盖 |
| 旧 attempt 的迟到启动/结果 | 只可写回其精确旧边界；不得按 current attempt 路由或覆盖新 attempt |
| 缺少精确凭证的迟到事件 | 未关联记录或拒绝；不得用名称、时钟或唯一候选匹配 |
| 已关闭/tombstoned attempt 的事件 | 识别后拒绝；仅可保留最小审计事实，绝不复活 execution/work item |

`tombstone` 只由明确 `close_task`、select 后可靠关闭未选 candidate 或其他显式处置生成。有效期内（现有语义为 7 天）迟到事件不能复活对象；到期清理也只能针对精确 `task_id + attempt` 与结果引用执行。超时、沉默、SessionEnd、容量压力、`pending_init` 和空列表都不是 tombstone 的来源。

### 6.3 duplicate 的收口

1. 旧 unknown Agent 迟到启动且新 attempt 已被显式 replacement，或两个候选均可能执行业务时，保留所有 attempt 并标记 duplicate。
2. 父 Agent提交 `select_attempt`，原子设定所选 current attempt；不以“最新”“响应最快”自动选择。
3. 未选的 stopped/interrupted/not-started candidate 可按明确处置关闭并生成 tombstone；未选 running candidate 只返回精确 interrupt target。
4. interrupt failed/unknown 时，未选 candidate 仍未关闭，duplicate 继续存在；明确 interrupt success 或精确 list terminal 后才关闭。
5. 仅当全部未选 candidate 已可靠关闭，才清除 duplicate，恢复所选 attempt 自身派生的 parent action。

## 7. 与现有工作包的迁移关系

| 现有材料 | D4 采用/冻结 | 后续迁移约束 |
| --- | --- | --- |
| D1 | 四层模型、unknown/attempt/tombstone 不变量、显式 disposition | D4 不新增业务状态；D2-D3 的契约/处置必须以精确 execution 为对象 |
| WP-04 | pending/claimed、调用三态、独立计数、lifecycle 记录、SubagentStart 授权 | 保留其最小操作字段，但以本文三维边界解释，不能从正文或工具名猜测 |
| WP-06 | 20 分钟等待、目标范围 list、Session/Stop、select 后 interrupt 与 tombstone 收口 | 不把 session 投影、recent activity 或 Stop 当作平台终态；duplicate 要到可靠关闭才清除 |
| restart-interruption-reconciliation | `pending_init`、精确空列表、`previous_status` 与受限重启核验 | 作为平台限制和事故收口设计输入；不把专用入口扩展为任意 thread 查询 |
| governance semantics Schema | 当前枚举、字段、2/2/2 预算、7天保留、initial attempt state | 本文是设计冻结，不反向改 Schema；若实施发现字段不足，先走 D6 兼容/切片裁决 |
| WP-03/WP-05（D1 引用） | 精确 task ref/Agent identity、权威结果文件和冲突保护 | spawn/迟到 identity 与正式 outcome 的单写入边界必须保持 |

旧的平面 `status`、根据错误正文推断恢复分支、把工具 success 当成 Agent/业务终态、unknown 自动重派、按 recent time 删除旧 attempt，均与 D4 冲突，应在 D6 迁移切片中删除或隔离，而不是增加兼容性解释。

## 8. omni-memo 类型场景的抽象回放

仓库只有“本轮不修复 omni-memo 对话”的约束以及上述平台事故类型，没有完整原始 transcript。以下场景以 `W` 为一个工作项、`A1/A2` 为不同 attempt，演示设计应如何处理缺失和迟到事实，不声称它们曾在该真实对话发生。

1. 父 Agent 为 `W/A1` 完成初始持久化并调用 `spawn_agent`。PostToolUse 是 `unknown`，所以 A1 为 `not_started/unconfirmed`、`spawn_observation=unknown`、`parent_action=reconcile`；没有 business result。
2. 应用重启后，目标范围 `list_agents` 先返回 `pending_init`，再返回精确空列表。D4 只记录 pending-init/absent observation，保留 A1 的 unknown 和可能副作用风险；不能将其改为 spawn failed、stopped 或自动重派。
3. 父 Agent因实际业务时限决定继续，明确记录接受重复风险的 growth authorization/transition，创建 replacement `W/A2`，使用新 task ref 和新 Agent。A1/A2 同时存在，标记 duplicate；A2 的启动/结果永不写回 A1。
4. 随后 A1 的精确 `SubagentStart` 迟到到达。它有 A1 task ref，因此 A1 变为 `running/confirmed`，而非覆盖 current A2。父 Agent必须 `select_attempt`，不能因 A1 较早或较晚启动自动选择。
5. 若选择 A2，A1 的精确 interrupt 调用返回 unknown，A1 保持 running/reconcile，duplicate 保留。后续精确 terminal list 或可靠 interrupt success 才允许关闭 A1 并写 tombstone；A2 的 complete outcome 仍需父验收，不能因 A1 已处理而自动关闭 W。

该回放的验收点是：平台不可观察性始终停留在 platform/execution 层；业务继续使用新 attempt；迟到事件精确归属；选择和关闭由 disposition 完成；没有任何步骤假定缺失的原始对话正文或平台内部状态。

## 9. 未决问题与 D5/D6 依赖

1. 真实 `spawn_agent`、`followup_task`、`interrupt_agent`、`list_agents` 响应的全部字段形态，以及 SubagentStart 与 PostToolUse 的实际乱序组合，仍需新对话真实测试，当前为 `not_checked`。
2. 各 Provider 下同 Agent `business_resume` 是否确实保留可用上下文，不能由本地状态设计保证；若不能，D6 应把它明确降级为 replacement 决策，而非复用 attempt。
3. 平台对 canonical path 精确范围空列表的保证强度、`pending_init` 生命周期和可用 thread interrupted 只读证据仍需真实验证；D4 的保守规则不依赖其一定可用。
4. D5 应展示事实来源、范围、时间、unknown/duplicate 和待父处置，不把诊断汇总升级为自动恢复或选择逻辑。
5. D6 应把本文件拆成可回滚实施切片，并为旧状态/旧 lifecycle 记录制定兼容读取和精确迁移策略；不得用默认值填补未知历史事实。

## 10. D4 完成判定

D4 在以下条件下完成：

- 已按 D1 四层模型明确 platform observation、execution status 与 identity status 的职责、字段和禁止推断。
- `spawn_agent`、受治理 follow-up、`interrupt_agent`、`list_agents`、`SubagentStart` 的 success/failed/unknown、pending_init、空列表、重启和乱序路径均有可对账规则。
- 同 Agent platform recovery、business resume、replacement 的 attempt 边界、预算和显式处置条件已区分。
- 迟到事件、幂等、旧 attempt、duplicate 和 tombstone 的收口规则不会把平台故障伪装为业务结果，也不声称插件修复平台内部能力。
- 已给出不依赖缺失真实对话正文的 omni-memo 类型抽象回放、迁移关系和未决真实验证项。

本文件完成设计交付，不代表运行时已经实现，也没有执行代码、Schema、测试、插件或真实平台验证。
