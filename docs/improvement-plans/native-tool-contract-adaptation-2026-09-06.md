# 原生工具契约适配修复方案

- 日期：2026-09-06
- 状态：开发仓库实施完成，已通过本地门禁；待集中审查，未部署或真实验证
- 源码基线：`d570e527b247ed41642d604a8937e800399b3f38`
- 核对的安装版本：`0.4.0+codex.20260906031301`
- 本轮实施授权已完成开发仓库实现与本地验证；不包含真实派发、发布、安装或状态清理。

配套 [执行清单](native-tool-contract-execution-2026-09-06.md) 固定函数边界、状态字段、错误判定和分步验收；实现时两份文档一起读取。模型分工建议为 `gpt-5.6-terra / high` 串行实现、`gpt-6-astra / high` 集中审查；本轮不创建或派发这些任务。

实际本地验收见 [实施验收记录](../validation/native-tool-contract-adaptation-implementation-2026-09-06.md)。其中只覆盖隔离测试和静态契约，平台运行面仍未验证。

## 1. 目标与证据

让同一版本的插件依据当前任务实际暴露的工具契约生成合法派发，并准确解释消息、等待和中断结果。保留任务范围与完成条件、精确身份绑定、单次 claim、单一 ledger 和原生工具执行通道。

本次直接核对了任务暴露的 `collaboration` 工具说明，并用不写文件的纯函数检查复现参数问题；未调用 prepare、claim、confirm 或原生 Agent 工具。涉及问题的渲染器、归一化器、prepare、Hook、生命周期、Skill 和 canonical semantics Schema 与安装缓存逐字节一致；不据此声称整个源码目录与运行包相同。

| 事实 | 证据及结论 |
| --- | --- |
| 当前 spawn 必填 `message`、`task_name`，可选 `fork_turns`、`model`、`reasoning_effort` | 本任务工具契约；`fork_turns` 接受 `none`、`all` 或正整数字符串 |
| 渲染器输出 `message`、`fork_context`，不输出 `task_name` | [渲染器](../../scripts/governance_dispatch_rendering.py)；纯函数检查确认非法字段及缺少必填字段 |
| 合法的当前参数被 Hook 归一化器拒绝 | [归一化器](../../scripts/governance_dispatch.py)；纯函数检查得到“不支持的字段” |
| prepare 写入异常后的回读也依赖 `fork_context` | [prepare 服务](../../scripts/governance_protocol.py)；必须与正常路径一起修复 |
| 插件拒绝有限轮数，却接受 `all` 加模型/推理覆盖 | [契约校验](../../scripts/governance_contracts.py)；当前原生契约明确禁止完整继承时覆盖模型或推理强度 |
| Skill 引用 `send_input`、`close_agent` 和旧 wait 返回结构 | [Skill](../../skills/subagent-governance/SKILL.md)；本任务提供 `send_message`、`followup_task`、`interrupt_agent`、邮箱式 `wait_agent`，不提供上述两个旧工具 |
| matcher/router 不识别 `collaboration.spawn_agent` | [Hook 配置](../../hooks/hooks.json)、[路由](../../scripts/governance_hook.py)；宿主当前是否归一化名称尚未验证 |

这证明当前运行面的静态契约不匹配，不证明所有 Codex 版本不兼容，也不证明 GPT-6 模型导致问题。

历史证据必须保留各自适用范围：[9 月适配记录](../validation/native-context-adapter-2026-09-06.md)记录了另一种 `fork_context` 参数面；[8 月真实验证](../validation/current-only-real-platform-validation.md)记录了特定版本的 flattened 工具名、opaque message，以及消息和中断回执未知。它们不能替代本版本、本任务的真实验证。现有 [architecture](../architecture.md) 的部分适配描述已与源码不一致，实施时需同步修正文档，历史验收报告保持原貌。

## 2. 决策一：显式选择有限的派发适配器

新增一个小型纯函数模块 `scripts/governance_native_adapter.py`，集中定义两种已有证据的参数形态。名称表示接口形态，不绑定模型名或宣称覆盖某个产品的所有版本。

| 适配器 | 原生输出 | 继承及覆盖规则 | 支持声明 |
| --- | --- | --- | --- |
| `collaboration_turns` | `message`、`task_name`、`fork_turns`；有明确覆盖时追加 model/effort | 默认显式 `none`；允许有限轮数；`all` 禁止任意 model/effort 覆盖 | 本次直接可见契约；端到端待验证 |
| `fork_context` | `message`、布尔 `fork_context`；有明确覆盖时追加 model/effort | 只映射 `none/all`；拒绝有限轮数；额外组合限制遵从该任务实际工具说明 | 保留已记录参数形态；本次未暴露，不宣称当前端到端可用 |

- Skill 在 prepare 前核对实际工具 Schema 与说明，通过新增 CLI 参数 `--native-interface` 显式选择；无默认接口，不从模型、版本号、工具名后缀或历史会话猜测。
- 未识别的必填字段、参数形态或操作语义应在 prepare 写入前报告不支持，不先派发再试错，不建立多适配器重试链。
- 该选择是父 Agent 的明确协作声明，不冒充宿主自动探测或平台证明。prepare 的用户说明展示选择及验证限制。
- 适配器负责生成、归一化和接口专属校验；业务契约仍表达 `fork_turns`，不混入原生布尔字段。正整数语法和合理长度上限在 canonical semantics 中统一定义，不把插件上限描述为平台上限。
- 完整继承时不得偷偷删除用户指定覆盖；应报出冲突。模型与推理覆盖的授权继续服从实际平台说明和用户要求。
- 返回的 spawn 参数原样提交。`task_name` 由现有生成器产生；显式名称与消息首行名称同时可见时必须一致。
- 不引入动态适配器注册、用户自定义映射、后台探测或第二套派发工具。

## 3. 决策二：冻结选择，并同步正常与异常路径

每条 task 保存 `native_interface`，从 prepare 到 close/reconcile 始终保留；claim 读取该值，不根据当次输入字段重新选接口。prepared capability 仍保存语义参数及完整预期 message；原生输入经所选适配器归一化后比较。显式默认值与省略值只能按对应原生契约归一化，不能共用旧布尔默认逻辑。

prepare 的异常回读复用同一参数转换函数，额外比较冻结的接口。接口选择不进入 business contract digest；它作为独立必校验字段与现有 spawn 配置共同约束 claim。不得留下正常派发已适配、异常恢复仍按旧字段判断的分支。

新增持久字段会改变严格状态结构，实施采用新的 `state-v10` 命名空间及 `state_format_version=10`，同步 runtime validator、Schema、diagnostics 和测试；TaskContract v2 业务输入保留，接口选择属于 CLI 控制参数。v9 及更早账本不读取、不迁移、不清理，也不增加缺字段兼容分支。该变化的代价是新版不能恢复旧版未关闭治理任务，应在部署交接中明确，而不能静默声称旧任务已闭环。

exact Session、权威 CLI entrypoint、首次绑定不可覆盖、相同 claim/confirm 幂等、重复派发拒绝及 declared context 二次校验继续保持。原生返回的机械 target 是唯一绑定来源；不强制它必须是 UUID，也不由 task name 拼接 canonical path。通知 sender 若与绑定表示不同，不自动做别名推断。

## 4. 决策三：把 Hook 边界独立验证

模型可见参数合法，不等于 Hook 收到相同参数。实现必须分开测试名称匹配、输入可见性和 durable claim。

- matcher 与 router 使用同一组受测的精确名称。保留现有裸名及 `multi_agent_v1` 形式，加入本任务可见的 `collaboration.spawn_agent` 和历史有证据的 `collaborationspawn_agent`；不做任意前缀或后缀匹配。
- 名称只决定是否检查，不决定参数适配器。通过显式 governed `task_name` 或可见消息标记定位 task ref；二者同时存在而冲突时拒绝。task ref 仅定位 prepared capability，不建立原生 target identity。
- 明文可见时比较完整 message、名称及配置。opaque 或不可见正文不能通过“非空”替代正文一致性，也不能把明文写回可能承载加密内容的 `updatedInput`。
- 首版对无法验证的 Hook 输入放行原生调用，附有界诊断，不建立 claim、不宣称验证成功；confirm 缺 claim 时仍进入 reconcile，不重派。若真实运行面始终 opaque，则该面的 governed 主链验收不通过，需基于新证据另行决定是否接受较弱的正文校验承诺。本方案不默认恢复历史 opaque 旁路。
- unmanaged 和未知工具保持零状态透传。治理存储、解析或 provider 契约异常遵守项目 fail-open 要求；仅已可靠识别的契约不一致或重复消费等协作违规按现有门禁拒绝。不得把一次存储异常伪装成违规，也不得把 fail-open 报为 durable claim。
- 写入报告失败但回读证明相同调用已 claim 时，保留现有精确恢复；无法确认时不伪造状态。原生调用已放行或结果未知后不自动再次 spawn。

fail-open 后账本可能仍为 prepared：原生成功仍只能 confirm 并因缺少 claim 进入 reconcile；原生明确未创建或结果未知时，允许父 Agent 对精确 prepared/claimed task/ref 记录 failed/unknown，分别关闭或进入 `dispatch_result_unknown` reconcile，不绑定 target。该结果入口不接受 bound/terminal/closed，不把放行误作创建成功。

不恢复 PostToolUse receipt、临时 runtime probe 或跨 Session 扫描。真实 Hook 名称和字段不可获得时，报告该边界未验证。

## 5. 决策四：按操作语义修正生命周期，保留单生命周期范围

| 当前原生操作 | 父 Agent 的处理与治理含义 |
| --- | --- |
| `send_message` | 给已经绑定的子 Agent 补充信息；不唤醒闲置 Agent。机械受理不等于子 Agent 已执行。明确 success/failed 仍零写入；不确定投递记录 unknown，禁止自动重发 |
| `followup_task` | 原任务尚未进入治理终态且需要继续执行时，对同一 exact target 发起后续工作；闲置时可唤醒。只用于原范围内继续，不建立新身份或 attempt；受理不等于 running 或完成 |
| `wait_agent` | 等待邮箱通知；正常超时、用户输入打断、邮箱更新摘要均不构成某个 Agent 的终态。不把摘要直接提交为 platform observation |
| `list_agents` | 仅在超时巡检或新异常证据需要对账时，查找已绑定的 exact target；不补绑身份，不反复轮询。列表字段需以实际返回验证后才能规范化 |
| terminal notification | 必须来自可归属已绑定 exact sender 的平台终态信号；普通消息中声称完成不自动等同平台终态。业务证据由父 Agent 验收，正文不写账本 |
| `interrupt_agent` | 请求中断当前执行；返回的 previous status 不能证明操作后 inactive。没有后续明确机械证据时记录 unknown，不能因为工具调用成功就写 stopped |
| `close-task` | 父 Agent 完成验收或明确停止跟踪后关闭账本。当前面不调用不存在的 `close_agent`，不声称释放并发槽或销毁 Agent |

等待以终态通知为主，不用业务文件、日志和测试猜测状态。单次阻塞等待不超过当前上层沟通约束允许的 60 秒；正常超时继续等待，达到预先说明的巡检间隔才做一次 exact-target 状态检查，不建立自动重派循环。

已有 [减法 ADR](../architecture-reduction-adr.md) 明确排除 managed business resume。本轮据此不增加 `terminal/closed/reconcile → bound`：尚未终结的 bound Agent 可以接收消息和原范围内 followup；一旦取得明确 completed/stopped/interrupted 终态或中断 inactive 事实，沿用 terminal 收口。仅有“闲置”信息不自动归类 completed，但实际返回 completed 时也不得为唤醒而忽略该事实。

这是有意保留的能力限制：同一 Agent 终态后的返工或中断后的受管恢复尚不支持。该功能需要解决迟到终态与新执行轮次的关联，不能靠清除 terminal fact 实现；不纳入此次适配，也不因不支持而自动创建替代 Agent。若用户需要该能力，应单独修订 ADR。此前讨论中的“新增恢复转换”建议在本方案中收窄为上述范围。

其他运行面只使用该任务实际暴露且语义已核对的操作；不因选择 `fork_context` 派发适配器，就推定存在 `send_input`、旧式 wait 或关闭能力。

## 6. 实施范围与顺序

1. 冻结两种参数形态的独立测试 fixture，注明来源日期、证据等级和未知项；先复现当前非法字段、缺失必填字段、完整继承覆盖冲突。fixture 不从待测渲染器生成。
2. 实现纯适配模块、CLI 显式选择、v10 状态及 Schema；同步 prepare、claim 和异常回读。沿用现有身份及存储 primitives。
3. 调整 Hook 精确名称与失败分类，验证 fail-open 不虚构 claim。新增模块加入 runtime bundle allowlist；不改部署事务实现。
4. 修正 Skill、runtime boundaries、architecture 及中英文 README 的相关承诺；保留历史报告，新增本轮验证记录。生命周期仅做本方案需要的操作说明和必要校验，不重写状态机。
5. 完成本地门禁后交付候选与证据；发布、部署、真实测试各按用户授权执行。

预计涉及：`governance_native_adapter.py`（新增）、contracts、rendering、protocol、dispatch、hook、cli、state、semantics、diagnostics、canonical Schema、Hook 配置、bundle allowlist、Skill/references、相关测试和架构说明。lifecycle 代码仅在测试证明当前校验无法表达上述边界时作最小调整。

## 7. 验收与停止条件

### 本地验收

| 测试组 | 必须证明 |
| --- | --- |
| 参数合法性 | 两接口均无多余/缺失字段；none/all/有限轮数、非法字符串、覆盖冲突和省略参数符合各自契约 |
| 冻结与身份 | 切换适配器、篡改 task name/message/config、重用 capability 被发现；同调用 claim 与 exact confirm 幂等；不能用列表或名称补绑 |
| 异常恢复 | prepare 写后错误回读使用相同语义；claim 写后错误只接受精确同调用事实；不因错误重复派发 |
| Hook | matcher/router 一致；明文完整校验；opaque/未知形态不 claim；unmanaged 零写入；内部故障放行且诊断不夸大 |
| 生命周期 | 邮箱唤醒不记终态；previous status 不记 inactive；消息受理不记完成；followup 不重开 terminal；close 不声称资源释放 |
| 状态与打包 | v10 validator/Schema 一致；旧 namespace 不触碰；只读操作零写入；新适配模块包含在运行包中 |

实施后运行项目要求的门禁：

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
git diff --check
```

测试使用临时隔离存储，不调用本任务真实治理 CLI 写状态。通过本地测试只说明实现符合已冻结契约，不说明宿主真实投递、opaque 转换或平台执行已验证。

### 经授权后的真实验收

- 部署只能经现有事务入口，在事务内完成写入、失败回滚和最终哈希验证；无论成功失败，命令结束后立即报告并停止，等待重启。
- 用户确认重启后，在开发任务之外新建独立测试任务，显式使用 `gpt-5.6-terra`、推理 `high`；用户明确另选配置才覆盖。无法确认实际配置则记为未验证。
- 新任务先核对实际工具契约和安装版本，再使用自己的 Hook 权威 exact session 与 CLI entrypoint；不复用方案中的来源任务身份。
- 按顺序验证 unmanaged 零状态、governed prepare/claim/confirm、wait/终态、消息、bound 范围内 followup、中断与账本关闭，以及同 exact Session 的恢复。首个 claim/bind 边界失败后停止后续受管场景，不手工制造 claim 或重派补测。
- 分别报告每个运行面：本地契约通过、真实主链通过、平台结果 unknown 或未验证。只在实际暴露对应接口的任务中验收它，不以一个面的成功代表另一个面。
- 稳定发布源与运行缓存一致性在未获部署授权时标记未验证；终态后恢复和资源释放明确为本轮非能力。

### 本方案文档验证

本轮仅检查 `git diff --check`、本地 Markdown 链接、章节与决策完整性以及改动范围；不运行全量运行时测试，不把上述计划中的门禁写成已执行结果。
