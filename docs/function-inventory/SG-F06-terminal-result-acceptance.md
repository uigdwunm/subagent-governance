# SG-F06 子 Agent 终态结果协议、验收与父任务闭环盘点

## 文档状态

- 当前状态：盘点完成；8 个功能点及整体覆盖、跨功能交界和最终修改方案输入均已确认，不再增加新的功能点。
- 一句话职责：把子 Agent 的完成、阻塞、需要决策及异常停止转换成稳定的结构化结果，完成机械验收、幂等落盘和父任务交接，而不替代父 Agent 判断业务是否真正完成。
- 本文只记录 SG-F06；用户后续明确授权实施第 7 项锁内 compare-and-set 和第 8 项终态回传责任文字，因此本轮同时修改对应运行时、Skill、运行边界和定向测试；主盘点、其他独立功能文档、Schema、fixture 和外部状态仍未修改。
- 当前依据：最新主盘点文档、SG-F04、SG-F05、SG-F07、SG-F08、运行时终态与生命周期区段、`task-result-v1` Schema、规则资产、Skill、等级参考、单元测试和生命周期 fixture。

## 一、功能边界

### 1. 主要负责

- 定义完成、阻塞、需要决策和各种异常停止场景的终态结果语义。
- 定义由 AI 填写的业务结果字段，以及由脚本生成的协议、身份、时间、状态和完整性字段。
- 在 `SubagentStop` 中执行任务关联、Schema、枚举、引用、数据边界和完整性等机械验收。
- 保存可幂等对账的结构化结果，并向父任务交接完整结果和后续动作。
- 区分父任务需要的完整终态上下文与主对话面向用户的简洁摘要。

### 2. 明确不负责

- 不重新定义 SG-F01 的治理等级选择、派发任务契约或上下文继承策略。
- 不拥有 SG-F03 的普通通信、恢复消息参数或原生通信调用。
- 不重新实现 SG-F05 的 StateStore 安全、等待巡检、平台对账、中断和会话生命周期。
- 不负责 SG-F04 的发布、安装、缓存和版本切换；只提供状态与结果格式的跨版本兼容要求。
- 不通过自然语言关键词、固定长度或固定终态卡替父 Agent 验收业务结果。
- 不创建第二套消息平台、后台调度器或 Agent 编排系统。

## 二、候选功能点

1. 终态场景与状态模型。
2. 结构化终态结果生成。
3. 治理等级下的终态要求。
4. `SubagentStop` 机械验收。
5. 协议错误与有限纠正。
6. 结果持久化与完整内容保存。
7. 幂等、冲突和迟到结果处理。
8. 父任务通知与用户摘要闭环。

功能点最终确认为 8 个；各项共享同一结果身份、机械验收、持久化和父任务闭环，不拆成第二个大功能。

## 三、第 1 项：终态场景与状态模型

### 1. 当前情况

当前运行时使用一个 `status` 字段同时表达 Agent 执行状态、任务业务结果、平台健康状态和父任务是否仍需采取动作，导致状态生成、恢复、Stop、SessionStart、裁剪和结果持久化使用同一枚举但语义不同。

| 当前状态 | 当前来源和含义 | 当前结果对象 | 已确认问题 |
| --- | --- | --- | --- |
| `pending` | 已创建治理记录，尚未确认派发结果 | 无 | 基本合理，但未与派发身份确认形成完整状态链 |
| `dispatched` | 被声明为活跃状态 | 无 | 当前运行时代码没有实际写入；可能应用于“已派发但身份未确认”，暂不能删除 |
| `running` | 派发回调或 `SubagentStart` 确认 Agent 进入执行 | 无 | 基本合理，但派发成功而缺少 Agent 身份时也会进入 `running` |
| `retry_required` | 平台错误后的 follow-up 未被机械识别为失败 | 无 | 原生调用未明确失败、Agent 已重启和业务恢复成功没有分层 |
| `complete` | `SubagentStop` 文本验收通过，且没有识别出阻塞或需要决策 | 有 | 没有显式状态字段时默认完成，可能误记业务结果 |
| `blocked` | `SubagentStop` 自由文本中的状态字段报告阻塞 | 有 | Agent 已停止但父任务通常仍需动作；Stop 会放行以便父任务报告阻塞，但当前不进入 SessionStart 恢复摘要 |
| `needs_decision` | 子 Agent 自由文本报告需要决策，或平台恢复达到上限 | 仅前一种路径有 | 两种来源语义不同，却共用同一状态；Stop 会放行以便父任务询问用户，部分路径没有结果对象 |
| `protocol_error` | 自由文本终态补充达到上限 | 无 | 属于结果协议处理失败，不是业务结果，却被当作可裁剪终态 |
| `failed` | 原生派发回调被识别为失败 | 无 | 当前表达派发失败，而不是子 Agent 的业务失败 |
| `interrupted` | 原生 `interrupt_agent` 回调未被识别为失败 | 无 | 属于生命周期关闭状态，只有状态和 tool use ID，没有结构化中断结果 |
| `platform_error` | `list_agents` 明确观察到 Agent `errored` | 无 | 同时属于终态和可恢复状态；SG-F05 已让 Stop 阻止一次，并让 SessionStart/SessionEnd 恢复或保留该记录，但它仍会被终态裁剪 |

当前状态集合的主要矛盾如下：

1. `platform_error` 同时位于 `TERMINAL_STATUSES` 和 `RESOLVABLE_STATUSES`，既被当作终态又允许恢复。
2. `blocked`、`needs_decision` 和 `platform_error` 对 Agent 执行而言可能已停止，但对父任务仍有恢复、决策或对账动作；三者对 Stop 的正确行为也不同。
3. SG-F05 已新增 `STOP_BLOCKING_STATUSES = ACTIVE_STATUSES | {"platform_error"}`，让平台错误阻止一次父任务结束，同时保持 `blocked`、`needs_decision` 可以向用户报告；最新 `SESSION_RESTORABLE_STATUSES` 和 `SESSION_END_PRESERVED_STATUSES` 已纳入 `platform_error`、`needs_decision`，但 `blocked` 仍不属于会话恢复或保留集合。
4. `_prune_state()` 按 `TERMINAL_STATUSES` 裁剪记录，可能回收仍需父任务处理的 `platform_error`、`blocked` 或 `needs_decision`。
5. `task-result-v1` Schema 枚举七种终态，但当前只有 `SubagentStop` 接受的 `complete`、`blocked` 和主动报告的 `needs_decision` 生成 `result_document`。
6. `needs_decision` 同时表示业务决策请求和平台恢复上限，没有稳定的来源、原因和退出转换。
7. 当前已有 `INTERRUPTIBLE_STATUSES = ACTIVE_STATUSES | {"platform_error", "needs_decision"}`，使仍需父任务动作的错误/决策状态在成功中断后转为 `interrupted`；这是 SG-F05 已完成的生命周期修补，SG-F06 只记录交界，不重复归属。

### 2. 与前后文的交接

#### 上游交接

- SG-F01 提供 `task_id`、治理等级、目标、范围和完成条件；SG-F06 消费这些身份与验收背景，但不重新生成派发契约。
- SG-F02 提供 `PostToolUse`、`SubagentStop`、Stop 等 Hook 注册和统一事件路由；SG-F06 定义终态事件的业务结果语义，不拥有事件接线。
- SG-F03 消费“是否允许通信、恢复或需要用户决策”的任务状态；它负责原生消息参数和调用，不应自行定义业务终态。
- SG-F04 只消费最终确定的状态版本与结果格式兼容要求，以判断 N/N-1 运行缓存是否能读取共享状态；它不决定状态枚举。
- SG-F05 主要拥有执行状态、平台观察、等待、恢复、中断、Stop、SessionStart/End 和状态裁剪；SG-F06 主要拥有业务结果、结果协议和父任务待办语义。

#### 下游交接

- 结构化终态生成必须使用本项确认的业务结果状态和机械生命周期字段，不能继续从自由文本推断一个混合状态。
- `SubagentStop` 机械验收必须知道哪些状态来自 Agent 业务结果，哪些状态只能由运行时生命周期事件生成。
- 结果持久化必须决定业务结果对象与平台/中断/协议异常记录是统一信封下的不同场景，还是不同对象之间的稳定引用。
- 幂等、冲突和迟到结果处理必须依据明确的状态维度和终态优先级，不能继续以事件处理先后隐式决定覆盖结果。
- 父任务闭环必须根据“是否仍需动作”判断是否允许结束，而不是只判断 Agent 是否已经停止。

### 3. 改进建议

不再用一个平面 `status` 同时表达所有语义。目标模型至少应区分以下四个维度；字段名和最终枚举在统一方案中确定：

1. **执行状态**：表达任务尚未派发、已派发但身份未确认、运行中或已经停止。
2. **业务结果**：表达尚无结果、完成、阻塞或需要决策。
3. **父任务动作**：表达无需动作、继续等待、恢复同一 Agent、请求用户决策或人工对账。
4. **平台观察**：保存最近一次原生平台状态，例如运行、错误或未知，而不由平台状态推断业务完成。

派发失败、中断、协议错误和平台错误应作为有明确来源的终止或异常原因记录，例如 `dispatch_failed`、`interrupted`、`protocol_error` 和 `platform_error`，不能继续与业务结果共用一个无来源的枚举值。

目标语义应满足：

- `complete` 表示已取得业务结果，但最终业务验收仍由父 Agent 负责。
- `blocked` 表示 Agent 已停止并提供阻塞结果，父任务仍需满足恢复条件或决定结束。
- `needs_decision` 表示父任务必须向用户请求选择，并保存业务请求或恢复上限等明确来源。
- `platform_error` 表示平台执行异常和待恢复动作，不是已完成的业务终态。
- `interrupted` 表示父任务已显式关闭执行，不表示平台错误被修复。
- `protocol_error` 表示结构化结果协议未建立或校验失败，需要父任务对账，不得伪装成业务失败。
- `failed` 必须区分派发失败、执行失败或结果报告的失败阶段，不能继续只靠一个状态值表达。

同时需要：

- 取消“没有明确业务状态时默认 `complete`”的规则。
- 区分子 Agent 主动请求决策与恢复上限触发的决策请求。
- 让 Stop、SessionStart、SessionEnd 和裁剪逻辑共同消费稳定的 action-required 语义。
- 暂不删除 `dispatched`；先确认是否用于替代当前派发成功但身份未确认的 `unmapped running`。
- 保持原生 `spawn_agent`、`wait_agent`、`list_agents`、`followup_task` 和 `interrupt_agent` 为唯一执行通道，不因状态拆分建立第二套编排系统。

### 4. 可以局部直接实施的内容

本项没有适合孤立修改的运行时代码。直接调整状态常量会同时改变任务关联、恢复资格、中断、Stop、SessionStart、状态裁剪、结果 Schema 和跨版本状态读取，容易制造新的错误终态或丢失待处理任务。

当前可以直接完成的只有盘点记录：

- 建立当前状态来源、结果对象、恢复性和父任务动作矩阵。
- 记录 `needs_decision` 双重来源和 `platform_error` 的终态/可恢复矛盾。
- 记录 `dispatched` 当前未写入，但可能承担身份未确认状态，暂不判定为无用。
- 记录 SG-F05 已完成的 `INTERRUPTIBLE_STATUSES` 修补，避免重复实施或重复归属。
- 把所有运行时状态集合修改留到状态协议、结果协议和会话生命周期能够一起验收时处理。

### 5. 必须留待最终统一方案的内容

- 多维状态字段的最终名称、枚举、必填关系和状态转换表。
- `dispatched` 是正式启用、改名为身份未确认状态，还是删除。
- `platform_error` 是否退出可裁剪终态集合，以及 SG-F05 当前 Stop 阻断、SessionStart 恢复、SessionEnd 保留的过渡行为如何收敛为统一 action-required 语义。
- `blocked`、`needs_decision` 如何映射为父任务 action-required，并在何种条件下解除。
- 业务决策请求和平台恢复上限是否共用一个业务状态，以及如何保存来源和原因。
- `failed`、`interrupted`、`protocol_error`、`platform_error` 是否生成统一结果信封，以及各自最小字段。
- 中断、`SubagentStop`、`list_agents`、follow-up 和 `SubagentStart` 并发或迟到时的优先级和冲突记录。
- 状态裁剪是否允许删除仍需恢复、对账或用户决策的记录。
- `STATE_VERSION`、状态目录版本和旧记录的迁移、隔离或拒绝策略。
- SG-F04 N/N-1 缓存并存时读取同一状态格式的兼容门禁。
- 真实 Codex 事件是否提供足够稳定的响应、时间或身份字段支持目标转换模型。
- 主盘点文档仍保留 `platform_error` 不进入 Stop/SessionStart 提醒的旧结论；SG-F05 第九项又记录“SG-F06 第一项仍是旧快照”，但 SG-F06 本轮已经修正。最终合并时需要同时更新主盘点并删除 SG-F05 中已经过期的跨文档漂移说明。

### 6. 当前测试与证据

- `tests/test_governance.py` 已覆盖派发失败、平台错误对账、恢复上限进入 `needs_decision`、SubagentStop 三种业务状态、已有终态保护、Stop 对活跃任务和 `platform_error` 的一次性阻断、SessionStart 对 `platform_error`/`needs_decision` 的恢复摘要、SessionEnd 对两类记录的保留以及状态裁剪等独立行为。
- `tests/test_hook_fixtures.py` 已覆盖成功生命周期、平台错误、恢复上限和中断状态，但 fixture 直接调用 `handle()`，不能证明真实 Codex 平台会产生完全相同的事件顺序、响应形状或会话恢复展示。
- 当前缺少统一状态转换矩阵测试、action-required 测试、业务决策与平台决策来源区分测试、乱序/迟到事件测试，以及跨版本状态兼容测试。
- `task-result-v1.schema.json` 与 `TERMINAL_STATUSES` 的枚举一致性已有测试，但这只证明枚举文本一致，不能证明所有状态都实际生成一致的结果对象或形成父任务闭环。

### 7. 本项结论

- 本功能点必须保留并重点改造。
- 它不是简单调整几个状态常量，而是 SG-F05 生命周期状态与 SG-F06 业务结果闭环之间的共享基础协议。
- SG-F06 负责业务结果和父任务待办语义，SG-F05 负责生命周期状态的保存与执行；最终统一方案必须同时修改两侧，不能在任一功能中孤立切换。
- 当前不修改运行时代码、Schema、规则或测试，只把上述结论作为后续结构化终态、机械验收和状态迁移方案的前置输入。

## 四、第 2 项：结构化终态结果生成

### 1. 当前情况

当前没有独立的结构化终态结果生成入口。子 Agent 只返回 `last_assistant_message` 自由文本，`SubagentStop` 在通过关键词、长度和格式检查后，从文本推断状态并临时拼装一个简化的 `result_document`。

当前链路为：

```text
子 Agent 自由文本
  → Hook 检查 ACK、长度、证据关键词和 strict 格式
  → 从文本状态字段推断 complete / blocked / needs_decision
  → 截断完整文本
  → 在 StateStore 任务记录内临时拼装 result_document
```

当前结果对象的实际字段和来源如下：

| 字段 | 当前来源 | 已确认问题 |
| --- | --- | --- |
| `protocol` | 脚本固定生成 `subagent-result-v1` | 合理，但只有成功 SubagentStop 路径使用 |
| `task_id` | Agent—任务映射 | 结构上合理，但 standard/strict 仍要求同一 ID 出现在自然语言正文 |
| `status` | `_reported_status()` 从自由文本状态字段推断 | 没有明确字段时默认 `complete`，无法稳定区分异常来源 |
| `result` | 完整终态文本经 `_bounded()` 截断 | 不是独立业务结果，约 600 字符边界可能丢失证据和后续动作 |
| `evidence` | 固定空数组 | 没有保存子 Agent 实际提供的证据 |
| `remaining` | 固定空数组 | 没有保存实际剩余事项 |

当前还缺少：

- 独立 `TaskResultInput` 和 `TaskResult` 模型。
- 可供子 Agent 调用的确定性结果生成入口。
- `result_id`、生成时间、内容哈希和稳定结果引用。
- `parent_next_step` 以及 blocked、needs_decision、failed 的分场景字段。
- prepared result 的创建、过期、完整性和单次消费语义。
- 运行时 JSON Schema 校验。
- 所有生命周期终止场景的一致结果对象。

`task-result-v1.schema.json` 当前只要求 `protocol`、`task_id`、`status` 和 `result`，允许任意扩展字段；测试只检查成功结果对象具备 Schema 所列基本字段和枚举，不能证明结构化结果生成、内容完整性或父任务投递已经实现。

### 2. 与前后文的交接

#### 上游交接

- SG-F01 已确认统一的参数所有权原则：AI 提供真实业务语义，确定性脚本负责校验、规范化、固定渲染和机械字段生成；SG-F06 直接复用该原则，不建立第二种生成哲学。
- SG-F02 负责让 `SubagentStop` 进入统一运行时；结构化结果生成入口是否复用现有 CLI 或使用独立子命令需要统一决定，但不改变 Hook 注册职责。
- SG-F03 的通信生成可以与结果生成共享基础校验、规范化和唯一引用能力，但 communication 与 result 必须使用不同协议、身份和生命周期。
- SG-F05 提供任务身份、Agent 映射和正式运行状态底座；prepared result 应是独立短期数据，不直接复用长期 StateStore 或 PreparedContractStore。
- SG-F04 只消费结果协议、生成器和临时存储的版本兼容要求，为 N/N-1 运行缓存切换提供门禁，不决定结果字段。

#### 下游交接

- `SubagentStop` 机械验收只读取稳定结果引用并加载 prepared result，不再从完整自然语言正文提取业务字段。
- 结果持久化保存验收后的完整 `TaskResult`，不再把截断终态文本当作正式结果。
- 幂等、冲突和迟到结果处理使用 `result_id` 与内容哈希，不再只依赖任务当前状态和事件先后顺序。
- 父任务通知消费已经验收的正式结果，再决定父任务下一步和用户可见摘要；结果生成器不直接替父 Agent 完成业务验收。

### 3. 参数所有权和候选结果结构

建议分成 AI 提供的业务参数和脚本生成的机械信封，不让两者互相代填。

#### AI 提供的公共业务字段

- `status`
- `result`
- `evidence[]`
- `remaining[]`
- `parent_next_step`

#### 分场景业务字段

| 场景 | 附加字段 | 所有权 |
| --- | --- | --- |
| `blocked` | `blocker`、`attempted[]`、`required_to_resume` | AI 根据真实阻塞情况填写 |
| `needs_decision` | `decision_question`、`options[]`、`recommendation` | AI 提供问题、选项影响和建议，不替用户决策 |
| `failed` | `failure_stage`、`failure_reason`、`attempted[]`、`recoverable` | AI 或可观察生命周期事件根据失败来源填写；最终来源规则待统一 |

脚本只检查字段存在、类型、枚举、集合和字符串大小等机械边界，不用关键词或固定文本格式判断这些内容是否真实、充分或正确。

`platform_error`、`interrupted` 和 `protocol_error` 通常来自运行时可观察事件，不应允许 AI 只靠自然语言自行声明。它们是否与 AI 业务结果共用一个信封，由第 1 项状态模型和最终统一方案共同确定。

#### 脚本生成的机械字段

- `protocol`
- `result_id`
- `task_id`
- 经过枚举校验的 `status`
- `generated_at`
- `content_hash`
- `result_reference`

`result_id` 表达一次结果提交的唯一身份，不能直接使用内容哈希替代；相同业务参数的不同执行仍是不同提交。`content_hash` 基于规范化业务字段计算，只用于完整性、幂等和冲突检查，不是脚本生成的业务摘要。

### 4. 目标生成链路

```text
子 Agent 完成实际执行
  → AI 填写固定结构的业务参数
  → 确定性结果生成器校验参数
  → 生成 result_id、时间、内容哈希和结果引用
  → 原子创建短期 PreparedResult
  → 返回人类可读终态和机械结果收据
  → SubagentStop 只消费结果收据并加载 PreparedResult
```

当前 `SubagentStop` Hook 只稳定接收到 `last_assistant_message`。如果真实 Codex 没有独立的结果引用字段，最终回复需要携带一个简短、稳定、可机械解析的结果收据；Hook 只解析该收据，不解析正文的业务语义。真实平台是否完整保留该收据必须通过实际任务验收，不能只由直接调用 `handle()` 的测试推定。

生成器必须保留原生 Agent 和 Hook 通道，只生成结构化结果及其引用，不发送消息、不调度 Agent，也不创建第二套父子任务通信平台。

### 5. 改进建议

1. 新增明确的 `TaskResultInput` 和 `TaskResult` 模型，分别表达 AI 业务输入和最终机械信封。
2. 为 complete、blocked、needs_decision 和 failed 建立场景化字段规则，不要求所有状态填写无意义字段。
3. 使用确定性生成器完成参数校验、规范化、唯一 ID、时间、哈希、结果引用和固定渲染。
4. 新增独立短期 `PreparedResultStore`；它与 PreparedContractStore 可以共享安全基础设施，但不能混用记录类型和消费时机。
5. 只有全部输入合法并完成原子写入时才返回有效结果引用；生成失败不得留下可被 `SubagentStop` 误消费的半成品。
6. `SubagentStop` 成功验收后提交或消费 prepared result，后续生命周期不再依赖临时对象。
7. 不再从自由文本猜测 `status`、`evidence`、`remaining` 或场景附加字段。
8. 不长期保留结构化生成和旧自由文本推断两条主路径；生成器、prepared store、Schema 和 SubagentStop 消费端必须作为一次原子切换实施。
9. 结果对象的底层结构不因治理等级不同而变化；不同等级的内容详细程度和人类可读渲染留给第 3 项确认。
10. 结果生成器不自动总结业务内容，也不根据任务契约伪造证据、剩余事项或父任务下一步。

### 6. 可以局部直接实施的内容

本项没有适合孤立修改的运行时代码：

- 不能只给 Schema 增加 `result_id`、时间和哈希，因为运行时尚不会生成或消费。
- 不能先删除自由文本解析，因为当前没有 prepared result 来源。
- 不能只创建未被使用的 `TaskResult` 类或生成脚本，避免形成无入口死代码。
- 不能只取消约 600 字符截断，否则会扩大 StateStore 容量风险但仍没有完整结果分层。
- 不能先要求 `evidence` 或 `remaining` 非空，否则当前只能继续从文本猜测或迫使 AI 填写无意义占位。

当前可以直接完成的只有盘点记录：

- 记录当前结果字段、实际来源和缺失能力。
- 记录 AI 业务字段与脚本机械字段的所有权矩阵。
- 记录 complete、blocked、needs_decision、failed 的候选场景字段。
- 记录 prepared result、结果引用和 SubagentStop 结果收据的目标链路。
- 明确现有 Schema shape 测试不等于结构化结果已实现。

### 7. 必须留待最终统一方案的内容

- 结果生成器使用独立脚本、现有运行时的新子命令，还是统一参数生成器的一个操作类型。
- `TaskResult` 的最终 Schema、协议版本和字段扩展策略。
- `failed` 属于 AI 业务结果、生命周期异常还是需要按来源拆分的公共场景。
- `platform_error`、`interrupted` 和 `protocol_error` 是否使用同一结果信封，以及最小字段集合。
- PreparedResultStore 的目录、权限、TTL、原子写入、单次消费和异常清理策略。
- 结果引用或收据如何进入 `last_assistant_message`，以及真实 Codex 对其保留和转发的保证。
- 规范化和内容哈希算法具体包含哪些字段，是否排除唯一 ID、时间和临时引用。
- 相同内容的不同任务、同一任务的不同执行和同一结果重放如何生成或复用身份。
- StateStore 保存完整结果、正式结果引用，还是使用独立长期结果文件。
- Schema 与 StateStore 版本迁移、旧结果读取和 SG-F04 N/N-1 兼容策略。
- 生成失败、prepared result 缺失/过期/篡改以及正式状态写入失败的不同处理方式。
- strict 卡、standard 证据要求和 light 简洁输出如何渲染同一底层结果对象。

### 8. 当前测试与证据缺口

- 当前 `test_successful_result_document_matches_schema` 只检查成功结果对象的字段形状、协议常量和状态枚举，不执行 JSON Schema validator，也不覆盖生成入口。
- 生命周期 fixture 只包含一条标准成功自由文本，没有结构化结果收据或 prepared result。
- 目标实现需要覆盖每种业务终态的合法生成、缺失字段、错误类型、非法枚举、大小边界和中文内容无损保存。
- 需要验证相同规范化业务内容的 `content_hash` 稳定，不同业务内容产生不同哈希，而每次独立提交的 `result_id` 保持唯一。
- 需要覆盖结果引用与任务不匹配、prepared result 缺失、过期、篡改和原子写入中断。
- 必须使用真实子 Agent 验证生成入口可调用、最终回复保留结果收据，并让真实 `SubagentStop` 取得同一 prepared result；直接调用 handler 或 fixture 不能替代该证据。

### 9. 本项结论

- 本功能点必须新增，是后续机械验收、完整持久化、幂等冲突和父任务通知的前置能力。
- 结构化结果生成必须落实“AI 填业务参数、脚本生成机械字段”，不得把固定脚本扩展为业务摘要或证据生成器。
- 生成入口、PreparedResultStore、Schema 和 `SubagentStop` 消费端必须原子实施，当前没有适合先行提交的孤立运行时代码。
- 当前只把结论写入盘点文档，不修改运行时、Schema、规则、Skill、测试或 fixture。

## 五、第 3 项：治理等级下的终态要求

### 1. 当前情况

当前四种请求等级没有使用四套结果协议，但运行时会根据实际 `mode` 和请求 `requested_mode` 对同一份 `last_assistant_message` 执行不同的自然语言检查，并按实际等级设置不同补充上限。

| 场景 | 当前终态检查 | 当前补充上限 | 已确认问题 |
| --- | --- | --- | --- |
| `light` | 非空；拒绝规范化后完全命中或短文本包含 ACK-only 词的回复 | 1 次 | 空值检查合理；ACK 集合和“短文本包含 ACK”的判断仍是语言启发式，可能误拒绝真实简短结果，也可能放过没有实质内容但未命中词表的回复 |
| `standard` | 包含任务 ID；正文至少 40 字符；命中至少一个证据关键词；同时执行 ACK 检查 | 2 次 | 把正文长度、关键词和任务 ID 复述当作业务完成证据，越过机械验收边界 |
| 显式 `strict` | 包含 standard 全部要求；还要求 `【子 Agent 终态】`、六个中文字段和三种中文状态值 | 2 次 | 固定卡适合作为人类可读渲染，但当前被 Hook 当作结果有效性的门槛；字段值仍由自由文本解析，不能形成稳定结果对象 |
| `auto → light` | 与实际 light 相同 | 1 次 | 实际等级影响终态阻断，但结果对象本身没有保存等级相关的内容要求或契约引用 |
| `auto → standard` | 与实际 standard 相同 | 2 次 | 继承了长度、关键词和任务 ID 正文检查的问题 |
| `auto → strict` | 执行 standard/strict 的实质结果、任务 ID、长度和证据关键词检查，但因为 `requested_mode != strict` 不要求 strict 卡 | 2 次 | “提高证据期望但不强制卡”的方向正确，但当前仍通过自由文本启发式实现 |

运行时的具体行为是：

- `_normalized_message()` 会移除标点、下划线和空白差异，再与固定 `ACK_ONLY` 集合比较。
- `_terminal_errors()` 对 standard/strict 要求任务 ID、40 字符和 `EVIDENCE_MARKERS` 命中；只有 `mode == strict` 且 `requested_mode == strict` 才检查固定终态卡。
- `_terminal_field()` 和 `_reported_status()` 从中文或英文行式字段提取状态；没有明确状态时默认 `complete`。
- `max_retries` 只按实际 `mode` 决定：light 为 1 次，其他实际等级为 2 次；超过后写入 `protocol_error` 并放行。
- 当前 `skills/subagent-governance/SKILL.md` 仍表达不同等级的业务内容期望和显式 strict 卡；`governance-levels.md` 进一步把这些期望描述成 Hook 机械检查，因此规则层仍混合了“父 Agent 期望”和“Hook 阻断条件”。
- `assets/agents-governance.md` 已由 SG-F04 收敛为按需加载 Skill 的最小入口，不再复制等级、等待和终态卡全文；完整协作语义当前以 Skill 为主要来源。

### 2. 已确认的目标原则

以下不是本项新提出的改进建议，而是主盘点文档和用户已经确认的统一原则：

1. 所有治理等级共用同一套结构化结果基础字段，不按等级建立不同 Schema 或不同结果存储格式。
2. AI 负责填写真实的 `status`、`result`、`evidence[]`、`remaining[]`、`parent_next_step` 及分场景业务字段；脚本只生成协议、结果 ID、时间、哈希和引用等机械字段。
3. Hook 只检查结果是否存在、字段类型、大小边界、枚举、任务/结果引用和场景字段关系，不使用 ACK、正文长度、证据关键词、任务 ID 正文存在或 strict 卡判断业务是否完成。
4. 治理等级继续表达父任务对结果详细程度、验证强度和风险说明的不同期望；这些期望由派发契约、AI 结果字段和父 Agent 业务验收落实。
5. 显式 strict 可以保留固定中文终态卡，但它是同一结构化结果对象的确定性人类可读渲染，不是 Hook 解析业务字段的来源或停止门槛。
6. `auto → strict` 可以提高证据和说明强度，但不能自动获得“父 Agent 显式选择 strict”的模板语义，因此不强制 strict 卡。

### 3. 与前后文的交接

#### 上游交接

- SG-F01 提供 `requested_mode`、实际 `mode`、任务契约和各等级的业务证据期望；SG-F06 消费这些字段决定结果内容要求和渲染方式，不重新执行 auto 风险分类。
- SG-F02 只负责 `SubagentStop` Hook 接入和运行时错误边界，不拥有各等级终态语义。
- SG-F03 负责父子 Agent 的普通通信和恢复调用；当结果需要纠正时，它只负责把稳定的协议纠正请求发送给同一 Agent，不定义哪些业务内容算充分。
- SG-F04 已确认全局 `AGENTS.md` 只保留最小 Skill 入口；终态等级规则应集中在 Skill、结构化契约和协议来源中，不能重新复制回全局资产。
- SG-F05 提供任务记录中的请求等级、实际等级、生命周期状态和补充/恢复所需状态底座；结果证据强度与业务验收仍归 SG-F06。

#### 下游交接

- 第 4 项 `SubagentStop` 机械验收应消费 prepared result 和任务契约引用，不再调用自然语言终态解析器。
- 第 5 项协议错误与有限纠正应使用统一的结构化协议错误和统一纠正预算，不继续把治理等级映射为 1 次或 2 次自然语言补写。
- 第 6 项结果持久化保存统一结果对象及其等级/契约引用，不因 light、standard、strict 选择不同存储形状。
- 第 8 项父任务闭环根据治理等级渲染适当详细程度的父任务上下文和用户摘要，但完整结果与主对话摘要仍是两个层次。

### 4. 保留、迁移和删除清单

#### 保留

- 保留 light、standard、strict 对业务结果详细程度和证据强度的差异。
- 保留显式 strict 的中文终态卡，作为确定性渲染格式和人类协作约定。
- 保留 `auto → strict` 不自动强制 strict 卡的规则。
- 保留空结果、缺少结构化结果对象、非法类型、非法枚举、越界数据和引用不匹配等机械错误的明确拒绝或纠正能力。
- 保留纠正必须有上限、超过上限进入父任务对账而不是无限续跑的总体原则。

#### 迁移

- 把 strict 卡从 Hook 自由文本解析迁移到确定性结果渲染器。
- 把任务 ID 正文存在检查迁移为 `task_id`、`result_reference` 与当前 Agent—任务映射的一致性检查。
- 把“需要证据”的等级要求迁移到任务契约和结构化 `evidence[]` 字段，由父 Agent 判断证据是否足以满足真实完成条件。
- 把状态识别从 `_terminal_field()`/`_reported_status()` 迁移到结构化 `status` 枚举和场景字段校验。
- 把当前按等级计算的自然语言补充次数迁移为统一结构化协议纠正策略；最终次数和可纠正错误类别留待统一方案确定。
- 把 Skill 和 `governance-levels.md` 中混合的“内容期望/Hook 门槛”拆分成父 Agent 协作要求、生成器参数规则和机械验收规则。

#### 删除

- 删除 `ACK_ONLY` 和基于规范化短文本的 ACK-only 终态判断。
- 删除 standard/strict 的 40 字符下限。
- 删除 `EVIDENCE_MARKERS` 关键词扫描。
- 删除任务 ID 必须出现在自然语言正文中的要求。
- 删除 `_terminal_field()` 对 strict 卡字段和中英文状态的业务解析，以及没有状态时默认 `complete` 的行为。
- 删除显式 strict 固定卡作为 Hook 停止门槛的行为。
- 删除 light 1 次、其他等级 2 次的自然语言补写策略及对应固化测试。

上述删除必须发生在结构化结果生成、prepared result、机械验收和协议纠正路径能够共同接管后；不是现在直接删除旧代码。

### 5. 改进建议

1. 在任务契约中保存请求等级、实际等级和等级对应的结果内容期望，由结果生成器通过契约引用取得，避免再次从终态正文推断。
2. 所有等级使用同一个 `TaskResultInput`；等级差异只影响业务字段的期望强度、场景字段要求和人类可读渲染，不改变公共机械信封。
3. light 允许简洁结果和空 `evidence[]` 的场景应由明确 Schema/契约规则表达，不能继续靠字符数或 ACK 词表猜测。
4. standard/strict 是否要求至少一项结构化证据，应依据任务契约和终态场景设计；不能仅因等级高就迫使 blocked、failed 或无需工具验证的任务填写伪证据。
5. 显式 strict 卡由生成器按固定顺序从已校验结果字段渲染；Hook 验证结果引用，不再反向解析卡片恢复结构化字段。
6. `auto → strict` 与显式 strict 使用相同底层结果结构和证据期望，但保留不同的渲染标志，确保只有显式 strict 输出强制卡。
7. 协议纠正只处理缺字段、类型、枚举、引用、大小和完整性等可机械定位问题；业务证据不足由父 Agent 决定追问、继续执行或拒绝验收。
8. Skill、等级参考、运行时、Schema 和测试必须作为一次原子切换更新，避免文档已经取消语义验收而旧 Hook 仍阻止停止。

### 6. 可以局部直接实施的内容

本项没有适合孤立修改的运行时代码、Schema、Skill 或测试。当前可以直接完成的只有盘点记录：

- 记录四种请求/实际等级的当前终态检查和补充上限矩阵。
- 把统一结果结构、取消自然语言业务验收和 strict 卡降级为渲染格式标记为已确认原则。
- 建立保留、迁移和删除清单，明确哪些当前检查不是目标能力。
- 登记 `assets/agents-governance.md` 已收敛为最小入口，避免后续方案再次复制完整规则。
- 修正 SG-F05 已让 SessionStart/SessionEnd 恢复或保留 `platform_error`、`needs_decision` 的并行变化。

### 7. 必须留待最终统一方案的内容

- `evidence[]` 是否依据派发契约或实际等级设置 `minItems`，以及 light、无需工具验证、blocked、needs_decision 和 failed 的例外规则。
- light、standard、显式 strict 的最终人类可读结果模板，以及模板是否只用于子 Agent 终态还是也用于父任务恢复上下文。
- `auto → strict` 实际提高哪些业务字段和证据要求，以及用哪个结构化标志区分显式 strict 渲染。
- 统一协议允许纠正几次、哪些错误可纠正、何时生成 `protocol_error`，以及是否阻止本次 Agent 停止。
- 结果生成器如何取得并核对 `requested_mode`、实际 `mode`、任务契约 ID 和完成条件引用。
- Skill、`governance-levels.md`、运行时、Schema、测试和 fixture 的原子切换顺序及发布门禁。
- SG-F04 N/N-1 旧缓存、已经派发的旧文本协议任务和新版 prepared result 消费端之间的兼容或隔离策略。
- 当前固化 ACK、关键词、长度、任务 ID、strict 卡和补充次数的测试如何替换为结构化字段、引用和场景矩阵测试。

### 8. 当前测试与证据缺口

- `test_standard_ack_only_is_continued`、`test_retry_limit_records_protocol_error` 和 `test_light_requests_only_one_terminal_supplement` 固化了 ACK 词表与按等级补充次数；它们保护当前行为，但不应迁移为目标协议测试。
- `test_standard_substantive_result_is_accepted` 固化任务 ID 正文、长度和证据关键词要求；目标实现应替换为 prepared result、Schema 和任务引用一致性测试。
- `test_auto_promoted_strict_accepts_substantive_result_without_strict_card` 正确保护“auto 提高证据强度但不强制 strict 卡”的语义，但其自然语言验收部分需要改为结构化结果测试。
- `test_light_accepts_concise_substantive_result_without_task_id` 证明当前 light 允许简洁结果；目标测试应证明 light 使用同一结果 Schema，并依据契约允许较少业务字段，而不是继续验证词表和长度豁免。
- `test_published_rules_match_runtime_governance_contract` 目前只核对规则文本和运行时常量存在，不能证明等级要求来自单一结构化来源，也不能证明真实子 Agent 能生成和提交目标结果对象。
- 生命周期 fixture 只有 standard 成功自由文本样本，没有 light、显式 strict、auto 提升、blocked、needs_decision 或结构化协议纠正样本；直接调用 `handle()` 也不能证明真实平台投递。

### 9. 本项结论

- 本功能点必须保留，但应从“按等级解析自然语言并阻止停止”改造为“统一结果协议下的内容期望、结构化字段规则和确定性渲染”。
- 当前 ACK、字符下限、证据关键词、任务 ID 正文和 strict 卡解析都不是目标机械验收能力，应在结构化主路径接管时删除。
- 显式 strict 卡和各等级证据强度仍有协作价值，但它们分别属于渲染规则和父 Agent 业务验收，不属于 Hook 对业务真实性的判断。
- 当前没有安全的孤立代码修改；本轮只更新 SG-F06 文档，把实现留给最终统一修改方案。

## 六、第 4 项：`SubagentStop` 机械验收

### 1. 当前情况

`hooks/hooks.json` 使用 `matcher: ".*"` 把所有 `SubagentStop` 事件交给统一运行时，命令超时为 10 秒，状态提示为“验收子 Agent 终态”。当前 handler 的实际处理顺序如下：

```text
SubagentStop
  → 按 session_id 读取 StateStore
  → 按 agent_id 查找 task_id 和任务记录
  → 检查任务当前状态
  → 对 last_assistant_message 执行自然语言验收
  → 从文本推断业务状态
  → 写入简化 result_document 或 retry_required / protocol_error
  → 阻止一次或放行 Agent 停止
```

当前主要分支如下：

| 输入或状态 | 当前行为 | 当前价值与问题 |
| --- | --- | --- |
| StateStore 不可读 | 告警并 `continue=true` | 保留原生终态可见性，符合治理故障不禁用原生 Agent 的原则；但正式结果不会保存 |
| Agent 没有任务映射 | 按 unmanaged 直接放行 | 合理保护第三方或特殊启动路径；当前没有结构化 unmanaged 诊断记录 |
| Agent 映射指向不存在的任务 | 在更新时重新比较映射并清理，随后放行 | 已具备局部并发保护，避免直接删除已经变化的映射 |
| 任务已在 `TERMINAL_STATUSES` | 不检查本次结果，直接放行 | 避免普通顺序下覆盖已有终态；但相同重放、冲突结果和迟到结果全部被静默合并 |
| 任务状态不在 active 或 terminal 集合 | 保留原状态、告警并放行 | 避免未知状态被强制改写；没有稳定的对账记录或错误分类 |
| 活跃任务且文本检查通过 | 推断状态并写入 `result_document`，随后放行 | 当前主成功路径；没有 prepared result、运行时 Schema 校验或稳定结果身份 |
| 活跃任务且文本检查失败、未达上限 | 写入 `retry_required` 并返回 `decision=block` | 能请求同一 Agent 补充，但当前触发条件属于自然语言语义检查 |
| 活跃任务且已达补充上限 | 写入 `protocol_error` 并放行 | 避免无限续跑；协议错误没有统一结果对象或父任务对账引用 |
| 正式状态写入失败 | 告警并放行 | 保留原生停止和最终文本；不能证明父任务一定看到告警或完整结果 |

当前值得保留的边界包括：

- 未映射 Agent 不因固定协议被阻止。
- 状态不可用或写入失败时 fail-open，并明确告警治理结果未保存。
- 已有终态和未知非活跃状态不会在普通顺序下被新的 SubagentStop 直接覆盖。
- 失效映射清理会在写锁内重新确认映射仍指向同一缺失任务。
- Hook 本身不调用 `send_message`、`followup_task`、`wait_agent` 或新建 Agent，不形成第二套编排器。

### 2. 已确认的问题

1. **验收对象错误**：当前验收的是 `last_assistant_message` 自由文本，不是结构化结果或稳定结果引用；第 3 项已经确认这些自然语言检查不应继续承担业务完成判断。
2. **没有 prepared result**：handler 无法核对 `result_id`、任务引用、生成时间、有效期、内容哈希、完整性或单次消费状态。
3. **Schema 没有进入运行时**：`task-result-v1.schema.json` 只是声明和测试锚点；成功测试只比较 required 字段、协议常量和状态枚举，没有执行 JSON Schema validator。
4. **业务状态仍靠文本推断**：`_reported_status()` 只识别 blocked 和 needs_decision 的行式字段，其他情况一律默认 `complete`。
5. **状态来源没有隔离**：当前 Schema 同时允许 `protocol_error`、`interrupted` 和 `platform_error`，但 SubagentStop 成功路径理论上只生成三种文本业务状态；没有机制禁止 AI 结果冒充生命周期状态。
6. **结果数据边界不完整**：正式 `result` 只是经 `_bounded()` 截断的完整正文，`evidence` 和 `remaining` 固定为空；Schema 没有结果 ID、引用、哈希、时间和分场景规则，且允许任意扩展字段。
7. **存在读取—写入竞态**：handler 先无锁持有最新状态快照，再通过单独 `store.update()` 写入。完成、重试和 protocol_error 回调只检查任务仍存在，不重新核对 Agent 映射、当前状态和预期旧状态；中间到达的中断、平台错误或其他终态可能被覆盖。
8. **已有终态保护过于粗糙**：普通顺序测试证明已存在终态不会覆盖，但没有 `result_id` 和哈希，无法区分相同结果幂等重放、不同结果冲突、旧执行迟到结果或新执行复用 Agent 标识。
9. **重入语义未验证**：fixture 携带 `stop_hook_active`，handler 当前不读取该字段；单元测试只能证明重复调用会消耗补充次数，不能证明真实 Codex 在 SubagentStop block 后如何重启 Agent、何时再次触发 Hook 或怎样设置该字段。
10. **父任务可见性未证明**：返回 `continue=true` 或 `decision=block` 只证明 handler 输出，不能证明原生平台一定把最终文本、告警和纠正理由完整交给父任务。

### 3. 与前后文的交接

#### 上游交接

- SG-F01 提供稳定任务 ID、请求等级、实际等级、完成条件和契约引用；机械验收只消费这些数据，不重新解析派发正文。
- SG-F02 提供 SubagentStop Hook 注册、统一 CLI、事件路由、输入上限和通用运行时错误边界；SG-F06 不重新定义 Hook 接线。
- 第 2 项提供 `TaskResult`、PreparedResultStore、`result_id`、时间、哈希和结果收据；没有这些输入，第 4 项不能切换为真正的机械验收。
- 第 3 项确认所有等级共用统一结果结构，Hook 不再使用 ACK、长度、关键词、任务 ID 正文或 strict 卡判断业务完成。
- SG-F05 提供 StateStore、Agent—任务映射、文件锁和生命周期状态；SG-F06 使用其原子更新能力提交结果，但不重新实现状态存储安全。

#### 下游交接

- 第 5 项根据本项输出的具体机械错误类型决定是否允许纠正、如何请求同一 Agent 补充以及何时进入 protocol_error。
- 第 6 项保存本项验收通过的完整正式结果和稳定引用，不再把 handler 内临时拼装对象当作完整结果库。
- 第 7 项依据 `result_id`、内容哈希、执行身份和当前状态处理幂等、冲突及迟到结果。
- 第 8 项只向父任务交接已经提交的正式结果、错误或冲突引用；SubagentStop 放行本身不能被描述为父任务已收到通知。
- SG-F03 只负责纠正或恢复时调用原生通信工具，不拥有 Schema、结果合法性或终态提交决定。

### 4. 目标机械验收链路

```text
SubagentStop
  → 解析简短、稳定的 result_reference 收据
  → 按 Agent—任务映射加载当前治理任务
  → 从 PreparedResultStore 加载候选结果
  → 核对 session / task / Agent / execution / result 身份
  → 核对 TTL、协议版本和内容哈希
  → 执行 Schema、类型、枚举、大小和分场景字段关系检查
  → 在同一状态锁内重新核对映射、预期旧状态和已有结果
  → 原子提交、幂等放行、记录冲突或返回协议错误
```

Hook 只解析结果收据，不解析人类可读正文的业务语义。如果真实 Codex 没有独立结构化结果字段，收据可以位于最终回复的稳定有界区段；正文仍供父 Agent 和用户阅读，但不是结果结构来源。

可由 AI 业务结果提交的状态应限制为 complete、blocked、needs_decision 及最终确认的业务 failed 场景。`platform_error`、`interrupted` 和 `protocol_error` 等状态只能由对应平台观察、中断或协议处理路径生成，不能仅凭 AI 结果参数伪造。

目标结果矩阵应至少覆盖：

| 场景 | 目标行为 |
| --- | --- |
| 未映射 Agent | 按 unmanaged 放行，不强制采用治理结果协议；必要时保留有界诊断 |
| 失效映射 | 锁内确认后清理并放行；映射已变化时不删除，交给父任务对账 |
| 有效首次结果 | 完成全部机械校验后原子提交正式结果并放行 |
| 相同 `result_id` 和哈希重放 | 幂等返回已有提交，不重复写入或重复通知 |
| 已有结果收到不同候选结果 | 保留原结果，记录冲突引用并交给父任务决策，不静默覆盖 |
| 旧执行的迟到结果 | 保留当前执行状态和结果，记录 late/conflict 事实，不恢复旧任务 |
| prepared result 缺失、过期或引用错误 | 不回退自由文本解析；返回具体协议错误并交给第 5 项决定纠正行为 |
| 内容哈希或任务/Agent 引用不一致 | 视为完整性或绑定错误，不消费候选结果，不覆盖当前状态 |
| 状态不可读写 | 保留原生停止和最终文本，告警 state-degraded，并明确正式结果未提交 |
| 当前状态不允许接受结果 | 保留原状态，记录预期状态与实际状态冲突，交给父任务对账 |

### 5. 改进建议

1. 定义专用结果收据格式，只携带协议版本、结果引用和必要的短完整性信息，不把完整业务结果或敏感内容塞入收据。
2. 把 JSON Schema 或等价的单一结构化校验逻辑真正接入生成端和消费端；不能继续只在测试中读取 Schema 文本比较字段。
3. 将可由 AI 提交的业务状态与运行时生成的生命周期/协议状态分开校验，并为 blocked、needs_decision、failed 建立条件字段规则。
4. 把 Agent 映射、预期任务状态、prepared result 完整性和正式结果提交放入可明确判定的事务边界；提交前必须重新读取锁内当前状态。
5. 为每种失败返回稳定错误分类，例如 missing、expired、tampered、reference_mismatch、schema_invalid、state_conflict 和 state_degraded，避免继续使用一组自然语言错误决定恢复动作。
6. 保留 fail-open 兼容边界，但区分 unmanaged、状态降级和治理协议非法：未映射 Agent 可以原生放行；已映射任务的非法结果不能伪装成完成；状态不可用时必须明确正式结果未保存。
7. SubagentStop 不主动调用通信或等待工具；需要纠正时返回结构化错误和父任务动作，由 SG-F03 与父 Agent 使用原生工具继续同一任务。
8. 通过真实子 Agent 验收结果收据能否完整到达 Hook、block 后的重入事件序列、`stop_hook_active` 语义和父任务最终可见内容。

### 6. 可以局部直接实施的内容

在不切换结果协议的前提下，有一项现有正确性修补可以独立实施，但本盘点任务没有代码修改权限：

- 完成、retry_required 和 protocol_error 的 `store.update()` 回调在同一锁内重新核对 Agent 映射仍指向同一任务、任务仍处于预期 active 状态且没有已有正式结果；状态已变化时不得覆盖，并返回明确对账提示。
- 同时新增可控竞态测试，在初始 read 后、update 回调前注入 terminal、platform_error、interrupted 或映射变化，证明迟到 SubagentStop 不会覆盖新状态。

这项修补不依赖 PreparedResultStore 或新 Schema，未来结构化提交路径同样需要该锁内 compare-and-set 边界，因此可以在用户另行授权运行时代码修改后优先实施。

以下内容不能孤立直接修改：

- 不能只调用现有 Schema validator，因为当前 handler 尚未取得独立结构化输入，验证的仍是临时拼装对象。
- 不能只删除自由文本验收，否则当前没有可接受的 prepared result 来源。
- 不能只要求结果收据，因为生成器和 PreparedResultStore 尚不存在。
- 不能只扩展已有终态保护，否则没有 `result_id`、哈希和执行身份，仍无法判断相同、冲突或迟到结果。

### 7. 必须留待最终统一方案的内容

- 结果收据的具体语法、长度、位置和真实 Codex 保留保证。
- PreparedResultStore 的路径、权限、TTL、单次消费、崩溃恢复和清理策略。
- 正式 TaskResult Schema、业务可提交状态集合、分场景字段以及运行时 validator 选择。
- prepared result 缺失、过期、篡改、Schema 错误和引用不匹配分别是否阻止停止、允许几次纠正或直接交给父任务。
- 正式提交的事务边界，以及 StateStore 与独立长期结果文件之间的原子性或可恢复提交协议。
- 相同结果、不同结果竞争、旧执行迟到、Agent ID/canonical path 重用和任务已经重新派发时的优先级。
- `stop_hook_active` 在真实 SubagentStop 重入中的准确含义，以及纠正上限是否应绑定 result submission attempt 而不是事件次数。
- 状态不可用、结果存储不可用和父任务通知不可用三类降级如何分别展示并恢复。
- SG-F04 N/N-1 缓存并存时，旧自由文本任务、新结果收据和共享状态版本的兼容、隔离或拒绝策略。
- Hook timeout、结果文件读取和 Schema 校验的性能边界，避免机械验收超时后丢失可诊断结果。

### 8. 当前测试与证据缺口

- `test_unmapped_subagent_stop_is_not_blocked` 和失效映射测试保护 unmanaged 放行与映射清理，是目标实现应保留的兼容边界。
- `test_subagent_stop_does_not_overwrite_existing_terminal_status` 只覆盖“调用开始前已经是终态”的顺序情况，没有覆盖 initial read 与 update 之间发生状态变化的竞态。
- `test_subagent_stop_degrades_open_when_terminal_write_fails` 证明 handler 会告警并放行，不能证明父任务或用户真实看到告警，也不能证明完整最终文本在 Hook 故障后仍被保留。
- `test_successful_result_document_matches_schema` 没有调用 JSON Schema validator，只证明临时对象具备部分 required 字段和枚举文本一致。
- `tests/test_concurrency.py` 只覆盖 32 个并行 spawn 保留全部任务记录，没有 SubagentStop 与中断、平台错误、重复结果或迟到事件的并发测试。
- 生命周期 fixture 只覆盖一条 standard 成功文本，缺少 unmanaged、失效映射、非活跃状态、结果引用、Schema 错误、哈希不匹配、重复、冲突和迟到结果。
- 所有 handler 测试均直接调用 Python 运行时，不能证明真实 Codex 会按预期传递结果收据、执行 block 重入或向父任务展示告警。

### 9. 本项结论

- 本功能点必须保留，是 prepared result 转换为正式任务结果的核心信任边界。
- 它的目标不是判断业务内容是否真实，而是证明“这个结果对象属于这个 Agent、任务和执行，结构合法、未过期、未篡改，并且当前状态允许原子提交”。
- unmanaged 放行、状态故障 fail-open、失效映射安全清理和未知状态不覆盖应保留；自由文本语义验收、默认 complete 和临时结果拼装应由结构化主路径替换。
- 当前可独立修补的是锁内状态与映射重新确认；完整机械验收必须与结果生成器、PreparedResultStore、Schema、协议纠正和幂等冲突策略统一实施。
- 本轮只更新 SG-F06 文档，不修改运行时、Schema、规则、Skill、测试或 fixture。

## 七、第 5 项：协议错误与有限纠正

### 1. 当前情况

当前协议纠正没有独立模型，完全嵌在 `_handle_subagent_stop()` 的自由文本验收分支中：

```text
自然语言终态检查失败
  → 读取任务记录中的 retry_count
  → light 最多阻止并补充 1 次，其他实际等级最多 2 次
  → 未达上限：状态写为 retry_required，返回 decision=block
  → 达到上限：状态写为 protocol_error，保存错误文本并放行
```

当前记录和行为如下：

| 项目 | 当前实现 | 已确认问题 |
| --- | --- | --- |
| 错误来源 | `_terminal_errors()` 产生自然语言错误列表 | 主要是 ACK、字符长度、证据关键词、任务 ID 和 strict 卡，属于第 3 项确认应删除的语义检查 |
| 纠正次数 | `retry_count`，派发时初始化为 0 | 没有 attempt ID、错误类型或最后一次候选结果身份 |
| 上限 | 实际 light 为 1，其他实际等级为 2 | 协议结构是否合法不应因治理等级不同而允许不同次数 |
| 纠正中状态 | `retry_required` | 与平台错误 follow-up 成功后的恢复状态完全同名，但分别使用 `retry_count` 和 `recovery_count` |
| 纠正动作 | 返回 `decision=block` 和一段自然语言 reason | 只要求“继续同一任务并给出真实执行结果”，没有按错误类型给出可执行修复参数 |
| 上限终态 | `protocol_error` | 只保存 `protocol_errors[]`、状态和时间，没有结构化错误记录或 result document |
| 父任务闭环 | 放行 SubagentStop，依赖 `systemMessage` 提醒父任务 | Stop、SessionStart 和 SessionEnd 当前都把它视为已形成、不可恢复的终态 |

值得保留的总体原则只有两项：

- 可纠正的协议问题应优先继续同一个 Agent 或同一次结果提交链路，不立即创建替代 Agent。
- 纠正必须有明确上限，达到上限后停止自动循环并交给父任务处理。

当前“什么是协议错误、哪些错误可纠正、纠正次数如何计算、达到上限后如何保留待办”均需要改造。

### 2. 已确认的问题

1. **当前协议错误实际是自然语言语义错误**：ACK、长度、关键词和终态卡差异不应继续进入目标 protocol_error。
2. **`retry_required` 混合两种不同状态**：终态补充表示结果协议尚未建立；平台 follow-up 表示 Agent 执行恢复调用已经返回且等待重新启动。两者对 SubagentStart、Stop、SessionStart 和父任务下一步的含义不同，却共用一个平面状态。
3. **两套计数器缺少关联模型**：`retry_count` 统计终态补充事件，`recovery_count` 统计平台错误后的成功恢复调用；同一任务可能先发生结果补充再发生平台恢复，两个计数和同一 `retry_required` 状态无法解释当前处于哪个流程。
4. **`retry_count` 缺少安全解析**：代码直接执行 `int(record.get("retry_count") or 0)`；布尔值、负数和非法字符串没有显式边界，非法值会由顶层异常处理降级放行，而不是形成可诊断的协议状态。`recovery_count` 已有独立安全解析函数，两者行为不一致。
5. **所有错误使用同一纠正动作**：缺少收据、结果过期、Schema 错误、哈希不符、任务绑定错误、状态冲突和存储故障不能都通过“让 Agent 再写一次结果”解决。
6. **纠正次数按等级分配没有机械依据**：light 一次、其他等级两次只是当前文本规则的延伸；统一结构化协议下，错误性质和可恢复性比治理等级更重要。
7. **计数按 Hook 事件而不是提交身份累积**：没有 `submission_attempt_id` 或 `result_id`，重复事件、平台重入和真实新提交无法区分；相同事件重放可能消耗纠正预算。
8. **达到上限后的记录不完整**：`protocol_errors[]` 是短中文错误文本，没有稳定错误码、来源阶段、候选结果引用、发生时间列表、是否可纠正、最终原因或父任务动作。
9. **`protocol_error` 被当作已解决终态**：它不阻止父任务 Stop，不进入 SessionStart 摘要，SessionEnd 在没有其他待处理状态时可以删除整个 session；但没有取得有效结果通常仍需要父任务对账或用户决策。
10. **真实 block 重入未验证**：规则要求恢复同一个 Agent，代码实际只返回 SubagentStop `decision=block`；测试通过重复直接调用 handler 模拟补充，不能证明平台会继续同一 Agent、是否再次发出 SubagentStart 或怎样设置 `stop_hook_active`。

### 3. 与前后文的交接

#### 上游交接

- 第 2 项结果生成器应在创建 PreparedResult 前拦截普通缺字段、类型、枚举和大小错误；这些生成期错误不应进入 SubagentStop 运行时纠正预算。
- 第 4 项机械验收提供稳定的错误代码、结果引用和绑定检查结果；第 5 项只根据错误分类决定是否可纠正及父任务动作。
- SG-F01 提供任务契约、完成条件和治理等级，但等级不再直接决定协议纠正次数。
- SG-F05 提供执行状态、平台恢复状态、Stop、SessionStart/End 和状态持久化；协议纠正必须与平台恢复分层，不能继续共享一个无来源的 `retry_required`。

#### 下游交接

- SG-F03 负责在需要显式消息时调用原生 `followup_task` 或发送纠正参数；它不决定错误类型、纠正预算或 protocol_error 终态。
- 第 6 项保存完整协议错误记录、最后可见候选结果或引用，以及 unresolved/resolved 状态；不能只依赖 session 运行记录。
- 第 7 项负责相同提交重放、结果冲突和迟到结果；这些场景不应消耗普通纠正次数。
- 第 8 项向父任务交接无法自动纠正的错误、可选动作和结果可用性；达到上限不等于任务业务失败或已经闭环。
- SG-F04 需要保证旧缓存中的文本补充路径与新版 submission attempt 协议不会共同消费同一状态文件并产生不同上限。

### 4. 目标错误分类与处理矩阵

目标协议至少应区分三类错误：

| 错误类别 | 示例 | 目标处理 |
| --- | --- | --- |
| 生成期参数错误 | 缺少必填字段、类型错误、非法枚举、字符串或数组越界、场景字段不完整 | 生成器立即返回明确错误，不创建 PreparedResult，不进入 SubagentStop，也不消耗运行时纠正预算 |
| 可由同一 Agent 重新提交 | 最终回复缺少结果收据、PreparedResult 已过期、引用的临时结果尚未成功创建或可安全重新生成 | 保留同一任务与执行身份，允许有限重新生成或重新提交，并记录 submission attempt |
| 不应自动纠正 | 内容哈希不符、任务/Agent/session 绑定错误、已有不同正式结果、旧执行迟到、当前状态冲突、结果或状态存储不可用 | 不让 Agent 盲目重写；保留现状和候选证据，记录冲突或降级，并立即交给父任务对账 |

目标错误记录建议包含：

- `error_code`
- `error_stage`
- `correctable`
- `submission_attempt_id`
- `task_id`
- `result_id` 或候选 `result_reference`
- `occurred_at`
- `attempt_count`
- `parent_action`
- 有界、不敏感的 `detail`

错误代码候选包括 `missing_reference`、`expired_result`、`schema_invalid`、`hash_mismatch`、`binding_mismatch`、`state_conflict`、`result_conflict`、`late_result`、`result_store_unavailable` 和 `state_degraded`。最终名称应与第 4、6、7 项共用一个来源，不能由各 handler 自行拼写。

### 5. 目标状态与纠正链路

结果纠正和平台恢复不应继续共用 `retry_required`。目标模型至少需要表达：

- Agent 当前是否仍运行或已经停止。
- 是否等待平台恢复后重新启动。
- 是否等待同一执行重新提交结果。
- 当前 submission attempt、已用纠正次数和最后错误。
- 是否已经转为父任务 action-required。

候选链路如下：

```text
生成器发现参数错误
  → 原地返回参数错误，不创建 prepared result

SubagentStop 发现可纠正提交错误
  → 创建 protocol attempt 记录
  → 在真实平台允许的情况下继续同一 Agent
  → Agent 重新生成或提交新的 result reference
  → 新 submission attempt 再次机械验收

SubagentStop 发现不可纠正错误或达到上限
  → 停止自动纠正
  → 保存 protocol_error 诊断对象和候选引用
  → 设置 parent_action=review/decide
  → 允许当前 Agent 停止，但保持父任务待处理和会话恢复线索
```

`protocol_error` 可以继续作为稳定错误类别或结果信封场景，但不能仅凭一个平面 terminal status 表示已经解决。它需要独立的 resolution/action 状态：当前回合应允许父 Agent 报告问题，compact/resume 后仍应恢复尚未处理的协议错误，只有父任务确认处理、重新取得正式结果或显式关闭后才允许归档和清理。

### 6. 改进建议

1. 将生成期校验与 SubagentStop 运行时纠正分开；能够在结果生成器中确定的错误不进入 Hook 补充循环。
2. 用 `submission_attempt_id` 和稳定错误代码记录每次提交，不再按 SubagentStop 事件次数直接增加一个任务级 `retry_count`。
3. 纠正预算根据错误是否可安全修复统一设计，不按 light、standard、strict 分配不同次数；最终次数由真实平台重入能力和误循环风险决定。
4. 拆分 result correction pending 与 platform recovery pending，或在多维状态模型中使用不同 action 字段；SubagentStart 不能再把两种来源无条件归并为 running。
5. 可纠正错误应给同一 Agent 精确参数，例如重新生成结果、重新附加收据或重新提交引用，不再笼统要求“给出真实执行结果”。
6. 哈希、绑定、冲突、迟到和存储错误直接交父任务对账，不通过自动重写掩盖完整性或状态问题。
7. 达到纠正上限后保存完整错误对象、最后候选引用和父任务动作；Stop 可以放行当前回合，但 SessionStart/End 和结果归档必须把 unresolved protocol error 作为待处理状态保留。
8. 真实子 Agent 验收必须确认 SubagentStop block 是否继续同一 Agent、是否触发 SubagentStart、重复事件是否消耗次数，以及父任务能否取得最终错误记录。

### 7. 可以局部直接实施的内容

本项没有建议孤立实施的运行时代码：

- 不能只调整 light/standard/strict 的补充次数，因为当前错误来源仍是应删除的自然语言规则。
- 不能只重命名 `retry_required`，因为平台恢复、SubagentStart、Stop、SessionStart/End、状态裁剪和测试都消费该状态。
- 不能只把 `protocol_error` 加入 SessionStart/End 保留集合，因为当前没有明确的错误对象、父任务动作和解除条件。
- `retry_count` 的防御性解析可以小修，但目标路径会用 submission attempt 替换该计数器；在完整切换前单独保留第三套过渡语义价值较低。
- 不能只新增错误码常量，因为第 4 项机械验收和第 6/7 项存储、冲突处理尚未共同消费，会形成未使用协议。

当前可以直接完成的只有盘点记录：

- 记录 `retry_required` 的终态纠正/平台恢复双重来源。
- 记录 `retry_count` 与 `recovery_count` 的作用和解析差异。
- 记录 `protocol_error` 当前会被 Stop 放行、SessionStart 忽略并可能在 SessionEnd 删除的闭环缺口。
- 建立生成期、可重新提交和不可自动纠正三类错误矩阵。
- 把纠正次数、attempt 身份和 action-required 行为留给统一方案。

第 4 项已经识别的锁内 compare-and-set 修补仍可在另行授权后独立实施；它属于通用终态写入正确性，不重复归为本项协议纠正改造。

### 8. 必须留待最终统一方案的内容

- 哪些机械错误允许同一 Agent 自动纠正，哪些必须立即交给父任务。
- 统一纠正上限，以及是否只允许一次运行时重新提交。
- `submission_attempt_id`、错误代码、错误阶段和 protocol error 对象的正式 Schema。
- `retry_required` 如何拆分为平台恢复、结果纠正或多维 action 状态。
- 结果生成失败、收据缺失、prepared result 过期与正式提交失败分别在哪一层计数。
- SubagentStop 原生 block 重入与父 Agent 显式 `followup_task` 的使用边界。
- 达到上限后的 Stop、SessionStart、SessionEnd、状态裁剪和结果归档行为。
- 父任务如何确认 protocol error 已处理、转为重新执行、用户决策或显式关闭。
- 状态存储、结果存储和父任务通知故障的不同降级与恢复策略。
- N/N-1 旧文本补充任务和新 submission attempt 协议的兼容、隔离或拒绝策略。

### 9. 当前测试与证据缺口

- `test_retry_limit_records_protocol_error` 和 `test_light_requests_only_one_terminal_supplement` 只通过连续直接调用 handler 证明当前 2/1 次自然语言补充规则，不证明真实 Agent 重入或同一执行重新提交。
- 当前没有 standard、strict 和 auto 各实际等级在上限行为上的完整矩阵；但目标实现不应继续按等级复制这些测试。
- 没有生成期错误与运行时提交错误的分层测试，也没有稳定错误码、attempt ID、可纠正性和父任务动作测试。
- 没有非法、负数、布尔或超大 `retry_count` 测试；非法字符串会使 handler 抛出并由 CLI 顶层降级放行。
- 没有测试区分终态纠正产生的 `retry_required` 与平台 follow-up 产生的同名状态，也没有验证两套计数器交错时的行为。
- 没有 protocol_error 在 Stop 放行后仍被父任务处理、compact/resume 恢复或 SessionEnd 保留的测试。
- fixture 没有协议错误和重新提交场景；现有 recovery-limit fixture 只覆盖平台恢复上限，不能作为终态协议纠正证据。
- handler 单元测试不能证明 Codex 的 block 重入、`stop_hook_active`、SubagentStart 顺序或父任务错误通知可见性。

### 10. 本项结论

- 本功能点必须保留，但应从“按治理等级重复要求补写自然语言”改造成“结构化错误分类、有限重新提交和父任务 action-required 闭环”。
- 生成期错误应尽早失败且不创建 prepared result；只有少量可安全修复的提交错误才允许同一 Agent 有界重新提交。
- 哈希、绑定、冲突、迟到和存储故障不应消耗自动纠正次数或要求 Agent 盲目重写结果。
- `retry_required` 的双重来源和 `protocol_error` 的假终态是本项与 SG-F05 状态模型的主要冲突，必须在统一状态方案中一起解决。
- 当前没有适合孤立提交的本项运行时代码；本轮只更新 SG-F06 文档，不修改运行时、Schema、规则、Skill、测试或 fixture。

## 八、第 6 项：结果持久化与完整内容保存

### 1. 当前情况

当前没有独立的正式结果存储。`SubagentStop` 验收通过后，运行时把一个临时拼装的 `result_document` 直接嵌入 session 级 `StateStore.tasks[task_id]`：

```text
last_assistant_message
  → _reported_status() 推断业务状态
  → _bounded(message, "已完成")
  → text[:MAX_CONTRACT_TEXT]
  → 最多 600 个 Python 字符写入 result_document.result
```

当前保存行为和缺口如下：

| 项目 | 当前实现 | 已确认问题 |
| --- | --- | --- |
| 正式结果位置 | 与任务契约、Agent 映射、运行状态共同内嵌在 session JSON | 没有独立结果生命周期、引用、读取接口或归档边界 |
| `result` | 保存整个 `last_assistant_message` 的前 600 个字符 | 不是独立业务结果；后半段证据、剩余事项、阻塞条件或父任务下一步可能被静默丢弃 |
| 截断标识 | 无 | 父任务和诊断代码无法知道保存内容不完整，也不知道原始长度 |
| `evidence` / `remaining` | 固定空数组 | 原回复即使提供证据和剩余事项也没有被结构化保存 |
| 状态覆盖 | 只有通过 SubagentStop 文本验收的 `complete`、`blocked`、主动业务 `needs_decision` | `failed`、`interrupted`、`platform_error`、`protocol_error` 和恢复上限决策通常没有统一结果对象 |
| 结果身份 | 无 `result_id`、执行身份、生成时间、内容哈希或稳定引用 | 不能证明重复提交相同、不同结果冲突或旧执行迟到 |
| 运行时消费 | 当前没有代码读取 `result_document` 完成父任务通知、会话恢复或业务验收 | 写入成功不能证明父任务取得结果或生命周期闭环 |
| 容量与保留 | 继承 StateStore 4 MB 上限、终态最多 200 条和 30 天裁剪 | 直接取消 600 字符限制并把任意长文本塞回 session JSON 会放大状态不可用和错误裁剪风险 |

`MAX_CONTRACT_TEXT = 600` 当前同时用于契约/通信等有界字段和结果全文，边界语义被混用。对单个通信字段设置机械大小上限是合理输入保护；把同一上限直接用于完整正式结果并静默截断则不是完整结果存储。

### 2. 原生子 Agent 回传与插件截断的区别

OpenAI 官方 Subagents 文档确认：主线程收集的是子 Agent 返回的 summary，Codex App 可以打开独立子 Agent thread 查看其工作和结果；文档同时说明模型存在上下文限制，推荐向主线程返回 summary 而不是原始中间输出。官方文档没有声明原生子 Agent 终态回传是永久、无损的完整结果存储，也没有给出一个固定字符或 token 截断阈值。

因此需要严格区分：

1. **当前插件截断是已经由代码证明的确定行为**：`_bounded()` 执行 `text[:600]`，按 Python 字符计数，不按字节或 token；超过部分被静默删除。
2. **原生平台边界是容量风险，不是已确认的固定截断协议**：主线程通常取得摘要，并可在支持的客户端查看子 Agent thread；但不能据此承诺 Hook 输入、主线程摘要、线程展示和长期历史永远保存完全相同的全文。
3. **两者可能叠加**：即使原生 `last_assistant_message` 到达 Hook 时完整，插件仍只保存前 600 字符；如果上游已经摘要化、受上下文边界影响或传输不完整，插件也没有长度、哈希或引用信息识别这一事实。
4. **原生 thread 不是治理协议的权威结果库**：它可作为人工回看和诊断来源，但正式闭环不能要求父 Agent 事后重新打开线程、复制长文本或猜测哪一段才是最终业务结果。

本项据此采用保守结论：不能声称“正常子 Agent 返回一定会被截断”，也不能假设“正常返回一定完整无损”；目标协议必须在结果生成时主动建立权威结构化记录，并让父任务通过稳定引用取得它。

官方证据：[OpenAI Subagents 文档](https://learn.chatgpt.com/docs/agent-configuration/subagents)。该页面能够证明 summary、独立 Agent thread 和上下文限制的产品边界，不能证明固定截断长度或 Hook 投递完整性。

### 3. 与前后文的交接

#### 上游交接

- 第 1 项提供业务结果、执行停止、平台异常和父任务待办的分层状态；结果存储不能继续只保存一个混合 `status`。
- 第 2 项生成完整 `TaskResult` 和机械信封；第 6 项只持久化已生成、已验证的正式结果，不从终态全文重新提取字段。
- 第 4 项在 SubagentStop 中核对结果引用、绑定、TTL、哈希和 Schema；只有提交成功的 prepared result 才能转为正式结果。
- 第 5 项输出结构化 protocol error、候选引用和父任务动作；结果存储必须保留无法提交正式业务结果时的诊断对象。
- SG-F05 提供 session 状态锁、原子更新、Agent—任务映射和生命周期保留；SG-F06 定义独立结果数据及其引用，不能把 StateStore 扩成无界 transcript 仓库。
- SG-F04 消费正式结果和状态格式的版本兼容、N/N-1 隔离和升级门禁，不决定业务保留期或内容结构。

#### 下游交接

- 第 7 项使用 `result_id`、规范化内容哈希、任务/执行身份和提交时间判断幂等、冲突及迟到结果。
- 第 8 项向父任务发送有界摘要、关键 action-required 字段和正式 `result_reference`；主对话再生成更简洁的用户摘要。
- SessionStart/compact 恢复只注入结果引用、状态、关键待办和有限摘要，不把完整结果正文重复塞回上下文。
- 诊断功能可以使用完整性元数据、提交错误和引用状态定位问题，但不能把人工可见 thread 当作唯一恢复数据源。

### 4. 目标数据分层

建议明确区分四个层次，避免同一段自由文本同时承担正式结果、父任务通知、用户展示和诊断记录：

| 层次 | 主要内容 | 保存/展示原则 |
| --- | --- | --- |
| 正式 `TaskResult` | 完整结构化业务字段、机械信封、分场景字段、引用和完整性信息 | 权威记录；原子写入；可按 `result_id` 读取；不得静默截断 |
| 生命周期状态记录 | 当前执行状态、父任务动作、最近错误、正式结果引用 | 保持有界；继续位于 StateStore；不复制完整业务正文 |
| 父任务终态通知 | 状态、关键结果摘要、证据/剩余事项摘要、下一步和 `result_reference` | 足以让父 Agent 继续，不倾倒内部协议或全部日志 |
| 主对话用户摘要 | 用户需要知道的结果、风险、阻塞或决策项 | 最简洁；由父 Agent 根据正式结果生成，不作为权威存储 |

原生子 Agent thread 属于产品层可检查记录，可辅助人工审查，但不替代上述四层中的正式结果和稳定引用。

### 5. 正式结果的内容与边界

正式结果应保存 AI 实际提交的结构化业务字段，而不是保存整个 transcript 或把终态卡全文当作 `result`：

- `result` 保存任务实际产出或结论。
- `evidence[]` 保存可核对的文件、命令、测试、引用或简短证据；大日志和大制品只保存有权限边界的引用、摘要与可选哈希。
- `remaining[]` 保存真实未完成事项。
- `parent_next_step` 保存父任务建议动作。
- blocked、needs_decision 和 failed 保存各自场景字段。
- 脚本生成 `protocol`、`result_id`、`task_id`、执行引用、`generated_at`、`content_hash` 和 `result_reference`。

“完整保存”不等于无限制保存任意文本。目标机械边界应按字段和总对象大小明确设置，并遵循：

1. 超过边界时在结果生成阶段明确拒绝或要求把大型内容写入受控制品并提交引用，不能接受后再静默截断。
2. 字符串、数组项数、单项大小和总编码字节数分别设限；不能只用一个 600 字符常量覆盖全部字段。
3. 哈希基于规范化后的完整业务字段计算；摘要、展示裁剪和换行渲染不改变正式内容哈希。
4. 结果中不得无边界复制敏感日志、凭证、完整命令输出或所有中间推理；保存父任务验收所需的业务结果和证据引用即可。
5. 如果某个字段为了通知或恢复摘要需要裁剪，必须标明摘要性质并同时携带正式结果引用；摘要裁剪不能回写覆盖权威结果。

### 6. 存储形态与生命周期建议

目标实现优先采用本地、私有、文件型结果存储，不引入数据库、后台服务或第二套编排平台。候选边界为：

```text
PreparedResultStore
  → SubagentStop 机械验收与原子提交
  → ResultStore 按 result_id 保存正式 TaskResult
  → StateStore 只保存 result_reference、摘要和 action-required 状态
```

ResultStore 应复用 SG-F05 已确认的安全属性：当前用户私有目录、普通文件、`0600`、安全路径、大小检查、临时文件、`fsync` 和原子替换。它可以复用公共安全辅助实现，但数据职责、保留策略和损坏隔离不能与 session StateStore 混为同一个 JSON。

需要为以下生命周期建立明确规则：

- prepared result 在正式提交前短期保存，具有 TTL、单次消费和清理边界。
- 正式结果按 `result_id` 不可变保存；任务记录只更新权威引用和必要状态。
- 结果读取失败、文件损坏或哈希不符时，StateStore 保留引用和 degraded 诊断，不伪造完整结果。
- SessionEnd 不应因为删除 session 运行状态而立即删除仍需父任务处理或仍在保留期内的正式结果。
- 结果保留期、数量/总字节上限、用户主动清理和孤儿 prepared/result 文件回收需要独立策略。
- N/N-1 运行缓存必须能识别结果协议版本；不能让两个版本用不同规则改写同一个不可变结果。

### 7. 改进建议

1. 删除正式结果对 `_bounded(..., 600)` 的依赖；保留 600 字符常量只用于确实需要该边界的单个输入/摘要字段，或拆成语义明确的独立常量。
2. 实现独立 `TaskResult` 模型和 ResultStore；StateStore 只保存稳定引用、状态、有限摘要和父任务动作。
3. 所有截断从“保存时静默删除”改为“生成时明确越界错误”或“通知层有标记摘要 + 正式引用”。
4. 为正式结果增加 `result_id`、生成时间、执行身份、内容哈希、协议版本和结果引用；为错误结果保存错误对象与候选引用。
5. 将原生 thread 定位为人工查看与补充诊断来源，不把它当作结果恢复必需条件；父 Agent 正常闭环只依赖正式结果和通知。
6. 让 SessionStart、Stop 和父任务通知只读取有限摘要及 action-required 字段，避免完整结果反复注入造成新的上下文污染。
7. 定义大型证据的受控引用方式和存在性/哈希检查；不把任意外部路径、临时日志或敏感内容直接视为长期可信证据。
8. 对结果存储不可用与 StateStore 不可用分别降级：原生停止可以放行，但必须明确正式结果是否未创建、未提交或不可读取。

### 8. 可以局部直接实施的内容

本项没有适合在当前协议下孤立切换的运行时代码：

- 不能只删除 600 字符截断并把完整终态全文写回 StateStore；这会直接放大 4 MB 状态上限、终态容量、会话读取和损坏隔离风险。
- 不能只把上限从 600 提高到更大数字；它仍然是静默丢内容，且没有完整结果身份、摘要层或引用层。
- 不能只增加 `result_truncated=true`；这只能暴露现状，不能恢复已经丢失的证据和后续动作，也不能解决上游原生摘要边界。
- 不能把完整子 Agent thread 复制进状态文件；这会把治理状态变成 transcript 仓库，并增加敏感信息与容量风险。
- 不能只新增 ResultStore 文件而不切换生成、验收、状态引用、父任务通知和清理路径；否则会形成两份都不权威的结果。

当前可以直接完成的只有盘点和验证输入：

- 明确记录本地确定性 600 字符截断与原生平台容量风险的区别。
- 记录当前无截断标识、无结果身份、无消费方和无长结果测试。
- 建立正式结果、StateStore 引用、父任务通知和用户摘要四层模型。
- 把 ResultStore 的安全属性、容量、保留、损坏隔离和 N/N-1 兼容要求交给统一方案。

若用户后续单独授权过渡性运行时修补，可以优先增加“原始字符数、是否截断和完整内容哈希”的诊断元数据及回归测试，使当前静默丢失变为可观察；但该修补只能作为迁移期诊断，不能替代正式 ResultStore，也不应先于最终字段命名和敏感信息规则孤立提交。

### 9. 必须留待最终统一方案的内容

- ResultStore 的目录、文件命名、权限、单文件/总容量、保留期、清理和损坏隔离策略。
- 正式 TaskResult 的最大编码字节数，以及每个业务字段、数组和大型证据引用的边界。
- `result_id`、执行引用、`generated_at`、`content_hash` 和 `result_reference` 的最终生成与验证规则。
- 正式结果、protocol error、平台错误、中断和派发失败是共用结果信封还是使用互相引用的不同对象。
- PreparedResult 提交到 ResultStore、StateStore 更新结果引用之间的崩溃一致性和可恢复提交协议。
- SessionEnd、状态裁剪、用户主动关闭、任务重新执行和项目卸载时，正式结果与 prepared result 如何分别清理。
- 原生 thread 不可见、历史被压缩或主线程只收到摘要时，父任务通过何种稳定读取入口取得正式结果。
- 大型本地制品引用的允许根目录、存在性、权限、哈希、生命周期和失效提示。
- 结果内容中的凭证、隐私、绝对路径和完整日志是否需要生成期拒绝、脱敏或只保存摘要。
- N/N-1 版本并存时结果 Schema、只读兼容、写入者唯一性和迁移门禁。

### 10. 当前测试与证据缺口

- `test_successful_result_document_matches_schema` 只确认简化对象具有字段和枚举，没有断言超过 600 字符时的行为、截断标识、原始长度、内容哈希或可恢复引用。
- 当前没有长 `last_assistant_message` 测试证明后半段证据、剩余事项和父任务下一步会被截断；该行为目前只能从 `_bounded()` 与 `MAX_CONTRACT_TEXT` 直接推导。
- 没有测试证明 `evidence` 和 `remaining` 从 AI 业务参数保存；当前固定空数组只满足形状断言。
- 没有独立结果文件的权限、符号链接拒绝、原子写、并发提交、容量、损坏隔离、保留或清理测试。
- 没有 ResultStore 提交成功但 StateStore 引用更新失败，或引用已写入但结果文件损坏/缺失的崩溃一致性测试。
- 没有 SessionEnd 删除运行状态后结果仍可读取，以及状态裁剪不会误删 action-required 结果的测试。
- 生命周期 fixture 只包含短成功终态，不能证明长结果、blocked、needs_decision、protocol_error 或大型证据引用的保存行为。
- handler 单元测试和 fixture 不能证明真实 Codex 平台对 `last_assistant_message`、主线程 summary、独立 Agent thread 和长输出采用何种固定截断阈值；官方文档也没有提供该保证。

### 11. 本项结论

- 本功能点必须保留，并从“在 session 状态里保存 600 字符终态片段”改造成“保存不可变的结构化正式结果，状态与通知只持有引用和有限摘要”。
- 当前 600 字符截断是插件自身已经确认的静默数据丢失；原生子 Agent 回传只应视为存在上下文和摘要边界风险，不能虚构固定截断规则或完整无损保证。
- 完整结果、父任务通知和用户摘要必须分层；完整不等于保存无限 transcript，而是完整保存经过边界校验的业务字段和受控证据引用。
- 直接放大或删除截断上限都会与 SG-F05 的 4 MB 状态容量、裁剪和会话生命周期冲突；正式切换必须与 ResultStore、结果引用、父任务通知、幂等冲突和版本兼容一起实施。
- 当前不修改运行时、Schema、规则、Skill、测试或 fixture；本轮只把本项现状、原生平台边界和统一改造输入写入 SG-F06 文档。

## 九、第 7 项：幂等、冲突和迟到结果处理

### 1. 当前情况

当前 StateStore 使用独占文件锁、原子替换和目录 `fsync`，能够防止普通并发写把 session JSON 写坏，也能保留多个并发 spawn 创建的任务记录；但这只是存储层原子性，不等于终态结果提交已经具备业务幂等、冲突判断或事件时序保护。

本项盘点开始时，`_handle_subagent_stop()` 的处理顺序为：

```text
锁内 read 后释放锁
  → 根据旧快照判断 Agent 映射、任务状态和 retry_count
  → 执行自然语言终态检查
  → 再次进入 store.update() 获取锁
  → 回调只检查 task_id 仍存在
  → 写入 complete / blocked / needs_decision / retry_required / protocol_error
```

因此原实现存在检查—写入竞态：初次读取后到真正写入前，如果 `interrupt_agent`、`list_agents`、另一个 `SubagentStop`、映射修正或其他生命周期事件改变任务，旧 SubagentStop 仍可能覆盖较新的 `interrupted`、`platform_error`、终态或映射决定。

原实现具备但不能称为完整幂等协议的保护包括：

- 调用开始前已经属于 `TERMINAL_STATUSES` 的任务会直接放行，普通顺序下不会再次覆盖。
- 失效映射清理已经在锁内重新检查 `agents[agent_id]` 与任务记录是否仍符合清理条件；映射已变化时不会误删。
- 成功 interrupt 已经在锁内确认当前状态属于 `INTERRUPTIBLE_STATUSES`；调用开始前已 complete 的任务不会被迟到 interrupt 覆盖。
- `SubagentStart` 不会仅凭启动事件复活调用开始前已经终态的任务。

这些保护仍无法回答以下问题：

- 两次 SubagentStop 是否提交同一个结果。
- 相同 `result_id` 是否被替换成不同内容。
- 两个不同结果是否竞争同一执行。
- 结果属于原执行、恢复后的执行还是重新派发后的执行。
- 相同无效事件是否重复消耗纠正预算。
- 已有终态后到达的不同结果是冲突、迟到、篡改还是合法的新执行结果。
- 结果已提交但父任务通知重放时是否会重复展示或重复采取动作。

### 2. 本轮发现并直接修补的竞态

用户明确授权后，本轮已经把完成、重试和纠错上限三条写入路径改为锁内 compare-and-set。`_handle_subagent_stop()` 在初次读取时保存预期状态和 `retry_count`，真正写入时重新核对：

- `tasks` 和 `agents` 仍为对象。
- `agents[agent_id]` 仍指向同一 `task_id`。
- 目标任务仍存在且是对象。
- 任务状态仍等于初次读取的预期状态。
- `retry_count` 未在检查期间变化。
- 尚不存在 `result_document`。

任一条件发生变化时，当前事件不再写入 complete、retry_required 或 protocol_error，也不覆盖较新状态；handler 放行原生停止并返回明确告警：已保留较新状态，交给父任务对账。

这项修补解决的是“旧快照覆盖新状态”，不是完整幂等协议。当前仍没有 execution ID、result ID、内容哈希或事件 ID；如果旧执行与新执行恰好复用相同 Agent 映射、状态和 retry_count，运行时仍无法识别它们属于不同执行。

### 3. 与前后文的交接

#### 上游交接

- 第 1 项提供执行状态、业务结果、平台观察和父任务动作的分层语义；本项的优先级不能继续依赖一个混合 `status`。
- 第 2 项生成 `result_id`、执行引用、内容哈希和结果收据；没有这些身份，本项只能防止覆盖，不能判断相同或冲突。
- 第 4 项在 SubagentStop 中完成绑定、Schema、哈希和预期状态校验；本项复用同一个锁内提交边界。
- 第 5 项提供 `submission_attempt_id` 和稳定错误码；重复协议事件不能继续按 Hook 次数消耗纠正预算。
- 第 6 项提供不可变 ResultStore；已有正式结果必须通过引用读取，不能由后来事件静默改写。
- SG-F05 提供 StateStore 锁、Agent 映射、恢复状态和生命周期事件；本项定义业务结果提交的 compare-and-set 条件及冲突语义。

#### 下游交接

- 第 8 项依据正式结果和通知身份去重父任务通知；幂等结果重放不能导致重复用户提示、重复恢复或重复决策请求。
- SessionStart/compact 恢复应引用当前权威结果和未解决冲突，不应把每次重复事件都展示成新终态。
- SG-F04 需要保证 N/N-1 运行版本不会用不同结果身份或冲突规则共同写同一个状态/结果存储。
- 后续诊断功能可以展示 conflict、late、tampered 和 state-degraded 事实，但不拥有结果优先级或覆盖规则。

### 4. 目标身份层次

目标协议至少需要区分四种身份，不能只依赖 `task_id` 或 Agent ID：

| 身份 | 作用 |
| --- | --- |
| `task_id` | 表示父任务定义的治理工作项，可以跨恢复保持稳定 |
| `execution_id` | 表示一次实际执行或恢复后的执行世代，用于识别旧执行迟到结果 |
| `submission_attempt_id` | 表示一次结果提交尝试，用于纠正预算和事件重放去重 |
| `result_id` | 表示一个正式候选结果；提交成功后成为不可变正式结果身份 |

`content_hash` 基于规范化业务字段计算，用于确认同一 `result_id` 的内容是否一致。它不能代替 `result_id`：相同内容可能来自不同执行，不同执行仍需保留独立身份和时序。

如果平台不能直接提供稳定 execution ID，生成器和状态机需要在派发、恢复或重新执行时机械生成执行世代，并通过 prepared result 与 Agent—任务映射绑定；不能从时间、task name 或终态文本猜测执行身份。

### 5. 目标处理矩阵

| 场景 | 目标行为 |
| --- | --- |
| 相同 `result_id`、相同 `content_hash` 重放 | 幂等返回已提交结果引用；不重复写入、不增加纠正次数、不重复通知 |
| 相同 `result_id`、不同哈希 | 记录完整性错误或 tampered result；拒绝覆盖，不要求 Agent 盲目改写 |
| 不同 `result_id` 同时竞争同一 `execution_id` | 第一个满足锁内提交条件的结果成为正式结果；其他保存为 conflict 候选并交父任务对账 |
| 同一执行已有正式结果后又提交不同结果 | 保留原结果不可变，记录 result conflict；不能静默忽略到完全没有证据 |
| 旧 `execution_id` 的结果迟到 | 不改变当前执行状态和权威结果；保存有界 late-result 记录及候选引用 |
| 新执行合法提交结果 | 使用新的 execution/result 身份提交；旧结果继续不可变保留并与原执行关联 |
| 相同 protocol submission event 重放 | 返回已有 attempt 处理结果，不重复消耗纠正预算 |
| 状态或 Agent 映射在提交期间变化 | compare-and-set 失败，保留较新状态并记录 state/binding conflict |
| interrupt 与结果竞争 | 锁内按执行身份和已提交事实决定；迟到 interrupt 不覆盖已完成结果，迟到结果也不把已关闭执行改回完成 |
| platform_error 与结果竞争 | 平台观察与业务结果分层保存；是否接受该执行的结果由事件身份和提交时序决定，不用平面状态互相覆盖 |
| ResultStore 成功但 StateStore 引用失败 | 进入可恢复的部分提交状态，通过 result ID 对账，不能创建第二个正式结果 |
| StateStore 已引用结果但结果文件缺失/损坏 | 保留引用和 degraded 诊断，禁止用新候选静默填补同一 result ID |

“第一个合法提交生效”必须建立在明确执行身份、锁内预期状态和不可变 ResultStore 之上，不等于简单按墙钟时间选择最早文件。冲突和迟到结果需要留有界证据，但不自动取代正式结果。

### 6. 改进建议

1. 以本轮新增的锁内 compare-and-set 作为所有正式结果、纠正状态和错误对象写入的统一基础，不再允许 handler 先读后无条件覆盖。
2. 为派发、恢复和重新执行生成稳定 `execution_id`；Agent ID、canonical path 和 task name 只用于平台关联，不作为执行世代身份。
3. 为每次提交生成 `submission_attempt_id` 和 `result_id`，并以规范化业务字段计算 `content_hash`。
4. ResultStore 使用 create-if-absent 或等价不可变提交；相同结果幂等读取，不同内容不能覆盖同一 result ID。
5. StateStore 在同一锁内检查预期 execution、任务状态、Agent 映射、已有结果引用和提交 attempt，再写入权威结果引用。
6. 冲突、迟到和完整性错误使用稳定分类及候选引用，不把完整候选内容重复塞入 StateStore。
7. 将纠正预算绑定 submission attempt，不绑定 SubagentStop 事件次数；平台重放同一事件不得消耗新次数。
8. 为父任务通知增加通知身份或以 result ID 幂等投递；相同正式结果只形成一次待处理动作。
9. 为事件乱序定义单调规则：旧执行事件不能改变新执行，已提交结果不能被迟到中断覆盖，平台健康观察不能推断业务完成。
10. 所有冲突处理保持 fail-safe：保留权威状态和原生可见结果，明确要求父任务对账，不自动选择内容更多或时间更新的候选。

### 7. 本轮已直接实施的内容

本轮已修改 `scripts/subagent_governance.py` 的 SubagentStop 写入区段：

- 新增统一锁内目标核对逻辑。
- complete/blocked/needs_decision 的结果写入只有在 Agent 映射、预期状态、retry_count 和正式结果均未变化时提交。
- retry_required 写入不再使用旧快照无条件覆盖，且不会在映射变化后增加 retry_count。
- protocol_error 写入不再覆盖检查期间到达的 platform_error、interrupted 或其他状态。
- compare-and-set 失败时返回明确 systemMessage，保留较新状态并交父任务对账。

本轮在 `tests/test_governance.py` 新增三个受控竞态测试：

1. 初次读取后任务转为 `interrupted`，成功终态不能覆盖或写入 `result_document`。
2. 初次读取后 Agent 映射改到其他任务，无效终态不能写入 retry_required 或增加 retry_count。
3. 达到补充上限后、真正写入前任务转为 `platform_error`，不能再覆盖为 protocol_error。

新增测试与原有成功终态、补充上限、已有终态保护和写入失败降级共 8 项定向测试已经通过。

本轮完成后全仓 `python3 -m unittest discover -s tests -v` 共 150 项通过；`python3 -m py_compile scripts/subagent_governance.py`、Plugin validator、`git diff --check` 和 SG-F06 文档尾随空白检查均通过。本轮未修改 Skill，因此未重复运行 Skill validator。

### 8. 仍不能局部直接实施的内容

- 不能只按终态文本计算哈希并把它当作正式 result ID；当前文本可能被摘要或截断，也混合状态卡和展示内容。
- 不能只使用 Agent ID 判断迟到结果；同一 Agent 可以恢复或继续执行，Agent ID 不表达执行世代。
- 不能只用 `updated_at` 或事件到达时间决定先后；墙钟相同、事件乱序、跨进程延迟和旧版本写入都会产生错误优先级。
- 不能把“任务已经终态则忽略”当作冲突处理；它保护原状态，但会丢失不同候选、迟到来源和父任务待办证据。
- 不能只给 result_document 增加 `result_id`，而不建立生成器、PreparedResult、不可变 ResultStore 和锁内 execution 绑定。
- 不能孤立实现通知去重；第 8 项必须先确认父任务通知的稳定参数、结果引用和真实投递边界。

### 9. 必须留待最终统一方案的内容

- task、execution、submission attempt、result 和 notification 五类身份的最终字段与生成时机。
- 恢复同一 Agent、重新执行、重新派发和父任务要求补充结果时，execution ID 是否延续或递增。
- ResultStore create-if-absent、StateStore 结果引用和 prepared result 消费之间的原子性/补偿协议。
- 同一 result ID 不同哈希、同一执行不同 result ID、不同执行相同内容的分类和父任务动作。
- conflict、late_result、tampered、partial_commit 和 orphan result 的正式 Schema、容量及保留期。
- interrupt、SubagentStop、list_agents、follow-up、SubagentStart 和 SessionEnd 的完整事件优先级矩阵。
- protocol submission event 的稳定身份，以及真实 Codex block 重入是否会重用或重新生成事件标识。
- 通知投递成功、重复、失败和父任务已经处理后的迟到通知如何幂等对账。
- SessionEnd、状态裁剪和结果清理如何保留 unresolved conflict，又不无限积累候选。
- N/N-1 运行版本对新身份、不可变结果和旧自由文本任务的兼容、隔离或拒绝门禁。

### 10. 当前测试与证据缺口

- 本轮三个受控假 Store 测试证明 read/update 间状态或映射变化不会被覆盖，但没有运行真实多进程 SubagentStop 与 interrupt/list 的竞争。
- `tests/test_concurrency.py` 仍只覆盖 32 个并发 spawn，不覆盖双结果提交、重复事件、ResultStore、SessionEnd 或进程崩溃。
- 现有“已有终态不覆盖”测试只证明顺序保护，不区分相同结果重放、不同结果冲突或旧执行迟到。
- 没有 execution ID、result ID、submission attempt 或内容哈希测试，因为对应协议尚未实现。
- 没有同一 result ID 不同哈希、两个不同 result ID 同时提交、ResultStore 部分成功和孤儿结果测试。
- 没有相同无效 SubagentStop 重放不消耗纠正预算的测试；当前缺少稳定事件/attempt 身份，无法可靠实现。
- 没有恢复同一 Agent 后旧执行终态迟到、canonical path 重用或 task name 重名下的结果隔离测试。
- fixture 没有 duplicate、conflict、late、tampered 或 interrupt/result 竞争场景。
- handler 测试不能证明真实 Codex 的 SubagentStop、interrupt、list、follow-up 和 SubagentStart 事件顺序或重复投递行为。

### 11. 本项结论

- 本功能点必须保留，是结果协议与生命周期并发之间的核心正确性边界。
- 本轮已经直接修复最明确的旧快照覆盖问题：完成、补充和 protocol_error 写入现在必须在锁内重新确认映射、预期状态、retry_count 和已有结果。
- 该修补只保证“状态已变化则不覆盖”，还不能判断相同结果、不同结果或旧执行迟到；完整语义必须依赖 execution ID、submission attempt、result ID、内容哈希和不可变 ResultStore。
- 目标行为是相同结果幂等、不同结果留痕冲突、旧执行迟到不覆盖、重复协议事件不重复计数、父任务通知不重复动作。
- 完整身份和冲突协议必须与第 2、4、5、6、8 项及 SG-F05 生命周期状态原子设计；不能继续用任务终态、Agent ID 或事件到达时间替代。

## 十、第 8 项：父任务通知与用户摘要闭环

### 1. 当前情况

当前终态闭环由三条没有机械绑定的链路组成：

```text
子 Agent 原生最终回复
  → Codex 平台向父线程返回 summary/result 或 mailbox 更新

SubagentStop
  → Hook 读取 last_assistant_message
  → 验收并更新治理状态/result_document
  → 返回 continue、decision=block 或 systemMessage

父 Agent
  → 观察原生回传和治理状态
  → 自行判断业务完成、恢复、阻塞或需要决策
  → 向用户生成主对话摘要
```

当前已经确认：

- `SubagentStop` 成功接受结果时通常只返回 `{"continue": true}`，不主动调用 `send_message`、`followup_task` 或其他父任务通知工具。
- 简化 `result_document` 写入 StateStore 后没有运行时代码读取、投递或确认父 Agent 已经观察。
- protocol_error、状态故障和 compare-and-set 冲突路径会返回 `systemMessage`，但这只是 Hook 输出；handler 测试不能证明父 Agent、用户或真实主线程展示已经看到该信息。
- Skill 要求父 Agent 显式调用 `wait_agent` 等待终态，mailbox 更新、完成通知或用户输入由 Codex 原生平台唤醒；Hook 不提供定时器，也不能主动唤醒主线程。
- lifecycle fixture 顺序调用 `handle()` 并检查状态变化或 SessionEnd 删除，未捕获真实父线程 summary、mailbox 事件或用户可见最终回复。
- 显式 strict 终态卡只约束子 Agent 最终回复形状，不是投递确认、正式结果存储或父任务业务验收协议。
- 当前没有 notification ID、父任务已观察时间、父任务验收状态、用户已报告状态或结果通知去重记录。

因此当前“子 Agent 停止”“Hook 接受终态”“治理状态写成 complete”“Codex 向父线程返回结果”“父 Agent 业务验收通过”和“主对话已向用户闭环”是六个不同事实，不能互相替代。

### 2. Codex 原生回传边界

OpenAI 官方 Subagents 文档说明：Codex 会把子 Agent 的 summary 返回主对话，主线程收集子 Agent 结果形成最终回复；支持的客户端允许打开独立 Agent thread 查看其工作和结果。官方说明能够证明原生产品具备结果汇总和线程查看能力，但没有证明：

- Hook 的 `last_assistant_message` 与父线程 summary 永远逐字相同。
- `SubagentStop` 返回 `continue` 或 `systemMessage` 就等于父 Agent 已收到通知。
- StateStore 中的 `result_document` 会被 Codex 平台自动读取或投递。
- 父 Agent 已经按原任务完成条件验收结果。
- 用户已经看到关键结论、阻塞或决策请求。

官方证据：[OpenAI Subagents 文档](https://learn.chatgpt.com/docs/agent-configuration/subagents)。本项目应继续使用原生回传和 Agent thread，不建立第二套终态消息平台；治理层只补充稳定结果引用、状态对账和父任务处理语义。

### 3. 当前责任缺口

| 层次 | 当前责任方 | 当前证据 | 缺口 |
| --- | --- | --- | --- |
| 子 Agent 终态内容 | 子 Agent + 派发契约 | 最终回复、strict 卡、治理等级规则 | 仍是自由文本，没有 prepared result 与正式引用 |
| 原生回传 | Codex 平台 | 官方产品说明、父 Agent `wait_agent` 工作流 | 仓库不能证明具体投递时序、完整性和重复行为 |
| Hook 机械验收 | SubagentStop handler | 状态和单元测试 | 只能证明 handler 返回和状态写入，不证明父任务观察 |
| 正式结果读取 | 当前无消费者 | `result_document` 只被写入 | 没有读取接口、result reference 或损坏/缺失处理 |
| 父任务业务验收 | 父 Agent | Skill 自然语言要求 | 没有稳定的验收输入、观察状态或完成确认 |
| 用户摘要 | 父 Agent 主对话 | 主盘点的简洁展示原则 | 没有分场景摘要参数，可能过度倾倒协议或遗漏待办 |

当前规则容易把“向父 Agent 发送明确终态通知”理解成子 Agent 还要额外调用一次消息工具。目标语义应明确：原生最终回复及平台返回父线程的 summary/result 是主要回传；除非父 Agent 明确请求补发，不创建第二份含义相同的终态消息。

### 4. 与前后文的交接

#### 上游交接

- 第 1 项提供业务结果、执行状态、平台观察和 action-required 语义；父任务不能只看平面 status 决定闭环。
- 第 2 项提供正式 TaskResult、结果身份和 `parent_next_step`；通知不从自由文本重新推断这些字段。
- 第 4 项确认结果属于正确 task、Agent 和 execution，并完成机械提交；通知只引用已经提交或明确失败的结果。
- 第 5 项提供 protocol error、可纠正性和父任务动作；达到上限不等于业务失败或用户已经知情。
- 第 6 项提供完整 ResultStore 与有限摘要；父任务正常闭环不能依赖事后打开 thread 复制结果。
- 第 7 项提供结果和通知幂等身份；重复原生回传或 SessionStart 恢复不能触发重复动作。
- SG-F05 提供 wait/list/recovery、Stop、SessionStart/End 和 action-required 状态底座；它不能声明结果内容或父任务业务验收成功。

#### 下游交接

- SG-F03 继续负责父 Agent 主动通信和恢复调用的原生参数，但不应为终态再创建一套 send_message 投递系统。
- SG-F04 需要把真实目标版本中的 wait、SubagentStop、父线程 summary 和用户展示纳入发布 smoke；handler/fixture 只能作为仓库层证据。
- 主对话由父 Agent 根据正式结果和用户上下文生成摘要，脚本只提供稳定字段和有界机械渲染，不替代 AI 选择业务重点。
- 后续诊断功能可以判断 result accepted、notification unknown、parent action pending 等事实，但不能声称修复平台投递。

### 5. 目标闭环阶段

建议把终态闭环明确分成五个阶段：

| 阶段 | 完成条件 | 不能证明的后续事实 |
| --- | --- | --- |
| 结果生成 | 子 Agent 创建合法 PreparedResult | 未证明 Hook 接受或父任务收到 |
| 结果接受 | Hook 完成绑定、Schema、哈希和锁内提交 | 未证明原生回传或父任务业务验收 |
| 原生回传 | Codex 将目标 Agent summary/result 返回父线程 | 未证明正式结果完整或父任务已经处理 |
| 父任务观察与验收 | 父 Agent 核对 Agent、task/execution/result 引用并按完成条件判断 | 未证明用户已经看到结论 |
| 用户闭环 | 父 Agent 报告关键结果、请求决策或说明阻塞/异常 | 不自动表示所有内部记录可立即清理 |

父任务只有在取得对应结果或明确知道结果不可用、完成业务验收并处理所有 action-required 场景后，才能把该子任务视为已闭环。Agent 停止或 Hook 放行不能单独满足该条件。

### 6. 父任务完整通知与用户摘要分层

父任务需要的完整终态上下文至少应包含：

- `task_id`
- `execution_id`
- `result_id`
- `status`
- 关键 `result`
- `evidence[]`
- `remaining[]`
- `parent_next_step`
- `result_reference`
- blocked、needs_decision、failed 等分场景字段
- protocol error、conflict、late result 或 state-degraded 等事实与父任务动作

脚本提供固定字段、枚举、引用和有界渲染；父 Agent 根据真实任务决定哪些业务内容最重要。

主对话用户摘要默认只包含：

- 已完成的主要结果或当前终态。
- 最关键的验证结论和必要文件/结果入口。
- 对用户有影响的风险或剩余事项。
- 当前阻塞条件或需要用户回答的决策问题。
- 父任务接下来已经采取或建议采取的动作。

协议版本、结果哈希、内部存储路径、完整状态转换、重试计数和大段诊断默认不向用户展示；只有定位故障或用户明确要求时才展开。

### 7. 分场景父任务动作

| 场景 | 父任务动作 | 用户摘要重点 |
| --- | --- | --- |
| `complete` | 核对完成条件和证据，继续主任务或报告完成 | 实际结果、关键验证、必要剩余事项 |
| `blocked` | 判断是否能补充条件、恢复同一 Agent 或结束该路径 | 阻塞原因、已尝试内容、解除条件 |
| 业务 `needs_decision` | 向用户提出明确问题、选项影响和建议 | 决策问题、互斥选项、推荐理由 |
| 平台恢复上限 `needs_decision` | 请求用户选择 provider、模型、稍后重试或停止 | 平台事实、已恢复次数、可选动作 |
| `protocol_error` | 判断重新提交、重新执行或接受 state-degraded 结果 | 正式结果是否可用、需要采取的动作 |
| `platform_error` | 依据恢复预算恢复或进入决策 | 平台执行异常，不伪装成业务阻塞 |
| `interrupted` | 确认执行已关闭并处理可能迟到结果 | 中断事实、已有可用产出和剩余事项 |
| result conflict/late | 保留权威结果，审查候选和执行身份 | 仅在影响用户结论或需要决策时展示 |
| 状态/结果存储降级 | 保留原生终态，明确正式结果未提交或不可读取 | 可确认的结果、缺失证据和人工对账需求 |

治理等级可以影响父 Agent 期望的证据强度，但所有等级都应使用同一结果身份、回传阶段和用户闭环原则；不能让 light 的通知可靠性低于 strict，也不能把 strict 内部协议全部展示给用户。

### 8. 本轮已直接实施的内容

用户明确授权后，本轮已经收敛以下规则文字：

- `skills/subagent-governance/SKILL.md` 明确原生最终回复和返回父线程的 summary/result 是主要终态回传通道，不额外复制第二份相同终态。
- 父 Agent 在 `wait_agent` 返回后仍须核对目标 Agent、任务身份和结果；完成通知、Agent 停止或 Hook 状态变化不能单独替代业务验收。
- `SubagentStop` 放行只表示不再阻止当前子 Agent 停止，不表示父任务已收到正式结果、完成业务验收或已经向用户报告。
- 父 Agent 根据正式结果决定继续、恢复、请求决策或结束；Hook 只做机械验收和状态记录。
- 主对话只展示关键业务结果、验证、剩余事项或决策问题，完整过程通过原生 Agent thread 或未来正式结果引用查看。
- `runtime-boundaries.md` 明确插件不创建第二套终态消息通道，`systemMessage`、状态写入和 handler fixture 均不能证明真实父线程投递成功。

`tests/test_governance.py` 已新增静态回归，保护原生回传、Hook 验收、父任务业务验收和用户摘要四者不被重新混写。该测试与现有规则一致性、运行边界和等待编排测试共 4 项定向测试已经通过。

本轮完成后全仓 `python3 -m unittest discover -s tests -v` 共 152 项通过；`python3 -m py_compile scripts/subagent_governance.py`、Plugin validator、Skill validator、`git diff --check` 和 SG-F06 文档尾随空白检查均通过。

### 9. 仍不能局部直接实施的内容

- 不能通过成功 SubagentStop 返回一个更长 `systemMessage` 代替父任务通知；它仍没有真实投递和观察保证，还会重复原生 summary。
- 不能让 Hook 自动调用 send_message；这会建立第二套消息链路、增加重复通知和权限边界，并且 Hook 不拥有父任务目标参数。
- 不能只增加 `notified=true`；Hook 最多知道自己产生了输出，不能证明父 Agent 或用户实际观察。
- 不能把父任务完整结果全部拼进 SessionStart 或主对话；这会造成上下文污染和内部协议泄漏。
- 不能只依赖原生 Agent thread 作为正式结果库；thread 适合人工查看，但不是插件可验证、可版本化和可幂等读取的协议存储。
- 不能孤立增加 notification ID；没有 result ID、正式结果引用和父任务消费入口时，该 ID 没有稳定语义。

### 10. 必须留待最终统一方案的内容

- 父任务读取 `result_reference` 的确定性入口，以及读取失败、损坏、过期或权限错误的处理。
- result、notification 和 parent observation 三类身份及其幂等关系。
- 父任务观察、业务验收、用户报告是否分别记录，以及哪些是自动可观察、哪些只能由父 Agent 显式确认。
- 相同正式结果重复回传、SessionStart 恢复或主线程重入时的通知去重。
- 结果已提交但原生回传缺失，或原生回传成功但结果提交失败时的对账与用户提示。
- blocked、needs_decision、protocol_error、platform_error、interrupted、conflict 和 state-degraded 的正式父任务通知 Schema。
- action-required 任务在 Stop、SessionStart、SessionEnd、状态裁剪和结果清理中的解除条件。
- 真实 wait_agent/mailbox/SubagentStop/主线程 summary/用户最终回复的端到端验收方式。
- N/N-1 版本并存时结果引用、通知阶段和 parent observation 状态的兼容、隔离或拒绝。
- 主盘点、SG-F05 和 `runtime-boundaries.md` 中仍存在的 platform_error/SessionStart/Stop 旧事实漂移；最终合并不能把这些矛盾表述继续并列保留。

### 11. 当前测试与证据缺口

- 新增静态测试只能证明 Skill 和运行边界明确区分责任，不能证明父 Agent 实际按规则执行。
- 成功 SubagentStop 单元测试只断言 `{"continue": true}` 和状态写入，不能证明 Codex 返回 summary 或父任务看到结果。
- protocol error、状态故障和 compare-and-set 冲突测试只断言 `systemMessage` 文本，不能证明真实主线程展示。
- lifecycle fixture 不读取 mailbox、不调用真实 wait_agent，也不捕获父 Agent 或用户最终回复。
- 没有正式结果读取、result reference、notification ID、parent observation 或用户摘要测试。
- 没有 complete、blocked、needs_decision、protocol_error、platform_error、interrupted 和 conflict 的端到端通知矩阵。
- 没有重复原生回传、compact/resume 后重复通知或父任务已处理后的迟到通知测试。
- OpenAI 官方文档证明原生产品汇总结果和展示 Agent thread，但没有提供本项目 Hook 状态与平台投递的机械关联保证。

### 12. 本项结论

- 本功能点必须保留，是“Agent 已停止”转换为“父任务已处理且用户已获得必要信息”的最终责任闭环。
- 项目继续以 Codex 原生最终回复、summary/result 和 Agent thread 为回传通道，不新增第二套终态消息平台。
- SubagentStop、StateStore 和 systemMessage 只提供机械验收、记录和诊断，不得被描述为通知投递、父任务业务验收或用户闭环已经完成。
- 本轮已经直接修正规则责任边界并增加静态回归；稳定结果引用、通知/观察幂等、action-required 解除和真实端到端投递仍需与前七项统一实现。
- 完整结果面向父任务，主对话面向用户只展示关键业务结果、验证、剩余事项或决策问题；两者不能共用一份过度压缩或过度冗长的文本。

## 十一、整体收口、覆盖审查与修改方案输入

### 1. 最终名称与大功能结论

- 最终名称：**子 Agent 终态结果协议、验收与父任务闭环**。
- 一句话职责：把单个子 Agent 的完成、阻塞、需要决策及异常停止转换成可引用、可机械验收、可幂等对账的正式结果，并把完整结果交给父任务处理、把关键结论交给用户，而不替代父 Agent 的业务判断。
- 8 个功能点共同消费同一 task/execution/result 身份和终态事件，拆成“结果协议”和“生命周期验收”两个大功能会让状态、结果提交、冲突处理和父任务闭环形成循环边界，因此继续保留为一个大功能。
- SG-F06 只拥有单 Agent 业务结果及其提交闭环；生命周期执行底座、原生通信、运行诊断和多 Agent 组级汇聚分别留在 SG-F05、SG-F03、SG-F07 和 SG-F08。

### 2. 文件与核心代码区段覆盖

| 文件或区段 | SG-F06 归属 | 当前作用与收口结论 |
| --- | --- | --- |
| `scripts/subagent_governance.py`：`_normalized_message()`、`_terminal_field()`、`_terminal_errors()`、`_reported_status()` | 主要归属 | 当前完成自由文本归一化、字段提取、语义验收和状态推断；目标由结构化结果输入、Schema 和机械校验替代，旧函数只在兼容窗口保留。 |
| `scripts/subagent_governance.py`：`_handle_subagent_stop()` | 主要归属 | 当前负责 Agent/task 关联、自由文本验收、有限补充、protocol_error、CAS 写入和降级放行；是 SG-F06 的运行时主入口。 |
| `scripts/subagent_governance.py`：`_recent_records()`、`_handle_stop()`、`_handle_session_start()`、`_handle_session_end()` | 次要关联，SG-F05 主要归属 | 消费终态和 action-required 分类决定父任务结束、恢复摘要与会话保留；SG-F06 只提供稳定结果/待办语义，不拥有会话处理实现。 |
| `scripts/subagent_governance.py`：`handle()` 的 `SubagentStop` 分支 | SG-F02 接线、SG-F06 业务语义 | 证明终态 handler 已接入统一路由，不证明真实 Codex 投递、父任务观察或用户闭环。 |
| `schemas/task-result-v1.schema.json` | 主要归属 | 当前声明七种状态和最小结果形状，但运行时未执行完整 Schema 校验，字段不足以表达正式结果身份、场景字段、完整性和父任务动作。 |
| `hooks/hooks.json`：`SubagentStop` | SG-F02 主要归属，SG-F06 次要关联 | 注册终态 Hook、命令和超时；业务验收规则不应复制到 Hook 配置。 |
| `skills/subagent-governance/SKILL.md`：终态处理与父任务闭环规则 | 主要归属 | 规定终态证据强度、有限纠正、原生回传、父任务验收和用户摘要责任；生命周期恢复细节与 SG-F05/SG-F03 共享。 |
| `skills/subagent-governance/references/governance-levels.md` | SG-F01 主要归属，SG-F06 次要关联 | 描述 light/standard/strict/auto 的终态证据强度和补充上限；最终不应成为多套结果 Schema。 |
| `skills/subagent-governance/references/runtime-boundaries.md` | SG-F05/SG-F07 共享边界，SG-F06 次要关联 | 明确 Hook、StateStore、`systemMessage` 和 fixture 不能证明真实父线程投递，且不创建第二套终态消息通道。 |
| `assets/agents-governance.md` | SG-F04 分发主要归属，SG-F06 语义输入 | 对外规则资产中的终态通知要求必须与 Skill 和结果协议一致；最终应保持短入口或规范来源，避免重复规则漂移。 |
| `tests/test_governance.py`：SubagentStop、result_document、Schema 形状、补充上限、fail-open、CAS 竞态及终态责任静态测试 | 主要归属 | 保护当前运行行为和本轮局部修补；其中自然语言关键词、长度和 strict 卡测试属于旧兼容行为，不应被误当作目标设计。 |
| `tests/test_hook_fixtures.py` 与 `tests/fixtures/lifecycle-v1.json` 的 SubagentStop 成功区段 | 次要集成归属 | 证明仓库内完整 handler 生命周期可以通过，不证明真实 mailbox、summary 或用户最终回复。 |
| `tests/fixtures/interrupt-v1.json`、`recovery-limit-v1.json` | SG-F05/SG-F03 主要归属，SG-F06 终态交界 | 提供 interrupted、platform recovery limit 和 needs_decision 的生命周期输入，但没有正式 TaskResult 或结果冲突场景。 |
| `docs/project-function-inventory.md`、SG-F04、SG-F05、SG-F07、SG-F08 | 只读上下游证据 | 主文档提供总原则；其他功能分别提供发布兼容、状态底座、诊断消费和组级汇聚边界，均不由 SG-F06 修改。 |

当前运行时核心行区段为：`_normalized_message()` 约 1096 行、`_terminal_field()` 约 1100 行、`_terminal_errors()` 约 1105 行、`_reported_status()` 约 1131 行、`_handle_subagent_stop()` 约 1142 行；生命周期消费区段从 `_recent_records()` 约 1290 行延伸到 `handle()` 约 1484 行。行号只用于本轮定位，最终实施应按函数和语义区段定位，避免并行修改后引用失效。

### 3. 保留、改造、降级和退役结论

| 当前内容 | 结论 | 原因与替代方向 |
| --- | --- | --- |
| task/Agent 映射、必填、类型、枚举、数据体积和引用检查 | 保留并加强 | 属于 Hook 合理的机械职责；应增加 execution/result 绑定、Schema、哈希和版本检查。 |
| 治理状态不可读写、未映射 Agent、失效映射时 fail-open | 保留 | 治理组件不能阻断原生 Agent；同时保留明确诊断和父任务对账事实。 |
| 有限补充和达到上限后退出 | 保留机制、改造触发条件 | 只针对缺失/非法结构或不可验证引用纠正，不能继续因业务措辞、关键词或长度反复阻止。 |
| ACK-only 检查 | 降级为旧自由文本路径的最低防误报 | PreparedResult 存在后不再作为正式结果核心验收；兼容期可提示或诊断明显无结果回复。 |
| 40 字符下限、证据关键词、任务 ID 必须出现在正文 | 退役硬性阻断 | 属于业务语义和表达形式判断，应由结构化字段、任务引用和父 Agent 验收替代。 |
| 显式 strict 固定中文终态卡 Hook 校验 | 从运行时验收退役，保留人类可读指导 | strict 可以提高证据要求，但不应建立另一套正式结果格式；结构化结果应跨治理等级统一。 |
| `_reported_status()` 未识别时默认 `complete` | 退役 | 缺失或非法 status 应是机械协议问题，不能被静默转换为完成。 |
| `result_document.result` 使用 `_bounded(..., 600)` | 从正式结果路径退役 | 静默截断会丢失业务结果和证据；完整内容应写入独立结果存储，状态中只保存有界摘要和引用。 |
| `result_document.evidence/remaining` 固定空数组 | 退役 | 应由 AI 根据真实任务提供并由结构化输入保留，脚本不能伪造为空。 |
| StateStore 内嵌、无消费者的临时 `result_document` | 迁移而非原地扩字段 | 目标是不可变 ResultStore 加 StateStore 引用；只增加几个字段不能解决读取、原子性、冲突和容量问题。 |
| `retry_required` 同时承担终态补充和平台恢复 | 拆分 | 协议提交纠正和平台执行恢复具有不同触发、预算和父任务动作，应进入多维状态模型。 |
| `task-result-v1` 只声明 Schema、不做运行时验证 | 改造 | Schema 不是无用文件，但当前只是文档和测试形状；目标应成为生成、提交和兼容验证的共同语义来源。 |
| 原生最终回复、summary/result 和 Agent thread | 保留为主要回传 | 治理层增加结果引用和对账，不建立第二套消息平台，也不宣称修复 provider 传输。 |

`_normalized_message()`、`_terminal_field()`、`_terminal_errors()` 和 `_reported_status()` 目前仍有兼容调用，不能按“无 import”直接删除；它们应随结构化结果双路径迁移逐步缩小，待 N/N-1 兼容窗口和旧自由文本 fixture 退出后再删除。`dispatched` 没有当前写入者的疑点属于 SG-F05 状态模型，不在 SG-F06 单独删除。

### 4. 已直接实施与尚未实现的边界

本轮用户授权后已经直接完成：

1. `_handle_subagent_stop()` 在 complete、retry_required 和 protocol_error 写入前进行锁内 compare-and-set，重新核对 Agent 映射、任务状态、retry_count 和已有结果，避免旧快照覆盖较新生命周期状态。
2. 新增三个受控竞态测试，覆盖 interrupted 后旧完成结果、映射变化后的补充写入和 platform_error 后 protocol_error 覆盖。
3. Skill 和 `runtime-boundaries.md` 已明确原生回传、Hook 验收、父任务业务验收和用户摘要是不同责任阶段，不创建第二套终态消息通道。
4. 新增静态规则回归，防止把 `continue`、StateStore、`systemMessage` 或 fixture 重新描述为真实父任务投递成功。

上述修改只修复确定的状态覆盖和责任表述问题。当前**尚未实现**：

- `TaskResultInput`、PreparedResult、正式 `TaskResult` 或独立 ResultStore。
- `result_id`、`execution_id`、`submission_attempt_id`、`content_hash` 和 `result_reference`。
- 相同结果幂等、不同结果冲突、旧 execution 迟到、篡改和部分提交处理。
- runtime JSON Schema validator、完整结果读取入口或跨版本迁移器。
- notification ID、parent observation、父任务验收确认或用户报告确认。
- 真实 Codex mailbox/summary/SubagentStop/用户最终回复端到端投递保证。

因此不得把本轮 CAS 修补描述为已经完成结果幂等协议，也不得把规则文字修改描述为已经实现父任务通知。

### 5. 测试与 fixture 覆盖结论

当前已经覆盖：

- standard、light、显式 strict 和 auto 提升的现有自由文本终态行为。
- complete、blocked、needs_decision 的当前状态推断和成功 `result_document` 基本形状。
- ACK-only、长度/证据要求、补充上限和 protocol_error 的现有兼容行为。
- 未映射 Agent、失效映射、已有终态、非活跃状态和状态读写失败时的保护或降级。
- 初次读取与最终写入之间状态、映射或 retry_count 变化的 CAS 保护。
- lifecycle fixture 中的单一路径成功终态，以及 SG-F05 fixture 提供的中断和恢复上限交界。

仍缺少：

- complete、blocked、needs_decision、failed、interrupted、platform_error、protocol_error 和 conflict 的统一结构化结果矩阵。
- runtime Schema 校验、字段容量、Unicode、大结果、证据列表、结果引用和完整内容读取测试。
- duplicate、conflict、late、tampered、partial commit、orphan result 和跨进程竞争测试。
- 恢复同一 Agent 后旧 execution 结果迟到、相同提交事件重放不重复消耗纠正预算和 notification 去重测试。
- SessionStart/Stop/SessionEnd 对 action-required、结果引用、冲突和结果清理的统一测试。
- SG-F07 对正式结果引用的只读诊断测试，以及 SG-F08 对 individual TaskResult 的组级汇聚契约测试。
- N/N-1 版本同时读取状态和结果协议的兼容、隔离或拒绝测试。
- 真实 Codex 的 `wait_agent`、mailbox、SubagentStop、summary/result、Agent thread 和主对话用户摘要端到端验收。

单元测试和 fixture 只能证明仓库 handler 行为，不得作为 Codex 平台投递顺序、原生 summary 完整性或父任务已经验收业务结果的证据。

### 6. 跨功能交界和当前矛盾

- **SG-F01 → SG-F06**：SG-F01 提供任务身份、治理等级和完成条件；SG-F06 生成结果。治理等级只影响父任务期望的证据强度，不应产生四套结果协议。
- **SG-F02 → SG-F06**：SG-F02 拥有 Hook 注册和统一事件路由；SG-F06 只拥有 `SubagentStop` 的终态业务语义与机械提交。
- **SG-F03 ↔ SG-F06**：SG-F03 拥有 `send_message`、`followup_task` 和恢复消息；SG-F06 继续使用原生最终回复和 summary/result，不新增终态消息通道。
- **SG-F04 ↔ SG-F06**：SG-F04 拥有发布、N/N-1 缓存和真实目标版本验收；SG-F06 提供结果/状态兼容要求，不能用开发仓库 handler 测试证明已发布版本真实投递。
- **SG-F05 ↔ SG-F06**：两者必须共同拆分执行状态、业务结果、平台观察和 action-required，并设计 StateStore、PreparedContractStore 和 ResultStore 的引用/生命周期；任一侧孤立调整状态枚举都会产生错误结束或错误清理。
- **SG-F07 ← SG-F06**：SG-F07 只读诊断结果是否存在、引用是否可读、完整性是否通过和父任务下一步；不得生成、修复或改写正式结果。
- **SG-F08 ← SG-F06**：SG-F08 消费 individual TaskResult 进行组级 fan-in、依赖和汇聚；单任务结果不能同时承担 coordination、wave 或聚合状态。

最终合并任务必须解决的文档漂移包括：

1. 主盘点文档仍只把 SG-F01～SG-F03 标为完成，并保留部分 platform_error、Stop、SessionStart 和终态验收旧快照。
2. SG-F05 已完成收口，但部分跨文档说明记录的是 SG-F06 较早状态；最终合并不能把“SG-F06 尚未修正”和本文当前结论同时保留。
3. `runtime-boundaries.md` 中生命周期事实应以 SG-F05 最新运行时为准，终态投递边界以 SG-F06 为准，诊断输出边界以 SG-F07 为准。
4. SG-F07 和 SG-F08 仍在逐项盘点；它们可以消费 SG-F06 的结果和引用，但不能反向扩张 SG-F06 为诊断引擎或多 Agent 编排器。
5. 不同文档记录的全仓测试总数来自不同并行时点，最终合并应记录验证命令和当次结果，不把 146、150、151、152 等历史数量当作协议事实。

### 7. 最终统一修改包建议顺序

1. **共同确定状态与身份协议**：SG-F05/SG-F06 先确定 task、execution、submission、result、notification 身份，多维状态、action-required 和事件优先级。
2. **建立结构化结果生成与存储**：实现 `TaskResultInput`、PreparedResult、正式 TaskResult、不可变 ResultStore、StateStore 引用和版本化 Schema。
3. **提供 N/N-1 双路径兼容**：新路径提交结构化结果；旧自由文本路径只做有界兼容和诊断，不静默伪造完整结果。
4. **收敛 SubagentStop 机械验收**：保留关联、类型、枚举、容量、版本、哈希和引用检查，移除关键词、40 字符、正文任务 ID 和 strict 固定卡硬阻断。
5. **实现幂等与冲突协议**：覆盖相同结果重放、不同结果竞争、旧 execution 迟到、篡改、部分提交、状态降级和冲突留痕。
6. **实现父任务消费闭环**：提供稳定结果读取、原生回传对账、parent observation、业务验收动作和简洁用户摘要输入，但不建立第二套消息平台。
7. **接入生命周期、诊断和组级汇聚**：SG-F05 消费 action-required 和清理规则，SG-F07 只读诊断引用，SG-F08 按 individual TaskResult 汇聚。
8. **完成跨版本和真实 Codex 验收**：由 SG-F04 发布候选执行 N/N-1 状态/结果兼容及真实 wait/mailbox/SubagentStop/summary/用户闭环 smoke。

这八步应作为一个有依赖顺序的统一修改包规划；不应先删除旧自由文本路径、单独扩大 Schema、单独增加 result ID 或单独增加通知字段。

### 8. 整体收口结论

- SG-F06 的 8 个功能点、主要文件、核心代码区段、测试证据、疑似退役内容、未覆盖边界和跨功能交接已经完成盘点。
- 当前最需要保留的是机械关联、有限结构纠正、fail-open 和锁内不覆盖保护；最需要改造的是平面状态、自由文本语义验收、临时结果对象、600 字符截断和无身份的父任务闭环。
- 当前没有可以继续孤立直接修改而不影响状态、兼容或结果协议的运行时代码；后续改动应进入上述统一修改包。
- 本文作为最终合并任务的 SG-F06 事实输入，不替代最终跨功能协议决策，也不授权发布、安装、外部写入或修改其他盘点文档。
