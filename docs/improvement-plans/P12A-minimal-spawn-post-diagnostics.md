# P12-A：governed spawn PostToolUse 最小诊断门槛

状态：本地实施完成，待授权安装与全新真实门槛验证；P12-B 的强制前置。<br>
执行配置：独立新对话，`gpt-5.6-terra`，`high`。<br>
原则：只回答“插件能否收到并以 same-ID 安全关联事件、以什么机械形状到达、在哪个关联阶段停止”，不修 identity，不扩大状态机。

## 为什么先做 P12-A

最新 P10-B V2 中，governed spawn 的 Pre claim 成功，child 也实际完成，但 canonical attempt 仍停在 `dispatch.state=claimed`、`post_observed=false`、`target_bound=false`。现有实现没有 spawn receipt，因此不能区分：

- 平台未向 Hook runtime 投递 PostToolUse；
- Post 到达但 tool name 未被 `tool_kind()` 识别；
- Post 使用了缺失或不同的 tool-use ID；
- same-ID Post 到达，但 PreparedContract lookup 或 canonical recheck 失败；
- adapter/handler/StateStore 写入失败；
- Hook 已处理，但缺少可跨 restart/compact 复盘的证据。

在这些分支尚未区分前直接实施完整 state-v9、identity binding、双阶段 transition 和 SessionStart 补偿，可能把平台能力边界扩大成长期架构。P12-A 不试图无条件区分全部分支；它只验证插件能否取得可作为 authority 的 same-ID Post 证据。没有 receipt 时，平台未投递、缺失/不同 ID 和 marker/Hook runtime 丢失仍可能无法互相区分，但它们都会触发同一个安全结论：停止 Post-based identity 扩建。

## 固定事实与证据纪律

- 基线报告：最新 P10-B 的 V1 passed、V2 failed、V3–V7 not_checked。
- 已证实：Pre claim 成功；child terminal 出现；exact list 返回唯一 completed target；canonical spawn Post/identity 未闭环。
- 未证实：平台是否投递 Post、Post 的真实 tool name/ID/envelope、handler 是否进入及失败阶段。
- “没有 probe receipt”只能表述为“插件没有保存关联到该 claim 的 Post 事实”，不得写成“平台没有投递”或“Codex bug”。
- 不读取、保存或输出 child 业务正文、prompt、summary、final、transcript、tool response 值、message 或完整 envelope。

## 范围

P12-A 只包含：

1. governed spawn Pre claim 后发布一个私有、短期、same-ID probe marker；
2. recognized spawn Post 或 unknown-name catch-all 的 exact marker hit 进入 sidecar diagnostics handler；
3. 对 current StateStore 与 current PreparedContract 作只为归属确认的 exact recheck；
4. 写入独立、严格、容量受限的 probe receipt；
5. 在 diagnose/view 中显示机械枚举和时间；
6. 完成本地测试后，经用户另行授权安装测试版并执行新的真实门槛任务。

P12-A 明确不包含：

- probe sidecar 自身不写 `dispatch_response`、`dispatch_target`、`agents` 或 `observation_record`；recognized spawn 保留既有 canonical Post transition；
- 不把 list/terminal/final 当作 Post 或 identity authority；
- 不改变 spawn retry budget、父方处置、等待、恢复或终态流程；
- 不增加 receipt-first canonical transition、generation replacement 或 PreparedContract settlement；
- 不修改 canonical state Schema，不升 `state_format_version`，不切换 `state-v9`；
- 不扩展 spawn success parser，不从 response 提取 target；
- 不做 SessionStart rebuild、自动修复或重放；
- 不读取、迁移、删除或重写旧 namespace/旧 probe 数据。

## 最小设计

### A. 独立 probe marker，不改 P11 lifecycle index

使用新的私有目录 `spawn-post-probe-ids-v1`，不升级或复用 P11 的 lifecycle `ClaimedPostIndex`。每条记录只含：

```json
{
  "probe_index_format_version": 1,
  "session_id": "…",
  "tool_use_id": "…",
  "task_id": "…",
  "attempt": 1,
  "task_ref": "…",
  "dispatch_operation": "initial_spawn | spawn_retry",
  "spawn_retry_count": 0,
  "claimed_at": 0,
  "expires_at": 0
}
```

- 文件名仍使用 SHA-256 `(session_id + NUL + tool_use_id)`，不得泄漏 ID。
- TTL 20 分钟、最多 256 条、目录/文件仅当前用户可访问。
- `claim_spawn()` 完成 StateStore 与 PreparedContract exact 回读后才发布 marker。
- marker 发布失败不撤销已 claim 的原生 spawn；Pre Hook 只输出固定码 `spawn_post_probe_unavailable`。
- lookup 只读，不创建目录、锁、StateStore 或输出。
- P12-A 不在 SessionStart 重建 marker；一次 marker 丢失被如实记录为诊断不可用，不借机增加恢复协议。

### B. 独立 probe receipt，sidecar 不写 canonical execution

使用新的私有目录 `spawn-post-probes-v1`。receipt 以 session/tool-use ID 的不可逆摘要定位，只允许以下机械字段：

```json
{
  "probe_format_version": 1,
  "session_id": "…",
  "tool_use_id_match": true,
  "task_id": "…",
  "attempt": 1,
  "task_ref": "…",
  "dispatch_operation": "initial_spawn | spawn_retry",
  "spawn_retry_count": 0,
  "tool_name_classification": "recognized | unrecognized",
  "admission_source": "recognized_prepared | exact_probe_marker",
  "claim_check": "not_checked | matched | prepared_missing | state_mismatch | validation_failed",
  "response_shape": "not_checked | empty | top_level_object | non_object | json_decode_failed | explicit_error",
  "handler_stage": "received | claim_checked | shape_classified | completed | handler_failed",
  "recorded_at": 0,
  "updated_at": 0
}
```

- 不保存 raw tool name；只保存 recognized/unrecognized。
- 不保存 response 字段名以外的值；若连字段名都非诊断必需，则只保存顶层 shape enum。
- 不保存 target、canonical path、child status、错误堆栈或任意业务字符串。
- handler 每推进一个机械阶段可 exact 更新同一 receipt；不得创建第二条不同 owner receipt。
- fixed bounded reason code 可进入 Hook UI；异常文本只在现有 fail-open 上下文中截断显示，不落 probe receipt。
- receipt 最多 256 条、保留 24 小时，允许显式 cleanup；不得扫描旧目录或借 cleanup 迁移数据。

### C. 严格入场

1. recognized spawn Post：优先查 exact probe marker；marker hit 后可以写 probe 并把后续 PreparedContract miss 记录为 `prepared_missing`。marker miss 时，只有 `PreparedContract.find_claimed(session_id, tool_use_id)` 返回唯一 current claim 才能 fallback 写 probe，并标记 `admission_source=recognized_prepared`。
2. unknown-name catch-all：只有 exact probe marker hit 才能构造后续 store，并必须再次精确核对 current PreparedContract 与 StateStore；不得使用 recognized-only Prepared fallback。
3. marker miss、missing ID、different ID、过期 marker、无关 catch-all：完全 inert，不写 receipt、不建 StateStore、不输出。
4. exact recheck 失败时，可以写入属于该 marker 的 bounded `claim_check` 结果，但不得由 probe 增加 canonical execution 写入；recognized spawn 随后仍执行既有 canonical Post 路径，unknown-name diagnostic 路径保持不变。different ID 因 marker miss 仍完全 inert。
5. P12-A 只调用纯 `spawn_response_shape()`；不得调用或扩大 success/identity adapter。

## 文件级实施清单

| 文件 | 修改 |
| --- | --- |
| 新的 probe storage 模块 | marker/receipt 的 strict validator、私有写入、TTL、容量、exact lookup/remove。 |
| `scripts/governance_dispatch.py` | claim 完成后发布 marker；失败仅返回固定诊断码。 |
| `scripts/governance_hook.py` | recognized/exact-marker sidecar admission；recognized 保留 legacy canonical handler，unknown marker miss 保持 inert。 |
| `scripts/governance_platform.py` | 增加纯顶层 `spawn_response_shape()`，不解析 identity。 |
| diagnostics/views | 只投影 probe enum、时间和 ID-match boolean。 |
| tests | marker、receipt、router、privacy、capacity、fault injection 和 regression。 |

不修改 canonical state Schema、P11 lifecycle receipt/index、Skill 的治理承诺或 Hook matcher。

## 测试矩阵

| 层级 | 必测 | 通过条件 |
| --- | --- | --- |
| marker | publish、same-ID lookup、different/missing ID、TTL、容量、损坏 | 仅 exact current claim 命中；miss 完全 inert。 |
| router | recognized spawn、unknown name + hit、unknown miss、unmanaged spawn | 前两类可写 probe；recognized 保留 legacy baseline，unknown-name probe 路径不写 canonical execution。 |
| recheck | Prepared missing、StateStore mismatch、attempt/ref/retry count mismatch | probe 仅写 bounded claim_check；recognized 的后续 legacy 结果保持基线，unknown-name 无 identity/dispatch 变化。 |
| shape | empty/object/non-object/invalid JSON/error envelope/nested content | 只记录顶层 enum，不读取 nested content。 |
| failure | marker write、receipt write、stage update、diagnostic read failure | 原生调用 fail-open；固定码；不伪造 Post 结论。 |
| privacy | raw name、target、response、message、summary、final、transcript 注入 | 全部拒绝或不落盘。 |
| regression | P1–P11 相关 suite、编译、Plugin/Skill validator、`git diff --check` | canonical state 与现有 lifecycle 行为不变。 |

## 实施顺序

1. 新任务完整阅读 `AGENTS.md`、P10/P11/P12-A/P12-B、最新 V2 报告、当前 Hook/dispatch/prepared/index/diagnostic 代码和测试。
2. 先补 failing tests，证明现有实现对 governed spawn 没有可复盘 probe。
3. 实现独立 marker/receipt store，再接入 claim 和 Post router。
4. 以 Pre claim 完成后的 snapshot 为基线，验证 probe sidecar 不增加额外 canonical 变化：recognized spawn 保留既有 canonical Post transition；unknown-name exact-marker diagnostic 路径前后 canonical state 逐字段相等。Pre claim 自身仍保留既有 canonical 变化。
5. 更新 P12-A 文档状态，跑完整本地门禁并提交；不得安装或宣称平台通过。
6. 用户明确授权后，使用受支持 installer 安装测试版并等待重启。
7. 创建全新的 Terra/high 真实验证任务，按下列门槛执行；不得复用实现任务充当真实验证。

## 真实验证门槛与停止条件

至少执行 3 次相互独立的 governed spawn，其中至少一次发生在 Codex 重启后的新任务中。每次只记录：Pre marker 是否发布、receipt 是否存在、name classification、ID-match、claim_check、response_shape、handler_stage，以及 canonical state 是否符合基线：recognized 为既有 legacy transition，unknown-name exact-marker diagnostics 为逐字段不变。

结果分流：

| 真实结果 | 结论与下一步 |
| --- | --- |
| same-ID receipt 稳定出现，claim matched，shape 可识别 | 证明 Post 可用于安全关联；允许评审并按实际 shape 缩减后实施 P12-B。 |
| receipt 出现且 name=unrecognized | 证明主要是路由/name drift；P12-B 只实施 exact marker route 和必要 binding，不扩大通用 matcher。 |
| receipt 出现但 Prepared/State mismatch | 只修证实的双存储一致性问题，再重跑 P12-A；不直接实施全部 P12-B。 |
| receipt 到达 handler_failed | 只修证实的 handler 阶段，再重跑 P12-A。 |
| 3 次均无 same-ID receipt，但 Pre marker 成功且 child 实际创建 | 停止 P12-B；只能表述为“插件未取得可安全关联的 Post”，原因可能仍包括未投递、不同/缺失 ID 或 runtime 丢失；不得按时间、task name、list 或 child terminal 继续猜 owner。 |
| 结果不一致/偶发 | 不实施自动恢复；增加的是验证样本或平台说明，不是更多状态机代码。 |

P12-A 的成功不是“修复 V2”，而是把未知分支缩小到足以做出继续或停止决定。只有上表明确允许时，P12-B 才从“条件方案”转为“待实施”。

## 本地验收标准

- 未新增 canonical 状态语义；recognized Post 保留既有 transition，probe 仅为 sidecar diagnostics。
- 无关 catch-all 与 different/missing ID 完全 inert。
- probe 只含白名单机械字段，容量、TTL、权限和 strict validator 有测试。
- recognized/unknown-name exact hit 可区分 handler 到达和失败阶段。
- 所有现有回归、编译与 validators 通过。
- 开发仓库提交完成；未安装、发布或写 stable/cache。
- 文档明确：absence of receipt 不是平台未投递的证明。

P12-A 没有需要预先决定的产品取舍；默认选择是最小、只诊断、可停止。任何超出本方案的 canonical 写入都必须回到用户重新确认。
