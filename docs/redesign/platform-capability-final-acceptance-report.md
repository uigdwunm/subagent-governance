# 平台能力最终综合验收报告

日期：2026-08-15

结论：**GO，仅限当前本地开发仓库与已完成真实 smoke 的实际观察范围。** 平台能力 Slice 1-5 已收口，已知代码 blocker 全部关闭，Slice 6 裁决为 `NO-SLICE`。该 GO 不等于 release-ready、稳定发布、稳定安装、Hook trust 生效或所有平台内部能力已验证。

本验收未修改 runtime、Schema、tests、Skill、fixtures 或历史实现/审查/smoke 报告；未部署、cachebuster、写稳定源/缓存、修改 Hook trust/Marketplace/Registry、清理缓存、创建真实 Agent、提交或推送。文档修改只用于当前状态收口。

## 1. 验收范围与方法

验收基线包括：

- 当前平台能力契约与最小状态机；
- Slice 1-5 的设计、实施、blocker 修复、独立审查与真实 smoke 报告；
- Slice 6 `NO-SLICE` 设计裁决；
- 当前 runtime、四个 repository Schema、Skill、focused/full tests、共享工作树 diff 与 `AGENTS.md`；
- 测试候选 `0.4.0-rc.12+codex.20260815060227` 的只读安装与哈希证据。

历史 NO-GO/FAIL 只用于回归和关闭链。当前状态以其后明确 superseding 的修复、独立复验和真实 smoke 为准。未读取既有 smoke StateStore 的业务正文；真实证据只来自保存的脱敏报告、关键资产哈希和只读安装检查。

## 2. 当前快照

| 资产 | SHA-256 |
| --- | --- |
| `.codex-plugin/plugin.json` | `6c0b1b8e205b68df2edceeb8bbaed07deb9288fce122be7e9afc5c6658d5b265` |
| `scripts/subagent_governance.py` | `cd56a4ae4e47dd441e8b7f18502f24da1fc041b56768fdf3fa6f481624dc5149` |
| `skills/subagent-governance/SKILL.md` | `fd4fbcb1d76c105a7d71872baa27ee39150a42738ccf669228f02c064086e033` |
| `schemas/task-contract-v1.schema.json` | `77c21afeba45860fe3d1f306576f18526396dcea9dde6e9e6677c47a825ef3be` |
| `schemas/task-result-v1.schema.json` | `576046d7f164a2fe27c60b4bc7de81247580de59bda556bf087fc2c496dad205` |
| `schemas/governance-semantics.schema.json` | `ddcba490055629a66680486852c563624b5c250eeaed29e1add0f4dec95c39a1` |
| `schemas/codex-hook-events-v1.contract.json` | `a4475afeb374db8503be8b5c1eef65372d33082b3b6f39cebbfa01746b4340c4` |

开发仓库 `<development-repository>`、测试源 `<stable-test-source>` 和目标缓存 `<runtime-cache>/0.4.0-rc.12+codex.20260815060227` 是三个不同 inode 的普通目录，不是符号链接。上述 7 个关键资产在三处逐项同哈希。

只读 `check_installation.py --require-development-sync` 结果：`deployment_in_sync=true`、`installation_paths_separated=true`、`stable_matches_cache=true`、`runtime_healthy=true`、`cache_entries_safe=true`。保留一个 N-1 测试缓存 `0.4.0-rc.12+codex.20260815053121`；未清理。`codex_registration_checked=false`、`hook_trust_checked=false`、`release_ready=null`、`release_readiness_status=not_evaluated`，所以这组证据只属于测试候选，不是 release acceptance。

## 3. Slice 1-5 综合结论

| Slice | 唯一目标 | 关键修改 | 独立验收 | 真实证据 | 最终状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | 固化官方 Hook 字段边界，撤销弱观察形成的强身份、强结果和 Stop 保证 | 官方 Hook machine contract；Start unbound；Stop 不消费 TaskResult/terminal text；StateStore 失败与不可靠 lifecycle fail-open；PreparedContract 正向门禁保留 | 没有单独命名的 Slice 1 独立报告；其冻结反例在 Slice 2-5 独立审查与本次 focused/full gate 持续复验 | 后续 parent-authority smoke 证明 native message 未改写、current child final 可达；独立 Start/Stop raw payload 仍 `not_checked` | **CLOSED**，限官方契约与本地 fail-open 目标 |
| 2 | 建立 dispatch、observation、result、closure 四平面 canonical state 与保守迁移 | format 2 四平面；legacy 单向 projection；exact canonical target authority；retired 字段写前剥离；CAS/concurrency | 第三轮 post-fix 独立复验 **GO**；原 B1-B4、NB1/NB2 与 empty alias blocker 均关闭 | Slice 4 smoke 真实验证 exact target、顶层 `agents` 与 terminal observation；不把相邻 smoke 扩大为全部 wire shape | **CLOSED** |
| 3 | 用父任务根据当前 native child notification 的显式结果记录替代 bearer/child-submit | format 4；删除 credential 容器/引用；stdin-only `--record-child-result`；exact `task_id + attempt + sender_target`；幂等、冲突、storage retry；不改 observation/identity | parent-authority redesign 的三轮独立复验最终 **GO**；旧 credential GO 已撤销 | 最新 parent-authority smoke **PASS**：exact sender、record/read/accept/tombstone，无 message rewrite、credential 或断流 | **CLOSED / REAL PASS** |
| 4 | 冻结有限 observation adapter、退役 freshness、固定 Stop advisory-only | 顶层 object/JSON-string `agents` adapter；wrapper malformed/error fail-open；machine policy source；`fresh_until=null`；Stop 三读后 `continue=true` | policy-source 最终独立复验 **GO**；4,128/4,128 wrapper matrix、12/12 field-source parity | 最新 observation smoke **PASS**：exact single-tag terminal、结果平面独立、同 Agent correction 后闭环 | **CLOSED / REAL PASS** |
| 5 | 提升严格 TaskResult producer clarity，不增加结果 authority | `completed != complete`；统一 initial/correction/resume renderer；字段 JSON 类型和最小 complete skeleton；validator 严格不变 | 初始独立 **GO** 后被真实 CORE FAIL supersede；数组字段 blocker 回修独立复验再次 **GO** | 最新 result-shape smoke **PASS**：第一次结果合法、无需 correction、record/read/accept/tombstone 完成 | **CLOSED / REAL PASS** |

## 4. 历史 blocker 关闭链

| 历史 blocker | 对应修复 | 后续复验/真实 smoke | 当前结论 |
| --- | --- | --- | --- |
| Slice 2 B1 exact observation 错绑；B2 弱 legacy result/closure 升级；B3 retired 字段回写；B4 平面外 not-created authority | exact dispatch target 等值、保守 migration、35/35 retired strip、dispatch-derived retry authority | 首轮 post-fix 关闭原 B2-B4 并继续发现 NB1/NB2 | 原组已关闭 |
| Slice 2 NB1 broad/wrong query 可形成 terminal；NB2 legacy 首次写入 Schema-invalid format 2 | query=response=唯一 dispatch target 三重等值；完整 canonical legacy core migration | 第二轮确认 NB2 和非空 NB1 关闭，继续发现 empty alias scope | 已关闭 |
| Slice 2 empty `agents` 仍信任 runtime alias | empty/non-empty 共用唯一 canonical dispatch-target resolver | 第三轮独立 GO；当前四平面 focused 74/74 | 已关闭 |
| 旧 Slice 3 bearer 方案的 generation revocation、storage-error Schema 和 secret-output blocker，以及 prior-Start late-failure 顺序问题 | 历史方案先修到本地 GO，随后真实 smoke 证明 Hook 阶段 message injection 与 secret-at-rest 根因，整个 bearer/child-submit authority 被撤销 | 旧第三轮 GO 文档顶部已标记 superseded；现行 parent-authority 方案另行验收 | 不再是当前实现路径 |
| 现行 Slice 3 format 2/3/4 损坏状态错误回退 legacy migration；未被 runtime 核对的 message digest 与残余 credential 文档 | 仅无版本/format 1 允许 legacy migration；删除 PreparedContract message digest；统一现行文档与 superseded 标记 | parent-authority 第三轮独立 GO；最新真实 smoke PASS | 已关闭 |
| Slice 3 恢复调用 success/unknown 后直接 exact error 会残留 lifecycle，形成无合法动作死状态 | exact same-target error 消费旧 recovery lifecycle，按 `recovery_count` 进入 awaiting-authorization/exhausted | 本地回归与历史真实 recovery smoke PASS；现行结果通道替换 credential 部分但保留恢复收敛语义 | 已关闭 |
| Slice 4 malformed `isError`/显式 `error` wrapper 可夹带 agents | strict boolean/error wrapper no-op | 第二轮确认样例关闭，但发现 `error=0` 与 `status/state` 遮蔽 | 部分类别继续追踪 |
| Slice 4 `error=0`、双 `status/state`、malformed status 与硬编码 `failure` | strict identity checks；遍历全部字段；machine wrapper statuses 与 parse policy | 第四轮 4,128 行为矩阵全过，继续发现两个 policy 未由 runtime 消费 | 行为 blocker 已关闭 |
| Slice 4 machine policy 只声明未消费，field-source 10/12 | runtime 加载 policy 并对 unsupported 值 import fail-fast | policy-source 最终独立 12/12、4,128/4,128，GO；真实 observation smoke PASS | 已关闭 |
| Slice 5 首次真实结果 `evidence`/`remaining` 为 scalar，原 smoke CORE FAIL | 单一 JSON type helper、共享 field renderer、必填数组说明与最小 complete skeleton；validator 不放宽 | blocker 独立复验 GO；候选 `20260815060227` result-shape smoke 首次合法、无 correction，PASS | 已关闭；历史 FAIL 保留 |

没有历史 blocker 被删除或改写为“从未发生”。当前判断依据是后续明确的修复、复验和真实 smoke。

## 5. 冻结不变量复验

| 不变量 | 当前证据 | 结论 |
| --- | --- | --- |
| Exact authority | non-empty/empty `list_agents` 只接受唯一 `dispatch_record.dispatch_target`；结果只接受 exact `task_id + attempt + sender_target` | PASS |
| 四平面 | DispatchRecord、ObservationRecord、ResultRecord、ClosureRecord 字段/枚举与 runtime/Schema 双向一致；结果不改 observation/identity | PASS |
| Parent-recorded result | 唯一正式写入口是 stdin-only `--record-child-result`；`_associate_result_record` 只有定义和该入口的单一调用 | PASS |
| No credential/secret | 当前无 credential/hash/install/revoke/submit/relay writer 定义；format 4 只保留旧 format 3 material 清理和 Schema forbidden 字段 | PASS |
| Limited adapter | 只读顶层 `agents`，object 或 JSON string；wrapper malformed/error no-op；不递归 content/summary/history/transcript | PASS |
| `fresh_until=null` | 2 个 null writer、1 个 non-null rejector；Schema 为 null-only；Stop 不消费 freshness | PASS |
| Stop advisory-only | hard-block helper/decision symbol为 0；StateStore 可读/不可读均固定 `continue=true`，失败最多三读且不写状态 | PASS |
| Strict TaskResult producer/validator | 4 个业务枚举、15 个字段、7 个基础必填、3 个场景与 2 个 shared-renderer caller 一致；非法 alias/scalar 严格拒绝 | PASS |
| No transcript/summary extraction | Start/Stop 当前 handler 不读取 lifecycle payload；4 个旧 helper 均仅有定义无调用；正式结果不从 observation 或文本构造 | PASS；旧 dead helper 物理删除留 backlog |

## 6. 最终门禁

Focused suites 有意按 Slice 责任面组合，存在测试模块交叉；不得把下列数字相加当作独立总数。

| 门禁 | 实际结果 |
| --- | --- |
| Slice 1 focused：Hook contract + Hook fixtures | **11/11 PASS** |
| Slice 2 focused：four-plane + canonical record + StateStore + concurrency | **74/74 PASS** |
| Slice 3 focused：parent result + formal parent closure | **42/42 PASS** |
| Slice 4 focused：Slice 4 capability + wait/recovery/session closure | **33/33 PASS** |
| Slice 5 设计 focused：parent result + communication + Slice 4 + semantic baseline | **118/118 PASS** |
| `python3 -m unittest discover -s tests -v` | **440/440 PASS** |
| `python3 -m py_compile scripts/*.py` | **5/5 project runtime scripts PASS** |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| `python3 scripts/release_preflight.py --mode development` | PASS；manifest `0.4.0-rc.12+codex.20260815060227`，expected tag `v0.4.0-rc.12` |
| 全部 repository JSON，包括隐藏目录 | **15/15 PASS** |
| enum/field/producer/validator parity focused | **5/5 PASS**；15 enum 组、10 canonical field set、TaskContract/TaskResult dataclass、4 business outcomes、15 result fields 对账 |
| 静态 authority gate | PASS：credential writer 0、legacy submit flag 0、4 个 retired helper 均 definition-only、renderer caller 2、result association 单一调用、Stop block symbol 0、freshness null writer 2/rejector 1、Start/Stop payload read 0 |
| `git diff --check` | PASS |
| 全部 untracked UTF-8 文本 whitespace/EOF | **70/70 PASS**；0 个非 UTF-8、trailing whitespace 或缺失 EOF newline |
| 只读安装检查与 7 个关键资产三方哈希 | PASS；只作为测试候选证据，release readiness 未评估 |

静态 repository-wide 搜索会命中保留的历史 credential/NO-GO 报告和负向测试；这些不是当前 writer。当前 runtime 中的 `secrets` 只用于生成公开 task ID，credential 相关 runtime 命中只用于 format 3 material 删除；Schema 命中均为禁止字段。未发现 business-result alias normalization、legacy submit CLI、observation-to-result mapping、transcript/summary extraction、hard Stop 或 non-null freshness authority。

## 7. 严格分类

### Blocker

无。未发现新的、可稳定复现的冻结不变量违例。

### Known limitation

- 明确 producer contract 不能保证模型每次都生成合法 TaskResult；非法 payload 仍需严格拒绝和有界 correction。
- exact running 只证明观察时刻，可能立即陈旧；当前没有 future freshness。
- Stop advisory 只展示 canonical 父责任，不证明 Agent 当前仍运行，也不替父任务验收结果。
- ObservationRecord 保存收敛后的事实，不是 observation event log。
- 真实 smoke 只证明已观察到的单次平台路径，不能升级为平台永远提供完整 current notification/exact sender 的保证。

### Backlog

- 获得官方或独立真实 TTL、刷新、乱序和跨重启保证后，重新设计 active freshness。
- freshness authority 成立且 Stop UI 展示、重入、fail-open 有正向证据后，重新评估 limited hard gate。
- 出现新的真实 wrapper/status shape 后，以保存的正向样本扩展最小 adapter，不做递归预适配。
- 多次真实复现 protocol-gap admission 缺口后，另行设计，不借当前结果通道扩大 authority。
- 出现事件历史缺失造成的独立 correctness/审计问题后，再评估 observation event log。
- 物理删除当前仅 definition-only 的旧 transcript/Start/result-gap helpers。
- 获得发布授权后执行发布候选的 N/N-1、archive、回滚与稳定安装验收。

### Not_checked

- 真实 non-terminal/running `list_agents` observation。
- parent Stop advisory 在真实 Codex UI 中的展示、重入和退出。
- 独立 SubagentStart/SubagentStop payload 的真实投递、顺序与 attempt 关联。
- active TTL、刷新事件、乱序优先级和跨重启 freshness。
- Provider restart、compact/resume、跨版本 StateStore 与 SessionEnd 完整矩阵。
- Provider 内部日志、mailbox、transport 和 UI 展示。
- Hook trust 当前展示状态与 Codex registration。
- 稳定发布源验收、Marketplace、Registry、发布归档、N/N-1、稳定安装与 release readiness。

### Platform-owned boundary

- 原生 worker 存活、调度、终止和跨进程恢复。
- Provider 网络、stream、mailbox 与 current child notification 的完整投递。
- Codex UI 的 Stop advisory 展示与重入。
- 平台内部 prompt/tool/Hook 变换、日志和 transcript 完整性。
- 官方 Hook 未提供的 attempt identity、TaskResult transport、active TTL 与刷新顺序。
- Hook trust 决策、Marketplace/Registry 状态和 Codex-owned 缓存行为。
- 模型是否始终生成合法 JSON 并遵守业务枚举。

这些分类互不替代：`not_checked` 不是失败，known limitation 是有意保守边界，platform-owned boundary 不是插件代码 blocker，backlog 也不是预批准实施清单。

## 8. Slice 6 `NO-SLICE`

没有新候选同时满足稳定真实复现、插件代码/机器契约根因、明确用户成本、不扩大 authority 的最小可逆修复和独立验收五项门槛。running、Stop UI、Start/Stop identity、TTL、Provider internals、Hook trust 与发布面分别缺少不同 authority 前提，不能组合成一个唯一功能切片。

因此 running、Stop UI、Start/Stop identity、TTL、Provider internals、Hook trust 和发布面不阻止当前本地功能收口；它们分别属于 limitation、not_checked、platform-owned 或 release boundary。但也正因没有对应证据，本报告不宣称这些能力已验证，不把 `NO-SLICE` 写成平台能力全覆盖。

## 9. 发布与安装边界

本地 GO 不自动授权：

- 写稳定发布源、创建稳定 tag 或发布归档；
- cachebuster/reinstall、运行缓存写入或 N-1/N-2 清理；
- Marketplace、Registry 或 Codex registration 写入；
- Hook trust、`hooks.json` 或 trust hash 修改；
- 新真实 Agent 或更广 smoke；
- 提交、推送或发布。

测试候选三方同哈希只证明当前保存的真实 smoke 可映射到当前关键快照。稳定发布仍需用户另行授权，并执行 `docs/release-process.md` 的发布专属验证。

## 10. 最终裁决与下一步

**最终裁决：GO。** 平台能力 Slice 1-5 对当前本地开发仓库与已完成真实 smoke 范围准入；当前 blocker 为无。Slice 6 为 `NO-SLICE`，平台能力功能序列停止扩展。

下一步由用户决定：

1. 另行授权稳定发布与安装验收；或
2. 另行授权更广平台验证，并继续把未观察项保持为独立证据问题。

两种选择都不能由本地 GO 自动推导。本文落盘后已再次复跑全部 focused/full tests、编译、validators、development preflight、JSON、diff、公开文档主机路径和 untracked UTF-8 whitespace/EOF；结果均为 PASS，最终数字见第 6 节。
