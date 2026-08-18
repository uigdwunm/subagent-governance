# D7 拆除 PreparedContract 派发门禁

日期：2026-08-15

状态：用户已确认删除 PreparedContract 门禁和插件专属 `task_name` 约束；本文已按平台能力 Slice 1-5 最终收口事实修订，等待独立新对话实施。本文只记录设计和实施交接上下文；修订本文时未修改运行时代码、Schema、Skill、测试、稳定发布源、运行缓存、Hook trust、Marketplace 或 Registry，也未创建真实测试对话。

本文是 `platform-capability-final-acceptance-report.md` 之后的新简化设计，不属于平台能力 Slice 6，也不新增 Hook、Start/Stop、freshness、parent Stop 或 provider authority。现有 Slice 1-5 最终 GO 和关键文件哈希只覆盖 D7 实施前基线；一旦实施 D7，必须重新完成本地门禁、独立审查和新的真实派发/结果 smoke，不能沿用旧 GO 宣称新实现已验收。

## 1. 新对话执行摘要

后续实现对话应先完整阅读本文件、仓库根目录 `AGENTS.md`、`schemas/codex-hook-events-v1.contract.json`、`tests/fixtures/exact-task-ref-opaque-message-v1.json`、`docs/redesign/platform-capability-contract-and-minimal-state-machine.md`、`docs/redesign/platform-capability-slice-5-implementation.md`、`docs/redesign/platform-capability-slice-6-design.md` 和 `docs/redesign/platform-capability-final-acceptance-report.md`，再检查当前工作树和实际代码，不得只依据本节摘要直接删除。

实施目标：

1. 删除 `PreparedContract` 独立存储、发送前硬门禁、短期凭证消费、双写回滚和过期清理。
2. 删除 `task_ref` 及 `sg_<mode>_<semantic_name>_t_<task_ref>` 强制命名身份链；插件不再规定、锁定或校验任何专属 `task_name` 格式。`task_name` 只受原生工具自身 schema 约束，不再参与 correctness。
3. 保留 TaskContract、用户可见派发说明、结构化派发 prompt、StateStore、四平面 execution、原生调用三值观察、Agent target、等待/恢复/通信/中断、正式结果和父 Agent 处置。
4. Hook 不再从 `task_name` 或 `message` 获取派发身份。真实平台 fixture 已证明 PreToolUse 中 `message` 可能是 opaque transport；正文只由生成器在平台处理前写给子 Agent，不作为 Hook correctness 输入。
5. `prepare_dispatch`、`prepare_spawn_retry` 和 `prepare_replacement_dispatch` 只写唯一长期权威 StateStore：在同一个 CAS 中创建 canonical execution/dispatch generation 并返回 `task_id + attempt + generation + spawn_args`。不再双写 PreparedContract。
6. spawn 的 PreToolUse/PostToolUse correctness 分支删除或退化为无状态 advisory，不做 admission、身份绑定或消息解析。父 Agent取得原生 `spawn_agent` 响应后，显式调用新的 `--record-spawn-observation`，以 `task_id + attempt + generation` 记录 `success|failed|unknown` 和响应实际提供的 Agent ID/canonical path。
7. 父 Agent记录 spawn observation 是当前 Slice 3 parent-authority 模型在 dispatch plane 的对称应用：父 Agent本来就是 native tool response 和 current child final 的直接接收者。本方案不宣称防御恶意父 Agent，也不把该记录升级为 platform running 或业务结果。
8. `SubagentStart` 继续 unbound advisory；没有新的真实正向证据前，不因其 `agent_id` 与已保存 target 相似或相等而新增 attempt identity authority。后续 runtime observation 仍只使用当前已准入的 exact canonical target `list_agents` adapter。
9. Slice 5 已收口的 TaskResult producer/validator/Schema parity 必须原样保留：`complete != completed`、数组字段类型、场景必填字段、initial/correction/resume 共用 renderer 均不得回退。
10. 新实现只修改本开发仓库。没有用户另行授权时，不得安装、发布、同步稳定源或运行缓存，也不得修改外部对话状态。

当前工作树包含大量用户已有修改和未跟踪设计/测试文件。新对话必须保留它们，不得 reset、checkout、覆盖或把共享工作树假定为 clean。

## 2. 为什么要拆

### 2.1 当前门禁实际提供的能力

当前 managed spawn 使用以下链路：

```text
TaskContract
  -> prepare_dispatch / prepare_spawn_retry / prepare_replacement_dispatch
  -> PreparedContract 文件 + StateStore execution
  -> task_ref
  -> 强制 task_name
  -> PreToolUse 解析 task_name 并消费 PreparedContract
  -> StateStore claim
  -> 原生 spawn_agent
  -> PostToolUse 用 tool_use_id 反查 PreparedContract
  -> 写 spawn observation
```

它能在 Hook 实际运行且调用方遵循生成器协议时，检查：

- `task_name`、`fork_turns`、`model`、`reasoning_effort` 是否与准备结果相同；
- PreparedContract 是否存在、未过期且未消费；
- retry/replacement 的 StateStore 前置事实是否仍成立；
- 同一 PreparedContract 是否只认领一次。

这些是防止调用方自己传错参数的协作校验，不是安全边界。当前 unmanaged spawn 只要不带 `sg_` 前缀即可绕过；Hook 未信任、未加载或内部失败时也不能提供平台级保证。当前门禁还没有比较真实 `message`，因此并未证明业务正文与准备时的 TaskContract 相同。

### 2.2 门禁制造的成本

为维护一个短期凭证和一份长期 StateStore 的一致性，当前实现额外承担：

- 独立目录、文件锁、权限校验、原子替换、写后回读和 CAS；
- PreparedContract 与 StateStore 双写；
- initial 双写失败后的完整 task 快照重建和精确回滚；
- replacement reservation 的预占、摘要、过期回滚和并发保护；
- claim 写后报错时 StateStore 与 PreparedContract 的双向恢复；
- 5 分钟 unclaimed 和 20 分钟 claimed-without-PostToolUse 的两阶段清理；
- task ref 派生、碰撞扩展、全 Session 占用扫描和强制标题解析；
- 大量只验证上述内部机制而不验证用户业务价值的测试和文档。

运行时的主要直接耦合点如下，行号以 2026-08-15 当前工作树为准，实施时必须重新确认：

| 当前符号 | 当前行区间 | 行数 | 处理方向 |
| --- | ---: | ---: | --- |
| `PreparedContractStore` | 2947-3335 | 389 | 删除 |
| `_prepared_record` | 4812-4857 | 46 | 删除 |
| initial/replacement claim 回滚与 cleanup helpers | 5004-5396 | 约 300 | 大部分删除 |
| `prepare_dispatch` | 5399-5536 | 138 | 改为只写 canonical StateStore generation，不再双写 |
| `prepare_replacement_dispatch` | 5539-5730 | 192 | 删除 reservation/PreparedContract 双写，保留单 StateStore CAS |
| `prepare_spawn_retry` | 5733-5866 | 134 | 删除 PreparedContract，改为追加有界 generation |
| `reconcile_prepared_dispatches` | 5869-5980 | 112 | 删除，由 prepared generation 责任视图替代 |
| `_handle_spawn` | 7190-7493 | 304 | 删除 spawn admission 主体；不得改读 opaque message |
| `_handle_post_tool` | 7945-8278 | 334 | 删除其中 spawn 凭证/观察分支；其他 operation 分支保留 |

当前 runtime 已因 Slice 5 增长到约 11,535 行，Schema 为约 1,671 行，Skill 为约 257 行。保守估算：运行时代码毛删除约 1,400-1,700 行；补回 dispatch generation、父任务 observation 记录入口和迁移后，运行时代码净减少约 1,100-1,400 行。测试净减少约 1,000-1,500 行；Schema、Skill 和当前有效文档净减少约 100-250 行。行数不是验收标准，只用于说明复杂度来源。

## 3. 已确认的平台事实

机器边界以 `schemas/codex-hook-events-v1.contract.json` 为准：

| 事件 | 可用的关键字段 | 本方案用途 |
| --- | --- | --- |
| common | `session_id` | 所有 StateStore 和 Hook 关联使用父 Session |
| PreToolUse | `tool_name`、`tool_use_id`、`tool_input` | 对 follow-up/communication/interrupt 继续消费 typed pending action；spawn 不再从这里取得业务身份或 admission authority |
| PostToolUse | 同一个 `tool_use_id`、`tool_input`、`tool_response` | 对已认领 lifecycle action 继续对账；spawn 分支不再尝试从 opaque input 关联 canonical execution |
| SubagentStart | `agent_id`、`agent_type` | 继续 unbound advisory；没有 task name/ref/path，也没有已验收 attempt-binding authority |
| SubagentStop | `agent_id`、可选 transcript/last message | 不作为正式 TaskResult authority，不从自然语言猜测结果 |

必须继续遵守：

- `SubagentStart` 官方字段不包含 task ref、task name、canonical path 或正式结果。
- `SubagentStop` 官方字段不包含 `task_result`。
- transcript/rollout 内部格式不是 Hook correctness 接口。
- spawn `message` 在 generator 到 child 的平台 transport 中可能在 Hook 前变成 opaque；Hook 不得从中解析 TaskContract、task ID、attempt、transition 或 digest。最新真实 smoke 只证明 generator 生成的 native message 能到达 child 且没有被 Hook 改写，不证明 Hook 可读 plaintext message。
- 父 Agent直接收到原生 spawn response 后记录的 Agent ID/canonical path，只证明“父任务观察到这次派发返回了这个 target”，不单独证明 Agent 已经 running 或已完成业务。
- `tool_use_id` 继续是 Hook 内 lifecycle action 的 Pre/Post 关联键，但不再是 managed spawn 的业务身份。spawn observation 使用生成器已持久化的 `task_id + attempt + generation`。

## 4. 目标职责边界

### 4.1 保留的插件核心

本次拆除不能推翻既有四层业务模型：

```text
work_item    一个稳定业务目标
execution    对该目标的一次业务执行边界
outcome      execution 提交的结构化业务结果
disposition  父 Agent 对结果或继续方式的显式处置
```

必须保留：

- 用户在派发前看见目标、治理等级、模型、强度、上下文、范围和完成条件；
- 子 Agent收到足够独立执行的 TaskContract 和终态格式要求；
- StateStore 记录 work item、execution、原生调用观察、target、恢复/纠正计数和父动作；
- success、failed、unknown 分离，原生调用结果不冒充业务结果；
- follow-up、wait、list、interrupt、恢复、business resume 和 replacement 的生命周期语义；
- TaskResult、结果文件、结果冲突、complete 后父验收和显式关闭；
- SessionStart/End、diagnose、group 和 action-required 的恢复责任。

### 4.2 明确删除的保证

本方案有意不再承诺：

- 每次原生 spawn 前都存在一份已持久化凭证；
- Hook 能把调用参数与某个事先保存的副本逐项比较后才允许发送；
- title 中包含不可缺少的内部身份；
- 同一 preparation 只能被调用一次；
- retry/replacement 的 candidate cap 在原生调用前拥有不可绕过的硬阻断；
- Hook/StateStore 故障时可以阻止原生 spawn。

这些能力如果将来再次被要求，必须以新的明确用户价值和真实平台证据重新设计，不能把 PreparedContract 换名后恢复。

### 4.3 新的 fail-open 原则

spawn PreToolUse 不再承担 managed admission，也不返回 deny。治理路径分成以下边界：

| 结果 | 行为 |
| --- | --- |
| preparation 成功 | canonical StateStore 已创建 execution/generation；父 Agent取得 spawn args，正常调用原生工具 |
| preparation 校验、CAS 或存储失败 | 不伪造 managed preparation；生成器明确报错。原生工具本身仍可被直接调用，但该调用按 unmanaged 处理，不声称受治理 |
| native spawn 已调用但 observation 尚未记录 | 已准备 generation 保持 action-required/reconcile；不按时间回滚或推断 failed |
| observation 记录失败 | 原生调用事实不回滚；保留 prepared generation 并告警，由父 Agent重试同一记录或人工对账 |
| 未走生成器的原生 spawn | Hook 原样放行，不创建或污染 managed work item |

这保留了正常 governed workflow 的机械 admission，却删除了 Hook 作为原生调用门禁的角色。插件不能阻止调用方绕开生成器直接使用原生工具，也不得把绕开后的调用包装为已治理。诊断应如实暴露 prepared-but-unobserved generation；时间经过不能自动证明调用未发生。

## 5. 新派发协议

### 5.1 插件不再强制 task_name

原生工具仍要求 `task_name` 时，调用方只需满足原生 `spawn_agent` 自身 schema。插件不增加前缀、后缀、治理等级、attempt、内部 ID、命名风格或唯一性要求，也不把原生 schema 约束复制成第二套插件校验。

生成器为了方便可以把 TaskContract 的 `semantic_name` 作为一个可替换默认值，例如：

```text
verify_hook_contract
review_migration
implement_dispatch_state
```

调用方可以在原生调用前把默认值换成任何原生工具接受的名称；这不会改变已准备 execution、父任务 observation 记录、StateStore 写入或后续结果绑定。Hook 不再：

- 要求 `sg_` 前缀；
- 从名称解析治理等级、attempt 或内部 ID；
- 用相似名称、唯一名称或路径后缀绑定 execution；
- 因名称格式不符合插件约定而拒绝 spawn。

StateStore 可以保存生成器建议的名称为可选展示事实，也可以完全不长期保存。父 Agent实际调用时即使换名，也无需回写。平台返回的 canonical path 是独立观察事实；两者不是同一个字段，也不能互相推导。不得要求 task name 在 Session 内唯一。

### 5.2 单一 StateStore preparation

生成器继续接收并机械校验完整 TaskContract，但不再创建 PreparedContract。一次正常 initial preparation 在唯一 StateStore CAS 中直接创建：

```text
work_item(task_id)
  -> execution(attempt=1)
  -> dispatch_record
  -> generation=0, observation=null, target=null
```

同一事务保存现有设计需要的 TaskContract/deliverable contract、contract digest、目标摘要、治理等级、范围、完成条件和证据要求。生成器随后返回：

```json
{
  "task_id": "sg-...",
  "attempt": 1,
  "generation": 0,
  "contract": {},
  "contract_digest": "...",
  "user_message": "...",
  "dispatch_prompt": "...",
  "spawn_args": {
    "task_name": "<可替换默认值>",
    "message": "<平台处理前的完整任务正文>",
    "fork_turns": "none"
  }
}
```

要求：

- `message` 继续在 generator 阶段写入公开 `task_id + attempt`、完整业务说明和 Slice 5 TaskResult reply contract，使 child 能提交严格结果。
- Hook 不读取、分类、比较或持久化 `message`；opaque transport 不影响 managed identity。
- 调用方可以替换 `spawn_args.task_name`，但不能把 generation 用于另一个 TaskContract/task/attempt。
- preparation 成功是 governed workflow 的开始，不是原生调用已经发生。prepared generation 必须进入 Session/action-required 视图，直到父 Agent记录 observation 或显式取消。
- 不设置五分钟自动过期。只有父 Agent能可靠确认原生 spawn 从未调用时，才可通过显式 `--cancel-prepared-spawn` 取消 generation；取消本身必须记录有界原因并经过 StateStore CAS。

### 5.3 父任务记录 spawn observation

父 Agent直接收到原生 `spawn_agent` response，因而在调用后立即执行 stdin-only：

```bash
python3 scripts/subagent_governance.py --record-spawn-observation --session <session_id>
```

输入固定为：

```json
{
  "task_id": "sg-...",
  "attempt": 1,
  "generation": 0,
  "call_observation": "success",
  "agent_id": null,
  "canonical_path": "/root/<exact-native-target>"
}
```

字段与组合规则：

| 字段 | 规则 |
| --- | --- |
| `task_id + attempt + generation` | 必须精确匹配一个 prepared、尚未观察的 dispatch generation |
| `call_observation` | 只允许 `success | failed | unknown`；描述原生调用，不是业务结果 |
| `agent_id` | 只保存原生 response 实际提供的非空 ID；未提供为 null |
| `canonical_path` | 只保存原生 response 实际提供的 absolute canonical target；未提供为 null |

组合约束：

- `success` 可以有 target，也可能没有；没有 target 时保持 `parent_action=reconcile`。
- 可靠 `failed` 不得携带 target；若 response 同时出现失败和正向 target，父 Agent必须记录 `unknown`，不能丢弃正向事实。
- `unknown` 可携带 response 中实际观察到的 target，但 target possession 不把 observation 改成 success。
- 入口不接受自由文本错误分类、不读取 transcript/summary/history、不修复枚举。
- 同一 generation 的相同 observation/target 重放幂等；不同 observation 或不同 target 不覆盖首份事实，进入 conflict/reconcile。
- StateStore 写入或回读失败不回滚已发生的原生调用；父 Agent可以用同一输入安全重试。

该入口与现有 `--record-child-result` 使用同一父任务权威边界：父 Agent是 native response 的直接接收者，插件执行严格机械校验和持久化，但不宣称密码学防御父 Agent。

### 5.4 显式取消未调用的 generation

`--cancel-prepared-spawn` 不是超时清理器，只供父 Agent在能够确认原生 `spawn_agent` 从未调用时撤销本次 preparation：

```bash
python3 scripts/subagent_governance.py --cancel-prepared-spawn --session <session_id>
```

stdin 固定提供：

```json
{
  "task_id": "sg-...",
  "attempt": 1,
  "generation": 0,
  "cancel_reason": "parent did not invoke native spawn_agent"
}
```

- 调用该入口本身就是父任务对“原生调用未发生”的明确权威声明；`cancel_reason` 必须是有界非空文本，但插件不从文本关键词判断证明是否充分。
- 只允许 exact generation 仍为 observation=null、target=null、未 canceled，且没有与该 generation 冲突的并发状态时执行 CAS。
- 相同取消输入重放幂等；不同原因、已 observed、已有 target、identity 不匹配或 stale state 均不覆盖已有事实。
- canceled generation 保留为不可变终态并占用该 generation 槽位；不删除 task/execution、不复用 generation 编号，也不回拨既有 growth authorization 或历史计数。initial/retry 在仍有 generation 容量时可进入 `retry_spawn`，容量耗尽时进入 `decide_disposition`；canceled replacement execution 可靠标记 inactive/closed，不再占 live duplicate candidate，但来源 execution 和已记录增长事实不回滚。
- 不确定是否调用、调用返回丢失、PostToolUse 缺失、时间经过或 Hook 未运行，都不满足取消条件，只能保留 observation=null/reconcile。

### 5.5 为什么需要显式记录

当前原生工具没有插件 metadata 参数，而用户已明确不允许插件强制 `task_name`；真实 fixture 又证明 Hook 层的 `message` 可能 opaque。因此 Hook 没有第三个稳定字段可以把某个 prepared TaskContract 与某次 spawn 自动关联。

在这些约束下只有三种选择：重新强制标题、猜测 opaque message/调用顺序，或由同时知道 preparation ID 和 native response 的父 Agent显式关联。本文选择第三种。额外一次本地记录调用是删除 PreparedContract 门禁和标题编码后的明确交互成本；它不能被隐藏为“PostToolUse 自动完成”。

## 6. 新事件流程

### 6.1 initial spawn

```text
父 Agent填写 TaskContract
  -> prepare_dispatch 校验并在 StateStore 创建 task/A1/generation 0
  -> 返回 task_id/attempt/generation/user_message/spawn_args
  -> 父 Agent先展示 user_message
  -> 调用原生 spawn_agent
  -> spawn PreToolUse/PostToolUse 不解析标题或正文、不做 managed mutation
  -> 父 Agent读取原生 response
  -> --record-spawn-observation(task_id, attempt, generation, call_observation, target)
  -> 后续 list/status/message/result/disposition 均从 StateStore 继续
```

`prepare_dispatch` 仍需要 `session_id`，因为它直接创建唯一 canonical StateStore execution；它不再创建第二份 PreparedContract。生成器输出中的默认 task name 不是契约字段，调用方可以替换，Hook 和 observation recorder 都不得比较 expected/actual task name。

### 6.2 PreToolUse spawn

spawn PreToolUse 不再有 managed correctness 职责。实现可以直接不处理 spawn kind，或只返回不含 mutation/authority 的有界 advisory；不得：

- 解析 `task_name`、opaque `message` 或正文中的 task ID；
- 查找、消费或重建 preparation；
- 比较 model、reasoning effort、fork turns 或 task name；
- 写 execution、generation、target、result 或 identity；
- 通过 `updatedInput` 改写 task name、message、model、reasoning effort 或 fork turns；
- 因任何治理状态返回 deny。

communication、followup、interrupt 等已有 typed pending action 的 PreToolUse admission 不在本次删除范围内，继续按当前 exact target、owner、预算和 CAS 规则执行。

### 6.3 PostToolUse spawn

spawn PostToolUse 同样不承担 managed mutation。它无法从任意 task name 或 opaque message 知道应更新哪个 prepared generation，也不得按唯一候选、调用顺序、最近 preparation 或相似名称猜测。

原 `_handle_post_tool` 中 communication/followup/interrupt/list-agents 分支继续保留。spawn-specific PreparedContract lookup、`find_claimed(tool_use_id)`、response 写入和凭证收缩全部删除，实际 response 由父 Agent按第 5.3 节显式记录。

### 6.4 PostToolUse 缺失

PostToolUse 是否存在不再影响 managed spawn correctness。真正需要对账的是“prepared generation 尚未收到父任务 observation”：

- observation 为 null，execution 不生成 failed、success 或 running；
- `parent_action=reconcile`，SessionStart/End 保留责任；
- 不按五分钟、二十分钟或其他纯时间阈值回滚 TaskContract/generation；
- 父 Agent若保留了同一次原生 response 和 exact preparation identity，可以用完全相同输入重试 `--record-spawn-observation`；current child notification、`list_agents`、同名 target 或唯一候选都不能反推某个 generation 的 native call observation；
- 只有能证明原生调用从未发生时，才允许显式取消 prepared generation。

删除 `reconcile_prepared_dispatches`；不需要用新的时间型 `reconcile_dispatch_calls` 换名恢复同一复杂度。现有 decision snapshot/SessionStart 直接把 observation=null 的 prepared generation 投影为待记录/待对账责任。

### 6.5 SubagentStart/Stop

- 删除基于 task name/task ref/transcript 的 Start route 和迟到 ref 绑定。
- SubagentStart 无条件保持当前 unbound advisory，不因 `agent_id` 等于父任务已记录值而新增 execution mutation；真实 Start/Stop attempt authority 仍为 `not_checked`。
- SubagentStop 继续不消费自然语言结果，不用 Stop 自动补 business result。
- 正式结果仍由父 Agent基于 exact sender target + task_id + attempt 记录。

## 7. 目标 StateStore 模型

### 7.1 删除的字段和对象

稳态 canonical 模型删除：

- `task_ref` definition 及 execution/dispatch/tombstone/pending/resume 中的所有引用；
- `task_name` 作为 required identity；`origin_task_name` 删除，只在确有展示价值时把原生实际输入保存为可选 `requested_task_name`；
- `replacement_reservation`、`reservation_id`、`reservation_snapshot_sha256`；
- PreparedContract 的 `consumed/tool_use_id/claimed_at/post_observed_at/created_at` 状态，以及 spawn correctness 中的 `tool_use_id` claim；
- `resume_task_ref`；
- task-ref collision、occupied refs 和强制 task-name machine semantics。

`task_id + attempt` 继续是业务 execution 身份；`generation` 是同一 execution 内有界的原生 spawn 次数；Agent ID/canonical path 是平台 target 身份。三者不要再合成第四个 `task_ref`。`tool_use_id` 只保留给 Hook 可精确认领的 lifecycle pending action，不进入新的 spawn identity。

### 7.2 DispatchRecord 建议形状

同一 execution 最多有首次 preparation 加两次 spawn retry，因此 generation 集合是有界事实，不是无限事件日志：

```json
{
  "task_id": "sg-...",
  "attempt": 1,
  "dispatch_kind": "initial_spawn",
  "contract_digest": "...",
  "generations": [
    {
      "generation": 0,
      "prepared_at": 0,
      "observed_at": null,
      "observation": null,
      "agent_id": null,
      "canonical_path": null,
      "canceled_at": null,
      "cancel_reason": null
    }
  ],
  "dispatch_target": null
}
```

规则：

- `generations` 最大 3 项：initial generation 0，加两个 retry generation；replacement 是新 execution，不追加到旧 execution。
- 新格式 preparation 从 generation 0 开始并在 StateStore CAS 中连续追加，编号只增不复用；父任务 observation 只能消费 exact `task_id + attempt + generation`。
- 从旧 aggregate state 迁移时允许只保留一个编号为旧 `spawn_retry_count` 的稀疏 generation，因为旧格式没有逐次历史；缺失的更低编号不是 prepared/unobserved call，不进入 action-required。迁移后继续从最高已占用编号加一，仍不得超过 2。
- generation 的 observation 初始为 null，只能一次性写 `success|failed|unknown`，或在证明未调用时显式写 canceled；不能同时 observed 和 canceled。
- 同一 generation 的完全相同 observation/target 重放幂等；不同 observation 或 target 属于 conflict，保留首份权威事实并进入 reconcile，不能静默覆盖。
- 第一份可靠 success target 写入 `dispatch_target`。后续 generation 出现不同正向 target 时保留全部 generation 事实，标记 duplicate/conflict 并要求父 Agent处置。
- `dispatch_target` 可以是结构化 `{agent_id, canonical_path}`，允许其中一个为空；不要把 canonical path 塞进 agent ID 字段。
- `spawn_retry_count` 从最高已占用 generation 编号派生；不得再保存一个可独立漂移的权威计数。compatibility projection 如暂时保留，只能单向派生，不能用数组长度推断稀疏迁移记录。
- `requested_task_name` 不进入 canonical controlled fields。若诊断确有展示需要，只能作为可选 display extension，不能影响任何校验或绑定。

### 7.3 其余四平面保持分离

- DispatchRecord 只记录原生调用及返回 target。
- ObservationRecord 只记录 exact target 的 active/terminal/error/unknown 平台观察。
- ResultRecord 只记录正式结果、存储、冲突和 sender provenance。
- ClosureRecord 只记录父动作、处置和关闭。

父任务记录的 spawn success 不写 ObservationRecord active；SubagentStart 继续不写 managed observation。正式 TaskResult 不反向制造 platform terminal。

## 8. retry、replacement 和 business resume

### 8.1 same-attempt spawn retry

`prepare_spawn_retry` 保留，因为最后一次 retry 授权、可靠 failed/显式 canceled 前置条件和原契约复用仍有产品价值。它改为单 StateStore CAS：

1. 读取当前 canonical execution；
2. 要求最近 generation 为可靠 failed 或父任务显式 canceled，且没有 target/正向执行证据；
3. 检查 generation/预算和最后一次用户授权；
4. 在同一锁内追加下一 generation 并使其 observation=null；该 generation 是 retry 预算的唯一权威；
5. 使用同一 task ID、attempt、TaskContract，返回新的原生调用参数和 exact generation；
6. 不写 PreparedContract、不依赖 task name、不等待 PreToolUse claim。

父 Agent调用原生 spawn 后，用 exact generation 记录 response。可靠 failed 或显式 canceled 才产生下一次 retry 资格；unknown 禁止新 generation。canceled generation 不复用、不退款并计入最多三个 generation 槽位；无法证明未调用时只能保留 null/reconcile。

retry 预算仍是 governed workflow 的机械硬规则，但 enforcement 位于显式 preparation，而不是 Hook。直接绕开生成器的原生 spawn 不会被插件误认成合法 retry。

### 8.2 replacement spawn

`prepare_replacement_dispatch` 同样改为单 StateStore CAS：

- 读取来源 work item/execution；
- 机械检查 lifecycle、duplicate risk、candidate 数量、transition 和 growth authorization；
- 在同一锁内创建 `attempt=N+1` canonical execution 和 generation 0，直接保存新 TaskContract/transition/growth facts；
- 返回同一 task ID、新 attempt/generation 和原生调用参数；`task_name` 由调用方按原生工具要求提供，插件不依赖其格式；
- 不创建独立 replacement reservation，不提前推进 `current_attempt`，不写 PreparedContract。

prepared replacement execution 本身占用一个 candidate，并持续 action-required，直到父 Agent记录 response。可靠 failed/canceled 可以机械关闭该未启动 execution；success/unknown 按现有 duplicate-risk 语义保留。StateStore CAS 失败时不返回 governed replacement 参数，不能把后续手工原生 spawn 错误附着到该 work item。

candidate cap 仍由 preparation CAS 对所有 governed replacement 强制执行，但它不宣称拦截直接绕过插件的 unmanaged spawn。删除的是原生 Hook 门禁和第二份凭证，不是 work item 内部增长规则。

### 8.3 business resume

same-Agent business resume 继续使用现有 StateStore `pending_action` + exact confirmed target + `followup_task`，不经过 spawn PreparedContract，也不受本次 task-name/task-ref 删除影响。

需要改写的只是：

- pending action 用 `task_id + new_attempt + target` 关联，不再携带 `resume_task_ref`；
- 新 attempt 的 identity 来自 work item、attempt 和 exact target；
- 删除 task name/ref 后不为 business resume 新增 Start authority；Start 继续 unbound，resume 的调用 observation 仍由现有 pending action/父任务显式事实和已准入 exact target 平台观察处理。

通信、recovery、correction 和 interrupt 的两阶段 pending action 不是本次要删除的 PreparedContract，不应顺手删除。

## 9. TaskContract 和正式结果

### 9.1 TaskContract 不降级

删除门禁不等于删除结构化派发。必须继续：

- 校验治理等级、auto features、上下文策略、model/effort、范围、禁止范围、完成条件和证据要求；
- 先向用户展示 `user_message`；
- 把完整目标和终态义务交给子 Agent；
- 确定性生成 deliverable contract 和 digest；
- 在 managed execution 创建时把必要契约数据写入 StateStore。

完整 TaskContract 在 preparation CAS 中直接进入 canonical execution，不依赖 Hook 或 PostToolUse fallback 重建。StateStore 只保存现有设计要求的 contract/deliverable 和摘要，不额外保存重复渲染正文；给 child 的完整 message 仍由同一 contract 在平台处理前生成。

### 9.2 TaskResult 保持 task_id + attempt

生成器仍在公开 prompt 中告诉子 Agent `task_id + attempt`，因此当前 `task-result-v1.schema.json` 不需要因为删除 task ref 而改变核心身份。父 Agent结果记录入口继续要求：

```text
sender_target + task_id + attempt + task_result
```

其中 sender target 必须精确匹配该 execution 由父任务 `--record-spawn-observation` 保存的 dispatch target。不得按 task name、当前 attempt、唯一候选或最近消息猜测 sender。

### 9.3 Slice 5 producer clarity 不变量

D7 实施发生在 Slice 5 真实 smoke 和最终综合验收之后，重写 generator、TaskContract renderer 或结果测试时必须保留：

- `business_result` 只允许 `complete | blocked | failed | needs_decision`；平台 terminal `completed` 永远不归一化为业务 `complete`；
- `_task_result_reply_contract()` 继续同时服务 initial dispatch、`result_correction` 和 `business_resume`，不能复制出三套字段说明；
- 字段 JSON 类型由同一 canonical helper/Schema 来源渲染，`evidence`、`remaining`、`attempted`、`options` 等保持数组类型；
- producer 指令包含合法最小 complete 示例和各场景额外必填字段；
- validator 对非法枚举和类型严格拒绝，不修 JSON、不接受 alias、不从 summary/transcript/history/Hook/observation 生成结果；
- producer、validator、`task-result-v1.schema.json`、machine semantics 的字段/类型/枚举 parity 测试继续通过。

## 10. 兼容和迁移策略

### 10.1 开发实现边界

本方案首先只要求开发仓库的新状态和隔离测试通过，不授权直接处理真实安装目录中的历史 `prepared/` 文件。实现对话不得为了测试方便修改：

- `~/plugins/subagent-governance`；
- `~/.codex/plugins/cache/personal/subagent-governance`；
- Marketplace、Registry、Hook trust；
- 真实 Session StateStore 或历史对话。

### 10.2 State format

当前 canonical state format 以实施时 Schema 实际值为准；2026-08-15 工作树中为 format 4。删除字段属于持久结构变化，应 bump 到下一格式，并提供确定性迁移测试：

| 旧事实 | 新映射 |
| --- | --- |
| `task_id + attempt + task_ref` | 丢弃派生 `task_ref`，保留 `task_id + attempt` |
| `task_name` | 默认丢弃；只有诊断确有展示需要时迁为不参与校验的可选 display extension |
| 旧 `spawn_retry_count + dispatch_record` | 只创建一个编号为旧 count 的稀疏 generation；`acknowledged|rejected|indeterminate` 分别保守映射为 `success|failed|unknown`，`prepared|claimed` 映射为 observation=null；不得伪造更低编号历史 generation |
| consumed PreparedContract 的 `tool_use_id` | 不进入新 spawn identity，也不单独证明 observation；只用同一 canonical StateStore 已有 dispatch state/target 补齐该 generation |
| `spawn_observed_agent_id/canonical_path` | 迁入对应 generation target 和 execution dispatch target |
| unconsumed PreparedContract + 精确 canonical execution | 按凭证中的目标 retry count 映射为 observation=null 的 prepared generation；若同编号已有 canonical 强事实则报告冲突而不覆盖，不提升为已发生调用，也不按时间删除 |
| orphan unconsumed PreparedContract | 不创建 task；诊断为 abandoned legacy preparation，留给显式迁移/清理裁决 |
| `replacement_reservation` 且无 tool-use ID | 其 canonical reserved execution 映射为 prepared replacement generation；不能静默生成 success、target 或 Agent事实 |
| pending/resume `task_ref` | 删除，使用已有 task ID、attempt、exact target 和 operation tool_use ID |
| tombstone `task_ref` | 删除，保留 task ID、attempt、target、close reason/time |

不要为了长期兼容把完整 PreparedContractStore 留在新 runtime。可选迁移方式应在发布前单独裁决：

1. 一个只读/显式执行的一次性 migration 命令；或
2. 仅在旧 StateStore 首次写入时读取必要 legacy prepared record，转换后不再写旧格式。

无论选哪种，迁移不得自动删除用户真实 legacy 文件。先写新状态并回读验证，再报告哪些旧文件可由用户授权清理。开发实现和稳定发布是两个不同授权阶段。format 4 到新格式的迁移必须保留 Slice 5 结果、结果冲突、acceptance、closure 和 exact observation 原始事实；不得因删除 dispatch gate 重算或提升这些平面。

### 10.3 文档历史

当前有效 README、Skill、runtime boundaries、governance-levels、平台最小状态机、`docs/redesign/README.md` 和项目功能盘点必须更新。历史 redesign/review 文档不应大规模改写；在直接宣称旧门禁仍是当前方案的文档顶部标记 superseded，并引用本文，保留历史证据。最终综合验收报告保留为 D7 之前的基线证据，并在顶部说明其 GO 不覆盖 D7 新实现，不能改写历史测试数字。

## 11. 代码删除与改写清单

### 11.1 完整删除

- `PreparedContractError`、`PreparedContractValidationError`、`PreparedContractConflictError`、`PreparedContractWriteError`。
- `PreparedContractStore` 和 `_prepared_root_for_store`。
- `_prepared_record`。
- `_initial_task_post_state`、initial preparation rollback health、exact dual-write cleanup。
- `_cleanup_unclaimed_prepared_dispatch`、`reconcile_prepared_dispatches`。
- PreparedContract claim/unclaim、delete-if、expiry、orphan 和 post shrink 分支。
- `derive_task_ref`、`select_task_ref`、`parse_task_name`、task-ref occupied/collision helpers。
- replacement reservation ID/digest/match/rollback machinery。
- `TASK_REF_LENGTHS`、强制 task-name regex semantics 和对应 Schema definitions。
- 只服务于 task-ref/transcript Start routing 且已经无真实 correctness authority 的 dead helpers。
- `prepared/` 作为新数据根目录及 README/diagnose 中的当前目录声明。

### 11.2 改写而不是删除

- `build_task_name`：从治理 correctness 路径删除。生成器如需便利默认值，直接使用 `semantic_name` 或一个不参与校验的独立展示 helper；不得建立插件命名规则。
- `prepare_dispatch`：保留 TaskContract 校验、user message、prompt/native args；在唯一 StateStore CAS 中直接创建 initial execution/generation，删除 PreparedContract 双写。
- `prepare_spawn_retry`：保留 admission 和授权检查；在同一 StateStore CAS 中追加 generation 并返回 exact generation/native args，删除凭证写入和 PreTool claim。
- `prepare_replacement_dispatch`：保留 growth/risk/candidate 检查；在同一 StateStore CAS 中创建 replacement execution/generation，删除独立 reservation 和双写。
- `_handle_spawn`：删除 managed spawn admission 主体。PreToolUse 不解析标题/message、不写 StateStore、不 deny。
- `_handle_post_tool` spawn 分支：删除 PreparedContract/tool-use lookup 和 managed mutation；其他 lifecycle/list operation 分支原样保留。
- 新增 stdin-only `record_spawn_observation` / `--record-spawn-observation`，严格消费 `task_id + attempt + generation + call_observation + agent_id/canonical_path`。
- 新增显式 `cancel_prepared_spawn` / `--cancel-prepared-spawn`，只在父 Agent能证明原生调用从未发生且 generation 仍精确未观察时取消。
- DispatchRecord、canonical validation、migration、compatibility projection、diagnostics。
- SessionStart/End：直接展示 prepared-but-unobserved generation 责任，不再运行 PreparedContract TTL reconcile，也不增加换名时间清理器。
- result sender mapping 和 Agent index：改为父任务记录的 exact dispatch target，不再依赖 ref/name/PostTool 自动关联。

### 11.3 必须保留

- StateStore 的锁、原子写、CAS 和写后回读。这是唯一长期状态，不是门禁冗余。
- TaskContract validation/rendering、deliverable contract 和 digest。
- native response 的有限三值/target 组合校验；不得从自由文本猜测。
- 四平面、work item/execution/result/disposition。
- communication/recovery/correction/interrupt pending action。
- retry/recovery/correction 的独立有限计数；只有 spawn retry 的消费载体改成 dispatch call generation。
- duplicate/select/close/tombstone/result conflict 等业务收口规则。
- diagnose、group、Session 恢复和正式结果父权威通道。
- Slice 5 的 `_task_result_reply_contract()`、字段类型 renderer、`complete != completed` validator 和 Schema parity。

## 12. 测试迁移

### 12.1 先新增的失败测试

实现删除前先用隔离临时目录新增或改写以下测试：

1. 多个不同且原生合法的 `task_name`（包括不含 `sg_`、不含 semantic name、与其他 execution 重名）都能生成和管理，且调用方替换生成器默认值不影响 preparation/observation/result。
2. initial preparation 只创建一个 canonical StateStore execution/generation，不创建 `prepared/` 或第二份凭证。
3. preparation 返回 exact `task_id + attempt + generation`，完整 child message 仍含公开 task/attempt 和 Slice 5 reply contract。
4. opaque `tool_input.message`、相同/相似/修改后的 task name 均不影响 spawn Hook；PreToolUse/PostToolUse 不产生 managed mutation。
5. spawn PreToolUse 在 PreparedContract 缺失、StateStore 不可用、参数变化或 malformed opaque input 时都不 deny、不返回 `updatedInput`。
6. 父任务 `record_spawn_observation` 对 success/failed/unknown 和 Agent ID/path 四种 target 组合执行严格正负矩阵。
7. exact `task_id + attempt + generation` 的同 observation/target 重放幂等；错 task、attempt、generation 和冲突 target 不覆盖首份事实。
8. reliable failed + target 组合被拒绝或要求 unknown；已有正向 target/observation 不被迟到 failure 覆盖。
9. prepared generation 未记录 observation 时保持 null/reconcile，不因 PostToolUse 缺失或时间经过自动变 unknown/failed/删除。
10. `cancel-prepared-spawn` 只有在 exact unobserved generation 且父 Agent明确证明未调用时成功；observed、target 已存在、并发变化均拒绝且 no-op。
11. parallel initial preparation 使用不同 task ID，StateStore CAS 不依赖 ref collision 或 task-name uniqueness。
12. retry preparation 在同一 CAS 追加有界 generation；最终授权、unknown 禁止 retry、取消占用槽位但可按剩余额度进入下一 generation、迟到旧 observation 均有回归。
13. replacement preparation 创建新 attempt/generation；candidate cap、duplicate risk、并发 stale、可靠 failed/canceled 和旧/new target 并存均保持既有业务语义。
14. 直接绕过生成器的原生 spawn 按 unmanaged 放行，不错误附着到唯一/最近/同名 managed work item。
15. parent result 仍以父任务记录的 exact sender target + task ID + attempt 成功记录，错 sender 拒绝。
16. SubagentStart/Stop 无论 agent ID、transcript 或扩展字段如何都不新增 managed identity/result mutation。
17. exact canonical target `list_agents` observation adapter、`fresh_until=null` 和 parent Stop advisory-only 不回退。
18. Slice 5 `complete != completed`、字段 JSON 类型、数组字段、最小 complete 示例和 producer/validator/Schema parity 全部保留。
19. 新 state format migration 删除 task ref 权威，允许旧 aggregate dispatch 只投影最高编号的稀疏 generation，不伪造历史责任，并保持 observation/result/closure、正式结果和 acceptance 原始事实。
20. 新 runtime 不创建 `prepared/` 目录，也不从 spawn `message` 解析 managed identity、generation 或 observation。

### 12.2 可删除的旧测试类别

可删除而不是机械改名的测试：

- PreparedContract 文件权限、原子性、回读、CAS、单次消费和 secret/credential absence；
- initial PreparedContract/StateStore 双写失败的完整回滚矩阵；
- orphan PreparedContract 和五分钟精确删除；
- claim 后异常恢复 PreparedContract；
- task ref 长度扩展、碰撞和强制 task-name 格式；
- 缺 PreparedContract、过期 PreparedContract、参数不一致时 PreToolUse deny；
- unbound Start 不删除 PreparedContract；
- SessionStart/End PreparedContract expiry。

`tests/test_dispatch_identity.py` 当前约 2,853 行，其中约 1,300-1,500 行属于上述门禁内部机制。replacement/retry/unknown/target/result mapping 测试不能整文件删除；原 PostTool target mapping 应改写为父任务 exact generation observation 测试。

### 12.3 不得弱化的回归

- native success/failed/unknown 不等于 business complete/failed；
- exact canonical target 的顶层 `list_agents` observation，以及 broad/alias/wrong/multi-target/nested/malformed wrapper 的负向边界；
- result replay/conflict/storage/acceptance；
- wrong sender/task/attempt 不写结果；
- unknown 不自动 retry、close 或覆盖正向事实；
- duplicate candidate 只有显式 select/disposition 收口；
- SessionEnd 不删除 action-required work item；
- Hook 内部失败对 native lifecycle fail-open；
- SubagentStart/Stop 不建立 attempt identity 或正式结果 authority，不读取 transcript、summary 或未知扩展生成强事实；
- `fresh_until` 固定为 JSON `null`，parent Stop 始终 advisory-only；
- `business_result="complete"` 与平台状态 `completed` 严格分离，不做 alias normalization；
- initial/correction/resume 共用 `_task_result_reply_contract()`，`evidence`、`remaining`、`attempted`、`options` 等字段保持 Schema 规定的 JSON 数组类型；
- producer、validator、TaskResult Schema 和 machine semantics 保持双向 parity；
- format 2/3/4 损坏或未知版本继续拒绝且不重写，不借 D7 migration 补造 observation、result 或 closure。

## 13. 推荐实施切片

每个切片先写失败测试，再做最小实现；不要把发布、安装或真实 smoke 混入代码实施。

### R1：冻结 generation 和父任务 observation 语义

- 在 governance Schema 中定义无 task-ref 的 DispatchRecord/DispatchGeneration 目标形状，以及 stdin-only `record_spawn_observation` 和 `cancel_prepared_spawn` 输入形状。
- 固定 `task_id + attempt + generation` 精确关联、三值 observation、target 组合、完全相同重放幂等、冲突保留首份事实、取消互斥、最大 generation 编号和 legacy sparse projection。
- 为 task-name 无关性、opaque/modified message 无关性、Schema/runtime 双向 parity 和 TaskContract/deliverable/Slice 5 renderer 不变量写失败测试。
- 暂不删除旧 runtime 路径，先让新旧结构边界在测试中可区分。

退出条件：generation 与两个父权威 CLI 的字段、组合和 CAS 语义无歧义；测试不依赖 Hook 可读 message、tool-use ID 或自定义 task name。

### R2：实现单 StateStore preparation 和父任务记录入口

- `prepare_dispatch` 在唯一 StateStore CAS 中直接创建 initial execution/generation，并返回 exact identity 与原生参数。
- 实现 stdin-only `--record-spawn-observation`：严格记录父任务直接观察到的 native response，不读取 message、title、transcript 或历史输出。
- 实现 stdin-only `--cancel-prepared-spawn`：只对 exact unobserved generation 接受父任务“原生调用从未发生”的明确声明和有界原因，并以 CAS 取消；插件不假装能独立证明该外部事实。
- 将 prepared-but-unobserved generation 纳入 decision snapshot、diagnose、SessionStart/End 的 action-required 视图，不增加时间型自动回滚。
- 删除 spawn PreToolUse/PostToolUse 的 managed mutation、deny、input rewrite 和关联逻辑；其他 lifecycle pending action/list-agents 分支保持不变。

退出条件：initial spawn 不需要 PreparedContract、task-ref title、Hook message 解析或 spawn PostToolUse 即可通过显式父任务记录完成本地 dispatch observation 闭环；缺少父任务记录时只保持 observation=null/reconcile。

### R3：迁移 retry/replacement/resume

- retry preparation 在同一 StateStore CAS 中追加有界 generation，以 generation 数和现有授权事实消费预算；unknown 不创建下一 generation。
- replacement preparation 在同一 CAS 中创建新 execution/generation，并保留 candidate cap、duplicate-risk、growth authorization 和 stale-write 检查；不再创建 reservation 文件或等待 PreTool claim。
- business resume pending action 删除 `resume_task_ref`，保留 `task_id + attempt + exact target` 和既有 typed operation 认领/对账。
- 迟到的旧 generation 父任务 observation 只能更新其 exact generation；不得覆盖新 generation target，若形成多个正向 target 则进入 duplicate/conflict 处置。

退出条件：success/failed/unknown、显式取消、迟到父 observation、并发 stale、generation 上限、duplicate/select 全部有新模型回归。

### R4：删除旧门禁和 task-ref 代码

- 删除 PreparedContractStore、双写 rollback、expiry/reconcile、reservation 和 ref/name helpers。
- 删除旧测试类别和 fixtures。
- Schema format bump、migration、compatibility projection 收口。

退出条件：活跃 runtime/Schema/Skill/tests 不再引用 PreparedContract、`prepared/`、`task_ref` 或 `_t_<ref>` correctness。

### R5：文档、诊断和发布前准备

- 更新 README、Skill、runtime boundaries、governance levels、project inventory、optimization plan。
- 历史文档标记 superseded，不伪造历史。
- 更新 diagnose 边界和 state format 报告。
- 只执行 development preflight，不在实现对话中安装、发布或创建真实 Agent。
- 明确标记 Slice 1-5 最终 GO 和旧关键资产哈希只属于 D7 前基线；列出新的独立本地验收和真实 smoke 准入条件。

退出条件：所有当前用户说明和机器语义只描述新链路；历史材料不会被误认为当前保证；实现结论只声明“开发仓库本地门禁通过”，不提前声明 D7 已完成真实验收。

## 14. 验收标准

### 14.1 行为验收

- managed initial spawn 不需要 PreparedContract 文件或任何插件规定的 task-name 格式。
- spawn PreToolUse/PostToolUse 不读取或解析 task name/message，不创建、认领、补建或修改 managed execution/generation/target/observation，也不会 deny 或 rewrite 原生调用。
- 父任务只能用 exact `task_id + attempt + generation` 记录 native spawn response；同事实重放幂等，错 identity 或冲突 observation/target 不覆盖首份事实。
- `success|failed|unknown` 与 target 的组合严格校验；spawn success 和 returned target 均不自动写 platform running 或业务结果。
- StateStore 是唯一长期治理状态；新运行不创建 `prepared/`。
- 缺少父任务 spawn observation 时保持 null/reconcile，不因 missing PostToolUse 或时间经过自动变为 unknown/failed/canceled。
- 只有父任务明确确认原生调用从未发生时才能取消 exact unobserved generation；插件不能从 Hook 缺失或超时自行推断。
- retry/replacement 的 generation/candidate/duplicate 规则在正常 managed preparation 路径机械执行，并在用户说明、Skill 和诊断中如实说明其不拦截 unmanaged spawn。
- SubagentStart 保持完全 unbound/advisory，即使其 Agent ID 与父任务记录的 target 相同也不产生新的 attempt authority。
- 后续平台观察仍只接受已准入 exact canonical target 的现有顶层 `list_agents` adapter；不增加 name、Start、message 或唯一候选旁路。
- TaskContract、用户派发透明度、正式结果和父验收保持可用。
- Slice 5 的 `complete != completed`、严格 JSON 字段类型、数组字段、共用 initial/correction/resume renderer 和 producer/validator/Schema parity 全部保持。
- communication、wait、recovery、interrupt、business resume、duplicate/select 和 Session 恢复没有行为回退。

### 14.2 静态验收

对活跃实现文件执行定向扫描；历史 superseded 文档和本文可以保留术语：

```text
scripts/subagent_governance.py
schemas/governance-semantics.schema.json
skills/subagent-governance/SKILL.md
skills/subagent-governance/references/*.md
README.md
tests/*.py
```

目标：

- 无 `PreparedContractStore`、`PreparedContract*Error`、`reconcile_prepared_dispatches`；
- 无新写入 `prepared/`；
- 无 task-ref task-name parser/collision machinery；
- 无 `ManagedDispatchEnvelope`、spawn message framing/parser 或通过 message/title/tool-use ID 自动关联 generation 的替代实现；
- `_handle_spawn` 的 managed spawn 路径不调用 deny、`updatedInput` 或 StateStore mutation；
- PostToolUse spawn 不访问独立 prepared store，也不写 managed dispatch/identity/observation；
- `--record-spawn-observation`、`--cancel-prepared-spawn`、DispatchGeneration 和 governance Schema/runtime 双向一致；
- task ID/attempt/generation/result/target consumers 均有新路径测试。

### 14.3 必跑验证

按照根 `AGENTS.md`，至少运行：

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
```

还必须运行：

- Plugin validator；
- Skill validator（Skill 必然会修改）；
- repository development preflight；
- 所有 JSON parse/Schema fixture validation；
- `git diff --check`；
- 与 dispatch、canonical schema、communication lifecycle、formal result、wait/session closure 相关的 focused suites。

没有实际命令输出证据不得宣称完成。开发仓库验证通过不等于安装、真实平台或稳定发布通过。

### 14.4 D7 后重新验收

D7 会改变 runtime、governance Schema、Skill、测试和关键资产哈希，因此 `platform-capability-final-acceptance-report.md` 的 GO 只能作为拆除前基线，不能直接覆盖新实现。完成 R1-R5 后至少还需要：

1. 在独立新对话中复核 D7 行为、迁移、删除范围、跨 Slice 反例和全部本地门禁，不复用实现对话自行验收；
2. 用户另行授权后，按项目“外部问题修复与真实测试”流程从开发仓库更新测试用本地插件；
3. 再新建真实测试对话，默认使用 `gpt-5.6-terra/high`，验证 generator message 到 child、父任务 exact generation observation、exact sender TaskResult、record/read/accept/tombstone，以及 spawn Hook 不依赖明文 message；
4. 真实报告只把实际观察项标为 passed，Start/Stop identity、running、Stop UI、restart/compact、Hook trust 等未覆盖项继续标为 `not_checked`；
5. 新关键资产哈希、本地独立验收和真实 smoke 都对齐后，才能形成 D7 后的新综合验收结论。稳定发布仍需单独授权和 release gate。

## 15. 已知风险和不可同时满足的要求

| 要求组合 | 结论 |
| --- | --- |
| PreToolUse 永不阻断 + candidate cap 不可绕过 | 无法同时保证；本文选择永不阻断，cap 成为正常 Skill 路径规则和诊断 |
| 不使用 title/message 自定义关联信息 + Hook 自动关联 prepared execution | 当前原生 schema 和 opaque-message 证据下无法同时满足；本文要求同时持有 preparation identity 与 native response 的父 Agent显式记录 |
| Hook 不参与 spawn managed mutation + 插件自动知道原生调用是否发生 | 无法同时保证；prepared generation 先落 StateStore，父任务 observation 才记录调用结果，缺失时保持 null/reconcile |
| 父任务 observation 通道 + 防恶意父 Agent伪造 native response | 当前模型无法同时保证；该通道与正式结果记录一样是明确的 parent-authority 协作边界，不是安全边界 |
| prepared generation 自动过期 + 不误删已经调用但 observation 丢失的事实 | 无法同时保证；本文不设时间过期，只允许父任务确认未调用后的显式取消 |
| 完全删除 StateStore + 跨重启恢复/有限预算/正式结果关联 | 无法同时满足；StateStore 必须保留 |
| spawn success/returned target + 立即断言 running | 不成立；success 只是父任务看到的派发响应，running 仍需已准入 exact canonical target 的 `list_agents` observation |
| 删除 task ref + 用相同 Agent ID 的 Start 迟到绑定 | 无法同时成立；本文删除该弱绑定，SubagentStart 始终 unbound，不把 ID 相等提升为新 authority |

## 16. 已确认的设计裁决

用户已确认以下目标，实施对话不得重新引入被删除机制来规避取舍：

1. PreparedContract、task ref、强制 task-name 身份链、双写回滚、reservation 和 expiry 完整删除，不是换名搬进 StateStore。
2. 插件不对 `task_name` 做任何专属强制要求；生成器默认值可替换，Hook correctness 不读取或比较它。
3. generator 仍把 TaskContract、公开 task ID/attempt 和严格 TaskResult 指令写进 child message，但 Hook 永不解析、比较或依赖该 message。
4. preparation 直接在唯一 StateStore 创建有界 generation；父 Agent在收到 native response 后用 exact identity 调用 `--record-spawn-observation`。
5. spawn PreToolUse/PostToolUse 不做 managed registration、claim、补建、identity binding 或 observation mutation，也不因治理状态 deny/rewrite。
6. retry/replacement cap 只对正常 managed preparation 路径机械生效；直接绕过生成器的原生 spawn 保持 unmanaged，插件不错误附着也不宣称阻断。
7. SubagentStart 保持 unbound/advisory；returned Agent ID/canonical path 只作为父任务 dispatch observation，后续 active/terminal 仍走 exact canonical target `list_agents` 边界。
8. D7 是最终综合验收之后的新简化，不是 Slice 6 或新 platform authority；实现会使旧 GO/hash 基线失效，必须重新独立验收并在另行授权后做新真实 smoke。

若后续改变任一裁决，必须先更新本文并重新评估删除量、状态迁移和验收范围，不得在实现中静默偏离。

## 17. 给实现对话的首条指令模板

用户在新对话中可以直接引用本文件并给出如下任务：

```text
请先完整阅读 AGENTS.md、docs/redesign/D7-remove-prepared-contract-dispatch-gate.md、
schemas/codex-hook-events-v1.contract.json、docs/redesign/platform-capability-contract-and-minimal-state-machine.md、
tests/fixtures/exact-task-ref-opaque-message-v1.json、docs/redesign/platform-capability-slice-5-implementation.md、
docs/redesign/platform-capability-slice-6-design.md 和 docs/redesign/platform-capability-final-acceptance-report.md，
检查当前 dirty worktree 与文档中列出的实际代码入口，然后按 R1-R5 在开发仓库实现。
目标是单 StateStore dispatch generation + 父任务 --record-spawn-observation；不得实现 ManagedDispatchEnvelope，
不得从 spawn message/task_name/tool_use_id 关联 managed execution，spawn PreToolUse/PostToolUse 不做 managed mutation。
先补失败测试，保留用户已有修改；不得写稳定发布源、运行缓存、Marketplace、Hook trust 或 Registry，
不得创建真实测试对话。完成后运行文档规定的 focused/full/validator/preflight 验证，
报告实际删除/新增/净减少行数、行为变化、迁移边界、验证证据和仍未检查的真实平台项目；
结论只限开发仓库，不沿用 D7 前 GO 或关键资产哈希宣称新实现已完成真实验收。
```

实施对话应把本文视为目标设计，不把当前 PreparedContract 代码、当前安装版 Skill 或旧历史文档当作更高优先级目标要求。若实际平台契约、当前 Schema 或用户最新裁决与本文冲突，应先报告可复核证据并更新设计，不得静默恢复硬门禁。实现完成后，独立本地验收和真实插件 smoke 必须各自使用新的对话；测试部署、创建真实 Agent 和稳定发布均需遵守项目边界与单独授权。
