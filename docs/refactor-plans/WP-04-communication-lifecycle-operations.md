# WP-04 通信与生命周期操作详细改造方案

## 一、状态、目标与权威边界

- 工作包：WP-04「通信与生命周期操作」。
- 权威来源：`docs/project-function-inventory.md`，重点是 U-01、U-03、U-05～U-08，SG-F03 全章，SG-F05 的平台错误、恢复次数、`last_lifecycle_operation`、`SubagentStart` 授权和主动中断，SG-F06 的有限结果纠正，第十三节 OR-07、OR-08、OR-10、OR-12，以及第十八节 WP-04。
- 前置依赖：WP-01 的 `MACHINE_SEMANTICS`、operation types、call observations、独立次数上限、父动作和 attempt 初值；WP-02 的 `StateStore.read/update/compare_and_set()`、原子替换和回读验证；WP-03 的 PreparedContract 派发链、`task_id + attempt + task_ref`、精确 `agents[target]={task_id, attempt}` 和有限响应适配边界。
- 唯一目标：建立显式通信生成入口、两阶段 `pending_action`、四类通信和主动中断的发送前认领、success/failed/unknown 对账、有限预算、迟到启动授权和最小 lifecycle 证据。
- 当前状态：方案已创建；实施完成后在本文末尾同步实际修改、测试证据、`not_checked`、退出结论和 WP-05 交接。

本阶段不实现正式 result 文件、结果冲突、父验收、parent disposition、完整 Session/Stop/action-required 展示、多 attempt 选择、整 task 关闭、tombstone 生命周期编排、诊断/group 或发布安装。

## 二、现状分支、消费者与稳定缺口

### 2.1 当前通信链

当前 `_handle_communication()` 同时承担生成和 PreToolUse：

1. 从原生工具参数读取 `operation_type`、`purpose`、`reason`、`content` 和 `expected_result`。
2. 根据工具名限制 `send_message`，并从旧平面 `status` 判断用途。
3. 把 `operation_type`、治理 task ID 和协议化正文写入实际 message。
4. 对 legacy 平台错误在生成阶段直接改写 `status=needs_decision`；StateStore 失败时对 governed 恢复也降级放行。
5. 没有持久化、单次认领或 `tool_use_id` 绑定的通信凭证。

当前 `_handle_post_tool()`：

- follow-up 只根据工具名、target、是否 failed 和旧 `status=platform_error` 猜测恢复用途；成功后才增加 `recovery_count`。
- managed `list_agents` 被直接跳过，尚未写入 `platform_observation=error`。
- interrupt 没有 PreToolUse 生成/认领，PostToolUse 只要未明确 failed 就把 legacy task 写成 interrupted；unknown 会被误判为成功，成功中断也被旧 Stop 逻辑视作已闭环。
- `SubagentStart` 只处理 spawn 身份绑定；stopped/not_started 的 managed attempt 不接受 lifecycle operation 的精确授权。

### 2.2 直接消费者

- `PreToolUse`：spawn、send_message、followup_task；本阶段增加 interrupt_agent 的显式意图处理。
- `PostToolUse`：spawn、follow-up、list_agents、interrupt；本阶段增加 send_message 的调用对账。
- `SubagentStart`：消费匹配的 pending/last lifecycle operation，确认恢复、补交或 business resume 启动。
- `SessionStart`：顺带把过期 prepared action 删除，把超时 claimed action 转为 unknown；不增加 scheduler。
- Stop/Session 旧运输桥：仅补充 managed pending/lifecycle 可见性所需的最小兼容，不提前实现 WP-06。
- Skill、runtime boundaries、hooks matcher、communication/recovery/interrupt fixtures 和相关测试。

### 2.3 修改前最小失败证据

先新增定向测试并在运行时代码修改前确认以下缺口失败：

1. 通信生成器不存在，Hook 会从原生输入读取 operation type，并把 task ID/operation type 注入实际 message。
2. 同 target 没有 prepared/claimed 两阶段冲突保护，5分钟未认领和20分钟已认领对账不存在。
3. 平台恢复计数在 PostToolUse 才增加，failed/unknown 会错误返还预算；恢复、纠正和 spawn retry 没有统一的发送前原子认领证据。
4. managed `list_agents` 不写多维平台/执行状态，普通消息仍依赖旧 `status`。
5. `result_correction` 和 `business_resume` 被固定拒绝，没有独立次数、新 attempt 或三态转换。
6. interrupt 没有发送前意图；`status=running` 等未知响应会被误判为成功并直接退出 active set。
7. lifecycle success/unknown 清理后没有最小迟到启动凭证，failed/interrupt 与正常恢复启动没有机械区分。

## 三、允许与禁止范围

### 3.1 允许修改

- `scripts/subagent_governance.py` 的通信生成、pending action、Pre/PostToolUse、managed list_agents、interrupt 和 SubagentStart lifecycle 授权。
- `hooks/hooks.json` 的 Pre/Post matcher，使 interrupt 进入 PreToolUse、send_message 进入 PostToolUse。
- `skills/subagent-governance/SKILL.md` 和 `references/runtime-boundaries.md` 中 WP-04 已落地边界；`governance-levels.md` 只在核心枚举一致性需要时调整。
- 通信、pending、恢复、纠正、继续、中断、启动授权的定向测试和相关 fixture。
- 同步本文。

### 3.2 明确禁止

- 不实现 WP-05 的 result 文件、结果提交、冲突、父验收或 parent disposition。
- 不实现 WP-06 的完整 action-required、Stop 三次读取、Session 展示、多 attempt 选择、重复执行选择、整 task 关闭或 tombstone 编排。
- 不实现 WP-07 诊断/group，不执行 WP-08 退役/发布/安装/外部清理。
- 不建立 PreparedCommunication、communication ID、消息历史、投递/阅读/处理状态或后台 scheduler。
- 不读取或分类通信正文来判断 operation type，不递归猜测平台响应或 Provider 错误语义。
- 不 stage、commit、push、发布、安装，不写稳定源、Marketplace、运行缓存、Hook trust 或 Registry。

## 四、通信输入、输出与生成入口

### 4.1 单一通信输入

`prepare_communication()` 接收：

- `target`
- `purpose`
- `reason`
- `content`
- `expected_result`
- `operation_type=normal_message|platform_recovery|result_correction|business_resume`

`business_resume` 额外要求 `task_contract`，由 WP-01 resolver/validator 重新解析当前 attempt 契约。第二次平台恢复通过入口参数显式提供用户授权，不把授权词写入正文。

脚本只检查字段存在、类型、非空、长度、枚举、精确 target 映射、task/attempt 引用和当前机械状态。未知额外字段忽略，不评价业务理由、内容或期望结果是否正确。

### 4.2 固定输出

返回：

- `user_message`：固定中文用户说明，只展示对象、目的、原因和期望结果。
- `message`：给子 Agent 的中文业务指令，只包含 `【通信目的】`、`【通信原因】`、`【具体内容】`、`【期望结果】` 和操作所需固定提醒。
- `native_args={target,message}`：直接供 send_message/followup_task 使用。
- 精确 task/attempt/task_ref 仅作为生成结果的机械元数据返回，不写入 `message`。
- StateStore 降级时，只有 normal message 可以返回 `degraded_warning` 并继续生成原生参数。

`result_correction` 固定加入“只补交结构化结果，不重做业务任务”；`business_resume` 固定渲染重新验证后的目标、范围、禁止范围、完成条件和证据要求；message 不包含内部 task ID、operation type、协议版本或存储路径。

### 4.3 主动中断生成

`prepare_interrupt()` 使用同样的 target、purpose、reason、content 和 expected_result 业务字段，输出固定用户说明和 `native_args={target}`。它在 StateStore 可用时创建 `operation_type=interrupt` 的 pending action；对父 Agent/用户明确给出的 target，StateStore 不可用时返回降级告警但不阻止原生中断。

## 五、pending_action 数据结构、认领与过期

### 5.1 最小结构

每个精确 attempt 至多一条 `pending_action`：

```text
target
task_id
attempt
task_ref
operation_type
phase=prepared|claimed
created_at
expires_at
tool_use_id
claimed_at
reason                 # 有界；interrupt 对账需要
authorized_recovery    # 仅平台最后一次恢复
resume_contract        # 仅 business resume 的最小新 attempt 契约事实
resume_task_ref        # 仅 business resume
start_observed_at      # 可空；SubagentStart 先于 PostToolUse 时使用
```

不保存完整 message、content、expected_result、通信历史、平台响应或 delivery/read/processed 状态。StateStore 全局扫描确保同 target 同时只有一条有效 pending action。

### 5.2 prepared 阶段

- 生成器在精确 target 对应的 managed attempt 上创建 `phase=prepared`。
- prepared action 固定5分钟有效；未认领过期时精确删除，不增加任何计数，不创建 last lifecycle 记录。
- 同 target 已有 prepared/claimed action 时拒绝新操作。
- normal message 的 StateStore 创建失败可以显式 fail-open；三个 governed lifecycle 通信必须硬拒绝。interrupt 是安全例外：明确 target 可 fail-open，但不得声称已记录治理意图。

### 5.3 claimed 阶段

- PreToolUse 只通过未加密精确 target 查找唯一 prepared action，不读取 message 推断用途。
- 原子绑定 `tool_use_id + claimed_at`，改为 `phase=claimed`。
- `platform_recovery` 在同一 CAS 中增加 `recovery_count`，第二次认领同时清除 `awaiting_authorization`。
- `result_correction` 在同一 CAS 中增加 `correction_count`。
- `business_resume` 在同一 CAS 中创建新 attempt、保存重新验证的契约和新 task_ref，并把 claimed action 迁移到新 attempt；原 Agent映射在精确 SubagentStart 前仍指向旧 attempt。
- normal message 和 interrupt 不增加任何次数。
- 任一发送前校验或 CAS 失败都不消费预算、不创建 attempt，也不允许 governed lifecycle 原生调用。

### 5.4 20分钟缺失 PostToolUse

- claimed action 从 `claimed_at` 起20分钟内保持调用对账中。
- 满20分钟仍没有 PostToolUse 时，在 SessionStart、显式 reconcile 或下一次生成读取中把调用记为 unknown，再按对应三态规则更新状态并清理 pending action。
- 已消耗的恢复/纠正预算和已创建的 business resume attempt 不回退。
- normal message 只清理并输出有界告警；不改生命周期。
- 不自动重发，不创建 scheduler，不把 unknown 写成 failed、complete、interrupted 或 closed。

## 六、四类通信的机械状态转换

### 6.1 normal_message

前置条件：精确 managed target 可处于正常执行/停止状态，但 `platform_observation=error` 时拒绝，不能绕过恢复；unmanaged/未映射 target 兼容放行且不创建虚假关联。

认领：不改 attempt、执行状态、平台状态、业务结果、父动作或任何计数。

PostToolUse：success/failed/unknown 都只清理 pending action；不写 `last_lifecycle_operation`。状态写失败输出 degraded 告警，原生调用事实不回滚。

### 6.2 platform_recovery

前置条件：精确 managed target、同 Agent同 attempt、`execution_status=stopped`、`platform_observation=error`、没有正式业务结果。第一次恢复要求 `recovery_count=0 + recovery_status=null`；第二次要求 `recovery_count=1 + recovery_status=awaiting_authorization` 且用户显式授权；两次后拒绝。success/unknown 的未解决 lifecycle 记录存在时拒绝重发。

认领：调用前增加 `recovery_count`；第二次认领清除 awaiting authorization。

PostToolUse：

| 次数 | success | unknown | failed |
| --- | --- | --- | --- |
| 1 | stopped/error/null + `parent_action=wait` | stopped/error/null + `parent_action=reconcile` | stopped/error/awaiting_authorization + `parent_action=ask_user` |
| 2 | stopped/error/null + `parent_action=wait` | stopped/error/null + `parent_action=reconcile` | stopped/error/exhausted + `parent_action=ask_user` |

success/unknown/failed 都不回退计数。只有匹配的精确 SubagentStart 才进入 running/normal/wait。第一次恢复启动后再次 errored 写 awaiting_authorization/ask_user；第二次恢复启动后再次 errored 写 exhausted/ask_user。业务结果保持原值，平台异常不生成 needs_decision。

### 6.3 result_correction

前置条件：精确 managed target、同 attempt、`execution_status=stopped`、`business_result=null`、`result_protocol_status=needs_correction`、`correction_count<2`，且没有未解决的 success/unknown lifecycle 记录。

认领：调用前增加 `correction_count`。

PostToolUse：

- success：stopped + needs_correction + `parent_action=wait`。
- unknown：stopped + needs_correction + `parent_action=reconcile`。
- 第一次 failed：stopped + needs_correction + `parent_action=correct_result`。
- 第二次 failed：stopped + exhausted + `parent_action=manual_review`。

不重做业务，不修改 business result，不复用 recovery/spawn 预算。正式结果提交、合法迟到结果和再次停止后的协议处理留给 WP-05；本阶段只提供补交调用与启动授权边界。

### 6.4 business_resume

前置条件：当前 attempt 已有 blocked/failed 业务结果、业务 needs_decision 已机械标记为已决、complete 已 rejected，或前一 resume delivery 明确 failed 后父 Agent再次决定继续。每次重新运行 TaskContract resolver/validator。默认使用原 Agent followup；同 Agent继续时 model 不得变化。

prepared：选择新 attempt 编号和新 task_ref，但不创建新 attempt。

认领：原生调用前创建新 attempt，写新契约摘要和 WP-01 初值；同 Agent已知，因此 identity 保持精确映射事实，但执行仍为 not_started。claimed pending action 迁移到新 attempt。已有旧 attempt 以最小 `prior_attempts` 结构保留，避免迟到事件被 current attempt 覆盖。

PostToolUse：

- success：新 attempt 保持 `not_started + parent_action=wait`。
- unknown：新 attempt 保持 `not_started + parent_action=reconcile`。
- failed：若仍 not_started，以 `resume_delivery_failed` 标记该 attempt 已关闭，并把 task 的待处理动作设为 `decide_disposition`；不生成业务 failed。

success/unknown 必须等待精确 SubagentStart 才进入 running。unknown 后不得对同 Agent重发；替代执行必须使用新 spawn/new Agent，此选择与重复执行处置留给 WP-06，本阶段只机械拒绝 same-Agent 绕过。

## 七、主动中断对账

### 7.1 认领

- 目标必须是父 Agent或用户明确给出的 Agent ID/canonical path；不做同名、同轮或候选猜测。
- managed target 在 StateStore 正常时要求匹配 prepared interrupt action，并在 PreToolUse 原子认领。
- unmanaged target 或 StateStore 不可用时可按原生中断兼容/fail-open，但明确告警没有可靠治理关联。

### 7.2 PostToolUse

- success：只写 `execution_status=interrupted + parent_action=decide_disposition`，清理 pending/last lifecycle；不自动关闭 task、不生成 tombstone、不写业务结果。
- failed：保持原执行状态和原父动作，不自动重试；保存最小 failed lifecycle 证据，不能授权启动。
- unknown：保持原执行状态，写 `parent_action=reconcile`，保存 `operation_type=interrupt` 的最小 lifecycle 证据；不自动重试。
- 原子认领后 PostToolUse 状态写失败时输出“平台调用已发生但治理状态未可靠记录”的 degraded 告警；不回退或伪造状态。

### 7.3 后续 list_agents

- interrupt unknown + running：保留 unknown 证据，`parent_action=ask_user`。
- interrupt unknown + errored：写 stopped/error，`parent_action=ask_user`；不自动恢复。
- interrupt unknown + stopped/completed：写真实 stopped，进入 `decide_disposition` 或后续正式结果路径；不倒推中断 success。

## 八、last_lifecycle_operation 与清理

每个 attempt 至多一条：

```text
operation_type=platform_recovery|result_correction|business_resume|interrupt
target
tool_use_id
call_observation=success|failed|unknown
claimed_at
completed_at
reason              # interrupt 需要；其他操作只保留有界机械原因
```

- normal message 不写。
- pending action 清理前写入；business resume delivery failed 后若 attempt 同时明确关闭，则按关闭规则立即清理。
- 不设置时间 TTL，不因 Session 压缩或时间经过删除。
- 匹配 SubagentStart 确认、正式结果、主动中断确认、明确关闭、tombstone 或人工解除时删除。
- 同一 attempt 创建下一次 lifecycle operation 前，只有旧记录已消费或 failed 状态已被当前机械转换明确取代时才允许覆盖。

## 九、SubagentStart 授权

启动解析顺序：

1. 精确 Agent ID/canonical path 映射。
2. 对 stopped/not_started managed attempt，查找同 target、同 task/attempt 的 claimed pending action。
3. pending 已清理时，查找同 target、同 task/attempt 的 last lifecycle operation。
4. success/unknown 的 platform_recovery、result_correction、business_resume 可以授权 running；确认后消费 last 记录。
5. failed lifecycle 不授权；若 stopped/not_started 收到启动，保留原执行状态并设 `parent_action=reconcile`。
6. interrupt 永不授权启动；已 interrupted attempt 不被迟到启动复活。
7. business resume 可以在精确 lifecycle 证据下把同一 Agent映射从旧 attempt 切换到新 attempt；不使用 current attempt、最近时间或唯一候选猜测。

SubagentStart 先于 PostToolUse 时，在 claimed action 写 `start_observed_at` 并推进真实 running；pending 保留到 PostToolUse/20分钟对账，避免丢失 tool_use_id 关联。

## 十、新旧路径切换

### 10.1 本阶段原子退出

- `_handle_communication()` 不再从原生扩展字段直接渲染协议正文；新生成器先创建 pending action，再输出原生 `target/message`。
- 实际 message 不再包含 task ID、operation type 或协议版本。
- managed follow-up 不再根据工具名、正文或旧 `status` 猜恢复用途；PreToolUse 只认领 pending action。
- recovery/correction 计数从 PostToolUse 移到发送前原子认领。
- managed list_agents、follow-up、interrupt 和 SubagentStart 改用多维状态，不写 legacy `status`。
- interrupt unknown 不再被当作 success，interrupt success 不再自动让治理 task 闭环。

### 10.2 暂时保留

- legacy 平面 task 继续走旧最小兼容分支，直到 WP-05/WP-06 原子替换自由文本结果、Stop/Session 和旧状态集合；本阶段不再扩展其语义。
- managed task 继续使用 WP-03 当前 attempt 平面记录；只有 business resume 需要时增加最小 `prior_attempts`，不实现完整 task container、current attempt选择或重复执行处置。
- 正式 result 产生前，测试可机械构造 `business_result`、`result_protocol_status` 和 `acceptance_status` 前置事实；本阶段不创建正式结果或验收事实。
- `_active_records()`、旧 Session 摘要和诊断留给 WP-06/WP-07。

## 十一、测试计划

### 11.1 定向通信与 pending

- 生成器字段、长度、枚举、引用和固定输出。
- message 不含 task ID、operation type、协议正文；result correction 固定禁止重做业务。
- prepared 5分钟、claimed 20分钟、同 target 冲突、tool_use_id 精确认领。
- normal message success/failed/unknown 不改状态和计数；StateStore 不可写 fail-open。
- unmanaged/unmapped 原生通信兼容放行且不创建治理关联。
- 四类 operation 不靠工具名或正文猜测。

### 11.2 平台恢复与纠正

- managed list_agents error 写 stopped/error/recover；普通状态有界记录。
- 第一次恢复 success/unknown/failed、SubagentStart、再次 errored。
- 第二次必须用户授权；success/unknown/failed 和第三次拒绝。
- recovery_count、correction_count、spawn_retry_count 独立。
- result correction success/unknown/第一次 failed/第二次 failed；两次上限。
- failed lifecycle 和 interrupt 不授权启动；late success/unknown 启动消费 last 记录。

### 11.3 business resume 与 interrupt

- blocked/failed/needs_decision resolved/complete rejected 前置条件。
- TaskContract 重新验证、同 Agent model 不变、新 task_ref 和发送前新 attempt 创建。
- resume success/unknown/failed 的 not_started 状态；unknown 后拒绝 same-Agent 重发。
- interrupt prepared/claimed、success/failed/unknown、list_agents running/error/stopped 对账。
- interrupt success 只写 interrupted/decide_disposition，不自动关闭。
- PostToolUse 状态写失败返回 degraded，计数/attempt 不回滚。

### 11.4 回归

- WP-01 语义、WP-02 StateStore、WP-03 派发/身份全部回归。
- hooks matcher 和 fixture 使用真实 identifier 漂移边界。
- 不出现 result 文件、parent disposition、完整 Session/Stop、多 attempt 选择、group 或发布写入。

## 十二、文件级实施步骤

1. 新建本文，锁定结构、转换和禁止范围。
2. 新增 `tests/test_communication_lifecycle.py`，先运行并记录目标测试对旧实现的稳定失败。
3. 增加通信/中断数据类或纯机械 validator、固定 renderer 和 CLI 入口。
4. 增加 managed attempt 遍历、精确 target、pending action、last lifecycle 和 business resume 最小 prior-attempt 辅助函数。
5. 实现 preparation、5/20分钟 reconcile 和 PreToolUse claim；计数/attempt 全部在原生调用前 CAS。
6. 用有限 call response adapter 和 tool_use_id claim 替换 managed follow-up/interrupt PostToolUse 猜测分支。
7. 接管 managed list_agents 多维平台状态，并实现 interrupt unknown 后续对账。
8. 扩展 SubagentStart 精确 lifecycle 授权和消费；保留 spawn task-ref 绑定。
9. 更新 hooks matcher、Skill/runtime boundary 和相关 fixture/旧断言。
10. 运行定向、全量、编译、Plugin/Skill validator、Schema/fixture 校验和 `git diff --check`。
11. 同步本文实施结果、验证、`not_checked`、退出条件和 WP-05 交接。

## 十三、最低验证

```text
python3 -m unittest -v tests.test_communication_lifecycle
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
python3 $HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 $HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
JSON Schema/fixture 确定性校验
git diff --check
```

## 十四、not_checked

仓库测试不能证明，统一标记 `not_checked`：

- 真实 send_message/followup_task/interrupt_agent 的公开参数和 Pre/PostToolUse 可见字段。
- 通信 message 在 Hook 前后的加密、投影或改写形态。
- 空响应、成功响应、失败响应和中断响应的真实稳定结构。
- PostToolUse 缺失、SubagentStart 早于/晚于 PostToolUse、mailbox 断流和 list_agents 的真实事件顺序。
- follow-up 是否真实投递、Agent 是否真实恢复、结果补交是否被处理、business resume 是否重新运行。
- Hook trust、Plugin/Skill 实际加载和用户可见说明展示。

## 十五、退出条件

WP-04 只有同时满足以下条件才退出：

1. 本文与实际实施同步。
2. 四类通信均由显式 operation type 生成，不读取正文或工具名猜用途。
3. pending action prepared/claimed、5/20分钟、同 target 唯一和 tool_use_id 对账成立。
4. recovery/correction 计数和 business resume attempt 在调用前原子消耗/创建，任何调用观察不回退。
5. normal message fail-open 与 governed lifecycle 硬门禁严格分离。
6. platform recovery 两次上限、result correction 两次上限和 business resume 三态稳定。
7. interrupt success/failed/unknown 不伪造关闭或 interrupted；unknown 不自动重试。
8. last lifecycle 无 TTL，SubagentStart 只消费匹配 success/unknown，failed/interrupt 不授权。
9. unmanaged/unmapped 兼容路径不创建虚假治理关联。
10. 未提前实现 WP-05～WP-08；全部适用本地验证通过，真实平台项如实标记。

## 十六、交给 WP-05 的稳定接口

- `prepare_communication()` 已提供 `result_correction` 的结构化补交请求、两次预算和 success/failed/unknown 状态边界；WP-05 负责决定何时写 `needs_correction`、何时接收合法结果和何时耗尽。
- StateStore 每 attempt 的 `correction_count`、`result_protocol_status`、`parent_action`、pending/last lifecycle 是正式结果纠正链的前置事实。
- business resume 已提供新 attempt 创建、重新验证 TaskContract、同 Agent target 和 delivery 三态；WP-05 在 blocked/failed/needs_decision/complete rejected 正式结果或父验收后设置可继续的前置状态。
- interrupt 已提供机械执行状态和迟到对账；WP-05 必须拒绝成功中断后才到达的正式结果，同时保留中断前已合法保存的结果。
- 正式结果文件、固定提交顺序、幂等/冲突、父验收和 parent disposition 均未在 WP-04 实现，WP-05 不得从自然语言消息或 lifecycle call observation 生成业务结果。

## 十七、实施结果

### 17.1 实际实现

- `scripts/subagent_governance.py` 新增统一 `prepare_communication()`、`prepare_interrupt()` 和对应 CLI 入口，固定生成用户可见说明、中文业务 message、原生工具名和原生参数。实际 message 不保存内部 task ID、operation type 或协议正文。
- managed target 的下一次通信或中断在 StateStore 当前 attempt 内创建单目标唯一 `pending_action`；prepared 5分钟未认领删除，claimed 20分钟缺失 PostToolUse 转 unknown。PreToolUse 只用精确 target 认领并绑定 `tool_use_id`，PostToolUse 只用该 ID 对账。
- recovery/correction 次数和 business resume 新 attempt 均在原生调用前的 CAS 认领中消耗或创建；调用 success/failed/unknown 与 PostToolUse 写失败均不回退已经持久化的预算或 attempt。
- normal message 不改变生命周期或任何计数；StateStore 不可用时明确告警 fail-open，健康 managed target 则必须使用生成器。platform error 状态拒绝 normal message 绕过恢复。unmanaged/unmapped 原生通信兼容放行且不创建 task 关联。
- platform recovery 使用 stopped/error 同 Agent同 attempt，两次上限为一次自动恢复和一次用户授权恢复；success/unknown/failed、再次 errored、awaiting authorization 和 exhausted 使用多维状态转换。
- result correction 保持原 attempt 和独立两次预算；消息固定声明只补交结构化结果、不重做业务。success、unknown、第一次 failed 和第二次 failed 均按主盘点转换，正式结果提交仍未实现。
- business resume 在 prepared 阶段选择新 attempt/task ref，在 PreToolUse 认领时重新验证 TaskContract 并创建 attempt；同 Agent沿用首次 task name，精确 SubagentStart 将 Agent映射切换到新 attempt。success/unknown 保持 not_started，failed 以 `resume_delivery_failed` 关闭投递失败 attempt；unknown 后拒绝 same-Agent follow-up 绕过，替代执行要求新 spawn/new Agent。
- interrupt 使用显式 prepared/claimed 意图；success 只写 interrupted/decide_disposition，不关闭 task；failed 保持原状态；unknown 保持原执行状态并 reconcile。后续 list_agents running/error/stopped 只按真实观察推进，不倒推调用成功。
- 每 attempt 至多一条最小 `last_lifecycle_operation`，无时间 TTL。SubagentStart 只接受匹配 recovery/correction/business resume 的 claimed 或 success/unknown last 记录；failed 和 interrupt 不授权启动，成功匹配后消费记录。
- managed follow-up、interrupt、list_agents 和 SubagentStart 主路径不再读取正文、工具名或 legacy 平面 `status` 猜操作语义；legacy 分支仅作为尚未原子退役的兼容桥保留，不扩展新语义。

### 17.2 文件与失败基线

WP-04 直接修改或新增：

- `docs/refactor-plans/WP-04-communication-lifecycle-operations.md`
- `schemas/governance-semantics.schema.json`
- `scripts/subagent_governance.py`
- `hooks/hooks.json`
- `skills/subagent-governance/SKILL.md`
- `skills/subagent-governance/references/runtime-boundaries.md`
- `tests/test_communication_lifecycle.py`
- `tests/test_governance.py`
- `tests/test_hook_fixtures.py`
- `tests/test_plugin_structure.py`
- `tests/test_semantic_baseline.py`
- `tests/fixtures/interrupt-v1.json`
- `tests/fixtures/recovery-limit-v1.json`

修改运行时代码前新增的首批5个定向测试稳定失败，原因是旧实现不存在通信/中断生成入口和两阶段 pending action，且仍依赖正文/工具分支和 legacy status；完成新主路径后定向测试扩展为23项。

### 17.3 验证结果

- `python3 -m unittest -v tests.test_communication_lifecycle`：23项通过。
- `python3 -m unittest discover -s tests -v`：217项通过，覆盖 WP-01～WP-03 全回归。
- `python3 -m py_compile scripts/subagent_governance.py`：通过。
- Plugin validator：`Plugin validation passed`。
- Skill validator：`Skill is valid`。
- JSON Schema/fixture 确定性校验：3个 Schema 和5个 fixture 均可解析；相对 `$ref`、JSON Pointer、正则和 WP-04 语义锚点通过。
- `git diff --check`：通过。

### 17.4 not_checked

以下仍为 `not_checked`，本地 fixture 不替代真实平台证据：

- 真实 `send_message`、`followup_task`、`interrupt_agent` 的公开参数和 Pre/PostToolUse 可见字段。
- message 在 Hook 前后的加密、投影或改写形态。
- 原生空响应、成功、失败和中断响应的稳定结构。
- PostToolUse 缺失、SubagentStart 早于/晚于 PostToolUse、mailbox 断流和 list_agents 的真实事件顺序。
- follow-up 的真实投递、Agent真实恢复、结果补交处理和 business resume 重新运行。
- Hook trust、Plugin/Skill 实际加载和用户可见说明展示。

### 17.5 退出与 WP-05 交接

WP-04 的本地实现和第17.3节全部验证已满足显式 operation type、pending prepared/claimed、5/20分钟、独立计数、四类通信三态、business resume 新 attempt、interrupt 对账、last lifecycle 无 TTL 和精确启动授权要求；本工作包可以退出，后续不得在本任务中继续 WP-05。

交给 WP-05 的前置接口保持第十六节定义：WP-04 提供 `correction_count`、`result_protocol_status` 前置状态、result correction pending/last lifecycle 和两次调用边界，但不创建正式结果；WP-05 必须实现结果文件固定提交顺序、合法迟到结果、幂等/冲突、complete 父验收与 parent disposition，并在正式结果、成功中断或明确关闭时消费对应 lifecycle 记录。不得从自然语言消息或 call observation 生成业务结果。
