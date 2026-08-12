# WP-03 确定性派发与身份绑定详细改造方案

## 一、状态、目标与前置边界

- 工作包：WP-03「确定性派发与身份绑定」。
- 权威来源：`docs/project-function-inventory.md`，重点是 U-01～U-03、U-05、U-06、U-08～U-10，SG-F01 全章，SG-F02 的 governed/unmanaged 接入边界，SG-F03 的任务关联，SG-F05 的派发观察、身份、PreparedContract、unknown 与迟到绑定，以及第十三节 OR-01、OR-02、OR-06、OR-09、OR-10 和第十八节 WP-03。
- 前置依赖：WP-01 的 `MACHINE_SEMANTICS`、`TaskFeatures`、`TaskContract`、`AttemptState`、`resolve_governance_mode()`、`validate_task_contract()`；WP-02 的 `StateStore.read/update/compare_and_set()`、`initial_attempt_state()`、分型异常、稳定锁、3/4 MiB、原子替换与回读验证。
- 唯一目标：建立结构化任务输入到原生 `spawn_agent` 参数的确定性生成入口，并让 governed spawn 在发送前通过 PreparedContract 与初始 StateStore 双门禁，再以 task ref、有限响应适配器和精确 `SubagentStart` 完成 Agent ID/canonical path 绑定。
- 当前状态：方案已创建；实施完成后将在本文末尾同步实际修改、失败基线、验证结果、`not_checked` 和 WP-04 交接。

本阶段不实现 WP-04 的通信 pending action、平台恢复、结果补交、business resume 或 interrupt 状态机；不实现 WP-05 正式结果与父验收；不实现 WP-06 完整等待、Session/Stop、多 attempt 选择和整 task 关闭；不实现 WP-07 诊断/group；不执行 WP-08 发布、安装或外部清理。

## 二、现状链路、消费者与可复现问题

### 2.1 当前派发链

当前 `_handle_spawn()`：

1. 要求旧名称 `sg_<resolved_mode>_<semantic_name>`。
2. 读取 message，判断 opaque/plaintext，并从正文提取目标、范围、完成条件和上下文。
3. 由 `session_id + turn_id + tool_use_id` 生成旧 task ID。
4. 向业务 message 追加治理信封。
5. 写入平面 legacy task；StateStore 写入失败时仍允许原生 governed spawn。

当前 `_handle_post_tool()`：

- 通过 `tool_use_id`，随后回退到 task name、turn 和唯一候选定位任务。
- `_extract_values()` 递归搜索任意嵌套身份字段。
- `_response_failed()` 递归搜索任意状态，并按字符串前缀猜测失败。
- spawn 没有可靠身份时仍直接写 `status=running`。

当前 `_handle_subagent_start()`：

- 已有 Agent 映射可直接恢复。
- 无映射时 `_assign_starting_agent()` 会把唯一未绑定候选分配给任意新 Agent。
- 启动事件没有 task ref 精确绑定主路径。

### 2.2 全部直接消费者

- `PreToolUse`：`_handle_spawn()` 当前创建 legacy task 并改写正文。
- `PostToolUse`：`_spawn_record()`、`_response_failed()`、`_extract_values()` 和 spawn 分支写派发/身份事实。
- `SubagentStart`：`_assign_starting_agent()`、`_handle_subagent_start()` 写 Agent 映射与 running。
- `_resolve_task_id()`：通信和 `list_agents` 使用 Agent/canonical path 关联；当前还包含 canonical 同名回退。
- `SubagentStop`、Stop、SessionStart、SessionEnd：仍消费 legacy 平面 `status`；WP-03 不能先删除这些消费者所需的兼容读取能力，但新 governed 记录不得继续写混合 status 或进入弱身份路径。
- `hooks/hooks.json`：PreToolUse、PostToolUse 与 SubagentStart 已接线，无需新增 Hook 类型。
- fixture 与测试：`tests/test_governance.py`、`tests/test_hook_fixtures.py`、`tests/test_concurrency.py`、`tests/test_state_store.py`、`tests/test_semantic_baseline.py` 和五个 lifecycle fixture 直接覆盖当前链路。

### 2.3 修改前最小失败证据

先增加并运行以下目标测试，确认旧实现失败：

1. 结构化生成器不存在，无法从 raw TaskContract 机械解析 auto、上下文和可空 model/effort。
2. 目标 task name、task ref 有界碰撞、64 字符长度和 PreparedContractStore 不存在。
3. governed spawn 仍接受旧 task name，并在 StateStore 不可写时 fail-open。
4. unmanaged spawn 当前被拒绝而不是兼容放行。
5. PostToolUse 对任意递归响应和错误字符串进行猜测，且 success 无身份时写成 running。
6. SubagentStart 会把唯一未绑定候选分配给无 task ref 的任意 Agent。

这些测试只证明 WP-03 现状缺口，不提前覆盖 WP-04～WP-07 状态机。

## 三、允许与禁止范围

### 3.1 允许修改

- `scripts/subagent_governance.py` 的确定性生成、PreparedContract、task ref、spawn Pre/PostToolUse、响应适配和 SubagentStart 精确绑定路径。
- `skills/subagent-governance/SKILL.md`、`references/governance-levels.md`、`references/runtime-boundaries.md` 中 WP-03 已落地边界。
- `hooks/hooks.json` 仅在 matcher 或当前事件接线确有缺口时修改；不把状态机放入配置。
- 新增 WP-03 定向测试与 fixture，并原子改写已被新主路径替代的旧断言。
- 同步本文。

### 3.2 明确禁止

- 不实现四类通信的两阶段 `pending_action`、恢复授权、补交或 business resume。
- 不实现正式 result 文件、SubagentStop 结构化结果提交、父验收或 disposition。
- 不实现完整 action-required/Stop/Session 生命周期、多 attempt 选择、重复执行处置或整 task tombstone 流程。
- 不实现诊断重写、group、后台 scheduler、自动 wait/list/follow-up/interrupt。
- 不根据 Provider、加密、解密或错误文本推断根因。
- 不 stage、commit、push、发布、安装；不写稳定源、Marketplace、运行缓存、Hook trust 或 Registry。

## 四、确定性生成器输入与输出

### 4.1 输入

生成器接收：

- `session_id`。
- AI 提交的 TaskContract 业务字段；`semantic_name` 可为待规范化文本，`requested_mode` 与其余 WP-01 字段必须存在。
- 可选的已存在 `task_id + attempt` 仅用于明确 failed 后的同 attempt spawn retry；新任务默认由生成器创建 task ID、`attempt=1`。
- 第二次也是最后一次同 attempt 重派需要显式授权标记；unknown 不允许走 retry 入口。

生成器先规范化 semantic name，再机械解析 `requested_mode → resolved_mode/resolution_reason`，构造完整 `TaskContract` 并调用 WP-01 validator。若调用者提供派生字段，必须与机械解析结果一致。

### 4.2 输出

返回一个纯结构化派发包：

- `task_id`、`attempt`、`task_ref`、`task_name`。
- 规范化后的完整 TaskContract。
- 用户可见派发说明。
- 子 Agent 完整首句 `message`。
- 原生 spawn 参数：`task_name`、`message`、上下文参数，以及仅在显式提供时出现的 `model`、`reasoning_effort`。

上下文映射固定为：

- isolated → `fork_turns="none"`，用户显示“否”。
- limited → `fork_turns="<N>"`，用户显示“否（仅继承最近 N 轮）”。
- full → `fork_turns="all"`，用户显示“是”。

`model=null/省略` 与 `reasoning_effort=null/省略` 时，原生参数省略对应键；用户说明分别显示固定继承文案，不猜测实际值。

### 4.3 固定渲染职责

- AI 提供目标、背景、范围、限制、完成条件、证据要求、文件和当前状态等业务内容。
- 生成器只按固定顺序渲染用户说明与 dispatch prompt，不分类正文、不评分内容、不补造业务事实。
- prompt 不写 task ref、prepared ref 或内部存储路径；task name 是原生参数中唯一契约查找引用。

## 五、task ID、semantic name、task ref 与名称算法

1. 新 task ID 使用有界随机 ID；尚未持久化前允许因32位 task ref 碰撞废弃并重新生成一次。
2. semantic name 转小写；非字母数字转换为下划线；连续下划线合并；首尾下划线删除；空值回退 `task`。
3. 规范输入固定为 `<task_id>:<attempt>`，计算 SHA-256 小写十六进制。
4. 按12、16、20、24、28、32位依次检查当前 Session 的 PreparedContract、StateStore task/attempt 和7天 tombstone。
5. 32位仍碰撞时，若为尚未持久化的新 task，重新生成一次 task ID 并从12位重试；第二个 task ID 仍不能取得唯一 ref 时拒绝。
6. 既有 `task_id + attempt` 的引用稳定不变；同 attempt retry 不换引用。
7. 名称固定为 `sg_<resolved_mode>_<semantic_name>_t_<task_ref>`，最多64字符；超长时只截断 semantic name，保留合法首尾且不截断 mode、`_t_` 或 task ref。

## 六、PreparedContract 结构、存储和有效期

### 6.1 私有存储

- 使用 governance data 根下的 `prepared/` 私有目录，并按 Session 安全隔离。
- 每个 task ref 一份普通 JSON 文件和稳定 Session 锁；目录0700、文件0600，拒绝符号链接、所有者异常和不安全权限。
- 使用同目录临时文件、fsync、`os.replace`、目录 fsync 和安全回读全内容核对。
- 不新增 `prepared_ref`；文件查找只使用 `session_id + task_ref`。

### 6.2 极简记录

PreparedContract 只保存派发与初始绑定需要的事实：

- `session_id`、`task_id`、`attempt`、`task_ref`。
- `task_name`、`resolved_mode`。
- 完整规范化 TaskContract。
- 原生可观察参数摘要：上下文参数、可选 model/effort、dispatch prompt 摘要。
- `created_at`、`consumed`、可空 `tool_use_id`、`claimed_at`、`post_observed_at`。

不保存通信历史、平台响应、版本字段、prepared ref、事件历史或结果。

### 6.3 两阶段有效期

- 未消费记录固定5分钟。过期时拒绝派发，并精确删除 PreparedContract 与仍保持 WP-01 初值、没有 claim/观察/身份的初始空 attempt；不生成 tombstone。
- PreToolUse 校验成功后记录 `consumed=true + tool_use_id + claimed_at`；已消费记录不能按5分钟规则删除。
- consumed 后缺少 PostToolUse：未满20分钟保持 `spawn_observation=null + parent_action=null`；满20分钟在正常 SessionStart/读取/显式对账入口写 `spawn_observation=unknown + identity_status=unconfirmed + execution_status=not_started + parent_action=reconcile`，继续保留 PreparedContract。
- 身份确认、可靠 failed、显式替代 attempt 或明确关闭后才按相应规则删除/替换 consumed 记录。本阶段只实现身份确认和可靠 failed/retry 所需部分，不建设后台清理器。

## 七、初始 StateStore 记录与双硬门禁

新任务使用 `admission="new_task"`，写入：

- `task_id`、`attempt=1`、`task_ref`、`task_name`。
- `semantic_name`、`requested_mode`、`resolved_mode`、`resolution_reason`。
- 有界契约摘要：objective、work/forbidden scope、completion conditions、evidence requirements、relevant files、current state、必要恢复提示。
- WP-01 `initial_attempt_state()` 的十四个字段。
- `created_at`、`updated_at` 和可空 claim/Agent字段。

Agent 映射固定为精确 target → `{task_id, attempt}`，不能只映射 task ID。

双门禁顺序：

1. 生成并验证 TaskContract、task ref、task name 和原生参数。
2. 原子写 PreparedContract并回读。
3. 用 `admission="new_task"` 原子创建 StateStore 初始记录并回读。
4. 再次核对两个存储中的 `session_id/task_id/attempt/task_ref/resolved_mode/task_name`。
5. 只有全部成功才返回可调用的 spawn 参数。

任一步失败都不允许调用原生 spawn；若第一份存储已写，执行精确补偿清理并报告原始失败，不能降级为 unmanaged。

## 八、PreToolUse 门禁与 governed/unmanaged 分流

- 无 `sg_` 前缀：unmanaged 兼容放行，保持原生参数，不创建任务、PreparedContract 或 Agent 映射，不进入 Stop/结果验收。
- 以 `sg_` 开头但不符合目标正则：拒绝，不降级。
- 合法目标名称：解析 resolved mode 与 task ref，读取 PreparedContract 和 StateStore 精确 attempt，核对 resolved mode、task name、上下文、可选 model/effort 等原生可观察参数。
- PreparedContract 缺失、不可读、过期、已消费、篡改，或 StateStore 缺失/不一致时拒绝。
- 校验通过后在发送前完成 PreparedContract consumed 标记与 StateStore claim 写入；任一写入或回读失败都拒绝，并尽力回滚另一侧 claim。
- message 可能被原生传输处理；Hook不做明密文分类，不从 message 恢复业务字段，也不把正文可见性写入状态。

## 九、PostToolUse 派发观察与有限响应适配器

### 9.1 关联

- 只用 PreToolUse 已保存的 `tool_use_id` 定位 consumed PreparedContract 和精确 task/attempt。
- 不回退到同名、同轮、唯一候选或任意候选。
- task name 可作为一致性复核，但不能替代 claim。

### 9.2 响应适配器

只读取明确支持的有限形状：

- 顶层原生结果对象的 Agent ID/canonical path/task path 字段。
- 已确认存在的单层结构化结果容器中的同名字段。
- 顶层明确的 success/failed 标记。

不递归遍历任意嵌套字段，不根据自由错误字符串或 Provider关键词判断失败。未知形状返回 `observation=unknown` 且不绑定身份。

### 9.3 状态转换

- failed：只在适配器取得可靠失败事实时写 `spawn_observation=failed`。首次失败且 count=0 → `parent_action=retry_spawn`；第一次 retry 失败且 count=1 → `parent_action=ask_user`；第二次 retry 失败且 count=2 → 写 `execution_status=stopped + parent_action=decide_disposition` 和 `spawn_retry_exhausted` attempt tombstone，不写业务 failed，也不关闭整个 task。retry 认领在下一次原生调用前增加计数，调用 failed/unknown 不回退。
- unknown：写 `spawn_observation=unknown + identity_status=unconfirmed + execution_status=not_started + parent_action=reconcile`；不得自动重派、关闭或改为 running。
- success 无身份：写 `spawn_observation=success + identity_status=unconfirmed + execution_status=not_started + parent_action=reconcile`。
- success 有可靠身份：精确绑定 Agent ID/canonical path，写 `identity_status=confirmed + execution_status=running + platform_observation=normal + recovery_status=null + parent_action=wait`。

可靠身份确认后，StateStore 已保留最小摘要；随后删除完整 PreparedContract。删除失败只输出 degraded 告警，不回滚真实身份或伪造 spawn 失败。

## 十、SubagentStart 精确身份绑定与迟到事件

- 首选已有 Agent ID/canonical path → `{task_id, attempt}` 映射。
- 未映射启动只在事件明确携带合法 task name/task ref 时，通过 StateStore/仍保留的 PreparedContract 精确定位 attempt。
- 删除唯一候选、最近候选、同名、同轮和任意候选绑定。
- 精确启动可以把 `spawn_observation=null|success|unknown` 的未确认 attempt 推进为 confirmed/running/normal/wait，并删除 PreparedContract。
- 已确认映射的重复启动幂等。
- 没有 task ref 且没有既有映射的启动按 unmanaged/未映射放行，不创建半套治理状态。
- 已关闭或存在明确冲突的 attempt 不被迟到启动复活；本阶段只保留精确事实与 reconcile，完整重复执行选择留给 WP-06。

## 十一、明确失败重派、unknown 与迟到绑定

- 同 attempt 明确失败重派沿用 task ID、attempt、task ref 和 task name。
- 首次原生调用不计入 `spawn_retry_count`；第一次重派认领写1；用户授权最后一次重派认领写2。
- 任何 retry 调用 unknown 后禁止继续复用该 attempt 重派。
- unknown 后若父 Agent/用户接受重复执行风险，必须由后续业务入口创建新 attempt 和新 task ref；WP-03只保证旧 attempt继续保留迟到绑定事实，不实现多 attempt 选择。
- 迟到 `SubagentStart` 按自己的 task ref 绑定原 attempt，不能因 current attempt、时间顺序或同名改绑。
- 缺失 PostToolUse 的20分钟转换与上述 unknown 使用同一状态，不自动创建替代 attempt。

## 十二、新旧路径原子切换

本阶段一次完成：

- 生成器成为所有新 governed spawn 的唯一合法入口。
- PreToolUse 删除正文读取、opaque/plaintext分类、治理信封注入和 legacy task 创建。
- 目标 task name 正则替换旧名称；合法旧 `sg_<mode>_<name>` 不再作为 governed 兼容桥。
- StateStore 新任务 fail-open 退出；unmanaged 无前缀调用成为唯一兼容放行路径。
- PostToolUse 删除 `_spawn_record()` 的同名/同轮候选回退、递归 `_extract_values()` 和递归/字符串 `_response_failed()`。
- SubagentStart 删除唯一候选分配。

为避免先删消费者：

- 通信、SubagentStop、Stop 和 Session 旧逻辑保留对 legacy 平面记录的兼容读取。
- 新 governed task 使用独立状态维度；WP-03只增加最小适配，让现有 Stop/Session 不会误删或忽略 running、identity-unconfirmed 和 reconcile 任务，不提前实现完整 WP-06。
- unmanaged 调用始终不创建上述记录，因此不会进入旧 Stop/结果路径。

## 十三、测试计划

### 13.1 定向生成与存储

- structured auto 的 light/standard/strict。
- isolated/limited/full 三种上下文和 null model/effort 省略。
- semantic name 规范化、64字符名称、task ref 12/16/20/24/28/32碰撞与二次 task ID 失败。
- PreparedContract 私有目录、原子写、回读失败、消费、重复消费、5分钟过期和 consumed 不过期。
- 初始 StateStore `admission="new_task"`、WP-01 初值、最小摘要、双门禁回滚和 StateStore 失败硬拒绝。

### 13.2 Hook 与身份

- governed 目标名称通过双门禁；旧目标名称/伪造 ref/缺失 contract/参数不一致拒绝。
- unmanaged 无前缀 spawn 原样放行且不创建状态。
- PostToolUse success/failed/unknown；success 无身份保持 not_started/unconfirmed/reconcile。
- 缺失 PostToolUse 20分钟转换。
- 顶层已知响应形状绑定；未知/深层嵌套/错误字符串保持 unknown。
- SubagentStart 通过 task ref或已有 Agent 映射精确绑定；迟到启动；弱唯一候选不绑定；终态/冲突不复活。
- 身份确认后 PreparedContract 删除；删除失败只告警。
- Agent 映射同时覆盖 Agent ID 与 canonical path，并精确指向 task/attempt。

### 13.3 回归与边界

- WP-01 语义和 WP-02 StateStore 全部回归。
- 旧通信、终态、Stop/Session 运输桥在未被 WP-04～WP-06 接管前继续通过必要回归。
- fixture 更新为目标 task ref/prepared 链；opaque fixture 不再证明正文分类。
- 不出现 pending action、result 文件、parent disposition、完整等待巡检、group 或发布写入。

## 十四、文件级实施步骤

1. 新建本文并记录现状消费者、目标结构、切换顺序与测试计划。
2. 新增 `tests/test_dispatch_identity.py`，先运行并记录旧实现失败；同步改写直接冲突的旧 spawn/身份测试与 fixture。
3. 在运行时新增 semantic name、task ref、task name、用户说明、dispatch prompt 和上下文投影的纯函数。
4. 新增 PreparedContractStore 与5/20分钟精确清理/对账能力。
5. 新增新任务准备入口和可选 CLI，先写 PreparedContract，再以 `admission="new_task"` 创建并回读初始 StateStore；失败补偿清理。
6. 原子替换 `_handle_spawn()` 为 governed/unmanaged 分流和双门禁消费；不再读取或改写业务正文。
7. 用有限响应适配器和精确 claim 替换 PostToolUse 递归/候选关联，完成 observation 与身份转换。
8. 用 task ref/已有 Agent映射替换 SubagentStart 弱候选绑定，身份确认后删除 PreparedContract。
9. 对旧 Stop/Session/通信消费者增加仅维持 WP-03 记录可见性的最小兼容适配，不实现后续状态机。
10. 更新 Skill 与两个参考文件，删除“WP-03 后续实现”措辞并记录真实平台 `not_checked`。
11. 运行定向、全量、编译、Plugin/Skill validator、JSON/fixture 校验和 `git diff --check`。
12. 同步本文实施结果、验证、not_checked、退出条件和 WP-04 交接。

## 十五、not_checked

以下必须依赖真实 Codex，仓库测试不能替代：

- 原生 `spawn_agent` 对生成器 `fork_turns/model/reasoning_effort` 投影的真实接受形状。
- PreToolUse 是否始终能观察未加密 task name、上下文和可选 model/effort。
- 真实 PostToolUse spawn success/failed 响应字段与是否存在单层结构化容器。
- 真实 SubagentStart 是否稳定提供 task name/task ref、Agent ID 和 canonical path。
- PostToolUse 缺失、SubagentStart 迟到和 mailbox 事件的真实顺序。
- Hook trust、Plugin/Skill 加载与用户可见派发说明的真实展示。

无法证明的项保持 `not_checked`；本地 fixture 只证明适配器和状态转换，不宣称平台保证。

## 十六、退出条件

WP-03 只有同时满足以下条件才退出：

1. 本文与实施同步。
2. 结构化生成器使用 WP-01 resolver/validator，不读取业务正文分类。
3. task ref、名称长度和碰撞规则有确定性测试。
4. PreparedContract 与初始 StateStore 都在原生 spawn 前原子写入并回读；任一失败硬拒绝。
5. governed/unmanaged 边界明确；无前缀调用不创建半套任务，合法治理前缀缺少凭证时不降级。
6. PreToolUse 单次消费、5分钟未消费清理和20分钟 consumed unknown 对账成立。
7. PostToolUse success/failed/unknown 使用有限响应适配器；unknown 不自动重派或写 running。
8. success 无身份保持 not_started/unconfirmed/reconcile；可靠身份或精确 SubagentStart 才确认 running。
9. Agent ID/canonical path 精确绑定 task/attempt；弱候选猜测退出。
10. 身份确认后 PreparedContract 收缩删除，失败只告警。
11. 未提前实现 WP-04～WP-08；全部适用本地验证通过，真实平台项如实标记。

## 十七、WP-04 交接接口

WP-03 将向 WP-04 提供：

- `prepare_dispatch()` / 同 attempt spawn retry 准备入口，返回规范 TaskContract、用户说明和原生 spawn 参数。
- `PreparedContractStore` 的 read/write/consume/delete 与5/20分钟对账能力；WP-04 不得复用它保存通信。
- 目标 task record 中精确 `task_id + attempt + task_ref`、resolved mode、最小契约摘要和 WP-01 状态维度。
- `agents[target] = {task_id, attempt}` 的精确 Agent ID/canonical path 映射。
- 有限 spawn 响应适配器和 `spawn_observation` 转换。
- `parent_action=retry_spawn|ask_user|reconcile|wait|decide_disposition` 的 spawn 前置事实。

WP-04 必须另行实现并保持分离：

- `operation_type` 对应的两阶段 `pending_action`。
- normal message fail-open、platform recovery、result correction、business resume 和 interrupt 的 success/failed/unknown。
- `last_lifecycle_operation`、恢复/纠正计数认领及同 Agent跨 attempt 关联。
- 不得把 PreparedContract 当作通信凭证，也不得回退到正文或弱身份猜测。

## 十八、实施同步与验证结果

### 18.1 已实施主路径

- `scripts/subagent_governance.py` 已新增确定性生成器、task ref/name 纯函数、`PreparedContractStore`、`prepare_dispatch()`、`prepare_spawn_retry()` 和 `reconcile_prepared_dispatches()`。
- CLI 已提供 `--prepare-dispatch`、`--prepare-spawn-retry <task_id>` 和 `--authorize-final-retry`；输入为 TaskContract JSON，输出包含用户说明、完整首句和原生 `spawn_args`。
- 新任务先写入并回读 PreparedContract，再使用 `admission="new_task"` 创建并回读 StateStore。任一门禁失败都补偿清理已创建部分并拒绝返回可调用的 governed spawn 参数。
- PreToolUse 已原子替换旧运输桥：无前缀调用按 unmanaged 原样放行；合法 governed 名称只通过 task ref 读取并认领双门禁，不读取、分类或改写 message。旧 `sg_<mode>_<name>` 名称不再放行。
- PostToolUse 只通过 consumed PreparedContract 中的 `tool_use_id` 关联精确 task/attempt，使用有限响应适配器区分 success、failed 和 unknown；未知响应不递归搜索字段，也不根据错误文本推断 Provider 根因。
- success 无身份保持 `not_started + unconfirmed + reconcile`；可靠 Agent ID/canonical path 映射为 `{task_id, attempt}` 后才进入 `running + normal + wait`。
- `SubagentStart` 只接受已有精确 Agent 映射或事件中的合法 task name/task ref；同名、同轮、唯一候选和任意候选绑定已退出。unknown 后的迟到精确启动可绑定原 attempt；明确 failed、stopped、interrupted 或已有业务结果的 attempt 不被启动事件复活。
- 未消费 PreparedContract 满5分钟后精确删除契约和仍为空的初始 attempt；consumed 且缺少 PostToolUse 满20分钟后转换为 unknown/reconcile，但不建设后台 scheduler。
- spawn retry 在原生调用前认领并增加独立计数：首次 retry 写1，用户授权的最后一次 retry 写2；unknown 不回退计数也不能继续复用 attempt；最后一次明确 failed 写 stopped/decide_disposition、`spawn_retry_exhausted` tombstone，并停止同 attempt 重派。
- 身份确认或明确 failed 后删除完整 PreparedContract；删除失败只产生告警，不回滚已经确认的观察事实。
- 新 managed 记录不会被 legacy `list_agents`、follow-up、interrupt 或自由文本 SubagentStop 分支写入混合 `status`；WP-04/05 目标状态机仍未实现。

### 18.2 测试与 fixture 切换

- 新增 `tests/test_dispatch_identity.py`，覆盖 structured auto、三种上下文、可空 model/effort、task ref 有界碰撞、64字符名称、PreparedContract 原子写入/回读/消费/过期、双门禁失败、governed/unmanaged、spawn retry、success/failed/unknown、缺失 PostToolUse、未知响应、精确/迟到启动、弱候选退出和身份确认后契约收缩。
- `tests/test_concurrency.py` 已从并发旧 spawn 运输桥切换为32路并发生成，核对 StateStore、PreparedContract、task ID 和 task ref 均完整且唯一。
- `tests/test_governance.py` 中依赖正文分类、信封注入、旧 task name、递归响应和弱身份回退的断言已原子退出；WP-04～WP-06 尚未改造的 legacy 生命周期测试改为直接构造旧记录，不再依赖已退役 spawn 路径。
- `tests/test_hook_fixtures.py` 与相关 fixture 已切换到生成器注入的目标 task name/ref；opaque fixture 只证明正文不可见时仍以 task ref 门禁，不再证明正文分类。

### 18.3 已完成验证

- `python3 -m unittest discover -s tests -v`：194 tests，全部通过。
- `python3 -m py_compile scripts/subagent_governance.py`：通过。
- Plugin validator、Skill validator、JSON Schema/fixture 校验与 `git diff --check` 在最终验证步骤执行；结果以本任务最终回传为准。

### 18.4 保持 not_checked

第十五节列出的真实 Codex 参数、Hook 事件、响应字段、时序、trust 和展示行为仍为 `not_checked`。本地测试只证明确定性生成、持久化、Hook 关联和状态转换，不把 fixture 形状宣称为平台保证。

### 18.5 WP-03 退出与 WP-04 前置接口

WP-03 退出时的稳定前置接口为：

- `prepare_dispatch()` / `prepare_spawn_retry()` 输出的 TaskContract、用户说明、dispatch prompt 和原生参数。
- `PreparedContractStore` 的原子 create/read/CAS/delete、5分钟未消费清理和20分钟 claimed 对账。
- StateStore 中 `task_id + attempt + task_ref + resolved_mode + contract_summary` 及 WP-01 初始/派发观察维度。
- `agents[target] = {task_id, attempt}` 的精确 Agent ID/canonical path 映射。
- `adapt_spawn_response()` 的有限 success/failed/unknown 观察结果。
- spawn 产生的 `parent_action=retry_spawn|ask_user|reconcile|wait|decide_disposition` 和独立 `spawn_retry_count`。

WP-04 只能在这些事实之上新增通信与生命周期 operation，不得重开正文分类、弱身份猜测或 PreparedContract 复用；本任务不继续实施 WP-04。
