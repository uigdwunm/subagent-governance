# WP-02 StateStore 安全底座详细改造方案

## 一、状态、目标与权威边界

- 工作包：WP-02「StateStore 安全底座」。
- 权威来源：`docs/project-function-inventory.md`，重点是 U-05、U-06、U-08、SG-F05、SG-F06 的存储边界、第十三节 OR-11/12/14/16、第十七节和第十八节。
- 前置依赖：WP-01 已完成；`schemas/governance-semantics.schema.json`、`AttemptState().to_record()`、`TaskContract`、`TaskResult` 及两个机械 validator 是本阶段不可重新解释的语义输入。
- 唯一目标：把每个 Session 的 StateStore 收缩为可靠、最小、可恢复的 JSON 持久化底座，提供稳定锁、锁内 compare-and-set、原子替换、回读验证、容量门限、损坏保全和精确 tombstone 清理能力。
- 当前状态：方案已完成初稿；实施结束后在本文末尾同步实际文件、测试证据、`not_checked` 项和 WP-03 交接。

本阶段只建设存储事实和原语，不实现派发、通信、结果、等待或父验收状态机。旧 Hook 为保持当前消费者可运行而保留的平面 `status`、字符串 Agent 映射和自由文本结果投影，均是临时运输桥，不是目标 StateStore 接口。

## 二、修改前 StateStore 结构与全部消费者

### 2.1 当前持久结构

当前空状态为：

```text
{
  session_id,
  tasks: {task_id: legacy_flat_task_record},
  agents: {agent_id_or_canonical_path: task_id},
  health: {status},
  updated_at
}
```

当前任务记录把契约摘要、原生调用标识、单一 `status`、混合重试计数、平台错误对象、中断信息和截断结果片段放在同一平面。该形状由 WP-01 明确标记为运输桥，不能继续扩展为目标模型。

### 2.2 写入者

- `_handle_spawn()`：创建旧式 task 记录；当前 StateStore 失败时仍降级放行。
- `_handle_communication()`：读取并可能修正恢复次数、切换旧 `needs_decision`。
- `_handle_post_tool()`：写 spawn、follow-up、list-agents 和 interrupt 结果。
- `_assign_starting_agent()` / `_handle_subagent_start()`：写 Agent 映射和 running 状态。
- `_handle_subagent_stop()`：清理失效映射、写旧自由文本终态、纠正次数和协议状态。
- `_handle_session_end()`：条件删除 Session JSON。
- `StateStore._prune_state()`：每次写入前按30天/200条删除通用 terminal 记录，并删除 Agent 映射。

### 2.3 读取者

- `_handle_communication()`、`_resolve_task_id()`：解析现有 task/Agent 关联。
- `_handle_subagent_start()`、`_handle_subagent_stop()`：读取当前映射和生命周期状态。
- `_handle_stop()`、`_handle_session_start()`、`_handle_session_end()`：读取旧状态集合和12小时窗口。
- `_diagnose()`：单 Session 走 `StateStore.read()`；全局扫描绕过 StateStore 直接读取 JSON。
- `tests/test_governance.py`、`tests/test_hook_fixtures.py`、`tests/test_concurrency.py`：直接构造、读取或断言旧状态。

### 2.4 修改前已确认缺口

1. JSON 损坏或非 UTF-8 时，原文件被移动为 `.corrupt-*`，随后返回空/降级状态；未解决任务会被伪装成不存在。
2. `_read_path()` 使用 `setdefault("tasks")`、`setdefault("agents")`、`setdefault("health")` 静默补造已有状态事实。
3. `_prune_state()` 以30天和最多200条裁剪所有旧 terminal 状态，可能删除 blocked、failed、needs-decision、平台错误等仍需父任务处理的记录。
4. 只有4 MiB硬上限；没有3 MiB新任务软准入，也没有区分新任务和已有任务更新。
5. 原子替换后没有重新读取和内容核对；替换或回读失败可能缺少可靠的失败边界。
6. 锁文件虽稳定保留，但打开后没有完整核对普通文件、所有者和最终权限。
7. 现有 `update()` 只能依赖 callback 内部手写条件，没有可复用、冲突时绝不写入的 CAS 原语。
8. 没有明确关闭 attempt 的最小 tombstone 结构、7天精确清理和结果文件精确清理回调。

## 三、本阶段允许与禁止范围

### 3.1 允许

- 重构 `StateStore` / `UnavailableStateStore` 的锁、读取、写入、容量、CAS、删除和精确清理接口。
- 新建空状态时写入 `session_id`、`tasks`、`agents`、`health`、`tombstones` 和 `updated_at`，不写协议版本。
- 提供从 WP-01 `AttemptState` 复制初始状态的最小辅助接口，不发明新枚举或默认值。
- 已有状态按本次操作传入的必需字段检查；未知额外字段原样保留。
- 保留旧 Hook 平面记录的最小兼容桥，使当前测试和消费者在 WP-03～WP-06 接管前继续运行。
- 增加 StateStore、并发、损坏、权限、容量、CAS、回读和 tombstone 的定向测试。

### 3.2 禁止

- 不实现 PreparedContract、task ref 生成/碰撞、确定性 prompt、governed spawn 硬门禁或精确身份绑定；归 WP-03。
- 不实现 pending action、四类通信完整转换、恢复授权、结果补交、business resume 或 interrupt unknown 状态机；归 WP-04。
- 不实现正式 result 文件提交、冲突状态机、父验收和 parent disposition；归 WP-05。
- 不实现20分钟父线程等待、Stop 三次读取、SessionStart/End 完整闭环、多 attempt 选择或 Hook 级关闭流程；归 WP-06。
- 不重写诊断为无副作用 JSON，也不增加 group；归 WP-07。
- 不清理全部旧路径、不发布、不安装、不写稳定源、Marketplace、运行缓存、Hook trust 或 Registry；归 WP-08 或另行授权。

## 四、目标最小数据边界

### 4.1 Session 顶层

新建状态只包含：

```text
session_id       当前 Session 精确标识
tasks            跨事件治理所需的最小 task/attempt 事实
agents           精确 Agent target → task/attempt 关联
health           StateStore 等组件的当前最小健康事实
tombstones       已明确关闭 attempt 的最小保留记录
updated_at       最近一次可靠写入时间
```

`groups` 是 WP-07 的可选字段，本阶段不创建。未知额外顶层字段兼容保留，不因存在额外字段拒绝或重写。

### 4.2 task / attempt

目标 task/attempt 记录只允许保存：

- `task_id`、正整数 `attempt`、后续 WP-03 提供的 `task_ref`。
- 当前 attempt 关联和精确 Agent ID/canonical path。
- 有界契约摘要：目标、工作/禁止范围、完成条件、`evidence_requirements[]`、resolved mode 和父动作恢复所需最小提示。
- WP-01 `AttemptState` 的十四个状态/计数字段。
- 后续 WP-04～WP-06 所需的单条 pending/last lifecycle、结果引用、关键时间、关闭事实和重复执行最小标记。

本阶段不定义完整多 attempt 状态机。`StateStore.initial_attempt_state()` 只返回 `AttemptState().to_record()` 的深拷贝，供 WP-03 创建正式记录；旧 Hook 暂时仍写平面记录，并在兼容记录中附带同一组初始字段，避免新事实继续使用 `pending/unset`。

### 4.3 Agent 映射

目标映射必须能精确定位 `task_id + attempt`；不能只映射到 task 后再猜 current attempt。WP-03 接管身份绑定前，旧字符串 `target → task_id` 映射作为兼容桥继续可读；StateStore 本身不根据名字、时间或唯一候选推断身份。

### 4.4 组件健康

- 可读、可写且回读验证成功时为 `ok`。
- 当前状态文件损坏、非 UTF-8、非普通文件、所有者/权限异常或超限时，StateStore 直接返回明确异常并保持原文件；不能写回同一文件伪造 `degraded`。
- 原生调用已经发生后的业务 handler 如何展示 degraded/人工对账由后续 WP 处理；StateStore 只保证失败不会返回成功。

### 4.5 tombstone

顶层 `tombstones` 只保存已明确关闭 attempt 的：

- `task_id`、`attempt`、可选 `task_ref`。
- 可选 Agent ID/canonical path。
- 有界 `last_state`、`close_reason` 和整数 `closed_at`。

没有明确关闭事实的记录不能成为 tombstone。固定保留期直接读取机器语义 `retention_seconds.tombstone=604800`。清理只接受精确 `task_id + attempt`，并可调用同样精确的 result 删除回调；不做文件名模糊匹配、目录年龄批量删除或后台清理。

## 五、锁、CAS、原子写入与安全策略

### 5.1 稳定锁

- 每个 Session 使用稳定 `<safe-session>.lock`。
- 锁文件使用 `O_NOFOLLOW`（平台支持时）打开，随后 `fstat` 核对普通文件和当前用户所有者，再设置 `0600`。
- 所有读、写、CAS、删除和 tombstone 清理都持有同一把独占 `flock`。
- 删除 Session JSON 时保留 `.lock`；不实现自动锁回收。

### 5.2 compare-and-set

新增显式 `compare_and_set(session_id, predicate, callback, ...)`：

1. 锁内读取当前状态。
2. 按本次操作声明的顶层必需字段校验。
3. 执行 predicate；不满足时抛出稳定冲突异常，不调用 callback、不更新 `updated_at`、不写文件。
4. predicate 满足后执行 callback。
5. 校验容量，原子写入并回读核对。
6. 只有全部成功后返回 callback 结果。

旧 `update()` 作为无条件 CAS 的兼容包装保留；后续状态机必须使用显式 CAS 表达 expected task/attempt/计数/状态。

### 5.3 原子替换与回读

- 在状态文件同目录创建随机临时普通文件，设置 `0600`。
- 写入完整 UTF-8 JSON、flush、`fsync` 文件。
- `os.replace()` 原子替换目标，再 `fsync` 父目录。
- 重新通过同一安全读取路径读取目标，核对结构和完整内容与待写状态相等。
- 任一写入、替换、目录同步或回读核对失败都抛错；调用方不得声称转换成功。

### 5.4 已有状态读取

- 不存在的状态文件可返回新的最小空状态；这是唯一合法的“空 Session”。
- 已存在文件必须是当前用户拥有、权限不向 group/other 开放的普通文件，且不超过4 MiB。
- JSON 必须是 UTF-8 对象，`session_id` 必须存在并精确匹配。
- 本次操作声明需要的字段缺失或类型错误时逐项报错。
- 未声明为本次操作所需的字段不做全量迁移或补默认；未知额外字段保留。
- 损坏、非 UTF-8、根结构非法、非普通文件、所有者/权限异常和超限均保持原文件原位并返回失败；不移动、不覆盖、不写空状态。

## 六、容量与清理

### 6.1 3 MiB / 4 MiB

- `NEW_TASK_SOFT_LIMIT_BYTES = 3 * 1024 * 1024`。
- `MAX_STATE_BYTES = 4 * 1024 * 1024`。
- 标记为“新任务准入”的写入，在 callback 后预计 JSON 超过3 MiB时拒绝且不替换原文件。
- 已有任务更新可以使用剩余空间，但超过4 MiB时拒绝且不替换原文件。
- 不截断字段、不删除任务、不隐藏 action-required 记录来满足容量。

### 6.2 删除旧通用裁剪

删除 `MAX_TERMINAL_RECORDS`、`TERMINAL_RETENTION_SECONDS` 和通用 `_prune_state()`。旧 `complete/blocked/failed/needs_decision/platform_error` 等记录不再按时间或数量删除。生命周期是否已明确关闭只由 tombstone/后续显式处置表达。

### 6.3 tombstone 精确清理

- 只清理 `closed_at <= now - 604800` 的合法 tombstone。
- 未满7天、字段缺失/非法或未知额外记录均不删除；非法记录明确报错，避免猜测。
- 提供 `result_cleanup(task_id, attempt)` 回调时，先在锁内对精确 tombstone 调用；失败则保留 tombstone并整体报错。
- result 删除成功但状态回写失败时整体仍报错；tombstone 保留，后续清理可幂等重试。
- Session JSON 是否为空并可删除由 WP-06 判断；本阶段清理方法只返回清理结果，不自动删除 `.lock`。

## 七、新旧接口切换与兼容桥

### 7.1 本阶段原子切换

- StateStore 读取不再隔离损坏文件或 `setdefault` 补事实。
- 所有 StateStore 写入统一走稳定锁、容量检查、原子替换和回读验证。
- `update()` 改为 CAS 原语的包装；新增显式 `compare_and_set()`。
- 新空状态增加 `tombstones`，不写版本。
- 通用 terminal 裁剪退出全部写路径。
- 提供 `initial_attempt_state()`、`cleanup_expired_tombstones()` 和精确 result cleanup 回调边界。

### 7.2 临时兼容桥

- WP-03 前：`_handle_spawn()` 仍从旧 task name/正文创建平面记录；兼容记录附带 `attempt=1` 和 WP-01 初始状态字段，但不生成 task ref、PreparedContract 或目标嵌套结构。WP-03 以正式 task/attempt 创建接口原子替换。
- WP-04 前：旧通信、恢复和 interrupt 分支继续读取 `status/recovery_count`；不得新增新的混合状态。WP-04 使用 CAS 和精确 Agent→attempt 映射原子替换。
- WP-05 前：旧自由文本 Stop 结果片段继续作为运输桥，不进入 StateStore 新接口或 tombstone 清理。WP-05 用正式 result 引用替换。
- WP-06 前：旧12小时恢复摘要和 SessionEnd 删除逻辑继续存在，但 StateStore 不再替它们裁剪记录；明确关闭、全量 attempt tombstone 和 Session JSON 删除责任由 WP-06 原子接管。
- WP-07 前：`_diagnose()` 仍有副作用/绕过统一解析的旧路径，本阶段不扩大；WP-07 必须改用 StateStore 只读解析器。

## 八、先失败后通过的测试计划

### 8.1 先建立失败证据

新增或改写最小测试，先在修改前运行并确认失败：

1. 损坏和非 UTF-8 文件必须留在原位并抛错；当前实现会移动后重建。
2. 已有状态缺少 `tasks` 或当前操作声明的字段必须报错；当前实现会 `setdefault`。
3. blocked/failed/needs_decision 等未解决记录不受30天/200条裁剪；当前实现会删除。
4. 新任务写入超过3 MiB应拒绝，已有任务更新在4 MiB内允许；当前没有软线。
5. 原子替换后回读失败必须抛错；当前没有回读。
6. CAS predicate 冲突不调用 callback、不更新文件；当前没有通用原语。

### 8.2 完整定向覆盖

- 多进程并发写入不丢记录。
- CAS 冲突不覆盖并发新状态。
- 损坏、非 UTF-8、非普通文件、所有者/权限异常和超限均不被当作空状态。
- 3 MiB新任务软准入、4 MiB硬上限和原文件不变。
- 未解决记录不因时间或数量裁剪。
- tombstone 只清理明确关闭且已满7天的精确 attempt；未满7天和普通任务保留。
- result cleanup 只收到精确 task_id/attempt；失败时 tombstone 保留。
- Session JSON 删除或 tombstone 清理后 `.lock` 仍存在。
- 临时文件写入、`os.replace` 或回读验证失败均不返回成功。
- 已有状态缺少当前操作必需字段明确报错；未知额外字段读取和后续写入保持。
- `initial_attempt_state()` 与机器语义和 `AttemptState().to_record()` 完全一致。
- WP-01 语义基线和旧 Hook 运输桥回归继续通过。

## 九、文件级实施步骤

1. 新建本文，记录修改前结构、读写者、范围、接口和测试计划。
2. 新增 `tests/test_state_store.py` 集中覆盖缺字段、损坏/非 UTF-8、非普通文件、所有者/权限、容量、原子替换、回读失败和 tombstone；在 `tests/test_governance.py` 改写与旧损坏恢复/通用裁剪目标冲突的 Hook 断言。
3. 在 `tests/test_concurrency.py` 增加显式跨进程 CAS 冲突与并发更新证据。
4. 重构 `scripts/subagent_governance.py` 的 StateStore：稳定锁验证、安全读取、容量编码、原子替换、回读核对、CAS、tombstone 清理和 UnavailableStateStore 接口。
5. 让旧 `update()`/`delete_if()` 消费新安全原语；仅做保持现有 Hook 消费者可运行所需的最小适配。
6. 删除通用 terminal 裁剪常量和调用；新建状态不写版本并增加 tombstones。
7. 运行 WP-02 定向测试，修复所有与目标边界冲突的旧断言。
8. 运行全量测试、编译、Plugin validator、Schema/fixture 校验和 `git diff --check`。
9. 将实际修改、验证结果、`not_checked` 和 WP-03 交接同步回本文。

## 十、验证命令

```text
python3 -m unittest -v <WP-02 StateStore 定向测试>
python3 -m unittest -v tests.test_concurrency
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
python3 $HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
JSON Schema 与 fixture 确定性校验
git diff --check
```

本阶段不修改 Skill 或分发资产时，Skill validator 为 `not_applicable`；若实际修改这些文件，则补跑并记录。

## 十一、not_checked 项

仓库内无法证明，统一标记 `not_checked`：

- 真实 Codex Hook 多进程在平台文件系统上的锁调度顺序。
- 平台进程被强制终止时 `fsync + os.replace + directory fsync` 的宿主机持久化保证。
- 原生调用已发生、随后 StateStore 写入/回读失败时，系统消息是否稳定到达父任务。
- 真实 SessionStart/Stop/SessionEnd 在损坏状态上的平台重试、展示和用户决策链；完整规则属于 WP-06。
- 正式 result 文件与 tombstone 的真实同步清理；WP-02 只验证精确底层回调，正式结果存储属于 WP-05。

## 十二、退出条件

WP-02 只有在以下条件同时满足时退出：

1. 本文与实际实施同步。
2. StateStore 新写入无版本字段，初始 attempt 状态读取 WP-01 机器语义。
3. 损坏、非 UTF-8、非普通文件、所有者/权限异常和超限状态保持不可用且原文件不被伪装为空。
4. 稳定锁、CAS、3/4 MiB、原子替换、目录同步和回读验证均有测试证据。
5. 通用 terminal 裁剪退出写路径；未解决任务不按时间、数量或容量删除。
6. tombstone/result cleanup 只针对明确关闭、满7天的精确 attempt，且 `.lock` 保留。
7. 没有实现 WP-03～WP-08 的业务状态机；兼容桥已标明退役工作包。
8. 所有适用本地验证通过，真实平台项如实标记 `not_checked`。
9. 没有 stage、commit、push、发布、安装或无关修改。

## 十三、交给 WP-03 的稳定接口与不可重新解释语义

稳定接口：

- `StateStore.read(session_id, required_fields=...)`：锁内安全读取；不存在与不可读严格区分。
- `StateStore.update(session_id, callback, required_fields=..., admission=...)`：无条件写包装，成功前完成原子替换和回读。
- `StateStore.compare_and_set(session_id, predicate, callback, ...)`：冲突不写，供 task/attempt、Agent绑定和计数转换使用。
- `StateStore.initial_attempt_state()`：等于 WP-01 `AttemptState().to_record()`。
- `StateStore.cleanup_expired_tombstones(...)`：7天、精确 task/attempt、可插入 result cleanup 的底层能力。
- `StateConflictError`、`StateCapacityError`、`StateValidationError`、`StateWriteError`：区分输入/冲突/容量/持久化失败，调用方不得统一当作成功或空状态。

WP-03 不得重新解释：

- 不增加协议版本或迁移门禁。
- 不使用 `setdefault` 补造已有状态事实。
- 新 attempt 只能使用 WP-01 的 null/枚举/计数初值。
- 3 MiB只限制新治理任务；4 MiB限制所有状态文件写入。
- StateStore/PreparedContract 任一门禁失败时，WP-03 governed spawn 必须在原生调用前拒绝；本阶段保留的旧 spawn fail-open 运输桥必须由 WP-03 原子退役。
- Agent 映射必须落到精确 task/attempt；不得复用旧的同名、同轮或唯一候选猜测。
- `.lock` 不随 Session JSON 删除。

## 十四、实施结果

### 14.1 修改前失败证据

在运行时代码修改前执行 WP-02 定向测试，25 项中出现5项失败、18项错误，稳定证明：

- 当前损坏/非 UTF-8 文件会被移动到 `.corrupt-*` 并重建状态。
- 240条旧 blocked/failed/needs_decision 记录会被通用裁剪清空。
- StateStore 缺少显式 CAS、3 MiB软准入、回读验证、tombstone 和分型异常接口。
- 已有状态缺字段会被 `setdefault` 补造。

这些失败来自目标测试对现状错误的直接断言，不是依赖随机时序的测试。

### 14.2 实际修改文件

- `scripts/subagent_governance.py`
  - 新增 `StateStoreError`、`StateValidationError`、`StateCapacityError`、`StateConflictError` 和 `StateWriteError`。
  - 新增3 MiB新任务软准入线；保留4 MiB硬上限，并在安全读取后再次按实际字节数检查。
  - 新空状态增加 `tombstones`，继续不写版本字段；`initial_attempt_state()` 直接复制 WP-01 `AttemptState`。
  - 锁文件在 `O_NOFOLLOW` 可用时使用该标志，打开后用 `fstat` 核对普通文件和当前所有者，并固定为 `0600`。
  - 已有状态用安全文件描述符读取，核对普通文件、所有者、权限、实际字节数、UTF-8 JSON、精确 session 和本次操作必需字段；未知额外字段保留。
  - 删除损坏文件隔离/空状态恢复、`setdefault` 补事实、30天/200条通用 terminal 裁剪。
  - 新增锁内 `compare_and_set()`；冲突不调用 callback、不更新 `updated_at`、不写文件。
  - 所有写入使用同目录临时文件、`0600`、文件 `fsync`、`os.replace`、目录 `fsync` 和安全回读全内容核对。
  - 新增7天精确 `cleanup_expired_tombstones()`，只接受匹配 key、`task_id`、`attempt`、关闭原因和关闭时间的记录，并提供精确 result cleanup 回调。
  - `delete()` / `delete_if()` 继续保留稳定 `.lock`。
  - 旧 spawn 运输桥新增 `attempt=1` 和 WP-01 十四项初始状态字段；未实现 task ref、PreparedContract 或 spawn 硬门禁。
  - 旧 list-agents 桥只保存允许字段的有界平台摘要，不再把任意完整 `agent_status` 对象写入 StateStore。
- `tests/test_state_store.py`
  - 新增26项 StateStore 安全测试，覆盖最小空状态、初始值、损坏保全、权限/所有者/普通文件、缺字段、未知字段、3/4 MiB、CAS、写入/替换/回读失败、tombstone、result cleanup 和稳定锁。
- `tests/test_concurrency.py`
  - 保留32进程并发派发不丢记录测试；新增两个进程竞争同一 CAS 时恰好一个提交、一个冲突的测试。
- `tests/test_governance.py`
  - 将损坏/非 UTF-8 Hook 断言改为原文件保留且旧 spawn 桥明确降级。
  - 将通用 terminal 裁剪断言改为240条记录完整保留。
  - 断言旧 spawn 兼容记录读取 WP-01 attempt 初值；非错误平台观察只保存最小摘要。
- 本方案文档。

没有修改 Schema、Skill、分发资产、发布工具、稳定源、Marketplace、运行缓存、Hook trust 或 Registry。

### 14.3 新旧路径实际边界

- StateStore 安全主路径已经切换到稳定锁、显式字段要求、CAS、3/4 MiB、原子替换和回读验证；所有现有 `update()` 写入都消费该主路径。
- 旧 Hook 平面 `status`、字符串 Agent→task 映射、旧 `tool_use_id/turn_id/task_name` 关联和有界 `legacy_free_text` 结果片段继续作为运输桥；本阶段没有扩展其业务语义。
- WP-03 必须用精确 task/attempt、PreparedContract 和 spawn 门禁替换旧 spawn/身份桥，并开始对新任务使用 `admission="new_task"`。
- WP-04 必须让通信、恢复和 interrupt 使用 `compare_and_set()`，退役旧混合状态转换。
- WP-05 必须删除内嵌 `legacy_free_text` 结果片段，改用正式结果文件引用。
- WP-06 必须接管明确关闭、全 task/attempt tombstone、SessionEnd/Stop 和结果同步清理；本阶段只提供底层精确清理能力。
- WP-07 必须替换当前诊断的副作用/直读路径；本阶段没有提前重写诊断。

### 14.4 验证结果

```text
python3 -m unittest -v tests.test_state_store tests.test_concurrency
  28 tests, OK

python3 -m unittest discover -s tests -v
  192 tests, OK

python3 -m py_compile scripts/subagent_governance.py
  passed

python3 $HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
  Plugin validation passed

python3 $HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
  Skill is valid

JSON/fixture deterministic validation
  3 schemas and 5 fixtures parsed; local refs, JSON pointers, and regex patterns validated

git diff --check
  passed
```

Skill/资产未由 WP-02 修改；Skill validator 仍额外执行并通过。

### 14.5 not_checked 与剩余风险

- 第十一节的真实 Codex 平台项目全部为 `not_checked`。
- 本地多进程测试证明同一文件系统内的锁和 CAS 行为，不能替代真实 Hook 调度、进程强杀、宿主机断电或平台消息展示证据。
- 旧 Hook 运输桥仍会把平面 `status` 和有界 `legacy_free_text` 结果片段写入同一状态文件；这是 WP-03～WP-06 前的兼容负担，不是新 StateStore 接口。它没有被扩展为 target task/attempt 状态机。
- 正式 result 文件尚未实现，因此当前只验证 result cleanup 回调收到精确 `task_id + attempt`，不能声称已经完成真实结果文件同步清理。
- 4 MiB写入拒绝通过异常向调用方保留 degraded/人工对账事实；如何把该事实映射为目标 `parent_action=manual_review` 属于后续状态机工作包。

### 14.6 退出结论

WP-02 本地退出条件已满足：方案与实施同步；StateStore 使用 WP-01 初始语义；不可读状态不再伪装为空；通用 terminal 裁剪退出；稳定锁、CAS、3/4 MiB、原子替换、回读验证和7天精确 tombstone/result cleanup 均有测试；没有提前实现 WP-03～WP-08；适用本地验证全部通过；真实平台项目明确为 `not_checked`。
