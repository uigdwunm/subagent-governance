# P11：followup PostToolUse 与 exact-list 的 current-only 绑定

状态：本地实施、门禁与测试安装已完成；全新 P10-B 在 V2 governed spawn 的 PostToolUse/canonical identity 闭环失败，V3–V7 未执行，须先另行诊断该前置缺口。  
前置：P10-B 的 V4 在真实任务 `01a0335e-bc19-7d32-bb57-4d948883f4b8` 失败；实现与文档基线为 `46b13b7`，整合报告提交为 `cb60308`。  
执行配置：独立新对话，`gpt-5.6-terra`，`high`。

本地实现已集成到当前改进分支：`cd76135`、`11cbd7b`、`6207eb9`。集成后 Python 3.9、3.11、3.12 各 307 个 unittest，以及 `py_compile`、development preflight、Plugin validator、Skill validator 和 `git diff --check` 均通过。测试版随后已安装，但全新 P10-B 在到达本方案重点 V4 前即于 V2 停止；真实平台状态仍以 `docs/platform-validation.md` 为准。

## 问题定义

P10-B V4 的 same-Agent `business_resume` 已通过 PreToolUse claim 创建 attempt 2，保留目标不变，并收到 attempt-2 的原生 final。可是：

- attempt 2 一直是 `dispatch.state=claimed`，即 `post_observed=false`；
- 对完整 canonical target 的 `list_agents({"path_prefix":"<exact-target>"})` 返回单个 completed Agent 后，attempt 2 仍没有 `observation_record.source=list_agents`，identity 仍未确认；
- 之后的 exact terminal notification 可以建立 terminal observation，但绝不能反推 followup PostToolUse 或 exact-list 已通过。

P11 的目标是分别消除和诊断这两个缺口：

1. 对 same-Agent resume 后的 exact list，将来自 active index/唯一未关闭 provenance 的目标绑定到 current attempt，不能因为 source attempt 保留同一 historical target 而静默丢弃事实。
2. 对 followup PostToolUse，先以最小、无业务正文的可观测性区分「Post 未投递」「事件到达但工具分类/ID 不匹配」「response envelope 未被 adapter 接受」「状态写入失败」。没有此证据，不把平台问题错误实现为放宽绑定。

这是 current-only 方案。不得读取、迁移、修复或删除旧 state namespace、旧 PreparedContract、旧 task name 或旧 session；若新增持久化字段需要格式升级，创建新的 current namespace/format 并显式拒绝旧格式。

## 已证实的证据与边界

### 已证实

| 事实 | 证据 | 结论 |
| --- | --- | --- |
| PreToolUse 已 claim resume attempt 2 | P10-B 状态及 Hook 输出；attempt 2/ref `e1ae7a569c62` 绑定 native call ID | business-resume preparation、context recheck、Pre claim 与 attempt/index 转移实际发生。 |
| source 和 attempt 2 使用同一 exact target | canonical session state：source 已 closed，attempt 2 为 current；二者 `dispatch_target` 相同 | same-Agent resume 的正常设计会形成两条 retained target provenance。 |
| native response call ID 与 Pre claim 相同 | 本机 session JSONL 的 function-call/function-call-output 有界摘要：`call_TOR…` 两端一致 | 没有 native call-ID 漂移的证据。 |
| followup native response 为零长度 envelope | JSONL 有界 shape：output length `0`、非 JSON | `adapt_lifecycle_response("")` 的既有规则会给出 `success`；若同一 ID 的 Post 到达 router，该 response 形状本身不应使 adapter 变成 unknown。 |
| exact list native response是 top-level `agents` 单元素 | JSONL 有界 shape：顶层仅 `agents`，元素有 `agent_name`/`agent_status`；输入只有 `path_prefix` | 形状与 adapter 的安全契约相符，且 returned name 等于 exact query target。不得从 child 业务正文取得任何状态。 |
| exact-list 内部路由在 resume 后必然无 candidate | `_resolve_exact_dispatch_target_attempt()` 扫描所有 executions，并仅在 `len(matches)==1` 返回；resume source 与 attempt 2 两条记录均有同一 target | 这是独立、确定的本地缺陷；`observe_agent_status_post_tool()` 于是无声返回，既不更新 state 也不给 Hook rejection reason。 |
| `agents[target]` 在 Pre claim 已转向 attempt 2 | `_create_resume_attempt()` 写入 index 后才设置 `current_attempt=2`；P10 state 曾显示 attempt 2 current/target bound | index/migration 不会阻止 lifecycle Post 按 tool-use ID 找到 pending；但当前 exact-list resolver没有使用该 index。 |

### 强推断，不是已证实的平台事实

- 若 `PostToolUse(followup_task, call_TOR…)` 到达现有 router，`_claimed_action_for_tool_use()` 应唯一定位 attempt 2 的 claimed pending，空 response 会被 adapter 归一为 success，随后会清除 pending、使 dispatch acknowledged。因此「Post 到达且 payload 保持当前 ID/shape、且状态可写」与 P10 最终 `claimed` 状态不相容。
- `hooks.json` 的 Post matcher 文本包含 `.*followup_task$`，router 的 `tool_kind()` 也接受 `followup_task` 及有前缀的名称；这提高“正常命名不会漏匹配”的可信度，但不证明真实平台确实发出 Post，或发出名称/ID与预期相同的事件。
- V2 的 spawn 与 exact list 已在同一 P10-B 任务完整闭环，故不是所有 PostToolUse、所有 list response 或所有 Hook 状态写入均失效。

### 仍需平台观测，不能猜测

当前资料无法区分以下分支：

1. 平台没有为这个 followup 发送 PostToolUse；
2. 平台发送了 Post，但现有 matcher 未匹配；
3. Post 到达 matcher 后的 tool classifier 未识别名称；
4. Post 的 `tool_use_id` 与 Pre claim 不同，或 response envelope 与 JSONL function-call-output 不同；
5. Post router/state 写入失败，但 UI/system message 未被保留为可审计证据；
6. exact list 的 Post 根本未到达，或已到达但被 adapter 拒绝。

终态通知、child final、transcript、summary、历史 final 和 list 的业务内容都不是这些分支的替代证据。

## 范围与非范围

范围：

- `followup_task` 的 PostToolUse 有界 transport receipt、ID/工具名/response-shape 的可诊断性；
- business-resume 后 same target 的 active/current attempt exact-list routing；
- 仅为上述两个路径所需的 current schema、views/diagnostics、fixtures、Hook contract/Skill 边界和测试；
- 本地门禁后，按 P10 的授权与全新对话规则重新验证 V1–V4。

非范围：

- 放宽 `path_prefix`、接受父路径/全量 `list_agents({})`、扫描 nested `content` 或 transcript；
- 以 terminal notification 或 native final 填补 Post/list state；
- 改变业务验收、child 消息正文、SubagentStart/Stop authority、重试预算或 parent disposition；
- 兼容/迁移旧状态；
- 安装、发布、stable source/cache/Hook trust/Marketplace/Registry 写入（本实施任务完成前一律禁止）；
- 在 P10失败任务中热修或续跑 V5–V7。

## 设计方案

### A. exact-list：按 current identity 安全路由，不按历史 target 全局唯一性路由

保留 adapter 的外部输入门槛不变：必须是 exact absolute `path_prefix`，顶层只允许一个 `agents` 元素，其 `agent_name` 必须逐字等于 query target，且 wrapper/error 规则维持现有严格性。

将 `observe_agent_status_post_tool()` 的内部解析替换为一个专用 `resolve_exact_list_observation_target(state, target)`：

1. 首先读取 `managed_target_admission(state, target)`。
2. 只有 admission 为 `managed`，且 candidate 的 `dispatch_target == target`、candidate 未关闭、`agents[target]`（若存在）与该 candidate 一致时，才路由到该 candidate；缺失 index 仅在唯一未关闭 retained provenance 的既有允许分支下由 admission 修复。
3. 若 index 指向未关闭但 target provenance 不符、同 target 有多条未关闭 provenance、或 target 仅剩 closed provenance，返回结构化拒绝原因并不写 observation。
4. closed source attempt 与 current attempt 共用 target 是预期 resume 历史，不构成第 3 步的歧义；list observation 只写 current/open attempt，绝不改写 source attempt。
5. `absent`、terminal、running、error、unknown 均使用同一个 resolver，避免空结果路径和非空结果路径语义分叉。

该改动保持“唯一 active/current identity”而不是“目标字符串在全部历史 execution 中只出现一次”。它不会从 list 生成 terminal notification，也不会将 not-found 单独视作 inactive。

同时让 router 对“adapter 已接受、但 canonical admission/route 拒绝”的结果返回有界 reason（例如 `current_identity_ambiguous`、`active_index_provenance_mismatch`、`closed_provenance_only`）。这修复现有 silent no-op，并使真实测试能辨别 adapter reject 与 lifecycle route reject。

### B. followup Post：先加入最小有界 receipt，再按结果分支实现

因为 P10 没有可观察的 Post delivery record，第一轮实现不得假设是 matcher、adapter 或平台问题。引入只记录机械字段的 temporary-but-tested current transport receipt：

- 关联键只允许 session、expected/received `tool_use_id`、native tool family、pending target、task/attempt/ref、时间和有限结果码；不得保存 `message`、TaskContract 内容、child final、response text、完整 envelope 或 transcript。
- response 只记录 `empty`、`top_level_object`、`non_object`、`json_decode_failed`、`explicit_error` 等固定分类，最多记录顶层字段名的截断集合；不得递归解析或存储任何字段值。
- 记录顺序必须在 lifecycle state transition 前。对同一 received ID 的重复 Post 幂等；receipt 写入失败必须 fail-open 并显式返回 bounded degraded reason，不能伪造 delivery success。
- 为让“名称未匹配”可见，Post hook 使用临时 catch-all transport entry（所有其他工具仍完全 inert、无 store construction、无 output），router 仅在其 ID/target能安全关联已 claim lifecycle pending 时写 receipt。这个 catch-all 是可观测性手段，不是把所有工具纳入治理。

由于当前 StateStore 严格拒绝未知字段，采用新的 current state format/namespace；不迁移 v6。receipt 位于 attempt 的 pending/last operation 所有者或一个严格有界的 current session transport section中，具体位置应在实现前由 schema/invariant 测试确定，且诊断投影只显示固定码、时间和 ID 是否匹配。推荐保留最新一次每 attempt receipt，避免累积事件日志。

#### 观测后的实施分支

| 观测结果 | 实施动作 | 禁止动作 |
| --- | --- | --- |
| receipt 显示 `followup`、same tool-use ID、empty response，transition 成功 | 修复仅需确保该路径有回归测试；P10 failure 的 Post 原因为当时事件未进入当前 router之外 | 不新增 response 宽松解析。 |
| receipt 显示 `followup`、same ID，但 adapter 分类为 unknown/failed | 仅扩展明确、顶层且被真实 envelope 证实的 response normalizer，并为该 exact shape 加 fixture | 不扫描 text/content/transcript，不把任意非空 response 当 success。 |
| receipt 显示 followup 但 tool-use ID 不同 | 将 pending 保持 claimed/reconcile，输出 `post_tool_use_id_mismatch`；同一次原生调用不得重发 | 不按 target 或时间猜测把 Post 绑定到 pending。 |
| catch-all 不产生可关联 receipt，而 native followup 的 call/output 仍存在 | 标记 `post_not_observed_by_hook`; 收集平台/Hook runtime 事件证据，作为平台投递或匹配边界处理 | 不把 native JSONL 当 Post event，也不从 child final 补状态。 |
| receipt 到达但 state transition 写入失败 | 保留 claimed、持久化健康/receipt failure 码，20 分钟后按既有 unknown reconcile，不回滚 attempt 或预算 | 不静默吞错或将 dispatch 直接 acknowledged。 |

是否长期保留 Post catch-all 由“需要用户决定的取舍”决定。无论选择如何，P11验收必须用 receipt 明确表明 P10新失败的分支。

### C. Post router 的 operation 类型必须来自已认领 pending

当前 hook Post 将 followup 与 normal message 都传为 `normal_message` 给 lifecycle adapter。空 response 因通用规则仍是 success，但该耦合会掩盖 operation-specific adapter 分支与 future diagnostics。实施时：先通过 tool-use ID 找到 claimed pending，再将其 `operation_type` 传给 `adapt_lifecycle_response()`；找不到 claim 时只形成有限 receipt/rejection，不以 tool name 或 target猜 operation。interrupt 的既有专用分支保持不变。

## 文件级修改清单

| 文件 | 修改 |
| --- | --- |
| `hooks/hooks.json` | 按选定取舍增加 Post catch-all transport 入口，或保留精确 matcher并证明真实名称；不得改变 Pre 的准入语义。 |
| `scripts/governance_hook.py` | 分离 Post receipt、tool classification、claimed pending lookup、operation-specific adapter 和 state transition；对 adapter reject 与 route reject 输出不同 bounded reason。 |
| `scripts/governance_lifecycle.py` | 提供 current-identity exact-list resolver；统一 absence/nonempty list route；提供 claimed pending 的只读解析和 receipt/state transition CAS。 |
| `scripts/governance_execution.py` | 如需，承载纯粹的 active-index/provenance predicate，避免 duplicate routing rules。 |
| `scripts/governance_platform.py` | 仅在真实 receipt 显示未知 shape 时添加最小顶层 normalizer case；保持不递归扫描。 |
| `scripts/governance_state.py`、`scripts/governance_state_store.py` | 定义新的 current-only strict state format/namespace、receipt 的字段上限和校验；旧格式直接拒绝。 |
| `schemas/governance-semantics.schema.json`、相关 contract/schema | 统一 receipt 枚举、route rejection codes 和 state ownership，避免代码私有字段漂移。 |
| `scripts/governance_views.py`、`scripts/governance_diagnostics.py` | 只投影 receipt 状态、时间、固定 reason 与 ID-match bool；不输出 response/message正文。 |
| `skills/subagent-governance/SKILL.md`、`docs/platform-validation.md` | 更新 followup Post 与 exact-list 的运行边界、诊断用法和 P10 status，不能把未重跑的平台事实记为通过。 |
| `tests/fixtures/*`、`tests/test_communication_lifecycle.py`、`tests/test_platform_observation_adapter.py`、`tests/test_p8_platform_hook_cli.py`、state/view/diagnostic tests | 覆盖下述矩阵。 |

如果真实 receipt 证明 matcher/平台 delivery 是唯一问题，则不改 platform normalizer；如果 current-identity resolver 可只在 lifecycle 内实现，则不为它创建泛化抽象。

## 状态迁移与失败策略

### business_resume 成功路径

```text
attempt N: terminal_notification + decide_disposition
  -> prepare business_resume (pending on N, prepared)
  -> Pre claim
     -> close N(reason=business_resume)
     -> create N+1(current, same target, dispatch=claimed, pending=claimed)
     -> agents[target] = N+1
  -> Post receipt (same tool-use ID, empty/supported envelope)
     -> N+1 dispatch=acknowledged; pending removed; parent_action=wait
  -> exact list(target)
     -> resolver selects active N+1, not closed N
     -> N+1 observation.source=list_agents
```

### 安全失败路径

- Post unknown/mismatch/write failure：N+1 remains `claimed` or moves only through the existing timed `unknown/reconcile` path. No resend to the same Agent.
- list adapter rejection：no canonical observation; emit adapter-specific reason.
- list route rejection：no canonical observation; emit route-specific reason and `reconcile` where current state is inconsistent.
- terminal notification：still may establish only its own exact terminal fact; it must not clear receipt ambiguity nor transform dispatch state.

## 测试矩阵

| 层级 | 必须新增或调整的案例 | 通过条件 |
| --- | --- | --- |
| platform adapter | `followup_task` 空 response；真实 receipt 若显示新 top-level shape则该 shape；error/non-object/nested content | 只接受明确顶层 shape；空 response=success；未知仍为 unknown。 |
| hook classifier/matcher | raw `followup_task`、namespaced followup、catch-all下无关工具；Post event tool name mismatch | 相关 event 有 receipt/明确 reason；无关工具不构造 store、不产生治理状态。 |
| ID binding | Pre claim 的 expected ID；Post same ID、different ID、missing ID、duplicate Post | same ID 只收口一次；mismatch绝不按 target/time绑定；duplicate幂等。 |
| business resume | Pre claim 建 N+1 后接 Post empty response | N closes、N+1 `acknowledged`、pending removed、index指向N+1、last lifecycle记录正确。 |
| exact list regression | N closed + N+1 open 同 target + index->N+1，list completed/running/error/absent | 四种结果都只写N+1；N的历史 observation不被改写。 |
| exact-list safety | index-target provenance不符、两个 open retained candidates、closed-only target、empty/multiple/wrong-name response | 不写 fact，给稳定 route/adapter code，并进入要求对账的边界。 |
| state/schema | receipt合法/非法、大小上限、未知字段、旧 namespace/format | 仅新格式接受；没有迁移/自动修复。 |
| view/diagnostic privacy | receipt发生、mismatch、write failure | 输出固定码、时间、match bool；不含 message、response body、contract/body 或 transcript。 |
| regression suite | P1–P9 相关全量 unittest、编译、Plugin validator、Skill validator、`git diff --check` | 全部通过；P11专用 cases包含在完整 suite。 |

现有测试给出的错误安全感：

- `test_business_resume_claim_creates_next_attempt` 只断言 Pre claim/attempt/index，完全没有为 attempt 2 投递 PostToolUse、空 response收口或 subsequent exact list。
- `recovery-limit-v1.json` 的 `followup_task` 空 response 覆盖的是 `platform_recovery` 同 attempt，不覆盖 resume 后的新 current attempt、same target 历史 provenance 或真实 Post delivery。
- `test_spawn_and_lifecycle_response_matrix`只测 `{"success": true}` 等通用 lifecycle shape，未断言 empty followup response 的 real hook round trip。
- `test_list_agents_accepts_only_one_exact_top_level_agent` 与 platform observation fixture都只有一条 target provenance；它们没有 construction of closed N + open N+1 same target。
- `test_hook_manifest_matchers_cover_router_tools`只检查 matcher 字符串包含工具名，未对正则执行、真实 Post delivery或 wildcard observability做契约测试。

## 实施顺序

1. 新对话完整阅读 `AGENTS.md`、本索引、P10、P11、真实报告、Skill 和相关代码；确认 P10之后没有未审计 runtime 变更。
2. 写 failing unit tests：resume N/N+1 same target exact-list、followup Post empty same ID、ID mismatch、route rejection；先证明现状。
3. 实现 current-only receipt/state contract及诊断投影，运行 format/privacy tests；不要先扩张 response parser。
4. 实现 exact-list current-identity resolver与route rejection，跑 adapter/lifecycle tests。
5. 使用 receipt 的结果实现上表对应的最小 followup Post 分支；若没有真实 shape证据，保留 strict unknown。
6. 更新 Hook/Skill/schema/docs，同步 machine contract与测试；运行完整本地门禁并提交开发仓库改动。
7. 只有用户重新授权后，按 P10-A 更新测试安装；之后建立又一个全新 P10-B对话，从 V1开始重跑，重点记录V4 receipt、attempt transition和 exact-list route code。

## 验收标准与 P10 重跑条件

P11 本地完成要求：

- same-Agent resume 后 N closed/N+1 current/shared target 的 exact list 在 N+1 写入 `source=list_agents`，且对不安全 index/provenance状态拒绝而非猜测；
- followup Post 的到达、ID匹配、response shape、adapter、state write各有可区分且隐私受限的证据；
- 同 ID empty response令 N+1从 claimed收口到 acknowledged；不匹配/未知不被错误确认；
- 所有上述测试和项目要求的全量门禁通过；没有旧格式迁移或外部安装写入；
- 实施 commit 已生成，文档不声称真实平台已通过。

P10只能在以下全部完成后重跑：P11本地门禁与 commit 完成、用户明确重新授权测试安装、installer完成并复核 digest/version、使用新独立任务加载目标版本。重跑必须从V1开始；V4须同时证明：

1. Pre claim、source close、N+1 current/index；
2. Post receipt显示实际分支，且若平台投递则 tool-use ID与Pre一致；
3. N+1 `dispatch.state=acknowledged` 与 `post_observed=true`；
4. exact `path_prefix` list 的 adapter和route均成功，N+1 `observation_record.source=list_agents`；
5. terminal notification仅作为独立终态事实记录。

V5–V7仍须在V4真实通过后才执行，不能被P11本地测试或旧P10 child final替代。

## 需要用户决定的取舍

1. 推荐：在一个测试版本中启用 PostToolUse catch-all，router对无关工具保持完全inert。优点是可区分“没有进入Hook”与可路由receipt，代价是每次Post都有轻量命令调用。若用户不接受，P11只能验证既有正则及已知名称，平台未投递与未知名称不匹配仍不可区分。
2. 推荐：receipt使用新的current-only state format/namespace、每attempt只保存最后一次固定码。优点是可跨compact/diagnose取证且不保存正文，代价是需要完整schema/validator/installer验证。若用户要求不持久化，只能在即时Hook UI中观察，P10失败无法复盘。
3. 真实 receipt 若显示非空但可解析的新followup envelope，是否仅支持该精确顶层shape（推荐）或把更宽泛的成功标签纳入adapter。推荐前者，避免把提供方文本或未知wrapper误认为delivery success。

未作出这些决定时，可以完成exact-list的确定性本地修复与相应测试，但不得声称followup Post的根因已确定或P10可以安全重跑。
