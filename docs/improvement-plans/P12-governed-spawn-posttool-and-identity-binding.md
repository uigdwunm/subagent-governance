# P12-B：governed spawn PostToolUse 与 canonical identity 条件修复

状态：条件方案；当前不得实施。只有 P12-A 真实验证满足激活门槛后，才可缩减并转为待实施。<br>
前置：P11 已在本地实施并安装，但新独立真实任务 `01a0339e-f49b-7990-a5db-d70ca7dee6d9` 的 V2 failed。<br>
执行配置：独立新对话，`gpt-5.6-terra`，`high`。

## 激活门槛

本方案不再作为 P10-B V2 failure 后的直接实施项。必须先完成 [P12-A 最小诊断门槛](P12A-minimal-spawn-post-diagnostics.md)，并取得以下任一真实证据：

- same-ID Post probe receipt 稳定出现，current PreparedContract 与 StateStore exact recheck matched；
- receipt 证明 tool name 未识别，但 exact marker 可以安全关联 owner；
- receipt 明确定位到插件 router、adapter 或写入阶段的可复现失败。

若 P12-A 的独立真实任务均没有 receipt、真实 Post 使用不同/缺失 ID，或结果仍不足以建立 same-ID authority，本方案保持冻结。不得以更多 catch-all、list 推断、时间匹配、task name 猜测或 SessionStart 自动恢复绕过门槛。

P12-A 通过后也不能原样照搬本方案：实施任务必须以实际 probe shape 和失败阶段删除无证据支持的分支，只保留解决已证实问题所需的最小子集。

## 问题定义

最新 P10-B 的 V2 通过了 governed spawn 的 PreToolUse 双门禁和 claim，却没有完成原生 PostToolUse/canonical identity 闭环。attempt 1 仍是 `dispatch.state=claimed`、`post_observed=false`、`target_bound=false`、`dispatch_target=null`、`observation_record.source=null`。完整 canonical target 的 exact `list_agents` 原生返回唯一 completed Agent，仍没有写成 canonical observation。

这不是 child 存在或业务完成的问题。若 P12-A 证明 same-ID Post 是可用 authority，P12-B 才让一次已 claim 的 **governed spawn** 获得与 P11 lifecycle claim 同等严格、可复盘、隐私受限的 Post 关联，并只在同一 Post 的严格 adapter 明确提供 canonical target 时绑定 identity。它不从 list、terminal notification、child final、summary 或 transcript 补回缺失的 spawn Post。

这是 current-only 方案：不得读取、迁移、修复、删除或重写旧 state namespace、旧 PreparedContract、旧 task name 或旧 session。新增持久化字段必须使用新的 current format/namespace，旧 current format 也直接拒绝。

## 固定基线和证据纪律

- 分支/起点：`codex/current-only-improvements`，`e71774822ddfc61483da0b81c7486e08cbe57f61`。
- 测试安装：`0.4.0-rc.13+codex.20260824114902`；stable/cache digest 为 `8d4f05e2b61bf62af6bb86c55d0f1b7ec05febbe33c4c50ed7df9204b4e1f004`。
- 最新真实任务：`01a0339e-f49b-7990-a5db-d70ca7dee6d9`；V1 passed、V2 failed、V3–V7 not_checked。
- 诊断和复验只能保留工具分类、ID 是否相等、顶层 envelope shape、受限字段名集合、长度和时间等机械摘要；不得读取或保存 child 业务正文、summary、历史 final 或 transcript。

### 已证实事实

| 事实 | 有界机械证据 | 可得结论 |
| --- | --- | --- |
| 最新 V2 的 PreToolUse 实际 claim 成功 | P10-B 报告记录凭证已消费、双门禁完成 | governed spawn 的 current claim 确实发生。 |
| child terminal 已出现 | 报告记录终态标记 | 原生 child 曾存在；不是 Post/identity authority。 |
| exact list 返回唯一 completed target | 顶层 `agents` 单元素的 shape 摘要 | raw list 符合已知 adapter 输入形状；未证明 router/route 成功。 |
| canonical attempt 保持 claimed 且 target/observation 为空 | 安装版只读 diagnose | spawn Post transition 未成功完成，list 未写 canonical fact。 |
| 上一次 P10-B 的 V2 passed | `f96d9f4` 之前的报告记录 `acknowledged`、`post_observed=true`、`target_bound=true`、`source=list_agents` | 同类 V2 曾闭环；不是本次平台投递的证明。 |
| 两次 V2 都取得 Pre claim 和 exact list | 两版真实报告的最小操作/状态摘要 | 本次不能归因于所有 Pre hook 或所有 list 调用失效。 |

### 代码上可确定的缺陷

1. `claim_spawn()` 只消费/写入 PreparedContract 和 canonical `dispatch_record.tool_use_id`；它不发布 `ClaimedPostIndex`，也不保存可供索引重建的独立 spawn claim timestamp。
2. `ClaimedPostIndex` 只接受 lifecycle 的 `normal_message`、`platform_recovery`、`business_resume`、`interrupt`；`rebuild_claimed_post_index()` 只扫描 `pending_action.phase=claimed`。它不覆盖 consumed/claimed PreparedContract 或 claimed spawn dispatch。
3. Post catch-all 在 `tool_kind(...) is None` 时只查上述 index。spawn 没有索引，未知或变名 spawn Post 会完全 inert：不建 StateStore、不读 PreparedContract、不写 receipt、不输出 reason。
4. 已识别 spawn Post 仍是旧路径：`PreparedContractStore.find_claimed(session_id, tool_use_id)` miss 时直接 `return None`；命中后直接 adapter + `observe_spawn_post_tool()`。它没有 receipt-first 状态、没有 classifier/ID/Prepared lookup/adapter/StateStore-write 的分段结果，也没有统一的 duplicate 语义。
5. 若旧 `observe_spawn_post_tool()` 真正执行，dispatch 至少会转为 `acknowledged`、`rejected` 或 `indeterminate`，或抛出而被 Hook fail-open 报告。因此本次 `claimed` 与“同 ID、已识别 Post 已完整执行”不相容；但不能区分未投递、变名、不同 ID、lookup miss 或 router/runtime failure。
6. P11 的 `post_receipt` 需要 lifecycle target、family 和 `pending_action`。它不能安全承载 target 尚未知的 spawn，现有严格 validator 也拒绝临时扩字段。

### 强推断和待观测分支

不能把平台偶发性直接标作代码 bug。`hooks.json` 的 Post matcher 为 `.*`，只证明配置意图，不能证明运行时为本调用投递 Post，也不能证明 name/ID 契约不变。当前证据仍无法区分：平台未投递；投递但名称未识别；ID 缺失/不同；同 ID 到达但 Prepared lookup、adapter 或 StateStore write 失败；或 Hook runtime 没有可审计地报告失败。

没有 receipt 只能表示“本插件没有保存已关联 Post 事实”；不得写为 `post_not_observed_by_hook`、平台无 Post 或平台 bug。

## 为什么 exact-list 不能补 identity

`list_agents` adapter 只证明调用者的 `path_prefix` 等于返回单元素的 `agent_name`。最新 failed attempt 没有 `dispatch_target`、`agents[target]` 映射或 retained target provenance；`resolve_exact_list_observation_target()` 必然返回 `unmanaged_target`。list tool-use ID 也不与 spawn claim 关联。

按 task name、时间邻近、唯一 claimed spawn、child terminal、raw list completed 或父路径猜 owner 都不安全：同 session 可以有并发 claim，调用者可以查询任意 target，外部 target 不因“像本 task”成为 canonical identity。不得放宽 `path_prefix`、接受全量 list、扫描 response、或让 list 自行写 `dispatch_target`。

唯一不放宽门槛的前向修复是：在 spawn Post 用 exact claimed `tool_use_id` 重验 owner 后，只使用 adapter 接受的 native canonical path 写 `dispatch_target` 和 `agents[target]`。随后 exact list 才有 provenance 可路由。对已有 failed attempt 不存在安全回填入口，必须保持 `reconcile`。当前没有依据证明 canonical path 可从 Pre 阶段机械计算，P12-B 不预绑定。

## 范围与非范围

范围：

- governed `spawn_agent` 的私有 claimed-ID index、catch-all admission、receipt-first Post transition、可重入补偿和严格 canonical target binding；
- spawn/lifecycle receipt 的 current-only 数据模型、diagnostics、views、SessionStart rebuild；
- 最小本地复现、门禁和下一次 P10 V2 重跑。

非范围：

- 不从 list/wait/terminal notification/child final/summary/transcript 推导 Post 或 identity；
- 不改变 TaskContract、Pre 准入、原生 spawn、retry budget、终态通知或父方处置；
- 不让无关 catch-all 事件进入治理，也不保存原始 tool name、tool input、response 值、完整 envelope、message 或业务正文；
- 不安装、发布、同步 stable/cache、修改 Hook trust、Marketplace、Registry、push 或 tag。

## 推荐设计

### A. 扩展 P11 私有 index 覆盖 spawn claim

将 P11 的 index 升级为 `index_format_version=2`，加入严格 discriminant：

```json
{
  "index_format_version": 2,
  "claim_kind": "spawn | lifecycle",
  "session_id": "…",
  "tool_use_id": "…",
  "task_id": "…",
  "attempt": 1,
  "task_ref": "…",
  "operation": "initial_spawn | spawn_retry | normal_message | platform_recovery | business_resume | interrupt",
  "dispatch_generation": "0 | 1 | 2 | null",
  "claimed_at": 0,
  "expires_at": 0
}
```

字段只是机械关联键；`dispatch_generation` 对 spawn 等于 `spawn_retry_count`，对 lifecycle 固定为 null，用来区分同一 execution attempt 内最多三次原生 spawn。不得加入 target（spawn receipt 前未知）、task prompt、message、response、原工具名或业务结果。保留 SHA-256 `(session_id + NUL + tool_use_id)` 文件名、私有权限、512 条容量和 20 分钟 TTL；lookup 保持只读且不创建目录、锁或 StateStore。

`claim_spawn()` 在 canonical state 和 PreparedContract 都精确回读为 claimed 后发布 spawn index。发布失败不撤销已许可的原生调用、不重派；Pre output 给出 `spawn_post_index_unavailable`。dispatch record 增加显式 `claimed_at`，SessionStart 才能从 current `dispatch_state=claimed + tool_use_id + claimed_at + dispatch_generation` 重建未过期 index；重建还必须精确确认 current PreparedContract 同 session/task/attempt/ref/ID/generation 且 consumed、未观察 Post。旧 PreparedContract 不读。

index 只是 admission hint。命中后仍须在 current StateStore 和 current PreparedContract exact CAS recheck。无 ID、过期/未命中 hint、无关 catch-all 事件保持完全 inert：不构造 StateStore、不输出、不写 state。

### B. 统一、区分 origin 的 receipt；不伪造 spawn target

将 P11 receipt 升级为严格 union：

```text
post_receipt = lifecycle_receipt | spawn_receipt
```

共同字段为 origin、session/task/attempt/ref、expected/received ID、`id_match=true`、`tool_name_classification`、`response_shape`、`processing_result`、`transition_state`、`recorded_at`。只允许 `recognized|unrecognized`，不得保存原 tool name。

`spawn_receipt` 还包含：

- `origin="spawn"`，`operation="initial_spawn|spawn_retry"`；
- `dispatch_generation=0|1|2`，必须与 receipt 对应 claim 的 `spawn_retry_count` 相等；
- `identity_result="bound|not_present|adapter_unknown|adapter_failed"`；
- `target_present` boolean（仅表示 adapter 接受的 top-level target 是否存在）；
- `prepared_settlement="mark_observed|delete_failed"` 与 `prepared_settlement_state="pending|applied|failed"`；
- receipt 时刻的 `previous_parent_action`（固定 enum/null）。

target 字符串只在 adapter 成功、exact owner recheck 后写入 `dispatch_record.dispatch_target` 和 `agents[target]`；receipt 本身不存 target。每个 execution attempt 仍只保留一个 current receipt slot，以延续 P11 的 bounded state：同一 generation 的不同 ID 永不覆盖；未完成的 receipt 永不覆盖；只有上一个 receipt 已 `transition_applied` 且 Prepared settlement 已 `applied`，并且新的同-attempt retry 已按更高 `dispatch_generation` 完成 exact claim 时，才允许用新 receipt 替换旧 receipt。旧 receipt 不作为历史 ledger 保留，retry count 与当前 receipt generation 提供当前诊断边界。

建议升为 `state_format_version=9`、新的 `state-v9` namespace，配套 schema、手写 validator、views 和 diagnostics；state-v8 和任何旧 PreparedContract 直接拒绝、不迁移、不删除。

### C. spawn Post router 的 index-first / receipt-first 协议

1. 取非空 `session_id`/`tool_use_id`。unknown-name catch-all 先查 index；miss 完全 inert。recognized spawn 使用同一 resolver；index miss 时允许直接以 `PreparedContract.find_claimed` 返回的唯一同 ID current claim 作为 fallback，并输出 `spawn_index_fallback_used`，随后仍执行完整 StateStore/PreparedContract exact recheck。这个 fallback 只属于已识别 spawn，不向 unknown-name catch-all 开放，也绝不按 task name/target 查找。
2. index hit 或 recognized exact-Prepared fallback 后才建 StateStore，重验 attempt open、`dispatch_state=claimed`、stored ID、task/attempt/ref/operation/generation/claimed-at 全等；再读取 PreparedContract 并重验 consumed、同 session/task/attempt/ref/ID/dispatch operation/generation。任何不符不写 receipt/identity，输出 `spawn_index_state_mismatch` 或 `spawn_prepared_lookup_miss`。
3. 只调用一次严格 `adapt_spawn_response()` 与新增 `spawn_response_shape()`。只解析一个顶层 JSON value 和允许的 documented top-level/`structuredContent` 字段；不得读 nested `content`、text、message 或 agent output，原始 response/字段值不落盘。
4. CAS 先写 `spawn_receipt.transition_state=receipt_recorded`。predicate 接受 exact claimed dispatch、同 ID/同 generation 已有 spawn receipt，或满足上一节严格替换条件的新 retry generation；其他不同 ID/generation 一律拒绝。写失败返回 `spawn_post_receipt_write_failed`，保留 claimed/reconcile。
5. 第二个 CAS 从 receipt 重入 transition：先恢复 receipt 的 `previous_parent_action`，再按 normalized result 更新 dispatch。
   - `success`：`acknowledged`；只有 adapter 提供合规 absolute canonical path 时绑定 target/index、`identity_result=bound`；success 无 path 保持 unconfirmed、`not_present/reconcile`。
   - `failed`：走现有受限 spawn retry；不得因为 child/list 事实改成功。
   - `unknown`：`indeterminate/reconcile`，不绑定 target。
   成功后写 `transition_applied`。写失败写 `transition_failed` 并保持 reconcile；same-ID duplicate 仅重入此 CAS。
6. transition 后按 receipt 的固定 settlement exact 收敛 PreparedContract：`success|unknown` 用 `recorded_at` 写 `post_observed_at`；明确 `failed` 则 exact 删除该 claimed PreparedContract，为同 attempt 的受限 retry 让出相同 `task_ref` 路径。settlement 失败不回滚 canonical dispatch/identity、不重派；receipt 写 `prepared_settlement_state=failed`，分别输出 `spawn_prepared_mark_observed_failed` 或 `spawn_prepared_delete_failed`。duplicate 或 SessionStart maintenance 只对同 session/task/attempt/ref/ID/generation 的 current record 重试相同 settlement。settlement 成功才删 index；完整完成后的 duplicate inert。

`post_observed` 诊断从 spawn receipt 已记录派生，`target_bound` 只从同一 Post transition 的 dispatch target 派生。这样 receipt 存在但 identity 未知，与 Post 完全未关联，成为不同的状态。

### D. exact-list 不变

保留 P11 current-identity resolver。只有上述 spawn Post 已绑定 dispatch target/index，adapter 接受的 exact list 才能写 `observation_record.source=list_agents`。target 为空的 claimed/acknowledged attempt 即使 list “看似匹配”也保持 `unmanaged_target` 拒绝，不回填身份。

## 失败和重试策略

| 边界 | 记录/行动 | 禁止 |
| --- | --- | --- |
| missing ID / catch-all miss | 完全 inert | 建 store、按名称/时间/target猜 owner、声称平台未投递。 |
| unknown name + exact spawn hit | `unrecognized` receipt 后 exact recheck | 保存原名或把 name 当 owner authority。 |
| different ID / Prepared miss | 不转 dispatch；固定 `spawn_prepared_lookup_miss`/`spawn_index_state_mismatch` | 匹配最近 claim、重派、绑定 raw target。 |
| empty/non-object/unknown envelope | receipt 记录 shape，`unknown/reconcile` | 任意非空 envelope = success。 |
| explicit failure | receipt-first 后既有 retry budget | 以 child/list 覆盖为 success。 |
| receipt write failure | fail-open message、claimed/reconcile | 静默吞错或 claimed→acknowledged。 |
| transition failure | `transition_failed`、same ID可重入 | 再发原生 spawn 或消费 retry。 |
| Prepared settlement failure | transition 不回滚，exact maintenance retry；failed 走 exact delete，其他结果走 mark-observed | 读/修历史 PreparedContract，或在旧 failed 凭证仍占位时创建 retry。 |
| index publish failure | known tool可唯一 Prepared fallback；unknown catch-all inert | 拒绝已 claim call或扩大 catch-all 搜索。 |
| duplicate same ID | applied 后 inert；未完成仅重入本地 CAS/settlement | 第二 receipt、第二绑定、第二 native call。 |

views/diagnostics/Hook UI 只显示 origin、时间、generation、ID-match bool、name classification、response shape、processing/identity/transition/settlement enum 与 bounded reason；不显示 message、raw response、tool input、contract、child final、summary 或 transcript。

## 替代方案和取舍

| 方案 | 结论 |
| --- | --- |
| 只扩展 `tool_kind()` 的 spawn 名称 | 无法发现未来变名、ID/lookup/write失败；拒绝。 |
| 只用 recognized `PreparedContract.find_claimed()` | unknown catch-all仍 inert，无 receipt-first/reentry；拒绝。 |
| list 按 task name/时间回填 target | 破坏 identity admission，可绑定外部/并发 target；拒绝。 |
| 为 spawn 单独无关 event log | 分叉 P11 的重入/隐私/诊断规则；不推荐。 |
| **推荐：扩展 P11 index + discriminated receipt** | 统一安全入场、failure attribution，且无关 catch-all 仍 inert；采用。 |

只有 P12-A 激活本方案后，用户才需决定是否接受推荐的 state-v9/index-v2 与每 attempt 一个可由严格新 generation 替换的 current 持久化 receipt。激活前不做该取舍，也不以“需要跨 compact/restart 诊断”为由提前扩大 canonical state。catch-all 已是 `.*`；若实施，P12-B 只让私有 index exact hit 的 unknown-name spawn 进入处理，不增加无关 state I/O；recognized spawn 的 exact Prepared fallback 仍受双存储重验约束。

## 文件级清单

| 文件 | 修改 |
| --- | --- |
| `scripts/governance_dispatch.py` | spawn index publication；receipt-first spawn transition、identity binding、Prepared settlement/reconcile。 |
| `scripts/governance_post_index.py` | index-v2 discriminant、spawn builder、strict validation、TTL/capacity/exact remove。 |
| `scripts/governance_lifecycle.py` | shared lookup/rebuild/maintenance，保持 lifecycle 语义。 |
| `scripts/governance_hook.py` | spawn recognized/catch-all admission 与 bounded reason；miss 不建 store。 |
| `scripts/governance_platform.py` | pure `spawn_response_shape()`；仅按真实 receipt 精确扩 adapter。 |
| `scripts/governance_execution.py` | 如需，纯 spawn claim/receipt predicate；绝不让 list 绑定 identity。 |
| state/store/semantics/schema | state-v9、discriminated receipt、claim timestamp、machine enum/validator。 |
| sessions/views/diagnostics | rebuild、exact settlement retry、隐私受限 projection。 |
| Skill/platform docs | 仅实现后更新边界/状态，不能声称平台通过。 |
| dispatch/hook/adapter/state/view/diagnostic/session tests | 覆盖下列矩阵。 |

`hooks/hooks.json` 已有 `PostToolUse.matcher=".*"`，P12-B 不需新增 matcher。若 runtime matcher 语义异常，只记录为平台验证分支，不放宽 identity。

## 状态迁移

```text
prepare dispatch
  -> Pre exact claim (PreparedContract + dispatch=claimed + claim timestamp)
  -> publish private spawn index
  -> Post same session + same ID
       -> exact state + PreparedContract recheck
       -> spawn receipt=receipt_recorded
       -> success + canonical path: acknowledged + target bound + active index
          success + no path: acknowledged + unconfirmed/reconcile
          failed: rejected + existing retry rule
          unknown: indeterminate + reconcile
       -> receipt=transition_applied
       -> success/unknown: PreparedContract mark-observed
          failed: PreparedContract exact delete
       -> settlement applied -> index remove
  -> exact list admissible only after target bound
```

`receipt_recorded`/`transition_failed` 是 durable recovery point，不是成功断言；`transition_applied` 才是 duplicate inert point。canonical target 的唯一来源是 adapter 接受的 spawn Post，list 只是既有 identity 的观察。

## 测试矩阵

| 层级 | 必测 | 通过条件 |
| --- | --- | --- |
| index | initial/retry publish、TTL、512上限、损坏、SessionStart rebuild | only current exact claim发布；旧/过期不复活。 |
| hook | raw/namespaced spawn、unknown name + hit、unknown miss、missing ID | hit 才建 store；miss/missing完全 inert；无原名泄漏。 |
| binding | same ID、different ID、Prepared mismatch、task/attempt/ref mismatch | only exact owner写 receipt；其余不转移。 |
| adapter | canonical path、success无path、explicit error、empty/non-object/JSON failure/nested content | 只接受明确顶层；unknown不绑定。 |
| reentry | receipt/transition/settlement fault + duplicate/SessionStart | 一个current receipt、无第二 native call、正确reconcile。 |
| same-attempt retry | generation 0/1/2、旧 applied receipt、旧 failed Prepared 删除失败/成功 | 未完成旧 receipt 不覆盖；settlement 完成后仅 exact 新 generation 可替换；旧凭证占位时不创建 retry。 |
| identity/list | bound 后 running/completed/error/absent；unbound后相同list；多open/index冲突 | 前者仅写正确attempt；后者拒绝不回填。 |
| retry | failed、unknown、success无identity | 仅明确failed进入既有retry。 |
| privacy/schema | 非法字段、泄漏、state-v8/旧Prepared | 新格式严格；旧数据不读不迁移；view无正文。 |
| regression | P1–P11相关完整 suite、编译、Plugin/Skill validator、`git diff --check` | 全过，wildcard inert contract不回退。 |

## 实施顺序

1. 新实施对话先读取 P12-A 的本地与真实验证报告，确认激活门槛已满足；否则停止，不修改代码。随后完整阅读 `AGENTS.md`、本索引、P10/P11/P12-A/P12-B、真实报告、当前安装 Skill、Hook、state/schema/dispatch/lifecycle/router/tests，确认 HEAD/工作树。
2. 先写 failing tests：spawn unknown-name Post invisibility、same-ID receipt/target binding、ID mismatch/inert、receipt/transition/settlement fault、同-attempt generation replacement、unbound-list refusal。
3. 实现 state-v9/schema/validator、index-v2；不读 state-v8/旧 PreparedContract；先跑 format/privacy/index tests。
4. 实现 `claim_spawn()` publication/rebuild、exact catch-all admission、receipt-first/reentrant transition 和 Prepared settlement。
5. 保持 P11 lifecycle 回归；只有真实 receipt 出现新 shape时才最小扩 adapter。
6. 更新 views/diagnostics/Skill/docs，跑完整本地门禁并提交。此时仍不得安装或称真实平台通过。
7. 用户明确重新授权后，按 P10-A 受支持 installer 更新测试版、复核新 digest/version，再建全新 P10-B 从 V1 重跑。

## 验收标准和下一次 P10-B 门槛

P12-B 本地完成要求：spawn Pre claim 有严格可重建 index；无关 catch-all 完全 inert；same-ID/same-generation Post receipt 先于 transition 持久化且可重入但不重派；同-attempt retry 只能在旧 settlement 完成后以更高 exact generation 替换 current receipt；只有 accepted canonical path 绑定 target；ID/Prepared/adapter/receipt/transition/settlement 失败各有不同固定码；unbound spawn 不可由 list 补 identity；新格式、隐私和全量门禁通过；开发仓库完成提交且无外部写入。

下一次 P10-B 必须在以上门禁、用户重新授权安装、installer digest/version 检查和**新的独立任务**完成后开始。V2 从 V1 重跑并记录：

1. Pre claim 的 task/attempt/ref 和 tool-use ID 是否可比（不记录正文）；
2. spawn receipt 的 origin、generation、ID-match、name classification、response shape、processing/identity/transition/settlement enum；
3. `dispatch.state=acknowledged`、`post_observed=true`，且只有 receipt 表示 target bound 时 `target_bound=true`；
4. 使用该 dispatch target 的 exact list adapter/route 成功并写 `observation_record.source=list_agents`；
5. terminal/final 只作自己的独立事实，绝不作为第2–4项证据。

V3–V7 只在 V2 完整通过后执行。若 V2 再失败，停止于 V2，保留最小 enum/时间证据并回开发仓库；不热修 cache 或继续后续场景。

## 激活后才需要用户决定的问题

1. 是否批准推荐的 `state-v9`/index-v2 current-only 升级及每 attempt 一个可由严格新 retry generation 替换的 current 持久化 receipt？推荐批准。
2. 若真实 receipt 显示新的无业务正文顶层 spawn envelope，是否只支持该精确 shape（推荐），还是放宽成功 parser？推荐只支持精确 shape。
3. PreparedContract settlement 失败时，是否允许 SessionStart 对**同一 current exact record**作一次无业务数据重试（推荐；success/unknown 重试 mark-observed，failed 重试 exact delete），还是只报告 degraded 并等待用户动作？两者都不得重派或读取历史 PreparedContract。
