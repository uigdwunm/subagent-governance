# WP-08 旧路径退役与发布准备验证详细方案

> 2026-08-14 状态：本文保留为历史退役计划。其 managed SubagentStop
> `task_result` 规则已被平台能力切片 1 supersede，不能作为当前 runtime、
> Skill 或发布保证。

## 一、状态、唯一目标与授权边界

- 阶段：WP-08，WP-01～WP-07 之后的最终本地收口阶段。
- 唯一目标：在新主路径已有真实消费者和测试的前提下，原子删除已确认退役的旧运行时、混合状态、自由文本正式结果、薄桥、过时 fixture/断言和当前文档残留，并形成可审计的本地发布准备证据。
- 产品裁决唯一来源：`docs/project-function-inventory.md`，尤其 U-01～U-10、第十三节 OR-01～OR-16、第十五至十九节。
- 本阶段只修改开发仓库 `$HOME/workspace/subagent-governance`。
- 本阶段没有发布、安装或外部写入授权：不写 `~/plugins/subagent-governance`、Marketplace、运行缓存、Hook trust、Registry 或全局 `AGENTS.md`，不创建符号链接，不 stage、commit、push。
- 外部安装现状只允许通过确认无写入的读取命令检查；不足以证明真实发布或真实平台行为时记录 `not_checked`，不请求扩大授权。

## 二、修改前基线与成功标准

### 2.1 已确认基线

修改前执行：

```text
python3 -m unittest discover -s tests -v
Ran 273 tests
OK
```

该基线证明 WP-01～WP-07 新主路径和旧兼容测试同时存在，不证明旧路径应继续保留。

### 2.2 WP-08 成功标准

1. 运行时不再定义或消费旧混合状态集合、旧任务 `status` 生命周期、混合 `retry_count`、legacy `platform_status/platform_error/interrupt_tool_use_id/protocol_errors/result_document`。
2. managed `SubagentStop` 只消费显式 `task_result`；unmanaged/未映射 Stop 原样放行；已有映射但记录不是当前 managed 形状时只告警并 fail-open，不执行旧状态机。
3. PostToolUse、SubagentStart、Stop、SessionStart/End、诊断只处理当前多维状态或 unmanaged 边界，不再更新旧记录。
4. `_active_records()`、`_recent_records()`、`_managed_action_required_records()`、`_session_end_preserved_records()`、`_legacy_action_required()` 及其专属断言全部删除；权威消费者直接使用 `_action_required_records()` 和 `_recent_activity_records()`。
5. 旧自由文本终态辅助、旧 fixture helper 和只证明已删除设计的 fixture/测试删除；保留并改名仍证明“opaque 正文不影响精确 task_ref”的当前 fixture。
6. README、开发 Skill、runtime boundaries、release process、主盘点和 optimization plan 描述最终当前实现，不再把 WP-08 或 legacy 接管写成未来工作。
7. 当前 `rg --files` 的每个有效文件在主盘点覆盖表中有保留功能归属；没有无消费者、仅证明已删除设计或重复空转的文件。
8. 定向、全量、编译、Plugin/Skill validator、Schema/fixture/语义锚点、发布工具、diff、覆盖表和旧术语消费者检查全部通过。
9. 真实平台矩阵逐项记录 `passed|failed|not_checked`；本任务不得用旧缓存或 fixture 冒充真实目标版本验收。
10. 最终结论明确区分“开发仓库本地改造完成”和“稳定发布已验收”。没有真实加载与 Hook trust 等证据时，稳定发布仍为未验收。

## 三、旧符号、分支、fixture、测试与当前消费者清单

### 3.1 旧混合状态与专属字段

| 旧目标 | 修改前消费者 | 新消费者/替代事实 | 处理 |
| --- | --- | --- | --- |
| `ACTIVE_STATUSES` | legacy SubagentStart、legacy Stop、legacy action/recent/active | `execution_status`、`spawn_observation`、`identity_status`、`parent_action` | 删除 |
| `INTERRUPTIBLE_STATUSES` | 未认领 interrupt 的 legacy PostToolUse | `pending_action` + `_apply_action_observation()` | 删除 |
| `TERMINAL_STATUSES` | legacy SubagentStop | TaskResult + `attempt_closed`/tombstone | 删除 |
| `RESOLVABLE_STATUSES` | `_resolve_task_id()` legacy 映射 | 精确 `{task_id,attempt}` managed 映射 | 删除 |
| `STOP_BLOCKING_STATUSES` | legacy Stop | `_managed_stop_blocking()` | 删除 |
| `SESSION_RESTORABLE_STATUSES` / `SESSION_END_PRESERVED_STATUSES` | 无运行消费者 | `_action_required_records()` | 删除 |
| `LEGACY_AUTOMATIC_RECOVERY_LIMIT` | legacy 单测 | `RETRY_LIMITS["recovery"]` 与 current lifecycle | 删除 |
| `status=pending/dispatched/running/retry_required/platform_error/protocol_error` | legacy task 分支和旧测试 | 当前独立状态维度 | 删除旧任务生命周期消费；保留原生响应和 CLI 中普通 `status` |
| `retry_count` | legacy free-text纠正 | `spawn_retry_count/recovery_count/correction_count` | 删除 |
| `platform_status/platform_error` | legacy list-agents | `platform_observation` + 有界摘要 | 删除 |
| `interrupt_tool_use_id` | legacy interrupt | `pending_action/last_lifecycle_operation` | 删除 |
| `protocol_errors/result_document` | legacy free-text Stop | 正式 result 文件 + `result_protocol_status` | 删除 |

### 3.2 自由文本终态

| 旧目标 | 修改前消费者 | 新消费者/替代事实 | 处理 |
| --- | --- | --- | --- |
| `_terminal_field()` | `_legacy_reported_status()` | `validate_task_result()` | 删除 |
| `_legacy_terminal_errors()` | legacy SubagentStop | `_record_managed_result_protocol_gap()` | 删除 |
| `_legacy_reported_status()` | legacy SubagentStop | `business_result` in TaskResult | 删除 |
| `last_assistant_message → result_document` | legacy mapped Stop | `submit_task_result()` | 删除 |
| `source=legacy_free_text` | 旧测试/状态 | 无 | 删除 |
| 空 `evidence/remaining`、600字符截断 | legacy result_document | 完整 result JSON | 删除 |
| strict卡/ACK/字符数/证据词/任务ID测试 | `tests/test_governance.py` | `tests/test_formal_result_parent_closure.py` 与语义基线 | 删除 |

保留：未映射 Agent 的 `SubagentStop` 直接放行；managed 映射的显式 `task_result` 提交、纠正次数、冲突和存储故障处理。

### 3.3 旧派发、正文和身份

- 当前代码已经没有正文 auto 分类词表、正文契约解析、正文改写、递归任意响应搜索、同名/同轮/唯一候选身份猜测或 Provider 文本特殊生命周期。
- `tests/test_dispatch_identity.py` 已覆盖旧 `sg_<mode>_<semantic_name>` governed 名称硬拒绝、opaque 正文不分类、有限响应适配器、unknown 深层响应、task_ref 精确身份绑定和唯一候选不绑定。
- WP-08 只删除残余 legacy 映射兼容：字符串 Agent→task、非 managed task 的启动状态写入和 `_resolve_task_id()` 对旧 `status` 的判断。
- 保留 `_call_failed()` 对原生工具响应中普通结构化 `isError/is_error/status/state` 的有限适配；它不解析错误文本或递归猜测。

### 3.4 旧诊断与会话薄桥

| 薄桥 | 当前事实 | 替代 |
| --- | --- | --- |
| `_active_records()` | 只剩定义 | `_recent_activity_records()` / `_action_required_records()` |
| `_recent_records()` | 只剩定义 | `_recent_activity_records()` |
| `_managed_action_required_records()` | 只剩定义 | `_action_required_records()` |
| `_session_restore_records()` | 只剩定义 | `_action_required_records()` |
| `_session_end_preserved_records()` | SessionEnd + legacy 单测 | SessionEnd 直接调用 `_action_required_records()` |
| `_legacy_action_required()` | legacy记录进入诊断/Session | 历史非 managed记录报告字段缺失/非法，不参与执行视图 |
| legacy active count/裸 StateStore | 旧测试目标 | WP-07规范化 snapshot |

### 3.5 fixture 与文件

- `provider-protocol-error-v1.json` 已在前阶段删除，禁止恢复。
- `opaque-spawn-v1.json` 仍证明当前边界，但历史命名含混；改名为 `exact-task-ref-opaque-message-v1.json`，断言只说明 opaque message 不影响 PreparedContract/task_ref 精确门禁。
- `agent-status-error-v1.json` 保留：证明已确认的 `list_agents` 结构化 `errored` 观察，而不是关键词特判。
- `recovery-limit-v1.json` 保留：证明 current 两次恢复上限和原生标识漂移，不再证明 legacy status。
- `lifecycle-v1.json`、`interrupt-v1.json` 保留：证明 current Hook matcher/身份/中断事件形状；若未使用的自由文本 Stop片段无断言则收缩。
- `tests/test_hook_fixtures.py:add_legacy_task` 无消费者，删除。
- 不删除 WP-01～WP-07 方案和 function inventory 过程档案；它们是历史决策证据。

### 3.6 过度设计目标残留

当前 Schema/运行时未实现 PreparedCommunication、PreparedResult双层、revision、随机 result/Aggregate ID、额外 execution/submission/communication/notification ID、事件审计、证据图、分页/游标/raw、DAG/batch/wave/租约/传播、child_agents权限、版本矩阵或 Provider特殊生命周期。WP-08 的责任是：

- 当前 README/Skill/runtime/release 文档只以“明确不提供”的边界提及必要否定项，不把它们写成未来目标。
- 主盘点与阶段方案可保留“已删除/停止实现”的历史证据。
- 发布流程不再要求状态迁移或协议版本兼容，只检查目标运行时当前操作所需字段。

## 四、删除前的新消费者证据

| 被退役职责 | 已接管实现 | 主要测试证据 |
| --- | --- | --- |
| 派发与身份 | `prepare_dispatch()`、PreparedContract、`_handle_spawn()`、`adapt_spawn_response()`、`_assign_starting_agent()` | `tests/test_dispatch_identity.py` |
| 显式通信/恢复/中断 | `prepare_communication()`、`prepare_interrupt()`、`pending_action`、`_apply_action_observation()` | `tests/test_communication_lifecycle.py` |
| 正式结果/纠正/父处置 | `submit_task_result()`、`read_task_result()`、`_record_managed_result_protocol_gap()`、`apply_parent_disposition()` | `tests/test_formal_result_parent_closure.py` |
| 等待/Stop/Session | `_action_required_records()`、`_recent_activity_records()`、`_managed_stop_blocking()`、SessionStart/End | `tests/test_wait_recovery_session_closure.py` |
| 只读诊断/group | `_build_diagnostic_document()`、`upsert_group()`、`read_group()` | `tests/test_minimal_diagnostics_lightweight_groups.py` |
| StateStore 安全/旧数据边界 | 显式必需字段读取、未知字段保留、无版本门禁、损坏保全 | `tests/test_state_store.py` |
| 发布/N/N-1 | `check_installation.py`、`reinstall_preserving_caches.py`、`apply_agents_block.py` | `tests/test_release_tools.py` |

删除只在上述正向测试仍通过的同一工作树中进行，避免功能空洞。

## 五、unmanaged 与历史旧数据兼容行为

1. 无 `sg_` 前缀的 spawn 原样 allow，不创建 task、PreparedContract 或 Agent映射。
2. 未映射的 communication/start/stop 不创建治理关联；Stop 不要求 TaskResult。
3. 以 `sg_` 开头但无合法 task_ref、PreparedContract 或匹配 StateStore 的 spawn 继续硬拒绝，不能降级为 unmanaged。
4. 精确 Agent映射存在且 record 为 `managed=true` 时，按当前字段逐项处理；缺少当前操作必需字段时明确报告并保持状态，不补默认值。
5. 精确映射存在但 record 不是 current managed 形状时，不再执行 legacy lifecycle：发出“历史/非managed映射不受当前结构化治理处理”的有界告警并放行原生事件。诊断会把缺失/非法 current字段报告为事实问题。
6. 未知额外字段保留/忽略，不因旧 version拒绝，不执行迁移，不把旧 `status` 转成当前多维事实。
7. 当前 managed record 的状态写入失败继续遵守各入口既有硬门禁或 fail-open边界；不得因为删除 legacy 路径放宽 governed spawn 或正式结果可靠性。

## 六、实施顺序与先失败证据

1. 新增 WP-08 定向退役测试，先断言运行时不再导出旧集合/函数、历史非managed映射不进入旧生命周期、SessionEnd直接消费权威视图、fixture新名称和当前文档无未来WP占位；在代码删除前稳定失败。
2. 保持 WP-03～WP-07 正向定向测试通过，作为新消费者已接管证据。
3. 删除常量和 PostToolUse legacy list/followup/interrupt分支；收紧 `_resolve_task_id()`、`_mapped_attempt()`、`_bind_identity_target()` 为精确 managed映射。
4. 删除 SubagentStart legacy状态写入；非managed历史映射只告警并按 unmanaged执行边界处理。
5. 删除自由文本 SubagentStop 全分支与辅助；managed和unmapped分流保持不变。
6. `_view_attempt_records()` 只投影 current managed attempt；历史旧记录不进入 action-required/recent/Stop/Session执行视图。诊断仍通过 skipped/required-field问题码报告可见损坏事实。
7. 删除薄桥，让 SessionEnd直接使用 `_action_required_records()`；更新摘要中的状态展示只读当前机械字段。
8. 删除/改写旧测试和fixture helper，改名 opaque fixture；不得删除 current有限响应、unknown、精确身份、恢复边界证据。
9. 更新当前文档、主盘点、optimization plan 和 release process。
10. 运行全套验证与只读外部检查；最后回填本文实施结果。

## 七、当前文件覆盖盘点方法

1. 使用 `rg --files` 和显式补充隐藏仓库文件（`.codex-plugin/plugin.json`、`.github/workflows/ci.yml`、`.gitignore`）生成当前清单。
2. 将连续 WP-01～WP-08 方案和五份 function inventory 作为可展开分组列入主盘点，但保证组内每个实际文件可由清单核对。
3. 运行 Python 脚本解析主盘点中的反引号路径/分组或使用确定性允许映射，与实际清单做集合差异；差异必须为空。
4. 对 Python运行时使用 AST 列出顶层函数/类，再按 SG-F01～SG-F08 和共享安全/CLI区段更新第十六节。
5. 对 fixture/test 使用 `rg` 反向确认消费者；无引用文件要么删除，要么说明直接CLI/发布证据归属。
6. 成功标准：每个有效文件至少有一个保留功能；没有只证明旧设计、无消费者或重复空转的文件。

## 八、本地发布工具、N/N-1 与只读外部检查

### 8.1 本地工具验证

- 运行 `tests/test_release_tools.py`，覆盖安装检查、最小入口应用、重装失败恢复、明确上一版本、N/N-1候选和不自动删除。
- 编译三个发布脚本。
- 不调用 `reinstall()` 的真实 Codex命令，不执行 `apply_agents_block.py --execute`，不运行 cachebuster，不复制稳定发布源。

### 8.2 只读外部现状

允许：

- `ls/stat/readlink` 检查开发仓库、稳定源和运行缓存是否同路径或符号链接。
- 读取稳定源 manifest 和缓存目录，计算只读 hash。
- 运行 `scripts/check_installation.py`，前提是代码审查确认该脚本只读。
- 读取 Codex当前安装/Hook状态的只读命令输出；若命令形状不确定或会触发写入则不运行。

禁止：

- `reinstall_preserving_caches.py` 主流程、`codex plugin add`、发布副本替换、Marketplace修改、全局规则 execute、Hook trust写入、缓存清理。

### 8.3 N/N-1结论边界

- 单测通过可证明包装器在模拟文件系统/命令结果下保护明确 N-1 并把 N-2作为 dry-run候选。
- 只读现状可证明当前稳定源/缓存的路径和 hash事实。
- 未执行真实整体回滚时，矩阵中的“N/N-1整体回滚”只能为 `not_checked`，不能写 passed。

## 九、真实平台验收矩阵（实施前占位）

| 项目 | 状态 | 证据/说明 |
| --- | --- | --- |
| 新版本真实加载 | not_checked | 本任务无安装授权 |
| 七类 Hook enabled/trusted | not_checked | 不用旧缓存状态替代目标版本验收 |
| light派发 | not_checked | 需目标版本真实任务 |
| standard派发 | not_checked | 同上 |
| strict派发 | not_checked | 同上 |
| auto派发 | not_checked | 同上 |
| normal send_message | not_checked | 同上 |
| list_agents errored→followup→SubagentStart与两次恢复上限 | not_checked | 本地fixture不替代真实平台 |
| interrupt | not_checked | 同上 |
| SubagentStop结构化结果保存与父读取 | not_checked | 需真实payload能力 |
| Stop、compact/resume、SessionEnd | not_checked | 需真实Hook时序 |
| 纯只读诊断 | not_checked | 本地只读测试与真实UI展示分开 |
| 轻量group一个失败、其他继续、父汇总 | not_checked | 需真实多任务链 |
| 活动任务字段预检 | not_checked | 需目标运行时实际活动记录 |
| N/N-1整体回滚 | not_checked | 本任务不执行发布/回滚 |

## 十、验证命令

```text
python3 -m unittest -v tests.test_wp08_legacy_retirement
python3 -m unittest -v tests.test_dispatch_identity tests.test_communication_lifecycle tests.test_formal_result_parent_closure tests.test_wait_recovery_session_closure tests.test_minimal_diagnostics_lightweight_groups
python3 -m unittest -v tests.test_release_tools
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
python3 -m py_compile scripts/apply_agents_block.py scripts/check_installation.py scripts/reinstall_preserving_caches.py
python3 $HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 $HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
标准库确定性检查：3 Schema、全部相对 $ref/JSON Pointer/regex、全部保留fixture、WP-08语义锚点
git diff --check
实际文件清单与主盘点覆盖一致性检查
旧符号/旧术语消费者检查（历史证据文档单独排除）
只读 scripts/check_installation.py 与路径/hash检查
```

## 十一、退出条件与发布判定

WP-08 本地退出必须同时满足：

1. 全部确认旧运行时、字段、分支、薄桥、测试和fixture已删除或切换。
2. 新主路径全部定向与全量测试通过。
3. 当前文档和主盘点收口，文件覆盖差异为空。
4. 本地发布工具、validator、Schema/fixture、编译与diff门禁通过。
5. 只读外部检查如实记录当前环境事实，不执行修复。
6. 真实平台矩阵每项有状态，未执行项保持 `not_checked`。

发布判定：

- “开发仓库本地改造完成”：上述本地退出条件满足即可成立。
- “稳定版可发布/发布验收完成”：只有目标版本真实加载、Hook trust、核心平台链路和回滚关键项实际通过，或用户明确接受对应风险并另行授权发布后才成立。
- 本任务预期结论是“开发仓库本地改造完成；稳定发布尚未验收”，不得宣称已发布或安装。

## 十二、删除可恢复性

本阶段删除的代码、测试和fixture仍可从 Git 历史或当前未提交基线恢复；本任务不创建 commit，因此不会生成新的恢复点。删除仅针对已被新主路径替代或确认无消费者的物料，不清理任何用户无关修改。

## 十三、实施结果（完成后回填）

### 13.1 先失败证据

新增 `tests/test_wp08_legacy_retirement.py` 后、删除运行时旧路径前执行：

```text
python3 -m unittest -v tests.test_wp08_legacy_retirement
Ran 5 tests
FAILED (failures=6)
```

失败稳定覆盖：18个旧运行时符号仍存在、历史非managed记录仍进入action-required、自由文本Stop仍生成旧结果、旧opaque fixture仍在、README仍把退役推迟到WP-08。

### 13.2 实际运行时删除与切换

`scripts/subagent_governance.py` 已完成：

- 删除 `ACTIVE_STATUSES`、`INTERRUPTIBLE_STATUSES`、`TERMINAL_STATUSES`、`RESOLVABLE_STATUSES`、`STOP_BLOCKING_STATUSES`、`SESSION_RESTORABLE_STATUSES`、`SESSION_END_PRESERVED_STATUSES`、`LEGACY_AUTOMATIC_RECOVERY_LIMIT`。
- 删除 `_platform_status_summary()`、`_call_failed()`、`_recovery_count()`、`_record_timestamp()` 等只剩旧分支或无消费者的辅助；最终AST检查没有只出现定义一次的顶层函数。
- `_resolve_task_id()`、`_mapped_attempt()`、`_bind_identity_target()` 只接受精确 `{task_id,attempt}` managed映射，不兼容字符串Agent→task映射，不按旧status判断可解析性。
- 删除 list-agents 对 legacy `platform_status/platform_error/status` 的写入、未认领followup的legacy恢复和未认领interrupt的legacy中断写入。
- SubagentStart 不再把历史记录写为running；发现精确映射但记录不是current managed形状时只告警，并按unmanaged执行边界提供通用上下文。
- 删除 `_terminal_field()`、`_legacy_terminal_errors()`、`_legacy_reported_status()` 以及 `last_assistant_message → status/result_document/source=legacy_free_text` 全链路。
- managed SubagentStop仍只消费显式 `task_result`；未映射Agent直接放行；历史/非managed映射只告警放行，不改旧记录，不生成正式结果或协议纠错状态。
- `_view_attempt_records()` 只投影current/prior managed attempts；删除 `_legacy_action_required()`、`_recent_records()`、`_active_records()`、`_managed_action_required_records()`、`_session_restore_records()`、`_session_end_preserved_records()`。
- `_action_required_records()`、`_recent_activity_records()`、`_stop_blocking_records()` 只消费current managed多维状态；SessionEnd直接调用 `_action_required_records()`。
- Session摘要不再回退读取旧 `mode/status/objective/completion` 字段。
- 诊断对磁盘历史非managed task报告 `current_required_field_missing|invalid` 的事实问题，不执行迁移、不补默认值，也不把旧记录放回执行视图。

### 13.3 测试与fixture退役

- `tests/test_governance.py` 删除 `add_legacy_task`、自由文本终态、strict卡/ACK/字符数/证据词/任务ID、旧协议纠错、legacy恢复/中断/Stop/Session/诊断桥断言；保留共享路由、unmanaged、文档契约、基础安全和当前初始记录回归。对应主路径由专门的WP-03～WP-07测试文件继续覆盖。
- `tests/test_hook_fixtures.py` 删除无消费者 `add_legacy_task`。
- 删除 `tests/fixtures/opaque-spawn-v1.json`，新增 `tests/fixtures/exact-task-ref-opaque-message-v1.json`，只证明opaque message不影响PreparedContract/task_ref精确门禁。
- `lifecycle-v1.json` 删除未消费的自由文本SubagentStop、Stop和SessionEnd尾段；`interrupt-v1.json` 删除未消费的旧派发/Stop片段；`recovery-limit-v1.json` 删除未消费的旧派发片段并保留current两次恢复链。
- 删除物料仍可从Git历史或当前未提交基线恢复；本任务没有创建commit。

### 13.4 当前文档与产品收口

- README改为描述最终主路径、全部稳定CLI、历史记录边界、纯只读诊断、轻量group、有限网络恢复和“本地完成不等于已发布”。
- runtime boundaries删除“WP-03/04/05/06已实现”阶段措辞，改为当前稳定行为；开发Skill本身已是最终current契约，无需重写历史规则。
- release process增加活动记录按当前操作所需字段预检、无版本门禁/迁移矩阵，以及“本地准备不授权外部写入”边界；旧独立Hook挂载检查继续作为发布安全门禁，不属于任务legacy状态机。
- optimization plan记录WP-01～WP-08本地实施完成，稳定发布/安装/真实平台验收未执行。
- 主盘点不改产品裁决，更新盘点状态、暂不删除项结果、52文件覆盖、运行时最终区段和WP-08后当前实现/完成结论；旧阶段方案和function inventory继续作为历史证据。
- `assets/agents-governance.md` 保持8行最小按需入口，没有复制完整协议；Schema、Hook和发布脚本无需为制造差异而修改。

### 13.5 文件覆盖复盘

最终执行：

```text
rg --files --hidden -g '!.git/**'
```

得到52个有效文件。确定性检查要求每个路径在主盘点第十五节逐项出现，结果：

```text
{'files': 52, 'inventory_coverage': 'complete'}
```

删除/替代依据：

- 旧 Provider文本特判fixture、`compatibility.md`、`related-skills.md` 已由前阶段删除，当前无消费者。
- `opaque-spawn-v1.json` 的有效current职责由新名称fixture接管。
- 未发现其他无消费者、仅证明已删除设计或重复空转的有效文件。
- 运行时AST与引用检查确认旧顶层符号均无定义/消费者，全部剩余顶层区段已在主盘点第十六节归属。

### 13.6 最终验证证据

```text
python3 -m unittest -v tests.test_wp08_legacy_retirement
Ran 5 tests
OK

python3 -m unittest -v tests.test_release_tools
Ran 26 tests
OK

python3 -m unittest discover -s tests -v
Ran 205 tests
OK

python3 -m py_compile scripts/subagent_governance.py
passed

python3 -m py_compile scripts/apply_agents_block.py scripts/check_installation.py scripts/reinstall_preserving_caches.py
passed

python3 $HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
Plugin validation passed

python3 $HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
Skill is valid!

Schema/fixture/WP-08确定性检查
{"fixtures": 5, "patterns": 10, "relative_refs_and_pointers": 35, "schemas": 3, "wp08_anchors": "ok"}

git diff --check
passed

旧符号与当前文档占位检查
no matches
```

全量测试从WP-07的273项降为205项，是因为删除了旧自由文本/legacy生命周期和重复桥测试；WP-03～WP-07的current定向测试仍全部通过，不是覆盖失败或测试未运行。

### 13.7 只读安装现状与N/N-1证据

只读执行 `python3 scripts/check_installation.py`，exit 0：

- 开发仓库、稳定源和当前运行缓存三路径分离且均非符号链接。
- 当前已安装稳定版为 `0.4.0-rc.9+codex.20260808155909`，稳定源与当前缓存hash相同：`fed424cb225c8293d74abf2b442a99a25b3025567fb2f5476943ae1a95d2b74c`。
- 当前运行安装 `runtime_healthy=true`、`deployment_in_sync=true`。
- 开发规则尚未部署：`development_rules_in_sync=false`，这是本任务未发布的预期事实。
- 当前保留8份历史兼容缓存，`retention_policy_satisfied=false`；本任务未清理。
- 旧独立Hook文件存在但未挂载：`legacy_hook_present=true`、`legacy_hook_mounted=false`。
- `release_ready=null`，registration和Hook trust未由该脚本检查。

只读执行 `codex plugin list --marketplace personal --json`，确认当前旧稳定版 installed/enabled且来源为稳定源。该证据只说明现有rc.9安装，不证明本开发工作树或目标新版本已加载。

本地 `tests/test_release_tools.py` 证明模拟环境中的明确N-1快照/恢复、命令失败恢复、目标缓存缺失失败、N-2 dry-run候选和不自动删除。没有执行真实整体回滚，因此真实N/N-1回滚保持 `not_checked`。

### 13.8 真实平台验收矩阵

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 新版本真实加载 | not_checked | 未发布/安装本开发工作树 |
| 七类Hook enabled/trusted | not_checked | 当前rc.9状态不能替代目标版本验收 |
| light派发 | not_checked | 未在目标新版本真实执行 |
| standard派发 | not_checked | 同上 |
| strict派发 | not_checked | 同上 |
| auto派发 | not_checked | 同上 |
| normal send_message | not_checked | 同上 |
| list_agents errored→followup→SubagentStart与两次恢复上限 | not_checked | 本地fixture/单测不替代真实Provider顺序 |
| interrupt | not_checked | 未在目标新版本真实执行 |
| SubagentStop结构化结果保存与父读取 | not_checked | 真实payload能力未验证 |
| Stop、compact/resume、SessionEnd | not_checked | 真实Hook时序未验证 |
| 纯只读诊断 | not_checked | 本地无副作用测试通过，真实Codex展示未验收 |
| 轻量group一个失败、其他继续、父汇总 | not_checked | 未执行真实多任务链 |
| 活动任务字段预检 | not_checked | 未对目标新运行时真实活动记录执行升级预检 |
| N/N-1整体回滚 | not_checked | 只有本地工具单测和当前只读现状 |

矩阵摘要：`passed=0`、`failed=0`、`not_checked=15`。这些not_checked是授权/真实平台边界，不是产品设计冲突。

### 13.9 发布结论与后续授权边界

- 结论：**开发仓库本地改造完成；稳定发布尚未验收。**
- 不能宣称“稳定版可发布验收完成”：目标新版本没有真实加载，Hook trust、真实派发/恢复/结果/Session/group和整体回滚均未验证；当前环境还保留8份历史缓存，不满足目标N/N-1保留策略。
- 本任务未执行发布、安装、稳定源替换、Marketplace更新、运行缓存写入、全局规则应用、Hook trust修改、Registry写入、缓存清理、stage、commit或push。
- 剩余事项只有用户另行明确授权后的受控发布/安装流程：生成正式版本/cachebuster和tag候选、导出稳定副本、包装重装、应用稳定版最小入口、完成真实平台矩阵、确认N/N-1整体回滚和后置缓存清理。

## 十四、D6 S6 后续兼容投影退役

WP-08 删除旧混合状态机后，D6 S1～S5 曾为纵向迁移保留 root current/`prior_attempts` 投影及 attempt-first diagnose/group 输出。2026-08-13 的 S6 已在所有新消费者切换到 `work_item + executions` 后删除这些临时兼容层；这不改写本节之前记录的 WP-08 历史基线。

- 新 task root 只含 `managed/task_id/work_item/executions`，projection writer/reader 已删除。
- 历史 flat record 不惰性迁移、不参与 Hook、CLI、Session、Stop、diagnose 或 group 决策；精确旧 Agent 映射只告警并 fail-open。
- diagnose 不再输出顶层 attempt-first `action_required/recent_activity` 数组；group member 不再输出三个旧别名。
- S6 失败先行、测试迁移、两个已知 D6 host-specific path errors、只读发布前检查和真实平台 `not_checked` 详见 `docs/redesign/S6-compatibility-retirement-release-preflight-implementation.md`。
- 本轮没有安装、发布、缓存同步、stage、commit 或 push；WP-08 先前只读安装现状不能证明本开发工作树已加载。
