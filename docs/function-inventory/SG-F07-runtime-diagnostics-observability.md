# SG-F07 运行诊断、问题定位与可观测性盘点

> 历史盘点：本文按 v4 功能边界编写，已被 `docs/project-function-inventory.md` 的 v5 清单取代。文中 SG-F06、TaskResult 和已删除 Schema/文档路径只表示历史依赖，不是当前文件或运行时契约。

## 文档状态

- 当前状态：盘点完成；八个首轮候选已收缩为六个最终功能点，文件、核心代码区段、测试、疑似退役内容、跨功能冲突和统一修改方案输入均已登记。
- 最终名称：**运行诊断、问题定位与可观测性**。
- 一句话职责：只读汇总派发、生命周期、平台观察和终态结果留下的可观察证据，说明治理任务当前状态、问题位置、证据边界和必要操作提示，而不执行恢复、不替代业务验收，也不修复 Codex/provider 传输故障。
- 本文是 SG-F07 的唯一盘点文档；不修改主盘点文档或 SG-F04、SG-F05、SG-F06、SG-F08 独立文档。
- 逐项盘点期间已经按用户授权完成诊断参数分流修补和少量现状证据测试；整体收口本轮只修改本文，其余运行诊断读取、输出、状态版本和分类改造均留作最终统一方案输入。

## 一、功能边界

### 1. 主要负责

- 提供运行期治理状态的只读诊断入口和明确检查范围。
- 汇总 Session、任务、Agent、最后状态变化、现有计数、平台观察、终态结果引用和治理健康信息。
- 基于可观察事实定位问题阶段和原因，标明证据来自状态、Hook、平台响应、Agent 自述还是诊断派生，不把指导术语直接伪装成平台事实或单一运行状态。
- 提供形状稳定的机器可读 JSON 和简短操作提示；父 Agent 继续负责组织主对话业务表达，本地完整状态继续作为直接诊断证据。
- 定义诊断读取与输出的容量、保留期、部分失败、实际外显字段和 StateStore 版本读取边界。

### 2. 明确不负责

- 不重新定义 SG-F01 的治理等级、派发契约和上下文策略。
- 不拥有 SG-F02 的插件发现、Hook 注册和普通事件路由，只消费其 CLI 入口交接。
- 不生成 SG-F03 的业务通信或恢复消息，也不实际调用恢复、中断或等待工具。
- 不重复 SG-F04 的安装健康、部署同步、发布就绪、Marketplace、缓存或 Hook trust 诊断。
- 不重新实现 SG-F05 的 StateStore 安全、状态转换、等待巡检、同 Agent 恢复和会话生命周期。
- 不生成、验收或持久化 SG-F06 的正式 TaskResult，只诊断其状态、引用、完整性和读取结果。
- 不创建远程遥测、后台监控器、第二套调度器或新的 Agent 编排平台。
- 不读取 transcript，不通过自由错误文本猜测 provider 根因、消息必然投递成功或业务实际完成。

## 二、首轮候选功能点与最终收缩

1. 诊断入口与检查范围。
2. 治理健康与降级告警。
3. Session、任务与 Agent 状态快照。
4. 状态转换与证据链。
5. 诊断问题定位与分类模型。
6. 分层诊断输出与机器可读报告协议。
7. 容量、保留与实际外显边界。
8. 状态版本读取与证据来源边界。

八个功能点共用同一套状态读取、证据边界和诊断输出，不需要拆成第二个大功能。安装发布诊断继续独立归 SG-F04。

### 整体去臆想审查与最终统一删减清单

用户复核后确认，前六项盘点把若干“未来可能需要”的设计扩大成了“必须建设”的目标。以下内容先保留原文作为盘点过程记录，最终统一审查时删除、降级或合并，不据此继续增加运行时代码、Schema 或测试：

1. 删除全面脱敏、凭证泄露、Issue、CI、日志转发或 provider 扩散等没有当前仓库和运行证据支持的威胁场景；本地原始状态保持完整，只检查实际输出是否包含完成当前用途所需的字段。
2. 删除完整事件/attempt 因果链目标，不建设包含 `event_id`、`attempt_id`、`caused_by_event_id`、八类事件及长期审计历史的新事件系统；优化计划只明确要求展示最后状态转换，因此第 4 项最终并入任务快照，只保留最后变化、现有计数和必要问题依据。
3. 删除“四个持久输出层加一个即时通道”及所有摘要必须从 `subagent-diagnostic-v1` 派生的权威报告管线；当前只需要一个形状稳定的诊断 JSON，Hook 告警、SessionStart 恢复摘要和父 Agent 用户表达继续承担各自已有职责。
4. 删除没有真实数据规模或调用需求支持的分页、稳定游标、`--task`、Agent、attempt、结果引用查询矩阵；如以后确有输出过大问题，先采用简单数量上限和遗漏数，再由实际需求决定是否增加选择器。
5. 大幅收缩 `DiagnosticIssue` 设计，不预先固定五级可信度、证据引用图、多问题选择规则和完整候选问题码列表；只保留当前事实能支持的原始任务状态、组件健康、稳定问题码、证据来源和必要父任务提示。
6. 删除把尚未实现的 SG-F08 协调组、组级报告和协调事件作为 SG-F07 当前输入的设计依赖；只保留跨功能边界说明，等真实协调状态存在后再盘点诊断交接。
7. 删除独立诊断 Schema 的 N/N-1 别名、问题码迁移和报告兼容体系预设计；当前只需在读取 StateStore 时如实区分支持、未知和不支持版本，没有外部机器消费者前不创建第二套版本协议。
8. 删除预先指定的 `0` 至 `4` 五档退出码方案；保留当前已经成立的 `0` 成功和 `2` 用法错误，部分失败或完全不可用需要非零时再按最小实际语义确定。
9. 不把“主对话用户摘要”作为脚本生成的新功能；脚本提供可观察事实和必要操作提示，父 Agent 继续根据正式结果与诊断事实组织用户表达。
10. 取消第 7 项原拟增加的 StateStore `0700`/`0600` 权限测试；该安全边界已归 SG-F05，不在 SG-F07 重复固化。
11. 最终统一审查时复核 `test_recovery_state_keeps_counters_but_no_transition_history`：它只证明当前没有事件字段，不是长期产品契约，宜删除或改写为验证最后状态变化的目标行为。`test_diagnose_active_count_excludes_stale_and_action_required_records` 同样只作为现状矛盾证据，改造 `active` 后应同步重写，不能阻止合理修复。

去除上述预设计后，SG-F07 最终应收缩为以下六个相互关联的功能点：

1. 诊断入口与只读检查。
2. 治理健康、降级与部分读取失败。
3. Session、任务、Agent 快照及最后状态变化。
4. 基于真实证据的问题定位。
5. 稳定机器可读 JSON 与简短操作提示。
6. 容量、保留和状态版本读取边界。

第 7 项后续按“容量、保留与实际外显边界”审查，不再以笼统敏感信息或攻击场景为前提；第 8 项仅补充状态版本读取和证据能证明什么，最终并入第 1、4、6 项，不再维持独立复杂协议设计。

第三至第十节保留逐项盘点时的原始分析和用户纠偏过程，其中关于全面脱敏、完整事件链、复杂诊断 Schema、分页、raw 模式和多层持久报告的旧建议不再代表最终目标；发生冲突时，以本节删减清单和第十一节整体收口结论为准。

## 三、第 1 项：诊断入口与检查范围

### 1. 当前情况

运行时通过 `scripts/subagent_governance.py` 的 `main()`、`_diagnose()` 和以下参数提供诊断入口：

- `--diagnose` 进入诊断模式。
- `--data-root` 显式选择状态数据根目录；未指定时依次使用 `SUBAGENT_GOVERNANCE_DATA`、`PLUGIN_DATA/state-v1` 或当前用户临时目录。
- `--session` 选择单个 Session；未指定时扫描数据根目录下的全部 `*.json`。

当前已经成立的行为：

- 输出始终包含解析后的绝对 `data_root`。
- 全局扫描按状态文件路径稳定排序。
- 全局扫描跳过符号链接和非普通文件。
- 输出使用 JSON；全局摘要包含 `session_id`、`active`、`tasks`、`health` 和 `updated_at`。
- 单 Session 路径输出完整状态对象。

当前确认的问题：

1. **诊断存在写入副作用**：数据根准备会创建目录并执行 `chmod 0700`；单 Session 查询通过 `StateStore.read()` 创建锁文件，损坏 JSON 还会被隔离并替换为空的 degraded 状态。当前 `--diagnose` 因此不是严格只读命令。
2. **两条读取路径语义不一致**：全局扫描直接 `json.loads()`，绕过 StateStore 的所有者、大小、Session ID、根节点和记录形状检查；单 Session 查询则执行 StateStore 的完整读取与恢复行为。
3. **部分失败被静默丢弃**：全局扫描对读取错误和 JSON 损坏直接 `continue`，不报告跳过数量、文件原因或 `partial/degraded`，并始终返回退出码 0。
4. **不存在的 Session 被伪装为空状态**：`StateStore.read()` 对不存在的状态文件返回 `_empty_state()`，诊断不能区分 `not_found` 和真实空 Session。
5. **单 Session 默认输出过度原始**：完整状态可能包含任务正文、规范路径、错误文本、平台摘要和终态结果片段，尚无默认脱敏摘要或显式 raw 边界。
6. **参数边界原本不严谨**：`main()` 在检查未知参数前进入诊断分支，导致 `--diagnose --unexpected` 被静默接受；`--session` 和 `--data-root` 也可脱离 `--diagnose` 落入 Hook stdin 模式。
7. **检查范围过粗**：当前只能查看全部 Session 汇总或完整单 Session，不能按 `task_id`、Agent 身份、attempt 或结果引用展开。
8. **错误输出不统一**：诊断路径位于普通 Hook 的顶层异常包装之外；根目录、单 Session 或记录形状错误可能直接形成 traceback，而全局部分失败却静默成功。
9. **缺少容量与分页边界**：全局扫描会一次输出所有 Session，没有记录上限、分页、稳定游标或按需展开协议。

### 2. 与前后文的交接

#### 上游交接

- SG-F02 拥有统一 Python CLI、Hook stdin/stdout 和普通事件路由；SG-F07 只拥有诊断模式的参数分流、读取范围和诊断错误语义，不借此重构各 `_handle_*` 业务 handler。
- SG-F05 拥有 StateStore、数据根、安全检查、状态版本、锁和损坏隔离；SG-F07 应消费统一的只读解析或适配层，不重复定义状态安全，也不借诊断命令执行状态恢复。
- SG-F01 提供稳定任务契约引用；SG-F03 提供通信、恢复和 attempt 身份。未来的按任务诊断应消费这些机械引用，不解析自由正文重新猜测任务身份。
- SG-F06 提供正式结果、结果引用和完整性字段；诊断只读取结果可用性、引用状态和错误，不生成或改写 TaskResult。

#### 下游交接

- 第 2 项定义 `healthy`、`partial`、`degraded`、错误对象和治理告警。
- 第 3、4 项定义 Session、任务、Agent、attempt、平台观察和最后状态转换的具体读取与展示。
- 第 5 项定义诊断阶段、原因、证据可信度和父任务动作，不由 CLI 选择器直接生成失败结论。
- 第 6 项定义机器可读诊断 Schema、父任务详情、用户摘要和受限 raw 模式。
- 第 7 项决定绝对路径、任务正文、错误文本、tool response 和结果内容在哪一层允许出现。
- 第 8 项决定旧 StateStore 版本、未知字段、不支持版本和 N/N-1 读取策略。

#### 跨功能排除

- SG-F04 的 `check_installation.py` 已独立输出 `runtime_healthy`、`deployment_in_sync`、`development_rules_in_sync`、`retention_policy_satisfied` 和 `release_ready`；SG-F07 不合并这些安装发布状态。
- SG-F07 可以消费 SG-F04 最终确定的跨版本兼容结论，但不检查 Marketplace、缓存、Hook trust、Git tag 或发布候选。

### 3. 改进建议

1. 明确分离 Hook 模式和诊断模式；未知参数始终拒绝，诊断选择器只能与 `--diagnose` 同时使用。
2. 建立无副作用的只读状态解析器：不创建数据目录、不修改权限、不创建锁文件、不隔离或改写损坏状态。
3. 全局与单 Session 使用同一套文件类型、所有者、大小、版本、Session ID 和基本结构校验，避免两套读取语义。
4. 建立分层检查范围：默认全部 Session 脱敏汇总，`--session` 查看单 Session 详情，后续增加按 `task_id` 的稳定展开；Agent、attempt 和结果引用作为任务证据链中的选择或关联条件。
5. 明确区分 `not_found`、`healthy`、`partial`、`degraded`、`unsupported_version` 和命令用法错误。
6. 即使检查失败也优先输出合法、版本化的诊断 JSON，不把 Python traceback 作为正式错误协议。
7. 全局扫描输出检查总数、成功数、跳过数和有界错误列表；不得静默忽略损坏或不可读状态。
8. 为大量 Session 建立稳定排序、数量上限、分页或按需展开，避免无限输出。
9. 保留实际数据根作为父任务和本地诊断证据；是否在主对话用户摘要中展示完整绝对路径由第 7 项统一决定。
10. 保留现有 `--diagnose` 外部调用方式作为兼容入口；是否未来增加真正子命令，只有在 Hook 命令、文档和兼容迁移共同设计后再决定。

### 4. 本轮直接实施的改进

用户已授权实施以下低耦合参数修补：

- `main()` 先检查未知参数，再进入 `--diagnose`，因此 `--diagnose --unexpected` 现在返回退出码 2 和明确错误。
- `--session` 或 `--data-root` 脱离 `--diagnose` 使用时返回退出码 2，不再落入 Hook stdin 模式。
- 新增定向测试 `test_diagnose_rejects_unknown_and_orphan_selector_arguments`，覆盖上述三种调用。

本轮没有直接修改 `_diagnose()` 的读取、输出、状态恢复或退出码行为，也没有改动 StateStore、Schema、Skill、README 或其他盘点文档。

### 5. 必须留待最终统一方案的内容

- 无副作用只读解析器与 StateStore 安全辅助如何复用。
- 数据根不存在、Session 不存在、部分读取失败和损坏状态的诊断状态及退出码。
- 单 Session 默认摘要、脱敏规则和显式 raw 模式。
- `--task`、Agent、attempt 和结果引用的最终查询参数及歧义处理。
- 机器可读诊断协议、Schema 版本和错误对象。
- 全局扫描的错误列表、分页、容量预算和路径展示策略。
- StateStore N/N-1、未知版本、未知字段和不可回退版本的只读兼容。
- 诊断错误与普通 Hook 顶层异常的共享错误模型；不能因统一包装而改变 SG-F02 已登记的 PreToolUse deny/fail-open 边界。

### 6. 不再作为目标的内容

- 不保留“损坏或不可读文件静默跳过且整体始终退出 0”作为目标行为。
- 不把完整原始 Session 状态作为普通诊断的默认输出。
- 不让只读诊断隐式创建、修复、隔离或改写状态。
- 不把不存在的 Session 表达成看似真实存在的空状态。
- 不把运行期任务诊断与 SG-F04 安装发布诊断合并成一个含义不清的总健康命令。

### 7. 测试与证据

- 原有 `test_diagnose_reports_explicit_data_root` 只证明显式数据根和 `sessions` 键存在。
- 本轮新增参数边界测试，先稳定复现三种错误调用均返回 0，再通过最小修补使其统一返回 2。
- 第 1 项收口时共享工作区完整回归共 151 项，全部通过；`scripts/subagent_governance.py` Python 编译、Plugin validator 和 Skill validator 均通过。
- 当前仍缺少单 Session 输出、Session 不存在、损坏文件、权限错误、符号链接、非法根节点、部分失败、只读副作用、脱敏、分页和跨版本读取测试。
- 单元测试和本地状态文件只能证明脚本内部行为，不能证明真实 Codex/provider 投递、网络恢复、Agent 执行或业务完成。

### 8. 本项结论

- “诊断入口与检查范围”必须保留，主要归属为 `_diagnose()` 及 `main()` 的诊断参数分支。
- 本轮已直接修复两个独立且低风险的参数分流问题；其余问题与健康状态、输出协议、敏感信息和版本适配强耦合，只登记为最终统一方案输入。
- 当前诊断入口仍不能称为严格只读、完整或安全分层的运行诊断；完成第 2、6、7、8 项前，不应扩大公开能力承诺。

## 四、第 2 项：治理健康与降级告警

### 1. 当前情况

当前运行时实际上有两套健康表达，分别是持久化的 `health` 和单次操作的 `last_warning`/Hook 告警。

#### 持久化 `health`

- `_empty_state()` 默认写入 `{"status": "ok"}`。
- 只有 JSON 损坏或非 UTF-8 状态文件被成功隔离时，才构造 `{"status": "degraded", "reason": "corrupt-state-recovered", "quarantine": ..., "updated_at": ...}`。
- 目录、文件、锁、所有者、权限、大小、写入或状态结构错误不会统一写入 `health`，通常只在当前 handler 返回异常文本。
- `health` 没有独立 Schema、版本、状态枚举校验、影响范围、故障首次/最后时间、恢复条件或确认状态。
- `quarantine` 直接保存绝对路径，没有区分本地原始证据和用户可见摘要。
- `platform_error`、`protocol_error`、业务 `failed` 和 `state-degraded` 没有共享同一状态字段；这是应当保留的分层方向，但还没有结构化诊断对象承载。

本轮在临时目录进行只读代码行为探针，确认了两个重要差异：

1. 损坏文件经 `StateStore.read()` 检测时会被隔离并返回一次性的 degraded 状态，但因为 `read()` 不回写恢复状态，下一次读取可能看到新建的 `ok` 空状态。
2. 损坏文件经 `StateStore.update()` 检测时，degraded 会随更新写回；后续成功更新仍保持 degraded，`last_warning` 却已被清空，当前没有显式 recovered/acknowledged 状态。

#### `last_warning` 和 Hook 告警

- `StateStore.last_warning` 每次 `read()`、`update()` 或 `delete_if()` 开始时清空，只是单个调用周期的临时字符串，不是可靠诊断事件。
- 各 handler 分别向 `additionalContext`、`systemMessage`、`decision` 或启动上下文写入不同措辞；相同状态错误没有稳定错误码、组件、阶段、严重程度或证据引用。
- `SubagentStart` 对 warning 使用 `_bounded()`，但多数异常消息直接拼接原始异常文本，尚无统一长度和脱敏边界。
- fail-open 只表示原生工具继续执行，不表示治理任务、Agent 身份、终态结果或恢复记录已经成功保存。
- 顶层 `main()` 对 `PreToolUse` 未捕获异常仍可能返回 deny，而其他 Hook 异常通常降级放行；契约错误与插件内部错误尚未由统一错误对象区分。

### 2. 与前后文的交接

#### 上游交接

- SG-F05 负责状态文件损坏、读写失败、容量超限和存储不可用的检测、隔离、重建及 fail-open 行为；SG-F07 负责这些事实的诊断表达，不重新实现状态操作。
- SG-F02 负责顶层异常捕获以及 `additionalContext`、`systemMessage`、`decision` 的 Hook 交接；SG-F07 可以提供统一告警对象和渲染要求，但不能单独改变所有 Hook 的 deny/fail-open 规则。
- SG-F06 负责正式结果是否生成和持久化；结果存储失败可以成为诊断问题，但 SG-F07 不伪造缺失结果。
- SG-F03 的通信或恢复调用可能在状态不可用时降级放行；SG-F07 只记录受影响的操作和证据，不执行恢复。

#### 下游交接

- 第 3、4 项说明健康问题影响了哪些 Session、任务、Agent、attempt 或状态转换。
- 第 5 项把 `state-degraded` 建模为诊断原因或组件健康事实，不把它加入任务生命周期状态集合。
- 第 6 项决定结构化问题如何进入机器 JSON、父任务详情和主对话摘要。
- 第 7 项决定异常文本、绝对路径和隔离文件引用的脱敏与容量边界。
- 第 8 项处理旧版 `health`、未知状态和跨版本错误码。

#### 跨功能排除

- SG-F04 的 `runtime_healthy` 表示安装文件系统和部署健康，不与 SG-F07 的运行期治理健康合并。
- `platform_error` 表示平台明确报告 Agent 执行错误，不是 StateStore 自身健康问题。
- `protocol_error` 表示治理结果协议失败，不是存储健康状态。

### 3. 改进建议

建议将健康和告警分成四层：

1. **治理组件健康**：表达 StateStore、ResultStore 或诊断读取器是否 `ok`、`degraded`、`unavailable` 或 `unknown`。
2. **诊断执行完整度**：表达本次检查是 `complete`、`partial` 还是 `failed`，不写入任务 `status`。
3. **结构化诊断问题**：至少包含稳定错误码、组件、操作、发生/观察时间、影响范围、持续状态、恢复动作、父任务建议、有界脱敏摘要和原始证据引用。
4. **用户可见告警**：由结构化问题生成简短提示，不直接复制任意异常文本。

具体建议：

- 为损坏、不可读、不可写、超限、版本不支持、结果缺失等建立稳定错误码。
- 区分“已隔离”“已重建”“仍不可用”和“已经恢复”，不要只使用 `degraded`。
- 只有实际重新检查通过时才能从 degraded 转为 recovered/ok，并保留最近故障引用。
- `health` 不保存完整异常、凭证或无界路径；原始证据留在受限本地层。
- 数据根汇总健康根据所有 Session 和扫描错误计算，不能恢复成单一含糊的 `clean`。
- 统一 Hook 告警渲染器，明确哪些故障 fail-open、哪些协议完整性错误必须拒绝。
- fail-open 告警必须说明哪些治理记录没有成功完成，不能只写“已降级放行”。
- `state-degraded` 应是诊断原因或组件健康事实，不应进入任务状态集合。

### 4. 本轮直接实施的改进

本轮不修改运行时健康模型，只补充能够保护当前合理边界并暴露未来改造依据的测试：

- 扩展 `test_corrupt_state_is_quarantined_and_spawn_is_allowed`，断言 `health.reason`、`health.updated_at`、隔离路径及隔离文件存在。
- 新增 `test_successful_state_update_does_not_silently_clear_degraded_health`，确保成功更新不会把持久化的历史 degraded 静默改成 `ok`，直到未来明确设计恢复/确认状态。

以下内容没有顺手改动：错误码、health Schema、告警脱敏、`last_warning` 生命周期、统一错误渲染和 Hook deny/fail-open 语义。

### 5. 必须留待最终统一方案的内容

- `health` 的最终 Schema、版本和合法状态集合。
- Session 健康、数据根健康和单次诊断完整度的分层。
- 错误码、严重程度、影响范围和父任务动作模型。
- 损坏隔离后的 degraded、recovered、ok 生命周期和确认条件。
- StateStore、正式结果存储和诊断读取失败是否共用错误信封。
- 告警对象与 `additionalContext`、`systemMessage`、诊断 JSON 的映射。
- 原始异常、绝对路径和隔离文件引用的保存与脱敏规则。
- PreToolUse 明确契约错误与插件内部未知异常的 deny/fail-open 分界。
- N/N-1 对未知 health 字段和错误码的读取策略。

### 6. 不再作为目标的内容

- 不把 `state-degraded` 提升为任务生命周期状态。
- 不把 `platform_error`、业务 `failed`、`protocol_error` 和 StateStore 健康故障塞进同一个 `status`。
- 不把 fail-open 描述成任务已经成功记录、恢复或完成。
- 不长期保存未经脱敏的完整异常文本、绝对路径或平台响应。
- 不用一次成功写入或一次普通读取自动宣称治理状态已经恢复。
- 不把运行期治理健康和 SG-F04 安装发布健康合并成一个总 `clean` 结论。

### 7. 测试与证据

- 现有测试已覆盖损坏/非 UTF-8 隔离、派发写入失败、StateStore 初始化失败、终态保存失败、Session 清理失败和多条 fail-open 告警路径。
- 本轮新增测试覆盖结构化损坏证据和 degraded 不被成功更新静默清除。
- 第 2 项验证时共享工作区完整回归共 153 项，全部通过；Python 编译、Plugin validator、Skill validator 和差异检查均通过。完整回归包含并行盘点任务新增测试，不能全部归因于 SG-F07。
- 当前缺少统一 health Schema、错误码、影响范围、故障/恢复时间、告警脱敏、异常长度、跨 handler 输出一致性和诊断汇总健康测试。
- 现有单元测试和临时状态探针只能证明本地 handler/StateStore 行为，不能证明真实 Codex Hook 告警一定到达父任务，也不能证明 provider 或网络问题已经恢复。

### 8. 本项结论

- “治理健康与降级告警”必须保留并重点改造。
- 当前 fail-open 方向符合项目边界，但 `health` 生命周期不一致、`last_warning` 过于临时、告警没有结构化错误对象，导致无法可靠判断治理组件是否仍处于 degraded。
- 本轮只补充测试和盘点证据；健康 Schema、错误模型、恢复确认、脱敏和统一输出必须与第 3、5、6、7、8 项一起在最终方案中处理。

## 五、第 3 项：Session、任务与 Agent 状态快照

### 1. 当前情况

当前诊断入口只有“粗略 Session 计数”和“完整原始 Session 状态”两种输出：

- 全局扫描输出 `session_id`、`active`、`tasks`、`health` 和 `updated_at`。
- `tasks` 只是任务字典长度，不区分执行中、待处理、终态、陈旧、未知或身份未确认。
- `active` 来自 `_active_records()`，只计算过去 12 小时内、状态属于 `pending`、`dispatched`、`running`、`retry_required` 的记录。
- 单 Session 输出整个 StateStore，包括契约字段、生命周期字段、Agent 映射、平台观察、重试/恢复计数和结果片段。

当前确认的问题：

1. 超过 12 小时但仍未解决的 `running` 会从 active 消失。
2. `platform_error` 和 `needs_decision` 不计入 active，即使父任务仍必须恢复或请求决策。
3. `protocol_error`、`blocked` 等状态只进入总任务数，不显示待父任务处理含义。
4. 最近一次 `platform_checked_at` 会重新让长期任务进入 active，导致 active 反映“近期被检查”而不是单纯执行状态。
5. `dispatched` 当前没有写入者，却仍在 active 集合中；`retry_required` 同时用于平台恢复和终态补充。
6. SessionEnd 会保留未解决记录而不使用 12 小时窗口，但诊断汇总可能同时显示 `active=0`，形成跨功能矛盾。
7. `agents` 是 `agent_id → task_id` 和 `canonical_task_path → task_id` 的混合索引，不能用 `len(agents)` 统计 Agent 数量；同一任务可能占两个索引。
8. 派发成功但响应缺少身份时，任务仍会进入 `running`，形成 `unmapped running`；未纳入治理的原生 Agent 又不会进入此快照。
9. 单 Session 原始输出没有分组、排序、分页、遗漏计数、默认脱敏或未知字段标记。
10. Task 字典键、记录内 `task_id`、Agent 映射和状态字段不一致时，当前快照没有提示诊断异常。

本轮新增的定向测试确认了一个具体矛盾：同一 Session 中有近期 running、陈旧 running、近期 `platform_error` 和近期 `needs_decision` 四条记录时，SessionEnd 保留集合包含 4 条，但全局诊断输出 `tasks=4、active=1`。

### 2. 与前后文的交接

#### 上游交接

- SG-F01 提供任务 ID、治理等级、目标、范围、完成条件和上下文策略；快照只消费这些契约字段，不重新生成或验收契约。
- SG-F03 提供通信、恢复 attempt 和目标引用；快照展示关联结果，不执行通信或恢复。
- SG-F05 拥有任务状态、Agent 映射、平台观察、恢复、中断和 Session 生命周期；SG-F07 只能读取并派生摘要，不改变状态转换。
- SG-F06 拥有业务终态、正式结果、协议错误和父任务闭环；快照只展示结果状态和稳定引用。

#### 下游交接

- 第 4 项把任务时间、attempt 和状态变化串成证据链。
- 第 5 项根据快照事实计算失败阶段、原因、证据可信度和父任务动作。
- 第 6 项定义快照的机器 JSON、父任务详情和用户摘要。
- 第 7 项决定任务正文、Agent 路径、错误文本和结果字段的脱敏规则。
- 第 8 项处理未知状态、未知字段和跨版本快照。

#### 跨功能排除

- 快照只包含本插件已经记录的治理任务，不是 `list_agents` 的完整平台 Agent 清单。
- 安装版本、缓存和 Hook trust 继续属于 SG-F04。
- 快照不以“是否显示”为依据修改任务状态、执行恢复或清理记录。

### 3. 改进建议

建议把快照分为 Session 摘要和有界任务列表。

#### Session 摘要

至少应包含：

- Session ID、状态版本和健康状态。
- 任务总数和按原始状态分组的计数。
- 执行中任务数、待父任务动作数、已提交结果数。
- 陈旧未解决任务数、身份未确认任务数、未知状态数。
- 有效映射、失效映射和歧义映射数量。
- 最后状态活动时间，而不只是根 JSON 最后写入时间。
- 本次快照的检查完整度、遗漏数和诊断问题引用。

#### 单任务快照

建议保留原始字段并增加明确的诊断派生层：

- `task_id` 和原始 `status`。
- 治理等级及有限目标摘要。
- `execution_state`：是否仍可能执行。
- `identity_state`：已绑定、未确认、失效、歧义或 unmanaged。
- `parent_action`：等待、对账、恢复、请求决策、验收、归档或无。
- `result_state`：无结果、已提交、缺失、冲突或不可读。
- Agent ID/canonical path 的受限引用。
- 创建、更新、平台检查和最后活动时间。
- `stale` 及其判断依据。
- retry/recovery 计数和证据链引用。

其他建议：

1. 保留原始 `status`，派生字段明确标为诊断计算结果。
2. 不再以一个 `active` 数字承担所有语义。
3. `stale` 作为独立维度，不因时间过久而静默隐藏任务。
4. Agent 数量按唯一治理任务或稳定执行身份计算，不能使用 `len(agents)`。
5. 全局和单 Session 使用同一快照生成逻辑，并提供稳定排序、数量上限和遗漏计数。
6. 未知状态和未知字段保留原值并标为 unknown，不自动转换成完成或失败。
7. `unmapped running` 明确显示为身份未确认，不能看起来像正常运行。

### 4. 本轮直接实施的改进

本轮不新增诊断字段，也不修改状态集合，只新增一条定向测试：

- `test_diagnose_active_count_excludes_stale_and_action_required_records` 固化当前 `active` 12 小时窗口、`platform_error`/`needs_decision` 排除行为，以及它与 SessionEnd 保留集合之间的差异。

现有 Agent 映射和 `unmapped running` 测试已作为本项证据复用；没有重复创建同义测试。

### 5. 必须留待最终统一方案的内容

- 执行状态、业务结果、平台观察、父任务动作和清理资格的分层模型。
- `active` 是否删除、保留为兼容字段或重命名为 `recent_active`。
- stale 时间阈值、长期任务和近期平台检查的关系。
- `dispatched`、`unmapped running` 和 `identity_unconfirmed` 的最终语义。
- `retry_required` 的平台恢复与终态补充是否拆分。
- Agent ID、canonical path 和执行身份的统一引用模型。
- Session、任务和 Agent 快照的正式 Schema。
- 快照排序、分页、遗漏计数和容量预算。
- 结果引用、协议错误和 action-required 的快照字段。
- 未知状态、旧版本和损坏记录的展示策略。

### 6. 不再作为目标的内容

- 不继续把 `active` 当成 Session 是否仍有待处理工作的权威指标。
- 不用 `len(agents)` 表示 Agent 数量。
- 不把超过 12 小时的未解决任务静默隐藏。
- 不把完整 StateStore 原样输出当成默认诊断快照。
- 不根据快照推导结果直接修改任务状态或执行恢复。
- 不把治理任务快照描述成完整平台 Agent 清单。
- 不删除 `_active_records()` 作为死代码；它仍有兼容价值，但应在新模型完成后改名、降级为兼容字段或移除。

### 7. 测试与证据

- 现有测试覆盖 Agent ID/canonical path 映射、身份缺失时的 `unmapped running`、歧义候选不猜测、失效映射清理、终态不复活、平台错误、SessionStart 优先级和 SessionEnd 保留。
- 本轮新增测试确认 `active` 汇总与 SessionEnd 保留集合的差异。
- 第 3 项验证时共享工作区完整回归共 154 项，全部通过；Python 编译、Plugin validator、Skill validator 和差异检查均通过。完整回归包含其他盘点任务的并行修改，不能全部归因于 SG-F07。
- 当前仍缺少正式快照 Schema、按状态/动作/身份分组的诊断测试、陈旧任务展示、唯一 Agent 计数、失效映射计数、分页和默认脱敏测试。
- 单元测试、fixture 和本地 JSON 只能证明插件内部状态投影，不能证明它等于 Codex 平台完整 Agent 列表，也不能证明父任务一定看到了所有快照内容。

### 8. 本项结论

- “Session、任务与 Agent 状态快照”必须保留并重点改造。
- 当前 `tasks` 总数仍有基础价值，但 `active` 语义不足，`agents` 只是混合索引，单 Session 原始输出又过于宽泛。
- 目标应从“两个粗略数字或完整原始 JSON”改为“有界、分层、可解释且保留原始状态的 Session/Task 快照”。
- 本轮只新增差异证据测试；快照字段、状态分层、身份模型和输出 Schema 必须与 SG-F05、SG-F06 及后续诊断功能统一确定。

## 六、第 4 项：状态转换与证据链

### 1. 当前情况

当前运行时没有独立的状态转换日志、事件列表或 attempt 对象。各 Hook 直接覆盖同一条任务记录，最终 StateStore 只保留最近状态和少量辅助字段：

- `PreToolUse spawn` 创建 `pending` 记录，保存 `tool_use_id`、`turn_id`、`created_at`、`updated_at`、`retry_count` 和 `recovery_count`。
- spawn `PostToolUse` 将明确失败写为 `failed`，否则写为 `running`，并尽可能保存 Agent ID 和 canonical task path。
- `SubagentStart` 对已有活跃映射或唯一未绑定候选写入 `running`，但不记录身份绑定事件的来源、候选集合或可信度。
- `list_agents PostToolUse` 保存最近一次 `platform_checked_at` 和 `platform_status`；明确 `errored` 时覆盖为 `platform_error` 并保存有界错误摘要。
- 成功 `followup_task PostToolUse` 只执行 `recovery_count += 1` 并写入 `retry_required`，不保存恢复请求、工具调用或回调 attempt。
- 成功中断写入 `interrupted` 和 `interrupt_tool_use_id`，失败中断不改变状态，也不保存失败 attempt。
- `SubagentStop` 验收通过时写入 `complete`、`blocked` 或 `needs_decision` 及简化 `result_document`；需要补充时增加 `retry_count` 并写入 `retry_required`，达到上限时写入 `protocol_error` 和 `protocol_errors`。
- `SessionEnd` 在没有待恢复或待决策任务时删除整个 Session 状态，没有独立事件归档。

现有证据字段包括 `tool_use_id`、`turn_id`、`created_at`、`updated_at`、`platform_checked_at`、`agent_id`、`canonical_task_path`、`platform_status`、`platform_error`、`retry_count`、`recovery_count`、`interrupt_tool_use_id`、`protocol_errors` 和 `result_document`，但这些字段是互不统一的最终快照，不能组成可靠的因果链。

当前确认的问题：

1. 没有记录转换前状态、转换后状态、触发事件、Actor、工具、结果和因果引用。
2. `updated_at` 只能说明记录最近被改过，不能说明发生了哪次动作，也不能区分实际发生时间和 Hook 观察时间。
3. 多次平台观察、恢复、中断或终态提交会覆盖同一记录，无法可靠重建完整路径。
4. 普通 `send_message` 不保存通信 attempt；`followup_task` 只保存恢复计数和最终状态。
5. `retry_required` 同时表示平台恢复后的重新启动等待和终态文本补充，无法只凭状态判断原因。
6. `_extract_values()` 和 `_response_failed()` 会递归搜索响应中的字段或失败标记，缺少稳定响应适配器、来源路径和证据引用。
7. 普通平台状态可以直接保存未知对象；明确错误虽已截断，但仍没有响应版本、观察来源或可信度字段。
8. 最终 `running` 加 `recovery_count=1` 不能证明父任务实际等待过、恢复调用命中了原 Agent、Agent 已重新开始业务执行或网络已经恢复。
9. 终态 CAS 可以防止检查期间覆盖较新状态，但冲突只通过一次性 `systemMessage` 表达，没有持久化冲突事件。
10. Session 状态被删除或终态记录被裁剪后，诊断无法继续解释历史失败路径。

本轮新增的特征测试构造 `running → platform_error → retry_required → running` 恢复链，确认最终记录只保留 `running`、`recovery_count=1`、最近平台错误和检查时间，没有 `events`、`attempts`、最后转换对象或恢复工具引用。

### 2. 与前后文的交接

#### 上游交接

- SG-F01 提供稳定的任务 ID、治理等级和派发契约引用；事件链消费这些身份，不重新生成任务契约。
- SG-F02 提供 Hook 注册、统一事件路由和原始事件输入；SG-F07 不拥有业务 Handler，只读取它们留下的结构化事件。
- SG-F03 拥有普通通信和恢复业务调用、目标解析与参数协议；未来应由该功能产生 communication/recovery attempt，SG-F07 只展示调用事实和关联结果。
- SG-F05 拥有 StateStore、生命周期转换、Agent 绑定、平台对账、恢复、中断及 Session 生命周期；它负责原子写入转换事实，SG-F07 不改变状态优先级。
- SG-F06 拥有终态提交、机械验收、结果持久化、幂等、冲突和迟到结果处理；它负责产生结果提交、验收或冲突事件，SG-F07 只读取其稳定引用。
- SG-F08 拥有协调计划、批次、父子层级和组级状态；未来只向 SG-F07 提供协调 ID、节点和组级事件引用，不把多 Agent 协调逻辑并入诊断。

#### 下游交接

- 第 5 项根据事件事实计算失败阶段、原因、证据可信度和父任务动作，不能通过最终状态反推不存在的历史。
- 第 6 项决定哪些事件进入机器可读 JSON、父任务完整诊断和主对话摘要。
- 第 7 项限制工具响应、错误文本、任务正文、路径、事件数量和保留时间。
- 第 8 项定义事件版本、未知事件、旧 StateStore 和 N/N-1 读取策略。

#### 跨功能排除

- SG-F07 不决定某个业务动作是否允许，也不根据诊断输出执行恢复、中断、重试或终态验收。
- 不保存 transcript、完整 tool response 或无限增长的审计日志。
- 不因为缺少投递确认就生成已证明的 delivery failure，也不因为 `SubagentStart` 出现就证明业务执行已经恢复。
- SG-F04 的安装、发布、缓存和 Hook trust 事件仍属于安装发布诊断，不进入运行任务事件链的主要归属。

### 3. 改进建议

建议建立有界、结构化、可因果串联的治理事件/attempt 链，而不是保存完整日志。每个可观察事件至少应包含：

- `event_id`、`task_id` 和稳定执行引用。
- 适用时的 `attempt_id`。
- `event_type` 和 `source`，区分 Hook、原生工具、平台观察、状态组件和 Agent 结果。
- `observed_at`，必要时单独保存声明的发生时间，但不能把自述时间当作平台事实。
- `from_state`、`to_state`。
- `outcome`：`requested`、`succeeded`、`failed`、`unknown` 或 `conflict`。
- `tool_use_id`、`turn_id`、Agent 或 canonical path 的受限引用。
- `evidence_reference` 和 `caused_by_event_id`。
- 稳定错误码及有界、脱敏错误摘要。

建议区分以下事件或 attempt：

1. dispatch attempt。
2. identity binding event。
3. communication attempt。
4. wait/reconcile observation。
5. recovery attempt。
6. interrupt attempt。
7. terminal submission/acceptance/conflict event。
8. state degradation/recovery event。

其他建议：

- 保留原始生命周期状态，但把动作结果、诊断原因、证据可信度和父任务动作拆成独立维度。
- `retry_required` 至少增加稳定 reason，区分平台恢复、终态补充和其他未来重试来源；是否最终拆状态由统一状态方案决定。
- 响应适配器只读取已确认的结构和字段路径，未知响应保留为 `unknown`，不能递归命中任意内部 `status` 就宣称失败。
- 明确证据等级：Hook 直接观察、平台明确返回、状态已持久化、Agent 自述、诊断推导和未知。
- 冲突、迟到和重复事件不能静默覆盖；保留有界冲突摘要和稳定引用。
- 每个任务只保存最近有限数量事件及必要 checkpoint；终态或 Session 清理前按照第 7 项确定保留和裁剪策略。

### 4. 本轮直接实施的改进

本轮不修改运行时状态模型，也不新增事件字段，只增加一条当前行为特征测试：

- `test_recovery_state_keeps_counters_but_no_transition_history` 通过现有 Handler 构造平台错误、成功 follow-up 和再次启动，确认 StateStore 最终只保留当前状态、恢复计数、最近平台错误和检查时间，没有转换或 attempt 历史。

该测试用于证明当前诊断缺口，不代表“没有事件链”是目标行为。未来实现正式事件模型时应同步改写该测试，使其验证新的有界事件协议。

### 5. 必须留待最终统一方案的内容

- 事件和 attempt 的正式字段、枚举、必填关系及 JSON Schema。
- 任务、执行、派发 attempt、通信 attempt、终态 attempt 和协调节点之间的身份引用。
- 哪些上游 Handler 写事件、如何与状态更新保持同一原子提交。
- 生命周期状态、业务结果、平台观察、诊断原因、证据等级和父任务动作的分层。
- `retry_required` 的 reason 或拆分方案。
- 重复、迟到、冲突和乱序事件的优先级、幂等键和保留方式。
- 事件数量、单事件大小、错误摘要、原始证据引用和 Session 清理后的保留期。
- 平台响应适配器、真实 Codex/provider smoke 和 fixture/handler 证据的证明层级。
- N/N-1 对未知事件、未知 outcome 和新字段的兼容读取。
- SG-F08 协调事件与单任务事件的引用方式，避免形成第二套事件系统。

### 6. 不再作为目标的内容

- 不把最终 `status` 和 `updated_at` 当作完整状态转换历史。
- 不用 `recovery_count` 证明恢复调用、Agent 重启或网络恢复已经成功。
- 不把 `SubagentStart` 自动解释为业务执行已经继续。
- 不保存完整 transcript、完整工具响应或无限增长日志。
- 不通过自由错误文本或递归字段命中猜测 provider 根因。
- 不让 SG-F07 反向修改 SG-F05 生命周期状态或 SG-F06 终态优先级。
- 不把单元测试、fixture 或本地 JSON 当作真实平台时序证据。

### 7. 测试与证据

- 现有测试分别覆盖派发映射、歧义身份不猜测、平台错误对账、有界错误摘要、一次平台恢复、恢复上限、中断、终态补充、协议错误、终态 CAS 和 SessionEnd 保留。
- 本轮新增恢复链特征测试，覆盖当前只有最终状态和计数、没有转换历史的事实。
- 第 4 项验证时共享工作区完整回归共 155 项，全部通过；Python 编译、Plugin validator 和 Skill validator 均通过。完整回归包含其他盘点任务的并行修改，不能全部归因于 SG-F07。
- 当前仍缺少事件 Schema、attempt 身份、转换来源、outcome、因果引用、重复/迟到/冲突持久化、容量裁剪和跨版本事件测试。
- 现有测试只能证明本地 Handler 与 StateStore 的状态投影，不能证明真实 Codex/provider 的事件顺序、消息投递、等待执行、网络恢复或业务完成。

### 8. 本项结论

- “状态转换与证据链”必须保留并重点改造，不是可以删除的功能点。
- 当前状态快照足以支持有限生命周期控制，但不足以解释完整失败路径、恢复动作、冲突和证据可信度。
- 目标应是有界、结构化、可因果串联且明确证据等级的治理事件/attempt 链，不是远程遥测或完整日志系统。
- 本轮只增加当前缺口的特征测试和盘点结论；事件 Schema、状态分层、容量、脱敏和跨版本策略必须与 SG-F03、SG-F05、SG-F06、SG-F08 统一确定。

## 七、第 5 项：诊断问题定位与分类模型

### 1. 当前情况

当前 `SKILL.md` 的“诊断失败”章节列出八个术语：`dispatch`、`delivery-suspected`、`execution`、`acceptance`、`orchestration`、`state-degraded`、`transport-opaque` 和 `platform-error`。它们目前是供 AI 和父 Agent 阅读的排障导航，不是运行时枚举、持久化字段或 JSON Schema。

这八个词混合了四种不同语义：

- 阶段：`dispatch`、`execution`、`acceptance`、`orchestration`。
- 不确定性或可见性：`delivery-suspected`、`transport-opaque`。
- 组件健康：`state-degraded`。
- 平台观察：`platform-error`。

因此它们不是互斥主分类。同一任务可能同时具有 opaque 正文、治理状态降级和明确平台错误；把八项直接变成一个 `failure_type` 会丢失事实并制造错误优先级。

| 指导术语 | 当前运行时事实或证据 | 当前判断 |
| --- | --- | --- |
| `dispatch` | PreToolUse 可以因参数或契约非法拒绝；spawn PostToolUse 明确失败时写入任务 `failed` | 保留为阶段，但必须区分契约非法、治理组件异常和原生派发失败 |
| `delivery-suspected` | 没有运行时字段；缺少任务 ID、Agent ID 或 canonical path 不能证明消息投递失败 | 不应作为失败主类，建议改为 `identity_unconfirmed` 或 `delivery_unconfirmed` 观察 |
| `execution` | 运行时只能观察启动、平台状态、停止和 Agent 自述，不能证明业务是否真实执行或发生漂移 | 保留为诊断阶段；证据不足时只能表达 `execution_unverified` |
| `acceptance` | 当前终态补充会进入 `retry_required`，达到上限进入 `protocol_error`，通过时保存 `result_document` | 保留为阶段；结果缺失、Schema 非法、冲突或迟到原因主要归 SG-F06 |
| `orchestration` | Hook 不观察 `wait_agent`；只能看到部分重复派发、错误中断、状态竞争和未来 SG-F08 组级事实 | 保留为阶段，但只能报告明确观察到的问题，不能因无记录就宣称父任务未等待 |
| `state-degraded` | 当前通过根 `health`、`last_warning` 和 Handler 告警表达 | 应属于治理组件健康，不进入任务生命周期状态 |
| `transport-opaque` | 当前已有 `message_visibility=opaque`；合法 `task_name` 下派发仍能正常建立 `pending` 任务 | 应属于可见性或能力限制，不是失败状态 |
| `platform-error` | 只有已映射任务在 `list_agents` 明确返回 `agent_status.errored` 时才写入 `platform_error` | 保留为明确平台观察，但不能据此确定 provider 根因、消息投递或业务结果 |

当前任务状态集合包括 `pending`、`dispatched`、`running`、`retry_required`、`complete`、`blocked`、`needs_decision`、`protocol_error`、`failed`、`interrupted` 和 `platform_error`。这些状态分别混合了执行阶段、业务结果、协议结果和父任务待处理状态，不能直接当作失败原因：

- `failed` 当前主要来自 spawn PostToolUse 明确失败，不表示子 Agent 的业务执行失败。
- `protocol_error` 表示终态协议处理问题，不证明业务结果失败。
- `needs_decision` 既可能来自 Agent 正式结果，也可能来自平台恢复上限，需要来源字段。
- `blocked` 是业务或外部条件阻塞结果，不等于治理组件错误。
- `interrupted` 表示成功中断后的生命周期终止，不一定是异常失败。
- `platform_error` 只证明平台在某次观察中报告 Agent `errored`，不证明错误根因。

还存在两个明确的跨版本漂移：

1. 当前开发仓库 Skill 和运行时统一规定不解析具体 provider 错误文本，所有明确 `errored` 使用相同的 `platform_error` 和恢复规则；但已打开任务或旧全局规则快照仍可能要求识别 `provider_protocol_incompatible` 并立即进入决策。这不是当前运行时已经实现的分类。
2. `runtime-boundaries.md` 仍声称 Stop 和 SessionStart 忽略 `platform_error`，而当前 `STOP_BLOCKING_STATUSES`、`SESSION_RESTORABLE_STATUSES` 已包含它；该共享参考已经滞后。

### 2. 与前后文的交接

#### 上游交接

- SG-F01 拥有治理等级、任务契约、派发参数和任务身份；它提供契约非法、身份缺失和派发请求事实，不提供完整诊断结论。
- SG-F02 拥有 Hook/CLI 顶层异常边界；明确契约拒绝和插件内部未知异常必须使用不同问题码，不能都写成 dispatch failure。
- SG-F03 拥有普通通信、恢复调用和目标关联；未来 communication/recovery attempt 为通信或恢复问题提供证据。
- SG-F05 拥有生命周期状态、组件健康、Agent 映射、平台观察、恢复上限和中断事实。
- SG-F06 拥有正式结果、机械验收、协议错误、冲突、迟到结果及 `blocked`/`needs_decision` 的业务来源。
- SG-F08 拥有协调计划、依赖、并发容量、重复派发和组级闭环事实；SG-F07 只消费其可观察协调问题。

#### 下游交接

- 第 6 项把诊断问题、证据和父任务动作组织成机器可读协议、父任务详情和用户摘要。
- 第 7 项决定错误文本、任务正文、平台响应和证据引用的脱敏及容量边界。
- 第 8 项定义问题码、未知分类、证据类型和旧版本诊断的兼容策略。

#### 跨功能排除

- SG-F07 不根据诊断分类改变任务状态、自动恢复、中断、重试或验收结果。
- 安装健康、缓存、发布就绪和 Hook trust 问题继续属于 SG-F04，不能使用同一个 `state-degraded` 混合表达。
- 不把缺少证据转换成已经确认的派发失败、投递失败、执行失败或父任务未等待。
- 不通过自由 provider 错误文本猜测根因或修改恢复策略。

### 3. 改进建议

建议把扁平的八类“失败类型”改成可叠加的诊断问题模型。至少包含：

- `issue_id`：本次诊断问题的稳定身份。
- `phase`：`dispatch`、`delivery`、`execution`、`acceptance`、`orchestration`、`state` 或 `platform`。
- `issue_code`：稳定、细粒度的问题码。
- `certainty`：`confirmed`、`observed`、`self_reported`、`inferred` 或 `unknown`。
- `evidence_source`：Hook、StateStore、平台观察、Agent 结果、父任务动作或文件/测试证据。
- `evidence_references`：关联第 4 项事件、attempt、结果和健康问题。
- `task_status`：保留上游原始生命周期状态，不由诊断重写。
- `component_health`：独立表达 StateStore、结果存储或诊断读取器健康。
- `parent_action`：等待、对账、恢复、验收、请求决策、归档或无。
- 有界、脱敏摘要和影响范围。

候选问题码可以包括：

- `dispatch_contract_invalid`
- `native_spawn_failed`
- `identity_unconfirmed`
- `delivery_unconfirmed`
- `execution_unverified`
- `result_missing`
- `result_schema_invalid`
- `result_conflict`
- `concurrent_state_conflict`
- `state_corrupt`
- `state_unavailable`
- `opaque_payload`
- `platform_errored`
- `recovery_limit_reached`

同一任务允许存在多个诊断问题。面向用户摘要可以根据严重程度、父任务动作和证据强度选择一个主要问题，但底层协议不能因为展示需要丢弃其他问题。

证据边界建议：

- `list_agents` 明确 `errored` 可以确认一次平台错误观察，但不能确认 provider 根因。
- opaque payload 可以确认 Hook 看不到正文，但不能说明子 Agent 没有收到正文。
- 缺少 Agent/任务映射只能确认身份未建立，不能确认消息投递失败。
- Agent 自述可以作为结果或执行证据来源，但业务完成仍需父任务结合工具、测试、文件或其他外部证据验收。
- 没有 `wait_agent` Hook 记录不能证明父任务没有等待；只有未来明确的父任务动作事件才能确认编排行为。

### 4. 本轮直接实施的改进

本轮不新增诊断枚举、不修改任务状态，也不修改 Skill 或共享运行边界，只扩展现有测试：

- `test_opaque_spawn_uses_task_name_mode_channel` 现在额外断言 opaque 正文下合法派发仍建立 `pending` 任务，保护“`transport-opaque` 是可见性限制，不是任务失败”的现行边界。

现有测试已经分别证明：

- `delivery-suspected` 被公开说明为指导术语，不是运行时状态或 Schema 字段。
- 普通响应文本包含 `error` 单词不会被误判，只有明确失败形状才会把派发写为 `failed`。
- 只有 `list_agents` 的明确 `errored` 会生成 `platform_error`。
- 终态证据不足和纠错上限会生成 `retry_required`/`protocol_error`，但不能据此判断业务执行失败。

### 5. 必须留待最终统一方案的内容

- 正式诊断 Schema、问题码枚举、必填关系及多问题并存方式。
- `delivery-suspected` 是否删除或改成 `identity_unconfirmed`/`delivery_unconfirmed`。
- `provider_protocol_incompatible` 是否保留为稳定问题码，以及可以使用什么确定性证据识别。
- `failed`、`protocol_error`、`platform_error`、`blocked`、`needs_decision` 与正式 TaskResult 的关系。
- `needs_decision` 的来源、问题引用和解除条件。
- execution 阶段可接受的 Agent 自述、工具、测试、文件和平台证据等级。
- orchestration 阶段如何消费 SG-F08 协调事实，以及如何避免通过缺失事件推断父任务错误。
- Skill、runtime-boundaries、README、全局规则快照、状态枚举和未来诊断 Schema 的统一术语来源。
- 机器码使用下划线还是兼容现有文档连字符，以及跨版本别名策略。

### 6. 不再作为目标的内容

- 不把八个指导术语直接做成互斥 `failure_type`。
- 不把 `delivery-suspected`、`transport-opaque` 或 `state-degraded` 新增为任务生命周期状态。
- 不把 `failed` 一律解释为业务执行失败。
- 不把 `protocol_error` 解释为子 Agent 工作失败。
- 不把 `needs_decision` 解释为单一原因。
- 不因缺少 Agent ID、任务 ID、等待事件或结果证据就宣称平台投递失败、父任务未等待或业务未执行。
- 不通过 provider 自由错误文本改变治理语义。

### 7. 测试与证据

- 现有测试覆盖派发契约拒绝、opaque 正文、明确派发失败、普通 error 单词不误判、平台 errored 对账、组件降级、终态补充、协议错误、恢复上限和 `needs_decision`。
- 本轮扩展 opaque 派发测试，确认可见性限制不会自动改变为失败状态。
- 第 5 项验证时共享工作区完整回归共 155 项，全部通过；Python 编译、Plugin validator 和 Skill validator 均通过。完整回归包含其他盘点任务的并行修改，不能全部归因于 SG-F07。
- 当前仍缺少正式诊断问题对象、问题码、证据等级、多问题并存、父任务动作和跨版本别名测试。
- 单元测试、fixture 和本地状态只能证明运行时对输入的投影，不能证明真实消息投递、业务执行、父任务等待或 provider 根因。

### 8. 本项结论

- 该功能点最终建议命名为“诊断问题定位与分类模型”，必须保留并重点改造。
- 八个现有术语适合作为排障导航的输入，但不适合作为同级、互斥的运行时失败枚举。
- 目标模型应拆分阶段、稳定问题码、证据来源、可信度、原始状态、组件健康和父任务动作，并允许多个问题同时存在。
- 本轮只保护 opaque 可见性边界并写入盘点结论；正式分类协议必须与 SG-F01、SG-F02、SG-F03、SG-F05、SG-F06、SG-F08 和后续输出/版本方案统一确定。

## 八、第 6 项：分层诊断输出与机器可读报告协议

### 1. 当前情况

当前系统已经存在多种输出通道，但没有统一、版本化的诊断报告协议。输出是否为 JSON 也不能决定其语义层级。

| 当前输出 | 当前内容 | 当前边界或问题 |
| --- | --- | --- |
| 全局 `--diagnose` | `data_root` 及每个 Session 的 `session_id`、`active`、`tasks`、`health`、`updated_at` | 无协议版本、生成时间、检查完整度、问题对象、读取错误、遗漏数或分页 |
| `--diagnose --session` | `data_root` 和完整原始 StateStore | 直接暴露状态记录；没有默认摘要、诊断派生字段、脱敏或显式 raw 边界 |
| PreToolUse Hook 输出 | `permissionDecision`、`permissionDecisionReason`、`updatedInput`、`additionalContext` | 是原生工具控制和 Agent 上下文，不是诊断报告 |
| PostToolUse/SessionEnd 等输出 | 一次性的 `systemMessage` | 文案分散、无稳定问题码；不能证明父任务一定观察到该消息 |
| Stop/SubagentStop 输出 | `decision`、`reason` 或 `continue` | 表示当前 Hook 是否阻止停止，不表示业务完成、治理健康或诊断问题已经解决 |
| SessionStart `additionalContext` | 最多 8 条、约 1800 字符的恢复摘要及未展开计数 | 是父 Agent 恢复提示，不是完整 Session 诊断，也没有机器协议 |
| SubagentStart `additionalContext` | 任务 ID、状态、治理等级、固定执行边界和告警 | 是子 Agent 启动上下文，不能代替父任务诊断 |
| `result_document` | 子 Agent 的终态结果片段 | 属于 SG-F06 的正式结果，不是诊断报告 |
| StateStore 和隔离文件 | 最完整的本地原始证据 | 当前单 Session 诊断会直接展开；其访问和展示边界尚未分层 |

当前确认的问题：

1. 全局和单 Session 诊断使用两种不同顶层形状，没有 `protocol`、Schema 或兼容版本。
2. 没有 `generated_at`、选择范围、检查完整度、报告总体状态或使用的状态版本。
3. 没有承载第 5 项问题码、证据可信度、父任务动作和第 4 项事件引用的稳定 `issues` 对象。
4. 全局扫描损坏或不可读文件时静默跳过，报告既没有 `partial`，也没有读取错误和遗漏计数。
5. `health` 只来自单个 StateStore 根节点，不能替代本次诊断执行是否完整或数据根整体是否健康。
6. `continue`、`decision`、`permissionDecision` 是 Codex Hook 控制字段，不能重用为诊断状态。
7. `systemMessage`、`additionalContext`、Session 摘要和诊断 JSON 分别由不同代码路径直接拼接，没有共享问题对象和确定性渲染层。
8. 主对话用户摘要目前依赖父 Agent 根据上下文自行生成，没有明确规定应消费哪个权威报告或如何标记证据不足。
9. 当前诊断成功通常返回退出码 0，部分扫描失败也返回 0；异常又可能直接 traceback，没有稳定自动化语义。
10. 当前没有分页、稳定游标、报告容量、遗漏原因或证据按需展开协议。

本轮新增的单 Session 定向测试确认：在显式数据根中创建治理任务后，`--diagnose --session session-1` 当前会返回合法 JSON，顶层包含解析后的 `data_root`，`session` 内包含正确 Session ID 和该任务记录。该测试只确认选择器和当前 JSON 可读性，不把完整 raw 状态作为目标协议。

### 2. 与前后文的交接

#### 上游交接

- SG-F02 拥有统一 CLI、Hook stdout 形状、平台允许的控制字段和 `additionalContext` 传输限制；SG-F07 不能自行向 Hook 输出添加未确认支持的自定义字段。
- SG-F05 提供状态、健康、Session、任务、Agent、平台观察和恢复事实；诊断报告只读消费，不复制第二套生命周期状态。
- SG-F06 提供正式 TaskResult、完整结果引用、终态异常和父任务闭环事实；诊断引用结果，不把结果正文复制成第二份诊断结果。
- SG-F08 提供协调组、批次、节点、依赖和组级结果事实；组级诊断通过引用进入统一报告，不建立独立报告协议。
- 第 3～5 项已经提供快照、事件/attempt 目标模型和诊断问题模型，均应成为机器报告的输入。

#### 下游交接

- 第 7 项决定每一输出层允许包含的任务正文、Agent 路径、错误文本、结果内容、原始响应和证据引用，并定义容量与保留期。
- 第 8 项决定诊断协议版本、未知字段、未知问题码、旧 StateStore 和 N/N-1 报告兼容。

#### 跨功能排除

- 机器诊断报告不是 TaskContract、TaskResult 或 StateStore 的替代品，只引用其稳定身份和状态。
- SG-F07 不创建第二套终态回传通道，也不宣称 Hook `systemMessage` 已送达父任务或用户。
- 主对话业务摘要仍由父 Agent 根据正式结果和诊断事实生成；脚本只做结构校验、字段选择和确定性渲染，不创作业务判断。
- 安装和发布诊断继续由 SG-F04 输出自己的报告；最终可以统一公共信封原则，但不能合并含义不同的检查对象。

### 3. 改进建议

建议建立四个持久输出层和一个即时 Hook 告警通道。

#### 3.1 本地原始证据层

- 保存 StateStore、正式结果、隔离文件和受限错误证据。
- 普通诊断不直接展开完整内容，只返回稳定本地证据引用。
- 通过显式、受限的 `--raw` 或本地文件检查访问。
- 不直接进入主对话、普通 `systemMessage` 或 `additionalContext`。

#### 3.2 权威机器可读诊断报告

建议建立 `subagent-diagnostic-v1`，至少包含：

- `protocol`
- `generated_at`
- `scope`
- `inspection_status`
- `overall_status`
- `component_health`
- `summary`
- `issues`
- `sessions`/`tasks`
- `omitted`
- `read_errors`
- `evidence_references`

`issues[]` 使用第 5 项的诊断问题对象；任务和 Session 快照使用第 3 项模型；最后事件和 attempt 引用第 4 项证据链。报告应成为其他摘要的唯一结构化输入。

#### 3.3 父任务操作视图

从权威报告确定性生成，至少包括：

- Session、任务和执行身份。
- 原始状态、组件健康和最后可观察事件。
- 诊断问题、证据来源和可信度。
- 已执行的重试/恢复次数及未确认边界。
- `parent_action` 和动作依据。
- 未展开数量、读取错误和原始证据引用。

该层应足以让父 Agent 继续等待、对账、恢复、验收或请求决策，但不倾倒完整 StateStore。

#### 3.4 主对话用户摘要

只保留：

- 是否存在需要关注的问题。
- 最重要的任务、影响和已确认事实。
- 用户需要选择或执行的动作。
- 关键验证和仍未确认的边界。

不得默认展示协议版本、内部哈希、完整状态、长错误文本、完整路径或所有事件。父 Agent 可以组织业务语言，但事实和动作必须来源于权威诊断报告及正式 TaskResult。

#### 3.5 Hook 即时告警通道

- SG-F07 拥有共享 `DiagnosticIssue` 信封、错误码和渲染规则。
- SG-F02 继续拥有 Hook 返回字段和平台传输边界。
- SG-F05、SG-F06 等上游组件在发现问题时产生结构化 issue，并与状态操作一起保存或返回。
- 当前 Hook 只把 issue 渲染成简短 `systemMessage`、`additionalContext` 或拒绝原因。
- 未经真实平台兼容证据，不向 Hook 返回对象增加任意 `diagnostics` 等自定义字段。

#### 3.6 退出码

建议把退出码作为粗粒度自动化结果，详细信息始终来自 JSON：

- `0`：完整检查且没有错误级问题。
- `1`：完整生成报告，但发现 degraded 或 action-required 问题。
- `2`：参数或命令用法错误。
- `3`：生成部分报告，存在不可读、损坏或不支持版本的数据。
- `4`：无法生成有效诊断报告。

单个任务处于正常 `running`、`blocked` 或其他业务状态是否影响 `overall_status`，必须由正式严重程度和父任务动作规则决定，不能直接把任意非 complete 状态映射成非零退出码。

### 4. 本轮直接实施的改进

本轮不修改 `_diagnose()` 输出、不创建 Schema，也不增加 Hook 自定义字段，只新增一条单 Session 定向测试：

- `test_diagnose_session_returns_selected_session_json` 创建一个有治理任务的 Session，调用显式数据根和 `--session`，确认返回合法 JSON、选择正确 Session、数据根正确且任务存在。

该测试用于补足当前单 Session 入口证据；未来切换正式诊断信封时可以更新顶层断言，但必须继续保护 Session 选择和任务引用不丢失。

### 5. 必须留待最终统一方案的内容

- `subagent-diagnostic-v1` 的正式 JSON Schema、字段枚举和必填关系。
- `DiagnosticIssue` 与 StateStore、事件/attempt、TaskResult 和协调节点的引用关系。
- 默认脱敏摘要、显式 raw 模式和本地证据访问控制。
- `inspection_status`、`overall_status`、问题严重程度和退出码的精确定义。
- 数据根不存在、Session 不存在、损坏状态、部分读取、未知版本和完整失败的错误对象。
- 稳定排序、数量上限、分页、游标、遗漏数和按需展开。
- Hook issue 如何映射到 `systemMessage`、`additionalContext`、`decision` 和 `permissionDecisionReason`。
- 父任务操作视图及主对话摘要的确定性字段和生成责任。
- SG-F08 组级报告与单任务报告的嵌套或引用方式。
- 是否建立独立诊断 Schema，以及它与 StateStore、TaskContract、TaskResult N/N-1 的兼容关系。

### 6. 不再作为目标的内容

- 不把“能够输出 JSON”直接等同于已经存在诊断协议。
- 不把完整 StateStore 作为普通单 Session 诊断的长期默认输出。
- 不把 Hook 控制字段当作诊断状态或业务结果。
- 不把 `systemMessage`、`additionalContext` 或 SubagentStop 放行描述成父任务或用户已经收到信息。
- 不创建第二套结果、消息或 Agent 编排通道。
- 不让脚本自由总结业务结论或补造用户摘要。
- 不向未确认支持的 Hook 输出中增加任意自定义诊断字段。

### 7. 测试与证据

- 现有测试覆盖 Hook CLI 合法 JSON、显式数据根、诊断参数边界、全局 Session 汇总、SessionStart 摘要容量和遗漏数、SubagentStart 固定上下文、Stop/SessionEnd 告警及终态回传责任边界。
- 本轮新增单 Session 诊断测试，覆盖显式 Session 选择和当前 JSON 可读性。
- 第 6 项验证时共享工作区完整回归共 156 项，全部通过；Python 编译、Plugin validator 和 Skill validator 均通过。完整回归包含其他盘点任务的并行修改，不能全部归因于 SG-F07。
- 当前仍缺少正式诊断 Schema、问题对象、部分失败、退出码、分页、父任务视图、用户摘要和 raw 模式测试。
- 直接调用 Handler、解析 stdout 或读取本地 JSON 只能证明本地输出形状，不能证明真实 Codex 会展示、传递或保留相同内容。

### 8. 本项结论

- “分层诊断输出与机器可读报告协议”必须保留并重点改造。
- 当前已经有多个输出通道，但它们分别承担原生控制、Agent 上下文、恢复提示、终态结果和原始证据职责，不能互相替代。
- 目标应建立唯一权威的机器诊断报告；父任务操作视图、主对话摘要和 Hook 即时告警从同一问题与证据模型派生。
- 本轮只补充单 Session 输出证据并记录分层方案；正式 Schema、退出码、raw、脱敏、容量和版本兼容必须在后续两项及最终统一方案中确定。

## 九、第 7 项：容量、保留与实际外显边界

### 1. 当前情况

本项原名“敏感信息、容量与保留边界”。用户复核后确认，当前仓库没有远程遥测、Issue、CI、日志上传或其他自动扩散诊断内容的实现证据，不应基于这些假想场景设计全面脱敏。本项因此改为盘点代码已经存在的输入、状态、摘要、诊断输出和本地文件边界。

当前已经存在的容量限制：

- Hook stdin 最多接受 `MAX_HOOK_INPUT_BYTES = 2 MiB`；`main()` 读取后按 UTF-8 字节数拒绝超限输入。
- 单个 Session StateStore 文件读写上限为 `MAX_STATE_BYTES = 4 MiB`。
- `_prune_state()` 最多保留 200 条终态记录，并删除超过 30 天的终态记录；裁剪只在状态写入时执行。
- `_bounded()` 对任务契约字段、平台错误、结果片段和部分上下文使用 600 字符上限；该限制按 Python 字符数计算，不是 UTF-8 字节预算。
- SessionStart 恢复摘要最多选择 8 条记录，总长度最多 1800 字符，单个展示字段最多 96 字符，并报告未展开数量。
- Stop 和 SessionEnd 默认最多展开 6 条任务，其余只显示遗漏数量。

当前已经存在的本地存储与保留行为：

- 状态目录由 SG-F05 保证为当前用户拥有的普通 `0700` 目录；状态文件、临时文件和锁文件使用 `0600`。
- JSON 损坏或非 UTF-8 文件会被移动为 `.corrupt-*` 隔离副本，当前没有隔离文件清理策略。
- Session JSON 删除后 `.lock` 文件仍保留；直接删除锁文件可能造成不同进程锁定不同 inode，因此不能把“存在旧锁文件”直接当作可安全清理的垃圾。
- SessionEnd 在没有需要保留的运行、恢复或决策任务时可以删除整个 Session JSON，因此“终态最多 200 条、30 天”只是仍存活状态文件内的裁剪上限，不是每个 Session 至少保留 30 天的承诺。
- 活跃任务没有数量或寿命上限；长期未终结记录、未知大对象或大量映射可能先触及 4 MiB 状态上限。

当前实际外显通道只有：

- `--diagnose` 把数据根绝对路径和 Session 摘要输出到调用者当前 stdout。
- `--diagnose --session` 把该 Session 的完整 StateStore 和数据根绝对路径输出到当前 stdout。
- Hook 通过 `systemMessage`、`additionalContext`、`reason` 或 `permissionDecisionReason` 输出当前操作需要的告警或说明。
- 本地 StateStore、隔离文件和锁文件仍是当前用户私有文件，不存在运行时自动上传或远程遥测路径。

完整单 Session 状态和绝对路径本身是本地诊断所需信息，不再把它们描述为默认“泄露”或要求统一隐藏。需要控制的是无关字段和无界对象造成的状态或 Hook 输出超限，而不是预设攻击者。

当前确认的真实问题：

1. 全局 `_diagnose()` 直接 `read_text()` 和 `json.loads()`，没有复用 StateStore 的 4 MiB、所有者和根结构检查；手工放入的超大 JSON 可能被完整读取，损坏或不可读文件又被静默跳过。
2. 全局诊断一次扫描并输出所有 Session 摘要，没有简单数量上限或遗漏数；当前没有证据要求分页或稳定游标，但输出规模仍缺少最小边界。
3. 活跃任务不会被终态裁剪规则处理；长期 `pending`、`running` 或 `retry_required` 可以持续占用状态容量。
4. 非错误 `platform_status` 仍可以保存完整未知对象；明确 errored 已被收缩为 600 字符摘要，但普通响应的大对象仍可能导致整个 Session 写入失败。
5. `task_name`、Agent ID、canonical path、`tool_use_id`、`turn_id` 和 `fork_turns` 没有统一持久化大小边界；Hook 输入上限和 StateStore 总上限只能在末端阻止整体超限，不能指出具体字段。
6. 多数契约和结果字段按字符截断，而 StateStore 按 UTF-8 字节限制；当前没有统一容量预算说明，也没有截断标识或原始长度元数据。
7. 多数 Handler 把异常文本直接拼入 Hook 告警；这些异常没有统一字符上限。该问题是 Hook 输出容量和可读性边界，不需要推导成敏感信息泄漏。
8. 隔离文件可能持续累积，但当前没有实际数量、磁盘占用或清理失败证据，不能凭空指定保留天数。

### 2. 与前后文的交接

#### 上游交接

- SG-F02 拥有 Hook stdin/stdout、`additionalContextLimit` 和顶层异常输出通道；SG-F07 只登记诊断与告警的实际输出规模，不改变 Hook 控制字段。
- SG-F01 拥有 TaskContract、`task_name` 和派发字段校验；任务名称及契约字段的最终长度边界应由 SG-F01 确定。
- SG-F03 拥有通信参数和目标引用；通信字段已有 600 字符输入限制，target 和平台身份的最终边界不能由诊断功能单独改变。
- SG-F05 拥有 StateStore 4 MiB 上限、私有权限、终态裁剪、隔离文件、锁文件、活跃状态和平台快照持久化；SG-F07 只诊断这些事实及其影响。
- SG-F06 拥有 `result_document`、结果截断、完整结果存储和保留策略；SG-F07 不扩大或删除结果正文，只展示结果是否完整及对状态容量的影响。

#### 下游交接

- 第 8 项只确认 StateStore 当前版本、未知或不支持版本能否安全读取，以及不同证据来源能证明什么；不再建立独立诊断报告迁移体系。
- 最终统一方案应把本项与第 8 项合并为“容量、保留和状态版本读取边界”，并清理前六项中已经登记的脱敏、raw、分页、游标和长期事件保留预设计。

#### 跨功能排除

- SG-F04 的稳定缓存、发布备份和 N/N-1 安装保留不属于运行 Session 状态容量。
- SG-F07 不修改 StateStore 文件权限、锁实现、终态裁剪或 SessionEnd 删除条件。
- SG-F07 不创建加密存储、secret scanner、远程日志、遥测上传或独立访问控制系统。
- SG-F07 不为尚未实现的 SG-F08 协调状态预留容量或保留协议。

### 3. 改进建议

1. 保留本地 StateStore 和单 Session 诊断的完整内容及绝对路径；不增加默认全面脱敏或单独 `--raw` 权限模式。
2. 全局诊断在读取前复用普通文件、所有者和 4 MiB 上限检查，并把超限、损坏和不可读文件计入部分失败，而不是静默忽略。
3. 全局摘要只需增加简单的检查总数、成功数、遗漏数和合理输出上限；没有真实规模需求前不建设分页、游标或复杂查询矩阵。
4. 诊断展示状态文件字节数、任务总数、终态数量、未解决数量和容量错误，使父任务能区分“业务状态异常”和“状态无法继续写入”。
5. 上游功能对会被持久化的未知对象和外部标识增加必要的形状或长度校验，目的只是在写入前定位具体超限字段，不是安全过滤。
6. 明确区分字符限制与 UTF-8 字节限制；如果内容被截断，应由字段所有者决定是否保存原始长度或截断标识。
7. 隔离文件只有在确认实际增长、恢复价值和安全删除条件后才设计保留规则；不预设固定天数。锁文件继续遵循 SG-F05 的并发安全结论，不做普通垃圾文件清理。
8. Hook 异常告警采用满足定位需要的有界摘要；原始异常若没有独立本地记录，也不因此新建日志系统。

### 4. 本轮直接实施的改进

本轮只修改 SG-F07 文档：

- 将第 7 项从“敏感信息、容量与保留边界”改名为“容量、保留与实际外显边界”。
- 明确本地完整状态和绝对路径是诊断信息，不默认脱敏或隐藏。
- 取消原拟增加的 StateStore `0700`/`0600` 权限测试；该行为已经归 SG-F05，SG-F07 不重复固化。
- 不修改 `_diagnose()`、StateStore、Hook 告警、Schema、Skill、README 或其他盘点文档，也不新增测试。

### 5. 必须留待最终统一方案的内容

- 全局诊断对超大、损坏、不可读和所有者异常文件的部分失败 JSON 及最小非零退出语义。
- 活跃任务数量、寿命、接近 4 MiB 时的处理和不误删可恢复任务的规则。
- 非错误 `platform_status` 的结构与大小限制。
- TaskContract、通信目标、Agent ID、canonical path、工具标识和结果引用的字段容量边界。
- SG-F06 完整结果存储替换当前 600 字符片段后的 StateStore 容量预算。
- 字符限制、字节限制、截断标识和原始长度的统一说明。
- 隔离文件实际增长统计、恢复用途和安全清理条件；锁文件是否存在任何安全回收时机继续归 SG-F05。
- 前六项中脱敏、raw、分页、游标、事件保留和多层持久输出内容的最终统一删除或改写。

### 6. 不再作为目标的内容

- 不以 Issue、CI、日志转发、provider 或未知第三方读取等假想场景作为本功能设计前提。
- 不对本地 StateStore、完整单 Session 诊断或绝对路径执行全面脱敏。
- 不创建 secret scanner、本地加密、远程遥测、访问令牌或新的权限系统。
- 不预先指定隔离文件清理天数，也不把 `.lock` 文件当作可以直接删除的垃圾。
- 不因可能存在大量 Session 就提前建设分页、稳定游标或完整查询语言。
- 不在 SG-F07 重复测试或修改 SG-F05 已拥有的 `0700`/`0600` 权限边界。

### 7. 测试与证据

- 代码已经定义 4 MiB StateStore 读写上限，但现有测试没有直接覆盖该边界；现有测试覆盖终态最多 200 条的裁剪、损坏和非 UTF-8 隔离、平台错误摘要 600 字符上限、SessionStart 1800 字符/8 条摘要以及 Stop 和 SessionStart 的遗漏计数。
- SG-F05 已确认目录、状态文件、临时文件和锁文件的权限与所有者检查，本项不重复增加权限测试。
- 现有测试没有覆盖 StateStore 4 MiB 读写边界、全局诊断读取超大文件、全局输出数量边界、非错误 `platform_status` 超大对象、活跃任务撑满状态或隔离文件长期累积。
- 这些本地单元测试只能证明容量和裁剪代码行为，不能证明真实 Codex Hook 的最终展示上限；本项也不再把缺少平台展示证据推导为敏感信息风险。
- 第 7 项只修改盘点文档，因此不需要重新运行运行时单元测试、Python 编译或 validator；仅执行文档差异和尾随空白检查。

### 8. 本项结论

- 该功能点最终名称为“容量、保留与实际外显边界”；必须保留事实盘点，但不再作为独立安全功能。
- 当前最重要的问题是全局诊断绕过 4 MiB 和结构检查、活跃任务与未知平台对象可能耗尽状态容量，以及隔离/锁文件缺少明确生命周期；这些问题分别需要 SG-F07 与 SG-F05 等上游功能共同处理。
- 本地完整状态、绝对路径和用户私有文件是合理诊断依据，不进行全面脱敏；Hook 告警只需要满足用途并保持有界。
- 本轮只完成文档重命名、事实边界和统一方案输入；没有新增代码或测试。最终收口时本项与第 8 项合并为“容量、保留和状态版本读取边界”。

## 十、第 8 项：状态版本读取与证据来源边界

### 1. 当前情况

本项原名“版本兼容与证据可信边界”。整体去臆想审查后，不再为尚不存在的独立诊断协议设计 N/N-1 别名、问题码迁移或复杂可信度体系，只盘点 StateStore 当前怎样读取版本，以及现有证据分别能证明什么。

#### StateStore 版本读取

- 运行时声明 `STATE_VERSION = 2`，新状态根写入 `version: 2`。
- 默认数据目录仍名为 `state-v1`；目录名和 JSON 内版本可能表示不同层次，但当前文档和代码没有明确解释。
- `_read_path()` 完成根节点和 Session ID 检查后直接执行 `value["version"] = STATE_VERSION`，不会先验证文件原始版本。
- 因此，缺少版本、旧版本或未来未知版本只要基本 JSON 形状可读，都会在内存中被改成版本 2。
- `StateStore.read()` 不立即回写该值，但后续任何 `update()` 都可能把状态按版本 2 保存；当前没有迁移步骤、迁移记录、旧版本拒绝或隔离策略。
- 单 Session `--diagnose` 通过 `StateStore.read()` 获取状态，因此会输出被覆盖后的版本 2，无法报告文件原始版本。
- 全局 `--diagnose` 直接 `json.loads()`，但摘要不包含 `version`，同样不能说明各文件实际版本。
- 读取器会保留多数未知根字段和任务字段，但“字段没有被删除”不表示 Handler 理解其语义、类型或状态优先级。
- `task-contract-v1.schema.json` 和 `task-result-v1.schema.json` 的 `additionalProperties: true` 允许扩展字段，但它们不是 StateStore Schema，也不是运行时迁移器。

当前没有覆盖以下情况的定向测试：

- 文件版本等于当前版本。
- 文件缺少版本。
- 文件为历史旧版本。
- 文件为未来未知版本。
- 旧运行缓存读取新状态或新运行缓存读取旧状态。
- 只读诊断保留并展示文件原始版本。

#### 证据来源及其可证明边界

SG-F07 不再建立 `confirmed`、`observed`、`self_reported`、`inferred` 等多级可信度枚举，只保留以下五类简单来源及事实边界：

1. **StateStore 持久化事实**：证明某个运行时曾把字段写入本地治理状态；不能证明 Codex 平台此刻仍处于该状态，也不能证明父任务已经看见。
2. **Hook 观察事实**：证明本地 Handler 收到相应 payload 并生成了返回对象；直接调用 `handle()` 的测试不能证明真实 Codex 会以相同顺序触发 Hook、展示输出或完成消息投递。
3. **原生平台观察**：`list_agents` 明确返回 `errored` 时，可以证明该次平台响应报告 Agent 错误；不能据此确定 provider 根因、消息是否投递、网络是否已经恢复或业务结果。
4. **Agent 自述结果**：`last_assistant_message` 或 `result_document` 可以证明插件保存了 Agent 自述内容及机械验收结果；不能替代父 Agent 对文件、测试、命令和业务完成情况的验收。
5. **诊断派生摘要**：`active`、stale、身份未确认和下一步提示等由本地规则计算；它们应明确为派生值，不能伪装成平台原始状态。

其他已经确认的边界：

- `SubagentStart` 只能证明启动事件被观察，不能证明业务执行已经继续或恢复完成。
- follow-up 回调未明确失败并写入 `retry_required`，不能证明同一 Agent 已重新启动；仍需后续启动或平台观察。
- `SubagentStop` 放行、保存 `result_document` 或返回 `systemMessage`，不能证明父任务已收到结果、完成业务验收或向用户闭环。
- 没有 `wait_agent` Hook 记录，不能通过本地状态证明父 Agent 是否执行过等待。
- 单元测试、fixture 和本地 JSON 只能证明本地代码对测试输入的处理，不能证明真实 provider 时序或平台投递。

### 2. 与前后文的交接

#### 上游交接

- SG-F05 拥有 StateStore 版本、目录命名、记录形状、迁移、拒绝、隔离和运行时读写语义；SG-F07 只诊断文件版本、当前读取器版本和读取结果。
- SG-F04 只管理 N/N-1 运行代码缓存，并消费“兼容、需要迁移或不可回退”的状态兼容结论作为发布门禁；缓存存在不能证明共享状态兼容。
- SG-F01 和 SG-F06 分别拥有 TaskContract、TaskResult 的协议版本和字段语义；SG-F07 不替它们定义协议迁移。
- SG-F02 拥有真实 Hook 注册、事件路由和 Codex 输出边界；SG-F07 不通过 Handler 单元测试宣称平台已经展示或投递。
- SG-F03、SG-F05 和 SG-F06 分别产生通信、生命周期、平台观察和终态事实；诊断只标记来源，不改变原始状态或结果。

#### 下游交接

- 最终统一方案把版本读取并入“诊断入口与只读检查”和“容量、保留和状态版本读取边界”。
- 五类证据来源并入“基于真实证据的问题定位”，不再保留第 8 项独立功能点，也不引入复杂证据图或可信度等级。

#### 跨功能排除

- SG-F07 不执行状态迁移、回写、隔离或版本升级。
- SG-F07 不决定稳定版本是否发布、回滚或删除 N-1 缓存。
- SG-F07 不创建独立诊断 Schema 的 N/N-1 兼容体系。
- SG-F07 不把本地测试、fixture 或状态文件当作真实 Codex/provider smoke 证据。
- 尚未实现的 SG-F08 协调状态不进入当前版本读取或证据来源模型。

### 3. 改进建议

1. StateStore 在覆盖或补充版本前先读取并保留文件原始版本，明确区分 `stored_version` 和当前 `reader_version`。
2. 为当前版本、缺失版本、明确支持的旧版本和未知未来版本建立最小处理矩阵；在没有迁移策略前不能静默改写成当前版本。
3. 全局和单 Session 诊断都展示文件原始版本、读取器版本和读取结果，例如支持、未知、不支持或读取失败。
4. 未知字段可以在只读诊断中保留原值，但运行 Handler 是否允许继续操作应由 SG-F05 的版本和形状规则决定。
5. N/N-1 兼容必须通过新旧运行代码对共享状态的双向读取及代表性生命周期测试证明，结果交给 SG-F04 发布门禁；不能根据缓存目录、Schema 名称或版本常量推断。
6. 诊断结论只在必要位置增加简单来源标记，如 StateStore、Hook、平台响应、Agent 自述或派生摘要；不增加五级可信度和证据引用图。
7. 公开说明必须与当前代码同步；`runtime-boundaries.md` 等共享文档中已经滞后的 `platform_error`、Stop 和 SessionStart 描述留待最终统一修改。

### 4. 本轮直接实施的改进

本轮只修改 SG-F07 文档：

- 将第 8 项改名为“状态版本读取与证据来源边界”。
- 记录 StateStore 静默覆盖文件版本、单 Session 诊断丢失原始版本和全局摘要不展示版本的事实。
- 将证据边界收缩为五类简单来源，不建立复杂可信度协议。
- 明确本项最终拆分并入诊断读取、问题定位和容量版本边界，不再保留独立功能点。
- 不修改 StateStore、`_diagnose()`、Schema、Skill、README、runtime-boundaries 或其他盘点文档，也不新增测试。

### 5. 必须留待最终统一方案的内容

- 缺失版本、历史版本、当前版本和未知未来版本的读取、迁移、隔离或拒绝矩阵。
- `state-v1` 目录名与 `STATE_VERSION = 2` 的层次定义及后续命名策略。
- 迁移成功、迁移失败、只读兼容和不可回退的状态表达。
- N/N-1 新旧运行缓存对共享状态的双向兼容测试和 SG-F04 发布门禁。
- TaskContract、TaskResult 与 StateStore 版本升级的兼容顺序。
- 全局与单 Session 诊断的原始版本、读取器版本和版本错误输出。
- Skill、README、runtime-boundaries、主盘点和各独立盘点文档中的状态及能力漂移。
- 真实 Codex Hook、Agent 生命周期和 provider 观察的分层 smoke；不能由 fixture 替代。

### 6. 不再作为目标的内容

- 不为尚不存在的独立诊断 Schema 设计 N/N-1、问题码别名或迁移协议。
- 不把版本常量、目录名、缓存存在或未知字段被保留描述成已经兼容。
- 不让 StateStore 静默覆盖版本成为目标行为。
- 不建立五级可信度、因果证据图或多层证据引用协议。
- 不用本地 Handler 测试证明真实 Hook 展示、消息投递、网络恢复或业务完成。
- 不把 `list_agents` 的一次平台错误观察解释为确定的 provider 根因或永久状态。

### 7. 测试与证据

- 当前测试覆盖 TaskContract/TaskResult 协议常量和 Schema 文本一致性，但没有直接断言新 StateStore 的版本字段，也没有覆盖任何 StateStore 版本兼容行为。
- 现有生命周期 fixture、Handler 单元测试和本地状态检查可以证明当前代码投影，不是 N/N-1 或真实平台兼容证明。
- 后续若修改版本读取，必须先增加当前、缺失、旧版、未来未知版本和只读诊断原始版本测试，再增加新旧运行缓存双向读取的发布门禁测试。
- 第 8 项只修改盘点文档，因此不需要重新运行运行时单元测试、Python 编译或 validator；仅执行文档差异和尾随空白检查。

### 8. 本项结论

- “状态版本读取与证据来源边界”的事实必须保留，但最终不作为独立功能点。
- 当前最严重的问题是 StateStore 把任何可读版本静默改成版本 2，使诊断既看不到文件原始版本，也无法诚实判断旧版或未来版本是否兼容。
- 诊断只需保留 StateStore、Hook、平台响应、Agent 自述和派生摘要五类来源及各自边界，不需要复杂可信度模型。
- 本轮只完成文档盘点，没有修改运行时代码或测试。至此八个候选功能点均已逐项确认，下一步是整体覆盖、去重、冲突和最终修改方案输入收口。

## 十一、整体收口、覆盖审查与修改方案输入

### 1. 最终功能身份与大功能结论

- 最终编号：`SG-F07`。
- 最终名称：**运行诊断、问题定位与可观测性**。
- 一句话职责：**只读检查治理状态及其上游留下的可观察证据，以稳定 JSON 和简短提示说明当前快照、治理健康、问题位置和证据边界。**
- 主要入口：`scripts/subagent_governance.py` 的 `--diagnose`、`--session`、`--data-root`、`_diagnose()` 及 `main()` 诊断分支。
- 次要入口：Hook 返回的 `systemMessage`、`additionalContext`、`reason` 和 `permissionDecisionReason`，以及 SessionStart 恢复摘要；它们是诊断事实的即时展示或消费方，不是第二套诊断存储。
- 主要使用者：父 Agent、本地开发者和排障者；脚本提供事实与必要操作提示，不替父 Agent 编写业务结论。

SG-F07 作为一个大功能保留，不再拆成“诊断 CLI”“失败分类”“告警协议”三个大功能。三者共同读取相同的 StateStore、平台观察和结果引用，并必须共享对“能证明什么、不能证明什么”的边界。实现内部仍应把只读读取、快照派生、问题定位和 JSON 渲染分开，避免 `_diagnose()` 继续同时承担文件扫描、状态解释和输出拼接。

SG-F07 不拥有新的运行事件模型。Hook 运行错误的检测和 fail-open/deny 决策分别归产生问题的 SG-F02、SG-F05、SG-F06 代码路径；SG-F07 只要求这些已有事实能够以稳定问题码或有界提示被读取和展示。没有必要为此建立远程遥测、长期事件库或统一审计总线。

#### 上游输入

- SG-F01 提供任务 ID、治理等级、契约和派发参数事实；SG-F07 不重新生成或验收 TaskContract。
- SG-F02 提供 CLI/Hooks 接线、原生输出字段和顶层异常边界；SG-F07 只拥有诊断参数分支与运行诊断输出语义。
- SG-F03 提供通信、follow-up 和目标关联事实；当前普通通信 attempt 没有持久记录时，诊断不得补造。
- SG-F05 提供 StateStore、health、任务状态、Agent 映射、平台观察、恢复计数和 Session 生命周期；这是 SG-F07 的主要事实底座。
- SG-F06 提供正式结果方向、当前 `result_document`、协议错误和父任务动作事实；SG-F07 只读诊断结果存在性、引用和完整性。
- SG-F08 当前没有正式协调运行实现，因此不是 SG-F07 当前数据源；以后只在真实协调状态存在后提供组级事实。

#### 下游消费

- 父 Agent 根据诊断事实决定继续等待、目标对账、恢复同一 Agent、验收结果或请求用户决策；SG-F07 不执行这些动作。
- SG-F04 在发布门禁中消费 StateStore/结果的 N/N-1 兼容结论和真实运行 smoke 要求，但安装健康、缓存和发布就绪仍归 SG-F04。
- README、Skill、运行边界和最终主盘点消费 SG-F07 的公开能力及术语结论；它们不能反向把规划目标描述成当前实现。

#### 明确排除

- 不拥有安装、发布、Marketplace、缓存、Hook trust 或 release readiness 诊断。
- 不拥有 StateStore 写入安全、状态转换、等待巡检、恢复、中断、Stop 或 Session 生命周期动作。
- 不拥有 TaskResult 生成、结果存储、SubagentStop 业务验收或用户闭环。
- 不建立 transcript 读取、远程遥测、后台监控器、调度器、消息平台、完整事件审计或协调组运行时。
- 不通过正文缺失、身份缺失、错误关键词或一次平台观察推断消息一定未投递、业务一定未执行或 provider 根因已经确定。
- 不对本地完整 Session 状态和绝对路径做没有实际需求依据的全面脱敏。

### 2. 六个最终功能点

| 最终功能点 | 当前情况 | 最终处理 |
| --- | --- | --- |
| 1. 诊断入口与只读检查 | 已有 `--diagnose`、全局汇总和单 Session JSON；参数分流已修补，但查询仍会创建目录/锁，单 Session 读取还可能隔离损坏文件 | 保留并改造为真正无副作用的统一只读读取；诚实区分不存在、损坏、不可读和不支持版本 |
| 2. 治理健康、降级与部分读取失败 | 根 `health` 只稳定表达损坏隔离后的 degraded；`last_warning` 和 Hook 告警分散，全局诊断静默跳过错误 | 保留；分开组件健康和本次检查完整度，提供最小稳定问题码、读取错误及部分失败语义 |
| 3. Session、任务、Agent 快照及最后状态变化 | 当前全局只有 `tasks`、12 小时 `active` 和根健康，单 Session 则输出完整 StateStore；没有最后变化对象 | 保留；显示原始状态、按状态/父任务动作计数、身份映射、关键时间和最后可观察变化，不建设完整事件历史 |
| 4. 基于真实证据的问题定位 | Skill 八类术语混合阶段、可见性、组件健康和平台观察，不是运行时枚举 | 保留并收缩；用少量稳定问题码和五类证据来源解释事实，允许并存但不建设可信度等级或证据图 |
| 5. 稳定机器可读 JSON 与简短操作提示 | 当前两种诊断 JSON 形状不同，无检查完整度、读取错误或稳定自动化语义；Hook/Session 摘要各自承担即时提示 | 保留；提供一个稳定、简单的 JSON 形状和必要操作提示，不创建四层持久报告、不让脚本生成主对话业务摘要 |
| 6. 容量、保留和状态版本读取边界 | 已有 2 MiB Hook、4 MiB StateStore、200 条/30 天终态裁剪和摘要上限；全局诊断绕过部分检查，状态读取静默覆盖版本 | 保留；统一只读容量检查、原始版本展示和最小兼容矩阵，按真实规模设置简单输出上限，不预建分页或诊断 Schema 迁移体系 |

首轮第 4 项“状态转换与证据链”并入第 3 项，只保留最后可观察变化、现有 retry/recovery 计数和必要问题依据。首轮第 7、8 项合并为最终第 6 项。首轮第 6 项收缩为一个机器 JSON 加已有即时提示，不保留复杂分层管线。

### 3. 仓库文件覆盖

| 文件 | SG-F07 关系 | 覆盖结论 |
| --- | --- | --- |
| `docs/function-inventory/SG-F07-runtime-diagnostics-observability.md` | 主要归属 | SG-F07 唯一盘点事实、证据、冲突和修改方案输入来源。 |
| `scripts/subagent_governance.py` | 主要归属（共享大文件的诊断区段） | `_diagnose()`、`main()` 诊断分支和诊断汇总直接归属；StateStore、生命周期、平台观察、结果处理只作为只读上游区段登记。 |
| `hooks/hooks.json` | SG-F02 主要，SG-F07 次要 | 提供 Hook 告警和 SessionStart 摘要的实际输出通道；没有独立诊断 Hook、后台监控器或 `wait_agent` 接线。 |
| `skills/subagent-governance/SKILL.md` | 分区共享；诊断失败章节为主要语义输入 | 八类术语是父 Agent 排障导航，不是运行时状态或 Schema；最终需收缩并与问题码、证据边界对齐。 |
| `skills/subagent-governance/references/runtime-boundaries.md` | 主要边界输入 | 规定 provider、opaque transport、状态降级、后台等待器和真实平台证据边界；部分 `platform_error` 生命周期说明已经滞后。 |
| `assets/agents-governance.md` | SG-F04 分发主要，SG-F07 次要 | 发布最小或共享规则入口；其中平台错误和诊断措辞最终应与 Skill 同源，但不是运行诊断实现。 |
| `README.md` | 次要公开承诺 | 概述状态机和诊断入口；公开描述必须限定为本地运行诊断，不能暗示 provider 修复或完整平台可观测性。 |
| `AGENTS.md` | 产品与工作边界 | 要求兼容失败并保留诊断信息；不是状态、问题码或诊断 JSON 的运行时协议来源。 |
| `docs/optimization-plan.md` | 目标与历史计划 | 要求展示活跃/终态/降级/协议错误和最后转换；必须与代码区分，不能直接当成已实现事实。 |
| `docs/project-function-inventory.md` | 只读总盘点交界 | 当前正式主表仍以 SG-F01～SG-F03 和早期事实为主；最终合并需纳入本文六项结论并清理旧诊断候选。 |
| `docs/function-inventory/SG-F04-install-release-cache.md` | 只读边界 | 安装健康、部署同步、发布就绪、缓存和真实 Codex 发布验收归 SG-F04；SG-F07 不重复。 |
| `docs/function-inventory/SG-F05-lifecycle-wait-recovery.md` | 主要上游事实 | 提供 StateStore、health、状态、平台观察、会话摘要和版本问题；综合诊断及 `_diagnose()` 仍归 SG-F07。 |
| `docs/function-inventory/SG-F06-terminal-result-acceptance.md` | 主要上游事实 | 提供结果、协议错误、冲突和父任务动作；SG-F07 只展示，不生成、修复或持久化结果。 |
| `docs/function-inventory/SG-F08-multi-agent-coordination.md` | 未来交界 | 当前没有协调运行对象可供诊断；其中对 SG-F07 进度和未来输入的部分描述已经滞后。 |
| `schemas/task-contract-v1.schema.json` | SG-F01 主要，SG-F07 次要引用 | 只提供任务契约版本和字段引用，不是诊断 Schema，也不证明 StateStore 兼容。 |
| `schemas/task-result-v1.schema.json` | SG-F06 主要，SG-F07 次要引用 | 只提供结果协议形状；诊断读取结果引用时消费其版本和完整性，不复制结果正文。 |
| `tests/test_governance.py` | 多功能共享；诊断定向区段主要归属 | 包含 CLI 参数、单 Session JSON、active 汇总、health/degraded、opaque 和恢复链现状证据；多数生命周期测试只作为上游证据。 |
| `tests/test_hook_fixtures.py` | 次要集成证据 | lifecycle、opaque、平台错误和恢复上限 fixture 证明本地 Handler 投影，不证明真实 Codex/provider 行为。 |
| `tests/fixtures/agent-status-error-v1.json` | SG-F05 主要，SG-F07 平台证据样本 | 证明测试输入含明确 `errored`；不能证明真实 provider 根因或实际断流恢复。 |
| `tests/fixtures/opaque-spawn-v1.json` | SG-F01 主要，SG-F07 可见性样本 | 证明 Hook 正文不可见时仍可通过 `task_name` 识别治理等级；opaque 不是失败状态。 |
| `tests/fixtures/recovery-limit-v1.json` | SG-F03/SG-F05 主要，SG-F07 状态样本 | 提供一次恢复和恢复上限的本地状态证据，不是完整 attempt 历史。 |
| `tests/fixtures/interrupt-v1.json`、`lifecycle-v1.json` | SG-F05/SG-F06 主要，SG-F07 次要样本 | 提供中断、Session 和终态输入；不能证明父任务实际看到提示或完成用户闭环。 |
| `tests/test_concurrency.py` | SG-F05 主要，SG-F07 容量/一致性次要证据 | 证明并发状态写入，不覆盖诊断并发读取、输出一致性或真实多 Agent 可观测性。 |

以下文件已核对并明确不属于 SG-F07 主要实现：`.codex-plugin/plugin.json`、`skills/subagent-governance/agents/openai.yaml` 和 `tests/test_plugin_structure.py` 归 SG-F02/SG-F04；`scripts/check_installation.py`、`scripts/reinstall_preserving_caches.py`、`scripts/apply_agents_block.py`、`docs/release-process.md`、`tests/test_release_tools.py` 归 SG-F04；`skills/subagent-governance/references/governance-levels.md` 主要归 SG-F01。它们不因包含“检查”“状态”或“验证”字样并入运行诊断。

### 4. 共享大文件核心代码区段覆盖

| 文件与函数/区段 | SG-F07 归属 | 当前事实与最终边界 |
| --- | --- | --- |
| `scripts/subagent_governance.py`：`main()` 的参数解析和诊断分支 | 主要 | 未知参数和孤立选择器已修补为退出 2；诊断异常仍缺少统一 JSON 错误边界。 |
| `scripts/subagent_governance.py`：`_diagnose()` | 主要 | 提供全局摘要和单 Session 状态；当前不是严格只读，两种读取路径不一致，部分失败静默且总返回 0。 |
| `scripts/subagent_governance.py`：`_prepare_private_directory()`、`_data_root()` | SG-F05 主要，SG-F07 读取交界 | 当前诊断会借此创建或修改数据根；目标只读路径不得产生这些副作用。 |
| `scripts/subagent_governance.py`：`StateStore._empty_state()`、`_read_path()`、`read()` | SG-F05 主要，SG-F07 核心上游 | 提供健康、容量、所有者、结构和损坏隔离事实；会创建锁、隔离文件并覆盖版本，不可直接作为只读诊断适配器。 |
| `scripts/subagent_governance.py`：`StateStore._prune_state()`、`_write_path()` | SG-F05 主要，SG-F07 容量事实 | 提供 4 MiB、200 条和 30 天边界；诊断只展示，不改变裁剪或保留策略。 |
| `scripts/subagent_governance.py`：`_recent_records()`、`_active_records()` | SG-F05 生成状态集合，SG-F07 当前主要消费者 | `active` 是 12 小时近期集合，不是所有待处理任务；未来改造后函数应改名、降级为兼容字段或移除。 |
| `scripts/subagent_governance.py`：`_session_restore_records()`、`_session_end_preserved_records()` | SG-F05 主要，SG-F07 对照输入 | 两者证明恢复展示和会话保留语义不同；诊断不能只复用 `active` 计数。 |
| `scripts/subagent_governance.py`：`_session_next_action()`、`_session_summary_line()`、`_session_start_context()` | SG-F05 主要，SG-F07 提示交界 | 已有简短操作提示和容量上限；可共享稳定事实或问题码，但不应改造成第二份完整诊断报告。 |
| `scripts/subagent_governance.py`：`_handle_post_tool()` 的 spawn/list/follow-up/interrupt 分支 | SG-F03/SG-F05 主要，SG-F07 证据输入 | 写入 Agent 映射、平台观察、恢复计数和中断事实；诊断不得从最终快照补造未持久化 attempt。 |
| `scripts/subagent_governance.py`：`_handle_subagent_start()` | SG-F05 主要，SG-F07 证据输入 | 证明启动 Hook 被观察，不证明业务执行或网络恢复已经完成。 |
| `scripts/subagent_governance.py`：`_handle_subagent_stop()` | SG-F06 主要，SG-F07 结果输入 | 写入当前结果片段和协议状态；诊断不重复自由文本验收，也不把 Hook 放行当作父任务已收到结果。 |
| `scripts/subagent_governance.py`：`_handle_stop()`、`_handle_session_start()`、`_handle_session_end()` | SG-F05 主要，SG-F07 展示交界 | 产生结束保护、恢复摘要和清理提示；它们是即时消费方，不是权威诊断状态。 |
| `scripts/subagent_governance.py`：Hook 模式顶层异常包装 | SG-F02 主要，SG-F07 告警交界 | PreToolUse 未知异常 deny，其他 Hook fail-open 并拼接异常；最终可统一问题码和有界提示，但不能由 SG-F07 单独改变执行策略。 |
| `scripts/subagent_governance.py`：`STATE_VERSION`、`MAX_HOOK_INPUT_BYTES`、`MAX_STATE_BYTES`、终态和 Session 摘要常量 | SG-F05/SG-F02 主要，SG-F07 边界输入 | 诊断展示和只读检查必须尊重这些实际边界；StateStore 版本不能继续被静默改写后再报告。 |

### 5. 测试、fixture 与真实证据边界

#### 当前已经覆盖

- `test_diagnose_rejects_unknown_and_orphan_selector_arguments` 保护诊断参数边界和退出码 2。
- `test_diagnose_reports_explicit_data_root` 证明全局诊断接受显式数据根并返回 `sessions`。
- `test_diagnose_session_returns_selected_session_json` 证明单 Session 选择器返回合法 JSON 和正确任务引用。
- `test_corrupt_state_is_quarantined_and_spawn_is_allowed` 与 `test_successful_state_update_does_not_silently_clear_degraded_health` 证明当前损坏隔离、degraded 证据和后续写入行为。
- `test_diagnose_active_count_excludes_stale_and_action_required_records` 证明当前 `active` 与 SessionEnd 保留集合存在语义差异。
- `test_recovery_state_keeps_counters_but_no_transition_history` 证明当前最终快照只有状态、计数和最近平台观察，没有转换历史。
- opaque、平台错误、有界错误摘要、SessionStart/End、Stop、结果和 fixture 测试提供问题定位所需的上游事实样本。

#### 当前仍缺少

- 真正无副作用诊断的测试：不存在数据根、Session 不存在、不创建锁、不 chmod、不隔离或改写损坏状态。
- 全局与单 Session 共用读取规则的测试：符号链接、非普通文件、所有者、4 MiB、非法根节点、Session ID 不匹配和不可读文件。
- 部分读取失败 JSON、检查总数/成功数/遗漏数、最小非零退出语义和完整失败的测试。
- 当前、缺失、旧版和未来未知 StateStore 版本，以及诊断保留 `stored_version` 的测试。
- 按原始状态、父任务动作、身份和最后变化生成快照的测试；不能继续只断言一个 `active` 数字。
- 稳定问题码、多问题并存、五类证据来源和简短操作提示的测试。
- 活跃任务或未知 `platform_status` 撑满 4 MiB、全局输出简单上限和隔离文件实际增长的测试。
- 真实 Codex 新任务对 `--diagnose` 的调用、Hook 告警展示、SessionStart 注入、`list_agents` 响应和 provider 断流边界 smoke。

#### 证据能够证明的上限

- Handler 单元测试只证明本地 Python 代码对测试 payload 的处理。
- fixture 只证明仓库中预设事件序列能够得到相应状态投影。
- StateStore JSON 只证明某个运行时曾写入相应字段，不证明平台此刻状态或父任务已经看到。
- `list_agents` 明确 `errored` 只证明该次平台响应报告错误，不证明 provider 根因、消息投递或网络恢复。
- Agent 自述和 `result_document` 只证明内容被保存并通过当前机械路径，不替代父 Agent 对文件、命令、测试和业务结果的验收。

本文记录的 151～156 项历史完整回归结果来自并行工作区的不同时点，只能证明当时共享工作树通过相应命令，不能作为 SG-F07 独占测试数量或最终协议事实。整体收口没有修改运行时代码和测试，因此不重新声称最新完整回归结果。

### 6. 保留、改造、合并与疑似退役结论

| 当前内容 | 结论 | 原因与处理方向 |
| --- | --- | --- |
| `--diagnose`、`--session`、`--data-root` | 保留 | 是清楚、低成本的本地运行诊断入口；保持兼容调用方式。 |
| `_diagnose()` | 保留职责、重写读取与输出内部 | 当前有实际调用价值，但副作用、两套读取语义和静默跳过必须改造。 |
| 完整单 Session 状态和绝对 `data_root` | 保留 | 是合理本地诊断证据，不做无依据全面脱敏；未来稳定 JSON 可继续提供或清楚标记原始状态。 |
| `_active_records()` 与 `active` | 暂时保留兼容、降级权威性 | 仍被诊断使用，不是死代码；12 小时窗口不能代表所有待处理工作。 |
| `health.status=degraded` | 保留事实、补完整度表达 | 损坏隔离证据有价值，但不能同时表示数据根、本次扫描和全部组件健康。 |
| Skill 八类诊断术语 | 保留导航、拆分语义 | 阶段、可见性、组件健康和平台观察不能继续作为同级互斥失败类型。 |
| `delivery-suspected` | 建议退役或改名 | 当前没有平台投递确认；优先表达 `identity_unconfirmed` 或 `delivery_unconfirmed`，不能写成已证明投递失败。 |
| `transport-opaque` | 保留能力限制，不作失败状态 | 只能证明 Hook 看不到正文；合法 `task_name` 下任务仍可正常进入 `pending`。 |
| `state-degraded`、`platform-error` | 保留事实，移出扁平失败主类 | 前者是组件健康，后者是平台观察；都不等于业务失败。 |
| `test_recovery_state_keeps_counters_but_no_transition_history` | 疑似退役或改写 | 只固化“当前没有事件字段”的缺口；实现最后状态变化后应验证目标行为。 |
| `test_diagnose_active_count_excludes_stale_and_action_required_records` | 疑似退役或改写 | 只固化当前 `active` 矛盾；新快照完成后应按状态/动作断言。 |
| 完整事件/attempt 因果链、证据图和五级可信度 | 删除目标 | 没有当前需求或运行证据支持，超出本项目必要诊断范围。 |
| 四层持久诊断输出、`subagent-diagnostic-v1` 权威管线和脚本用户摘要 | 删除目标 | 当前只需稳定 JSON、已有 Hook/Session 提示和父 Agent 业务表达。 |
| 分页、稳定游标、完整查询矩阵 | 删除预设计 | 当前没有实际数据规模或消费者需求；先用简单数量上限和遗漏数。 |
| 独立诊断 Schema 的 N/N-1 体系、五档退出码 | 删除预设计 | 没有独立外部机器消费者；先解决 StateStore 原始版本读取和最小退出语义。 |
| SG-F06 的自由文本终态函数和 600 字符结果片段 | 不归 SG-F07 删除 | 属于 SG-F06 结构化结果迁移；SG-F07 只登记诊断影响。 |
| SG-F05 的 `dispatched` 无写入者、状态集合混合和锁文件生命周期 | 不归 SG-F07 单独删除 | 属于生命周期与状态模型；SG-F07 只展示冲突并消费最终结论。 |

当前没有可以由 SG-F07 独立直接删除的有效运行时代码、Schema、fixture 或文件。可退役内容主要是本文中的过度设计、两个现状特征测试在目标行为实现后的旧断言，以及 Skill 中可能误导的 `delivery-suspected` 命名。

### 7. 跨功能冲突与最终合并事项

1. **主盘点时点滞后**：`docs/project-function-inventory.md` 仍以 SG-F01～SG-F03 的正式收口为主，包含早期诊断候选和状态事实；最终合并应以本文六项结论为准。
2. **Skill 分类混层**：八类“诊断失败”同时表达阶段、可见性、组件健康和平台观察；最终规则应改成少量问题码加来源，不作为任务 `status`。
3. **生命周期参考滞后**：`runtime-boundaries.md` 仍有 Stop/SessionStart 忽略 `platform_error` 的旧描述，当前运行时和 SG-F05 已将其纳入相关集合。
4. **StateStore 版本不诚实**：SG-F05 与本文都确认读取器把任意可读版本覆盖为 2；SG-F04 又需要 N/N-1 兼容结论。最终方案必须先解决原始版本读取，再谈发布兼容。
5. **结果与诊断边界**：SG-F06 的正式 ResultStore 尚未实现；SG-F07 不能提前冻结结果引用字段，也不能继续把临时 `result_document` 当长期诊断协议。
6. **协调输入时点漂移**：SG-F08 已完成盘点但没有正式运行实现；其文档仍称 SG-F07 只完成前五项、尚未完成输出/敏感信息/版本三项，并把未来协调状态描述为诊断输入。最终合并应更新进度事实，只保留职责方向。
7. **公开承诺与实现差距**：README 和优化计划笼统声明诊断能力或目标展示项；当前实现仍只有有限汇总和原始单 Session 状态，不能描述成完整运行可观测性。
8. **状态与问题混用**：SG-F05 生命周期状态、SG-F06 业务结果、SG-F07 诊断问题和未来 SG-F08 组状态不能继续共用一个扁平 `status` 语义。
9. **历史回归数量漂移**：各盘点文档记录的全仓测试总数来自不同并行时点；最终合并只记录验证命令和当次结果，不比较历史数字。
10. **本地与平台证据混用**：主盘点、Skill、README 和测试说明都应明确 Handler、fixture、本地 JSON、真实 Codex smoke 和 provider 观察分别能证明到哪一层。

### 8. 最终统一修改包建议顺序

| 修改包 | 主要内容 | 依赖与边界 |
| --- | --- | --- |
| 1. 无副作用诊断读取 | 建立统一只读解析，处理不存在、损坏、超限、所有者、结构和原始版本；全局与单 Session 共用 | 复用 SG-F05 的检查语义但不创建锁、不隔离、不回写、不 chmod |
| 2. 健康与部分失败 | 分开组件健康和本次检查完整度，输出检查总数、成功数、遗漏数、读取错误和最小问题码 | 不改变 SG-F02/SG-F05 的 fail-open/deny 或状态恢复动作 |
| 3. 快照与最后变化 | 输出原始状态、状态分组、父任务动作、身份映射、关键时间、retry/recovery 计数和最后可观察变化 | 与 SG-F05/SG-F06 共同确定状态/结果分层；不建设完整事件链 |
| 4. 真实证据问题定位 | 收缩 Skill 八类术语，定义少量稳定问题码和五类来源，明确 `delivery_unconfirmed`、opaque、degraded 和 platform error 边界 | 不通过缺失证据或自由错误文本猜测平台、执行和业务结论 |
| 5. 稳定 JSON 与最小 CLI 语义 | 统一全局/单 Session 顶层形状、稳定排序、简单输出上限、遗漏数、必要操作提示和最小退出语义 | 保持当前入口兼容；不创建四层报告、分页系统或脚本用户摘要 |
| 6. 容量、版本和规则收口 | 覆盖 4 MiB、活跃记录、未知平台对象、原始版本和 N/N-1 读取测试；同步 Skill、README、runtime boundaries、主盘点和相邻文档 | SG-F04 执行真实发布兼容门禁；SG-F07 不迁移状态、不发布、不修改协调或结果协议 |

建议按 1 → 2 → 3 → 4 → 5 → 6 实施。只先改输出字段会继续继承副作用和版本误报；只先改 Skill 术语又没有机器事实支撑；先建设事件、Schema、分页或脱敏系统则会重新引入已经确认不必要的复杂度。

### 9. 已直接完成与尚未实现的边界

逐项盘点期间已经按用户授权完成：

1. `main()` 在诊断分支前拒绝未知参数。
2. `--session` 和 `--data-root` 脱离 `--diagnose` 时返回退出码 2。
3. 增加诊断参数、单 Session JSON、degraded 保留、active 语义差异、恢复链缺少历史和 opaque 非失败边界的定向测试。

这些局部修改只保护现状和明确参数边界。当前尚未实现：

- 无副作用只读读取器。
- 部分失败、读取错误和非零诊断退出语义。
- 正式快照、最后变化和稳定问题码。
- 统一诊断 JSON 形状及简单输出上限。
- StateStore 原始版本保留、版本处理矩阵和 N/N-1 兼容测试。
- 真实 Codex/provider 诊断 smoke。

整体收口本轮没有修改运行时代码、测试、Schema、Skill、README、AGENTS、主盘点或其他功能文档，也没有执行 Agent 恢复、中断、发布、安装、缓存、Hook trust 或外部状态操作。

### 10. 最终完成结论

- SG-F07 的最终名称、职责、主要入口、上下游和明确排除范围已经确认。
- 八个首轮候选已收缩为六个必要功能点；不再建设完整事件审计、复杂证据等级、四层持久报告、全面脱敏、分页查询或独立诊断版本体系。
- `--diagnose`、`health/degraded`、Session/任务/Agent 摘要、状态变化证据、八类指导术语、Hook 告警、容量、保留和 StateStore 版本读取的当前行为及问题均已登记。
- 相关仓库文件、共享大文件核心区段、测试、fixture、疑似退役内容、真实平台证据边界和跨功能冲突已经覆盖。
- 当前没有新的 SG-F07 功能点需要继续逐项盘点；后续进入全部功能文档的统一合并审查，并按六个修改包形成项目级修改方案。
- 本文完成表示盘点和方案输入已经闭环，不表示运行诊断协议已经实现，也不扩大修改共享代码、发布环境或其他盘点文档的权限。
