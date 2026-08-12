# Subagent Governance 项目功能盘点总文档

## 一、文档状态与使用规则

- 盘点状态：**全部完成，WP-01～WP-08 本地实施已收口**。
- 盘点完成日期：2026-08-11；WP-08 当前实现回填：2026-08-12。
- 本文是后续生成项目修改方案的唯一主盘点入口。
- 改造准备度：**可以据此生成并执行分阶段改造方案**；当前没有待用户选择的设计问题。不得把全文理解为一次性大改授权，实施时仍需按第十八节的依赖顺序拆分、验证和原子替换旧路径。
- 本文合并以下盘点材料：
  1. 原主盘点中的 SG-F01～SG-F03。
  2. `docs/function-inventory/SG-F04-install-release-cache.md`。
  3. `docs/function-inventory/SG-F05-lifecycle-wait-recovery.md`。
  4. `docs/function-inventory/SG-F06-terminal-result-acceptance.md`。
  5. `docs/function-inventory/SG-F07-runtime-diagnostics-observability.md`。
  6. `docs/function-inventory/SG-F08-multi-agent-coordination.md`。
- 五份独立盘点文档继续保留为过程证据和细节档案，但不再作为最终方案的并列规范来源；发生冲突时以本文为准。
- 本文中的“当前实现”表示盘点时已经从代码、测试或环境中确认的事实；“目标结论”表示后续修改方案应遵循的方向；“待验证”表示仓库测试无法替代真实 Codex 平台证据。
- 删除裁决具有级联效力：某个大功能、存储层、状态分支或协议概念一旦明确删除，其专属字段、校验、改造点、测试、诊断、发布门禁和验证矩阵必须同步删除；只有被明确重新归属到其他保留功能的内容才能继续存在。不得一处声明删除父项，另一处仍要求实现其子项。
- 各盘点文档记录的历史测试数量来自不同并行时点，不作为协议事实。后续只记录实际执行的验证命令和当次结果。
- 后续改造的推荐读取顺序：先读第十八节的执行基线，再读第四节的跨功能裁决，随后按所实施的 SG-F01～SG-F08 章节查细节；第十三节用于删除边界，第十五至十七节用于文件覆盖和验收证据。过程盘点文档只在需要追溯证据时读取。

## 二、最终大功能清单

| 编号 | 最终名称 | 核心作用 | 性质 | 最终状态 |
| --- | --- | --- | --- | --- |
| SG-F01 | 治理等级选择与任务契约 | 为一次原生子 Agent 派发确定治理强度，生成完整、稳定、可执行的任务契约 | 核心 | 已完成盘点 |
| SG-F02 | 插件发现、Hook 注册与运行时接入 | 让 Codex 正确发现插件和 Skill，并把七类 Hook 事件接入统一运行时 | 支撑 | 已完成盘点 |
| SG-F03 | 子 Agent 业务通信、恢复指令与任务关联 | 规范父 Agent 向既有子 Agent 发送普通消息或恢复指令，并关联原任务 | 核心 | 已完成盘点 |
| SG-F04 | 稳定发布、安装与兼容缓存治理 | 将已验证版本安全交付到稳定源、Marketplace 和运行缓存，并保留必要回滚能力 | 运维支撑 | 已完成盘点 |
| SG-F05 | 治理状态持久化、等待巡检与异常恢复 | 保存任务和 Agent 状态，支撑等待、平台对账、同 Agent 有限恢复和会话恢复 | 核心 | 已完成盘点 |
| SG-F06 | 子 Agent 终态结果协议、验收与父任务闭环 | 保存子 Agent 明确提交的完成、阻塞、失败和待决策业务结果，交给父任务验收和汇报；机械异常只进入生命周期状态 | 核心 | 已完成盘点 |
| SG-F07 | 运行诊断、问题定位与可观测性 | 只读展示治理状态、健康、证据边界和下一步操作提示 | 支撑 | 已完成盘点 |
| SG-F08 | 轻量多 Agent 协调 | 记录多个独立任务属于同一目标，并帮助父 Agent 等待、恢复和汇总 | 可选支撑 | 已完成盘点；已从完整编排系统收缩 |

## 三、插件因何而存在

没有以下四类能力，本插件就失去主要意义：

1. **稳定派发与上下文交接**：父 Agent 必须以统一参数生成完整首句，使子 Agent 明确目标、范围、限制、上下文和完成条件。
2. **稳定通信与任务关联**：父 Agent 对运行中的子 Agent 补充上下文、修正方向或发送恢复指令时，必须知道消息发给谁、为何发送以及期望什么结果。
3. **网络失败下的等待与恢复**：父 Agent 能够等待真实终态，在网络或 Provider 断流后对账目标 Agent，并优先恢复同一个 Agent，而不是重复派发。
4. **终态结果与父任务闭环**：子 Agent 完成、阻塞或需要决策时，必须形成完整结果，父 Agent 能继续验收、决策并向用户报告。

SG-F02、SG-F04 和 SG-F07用于让上述核心能力能够被正确加载、发布和排障。SG-F08只提供轻量多任务关联，不得扩张为本插件存在的前提。

## 四、跨功能统一裁决

### U-01 参数传递规则必须稳定

- 每一种交互场景都应有明确参数集合：派发、普通通信、恢复通信、完成、阻塞、需要决策、平台错误、主动中断和父任务显式处置。
- 状态、操作类型和治理等级等字段使用固定枚举。
- 目标、原因、具体内容、上下文、结果、证据和建议等业务语义由 AI 根据真实任务生成。
- 脚本负责字段存在性、类型、长度、枚举、引用和基本结构校验，不替 AI 创作业务内容。
- 用户裁决（2026-08-11）：模型与推理强度直接使用可空的 `model` 和 `reasoning_effort` 字段表达，不增加 `inherit/default/auto` 伪枚举。字段为空或省略时，生成器在原生调用中省略对应参数，并分别向用户显示“继承主 Agent（未显式覆盖）”和“继承主 Agent 当前强度（未显式覆盖）”；不得猜测实际继承值。显式 `model` 只校验字符串类型、非空和合理长度，不维护模型白名单；显式 `reasoning_effort` 使用 `low|medium|high|xhigh|max|ultra` 固定枚举。business resume 继续原 Agent时不能改变模型；新 attempt 明确要求更换模型时必须重新 spawn。
- 用户裁决（2026-08-11）：子 Agent业务通信必须显式提供 `operation_type=normal_message|platform_recovery|result_correction|business_resume`。四类操作共享对象、原因、具体内容和期望结果等 AI业务字段，但分别驱动固定状态转换；不得根据工具名、当前状态或自然语言正文猜测本次 follow-up 的用途。

### U-02 用户展示与子 Agent 首句必须分层

- 主对话只向用户展示派发原因、目标、治理参数、工作范围和完成条件等关键信息。
- 调用子 Agent 的第一句话必须尽可能完整，包含足以独立执行的任务上下文。
- 为了让主对话简洁，不能删除子 Agent 真正执行所需的背景、限制或验收条件。
- Hook 内部状态、短引用和机械 ID 不应无必要地展示给用户。
- 用户裁决（2026-08-11）：上下文策略默认使用隔离，由生成器把任务相关背景完整写入子 Agent首句；有限或完整继承只在任务确实依赖连续对话、无法可靠压缩的细微语义、用户明确要求或存在未落盘状态时显式选择并说明原因。不得用无差别完整继承弥补首句生成质量。
- 用户裁决（2026-08-11）：上下文结构化参数固定为 `context_strategy`、`context_turns` 和 `context_reason`。`isolated` 映射为原生不继承上下文，`context_turns` 必须为空且 reason 可省略；`limited` 映射为继承最近 N 轮，`context_turns` 必须是1至100的正整数且 reason 必须存在；`full` 映射为继承全部上下文，`context_turns` 必须为空且 reason 必须存在。对应原生参数分别为 `none`、正整数 N 和 `all`；用户可见说明固定渲染为“否”“否（仅继承最近 N 轮）”和“是”，不得展示内部参数名。脚本只检查枚举、数值范围、字段存在和合理长度，不评价继承理由是否充分。
- 首句上下文由 AI生成，至少组织唯一目标、相关历史裁决、工作与禁止范围、相关文件和当前状态、完成条件、验收证据、恢复与终态义务。脚本只校验策略枚举、字段存在、类型和合理长度，不用关键词、评分或业务规则判断内容是否“足够详细”。

### U-03 固定格式生成和结构校验必须保留

目标链路为：

```text
AI 填写结构化业务参数
  → 确定性生成器进行机械校验
  → 生成用户说明、dispatch prompt 或通信消息
  → 调用原生 Agent 工具
  → Hook 在可观察范围内复核引用、状态和原生参数
```

- 固定格式不是过度设计。
- 格式错误可以在原生工具执行前打回主 Agent，要求重新生成。
- 格式打回只纠正本次调用，不消耗平台恢复次数，也不改变子 Agent 生命周期状态。
- 原生公开工具如果不接受额外业务字段，应由独立生成器先输出合法的 `target/message` 或 `task_name/message`，不能假设额外字段一定能进入 Hook。
- 对终态场景，结构化结果是唯一权威数据；中文终态卡只是由同一份结构化结果生成的展示文本。终态卡渲染错误应重新生成展示文本，不得把已经合法保存的结构化结果打回子 Agent重新执行或重新提交。

### U-04 插件不承担业务语义验收

应删除或降级的硬性判断包括：

- 用关键词判断任务是否真正完成。
- 用固定文本长度判断结果是否充分。
- 用“证据”“测试”等自然语言词判断证据是否存在。
- 要求任务 ID 必须出现在自然语言正文中。
- 因表达方式不同而反复阻止停止或强制续跑。
- 用自然语言风险词决定安全等级。

父 Agent 负责业务验收；Hook 只负责结构、身份、状态和数据边界。

用户裁决（2026-08-11）：插件不承担下级子 Agent 的权限、层级或范围裁决。统一任务契约不设置独立且必填的 `child_agents` 授权字段，不限制嵌套深度、不传播派发权限、不建立父子任务图，也不机械判断下级任务是否属于上级业务范围。`task_features.allows_child_agents` 仅作为 auto 解析时由 AI提供的可选复杂度信号，不代表插件授予或禁止权限；业务上的允许或禁止由 AI写入 work scope 或 forbidden scope。任何 Agent真正调用 `spawn_agent` 时，都作为一次新的独立派发重新进入同一治理链。

### U-05 存储与身份体系必须收缩

推荐数据边界：

```text
governance-data/
├── prepared/   # 短期 PreparedContract
├── sessions/   # StateStore 生命周期状态
└── results/    # task_id + attempt 对应的完整结果
```

身份生成与派发链：

```text
task_id + attempt
  → task_ref
  → PreparedContract + 初始 StateStore
  → task_name
  → spawn_agent
  → agent_id / canonical path
```

事件反向绑定链：

```text
task_name 中的 task_ref
  → PreparedContract / StateStore
  → task_id + attempt
  → agent_id / canonical path 绑定
  → results/<task_id>-<attempt>.json
```

保留：

- `StateStore`。
- 极简、短期 `PreparedContract`。
- `task_id`、原生 Agent 标识和简单递增 `attempt`。
- 按 `task_id + attempt` 保存的完整结果文件。

用户裁决（2026-08-11）：StateStore 是核心可靠性底座，不能删除，但必须收缩为每个 Session 一份带稳定锁文件的最小治理状态 JSON。Hook 每次由独立 Python 进程执行，且任务可能跨越网络断流、20分钟等待、上下文压缩和会话恢复；没有持久状态就无法可靠关联任务与 Agent、限制同 Agent恢复次数、区分通信操作、绑定正式结果或恢复父 Agent待处理责任。原生 `list_agents` 只能提供当前平台观察，不能替代 task/attempt、契约摘要、恢复计数、结果引用和父 Agent验收状态。StateStore 不得发展成任务数据库、消息系统、完整事件历史或审计平台。

StateStore 最终只承担：

- Session 基本信息、组件健康和更新时间。
- `task_id + attempt + task_ref`、Agent ID/canonical path 和当前 attempt 关联。
- 恢复和验收同一任务所需的最小契约摘要：目标、工作/禁止范围、完成条件、有界 `evidence_requirements[]`、当前治理等级和父 Agent下一步动作；不保存完整 dispatch prompt 或完整对话。
- 已分离的派发观察、身份、执行、平台、业务结果、结果验收、结果协议、结果存储、父动作和会话保留状态。
- spawn 明确失败重试、平台恢复和结果补交的独立有限计数。
- 两阶段 `pending_action`、正式结果文件引用、重复执行标记、关键时间、明确关闭后的最小 tombstone，以及父 Agent显式创建的轻量 group 记录。未认领 action 短期存在；已认领 action 只保留完成调用对账所需的最小事实。
- 每个 attempt 至多一条已清理 lifecycle action 的最小 `last_lifecycle_operation`，只保存 `operation_type=platform_recovery|result_correction|business_resume|interrupt`、精确 target、可用时的 `tool_use_id`、`call_observation`、`claimed_at` 和 `completed_at`，用于网络延迟下的迟到启动或中断结果对账；不保存普通消息或完整通信正文。
- 用户裁决（2026-08-11）：`last_lifecycle_operation` 不设置5分钟、20分钟、12小时或其他单纯时间 TTL。匹配的 `SubagentStart` 确认后、attempt 取得正式业务结果后、attempt 被明确确认主动中断或关闭/转入 tombstone 后、failed 调用经人工对账确认与后续事件无关后，必须删除该记录；同一 attempt 创建下一次 lifecycle operation 前也必须先明确消费或解除旧记录。attempt 仍未解决且最后调用观察为 success/unknown 时继续保留，不因会话压缩或时间经过自动删除。每个 attempt 始终最多一条，不增加历史表或后台清理器。

完整业务结果及子 Agent实际产生的 `evidence[]` 保存在独立 result 文件；StateStore 中的 `evidence_requirements[]` 只是当前 attempt 的契约要求，不复制实际证据。完整 PreparedContract 只短期存在；完整平台响应、通信历史、正文可见性分析、版本迁移信息和推测性根因都不进入 StateStore。

用户裁决（2026-08-11）：`attempt` 表示一次正式业务执行结果边界，不表示每一段平台连接。普通平台错误后通过 `followup_task` 恢复同一个 Agent时保持当前 attempt，只增加独立的 `recovery_count`；已有 blocked 或业务 needs_decision 正式结果后继续执行，或者原 Agent客观上无法继续而重建执行者时，才递增 attempt。已结束 attempt 的结果文件不可重新打开或覆盖。

默认暂停或合并：

- 独立文件或独立存储层形式的 `PreparedCommunication`；通信操作类型只使用 StateStore 内短期 `pending_action`。
- `PreparedResultStore → ResultStore` 双层提交。
- 独立 `execution_id`、`submission_attempt_id`、`communication_id`、`notification_id`。
- 随机 `result_id`、AggregateResult ID。
- 结果 revision、复杂哈希冲突数据库、通知确认和完整事务系统。

只有真实平台事件证明简单方案不足时，才增加新的身份或存储层。

### U-06 状态、结果、平台观察和父任务动作必须分离

当前单一 `status` 混合了四类语义：

1. 子 Agent 执行状态。
2. 平台观察状态。
3. 子 Agent 业务结果。
4. 父任务下一步动作。

目标模型至少应区分：

- 执行：`not_started`、`running`、`stopped` 或 `interrupted`；不再承载派发结果或身份确认语义。`stopped` 只表示当前没有执行，不单独表示 attempt 已产生业务终态，必须结合业务结果、平台状态和 pending action 判断。
- 派发观察：原生调用成功、失败或结果未知。
- 身份观察：Agent 身份未确认或已确认。
- 平台观察：正常、错误或未知；不再为 Provider 协议不兼容建立特殊生命周期类别。
- 业务结果：完成、阻塞、需要决策、失败。
- 结果验收：`null`、待验收、已接受或已拒绝；只用于 complete 结果的父 Agent验收。
- 结果协议：`null | needs_correction | valid | exhausted`。
- 结果存储：`null | available | unavailable`；存储故障不等于结果协议非法。
- 父任务动作：继续等待、对账、重试派发、恢复、纠正结果、业务继续、验收、询问用户、人工检查或解决重复执行；明确关闭由处置记录和 tombstone 表达，不使用“结束”动作。
- 会话保留：未解决时继续保留，明确关闭后进入 tombstone，保留期结束后精确清理。

用户裁决（2026-08-11）：`parent_action` 是状态机根据已持久化事实给出的权威下一步动作，允许 JSON `null` 或 `wait | reconcile | retry_spawn | recover | correct_result | decide_disposition | business_resume | accept_result | ask_user | manual_review | resolve_duplicate`。初始 attempt 尚未进入原生调用时为 null；任务明确关闭后同样清空为 null。它只表示父 Agent接下来应处理什么，不表示对应工具调用、验收或处置已经完成；真正处于调用过程中的操作由两阶段 `pending_action` 或已消费 PreparedContract 表达，父 Agent已经作出的验收、选择或关闭决定由 `parent_disposition` 表达。关闭状态和 tombstone 负责表达终态，不增加 `end` 或 `closed` 动作值。`business_resume` 沿用同名 operation type，避免同一操作出现两套字段值。

用户裁决（2026-08-11）：`decide_disposition` 专门表示合法业务结果或中断已经发生，但插件不能替父 Agent判断应继续、调整、询问用户还是关闭。`business_result=complete` 使用 `accept_result`，`business_result=needs_decision` 使用 `ask_user`，`business_result=blocked|failed` 使用 `decide_disposition`；complete 被 rejected 后和未关闭的主动中断同样使用 `decide_disposition`。只有父 Agent已经明确决定继续并准备创建新 attempt 时才写 `parent_action=business_resume`。协议、存储或治理组件异常继续使用 `manual_review`，不得把正常业务结果伪装成治理故障。

用户裁决（2026-08-11）：目标状态模型不保留 `archive/archived`。时间只产生 stale 诊断标记，不改变会话保留责任；未解决任务不得按时长自动关闭或清理。父 Agent验收完成、带有明确关闭意图的中断、父 Agent其他显式处置或用户决定统一通过 `close_task` 进入7天 tombstone，保留期结束后再精确清理；不增加独立归档入口、归档恢复流程或归档状态。

用户裁决（2026-08-11）：观察型状态统一区分“尚未发生”和“已经发生但结果未知”。新建 attempt 的核心观察字段固定存在；相关事件尚未发生或该观察尚不适用时使用 JSON `null`，只有工具调用、平台查询或其他观察已经实际发生但结果无法确认时才使用枚举 `unknown`。不得用字段缺失、空字符串、`unset` 或 `pending` 代替初始空值。对已有记录仍只检查当前操作真正需要的字段，缺少无关观察字段时不整体拒绝、不静默补造事实。

用户裁决（2026-08-11）：新建受治理 spawn attempt 的初始 StateStore 固定写 `execution_status=not_started`、`spawn_observation=null`、`identity_status=unconfirmed`、`platform_observation=null`、`business_result=null`、`acceptance_status=null`、`result_protocol_status=null`、`result_storage_status=null`、`result_conflict=false`、`recovery_status=null`、`parent_action=null`，并把 `spawn_retry_count/recovery_count/correction_count` 初始化为0。spawn 结果 unknown 且身份未确认时，执行仍为 `not_started`、身份为 `unconfirmed`。取得可靠 Agent身份或精确绑定的 `SubagentStart` 后进入 `running`，并同步写 `platform_observation=normal`、平台观察时间和来源、`recovery_status=null` 与 `parent_action=wait`；恢复计数不清零。complete、blocked、failed 或业务 needs_decision 结束当前 attempt 时进入 `stopped`；`list_agents` 明确报告当前 Agent `errored` 时同样进入 `stopped`，但 `business_result` 保持 JSON `null`，表示 attempt 尚未产生业务终态；成功主动中断时进入 `interrupted`。删除执行维度中的“待派发”和“身份待确认”，分别由 `spawn_observation` 与 `identity_status` 表达。

用户裁决（2026-08-11）：只有精确绑定当前 task/attempt 的 `SubagentStart` 能把平台观察更新为 normal；普通消息、弱身份候选或无法确认 attempt 的启动事件不得清除已有 error/unknown。后续 `list_agents` 再次明确报告 errored 时，重新写 `platform_observation=error` 并进入对应的恢复状态。StateStore 不保存完整平台错误事件历史，既有 `recovery_count` 和当前观察来源足以说明发生过恢复。

用户裁决（2026-08-11）：同一 attempt 在 `execution_status=stopped`、没有正式业务结果且未关闭、未中断时，只有存在匹配的 `pending_action=platform_recovery|result_correction`，或同一 Agent/attempt 精确匹配最近一条 `operation_type=platform_recovery|result_correction + call_observation=success|unknown` 的 `last_lifecycle_operation` 时，才允许收到 `SubagentStart` 后重新进入 `running`。`platform_recovery` 用于恢复原业务执行，`result_correction` 只允许重新生成和提交结构化结果，不能重新执行业务任务。新建 business resume attempt 在 `execution_status=not_started` 时只接受匹配的 business-resume pending/last-operation 证据确认启动。`operation_type=interrupt` 的记录只用于中断结果对账，绝不能授权 stopped/not_started → running。匹配成功后删除对应 `last_lifecycle_operation`；重复启动事件在已经 running 时按幂等事件处理。因 complete、blocked、failed 或业务 needs_decision 进入 stopped 的 attempt 已结束，不能重新运行；`interrupted` 也不能恢复原 attempt，继续执行必须创建新 attempt。

用户裁决（2026-08-11）：`blocked` 表示本次执行已经停止，但业务任务仍未解决。它应表达为 `execution_status=stopped`、`business_result=blocked` 与 `parent_action=decide_disposition` 的组合，并持续进入 `action_required`。父 Agent向用户报告阻塞只完成了当前汇报动作，不等于关闭任务；只有阻塞解除后继续并完成、用户明确放弃，或父 Agent依据用户指示显式关闭，才能退出待处理集合。

用户裁决（2026-08-11）：`business_result=failed` 同样只结束当前 attempt，不自动关闭治理任务。失败结果表示本次执行未实现目标，设置 `parent_action=decide_disposition` 并继续进入 `action_required`；父 Agent或用户必须明确选择接受失败并关闭、放弃任务，或者调整条件后创建新 attempt。单纯汇报失败不能让未实现的目标隐式消失。

用户裁决（2026-08-11）：`business_result=complete` 只表示子 Agent声明本 attempt 已完成，不等于父 Agent已经完成业务验收。合法 complete 结果写入后设置 `acceptance_status=pending` 与 `parent_action=accept_result`，任务继续进入 `action_required`；父 Agent核对工作成果和证据后，显式写为 accepted 才能关闭，写为 rejected 时保留原结果并设置 `parent_action=decide_disposition`，之后再由父 Agent决定创建新 attempt 或进行其他明确处置。

用户裁决（2026-08-11）：StateStore 中 `acceptance_status` 字段固定存在并允许为 JSON `null`，但只服务于 `business_result=complete` 的父 Agent验收。没有正式结果，或正式结果为 `blocked | failed | needs_decision` 时保持 `acceptance_status=null`；只有合法 complete 结果写入后才进入 `pending`，再由父 Agent显式处置为 `accepted` 或 `rejected`。接受失败、确认阻塞无法解除、放弃决策任务等场景统一通过 `close_task` 和关闭原因表达，不写成 accepted。正式 result 文件不包含 `acceptance_status`，因为它是结果提交后由父 Agent产生的治理状态，不属于子 Agent业务结果。

用户裁决（2026-08-11）：StateStore 中 `result_protocol_status` 字段固定存在，取值为 `null | needs_correction | valid | exhausted`。尚未进入结果提交阶段时为 JSON `null`；子 Agent停止但尚未取得合法结果且仍有补交次数时写 `needs_correction`；结构化结果通过字段、类型、枚举、引用、长度和基本组合等机械协议检查时写 `valid`；两次补交后仍没有合法结果时写 `exhausted`。结果内容协议合法但正式结果存储失败时仍记录 `result_protocol_status=valid`，同时单独写 `result_storage_status=unavailable`，不得把存储故障改写成协议错误。正式 result 文件不包含 `result_protocol_status`，因为该文件只允许保存已经通过协议检查的业务结果。

用户裁决（2026-08-11）：StateStore 中 `result_storage_status` 字段固定存在，取值为 `null | available | unavailable`。尚未产生合法结果且没有尝试结果存储时为 JSON `null`；result 文件原子写入、重新读取验证和 StateStore 关联全部成功后写 `available`；合法结果的写入、读取或关联失败时写 `unavailable`，并保持 `business_result=null`。孤立 result 文件经过精确 task/attempt、Schema、身份和冲突检查并重新关联成功后，将该字段从 `null` 或 `unavailable` 改为 `available`，再写入对应业务结果、验收状态和父动作。`available` 只表示正式结果可以可靠读取，不表示父 Agent已经验收。正式 result 文件不包含 `result_storage_status`。

用户裁决（2026-08-11）：StateStore 中 `result_conflict` 固定为布尔值，初始为 false。同一 `task_id + attempt` 已有合法正式结果 A，又收到内容不同但协议合法的结果 B 时，原结果文件 A 保持唯一权威且不得覆盖，B 不写入第二套候选结果库；设置 `result_conflict=true + parent_action=manual_review`，只保存 B 的 SHA-256 摘要和首次发现时间，用于识别相同冲突重放，不保存第二份完整结果或冲突历史列表。原有 `business_result`、`result_protocol_status=valid`、`result_storage_status=available` 和 `acceptance_status` 保持不变，不能把冲突伪装成协议或存储故障。相同 B 重放幂等；冲突未解决前任务持续进入 `action_required`。父 Agent通过现有 `accept_result`、`reject_result`、`close_task` 或明确创建新 attempt 作出处置时，在同一锁内清除冲突标记和摘要，不新增结果冲突动作枚举。

用户裁决（2026-08-11）：成功 `interrupt_agent` 只结束当前执行，不自动关闭治理任务。只有中断原因明确表示用户放弃、取消或父 Agent已完成处置时，任务才能退出 `action_required`；为修正方向、更换执行者、处理资源冲突或等待用户决定而中断时，保留任务和原因，设置 `parent_action=decide_disposition`，后续通过新 attempt 或明确决策继续。

用户裁决（2026-08-11）：`interrupt_agent` 调用 unknown 时不得把 attempt 写成 interrupted，也不得自动重试。保持原 `execution_status`，设置 `parent_action=reconcile`，并在现有 `last_lifecycle_operation` 保存 `operation_type=interrupt`、精确 target、原因和 `call_observation=unknown`。后续明确收到中断 success 才写 interrupted；目标对账仍为 running 时保留 unknown 调用证据并设置 `parent_action=ask_user`，由用户决定再次中断或允许继续；目标已经 stopped/completed 时不能倒推为中断成功，改按真实 Stop 和正式结果处理；目标明确 errored 时记录平台错误，但因父 Agent原本正在主动停止该 Agent，不得自动进入平台恢复，设置 `parent_action=ask_user` 决定恢复还是关闭。unknown 中断记录必须持续进入 `action_required`，直到被明确结果或显式处置消费。

用户裁决（2026-08-11）：结果补交达到两次上限后仍不合法时，不写业务 failed 或 needs_decision。记录 `result_protocol_status=exhausted`、停止自动补交并设置 `parent_action=manual_review`，`business_result` 保持 JSON `null`；保留原生最终回复和已有工作，任务继续进入 `action_required`，等待父 Agent核对现状、创建新 attempt、请求用户决定或作出其他显式处置。父 Agent不得根据自然语言回复代替子 Agent编造正式结构化结果。

用户裁决（2026-08-11）：`result_correction` 调用结果使用固定父动作。调用 success 时保持 `execution_status=stopped + result_protocol_status=needs_correction + parent_action=wait`，只有同一 Agent、同一 attempt 的精确 `SubagentStart` 才能进入 running，且运行权限只覆盖结果生成与提交。调用 unknown 时保持 stopped/needs_correction，写 `parent_action=reconcile`、保留最小 `last_lifecycle_operation` 并禁止自动重发；迟到的精确启动或合法结果仍可正常确认。调用明确 failed 时不回退已经消耗的 `correction_count`：若当前计数为1，则重新设置 `parent_action=correct_result`，允许第二次也是最后一次补交；若当前计数为2，则设置 `result_protocol_status=exhausted + parent_action=manual_review`。补交启动后再次停止仍没有合法结果时采用相同剩余额度判断。合法结果先于启动事件到达时可直接按正式结果路径保存，并消费对应 lifecycle 记录，不要求为了形式补一个 SubagentStart。

用户裁决（2026-08-11）：首次 `spawn_agent` 的明确失败和结果未知必须分开处理。首次原生派发不计入 `spawn_retry_count`；`spawn_observation=failed` 且能确认 Agent未创建时，可在原 `task_id + attempt` 上自动重派一次。完成调用前机械校验并原子认领该重派时设置 `spawn_retry_count=1`，原生调用的 failed 或 unknown 都不回退计数，只有真正调用前被拒绝才不消耗。自动重派再次明确失败后停止自动重试并进入 `action_required`；用户明确要求继续时允许第二次也是最后一次同 attempt 重派，认领时设置 `spawn_retry_count=2`。第二次重派仍 failed 时，禁止继续复用并显式关闭该 attempt；继续执行必须创建新 attempt。任何一次重派结果为 unknown 时，都不得继续重派或关闭同一 attempt；保持 `identity_status=unconfirmed`，等待迟到的 `SubagentStart`、mailbox 或其他可靠身份事实，只有明确接受重复执行风险后才能另建新 attempt。所有同 attempt 重派沿用原 `task_ref`，只有新 attempt 生成新引用。

用户裁决（2026-08-11）：spawn 路径按机械阶段设置固定父动作。首次明确 failed 且 `spawn_retry_count=0` 时写 `parent_action=retry_spawn` 并执行一次自动重派；自动重派再次明确 failed、`spawn_retry_count=1` 时写 `parent_action=ask_user`，由用户选择是否授权最后一次同-attempt 重派、创建新 attempt 或关闭。用户授权最后一次重派时先原子认领、设置 `spawn_retry_count=2 + parent_action=retry_spawn`，再执行原生 spawn。任意一次调用返回 unknown 时写 `spawn_observation=unknown + identity_status=unconfirmed + parent_action=reconcile`，禁止继续复用该 attempt 重派。调用 success 但身份尚未确认时同样写 `spawn_observation=success + identity_status=unconfirmed + execution_status=not_started + parent_action=reconcile`；没有可靠 Agent target 时不能使用 `wait_agent` 或目标范围 `list_agents`，也不能提前进入 running。只有取得可靠身份或精确 `SubagentStart` 到达后，才写 confirmed/running/normal/wait。最后一次重派明确 failed 时机械关闭当前 attempt 并生成 tombstone，不写业务 failed；原 task 继续进入 `action_required + parent_action=decide_disposition`，继续执行必须创建新 attempt。

用户裁决（2026-08-11）：目标 `task_name` 使用 `sg_<mode>_<semantic_name>_t_<task_ref>`，其中 `task_ref` 由现有 `task_id + attempt` 确定性派生，不创建新身份。生成器负责总长度和会话内唯一性，碰撞时按既定长度扩展规则处理；主对话不展示内部短引用。若真实 `SubagentStart` 暴露 task name，Hook用短引用精确回绑迟到 Agent及其 attempt；若平台不暴露，则保持 `identity_status=unconfirmed`，不能回退到同名、同轮或唯一候选猜测。

用户裁决（2026-08-11）：`task_ref` 的规范输入固定为 `<task_id>:<attempt>`，计算 SHA-256 后使用小写十六进制摘要。初始取前12位；若与当前 PreparedContract、StateStore 任务或7天保留期内 tombstone 碰撞，则依次扩展为16、20、24、28、32位。32位仍碰撞时不得覆盖或无限延长；由于此阶段尚未写入 PreparedContract 和初始 StateStore，废弃本次新生成的 task ID、重新生成一次 task ID 并从12位重新计算。新 task ID 仍无法得到唯一引用时拒绝生成本次任务并返回明确错误，不调用 `spawn_agent`。同一既有 `task_id + attempt` 始终得到同一引用，明确失败后的同 attempt 重派不得换引用，也不能因后来出现碰撞而改名。`task_name` 固定最多64个字符；`semantic_name` 只允许小写字母、数字和下划线，连续下划线合并、首尾下划线删除，空值回退为 `task`。名称过长时只截断 semantic name，不得截断治理等级、`_t_` 标记或 task ref。

用户裁决（2026-08-11）：不再建立或传输独立 `prepared_ref`。`task_name` 中的 `task_ref` 是原生派发参数中唯一的契约查找引用，PreparedContract 以该 `task_ref` 为存储和查找键，并与初始 StateStore 共同记录 `task_id + attempt + resolved_mode` 等机械事实。PreToolUse 从未加密的 task name 解析 `task_ref` 后读取并核对 PreparedContract；message 只承载子 Agent需要理解的业务正文，不写入机械引用。PreparedContract 仍执行发送前硬门禁、单次使用、回读验证和身份确认后删除，不因删除独立引用而弱化。

用户裁决（2026-08-11）：`spawn_observation=unknown` 后，只有父 Agent或用户每次明确接受重复执行风险才允许重新派发，并且必须创建新 attempt 和新的 task 短引用；不得自动连续创建替代 attempt，也不设置固定“最多两个 attempt”限制。每个旧 unknown attempt 都保留为可能迟到的执行边界，不能改写成明确失败或复用其结果地址；旧 Agent之后出现时仍绑定自己的 attempt，其启动和结果不能覆盖 current attempt。

用户裁决（2026-08-11）：任一旧 unknown Agent迟到出现并与当前或其他尚未处置 attempt 形成重复执行时，不自动中断任何 Agent。记录 `duplicate_execution=true` 与 `parent_action=resolve_duplicate`，立即进入人工处置；父 Agent向用户说明全部候选 attempt、Agent和已知进度，由用户或父 Agent依据明确授权从全部候选中选择一个。选择时不新增 `selected_attempt` 字段，而是在同一锁内把任务的 `current_attempt` 原子切换为被选择的 attempt，并把其余所有未关闭候选标记为 `duplicate_not_selected`；选择持久化失败时不得自动中断任何 Agent。每个 attempt 的结果分别保存，任何 attempt 都不能覆盖其他 attempt；只有 current attempt 的结果自动进入当前任务验收链，所有非 current 结果只作为独立参考，不能自动切换 current attempt。

用户裁决（2026-08-11）：`select_attempt` 本身表示“保留所选 attempt、放弃其余重复执行候选”的明确父处置，不新增 `close_attempt`。选择必须在同一锁内原子写入 current attempt，并立即关闭所有已停止、已中断、身份未确认或其他非运行的未选候选，为其分别生成7天 tombstone；已有正式结果继续按 tombstone 保留期保存。仍在运行的未选候选只标记为 `duplicate_not_selected` 并返回全部精确中断 target，不由入口自动中断。父 Agent随后成功中断这些 Agent 时，复用已保存的 select 关闭意图，直接关闭对应 attempt 并生成 tombstone；中断 failed/unknown 时不得提前关闭。只有全部未选 attempt 都可靠关闭后才清除 `duplicate_execution`，并让所选 current attempt 进入其正常等待或结果验收链。

用户裁决（2026-08-11）：显式关闭的 task/attempt 必须保留最小 tombstone，固定保留7天；SessionEnd 在 tombstone 仍有效时不得删除整个 session JSON。tombstone 仅保存 `task_id + attempt`、Agent ID/canonical path、task 短引用、最后状态、关闭原因和关闭时间，用于识别迟到事件并阻止任务复活；只有所有任务已明确处置且 tombstone 超过7天后，才能在同一清理流程中删除对应正式结果、tombstone 和空 session 状态。暂不增加可配置项或后台 scheduler。

用户裁决（2026-08-11）：PreparedContract 只作为派发和初始身份绑定的短期凭证。身份确认后，将目标、工作/禁止范围、完成条件、Agent映射、`task_id + attempt + task_ref` 和必要恢复提示的最小摘要写入 StateStore，然后删除完整 PreparedContract；不得为了会话恢复长期保存完整首句。spawn unknown 时可暂时保留，迟到绑定成功或显式创建替代 attempt 后立即收缩为最小映射。

用户裁决（2026-08-11）：PreparedContract 使用两阶段有效期。尚未通过 PreToolUse 消费的契约固定有效5分钟，过期后拒绝派发并要求重新生成；由于该阶段能够确认原生受治理调用尚未发生，同时精确删除 PreparedContract 和对应的初始空 spawn attempt，不生成 tombstone。PreToolUse 校验成功后立即标记为已消费，并记录本次 `tool_use_id` 和 `claimed_at`；已消费契约不再因普通5分钟时限删除，而是保留到 Agent身份确认、可靠证据确认 spawn 失败、显式创建替代 attempt 或 task被明确关闭。身份确认后先把最小恢复摘要写入 StateStore，再删除完整契约；`spawn_observation=unknown` 不能仅因时间经过丢失迟到绑定所需信息。过期清理只在正常读取、SessionStart、SessionEnd 或状态写入时顺带执行，不增加后台 scheduler。

用户裁决（2026-08-11）：PreparedContract 已被 PreToolUse 消费但没有收到 spawn PostToolUse 时，`claimed_at` 未满20分钟只显示“派发调用仍在对账期”，保持初始 `spawn_observation=null + parent_action=null` 且禁止重派；该 consumed 记录进入 `action_required`。满20分钟仍没有 PostToolUse 时，在正常 SessionStart、状态读取或父 Agent恢复流程中写 `spawn_observation=unknown + identity_status=unconfirmed + execution_status=not_started + parent_action=reconcile`，继续保留迟到身份绑定所需的 PreparedContract，不得删除、重派或改写为 failed。之后精确 `SubagentStart` 正常绑定；迟到的明确 failed 调用结果则进入既定 spawn 重试流程。20分钟只用于缺失调用结果对账，不表示任务超时，也不增加后台定时器。

用户裁决（2026-08-11）：`business_resume` 创建新 attempt 后默认通过 `followup_task` 继续原 Agent，以保留上下文和进度。每个新 attempt 只允许投递一次 business resume 消息，不增加独立重试计数。调用明确 failed 且确认消息未送达时，以 `resume_delivery_failed` 显式关闭这个尚未启动、没有业务结果的 attempt，并把原 task 设置为 `parent_action=decide_disposition`；继续业务必须再创建新 attempt。调用 unknown 时保持 `execution_status=not_started + parent_action=reconcile + action_required`，不得关闭或重发，等待迟到的 `SubagentStart`；只有父 Agent或用户明确接受重复执行风险后才能创建替代 attempt。调用 success 时保持 `execution_status=not_started + parent_action=wait + action_required`：原 Agent身份和等待 target 已经可靠确认，可以继续等待同一 Agent，但 success 只表示 follow-up 未明确失败，仍需精确 `SubagentStart` 才进入 `running`。精确启动后写 `execution_status=running + platform_observation=normal + parent_action=wait`。替代 attempt 必须通过新的 `spawn_agent` 创建新 Agent并使用新 task ref，不得继续复用原 Agent；旧 Agent继续绑定旧 unknown attempt，避免仅凭 current attempt、最近时间或相同 target 猜测迟到启动归属。除上述 unknown 替代场景外，只有原 Agent客观上无法继续/无法接收 follow-up、用户明确要求更换、父 Agent确认其持续方向错误，或存在身份/重复执行冲突时，才重新 `spawn_agent`；该路径使用既定 spawn 重派规则。同一 Agent正常跨 attempt 时不修改既有 task name；Agent绑定后以 Agent ID/canonical path、StateStore 当前 attempt 和 pending/last lifecycle operation 为权威。

用户裁决（2026-08-11）：治理等级、范围、完成条件和证据要求属于 attempt，不永久绑定整个 task。每次 `business_resume` 都重新提交结构化任务特征并解析 `requested_mode/resolved_mode`；继续原 Agent时由 StateStore 当前 attempt 和完整恢复消息承载新契约，task name 保留首次 spawn 值。若新 attempt 要求更换模型、Provider 或原 Agent无法满足的执行环境，则必须重新 spawn，不能把 follow-up 描述成已经换模。

用户裁决（2026-08-11）：`auto` 只作为派发生成阶段的请求方式，不是第四个运行时治理等级。生成器在调用 `spawn_agent` 前依据结构化任务特征确定 `resolved_mode=light|standard|strict`，并保存 `requested_mode=auto` 与稳定 `resolution_reason`；task name、dispatch prompt、Hook状态机和结果协议只使用 resolved mode，不再由 Hook读取正文二次分类或兼容降级为 standard。

用户裁决（2026-08-11）：`auto` 使用固定优先级规则解析，不建立风险评分或自然语言关键词分类。只要 `risk=high`、`destructive=true`、`production=true`、`concurrent_write=true`、`multi_stage_acceptance=true`，或可选的 `allows_child_agents` 被显式提供为 true，其中任一成立就解析为 `strict`；仅当 `risk=low`、`read_only=true`、`writes_files=false` 且不存在任何 strict 信号时解析为 `light`；其余合法组合统一解析为 `standard`。缺少可选 `allows_child_agents` 只表示没有提供这项复杂度信号，不静默补写 false，也不影响插件之外的真实派发权限。生成器只拒绝 `read_only=true` 与 `writes_files=true` 等明显机械矛盾，不判断业务描述是否真的危险。

用户裁决（2026-08-11）：显式治理等级不由插件二次裁决。`requested_mode=light|standard|strict` 时，`resolved_mode` 固定等于请求值，`resolution_reason=explicit_request`；不得依据 task features 自动提升、降低或拒绝派发。显式等级下 task features 可省略，提供时只作为审计信息保存。Skill可以建议高风险任务使用 strict，但生成器和 Hook只拒绝非法枚举、错误类型等机械问题，不判断显式等级是否足够安全。

用户裁决（2026-08-11）：只要 `resolved_mode=strict`，无论最初是显式 strict 还是 auto 解析而来，都执行同一套完整 strict 语义：生成完整 strict 派发契约、采用相同证据强度，并从权威结构化结果渲染同一种中文终态卡。`requested_mode` 只用于审计和用户说明，不产生弱化 strict；终态卡仍是展示层，Hook不解析其措辞或用其阻断合法结构化结果。

用户裁决（2026-08-11）：只有 `task_name` 带合法 `sg_` 治理前缀的派发进入 PreparedContract 和初始 StateStore 硬门禁。无前缀原生 `spawn_agent` 视为 unmanaged 兼容调用，放行并记录有限诊断，不创建半套治理状态，也不承诺等待恢复、结果验收或 Stop 保护；不得再把无前缀调用默认升级为 standard。插件生成器始终产生带 resolved mode 和 task_ref 的治理 task name。

用户裁决（2026-08-11）：StateStore 中 `recovery_status` 字段固定存在，取值为 `null | awaiting_authorization | exhausted`。正常状态、可直接执行首次自动恢复以及仍在等待恢复调用对账时使用 JSON `null`；第一次自动恢复调用明确 failed，或第一次恢复成功启动后再次发生平台错误时，写 `awaiting_authorization + parent_action=ask_user`，表示仍可由用户明确授权最后一次恢复；最后一次恢复调用明确 failed，或恢复后再次被 `list_agents` 确认为 errored 时才写 `exhausted + parent_action=ask_user`。业务需要决策和平台恢复异常必须分开表达：只有子 Agent提交合法决策问题时才写 `business_result=needs_decision`，平台路径始终保持 `business_result=null`，不得伪造业务结果。

用户裁决（2026-08-11）：不保留独立的 `platform_error` 字段、枚举或生命周期状态。所有机械记录统一使用 `platform_observation=normal|error|unknown`；文本可以称“平台错误”，但代码字段必须写完整字段和值。`platform_observation=error + recovery_status=null + parent_action=recover` 表示当前可以执行首次自动恢复；恢复调用 success 后仍保留 error，但父动作改为 wait，调用 unknown 时改为 reconcile。`recovery_status=awaiting_authorization|exhausted + parent_action=ask_user` 分别表示等待最后一次授权或最终无法继续恢复。`platform_observation=unknown` 只表示平台观察已经发生但结果无法确认，不足以触发恢复，必须继续对账。`needs_decision` 只保留为业务结果枚举，不再兼任平台恢复状态。

用户裁决（2026-08-11）：第一次 `platform_recovery` 调用 success 时保持 `execution_status=stopped + platform_observation=error + recovery_status=null + parent_action=wait`，只有精确 `SubagentStart` 才写 running/normal/wait。第一次调用 unknown 时保持 stopped/error/null，设置 `parent_action=reconcile`、保留最小 `last_lifecycle_operation` 并禁止再次自动恢复。第一次调用明确 failed 时不回退 `recovery_count=1`，写 `recovery_status=awaiting_authorization + parent_action=ask_user`；只有用户明确授权才允许第二次也是最后一次恢复。第一次恢复成功启动后再次出现平台错误时采用同一 awaiting-authorization 状态。第二次恢复继续使用既定规则：unknown 进入 reconcile，明确 failed 或恢复后再次 errored 才进入 exhausted。

### U-07 网络恢复流程是核心可靠性能力

正确责任链为：

```text
父 Agent 调用 wait_agent
  → mailbox 正常唤醒，或超时/明确断流
  → 父 Agent 对目标范围调用 list_agents
  → 明确 errored 才记录 platform_observation=error
  → 父 Agent 调用 followup_task 恢复同一个 Agent
  → 第一次调用 success：保持 stopped/error，parent_action=wait
  → 第一次调用 unknown：保持 stopped/error，parent_action=reconcile，禁止自动重发
  → 第一次调用 failed：recovery_status=awaiting_authorization，parent_action=ask_user
  → SubagentStart 确认重新运行
  → 再次平台错误时 recovery_status=awaiting_authorization
  → parent_action=ask_user，business_result 保持 null
  → 用户明确授权时允许同一 Agent、同一 attempt 再恢复一次
  → 认领第二次恢复时清除 awaiting_authorization，由 pending_action、调用观察和 recovery_count=2 表达处理过程
  → 第二次调用 unknown 时 recovery_status=null、parent_action=reconcile，保留 last_lifecycle_operation，禁止再发恢复请求
  → 匹配的迟到 SubagentStart 到达时进入 running、platform_observation=normal、recovery_status=null、parent_action=wait，recovery_count 保持2
  → 第二次明确 failed，或恢复后再次 errored 时 recovery_status=exhausted，禁止继续恢复该 Agent/attempt
```

- Hook 没有后台线程、定时器或自动唤醒能力。
- 20 分钟等待规则是父 Agent 工作流，不是 Hook scheduler。
- 超时、沉默或测试耗时本身不是异常证据。
- 普通平台错误只自动恢复一次。
- 自动恢复后再次失败时，只允许用户明确授权一次额外恢复；同一 Agent、同一 attempt 最多执行两次平台恢复，不得重置计数或无限追问。
- 第二次恢复后仍失败时，不得继续恢复该 Agent/attempt；只能创建新 attempt 并按需要更换 Agent、模型或 Provider，稍后重新执行整个任务，或者显式关闭。
- 用户裁决（2026-08-11）：不保留 `provider_protocol_incompatible` 特殊恢复分支。所有 `list_agents` 明确报告的 `errored` 都统一写为 `platform_observation=error`，允许同一个 Agent 自动恢复一次；恢复后再次出现平台错误时将 `recovery_status` 置为 `awaiting_authorization`，并由 `parent_action=ask_user` 请求用户决定是否使用最后一次恢复。用户明确授权并成功认领后还可执行第二次也是最后一次恢复；认领时清除 awaiting authorization。最后一次调用 unknown 时只进入 reconcile 并等待迟到启动，明确 failed 或恢复后再次 errored 时才写 `recovery_status=exhausted`。整个过程不写业务 `needs_decision` 结果。
- 插件不解析 Provider、加密、解密或解码错误文本，也不因错误内容看起来不可恢复而跳过首次统一恢复。
- `light` 也必须保留网络恢复、状态安全和任务关联能力。

### U-08 治理组件故障必须与非法输入分开

- 明确缺字段、非法枚举、过期或篡改的 PreparedContract、task ref 冲突或原生参数不一致，应拒绝并给出可操作错误。
- 用户裁决（2026-08-11）：PreparedContract 是受治理派发的硬性凭证。task name 中的 `task_ref` 无法解析、对应 PreparedContract 缺失、无法读取或无法验证时，同样拒绝派发并要求父 Agent重新生成，不允许按 unmanaged 降级放行。
- 由于派发生成链路由本插件控制，生成器必须在调用 `spawn_agent` 前完成私有目录检查、原子写入、落盘后重新读取和完整性核对；任何一步失败都不得发起原生派发。Hook 正常情况下应始终能够读到合法契约。
- 用户裁决（2026-08-11）：创建新的受治理任务时，初始 StateStore 记录与 PreparedContract 同属派发硬门禁。必须先原子写入任务、attempt、task_ref、派发观察初值和最小恢复字段，并重新读取验证成功，才允许调用 `spawn_agent`；StateStore 已满、不可写或不可验证时拒绝本次受治理派发，不得静默降级为 unmanaged。
- 已经派发并在平台存在的 Agent，其普通消息、最终回复、只读诊断或不依赖新状态转换的兼容路径遇到 StateStore 写入失败、诊断读取失败或插件内部未知异常时，应告警并尽量 fail-open。`platform_recovery`、`result_correction` 和 `business_resume` 必须先成功持久化各自的 pending action、计数或新 attempt；这些前置写入失败时拒绝本次受治理状态变更，不能用 fail-open 绕过恢复上限或 attempt 绑定。用户仍可明确选择发送不受治理的普通消息，但不得把它记作已经治理的恢复、补交或业务继续。
- 用户裁决（2026-08-11）：正式结果存储不可写、不可读或内部异常属于治理组件故障，不属于子 Agent结果协议错误。此时保留原生最终回复，记录 `result_storage_status=unavailable`，并将对应治理组件健康标记为 `degraded`，允许 Agent停止，不恢复子 Agent，也不消耗结果补交次数；由于没有持久化正式结果，`business_result` 不据此进入权威状态，任务保持 `action_required + parent_action=manual_review`。只有子 Agent已经提交的合法、内容确定且仍可取得的结构化结果可以在存储恢复后原样重试保存；否则由父 Agent创建新 attempt、请求用户决定或作出其他显式处置，不能代写正式结果。
- fail-open 只适用于 PreparedContract 和初始 StateStore 记录均已验证、原生派发已经发生之后且不要求新增权威状态的普通通信、最终回复、诊断和兼容路径；不能绕过新任务契约、初始持久化、状态变更通信的原子认领或新 attempt 创建。
- `interrupt_agent` 是上述规则的安全例外：只要父 Agent或用户提供了明确的 Agent ID/canonical path，就不得因 StateStore 写入失败阻止原生中断；StateStore 不可读时不得猜测目标。中断调用成功但状态无法持久化时，必须即时报告“平台中断成功但治理状态未可靠记录”，禁止自动恢复或声称任务已经关闭，等待后续人工对账。
- Stop 是 fail-open 的例外：当父任务结束保护无法读取 StateStore 时，必须在本次 Stop 内总共尝试三次读取；全部失败后停止自动重试、阻止本次结束并返回即时的“需要用户决策”，不能假装没有未完成任务。
- 不得使用一个宽泛异常处理同时放行非法契约或阻断原生工具。
- 无 `sg_` 前缀或未映射到治理任务的特殊启动路径按 unmanaged 兼容放行，不应因 PreparedContract、固定模板或治理终态要求被阻断；诊断必须明确其不具备治理保障。

### U-09 本地证据与真实平台证据必须分层

证据强度从低到高分为：

1. 静态配置和 Schema。
2. 单元测试。
3. Hook fixture 调用本地 `handle()`。
4. 本地状态文件和诊断输出。
5. 真实 Codex 插件加载、`/hooks`、Agent 生命周期和 Provider 行为。

低层证据不能证明高层平台事实。尤其不能用 fixture 证明消息真正投递、Provider 已恢复、父任务已看到终态或 Hook trust 已生效。

### U-10 协议语义需要单一来源

- 当前同一规则分散在 `AGENTS.md`、Skill、参考文档、Schema、README、Python 和测试中，存在时点漂移。
- 用户裁决（2026-08-11）：单一来源只覆盖机器协议，不建设完整文档生成系统。建立最小权威语义源，集中维护枚举、字段名与基本类型、operation type、状态维度、机械状态转换、重试次数、保留期限和 task name 格式。
- 用户裁决（2026-08-11）：交互和持久化数据不使用协议版本作为兼容门禁。每次派发、通信、状态转换、结果提交和诊断读取都只校验当前操作真正需要的字段、类型、枚举、引用和基本组合；缺少字段时返回明确缺项，要求 AI或父 Agent重新补充后再执行。未知额外字段兼容忽略，不因数据来自旧插件版本而拒绝，也不静默迁移、重写或用默认值伪造缺失事实。JSON Schema只描述当前字段要求，不承担版本协商；Manifest版本仍仅用于插件发布、缓存身份和N/N-1整体回滚。
- Python、JSON Schema 和确定性生成器读取或校验该机器语义源；AGENTS、Skill、README、参考文档和盘点文档继续人工维护自然语言。
- 对自然语言载体使用少量一致性测试：检查核心枚举、固定参数名、次数/期限、task name 格式和已删除状态，不要求逐字生成或全文包含测试。
- 不要求插件 UI 文案和 Skill UI 文案逐字相同，但核心名称、等级、状态、字段和边界必须一致。
- 不应继续依靠大量静态文本包含测试维持多份手写协议，也不把自然语言说明编译成模板产物。

## 五、SG-F01 治理等级选择与任务契约

### SG-F01-01 功能职责

指导父 Agent 为一次新 spawn 或 business resume attempt 选择最低但足够的治理强度，并形成唯一当前目标、明确范围、上下文策略和可验证完成条件。

### SG-F01-02 主要入口

- `skills/subagent-governance/SKILL.md` 的 frontmatter 和派发章节。
- `skills/subagent-governance/references/governance-levels.md`。
- `schemas/task-contract-v1.schema.json`。
- `scripts/subagent_governance.py` 中的等级解析、`TaskContract` 和 `_handle_spawn()`。
- `spawn_agent` 的 `PreToolUse`。

### SG-F01-03 当前已确认事实

- Skill 是语义决策和参数组织层，不是执行层。
- 当前运行时要求 `task_name` 使用 `sg_<mode>_<semantic_name>`。
- 当前 `auto` 仍读取正文信号分类，属于待替换实现。
- 当前 Hook 仍读取、校验并改写派发正文，属于待替换实现。
- `task-contract-v1.schema.json` 当前主要是协议声明和测试锚点，不是完整运行时 validator。
- 当前派发身份主要依赖 `tool_use_id`，并以 `task_name/turn_id` 回退；成功但缺少 Agent 身份时可能形成 unmapped running。

### SG-F01-04 目标参数所有权

AI 提供：

- 请求治理方式和结构化任务特征。
- `auto` 的结构化任务特征要求 `risk`、`read_only`、`writes_files`、`destructive`、`production`、`concurrent_write` 和 `multi_stage_acceptance`；`allows_child_agents` 只是可选复杂度信号，不是权限字段。
- 目标、背景、工作范围、禁止范围。
- 完成条件和验收证据。
- 模型、强度、上下文继承策略；策略枚举为 isolated、limited 或 full，默认 isolated。limited/full 必须同时提供继承原因和范围说明。
- 面向子 Agent的完整任务上下文，包括当前目标、相关背景和裁决、范围、文件与状态、完成条件、证据要求以及恢复和终态义务。

这些业务参数按 attempt 保存。business resume 不得仅复制上一 attempt 状态；必须重新确认当前目标变化、风险特征、范围、完成条件和证据要求。

用户裁决（2026-08-11）：三种实际治理等级共用一套任务契约 Schema，不建立 light、standard、strict 三套结构。AI字段固定为 `semantic_name`、`requested_mode`、`task_features`、`objective`、`background`、`work_scope[]`、`forbidden_scope[]`、`completion_conditions[]`、`evidence_requirements[]`、`relevant_files[]`、`current_state`、`model`、`reasoning_effort`、`context_strategy`、`context_turns` 和 `context_reason`。其中 task features 仅在 requested mode 为 auto 时必填；objective、background、work scope、completion conditions 和 context strategy 对所有等级必填；model、reasoning effort、relevant files 和 current state 可为空。light 允许 forbidden scope 和 evidence requirements 为空；standard 要求至少一项 evidence requirement；strict 要求 forbidden scope 和 evidence requirements 都至少一项。脚本只校验字段、类型、数组长度和机械组合，不评价内容质量；固定终态通知、等待恢复规则和格式标题由生成器写入，不要求 AI重复填写模板。

脚本生成：

- 实际治理等级。
- 规范化并保存 AI提交的 `requested_mode`，生成 `resolved_mode` 和稳定的 `resolution_reason`。
- 规范化语义名称。
- `task_id` 和从 `task_id + attempt` 派生的 `task_ref`；不生成独立 `prepared_ref`。
- task ref 按12、16、20、24、28、32位依次检查唯一性；32位仍冲突时只重新生成一次尚未持久化的 task ID，再次冲突则拒绝生成，不进入原生派发。
- 固定用户说明和 dispatch prompt。
- `task_name`，目标格式为 `sg_<mode>_<semantic_name>_t_<task_ref>`；`task_ref` 从现有 `task_id + attempt` 确定性派生。

其中 `<mode>` 永远使用 `resolved_mode`。用户请求 auto 时，用户说明同时展示 requested mode、resolved mode 和简短解析原因；不得生成 `sg_auto_` 运行时前缀。
- 生成时间和必要机械字段；不生成用于兼容门禁的协议版本字段。

### SG-F01-05 目标生成链路

1. AI 提交结构化参数。
2. 生成器做存在、类型、长度、枚举和组合检查；对上下文只做机械边界检查，不评价业务完整性。
3. `auto` 解析为 `light/standard/strict`。
4. 在私有目录原子写入极简 PreparedContract，并立即重新读取、核对完整性和过期时间。
5. 原子创建初始 StateStore 任务记录并重新读取验证，确认容量、权限和当前派发所需的最小字段均可用。
6. 生成合法 `task_name` 和完整派发正文；task name 同时携带治理等级、可读语义名和会话内唯一的 task 短引用。
7. 只有 PreparedContract 与初始 StateStore 记录都验证成功后才调用原生 `spawn_agent`；任何生成、落盘或回读失败都停在本步骤之前。
8. Hook 从 task name 解析 `task_ref`，据此核对 PreparedContract、初始任务记录和原生可观察参数；PreToolUse 放行时把契约标记为 consumed 并记录 `tool_use_id + claimed_at`。
9. 原生派发发生后根据 PostToolUse 更新派发观察；consumed 后20分钟仍缺少 PostToolUse 时按 unknown/reconcile 对账，不重派、不删除契约。身份确认后提取最小恢复摘要并删除完整 PreparedContract。

未消费 PreparedContract 在5分钟后过期时，精确删除契约和对应的初始空 spawn attempt，不生成 tombstone；因为 PreToolUse 尚未认领，可以确认没有受治理原生派发需要迟到绑定。已经消费的契约不能走这条清理路径。

若原生派发明确失败且确认没有创建 Agent，允许自动重派一次，仍使用原 `task_id + attempt + task_ref`；自动重派再次明确失败后，经用户明确授权还可进行第二次也是最后一次同 attempt 重派。每次重派都在调用前原子认领并增加 `spawn_retry_count`，原 PreparedContract 已经消费、不可复用或过期时，以同一 task ref 重新生成并原子替换对应 PreparedContract。任一次重派结果 unknown 或第二次重派明确失败后，都不得继续复用该 attempt；若要继续，必须按既定关闭和重复执行风险规则创建新 attempt。若派发结果 unknown，则不得生成新 task ref 并自动重派，以免重复创建 Agent。

unknown 经显式决策后重新派发时，与明确失败重派不同：必须递增 attempt、生成新的 task 短引用和 PreparedContract，并把旧 attempt 保留为身份待确认/可能迟到状态。

### SG-F01-06 保留内容

- 三档实际治理强度。
- `auto` 作为生成阶段的一次性选择策略，不作为第四个实际运行等级。
- Hook只消费 PreparedContract 中已经确定的 `resolved_mode`，不因正文可见性、加密状态或兼容入口重新解析 auto。
- 所有 `resolved_mode=strict` 的任务共用完整 strict 契约字段和执行要求，不根据 `requested_mode` 分裂为显式 strict 与 auto-strict 两种运行语义。
- 首句完整上下文要求。
- 默认隔离、按需有限或完整继承的显式上下文策略。
- 确定性名称和格式生成。
- task name 中复用现有 `task_id + attempt` 的短引用，作为加密传输和迟到启动场景下可机械读取的精确绑定线索。
- 结构化任务契约。
- 非法、缺失、不可读或不可验证契约的发送前拒绝。
- 原生 `spawn_agent` 作为唯一派发通道。
- `task_id` 和 Agent 身份的稳定关联。
- `sg_` 前缀作为明确进入治理的边界；插件生成的所有派发必须带 resolved mode 与 task_ref。

### SG-F01-07 删除或替换内容

- Hook 对派发正文的字段提取。
- 正文明文/密文猜测及分支。
- 正文关键词 `auto` 分类。
- `HIGH_RISK_MARKERS`、`READ_ONLY_MARKERS`、`WRITE_MARKERS`、`NEGATION_MARKERS`、`_classification_text()` 及等价正文分类路径。
- Hook 改写完整业务正文。
- 依赖同名、同轮或唯一候选进行长期身份猜测。
- 把 `strict` 当作业务安全验证器。
- 没有运行时消费者的外部 Skill 清单。

### SG-F01-08 待验证

- 生成器输出能否直接适配真实原生工具参数。
- 真实 `SubagentStart` 是否稳定提供 task name，以及短 task ref 能否在迟到启动事件中完成精确回绑。
- 派发响应的稳定 Agent ID/canonical path 适配。
- 成功调用但身份未确认时的正式状态。
- isolated、limited 和 full 在真实 `spawn_agent` 中的参数映射，以及生成首句在独立上下文中的可执行性。

## 六、SG-F02 插件发现、Hook 注册与运行时接入

### SG-F02-01 功能职责

让 Codex 发现插件和 Skill，加载默认 Hook 配置，把 Hook 输入送入统一 Python 入口并路由到对应业务 handler。

### SG-F02-02 主要组成

- `.codex-plugin/plugin.json`：插件身份、版本、Skill 根目录和安装 UI 元数据。
- `skills/subagent-governance/agents/openai.yaml`：Skill UI 元数据。
- `hooks/hooks.json`：七类 Hook 接线。
- `scripts/subagent_governance.py` 的 `_tool_kind()`、`handle()`、`main()`。
- `tests/test_plugin_structure.py`：结构和入口测试。

### SG-F02-03 七类 Hook

1. `PreToolUse`：派发和通信预处理。
2. `PostToolUse`：派发结果、follow-up、中断和平台状态对账。
3. `SessionStart`：恢复摘要。
4. `SessionEnd`：条件清理。
5. `SubagentStart`：身份确认和启动上下文。
6. `SubagentStop`：终态处理。
7. `Stop`：父任务结束保护。

### SG-F02-04 已确认保留

- Manifest 默认 `./hooks/hooks.json` 路径，不必为显式性增加字段。
- 插件层和 Skill 层各自保留 UI 元数据。
- 七类事件统一调用 `python3 "$PLUGIN_ROOT/scripts/subagent_governance.py"`。
- `send_message_to_thread` 不得误识别为子 Agent 通信。
- Hook 配置只负责接线，不承载业务状态机。
- 用户裁决（2026-08-11）：`additionalContextLimit` 的平台 token 阈值与 Python 本地字符上限分别管理并使用明确单位命名。当前平台上限继续为1800 tokens，SessionStart 等本地摘要继续使用更保守的1800 characters；不得因为数值相同而混为同一限制，也不建设 token 估算或动态压缩系统。

### SG-F02-05 需要改造

- `main()` 必须区分预期非法输入和插件内部未知异常。
- 合法契约错误继续拒绝；新受治理派发在 PreparedContract 或初始 StateStore 门禁内发生的插件错误同样拒绝并给出诊断。原生派发已经发生后的插件未知错误才告警并 fail-open。
- 真实原生响应需要明确适配器，不能无限递归搜索任意嵌套字段。
- `additionalContext` 使用固定、简单的保留顺序：关键状态告警；`task_id + attempt`、Agent身份和父动作；当前状态与恢复/纠正次数；有界目标摘要；最近活动等次要信息。渲染时预留总数、已展开数、遗漏数和“不要重复派发”等固定提示空间；超限时从低优先级尾部删除完整记录，不从中间截断身份、状态、告警或计数。SubagentStart 只补当前任务的机械身份和生命周期状态，不复制完整 dispatch prompt。
- PreToolUse 先按 task name 是否具有合法 `sg_` 前缀区分 governed 与 unmanaged。governed 调用执行硬门禁；unmanaged 调用只记录有限诊断并放行，不创建会阻塞 Stop 的不完整任务。

### SG-F02-06 明确不负责

- Marketplace、稳定发布源和缓存生命周期。
- Hook trust 的写入和内部 hash 算法。
- 各 `_handle_*` 的派发、通信、状态、结果和诊断语义。
- Provider 稳定性或平台内部投递保证。
- 强迫第三方 Skill 或无前缀原生调用采用本协议；这些调用保持 unmanaged。

### SG-F02-07 待验证

- 交互式 `/hooks` 中七类当前定义是否 enabled/trusted。
- 插件 UI 和 Skill UI 实际展示。
- 稳定新版真实加载。
- 至少一个代表性生命周期事件真实触发。
- 平台 token spill、临时文件和首尾预览行为。

## 七、SG-F03 子 Agent 业务通信、恢复指令与任务关联

### SG-F03-01 功能职责

把父 Agent 提供的通信业务语义转换成原生 `send_message` 或 `followup_task` 参数，在能够解析时关联原治理任务，并通过显式 operation type 区分普通消息、平台恢复、结果补交和业务继续。

### SG-F03-02 固定业务参数

四类通信均保留以下核心字段：

- 对象。
- 目的。
- 原因。
- 具体内容。
- 期望结果。
- `operation_type`：`normal_message`、`platform_recovery`、`result_correction` 或 `business_resume`。

当前实现中的 `purpose`、`reason`、`content` 和 `expected_result` 是稳定协议的一部分，不应因为由 AI 填写就删除。

### SG-F03-03 目标生成方式

- AI 填写通信业务字段。
- 生成器校验字段并渲染用户说明与实际消息。
- 生成器校验 operation type 与当前 task/attempt 状态是否机械兼容，不解析业务正文推断类型。
- 生成器在现有 StateStore 中为精确 target 写入一条 `pending_action`，至少包含 `target/task_id/attempt/operation_type/phase/expires_at`；同一 target 同时只允许一条。初始 `phase=prepared`，只对下一次匹配调用有效，固定最长保留5分钟；未被认领即过期时直接删除并重新生成，不消耗任何次数。
- 生成器直接输出原生工具支持的 `target` 和 `message`。
- 给子 Agent的 message 只包含其需要理解的中文业务指令；`operation_type` 不作为 Hook 依赖字段写入可能加密的 message。
- PreToolUse 根据未加密的精确 target 在锁内取得唯一 prepared action，复核任务引用、操作类型和生命周期边界，绑定本次 `tool_use_id`、写入 `claimed_at` 并原子改为 `phase=claimed`；需要计数的操作在此时消耗预算。claimed action 不再按普通5分钟期限直接删除。
- PostToolUse 根据 `tool_use_id` 记录原生调用的 success、failed 或 unknown，完成对应状态更新后删除 pending action。
- `platform_recovery`、`result_correction` 或 `business_resume` 的 pending action 在 PostToolUse 完成或20分钟 unknown 对账后删除前，把上述最小字段写入当前 attempt 的 `last_lifecycle_operation`；同一 attempt 只保留最近一条，新的 lifecycle operation 必须先通过现有状态机确认旧记录已经消费或不再适用。`normal_message` 不写该记录。
- claimed action 从 `claimed_at` 起满20分钟仍没有 PostToolUse 时，不增加后台定时器；在下一次 SessionStart、状态读取或父 Agent恢复时将调用观察记为 unknown，保存最小 `last_lifecycle_operation` 后再删除 pending action。未满20分钟的普通读取只展示调用仍在对账期内，不提前改写。mailbox 或平台工具已经明确报告调用失败时可以立即记录 failed，不等待期限。已经消耗的次数不回退；`platform_recovery`、`result_correction` 和 `business_resume` 进入 `action_required` 且不得自动重发。`business_resume` unknown 使用 `parent_action=reconcile`，success 使用 `parent_action=wait`，failed 关闭该新 attempt 并把原 task 改为 `parent_action=decide_disposition`。`normal_message` 只输出有界告警后清理。该20分钟只用于缺失调用结果对账，不代表业务任务超时，也不改变 Agent执行状态。
- `call_observation=failed` 的 last lifecycle operation 不自动授权 stopped/not_started → running；之后出现同一 Agent启动事件时记录机械不一致并设置 `parent_action=reconcile`，不得直接猜测该启动属于本次操作。
- last lifecycle operation 按 attempt 生命周期而不是时钟清理：success/unknown 在任务未解决时跨 Session 保留；启动确认、正式结果、主动中断、明确关闭、tombstone 或人工解除后删除。不得为了状态体积按时间裁剪这条仍承担迟到绑定责任的记录。
- 已有 Agent的 StateStore 临时不可写时，`normal_message` 可以告警后 fail-open，并明确本次通信未可靠记录。`platform_recovery`、`result_correction` 或 `business_resume` 的 pending action、计数或新 attempt 无法创建、更新或回读验证时，拒绝本次受治理操作；不得声称状态转换已经成功，也不得以普通消息名义绕过。若原子认领已经成功、原生调用随后发生而 PostToolUse 更新失败，则调用不能回滚，只记录 degraded 告警并停止后续自动操作，等待父 Agent人工对账。
- 不依赖原生工具允许额外业务字段先进入 `PreToolUse`。

### SG-F03-04 普通消息规则

- 用于补充上下文、修正方向或请求信息。
- 不改变生命周期状态。
- 不增加 `recovery_count`。
- 任务处于 `platform_observation=error` 时不能用普通消息绕过恢复流程。
- PreToolUse 放行只证明参数合法，不能证明消息已投递或已处理。
- `normal_message` 不改变 attempt、`recovery_count` 或 `correction_count`。
- StateStore 暂时不可写时，`normal_message` 仍可作为明确降级的原生普通消息发送；该路径不创建或冒充任何恢复、补交或业务继续状态。

### SG-F03-05 恢复指令规则

- 只有 `list_agents` 明确对账为 `errored` 后，任务才进入平台恢复路径。
- 针对 `platform_observation=error` 的恢复在完成参数校验并原子认领操作后、真正调用 `followup_task` 前增加 `recovery_count`；参数或状态在调用前被拒绝时不消耗次数。
- follow-up 的原生调用观察单独记录为 `success | failed | unknown`；三种结果都不回退已经消耗的恢复次数，其中 unknown 按可能已经投递处理。
- 第一次 follow-up success 只表示原生调用未明确失败，保持 `stopped + platform_observation=error + recovery_status=null + parent_action=wait`；unknown 改为 `parent_action=reconcile`、保留最小 lifecycle 记录并禁止自动重发；明确 failed 时写 `recovery_status=awaiting_authorization + parent_action=ask_user`，等待用户决定是否使用最后一次恢复。
- `SubagentStart` 才确认同一个 Agent 重新运行。
- `SubagentStop` 和正式结果才说明业务是否完成。
- 所有平台错误使用同一规则：同一任务只自动恢复一次，不再区分 Provider 协议不兼容等特殊错误类型。
- 第一次自动恢复明确 failed，或恢复成功启动后再次出现平台错误时，记录 `recovery_status=awaiting_authorization`，父任务动作改为 `ask_user`；这不是子 Agent提交的业务 `needs_decision` 结果。
- 用户明确要求继续时，可以在同一 Agent、同一 attempt 上执行第二次也是最后一次平台恢复，`recovery_count` 增加到2且不得重置；再次失败后禁止继续恢复该 Agent/attempt。
- 第二次平台恢复调用 unknown 时不写 exhausted，改为 `recovery_status=null + parent_action=reconcile` 并保留最小 last lifecycle operation；匹配的迟到 SubagentStart 可以确认 running。第二次调用明确 failed 或恢复后再次 errored 时才写 exhausted。
- `platform_recovery` 只能用于明确的 `platform_observation=error`，保持原 attempt，并只增加 `recovery_count`。

### SG-F03-06 结果补交与业务继续

- `result_correction` 只能用于结构化结果的机械缺陷，保持原 attempt，消息必须明确“只补交结果，不重做业务”。父 Agent完成调用前机械校验并原子认领该 pending action 后立即增加 `correction_count`，再调用 `followup_task`；调用结果的 `success | failed | unknown` 不回退计数，只有真正调用前被拒绝才不消耗预算。success 保持 `stopped + needs_correction + parent_action=wait`，unknown 保持 `stopped + needs_correction + parent_action=reconcile` 并禁止自动重发；第一次明确 failed 后恢复 `parent_action=correct_result`，第二次明确 failed 后进入 `exhausted + manual_review`。处于 stopped 且没有正式业务结果的同一 Agent收到该 pending action 后，只能在精确 `SubagentStart` 时重新进入 running；补交完成或再次停止后仍按原 attempt 的结果协议和剩余额度处理。合法结果先于启动事件到达时可直接保存，不要求补造启动事实。
- `business_resume` 用于 blocked、failed、业务 needs_decision 已获选择或 complete 验收 rejected 后继续原目标；调用前先在原 `task_id` 下创建新 attempt，再向选定 Agent发送完整的新 attempt 上下文。
- 每个 business resume attempt 只投递一次，不新增 `business_resume_retry_count`。follow-up 明确 failed 且确认未送达时，以 `resume_delivery_failed` 关闭这个 not_started attempt，并把原 task 设置为 `parent_action=decide_disposition`；unknown 时保持 `not_started + parent_action=reconcile + action_required`，禁止关闭或重发；success 时保持 `not_started + parent_action=wait + action_required`，因为同一 Agent的精确 target 已知，可以继续等待，但必须等其 `SubagentStart` 才进入 running。
- unknown 后只有明确接受重复执行风险才能创建替代 attempt，旧 attempt仍保留迟到绑定和重复执行保护。该替代 attempt 必须改用新的 `spawn_agent` 创建不同 Agent，完全复用 spawn observation、retry count、unknown 和 task ref 规则；不得把新的 same-Agent follow-up 绑定到 current attempt 来绕过归属歧义。
- business resume 默认选择原 Agent并调用 `followup_task`；但前一 same-Agent business resume attempt 仍为 unknown 且未确认启动时，替代 attempt 必须更换 Agent。其他情况下，只有原 Agent不可继续、用户明确换 Agent/模型/Provider、父 Agent确认原执行者不适合继续，或身份冲突需要更换时，才通过新 `spawn_agent` 执行该 attempt。
- 创建 business resume attempt 时重新运行 SG-F01 的结构化等级解析，并把该 attempt 的 requested/resolved mode、范围、完成条件和证据要求写入 StateStore；后续 Hook和结果验收读取当前 attempt，而不是首次 task name 中的旧等级。
- 同一 Agent跨 attempt 时沿用 Agent ID/canonical path，task name 保持首次 spawn 的值；新 attempt ref 写入 StateStore 和 pending action，不要求也不能改写原 task name。
- 四类 operation type 使用独立计数和状态转换，任何一种都不能消耗另一种的预算。
- `platform_recovery`、`result_correction` 和 `business_resume` 的前置状态写入或回读验证失败时不得调用原生工具。原子认领成功后若原生调用或 PostToolUse 状态更新失败，不回滚已经持久化的计数或 attempt，并停止自动执行下一步。
- 工具调用成功只表示原生调用未明确失败；业务继续是否重新运行、结果补交是否成功，仍分别由 `SubagentStart` 和正式结果确认。

### SG-F03-07 任务关联

保留：

- `task_id`。
- 原生 Agent ID。
- canonical task path。
- 必要的短期 `task_name` 语义名。
- task name 中绑定现有 `task_id + attempt` 的确定性短引用。

目标：

- 通过 task name 中的 `task_ref` 定位 PreparedContract 并完成精确关联。
- 保留 task name 短引用的精确绑定，删除仅凭语义同名、同轮或唯一候选进行的猜测和失效映射。
- task name 短引用只用于首次 spawn、替代 spawn 和尚未绑定 Agent的迟到启动；Agent完成精确绑定后，后续 attempt 解析优先使用 Agent ID/canonical path 和 StateStore 当前 attempt。
- 未映射时如实降级，不把未知关系描述成已关联。
- 目标明确映射到 governed task 时执行完整通信格式和生命周期校验；目标属于 unmanaged Agent或无法映射到治理任务时，原生通信兼容放行并记录有限诊断，不创建虚假的 task 关联。

### SG-F03-08 默认暂停的过度设计

- 不创建独立 PreparedCommunication 文件、目录或长期协议；只在现有 StateStore 中保留单目标唯一、短期存在的 `pending_action`。
- 不默认引入 `communication_id`。
- 不建立“已送达”“已阅读”“已处理”等平台无法证明的状态。
- 不为普通 `send_message` 单独建设复杂 PostToolUse 状态机。
- `pending_action` 不保存完整 message、通信历史或投递确认；只有真实重复、乱序或冲突事件证明简单方案不足时，才增加更多通信持久化。

### SG-F03-09 待验证

- 真实 `send_message/followup_task` 的公开参数和 Hook 可见边界。
- follow-up 原生响应字段。
- 重复或迟到 follow-up 的实际事件形态。
- 断流、等待、对账、同 Agent 恢复和二次失败决策的真实链路。

## 八、SG-F04 稳定发布、安装与兼容缓存治理

### SG-F04-01 功能职责

把已经验证的开发版本可追溯地交付到稳定发布源、Personal Marketplace 和当前运行缓存，并在升级失败时保留上一实际版本。

### SG-F04-02 发布身份

- Manifest 完整版本是缓存身份。
- 发布候选应绑定明确提交和 tag。
- 开发仓库、稳定发布源和运行缓存必须是独立普通目录。
- 不使用符号链接连接三层目录。
- 不从目录排序猜测上一版本。

### SG-F04-03 发布门禁

发布前至少核对：

1. 工作树和候选提交。
2. Manifest 版本和 cachebuster。
3. 单元测试和 Python 编译。
4. Plugin validator。
5. Skill validator。
6. 用户裁决（2026-08-11）：仅在 Hook/运行时脚本、文件路径与权限、所有者或符号链接处理、原子写入、安装/重装/缓存/回滚脚本、外部命令调用或输入边界发生变化时，执行针对本次变更及其直接数据边界的安全检查。纯文档、UI 元数据或非安全相关测试变更记录为 `not_applicable`，不要求重复全仓审计。
7. 稳定副本内容哈希。
8. 真实加载验收计划。

仓库测试通过不等于发布完成。

安全检查属于开发发布流程，不进入插件运行时，也不验收子 Agent 的业务安全性；不建设漏洞管理平台、长期安全数据库、签名证明或自动风险评分。发布证据只记录是否适用、实际检查范围、发现的问题和处理结果。

### SG-F04-04 稳定副本与 Marketplace

- Personal Marketplace 继续指向与开发仓库隔离的稳定源。
- 重装使用原生 `codex plugin add`，不建立第二套插件管理器。
- `check_installation.py` 只读区分运行健康、部署同步、开发同步、保留策略和发布就绪。
- Marketplace enabled、来源和 CLI 字段应使用受支持的结构化接口；字段未知时报告 unknown，不猜测。

### SG-F04-05 N/N-1 回滚缓存

- 用户裁决（2026-08-11）：N-1 继续只作为新版整体回滚资产，不建设显式状态版本迁移协议；但活动任务是否可继续不再由插件版本决定，而由每次交互所需字段是否齐全决定。N或N-1处理数据时都只执行当前操作的结构校验，不读取或比较协议版本。
- 当前版本 N 和升级前实际版本 N-1 继续作为发布与回滚资产保留，不建立版本数据库或兼容矩阵。
- 重装前显式确认上一版本，不按目录名排序猜测。
- N-2 及更旧缓存只是清理候选。
- 升级前不再要求活动任务数量为零，也不因其来自旧缓存而阻止升级；只对运行中、待恢复、待验收和其他 `action_required` 记录执行目标运行时所需字段的结构预检。缺少必要字段时列出缺项并要求补充或明确处置，字段齐全时允许继续。
- 删除旧缓存前必须确认目标版本真实加载、回滚窗口已结束且没有任务引用该缓存。
- 缓存保护不能被描述为已经证明所有历史数据都可用；兼容性只能由实际交互的字段校验结果说明。

### SG-F04-06 最小全局入口

- 全局 `AGENTS.md` 只保留按需加载 Skill 的最小入口。
- 完整等待、恢复、终态和诊断规则应放在 Skill 或共享语义源中。
- `apply_agents_block.py` 只修改受管理标记区间，保护用户其他内容、所有者、权限、符号链接和并发修改。
- 用户裁决（2026-08-11）：用户明确执行安装命令即视为授权初始化最小全局入口，不再额外询问。`AGENTS.md` 不存在时创建普通文件并只写最小受管理区块；文件存在但没有标记时保留全部原文，在末尾追加唯一受管理区块；恰好一对合法标记时只替换区块内部。多对标记、标记缺失一端或顺序错误、符号链接、所有者异常、权限不安全或并发摘要变化时拒绝修改。`--check` 始终只读，不创建文件或标记；卸载只删除受管理区块，不删除整个 `AGENTS.md`，即使文件因此为空也保留该文件。

### SG-F04-07 真实发布验收

必须分开记录：

- 文件和目录存在。
- 稳定源与缓存内容一致。
- 插件 installed/enabled。
- 当前 Hook 定义 trusted/enabled。
- 新任务加载目标 Skill。
- 代表性生命周期事件真实触发。
- 升级预检确认活动任务具备目标运行时当前操作所需字段；不检查或比较其协议版本。

无法检查的项目记录 `not_checked`，不能默认成功。

### SG-F04-08 回滚和退役

- 回滚恢复上一稳定源、上一入口和 N-1。
- 真实验收失败时不得提交旧缓存清理。
- legacy Hook、稳定备份和旧缓存是不同资产，必须分别确认引用和授权。
- Codex-owned trust 记录不由仓库脚本手工清理。

### SG-F04-09 已确认有效内容

- `scripts/check_installation.py`。
- `scripts/reinstall_preserving_caches.py`。
- `scripts/apply_agents_block.py`。
- `docs/release-process.md`。
- `tests/test_release_tools.py`。

这些文件均有实际职责和测试，不属于无用代码。

### SG-F04-10 过度设计警戒

SG-F04 是支撑功能，不应扩张为独立发布平台。后续方案应优先保留：

- 少量确定性 preflight。
- 原生 CLI 包装。
- 显式 N/N-1 回滚缓存。
- 用户裁决（2026-08-11）：保留单个覆盖式 `last-transaction.json` 作为一次重装的恢复凭证。它只记录上一/目标版本、当前与失败阶段、快照路径及标识、开始/更新时间、命令返回码、已恢复缓存和待清理缓存；每次重装原子覆盖，不积累历史。不保存完整 stdout/stderr、环境变量、用户目录内容或长期命令历史，也不建设事务数据库、事件日志、自动回滚编排器或发布历史查询。该记录只帮助识别中断阶段和恢复快照，不证明新版本已经通过真实验收。
- 真实验收矩阵。

以下内容只有出现真实故障证据后才增加：

- 完整版本数据库。
- 跨步骤分布式事务。
- 长期全历史缓存索引。
- 自建 trust hash 实现。
- 独立 Marketplace 管理器。
- 复杂自动回滚编排器。

## 九、SG-F05 治理状态持久化、等待巡检与异常恢复

### SG-F05-01 功能职责

保存治理任务、Agent 身份和运行健康状态，为等待巡检、平台对账、有限恢复、中断保护和会话恢复提供共享状态底座。

StateStore 的存在是因为各 Hook 调用没有可依赖的共享内存，且主对话历史可能被压缩或因网络失败中断；它只保存跨事件继续治理所需的最小机械事实，不保存完整业务过程。

### SG-F05-02 状态持久化

保留：

- 私有数据目录。
- 普通文件和所有者检查。
- 每个 Session 的稳定 `.lock` 文件、文件锁和原子替换。
- 状态损坏、不可读或超限时的原始数据保全、即时告警和 degraded 健康事实；不得把不可读状态当作合法空状态继续。
- 状态大小边界，以及仅针对已明确关闭 tombstone 和对应结果的精确到期清理；不得恢复通用“终态裁剪”。
- 状态不可用时的告警降级。

需要改造：

- 活跃任务不设固定数量上限；容量使用3 MiB新任务软准入线和4 MiB硬上限，寿命与stale不触发未解决任务自动清理。
- 状态结构需要按当前操作执行最低逐条字段校验；缺项时明确返回缺少的字段，不按版本拒绝或静默补默认值。
- 用户裁决（2026-08-11）：Session 完全闭环后可以按既定规则精确删除状态 JSON、到期 tombstone 和对应结果，但运行时不自动删除该 Session 的 `.lock` 文件。锁文件是稳定的并发互斥入口，不保存业务数据；删除后重建可能使已经打开旧 inode 的进程与使用新文件的进程分别取得锁，破坏互斥。不得建设“检测无人持锁后自动删除”的竞态回收流程；只有未来出现真实容量问题时，才考虑在明确停止相关进程后的独立人工维护工具。
- StateStore 只保存恢复和验收同一任务所需的最小摘要，不复制完整 dispatch prompt 或 PreparedContract；摘要至少覆盖目标、范围、完成条件、有界 `evidence_requirements[]`、Agent映射、task/attempt/task_ref 和下一恢复动作。实际 `evidence[]` 只存在于正式 result 文件。
- 新治理任务的初始记录必须在 spawn 前完成原子写入和回读验证；容量、权限或当前派发所需字段不满足时拒绝派发。该硬门禁不追溯阻断已经存在的 Agent。

用户裁决（2026-08-11）：目标顶层只保留 `session_id`、任务集合、Agent 映射、可选轻量 group 集合、组件健康和 `updated_at` 等当前读取必需信息；不再写入或强制改写 StateStore 协议版本字段。任务/attempt 记录按 U-05 的最小职责保存，不内嵌完整结果、完整消息、完整平台对象或历史事件。新建空状态时可以生成结构所需字段；读取已有状态时缺少当前操作必需字段必须明确报缺项，不能用 `setdefault` 等方式静默补成看似有效的数据。

状态 JSON 损坏、非 UTF-8 或根结构非法时，运行时必须保留原文件作为人工恢复证据并返回读取失败；不得像当前实现一样把原文件移动后返回新的空状态，使未解决任务消失。已经存在的 Agent后续通信和最终回复仍按 fail-open 边界放行，但不得声称状态转换已记录；Stop 按已确定的三次读取失败规则阻止无证据结束。是否额外复制诊断备份只有出现真实需要后再决定，不自动创建一份新的权威状态。

用户裁决（2026-08-11）：StateStore不设置固定任务数量上限，避免插件替Codex限制Agent数量；单Session状态文件继续使用4 MiB硬上限，并以3 MiB作为新治理任务的软准入线。预计写入新任务后超过3 MiB时拒绝新派发并提示先处置已有任务，剩余约1 MiB只供已有任务写入身份、平台观察、恢复计数、正式结果引用、父Agent验收、明确关闭和tombstone。不得为了腾空间删除、截断或隐藏任何 action-required 任务；完整结果和大段证据写入独立result文件，StateStore只存有界摘要和引用。已有任务更新仍会超过4 MiB时不得覆盖原文件，记录state-degraded并进入manual review；原生通信或最终回复遵循既定fail-open边界，Stop继续执行三次读取失败后的用户决策规则。已关闭tombstone到期后按既定精确清理自然释放空间，不增加后台清理器。

### SG-F05-03 身份绑定与启动确认

- 派发、通信、平台对账和终态共用同一任务—Agent 关联。
- Agent ID/canonical path 一旦可靠绑定，就成为同一 Agent跨 attempt 的主身份；task name 短引用退回为初始/迟到 spawn 绑定线索，不能覆盖 StateStore 已明确的当前 attempt。
- `SubagentStart` 只确认身份和执行边界，不复制完整业务契约。
- 身份确认完成后，原子写入最小恢复摘要并删除完整 PreparedContract；删除失败记录降级告警，但不得把完整 PreparedContract 和 StateStore 摘要长期并列为两份权威契约。
- 终态不能被迟到启动事件复活。
- 用户裁决（2026-08-11）：删除 `dispatched` 生命周期状态。原生 spawn 调用结果记录为 `spawn_observation=success|failed|unknown`，Agent 身份单独记录为 `identity_status=unconfirmed|confirmed`。
- PreparedContract 绑定后保持 `execution_status=not_started`；只有取得可靠 Agent 身份或收到 `SubagentStart` 后，`execution_status` 才进入 `running`。原生调用未明确失败但身份未确认时不得写成 running。
- `spawn_observation=failed` 必须表示有可靠证据确认本次没有创建 Agent。首次 failed 设置 `parent_action=retry_spawn` 并允许自动重派一次；自动重派再次 failed、`spawn_retry_count=1` 时设置 `parent_action=ask_user`；用户授权最后一次重派后原子增加到2并设置 `parent_action=retry_spawn`。第二次重派仍 failed 时机械关闭该 attempt、生成 tombstone，并把原 task 转为 `parent_action=decide_disposition`，不写业务 failed。
- `spawn_observation=unknown + identity_status=unconfirmed` 设置 `parent_action=reconcile` 且不得自动重派；只有 task name 中的现有 task 短引用能够唯一解析到 PreparedContract 时，迟到 `SubagentStart` 才能精确绑定并进入 running。无法精确解析时继续对账并保持 `action_required`。
- `spawn_observation=success + identity_status=unconfirmed` 保持 `execution_status=not_started + parent_action=reconcile`；原生调用成功本身不能提供可供 `wait_agent` 或目标范围 `list_agents` 使用的可靠 Agent target，也不能提前写 running。只有取得可靠身份或收到精确 SubagentStart 后，才写 confirmed/running/normal/wait。
- unknown 后经显式授权创建替代执行时，新 Agent属于新 attempt；旧 attempt 不因替代派发而变成 failed 或 closed。旧 Agent若迟到出现，仍按自己的 task 短引用绑定旧 attempt，并触发重复执行处置，不能夺取当前 attempt 身份。
- 创建替代 attempt 后，旧 unknown attempt 的完整 PreparedContract 删除，只在 StateStore 保留 task_ref、身份待确认状态和迟到绑定所需最小映射；新 attempt 使用自己的短期 PreparedContract。
- 当同一 task 的两个或更多尚未处置 attempt 确认形成重复执行时，记录 `duplicate_execution=true` 并把父任务动作设为 `resolve_duplicate`。该状态要求立即向用户或有权限的父 Agent展示全部候选并请求选择，不进入普通 20 分钟等待循环，也不由 Hook 自动调用 `interrupt_agent`。
- pending action 已经清理后到达的迟到 `SubagentStart`，只有在精确 Agent/attempt 与 `last_lifecycle_operation` 匹配、`operation_type=platform_recovery|result_correction|business_resume`、调用观察为 success 或 unknown、attempt 未关闭/中断且没有正式结果时才确认启动；确认后消费并删除该最小记录。failed 观察后的启动只进入 reconcile，不直接切换 running；`operation_type=interrupt` 永远不能作为重新启动授权。
- 选择保留某一 attempt 时，在同一锁内把任务的 `current_attempt` 切换为所选 attempt，并把其余所有未关闭候选 attempt 标记为 `duplicate_not_selected`；同时关闭其中所有非运行候选并分别生成7天 tombstone。任一步持久化失败时整个选择事务失败，不得中断任何 Agent，也不得留下部分关闭状态。所选 attempt 已有合法结果时，在重复状态完全解除后进入该结果的父验收流程。
- 选择事务成功后，父 Agent显式中断仍在运行的全部未选 attempt；入口返回所有精确 Agent target，但不自动调用 `interrupt_agent`。成功中断时复用已保存的选择关闭意图，直接关闭对应 attempt 并生成 tombstone；中断 failed/unknown 时保持未关闭并继续对账。未选 attempt 的已有结果在各自 result 文件中保留到 tombstone 到期，只作为参考，不得自动满足当前任务或切换 current attempt。
- 只有 current attempt 选择已经持久化，且所有未选 attempt 都已可靠关闭后，才能清除 `duplicate_execution`。任务最终关闭时，每个重复 attempt 都必须已经具有独立关闭记录和 tombstone，防止迟到事件复活。
- 删除语义同名、同轮和唯一候选猜测；保留 task name 短引用作为稳定引用在启动事件中的可观察载体。
- Stop、SessionStart 和诊断通过执行、派发观察和身份观察三个维度说明“调用已发生但身份未确认”，不再依赖一个混合状态；success 与 unknown 的未确认身份 attempt 都必须保留为 `action_required`，不能因为原生调用返回 success 而从恢复摘要或结束保护中消失。

### SG-F05-04 父 Agent 等待与巡检

- 父 Agent 保存目标 Agent ID/canonical path。
- 正常执行期间只等待终态，不反复读取代码、Git、日志或测试猜测进度。
- mailbox 明确错误时立即目标对账。
- 只有正常等待满约定时长才进行一次巡检。
- Agent 仍正常运行时继续等待，不发送心跳。
- Hook 不实现定时器或自动巡检。

### SG-F05-05 平台状态对账

- 只消费显式 `list_agents` 结果。
- 普通平台状态只更新最近观察，不改变业务状态。
- 明确 `errored` 才记录 `platform_observation=error`，同时把当前执行从 `running` 改为 `stopped`；`business_result` 保持 JSON `null`，不能形成假运行或伪造业务终态。
- 未知响应必须降级为 unknown，不递归猜测任意字段。
- 错误摘要必须有界且不保存敏感大对象。

### SG-F05-06 同 Agent 有限恢复

- 首次可恢复平台错误优先 `followup_task` 同一个 Agent。
- 恢复请求、原生调用成功、Agent 再次启动和业务完成是四个不同事实。
- 恢复请求和原生调用成功期间继续保持 `execution_status=stopped`；只有同一 Agent再次触发 `SubagentStart`，且当前 `pending_action=platform_recovery`、没有正式业务结果时，才恢复为 `running`。
- 恢复需原子认领，防止并发双恢复；认领成功后立即增加 `recovery_count`，再调用原生 `followup_task`。调用结果另存为 `success | failed | unknown`，不得因调用失败或结果未知而回退计数；只有实际调用前的机械校验失败不消耗预算。
- 第一次恢复调用 success 时保持 `execution_status=stopped + platform_observation=error + recovery_status=null + parent_action=wait`；调用 unknown 时保持 stopped/error/null，设置 `parent_action=reconcile`、保留 success/unknown `last_lifecycle_operation` 并禁止再次自动恢复；调用明确 failed 时写 `recovery_status=awaiting_authorization + parent_action=ask_user`。第一次恢复成功启动后再次平台错误时同样停止自动恢复，记录 awaiting authorization；`business_result` 始终保持 JSON `null`。用户明确授权并原子认领后，清除 awaiting authorization，允许同一 Agent、同一 attempt 再恢复一次，`recovery_count` 增加到2；由两阶段 `pending_action` 和原生调用观察表达本次恢复仍在处理。最后一次调用 unknown 时设置 `recovery_status=null + parent_action=reconcile`，保留 success/unknown `last_lifecycle_operation` 并禁止再次发送恢复请求；匹配的迟到 `SubagentStart` 到达时以更强平台事实为准，进入 running，同时写 `platform_observation=normal`、最新观察时间/来源、`recovery_status=null` 和 `parent_action=wait`，再消费该记录，`recovery_count` 仍为2。最后一次调用明确 failed，或恢复启动后再次被 `list_agents` 确认为 errored 时，才写 `recovery_status=exhausted + parent_action=ask_user` 并禁止继续恢复该 Agent/attempt。
- 如果已经写为 exhausted 后又到达与最后一次 success/unknown 恢复操作精确匹配的迟到 `SubagentStart`，同样以真实启动事实为准，写 `execution_status=running + platform_observation=normal + recovery_status=null + parent_action=wait`；但该 attempt 的恢复预算仍已用完，之后再次出现平台错误时直接回到 exhausted，不允许第三次恢复。
- 普通平台恢复继续原 attempt，只增加 `recovery_count`；不得因为一次断流和 follow-up 就创建新的业务 attempt。
- StateStore 中的恢复摘要只保存恢复同一任务所需的最小进度，不新增独立 checkpoint 存储，也不复制整个历史对话。

### SG-F05-07 主动中断

- `interrupt_agent` 是显式关闭执行的生命周期动作。
- 中断目标必须来自父 Agent或用户明确提供的 Agent ID/canonical path；StateStore 不可读时不得通过同名、同轮或候选任务猜测目标。
- 主动中断采用 fail-open：状态读取或写入失败不能阻止对明确 target 的原生中断。调用前可以尽力记录请求，原生调用成功后再尽力写入 interrupted；任一步持久化失败都必须即时告警，明确区分平台调用事实与未可靠记录的治理状态。
- 成功中断进入 `execution_status=interrupted`，父任务不得继续把当前执行视为运行中；这不单独决定治理任务是否关闭。
- 中断成功但 `execution_status=interrupted` 无法持久化时，不得声称任务已关闭，不得自动恢复该 Agent，并在 Stop、SessionStart 或状态恢复后要求人工对账。
- 中断失败保持原状态，不自动重试；是否再次尝试由父 Agent或用户决定。
- 中断调用 unknown 时同样保持原 `execution_status`，不能写 interrupted；设置 `parent_action=reconcile`，在现有 `last_lifecycle_operation` 保存 `operation_type=interrupt`、精确 target、原因和 `call_observation=unknown`，禁止自动再次中断。
- unknown 后收到明确 success 才进入 interrupted；目标范围对账仍为 running 时保留 unknown 调用证据并设置 `parent_action=ask_user`，由用户选择再次中断或允许继续。目标已 stopped/completed 时不倒推中断成功，按真实 Stop 和正式结果处理；目标 errored 时记录 `platform_observation=error`，但不自动恢复，改为 `parent_action=ask_user`，由用户决定恢复或关闭。
- 需要记录目标 attempt、原因、发起者和最小处置意图。用户放弃/取消或父 Agent明确完成处置时，才可同步写入关闭/tombstone；战术中断、换 Agent、资源冲突或待决策中断继续保留 `action_required`。
- 未关闭的中断后续恢复必须创建新 attempt，不能让已停止的 attempt 重新进入 running，也不能覆盖其已有结果。
- 成功中断前已经合法保存的正式结果独立保留；成功中断后才到达的结果不能成为该 attempt 的正式结果，只保留原生回复作为非权威参考。
- 迟到启动或停止事件不能覆盖已确认中断。

### SG-F05-08 Stop 结束保护

- 父任务 Stop 只做一次机械保护，不替父 Agent 业务决策。
- 运行中、已消费但仍在调用对账期的 spawn、`identity_status=unconfirmed + spawn_observation=success|unknown`、明确派发失败重试耗尽和待恢复平台错误应阻止无处理结束；尚未消费且可安全过期清理的初始空 attempt 不得仅因 identity unconfirmed 被误判为已经派发。
- `business_result=complete` 但 `acceptance_status=pending` 的任务仍未闭环，允许父任务结束当前回复去执行验收或向用户报告，但不能从 `action_required` 消失。
- `result_protocol_status=exhausted` 表示没有取得可依赖的正式业务结果，允许父任务结束当前回复进行人工核对，但不得把它当成业务失败、完成或已关闭。
- `business_result=blocked`、`business_result=failed`、`business_result=needs_decision`、`recovery_status=awaiting_authorization` 或 `recovery_status=exhausted` 可以允许父任务结束当前回复并向用户报告，但任务本身仍属于 `action_required`，必须在恢复摘要中保留；一次报告不能隐式关闭任务。
- 用户裁决（2026-08-11）：状态读取失败时，在同一次 Stop 处理中执行“首次读取 + 两次短重试”，总共最多三次；任意一次成功后立即按真实状态继续判断。
- 三次全部失败时停止自动重试并阻止本次 Stop，向父 Agent返回即时的“需要用户决策”，说明无法确认是否仍有运行任务。该提示不依赖已经不可用的 StateStore 持久化。
- 达到上限后不得由父 Agent自动重复触发 Stop；必须询问用户是强制结束，还是先诊断、修复或恢复状态。
- stale 策略必须与 SessionStart/End 和裁剪一致。

### SG-F05-09 SessionStart

- startup、resume、clear、compact 时恢复必要任务摘要。
- 摘要优先展示任务 ID、Agent、状态、目标摘要和下一步。
- 必须分别覆盖已消费 PreparedContract 仍在20分钟调用对账期、派发结果 unknown/身份待确认、明确派发失败重试耗尽、待恢复的 `platform_observation=error`、等待用户授权的 `recovery_status=awaiting_authorization`、最终恢复耗尽的 `recovery_status=exhausted`、等待补交的 `result_protocol_status=needs_correction`、结果纠正耗尽的 `result_protocol_status=exhausted`、中断调用 unknown 的待对账记录、结果存储不可用、`result_conflict=true`、待父 Agent验收的 complete 结果和业务 `business_result=needs_decision`。
- 输出有界并明确未展开数量。
- 不自动调用 Agent 工具，不自动恢复。
- 用户裁决（2026-08-11）：拆分“最近活动”和“仍需处理”两个派生视图。12 小时只用于 `recent_activity` 和 stale 标记，不能让未解决任务退出恢复摘要。
- `action_required` 的主条件固定为：attempt/task 尚未关闭且 `parent_action != null`。此外，`execution_status=running`、已消费但尚未取得 PostToolUse 的 spawn PreparedContract、尚未完成对账的 claimed lifecycle action 等调用进行中状态，即使父动作暂时为 null，也必须进入 `action_required`。因此 retry_spawn、reconcile、recover、correct_result、business_resume、accept_result、ask_user、manual_review、resolve_duplicate，以及身份未确认、平台错误、恢复/纠正耗尽、结果存储不可用、`result_conflict=true`、业务 blocked/failed/needs_decision、complete 待验收和未关闭 interrupted 等场景都由同一规则覆盖，不再依赖容易遗漏的并列长条件。摘要有界展开并显示未展开数量，只有明确关闭或已确认处置使父动作和调用中状态全部解除后才退出。
- 尚未完成对账的 claimed `platform_recovery`、`result_correction` 或 `business_resume` 也进入 `action_required`；`claimed_at` 未满20分钟时显示仍在对账期内，满20分钟仍缺少 PostToolUse 才记为 unknown。不得因为 prepared action 的5分钟规则删除已认领事实或自动重发。
- `business_resume` 调用 success 或 unknown 的新 attempt 都以 not_started 进入 `action_required`：success 使用 `parent_action=wait`，unknown 使用 `parent_action=reconcile`；明确 failed 并以 `resume_delivery_failed` 关闭的 attempt 退出当前执行集合，但原 task 设置为 `parent_action=decide_disposition`，仍需通过新 attempt 或其他显式处置继续闭环。
- complete 结果被父 Agent拒绝时，原 attempt 和结果文件保持不变；后续补充业务工作必须创建新 attempt，不能通过覆盖原 complete 结果伪造验收通过。
- `blocked` 即使已经由父 Agent向用户报告，也不能仅因“已报告”退出 `action_required`；恢复摘要应继续展示阻塞原因、已尝试事项和恢复条件，直到阻塞解除并产生后续 attempt，或用户明确放弃/关闭。
- `failed` 即使已经由父 Agent向用户报告，也继续展示失败原因、证据和建议动作，直到明确接受失败并关闭、放弃，或创建新 attempt 重试。
- 用户裁决（2026-08-11）：stale 任务不设自动关闭或清理期限。即使长期没有新观察，也必须继续恢复提示，直到出现明确处置事件。

### SG-F05-10 SessionEnd

- 主会话结束不等于子任务已经解决。
- 有运行、待恢复、等待平台恢复授权、平台恢复最终耗尽、结果纠正耗尽、complete 待验收、业务阻塞、业务失败、业务待决策或未关闭中断任务时保留状态。
- `action_required` 不使用 12 小时过滤；stale 任务仍保留，等待父 Agent或用户明确处理。
- `business_result=blocked` 属于未解决任务：本次 `execution_status` 可以是 stopped，但 SessionEnd 仍需保留其状态和恢复条件。
- 只有不存在任何 `action_required` 任务且不存在仍在保留期内的 tombstone 时，才在同一锁边界内安全删除 session JSON。
- 不建立归档状态或按时长自动关闭；明确处置统一写为 closed 并进入 tombstone，来源只能是父 Agent验收完成、带有明确关闭意图的成功中断、父 Agent其他显式处置或用户明确放弃/关闭。
- 显式关闭后保留的 tombstone 只保存 `task_id + attempt`、Agent ID/canonical path、task 短引用、最后状态、关闭原因和关闭时间，用于识别迟到事件，不让任务重新进入 `action_required`。
- tombstone 固定保留7天，只在正常 SessionStart、SessionEnd 或状态写入的锁内顺便清理，不建设后台 scheduler，也暂不增加配置项。
- tombstone 的7天时间清理只适用于已经明确关闭的任务，不得复用于 unresolved、stale 或其他 `action_required` 任务。
- 对应 `results/<task_id>-<attempt>.json` 与 tombstone 同步清理；必须精确核对 task 和 attempt，不能用文件名模糊匹配或目录年龄批量删除。
- Session 数据清理不得删除对应 `.lock` 文件，也不能为了清理目录破坏仍被进程持有的锁语义。

### SG-F05-11 实施时必须替换的旧问题

- `dispatched` 当前没有稳定写入者，已决定从目标状态模型删除，并由 `spawn_observation` 与 `identity_status` 取代。
- 删除混合字段 `retry_required`：平台路径使用 `platform_observation/recovery_status`，结果补交使用 `result_protocol_status/correction_count`。
- 删除独立 `platform_error` 状态；平台错误事实只使用 `platform_observation=error`，是否待恢复由 `recovery_status` 和 `parent_action` 表达。
- `needs_decision` 只保留为业务结果；平台自动恢复额度已用完但仍可由用户授权最后一次时使用 `recovery_status=awaiting_authorization + parent_action=ask_user`，最终无法继续恢复时使用 `recovery_status=exhausted + parent_action=ask_user`。
- 原 SessionStart 12 小时窗口拆分为 `recent_activity` 与 `action_required`；时间不再触发未解决任务关闭或清理。
- 删除显式 N/N-1 状态迁移、版本矩阵和按版本拒绝目标；发布流程改为对活动记录执行所需字段的结构预检。
- SubagentStop、follow-up、list 和 interrupt 等并发路径需要锁内 compare-and-set。

当前 `scripts/subagent_governance.py` 的 StateStore 相关实现还必须执行以下具体替换：

- 删除 `STATE_VERSION`、空状态中的 `version` 和读取时强制执行的 `value["version"] = STATE_VERSION`；不以 stored version 判断可读性。
- `_read_path()` 不再通过 `setdefault("tasks", {})`、`setdefault("agents", {})` 或默认 health 静默修补已有状态；按当前操作列出缺失字段，未知额外字段忽略。
- 删除“将损坏/非 UTF-8 状态移动到 `.corrupt-*` 后返回空状态”的恢复路径。不可读状态必须保持不可读事实，不能让 Stop、SessionStart 或诊断误认为没有未完成任务。
- 删除 `_prune_state()` 中 `TERMINAL_RETENTION_SECONDS=30天`、`MAX_TERMINAL_RECORDS=200` 和按数量/时间裁剪通用 terminal 状态的逻辑；只实现明确关闭 tombstone 的7天精确清理，并同步核对对应 result 文件。
- `_handle_spawn()` 创建受治理任务时，StateStore 初始写入或回读失败必须拒绝派发；删除当前“治理状态不可写仍降级放行并仅依赖消息任务 ID”的新任务路径。
- 当前 `TaskContract.to_record()` 直接写入的 `protocol`、`message_visibility`、`child_agents`、旧 `fork_turns` 表达和其他正文解析遗留字段按最终 Schema 删除或替换；只保留当前 attempt 恢复、显示和机械状态转换真正需要的字段。显式 model/reasoning effort 和规范化 context strategy 只有在当前 attempt 实际提供或恢复需要时保存。
- 当前 `tool_use_id`、`turn_id` 和首次 task name 只在完成派发关联、幂等和迟到身份绑定所需期间保留；身份确认后收缩为 `task_id + attempt + task_ref + Agent ID/canonical path` 主关联，不作为长期业务档案。
- 删除单一 `status` 字段及其 `ACTIVE_STATUSES/TERMINAL_STATUSES` 混合判断，改为 U-06 已确认的独立状态维度；所有读取者按本次操作需要的维度判断。
- 删除混合 `retry_count`；分别使用 `spawn_retry_count`、`recovery_count` 和 `correction_count`，任一计数不能消耗另一条路径的预算。
- `agents` 映射必须能够定位具体 task/attempt；不能只映射到 task 后再假设当前 attempt，也不能被迟到启动覆盖。
- 当前 `platform_status` 任意对象和重复的 `platform_error` 字段统一收缩为 `platform_observation`、观察时间、来源和有界摘要；不保存完整原生响应，也不解析错误文本推断 Provider 根因。
- 当前仅保存 `interrupt_tool_use_id` 的做法替换为目标 attempt、精确 target、机械调用观察、原因、发起者和最小处置意图；中断 unknown 复用每 attempt 唯一的 `last_lifecycle_operation` 对账，不自动重试、不提前写 interrupted，中断本身也不自动关闭治理任务。
- 删除内嵌且截断的 `result_document`、固定空 `evidence/remaining` 和 `protocol_errors` 旧终态路径；StateStore 只保存 result 文件引用、结果/验收/协议/存储状态和父动作。
- 增加当前实现尚缺少的两阶段 `pending_action`、多 attempt 并存与迟到绑定信息、重复执行标记、最小 tombstone 和轻量 group 记录；这些都必须复用同一 StateStore，不新增独立数据库或历史表。
- 所有写路径继续使用稳定 `.lock`、锁内 compare-and-set、原子替换、3 MiB新任务软准入线和4 MiB硬上限；超过边界时不得截断、删除或隐藏 action-required 任务。

### SG-F05-12 StateStore 改造验收

后续实现至少验证：

- 新受治理 spawn 在 PreparedContract 或初始 StateStore 写入、回读、容量和必需字段任一步失败时被发送前拒绝；unmanaged 原生调用继续兼容放行。
- 新受治理 spawn attempt 的初始观察、结果、验收、存储、恢复和父动作字段使用已确认的 null/初始枚举，三个独立计数均为0；未消费 PreparedContract 满5分钟后与对应初始空 attempt 一起精确删除且不生成 tombstone。
- task ref 碰撞按12至32位有界扩展；32位仍冲突时只允许在任何持久化之前重新生成一次 task ID，第二个 task ID 仍冲突则明确拒绝，既有 task/attempt 的引用永不改名。
- PreparedContract 被 PreToolUse 消费时保存 `tool_use_id + claimed_at`；缺少 PostToolUse 未满20分钟时保持 null 并显示调用对账中，满20分钟后稳定转为 `spawn_observation=unknown + identity_status=unconfirmed + execution_status=not_started + parent_action=reconcile`，不自动重派或删除迟到绑定凭证。
- 已有状态缺少当前操作必需字段时逐项报告，未知额外字段被忽略；不会读取版本门禁、静默补默认值或改写版本。
- 损坏、非 UTF-8、非普通文件、所有者异常和超限状态不会被当作空 Session；原始文件保持可供人工检查，Stop 执行三次读取失败规则。
- 已存在 Agent遇到 StateStore 写入失败时，原生通信和最终回复按 fail-open 边界继续，但状态转换、计数和验收不得伪装成已经保存。
- 明确 target 的 `interrupt_agent` 在 StateStore 故障时仍能执行；平台成功而状态落盘失败时产生即时 degraded 告警，不自动恢复、不伪造 interrupted 已持久化，并在后续恢复流程中要求人工对账。
- 多进程并发写入、Agent绑定、恢复认领、结果提交、中断和父 Agent验收使用同一稳定锁与锁内 compare-and-set，不发生覆盖或双恢复。
- 结果提交验证先写并回读 result 文件、再更新 StateStore；模拟两个提交阶段之间中断时，不出现 StateStore 指向不存在文件的假正式结果。已写 result 文件但 StateStore 未关联时能够按精确 task/attempt 有界恢复，不覆盖不同内容的已有结果。
- 同一 attempt 的不同合法结果不会覆盖原文件或创建候选结果库；StateStore 保持原业务/协议/存储/验收状态，写入 result_conflict、冲突摘要、发现时间和 manual_review。相同冲突重放幂等，现有父处置或新 attempt 创建能原子清除冲突，失败时保持 action-required。
- 3 MiB软准入线只阻止新治理任务，4 MiB硬上限不覆盖原文件；任何 action-required 任务都不会因时间、数量或容量被裁剪。
- 只有明确关闭且满7天的 tombstone 及其精确 result 文件被同步清理，Session JSON 清理后 `.lock` 文件仍保留。
- 多 attempt、旧 unknown Agent迟到、重复执行和结果冲突均保持独立身份与结果地址；Agent映射不能把旧 attempt 绑定成当前 attempt。
- 连续多次 unknown 经逐次明确授权后可以形成三个或更多 attempt；重复执行选择必须展示全部候选、只选一个 current，并把其余所有候选标记为 duplicate_not_selected，不能退化为固定二选一逻辑。
- select_attempt 在一个原子事务中选择 current、关闭并 tombstone 全部非运行未选候选，同时返回全部运行未选候选的精确中断 target；这些 Agent只有中断 success 后才依据选择意图关闭，failed/unknown 不提前关闭。全部未选候选关闭前 duplicate_execution 不得清除，且不新增 close_attempt。
- StateStore 不再包含完整 prompt、完整消息、完整平台响应、内嵌完整结果、固定空证据、版本迁移字段或事件历史。
- prepared `pending_action` 的5分钟过期、claimed action 满20分钟后的 unknown 对账、单目标唯一性、result引用、父验收状态、轻量 group 派生以及 SessionStart/action-required 恢复摘要均使用最小字段正常工作。
- lifecycle pending action 清理后保留的最小 `last_lifecycle_operation` 能够确认 platform recovery、result correction 或 business resume 的 success/unknown 调用所对应的迟到 SubagentStart，确认后删除；failed 调用后的启动进入 reconcile，且普通消息不会污染该记录。interrupt/unknown 复用同一最小记录进行中断结果对账，但绝不能授权 stopped/not_started → running。
- interrupt success、failed 和 unknown 分别进入 interrupted、保持原状态或保持原状态并 reconcile；unknown 不自动重试，对账仍 running 或 errored 时进入 ask_user，stopped/completed 时按真实 Stop/结果处理，不能倒推中断成功。
- 第一次 platform recovery 的 success、unknown 和 failed 分别保持 stopped/error 并映射为 wait、reconcile 或 awaiting_authorization/ask_user；只有精确 SubagentStart 能进入 running/normal，第一次明确 failed 或恢复启动后再次 errored 才允许用户授权第二次也是最后一次恢复。
- same-Agent business resume 为 unknown 时，替代 attempt 必须 spawn 新 Agent；测试旧 Agent迟到启动和新 Agent正常启动能够分别绑定旧、新 attempt，不依赖 current attempt 或时间顺序猜测。
- same-Agent business resume 的 success、unknown 和 failed 分别保持 `not_started + wait`、`not_started + reconcile`，或以 `resume_delivery_failed` 关闭新 attempt 并把原 task 转为 `decide_disposition`；只有精确 SubagentStart 能把 success/unknown attempt 改为 running。
- result correction 的 success、unknown、第一次 failed、第二次 failed 和补交启动后再次无合法结果，分别稳定映射为 wait、reconcile、correct_result、exhausted/manual_review，或按剩余次数选择 correct_result 与 exhausted/manual_review；success/unknown 不会被自动重发，合法结果可以先于启动事件到达并正常保存。
- 多 attempt task 的 `close_task` 使用 expected current attempt 做 compare-and-set，但实际枚举并关闭整个 task；任一 running attempt 都会返回精确中断目标并阻止关闭，全部非运行 attempt 成功生成 tombstone 后才退出 action-required。
- `accept_result` 复用同一整 task 关闭过程；验证旧 unknown/stopped attempt 会生成 tombstone、任一 running attempt 会阻止 accepted，并且 StateStore 不会出现 accepted 与未关闭 task 的半完成组合。
- spawn 首次 failed、自动重派 failed、用户授权最终重派、任意 unknown、success 未绑定、精确 SubagentStart 和最终 failed 分别写入 retry_spawn、ask_user、reconcile、reconcile、wait 或 decide_disposition，不产生假 running 或业务 failed；success/unknown 且身份未确认的 attempt 都进入 action-required，并由 Stop、SessionStart 和诊断保留。

当前测试中要求 `.corrupt-* + corrupt-state-recovered + 继续派发`、StateStore 写入/初始化失败时受治理 spawn fail-open、以及 `MAX_TERMINAL_RECORDS` 通用裁剪的用例必须删除或改写为上述目标行为；不能把现状错误重新固化成兼容要求。

### SG-F05-13 不应新增

- 后台 scheduler。
- Hook 自动 `wait_agent`。
- Hook 自动 `list_agents`。
- 无限恢复。
- 全量 transcript 重建。
- 为理论竞态预建复杂事件数据库。

## 十、SG-F06 子 Agent 终态结果协议、验收与父任务闭环

### SG-F06-01 功能职责

把单个子 Agent 明确提交的完成、阻塞、失败和业务需要决策保存为完整、可引用的正式结果，交给父任务验收，并为用户摘要提供关键输入。平台错误、spawn 失败、主动中断、结果协议纠正耗尽和结果存储故障只记录机械状态与父任务下一步，不由插件生成正式业务结果。

### SG-F06-02 统一结构化结果

用户裁决（2026-08-11）：采用“结构化结果是唯一正式结果”的方案。中文终态卡不再承担独立的数据来源或 Hook 阻断职责。

所有治理等级共用同一结果结构，至少包括：

- `task_id`。
- `attempt`。
- `business_result`。
- `result`。
- `evidence[]`。
- `remaining[]`。
- `suggested_parent_next_step`。

用户裁决（2026-08-11）：正式结果中的 `suggested_parent_next_step` 只表示子 Agent 根据业务结果生成的自然语言建议，供父 Agent参考，不控制任务生命周期；StateStore 中的 `parent_action` 继续表示状态机根据已持久化事实确定的权威待执行动作。两者不得自动互相覆盖，父 Agent可以忽略子 Agent建议并依据实际情况作出显式处置。结果生成器只检查 `suggested_parent_next_step` 是否存在、类型是否正确以及长度是否合理，不机械判断建议内容是否正确。

用户裁决（2026-08-11）：正式结果不再使用含义宽泛的 `status`，统一使用 `business_result=complete|blocked|failed|needs_decision`。合法结果持久化后可直接写入 StateStore 的同名业务结果维度，不再建立 `status → business_result` 的额外映射；`execution_status`、`acceptance_status`、`result_protocol_status` 等继续分别表达执行、父 Agent验收和结果协议状态。

用户裁决（2026-08-11）：StateStore 中 `business_result` 字段固定存在且允许为 JSON `null`；`null` 只表示当前 attempt 尚未取得合法正式业务结果。只有合法结构化结果成功保存后，才能将其写为 `complete | blocked | failed | needs_decision` 之一。不增加 `unset` 或 `unknown` 业务结果枚举。正式 result 文件只有在业务结果非空且合法时才创建，因此其中的 `business_result` 不允许为 `null`。平台错误、派发失败、主动中断、结果协议纠正耗尽和结果存储故障都不能自行把该字段改成业务枚举。

正式 result 文件只由子 Agent 合法提交的 `complete | blocked | failed | needs_decision` 业务结果产生。机械异常发生时，StateStore 的 `business_result` 保持 JSON `null`；如果异常发生前已经存在合法业务结果，该结果独立保留，但异常本身不创建或覆盖正式结果。

分场景字段：

- blocked：`blocker`、`attempted[]`、`required_to_resume`。
- failed：`failure_reason`、`attempted[]`、`retry_conditions`；字段内容由子 Agent根据真实业务情况填写。
- 业务 needs_decision：`decision_question`、`options[]`、`recommendation`；只有子 Agent真实提交业务选择问题时使用。
- 平台错误、spawn 失败、中断、结果协议纠正耗尽或结果存储故障：只在 StateStore 保存机械事实和父任务动作，不由脚本编造业务结果或创建正式 result 文件。

平台恢复等待用户授权、最后一次调用 unknown 对账或最终耗尽都不生成正式的 needs_decision 结果文件；它保留最后一次合法业务结果（如有），并分别使用 `recovery_status=awaiting_authorization + parent_action=ask_user`、`recovery_status=null + parent_action=reconcile` 或 `recovery_status=exhausted + parent_action=ask_user` 表达机械下一步。

业务字段由 AI 填写，脚本不自动总结。

用户裁决（2026-08-11）：合法的 blocked 结果可以结束当前子 Agent attempt，但不能关闭治理任务。父 Agent报告 blocker 后，该任务仍保留在 `action_required`；阻塞条件解除后基于原 `task_id` 创建后续 attempt，只有后续完成或用户明确放弃/关闭才结束该待处理责任。

同样地，业务 `needs_decision` 结果结束当前 attempt；用户提供选择后继续原任务时，基于原 `task_id` 创建新 attempt。平台自动恢复额度用完并进入 `awaiting_authorization` 时没有生成业务结果；用户选择使用最后一次恢复且仍使用原 Agent时可以沿用原 attempt。最后一次调用 unknown 时先 reconcile 并等待迟到启动，不直接视为 exhausted；明确失败或恢复后再次 errored 并进入 `exhausted` 后，继续业务必须创建新 attempt，并按需要更换 Agent、模型或 Provider，不能在原 attempt 上继续重试。

合法的 failed 结果也结束当前 attempt，但治理任务保持待处理。父 Agent或用户选择重试时，基于原 `task_id` 创建新 attempt；选择接受失败、放弃或关闭时，记录显式处置后退出 `action_required`。

### SG-F06-03 治理等级只影响证据强度

- `light` 可以简洁，但必须有实际结果。
- `standard` 应提供结果、验证或证据和剩余事项。
- `strict` 要求更完整的结构化证据；生成器可以将同一份结果渲染为固定中文终态卡供人阅读。
- 三档不建立三套结果 Schema。
- Hook 只校验结构化结果、任务引用和状态，不解析或验收 strict 中文终态卡；终态卡格式错误只触发展示文本重新渲染。
- `auto` 解析完成后只使用实际等级；auto 解析为 strict 时，与显式 strict 使用相同的结构化证据要求和固定中文终态卡渲染。
- `requested_mode=auto` 只用于审计和用户说明；终态 Schema、证据强度、展示渲染和 Hook 生命周期判断只读取 `resolved_mode`。
- 结果验收读取结果所属 attempt 的 `resolved_mode`，不能使用 Agent首次 task name 中可能已经过时的等级。
- 三种等级的正式结果都要求 `evidence[]` 字段存在且为有界数组，但允许为空；不得用非空数量代替证据充分性判断。standard/strict 的生成指令和 attempt 契约仍携带相应 `evidence_requirements[]`，实际证据是否满足这些要求由父 Agent验收。

### SG-F06-04 SubagentStop 机械验收

只检查：

- Agent—任务映射。
- `task_id + attempt` 绑定。
- 必填、类型、枚举、长度和数组边界。
- 当前执行是否允许提交结果。
- 状态转换是否合法。
- 结果文件是否存在、可读和属于当前任务。
- 写入时锁内再次核对旧状态，防止覆盖已确认中断或已有正式结果。`platform_observation=error` 只是独立的平台观察事实，不能单独阻止同一 Agent、同一 attempt 的合法首次结果提交。

不检查：

- 结果是否“看起来足够长”。
- 是否包含证据关键词。
- `evidence[]` 是否非空或数量是否“足够”。
- 业务判断是否真实。
- 是否采用固定自然语言措辞。
- task ID 是否出现在正文。

因此，即使 strict 中文终态卡缺少某一展示行，只要权威结构化结果字段完整且引用合法，SubagentStop 仍接受该结果；展示层随后从权威数据重新生成终态卡。

SubagentStop 接受 `business_result=complete` 后只设置 `acceptance_status=pending`，不能代替父 Agent把它写为 accepted。这里的机械接受表示“结果协议合法”，不表示“业务目标已经验收通过”。

任一合法业务结果通过机械检查时都设置 `result_protocol_status=valid`；只有 complete 同时进入 `acceptance_status=pending`，其他业务结果的 `acceptance_status` 保持 `null`。

### SG-F06-05 有限纠正

- 用户裁决（2026-08-11）：保留有限结果补交。只在子 Agent能够修正的结构缺失、非法枚举、任务引用不匹配、未调用结果生成器或生成器因业务参数拒绝写入时，恢复同一个子 Agent并明确告知需要修正的机械字段。
- 如果结构化结果参数已经合法，但结果目录、原子写入、文件读取或存储代码自身失败，则属于结果存储降级，不进入补交链。
- 补交只重新生成结构化结果，不重新执行业务任务；原任务的工作成果、Agent 身份和上下文继续保留。
- result correction 被认领并发送给同一 Agent后，允许原 attempt 从 stopped 重新进入 running，但该运行权限只覆盖结果生成与提交；不得修改业务成果或把补交伪装成新的业务执行。
- 子 Agent尚在当前执行中时，结果生成器因字段、类型、枚举或其他机械参数错误而拒绝写入，子 Agent可以在本轮直接修正，不消耗 `correction_count`。只有 SubagentStop 时仍未取得合法结果、父 Agent需要真正发送 `result_correction` 时，才进入运行时纠正预算。
- SubagentStop 时仍未取得合法结果且补交预算尚未耗尽，写 `result_protocol_status=needs_correction + parent_action=correct_result`；该状态只说明需要机械补交，不生成业务结果。
- `result_correction` 在完成调用前机械校验并原子认领时增加 `correction_count`；原生 follow-up 的 success、failed 或 unknown 都不回退次数，`SubagentStart` 和后续结果提交也不重复计数。success 保持 `execution_status=stopped + result_protocol_status=needs_correction + parent_action=wait`，等待同一 Agent、同一 attempt 的精确启动或合法结果；unknown 改为 `parent_action=reconcile`，保留 lifecycle 记录且不自动重发；明确 failed 时，`correction_count=1` 重新进入 `parent_action=correct_result`，`correction_count=2` 进入 `result_protocol_status=exhausted + parent_action=manual_review`。
- 用户裁决（2026-08-11）：所有治理等级统一最多补交两次，不再使用 light 一次、standard/strict 两次的分级预算；第三次仍不合法时记录协议问题并交给父任务。
- 第三次仍不合法时设置 `result_protocol_status=exhausted + parent_action=manual_review`，停止自动恢复子 Agent；不得据此生成业务 failed、blocked 或 needs_decision。
- 用户裁决（2026-08-11）：`result_protocol_status=exhausted` 只禁止继续发送新的 `result_correction`，不永久禁止接收同一 Agent、同一 task/attempt 的合法迟到结果。迟到提交通过结构、身份、attempt、关闭状态和冲突检查后，仍按固定结果提交顺序保存；成功后将协议状态改为 `valid`，写入对应业务结果、存储状态、验收状态和父动作。已经消耗的 `correction_count` 不回退、不减少，也不因迟到结果重新启动 Agent。
- 父 Agent可以依据原生最终回复和实际工作进行人工核对、保留原记录并创建新 attempt，或请求用户决定；但不得据此代替子 Agent生成正式结构化结果。没有取得合法结构化结果时，当前 attempt 保持没有正式业务结果。
- 平台恢复次数和结果纠正次数必须分开。
- 相同结构化结果重放不重复消耗预算。
- 补交成功只表示结果协议已经修正，父 Agent仍需独立验收业务结果。
- 补交启动后再次停止仍没有合法结果时，若 `correction_count<2` 则保持 `needs_correction + parent_action=correct_result`；若 `correction_count=2` 则进入 `exhausted + manual_review`。合法结果先于 SubagentStart 到达时按正常结果提交处理，并删除匹配的 pending/last lifecycle operation。

### SG-F06-06 完整结果保存

- 当前 `result_document.result` 的 600 字符静默截断必须退出正式结果路径。
- 完整结果保存到 `results/<task_id>-<attempt>.json`。
- StateStore 只保存有界摘要和可推导的结果引用。
- `evidence` 和 `remaining` 不得由脚本固定为空数组。
- `evidence[]` 可以由子 Agent根据真实情况提交为空；脚本只检查字段存在、数组与条目类型、单项长度和总量上限，不自动补值，也不因空数组直接拒绝结果。
- 结果文件采用私有路径、原子写入和基本 Schema 检查。
- 用户裁决（2026-08-11）：正式结果使用固定提交顺序，不增加 PreparedResult 或跨文件事务层。结果提交必须在 StateStore 稳定锁内重新核对 task、attempt、Agent绑定、旧结果状态和当前提交资格，完成结构化结果机械校验后，先把 `results/<task_id>-<attempt>.json` 原子写入并重新读取验证；只有结果文件确认存在、内容完整且属于当前 task/attempt 后，才能原子更新 StateStore 中的结果引用、`business_result`、`result_protocol_status=valid`、`result_storage_status=available`、`acceptance_status` 和 `parent_action`。不得先让 StateStore 宣称存在正式结果再写结果文件。
- result 文件已经写入但 StateStore 更新失败时，保留该文件，不删除、不覆盖，也不提前声称 StateStore 已完成关联；输出即时 degraded 告警。后续 SessionStart、状态读取或人工恢复在同一稳定锁内根据精确 `task_id + attempt` 重新读取并验证该文件，内容合法且与现有状态不冲突时补写 StateStore 关联。该恢复只重存已经存在的合法结构化结果，不从自然语言生成结果，不增加后台修复器。
- 同一结果路径已经存在内容相同的合法结果时按幂等重放处理；存在内容不同的合法结果时保留原文件，设置 `result_conflict=true + parent_action=manual_review` 并拒绝覆盖。StateStore 只保存冲突内容的 SHA-256 摘要和首次发现时间，不保存第二份完整结果或历史列表；相同冲突重放幂等。StateStore 更新成功前不得让新内容替换已有正式结果。
- 结果存储故障时保留原生最终回复并输出明确降级告警，记录 `result_storage_status=unavailable + parent_action=manual_review`。如果子 Agent已经提交了合法、内容确定且仍可取得的结构化结果，父 Agent可以在存储恢复后原样重试持久化，不得修改业务字段；否则只能创建新 attempt、请求用户决定或进行其他显式处置，不能根据自然语言回复生成正式结果。result 文件与 StateStore 关联全部成功前，不得宣称当前任务已经拥有可依赖的正式结果，也不提前写入权威 `business_result`。
- 正式结果不作为永久审计档案。只有对应 task/attempt 已显式关闭且7天 tombstone 保留期结束后，才能在同一锁边界内精确删除结果文件；任何 unresolved、待验收、blocked、failed、needs_decision、重复执行冲突或其他 `action_required` 结果都不得按时间删除。

### SG-F06-07 幂等、冲突和迟到结果

最小实现：

- `task_id + attempt` 唯一定位一次执行结果。
- 相同内容的重复提交幂等。
- 已有不同结果时不静默覆盖，保留原结果并向父任务报告冲突；原业务结果、协议、存储和验收状态保持不变，另写 `result_conflict=true + parent_action=manual_review`。冲突候选只留摘要和时间，不建立候选结果库。
- 旧 attempt 的迟到结果不能覆盖当前 attempt。
- unknown 后人工重派产生的新 attempt 与旧 unknown attempt 使用不同结果地址；旧 attempt 的迟到结果只能作为旧执行证据，由父 Agent决定是否参考，不能成为当前正式结果。
- 重复执行经明确选择后，只有被写入 `current_attempt` 的 attempt 结果进入当前任务验收；`duplicate_not_selected` attempt 的结果继续保留在自己的结果地址，但不能自动成为当前业务结果。
- 平台错误后，同一 Agent、同一 attempt 的迟到结果如果结构合法、身份明确且尚无正式结果，可以正常保存；平台错误记录作为独立历史事实保留。
- 结果纠正耗尽后，同一 Agent、同一 task/attempt 的合法迟到结果如果尚无正式结果、attempt 未关闭且未被主动中断，可以正常保存，并把 `result_protocol_status` 从 `exhausted` 改为 `valid`；纠正计数保持原值。该规则只接收已经到达的合法结果，不允许再发送补交请求。
- 成功主动中断后才到达的结果不能成为该 attempt 的正式结果，只作为非权威参考交给父任务；中断前已经合法保存的结果继续独立保留。
- 同一 attempt 内的平台恢复不改变结果地址；只有该 attempt 尚未保存正式业务结果时，恢复后的 Agent才可首次提交该地址。已有 blocked、needs_decision、complete 或 failed 结果后继续执行必须创建新 attempt，不能覆盖原文件。

默认不实现：

- 独立 `submission_attempt_id`。
- 随机 `result_id`。
- 复杂 revision。
- 候选结果数据库。
- PreparedResult 与正式 ResultStore 两阶段提交。
- notification ID 和确认协议。

### SG-F06-08 父任务闭环

- 原生 Agent 最终回复和 summary 仍是主要回传通道。
- 结果文件提供完整、稳定的读取来源。
- 父 Agent负责核对业务结果、文件、命令和测试。
- 主对话只展示关键结果、验证、剩余事项和决策。
- complete 结果在父 Agent验收前保持 `acceptance_status=pending + parent_action=accept_result` 并继续进入 `action_required`。验收通过后写 accepted 并关闭任务；验收不通过写 rejected，保留原结果并基于原 `task_id` 创建新 attempt 或进行其他明确处置。
- 对 blocked 结果，设置 `parent_action=decide_disposition`；父 Agent必须说明 blocker、已尝试事项和恢复条件，但“已经汇报”不等于业务闭环。任务继续进入 `action_required`，等待恢复或显式关闭。
- 对 failed 结果，同样设置 `parent_action=decide_disposition`；父 Agent必须说明失败原因、证据和可选下一步。任务不会因汇报失败自动关闭，必须获得明确处置或创建新 attempt。
- 对业务 needs_decision 结果，设置 `parent_action=ask_user`；用户提供选择后，父 Agent再决定关闭或切换为 `business_resume` 创建新 attempt。
- Hook 放行、StateStore 写入或 fixture 成功都不等于父任务已经验收。
- 不建立第二套消息平台。

### SG-F06-09 父任务显式处置入口

增加一个最小 `parent_disposition` 生成与写入入口，使父 Agent的验收和关闭决定不依赖自然语言推断。固定参数为：

- `task_id`。
- `attempt`：对 `accept_result`、`reject_result` 和 `close_task` 表示调用者预期的 current attempt；对 `select_attempt` 表示要选择的新 current attempt。
- `action`：`accept_result | reject_result | close_task | select_attempt`。
- `reason`：由父 Agent根据真实业务决定生成，脚本只检查存在、类型和合理长度。

机械语义：

- 用户裁决（2026-08-11）：`accept_result` 只适用于 current attempt 已有合法 complete 结果且 `acceptance_status=pending`，并且必须复用与 `close_task` 相同的整 task 关闭过程。入口先核对 expected current attempt 和 complete 结果，再在同一锁内枚举全部未关闭 attempt；任一 attempt 存在 confirmed running Agent 时拒绝验收关闭并返回全部精确中断 target。`identity_status=unconfirmed`、stopped、interrupted、duplicate_not_selected 等非运行 attempt 随 task 关闭并分别生成 tombstone；只有 current complete attempt 写 `acceptance_status=accepted`，其他 attempt 只记录关闭原因，不伪造 accepted。所有 attempt 的关闭、tombstone、current acceptance 和 `parent_action=null` 必须一次原子写入并回读验证，任一步失败都不得出现“结果已 accepted、task 未可靠关闭”的半完成状态。
- `result_conflict=true` 不改变现有正式结果的业务字段，但禁止沿用冲突前的自动提示直接验收。父 Agent重新核对原结果后，可以用带真实 reason 的现有 `accept_result`、`reject_result` 或 `close_task` 明确解决冲突；对应事务必须同时清除 `result_conflict`、冲突摘要和发现时间。若父 Agent选择通过 business resume 创建新 attempt，则在新 attempt 原子创建时把旧 attempt 的冲突标记一并清除。任一步失败时保持冲突状态，不新增 `resolve_result_conflict` action。
- 只要 `duplicate_execution=true`，`accept_result` 机械拒绝验收；必须先通过 `select_attempt` 确定唯一 current attempt，关闭全部非运行未选候选，再显式中断并关闭全部运行未选候选，可靠清除重复状态后才能进入上述整 task 验收关闭流程。
- `reject_result` 同样只适用于已经确定且不存在重复执行冲突的 current attempt 待验收 complete 结果；原子写为 rejected，设置 `parent_action=decide_disposition`，保留原 result 文件并继续进入 `action_required`，不自动创建新 attempt。父 Agent明确决定继续后再切换为 `business_resume`。
- 非 current attempt 的 complete 结果可以保留和供父 Agent参考，但不能执行 accept_result 或 reject_result。
- 用户裁决（2026-08-11）：`close_task.attempt` 只表示调用者预期的 current attempt，用于锁内 compare-and-set；操作成功时关闭范围是整个 task。入口必须在同一锁内枚举该 task 的全部未关闭 attempt，包括 current、旧 unknown、duplicate_not_selected、已停止历史 attempt 和其他仍待处置 attempt。只要任一 attempt 存在已确认 `execution_status=running` 的 Agent，就机械拒绝整 task 关闭，并返回所有需要先显式中断的精确 Agent target；本入口不自动中断。平台中断成功但治理状态未可靠写入时也必须先人工对账。
- 所有未运行的 stopped、interrupted、duplicate_not_selected 和其他未关闭 attempt 随整个 task 一起明确关闭，分别保存关闭原因并生成最小 tombstone；不得只关闭 current attempt 后遗留其他 action-required attempt。身份 unknown 的 attempt 因没有可靠 target 无法先中断，允许随明确 `close_task` 关闭，但必须保留 task ref 与7天 tombstone，任何迟到 Agent或结果只能被识别为已关闭事件，不能复活任务。不增加 `force_close` 枚举或额外确认字段，显式 `close_task` 本身代表关闭意图。
- 所有 attempt 的关闭状态和 tombstone 必须在同一锁内完整写入并回读验证后，task 才能退出 `action_required` 并设置 `parent_action=null`；任一步失败都不得声称整个 task 已关闭。各 attempt 的正式结果按既定7天规则保留和清理，`close_task` 不编造或覆盖业务结果。
- `select_attempt` 从同一 task 的全部重复执行候选中选择传入 attempt，表示“保留所选、放弃其余”的明确关闭意图。入口在同一锁内原子写入 `current_attempt`，把其余所有未关闭候选标记为 `duplicate_not_selected`，并立即关闭其中的 stopped、interrupted、identity unconfirmed 和其他非运行候选，为每个 attempt 生成独立7天 tombstone；已有结果继续保留到 tombstone 到期。仍在运行的未选候选保持未关闭，入口返回全部精确中断 target，不自动调用 `interrupt_agent`。父 Agent后续中断成功时依据已保存的 select 意图关闭对应 attempt；failed/unknown 时不得提前关闭。所有未选候选关闭后清除 `duplicate_execution`。选择事务任一步持久化失败时整体失败，不得中断任何 Agent或留下部分选择状态；不得假设重复执行永远只有两个 attempt，也不新增 `close_attempt` action。

`accept_result`、`reject_result` 和 `close_task` 必须在锁内检查传入 attempt 等于 StateStore 当前 `current_attempt`，将其作为 compare-and-set 条件；不一致时拒绝操作，返回实际 current attempt 并要求父 Agent重新判断。`select_attempt` 是唯一可以传入非 current attempt 的 action，但目标 attempt 必须属于同一 task，且当前确实存在尚未解决的重复执行冲突。不得根据最大编号、最近时间或其他弱信号自动选择，也不得静默改写调用参数。

该入口只校验字段、枚举、task/attempt 引用、当前状态和机械转换，不判断父 Agent的业务选择是否正确。所有写入使用 StateStore 稳定锁、锁内 compare-and-set、原子替换和回读验证；失败时不得声称验收、选择或关闭已经完成。它只是治理状态处置入口，不发送 Agent 消息、不自动调用 `interrupt_agent`、不创建新 attempt，也不建立第二套编排平台。

### SG-F06-10 需要退役的当前路径

- `_terminal_field()` 的自由文本字段抽取。
- `_terminal_errors()` 中的字符数、关键词和固定卡硬性判断。
- `_reported_status()` 未识别时默认 complete。
- StateStore 内嵌、无正式消费者的临时 `result_document`。
- 混合字段 `retry_required`；分别由 `recovery_status` 与 `result_protocol_status/correction_count` 取代。
- 用自然语言终态反复续跑子 Agent。

这些函数在新结构化结果主路径完成前仍可能有调用，实施时应原子替换，不能先删后留下无结果来源。

### SG-F06-11 待验证

- 真实 SubagentStop payload 和原生最终回复边界。
- 大结果、Unicode、证据列表和文件读取。
- 相同结果重放、冲突、迟到和跨进程竞争。
- compact/resume 后父任务读取结果。
- 正式结果缺少当前验收所需字段时必须明确列出缺项并要求补交；未知额外字段兼容忽略，不读取协议版本，也不静默迁移、改写或补造业务字段。
- 真实 mailbox、summary 和用户最终回复链路。
- `parent_disposition` 的 accepted/rejected/close/select 合法转换、并发 compare-and-set、写入失败和回读验证。

## 十一、SG-F07 运行诊断、问题定位与可观测性

### SG-F07-01 功能职责

只读检查治理状态和上游已经留下的可观察证据，以稳定 JSON 和简短提示说明当前快照、治理健康、问题位置和证据边界。

用户裁决（2026-08-11）：诊断不是插件的核心业务功能，但考虑到本项目需要在网络断流、父线程恢复、状态损坏和任务未闭环时区分“仍在运行、平台已报错、等待父 Agent 验收、身份未确认或治理状态不可读”，保留一个最小只读诊断入口。它只充当治理状态检查和故障定位仪表盘；不得发展成独立监控、审计、修复或业务判断平台。即使诊断能力不可用，原生子 Agent 和核心治理流程也不应因此被替代或扩大阻断范围。

### SG-F07-02 诊断入口与只读读取

- 保留 `--diagnose`、`--session` 和 `--data-root`。
- 全局和单 Session 必须使用同一套只读解析。
- 诊断不得创建目录、锁文件、隔离文件、chmod 或回写状态。
- 区分不存在、损坏、不可读、超限、所有者错误和当前操作所需字段缺失。
- 未知参数和孤立选择器返回明确参数错误。

### SG-F07-03 健康与检查完整度

分开表达：

- 组件健康：正常、degraded、不可用。
- 本次扫描完整度：检查总数、成功数、失败数、遗漏数。
- 读取问题：最小稳定问题码和有界错误。
- Hook 即时告警：只展示已有事实，不建立第二份持久状态。

`health.status=degraded` 不能同时代表所有组件和整次扫描结果。

### SG-F07-04 Session、任务和 Agent 快照

用户裁决（2026-08-11）：默认诊断输出是从 StateStore 和正式结果引用中读取的稳定规范化视图，不直接转储完整状态文件，也暂不增加 `--raw` 模式。应展示：

- Session ID、组件健康和扫描完整度。
- `task_id + attempt`、Agent ID/canonical path 和按语义维度分组的当前状态。
- 父任务下一步动作。
- 关键时间。
- spawn retry、platform recovery 和 result correction 等机械计数。
- 最近平台观察。
- 最后可观察变化。
- `recent_activity` 只说明最近 12 小时发生过变化的任务；`action_required` 展示全部未解决任务，并单独标记 stale 和未展开数量。

默认不输出完整 dispatch prompt、通信正文、完整业务结果与证据、完整平台响应对象、StateStore 内部字段和已经退出目标的历史兼容字段。需要深度排查时直接检查受保护的本地数据文件；只有出现真实重复需求后才考虑受限原始输出选项。不建设完整事件历史或 attempt 因果图。

### SG-F07-05 问题定位

用户裁决（2026-08-11）：诊断只报告现有数据可以直接证明的事实，不把缺失证据、流程阶段或错误文本转换为推测性根因。问题码保持少量、稳定，并按实际实现需要从以下事实类别取值：

- 当前操作所需字段缺失或字段值非法。
- 状态文件不存在、不可读、损坏、超限或所有者不符合要求。
- Agent 身份尚未确认。
- 平台明确报告 Agent `errored`。
- 正式结果不存在、字段不完整或同一 attempt 出现冲突结果。
- 本次诊断扫描不完整。

原有 `delivery-suspected`、`execution`、`orchestration` 等推测性原因退出目标；没有 Agent 身份只能报告 identity unconfirmed，不能推断消息未送达；缺少执行或终态证据不能推断任务漂移或父 Agent 编排错误。`transport-opaque` 作为能力边界说明展示，不属于故障问题码；`action_required` 作为任务状态展示，不伪装成根因。Provider 相关内容只展示平台已有的可观察状态和有界原始信息，不根据错误关键词猜测根因或业务失败。

### SG-F07-06 稳定输出

- 提供一个稳定、简单的 JSON 顶层形状；内容是上述规范化快照，不是存储 Schema 的镜像。
- 全局和单 Session 使用一致命名和排序。
- 输出包含遗漏数和必要操作提示。
- 使用简单数量/体积上限。
- 用户裁决（2026-08-11）：退出码只表达“命令是否合法”和“扫描是否完整”，不表达任务业务健康或是否完成：
  - `0`：参数合法且完成全部请求目标的扫描；即使发现任务异常或待处理事项，也在 JSON 中报告并返回 `0`。
  - `1`：一个或多个请求目标不存在、损坏、不可读或因其他读取问题未能完成扫描；仍在 stdout 输出结构合法的部分结果 JSON。
  - `2`：CLI 参数错误，例如未知参数、参数值缺失或选择器冲突。
- 全局扫描中单个 Session 读取失败时继续处理其他 Session，最终返回 `1`；指定单个 Session 不存在或不可读时同样返回 `1`。
- stdout 始终保持稳定 JSON；必要的简短人工提示写入 stderr。具体损坏、权限、超限和字段缺失等原因放入 JSON 问题码，不继续扩张退出码体系。
- 脚本不生成主对话业务摘要。

### SG-F07-07 容量与结构边界

- 诊断尊重 Hook 输入、StateStore 和摘要的实际容量。
- 不以 stored version 判断数据是否可读，也不输出版本兼容矩阵。
- 按诊断视图所需字段逐项读取；字段缺失时显示明确缺项和受影响视图，未知额外字段忽略，不静默改写或补默认值。
- 活动任务升级前只做目标运行时所需字段的结构预检，不因创建它的插件版本不同而阻止继续。
- 没有真实数据规模需求时不实现分页、游标和复杂查询。

### SG-F07-08 明确删除的过度设计目标

- 完整事件审计。
- 复杂证据图和五级可信度。
- 四层持久诊断报告。
- `subagent-diagnostic-v1` 权威协议管线。
- 脚本自动生成用户摘要。
- 全面路径脱敏系统。
- 分页、稳定游标和查询矩阵。
- 独立诊断 Schema 的 N/N-1 迁移体系。
- 五档退出码。

### SG-F07-09 待验证

- 真正无副作用的读取行为。
- 部分读取失败和退出语义。
- 4 MiB 状态、未知大平台对象和输出上限。
- 真实 Codex 中的 Hook 告警、SessionStart 注入和 Provider 断流证据。
- 诊断对正式结果引用的读取。

## 十二、SG-F08 轻量多 Agent 协调

### SG-F08-01 最终定位

SG-F08 不再建设“多 Agent 协调与组级闭环系统”，而是作为父 Agent 的轻量任务关联辅助。它组合 individual task，不拥有新的执行平台、调度器或业务裁决器。

### SG-F08-02 批量派发透明度

- 主对话可用一张表列出每个 Agent 的目标、治理等级、模型、强度、上下文策略、范围和完成条件。
- 表格只是用户展示，不是结构化调度计划。
- 每个 Agent 仍通过一次原生 `spawn_agent` 独立派发。

### SG-F08-03 轻量组引用

用户裁决（2026-08-11）：group只在父Agent显式创建时存在，不根据同一会话、同一轮或并行派发自动生成。只保存：

- `group_id`。
- `objective_summary`。
- `members[]`，每个成员只包含 `task_id` 和 `required`。
- `created_at` 与 `updated_at`。

不复制individual task的角色、目标、结果、失败原因、恢复状态或父动作；需要时直接读取individual task。`summary_ready` 和 `group_action_required` 实时派生，不持久化为group状态。不保存完整图版本、图哈希、节点 revision 或批次状态机。group不设置独立保留期限；所有成员完成明确处置并完成对应清理后，group随Session一起删除。

### SG-F08-04 最低机械校验

只检查：

- 引用任务是否存在。
- required 值是否合法。
- 同一 group 中 task 引用不重复。

业务分组、角色含义、可并行性和失败处理由父 Agent 判断。

### SG-F08-05 等待和恢复

- 每个 Agent 使用 SG-F05 的 individual 等待、对账和有限恢复。
- 一个 Agent 失败默认只处理该 Agent。
- 其他 Agent 正常执行时继续等待。
- 不自动暂停、取消或中断整组。
- 不建立多目标后台事件路由器。
- 父 Agent可以根据 mailbox 返回选择下一目标。

### SG-F08-06 结果汇总

- 每个任务分别产生 SG-F06 individual result。
- 用户裁决（2026-08-11）：组级“可以汇总”和“已经解决”必须分开。任何已有信息都可以生成阶段性摘要；当每个 required task 都已有可读正式结果，或已经通过 `parent_disposition` 等路径形成带原因的明确最终处置记录时，派生 `summary_ready=true`。它只表示所有必需成员都有可用于完整汇总的材料，不表示所有任务成功，也不等于组已经闭环。
- `group_action_required` 直接由 individual task 派生：只要任一 required task 仍待父 Agent验收、blocked、failed、needs_decision、平台/协议/存储故障、重复执行冲突或其他未完成处置，组就继续需要处理。
- 只有所有 required task 都完成 individual 处置后，组才退出 `group_action_required`。完成处置包括 complete 被 accepted，或失败、阻塞、决策和冲突已经通过恢复、显式关闭、接受失败或用户放弃等方式得到明确结论。
- 父 Agent在 summary ready 后读取各成员的正式结果或明确最终处置记录，比较并处理冲突；若组仍需处理，生成的是“当前结果汇总”而不是伪装成最终完成摘要。
- 父 Agent生成最终用户摘要。
- 不生成 `AggregateResult`、聚合 revision 或自动业务裁决。
- 哪些必需结果尚未返回或尚未完成 individual 处置，直接由 `members[]` 引用的 individual task 实时派生；不得在 group 中重复持久化。`summary_ready` 和 `group_action_required` 都是派生视图，不新增独立组状态机。

### SG-F08-07 明确停止的目标

- 完整 CoordinationPlan。
- DAG/拓扑执行器。
- batch、wave、并发容量状态机。
- 父子/孙级复杂规则传播。
- 资源租约和自动调度。
- 独立组状态机。
- 自动故障/暂停/取消传播。
- AggregateResult 和迟到重聚合。
- 组级协议版本和 N/N-1 迁移。

### SG-F08-08 当前代码事实

- 当前仓库没有正式协调运行实现。
- 当前 `child_agents=allow|deny` 属于待退役的独立授权字段；目标实现只在 auto task features 中保留可选的 `allows_child_agents` 复杂度信号，不建立父子任务图或权限系统。
- Skill 批量派发表格只提供透明度。
- `tests/test_concurrency.py` 只证明并发 StateStore 写入不丢记录，不证明业务协调。
- 因此没有可直接删除的 SG-F08 运行时代码；主要动作是停止继续实现原独立文档提出的完整系统。

## 十三、按优先级排列的删除、收缩与替换项

| 优先级 | 项目 | 最终处理 | 确认状态 |
| --- | --- | --- | --- |
| P0 | 自然语言关键词、字符数和固定文案驱动的业务验收 | 删除硬性阻断，改为结构化参数和父 Agent 业务验收 | 已确认 |
| P0 | Hook 正文 `auto` 风险分类 | 删除，`auto` 前移到生成器并解析成实际等级 | 已确认 |
| P0 | 600 字符正式结果截断和空 evidence/remaining | 替换为完整结果文件和有界状态摘要 | 已确认 |
| P0 | 单一 `status` 混合执行、平台、结果和动作 | 拆分多维语义 | 已在各盘点中确认 |
| P1 | 完整多 Agent 编排系统 | 停止实现，只保留轻量任务关联 | 已确认 |
| P1 | PreparedResult/ResultStore 双层提交和大量随机 ID | 合并为 PreparedContract、StateStore、`task_id + attempt` 结果文件 | 已确认 |
| P1 | 语义同名、同轮和唯一候选身份猜测 | 删除；task name 只保留现有 task_id + attempt 短引用的精确绑定 | 已确认方向 |
| P1 | PreToolUse 内部异常一律 deny | 区分非法契约与插件故障 | 已确认方向 |
| P2 | 完整诊断协议、四层报告、分页、事件审计和证据图 | 删除过度目标，保留简单只读 JSON 和提示 | 盘点结论 |
| P2 | SG-F04 扩张为独立发布系统 | 保留原生 CLI 包装、N/N-1 回滚缓存和真实验收；删除协议版本门禁、版本矩阵和状态迁移目标，活动任务只做字段结构预检 | 已确认 |
| P2 | 独立 PreparedCommunication、通信 ID 和投递确认状态 | 删除；只保留 StateStore 内短期 `pending_action` 传递机械操作类型 | 已确认 |
| P3 | 协议在 AGENTS、Skill、README、Schema、Python 和测试中重复维护 | 只建立机器语义最小权威源；自然语言人工维护并做核心一致性检查 | 已确认 |
| P3 | `delivery-suspected` 等混层诊断术语 | 删除推测性原因，只保留可观察事实问题码、来源和 unknown 边界 | 已确认 |
| P3 | `dispatched` 无写入者、`_active_records()` 名称误导 | 删除 `dispatched` 并拆分派发/身份观察；用 `_recent_activity_records()` 与 `_action_required_records()` 替换 `_active_records()` | 已确认 |

### 职责越界专项实施清单

用户确认（2026-08-11）：以下16类内容都属于插件承担了不应由它负责的业务判断、平台判断、权限控制或外围系统职责，全部作为后续修改方案中的明确实施项。这里的“删除”通常指删除旧行为、状态转换、字段或分支；仍有当前调用者的路径必须在新的结构化主路径可用后原子替换，不得先删出功能空洞。

| 编号 | 优先级 | 越界内容 | 必须执行的处理 |
| --- | --- | --- | --- |
| OR-01 | P0 | 自然语言风险分类 | 删除 `HIGH_RISK_MARKERS`、`READ_ONLY_MARKERS`、`WRITE_MARKERS`、`NEGATION_MARKERS`、`_classification_text()` 及正文 auto 分类；auto 只消费 AI提交的结构化 task features。 |
| OR-02 | P0 | Hook 解析和改写派发业务正文 | 删除从 message 提取目标、范围、证据、上下文和明密文类型来形成契约的主路径；删除 Hook追加治理信封、任务 ID和 strict 正文字段校验。完整 prompt 由确定性生成器产生，Hook只核对 task ref、PreparedContract、初始 StateStore 和原生参数。 |
| OR-03 | P0 | 下级子 Agent 权限、层级和范围控制 | 删除独立的 `child_agents=allow` / `child_agents=deny` 授权字段、`【下级子 Agent】` strict 机械字段、权限传播、层级限制和父子任务图目标。只允许 `task_features.allows_child_agents` 作为 auto 的可选复杂度信号；实际 spawn 每次独立进入治理。 |
| OR-04 | P0 | 自然语言终态业务验收 | 删除 ACK 词表、最小字符数、证据关键词、自然语言任务 ID、固定标题和字段措辞驱动的终态阻断；Hook只校验正式结构化结果的存在、类型、枚举、引用、长度边界和基本组合。 |
| OR-05 | P0 | 从原生最终回复推断并生成正式业务结果 | 删除 `_reported_status()`、自由文本状态提取、600字符结果截断和自动填充空 evidence/remaining。正式结果只来自 `results/<task_id>-<attempt>.json`，中文终态卡只由同一结构化结果渲染。 |
| OR-06 | P0 | 强迫所有原生 Agent调用进入治理 | 删除无 `sg_` 前缀调用的默认拒绝或默认 standard；unmanaged spawn、通信、启动和停止兼容放行，不注入治理启动指令、不创建半套状态、不进入Stop保护或结果验收。 |
| OR-07 | P0 | Hook改写通信正文并猜测操作类型 | 删除在实际 message 中注入通信协议、内部任务 ID和机械 operation type；删除根据工具名、当前状态或自然语言推断通信用途。生成器显式提供 operation type 并写入两阶段 `pending_action`，实际 message 只保留子 Agent需要理解的中文业务指令。 |
| OR-08 | P0 | Hook替父 Agent或用户作业务处置 | 删除 `spawn` 调用成功即认定 running、调用失败即写业务 failed、平台恢复耗尽即伪造业务 needs_decision、成功中断即关闭整个任务、SubagentStop complete 即视为父 Agent accepted 等自动结论；只记录机械观察并由分离的身份、平台、结果、验收和父动作字段继续处理。 |
| OR-09 | P1 | 使用弱证据猜测任务—Agent身份 | 删除语义同名、同轮、唯一候选和任意首个候选绑定；首次或迟到 spawn 只使用 task name 中的 task ref，绑定后只使用 Agent ID/canonical path 与 StateStore 当前 attempt。 |
| OR-10 | P1 | 递归猜测任意平台响应和错误语义 | 删除对任意嵌套字段的递归搜索、字符串前缀失败判断和 Provider/加密/解密错误文本特判；只适配已经确认的原生响应形状，未知形状记录为 unknown，不改变业务结果。 |
| OR-11 | P1 | 按时间或数量自动删除未解决任务 | 删除30天、最多200条等通用 terminal 裁剪对 blocked、failed、needs_decision、`platform_observation=error`、恢复耗尽和其他 action-required 记录的作用。只对明确关闭的 tombstone 使用固定7天精确清理，未解决任务不按时间关闭或删除。 |
| OR-12 | P1 | 多余存储层、身份和投递确认系统 | 不建设或删除 PreparedCommunication、PreparedResult双层提交、result revision、随机 result/Aggregate ID、execution/submission/communication/notification ID、完整事务数据库以及“已送达/已阅读/已处理”状态。保留 PreparedContract、StateStore、task/attempt、pending action 和正式结果文件。 |
| OR-13 | P1 | 使用推测性原因代替可观察诊断事实 | 删除 `delivery-suspected`、`execution`、`orchestration` 等术语作为诊断根因或问题码的用法；`execution_status` 只作为机械执行状态维度保留。没有可靠 Agent 身份时只报告 `identity_unconfirmed`，缺少执行或终态证据时只报告具体字段或证据缺失，不推断消息投递失败、任务漂移或父 Agent 编排错误。诊断只输出少量事实问题码、证据来源、检查完整度和 unknown 边界。 |
| OR-14 | P1 | 诊断命令产生副作用或发展成独立诊断平台 | 诊断不得创建目录、锁文件、隔离文件、chmod、修复或回写状态；同时删除四层持久报告、完整事件审计、证据图、分页游标、查询矩阵、独立迁移 Schema 和五档退出码，只保留有界只读 JSON 与简短提示。 |
| OR-15 | P2 | 完整多 Agent编排系统 | 停止 DAG、batch、wave、容量调度、资源租约、自动暂停/取消/失败传播、组状态机、AggregateResult 和迟到重聚合；SG-F08只保留轻量 group 关联和 individual task 结果汇总辅助。 |
| OR-16 | P2 | 完整版本迁移、发布平台和规则扩张 | 删除协议版本兼容门禁、版本矩阵和状态迁移目标；每次交互只看所需字段是否齐全。仍不建设版本数据库、分布式发布事务、自建 trust hash、Marketplace 管理器或复杂自动回滚编排。全局 `AGENTS.md` 只保留按需加载 Skill 的最小入口，不强迫第三方 Skill采用本协议。 |

以下能力不属于越界删除范围，后续方案必须保留：确定性生成器、结构校验、PreparedContract与初始 StateStore派发硬门禁、task ref、显式 operation type、20分钟等待、目标范围对账、同 Agent一次自动平台恢复及一次用户授权恢复、结构化正式结果、父 Agent显式验收、最小只读诊断和 N/N-1 整体回滚。

### 已确认删除或已经退出目标

- 原 `references/related-skills.md`：没有运行时消费者，已删除。
- 原 `compatibility.md`：已由 `runtime-boundaries.md` 替代。
- 原 Provider 错误文本特判 fixture：不应恢复为关键词判断。
- `provider_protocol_incompatible` 特殊生命周期分支：不再作为目标；所有已确认平台错误统一写为 `platform_observation=error` 并进入有界恢复链。
- Hook 中无处理分支的 `interrupt_agent` PreToolUse 注册：已移除。
- SG-F08 完整协调系统目标：停止实现，其 DAG、批次、组状态、自动传播和 AggregateResult 子项一并删除。
- SG-F07 完整诊断协议目标：停止实现，其四层报告、事件审计、证据图、分页、独立 Schema 和五档退出码子项一并删除。

### 目标主路径完成后删除

- 正文 `auto` 分类词表和函数。
- 派发正文解析、明密文猜测和 Hook 正文改写。
- 自由文本终态字段提取、长度和证据关键词硬阻断。
- strict 中文终态卡的 Hook 文本解析和格式阻断。
- 语义同名、同轮和唯一候选身份猜测；不删除 task name 中现有 task_id + attempt 短引用的精确绑定路径。
- `dispatched` 状态常量、集合成员和相关旧断言。
- 600 字符正式结果片段和固定空 evidence/remaining。
- 固化旧缺口的现状特征测试。
- 已被结构化生成器替代的文本包含一致性测试。

### 盘点时暂不删除项的 WP-08 结果

- `_active_records()`：WP-07 已移除最后诊断消费者，WP-08 已与 `_recent_records()`、`_managed_action_required_records()` 一并删除；权威视图为 `_recent_activity_records()` 与 `_action_required_records()`。
- session `.lock` 文件：作为稳定并发互斥入口保留，运行时不自动删除；这不是暂缓决定的清理候选。
- `opaque-spawn-v1.json`：task ref + PreparedContract 链完成后已改名为 `exact-task-ref-opaque-message-v1.json`，只证明opaque正文不影响精确凭证关联。
- 发布工具中的重复安全辅助：当前均有调用和测试，先评估最小共享抽取。
- N-2 缓存、legacy Hook 和稳定备份：属于外部退役候选，需真实验收和明确删除授权。

## 十四、跨功能数据与控制链

### 1. 派发链

```text
AI 结构化参数
  → 生成器解析实际等级并生成 PreparedContract
  → task_name（治理前缀 + 语义名 + task 短引用）+ 完整 prompt
  → spawn_agent
  → PreToolUse 机械核对并消费 PreparedContract
  → PostToolUse 记录 success / failed / unknown，并在原生响应可靠提供时绑定 Agent 身份
  → 身份仍未确认时进入 reconcile
  → 精确 SubagentStart 最终确认身份和 running
```

### 2. 通信链

```text
AI 提供对象、目的、原因、内容和期望结果
  → 显式选择 operation_type
  → 生成器写入 StateStore 短期 pending_action
  → 输出用户说明与 target/message
  → send_message 或 followup_task
  → Hook 根据 target/pending_action 核对任务引用和状态边界
  → 原生平台执行
  → PostToolUse 更新状态并清除 pending_action
```

### 3. 网络恢复链

```text
wait_agent
  → mailbox 错误或等待超时
  → 目标范围 list_agents
  → errored 才写 platform_observation=error
  → followup_task 同 Agent，保持当前 attempt 并增加 recovery_count
  → 第一次调用 success：stopped/error + parent_action=wait
  → 第一次调用 unknown：stopped/error + parent_action=reconcile，禁止自动重发
  → 第一次调用 failed：recovery_status=awaiting_authorization + parent_action=ask_user
  → 精确 SubagentStart 后 running/normal/wait
  → 恢复启动后再次错误则 recovery_status=awaiting_authorization
  → parent_action=ask_user，business_result 保持 null
  → 用户授权最后一次恢复并完成原子认领
  → 第二次调用 unknown 时 recovery_status=null、parent_action=reconcile，等待迟到启动
  → 匹配迟到启动后 running、platform_observation=normal、recovery_status=null、parent_action=wait，recovery_count 仍为2
  → 第二次明确 failed 或恢复后再次 errored 时 recovery_status=exhausted
```

### 4. 终态链

```text
子 Agent 生成结构化业务结果
  → 写 results/<task_id>-<attempt>.json
  → SubagentStop 机械核对
  → StateStore 保存摘要和引用
  → complete 结果进入 acceptance_status=pending
  → 父 Agent读取完整结果并验收为 accepted 或 rejected
  → 向用户展示关键结论
```

### 5. 会话恢复链

```text
SessionStart / compact / resume
  → 读取 sessions 状态
  → 分开展示调用对账、身份未确认、待恢复、等待授权、恢复/纠正耗尽、结果冲突、待验收和业务待决策摘要
  → 父 Agent按 parent_action 继续等待、对账、恢复、纠正、验收、人工检查或询问用户
```

## 十五、全仓文件覆盖表

| 文件 | 主要功能归属 | 结论 |
| --- | --- | --- |
| `.codex-plugin/plugin.json` | SG-F02、SG-F04 | 插件身份、Skill 根目录、版本和发布缓存身份 |
| `.github/workflows/ci.yml` | SG-F04 | 基础 CI 发布门禁 |
| `.gitignore` | SG-F04/仓库支撑 | 排除缓存和临时产物 |
| `AGENTS.md` | 跨功能规则 | 项目边界、核心治理目标和开发约束 |
| `README.md` | 跨功能公开说明 | 能力、边界、安装和诊断入口 |
| `assets/agents-governance.md` | SG-F04 分发；SG-F01/03/05/06 语义 | 全局最小入口资产 |
| `docs/project-function-inventory.md` | 全部 | 本总文档 |
| `docs/function-inventory/SG-F04-install-release-cache.md` | SG-F04 | 过程证据档案 |
| `docs/function-inventory/SG-F05-lifecycle-wait-recovery.md` | SG-F05 | 过程证据档案 |
| `docs/function-inventory/SG-F06-terminal-result-acceptance.md` | SG-F06 | 过程证据档案 |
| `docs/function-inventory/SG-F07-runtime-diagnostics-observability.md` | SG-F07 | 过程证据档案 |
| `docs/function-inventory/SG-F08-multi-agent-coordination.md` | SG-F08 | 过程证据档案；完整编排结论已被本文覆盖 |
| `docs/optimization-plan.md` | 跨功能计划 | WP-01～WP-08 本地实施总览和稳定发布未执行边界 |
| `docs/refactor-plans/WP-01-semantic-schema-baseline.md` | SG-F01 | 阶段方案与实施证据 |
| `docs/refactor-plans/WP-02-state-store-safety.md` | SG-F05 | 阶段方案与实施证据 |
| `docs/refactor-plans/WP-03-deterministic-dispatch-identity.md` | SG-F01/02/05 | 阶段方案与实施证据 |
| `docs/refactor-plans/WP-04-communication-lifecycle-operations.md` | SG-F03/05 | 阶段方案与实施证据 |
| `docs/refactor-plans/WP-05-formal-result-parent-closure.md` | SG-F06 | 阶段方案与实施证据 |
| `docs/refactor-plans/WP-06-wait-recovery-session-closure.md` | SG-F05/06 | 阶段方案与实施证据 |
| `docs/refactor-plans/WP-07-minimal-diagnostics-lightweight-groups.md` | SG-F07/08 | 阶段方案与实施证据 |
| `docs/refactor-plans/WP-08-legacy-retirement-release-readiness.md` | 全部/SG-F04 | 最终退役、覆盖、验证和发布准备记录 |
| `docs/release-process.md` | SG-F04 | 发布、验收和回滚流程 |
| `hooks/hooks.json` | SG-F02 | 七类 Hook 注册 |
| `schemas/governance-semantics.schema.json` | SG-F01/03/05/06/07/08 | 最小机器语义权威源 |
| `schemas/task-contract-v1.schema.json` | SG-F01 | 任务契约结构声明 |
| `schemas/task-result-v1.schema.json` | SG-F06 | 终态结果结构声明 |
| `scripts/apply_agents_block.py` | SG-F04 | 全局最小入口安全分发 |
| `scripts/check_installation.py` | SG-F04 | 安装和部署状态只读检查 |
| `scripts/reinstall_preserving_caches.py` | SG-F04 | N/N-1 重装保护 |
| `scripts/subagent_governance.py` | SG-F01/02/03/05/06/07 | 共享运行时；各区段归属见下一节 |
| `skills/subagent-governance/SKILL.md` | SG-F01/03/05/06/07/08 | 父 Agent 协作规则入口 |
| `skills/subagent-governance/agents/openai.yaml` | SG-F02 | Skill UI 元数据 |
| `skills/subagent-governance/references/governance-levels.md` | SG-F01/06 | 等级和证据强度参考 |
| `skills/subagent-governance/references/runtime-boundaries.md` | SG-F02/05/06/07 | 原生工具、平台和运行边界 |
| `tests/fixtures/agent-status-error-v1.json` | SG-F03/05/07 | 平台错误对账样本 |
| `tests/fixtures/interrupt-v1.json` | SG-F05/06 | 中断生命周期样本 |
| `tests/fixtures/lifecycle-v1.json` | SG-F05/06 | 启停、会话和终态样本 |
| `tests/fixtures/exact-task-ref-opaque-message-v1.json` | SG-F01/02/05 | opaque正文不影响PreparedContract/task_ref精确门禁 |
| `tests/fixtures/recovery-limit-v1.json` | SG-F03/05 | 一次恢复和恢复上限样本 |
| `tests/test_concurrency.py` | SG-F05 | StateStore 并发写入；不是 SG-F08 协调测试 |
| `tests/test_communication_lifecycle.py` | SG-F03/05 | 四类通信、恢复、中断和三态对账 |
| `tests/test_dispatch_identity.py` | SG-F01/02/05 | 生成器、PreparedContract、task_ref和精确身份 |
| `tests/test_formal_result_parent_closure.py` | SG-F06 | 正式结果、冲突、补交和父处置 |
| `tests/test_governance.py` | SG-F01/02/05/06/07 | 共享路由、unmanaged、文档和基础安全回归 |
| `tests/test_hook_fixtures.py` | SG-F01/03/05/06 | 本地 Hook 事件链测试 |
| `tests/test_minimal_diagnostics_lightweight_groups.py` | SG-F07/08 | 纯只读诊断和轻量group |
| `tests/test_plugin_structure.py` | SG-F02/04 | Manifest、Skill 和 Hook 静态结构 |
| `tests/test_release_tools.py` | SG-F04 | 发布、重装、安装检查和入口分发测试 |
| `tests/test_semantic_baseline.py` | SG-F01/06 | 机器语义、Schema和自然语言规则一致性 |
| `tests/test_state_store.py` | SG-F05 | StateStore安全、容量、CAS和精确清理 |
| `tests/test_wait_recovery_session_closure.py` | SG-F05/06 | action-required、Stop、Session、多attempt和tombstone |
| `tests/test_wp08_legacy_retirement.py` | 全部 | 旧符号、历史记录边界、fixture改名和当前文档收口 |

覆盖结论（2026-08-12）：按 `rg --files --hidden -g '!.git/**'` 重新盘点的52个有效文件全部列于本表并有保留功能归属。已删除 `tests/fixtures/opaque-spawn-v1.json`（由语义更准确的 current fixture替代）、旧 Provider文本特判fixture、`compatibility.md`、`related-skills.md`；没有未被保留功能覆盖的文件。

## 十六、`scripts/subagent_governance.py` 核心区段覆盖

| 代码区段 | 主要归属 | 最终处理 |
| --- | --- | --- |
| 机器语义加载、协议常量、数据类和机械validator | SG-F01/06 | 直接消费三Schema中的最小权威语义，无版本门禁或正文分类 |
| 路径、时间、权限和数据根辅助 | SG-F05 | 保留安全边界，诊断另建只读路径 |
| `StateStore` / `UnavailableStateStore` | SG-F05 | 最小持久状态、稳定锁、CAS、容量、损坏保全和精确tombstone/result清理 |
| `PreparedContractStore`、task/result地址和结果锁 | SG-F01/05/06 | PreparedContract短期凭证与确定性正式结果文件 |
| `prepare_dispatch()` / `prepare_spawn_retry()` / 渲染函数 | SG-F01/05 | 结构化契约、task_ref和双硬门禁 |
| `prepare_communication()` / `prepare_interrupt()` / pending action | SG-F03/05 | 显式operation_type、5/20分钟认领与对账 |
| `submit_task_result()` / `read_task_result()` / `reassociate_task_result()` | SG-F06 | 正式结果先写回读再关联、幂等/冲突/迟到保护 |
| `apply_parent_disposition()` 与duplicate/select辅助 | SG-F06/05 | accept/reject/close/select原子父处置 |
| `_tool_kind()`、`handle()`、`main()` | SG-F02/07 | 保留路由，区分非法输入与内部异常 |
| `_handle_spawn()` / `_resolve_task_id()` | SG-F01/03/05 | 只消费PreparedContract和精确 `{task_id,attempt}` 映射 |
| 有限原生响应适配器与 `_handle_post_tool()` | SG-F02/03/05 | 只读已知顶层/单层结构化字段；unknown不猜测 |
| `_assign_starting_agent()` / `_handle_subagent_start()` | SG-F05 | task_ref或精确Agent映射；历史非managed记录只告警放行 |
| `_handle_subagent_stop()` | SG-F06/05 | managed只消费显式TaskResult；未映射/历史非managed不生成正式结果 |
| `_action_required_records()` / `_recent_activity_records()` | SG-F05/07 | current/prior managed attempt权威派生视图；旧active/recent桥已删除 |
| `_handle_stop()` | SG-F05 | 与 action-required 和 stale 策略统一 |
| `_handle_session_start()` | SG-F05/07 | 保留有界恢复摘要 |
| `_handle_session_end()` | SG-F05 | 直接消费action-required，与tombstone和锁生命周期统一 |
| group校验/读写/派生 | SG-F08 | 只持久化五字段引用，实时派生两个布尔值 |
| 只读诊断构建器与 `_diagnose()` | SG-F07 | 无锁、无副作用、稳定JSON和0/1/2退出码 |
| CLI argument parser和所有稳定子命令 | SG-F01/03/04/05/06/07/08 | 结构化本地入口，不引入第二套编排平台 |

覆盖结论：共享运行时的全部顶层区段均由保留功能消费。旧混合状态集合、legacy list/followup/interrupt、自由文本终态、旧派生视图和Session薄桥已删除；没有无消费者的顶层legacy函数。

## 十七、测试与证据总表

### 已有仓库证据

- 完整单元测试入口：`python3 -m unittest discover -s tests -v`。
- 运行时编译：`python3 -m py_compile scripts/subagent_governance.py`。
- 发布工具编译。
- Plugin validator。
- Skill validator。
- fixture JSON 解析。
- `git diff --check`。
- Manifest、Skill、Hook、Schema 和规则一致性测试。
- StateStore 安全、并发、损坏和现状裁剪测试；其中自动空状态恢复、受治理 spawn fail-open 和通用 terminal 裁剪只证明当前实现，后续必须按 SG-F05-12 改写，不能作为最终行为证据。
- 派发、通信、平台恢复、中断、Stop、SessionStart/End 和 SubagentStop 定向测试。
- 发布、N/N-1 回滚缓存、安装检查和全局入口分发测试。

### 仓库证据不能证明

- 真实 Hook trust。
- 真实 Plugin/Skill UI。
- 真实原生工具是否接受当前扩展参数。
- Provider 断流和恢复。
- mailbox 唤醒顺序。
- 子 Agent 是否实际处理消息。
- 父任务是否看到并验收最终结果。
- 平台 token spill。
- 升级预检对活动任务缺失字段和旧缓存引用的真实识别。
- N-1 整体回滚能否恢复上一稳定版本；交互数据兼容性不按版本判断，只由实际字段校验验证。

### 后续真实验收最小矩阵

1. 新稳定版本被新任务加载。
2. `/hooks` 中七类 Hook enabled/trusted。
3. 一次 light 派发。
4. 一次 standard 编码或诊断派发。
5. 一次 explicit strict 派发。
6. 一次 `auto` 结构化解析。
7. 普通 `send_message`。
8. `list_agents errored → followup_task → SubagentStart`。
9. 二次平台错误进入决策。
10. `interrupt_agent`。
11. `SubagentStop` 完整结果保存和父任务读取。
12. Stop、compact/resume 和 SessionEnd。
13. 诊断只读输出。
14. 升级前活动任务字段结构预检与 N-1 整体回滚。
15. 轻量多 Agent group 中一个失败、其他继续、父 Agent 汇总。

## 十八、改造执行基线

### 18.1 可执行性结论

**可以依据本文改造插件项目。** 产品边界、目标状态、有限重试、结果协议、父任务处置、删除范围、文件归属和验收证据已经确定，当前不存在会阻止方案生成的设计缺口。

但本文是改造事实与决策输入，不应被执行成一次性大补丁。`scripts/subagent_governance.py` 同时承载派发、通信、状态、结果、会话和诊断，旧路径之间存在调用依赖；必须按本节工作包分阶段实施，并遵守“新主路径通过验证后再原子退役旧路径”的规则。

以下事项属于真实平台验证，不是继续设计的前置阻塞：

- 原生 spawn 响应稳定提供哪些 Agent ID/canonical path 字段。
- `SubagentStart` 是否稳定暴露 task name 和 task ref。
- 缺失 PostToolUse、mailbox 断流和迟到事件的真实顺序。
- Hook trust、Skill 加载、Provider 断流和运行缓存切换。

实现必须为这些边界保留明确的 unknown、reconcile、告警或 `not_checked`，不能用本地 fixture 假装已经取得平台保证。

### 18.2 目标状态模型速查

本表是实现和方案拆分时的状态字段索引；完整转换条件以 U-06、SG-F05 和 SG-F06 为准。

| 维度 | 字段 | 合法值 | 责任边界 |
| --- | --- | --- | --- |
| 执行 | `execution_status` | `not_started, running, stopped, interrupted` | 只表示当前执行是否运行，不承载派发、平台或业务结论 |
| 派发观察 | `spawn_observation` | `null, success, failed, unknown` | null 表示尚无观察；unknown 表示调用已经进入对账但结果不明 |
| 身份 | `identity_status` | `unconfirmed, confirmed` | 只有可靠原生身份或精确 `SubagentStart` 才确认 |
| 平台观察 | `platform_observation` | `null, normal, error, unknown` | 只保存明确平台事实，不解析 Provider 错误语义 |
| 业务结果 | `business_result` | `null, complete, blocked, failed, needs_decision` | 只来自合法正式结果，不由平台或治理异常生成 |
| 父验收 | `acceptance_status` | `null, pending, accepted, rejected` | 只服务于 complete 结果 |
| 结果协议 | `result_protocol_status` | `null, needs_correction, valid, exhausted` | 只表达结构化结果协议状态 |
| 结果存储 | `result_storage_status` | `null, available, unavailable` | 与协议合法性分离 |
| 结果冲突 | `result_conflict` | `false, true` | 不覆盖原结果；true 时进入人工检查 |
| 平台恢复 | `recovery_status` | `null, awaiting_authorization, exhausted` | 与业务 needs_decision 分离 |
| 父动作 | `parent_action` | `null, wait, reconcile, retry_spawn, recover, correct_result, decide_disposition, business_resume, accept_result, ask_user, manual_review, resolve_duplicate` | 状态机给父 Agent 的权威下一步，不表示动作已经完成 |
| 有限次数 | `spawn_retry_count` | `0..2` | 首次原生调用不计数；同 attempt 最多两次重派 |
| 有限次数 | `recovery_count` | `0..2` | 一次自动恢复和一次用户授权恢复 |
| 有限次数 | `correction_count` | `0..2` | 所有治理等级统一最多两次结果补交 |
| 调用对账 | `pending_action` / `last_lifecycle_operation` | 本文已确认的最小结构 | 只保存正在调用或迟到事件对账所需事实，不形成事件历史 |
| 关闭保留 | closed attempt + tombstone | 固定7天 | 只清理已明确关闭的 attempt 及其精确结果文件 |

### 18.3 实施工作包与依赖

| 工作包 | 目标 | 主要文件范围 | 前置依赖 | 完成条件 |
| --- | --- | --- | --- | --- |
| WP-01 语义与 Schema 基线 | 固定任务参数、结果参数、状态枚举、父动作和机械校验边界 | `schemas/*.json`、`scripts/subagent_governance.py` 的常量/数据类、`skills/subagent-governance/SKILL.md`、`assets/agents-governance.md`、一致性测试 | 无 | Schema、运行时、生成说明和测试使用同一组已确认字段；删除版本门禁和自然语言语义校验目标 |
| WP-02 StateStore 安全底座 | 实现最小状态、稳定锁、CAS、原子替换、容量边界、损坏保全、初始值和精确清理 | `scripts/subagent_governance.py`、`tests/test_governance.py`、`tests/test_concurrency.py` | WP-01 | 不可读状态不伪装为空；3/4 MiB边界正确；未解决任务不裁剪；tombstone/result 精确清理；`.lock` 保留 |
| WP-03 确定性派发与身份绑定 | 实现生成器、auto 解析、PreparedContract、task ref、spawn 前硬门禁和迟到身份绑定 | task contract Schema、运行时 spawn/PreToolUse/PostToolUse/SubagentStart、Hook fixtures | WP-01、WP-02 | governed spawn 不读业务正文；无前缀调用兼容放行；success/failed/unknown 和缺失 PostToolUse 映射正确；不使用弱身份猜测 |
| WP-04 通信与生命周期操作 | 实现显式 operation type、pending action、normal message、platform recovery、result correction、business resume 和 interrupt 对账 | 运行时通信/PostToolUse/list/interrupt 分支、Skill/全局规则、通信和恢复 fixtures | WP-02、WP-03 | 四类通信不靠正文猜测；三种调用观察均有固定转换；次数隔离；unknown 不自动重发；interrupt unknown 不伪造 interrupted |
| WP-05 正式结果与父任务闭环 | 实现完整结果文件、固定提交顺序、幂等/冲突、有限纠正、验收和 parent disposition | result Schema、运行时 SubagentStop/result/parent disposition、结果测试 | WP-01～WP-04 | 不再截断正式结果；先写并回读 result 再更新状态；complete 必须父验收；冲突不覆盖；accept/reject/close/select 原子且可回读 |
| WP-06 等待、恢复和会话闭环 | 实现 action-required、20分钟巡检工作流、SessionStart/End、Stop、中断后处置、重复执行和 tombstone 生命周期 | 运行时 wait/list/session/stop 路径、生命周期/恢复/中断 fixtures | WP-02～WP-05 | 网络断流可有限恢复；所有未解决状态跨 compact/resume 保留；Stop 读取失败执行三次规则；多 attempt 可选择并可靠关闭未选执行 |
| WP-07 最小诊断与轻量 group | 重写无副作用诊断，增加仅含引用的显式 group 和派生汇总视图 | 运行时 diagnose/group、README、诊断与并发测试 | WP-02、WP-05、WP-06 | 诊断只读、稳定 JSON、部分失败有界；group 不拥有执行状态机；individual task 仍是权威来源 |
| WP-08 旧路径退役与发布验证 | 删除已被替代的正文解析、旧状态、自由文本终态和过度设计目标，完成发布工具与真实平台验收 | 运行时旧函数、测试 fixture、README、发布脚本；获得明确发布授权后才包含稳定源与缓存 | WP-01～WP-07 | 无删除父项的残留消费者；全套仓库验证通过；N/N-1 整体回滚可用；真实矩阵逐项记录 passed/failed/not_checked |

### 18.4 每个工作包的实施规则

1. 修改运行时代码前，先增加能够稳定复现当前缺口的最小测试；纯删除现状错误测试时，先证明新路径已有覆盖。
2. 每个工作包只修改直接相关文件，保留用户已有改动；不得顺带重构无关发布、诊断或协调代码。
3. 新旧路径存在调用依赖时，先让新路径成为唯一消费者，再在同一工作包或紧邻工作包删除旧实现；不得先删除结果来源、身份映射或 Stop 保护。
4. StateStore、result 文件、PreparedContract 和 tombstone 的写入转换必须在稳定锁内完成 CAS、原子替换和回读验证；失败时不得宣称转换成功。
5. 任何 unknown 都不能自动转换为 failed、complete、interrupted 或 closed；只有更强的真实平台或明确父处置事实才能推进状态。
6. 任何业务正文、结果、原因、证据和建议都由 AI生成；脚本只做已确认的字段、类型、长度、枚举、引用和基本组合校验。
7. 每个工作包完成后同步更新运行时契约、Schema、Skill、`assets/agents-governance.md` 和相关测试，避免规则漂移；不要求不相关文档重复所有细节。
8. 所有工作包默认只修改本开发仓库。写入稳定发布源、Marketplace、运行缓存、Hook trust 或 Registry 仍需用户明确要求“发布、安装或更新稳定版”，本文不构成该外部写入授权。

### 18.5 最低验证门槛

每个涉及运行时的工作包至少执行：

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
```

并根据修改范围补充：

- Plugin validator。
- Skill validator（修改 Skill 或分发资产时）。
- JSON fixture 与 Schema 校验。
- 安装/发布工具测试（修改 SG-F04 时）。
- `git diff --check`。

稳定发布前还必须执行第十七节真实验收矩阵，确认开发仓库、稳定发布源和运行缓存不是同一路径或符号链接，并核对稳定源与目标缓存哈希。无法在当前环境验证的真实平台项必须标记 `not_checked`，不能默认通过。

### 18.6 改造完成判定

只有同时满足以下条件，才能称插件改造完成：

- WP-01～WP-08 均达到完成条件。
- SG-F01～SG-F08 的保留能力均有实际消费者和测试，已删除父项不存在残留字段、分支或断言。
- 全部未解决任务都不会因时间、容量、会话结束或治理组件异常静默消失。
- 派发、通信、恢复、中断、结果和父处置的 success/failed/unknown 路径均有证据。
- 本地验证全部通过，真实 Codex 项逐项记录 passed、failed 或 not_checked。
- 发布与回滚验证完成前，不删除上一稳定缓存、legacy Hook 或稳定备份。

其中“开发仓库改造完成”和“稳定版可发布”必须分开：真实平台项尚为 `not_checked` 时可以完成本地代码改造，但不能据此宣称稳定发布验收完成；发布关键项必须实际通过或由用户明确接受对应风险后，才能进入稳定源和缓存更新。

### 18.7 WP-08 后当前实现覆盖结论

- WP-01～WP-08 的开发仓库实现均已完成；第5～18节中“当前仍有”“后续必须替换”等措辞保留为盘点时和阶段执行前的历史事实，当前状态以本节、第十五/十六节和WP-08方案实施结果为准。
- 已删除父项的专属运行字段、分支、自由文本结果、legacy测试、诊断桥和发布迁移要求不再列为待办；当前没有未确认修改点。
- 真实平台 `not_checked` 只表示当前任务未安装或加载目标新版本，不能反推产品设计仍有冲突，也不能把旧安装缓存的行为算作目标版本证据。
- 开发仓库本地改造完成；稳定发布尚未验收。后续只有在用户另行授权发布/安装后，才执行稳定源、Marketplace、运行缓存、全局入口和Hook trust写入。

## 十九、最终完成结论

1. SG-F01～SG-F08 均已完成盘点。
2. 全部大功能的作用、边界、现状、改造方向、退役内容和验证缺口已经逐条列出。
3. WP-01～WP-08 已完成开发仓库本地实施；稳定发布、安装和真实平台验收未执行。
4. 当前仓库按隐藏文件在内的52个有效文件重新盘点，全部有保留功能归属。
5. `scripts/subagent_governance.py` 的全部顶层代码区段均有归属；旧混合状态、自由文本终态、legacy生命周期分支和诊断/Session薄桥已退役。
6. 已删除或替代的文件包括旧 Provider文本特判fixture、`compatibility.md`、`related-skills.md` 和含混的 `opaque-spawn-v1.json`；后者由当前精确task_ref fixture替代。
7. 完整多 Agent 编排、复杂诊断协议、多层结果存储和大量身份体系保持明确收缩，不是后续目标。
8. 网络不稳定下的20分钟等待、目标对账、同 Agent一次自动加一次用户授权恢复继续作为核心能力保留。
9. unmanaged原生路径继续不创建治理状态；无效 `sg_` governed调用继续硬拒绝；历史旧记录不迁移、不补默认值，只按当前操作字段或诊断事实处理。
10. 本地验证和发布工具证据可以证明开发仓库改造完成，但不能替代新版本真实加载、Hook trust、真实SubagentStop/group/Session链路或N/N-1整体回滚；这些项保持 `not_checked`，当前不存在产品设计冲突或未确认修改点。
