# 平台能力契约重设计：Slice 2 blocker 修复

日期：2026-08-14

状态：四组原独立验收 blocker、修复后复验 NB1/NB2 与 empty list alias scope blocker 已在开发仓库修复并通过本地门禁；可以再次开始新的独立验收。未安装、未部署、未发布、未执行真实平台测试。

## 1. 范围

本轮只处理 `platform-capability-slice-2-independent-review.md` 的 B1-B4。实现源保持为当前开发仓库根目录；共享工作树中既有 F1-F13、Slice 1、Slice 2 和用户修改全部保留。

明确未处理：Slice 3 result credential、freshness、parent Stop hard gate、transcript adapter、Start/Stop identity authority、兼容 reader 清理和其他 backlog。本轮未安装或同步插件，未写稳定源、运行缓存、Marketplace、Hook trust 或 Registry，未创建真实测试任务，未修改既有 smoke StateStore，未提交或推送。

## 2. B1：exact observation binding

根因有三层：legacy migration 忽略 `platform_observation_target`；compatibility writer 把任意非空 target 标成 exact；format-2 validation 只核对 bound task/attempt，不核对 observation subject 与同 execution 的 dispatch target。非 exact alias 还可经 `agents` index 进入 `list_agents` terminal 路径。

修改：

- legacy observation 只有 `legacy target == dispatch_record.dispatch_target` 时绑定；target 缺失为 `not_observed`，错配为 unbound `unknown`，均不带 terminal status。
- runtime 以 `_observation_has_exact_dispatch_target()` 统一检查 subject kind、subject、task、attempt 和 binding basis。
- format-2 exact binding 的 subject 不等于 dispatch target 时直接拒绝；非空错 target 也不能携带 active/terminal。
- target-scoped list observation 只在 canonical executions 中按唯一 exact `dispatch_record.dispatch_target` 路由。零匹配或多匹配均不猜测；不读取 alias、同名或 current attempt 建立 authority。

回归覆盖 legacy exact/missing/mismatch、format-2 cross-plane corruption、错 alias terminal、无 Start/无 active index 的 exact terminal 正向路径。

## 3. B2：保守 legacy result/closure migration

根因是旧 migration 先按弱字段决定 result state，再无条件保留枚举合法的 `business_result`；closure 则读取 disposition action/reason/time，却不校验 record 自带的 task/attempt。

修改：

- business result 迁移要求 protocol valid、storage available、合法 business result、非空 reference、64 位小写十六进制 SHA-256 和合法非负 stored timestamp 同时成立。
- 只有上述 base result 完整时才迁移 result reference、digest、submitted time、business result 和 acceptance。
- conflict 还必须有合法 conflict digest 与 first-seen timestamp；弱 conflict 不提升为 conflict。
- missing、storage error 和其他弱证据统一不携带 business result、acceptance 或 payload-valid 强事实。
- parent disposition 只有 record 的 `task_id + attempt` 与当前 execution 完全一致时才迁移 action/reason/recorded time；错绑 record 不重新归属。

回归覆盖裸 `failed`、valid+storage unavailable、缺 digest/time 的伪 valid、完整合法 result，以及 wrong task/wrong attempt disposition。

## 4. B3：retired fields write boundary

根因是 Schema 使用 boolean `false` 退役 34 个 execution 字段，而 runtime strip 集合只有 31 个，导致三个旧 disposition 字段能被 format-2 no-op CAS 原样写回。

修改后 Schema boolean-false 集合与 `LEGACY_EXECUTION_PROJECTION_FIELDS` 精确双向相等；新增覆盖 `parent_disposition`、`parent_disposition_at`、`parent_disposition_reason`，并把不再允许作为 authority 的 `spawn_not_created` 一并声明为 retired。format-2 read/write 会剥离全部集合成员，兼容投影仍只存在于读取视图。

回归机械枚举 Schema boolean-false properties，并把每个字段注入 raw format-2 execution 后执行 no-op update，断言持久化输出一个也不包含。raw canonical 继续通过 Schema，projected reader view 继续被拒绝。

## 5. B4：single canonical authority

根因是 `spawn_not_created` 位于四平面外，却被 PostTool writer、retry preparation/claim 和 decision snapshot 共同当作 authority；execution-level forward extension 因而可以改变 admission 和 allowed actions。

修改后 PostTool 不再写该字段；retry preparation、PreTool claim 和 allowed-actions 都调用 `_dispatch_reliably_not_created()`，该谓词唯一读取 `dispatch_record.dispatch_state == rejected`。`spawn_not_created` 作为 retired extension 在存储边界剥离，runtime 无生产读者。

回归构造四平面逐字段相同的两个 execution，只切换平面外 extension，断言 allowed actions 完全相同且都由 rejected dispatch 得到 `retry_spawn`。既有 retry admission 测试继续证明只改平面外字段不能绕过 canonical dispatch state。

## 6. 验证

修复前：新增 focused regression 稳定得到 10 个失败断言，分别命中 B1-B4。

修复后：

| 验证 | 结果 |
| --- | --- |
| `python3 -m unittest tests.test_four_plane_state_model -v` | 17 tests，OK |
| migration fixtures | exact/missing/mismatch observation、弱/完整 result、错绑 closure 全部通过 |
| Schema/runtime parity 与 raw-vs-projected | passed |
| CAS/concurrency | 跨进程 one-commit/one-conflict 及完整并发套件通过 |
| `python3 -m unittest discover -s tests -v` | 404 tests，OK |
| Python compile | `scripts/` 和本轮涉及 tests 全部通过 |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| 仓库 JSON parse | passed |
| `git diff --check` / untracked whitespace | passed |

## 7. 剩余边界与下一步

本地门禁只证明当前代码和 fixture 下的四组反例已关闭，不证明真实 Codex 平台 wire shape、Hook 投递、child submit、provider restart 或跨版本行为。Result credential 仍属于 Slice 3；freshness 和 parent Stop hard gate仍未启用；Start/Stop 保持 unbound advisory；compatibility readers 的系统性退役仍是后续工作。

下一步可以开始一个新的独立验收，复跑原 B1-B4 反例并审查本轮新增 exact-target resolver、迁移组合约束、retired parity 和 dispatch-derived retry authority。不得由本修复任务自行启动独立验收或 Slice 3。

## 8. 修复后复验 NB1：exact list query scope

修复后独立复验确认返回项虽已按 canonical `dispatch_target` 路由，但非空响应路径没有验证产生该响应的查询 scope。broad `/root`、错 prefix 或缺失 prefix 只要返回项名称等于 managed dispatch target，就会建立 exact terminal 强事实。

修改后，非空 `list_agents` 只接受单项 exact observation，并机械要求：

```text
tool_input.path_prefix == response.agents[0].agent_name
                       == unique execution.dispatch_record.dispatch_target
```

`path_prefix` 必须是原样 canonical path；不 trim、不接受 alias。缺 prefix、broad/wrong prefix、alias、不同返回 target、多目标响应或零/多 execution 匹配均直接保持原 canonical observation，不写 terminal、confirmed 或 stopped。exact prefix + exact 单项响应仍可在没有 Start 和 active index 时收敛。

回归覆盖 broad、wrong、missing、alias、different response target、exact positive 和无 Start exact terminal positive；既有 interrupt、recovery 和 correction fixture 已改为明确 exact canonical 查询。

## 9. 修复后复验 NB2：Schema-valid legacy canonicalization

复验发现现有 migration 只替换四平面，原样保留空 `contract_summary`、空 `deliverable_contract` 和旧 `dispatch_kind=initial`，导致首次锁内 no-op write 虽标记 format 2，完整 `canonical_state` 仍有 20 个 Schema errors。

修改后 legacy core migration：

- 保留满足当前边界的 contract 文本、列表、context/model/effort 和 artifact expectations；非法或缺失值不猜原业务内容。
- 缺失 objective 优先使用 work item 的 retained objective summary；其他缺失合同信息使用确定性的 unavailable 描述、空范围/证据列表和显式父审阅 completion condition。
- 重新生成只引用迁移后 completion/evidence 列表的最小 deliverable contract，固定 `review_required=true`，不生成业务结果、完成、证据或 artifact 强事实。
- 将确定的旧枚举 `initial` 机械映射为 `initial_spawn`；不放宽 Schema。

format 1 和无版本 fixture 均验证 read 不回写、首次 no-op update 持久化 `state_format_version=2`，随后对完整 raw `canonical_state` 得到 0 errors。unknown version 与损坏状态仍保留原文件且不回写。

## 10. NB1/NB2 修复后验证

| 验证 | 结果 |
| --- | --- |
| `python3 -m unittest tests.test_four_plane_state_model -v` | 18 tests，OK |
| migration fixture | format 1 与无版本 read -> no-op update -> raw canonical 均 0 Schema errors |
| exact query matrix | broad/wrong/missing/alias 不升级；exact terminal 正向收敛 |
| 原 B1-B4 / retired parity / single authority | passed；retired 35/35 |
| raw-vs-projected / Schema-runtime parity | passed |
| CAS/concurrency / Slice 1 Hook fail-open | passed |
| `python3 -m unittest discover -s tests -v` | 405 tests，OK |

本地门禁通过后可以再次开始新的独立验收。剩余限制不变：未实现 Slice 3 credential，未启用 freshness 或 parent Stop hard gate，未增加 transcript adapter，未安装、部署、发布或创建真实测试任务。

## 11. 第二轮复验：empty list alias scope bypass

第二轮独立复验确认非空 NB1 三重等值已经生效，但 empty response 仍调用 `_managed_target_attempt()`，把 `agents` runtime alias index 当成 observation authority。报告反例在临时 StateStore 中稳定把已有 canonical exact active observation 从：

```text
/root/sg_standard_slice_2_legacy_t_0123456789ab active confirmed running
```

错误改写成：

```text
/root/runtime-alias unknown unconfirmed not_started
```

修复将 `_record_exact_absence()` 的解析入口改为唯一 canonical `_resolve_exact_dispatch_target_attempt()`。empty response 现在只有在 raw `path_prefix` 精确等于全状态中唯一一个 managed execution 的 `dispatch_record.dispatch_target` 时才可写 observation。`agents` alias、active index、broad/wrong/missing prefix、不同 target、零匹配或多匹配不再参与候选选择，并且在任何 execution mutation 前 fail-open no-op。

保留的正向行为是：无 Start、无 active index 时，unique exact canonical empty 可写 `absent_at_check`，但不能单独生成 terminal 或 business failed；已有 exact empty 与同 target reliable interrupt/not_found 的允许组合仍按冻结规则收敛。非空 NB1 三重等值、NB2 Schema-valid migration、原 B1-B4、retired 35/35 和 dispatch-derived single authority 均未修改。

回归与门禁：

| 验证 | 结果 |
| --- | --- |
| 新增 empty scope regression | 4 tests；覆盖 alias、broad/wrong/missing、unique exact、duplicate canonical；OK |
| `python3 -m unittest tests.test_four_plane_state_model -v` | 22 tests，OK |
| Slice 2 focused 组合 | 225 tests，OK |
| exact empty + reliable interrupt/not_found | 既有正向测试通过 |
| migration / Schema-runtime / raw-projected / CAS/concurrency / Hook fail-open | passed |
| `python3 -m unittest discover -s tests -v` | 409 tests，OK |
| Python compile / validators / JSON | 24 Python files；Plugin 和 Skill validator；17 JSON files，全部 passed |
| `git diff --check` / untracked whitespace | passed |

本轮未改独立复验报告、Schema、fixture 或 Skill；未扩大 hard gate，未部署、安装、发布、同步稳定源或缓存，未创建测试任务，未访问 smoke StateStore，未提交或推送。开发仓库已具备再次独立复验条件，本任务不自行启动复验或 Slice 3。
