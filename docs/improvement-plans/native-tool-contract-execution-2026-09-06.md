# 原生工具契约适配：执行清单

- 状态：E1–E4 已在开发仓库完成；本地门禁通过，待集中审查；未部署或真实验证。
- 设计依据：[修复方案](native-tool-contract-adaptation-2026-09-06.md)。先读项目 [AGENTS.md](../../AGENTS.md)。
- 基线：`d570e527b247ed41642d604a8937e800399b3f38`；后续实现开始时核对实际 HEAD 和工作树差异，保留用户修改。
- 分工：建议 `gpt-5.6-terra / high` 负责一个串行实现任务，`gpt-6-astra / high` 对最终候选集中审查。出现停止条件才提前审查，不为每一步创建新任务。
- 本轮实施授权已完成；仍不包含部署、真实派发或清理旧状态。实际执行结果见配套[实施验收记录](../validation/native-tool-contract-adaptation-implementation-2026-09-06.md)。

## 1. 两项范围复核

| 选择 | 结论与原因 | 明确代价 |
| --- | --- | --- |
| 两种派发参数形态 | 保留 `collaboration_turns` 与 `fork_context` 两个固定分支。仓库刚从前者切向后者，本次发现反向不兼容；再次全局替换会重复该问题。只复用当前代码中的布尔映射，不建设通用 provider 框架 | 两组独立 fixture 和组合校验；未真实验收的运行面必须标注未验证 |
| 冻结接口选择 | 不从输入字段或工具名称反推，因为它们正是需要检查的内容。显式选择保存在 task，claim、异常回读与恢复使用同一值 | CLI 增加一个 prepare 专用参数；task 增加一个必填字段 |
| `state-v10` | 保留。v9 每个 phase 使用关闭字段集合；增加必填字段后继续读取 v9 需要默认推断或迁移，与 current-only 原则冲突 | 新版不恢复 v9 未闭环账本；旧数据原地保留，部署交接明确说明 |
| 终态后再次执行 | 不纳入；保留 ADR 的单生命周期范围，避免迟到通知归属和多轮执行账本 | 不承诺终态返工、受管中断恢复或释放 Agent 资源 |

`state-v10` 是上述冻结方案的结果，不是适配任意新工具都必须升级状态版本。若未来取消持久接口选择，应重新评估，执行者不得自行退回 v9 或添加兼容读取。

## 2. 固定接口与样例

新增纯模块 `scripts/governance_native_adapter.py`，不导入 Hook、CLI、StateStore 或业务契约模块。输入为现有语义字典，避免循环依赖；只允许依赖 canonical semantics、纯身份解析及错误类型。

```python
def validate_native_spawn(native_interface: str, spawn: dict[str, Any]) -> None: ...
def render_native_spawn(native_interface: str, expected: dict[str, Any]) -> dict[str, Any]: ...
def normalize_native_spawn(native_interface: str, tool_input: Any) -> dict[str, Any]: ...
```

职责固定如下：

- `validate_native_spawn`：验证接口枚举和该接口的继承/覆盖组合；prepare 在创建存储或进入 update 前执行。无效请求沿用 ValueError → DispatchPreparationError 边界。
- `render_native_spawn`：接受 `expected_native_parameters` 既有五字段，输出当前接口参数；覆盖为 null 时省略字段，绝不输出两个上下文字段。
- `normalize_native_spawn`：仅接受可验证的完整输入，返回五字段语义字典，model/effort 省略时转 null。不可验证输入抛 `NativeInputUnavailable`；明确的已知字段违规抛 `NativeInputMismatch`。两种异常放在 `governance_errors.py`，不依靠错误字符串分类。
- `_normalized_tool_input` 删除旧布尔实现，改为委托或删除该内部包装；正常 claim 和精确写后回读都调用相同归一化逻辑。
- `expected_native_parameters` 继续由 rendering 模块根据 contract 生成。`spawn_args` 改为带必填 keyword-only `native_interface`，调用纯适配器；不默认任何分支。
- `prepare_dispatch` 和 `initial_task_record` 增加必填 keyword-only `native_interface`。claim 从已锁定 task 读取接口，不让调用方再传一个可覆盖值。
- CLI `--native-interface` 仅配合 `--prepare-dispatch`；缺失、未知值、或用于其他操作均在存储构造前失败。lifecycle/confirm/status 输入结构不增加该字段。

可手工编写的固定样例（名称只用于 fixture，不用于真实 Agent 身份）：

```json
{
  "task_name": "sg_standard_check_t_aaaaaaaaaaaa",
  "message": "[subagent-governance:sg_standard_check_t_aaaaaaaaaaaa]\n检查契约",
  "fork_turns": "none",
  "model": null,
  "reasoning_effort": null
}
```

`collaboration_turns` 输出精确为样例中的 task_name/message/fork_turns 三字段；`fork_context` 输出精确为同一 message 加 `"fork_context": false`。有限继承 `"3"` 只允许前者，按原值传递；布尔接口拒绝，不能悄悄改成 all。

语法固定为 `^(?:none|all|[1-9][0-9]{0,11})$`，沿用现有 12 字符长度边界；这是插件输入界限。拒绝 `0`、`01`、`+1`、负数、小数、空白、数字类型和布尔值。canonical Schema 定义语法，runtime 从同一语义源读取。`fork_context` 的 false/true 分别还原 none/all，拒绝字符串和数值布尔替代品。

`collaboration_turns` 缺少 fork_turns 时规范化为 all，符合本任务工具默认值；因此与默认隔离 none 的 capability 不相等，必须拒绝。旧布尔面缺少 fork_context 沿用已有 false 默认。原生可选覆盖字段显式 null 不视为省略：两种已知 Schema 都只声明字符串，Hook 中这种形态按不可验证输入处理。

`collaboration_turns` 的 all 加任一非 null 覆盖在 prepare 前拒绝；布尔面保留已有 all 加显式覆盖能力，不把当前 collaboration 的限制推广过去。每次派发仍需检查该任务的实际说明；与已记录布尔规则冲突时停止该面的派发，不现场改适配器。

## 3. 状态与恢复修改点

新增字段只有 `task.native_interface`，值为上述两种枚举；六个 phase 均必填。prepared capability 五个既有字段不变；expected 五字段语义不变。新版本号/namespace 只由 canonical semantics 定义，diagnostics 等消费者读取常量，不再硬编码 9 或 10。

| 修改点 | 必须执行的动作 |
| --- | --- |
| canonical Schema | 增加 `$defs.native_interface`；六种 task 的 required/properties 引用它；版本常量与 namespace 更新；扩展 fork_turns 语法 |
| `governance_state.py` | `COMMON_FIELDS` 加字段并检查枚举；prepared 验证额外接受所属接口，校验 contract spawn 与接口组合；保留 digest、context 和 expected 的一致性检查 |
| `initial_task_record` | 写入一次接口；prepare 返回也包含接口，并展示到 user_message |
| `confirm_dispatch` / `record_dispatch_result` | 两处清空重建 task 的 common 字段集合加入接口；不只修改生命周期模块 |
| `governance_lifecycle.py` | `PRESERVED_FACT_FIELDS` 加接口，确保 close/reconcile 不丢失；其余转移语义保持原样 |
| `governance_diagnostics.py` / SessionStart | 输出接口，版本读常量；缺失账本仍零写入；摘要继续使用既有长度上限 |
| prepare 异常回读 | 比较 exact task_id/ref、business digest、接口及完整语义参数；语义通过同一适配器规范化返回的 spawn_args 得到，不再手写 fork_context 判断 |
| dispatch 结果入口 | prepared/claimed 接受 exact task/ref 的 failed/unknown；failed 仅代表父方明确报告未创建；unknown 转 reconcile；成功仍只走 confirm |

不把接口塞入 task_id/task_ref 或 business digest；接口字段独立校验。既有 spawn digest 仍校验模型/继承配置。validator 无法识别出“两个接口都允许的配置被整体篡改”为原始接口，这与现有父方协作账本的信任边界一致，不宣称防任意磁盘篡改。

更新测试 fixture 的当前版本值；旧 v9 数据作为“不得访问”fixture 保留。测试文件 `test_v9_dispatch_chain.py`、`test_v9_lifecycle.py` 可继续使用原文件名以减少移动，类和说明更新当前含义；不要把历史报告全局替换成 v10。

## 4. Hook 判定表与错误所有权

精确名称集合为 `spawn_agent`、`multi_agent_v1.spawn_agent`、`multi_agent_v1__spawn_agent`、`multi_agent_v1spawn_agent`、`collaboration.spawn_agent`、`collaborationspawn_agent`。不增加其他猜测别名。把集合放在 canonical semantics，router 读取，测试验证静态 matcher 与该集合一致。

处理顺序：名称与可见 governed 标记 → 精确 session/call → 读取并验证 ledger → 选冻结接口 → 输入归一化 → 原子 claim。未知工具、完全无治理标记的输入在构造 StateStore 前返回。显式有效 governed task_name 可定位 ref，即使 message 不可见，也不得凭此跳过正文验证。

| 情况 | Hook 输出 | ledger 与后续 |
| --- | --- | --- |
| 未知工具或无治理标记 | 透传，不加治理成功声明 | 不读写账本 |
| 可见治理字段互相矛盾、可见明文标记格式损坏 | deny，报告明确字段违规 | 不 claim |
| 缺少可用 session_id/tool_use_id，或输入形态无法解析 | allow + 有界不可验证诊断 | 不 claim；不猜身份 |
| 已明确识别 task，但有新字段、缺原生必填字段、message 缺失/非字符串/null 覆盖 | allow + `NativeInputUnavailable` 诊断 | 不 claim；未知 provider 形态不能当作已验证违规 |
| message 没有可辨认的治理明文首行，但显式 governed task_name 可见 | allow + 正文不可验证诊断 | 不 claim；不区分猜测的 ciphertext 与普通文本 |
| 明文首行可识别，名称、正文或已知合法参数与 capability 不相等 | deny，`NativeInputMismatch` | 不 claim；不能以“可能 opaque”为由放过明确可比的不一致 |
| 已知字段非法值，例如非布尔 fork_context、非法轮数字符串 | deny，`NativeInputMismatch` | 不 claim |
| 账本有效但 ref 不存在、已过期、被另一调用消费，或 phase 不允许 claim | deny，明确 `StateConflictError` | 保持原始事实；不以 new prepare 自动重派 |
| 声明材料可读取且精确验证结果变化 | deny，明确材料冲突 | 不 claim |
| 材料不可读取、账本损坏、锁/磁盘/权限/内部实现异常 | allow + 有界内部故障诊断 | 不声称 claim；已发生写入不得伪装回滚 |
| 原子 claim 成功，或写后报错但精确回读证明同调用已提交 | allow + claimed 声明 | 同调用幂等；不同调用不能消费 |

不依据“非空字符串”识别 opaque。无可辨认明文标记时，只能说不可验证。纯输入不可验证不允许写一个错误的成功 claim。

异常分类必须在事实产生处完成：`claim_spawn` 保留业务 `StateConflictError`；存储 `StateValidationError/StateWriteError/StateCapacityError` 等归为治理故障；材料 I/O 与可读取但摘要变化分别处理，不用 `except Exception: deny` 兜底。`governance_cli._hook` 的最外层异常也改为 fail-open，避免内层已分类而外层重新误拒绝。不能将所有 StateStoreError 一律当作冲突，因为 StateConflictError 也是其子类。

Hook 只检查，不改原生输入：成功与降级输出均省略 `updatedInput`。诊断仅包含操作、有限 reason code 和可用 task ref，不输出 message、契约正文、文件内容或原始异常中可能携带的敏感值；不增加日志存储。confirm 缺 claim 仍保留现有 `dispatch_claim_missing` 行为。

## 5. 四步串行实施与测试清单

每步先添加能证明所改行为的测试，再实现并运行该步测试。步骤间不要求新建任务、重新设计或重复征求已获实施授权。出现停止条件时保留修改并报告。

### E1：参数适配器

- 文件：新增 native adapter 与 `tests/test_native_adapter.py`；修改 contracts、semantics、errors、canonical Schema；fixture 可放在该测试模块，保持手写独立数据。
- 测试：两接口默认/完整继承；turns 的有限继承和省略默认；布尔面的显式覆盖；非法轮数/布尔/null；all 覆盖冲突；未知字段不可验证；明文不一致与不可验证正文分流；输入字典不被修改。
- 检查：`python3 -m unittest tests.test_native_adapter -v`。
- 完成条件：纯函数接口可用；fixture 不调用渲染器生成“预期答案”；无运行状态写入。此步期间旧集成测试可能尚未接入新接口，不宣称全仓通过。

### E2：v10 与派发链

- 文件：rendering、protocol、dispatch、cli、state、lifecycle 的字段保留点、diagnostics；相关现有 dispatch/lifecycle/state/schema 测试。
- 测试：CLI 缺少/错误/误用于其他操作的接口参数零状态失败；两接口 prepare → claim → confirm；全六 phase 保留接口；expected 与 contract 校验；同调用幂等、另一调用拒绝；prepared 的 failed/unknown 收口；缺 claim 的 success 不绑定；v9 隔离；完整 prepare 写后回读故障注入。
- 测试：两种适配器各覆盖相同精确调用的 claim 写后失败回读；task/ref/接口/message/config 任一不等时不能报告精确恢复。不得通过回读业务目标相同就误认同一个 task。
- 检查：`python3 -m unittest tests.test_v9_dispatch_chain tests.test_v9_lifecycle tests.test_state_store tests.test_state_store_modules tests.test_semantic_baseline -v`。
- 完成条件：业务契约仍为 v2，只有 v10 namespace 被读写；完整继承的合法性由所选接口判断；prepare 正常与异常路径使用相同语义。

### E3：Hook 接入与故障边界

- 文件：hook、cli Hook 外层、identity 的标记识别辅助函数（仅在需要时）、errors、Hook manifest；dispatch 中精确区分冲突与内部故障的部分；对应 Hook/dispatch/结构测试。
- 逐行覆盖第 4 节判定表；验证输出、账本前后字节和是否构造/读取存储。可恢复写后故障验证保留真实 claim，不把所有异常都期待零写入。
- 检查：`python3 -m unittest tests.test_v9_dispatch_chain tests.test_hook_event_contract tests.test_plugin_structure -v`。
- 完成条件：已知名称匹配，第三方近似名称透传；内部故障不禁用原生通道，无法验证不虚构成功；未引入 Post Hook 或新事件日志。

### E4：Skill、打包和集中验收

- 文件：Skill、runtime boundaries、architecture、中英文 README、bundle allowlist、相关当前版本说明及本轮新验收记录。历史 ADR/报告只增加必要的当前文档链接或状态说明，不覆写历史事实。
- Skill 写出显式接口选择、工具语义、权威 session/entrypoint、终态后不可恢复边界；描述中纳入 followup_task，禁止推定旧通信工具可用。
- 不新增 lifecycle 原生工具返回解析器：当前 ledger 接收父方规范化事实，机械返回未实测部分在真实验收记录中保留 unknown。用既有领域测试验证规范化后的 bound/terminal/reconcile 规则；不以字符串包含断言假装验证真实等待或投递。
- bundle 加入新模块，继续不打包 tests/plans/validation。完成修复方案列出的全量 unittest、compileall、plugin validator、Skill validator、diff 检查；此前步骤已通过的检查不单独重复。
- 完成条件：全部本地门禁通过，最终差异仅涉及方案范围，提交一份按测试组列出实际结果与剩余未知项的记录。未授权部署时不检查或改写运行缓存来补齐验收。

## 6. 停止条件与交付格式

以下情况报告精确证据并返回设计讨论，不自行变更产品承诺：

1. HEAD 已改变且相关模块有影响契约的新实现；仅无关差异不构成停止理由。
2. 实施任务实际工具契约不匹配任一已记录形态；继续可独立完成的纯函数/fixture 工作，不用它试派发。
3. 需要接受不可见正文为已验证、从列表推断身份、恢复 terminal 或引入多 attempt 才能满足新增要求。
4. 某异常无法判断是可靠冲突还是内部故障；先按不可验证保守处理并报告，不能只为让测试通过而 hard deny 或声称 claim。
5. 测试出现与修改无关的基线失败：给出证据，保留相关检查结果，不擅自重构无关模块。

最终实现交付必须包含：实际基线与候选标识、改动摘要、E1–E4 完成情况、测试命令和结果、仍未验证的原生/Hook 行为、未部署声明、旧账本不恢复及终态后恢复限制。测试通过不等于真实插件验收完成。

集中审查重点为：适配器是否冻结；六 phase 是否保留字段；写后错误是否会重复创建；Hook 失败分类是否误阻断或虚构成功；两种接口规则是否互相污染；生命周期文案是否承诺了不可用能力。审查独立读取最终差异和测试证据，不只认可实现者的总结。

## 7. 后续实现任务交接文本

以下是后续明确授权实施时使用的模板，本轮不发送。当前插件本身存在派发不匹配，不用它创建受管子 Agent 来实施自身修复；可由用户切换模型或明确要求建立普通 Codex 实现任务。新任务若拿不到这两份尚未提交文档，应先把文档作为完整材料交接或冻结到可读取提交，不能仅凭基线提交声称已包含方案。

```text
请在 subagent-governance 开发仓库实施：
docs/improvement-plans/native-tool-contract-adaptation-2026-09-06.md
docs/improvement-plans/native-tool-contract-execution-2026-09-06.md

模型 gpt-5.6-terra，推理 high。先读取 AGENTS.md 和以上两份文件，核对
实际 HEAD 与原设计基线 d570e527b247ed41642d604a8937e800399b3f38 的差异。
保留用户修改，按 E1–E4 串行实施，以独立 fixture 和实际测试结果验收。
本任务授权范围为开发仓库实现、相关测试和验证记录，不部署、不真实派发、
不清理治理状态，不修改稳定源、安装缓存、Hook trust、Marketplace 或 Registry。
不要派发子 Agent。遇到执行清单停止条件时报告证据和未完成项。
完成后按清单交付候选与测试证据，留给 gpt-6-astra / high 集中审查。
```

真实测试继续遵守主方案的另行授权、部署事务结束即停、重启后独立任务要求；该实现模板不是部署或真实测试授权。
