# F8: F1-F7 修复后综合架构复核

日期：2026-08-14

性质：独立、本地、只读架构复核；除本文外未实施修复

基线：当前 dirty development worktree，F1-F7 已在本地实现，未安装、发布或同步插件

## 1. 结论

**当前不准入“同步测试插件 + 新对话真实测试”。必须先完成两个独立的本地修复切片，再重新执行本地综合验收。**

F1-F7 已把原综合审查的 9 项 findings 在各自声明边界内全部修复：关闭后的 growth admission、replacement reservation/claim/expiry、same-Agent 迟到事件、基于 execution facts 的 duplicate risk、可靠停止来源、`action_required` 单一派生权威、growth projection、可执行 canonical Schema，以及 canonical-only 残留清理，均有当前代码与定向测试支持。

但组合后的架构仍有两个新的 P1 缺口：

1. retained canonical execution 仍有精确 target provenance、但 active `agents[target]` 索引缺失时，三类 managed lifecycle follow-up 会退化成 unmanaged 并绕过硬门禁。
2. initial dispatch preparation 的异常清理没有绑定完整 task 快照；它既可能删除并发写入，也会在清理失败时吞掉错误、删除 PreparedContract 并留下不可继续的孤立 task。

因此，本地架构尚未形成完整的“管理对象识别 -> 前置授权 -> 原子认领 -> 异常恢复 -> 可诊断终态”闭环。此结论不否定 F1-F7 对原 9 项问题的修复，也不把本地单测等同真实平台验收。

## 2. Findings

### P0

无。

### P1-1: active target index 缺失会让 retained managed execution 逃逸 lifecycle 治理

**位置**

- `scripts/subagent_governance.py:1962`，`_managed_target_attempt()` 只读取 `state.agents[target]`。
- `scripts/subagent_governance.py:4483-4508`，`_prepare_managed_action()` 在该索引缺失时直接返回 `managed=false`。
- `scripts/subagent_governance.py:5699-5706`，`_claim_pending_action()` 在无 pending action 且索引缺失时直接 allow unmanaged 原生调用。
- 与 `skills/subagent-governance/SKILL.md:115-126`、`skills/subagent-governance/references/runtime-boundaries.md:14-21` 发布的 retained provenance 与 managed lifecycle fail-closed 语义不一致。

**可触发场景**

1. 建立 open、confirmed 的 managed execution，使其 `agent_id` 或 `canonical_task_path` 精确等于 target。
2. 只删除 `state.agents[target]`，保留 canonical task、execution 和 target provenance。
3. 分别准备 `platform_recovery`、`result_correction`、`business_resume`。
4. generator 三次均返回 `managed=false`；随后无 pending action 的 `followup_task` PreToolUse 三次均 allow。

本次临时目录复现结果：

| operation | prepared managed | PreToolUse | 状态变化 |
| --- | --- | --- | --- |
| `platform_recovery` | `false` | `allow` | `recovery_count` 仍为 0，无 pending action |
| `result_correction` | `false` | `allow` | `correction_count` 仍为 0，无 pending action |
| `business_resume` | `false` | `allow` | 仍只有 attempt 1，未创建 attempt 2 |

三项复现中，execution 的精确 target provenance 均仍存在。

**影响**

- recovery/correction 预算、pending action、`tool_use_id` 对账及 business-resume growth admission 可被整体绕过。
- 原生 follow-up 可能实际恢复或继续已受治理业务，但 StateStore 不记录授权、attempt 或运行事实；后续 Start/result/Stop 只能面对缺失因果链。
- active index 本应只是当前查找索引，retained execution 才是历史 provenance；当前 lifecycle 分类却把索引缺失等同“从未受治理”，形成错误 fail-open。

**最小修复方向**

- unmanaged fallback 前，按 target 检查 retained canonical provenance。
- 精确唯一匹配到 open managed execution 时，必须在锁内安全重建/核对 active index，或明确 fail-closed 进入 reconcile；不得按 unmanaged 放行 lifecycle operation。
- 多个 retained attempt 匹配同一 target 且无法机械选择时拒绝并要求对账，不猜 current attempt。
- 真正无 canonical provenance 的 target 才保留 unmanaged compatibility；`normal_message` 与明确 interrupt 的既有故障降级例外应单独保持。
- 为 generator 和直接 PreToolUse 两个入口补齐 missing/stale/ambiguous index，以及 same-Agent A1/A2 的三类 lifecycle 回归测试。

**F9 实施状态（2026-08-14）**：已在开发仓库完成本地修复。`_managed_target_admission()` 现在以 execution 的精确 `agent_id/canonical_task_path` retained provenance 为身份权威，把 `agents[target]` 限定为可在锁内修复的 active lookup index。唯一且未关闭的精确 candidate 会在 generator pending 创建或 PreTool pending 认领的同一 StateStore 锁内恢复索引；无可靠 active index 时的多个未关闭 candidate、live index/provenance 冲突和锁内分类变化均 fail-closed/reconcile。已可靠关闭的 historical provenance 明确拒绝且不复活，只有完全没有 canonical provenance 的 target 保留 unmanaged compatibility。父侧验收补充发现的 A1 prepared pending 与锁内 active A2 candidate 错配也已修复：claim predicate 与 writer 均要求 admission candidate 精确等于 pending owner，失败时保留旧 pending，且不消费预算、创建 attempt 或回拨 mapping；business-resume delivery-failure retry 以 `prepared_on_attempt` 独立保存来源，不放宽 owner admission。三类 governed lifecycle 的 generator、直接无 pending PreToolUse、pending claim/预算或新 attempt，以及 normal/interrupt、same-Agent A1/A2、F6 compatibility convergence 均已有回归证据。完整决策表、锁边界与验证见 `docs/redesign/F9-retained-target-lifecycle-admission.md`。

本状态追加不改写上述原始 finding、临时反例或历史证据。P1-2/F10 initial preparation rollback 已按下文 F10 状态关闭；真实插件测试仍按本阶段约束保持 `not_checked`，未据此同步测试插件或放宽发布准入。

### P1-2: initial preparation rollback 可删除并发事实，失败时还会形成静默孤立 task

**位置**

- `scripts/subagent_governance.py:3438-3472`，`_cleanup_initial_attempt()` 只核对 task ref、未 claim 和默认 `AttemptState`，不核对完整 initial task 快照。
- `scripts/subagent_governance.py:3688-3700`，StateStore 写入报告错误后先删除 PreparedContract。
- `scripts/subagent_governance.py:3714-3722`，后续 task cleanup 和 PreparedContract cleanup 的异常均被吞掉。

**反例 A：并发事实被清理覆盖**

1. initial `compare_and_set()` 实际持久化 task。
2. 另一个 StateStore writer 给该 task 的 `work_item` 写入额外 canonical/extension fact。
3. 第一个写入方随后报告 readback failure。
4. `_cleanup_initial_attempt()` 的窄谓词仍成立，删除整个 task。

临时目录复现结果：`task_survives=false`、`concurrent_fact_survives=false`、PreparedContract 为空。也就是说，异常回滚删除了并发 writer 已提交的事实。

**反例 B：清理失败被隐藏并形成孤立状态**

1. initial StateStore 已持久化后报告错误。
2. 随后的 `_cleanup_initial_attempt()` 再次发生写错误。
3. 返回给调用者的错误只包含第一次写入错误，清理失败被吞掉。

临时目录复现结果：canonical task 仍存在、PreparedContract 已删除、`_action_required_records()` 为空。该 open/not-started task 不能 claim 原生 spawn、不会按 prepared expiry 回收，也不进入 action-required 提醒。

**影响**

- 违反异常恢复不得覆盖较新并发事实的 CAS/rollback 不变量。
- 可能留下无凭证、不可重试、不可自动过期且不进入责任视图的 dead state。
- 错误信息把 rollback-incomplete 伪装成普通 preparation failure，降低诊断能力。
- replacement/claim 路径已经采用完整快照保护；initial preparation 形成了同一抽象内不一致的恢复语义。

**最小修复方向**

- initial preparation 保存完整 pre/post task 快照，只有当前 task 仍逐字段等于本次 initial post-state 时才能删除。
- 在安全 task cleanup 完成前不要不可逆删除唯一 PreparedContract；无法证明安全回滚时保留可诊断凭证/状态并返回明确 degraded rollback-incomplete。
- 汇总并报告 cleanup errors，不使用空 `except`。
- 增加 persist-then-error、并发变化、cleanup failure、PreparedContract cleanup failure 四类回归测试，并断言 concurrent facts 不丢失、凭证与 task 不形成 split-brain。

**F10 实施状态（2026-08-14）**：已在开发仓库完成本地修复。initial PreparedContract 不复制第二份 canonical task；运行时从其已有完整 TaskContract、identity 与 `created_at` 确定性重建唯一 initial post-state。即时 preparation rollback 与 5 分钟 unclaimed initial reconcile 复用同一整 task equality：只有当前 task 逐字段精确等于 post-state 才在 StateStore CAS 锁内先删 task，确认 task absent 后再删 PreparedContract。extension、timestamp、identity、claim、`parent_action` 或任意字段变化均阻止两类删除并保留凭证；可写时持久化 `parent_action=reconcile`、rollback-incomplete marker，并对 health 做 `ok < degraded < unavailable` 的单调最小合并。health-only 并发更新不扩展 task marker CAS predicate，较新 health marker、非法形状和其他 health 字段均保留。不可写时错误明确说明凭证被保留供显式 reconcile/expiry 重试。task 已安全删除但凭证删除失败时报告 retryable orphan，后续 expiry 可在 task absent 时安全删除。原始错误与各 cleanup error 均汇总可见，不再有空 `except`。failure-first、决策表、异常矩阵和验证见 `docs/redesign/F10-initial-preparation-exact-rollback.md`。

本状态追加不改写上述原始 finding、临时反例或历史证据，也不改变 F9 retained-target identity admission 语义。

### P2

无独立 P2 finding。P1-2 已包含其诊断失败维度。

### P3

无。

## 3. 原 9 项 findings 对账

| 原 finding | 状态 | 独立依据 |
| --- | --- | --- |
| P1-1：closed/tombstoned work item 可再次 spawn | **resolved** | `_growth_admission_error()` 在 prepare 与 claim 检查 open/unclosed；close 后 retry、replacement prepare/claim 定向测试通过。 |
| P1-2：unclaimed replacement 绕过 candidate cap 且不能安全过期 | **resolved** | reservation 计入 candidate 与 action-required；claim 锁内重查；精确 expiry/CAS/并发变化测试通过。新 P1-2 是 initial preparation rollback，不是原 replacement reservation 缺口。 |
| P1-3：same-Agent A1 迟到 Stop/result 污染或拒绝 A2 | **resolved** | result/Stop 先用 `task_id + attempt` 与 retained provenance 路由；A1/A2 定向测试通过。 |
| P1-4：duplicate-risk 依赖 reason code 而非来源事实 | **resolved** | `_replacement_source_may_coexist()` 与全 candidate 集合从 canonical execution facts 派生；prepare/claim 都重查。 |
| P2-1：可靠 stopped source 仍制造 false duplicate/select | **resolved** | stopped/interrupted/closed 被 coexistence predicate 排除；claim 最终 stopped source 和 non-current live candidate 测试通过。 |
| P2-2：持久化 `work_item.action_required` 形成第二权威 | **resolved** | Schema 禁止该持久字段；`_sync_canonical_work_item()` 移除旧值；共享 candidate predicate 被 diagnose/group/Session/Stop 使用。 |
| P2-3：diagnose/SessionStart 缺少 growth facts | **resolved** | growth 从 canonical work item 单源投影，group 透传 member snapshot，SessionStart 使用同一 snapshot；定向测试通过。 |
| P2-4：Schema 不是可执行 canonical record 权威 | **resolved** | canonical state/task/work-item/execution/transition/operation/result/closure/decision definitions 可执行；runtime/Schema 双向枚举和组合测试、validator 通过。 |
| P3-1：canonical-only 退休后仍有死 guidance/runtime 残留 | **resolved** | S6/F7 residual scans 与 `test_s6_compatibility_retirement` 全部通过；现存旧名称只在显式 compatibility convergence 路径和测试中出现。 |

## 4. 核心不变量矩阵

| 不变量 | 结果 | 证据与边界 |
| --- | --- | --- |
| 关闭单向性与 growth admission | 通过 | closed/tombstoned 后 prepare 和 stale claim 均拒绝，不写 native spawn authority。 |
| reservation/claim/expiry/CAS/rollback | **部分通过** | replacement reservation 与 claim 路径通过；initial preparation rollback 存在 P1-2。 |
| same-Agent retained provenance | **部分通过** | Stop/result 迟到路由通过；lifecycle target 分类仍错误依赖 active index，见 P1-1。 |
| duplicate-risk/select/interrupt 收口 | 通过 | 全 live candidates 派生 risk；无精确 target 时保留 unresolved，不因空 target 列表伪关闭。 |
| canonical work-item 单一权威 | 通过 | work item + executions 为持久权威；attempt 只作为候选投影，无 root/prior 决策权威。 |
| growth facts | 通过 | 计数、soft facts 与 latest authorization 均来自 canonical work item；不授权执行。 |
| formal result/disposition | 通过 | result 文件和 StateStore 精确关联；formal disposition 与 growth authorization 分名分 enum。 |
| 平台恢复与 unknown | **部分通过** | success/failed/unknown、20 分钟 reconcile 和精确 Start 在正常 mapping 下通过；missing index 可绕过，真实平台不可见。 |
| Session/Stop/tombstone | 通过（本地） | Stop 三读、SessionStart/End、精确 tombstone/result cleanup 的测试通过；真实 Hook 行为未检查。 |
| diagnose/group | 通过（本地） | read-only、work-item-first、共享 action-required、独立 recent、member growth 均通过。 |
| Schema/runtime/docs 一致性 | **部分通过** | 原 F1-F7 semantic fields 一致；P1-1 的 runtime fail-open 与 Skill/runtime-boundaries 的 fail-closed 承诺不一致。 |
| Hook 故障降级边界 | **部分通过** | governed spawn 和正常 lifecycle StateStore failure 多数硬拒绝；P1-1 与 P1-2 分别存在错误 fail-open 和不可诊断 rollback。 |

## 5. 跨切片反例结果

| 反例 | 结果 | 观察 |
| --- | --- | --- |
| close 后 retry/replacement | 通过 | prepare 与已 prepared 的 stale claim 都拒绝；不复活、不写 `spawn_tool_use_id`。 |
| reservation 过期 / CAS 冲突 | 通过 | 只删除完整快照匹配的 reservation；并发变化不删除；CAS 失败不提交 growth count。 |
| A1/A2 同 Agent 迟到 Stop/result | 通过 | A1 结果留在 A1，A2 active mapping/状态不被覆盖。 |
| unknown replacement duplicate | 通过 | 从全部可能共存 execution 派生 duplicate；failed current 不掩盖 prior live candidate。 |
| select 后无 target 候选 | 通过 | `interrupt_targets=[]`，但未知未选 execution 仍 open、duplicate、`resolve_duplicate`；selected 也保持 unresolved。 |
| legacy null/non-null 冲突 | 通过 | canonical null 可吸收合法 legacy fact 并移除旧名；两个 non-null 不同值硬拒绝。 |
| action-required 与 recent 分离 | 通过 | stale prior 可 action-required 而不 recent；SessionStart 分区且不互相授权。 |
| 真实平台能力不可见 | `not_checked` | 本地只证明 adapter/fixture 语义，不能证明真实 Hook payload、Provider、mailbox 或 UI 提供这些事实。 |
| retained provenance 存在但 active index 缺失 | **失败** | 三类 managed lifecycle 均退化 unmanaged，见 P1-1。 |
| initial persist-then-error 后并发变化/清理失败 | **失败** | 并发事实可被删除；清理失败会留下无 PreparedContract 且非 action-required 的 task，见 P1-2。 |

## 6. 本地证据

### 完整验证

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
Ran 351 tests in 8.482s
FAILED (errors=2)
```

349 项通过；仅以下两个既有 release-preflight errors：

- `test_current_development_tree_passes_with_supported_ref`
- `test_release_requires_manifest_tag_and_marketplace_ref_to_match`

二者均报告 `host-specific path in docs/redesign/D6-migration-and-slices.md`。本复核按约束未修复 D6。

```text
PYTHONPYCACHEPREFIX="<temporary-directory>" python3 -m py_compile scripts/subagent_governance.py
# exit 0

python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
# Plugin validation passed

python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
# Skill is valid

rg --files -g '*.json' -0 | xargs -0 -n1 jq empty
# exit 0

git diff --check
# exit 0（创建本文前后）
```

创建本文后另行运行 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests.test_release_preflight`：5 项中 3 项通过，仍仅有上述两个 D6 errors；F8 未引入新的 preflight finding。随后复跑 Plugin validator 通过，并以 `git diff --no-index --check /dev/null docs/redesign/F8-post-remediation-integrated-review.md` 确认本文自身无 whitespace error。

### 聚焦反例验证

使用 `python3 -m unittest -v` 独立运行 12 项定向测试，覆盖：关闭后 growth、reservation expiry 与并发变化、replacement CAS、same-Agent 迟到 Stop/result、全 live candidate duplicate/select、legacy null/non-null convergence/conflict、action-required/recent 分离和 interrupt unknown。结果：

```text
Ran 12 tests in 0.107s
OK
```

新增 finding 使用 `PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY' ... PY` 在临时 StateStore 中执行三组非破坏性复现：

- missing active index：`platform_recovery`、`result_correction`、`business_resume` 全部 `managed=false + allow`，canonical provenance 保留而预算/attempt/pending 均不变。
- initial cleanup concurrent change：`task_survives=false`、`concurrent_fact_survives=false`。
- initial cleanup write failure：task 保留、PreparedContract 为空、action-required 为空，错误未包含 cleanup failure。

静态扫描还核对了 retired root/prior authority、`last_disposition`、execution `parent_disposition`、candidate `growth_facts` 与持久 `action_required`。命中均属于明确的兼容读取/收敛、Schema 禁止项、语义描述或测试；未发现新的运行时第二权威。

## 7. not_checked

- 未安装、发布、同步测试插件、稳定发布源或运行缓存。
- 未写 Hook trust、Marketplace、Registry，未执行 cachebuster/reinstall。
- 未新建真实测试对话；未检查真实 Plugin/Skill/Hook 加载。
- 未检查真实 `spawn_agent`/`followup_task`/`interrupt_agent` 参数形状、task name 可见性、Hook payload 中的 `task_result`、same-Agent target 标识或 `previous_status`。
- 未检查真实 Provider 断流、mailbox 唤醒、wait/list 状态投影、UI 终态展示和上下文压缩恢复。
- 未把 fixture、adapter、单测或本地 StateStore 结果解释为真实 transport/provider 验收。
- 未修复或绕过 D6 的两个既有 release-preflight errors。
- 未检查稳定发布源与运行缓存哈希、非符号链接关系或稳定发布准入，因为本阶段明确不发布。

## 8. 残余风险

- 即使修复两个 P1，本地模型仍无法证明平台会提供精确 Stop/result/Start/interrupt facts；unknown 和人工对账边界必须在真实测试中验证。
- Schema 可以约束 `agents` mapping 和 execution record 各自形状，但不能单靠 JSON Schema 证明跨对象 target 索引一致性；runtime reconciliation 和 diagnostics 仍承担该责任。
- compatibility convergence 是显式的 write-time 收敛，不是离线迁移。真实旧状态组合仍需通过测试插件环境观察，不能因当前 fixture 通过而假定所有历史状态可恢复。
- F8 的两个临时反例尚未成为仓库回归测试；在对应修复切片合入前，后续改动可能继续掩盖或扩大问题。
- D6 host-specific path 仍使完整 suite 非全绿；它不导致本次两个架构 finding，但会阻止后续 release-preflight 完整通过。

## 9. 下一阶段准入条件与建议任务拆分

### 当前准入决定

**不进入测试插件同步。** 先完成以下两个互不混合的本地切片：

1. **F9: retained-target managed lifecycle admission**
   - 统一 active index、retained provenance 与 truly unmanaged target 的机械分类。
   - 修复 generator 与 PreToolUse 两个绕过入口。
   - 覆盖 missing/stale/ambiguous mapping、same-Agent 多 attempt、三类 lifecycle 和既有 normal/interrupt 降级边界。
   - 同步 runtime、Schema semantic anchor、Skill/runtime-boundaries 与测试；不得隐式选择 attempt 或建立第二 identity authority。

2. **F10: initial preparation exact rollback**
   - 用完整 task snapshot 保护 initial persist-then-error cleanup。
   - 明确 PreparedContract 与 StateStore 的安全删除顺序及 rollback-incomplete 终态。
   - 覆盖并发变化、cleanup failure、prepared cleanup failure 和可重试/可诊断性。
   - 复用 F1 已有 rollback 语义，不另建 transaction log、scheduler 或迁移层。

### 重新准入所需证据

- 两个临时反例先成为稳定失败测试，再由最小修复转绿。
- 当前 351 项测试与新增测试全部通过；D6 两项若仍按当前任务保持已知例外，必须单独如实列出，不能称全绿或 release-ready。
- `py_compile`、Plugin validator、Skill validator、JSON parse、`git diff --check` 全部通过。
- 静态复核确认没有新的 identity authority、rollback state、隐式迁移或 unmanaged fallback。
- 完成新的本地 post-fix review 后，才进入“从开发仓库同步测试插件 -> 新建 `gpt-5.6-terra` / `high` 对话 -> 真实 Hook/Provider/UI 测试”。
- 真实测试通过仍只代表测试插件环境准入，不等于已安装稳定版、已发布或稳定发布可用。
