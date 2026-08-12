# WP-07 最小诊断与轻量 group 详细改造方案

## 一、状态、唯一目标与权威边界

- 工作包：WP-07「最小诊断与轻量 group」。
- 权威来源：`docs/project-function-inventory.md`，重点是 U-04～U-10、SG-F07、SG-F08、第十三节、全仓覆盖表和第十六～十八节；`docs/optimization-plan.md` 只提供阶段顺序。
- 前置依赖：WP-02 的安全 StateStore 写路径；WP-05 的确定性正式结果地址与机械校验；WP-06 的 `_action_required_records()`、`_recent_activity_records()`、精确 current/prior attempt 投影、关闭/tombstone 和 duplicate/select 事实。
- 唯一目标：把 `--diagnose` 改成无副作用、稳定 JSON、只报告直接证据的规范化只读入口；增加父 Agent 显式 upsert/read 的轻量 group，只持久化 individual task 引用并实时派生 `summary_ready` 与 `group_action_required`。
- 当前状态：方案先行完成；运行时代码修改前将新增定向测试并确认失败，实施后在本文末尾回填实际结果、验证证据、`not_checked`、退出结论与 WP-08 交接。

本阶段不建立监控、修复、审计、分页、raw 模式、复杂查询、DAG、batch、wave、调度器、组级状态机、AggregateResult、自动传播或自动业务裁决；不发布、不安装、不写稳定源、Marketplace、运行缓存、Hook trust 或 Registry。

## 二、修改前代码事实与缺口

### 2.1 当前 `_diagnose()` 的副作用

当前 `_diagnose()` 通过 `_prepare_private_directory()`、`_data_root()` 和 `StateStore(...)` 进入诊断路径：

1. 显式 `--data-root` 会被 `mkdir(..., parents=True)` 创建并被 `chmod(0700)`。
2. 默认数据根会被 `_data_root()` 创建或改权限。
3. 指定单 Session 时，`StateStore.read()` 先打开或创建稳定 `.lock`；不存在的 Session 被解释为新空状态而不是“请求目标不存在”。
4. 上述路径不满足诊断不得创建目录、锁、临时文件或修改权限的裁决。

### 2.2 当前输出与错误语义

- 单 Session 直接输出完整 StateStore：包含完整 tasks/agents、legacy 字段、内部 pending/lifecycle 数据和潜在业务摘要，不是规范化诊断快照。
- 全局扫描只输出 `session_id/active/tasks/health/updated_at`，且损坏、非 UTF-8、不可读、符号链接和非普通文件被静默跳过。
- 全局与单 Session 没有共享解析函数和共享 snapshot 形状。
- `health.status` 同时承担组件健康和扫描成功的暗示，没有独立 `scan` 完整度。
- 没有稳定 issue code；不存在、权限、所有者、4 MiB、根结构和结果引用问题均不能机械区分。
- 所有诊断路径固定返回 0；单 Session 不存在、损坏和全局部分失败没有 exit 1。
- CLI 参数错误返回 2，但诊断参数错误的 stdout 不是稳定 JSON。

### 2.3 旧 active count 语义

当前全局诊断使用 `_active_records()`。WP-06 已明确该函数只表示最近 12 小时内的 legacy-compatible active count，不是 action-required 权威；stale、complete pending、blocked、failed、needs-decision、result conflict 等未解决任务会被遗漏。WP-07 必须让新诊断直接消费 `_action_required_records()` 和 `_recent_activity_records()`；`_active_records()` 本阶段不删除，留给 WP-08 与最后 legacy 测试一起退役。

### 2.4 group 现状

当前 StateStore 顶层允许未来 `groups` 扩展，但运行时没有 group 创建、更新、读取、机械校验或派生逻辑。仓库没有 CoordinationPlan、DAG、batch/wave、组状态机或 AggregateResult；本阶段只新增主盘点已裁决的最小引用能力，不补建完整协调系统。

## 三、允许与禁止修改范围

### 3.1 允许修改

- `scripts/subagent_governance.py`：专用只读诊断路径、规范化 snapshot、正式结果只读核对、group upsert/read/派生函数和最小 CLI。
- `schemas/governance-semantics.schema.json`：只增加诊断容量、group 字段/容量和派生语义机器锚点；不增加独立诊断 Schema 或版本门禁。
- `tests/test_minimal_diagnostics_lightweight_groups.py`：WP-07 定向失败与通过证据。
- `tests/test_governance.py`：原子替换旧诊断裸状态/active count 断言，保留 CLI 参数边界回归。
- `tests/test_semantic_baseline.py`、`tests/test_plugin_structure.py`：只增加 WP-07 机器/文档锚点。
- `skills/subagent-governance/SKILL.md`、`skills/subagent-governance/references/runtime-boundaries.md`、`README.md`：同步最小诊断和轻量 group 入口与边界。
- 本方案文档。

### 3.2 明确禁止

- 不修改 `assets/agents-governance.md`：现有内容只是按需加载 Skill 的最小入口，与 group 术语没有冲突。
- 不修改第三方 Skill或安装缓存。
- 不调用或实现 Agent 工具、后台 scheduler、自动恢复、中断、验收或组级传播。
- 不重新解释 WP-01～WP-06 的生命周期、正式结果、关闭、tombstone 或 parent disposition。
- 不删除 legacy `_active_records()`、`_legacy_*`、`result_document`、旧 fixture 或发布残留；这些统一交给 WP-08。
- 不 stage、commit、push、发布、安装或进行真实平台操作。

## 四、专用只读诊断路径

### 4.1 纯路径解析

新增不触碰文件系统的 `_data_root_path()`：只根据 `SUBAGENT_GOVERNANCE_DATA`、`PLUGIN_DATA` 和默认临时目录计算 Path。现有 `_data_root()` 继续调用 `_prepare_private_directory(_data_root_path())` 服务写路径；诊断只使用 `_data_root_path()` 或显式 `--data-root` 的绝对词法路径，不调用 `_prepare_private_directory()`。

### 4.2 Session 文件只读读取器

新增专用 `_read_session_file_read_only(path, requested_session=None)`，不构造 `StateStore`、不打开 `.lock`：

1. `lstat` 区分不存在、符号链接、非普通文件、所有者异常、权限异常和超限。
2. 使用 `O_RDONLY` 与可用时的 `O_NOFOLLOW` 打开；`fstat` 再核对普通文件、所有者和大小。
3. 最多读取 `MAX_STATE_BYTES + 1`，拒绝超过 4 MiB。
4. 严格解码 UTF-8 并解析 JSON 对象。
5. 核对 `session_id` 存在、为非空字符串、与单 Session 请求精确匹配；未知额外字段保留在内存但不会原样输出。
6. 任何失败只返回事实 issue，不移动、隔离、修复或改写原文件。

诊断不得调用 reconcile、tombstone cleanup、result reassociation、StateStore health 写入、`updated_at` 更新或 chmod/chown。

### 4.3 全局目录扫描

- 数据根不存在：返回 `data_root_exists=false` 的完整空扫描，exit 0，不创建任何目录。
- `sessions/` 不存在：同样返回完整空扫描，exit 0。
- `sessions/` 是符号链接、非目录或无法列举：返回顶层 `scan_incomplete`，exit 1。
- 只把 `sessions/*.json` 名称作为 Session 请求目标；`.lock`、临时文件和其他内部实现不进入输出。
- 候选按文件名排序后应用 Session 上限；单个 Session 失败不阻止其他 Session。
- 成功 snapshot 最终按 `session_id`、源文件名稳定排序。

## 五、稳定 JSON 形状与排序

### 5.1 顶层

固定、无版本字段的顶层为：

```text
data_root: string
data_root_exists: boolean
scope: "all_sessions" | "single_session"
requested_session: string | null
scan:
  requested: integer
  checked: integer
  succeeded: integer
  failed: integer
  omitted: integer
  complete: boolean
sessions: SessionSnapshot[]
issues: Issue[]
boundaries:
  transport_opaque: true
  provider_status: "not_checked"
  hook_trust: "not_checked"
  repairs_state: false
  writes_files: false
```

`scan` 只表达本次读取完整度；任务异常、action-required、平台 error 或结果冲突不自动改变 exit code。`omitted` 统计因 session/attempt/group/issue/总输出上限未展开的记录数；任何 omitted 都使 `complete=false` 和 exit 1。

### 5.2 SessionSnapshot

每个成功或部分成功解析的 Session 使用同一形状：

```text
session_id
component_health: {status, source}
updated_at
counts:
  tasks
  attempts
  action_required
  recent_activity
  groups
  tombstones
action_required: AttemptSnapshot[]
recent_activity: AttemptSnapshot[]
groups: GroupSnapshot[]
issues: Issue[]
```

- `component_health.status` 只规范化持久化 `health.status` 的 `ok|degraded|unavailable`；缺失或非法时为 `unknown` 并生成字段 issue。
- `component_health.source` 固定为 `persisted_health`。
- `counts` 是读取到的事实计数，不直接镜像 tasks/groups 原始对象。
- action-required 与 recent-activity 都直接消费 WP-06 视图；同一 attempt 可以同时出现在两个列表中。

### 5.3 AttemptSnapshot

固定仅输出：

- 引用：`task_id`、`attempt`、`is_current_attempt`、`agent_id`、`canonical_task_path`。
- 状态：`execution_status`、`spawn_observation`、`identity_status`、`platform_observation`、`business_result`、`acceptance_status`、`result_protocol_status`、`result_storage_status`、`result_conflict`、`recovery_status`、`parent_action`。
- 计数：`spawn_retry_count`、`recovery_count`、`correction_count`。
- 时间：`activity_at` 与有值时的 `created_at/updated_at/platform_checked_at/spawn_claimed_at/spawn_post_observed_at/result_stored_at/attempt_closed_at`，统一放入 `timestamps`。
- 最小契约摘要：`resolved_mode`、有界 `objective`、最多 3 条 `completion_conditions` 及遗漏数。
- 派生标志：`stale`、`action_required`、`recent_activity`、`closed`。
- 正式结果：无适用引用时为 null；否则只输出 `reference/readable/usable/sha256_matches/business_result/result_chars/evidence_count/remaining_count`。

不输出完整 dispatch prompt、通信正文、pending action、last lifecycle 原始对象、完整平台响应、完整 result/evidence/remaining、完整 StateStore、legacy `status/result_document/protocol_error` 或其他历史兼容字段。

### 5.4 Issue

固定形状：

```text
code: string
message: 有界字符串
context: 仅包含适用的 session_id/path/field/task_id/attempt/group_id/fact
```

排序按 `code/session_id/task_id/attempt/group_id/field/path`。message 不包含完整业务正文、完整平台对象或 Provider 文本。

## 六、最小 issue code 集合

只使用直接证据生成以下 code：

- `current_required_field_missing`：当前 snapshot、attempt 或 group 派生必需字段不存在。
- `current_required_field_invalid`：上述字段类型、枚举、引用或基本组合非法。
- `session_missing`。
- `session_symlink`。
- `session_not_regular`。
- `session_unreadable`。
- `session_owner_mismatch`。
- `session_permissions_unsafe`。
- `session_oversized`。
- `session_non_utf8`。
- `session_json_invalid`。
- `session_root_invalid`：JSON 根不是对象或 session_id 不匹配。
- `identity_unconfirmed`：managed 未关闭 attempt 的持久化身份仍为 unconfirmed。
- `platform_error`：持久化 `platform_observation=error`。
- `result_missing`：available/有 reference 的精确结果文件不存在。
- `result_invalid`：精确结果文件不安全、不可读、超限、非 UTF-8、JSON/Schema/task-attempt/canonical/reference/hash 不一致，或 StateStore 结果引用字段非法。
- `result_conflict`：持久化 `result_conflict=true`；不读取或保存第二候选结果。
- `scan_incomplete`：目录、容量、字段或输出遗漏使本次扫描不能完整完成。

明确不使用 `delivery-suspected`、`execution`、`orchestration`、Provider/加密/解密/stream 关键词推测；`transport_opaque` 只在 boundaries；`action_required` 只作为 snapshot 标志。

## 七、正式结果引用只读核对

### 7.1 触发条件

当 attempt 的 `result_storage_status=available` 或存在非空 `result_reference` 时执行精确核对；其他状态不扫描 results 目录、不寻找候选、不制造缺失问题。

### 7.2 核对顺序

1. 由 `task_id + attempt` 调用纯计算 `result_file_path()` 得到唯一地址，不使用 glob。
2. `result_reference` 必须等于确定性文件名。
3. 直接调用安全只读 `_read_result_path()`；它只执行 lstat/open/read/机械校验，不创建结果锁。
4. 核对文件内 task/attempt、TaskResult Schema、canonical bytes 和 SHA-256。
5. `result_sha256` 存在时必须匹配；缺失/非法按当前必需字段 issue，摘要标 `sha256_matches=null|false`。
6. 输出只保留业务结果枚举和长度/数量元数据，不输出业务正文或证据。

读取失败不改变 `result_storage_status`，不重关联、不重写、不删除。`result_conflict=true` 只展示已有冲突事实，不读取第二候选。

## 八、退出码、部分失败与 JSON 参数错误

- exit 0：参数合法且所有请求目标、引用和要求展开的记录扫描完整；任务处于异常/action-required 仍为 0。
- exit 1：目标不存在、状态/结果读取失败、当前必需字段缺失/非法或任何容量 omitted 使扫描不完整；stdout 仍输出合法顶层 JSON。
- exit 2：未知参数、缺值、操作选择器冲突或孤立 selector。若命令行包含 `--diagnose`，stdout 仍输出固定诊断 JSON，错误事实写入 `issues`；stderr 只写简短提示。

全局单个 Session 失败继续其他 Session。单 Session 不存在/不可读返回 requested=checked=1、failed=1、complete=false 和 exit 1。

## 九、容量边界

在机器语义源增加简单固定锚点：

```text
diagnostic.sessions = 128
diagnostic.attempts_per_session = 256
diagnostic.groups_per_session = 64
diagnostic.issues = 256
diagnostic.output_bytes = 2097152
group.members = 128
group.id_max_length = 128
group.objective_summary_max_length = 600
```

- 超过 Session、attempt、group 或 issue 上限时保留确定性排序的前 N 项，增加 omitted 和 `scan_incomplete`。
- 总 JSON 超过 2 MiB 时从排序末尾删除完整 Session snapshot，增加 omitted，直至合法；不截断单个 JSON token、不输出半对象。
- 不实现分页、游标、查询矩阵、复杂过滤或 raw 模式。
- 4 MiB Session 和 2 MiB result 文件继续使用现有硬边界；诊断不会通过版本字段决定可读性。

## 十、轻量 group 持久结构与入口

### 10.1 最小结构

StateStore 顶层可选 `groups` 对象；每个值只保存：

```text
group_id
objective_summary
members: [{task_id, required}]
created_at
updated_at
```

不保存角色、成员目标、Agent target、结果、失败原因、恢复状态、父动作、`summary_ready`、`group_action_required`、组 status、batch/wave/revision/图哈希或 AggregateResult。

### 10.2 函数与 CLI

提供两个最小函数：

- `upsert_group(value, session_id, state_store=..., now=...)`：输入只消费 `group_id/objective_summary/members`，忽略未知额外字段；在 StateStore 稳定锁内创建或整体更新，创建时写 created/updated，更新时保留 created_at 并改 updated_at，完成原子替换和回读。
- `read_group(session_id, group_id, state_store=..., results_root=...)`：读取当前 StateStore 并返回实时派生 GroupSnapshot；它不修改 group，但普通 CLI 读取可以经过 StateStore 稳定锁。诊断不调用此函数的 StateStore 路径，而对已只读解析的 state 调用同一纯派生函数。

CLI：

- `--upsert-group --session <id> [--data-root <root>]`，stdin 接收 group 输入。
- `--read-group --session <id> --group-id <id> [--data-root <root>]`。

这两个入口足以显式创建/更新和读取，不增加 list/delete/member mutation 子命令；全量 group 可由诊断 Session snapshot 查看，group 随 Session 删除。

### 10.3 最低机械校验

- group_id、objective_summary 为非空字符串并满足长度上限。
- members 为数组且不超过 128；每项是对象，task_id 非空且不超过机器 task_id 上限，required 必须是布尔值。
- 同一 group 中 task_id 不重复。
- 每个 task_id 必须存在于当前 Session `tasks` 对象。
- 已有 `groups` 若不是对象则拒绝，不用 `setdefault` 覆盖非法事实。
- 未知额外字段忽略；不判断业务分组、角色、可并行性或失败策略。

## 十一、group 实时派生算法

### 11.1 member individual facts

每个成员实时投影：

- `task_id/required/exists/current_attempt`。
- `individual_action_required`：直接检查 `_action_required_records(state)` 中该 task 的任一 attempt。
- `disposition_complete`：该 task 的全部 current/prior attempts 均通过 `attempt_closed` 或精确 tombstone 关闭，且每个关闭 attempt 有 `attempt_close_reason`、tombstone `close_reason` 或父处置 reason；不存在 attempt 或仅有 parent_action=null 的未关闭记录不能视为完成处置。
- `summary_material_ready`：current attempt 的正式结果通过精确只读核对并 usable，或 `disposition_complete=true`。
- `formal_result`：只展示 current attempt 的同一有界元数据；不复制完整结果。

### 11.2 `summary_ready`

- 只看 required 成员。
- required 非空且每个 required 的 `summary_material_ready=true` 时为 true。
- required 为空时固定为 false，避免把空 group 表示成“完整汇总材料已齐备”。
- complete 结果可读但仍 pending 验收时 summary_ready 可以为 true。
- optional 成员不影响该布尔值。

### 11.3 `group_action_required`

- required 为空时固定为 false：没有必需 individual task 需要组聚合处置，但 summary_ready 仍为 false。
- required 非空时，只要任一 required 的 `disposition_complete=false` 就为 true。
- 因此待验收、blocked、failed、needs_decision、平台/协议/存储问题、result conflict、duplicate、运行/待对账或其他未关闭状态都会直接通过 individual action-required/关闭事实使其为 true。
- 只有全部 required task 均完成 individual 明确处置后为 false；它不依赖 summary_ready，不建立组级转换。
- optional 成员只展示自己的 individual 摘要，不影响两个 required 聚合信号。

### 11.4 结果汇总边界

GroupSnapshot 只展示 `group_id/objective_summary/members/created_at/updated_at/summary_ready/group_action_required`。父 Agent自行读取 individual 正式结果并生成用户摘要；运行时不生成 AggregateResult、自动比较冲突、组级结论或迟到重聚合。

## 十二、文档同步

- `README.md`：把过时的“WP-03 后续接管”说明更新为当前 WP-06/WP-07 能力；增加诊断退出码、纯只读边界和 group CLI 示例；不宣称发布或真实平台已验证。
- `skills/subagent-governance/SKILL.md`：保留已有批量派发表格透明度，明确表格不是调度计划、每个 Agent 独立 spawn；增加 group 必须显式 upsert、只引用 individual task、两个派生信号和父 Agent读取 individual result 汇总。
- `runtime-boundaries.md`：记录诊断无副作用、结果只读复验、group 不拥有状态机/调度器/恢复链。
- `assets/agents-governance.md` 不修改。

## 十三、先失败测试与文件级实施步骤

### 13.1 运行时代码修改前的失败测试

新增 `tests/test_minimal_diagnostics_lightweight_groups.py`，先确认旧实现稳定失败：

1. 诊断不存在的数据根会被当前实现创建。
2. 单 Session 诊断会创建 `.lock` 并裸输出 StateStore。
3. 损坏/符号链接/权限/超限 Session 被跳过且 exit 仍为 0。
4. 全局部分失败没有稳定 scan/issues，旧 active count 不等于 WP-06 action-required。
5. result 缺失/损坏/hash 冲突没有只读问题码。
6. 4 MiB、session/attempt/group/output 上限没有 omitted/exit 1。
7. 不存在 group upsert/read/校验或两个派生信号。

### 13.2 实施顺序

1. 新增上述失败测试并记录失败数量/原因。
2. 在机器语义源加入 WP-07 容量与 group 锚点，Python 读取常量。
3. 抽出纯 `_data_root_path()`，保持所有现有写路径继续调用 `_prepare_private_directory()`。
4. 实现只读 Session/目录/result 诊断辅助、issue 归一化和 attempt snapshot cache。
5. 实现共享 SessionSnapshot、全局/单 Session扫描、稳定排序、容量和 exit 0/1。
6. 调整 CLI 参数解析，使诊断参数错误 exit 2 且 stdout 保持稳定 JSON。
7. 实现 group validator、`upsert_group()`、纯派生 GroupSnapshot、`read_group()` 和两个 CLI。
8. 原子替换 `tests/test_governance.py` 的旧裸状态/active count 诊断断言；保留 `_active_records()` 实现不删。
9. 更新 README、Skill、runtime-boundaries 和一致性测试。
10. 执行定向、全量、编译、Plugin/Skill validator、Schema/fixture/锚点、无副作用和 diff check。
11. 回填本文实施结果、验证、not_checked、退出结论和 WP-08 交接。

## 十四、验证计划

至少执行：

```text
python3 -m unittest -v tests.test_minimal_diagnostics_lightweight_groups
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
python3 $HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 $HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
git diff --check
```

额外确定性验证：

- 3 个 Schema、相关 fixture、全部相对 `$ref`/JSON Pointer/正则和 WP-07 诊断/group 锚点。
- 诊断前后数据根递归树、每个对象类型、inode、mtime_ns、mode、size 和普通文件 SHA-256 完全一致。
- 全局部分失败、单 Session 缺失/不可读、result 缺失/损坏/hash 不一致、4 MiB Session 边界、session/attempt/group/issue/总输出 omitted。
- group 并发 upsert 通过 StateStore 锁和回读保持完整 JSON；不要求多 group 调度语义。

## 十五、not_checked

本地仓库无法证明，最终统一标记 `not_checked`：

- 真实 Hook 即时告警和 SessionStart 展示如何与诊断 JSON配合。
- 真实 Provider 断流、mailbox、原生 Agent状态字段和 transport opaque 的平台表现。
- 真实 Hook trust、Plugin/Skill 加载和运行缓存版本。
- 真实数据规模、2 MiB诊断输出在 Codex UI/终端中的展示体验。
- 父 Agent在真实任务中创建 group、并行等待 individual Agent、读取正式结果并生成汇总的完整使用链。
- 真实平台向 SubagentStop 传递 WP-05 `task_result` 的能力。

## 十六、退出条件

WP-07 只有同时满足以下条件才退出：

1. 方案、失败基线、实现和验证证据全部回填。
2. 诊断不创建或修改任何数据对象，前后 inode/mtime/mode/hash 测试通过。
3. 全局/单 Session共享只读解析和 snapshot，稳定 JSON不转储原始状态/结果。
4. scan、component health、issues 和 exit 0/1/2 分层正确；部分失败继续扫描。
5. action-required/recent-activity 直接消费 WP-06 权威函数；新诊断不再消费 `_active_records()`。
6. 正式结果只读复验精确、无重关联/回写/删除，默认不输出完整业务正文和证据。
7. group 只持久化最小引用，upsert 使用 StateStore安全写路径，两个聚合信号实时派生且 required/optional/空 required 语义通过测试。
8. 未实现被明确禁止的诊断平台和多 Agent编排目标。
9. 全部适用本地验证通过，真实平台项明确为 not_checked。

## 十七、WP-08 预交接

WP-07 完成后，WP-08 可删除或收口：

- `_active_records()` 的最后旧诊断消费者已消失；确认其他 legacy 测试/Session桥无消费者后删除 `_active_records()`、`_recent_records()` 和相关旧 active count 断言。
- 删除 `tests/test_governance.py` 中旧诊断 `session` 裸状态和 `active` 字段目标，以及任何 legacy `status/result_document` 诊断残留。
- 评估并删除 `_managed_action_required_records()`、`_session_end_preserved_records()` 等只剩兼容测试的薄桥；不得删除 WP-06 权威 `_action_required_records()` / `_recent_activity_records()`。
- 删除 README、Skill 或 runtime-boundaries 中“后续 WP 接管”的历史措辞，保留稳定新 CLI 与真实平台 not_checked。
- 发布前只保留新诊断 JSON形状、group upsert/read 和 individual result/parent disposition 稳定接口；不得在未授权时写稳定源或缓存。
- WP-08 仍负责全仓 legacy 路径退役、发布工具总收口、N/N-1、真实 Hook/Provider/Session/group 使用矩阵和最终发布边界；WP-07 不提前执行。

## 十八、实施结果与交接（实施后回填）

### 18.1 失败基线

运行时代码修改前新增首批 WP-07 测试并执行：

```text
python3 -m unittest -v tests.test_minimal_diagnostics_lightweight_groups
Ran 14 tests
FAILED (failures=5, errors=11)
```

失败事实与方案预期一致：旧 `--diagnose` 会构造 `StateStore` 并创建数据根/Session 锁，输出裸状态和 legacy `active`，损坏或不可读 Session 被跳过且退出码不反映部分失败；不存在纯只读 formal result 核对、规范化 snapshot、容量 omitted、显式 group upsert/read 和两个派生布尔值。

实现审查阶段又先补了两个稳定失败用例：非法/缺失 current attempt 字段会被派生视图跳过，非法 task_id 还会使诊断无 JSON 异常退出；`--diagnose --task-id ...` 会被静默忽略并返回 0。修复前两项测试分别表现为无 JSON/异常和期望 exit 2 实得 exit 0，随后才实施最小修复。

### 18.2 实际修改

- `schemas/governance-semantics.schema.json`
  - 增加 `diagnostic_limits` 机器锚点：128 Session、每 Session 256 attempts、64 groups、256 issues、2 MiB 输出。
  - 增加 group 最小字段、长度/成员数量与“不持久化派生状态”锚点；未增加诊断 Schema 或版本门禁。
- `scripts/subagent_governance.py`
  - 抽出 `_data_root_path()`，诊断只做路径计算；写路径继续使用既有私有目录准备逻辑。
  - 用 `_read_session_file_read_only()` 和共享 snapshot 构建器替换旧 `_diagnose()`：不构造 `StateStore`，不创建目录、锁、临时/隔离文件，不 chmod/chown/移动/清理/回写。
  - 顶层固定输出 `data_root/data_root_exists/scope/requested_session/scan/sessions/issues/boundaries`；全局和单 Session共用同一解析、SessionSnapshot、排序、数量/体积裁剪和 exit 0/1 规则。
  - SessionSnapshot 分离 persisted `component_health` 与本次 `scan.complete`；attempt snapshot 只保留身份、执行/平台/结果/恢复/父动作、计数、关键时间、有界契约摘要和 `stale/action_required/recent_activity`。
  - 新诊断直接消费 `_action_required_records()` 与 `_recent_activity_records()`；`_active_records()` 已无诊断消费者但暂不删除。
  - 对 managed current/prior attempt 的可观察字段缺失/非法生成稳定事实问题码；非法 task identity 不再导致诊断异常退出。
  - 对 `available` 或已有 `result_reference` 的精确确定性 result 文件执行只读普通文件、owner、mode、4 MiB、UTF-8/JSON、Schema、task_id+attempt、canonical bytes、SHA-256 与有界摘要核对；不重关联、不扫描第二候选、不输出完整 result/evidence/remaining、不改变持久状态。
  - 全局部分失败继续其他 Session；单 Session失败和扫描/输出 omitted 返回 1；业务异常和 action-required 不改变退出码。诊断参数错误及非诊断选择器冲突 stdout 保持 JSON并返回 2。
  - 增加 `GroupValidationError`、`GroupNotFoundError`、`upsert_group()`、`read_group()`、`--upsert-group`、`--read-group --group-id`。持久化严格投影为 `group_id/objective_summary/members/created_at/updated_at`，引用检查与更新复用 StateStore 锁、原子替换和回读。
  - group snapshot 实时派生成员有界摘要、`summary_ready` 和 `group_action_required`；required 为空时二者均 false，optional 不参与聚合，individual 生命周期/结果/父处置仍是唯一权威。
- `tests/test_minimal_diagnostics_lightweight_groups.py`
  - 最终 20 项定向测试覆盖纯只读、空根、单 Session/全局部分失败、符号链接/权限/4 MiB、非法 current attempt、result 缺失/损坏、attempt/group/issues/output 上限、CLI exit 0/1/2、group 最小持久化/校验/派生/显式性和 16 进程并发 upsert。
- `tests/test_governance.py`
  - 旧裸状态/`active` 诊断断言改为新规范化顶层、SessionSnapshot 与 action-required/recent-activity 语义；未删除其他 WP-08 legacy 测试。
- `README.md`、`skills/subagent-governance/SKILL.md`、`skills/subagent-governance/references/runtime-boundaries.md`
  - 同步纯只读诊断、退出码、显式 group CLI、批量透明表格不是调度计划、individual result 汇总责任和禁止 AggregateResult/组级状态机边界。
- `assets/agents-governance.md` 未修改；未写稳定发布源、Marketplace、运行缓存、Hook trust 或 Registry。

### 18.3 验证证据

失败基线之后最终验证：

```text
python3 -m unittest -v tests.test_minimal_diagnostics_lightweight_groups
Ran 20 tests
OK

python3 -m unittest discover -s tests -v
Ran 273 tests
OK

python3 -m py_compile scripts/subagent_governance.py
通过

python3 $HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
Plugin validation passed

python3 $HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
Skill is valid!

git diff --check
通过
```

独立机器语义确定性检查使用标准库解析 3 个 Schema，解析 35 个相对 `$ref`/JSON Pointer，编译 10 个正则，解析 5 个 Hook fixtures，并精确核对 WP-07 `diagnostic_limits` 和 group 字段/派生状态锚点，结果为：

```json
{"fixtures": 5, "patterns": 10, "relative_refs_and_pointers": 35, "schemas": 3, "wp07_anchors": "ok"}
```

默认 Python 环境没有第三方 `jsonschema` 包，因此独立命令没有重复执行 Draft 2020-12 meta-schema validator；三个 Schema 的仓库 Plugin validator、运行时/Schema 一致性测试、相对引用/Pointer/正则检查均已通过。

无副作用/损坏/容量集合单独执行 8 项通过。测试在诊断前后递归比较对象类型、inode、mtime_ns、mode、size 和普通文件 SHA-256；覆盖不存在数据根不创建、单 Session 不创建锁或改写状态、符号链接/权限/4 MiB边界不修复、损坏 result 不改状态、全局部分失败、单 Session失败、attempt/group上限和2 MiB输出裁剪。

并发 group upsert 使用 16 个独立 CLI 进程写入同一 Session，最终回读保留全部 16 个 group 且每项只有五个允许字段。

### 18.4 not_checked

- 真实 Hook 即时告警和 SessionStart 展示如何与诊断 JSON配合。
- 真实 Provider 断流、mailbox、原生 Agent状态和 transport opaque 平台表现。
- 真实 Hook trust、Plugin/Skill 实际加载和运行缓存版本。
- 真实数据规模以及 2 MiB诊断输出在 Codex UI/终端中的展示体验。
- 父 Agent在真实任务中显式创建 group、独立等待成员、读取 individual正式结果并生成人类汇总的完整链路。
- 真实平台向 SubagentStop 传递 `task_result` 的能力。

### 18.5 退出结论

WP-07 的本地退出条件全部满足：诊断路径纯只读且稳定 JSON；全局/单 Session共用解析和 snapshot；scan/component health/issues/exit 0/1/2 分层；WP-06 权威派生视图和 WP-05正式结果引用被直接消费；轻量 group 只有显式最小引用持久化和实时派生信号；定向、全量、编译、Plugin/Skill validator、机器语义锚点、无副作用、容量和 diff 门禁均通过。

未发现新代码事实与主盘点裁决存在无法兼容的实质冲突。阶段状态为“完成”，不在本阶段开始 WP-08、发布或真实平台操作。

### 18.6 WP-08 交接

稳定新接口与语义：

- 诊断入口：`_build_diagnostic_document()` / `_diagnose()` / `--diagnose [--session] [--data-root]`，纯只读，固定顶层与 SessionSnapshot，退出码只表达参数合法性和扫描完整度。
- 权威派生视图：`_action_required_records()`、`_recent_activity_records()`；不得退回12小时 active 作为待处置权威。
- 正式结果：精确确定性 result 引用与只读有界复验；individual result/parent disposition 仍是唯一业务与生命周期权威。
- group：`upsert_group()`、`read_group()`、`--upsert-group`、`--read-group --group-id`；只持久化五字段，`summary_ready/group_action_required` 不持久化且不构成状态机。

WP-08 可删除/收口清单：

1. `_active_records()` 已只剩定义，无运行时/测试消费者；可在确认外部兼容边界后删除。
2. `_recent_records()` 和 `_managed_action_required_records()` 已只剩定义；可与相关 legacy 状态集合测试一起删除，不得删除 WP-06 两个权威函数。
3. `_session_end_preserved_records()` 仍由 SessionEnd 和一个 legacy 单测消费；WP-08 可让 SessionEnd 直接使用 `_action_required_records()` 后删除该薄桥与对应桥测试。
4. `tests/test_governance.py` 中 legacy free-text `result_document/status`、旧 unmanaged lifecycle 与桥函数测试仍在；应按主盘点一次性退役，不能把它们重新接入新诊断。
5. WP-01～WP-06 方案和 function inventory 中“`_active_records()` 仍供旧诊断使用”的文字是历史事实；WP-08 可在最终文档收口中标为已退役，但不应回改阶段证据。
6. README 中“legacy 分支尚待 WP-08 原子退役”和 release preflight 边界可在 WP-08 完成后更新；保留新诊断/group CLI、真实平台 `not_checked` 与 AggregateResult 禁止边界。
7. 发布前仍需验证开发仓库与稳定源非同路径/非符号链接、稳定源与目标运行缓存哈希、N/N-1、真实 Hook/Provider/SessionStart/SubagentStop/group 使用矩阵；未经明确授权不得写稳定源、缓存、Hook trust、Marketplace 或 Registry。
