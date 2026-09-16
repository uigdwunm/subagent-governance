# 原生接口与运行环境兼容矩阵

核对日期：2026-09-16；开发基线 `e7bb27e`，state-v12 / TaskContract v2。
这是能力与证据矩阵，不是客户端全面兼容声明。模型名称不决定接口适配器。

## 证据层级与维护

| 标识 | 来源 | 能证明什么 |
| --- | --- | --- |
| S | 本次开发会话公开 `collaboration.spawn_agent` schema，2026-09-16 | 本环境声明的参数和约束；精确客户端版本未取得 |
| O | [官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)，2026-09-16 实际读取 | 文档声明的事件、字段、输出及信任规则；不证明当前投递 |
| L | [adapter 测试](../tests/test_native_adapter.py)、[兼容案例](../tests/test_native_compatibility.py)、[Hook 测试](../tests/test_hook_event_contract.py)、[故障测试](../tests/test_hook_failures.py)、[dispatch 测试](../tests/test_v10_dispatch_chain.py) | 本地实现行为；不是原生工具实际执行 |
| H | [历史真实验收](validation/current-only-real-platform-validation.md) | 仅对应记录中的 state-v9、版本、环境和具体结果 |
| P | state-v12 重启后独立真实测试 | 未执行；不得用 S/O/L/H 替代 |

更新时逐项记录接口、客户端版本（无法取得则标 unknown）、系统/Python、插件提交或 digest、来源日期、具体测试及结果。接口声明变化、Hook 文档变化或真实失败触发复核；不靠修改核对日期升级证据。不将客户端版本、模型可用性、Hook 信任和实际执行合为一个支持标记。新增原生字段需先取得语义证据和独立 fixture，再决定是否扩展适配器。

## 参数与继承能力

| 项目 | collaboration_turns | fork_context | 证据 |
| --- | --- | --- | --- |
| 必填 | task_name、message：string | message：string；本地支持子集 | S/L；后者历史 [接口记录](validation/native-context-adapter-2026-09-06.md)/L |
| 可省略 | fork_turns、model、reasoning_effort | fork_context、model、reasoning_effort | S/L；后者历史/L |
| 省略继承字段 | all | false → none | S/L；后者历史/L |
| 显式继承 | none / all / 正整数字符串；本地限定 1–12 ASCII 数字、不以 0 开头 | false → none，true → all；拒绝有限轮数 | S/L；后者 L |
| 继承字段 null 或错误类型 | native_conflict | native_conflict | L |
| model/effort | 可选 string；all 禁止覆盖；组合可用性查当次工具说明 | 可选 string；本地允许 all 时覆盖，当前平台未核实 | S/L；后者历史/L |
| model/effort 显式 null | input_unavailable；省略则内部归一化 null | 相同 | L |
| model/effort 错误类型或不同值 | 不等于冻结值时 claim_conflict；normalize 本身不单独做类型校验 | 相同 | L |
| 可见治理标记 | 生成的 task_name；消息标记存在时必须一致 | 首行消息标记定位 task ref | L；H 仅历史环境 |
| 消息正文 | string；不证明非空或明文完整性；claim 不比较正文 | string；无标记不识别为 governed | L |
| 未知字段／混合接口／structured items | input_unavailable，不宣称等价支持 | 相同；缺少任何可识别身份时 unmanaged 透传 | L |

TaskContract 准备层省略继承时默认 **none**，与原生默认值分开。render 显式发出继承字段、省略内部 null 的 model/effort。冻结 native_interface 不随工具名称猜测切换；claim 比较 task_name、fork_turns、model、reasoning_effort。消息正文改写不构成内容完整性验证。

支持的精确工具拼写为 `spawn_agent`、`multi_agent_v1.spawn_agent`、`multi_agent_v1__spawn_agent`、`multi_agent_v1spawn_agent`、`collaboration.spawn_agent`、`collaborationspawn_agent`（L；部分有 H）。官方 `Agent` matcher 别名不是本项目 router 新增输入名的证据，不新增别名；未知工具/事件静默透传。

## Hook envelope 与输出

O 描述共同字段 session_id、cwd、hook_event_name、model（string），transcript_path（string/null）；PreToolUse 增加 turn_id、tool_name、tool_use_id、tool_input（JSON value）和 permission_mode。SessionStart 使用 source 和 permission_mode。

这些是文档描述，不是插件全字段准入要求：runtime 仅路由 PreToolUse/SessionStart，识别 governed 后要求非空字符串 session_id/call ID 及可验证原生输入。cwd/model/turn_id 等不会成为身份替代物。顶层扩展忽略，tool_input 扩展不可验证；二者不可混淆。

PreToolUse 正常输出为 hookSpecificOutput 的 allow/deny 和安全诊断；外层异常或无法解析输入仅输出 systemMessage，exit 0。PreToolUse 不支持顶层 continue；此输出修正保持 D 的 fail-open 意图。历史 [事件 fixture](../schemas/codex-hook-events-v1.contract.json) 保留原 checked_date，新增只覆盖已注册事件的核对记录；未启用事件不转为 runtime authority。

| 场景 | 动作／claim 证据 | 来源 |
| --- | --- | --- |
| unmanaged、未知工具/事件 | 静默透传，无治理声明 | L |
| 身份字段缺失、输入识别失败 | allow / not_attempted | L |
| 已识别治理输入的未知字段、model/effort null | allow / unconfirmed | L |
| 标记冲突 | deny / not_attempted | L |
| 已知原生形状或冻结值冲突 | deny / unconfirmed | L |
| 已消费 capability + 未知字段 | 保留已确认冲突的拒绝优先级 | L |
| 提交报错 | 仅同一 claim 精确回读成功才 confirmed；否则 unknown | L |
| 外层解析失败／异常 | 安全 systemMessage / not_attempted 或 unknown | O/L |

完整动作与诊断以 [D 故障契约](../skills/subagent-governance/references/runtime-boundaries.md#hook-故障分类与证据契约) 为准。Hook 决策、claim、原生执行、业务验收分别记录；输出测试不证明平台收到或遵从。

## 环境与真实回执

| 环境／能力 | 证据与状态 |
| --- | --- |
| 当前桌面会话 collaboration schema | S；精确客户端版本 unknown；未在本任务真实派发 |
| fork_context 客户端 | 历史接口记录和 L；当前可用客户端及真实投递未验证 |
| macOS 本地 Python | 本次结果见 [E 验收](validation/native-compatibility-2026-09-16.md) |
| Linux/macOS/Windows × Python 3.11/3.12 | CI 已配置；本次未触发远端 CI，不记 passed |
| POSIX/Windows 锁、命令与缓存 | 本地代码/fixture 覆盖；Windows 实际锁和 commandWindows 未验证 |
| 当前安装、trust、Registry、运行缓存一致性 | 本次未验证；未安装或修改 |
| state-v9 历史真实链路 | H；V4/V5 的 unknown 不升级为投递或中断成功 |
| state-v12 Hook/native 链路 | P 未执行；临时 bundle 测试只算 L |

官方文档要求信任当前 Hook 定义，installed/enabled 不等于 trusted；部分工具路径可能跳过 Hook。当前工具声明只说明 spawn 返回 agent ID 或 canonical task name 的使用约定，不证明某次返回。插件不新增回执解析器：父任务只取本次返回的 exact target 显式 confirm。wait、消息、中断和 terminal 仍按现有 exact-target 事实契约处理，缺少确定回执保持 unknown。

## 派发前、运行时与 F 交接

派发前可核对当次 schema、接口选择、字段类型、默认值、继承限制及声明的模型组合；prepare/render 可核对本地契约。可取得的只读 trust/版本证据单列，缺失不伪造。

只有 Hook 执行时才能发现实际工具名、可见标记、call ID、输入改写、材料漂移和 claim 写入结果。Hook 未执行或输出未送达时，预检不能保证治理提示或拒绝生效；缺 claim 的 confirm 仍 reconcile，不推断失败原因、不自动重派。

F 可使用本矩阵和本地验收确定可测条件；真实效果评测前仍需独立授权部署、重启和新任务，父任务与子 Agent 均显式 gpt-6-astra/high 并分别核实。无法核实配置标未验证。E 不开展返工成本对照、不声称业务质量改善，不增加 PostToolUse authority、状态格式、诊断存储或新的执行通道。
