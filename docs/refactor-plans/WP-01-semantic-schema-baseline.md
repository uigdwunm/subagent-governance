# WP-01 语义与 Schema 基线详细改造方案

## 一、状态与目标

- 工作包：WP-01「语义与 Schema 基线」。
- 权威来源：`docs/project-function-inventory.md`，尤其是 U-01～U-06、U-08、U-10、SG-F01、SG-F06、第十三节、第十七节和第十八节。
- 唯一目标：固定后续工作包共同依赖的任务契约、正式结果、治理等级、上下文策略、状态维度、父任务动作和机械校验边界，并让 Schema、Python 语义接口、Skill、分发资产和一致性测试对齐。
- 当前状态：方案已完成初稿；实施后将在本文末尾同步实际修改、验证结果和 `not_checked` 项。

## 二、修改前基线与现状缺口

修改前运行了三项既有一致性测试：

```text
python3 -m unittest -v \
  tests.test_governance.GovernanceTests.test_runtime_task_contract_matches_schema_shape \
  tests.test_governance.GovernanceTests.test_successful_result_document_matches_schema \
  tests.test_plugin_structure.PluginStructureTests.test_protocol_schemas_match_runtime_contract
```

结果为 3 项全部通过，但这些测试只证明旧 Schema、旧 Python 数据类和旧内嵌结果彼此一致，不能证明它们符合主盘点。

随后执行只读字段差异检查，得到以下稳定缺口：

- 任务契约缺少：`background`、`completion_conditions`、`context_reason`、`context_strategy`、`context_turns`、`current_state`、`evidence_requirements`、`forbidden_scope`、`relevant_files`、`semantic_name`、`task_features`、`work_scope`。
- 任务契约仍包含已否决定义：`protocol`、`mode`、`mode_reason`、`scope`、`completion`、`message_visibility`、`child_agents`、`fork_turns`。
- 正式结果缺少：`attempt`、`business_result`、`suggested_parent_next_step` 以及 blocked、failed、needs_decision 的场景字段。
- 正式结果仍包含已否决定义：`protocol`、宽泛 `status`。
- Python 仍存在旧语义目标：协议版本常量、`STATE_VERSION`、正文风险关键词集合、ACK/证据关键词和 strict 终态自然语言字段检查。

具体差异如下：

1. `schemas/task-contract-v1.schema.json` 描述的是 Hook 从正文拼出的旧记录，不是主盘点确认的统一任务契约。
2. `schemas/task-result-v1.schema.json` 把机械异常和业务结果混入同一 `status`，没有 attempt 绑定和分场景业务字段。
3. `scripts/subagent_governance.py` 的 `TaskContract` 保存协议版本、正文可见性、独立下级 Agent 授权和原生 `fork_turns`；这些都不是目标契约字段。
4. `_resolved_mode()` 读取业务正文、风险词和 `【下级子 Agent】`，与结构化 `task_features` 裁决冲突。
5. `_terminal_errors()` 使用 ACK 词表、字符数、证据关键词、任务 ID 和固定终态卡判断业务充分性，越过机械校验边界。
6. `_reported_status()` 从自由文本推断业务结果，现有 `result_document` 截断正文并固定写空 `evidence/remaining`；该路径在 WP-05 前仍有生命周期消费者，但不能继续作为正式结果 Schema 或最终验收要求。
7. `STATE_VERSION`、结果/通信/任务 `protocol` 字段仍被写入或展示，形成已被 U-10 否决的交互和持久化版本语义。
8. Skill 和等级参考仍描述正文 auto 分类、独立 `child_agents` 授权、分等级结果补交次数和自然语言终态硬校验。
9. 分发资产已经收缩为按需加载 Skill 的最小入口，本阶段只需用一致性测试确认它不重新复制机器协议。

## 三、本阶段修改范围

### 3.1 允许修改

- 新增最小机器语义源：`schemas/governance-semantics.schema.json`。
- 重写 `schemas/task-contract-v1.schema.json` 和 `schemas/task-result-v1.schema.json`，使其引用机器语义源。
- 修改 `scripts/subagent_governance.py` 顶部协议常量、枚举、数据类和纯机械校验函数；仅做阻止旧语义继续成为权威所必需的最小运行时衔接。
- 更新 `skills/subagent-governance/SKILL.md`、`skills/subagent-governance/references/governance-levels.md` 和直接重复旧边界的 `runtime-boundaries.md`。
- 必要时调整 `assets/agents-governance.md`；若现有最小入口已符合 U-10，则只增加测试锚点，不为改动而改动。
- 新增或改写 Schema、语义一致性和最小运行时回归测试。
- 同步本文的实施结果和验证证据。

### 3.2 明确禁止

- 不实现 PreparedContract、task ref 碰撞处理、spawn 前硬门禁、确定性 prompt 生成器或身份绑定链；这些属于 WP-03。
- 不重写 StateStore 锁、容量、损坏保全、CAS、tombstone 或清理行为；这些属于 WP-02。
- 不实现 `pending_action`、四类通信的完整运行时状态转换、恢复计数认领或中断 unknown 对账；这些属于 WP-04。
- 不实现正式 result 文件写入、结果冲突、有限补交状态机、父验收或 parent disposition；这些属于 WP-05。
- 不实现 SessionStart/End、Stop、等待恢复、多 attempt、重复执行、诊断或 group 的目标状态机；这些属于 WP-06～WP-07。
- 不发布、不安装、不写稳定源、Marketplace、运行缓存、Hook trust 或 Registry。
- 不清理与本阶段无关的用户修改，不 stage、不 commit、不 push。

## 四、目标语义与单一来源

### 4.1 机器语义源

新增 `schemas/governance-semantics.schema.json`，集中保存：

- 请求治理方式：`auto | light | standard | strict`。
- 实际治理等级：`light | standard | strict`。
- task feature 的 `risk`、布尔字段和结构化 auto 解析规则所需信号。
- `reasoning_effort`：`low | medium | high | xhigh | max | ultra`。
- 上下文策略：`isolated | limited | full`，以及 `context_turns` 的 1～100 边界。
- 通信 operation type：`normal_message | platform_recovery | result_correction | business_resume`。
- 执行、派发观察、身份、平台观察、业务结果、父验收、结果协议、结果存储、恢复状态和父动作枚举。
- 父处置 action、调用观察和 lifecycle operation 枚举。
- 三类独立次数上限、PreparedContract/pending 对账时限、recent activity 和 tombstone 保留期。
- 目标 task name 格式 `sg_<resolved_mode>_<semantic_name>_t_<task_ref>`、64 字符上限和 task ref 长度序列。
- 任务契约、正式结果和 attempt 初始状态的字段集合。

JSON Schema 通过 `$ref` 复用其中的枚举和基础字段；Python 在导入时读取同一文件并导出只读常量。自然语言文档不从该文件生成，只用少量一致性测试核对核心名称和已删除语义。

### 4.2 统一任务契约

单一 `TaskContract` 包含：

- AI 输入字段：`semantic_name`、`requested_mode`、`task_features`、`objective`、`background`、`work_scope[]`、`forbidden_scope[]`、`completion_conditions[]`、`evidence_requirements[]`、`relevant_files[]`、`current_state`、`model`、`reasoning_effort`、`context_strategy`、`context_turns`、`context_reason`。
- 生成阶段字段：`resolved_mode`、`resolution_reason`。

机械组合规则：

- `requested_mode=auto` 时 `task_features` 必填；显式等级时可省略。
- 显式等级的 `resolved_mode` 必须与请求值相同，reason 固定为 `explicit_request`。
- auto 只读取结构化 feature：任一 strict 信号为 true 或 `risk=high` 时解析 strict；`risk=low + read_only=true + writes_files=false` 且无 strict 信号时解析 light；其余合法组合解析 standard。
- `read_only=true` 与 `writes_files=true` 是机械矛盾。
- standard 至少一个 `evidence_requirements`；strict 至少一个 `forbidden_scope` 和一个 `evidence_requirements`；light 可为空。
- `isolated` 要求 `context_turns=null`，reason 可空；`limited` 要求 1～100 且 reason 非空；`full` 要求 turns 为 null 且 reason 非空。
- `model` 可空或省略；显式值只检查非空字符串和长度。`reasoning_effort` 可空或省略；显式值只检查固定枚举。
- 未知额外字段兼容忽略；不使用协议版本门禁，不补造缺失业务事实。

### 4.3 统一正式结果

单一 `TaskResult` 基础字段：

- `task_id`、`attempt`、`business_result`、`result`、`evidence[]`、`remaining[]`、`suggested_parent_next_step`。

场景字段：

- blocked：`blocker`、`attempted[]`、`required_to_resume`。
- failed：`failure_reason`、`attempted[]`、`retry_conditions`。
- needs_decision：`decision_question`、`options[]`、`recommendation`。
- complete：不增加父验收字段；`acceptance_status` 只属于后续 StateStore。

结果 Schema 不包含 `protocol`、宽泛 `status`、`acceptance_status`、`result_protocol_status` 或 `result_storage_status`。`evidence[]` 必须存在但允许为空。脚本只检查字段、类型、枚举、引用、长度和基本组合，不判断结果真实性、证据充分性或建议正确性。

### 4.4 attempt 初始状态接口

新增仅表达初始值的 `AttemptState` 数据结构，固定：

```text
execution_status=not_started
spawn_observation=null
identity_status=unconfirmed
platform_observation=null
business_result=null
acceptance_status=null
result_protocol_status=null
result_storage_status=null
result_conflict=false
recovery_status=null
parent_action=null
spawn_retry_count=0
recovery_count=0
correction_count=0
```

该结构只是 WP-02 的稳定输入和测试锚点，不在本阶段接管现有 StateStore 或实现状态转换。

## 五、文件级实施步骤

1. 先新增语义/Schema 定向测试，覆盖字段集合、枚举、条件组合、无版本字段、未知字段兼容、结构化 auto、上下文策略、正式结果场景字段和初始状态。
2. 新增机器语义源，并让两个当前 Schema 通过相对 `$ref` 使用其定义。
3. 在 Python 中加载语义源，新增目标常量、`TaskFeatures`、`TaskContract`、`TaskResult`、`AttemptState` 和纯机械 validator/auto resolver。
4. 移除 Python 中作为最终语义来源的协议版本常量和 StateStore `version` 写入；已有状态按当前操作字段读取，完整安全改造留给 WP-02。
5. 删除正文关键词 auto 分类函数和词表。当前 Hook 在 WP-03 生成器接管前仅接受已经解析为 light/standard/strict 的旧式过渡 task name，不再接受 `sg_auto_`；目标 task name 正则只作为 WP-03 稳定接口，不提前实现 task ref/PreparedContract。
6. 删除 ACK、字符数、证据关键词、任务 ID 和 strict 终态卡驱动的阻断。WP-05 前保留最小自由文本生命周期桥接，但明确它不是正式结果 Schema 或业务验收来源；旧内嵌结果不再与正式结果 Schema 做一致性断言。
7. 更新 Skill 和等级/运行边界参考：要求 AI 提供结构化字段，说明 auto、上下文、结果和机械校验边界；删除独立 `child_agents` 授权、正文分类、分级补交预算和自然语言硬验收目标。
8. 保持全局分发资产为最小 Skill 入口；一致性测试确认其不复制机器协议。
9. 改写旧一致性测试，确保它们不再把已否决结构当作最终要求；保留与当前生命周期桥接直接相关的最小回归测试。
10. 运行定向测试、全量测试、编译、Plugin validator、Skill validator、Schema/fixture 校验和 `git diff --check`；最后同步本文实施结果。

## 六、新旧路径切换与暂时保留

### 本阶段原子切换

- Schema 和 Python 的权威契约/结果数据结构一次切换到新字段。
- auto 的权威解析一次切换到结构化 `task_features`；正文分类常量和函数删除。
- 版本字段不再属于契约、结果、通信或新建 StateStore 的权威结构。
- 自然语言终态不再执行 ACK、长度、关键词、任务 ID 或固定卡片业务验收。

### 暂时保留到后续工作包

- 当前 Hook 的旧式 `sg_<resolved_mode>_<semantic_name>` 名称只作为 WP-03 前的运输桥接；目标名称常量已经固定为带 `_t_<task_ref>` 的格式，但本阶段不伪造 task ref，也不实现 PreparedContract。
- 当前 StateStore 的单一 `status`、`retry_count`、旧任务记录形状和通用裁剪由 WP-02 及后续工作包原子替换；本阶段新增的 `AttemptState` 不提前接管这些消费者。
- 当前 SubagentStop 仍需让旧生命周期测试可结束，但其自由文本桥接结果不再称为正式结果，也不再受正式结果 Schema 支持；正式 result 文件、结果提交顺序和父验收由 WP-05 实现。
- 通信正文投影和旧恢复状态机保持到 WP-04；本阶段只固定 operation type 枚举和删除版本文案。

这些临时内容必须在对应后续工作包中由新消费者接管后删除，不能被新测试重新固化为最终协议。

## 七、测试策略

### 7.1 先增改的定向测试

- 语义源可以解析，核心枚举、次数、期限和 task name 规则与主盘点一致。
- contract/result Schema 没有 `protocol` 版本字段，未知额外字段允许存在。
- Python 数据类字段与语义源/Schema 一致。
- explicit mode 不被 task features 二次裁决。
- auto 只按结构化 features 解析 light/standard/strict，并拒绝明显机械矛盾。
- 上下文 `isolated/limited/full` 组合正确。
- standard/strict 的数组最低要求正确，light 允许空 forbidden/evidence。
- formal result 的 complete/blocked/failed/needs_decision 场景字段正确，`evidence[]` 可为空。
- `AttemptState` 初始 null、枚举和三类计数正确。
- 旧正文风险词不再参与 auto；旧 ACK/长度/证据关键词/strict 卡不再构成终态硬阻断。
- Skill/参考文档包含当前字段、操作类型、目标名称和机械校验边界，不再要求独立 `child_agents` 或版本门禁。

### 7.2 验证命令

```text
python3 -m unittest -v <WP-01 定向测试>
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
python3 $HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 $HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
JSON Schema 与 fixture 校验命令（使用环境可用的 validator；若无第三方库则使用仓库内确定性结构检查）
git diff --check
```

## 八、真实平台 not_checked 项

以下项目无法由 WP-01 仓库测试证明，统一记录为 `not_checked`：

- 原生 `spawn_agent` 对未来生成器输出参数的真实接受情况。
- 真实 `SubagentStart` 是否稳定暴露 task name/task ref。
- 原生 spawn 响应中的 Agent ID/canonical path 形状。
- isolated、limited、full 到真实原生上下文参数的映射。
- 结构化正式结果如何进入真实 SubagentStop/mailbox/summary 链路。
- Hook trust、Skill 实际加载和运行缓存切换。

## 九、退出条件

WP-01 只有在以下条件同时满足时退出：

1. 本文与实际修改同步。
2. 机器语义源、两个 Schema、Python 目标数据结构、Skill/参考文档和一致性测试使用同一字段和枚举。
3. 版本门禁、正文关键词 auto 分类和自然语言业务语义硬验收已从目标语义中删除；旧测试不再把它们当作最终要求。
4. 仅建立 WP-02～WP-08 所需接口，没有提前实现状态机、存储、派发链、通信链、结果持久化、会话恢复、诊断或 group。
5. 所有适用本地验证通过；真实平台项明确为 `not_checked`。
6. `git diff` 中没有本任务产生的无关修改。

## 十、交给 WP-02 的稳定接口

- 可直接从机器语义源和 Python 常量读取全部状态维度、合法枚举、次数上限、保留期限和父动作。
- `AttemptState` 提供新 attempt 的唯一初始值集合，WP-02 不得自行补充 `pending/unset` 或版本字段。
- `TaskContract` 提供 StateStore 最小摘要所需的目标、范围、完成条件、证据要求和 resolved mode 字段名。
- `TaskResult` 和 business result → parent action 映射为 WP-05 预留稳定接口，但 WP-02 不得内嵌完整结果。
- WP-02 必须继续遵守未知额外字段兼容忽略、缺少当前操作必需字段明确报错、不静默补造事实的边界。

## 十一、实施结果

### 11.1 实际修改

新增：

- `schemas/governance-semantics.schema.json`：机器语义单一来源，集中保存字段集合、枚举、auto 解析信号、等级最低要求、上下文轮数、状态初值、父动作映射、次数/期限和目标 task name 规则。
- `tests/test_semantic_baseline.py`：覆盖机器语义、Schema、Python 数据结构和 validator 的一致性，以及已否决语义不再作为运行时权威。
- 本方案文档。

重写或调整：

- `schemas/task-contract-v1.schema.json`：切换为统一任务契约；移除协议版本、旧 `mode/scope/completion/message_visibility/child_agents/fork_turns`，引用机器语义源，并固定上下文与等级机械组合。
- `schemas/task-result-v1.schema.json`：切换为统一正式业务结果；移除协议版本和宽泛 `status`，增加 attempt、四类业务结果和分场景字段。
- `scripts/subagent_governance.py`：新增 `TaskFeatures`、`TaskContract`、`TaskResult`、`AttemptState`、`resolve_governance_mode()`、`validate_task_contract()` 和 `validate_task_result()`；Python 枚举、次数、期限、auto 规则、等级最低要求、上下文边界、结果场景字段和 attempt 初值读取机器语义源。
- `skills/subagent-governance/SKILL.md`、`references/governance-levels.md`、`references/runtime-boundaries.md`：改为结构化契约、结构化 auto、显式 operation type、统一正式结果和纯机械校验边界。
- `tests/test_governance.py`、`tests/test_plugin_structure.py`、`tests/test_concurrency.py`、`tests/fixtures/recovery-limit-v1.json`：删除或改写继续要求正文分类、协议版本、自然语言终态硬验收和旧 Schema 形状的断言，同时保留当前运输桥和生命周期回归。

`assets/agents-governance.md` 已经是符合 U-10 的最小 Skill 入口，本阶段没有为了制造差异而重复修改。

### 11.2 新旧路径边界

- 目标机器接口已经切换到新契约、正式结果、状态维度和父动作；新结构不包含交互/持久化协议版本门禁。
- WP-03 前暂时保留旧式已解析名称 `sg_<light|standard|strict>_<semantic_name>` 作为开发运输桥；它拒绝 `sg_auto_`，正文不再参与等级解析。目标名称 `sg_<resolved_mode>_<semantic_name>_t_<task_ref>` 只固定语义和正则，没有提前实现 PreparedContract 或 task ref。
- WP-05 前暂时保留自由文本 Stop 生命周期桥。它只检查回复是否为空，内嵌记录标记 `source=legacy_free_text`，不再冒充正式结果 Schema，也不以 ACK、长度、关键词、任务 ID 或 strict 卡片判断业务充分性。
- 现有 StateStore 的旧平面状态和后续运行时消费者没有在本阶段重写；`AttemptState` 只是 WP-02 的稳定初始接口。
- `result_correction`、`business_resume` 的完整状态转换、正式结果存储、父验收、会话恢复和诊断仍由 WP-04～WP-07 实现，本阶段没有提前接管。

### 11.3 验证结果

以下验证全部通过：

```text
python3 -m unittest discover -s tests -v
  166 tests, OK

python3 -m py_compile scripts/subagent_governance.py
  passed

python3 $HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
  Plugin validation passed

python3 $HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
  Skill is valid

JSON/fixture deterministic validation
  3 schemas and 5 fixtures parsed; all local $ref targets and JSON pointers resolved;
  regex patterns compiled; canonical contract/result passed Python mechanical validators

git diff --check
  passed
```

系统 Python、Codex bundled Python 和 bundled Node 依赖中均未提供 `jsonschema`、`referencing` 或 `ajv`，因此没有声称执行第三方 Draft 2020-12 meta-schema validator。仓库内验证覆盖 JSON 解析、引用完整性、Schema/机器字段一致性、条件锚点、有效/无效样例和 Python validator 行为。

### 11.4 `not_checked` 与剩余风险

第八节列出的真实 Codex 平台项全部保持 `not_checked`。本地测试不能证明真实插件加载、Hook trust、原生 task name/task ref 可见性、上下文参数映射、mailbox 投递或结构化结果进入真实 Stop/summary 链路。

剩余风险均已限定在后续工作包：

- 当前旧 StateStore 和生命周期桥仍使用平面 `status`；必须由 WP-02 及后续阶段按新接口原子替换，不能把过渡记录形状当作最终 Schema。
- 当前 Hook 尚未消费目标 `TaskContract` 或正式 `TaskResult`；WP-03/WP-05 接入时必须继续使用本阶段 validator 和机器语义源，不能重新解析正文或复制枚举。
- 尚无第三方 JSON Schema 引擎的独立执行证据；后续运行环境提供 validator 时可补充，但不得以此改变本阶段已确认字段和机械语义。

### 11.5 退出结论与 WP-02 交接

WP-01 的本地退出条件已满足：方案与实施同步；Schema、Python、Skill、参考资产和测试使用同一组字段与枚举；协议版本门禁、正文关键词 auto 分类和自然语言业务语义硬验收已从目标语义及旧测试要求中退役；没有提前实现 WP-02～WP-08；适用本地验证全部通过。

交给 WP-02 的稳定接口：

- `MACHINE_SEMANTICS` / `schemas/governance-semantics.schema.json` 是状态字段、枚举、初值、次数、期限和父动作的机器来源。
- `AttemptState().to_record()` 必须继续等于 `x-semantics.initial_attempt_state`；WP-02 不得增加 `pending/unset` 或版本字段补造初值。
- `TaskContract`、`TaskResult` 及两个 validator 是后续持久化摘要和正式结果接入的字段边界；未知额外字段兼容忽略，缺少当前操作必需字段明确报错。
- WP-02 只接管最小安全 StateStore，不得顺带实现 PreparedContract、派发链、通信链、结果文件、父验收、会话恢复或 group。
