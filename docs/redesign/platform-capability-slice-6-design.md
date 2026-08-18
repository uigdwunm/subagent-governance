# 平台能力 Slice 6：边界冻结与最终收口裁决

日期：2026-08-15

状态：设计完成；明确裁决为 **NO-SLICE**。平台能力序列在 Slice 5 后停止功能扩展。下一步应另开一次“平台能力最终综合验收与报告”任务，但该任务是验收与文档收口，不命名为 Slice 6，也不自动授权测试部署、真实 Agent、稳定安装、发布、提交或推送。

## 1. 裁决

当前不存在同时满足以下五项证据的新功能候选：

1. 可在当前版本稳定真实复现；
2. 可定位到插件代码或机器契约根因；
3. 有明确且非推测的用户成本；
4. 存在不扩大 authority 的最小可逆修复；
5. 可以与既有 Slice 独立验收。

因此裁决不是 `IMPLEMENT`，也不是为某个已识别候选等待证据的 `HOLD`，而是 **NO-SLICE**。

Slice 1-5 已完成当前正向证据允许的最小平台能力闭环：官方 Hook 能力降级、四平面 canonical state、父任务权威结果通道、有限 exact `list_agents` adapter 与 Stop advisory-only，以及 TaskResult producer clarity。继续用 Slice 6 编号承载“无新增 authority 的整合、文档、门禁”会混淆功能增量和验收活动，并制造一个没有独立状态转换、代码根因或用户问题的空切片。

平台能力最终综合验收仍然必要，但它只做证据对账、当前快照门禁、真实证据范围审计和文档状态收口。若综合验收发现新的稳定反例，应先把反例分类并单独设计；不能预先保留 Slice 6 编号，也不能在综合验收中顺带实现。

## 2. 当前证据基线

### 2.1 已完成的正向闭环

| 范围 | 当前结论 | 证据边界 |
| --- | --- | --- |
| Slice 1 | 已完成 | 官方 Hook 字段成为机器边界；Start 不建立 attempt identity，Stop 不承载正式结果，弱观察不形成 hard gate |
| Slice 2 | 已完成 | dispatch、observation、result、closure 四平面 canonical state 与保守迁移完成 |
| Slice 3 | 真实 PASS | 父任务可根据 current native child notification，以 exact `task_id + attempt + sender_target` 完成 record/read/accept/tombstone |
| Slice 4 | 独立 GO、真实 PASS | 顶层 exact `agents` adapter、字符串/单标签 terminal shape、`fresh_until=null`、Stop advisory-only 已闭环 |
| Slice 5 | 独立 GO、真实 PASS | 唯一 Agent 第一次 TaskResult 完整合法；平台 `completed` 与业务 `complete` 未混合；无 correction 即完成正式闭环 |
| D1-D6、旧 S1-S6、F1-F13 | completed historical work | 四层对象、迁移、增长、结果、恢复、诊断、兼容退役和本地架构门禁均不得借新编号重复 |

最新 Slice 5 smoke 记录的关键资产 SHA-256 与本设计时开发工作树逐项一致：

| 资产 | SHA-256 |
| --- | --- |
| `.codex-plugin/plugin.json` | `6c0b1b8e205b68df2edceeb8bbaed07deb9288fce122be7e9afc5c6658d5b265` |
| `scripts/subagent_governance.py` | `cd56a4ae4e47dd441e8b7f18502f24da1fc041b56768fdf3fa6f481624dc5149` |
| `skills/subagent-governance/SKILL.md` | `fd4fbcb1d76c105a7d71872baa27ee39150a42738ccf669228f02c064086e033` |
| `schemas/task-contract-v1.schema.json` | `77c21afeba45860fe3d1f306576f18526396dcea9dde6e9e6677c47a825ef3be` |
| `schemas/task-result-v1.schema.json` | `576046d7f164a2fe27c60b4bc7de81247580de59bda556bf087fc2c496dad205` |
| `schemas/governance-semantics.schema.json` | `ddcba490055629a66680486852c563624b5c250eeaed29e1add0f4dec95c39a1` |

这组一致性只证明最新 smoke 针对当前关键快照有效，不把 smoke 未覆盖的能力升级为 `passed`，也不证明稳定发布面已经验收。

### 2.2 当前 blocker

**无。**

当前没有可稳定复现的冻结不变量违例，也没有尚未关闭的 Slice 1-5 代码 blocker。尤其不能把以下事实误写为 blocker：真实 smoke 没有捕获 running、没有展示 parent Stop UI、没有重启 provider、没有 compact/resume、没有验证 Hook trust 或稳定安装。

`not_checked` 是证据缺失分类，不是失败；known limitation 是有意保守边界，不是缺陷；platform-owned boundary 不是插件代码 blocker。

## 3. 第一性问题分类

### 3.1 用户仍可能真实遇到的问题

| 问题 | 分类 | 当前处理 | 为什么不形成 Slice 6 |
| --- | --- | --- | --- |
| 模型仍可能返回非法或不完整 TaskResult | known limitation | strict validator 拒绝；已有有界 correction | Slice 5 已修复可定位的 producer clarity 根因；模型不保证遵约属于剩余概率，不存在新的稳定代码反例 |
| exact running 观察可能在产生后立即陈旧 | known limitation | `fresh_until=null`；不形成 hard gate | 保守行为符合冻结不变量；没有 TTL/刷新/乱序 authority，不能靠猜测修复 |
| parent Stop 不阻止仍有责任的任务结束 | known limitation / deliberate safety boundary | 只显示有界 advisory，固定 `continue=true` | 在没有 fresh active authority 时 hard block 更不安全；当前行为是 Slice 4 明确裁决 |
| ObservationRecord 只保存收敛结果，不保存事件历史 | backlog | 诊断展示当前 canonical facts | 没有独立、稳定、可量化的用户 correctness 问题，也没有最小必要 event-log 规格 |
| 应用或 provider 重启可能中断 worker，平台投影可能出现 `pending_init` 或空列表 | platform-owned boundary；部分历史问题已修复 | 插件只适配可见响应，并允许基于精确外部事实的有界 reconciliation | 桌面进程、worker 和活动列表投影不由插件控制；旧 adapter 根因已完成修复，剩余部分无插件 authority |
| Hook 未 trust 时真实 Hook 被跳过 | operational/release boundary | README 和发布流程要求用户交互 review/trust | 插件不能自我授权或修改 trust；未经发布授权也不应写 trust 状态 |
| 旧任务仍引用启动时缓存 | operational known limitation | 发布工具保留明确 N-1，要求新任务验收目标版本 | 这是缓存生命周期与发布验收问题，不是新的 runtime feature |

### 3.2 `not_checked`

以下项目仍应原样保留为 `not_checked`，不能因相邻 terminal smoke 通过而提升：

- 真实 non-terminal/running `list_agents` observation；
- parent Stop advisory 在真实 Codex UI 中的展示、重入和退出行为；
- 独立 `SubagentStart`/`SubagentStop` payload 的真实投递、顺序和可见性；
- Start/Stop 与 attempt identity 的真实关联能力；
- active TTL、刷新事件、乱序优先级和跨重启 freshness；
- provider restart、compact/resume 和跨版本 StateStore 行为；
- Provider 内部日志、mailbox、transport 和 UI 展示；
- Hook trust 当前展示状态；
- 稳定源、Marketplace、Registry、运行缓存、发布归档、N/N-1 和稳定安装；
- SessionEnd 与跨版本旧任务继续运行的完整真实矩阵。

其中部分项目可以在最终综合验收中继续标注而不主动触发。没有稳定不变量反例时，不需要为了把 `not_checked` 变成 `passed` 而干扰正常核心闭环或扩大真实测试面。

### 3.3 Platform-owned boundary

插件没有 authority 修复或保证：

- 原生 worker 的存活、调度、终止与跨进程恢复；
- provider 网络、stream、mailbox 与 current child notification 的完整投递；
- Codex UI 是否展示、何时展示、如何重入 Stop advisory；
- 平台内部 prompt/tool/Hook 变换、日志和 transcript 完整性；
- 官方 Hook 未提供的 attempt identity、TaskResult transport、active TTL 或刷新顺序；
- Hook trust 决策、Marketplace/Registry 状态与 Codex-owned 缓存行为；
- 模型是否始终生成合法 JSON 或严格遵守业务枚举。

插件只能在平台实际暴露的有限事实上保持严格、可逆、fail-open 的本地转换；不能把不可见平台状态包装为本地强事实。

### 3.4 Backlog

以下事项只有出现新 authority 证据或稳定反例后才能重开设计：

- 官方或独立真实 TTL、刷新、乱序与跨重启保证成立后，重新设计 active freshness；
- freshness authority 成立，且 Stop UI 展示、重入和 fail-open 均有正向证据后，重新评估 limited hard gate；
- 出现新的真实 wrapper/status shape 后，以保存的正向样本增加最小 adapter，不做递归预适配；
- 多次真实 smoke 稳定证明 invalid current notification 无法进入既有 correction admission 后，单独评估 protocol-gap 入口；
- 只有事件历史缺失造成独立 correctness 或审计问题时，才评估 Observation event log；
- 发布候选明确后，再执行 N/N-1、archive、稳定缓存和回滚验收。

Backlog 不是预批准的实施清单。每一项仍需重新满足五项证据门槛。

### 3.5 Completed historical work

不得由最终综合验收或未来候选重复：

- D1-D6 的 work item、dispatch/deliverable、outcome/disposition、recovery、diagnostics 和 migration/slices 设计；
- 旧 D6 S1-S6 的实现，尤其旧 S6 compatibility retirement/release preparation；
- F1-F13 的 growth、late-event routing、duplicate risk、action-required、canonical Schema、cleanup、lifecycle admission、rollback、interrupt fail-open 与最终本地验收；
- 平台 Slice 1-5 的官方能力降级、四平面、父结果通道、有限 observation/Stop 和结果词汇/字段形状 clarity。

## 4. 新候选五项证据审查

| 候选 | 真实复现 | 代码根因 | 用户成本 | 最小可逆修复 | 独立验收 | 裁决 |
| --- | --- | --- | --- | --- | --- | --- |
| running observation authority | 否，真实 smoke `not_checked` | 否；当前 adapter 已覆盖已见 shape | 未独立量化 | 否；缺 freshness 会扩大 authority | 否 | 不准入 |
| parent Stop hard gate | 否，UI/重入 `not_checked` | 否；advisory-only 是冻结行为 | hard gate 与 fail-open 的净收益未知 | 否；必依赖新 freshness authority | 否 | 不准入 |
| Start/Stop identity | 否 | 官方契约明确缺 attempt 关联键 | 已由 exact dispatch target 与父结果通道规避 | 否；任何猜绑定都会扩大 authority | 否 | 不准入 |
| TTL/freshness | 否 | 平台没有提供时钟、刷新、乱序或重启语义 | 只能推测 | 否；任意 TTL 都是本地猜测 | 否 | 不准入 |
| provider restart/compact | 有历史平台事故，但当前候选路径未独立复现 | 剩余根因在平台 worker/投影；插件 adapter 根因已修复 | 平台中断成本真实 | 插件无最小修复 authority | 只能验收有限 reconciliation，不能验收平台修复 | 不准入 |
| Hook trust 自动化 | 未检查当前目标 trust | 不在插件 runtime/Schema/Skill 根因内 | 未 trust 会跳过 Hook | 无；必须由用户交互授权 | 发布验收可检查，但不是切片 | 不准入 |
| 发布/稳定安装 | `not_checked` | 无功能代码根因 | 运维风险明确 | 有既有发布流程，不需要新功能 | 可做发布验收，但需明确授权 | 不准入 |
| 新 wrapper 预适配 | 无新样本 | 无 | 无当前成本 | 否；会引入猜测 parser | 无正向 fixture | 不准入 |
| Observation event log | 无稳定反例 | 当前是有意收敛模型 | 无独立成本证据 | 不是最小修改 | 无冻结需求 | 不准入 |
| 最终整合/文档/门禁 | 不是用户功能问题 | 无代码根因 | 文档状态滞后会造成阅读成本 | 可在收口任务直接修文档 | 可验收，但不产生功能 Slice | 作为最终综合收口，不称 Slice 6 |

结论：没有一项候选通过五项门槛。将任一候选实现都会把未知平台行为错误提升为插件 authority，或重复已完成工作。

## 5. 关键 authority 冻结

### 5.1 Running observation

当前只允许 exact canonical target、受支持顶层 `agents` shape 形成一次 observation。即使真实捕获 `running`，它也只证明观察时刻的有限事实；在平台提供 TTL、刷新和乱序保证前，不产生 future freshness，不改变 `fresh_until=null`，不授权自动恢复、replacement 或 Stop block。

### 5.2 Parent Stop UI

本地代码和测试只证明 Stop 对 canonical action-required 返回 bounded advisory、固定 `continue=true`，并在 StateStore 不可读时三读后 fail-open。真实 UI 展示、重入和退出尚未验证。展示证据即使取得，也不会单独授权 hard gate；hard gate 仍必须先有 fresh active authority。

### 5.3 Start/Stop identity

官方 `SubagentStart` 不提供 attempt 关联键；官方 `SubagentStop` 不提供 TaskResult。真实 payload 可见性或顺序不能补上缺失的稳定关联键。不得按 task ref、同名、时间邻近、唯一候选、transcript 或 summary 猜绑定。

### 5.4 TTL/freshness

没有官方或独立真实证据定义 TTL 长度、刷新触发、时钟、乱序优先级或跨重启有效性。因此 `fresh_until` 保持 JSON `null`；任何非 null 设计都需要新的状态格式和独立乱序/重启验收，不能在最终收口中静默启用。

### 5.5 Provider restart/compact

现有事故证明平台重启可能中断 worker，且投影可出现 `pending_init`/empty；它没有证明插件能恢复 provider 或稳定查询 thread 终态。当前受约束 reconciliation 只接受父任务提供的精确外部事实并收口本地 attempt，不生成业务结果，不自动 replacement。compact/resume 仍为 `not_checked`。

### 5.6 Hook trust 与发布面

Hook trust 是用户和 Codex 的交互授权，不是本地代码可写 authority。Marketplace、Registry、稳定源、运行缓存、archive、N/N-1 和清理均属于发布面。现有 release process 已定义门禁；未执行只表示 `not_checked`，不证明需要新 runtime Slice。

## 6. 为什么不是 HOLD

`HOLD` 适用于已经识别出唯一候选和代码根因，但缺少一项决定性外部证据，未来证据到达后可以继续同一冻结目标。当前情形不同：

- running、Stop、TTL、Start/Stop identity 分别缺少不同的 authority 前提，不构成一个唯一候选；
- restart/compact 的剩余部分属于平台内部，插件没有候选修复面；
- Hook trust 和发布面是运维授权，不是功能设计；
- 文档与门禁收口没有状态机增量或代码根因。

因此保留“Slice 6 HOLD”会暗示已有待实施功能，并让 `not_checked` 获得不应有的优先级。正确做法是结束当前序列；未来若出现新证据，再以问题本身命名并重新准入。

## 7. 下一步：平台能力最终综合验收与报告

下一步应在新的独立对话中执行一次“平台能力最终综合验收与报告”。这是大上下文工作，必须单独沉淀报告，不复用本设计对话，也不称为 Slice 6。

### 7.1 唯一目标

对当前开发快照和 Slice 1-5 全部正向/负向边界做一次非增量、证据可追溯的综合验收，确认没有跨 Slice 回退，统一当前状态文档，并明确发布前仍缺少的授权与真实证据。

### 7.2 建议阶段

1. **快照与归属对账**：记录开发树关键资产哈希、manifest 版本、共享工作树基线和 Slice 1-5 报告链；不把 `git diff HEAD` 自动归因给最后一个 Slice。
2. **跨 Slice 不变量审计**：重新证明四平面隔离、exact sender 结果权威、terminal observation 不合成业务结果、`completed != complete`、`fresh_until=null`、Stop advisory-only、无 transcript/summary/Start/Stop authority 旁路。
3. **本地综合门禁**：运行 focused matrix、全量 unittest、Python compile、Plugin validator、Skill validator、development preflight、全部 JSON parse、Schema/runtime 双向 parity、`git diff --check` 和 untracked whitespace。
4. **真实证据对账**：复核 Slice 3/4/5 最新真实报告与当前关键哈希；分别标记 `passed|failed|not_checked`，不得由邻近结果推断 running、Stop UI、restart、compact 或 Hook trust。
5. **文档收口**：只在综合验收结论允许时更新当前状态文档，删除过时的“下一 Slice 准入”措辞，但保留历史报告原文和 superseded 标记。
6. **最终报告**：新增一份最终综合验收报告，明确 blocker、known limitation、backlog、not_checked、platform-owned boundary、completed historical work，以及发布准入仍为未授权。

### 7.3 本地失败先行/反例矩阵

最终综合验收不新增功能测试，但必须主动重放跨 Slice 反例，而不是只运行已有 suite：

| ID | 反例 | 必须结果 |
| --- | --- | --- |
| FC-T1 | wrong/alias/broad/multi-target `list_agents` | 不建立 exact observation，不改变四平面强事实 |
| FC-T2 | nested/malformed/explicit-error wrapper | no-op/unknown；不扫描 summary、content、transcript |
| FC-T3 | exact `running` | `fresh_until=null`；Stop 仍 `continue=true` |
| FC-T4 | exact terminal `completed` 且无 TaskResult | business result 仍为 null，不自动 complete |
| FC-T5 | current child `business_result=completed` | strict reject；StateStore 与 result files 零 mutation |
| FC-T6 | exact sender 的合法 `complete` | record/read/pending/accept/tombstone 正常，observation/identity 不被结果改写 |
| FC-T7 | wrong task/attempt/sender 或冲突 payload | 写前拒绝或保留首份；不覆盖、不伪造 failed |
| FC-T8 | non-null `fresh_until` current state | Schema/runtime 拒绝且原始文件不重写 |
| FC-T9 | Start/Stop 带 transcript、last message 或 `task_result` 扩展 | 不建立 identity/result authority，native lifecycle fail-open |
| FC-T10 | StateStore Stop 三读失败 | 告警、`continue=true`、无写入 |
| FC-T11 | provider error/unknown/recovery/correction 边界 | success/failed/unknown 分离，预算有界，不产生业务结果 |
| FC-T12 | format 2/3/4 损坏或未知版本 | 拒绝且不重写；不借最终收口迁移或补造事实 |

所有主动状态使用新的 `TemporaryDirectory`。不得读取其他 smoke StateStore 的业务正文；真实报告只读取已落盘的脱敏证据和哈希。

### 7.4 真实 smoke 裁决

现有 Slice 3、4、5 真实报告与当前关键资产哈希一致，已足以支持本次 `NO-SLICE`。最终综合验收不应为了覆盖率自动创建 Agent。

若后续任务明确授权测试缓存更新和真实 Agent，可增加一个最小综合 smoke，但其目的只能是验证当前目标版本的既有闭环与加载来源，不能借机探索或启用新 authority：

- 新任务、`gpt-5.6-terra/high`，不得使用 luna 或 `xhigh`；
- 一个 `light`、`isolated`、只读、短任务，唯一 exact target；
- 第一次 TaskResult 合法，完成 exact record/read/accept/tombstone；
- terminal observation 与 business result 独立；
- 不强制捕获 running，不主动触发 Stop UI、restart、compact、recovery、replacement 或 correction；
- 未观察项继续写 `not_checked`。

没有明确部署/真实 Agent 授权时，综合验收只做本地门禁、哈希对账和既有真实报告审计。

### 7.5 上下文估算

这是一次高上下文独立任务：约需读取 25-35 份当前设计、实施、独立验收与真实报告，加上 runtime/Schema/Skill/tests 的定向 inventory；建议预留一个完整 `gpt-5.6-terra/high` 或 `gpt-5.6-sol/high` 对话。不得使用 luna 或 `xhigh`。若进入真实 smoke，应再单开新任务，避免实现/验收历史污染平台加载与终态证据。

## 8. 最终收口需要更新的文档状态

本设计任务不修改以下文件，但最终综合验收通过后应更新：

| 文件 | 当前滞后 | 最终收口应做 |
| --- | --- | --- |
| `docs/redesign/README.md` | 仍写 Slice 4 只允许独立验收，并禁止 Slice 5 | 更新为 Slice 1-5 已收口、Slice 6 `NO-SLICE`、下一步为最终综合验收；补 Slice 5 与本裁决索引 |
| `docs/redesign/platform-capability-contract-and-minimal-state-machine.md` | 真实平台验收段只写 Slice 3 PASS、Slice 4 仍只有本地证据 | 记录 Slice 4 exact adapter/freshness disabled/Stop advisory-only 真实 PASS，以及 Slice 5 首次合法结果与闭环真实 PASS；继续保留 running/Stop UI 等 `not_checked` |
| `README.md` / `README.en.md` | 功能边界大体正确，但没有当前 Slice 1-5 与最终收口状态摘要 | 仅在确有用户价值时加入简短当前能力/验收链接；不把内部切片历史扩写成使用手册 |
| `docs/platform-validation.md` | 公开摘要仍以 `0.4.0-rc.10` 为当前环境 | 在最终综合与发布边界明确后更新公开、脱敏的当前验收范围；不得复制本机路径、Session 或原始业务结果 |
| 其他路线/库存文档 | 可能保留被后续 Slice supersede 的旧状态语句 | 只修当前状态与索引；历史设计正文保留并通过 superseded/完成标记解释，不重写旧报告 |

文档滞后会增加维护者阅读成本，但它不改变 runtime correctness，因此不是 Slice 6 功能 blocker。更新必须由最终综合验收的证据驱动，不能在本设计任务中先写 PASS。

## 9. 发布与稳定安装边界

`NO-SLICE` 只表示当前没有新的平台能力功能需要实现，不表示发布就绪。以下权限仍未自动获得：

- 写稳定发布源或创建稳定 tag；
- 更新 Marketplace、Registry 或运行缓存；
- 修改 Hook trust、`hooks.json` 或任何 trust hash；
- 执行 cachebuster/reinstall、N-2 清理或缓存保留变更；
- 创建真实 Agent 或新的平台 smoke；
- 提交、推送或发布。

原因有三：

1. 功能冻结与发布授权是不同决策；
2. Hook trust、stable source、archive、cache、N/N-1 和 rollback 仍有发布专属门禁；
3. 用户必须明确授权外部写入、真实测试和稳定安装，最终综合验收不能代替该授权。

只有最终综合验收通过，发布候选范围明确，且用户另行明确授权后，才能按现有 `docs/release-process.md` 执行发布与稳定安装。任一发布必需项为 `failed` 或 `not_checked` 时，不能把 `NO-SLICE` 当作豁免。

## 10. 终态

最终裁决：**NO-SLICE**。

- 停止平台能力功能扩展，不实现 Slice 6；
- 不把最终整合/文档/门禁收口命名为 Slice 6；
- 下一步应是新的“平台能力最终综合验收与报告”任务；
- 新证据若暴露稳定反例，先重新分类和独立设计，不在收口中顺带修复；
- 发布、稳定安装、Hook trust、缓存写入、真实 Agent、提交和推送仍需分别明确授权。
