# 平台能力契约重设计：实施切片 2

日期：2026-08-14

状态：开发仓库内实现、原 B1-B4、NB1/NB2 与 empty list alias scope blocker 修复和本地门禁完成；可以再次开始独立验收。未安装、未部署、未发布、未执行真实平台测试。

## 1. 目标与边界

本切片把 managed execution 的持久化语义拆成四个相互独立的 canonical plane：`DispatchRecord`、`ObservationRecord`、`ResultRecord` 和 `ClosureRecord`。StateStore 当前格式为 `state_format_version=2`。旧字段只在读取边界由四平面单向投影，写盘时全部删除，不能与四平面形成双权威。

本切片保持 Slice 1 的 Hook 行为：SubagentStart/SubagentStop 仍是 unbound advisory observation；缺失事件、未知状态、StateStore 不可读和结果缺失均不新增 hard gate。本切片没有实现 result credential，没有启用 active freshness 或 parent Stop limited hard gate，也没有新增 transcript adapter。

## 2. Canonical 四平面

每个 format-2 managed execution 必须同时包含以下记录：

| 平面 | 权威事实 | 本切片明确不代表 |
| --- | --- | --- |
| `dispatch_record` | `task_id + attempt + task_ref`、dispatch state、Pre/Post tool correlation、`dispatch_target` | Agent 已启动、runtime identity、业务结果 |
| `observation_record` | observation subject、binding basis、source、`not_observed/active/terminal/absent_at_check/error/unknown` | 业务结果、父处置 |
| `result_record` | 显式结果的存储、校验、冲突和 acceptance facts | 平台 terminal、自然语言 summary |
| `closure_record` | closure state、父处置、reason、parent action | platform identity、dispatch success |

`credential_id` 和 `submission_id` 保留为 nullable Schema 字段。现有显式结果入口继续使用 Slice 1 前已有的 retained target provenance；attempt-scoped credential 属于 Slice 3。

PostToolUse 的 canonical path 只写入 `dispatch_record.dispatch_target`。Observation 只有在 exact target observation 成立时，才以 `binding_basis=exact_dispatch_target` 绑定回同一 `task_id + attempt`。裸 Start/Stop alias 不会提升成 managed attempt identity。

## 3. 版本与迁移

### 3.1 支持矩阵

| 输入状态 | 读取行为 | 后续锁内写入 |
| --- | --- | --- |
| 无 `state_format_version` | 按 legacy format 1 迁移到内存四平面并生成 compatibility projection；不回写 | 原子保存 format 2 |
| `state_format_version=1` | 同上 | 原子保存 format 2 |
| `state_format_version=2` | 校验四平面结构、字段集、枚举、类型和 binding identity，再生成 compatibility projection | 继续保存 format 2 |
| 未知版本 | `StateValidationError`；原文件保留 | 不回写 |
| 损坏四平面 | `StateValidationError`；原文件保留 | 不回写 |

迁移不做离线批量重写。`StateStore.read()` 只在内存中迁移和投影；首次实际 `update()`/CAS 在同一 Session 锁内保存 format 2，并执行写后 raw readback。

### 3.2 Legacy 到四平面映射

| Legacy fact | Format-2 canonical mapping |
| --- | --- |
| `spawn_observation` / `spawn_tool_use_id` | `dispatch_record.dispatch_state` / `tool_use_id` |
| `spawn_observed_canonical_path` | `dispatch_record.dispatch_target` |
| exact `list_agents` terminal + target | bound `observation_record.observed_state=terminal` |
| exact platform error/unknown + target | bound observation `error/unknown` |
| 只有旧 `execution_status=running` | `observation_record.observed_state=not_observed` |
| result storage/protocol/business fields | `result_record` |
| attempt close/disposition/parent action | `closure_record` |

迁移有意不信任旧 `running` 位。缺少 Start/Stop 或 exact target observation 时，结果是 `not_observed`，不能推导 `not_started`、`running` 或 `failed`。

## 4. Compatibility Projection

现有读取者通过 `_execution_compatibility_projection()` 获得临时旧字段视图。投影方向固定为 canonical 到 reader：

- dispatch state 投影为 `spawn_observation` 和旧 correlation 字段；
- observation 的 `active/terminal/absent_at_check/error/unknown` 投影为旧诊断字段；
- `not_observed` 为兼容读取投影成 `execution_status=not_started`，但该值不写盘，也不是“从未启动”的 canonical 事实；
- result 和 closure 投影为现有 result/disposition reader 所需字段；
- 每次写盘前 `LEGACY_EXECUTION_PROJECTION_FIELDS` 全部删除；format-2 Schema 对这些已知旧字段显式使用 boolean `false`，同时保留 execution-level forward extension 兼容。

测试证明直接修改 compatibility field 不会覆盖 canonical plane；下一次写盘会丢弃该旧字段。需要写语义事实的现有 runtime writer 统一通过 `_set_execution_fact()` 更新所属 plane。

## 5. Observation 与 fail-open 行为

- 只有 raw query target 唯一等于 managed execution 的 canonical `dispatch_record.dispatch_target` 时，exact empty list 才写 `absent_at_check`；不会保留或生成 `running`，也不会单独生成 terminal。
- invalid/unknown list response 写 `unknown` 或保留 advisory 状态，不生成 terminal。
- platform error 写 observation `error`，不生成业务 `failed`，兼容 lifecycle 投影也不再伪造 `stopped`。
- exact `absent_at_check` 加同 target、已认领 interrupt 的可靠 `previous_status=not_found` 可以沿既有 Slice 1 规则确认 inactive；判断读取 canonical observation，不依赖旧 `running` 位。
- result submission 只改变 result/closure plane，不把 observation 改成 terminal；因此 active observation 与待验收 result 可以同时存在。
- StateStore 未知版本、损坏、不可读或 CAS 冲突继续由既有 Hook 异常边界 advisory/fail-open；本切片不新增 parent Stop hard gate。

## 6. Schema、序列化与并发

`schemas/governance-semantics.schema.json` 新增四个独立 definition 和 `canonical_state`。runtime 从同一 Schema 加载 plane enum，测试双向比较 required/properties 集合。

raw format-2 StateStore 可通过 `canonical_state` 校验；带 compatibility projection 的 reader view 必须校验失败，防止旧字段被误当成可持久化权威。四个 plane definition 均拒绝未知内部字段；StateStore runtime 也拒绝缺字段、额外 plane 字段、未知 enum、非法 timestamp、错配的 `task_id/attempt/task_ref` 和非法 observation binding。

CAS 回归使用两个独立 Python 进程竞争同一 `dispatch_record.dispatch_state=claimed` 前置条件，结果固定为一个 commit 和一个 conflict。迁移写入也复用 StateStore 原锁、原子替换和写后回读，不引入第二套事务机制。

## 7. 验证证据

| 门禁 | 结果 |
| --- | --- |
| migration fixtures | format 1 与无版本 legacy 均投影到四平面；旧 running 不生成 active |
| Schema/runtime parity | passed；raw canonical state 通过，projected reader view 被拒绝 |
| CAS/concurrency | passed；跨进程单 winner；既有并发套件通过 |
| `python3 -m unittest discover -s tests -v` | 395 tests，OK |
| Python compile | passed；`scripts/` 与 `tests/` 下全部 Python 文件 |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!`；仅用于共享工作树组合验证，Slice 2 未修改 Skill |
| JSON parse | passed；仓库全部 JSON |
| `git diff --check` | passed；另检查全部 untracked 文件 |

Skill 文件不是本切片修改面，因此 Slice 2 不要求新增 Skill validator 证据。共享工作树中的 Skill 修改来自前序工作，未由本切片覆盖或回退。

## 8. 已知限制与下一步审阅点

- Compatibility readers 尚未全部改写为直接消费 plane record；其输入已经是单向投影，不再是第二持久化权威。后续可按消费者逐项退役，但不应在 Slice 3 credential 工作中顺带扩展。
- 当前每个 execution 保存一个收敛后的 ObservationRecord，不是 observation event log。乱序、多 observation 历史和审计事件序列仍是 backlog。
- result credential、secret hash、签发/消费/撤销和真实子 Agent 提交可达性均未实现、未验证。
- `fresh_until` 当前为 nullable 且未驱动 hard gate；parent Stop 继续完全 advisory/fail-open。
- 没有安装或同步稳定源/运行缓存，没有修改 Marketplace、Hook trust 或 Registry，没有创建真实测试对话。

下一步审阅应重点检查：raw Schema 是否完整拒绝所有 retired semantic field；legacy migration 是否对每类历史 exact observation 都保持保守；compatibility reader 是否存在绕过 `_set_execution_fact()` 的 writer；以及 Slice 3 credential 如何只接入 result plane 而不重新耦合 runtime identity。

## 9. 独立验收 blocker 修复

`platform-capability-slice-2-independent-review.md` 报告的四组 blocker 已在开发仓库内按原反例修复：

1. exact observation binding：legacy migration 只有在 `platform_observation_target` 非空且机械等于同一 execution 的 `dispatch_record.dispatch_target` 时才建立 `exact_dispatch_target` binding；缺失保持 `not_observed`，错配保持 unbound `unknown`。format-2 runtime validation 拒绝 exact binding 的 cross-plane subject 错配。`list_agents` 只按唯一 exact canonical `dispatch_target` 路由，不依赖 Start 或 `agents` alias index；错 target 不生成 terminal/confirmed。
2. conservative result/closure migration：legacy business result 只有在 protocol valid、storage available、business result 合法、reference 非空、SHA-256 合法且 stored timestamp 合法时迁移；不完整 conflict 证据不提升 conflict，missing/storage error/弱字段不携带业务结果或 acceptance。legacy parent disposition 只有 `task_id + attempt` 与当前 execution 精确相等时才进入 closure。
3. retired fields write boundary：Schema `execution_record.properties` 中全部 boolean-false 字段与 `LEGACY_EXECUTION_PROJECTION_FIELDS` 机械双向相等。`parent_disposition`、`parent_disposition_at`、`parent_disposition_reason` 和 `spawn_not_created` 均在 format-2 read/write 边界剥离，no-op CAS 不会重新写回。
4. single canonical authority：可靠 not-created 事实唯一从受校验的 `dispatch_record.dispatch_state=rejected` 派生。prepare、PreTool claim 和 allowed-actions 不再读取或写入平面外 `spawn_not_created`；同四平面下切换该扩展字段不会改变决策。

修复没有增加 credential、freshness hard gate、parent Stop hard gate、transcript adapter 或 Start/Stop identity authority，也没有清理无关 compatibility readers。详细根因和逐项回归见 `platform-capability-slice-2-blocker-fixes.md`。

## 10. 修复后验证证据

| 门禁 | 修复后结果 |
| --- | --- |
| blocker focused regression | `tests.test_four_plane_state_model` 17 tests，OK；覆盖 exact/mismatch/missing target、无 Start exact terminal、弱/完整 result、错绑 closure、retired parity/no-op strip、平面外 decision authority 和跨进程 CAS |
| raw-vs-projected / Schema-runtime parity | passed；全部 boolean-false retired execution fields 与 runtime strip set 精确相等 |
| dispatch/retry/closure/concurrency 组合回归 | passed |
| `python3 -m unittest discover -s tests -v` | 404 tests，OK |
| Python compile | passed；`scripts/` 全部 Python 和本轮涉及 tests |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!`；共享工作树组合验证 |
| 仓库 JSON parse | passed |
| `git diff --check` / untracked whitespace | passed |

以上是本地开发仓库证据，不替代新的独立验收或真实平台 smoke。按本任务冻结边界，本轮没有安装/同步插件、修改稳定源或缓存、创建真实测试任务，也没有检查或删除既有 smoke StateStore。

## 11. 修复后独立复验 NB1/NB2

`platform-capability-slice-2-post-fix-independent-review.md` 新发现的两项 blocker 已在同一 Slice 2 范围内修复：

1. NB1 exact query scope：非空 `list_agents` observation 现在同时要求 `tool_input.path_prefix` 是以 `/` 开头的原样字符串、响应只含一个 Agent 项，并且 `path_prefix == agent_name ==` 唯一 canonical execution 的 `dispatch_record.dispatch_target`。broad `/root`、错 prefix、缺 prefix、runtime alias、不同返回 target 或多目标响应都不进入 managed observation writer，因此不能生成 `exact_dispatch_target`、`terminal`、`confirmed` 或 `stopped`。无 Start、无 active index 的 exact canonical target terminal 正向路径保持可收敛。
2. NB2 canonical legacy core migration：format 1 和无版本 execution 在四平面迁移时同时规范 `contract_summary`、`deliverable_contract` 和旧 `dispatch_kind=initial`。可验证的旧 contract 字段与 artifact expectation 保留；缺失内容使用明确标注“legacy 未保留”的确定性保守值，completion 只要求显式父审阅，不生成业务完成、结果、证据或范围事实；旧 initial 枚举机械映射为 `initial_spawn`。当前 migration fixture 首次 no-op update 后的完整 raw `canonical_state` 为零 Schema errors。

本轮没有放宽 `governance-semantics.schema.json`。unknown version、损坏 state/plane 和 CAS conflict 仍不回写；原 B1-B4、35/35 retired parity、raw-vs-projected 与 dispatch-derived single authority 回归继续通过。

修复后本地证据：

| 门禁 | 结果 |
| --- | --- |
| NB1/NB2 focused regression | `tests.test_four_plane_state_model` 18 tests，OK |
| 报告反例 | broad/wrong/missing/alias 保持 `not_observed + unconfirmed`；exact terminal 收敛；format 1/无版本 raw canonical 均 0 errors |
| migration / Schema / runtime parity | passed；format 1 与无版本首次写入均为 Schema-valid format 2 |
| CAS/concurrency 与 Slice 1 fail-open | passed |
| `python3 -m unittest discover -s tests -v` | 405 tests，OK |

以上结果允许启动一次新的独立验收；本修复任务本身不启动独立验收、真实测试或 Slice 3。

## 12. 第二轮复验 empty list alias scope blocker

`platform-capability-slice-2-second-post-fix-independent-review.md` 发现 empty `list_agents` 分支仍通过 `agents` active index 解析 target。只要 absolute runtime alias 指向 managed attempt，alias-scoped empty response 就能覆写既有 exact canonical observation 的 subject，并把 `active/confirmed/running` 降成 `unknown/unconfirmed/not_started`。这违反 observation 只能由 canonical dispatch target 授权的单一权威约束。

修复后，empty 与非空路径共享 `_resolve_exact_dispatch_target_attempt()` 的 canonical authority。任何 mutation 前都必须满足 raw `tool_input.path_prefix` 原样等于且只等于一个 managed execution 的 `dispatch_record.dispatch_target`。resolver 不读取 `agents` index；runtime alias、broad `/root`、wrong/missing prefix、active alias mapping、不同 target、零匹配和多 canonical 匹配全部保持原 execution 不变。唯一 exact canonical empty 即使没有 Start 或 active index 也可记录 `absent_at_check`，但不单独生成 terminal、failed 或 hard gate；与同 target reliable interrupt/not_found 的既有组合收敛规则保持不变。

本轮新增回归先稳定复现报告反例：

```text
before /root/sg_standard_slice_2_legacy_t_0123456789ab active confirmed running
after  /root/runtime-alias unknown unconfirmed not_started
```

修复后本地证据：

| 门禁 | 结果 |
| --- | --- |
| empty scope focused regression | runtime alias、broad/wrong/missing、零/多 canonical 匹配均 no-op；unique canonical empty 保守记录 absence |
| exact empty + interrupt/not_found | 既有同 target 正向收敛通过 |
| `tests.test_four_plane_state_model` | 22 tests，OK |
| Slice 2 focused 组合 | 225 tests，OK |
| migration / Schema-runtime / raw-projected / retired parity | passed；NB2 format 1 与无版本迁移、NB1 非空三重等值、retired 35/35 均未回退 |
| CAS/concurrency / Slice 1 Hook fail-open | passed |
| `python3 -m unittest discover -s tests -v` | 409 tests，OK |
| Python compile | `scripts/` 与 `tests/` 共 24 files，passed |
| Plugin / Skill validator | `Plugin validation passed`；`Skill is valid!` |
| JSON / whitespace | 17 JSON files parsed；`git diff --check` 与 untracked whitespace passed |

本轮只改 empty observation 路由、对应测试和两份 Slice 2 实施文档；没有放宽 Schema，没有实现 Slice 3 credential、freshness 或 parent Stop hard gate，没有新增 transcript adapter，也没有安装、部署、发布、同步缓存、创建真实任务或访问 smoke StateStore。以上证据允许再次启动独立复验，但本任务不自行启动。
