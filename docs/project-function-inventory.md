# 项目功能清单

本文描述 v5 当前有效功能。v4 的正式结果持久化、业务验收、结果补交和四平面设计已经退休，不再构成运行时契约。

## F01 治理等级与 TaskContract

- 支持 `light|standard|strict|auto`。
- 显式等级不自动升降；auto 只按结构化 task features 解析。
- TaskContract 固定表达目标、背景、工作与禁止范围、完成条件、证据要求、相关文件、当前状态、模型、强度和上下文策略。
- 插件只做字段、枚举、类型、长度和基本组合校验，不评价业务内容。

## F02 PreparedContract 与派发门禁

- `--prepare-dispatch` 在原生 spawn 前持久化并回读 PreparedContract 和初始 StateStore。
- task name 使用确定性 task ref；PreToolUse 不读取业务正文。
- initial 和 retry 在 preparation 与 claim 两处校验 work item open 和 attempt 未关闭。
- spawn retry 最多两次；unknown observation 禁止复用 attempt。

## F03 Identity 与 retained provenance

- `agents[target]` 是 active index。
- execution 的 `dispatch_record.dispatch_target` 是 retained provenance。
- 唯一未关闭 retained candidate 可修复索引；多个候选或索引冲突要求 reconcile。
- historical closed target 不复活；没有 canonical provenance 才按 unmanaged 兼容。
- 插件不注册 `SubagentStart`、`SubagentStop`；原生事件不建立 managed identity 或终态事实。

## F04 StateStore

- 每个 Session 一份 JSON 和稳定 lock。
- 当前 `state_format_version=5`。
- 每个 execution 的 canonical planes：
  - `dispatch_record`
  - `observation_record`
  - `closure_record`
- StateStore 保存有限契约摘要、identity、pending operation、恢复计数和 tombstone。
- StateStore 不保存业务结果正文、业务验收、结果协议、结果引用或摘要哈希。
- v4 锁内迁移只把精确绑定的旧父记录降维为 terminal notification，并删除全部结果相关字段。

## F05 通信与生命周期操作

- `normal_message`：补充上下文，不改变生命周期。
- `platform_recovery`：只适用于精确 observation error；一次自动恢复和一次用户授权恢复。
- `business_resume`：在 terminal notification 已到且父动作允许时创建新 attempt。
- `interrupt`：显式请求目标停止，unknown 保持 reconcile。
- pending action 使用 prepared/claimed 两阶段和 `tool_use_id` 对账。
- managed lifecycle operation 在前置状态不可可靠写入时拒绝；normal message 在真实 StateStore unavailable 时可告警 fail-open。

## F06 等待与平台观察

- 正常等待使用20分钟 timeout。
- 正常超时后做一次 exact target 巡检；明确平台错误立即巡检。
- `list_agents` adapter 只读取顶层 `agents`。
- 非空事实要求 query target、agent name 和唯一 dispatch target 精确一致。
- platform completed/stopped/interrupted 只证明平台终态，不生成业务结论。
- 平台终态先到时 closure 为 `await_notification`，父动作是 reconcile。

## F07 Terminal Notification Channel

- 父 Agent 通过 `--record-terminal-notification` 记录当前原生 child notification。
- 输入只包含 exact sender target、task、attempt 和 terminal status。
- 相同通知幂等；冲突 terminal status 保留首个事实并进入 reconcile。
- 通知正文不扫描、不持久化。
- 通知到达后 closure 为 `await_parent`，父动作是 `decide_disposition`。
- 不创建独立结果目录或结果文件。

## F08 父处置

- `--parent-disposition` 只接受 `close_task`。
- close 关闭全部可靠非运行 attempts，对明确 running attempts 返回 interrupt targets。
- 关闭写最小 tombstone，保留7天。
- 插件不提供 accept/reject 业务验收。父 Agent 直接阅读原生通知并自行判断是否关闭或继续。

## F09 Group

- Group 只保存 ID、目标摘要、member task IDs 和 required 标志。
- `summary_ready` 要求 required 非空且每个 required member 已收到 terminal notification 或已关闭。
- `group_action_required` 聚合 required members 的 individual action-required。
- optional members 不影响 required 聚合。
- 不建立 DAG、batch、wave、aggregate business result 或组级状态机。

## F10 Session 闭环

- SessionStart 对账 prepared/claimed 操作、清理到期 tombstone，并输出 work-item 决策摘要。
- Stop 最多读取 StateStore 三次，只给 advisory，固定 fail-open。
- SessionEnd 只在无 action-required 且无保留期 tombstone 时删除 Session JSON。
- 稳定 lock 永不删除。
- v5 不读取或删除旧结果文件；历史磁盘数据由用户自行清理。

## F11 诊断

- `--diagnose` 使用无锁只读路径。
- 不创建数据根、Session、lock、临时文件，不 reconcile、修复或回写。
- 输出 Session、work item、execution candidate、notification、closure、group 和 bounded issues。
- 不扫描旧结果目录，不输出业务正文。

## F12 Hook 兼容

- 官方事件字段由 `schemas/codex-hook-events-v1.contract.json` 固化。
- correctness-critical 非官方字段不建立强事实。
- unknown lifecycle extensions fail-open。
- 无 governed provenance 的原生操作不创建半套状态。

## F13 安装、升级和发布

- 插件 manifest、Skill、Hooks 和 Marketplace 元数据由开发仓库维护。
- 安装缓存与稳定发布源不作为开发修改源。
- release preflight 检查版本、权限、符号链接、敏感信息和 Git 引用。
- 当前任务未授权发布、安装或更新稳定版时，不写稳定源、Marketplace、运行缓存或 Hook trust。

## 机器语义来源

- `schemas/governance-semantics.schema.json`：状态、枚举和运行时规则。
- `schemas/task-contract-v1.schema.json`：TaskContract。
- `schemas/codex-hook-events-v1.contract.json`：官方 Hook 字段能力边界。
- `skills/subagent-governance/SKILL.md`：Agent 可执行协议。
- `skills/subagent-governance/references/runtime-boundaries.md`：运行边界摘要。
