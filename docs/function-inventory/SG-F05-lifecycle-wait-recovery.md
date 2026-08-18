# SG-F05 治理状态持久化、等待巡检与异常恢复盘点

> 历史盘点：本文按 v4 功能边界编写，已被 `docs/project-function-inventory.md` 的 v5 清单取代。文中 SG-F06、TaskResult 和已删除 Schema/文档路径只表示历史依赖，不是当前文件或运行时契约。

## 文档状态

- 当前状态：已完成本轮盘点和整体收口；9 个功能点均已确认，不再增加新的功能点。
- 一句话职责：保存治理任务、Agent 身份和运行健康状态，为父 Agent 等待、平台对账、有限恢复、中断保护和会话恢复提供共享状态底座。
- 本文只记录 SG-F05；不修改 `docs/project-function-inventory.md`、SG-F04 独立文档或其他功能文档。
- 本轮依据：最新主盘点文档、SG-F04、SG-F06 独立盘点文档、运行时、规则、Skill、运行边界文档、Schema、单元测试、并发测试和 fixture。

## 一、功能边界

### 1. 主要负责

- 按 `session_id` 持久化任务记录、Agent 映射、状态版本和健康告警。
- 以文件锁、原子写入、私有目录和损坏隔离保护状态一致性。
- 为后续等待、`list_agents` 平台状态对账、同 Agent 恢复、`Stop`、`SessionStart`/`SessionEnd` 和中断状态提供统一数据入口。
- 在状态不可用时告警并降级放行原生 Agent 工具，不把治理插件故障扩大成原生工具不可用。

### 2. 不负责

- 不负责父 Agent 实际调用 `wait_agent`、`list_agents` 或 `followup_task`；等待周期和超时巡检是父 Agent 规则与 Codex 原生工具行为。
- 不负责修复 provider 断流、消息投递、平台唤醒或模型执行错误。
- 不重新生成 SG-F01 的派发契约，不拥有 SG-F03 的通信业务字段，也不负责后续终态功能的业务结果验收。
- 不单独引入数据库、守护进程或第二套编排平台。

## 二、当前情况

### 1. 状态文件与安全边界

- `StateStore` 按 session 生成安全文件名，状态文件和锁文件位于用户私有目录；目录要求为当前用户拥有的普通 `0700` 目录，文件不能是符号链接。
- 更新流程使用独占 `flock`，临时文件 `0600` 写入、`fsync`，随后原子替换状态文件并同步父目录。
- 读取时检查文件类型、拥有者、大小上限和 JSON 根结构，并确认状态中的 `session_id` 与当前 session 一致。
- 当前状态根包含 `version`、`session_id`、`tasks`、`agents`、`health` 和 `updated_at`；`health` 主要用于记录状态损坏后的 degraded 信息，并由 `--diagnose` 输出。

### 2. 损坏隔离与降级

- JSON 损坏或非 UTF-8 时，原文件被重命名为带时间和随机后缀的 `.corrupt-*` 副本，随后建立空的 degraded 状态。
- 状态目录、文件、锁或写入失败时，运行时通过 `UnavailableStateStore` 或各 handler 的异常处理返回告警并放行原生工具。
- 该降级只表示“治理状态不可用但原生调用继续”，不表示任务已成功记录、Agent 已恢复或平台错误已修复。
- 当前未处理的 `PreToolUse` 内部未知异常仍可能由 CLI 包装成 `deny`；这是 SG-F02 的运行时异常边界，不在本项直接改造。

### 3. 版本、Schema 与记录形状

- 运行时声明 `STATE_VERSION = 2`，但读取旧文件时直接把 `version` 覆盖为当前值，没有显式迁移、旧版本拒绝或隔离策略。
- `task-contract-v1.schema.json` 是协议和测试锚点，不是运行时 validator；状态记录同时容纳契约字段、生命周期字段、Agent 映射和平台错误字段。
- Schema 的 `additionalProperties: true` 允许这些运行时扩展字段共存，但没有清楚区分短期 prepared contract、已绑定运行状态和终态结果。
- 数据根目录名仍为 `state-v1`，与 JSON 中的 `STATE_VERSION = 2` 可能表达不同层次，也容易造成发布缓存和状态迁移误解。

### 4. 裁剪与容量

- `_prune_state()` 只清理 `TERMINAL_STATUSES` 中超过 30 天或超过 200 条保留范围的记录，并删除指向不存在任务的 Agent 映射。
- 原实现假设终态记录的时间字段和内嵌 `task_id` 始终有效；坏时间戳可能让一次状态写入失败，内嵌 ID 缺失或不一致也可能导致错误裁剪。
- 本轮已增加 `_record_timestamp()`：优先使用 `updated_at`、回退到 `created_at`，坏值按旧记录处理；裁剪改用任务字典键而非内嵌 `task_id`，并新增对应回归测试。
- 当前没有 `pending`、`running` 或 `retry_required` 的数量/寿命上限；长期活跃记录可能累积到 4 MB 状态文件上限并触发整体状态不可用。

### 5. 锁文件与删除

- `StateStore.delete()` 在锁保护下删除 session JSON，但保留 `.lock` 文件。
- 直接删除锁文件可能与其他进程竞争，形成不同进程使用不同 inode 的锁分裂风险；当前没有安全的锁文件回收策略。

### 6. 状态枚举交界

- 当前 `ACTIVE_STATUSES` 为 `pending`、`dispatched`、`running`、`retry_required`，但运行时代码没有真正写入 `dispatched`。
- `platform_error` 同时被列入 `TERMINAL_STATUSES` 和 `RESOLVABLE_STATUSES`：它可以被 `followup_task` 恢复，却会被终态裁剪和 `_active_records()` 排除。
- `needs_decision`、`blocked` 等状态对 Agent 执行来说可能已经停止，但对父任务仍可能需要用户动作；“Agent 终态”和“治理任务需要处理”目前没有分层。

## 三、与前后文的交接

### 1. 上游交接

- SG-F01 提供治理等级、任务目标、范围、禁止事项、完成条件和任务身份；未来确定性生成脚本应先写短期 `PreparedContractStore`，再把已验证契约绑定进 `StateStore`。
- SG-F02 提供 Manifest、Hook 注册和统一事件路由；状态存储只消费事件，不拥有插件发现或安装入口。
- SG-F04 负责发布版本、安装缓存和旧版本资产保护；它需要知道状态格式是否跨缓存版本兼容，但不应定义运行时状态迁移语义。

### 2. 下游交接

- SG-F03 通过 `tasks` 和 `agents` 消费任务映射与可解析状态；它不应为普通消息或 follow-up 创建第二套任务状态。
- 后续等待/平台对账功能消费活跃任务和 Agent 映射；恢复功能消费 `platform_error`、`retry_required`、恢复次数和失败摘要。
- 中断、Stop、SessionStart/End 和后续终态验收共享同一记录，因此它们必须共同确认“活跃”“需要治理动作”和“真正终态”的分类。
- 终态功能应使用独立的结构化结果对象或明确的结果字段，不应继续把业务结果和契约状态无边界地混在同一记录中。

## 四、改进建议

### 1. 保留一个共享状态底座，拆分数据职责

建议保留 `StateStore` 作为 session 级运行状态底座，同时新增短期 `PreparedContractStore`，后续再由终态功能定义 `PreparedResult` 或结构化结果存储。不要引入数据库、后台服务或第二套编排平台。

### 2. 建立显式状态版本策略

最终方案必须决定旧版本是迁移、隔离还是拒绝，并为迁移失败保留可诊断降级；在此之前不要直接改 `STATE_VERSION` 或 `state-v1` 路径名称。

### 3. 分离执行状态与治理动作状态

建议把 `platform_error`、`needs_decision`、`blocked` 从“是否仍在运行”问题中分离出来，形成可供 `Stop`、`SessionStart` 和恢复逻辑共同使用的 action-required 语义。

### 4. 限制活跃状态增长

除终态数量/保留期外，应设计活跃任务上限、长期无更新告警、状态接近容量上限时的处理和不误删可恢复任务的规则。

### 5. 收紧状态结构校验

至少校验版本、session、任务键与 `task_id`、时间字段、Agent 映射和状态枚举；是否直接执行完整 JSON Schema 校验，留给 SG-F01 确定性契约和最终统一方案决定。

### 6. 明确降级边界

状态不可用时可以 fail-open 并告警；但 prepared contract 缺失、过期或篡改属于身份完整性错误，不能未经决策直接套用普通 StateStore 降级规则。

## 五、可局部直接实施的内容

本轮已在用户授权范围内直接完成以下低风险修补：

- 新增 `_record_timestamp()`，安全处理坏的 `updated_at`/`created_at`。
- `_prune_state()` 改用状态字典键作为任务身份，不再依赖可能缺失或不一致的内嵌 `task_id`。
- 新增 `test_state_pruning_tolerates_malformed_terminal_records`，覆盖坏时间戳、创建时间回退、缺少内嵌 ID、活跃坏记录和 Agent 映射清理。

这些改动不改变任何状态枚举、恢复上限或会话生命周期语义。

## 六、必须留待最终统一方案的内容

以下事项已经确认是问题输入，但不应在第一项中孤立修改：

- `STATE_VERSION` 迁移、拒绝、隔离和数据目录版本命名。
- `PreparedContractStore`、`StateStore` 与终态结果存储的职责拆分。
- `platform_error`、`needs_decision`、`blocked` 的 action-required 语义及其对裁剪、Stop、SessionStart 的影响。
- 活跃任务数量/寿命上限、4 MB 超限和长任务保留。
- `SessionEnd` 是否保留仍需恢复或用户决策的任务。
- `.lock` 文件的安全回收和并发 SessionEnd 竞态。
- 状态不可用与契约缺失/篡改的不同降级策略。
- 发布缓存切换时不同版本运行时读取同一状态的兼容门禁。

## 七、测试与证据覆盖

- `tests/test_governance.py` 已覆盖状态损坏隔离、非 UTF-8 隔离、写入失败降级、状态裁剪、状态 Schema 形状和诊断输出。
- `tests/test_concurrency.py` 已覆盖 32 个并发派发不会丢失任务记录。
- 本轮新增裁剪坏记录回归测试，并运行：

  ```text
  python3 -m unittest tests.test_governance.GovernanceTests.test_state_pruning_keeps_only_recent_terminal_records tests.test_governance.GovernanceTests.test_state_pruning_tolerates_malformed_terminal_records tests.test_concurrency -v
  ```

  结果：3 项测试全部通过。

- 完整回归与静态验证：

  - `python3 -m unittest discover -s tests -v`：116 项通过。
  - `python3 -m py_compile scripts/subagent_governance.py`：通过。
  - Plugin validator：通过。
  - `git diff --check` 与 SG-F05 文档尾随空白检查：通过。

- 尚未证明：旧版本迁移、多进程 `SessionEnd` 竞争、活跃记录超限、真实 Codex Hook 触发、真实 wait/wake、provider 恢复或跨缓存版本状态兼容。

## 八、当前文件与代码覆盖

| 文件或区段 | 归属 | 说明 |
| --- | --- | --- |
| `scripts/subagent_governance.py`：`StateStore`、`UnavailableStateStore`、状态常量和 `_record_timestamp()`/`_prune_state()` | SG-F05 主要归属 | 状态数据、安全、裁剪和降级底座 |
| `schemas/task-contract-v1.schema.json` | SG-F01 主要归属，SG-F05 次要关联 | 当前契约字段与运行状态字段仍有混合交界 |
| `tests/test_governance.py` 状态存储、损坏隔离、降级和裁剪测试 | SG-F05 主要归属 | 保护状态底座边界 |
| `tests/test_concurrency.py` | SG-F05 主要归属 | 保护并发状态更新不丢记录 |
| `skills/subagent-governance/references/runtime-boundaries.md` | SG-F05 次要关联 | 说明状态降级和原生平台边界 |
| `docs/function-inventory/SG-F04-install-release-cache.md` | SG-F04 主要归属 | 仅交接发布缓存兼容，不重复归属状态存储 |

## 九、跨功能冲突与修改方案输入

- SG-F01 计划引入 `PreparedContractStore`，不能与现有按 session 的 `StateStore` 混为同一存储生命周期。
- SG-F03 仍依赖 `tasks`/`agents` 映射，不能单独改变任务 ID 或状态枚举。
- SG-F04 的旧缓存保护意味着状态格式迁移必须考虑旧运行时代码仍可能存在；发布安装功能不应自行修改状态文件。
- 后续等待、恢复、Stop、SessionStart/End 和终态功能必须共同确认状态分类，否则会继续出现 `platform_error` 可恢复但被当作终态的矛盾。

## 十、第二项：任务—Agent 身份绑定与启动确认

### 1. 当前情况

- `PostToolUse` 的派发分支首先按 `tool_use_id` 找回 pending 任务；事件 ID 发生漂移时，再按 `task_name` 与 `turn_id` 回退，只有候选唯一时才绑定。
- 原生派发成功但响应缺少 `agent_id` 或 `canonical_task_path` 时，当前任务仍会进入 `running`，形成无法通信、平台对账或终态验收的 `unmapped running`。
- `_resolve_task_id()` 的解析顺序是直接 `agents[target]`、完全匹配 `canonical_task_path`、最后是 canonical path 末段的唯一 `task_name`；终态、失效映射和歧义候选不会被重新关联。
- `SubagentStart` 对已有活跃映射进入 `running`；对 `retry_required` 的成功恢复可以确认再次启动；终态任务不会仅因启动事件被复活。
- 当 `SubagentStart` 没有已有映射且只有一个未绑定活跃候选时，`_assign_starting_agent()` 仍会自动猜测并补绑定；这是稳定任务引用完成前的临时保护。
- `SubagentStart` 输出固定生命周期元数据，只传递任务 ID、状态、治理等级和告警，不重复原始目标、范围或完成条件；这符合主线程说明与子 Agent 首句分层规则。
- `_extract_values()` 会递归搜索响应中的多种身份字段，`_response_failed()` 会递归搜索错误字段；这能容忍响应形状漂移，但也可能把无关嵌套值误当成身份或错误。

### 2. 前后文交接

- SG-F01 负责创建治理任务身份和派发契约；SG-F05 消费其任务 ID，不重新判断治理等级或生成派发业务字段。
- SG-F02 负责把 `spawn_agent`、`SubagentStart` 和 `PostToolUse` 接入统一脚本；具体身份绑定和启动状态属于 SG-F05。
- SG-F03 已消费当前映射规则来关联普通消息和 follow-up，但其 `task_name` 唯一回退、通信身份和 prepared communication 最终要交给稳定任务引用方案统一替换。
- SG-F04 保护旧缓存和已打开任务引用的旧版本资产；它不应自行猜测 Agent 身份，但发布切换必须兼容状态 Schema 和任务引用的版本演进。
- 后续等待、平台错误对账、恢复上限、中断、Stop、SessionStart/End 和终态验收都复用同一 Agent—任务关系；因此不能在某个功能中单独删除 task name 回退或改变映射状态语义。

### 3. 改进建议

1. 让 prepared contract 携带稳定、唯一的任务引用，派发响应通过明确适配器绑定 `agent_id` 和 canonical path；成功绑定后不再依赖 `task_name` 猜测。
2. 将派发结果区分为“已调用但身份未确认”和“已取得 Agent 身份”，避免把 `unmapped running` 当成正常运行。
3. 为映射写入记录来源和时间，例如 `tool_use_id`、canonical path、task name fallback 或 `SubagentStart` fallback，便于诊断迟到事件和标识漂移。
4. 将身份解析从“递归搜所有字符串”收紧为声明过的受支持响应结构；未知结构应记录未确认，而不是静默选取第一个值。
5. 保留未映射 Agent 的原生放行边界，避免插件干扰第三方或特殊启动路径；但应向父任务提供明确的 `unmapped` 诊断摘要。
6. 在稳定引用方案完成后删除 `_assign_starting_agent()` 的唯一候选自动绑定和 `_resolve_task_id()` 的唯一 `task_name` 回退，并保留迁移期的明确失败证据而不是静默 pending。

### 4. 本轮可局部直接实施的内容

- 已复用第一项新增的 `_record_timestamp()`，让 `SubagentStart` 的未绑定候选排序在遇到坏 `created_at` 时安全降级，不因混合类型时间戳抛出异常。
- 已新增 `test_subagent_start_tolerates_malformed_candidate_timestamps`，确认坏候选记录不会破坏启动事件，也不会在多个候选存在时擅自猜测身份。

该修补只增加容错和证据，不改变当前身份解析顺序、唯一候选回退或 `unmapped running` 状态语义。

### 5. 必须留待最终统一方案的内容

- prepared contract/communication 的稳定任务引用格式和存储交接。
- `tool_use_id` 漂移、Agent ID 漂移、canonical path 重用、task name 重名和迟到事件的冲突协议。
- `unmapped running` 是否改为 `dispatched`、`identity_unconfirmed` 或独立诊断字段。
- 是否记录身份绑定来源、绑定时间、响应版本和原生响应摘要。
- 递归身份/错误提取应支持的真实 Codex 响应 Schema。
- 唯一候选自动绑定和 task name 回退的退出时机，以及旧缓存版本如何读取新引用。
- `SubagentStart` 在 `platform_error`、`needs_decision`、`blocked` 和 `interrupted` 状态下的统一上下文和恢复入口。

### 6. 测试与证据

- 已有测试覆盖：`tool_use_id` 直接绑定、事件 ID 漂移回退、canonical path、task name 唯一回退、同名歧义不猜测、成功但无身份的 `unmapped running`、失效映射清理、终态不复活、成功 follow-up 后再次启动和固定启动上下文。
- 本轮新增坏时间戳候选测试；身份绑定与启动相关 5 项定向测试通过。
- 完整回归更新为 117 项通过；Python 编译、Plugin validator、`git diff --check` 和 SG-F05 文档尾随空白检查均通过。
- 尚未证明：真实 Codex 派发响应的稳定字段形状、跨版本 Agent ID 漂移、任务名重用、真实 SubagentStart 自动触发和平台唤醒后的身份恢复。

## 十一、第三项：父 Agent 等待与目标巡检

### 1. 当前情况

- 派发完成后，父 Agent 按规则保存 Agent ID 和 canonical task path，并显式调用原生 `wait_agent`，单次等待参数为 `timeout_ms: 1200000`。
- mailbox 的正常消息、完成通知或用户输入会由 Codex 平台提前结束等待；这属于原生工具和平台调度能力，不是 Hook 生成的唤醒事件。
- mailbox 明确报告 `stream disconnected`、`errored` 或其他平台执行失败时，父 Agent 应立即调用目标范围的 `list_agents`，不等待 20 分钟超时。
- 只有等待满 20 分钟时才进行一次目标范围巡检；支持时使用 canonical task path 作为 `path_prefix`，避免扫描无关 Agent。
- Agent 仍正常运行时，父 Agent 不读取代码、Git、日志或测试状态，不发送心跳，也不向用户输出无证据进度；直接再次调用 `wait_agent`。
- 等待超时、沉默、长测试和上下文压缩都不是异常证据；只有平台状态提供客观停止、消失或错误证据时才进入恢复判断。
- `hooks/hooks.json` 没有匹配 `wait_agent`；Hook 不观察等待开始或超时，也没有后台定时器。`PostToolUse` 只在父 Agent 已调用 `list_agents` 后观察其响应。
- 因此当前“沉睡—检查—唤醒”由三部分组成：父 Agent 执行规则、Codex 原生等待/唤醒工具、Hook 对已发生 `list_agents` 结果的状态记录。

### 2. 前后文交接

- SG-F01 在允许下级子 Agent 或隔离上下文派发时，必须把终态通知和等待巡检规则写入派发契约；它负责交接规则，不执行等待。
- SG-F02 只确认 `list_agents` 的 PostToolUse 接线和 Hook 路由；没有 `wait_agent` Hook 是当前真实边界，不是漏注册的自动调度能力。
- SG-F03 已确认恢复消息、恢复次数和网络断流后的通信交界；其主盘点文档中的等待—检查—唤醒段落属于跨功能说明，SG-F05 是等待巡检状态链的主要归属。
- 第二项身份绑定提供目标 Agent ID/canonical path；没有稳定身份时，父 Agent 无法执行可靠的目标范围巡检。
- 下一项平台状态对账消费 `list_agents` 的明确结果；本项不根据返回文本自行改变任务状态。
- Stop 和 SessionStart/End 必须确保父任务等待期间不会丢失任务或重复派发；该部分由后续会话与停止功能继续盘点。

### 3. 改进建议

1. 保留原生 `wait_agent` 作为唯一等待通道，不在插件中增加后台 scheduler、轮询线程或第二套唤醒系统。
2. 将等待规则作为确定性派发/恢复模板的一部分生成，尤其在允许下级 Agent 或隔离上下文时，避免仅依赖压缩前的父线程历史。
3. 父 Agent 应保存稳定任务引用、Agent ID、canonical path 和最近一次等待/巡检结论；若平台没有可观察的 wait 事件，不应伪造 Hook 状态表示“正在等待”。
4. 20 分钟是父 Agent 策略值，不是 Hook timeout；未来若允许调整，应使用单一策略来源生成规则和测试，不要散落多个自然语言常量。
5. 真实验收应区分“`wait_agent` 正常等待”“超时返回”“mailbox 平台错误”“用户输入打断”和“任务完成通知”五类唤醒原因。
6. 继续保持健康巡检静默；用户可见消息只在出现实质结果、明确错误或需要决策时发送。

### 4. 本轮可局部直接实施的内容

- 第三项盘点时完整规则同时出现在规则资产和 Skill；SG-F04 后续已把 `assets/agents-governance.md` 收敛为最小 Skill 入口。当前完整等待、巡检和恢复软指导以 Skill 为主要来源，运行边界文档说明能力限制；Hook 没有定时器，也不能独立唤醒主线程或子 Agent。
- 本轮新增 `test_waiting_rules_keep_orchestration_with_parent_and_native_tools`，机械保护以下边界：20 分钟等待参数、超时后目标巡检、`path_prefix`、超时不等于错误、正常路径重新等待、父 Agent 显式调用，以及 Hook 不注册 `wait_agent` 但保留 `list_agents` 观察入口。
- 不新增 `wait_agent` Hook，也不修改运行时代码；增加该入口会错误暗示插件能够观察或控制原生等待生命周期。

### 5. 必须留待最终统一方案的内容

- 是否需要确定性的等待策略生成器，以及它与派发生成脚本、下级 Agent 契约的共享参数结构。
- 父 Agent 等待 checkpoint 是否需要持久化；若平台没有 wait 事件，如何在不伪造状态的前提下记录。
- 20 分钟策略是否固定、可配置或按任务类型调整，以及如何保持 Skill、最小全局入口和测试一致。
- `wait_agent`、mailbox update 和用户输入的真实平台返回形状及恢复后的线程唤醒语义。
- 并行多个 Agent 时的批量等待、单目标巡检和 mailbox 首个事件唤醒策略。
- compact/resume、Stop 或 SessionEnd 发生在等待期间时的状态保留和继续等待行为。
- 是否需要平台级自动化支持；插件只能声明依赖，不能把外部自动化能力描述成当前实现。

### 6. 测试与证据

- 规则一致性测试可以证明发布资产明确要求父 Agent 使用 `wait_agent`/`list_agents`，并证明当前 Hook 配置没有 `wait_agent` matcher。
- 本轮等待边界、`list_agents` 对账和 Hook 配置 3 项定向测试通过；完整回归更新为 118 项通过，Python 编译、Plugin validator、`git diff --check` 和文档尾随空白检查均通过。
- handler、fixture 和单元测试只能证明已有 `list_agents` payload 的状态对账，不能证明 Codex 会按 20 分钟周期自动调用工具或真实唤醒父任务。
- 尚缺真实平台验收：正常完成提前唤醒、20 分钟超时、错误立即唤醒、用户输入中断、多个 Agent 等待和 compact/resume 后继续等待。

## 十二、第四项：平台状态对账与错误分类

### 1. 当前情况

- `PostToolUse` 只有在父 Agent 已经主动调用原生 `list_agents` 后，才能读取响应中的 `agents[*].agent_status`；Hook 不会主动查询平台，也不会因 mailbox 文本自行执行对账。
- 只有明确形如 `agent_status: {"errored": ...}` 的状态才把已映射任务转为 `platform_error`，同时记录 `platform_checked_at`、有界 `platform_error` 摘要和有界错误状态快照。
- `running` 等非错误平台状态只更新最近检查信息，不把治理任务改成 `running`、`complete` 或其他生命周期状态；平台健康与任务业务终态仍是两个不同维度。
- 非错误平台状态当前仍把整个 `agent_status` 对象写入 `platform_status`；在真实响应 Schema 尚未确认前，本轮没有贸然丢弃字段，但超大未知诊断仍可能触发状态容量问题。
- 非错误对账只写 `platform_checked_at`，不会刷新 `_active_records()` 使用的 `updated_at`；因此任务即使刚被平台确认仍在运行，创建或生命周期更新时间超过 12 小时后仍可能从 Stop/SessionStart 的活跃集合中消失。
- 平台错误文本不再按字符串识别 `provider_protocol_incompatible` 等业务分类；插件只记录可观察的 `errored` 事实，具体错误诊断和用户决策由后续恢复/诊断流程处理。
- 当前 `platform_error` 同时属于 `TERMINAL_STATUSES` 和 `RESOLVABLE_STATUSES`：通信解析和 `followup_task` 可以找到它，但 `_active_records()`、`Stop` 和 `SessionStart` 会忽略它，终态裁剪还可能回收它。这是状态分类矛盾，不适合在本项局部修改。
- Hook 记录 `platform_error` 后不会自动调用 `followup_task`、重新等待、重新派发或修复 provider 流；后续动作仍由父 Agent 按规则显式执行。

### 2. 前后文交接

- 上游等待巡检只负责何时调用 `list_agents` 和限定目标范围；本项只消费已经返回的平台证据，不能把等待超时、沉默或 `stream disconnected` 文本本身直接当作 Agent 已 errored。
- 第二项身份绑定提供 Agent ID/canonical path 到治理任务的映射；未映射 Agent 的平台状态保持原生放行，不应猜测关联到唯一任务。
- SG-F03 负责 `send_message`/`followup_task` 的通信格式和恢复调用；本项负责恢复前的 `platform_error` 状态入口，不拥有恢复消息内容。
- 下一项有限恢复应消费 `platform_error`、恢复次数和最近错误摘要，决定同 Agent 恢复一次或进入 `needs_decision`；不能在 `list_agents` 对账 handler 内直接执行恢复。
- 后续 Stop、SessionStart/End 和终态功能必须共同决定 action-required、Agent 终态和可裁剪终态的分类，否则平台失败任务仍可能过早从父任务视野中消失。

### 3. 改进建议

1. 将平台观察状态与治理生命周期分层：`platform_status` 表示最近一次平台证据，`execution_status` 表示 Agent 是否运行，`action_required` 表示父任务是否仍需恢复或决策。
2. 给 `list_agents` 建立明确响应适配器，只接受已确认的 Agent 标识和状态字段；未知、缺失、重复或歧义响应应记录诊断，不应改变生命周期。
3. 为对账增加单调性或事件时序规则，防止迟到的 `running`、重复 `errored` 或乱序响应覆盖较新的恢复/终态状态。
4. 对平台错误摘要继续执行长度限制，并在最终方案中确认敏感信息清理、结构化错误码和原始诊断是否只进入日志而非持久状态。
5. 明确 `platform_checked_at` 是否参与活跃性判断：不应把健康检查等同于业务进展，但也不能让刚确认仍在运行的长任务因 12 小时截止而消失；建议独立计算执行存活和业务更新时间。
6. 保持普通健康状态不推断业务完成；只有终态 Hook 和业务验收可以确认任务结果，`list_agents` 不能代替终态协议。
7. 增加真实 Codex 平台验收，确认 `list_agents` 的实际 Schema、errored/正常状态形状、canonical path 映射以及断流后是否仍可取得可信状态。

### 4. 本轮可局部直接实施的内容

- 原实现虽然对 `platform_error` 字段做了长度限制，却仍把完整 `agent_status` 原样写入 `platform_status`；超长 provider 诊断可能使整个 session 状态超过 4 MB 并导致状态存储降级。
- 本轮已将明确错误状态改为只持久化 `{"errored": <有界摘要>}`，不再保存同一错误对象中的额外大体积诊断字段；这只收紧存储边界，不改变 `platform_error` 状态转换。
- 非错误状态仍保存当前平台快照并增加 `platform_checked_at`，但不改变治理任务生命周期。
- 已新增 `test_list_agents_bounds_recorded_platform_error_snapshot` 和 `test_list_agents_non_error_status_does_not_change_lifecycle`，分别保护容量边界和“观察不等于状态推断”的原则。

### 5. 必须留待最终统一方案的内容

- `platform_error` 是否应从可裁剪终态集合中移出，改为 action-required 或独立执行终态维度。
- `platform_error` 对 Stop、SessionStart、SessionEnd、状态裁剪和 12 小时恢复摘要的统一行为。
- 普通平台错误、恢复上限、`provider_protocol_incompatible`、业务阻塞、主动中断和真实终态之间的结构化分类。
- `list_agents` 真实响应适配器、多个标识匹配、迟到/重复/乱序事件和未知状态的处理。
- 非错误 `platform_status` 的字段白名单与容量限制，以及 `platform_checked_at` 和 12 小时活跃截止之间的关系。
- 错误快照的敏感信息清理、结构化错误码、日志保留与状态文件容量预算。
- 真实平台 errored/normal 状态和 mailbox 断流后的端到端验收；fixture 只能证明既定 payload 的 handler 行为。

### 6. 测试与证据

- 既有 `test_list_agents_reconciles_stream_error` 和 fixture 测试证明：明确 `errored` payload 会把已映射任务对账为 `platform_error`。
- 本轮新增的有界错误快照与非错误状态测试，与 `test_all_platform_error_text_uses_bounded_recovery` 一起通过；第四项 4 个定向测试全部通过。
- 单元测试不证明父 Agent 会自动调用 `list_agents`，也不证明 Codex 平台会返回相同 Schema、自动恢复 provider 或重新唤醒主线程。
- 完整回归更新为 120 项通过；`python3 -m py_compile scripts/subagent_governance.py`、Plugin validator、`git diff --check` 和 SG-F05 文档尾随空白检查均通过。

## 十三、第五项：同 Agent 有限恢复与恢复上限

### 1. 当前情况

- 本功能点不主动发起恢复。父 Agent 按规则确认需要恢复后显式调用原生 `followup_task`；SG-F03 负责通信业务参数和固定消息，本项负责恢复资格、恢复次数和生命周期状态转换。
- 新任务记录初始化 `recovery_count = 0`。只有任务当前处于 `platform_error`，且 follow-up 的 PostToolUse 响应没有被 `_response_failed()` 识别为明确失败时，才增加恢复次数并进入 `retry_required`。
- `pending`、`dispatched`、`running` 或已有 `retry_required` 状态下的普通 follow-up 不消耗平台恢复次数；明确失败的 follow-up 也保持 `platform_error` 和原恢复次数。
- `SubagentStart` 是当前确认恢复启动的唯一生命周期信号：已映射 `retry_required` 任务收到启动事件后进入 `running`。follow-up 工具返回本身只表示“没有被机械规则识别为失败”，不能证明消息送达、Agent 已重新启动或业务任务已恢复完成。
- `MAX_PLATFORM_RECOVERIES = 1`。任务完成一次恢复后再次被 `list_agents` 对账为 `platform_error`，下一次 follow-up 的 PreToolUse 会把任务转为 `needs_decision` 并拒绝调用；后续对同一目标继续拒绝，`recovery_count` 保持 1。
- 当前没有恢复 attempt ID、in-flight 状态、checkpoint 字段或 Pre/PostToolUse 精确关联。恢复依赖回调时重新解析目标和当前状态。
- `needs_decision` 当前只有进入路径，没有由用户决策驱动的结构化退出路径；切换 provider、稍后重试或重建任务仍依赖父 Agent 自行解释并可能创建新治理任务。

### 2. 当前完整状态链

```text
platform_error + recovery_count=0
  → followup_task PreToolUse 允许
  → 原生 followup 未明确失败
  → PostToolUse: retry_required + recovery_count=1
  → SubagentStart: running
  → list_agents 再次明确 errored
  → platform_error + recovery_count=1
  → 下一次 followup_task PreToolUse
  → needs_decision，拒绝继续自动恢复
```

链路中的三个结果层不能合并：原生 follow-up 未明确失败、Agent 再次启动、业务任务最终完成分别由 PostToolUse、`SubagentStart` 和后续终态验收确认。

### 3. 前后文交接

- 第四项平台状态对账提供唯一正常恢复入口 `platform_error`；等待超时、普通消息失败或业务阻塞不能自行消耗平台恢复次数。
- 第二项身份绑定提供同一 Agent 的 ID/canonical path 映射；如果恢复后 Agent 标识变化且 `SubagentStart` 无法重新关联，任务可能停留在 `retry_required`。
- SG-F03 主要拥有恢复消息字段、用户可见通信说明、`updatedInput` 投影和未来 communication ID/prepared communication；SG-F05 主要拥有恢复资格、计数、状态转换、并发和恢复上限。主盘点中 SG-F03 已记录的恢复次数结论应在最终合并时改为跨功能交接，避免双重主要归属。
- 父 Agent 规则决定是否调用 `followup_task`、是否继续等待和何时向用户请求决策；Hook 只阻止超过上限的已映射恢复，不能自行执行恢复或 provider 切换。
- 后续 Stop、SessionStart/End 必须保留 `retry_required`、`platform_error` 和 `needs_decision` 的处理线索；终态功能负责确认恢复后的业务结果，不能把 `SubagentStart` 当作完成。
- SG-F04 只保证当前/上一版本运行代码缓存；恢复期间若跨版本，`recovery_count`、attempt 状态和任务引用的兼容性归 SG-F05。

### 4. 已确认的问题

1. **恢复成功证据偏弱**：空响应、未知响应或没有可识别错误字段都被视为“未明确失败”，随后计入恢复次数；这不是平台接收或 Agent 处理的权威证明。
2. **并发双恢复窗口**：两个并发 PreToolUse 都可能在 `recovery_count = 0` 时获准调用原生 follow-up；计数只在 PostToolUse 更新，缺少原子恢复占位，无法保证平台层只收到一次恢复。
3. **缺少执行关联**：迟到的旧 PostToolUse 可能在任务重新进入 `platform_error` 后被误当作本轮恢复成功；当前没有 communication/attempt ID 区分调用。
4. **启动确认依赖未验证**：代码和 fixture 假设成功 follow-up 后会出现 `SubagentStart`，但尚无真实 Codex 证据证明恢复同一 Agent 总会重触发该 Hook；若不触发，任务会长期停留在 `retry_required`。
5. **`needs_decision` 是状态死路**：当前可以阻止第二次恢复，却没有记录用户选择、解除决策状态、重用 checkpoint 或安全建立替代任务的协议。
6. **恢复上下文不足**：当前恢复消息由父 Agent 提供业务内容，状态记录没有结构化 checkpoint、已完成工作或继续条件；“恢复同一 Agent”不等于上下文一定完整。
7. **计数损坏会错误阻断**：原实现直接执行 `int(recovery_count)`；合法 JSON 中的非数字、负数或布尔值会导致 PreToolUse 异常，并由 CLI 包装成 deny，违反状态异常降级放行原则。
8. **规则版本发生漂移**：当前开发仓库的 Skill、运行边界和代码统一规定“不解析 provider 错误文本”，`assets/agents-governance.md` 已缩成不承载该语义的最小入口；但本任务启动时加载的 `$HOME/.codex/AGENTS.md` 旧规则快照仍要求识别 `provider_protocol_incompatible` 并首次直接进入 `needs_decision`。这说明开发源、已部署全局入口或已打开任务快照不是同一语义版本，必须与 SG-F04 发布/缓存治理联合处理。

### 5. 改进建议

1. 为每次平台恢复建立稳定 `recovery_attempt_id`，至少记录任务 ID、目标 Agent、触发错误、创建时间、状态和关联的原生 tool use ID；不要只靠 target 和当前状态重猜。
2. 在 PreToolUse 原子预留 `recovery_in_flight`，防止并发双调用；PostToolUse 明确失败时释放或标记失败，缺失回调时通过有界超时进入待对账状态，而不是无限占位。
3. 分离 `recovery_attempt_count`、`native_call_status`、`agent_restart_status` 和任务业务状态，明确恢复上限统计的是“已发起”“原生接受”还是“Agent 已重启”。
4. 由真实响应适配器确认 follow-up 成功/失败；未知响应应标记 `outcome_unknown` 并请求 `list_agents` 对账，不应直接宣称恢复成功。
5. 明确恢复确认事件：若真实平台保证 `SubagentStart`，为其建立版本化证据；若不保证，则允许由可信 `list_agents running` 或其他原生事件确认执行恢复，但仍不推断业务完成。
6. 为 `needs_decision` 定义结构化决策和退出路径，例如 retry later、switch provider、rebuild from checkpoint、cancel；每个选择都要保留原任务引用并防止重复派发。
7. 将 provider 错误分类策略放入单一语义来源。最终只能二选一：所有错误统一有界恢复，或按结构化错误码区分不可恢复错误；不能继续由全局规则按文本特判、仓库代码却统一恢复。
8. 恢复消息应消费结构化 checkpoint 和继续条件，但消息生成仍归 SG-F03；SG-F05 只定义恢复状态所需字段和交接契约。

### 6. 本轮可局部直接实施的内容

- 新增 `_recovery_count()`，安全解析非负恢复次数；字符串、负数和布尔值不再直接触发异常。
- PreToolUse 遇到无效恢复次数时将其规范化为 0，向父任务返回明确降级告警，并放行本次原生 follow-up；这遵守治理状态异常不应禁用原生工具的现行边界。
- follow-up 成功回调复用同一安全解析，避免 PostToolUse 因坏计数失去状态交接；规范化后的首次成功恢复记录为 1 并进入 `retry_required`。
- 新增 `test_malformed_platform_recovery_count_degrades_open_and_recovers`，先稳定复现原有 `ValueError`，再验证告警放行、计数归一化和成功回调状态转换。

本轮不局部增加 `recovery_in_flight`、attempt ID 或 `needs_decision` 退出路径，因为这些会同时改变 SG-F03 的 Pre/PostToolUse 关联、状态 Schema、会话恢复和并发语义。

### 7. 必须留待最终统一方案的内容

- `recovery_attempt_id`、prepared communication 和 Pre/PostToolUse 精确关联的共同协议。
- 并发恢复的原子占位、失败释放、未知结果、超时和迟到回调处理。
- 恢复次数究竟统计发起、原生接受还是 Agent 再启动，以及旧 `recovery_count` 的迁移语义。
- `SubagentStart` 是否是 follow-up 恢复的可靠确认事件，以及 Agent ID 漂移后的重新绑定。
- `needs_decision` 的用户决策对象、退出转换、checkpoint 重建和取消语义。
- 已部署全局入口、Skill、运行代码、稳定缓存和已打开任务规则快照之间的 provider 错误分类版本漂移。
- `retry_required`、`platform_error`、`needs_decision` 对 Stop、SessionStart/End、裁剪和跨版本恢复的共同分类。
- 真实平台验收：并发 follow-up、调用成功但未启动、PostToolUse 缺失、迟到回调、二次错误、用户决策后继续和不重复派发。

### 8. 测试与证据

- 单元测试已覆盖非平台 follow-up 不计数、明确失败不计数、首次成功进入 `retry_required`、`SubagentStart` 恢复 `running`、第二次错误触发上限、同目标重复拒绝和 canonical path 标识漂移。
- `recovery-limit-v1.json` fixture 覆盖一条连续事件链，但它直接调用 `handle()`；不能证明真实平台接受附加通信参数、生成相同事件顺序或在恢复后触发 `SubagentStart`。
- 本轮新增坏计数降级测试；第五项 7 个定向测试全部通过。
- 完整回归更新为 128 项通过；`python3 -m py_compile scripts/subagent_governance.py`、Plugin validator、`git diff --check` 和 SG-F05 文档尾随空白检查均通过。测试总数包含并行任务同期新增的其他测试，本项新增 1 项。

## 十四、第六项：主动中断与中断终态

### 1. 当前情况

- `interrupt_agent` 始终由父 Agent 或用户工作流显式调用，插件不会因等待超时、状态含糊、`list_agents` 失败或平台断流自动中断 Agent。
- `hooks/hooks.json` 只在 PostToolUse 观察 `interrupt_agent`。此前没有运行时处理的 PreToolUse 空转入口已在 SG-F01 移除；当前 Hook 不校验中断原因、用户可见说明或授权上下文。
- 父 Agent 规则要求业务中断前先在主线程使用 `【子 Agent 通信】` 说明对象、目的、原因和期望结果，但 Hook 不读取 transcript，因此这是一条父 Agent 行为规则，不是插件可机械证明的前置条件。
- PostToolUse 使用 `_response_failed()` 判断明确失败；明确失败或缺少 target 时不改变状态。原生 `interrupt_agent` 返回的是目标 Agent 的先前状态，因此 fixture 中 `{"status": "running"}` 可以表示成功中断了先前运行中的 Agent，而不是中断后仍在运行。
- 成功中断会把已映射且可中断的治理任务写为 `interrupted`，记录 `updated_at` 和 `interrupt_tool_use_id`；Stop 随后不再把它视为活跃任务。
- 原实现只允许 `ACTIVE_STATUSES` 转为 `interrupted`，导致 `platform_error` 和 `needs_decision` 即使原生中断成功也保留旧状态。本轮已把这两个仍需父任务行动的状态加入显式 `INTERRUPTIBLE_STATUSES`。
- `complete`、`blocked`、`failed`、`protocol_error` 和已经 `interrupted` 的真正终态不会被迟到的中断回调覆盖；当前语义是已经确认的业务终态优先于迟到中断。
- 未映射 target、失效 Agent 映射或不支持的目标形态按原生调用结果放行，但无法形成治理任务的中断终态；插件不会猜测唯一任务身份。

### 2. 中断后的状态稳定性

```text
ACTIVE / platform_error / needs_decision
  → 原生 interrupt_agent 明确失败
      → 保留原状态
  → 原生 interrupt_agent 未明确失败
      → interrupted
          → Stop 放行父任务结束
          → 迟到 followup PostToolUse 不再计恢复
          → 迟到 SubagentStart 不复活任务
          → 迟到 SubagentStop 不覆盖 interrupted
          → 后续 list_agents 不重新对账为 platform_error
```

这个链路只能证明治理记录已按原生中断结果闭环，不能证明远端模型进程、provider 请求或平台内部资源已经物理终止。

### 3. 前后文交接

- 等待巡检功能负责“无证据不干预”；只有用户或父 Agent 基于明确业务决定才进入中断，本项不把超时自动升级为 interrupt。
- 身份绑定功能提供 target 到治理任务的映射；中断 PostToolUse 当前只消费直接映射，不拥有 canonical path/task name 的新猜测规则。
- SG-F03 只与中断前的用户可见通信说明交界，不拥有中断状态机；`interrupt_agent` 没有业务消息投影，也不应被包装成 `send_message` 或 `followup_task`。
- 恢复功能与中断互斥：成功中断后旧 follow-up、SubagentStart 或平台错误不能重新激活任务；如果用户未来明确要求重建，应创建带原任务引用的新执行身份，而不是复活 `interrupted`。
- Stop 消费 `interrupted` 作为不再阻止父任务结束的终态；SessionStart 不恢复该任务。第九项实施后，仅剩 `interrupted` 等不可恢复状态时 SessionEnd 可以清理 session；若并存其他可恢复状态则保留整个状态文件。
- 后续终态功能需要决定中断是否生成结构化 result/cancellation 文档；当前只保存状态和 tool use ID，没有原因、发起者、先前状态或用户决策证据。

### 4. 已确认的问题

1. **成功判定仍是负向推断**：除明确错误外，空响应和未知响应也会被视为中断成功；当前 fixture 的 `status=running` 有原生“返回先前状态”语义支持，但仍缺少完整响应适配器。
2. **没有中断 attempt 身份**：只记录 PostToolUse 的 `interrupt_tool_use_id`，没有 prepared interrupt、Pre/Post 精确关联、请求时间、完成时间或幂等键。
3. **并发终态采用事件处理顺序**：中断与 SubagentStop 同时发生时，先写入的真正终态基本获胜；没有平台事件时间、结果 ID 或冲突记录，无法区分迟到与真实先后。
4. **未映射成功中断无法记账**：原生工具可能成功，但治理状态没有任务可写；父任务只能依赖原生结果，SessionStart 和诊断无法展示该中断。
5. **缺少中断原因和审计字段**：当前没有 `interrupt_reason`、initiator、previous platform status、用户确认或关联决策；`last_assistant_message` 也不应被反向猜测为中断原因。
6. **中断终态没有结果文档**：`interrupted` 属于终态集合和裁剪范围，但不像成功的 SubagentStop 那样生成 `result_document`，后续统一终态 Schema 需要确认最小取消证据。
7. **插件不能验证主线程说明**：中断前用户可见说明由父 Agent 规则保证；增加 PreToolUse Hook 也无法读取 transcript 证明说明已经发送，不应重新引入无行为的空转 Hook。

### 5. 改进建议

1. 保留 `interrupt_agent` 原生通道和父 Agent 显式决策，不增加基于超时或错误文本的自动中断器。
2. 建立最小 interrupt attempt 记录，包含稳定 attempt ID、任务 ID、target、tool use ID、请求/完成时间、结果分类和可选结构化原因；不要保存完整敏感响应。
3. 为原生中断响应建立适配器，明确区分成功返回的 previous status、明确失败和 outcome unknown；未知结果应提示父 Agent 使用目标范围状态对账，而不是直接制造确定性终态。
4. 建立终态优先级和冲突记录：已确认 `complete`/`failed` 等业务结果不被迟到中断覆盖；成功中断先到时后续启动/恢复不得复活，但迟到业务结果是否作为补充证据应由终态功能决定。
5. 为 `platform_error`、`needs_decision` 的取消动作定义明确语义：成功中断表示父任务放弃继续恢复并关闭治理动作，不表示平台错误已经被修复。
6. 在结构化终态方案中为 interrupted/cancelled 定义最小结果对象，保存原因类别和关联 attempt，不要求从自由文本判断用户意图。
7. 真实平台验收应覆盖运行中中断、平台错误后中断、决策状态中断、明确失败、未知响应、未映射目标、迟到 SubagentStop 和 Stop 放行。

### 6. 本轮可局部直接实施的内容

- 新增 `INTERRUPTIBLE_STATUSES = ACTIVE_STATUSES | {"platform_error", "needs_decision"}`，让仍需父任务处理的错误/决策状态在原生中断成功后真正进入 `interrupted`。
- 保留 `complete` 等真正终态不被迟到中断覆盖，避免把已完成业务结果改写成取消。
- 新增 `test_successful_interrupt_closes_action_required_states`，先复现两个状态未闭环，再验证 `platform_error` 和 `needs_decision` 均能记录中断及 tool use ID。
- 新增 `test_successful_interrupt_does_not_overwrite_completed_task`，保护迟到中断不覆盖已经确认的完成状态。

这些改动只修正规则与运行状态机的不一致，没有增加自动中断、PreToolUse 阻断、中断原因推断或新的原生参数。

### 7. 必须留待最终统一方案的内容

- interrupt attempt ID、prepared 记录、Pre/Post 精确关联和未知结果状态。
- 中断、SubagentStop、list_agents、follow-up 和 SubagentStart 并发/迟到事件的终态优先级及冲突证据。
- 中断原因、发起者、用户决策和先前平台状态的最小安全记录。
- 未映射 Agent 成功中断后的诊断与任务引用恢复边界。
- `interrupted` 是否生成结构化结果文档，以及与后续终态 Schema 的职责交接。
- `platform_error`/`needs_decision` 被中断后对 SessionStart、SessionEnd、裁剪和跨版本状态兼容的影响。
- 真实 Codex `interrupt_agent` 响应 Schema、previous status 语义和平台资源终止保证。

### 8. 测试与证据

- 既有测试覆盖运行中任务成功中断后 Stop 放行，以及明确失败保持 `running`。
- `interrupt-v1.json` fixture 覆盖派发、映射、`status=running` 的原生先前状态响应、中断记账和 Stop；它直接调用 `handle()`，不是实际平台中断端到端证明。
- 本轮新增 action-required 状态中断和完成终态不覆盖测试；第六项 5 个定向测试全部通过。
- 完整回归更新为 132 项通过；`python3 -m py_compile scripts/subagent_governance.py`、Plugin validator、`git diff --check` 和 SG-F05 文档尾随空白检查均通过。测试总数包含并行任务同期新增的其他测试，本项新增 2 项。

## 十五、第七项：父任务 Stop 结束保护

### 1. 当前情况

- `hooks/hooks.json` 为根任务 `Stop` 注册统一运行时，timeout 为 10 秒，状态提示为“检查未完成的子 Agent”。该 Hook 只在父任务准备结束时检查治理状态，不执行等待、恢复、中断或重新派发。
- 原实现调用 `_active_records()`，只检查最近 12 小时的 `pending`、`dispatched`、`running` 和 `retry_required`。存在记录时第一次 Stop 返回 `decision=block`；若 `stop_hook_active` 已为真，则为避免 Stop Hook 递归而放行，并通过 `systemMessage` 保留同一提醒。
- 状态存储不可读时 Stop 按 fail-open 边界放行并告警，避免治理插件故障导致父任务无法结束；这也意味着状态真正丢失时插件无法继续提供未完成任务保护。
- `complete`、`failed`、`protocol_error`、`interrupted` 等真正终态不阻止父任务结束。`blocked` 和 `needs_decision` 也必须允许父任务结束当前回合，否则父 Agent 无法把阻塞事实或决策问题交给用户。
- 原实现把 `platform_error` 排除在 Stop 检查之外，父任务可能在尚未恢复、尚未请求用户决策时静默结束。本轮新增独立 `STOP_BLOCKING_STATUSES = ACTIVE_STATUSES | {"platform_error"}`，不再用“是否 active”同时表达“是否允许父任务结束”。
- `platform_error` 现在会触发一次 Stop 阻止，要求父 Agent等待、恢复或处理协议状态；进入 `needs_decision` 后 Stop 放行，让父 Agent 能向用户请求 provider、模型、稍后重试或取消等决策。
- 最近任务筛选现在使用 `updated_at`、`platform_checked_at` 和 `created_at` 中的最大有效值；刚被 `list_agents` 确认仍在运行的长任务不会仅因业务 `updated_at` 超过 12 小时而被 Stop 忽略。
- Stop 摘要最多展开 6 个任务；本轮对超出部分增加“另有 N 个”提示，避免父 Agent误以为只有已展示任务。

### 2. 当前 Stop 状态分类

| 状态 | 当前 Stop 行为 | 原因 |
| --- | --- | --- |
| `pending` / `dispatched` / `running` / `retry_required` | 第一次阻止 | Agent 工作尚未闭环 |
| `platform_error` | 第一次阻止 | 仍需恢复或转换为用户决策 |
| `needs_decision` | 放行 | 父任务必须停下来向用户提问 |
| `blocked` | 放行 | 父任务必须报告阻塞和恢复条件 |
| `complete` / `failed` / `protocol_error` / `interrupted` | 放行 | 当前执行已经形成终态 |

Stop 的“阻止一次”是父任务结束保护，不是强制调度器：插件无法保证父 Agent 收到阻止理由后一定调用 `wait_agent`、`followup_task` 或向用户提问。

### 3. 前后文交接

- 等待巡检和平台对账向 Stop 提供活跃状态、最近平台检查和 `platform_error`；Stop 只防止无处理地结束，不拥有后续动作选择。
- 有限恢复把首次错误转换为 `retry_required`，继续阻止父任务结束；恢复达到上限后进入 `needs_decision`，Stop 必须放行以完成用户交互。
- 中断成功后进入 `interrupted`，Stop 不再阻止；中断失败保持原状态并继续按该状态判断。
- SG-F03 的普通消息和恢复消息不决定 Stop；只有共享生命周期状态产生结束保护副作用。
- 下一项 SessionStart 应使用与 Stop 不完全相同的集合：会话恢复摘要需要展示 `platform_error` 和 `needs_decision`，但 Stop 不能阻止 `needs_decision` 的用户提问。
- SessionEnd 是否能在仍有 Stop 阻止状态时删除 session 状态，必须在会话清理项单独处理；Stop 本身不能阻止 Codex 平台直接触发 SessionEnd。
- 后续终态功能负责确认 `blocked`、`needs_decision` 和真正结果的结构化证据；Stop 不应解析父 Agent 最后一条自然语言来猜测是否已经正确报告。

### 4. 已确认的问题

1. **一次阻止不等于完成处理**：`stop_hook_active` 路径为防递归必须放行，因此规则仍依赖父 Agent读取提醒并执行等待、恢复或用户交互。
2. **12 小时仍是任意策略值**：本轮修复了近期平台检查未计入的问题，但完全没有更新时间或平台检查超过 12 小时的活跃/平台错误任务仍会被忽略；当前没有显式 stale 状态或用户确认清理流程。
3. **状态不可用时只能放行**：符合兼容优先原则，却可能让真实运行中的子任务失去父任务保护；告警是否能在会话结束前被用户看到依赖 Codex Hook 展示。
4. **Stop 不验证父任务下一步**：阻止理由只能提示“等待或处理协议状态”，不能证明父 Agent 已正确调用原生工具，也不能从 `last_assistant_message` 可靠判断是否已向用户说明。
5. **状态分类仍是补丁式集合**：`STOP_BLOCKING_STATUSES` 解决当前行为，但 `platform_error` 仍同时位于 `TERMINAL_STATUSES`；最终需要执行状态、治理动作和业务终态分层，而不是长期维护多个互相重叠集合。
6. **共享运行边界文档已经滞后**：第七项实施后 `runtime-boundaries.md` 仍写着 Stop 和 SessionStart 都忽略 `platform_error`；第八项随后也修复了 SessionStart，因此当前两项都与该参考文档不一致。受本任务只写 SG-F05 文档的边界限制，最终合并/实施必须同步修正。
7. **摘要没有稳定优先级**：当前按任务字典顺序选前 6 个，没有优先展示平台错误、最长等待或最近检查任务；虽然会报告遗漏数量，但重要任务可能未在首屏展开。

### 5. 改进建议

1. 将 Stop 的输入定义为明确 `parent_exit_blocking` 语义，不再从通用 ACTIVE/TERMINAL 集合推导；该字段或纯函数应由统一状态模型生成。
2. 保留 `needs_decision`、`blocked` 的放行行为，并确保父任务用户可见输出包含结构化问题、选项、阻塞条件或下一步；不要用 Stop 无限阻止来代替用户交互。
3. 将 12 小时改成显式 stale 策略：到期后先形成可诊断 stale/action-required 状态，而不是直接从结束保护集合消失；是否清理应由用户决策或 Session 生命周期规则决定。
4. Stop 摘要应按风险和新鲜度排序，优先 `platform_error`、`retry_required`、`running`，并继续保持总长度限制和遗漏计数。
5. 真实平台验收应覆盖第一次 block、`stop_hook_active` 防递归放行、父 Agent继续等待、平台错误恢复、用户决策提问和状态不可用告警展示。
6. 不在 Stop Hook 内调用 `wait_agent` 或 `followup_task`；它只提供结束门禁和明确理由，避免形成第二套编排器。

### 6. 本轮可局部直接实施的内容

- 新增 `STOP_BLOCKING_STATUSES`，让近期 `platform_error` 与活跃任务一起触发 Stop 保护，同时保持 `needs_decision` 和 `blocked` 可以正常向用户报告。
- 新增 `_activity_timestamp()`，使用 `updated_at`、`platform_checked_at`、`created_at` 中的最大有效值判断近期活动。
- 抽出 `_recent_records()`，让 `_active_records()` 和 Stop 的阻止集合不再被迫共用同一状态含义；SessionStart 当前仍调用 `_active_records()`。
- Stop 理由改为“运行中或待恢复”，不再把代码中已列为 terminal 的 `platform_error` 描述成简单“未终态”。
- 多任务摘要增加遗漏数量。
- 更新 `test_list_agents_reconciles_stream_error`，把原来证明缺口的 Stop 放行断言改为平台错误会阻止一次。
- 新增 `test_root_stop_allows_needs_decision_for_user_response`、`test_root_stop_uses_recent_platform_check_for_long_running_task` 和 `test_root_stop_reports_omitted_blocking_tasks`。

### 7. 必须留待最终统一方案的内容

- 执行状态、action-required、parent-exit-blocking 和业务终态的正式分层。
- 超过 12 小时的运行中、平台错误和恢复任务如何进入 stale、告警、用户决策或清理。
- Stop 摘要优先级、稳定排序、长度预算和多个并行 Agent 的展示策略。
- Stop block 后父 Agent 实际等待/恢复/提问的真实平台行为，以及 `stop_hook_active` 的准确事件序列。
- 状态不可用时的用户可见告警保证和后续 SessionStart 恢复补偿。
- `runtime-boundaries.md`、Skill、最小全局入口、测试和最终状态模型的同步更新。
- Stop 与 SessionEnd 并发时的条件保留、删除后晚到事件和 session tombstone 协议。

### 8. 测试与证据

- 既有测试覆盖活跃任务第一次 Stop 阻止、递归路径放行和成功中断后 Stop 放行。
- 本轮定向测试覆盖平台错误阻止、`needs_decision` 放行、近期平台检查保持长任务保护、多任务遗漏提示和中断交界；第七项 7 个定向测试全部通过。
- 单元测试直接调用 `handle()`，不能证明 Codex 会怎样展示 block reason、何时设置 `stop_hook_active`，或父 Agent是否会按提示继续等待。
- 完整回归更新为 135 项通过；`python3 -m py_compile scripts/subagent_governance.py`、Plugin validator、`git diff --check` 和 SG-F05 文档尾随空白检查均通过。本项新增 3 项测试并修改 1 项原本固化 Stop 缺口的断言。

## 十六、第八项：SessionStart 与 compact/resume 会话恢复摘要

### 1. 当前情况

- `hooks/hooks.json` 在 `startup`、`resume`、`clear` 和 `compact` 四类 SessionStart 来源上运行统一 handler，timeout 为 10 秒，平台 `additionalContextLimit` 为 1800。
- SessionStart 从当前 `session_id` 的 StateStore 读取近期任务并生成固定 `additionalContext`；它不会调用 `wait_agent`、`list_agents`、`followup_task`，也不会自行创建、恢复或唤醒 Agent。
- 摘要按任务输出治理任务 ID、治理等级、状态、目标、完成条件、恢复对象和机械生成的下一步；各业务字段限制为 96 字符，总上下文限制为 1800 字符，最多尝试展开 8 条，超出时明确报告未展开数量。
- 原实现只调用 `_active_records()`，因此 `platform_error` 和 `needs_decision` 在 compact/resume 后完全不提示。父 Agent可能误以为没有待恢复或待决策任务并重复派发。
- 本轮新增 `SESSION_RESTORABLE_STATUSES = ACTIVE_STATUSES | {"platform_error", "needs_decision"}`，SessionStart 不再与 Stop 共用同一状态集合：`needs_decision` 不阻止父任务结束，但必须在新回合恢复决策请求。
- 恢复摘要按状态优先级排序：`platform_error`、`needs_decision`、`retry_required`、`running`、`dispatched`、`pending`；同状态按最近活动时间和任务 ID 稳定排序，避免普通 running 任务把更紧急的平台错误挤出摘要。
- 最近活动时间使用 `updated_at`、`platform_checked_at`、`created_at` 的最大有效值；刚被平台确认仍运行的长任务可以进入 SessionStart 摘要。
- `complete`、`failed`、`protocol_error`、`interrupted` 和 `blocked` 当前不进入会话恢复摘要。它们属于已形成结果或已停止执行的状态，是否需要历史结果回顾归后续终态/诊断功能，不由运行恢复摘要承担。

### 2. 状态对应的固定下一步

| 状态 | SessionStart 摘要中的机械提示 |
| --- | --- |
| `platform_error` | 对账后恢复同一 Agent；达到上限时请求用户决策 |
| `needs_decision` | 恢复已有决策请求；不要自动 follow-up |
| `retry_required` | 等待同一 Agent 再次启动或重新对账 |
| `running` | 等待原 Agent并按规则巡检 |
| `dispatched` | 等待 Agent 身份或启动确认 |
| `pending` | 核对派发结果；不要重复创建任务 |

这些提示只根据状态生成机械下一步，不创作用户业务问题、provider 选择、checkpoint 或恢复内容。

### 3. 当前恢复链路

```text
startup / resume / clear / compact
  → 按 session_id 读取 StateStore
  → 选择近期可恢复或待决策任务
  → 按状态优先级和最近活动排序
  → 生成最多 1800 字符的 additionalContext
  → Codex 平台把上下文交给父 Agent
  → 父 Agent按状态显式等待、对账、恢复或继续用户决策
```

Hook 只生成摘要；“上下文被平台实际注入”“父 Agent看到后按规则行动”和“原 Agent被唤醒”仍分别依赖 Codex Hook 平台、父 Agent执行和原生工具。

### 4. 前后文交接

- StateStore 提供任务目标、完成条件、Agent ID/canonical path、状态和时间字段；SessionStart 不重新解析原派发正文或 transcript。
- Stop 与 SessionStart 使用不同集合：Stop 阻止近期活跃任务和 `platform_error`，但放行 `needs_decision`；SessionStart 同时恢复 `platform_error` 和 `needs_decision`。
- 平台对账提供 `platform_checked_at` 和 `platform_error`；有限恢复提供 `retry_required` 和恢复上限决策；SessionStart 只展示这些状态，不执行转换。
- SG-F03 负责真正的 follow-up 恢复消息；摘要只告诉父 Agent下一步类型，不生成通信业务字段或声称消息已发送。
- 中断与真正终态不恢复，避免 compact/resume 后复活旧任务；如果用户需要重新执行，应建立带原任务引用的新执行身份。
- 第九项 SessionEnd 已作为相邻生命周期边界审查：当前会条件保留 SessionStart 可恢复状态，不再无条件清空输入；正式归档和迟到事件协议仍待统一。
- SG-F04 需要保证 N/N-1 代码都能读取同一状态格式；SessionStart 摘要字段或状态集合变化不能由缓存切换自行推断。

### 5. 已确认的问题

1. **12 小时截止仍会丢失长时间恢复线索**：有近期平台检查的长任务已经修复，但完全没有新事件超过 12 小时的 active、`platform_error` 或 `needs_decision` 仍不会显示；当前没有 stale 分组。
2. **决策上下文不完整**：`needs_decision` 只保存 `decision_reason` 等有限状态，没有结构化问题、选项、推荐和用户已有选择；摘要只能提示恢复决策请求，不能重建具体问题。
3. **恢复 checkpoint 不完整**：摘要保存目标和完成条件，但没有已完成步骤、当前文件/测试、继续位置或不得重复动作；Agent 无法继续时仍缺少可靠重建材料。
4. **摘要有界必然遗漏**：最多 8 条且受 1800 字符限制，虽然会报告遗漏数量，但父 Agent没有由摘要直接展开其余任务的结构化工具交接。
5. **四种 source 使用同一策略**：startup、resume、clear、compact 没有区分；用户主动 clear 与系统 compact 是否应恢复完全相同内容尚无真实产品语义证据。
6. **字符限制不等于平台 token 限制**：运行时按字符截断，Hook 配置的 `additionalContextLimit` 由平台处理；多 Hook 叠加、中文 token 和 spill 行为没有端到端证明。
7. **状态不可用只能告警放行**：损坏隔离后摘要可能为空，用户只能看到 degraded 告警；插件不能从 transcript 或平台内部记录重建丢失状态。
8. **共享文档已滞后**：主盘点文档和 `runtime-boundaries.md` 仍记录 SessionStart 忽略 `platform_error`；SG-F06 最新文档已经对齐本轮实现。SG-F05 只登记冲突，最终合并/实施再更新共享结论。

### 6. 改进建议

1. 定义正式 `session_restore_required` 语义，与 `parent_exit_blocking` 分离；状态模型直接产出是否进入摘要和下一步类型。
2. 将超过近期窗口但仍未解决的任务放入有界 stale 摘要，而不是静默忽略；由父 Agent或用户决定重新对账、关闭或归档。
3. 为 `needs_decision` 保存结构化 decision request，包括问题、选项、推荐、创建时间和用户选择状态，使 compact/resume 可以真正恢复决策。
4. 为恢复失败或 Agent 无法继续的任务保存最小 checkpoint；SessionStart 只展示摘要和引用，不把完整敏感工作内容倾倒进 additionalContext。
5. 提供按 session/task ID 读取其余遗漏任务的只读诊断入口，避免通过扩大固定摘要解决所有容量问题。
6. 根据真实 Codex 语义确认 startup、resume、clear、compact 是否需要不同策略；在此之前保持统一、可预测行为。
7. 真实验收必须确认 additionalContext 实际注入、边界截断、中文内容、多个任务优先级和父 Agent不重复派发。

### 7. 本轮可局部直接实施的内容

- 新增 `SESSION_RESTORABLE_STATUSES`，恢复近期 `platform_error` 和 `needs_decision`。
- 新增 `_session_restore_records()`，按 action-required 优先级、最近活动时间和任务 ID 稳定排序。
- 新增 `_session_next_action()`，为六类可恢复状态生成不同的机械下一步。
- `_session_summary_line()` 增加下一步字段，footer 改为按状态等待、恢复或继续决策，不再对所有任务笼统要求恢复。
- 遗漏提示从“活跃任务”改成“待处理任务”，与新增 action-required 状态一致。
- 新增 `test_session_start_restores_action_required_states` 和 `test_session_start_prioritizes_action_required_over_running_tasks`，并更新既有 footer/遗漏提示断言。

### 8. 必须留待最终统一方案的内容

- `session_restore_required`、action-required、parent-exit-blocking 和业务终态的统一状态模型。
- 超过 12 小时的 stale 任务恢复、归档和用户决策策略。
- decision request、checkpoint、恢复 attempt 和任务身份的结构化引用。
- startup、resume、clear、compact 的真实语义差异及是否需要分场景摘要。
- 摘要遗漏任务的按需展开接口、排序优先级和容量预算。
- Codex additionalContext 的真实注入、token/spill、多 Hook 叠加和新任务唤醒验收。
- 主盘点文档、`runtime-boundaries.md`、Skill、最小全局入口和最终实现的一致性更新。
- SessionEnd 删除与 SessionStart 恢复之间的数据存续协议。

### 9. 测试与证据

- 既有测试覆盖 active 摘要、目标/完成条件、8 条限制、遗漏提示、1800 字符边界、固定首尾和坏记录跳过。
- 本轮新增 action-required 恢复和优先级测试；第八项 7 个定向测试全部通过。
- 单元测试只证明 handler 输出，不能证明 Codex 平台一定注入完整 additionalContext、父 Agent执行正确下一步或原 Agent被唤醒。
- 完整回归执行 138 项，其中 136 项通过，2 项失败：`test_published_rules_match_runtime_governance_contract` 和 `test_plugin_metadata_matches_skill_entrypoint`。两项都源于并行任务刚改写 `skills/subagent-governance/SKILL.md` 后旧文案断言尚未同步，与本项 SessionStart 修改无关；本任务不越权修改其他功能的 Skill 或测试。第八项 7 个定向测试、`python3 -m py_compile scripts/subagent_governance.py`、Plugin validator、`git diff --check` 和 SG-F05 文档尾随空白检查均通过。本项新增 2 项测试。

## 十七、第九项：SessionEnd 状态清理与恢复线索保留

### 1. 当前情况

- `hooks/hooks.json` 只为 `reason=other` 注册 SessionEnd handler，timeout 为 3 秒，状态提示为“清理子 Agent 治理状态”；仓库没有真实平台证据说明 `other` 覆盖关闭、归档、退出、崩溃或其他哪些会话结束场景。
- SessionEnd 是主任务会话事件，不是子 Agent 生命周期终止信号。它不会调用 `interrupt_agent`、不会等待子 Agent、不会改变 Agent 平台状态，也不能证明仍运行的子 Agent 已经停止。
- 原实现不读取任务状态，直接执行 `store.delete(session_id)`。因此 `pending`、`dispatched`、`running`、`retry_required`、`platform_error` 和 `needs_decision` 都会连同任务—Agent 映射、恢复次数、平台错误摘要和决策原因一起删除。
- 删除后同一 `session_id` 的 SessionStart 只能读到空状态，无法提示等待、恢复或继续用户决策；父 Agent可能重复派发，或者把仍在平台运行的 Agent 当成无治理任务。
- `StateStore.delete()` 使用与更新相同的 session `.lock` 文件锁住 JSON 删除，但保留锁文件。保留锁文件避免并发进程因删除并重建不同 inode 而使用不同锁；当前没有安全锁文件回收协议。
- 单纯在 handler 中先 `read()`、再根据结果调用 `delete()` 仍不安全：两个操作之间如果出现晚到的 PostToolUse、SubagentStart 或其他状态更新，新写入记录可能被后续删除。

### 2. 本轮实施后的状态链

本轮新增独立的 `SESSION_END_PRESERVED_STATUSES`，当前成员与 SessionStart 可恢复集合相同，但保持独立策略名称：

```text
pending / dispatched / running / retry_required
platform_error / needs_decision
```

新的清理链路为：

```text
SessionEnd(reason=other)
  → 获取当前 session 的同一把文件锁
  → 在锁内读取并检查全部任务，不使用 12 小时摘要窗口
  ├─ 存在上述任一状态
  │    → 保留整个 session JSON 和 Agent 映射
  │    → 返回有界任务摘要，说明 SessionEnd 不会终止 Agent
  │    → 未来同 session 的 SessionStart 可恢复等待/恢复/决策提示
  └─ 不存在上述状态
       → 删除 session JSON
       → 保留 .lock 文件
```

- 本轮新增 `StateStore.delete_if()`，把“检查是否允许删除”和“实际删除”放在同一锁临界区，消除 handler 层先读后删的竞态窗口；原 `delete()` 复用该原子入口保持既有无条件删除能力。
- 保留判断扫描全部记录，不复用 `_recent_records()` 的 12 小时窗口。即使运行任务、平台错误或决策请求超过 12 小时未更新，也不能只因摘要策略过期而在 SessionEnd 被删除。
- 全部任务已进入 `complete`、`blocked`、`protocol_error`、`failed` 或 `interrupted` 等当前不可恢复状态时，SessionEnd 仍删除 session JSON，保持既有成功生命周期 fixture 的清理行为。
- 状态存储不可用或原子清理失败时继续 fail-open，返回 `continue=true` 和明确告警；插件不会把清理故障扩大成 Codex 会话无法结束。

### 3. 与前后文的交接

- Stop 负责在父 Agent主动结束回复时阻止近期 active 和 `platform_error` 被无处理地放弃，但 Stop 不能阻止 Codex 随后直接触发 SessionEnd；因此 SessionEnd 必须独立保护所有可恢复记录，而且不能受 Stop 的 12 小时窗口限制。
- SessionStart 和 SessionEnd 当前使用成员相同但职责独立的集合：前者决定恢复摘要展示，后者决定状态文件能否删除。后续若两者语义分化，必须显式调整并增加状态矩阵测试，不能依赖同一个集合别名静默联动。
- SG-F03 提供真正的 follow-up 恢复调用和通信内容；SessionEnd 只保留其所需的任务 ID、Agent 映射和恢复次数，不生成恢复消息，也不声称 Agent 已被唤醒。
- SG-F06 负责 `blocked`、`protocol_error`、业务 `needs_decision` 和其他终态结果是否需要独立归档。SG-F05 本轮不把所有业务结果永久保存在 session 运行状态中；当前 `needs_decision` 被保留是因为 SessionStart 已将其作为待继续用户决策的恢复状态。
- SG-F04 需要保证 N/N-1 运行时代码都理解条件删除行为和状态格式。旧缓存若仍执行无条件 SessionEnd 删除，仍可能破坏新版所需的恢复线索；这属于跨版本状态兼容门禁，不由 SessionEnd 局部代码解决。
- `runtime-boundaries.md` 仍只笼统描述“SessionEnd 清理主任务治理状态”，没有说明当前条件保留，并保留 Stop/SessionStart 忽略 `platform_error` 的旧结论；SG-F06 最新第一项已经对齐 SG-F05 的 SessionStart/SessionEnd 行为。剩余共享文档漂移在最终合并时统一，不在本功能越权修改。

### 4. 已确认的问题

1. **SessionEnd 不等于任务已解决**：主会话关闭时子 Agent 仍可能在 Codex 平台运行、等待恢复或等待用户决策；原来的无条件删除会把会话事件误当成所有子任务终态。
2. **当前只保留运行恢复线索，不是正式归档**：保留整个 session JSON 可以避免即时丢失，但没有 `session_closed_at`、关闭原因、归档状态、恢复确认或用户清理决策。
3. **长期未解决记录可能无限保留**：本轮刻意不使用 12 小时窗口，因此 abandoned `pending`、失联 `running` 或长期 `needs_decision` 会持续占用状态容量；当前没有 stale/abandoned 分类和显式清理入口。
4. **迟到事件仍缺少 tombstone 和事件身份**：锁内条件删除保证并发更新不会夹在检查与删除之间；但成功删除以后到达的旧 PostToolUse、SubagentStart、SubagentStop 或 list_agents 事件仍可能重建空状态、无法解析任务，或因事件处理顺序产生不同结果。
5. **不可恢复终态直接删除仍依赖 SG-F06**：`blocked`、`protocol_error`、`failed` 和 `interrupted` 当前不阻止清理。它们是否需要历史结果、父任务待办或审计留存，必须由结构化终态和归档协议决定，不能在 SG-F05 中把临时运行状态当永久结果库。
6. **锁文件没有回收协议**：继续保留 `.lock` 是当前并发安全选择，但大量历史 session 会留下小锁文件；不能通过 SessionEnd 直接删除锁文件，否则可能造成锁 inode 分裂。
7. **真实 SessionEnd 输出不可见性未验证**：单元测试能证明 handler 返回告警，不能证明 Codex 在会话结束阶段一定向用户展示 `systemMessage`，也不能证明同一 session 之后必然会触发 resume SessionStart。
8. **reason 语义不完整**：Hook 只匹配 `other`，没有覆盖或区分 compact、clear、用户删除、正常关闭、崩溃等产品场景；compact/clear 当前走 SessionStart，不等于已经证明 SessionEnd 永不同时发生。

### 5. 改进建议

1. 建立明确的 session 生命周期字段，至少区分 `open`、`closed_with_pending_work`、`resolved`、`archived` 和 `deleted`；SessionEnd 只记录会话关闭，不直接等同任务解决。
2. 由统一状态模型产出 `session_preservation_required`，与 `session_restore_required`、`parent_exit_blocking` 和业务结果归档分别定义；当前多个集合只是过渡性实现。
3. 为长期无事件任务建立 stale 分组和用户可见清理决策，不能在“永久保留”和“12 小时后静默删除”之间二选一。
4. 为迟到事件保存 session/task tombstone、事件 ID或最小关闭版本，明确删除后哪些事件允许重建、哪些只记录冲突、哪些必须忽略。
5. 由 SG-F06 建立独立结果归档或稳定结果引用后，再决定 `complete`、`blocked`、`protocol_error`、`failed` 和 `interrupted` 的 session 运行状态何时可删除。
6. 定义状态 JSON、归档和 `.lock` 文件各自的保留期与安全回收协议；锁文件清理必须证明不存在仍持有旧 inode 的进程。
7. 用真实 Codex 场景验收 SessionEnd reason、告警展示、关闭后 Agent 是否继续运行、同 session 恢复、跨进程晚到事件和旧缓存行为。

### 6. 本轮可局部直接实施的内容

- 新增 `SESSION_END_PRESERVED_STATUSES`，条件保留 active、`platform_error` 和 `needs_decision`。
- 新增 `_session_end_preserved_records()`，检查全部未解决记录并稳定排序，不受 12 小时摘要窗口影响。
- 新增 `StateStore.delete_if()` 与 `UnavailableStateStore.delete_if()`，在同一 session 锁内完成检查和删除；`delete()` 继续作为无条件兼容入口。
- `_handle_session_end()` 改为仅在没有可恢复/待决策任务时删除；保留时输出最多 6 条任务摘要和遗漏数量，明确 SessionEnd 不会终止 Agent。
- 新增运行中任务保留、全部解决后删除、超时及 action-required 状态保留、清理失败降级测试；成功生命周期 fixture 继续证明完整终态后仍会删除状态。

### 7. 必须留待最终统一方案的内容

- session closed、task resolved、result archived 和 state deleted 的正式状态与转换协议。
- active/action-required/stale/terminal/result-retention 的统一分类，以及 `blocked`、`protocol_error` 等状态是否需要恢复或归档。
- abandoned pending、长期 running、平台断流和长期用户决策的保留上限及显式清理入口。
- 删除后的 tombstone、晚到事件、重复 SessionEnd、多进程 Hook 和事件乱序幂等策略。
- `.lock` 文件回收、状态 JSON/结果归档分层和 4 MB 容量治理。
- SessionEnd reason 的真实产品语义、用户可见告警保证和同 session resume 行为。
- N/N-1 运行缓存并存时，旧版无条件删除与新版条件保留的状态兼容门禁。
- 主盘点、`runtime-boundaries.md`、Skill、最小全局入口、Hook 状态提示和最终实现的一致性更新。

### 8. 测试与证据

- 修复前新增测试稳定复现：运行中和 action-required 状态经过 SessionEnd 后文件被直接删除，handler 没有保留提示；全部解决后的既有删除路径仍通过。
- 本轮 5 项定向测试通过：运行中状态保留、全部解决后删除、超过 12 小时的 `running`/`platform_error`/`needs_decision` 保留、清理失败降级，以及完整成功生命周期 fixture 的最终删除。
- 测试证明 handler 和 StateStore 的条件删除语义；同锁临界区由代码路径确认。当前尚无受控多进程 SessionEnd/晚到事件竞争测试，也不能把直接调用 `handle()` 的 fixture 当作真实 Codex SessionEnd/resume 端到端证明。
- 最新完整回归共 142 项，全部通过；`python3 -m py_compile scripts/subagent_governance.py`、Plugin validator、`git diff --check` 和 SG-F05 文档尾随空白检查均通过。本项新增 4 项单元测试，并继续复用完整成功生命周期 fixture 验证全部解决后删除。

## 十八、SG-F05 最终收口

### 1. 最终名称、职责与拆分结论

- 最终编号和名称：**SG-F05 治理状态持久化、等待巡检与异常恢复**。
- 最终一句话职责：**保存治理任务、Agent 身份和运行健康状态，为父 Agent 的等待巡检、平台对账、有限恢复、中断保护和会话恢复提供共享状态底座。**
- 本功能保持为一个大功能，不拆成“状态存储”和“执行恢复”两个大功能。两者虽然可以在实现内部区分数据层、状态对账层和会话保护层，但任务—Agent 映射、恢复次数、平台错误、Stop、SessionStart/End 与并发锁共同修改同一记录；强行分成两个大功能会把状态枚举、版本、锁、裁剪和恢复资格变成双向依赖。
- 内部按三层理解：StateStore 和状态安全属于数据层；身份绑定、平台观察、中断和恢复次数属于生命周期状态层；父 Agent等待规则、Stop 与 SessionStart/End 属于编排交接和会话保护层。三层共享一个状态协议，但不意味着 Hook 自己执行等待或平台唤醒。

### 2. 九个功能点最终结论

| 功能点 | 最终结论 | 本轮直接完成 | 仍需统一设计 |
| --- | --- | --- | --- |
| 1. 治理状态持久化与状态模型 | 必须保留，是全部生命周期功能的数据底座 | 坏时间戳安全裁剪、按字典键裁剪 | 状态版本迁移、多维状态模型、容量与旧版本兼容 |
| 2. 任务—Agent 身份绑定与启动确认 | 必须保留，是通信、巡检、恢复和终态的共同身份入口 | SubagentStart 坏时间戳容错 | 稳定任务引用、响应适配器、取消名称猜测、`unmapped running` |
| 3. 父 Agent 等待与目标巡检 | 必须保留为父 Agent工作流，不属于 Hook 定时器 | 规则/Hook 边界回归测试 | 20 分钟策略、真实 wait/wake 验收、产品状态接口 |
| 4. 平台状态对账与错误分类 | 必须保留，只消费显式 `list_agents` 结果 | 错误摘要有界保存、普通状态不改生命周期 | 平台响应适配、普通状态容量、结构化错误码 |
| 5. 同 Agent 有限恢复与恢复上限 | 必须保留，防止无限恢复和重复派发 | 非法恢复次数安全降级 | attempt ID、并发幂等、checkpoint、二次错误自动决策时机 |
| 6. 主动中断与中断终态 | 必须保留为显式关闭执行的生命周期动作 | action-required 状态可中断、真正终态不覆盖 | 中断 attempt、原因/发起者、迟到事件和结构化结果 |
| 7. 父任务 Stop 结束保护 | 必须保留，但只提供一次机械保护 | `platform_error` 纳入保护、最近平台检查、遗漏计数 | stale 策略、真实 stop_hook 事件序列、状态不可用提示保证 |
| 8. SessionStart 与 compact/resume 恢复摘要 | 必须保留，是上下文压缩后避免重复派发的主要机械补偿 | 恢复 `platform_error`/`needs_decision`、优先级和下一步 | decision request、checkpoint、按需展开、source 差异、真实注入 |
| 9. SessionEnd 状态清理与恢复线索保留 | 必须保留，不能把主会话结束等同子任务解决 | 同锁条件删除、超时未解决任务保留、清理失败降级 | session 归档、tombstone、晚到事件、锁文件回收 |

没有需要删除或合并掉的整个功能点。可以删除的是后续目标主路径接管后的临时回退、文本特判和重复规则，不是上述九项职责本身。

### 3. 当前实际状态模型

| 语义集合 | 当前成员 | 当前用途 | 已确认冲突 |
| --- | --- | --- | --- |
| `ACTIVE_STATUSES` | `pending`、`dispatched`、`running`、`retry_required` | 身份解析、启动、Stop/会话集合的基础 | `dispatched` 当前没有写入者；`retry_required` 同时用于平台恢复和终态补充 |
| `RESOLVABLE_STATUSES` | active + `platform_error` | Agent ID/canonical path/task name 解析 | 把执行状态和通信可解析性混在同一集合 |
| `INTERRUPTIBLE_STATUSES` | active + `platform_error`、`needs_decision` | 成功 interrupt 后关闭仍需动作的任务 | 中断结果只有状态和 tool use ID |
| `STOP_BLOCKING_STATUSES` | active + `platform_error` | 阻止父任务无处理结束 | `needs_decision`、`blocked` 为便于向用户报告而放行 |
| `SESSION_RESTORABLE_STATUSES` | active + `platform_error`、`needs_decision` | SessionStart 恢复摘要 | 只显示 12 小时内记录，长期未解决任务仍可能不可见 |
| `SESSION_END_PRESERVED_STATUSES` | active + `platform_error`、`needs_decision` | SessionEnd 条件保留 | 不使用 12 小时窗口，可能长期保留 abandoned 记录 |
| `TERMINAL_STATUSES` | `complete`、`blocked`、`needs_decision`、`protocol_error`、`failed`、`interrupted`、`platform_error` | 裁剪和 SubagentStop 终态保护 | `platform_error`、`needs_decision` 仍需动作却被当作可裁剪终态 |

当前状态转换链为：

```text
spawn PreToolUse
  → pending
spawn PostToolUse
  ├─ 明确失败 → failed
  └─ 未明确失败 → running + 尝试绑定 Agent 身份
SubagentStart
  → 已映射或唯一未绑定 active 候选 → running

父 Agent显式 wait_agent
  → Codex 平台负责等待和 mailbox 唤醒
父 Agent显式 list_agents
  ├─ 普通状态 → 只更新 platform_checked_at/platform_status
  └─ 明确 errored → platform_error

platform_error 后成功 followup_task
  → recovery_count + 1 → retry_required
后续 SubagentStart
  → running
再次 list_agents errored
  → platform_error
父 Agent再次尝试恢复
  → PreToolUse 发现恢复上限 → needs_decision 并拒绝调用

成功 interrupt_agent
  → active/platform_error/needs_decision → interrupted
SubagentStop
  → SG-F06 当前文本路径产生 complete/blocked/needs_decision
  → 协议补充时进入 retry_required，达到上限进入 protocol_error

Stop
  → 只阻止或放行，不改变任务状态
SessionStart
  → 只注入恢复摘要，不调用 Agent 工具
SessionEnd
  → 有可恢复/待决策状态则保留；否则删除 session JSON
```

特别注意：第二次 `list_agents` 错误本身仍先写回 `platform_error`，只有父 Agent随后再次准备调用 `followup_task` 时，PreToolUse 才把记录转换成 `needs_decision`。README/Skill 中“再次错误时进入 needs_decision”的简写需要在最终统一时明确是规则动作还是已经发生的代码转换。

### 4. “沉睡—检查—唤醒”责任边界

| 责任方 | 真正负责的部分 | 明确不负责 |
| --- | --- | --- |
| 父 Agent + Skill | 保存目标 Agent 标识；显式调用 `wait_agent`；超时或明确断流后目标范围调用 `list_agents`；依据状态决定 follow-up、提问或继续等待 | 不能假设自然语言规则已经被自动执行 |
| Codex 原生工具 | `wait_agent` 的阻塞等待、`list_agents` 的平台查询、`followup_task`/`interrupt_agent` 的实际调用 | 不保证 provider 稳定、Hook 状态正确或业务任务完成 |
| Codex 平台 | mailbox 更新或用户输入使等待提前返回，调度原 Agent，再次触发可用生命周期事件 | 仓库没有证明所有断流、唤醒、迟到事件和 Hook 调用顺序 |
| Hook 运行时 | 记录已发生的 spawn、list、follow-up、interrupt、SubagentStart/Stop、Stop 和会话事件；维护状态与保护提示 | 没有后台线程、20 分钟定时器、自动 `wait_agent`、自动 `list_agents` 或 provider 修复能力 |
| StateStore | 保存任务、Agent 映射、恢复次数、平台摘要和会话恢复输入 | 不能从 transcript 或平台内部记录重建未写入/已损坏的完整上下文 |

因此现状是“父 Agent按 Skill 执行 + 原生工具/平台提供真实等待唤醒 + Hook 记录可观察事件”，不是“插件自行沉睡并定时唤醒主线程”。项目不应为此引入第二套 scheduler；目标是增强确定性引用、状态检查和真实平台验收。

### 5. 最终上下游交接

- SG-F01 提供任务契约、治理等级、模型/强度和上下文策略；SG-F05 从派发 Hook 接收任务身份并进入 `pending`，不重新生成业务契约。未来 PreparedContractStore 成功绑定后应把正式运行字段复制到 StateStore。
- SG-F02 提供七类 Hook 注册、统一 CLI 和事件路由；SG-F05 拥有其中 PostTool 生命周期分支、SubagentStart、Stop、SessionStart/End 的状态语义，不拥有 Manifest 或 trust。
- SG-F03 提供普通消息与恢复消息参数、原生 `followup_task` 调用及其通信身份；SG-F05提供恢复资格、次数、`platform_error → retry_required → running` 状态交接。
- SG-F04 提供发布、N/N-1 缓存、最小全局入口和真实生命周期 smoke 验收；SG-F05 输出状态版本/迁移门禁和待验收生命周期矩阵，不管理安装目录。
- SG-F06 提供业务终态结果、结构化结果、SubagentStop 机械验收和父任务闭环；SG-F05提供执行状态、Agent 映射、中断、会话存续和异常原因。`blocked`、结果归档和业务 `needs_decision` 的正式语义由两者共同使用但以 SG-F06 为主。

### 6. 最终文件覆盖

| 文件 | SG-F05 归属 | 覆盖结论 |
| --- | --- | --- |
| `scripts/subagent_governance.py` | 主要归属（共享大文件） | StateStore、状态常量、身份/平台生命周期、Stop 和 SessionStart/End 是核心；spawn/通信/SubagentStop 只登记交界 |
| `hooks/hooks.json` | SG-F02 主要，SG-F05 次要 | PostToolUse、SubagentStart、Stop、SessionStart、SessionEnd 提供接线；没有 `wait_agent` matcher |
| `skills/subagent-governance/SKILL.md` | 分区共享；等待/状态对账/恢复/中断主要归 SG-F05 | SG-F04 收敛全局资产后，完整父 Agent软指导以此为主要来源 |
| `skills/subagent-governance/references/runtime-boundaries.md` | SG-F05 主要内容，SG-F02 次要接入 | 原生工具、状态降级、等待、平台和会话边界；当前 Stop/SessionStart/SessionEnd 结论滞后 |
| `assets/agents-governance.md` | SG-F04 主要，SG-F05 次要 | 只保留按需加载 Skill 的最小入口，不再拥有完整等待恢复规则 |
| `AGENTS.md` | 项目治理目标次要关联 | 描述有序等待、有限恢复和失败兼容目标，不是运行时状态协议来源 |
| `README.md` | 次要关联 | 说明平台错误、恢复上限和能力边界；二次错误转换时机需与代码精确对齐 |
| `docs/optimization-plan.md` | 次要关联 | 记录目标状态机和验证方向，不是现状证据 |
| `docs/release-process.md` | SG-F04 主要，SG-F05 次要 | 真实生命周期 smoke 和 SessionEnd 证据要求消费 SG-F05 验收矩阵 |
| `schemas/task-contract-v1.schema.json` | SG-F01 主要，SG-F05 次要 | StateStore 当前混合保存契约字段；没有独立状态 Schema |
| `schemas/task-result-v1.schema.json` | SG-F06 主要，SG-F05 次要 | 终态状态与生命周期裁剪/会话策略交界 |
| `tests/test_governance.py` | 分区共享；SG-F05 相关区段主要归属 | 覆盖状态安全、映射、平台对账、恢复、中断、Stop 和会话生命周期 |
| `tests/test_concurrency.py` | SG-F05 主要，SG-F01 次要 | 仅证明并发派发记录不丢失；没有覆盖多 Hook、SessionEnd 或恢复并发 |
| `tests/test_hook_fixtures.py` | 分区共享 | 生命周期、平台错误、恢复上限和中断事件串属于 SG-F05 证据 |
| `tests/fixtures/lifecycle-v1.json` | SG-F05/SG-F06 共享 | SessionStart、SubagentStart/Stop、Stop、SessionEnd 成功链；不是平台端到端 |
| `tests/fixtures/interrupt-v1.json` | SG-F05 主要 | 中断回调和 Stop 放行链 |
| `tests/fixtures/agent-status-error-v1.json` | SG-F05 主要，SG-F03 次要 | `list_agents` errored 对账输入 |
| `tests/fixtures/recovery-limit-v1.json` | SG-F03/SG-F05 共享 | 平台错误、首次恢复、再次启动、二次错误和恢复上限 |
| `tests/fixtures/opaque-spawn-v1.json` | SG-F01/SG-F02 主要，SG-F05 次要 | 为映射与平台错误 fixture 准备任务，不是等待恢复核心 fixture |
| `tests/test_plugin_structure.py` | SG-F02/SG-F04 主要，SG-F05 次要 | 保护 Hook 事件、Skill 入口和最小全局资产，不证明运行状态机 |

其他发布脚本、安装检查、Marketplace 元数据、Skill UI 和发布工具测试均归 SG-F04；SG-F05 只消费版本兼容和真实 smoke 结论，不重复登记为本功能代码。

### 7. 核心代码区段覆盖

| 代码区段 | 归属和结论 |
| --- | --- |
| 常量与时间/路径辅助（约第 24-179 行） | 状态集合、保留期、容量、活动时间和私有数据根主要归 SG-F05；契约常量属共享交界 |
| `StateStore`/`UnavailableStateStore`（约第 180-385 行） | SG-F05 核心；锁、原子写、损坏隔离、裁剪、条件删除和 fail-open 状态入口 |
| `_handle_spawn()`（约第 602-659 行） | SG-F01 主要；向 StateStore 写 `pending` 是 SG-F05 下游交接 |
| `_handle_communication()`（约第 660-815 行） | SG-F03 主要；恢复次数合法性和 `needs_decision` 转换是 SG-F05 交界 |
| `_resolve_task_id()`、响应解析与 `_handle_post_tool()`（约第 816-1020 行） | 身份解析、spawn 结果、list 对账、follow-up 状态和 interrupt 主要由 SG-F05 按区段拥有；消息参数仍归 SG-F03 |
| `_assign_starting_agent()`、SubagentStart（约第 1021-1096 行） | SG-F05 核心；唯一候选回退是临时兼容机制 |
| `_handle_subagent_stop()`（约第 1142-1245 行） | SG-F06 主要；其读写 active、retry_required 和终态状态是 SG-F05 状态协议交界 |
| 最近记录、Stop、SessionStart/End（约第 1247-1438 行） | SG-F05 核心；分别实现近期保护、恢复摘要和条件清理 |
| `handle()` 事件路由（约第 1441-1470 行） | SG-F02 主要，SG-F05 消费对应事件分支 |
| `_diagnose()`（约第 1472-1496 行） | SG-F05 次要；提供 session/health/active 只读摘要，但 active 仍使用 12 小时集合 |

所有 SG-F05 核心代码区段均已获得功能归属；没有发现完全没有调用或测试价值、可以在本轮直接删除的核心函数。

### 8. 测试与 fixture 最终覆盖

- `tests/test_governance.py` 已覆盖状态目录/文件安全、损坏与非 UTF-8 隔离、写入降级、裁剪、坏时间戳、身份绑定、映射清理、普通/错误平台状态、错误摘要边界、恢复次数损坏、首次恢复、再次启动、恢复上限、中断成功/失败、Stop、SessionStart 和 SessionEnd。
- 本轮九项累计新增 17 项 SG-F05 定向单元测试，并调整了原本固化 Stop 平台错误缺口的断言；当前完整回归包含并行功能新增测试，因此总数不能全部归因于 SG-F05。
- `tests/test_concurrency.py` 只覆盖 32 个并发 spawn 更新同一 session 不丢记录；没有证明并发 follow-up、list、interrupt、SubagentStop、SessionEnd 或进程崩溃后的状态一致性。
- fixture 证明既定 payload 形状可以驱动内部状态链，但不经过真实 `wait_agent`、mailbox、Codex Hook trust、provider 流或产品调度；真实端到端证据由 SG-F04 发布验收矩阵承接。
- 仍缺少：受控多进程 SessionEnd/晚到事件、双恢复并发、list/follow-up 乱序、4 MB 活跃状态超限、旧版本迁移、真实 compact/resume、真实 wait/wake 和真实 provider 断流恢复。

### 9. 疑似无用、历史残留与保留判断

- `dispatched` 当前没有写入者，属于疑似未完成状态，不直接删除；它可能用于替代“派发回调成功但身份未确认”的 `unmapped running`。最终统一状态模型必须选择正式启用、改名或删除。
- `_active_records()` 当前主要由诊断输出使用，且与 Stop/SessionStart 已分开；它不是死代码，但名称容易让人误以为是所有生命周期的统一活跃定义。
- session `.lock` 文件在 JSON 删除后仍保留不是遗漏清理，而是避免并发进程锁定不同 inode 的安全选择；只有建立可证明安全的回收协议后才能删除。
- 已删除的 `tests/fixtures/provider-protocol-error-v1.json` 对应已取消的 provider 文本特判。当前代码、Skill 和 README 使用统一有界恢复，该 fixture 不应恢复；若未来平台提供结构化不可恢复错误码，应新增结构化 fixture，而不是复活文本匹配。
- 已删除的 `compatibility.md` 已由 `runtime-boundaries.md` 替代；生命周期能力边界仍有用途，问题是内容滞后而不是文件多余。
- `opaque-spawn-v1.json` 不是 SG-F05 核心 fixture，但为真实形态的身份绑定、平台对账和恢复链提供上游准备，不应仅因主要归属在 SG-F01/SG-F02 而删除。
- 详细等待规则从 `assets/agents-governance.md` 删除并迁入 Skill 是正确收敛，不应再复制回全局资产；当前打开任务可能继续持有旧规则快照，属于发布/会话版本边界。

### 10. 跨功能冲突与最终合并事项

1. 主盘点文档仍只把 SG-F01 至 SG-F03 标记为已完成，并保留 Stop/SessionStart 不提示 `platform_error`、SessionEnd 未闭环等旧事实；最终合并必须用 SG-F05 最新结论替换，不能并列保留矛盾版本。
2. `runtime-boundaries.md` 仍声称 Stop/SessionStart 忽略 `platform_error`，也没有说明 SessionEnd 条件保留；这是当前最明确的共享参考漂移。
3. SG-F04 已把全局资产改成最小 Skill 入口；SG-F05 历史章节中“规则资产拥有完整等待规则”的描述只代表盘点时快照，最终归属以本收口节为准。
4. 当前开发 Skill/代码不解析 provider 文本，但已打开任务或尚未发布的全局规则快照可能仍含 `provider_protocol_incompatible` 特判；目标版本发布和新任务 smoke 必须验证语义来源已经统一。
5. README/Skill 把“恢复后再次错误”简写成进入 `needs_decision`，而代码在再次 list 对账后先写 `platform_error`，直到下一次 follow-up PreToolUse 才转换；最终方案需决定转换应发生在对账时还是恢复尝试时。
6. SG-F06 已正确记录 `platform_error`/`needs_decision` 的最新 SessionStart/End 行为，但它计划重构业务终态和结果归档；SG-F05 的会话删除、裁剪和 action-required 集合必须与该方案原子切换。
7. SG-F04 的 N/N-1 缓存保护只保证代码目录存在，尚未证明旧版和新版能安全读写同一 StateStore；状态版本迁移或不可回退时必须成为发布门禁。
8. SG-F01/SG-F03 计划引入 PreparedContract/PreparedCommunication 和稳定任务引用；完成后应删除 SG-F05 的唯一 task name、唯一未绑定候选等猜测回退，不能长期双轨。
9. SG-F06 最新第 4 项确认 SubagentStop 存在“先读状态、后单独 update”的竞态；完成、重试或 `protocol_error` 回调没有在锁内重新核对 Agent 映射和预期旧状态，可能覆盖中间到达的 `platform_error`、`interrupted` 或其他终态。该修补以 SG-F06 机械验收为主要归属，但需要复用 SG-F05 的原子状态更新边界。

### 11. 修改方案输入

| 编号 | 已确认问题 | 目标状态 | 优先级 | 主要影响 |
| --- | --- | --- | --- | --- |
| `SG-F05-PLAN-01` | 单一 `status` 同时表达执行、平台、业务结果和父任务动作 | 建立执行状态、平台观察、业务结果、父任务动作和会话保留的分层模型；所有集合由同一语义源生成 | 高 | SG-F05、SG-F06、Schema、Skill、测试 |
| `SG-F05-PLAN-02` | `STATE_VERSION=2` 无迁移，目录名仍为 `state-v1`，N/N-1 可并存 | 定义迁移、隔离、拒绝和不可回退门禁；旧版不能静默覆盖新版状态 | 高 | StateStore、SG-F04 发布门禁、诊断 |
| `SG-F05-PLAN-03` | 身份和事件依赖 Agent ID、canonical path、task name、tool use ID 回退 | 使用稳定任务引用、明确响应适配器和 spawn/communication/recovery/interrupt attempt ID；删除名称猜测 | 高 | SG-F01、SG-F03、SG-F05、fixture |
| `SG-F05-PLAN-04` | 平台恢复没有 in-flight/attempt 幂等，并发调用可能双恢复 | 原子认领一次恢复，区分请求成功、Agent 再次启动和业务完成；二次错误转换时机唯一 | 高 | 通信、PostTool、SubagentStart、状态测试 |
| `SG-F05-PLAN-05` | SessionStart 12 小时窗口、SessionEnd 无限保留和终态裁剪互相矛盾 | 建立 stale、closed、archived、deleted、tombstone 与显式清理协议，保留最小 checkpoint/decision request | 高 | Stop、SessionStart/End、StateStore、SG-F06 |
| `SG-F05-PLAN-06` | 平台响应使用递归字段搜寻，状态摘要仍可能保存未知大对象 | 建立支持的 Codex 响应适配器、字段/大小边界、unknown 降级和脱敏错误摘要 | 中 | PostTool、身份映射、list/interrupt 测试 |
| `SG-F05-PLAN-07` | 并发只证明 spawn 不丢记录；SubagentStop 等路径存在读—写竞态；活跃状态无数量/寿命上限，锁文件无回收协议 | 增加锁内 compare-and-set、多 Hook 竞争、崩溃、容量和回收测试；定义活跃容量及安全锁生命周期 | 高 | StateStore、SG-F06 SubagentStop、并发测试、诊断 |
| `SG-F05-PLAN-08` | 沉睡—检查—唤醒依赖父 Agent和 Codex 平台，仓库测试不能证明真实行为 | 在目标发布后执行真实 wait/list/follow-up/Stop/SessionStart/End smoke，按 `passed/failed/not_checked` 记录 | 高 | SG-F04 验收、Skill、真实新任务 |
| `SG-F05-PLAN-09` | Skill、最小全局入口、README、运行边界和已打开任务快照存在版本漂移 | 以 Skill/结构化语义源为完整软指导，最小入口只负责加载；发布后验证新任务并明确旧任务兼容窗口 | 中 | SG-F04、文档、Skill、运行缓存 |

这些是后续统一修改方案的输入，不代表本盘点任务已经授权实施状态迁移、发布、真实 Agent smoke 或外部环境写入。

### 12. 完成判定

- 最终名称、一句话职责、九个功能点、状态模型、完整状态链和责任边界已经确认。
- StateStore 安全、身份/启动、等待/对账、有限恢复、中断、Stop、SessionStart 和 SessionEnd 均已逐项记录当前事实、直接修补和统一方案输入。
- 主线程沉睡—检查—唤醒已明确分成父 Agent规则、Codex 原生工具、平台调度和 Hook 状态记录，不再把指导规则描述成插件定时器。
- 相关文件、核心代码区段、测试、fixture、疑似无用内容、历史删除项和跨功能冲突已经覆盖。
- 本功能只写 SG-F05 独立文档；主盘点、SG-F04、SG-F06 和共享运行边界的剩余更新留给最终合并，不在本任务越权修改。
- 本轮盘点可以标记为 **已完成**；真实 Codex wait/wake、Hook trust、provider 恢复和跨版本状态兼容仍是后续实施/发布验收，不是把盘点继续保持为“进行中”的理由。
- 收口时最新完整回归共 146 项，全部通过；四个项目 Python 脚本编译、全部现存 fixture JSON、Plugin validator、Skill validator、`git diff --check` 和 SG-F05 文档尾随空白检查均通过。
