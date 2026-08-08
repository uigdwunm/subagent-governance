<!-- subagent-governance:start -->
## 子 agent 协作

- 所有与子 agent 有关的自然语言说明、dispatch prompt、中途通信和终态通知都必须使用中文。模型名、强度值、命令、代码、文件路径、agent ID、canonical task path 和协议状态等技术标识可以保留原文。
- 使用 `light`、`standard`、`strict` 或 `auto` 治理等级增强原生 `spawn_agent`，选择最低但足够的等级；不确定时使用 `auto`。只读、短时、低风险任务优先 `light`，普通编码、诊断、研究和 Review 优先 `standard`，安全、迁移、数据风险、并发写入、多阶段验收或允许下级子 Agent 的任务使用显式 `strict`。
- `auto` 只根据可观察的派发信号选择证据强度。`auto` 提升到严格证据要求时，不自动强制固定终态模板；只有父 agent 显式选择 `strict` 才执行完整严格契约和终态卡校验。
- Codex 的原生子 Agent 传输可能在 Hook 运行前把 `message` 加密。每次调用 `spawn_agent` 时，`task_name` 必须使用 `sg_<mode>_<semantic_name>` 形式携带可机械识别的治理等级，例如 `sg_strict_security_review`；`semantic_name` 只使用小写字母、数字和下划线。正文中的 `【治理等级】` 仍用于子 Agent 阅读，但不得作为 Hook 唯一可见的等级来源。
- 当正文在 Hook 层不可见且 `task_name` 没有治理前缀时，Hook 按 `standard` 兼容模式处理；需要可靠的 `light`、`strict` 或 `auto` 行为时必须使用对应前缀。
- 调用 `spawn_agent` 前，父 agent 必须先在主线程发送一条用户可见的说明。单个子 agent 使用以下固定格式，不得展示内部任务 ID 或英文属性名 `fork_turns`：

  ```text
  【子 Agent 派发】
  目标：<本次子 agent 要解决的问题>
  治理等级：<light | standard | strict | auto>
  模型：<显式模型，或“继承主 Agent（未显式覆盖）”>
  强度：<显式强度，或“继承主 Agent 当前强度（未显式覆盖）”>
  是否继承主线程全部上下文：<是 | 否 | 否（仅继承最近 N 轮）>
  工作范围：<允许读取、修改或验证的范围>
  完成条件：<可验证的终态条件>
  回传要求：完成、阻塞或需要决策时，向父 agent 发送明确终态通知
  ```

- `fork_turns: "all"` 对外显示为 `是否继承主线程全部上下文：是`；`fork_turns: "none"` 显示为 `否`；正整数 N 显示为 `否（仅继承最近 N 轮）`。用户可见说明中禁止出现 `fork_turns` 字样。
- 批量并行派发时，可以用一条 `【子 Agent 批量派发】` 表格列出每个 agent 的目标、治理等级、模型、强度、是否继承主线程全部上下文和完成条件；不得省略任何一个 agent。
- 不得猜测未显式设置的模型 slug 或推理强度；继承时按上述固定措辞报告。
- 所有 dispatch prompt 都必须包含 `【治理等级】light|standard|strict|auto`，说明唯一当前目标，并明确工作范围和完成条件。不得把旧 ACK、旧任务或父线程历史写成高于本次派发的指令。
- `light` 任务保持简洁，至少包含 `【目标】`、`【工作范围】` 和 `【完成条件】`；不得为了满足格式扩写成重型契约。
- `standard` 任务还应明确模型、强度、上下文策略、终态通知义务和是否允许下级子 Agent；完成条件必须可验证。
- 显式 `strict` 任务必须包含以下契约字段：`【目标】`、`【工作范围】`、`【禁止范围】`、`【完成条件】`、`【验收证据】`、`【上下文策略】`、`【下级子 Agent】`。完整继承上下文时必须说明理由；模型、强度和实际上下文继承方式也必须写清楚。正文为明文时 Hook 可机械校验这些字段；正文被原生传输加密时，Hook 只能机械校验 `task_name` 等可观察元数据，字段完整性由父 Agent 和子 Agent 的提示契约保证。
- `【下级子 Agent】` 必须明确写 `禁止` 或 `允许`。写 `允许` 时，dispatch prompt 必须完整写入本节的 20 分钟通知等待、目标范围巡检、同 agent 恢复和终态通知规则；不得只引用 `AGENTS.md`。
- 调用 `send_message`、`followup_task` 或为业务目的调用 `interrupt_agent` 前，父 agent 必须先在主线程使用以下固定格式说明本次通信目的：

  ```text
  【子 Agent 通信】
  对象：<agent ID 或 canonical task path>
  目的：<补充上下文 | 修正方向 | 请求终态通知 | 恢复执行 | 其他明确目的>
  原因：<为什么现在需要通信>
  期望结果：<收到消息后应完成什么>
  ```

- `send_message` 和 `followup_task` 的实际消息必须使用中文，并包含 `【通信目的】`、`【具体内容】`、`【期望结果】`。健康巡检中的 `wait_agent` 和目标范围 `list_agents` 不属于业务通信，保持静默，不发送用户可见巡检消息。
- `light` 终态可以简洁，但必须给出实际结果，不能只有“收到”“明白”或“开始执行”。
- `standard` 终态以及 `auto` 提升的严格证据终态必须说明实际结果、执行过的验证或证据和剩余事项，并保留派发中的治理任务 ID（如果存在）；不强制固定模板。
- 显式 `strict` 终态必须使用以下中文格式；工作流可以在其中保留 `WORK_ITEM_COMPLETE`、`BLOCKED` 等协议状态，但不得用协议状态替代中文字段：

  ```text
  【子 Agent 终态】
  状态：完成 | 阻塞 | 需要决策
  目标：<原任务目标>
  结果：<完成内容或问题>
  验证：<执行的检查和结果>
  剩余事项：<无或明确事项>
  父任务下一步：<建议父 agent 如何继续>
  ```

- 当子 agent 使用 `fork_turns: "none"` 或在独立新对话中启动时，父 agent 必须在 dispatch prompt 中明文写入该子 agent 的终态通知义务；如果该子 agent 还会继续派发下级 agent，也必须明文写入本节的 20 分钟巡检与异常恢复规则。不得依赖父对话、隐式继承或要求新 agent 自行查找这些规则。
- 派发子 agent 后，父 agent 保存目标 agent 的 ID 和 canonical task path，并进入通知等待循环，以 `timeout_ms: 1200000` 调用 `wait_agent`。
- 正常的 mailbox update、子 agent 消息、完成通知或用户输入会提前结束等待；父 agent 立即退出本轮循环并按原工作流处理。子 agent 的正常完成不需要巡检介入。
- mailbox 明确报告 `stream disconnected`、`errored` 或其他平台执行失败时，应立即调用目标范围的 `list_agents` 完成状态对账，再决定恢复；不必等待 20 分钟超时。
- 仅当 20 分钟等待超时时，调用一次 `list_agents` 检查该目标 agent；支持时使用其 canonical task path 作为 `path_prefix`，不要扫描或分析无关代理。
- 如果目标 agent 仍处于正常运行状态，不输出进度说明，不读取代码、Git、日志或测试状态，不发送心跳或追问，立即再次以 `timeout_ms: 1200000` 调用 `wait_agent`。
- 超时本身、沉默、测试耗时或上下文压缩都不是异常证据。只有平台状态客观显示本应运行的目标 agent 已停止、消失或异常，且父 agent 没收到终态通知时，才进入恢复流程。
- 恢复时优先对同一个 agent 使用 `followup_task`，要求其继续原任务或补发终态通知；能够继续时等待同一个 agent。治理组件只允许同一任务在普通 `platform_error` 后自动恢复一次；恢复后再次出现平台错误时必须停止重试、进入 `needs_decision` 并询问用户是否切换 provider、模型或稍后重新派发。若错误明确表示加密函数输出无法解密或解码，则属于 `provider_protocol_incompatible`，首次确认后立即进入 `needs_decision`，不得对同一 agent 执行无效恢复。只有原 agent 客观上无法继续或无法接收 follow-up 时，才从已保留的 checkpoint 重建同一任务。
- `list_agents` 失败或状态含糊时不得中断或重建；继续等待并在下一轮重新检查。
- 健康巡检路径的唯一常规操作是 `wait_agent`、目标范围的 `list_agents`、再次 `wait_agent`；不得插入用户可见的巡检消息或其他业务判断。
- 成功调用 `interrupt_agent` 后，治理任务进入 `interrupted` 终态，父任务不得继续把它视为运行中任务；中断失败时保持原状态。
- `list_agents` 确认 Agent 为普通 `errored` 时，治理任务进入 `platform_error`，记录平台错误并退出假运行状态；首次成功 `followup_task` 和后续 `SubagentStart` 会把同一任务恢复为运行中。同一任务恢复后再次确认平台错误时进入 `needs_decision`，不得继续自动 `followup_task`。加密函数输出无法解密或解码时直接记录 `provider_protocol_incompatible` 并进入 `needs_decision`。
- 子 agent 在完成工作、遇到阻塞或需要决策时，必须向父 agent 发送符合当前治理等级的明确终态通知。仅完成代码、创建提交或停止运行，不视为已通知父 agent。
- Hook 和 Skill 只提供用户级协作护栏、状态恢复和诊断，不替代 Codex 沙箱、批准机制、provider 稳定性或平台内部消息投递保证。它们可以识别并记录 `stream disconnected` 和明确的 provider 协议不兼容，但不能修复 provider 流。治理状态异常时应告警并降级放行原生子 Agent；未映射到治理任务 ID 的特殊启动路径不得因固定模板被强制阻止。
<!-- subagent-governance:end -->
