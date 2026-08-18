# S1-S6 整体架构复核

日期：2026-08-14

结论：本轮没有发现 P0。发现 4 个 P1、4 个 P2 和 1 个 P3。P1 集中在关闭后的增长 admission、replacement candidate 预算、same-Agent 跨 attempt 迟到事件路由和 duplicate-risk 授权；它们说明冻结模型 `work_item -> execution -> outcome -> disposition` 的主结构已经建立，但跨切片状态机尚未完全闭合。canonical-only 的 root current/`prior_attempts` 权威退役已在主要消费者中生效，没有发现历史 attempt-first record 被提升为 current managed 的路径。

## Findings

### P1-1：tombstoned work item 和已关闭 execution 仍可发起新的 native spawn

**证据**

- `scripts/subagent_governance.py:3083-3096` 的 replacement 初始检查只验证 managed task、candidate 数和 `current_attempt`，没有验证 `work_item.lifecycle == open` 或来源 execution 未关闭。
- `scripts/subagent_governance.py:3117-3165` 的锁内 admission 只重查 candidate 数、`current_attempt` 和 identity 占用，仍未检查 lifecycle/`attempt_closed`。
- `scripts/subagent_governance.py:3218-3232` 的 same-attempt spawn retry 只检查 spawn observation、identity 和重试计数，没有拒绝 closed attempt 或 tombstoned work item。
- `scripts/subagent_governance.py:4553-4597` 的 `PreToolUse` spawn claim 同样没有在最终调用边界重查 work-item/execution 是否已关闭。
- 这违反 `docs/redesign/D1-work-item-convergence.md:106-112` 的 attempt、关闭和单向不变量，以及 `docs/redesign/D4-platform-recovery-boundary.md:189-193` 的迟到/tombstone 规则。

**触发条件**

1. work item 已经通过 disposition 关闭并进入 `lifecycle=tombstoned`，随后调用 `prepare_replacement_dispatch()`；或
2. execution 已经 `attempt_closed=true`，但仍保留满足 retry predicate 的 `spawn_observation=failed`、`identity_status=unconfirmed`、`spawn_not_created=true`，随后准备并 claim spawn retry。

本地临时目录中的最小复现输出为：

```text
replacement_after_close allow tombstoned 2 None call-r
retry_after_close allow tombstoned True call2 retry_spawn
```

**后果**

- 显式关闭不再是单向边界；tombstoned work item 可以新增 replacement execution。
- 已关闭 attempt 可以再次消费 PreparedContract 并实际调用 native spawn。
- 状态可同时出现 `work_item.lifecycle=tombstoned` 与未关闭/已 claimed execution，造成 disposition、Stop、SessionEnd 和诊断对“是否已结束”的相互矛盾解释。

**现有测试为何未捕获**

- 当前测试覆盖迟到 Start/result 被关闭边界拒绝，以及 tombstone 精确保留/清理；例如 `tests/test_formal_result_parent_closure.py:728-780` 和 `tests/test_state_store.py:379-455`。
- 没有测试在 close/tombstone 之后调用 replacement preparation、spawn retry preparation 和最终 `PreToolUse` claim。

**最小修复方向**

在 preparation 和最终锁内 claim 两处共享一个 operation-specific admission predicate：要求 `work_item.lifecycle == open`、来源 execution 未关闭，并验证来源状态确实允许该 operation。失败时应精确回滚尚未消费的 PreparedContract，不能依赖较早的无锁快照。

**F1 实施状态（2026-08-14）**：已在开发仓库修复。replacement/retry preparation 与最终 PreToolUse claim 共享 open/unclosed admission；claim 在 StateStore 锁内重查，失败不写 native spawn 权威事实，tombstone 不会被派发路径复活。证据与边界见 `docs/redesign/F1-growth-admission-reservation-implementation.md`。

### P1-2：未 claim 的 replacement 不占 candidate 预算，且过期后无法清理

**证据**

- `scripts/subagent_governance.py:3117-3165` 在 native spawn claim 之前就创建 replacement execution、推进 current attempt 并写入 duplicate/disposition 聚合。
- `scripts/subagent_governance.py:3593-3624` 只在 initial/replacement execution 已有 `spawn_tool_use_id` 时将其计为 live candidate；未 claim 的 replacement 不占预算。
- `scripts/subagent_governance.py:4572-4597` 在 claim 时只核对目标 execution 的 spawn 字段，不重查 work item 的 live/reserved candidate 数。
- `scripts/subagent_governance.py:2892-2926` 的 unclaimed expiry 回滚只接受 pristine initial attempt；replacement 已带 `dispatch_kind=replacement_spawn`、`parent_action=resolve_duplicate` 等修改，predicate 不成立。
- `scripts/subagent_governance.py:3313-3321` 捕获该清理冲突后直接 `continue`，因此 PreparedContract 和 canonical execution 都保留。
- `docs/redesign/D6-migration-and-slices.md:181-188` 要求一个 work item 最多有两个未关闭、可能仍执行业务的 candidates，并要求增长由 disposition gate 控制。

**触发条件**

在 A1 仍为一个 live candidate 时连续 prepare A2、A3 replacement，暂不 claim；之后依次 claim A2、A3。由于 preparation 和 claim 均没有把未 claim replacement 当作 reserved capacity，两个 claim 都被允许。

本地最小复现输出为：

```text
prepared_attempts ['1', '2', '3']
live_before_claim 1
claim_decisions allow allow
live_after_claim 3
spawn_tool_ids {'1': 'call1', '2': 'call2', '3': 'call3'}

expiry_result {'expired': 0, 'reconciled': 0}
replacement_still_present True True
```

**后果**

- 硬性的 two-live-candidate cap 可被顺序 preparation + claim 绕过，单个 work item 能发起三个或更多并行业务 Agent。
- 五分钟后 unclaimed replacement 仍同时占用 task ref、attempt、current/duplicate 状态和 PreparedContract，形成无自动退出路径的悬空状态。
- 后续 replacement、business resume、select/interrupt 和诊断均会基于被遗留的 execution 作出决定。

**现有测试为何未捕获**

- `tests/test_dispatch_identity.py:268-322` 覆盖 preparation 的 stale snapshot/CAS admission，但注入的是已经 live 的并发 execution。
- `tests/test_wait_recovery_session_closure.py:625-652` 覆盖 canonical pending action expiry；现有 PreparedContract expiry 测试只覆盖 pristine initial attempt。
- 没有覆盖多个 unclaimed replacement、claim 时的预算重查或 replacement-specific expiry rollback。

**最小修复方向**

将未 claim replacement 作为 reserved candidate capacity 纳入同一预算；`PreToolUse` 在锁内再次核对预算。为 replacement 增加 operation-aware 的精确过期回滚，原子恢复 `current_attempt`、duplicate 标记、parent action、last disposition 和增长计数，或改变 preparation 结构，使这些状态只在 claim 成功时提交。

**F1 实施状态（2026-08-14）**：已在开发仓库修复。preparation 只写快照摘要绑定的 reserved execution，不推进 current 或提交 duplicate/disposition/growth facts；reservation 计入 two-candidate cap 且每个 work item 最多一个。claim 成功才原子提交增长事实；StateStore 若在 claim 已持久化后报错，只在完整 canonical task 仍精确等于本次 post-claim 快照时恢复 pre-claim 状态与未消费 PreparedContract；若 callback 尚未执行，也仅在 task 精确保持发送前状态时重开同一凭证，额外并发变化明确 degraded 且不覆盖；5分钟过期按精确 reservation identity/snapshot 幂等回滚。证据与边界见 `docs/redesign/F1-growth-admission-reservation-implementation.md`。

### P1-3：same-Agent resume 后，旧 attempt 的迟到 Stop/result 会被拒绝或写坏新 attempt（F2 已本地修复）

**证据**

- `scripts/subagent_governance.py:1745-1766` 的 target mapping 只保存一个 active attempt。
- `scripts/subagent_governance.py:5438-5456` 在 business-resume Start 时把同一 target mapping 改到新 attempt。
- `scripts/subagent_governance.py:2152-2157` 要求正式 TaskResult 的 `task_id + attempt` 必须等于 target 当前 mapping；mapping 前移后，旧 attempt 的精确结果也被拒绝。
- `scripts/subagent_governance.py:5628-5640` 的 SubagentStop 先按 target mapping 选 execution；`scripts/subagent_governance.py:5695-5717` 发现 payload attempt 不匹配后，把 protocol gap 写入这个已映射的新 attempt。
- `docs/redesign/D4-platform-recovery-boundary.md:186-191` 要求迟到事件只写回精确旧 attempt，不能按 current 路由。`docs/redesign/D6-migration-and-slices.md:161-177` 也明确 mapping 只能辅助当前查找，不能把无凭证迟到事件写入 execution。

**触发条件**

A1 和 A2 是同一个 Agent target；A1 结束后创建 same-Agent business resume A2，A2 Start 先到并推进 mapping，随后 A1 的 Stop/TaskResult 迟到。

本地最小复现中，A2 Start 后迟到的 A1 Stop 产生：

```text
mapping_before_late_stop {'attempt': 2, 'task_id': 'late-same-agent'}
a2_before {'execution_status': 'running', 'business_result': None,
           'result_protocol_status': None, 'parent_action': 'wait'}

stop_message managed attempt 已停止但没有合法结构化结果；应使用 result_correction 补交本次结果。

a1_after {'execution_status': 'stopped', 'business_result': 'failed',
          'result_protocol_status': None, 'parent_action': 'decide_disposition'}
a2_after {'execution_status': 'stopped', 'business_result': None,
          'result_protocol_status': 'needs_correction',
          'parent_action': 'correct_result'}
```

**后果**

- A1 的精确迟到 TaskResult 无法进入 A1 outcome 边界。
- 更严重的是，迟到 A1 Stop 会把正在运行的 A2 误标为 stopped，并制造 A2 result-correction 责任。
- 这同时破坏 identity、attempt、outcome 和 parent-action 不变量；后续 Stop/SessionStart 会把伪造的 A2 责任当成权威事实。

**现有测试为何未捕获**

- `tests/test_formal_result_parent_closure.py:496-521` 的迟到旧结果测试使用 `agent-old` 和 `agent-new` 两个 target，没有覆盖 same-target 跨 attempt。
- business-resume 测试覆盖 mapping 前移和 reuse gate，但没有在新 Start 后注入旧 Stop/result。

**最小修复方向**

显式 TaskResult 应先按 payload 的 `task_id + attempt` 找 retained execution identity，再验证 target 确实属于同一 work item/该 execution 的 provenance；当前 mapping 不能否定旧 attempt 的精确凭证。SubagentStop 若携带 task/attempt，则必须按该边界路由；若 payload 与 current mapping 冲突，应拒绝或记录未关联审计事实，绝不能把 protocol gap 写到另一 attempt。

**F2 实施状态（2026-08-14）**：已在开发仓库修复。`agents[target]` 继续只作 active index；每个 execution 保留自己的 `agent_id/canonical_task_path` provenance。显式 TaskResult 先由 payload `task_id + attempt` 找到 retained execution，再验证 target provenance，不再要求等于 active mapping。SubagentStop 的精确 payload 同样按 retained execution 路由；缺失、冲突或不存在的身份不会 fallback 到 active/current/最大 attempt/同名候选，也不会向另一 attempt 写 protocol gap。same-target business resume 的旧结果不再将 A2 误投影为 duplicate。实现与本地证据见 `docs/redesign/F2-same-agent-late-event-routing-implementation.md`；真实 SubagentStop payload 是否可携带 task/attempt 仍为 `not_checked`。

### P1-4：replacement 的 duplicate-risk 授权绑定 reason code，而不是来源 execution 的实际状态

**证据**

- `scripts/subagent_governance.py:3066-3076` 只在 `reason_code=unknown_duplicate_risk_accepted` 时要求 `duplicate_risk_accepted=true`。
- `scripts/subagent_governance.py:3083-3096` 和 `scripts/subagent_governance.py:3117-3127` 不根据来源 execution 的 running/unknown 状态要求风险确认。
- 因此来源仍 running/unknown 时，调用者可改用 `agent_unavailable` 或 `user_requested_replacement` 并保持 `duplicate_risk_accepted=false`，仍通过 admission。
- `docs/redesign/D6-migration-and-slices.md:165-177` 的冻结契约要求旧 execution 是 unknown/running 时必须 `duplicate_risk_accepted=true`；授权条件是来源事实，不是 reason-code 拼写。

**触发条件**

来源 execution 仍可能运行，父调用传入合法 replacement disposition，但使用非 `unknown_duplicate_risk_accepted` reason code 且未接受 duplicate risk。

**后果**

- native replacement spawn 可以在没有明确接受重复执行风险时发生。
- reason code 变成绕过安全 gate 的控制输入，事实层和授权层未分离。

**现有测试为何未捕获**

- unknown replacement 的测试通常同时传入专用 reason code 和 `duplicate_risk_accepted=true`。
- `tests/test_dispatch_identity.py:196-233` 验证 reliably stopped source 可用 `agent_unavailable` 创建 replacement，但没有对应的 running/unknown source + false risk 反例。

**最小修复方向**

在锁内读取来源 execution 的 live/unknown 事实；只要可能与 replacement 共存，就强制要求 `duplicate_risk_accepted=true`，并把专用 reason code 作为说明而非唯一 gate。可靠 stopped/closed source 不应被迫接受不存在的 duplicate risk。

**F3 实施状态（2026-08-14）**：已在开发仓库修复。共享的 canonical single-execution coexistence predicate 排除 `attempt_closed` 与可靠 `stopped|interrupted`，纳入 `running`、已 claim native spawn 的 `null|success|unknown` 与已 claim business resume 的 `success|unknown`；prepare/StateStore callback/PreToolUse claim 都从它派生排除本次 reservation 的全部现存 live candidates。任一共存 candidate 都要求 `duplicate_risk_accepted=true`，而专用 `unknown_duplicate_risk_accepted=false` 仍机械拒绝。详见 `F3-replacement-duplicate-risk-facts-implementation.md`。

### P2-1：replacement 无条件制造 duplicate，可靠停止的来源也进入虚假的 select/interrupt 流程

**证据**

- `scripts/subagent_governance.py:3144-3150` 无条件把新旧 execution 都设为 `duplicate_execution=true`、`parent_action=resolve_duplicate`。
- `docs/redesign/D6-migration-and-slices.md:174-177` 只在 A(N) 与 replacement 可能同时存在时要求 duplicate/select 收口。
- `tests/test_dispatch_identity.py:196-233` 明确构造 reliably stopped、正式结果可用的 source，并验证 replacement 可以创建，但没有断言 duplicate/parent-action 应保持为非冲突状态。

**触发条件**

来源 execution 已可靠 stopped/interrupted，不再可能继续执行业务，父任务显式授权创建新的 execution 边界。

**后果**

- work item 被错误投影为存在两个 live/冲突 candidates，只允许 `select_attempt`。
- 父任务可能对已经停止的 Agent 发出不必要的 interrupt，或在没有真实重复风险时阻塞 outcome/disposition 流程。

**现有测试为何未捕获**

现有测试只验证 candidate budget 不计可靠 stopped source，以及 replacement attempt 成功创建，没有检查创建后的 decision snapshot、duplicate 标记和 allowed actions。

**最小修复方向**

根据来源 execution 的权威 live/unknown 事实条件化写入 duplicate 标记；可靠 stopped/closed source 应直接成为 prior execution，而新 attempt 成为 current。增加 stopped-source replacement 到 S5 snapshot/allowed-actions 的跨切片测试。

**F3 实施状态（2026-08-14）**：已在开发仓库修复。claim 只给新 attempt 与最终全部 live candidates 写 `duplicate_execution + resolve_duplicate`；可靠 failed/stopped/interrupted source 即使曾参与旧 duplicate 也保持 non-duplicate prior。`select_attempt` 只处理当前 duplicate 集合；未知 live candidate 没有精确 interrupt target 时保持未关闭和 unresolved duplicate，不能以空 target 伪造关闭或清除 selected duplicate。S5 对真实 candidate 投影 `selection_pending/select_attempt`，但无现存 candidate 的 stopped-source replacement 不再出现虚假选择或中断流程。

### P2-2：持久化 `work_item.action_required` 与权威派生视图存在双权威

**证据**

- `scripts/subagent_governance.py:1995-2005` 的持久化聚合只检查未关闭 execution 是否有非空 `parent_action`。
- `scripts/subagent_governance.py:5813-5844` 的权威派生 predicate 还包括 running、spawn/pending/lifecycle call、unconfirmed success/unknown identity 和 duplicate。
- `docs/redesign/D5-decision-diagnostics.md:180-184` 要求 `work_item.action_required` 等于任一 candidate action-required，并明确 prior attempt 也参与。
- Schema 又把该派生值列为持久化必填字段：`schemas/governance-semantics.schema.json:202-225`。

**触发条件**

例如 initial spawn 已 claim、`spawn_tool_use_id` 非空且 `spawn_observation=null`，但 execution 的 `parent_action=null`。

本地复现输出为：

```text
stored_work_item_action_required False
derived_action_required [('action-task', 1)]
```

**后果**

- 同一个 action-required 事实有两个值；直接读取 work item 的消费者会认为无需动作，而 Stop/Session/diagnose 的派生消费者认为仍需对账。
- 当前关键消费者多数重新派生，所以尚未复现 SessionEnd 静默删除；但 Schema 和记录本身已经提供了可被误用的冲突权威。

**现有测试为何未捕获**

- `tests/test_wait_recovery_session_closure.py:211-252` 验证派生视图包含无 parent action 的权威调用。
- 诊断测试也验证 candidate action-required，但没有同步断言持久化 `work_item.action_required` 与同一 predicate 一致。

**最小修复方向**

优先删除持久化派生字段并由唯一共享 predicate 计算；若保留，则所有写入必须在同一锁内调用同一 predicate，Schema/测试应明确它是缓存而非独立事实，并断言与权威视图恒等。

**F4 实施状态（2026-08-14）**：已在开发仓库修复。canonical `work_item` 不再持久化 `action_required`，Schema 同步删除其必填/属性定义；历史同名字段只按未知扩展兼容读取，纯只读 diagnose 不迁移，下一次 canonical execution 同锁写入时由 `_sync_canonical_work_item()` 移除。唯一权威 `_canonical_action_required_candidate()` 覆盖 current/prior execution、replacement reservation、running、spawn/pending/lifecycle call、unconfirmed success/unknown identity 与 duplicate；`_action_required_records()`、Stop gate、SessionStart、SessionEnd、diagnose candidate/work-item snapshot 和 group 聚合均复用该 predicate，可靠关闭后归零。失败先行、字段影响、验证和未检查项见 `docs/redesign/F4-action-required-single-authority-implementation.md`。

### P2-3：S3 的软增长 facts 没有进入 S5 diagnose 或 SessionStart

**证据**

- replacement 和 resume 把软事实写在 work item：`scripts/subagent_governance.py:3159-3161`、`scripts/subagent_governance.py:4683-4690`。
- `scripts/subagent_governance.py:6419-6423` 的 diagnostic candidate 却读取 execution 上不存在的 `growth_facts[]`。
- `scripts/subagent_governance.py:6759-6765` 仅从 candidates 聚合 work-item facts，没有读取 `work_item.repeated_business_attempts`、`repeated_replacements` 及计数。
- `scripts/subagent_governance.py:7051-7075` 的 SessionStart summary 也没有输出 snapshot facts 或增长计数/最近原因。
- `docs/redesign/D6-migration-and-slices.md:181-189` 明确要求这些软告警在 diagnosis/SessionStart 显示累计次数和最近原因。

**触发条件**

work item 到达第 4 个 business attempt，或发生第 2 次及以后的 replacement。

**后果**

- 状态中虽然持久化了增长事实，但父任务恢复和诊断看不到冻结设计要求的告警。
- “下一 disposition 必须说明继续理由”的治理意图无法通过主要只读入口落实。

**现有测试为何未捕获**

- `tests/test_dispatch_identity.py:372-394` 只断言 replacement fact 被持久化。
- `tests/test_communication_lifecycle.py:1997-2020` 只断言 business-attempt fact 被持久化。
- 没有从 S3 写入一路断言到 S5 work-item snapshot 和 SessionStart 文本。

**最小修复方向**

从 canonical work item 直接投影有界的增长 facts、计数和最近 reason 到 decision snapshot，并由 SessionStart 消费同一字段；在 machine semantics 中定义输出形状，补一条 S3 -> S5 -> SessionStart 的跨切片测试。

**F5 实施状态（2026-08-14）**：已在开发仓库修复。WorkItemDecisionSnapshot 新增 canonical `growth` 投影，固定输出 `attempt_count`、`replacement_spawn_count`、`repeated_business_attempts`、`repeated_replacements`、soft warning、唯一 facts 集合和最近增长授权的有界摘要。通用 `last_disposition` 会被后续正式处置覆盖，因此 claim 同锁持久化单条 `work_item.last_growth_authorization`，不建立事件日志。candidate 的伪 `growth_facts[]` reader 已删除；diagnose、group member 和 SessionStart 复用同一 snapshot。软提醒不进入 action-required，也不阻止 Stop/SessionEnd 或触发自动关闭/spawn。失败先行、输出形状和验证见 `docs/redesign/F5-growth-facts-projection-implementation.md`。

### P2-4：governance Schema 尚不能作为最终 record/disposition 模型的唯一机器语义锚点

**证据**

- D6 要求受控的 `parent_disposition_record`、`work_item`、`execution_record` 和 transition 定义：`docs/redesign/D6-migration-and-slices.md:90-119`。
- Schema 只有 disposition action enum：`schemas/governance-semantics.schema.json:91-94`，并没有 `$defs.parent_disposition_record`；`x-semantics.parent_disposition_fields` 也只列字段名，见 `schemas/governance-semantics.schema.json:519-525`。
- `work_item.last_disposition` 只是任意 object，`work_item` 允许任意额外字段：`schemas/governance-semantics.schema.json:202-226`。
- `execution_record` 只要求 `task_id/attempt` 和少量 outcome 字段，同时允许任意额外字段：`schemas/governance-semantics.schema.json:228-240`。identity、dispatch kind、transition、pending/lifecycle operation、duplicate、closure、parent action/disposition 等最终状态机字段均不受该定义约束。
- runtime 把增长授权写入名为 `parent_disposition`/`last_disposition` 的字段，action 为 `resume_business` 或 `spawn_replacement`：`scripts/subagent_governance.py:3140-3158`、`scripts/subagent_governance.py:4662-4688`；而 Schema 中 `parent_disposition` enum 只允许 outcome disposition 的四个 action。
- `tests/test_semantic_baseline.py:147-160` 只对 TaskContract、TaskResult、AttemptState dataclass 做 field-set 等值；`tests/test_semantic_baseline.py:393-418` 只确认 S5 定义存在及部分规则，没有用 Schema 验证 runtime-emitted canonical records。

**触发条件**

任何字段改名、runtime 新增非法 enum、遗漏 required 状态字段，或消费者把 growth authorization 当成 formal outcome disposition；现有 Schema 校验仍可能通过或根本无法覆盖该对象。

**后果**

- “Schema 是唯一机器语义锚点”的发布声明缺少可执行保证。
- Python、Skill/README、Schema 和 fixture 可以各自通过测试但语义漂移，尤其容易混淆 growth authorization 与最终 outcome disposition。

**现有测试为何未捕获**

semantic baseline 只覆盖三个旧 field sets 和定义存在性；没有构造 runtime 的 initial/resume/replacement/result/disposition/close records 后逐一做逻辑 Schema 校验，也没有核对 disposition 类型与字段名。

**最小修复方向**

明确区分 formal outcome disposition 与 growth authorization 的对象名；补齐 canonical work-item/execution/transition/operation/closure record 的受控定义。用 runtime 实际生成的各阶段 records 做 Schema/semantic validator 测试，并把 Python enum/field set 与 Schema 枚举做双向一致性断言。

**F6 实施状态（2026-08-14）**：已在开发仓库修复。governance Schema 现包含受控 canonical state/task/work-item/execution、transition、growth authorization、formal disposition、pending/lifecycle operation、replacement reservation、result/closure/tombstone、identity mapping 与只读 decision snapshot 定义；runtime 实际生成的 initial/retry/replacement/resume/recovery/correction/interrupt/result/disposition/duplicate-close records 均进入可重复 validator。增长授权改名为 `growth_authorization`/`last_growth_authorization`，formal 处置改为 `parent_disposition_record`/`last_parent_disposition`，旧混淆字段仅 compatibility-read 并在写入时按 absent/null/non-null 三态单向收敛，冲突拒绝；只读 formal compatibility 从当前 canonical task key 补齐旧 work-item 形状缺少的 `task_id`。失败先行、inventory 和验证记录见 `F6-canonical-record-schema-implementation.md`。

### P3-1：S6 canonical-only 退役已生效，但 Skill/边界文档和 runtime 仍留有 attempt-first/legacy 残余

**证据**

- S6 已明确 diagnose 删除顶层 attempt-first arrays，work-item snapshot 只消费 canonical executions：`docs/redesign/S6-compatibility-retirement-release-preflight-implementation.md:52-57`。
- 测试确认历史 attempt-first managed record 不惰性迁移，diagnose 不再输出顶层 `action_required/recent_activity`：`tests/test_s6_compatibility_retirement.py:55-126`。
- Skill 仍描述稳定 snapshot “直接消费 `_action_required_records()` 与 `_recent_activity_records()`”：`skills/subagent-governance/SKILL.md:202-207`；runtime boundary 也称 diagnose “直接消费权威 action_required/recent_activity 视图”：`skills/subagent-governance/references/runtime-boundaries.md:31-35`。这没有说明 work-item-first 输出，容易被理解为已退役的 attempt-first 主入口。
- `scripts/subagent_governance.py:2450-2458` 仍保留 root-current fallback；`scripts/subagent_governance.py:3208-3215` 的注释仍声称存在构建 legacy in-memory view 的 adapter，但 `_ensure_canonical_task_record()` 已拒绝历史 record。
- `scripts/subagent_governance.py:7660-7733` 仍定义 `_diagnostic_attempt_snapshot()`；其 snapshots map 在 `scripts/subagent_governance.py:7925-7932` 构造后不再作为正式输出。

**触发条件**

维护者按 Skill/注释实现新的 diagnose 消费者，或后续改动误用尚存的 fallback/dead helper。

**后果**

- 当前运行时主要权威路径没有因此回退，但文档和死代码会继续暗示 attempt-first compatibility 仍是受支持架构。
- 后续切片可能重新引入 root/prior reader 或基于旧 snapshot 的语义漂移。

**现有测试覆盖情况**

S6 retirement 测试已经有效阻止历史 managed record 的惰性迁移和旧顶层输出复活；缺口是没有检查 Skill/边界文档措辞，也没有禁止无消费者的 legacy helper/fallback。

**最小修复方向**

把 Skill/runtime-boundary 改为 work-item decision snapshot 的实际数据流；确认没有内部消费者后删除 unreachable root fallback、过期注释和 dead attempt snapshot helper。保留 S6 的行为测试作为退役护栏。

**F7 实施状态（2026-08-14）**：已在开发仓库完成重新审计与清理。旧证据中的通用 root-current reader、私有 helper 文案和多数 legacy adapter 已由 S6/F1-F6 消解；当前仍成立的 duplicate 收口 root fallback、错误 retry adapter 注释、dead diagnostic attempt helper 与未消费 snapshot/key maps 已删除。开发 Skill/runtime-boundaries 现在以 `WorkItemDecisionSnapshot` 为对外决策/诊断入口，attempt 只作为 `execution_candidates[]` 候选事实；退役测试同时禁止上述 runtime 残余和当前指导文档发布内部 helper 名。F6 的 `last_disposition`、execution/pending/PreparedContract legacy-name readers 因承担受控 compatibility-read 与冲突收敛职责明确保留。inventory、失败先行、验证、`not_checked` 和 remaining 见 `F7-canonical-only-residual-cleanup.md`。

## 审查范围与方法

本轮是独立只读架构复核。除本文外没有修改运行时代码、Schema、测试、Skill、README、稳定发布源、运行缓存、Hook trust、Marketplace、Registry 或外部对话。

已完整或按关键路径阅读：

- `AGENTS.md`；
- `docs/redesign/D1-work-item-convergence.md` 至 `D6-migration-and-slices.md`；
- S1-S6 六份 implementation record；
- `schemas/governance-semantics.schema.json`；
- `skills/subagent-governance/SKILL.md` 与 `references/runtime-boundaries.md`；
- `README.md`；
- `scripts/subagent_governance.py` 中 dispatch/PreparedContract、identity/Start/Stop、communication/resume/replacement、formal result/disposition、reconcile/diagnose/group、Stop/SessionStart/SessionEnd 关键路径；
- dispatch、communication、formal result、diagnostics/group、state store、session closure 和 S6 retirement 相关测试。

方法：以冻结模型 `work_item -> execution -> outcome -> disposition` 为主线，逐项对照 D1 不变量、D2 identity/deliverable、D3 outcome/disposition、D4 recovery/迟到事件、D5 work-item decision snapshot、D6 migration/slice exit criteria；同时做静态 reader/writer 搜索、锁内 admission/CAS 路径检查、定向临时目录复现和完整本地测试。

## 跨切片不变量核对

| 不变量 | 结论 | 证据/说明 |
| --- | --- | --- |
| work item 是任务目标唯一权威，状态单向收口 | **通过 F1 本地验证** | preparation 与 claim 都执行 lifecycle/source admission；关闭或 tombstone 后不能新增或重派 execution。 |
| execution identity 以 `task_id + attempt + ref/target provenance` 精确绑定 | **通过 F2 本地验证** | active target index 与 retained provenance 分离；same-target A1/A2 迟到 Stop/result 不会写坏 A2。真实平台 payload 仍为 not_checked。 |
| platform execution、business outcome、storage、acceptance 相互分离 | **通过本地检查** | storage failure 保持 `business_result=null`；result replay 幂等、冲突保留第一份；相关测试见 `tests/test_formal_result_parent_closure.py:232-242`、`:387-401`、`:460-477`。 |
| 同一 attempt 是单一正式结果边界 | **通过 F1/F2 本地验证** | closed attempt 不可重派；same-Agent A1/A2 的迟到 Start/Stop/result 按 retained provenance 归属自己的 attempt。 |
| unknown 不得自动变成 success/failed/stopped/interrupted | **通过 F3 本地验证** | interrupt unknown 保持未关闭并要求 reconcile；replacement gate 从 canonical coexistence facts 判定，不用 reason code 把 unknown 改写成终态。 |
| parent action 只表达下一步，不代表调用/关闭已完成 | **通过 F4 本地验证** | `parent_action` 仍只表达下一步；action-required 从 canonical candidate facts 派生，已 claim 但无 parent action 的 spawn/pending/lifecycle 调用仍进入责任视图。 |
| 未解决 work item 不因时间/SessionEnd/容量静默清理 | **通过 F1/F4 本地验证** | reservation 是 action-required candidate；只在精确快照匹配时过期清理，SessionEnd 使用统一 canonical derived view。 |
| duplicate 只在可能共存时成立，最多两个 live candidates | **通过 F1/F3 本地验证** | reserved/live candidate cap 在 prepare/claim 重查；可靠 stopped/closed source 排除，duplicate 只投影到真实 coexistence candidates。 |
| tombstone 期间迟到事件不复活对象 | **通过 F1/F2 本地验证** | 迟到 Start/result 被拒绝，growth/spawn admission 也拒绝 tombstoned work item。 |
| CAS/storage failure 不留下半提交结果或覆盖首个 outcome | **通过 F1 本地验证** | result 首份权威与冲突保护保持；replacement claim/rollback 只在完整 pre/post snapshot 精确匹配时恢复，否则保留并报告 degraded。 |
| canonical-only reader/writer 退役 | **主要路径通过** | 没有发现 `prior_attempts` 权威 reader/writer，也没有发现历史 record 被提升为 current managed；S6 tests 覆盖拒绝和输出退役。P3-1 仅为文档/死代码残余。 |
| diagnose/group/SessionStart 使用同一 work-item decision 语义 | **通过 F5/F6 本地验证** | F4 统一 action-required；F5 统一 canonical growth snapshot、group member 与 SessionStart 消费；F6 使 canonical sources、growth/formal disposition 分界和只读 decision snapshot 进入同一可执行 Schema。 |
| Stop/SessionEnd 不解析 diagnose 输出，不以 recent window 代替责任 | **通过本地检查** | canonical `_action_required_records()` 保留 stale prior/调用中责任，SessionEnd 相关测试覆盖 root projection 不一致；见 `tests/test_wait_recovery_session_closure.py:127-252`、`:669-720`。 |

## 验证证据

### 完整测试

执行：

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

F6 兼容 null-merge 与只读 task-context 修正后的结果：共 348 个测试，346 passed，2 errors。两个 error 均为已有 D6 host-specific path 发布前检查问题：

- `test_current_development_tree_passes_with_supported_ref`
- `test_release_requires_manifest_tag_and_marketplace_ref_to_match`

二者由 `docs/redesign/D6-migration-and-slices.md` 中 host-specific path 触发，不是本轮新增文档或上述临时复现造成；不能把完整测试表述为全绿。

### 静态与 validator

```text
python3 -m py_compile scripts/*.py
```

通过；bytecode 输出重定向到临时目录，没有修改仓库文件。

- Plugin validator：passed。
- Skill validator：passed。
- 全部仓库 JSON 解析：passed。
- `git diff --check`：passed。

### 定向诊断

使用临时目录中的 StateStore/PreparedContractStore 做了以下非破坏性复现：

- tombstoned replacement 与 closed-attempt spawn retry；
- 多个 unclaimed replacement 绕过 two-candidate cap；
- replacement PreparedContract 过期无法回滚；
- same-Agent resume 后旧 Stop/result 迟到；
- persisted/derived `action_required` 分歧。

复现只写临时目录，没有修改现有项目文件。

## 已确认的良好边界

- formal TaskResult 的业务结果、协议状态、存储状态和验收状态在主要路径上保持分离；storage failure 没有伪造成 business failed。
- 同一正式结果 replay 幂等；不同合法结果不按时间覆盖首份，而是记录 conflict。
- interrupt/select 的 failed/unknown 不会提前关闭未选 execution；只有可靠 success 才进入精确关闭。
- Stop、SessionStart、SessionEnd 的关键责任判断读取 canonical executions/派生视图，不依赖 diagnose JSON，也不使用 12 小时 recent window 代替 action-required。
- canonical-only 退役的实质行为有效：历史 attempt-first managed record 不惰性迁移，root/prior 字段不作为权威 current，diagnose 不再输出 attempt-first 顶层 arrays。
- group 保持只读聚合，不拥有 Agent lifecycle、调度或 aggregate outcome。

## not_checked 与 residual risks

以下项目需要真实 Codex 插件/平台验证。本轮授权明确禁止安装、缓存同步和新建外部真实测试对话，因此全部是 `not_checked`，不是 bug 或本地失败：

1. 当前开发工作树是否被真实插件加载，以及七类 Hook 的 enabled/trusted 状态。
2. light/standard/strict/auto 的真实 `spawn_agent` 参数、task name/ref 可见性与 provider response shape。
3. `send_message`、`followup_task`、`list_agents`、`interrupt_agent` 的真实投递、乱序、断流和 terminal shape。
4. SubagentStart/SubagentStop/TaskResult 的真实 payload，特别是 same-Agent 跨 attempt 时是否携带足够的精确 identity。
5. provider restart、`pending_init`、精确空 list、mailbox 静默和 compact/resume 的实际时序。
6. Stop、SessionStart、SessionEnd 的真实 Hook 顺序、父任务展示与降级放行行为。
7. diagnose/group 在 UI 和父任务链中的展示、容量截断和恢复体验。
8. N/N-1 安装、升级、回滚、稳定源/缓存 hash 与 Hook trust。

S6 implementation record 的真实矩阵仍为 `passed=0, failed=0, not_checked=8`（`docs/redesign/S6-compatibility-retirement-release-preflight-implementation.md:118-131`）。不能据此声称稳定发布已验证，也不能把它计入上述 findings 的严重度。

## 建议下一步

1. 先修复 P1-1 和 P1-2：统一 growth/spawn 的锁内 admission、reserved candidate 预算与 operation-aware rollback；它们直接决定关闭单向性和并发上限。
2. P1-3 已由 F2 在开发仓库修复：保留 same-Agent A1/A2 的 Start/Stop/result 定向回归，并在后续真实插件测试中核对可观察的 SubagentStop payload。
3. 修复 P1-4/P2-1：以来源 execution 事实决定 duplicate-risk gate 和 duplicate 标记，不再以 reason code 或“所有 replacement”代替事实判断。
4. action-required 已由 F4 统一，P2-3 增长事实投影也已由 F5 完成；保留 S3 -> S5 -> SessionStart 的真实 claim 回归。
5. P2-4 已由 F6 完成本地实现与 runtime-emitted record/field/enum 一致性验证；P3 legacy 残余仍应另行清理，不并入 F6。
6. 完成本地修复和规定验证后，再按项目“外部问题修复与真实测试”流程同步测试插件并新建独立对话；真实矩阵通过前，不作“整体架构已闭环”或“可发布”的结论。
