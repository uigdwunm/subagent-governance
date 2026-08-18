# 平台能力 Slice 5：正式结果词汇消歧（不新增 authority）

日期：2026-08-15

状态：边界已冻结；设计裁决为 **IMPLEMENT**。本裁决只准入后续独立实施任务，不在本文中修改 runtime、Schema、Skill、tests 或既有文档，也不批准测试部署、cachebuster、真实 Agent、发布、提交或推送。

## 1. 裁决

Slice 4 之后没有足够的官方或真实正向证据新增 runtime identity、active freshness、parent Stop hard gate 或其他平台 authority。Slice 5 因此冻结为一个**不新增 authority 的协议可用性切片**：

> 在所有插件生成的 TaskResult 生产者指令和父任务校验反馈中，机械区分平台终态 `completed` 与业务结果 `complete`，降低首次结果因词汇混淆而被拒绝、消耗一次 `result_correction` 和增加一次 native 往返的概率。

Slice 5 不接受 `completed` 作为业务别名，不自动修复 child payload，不从 `list_agents`、summary、transcript、Hook 或终态通知补造业务结果。严格拒绝仍是正确行为；本切片只让合法值在生产前更明确、拒绝后更可操作。

最终准入结论：**IMPLEMENT**。

## 2. 证据清单

### 2.1 已有正向平台证据

| 证据 | 已证明 | 没有证明 |
| --- | --- | --- |
| Slice 3 parent-authority 真实 smoke | 原生 child final 可到达父任务；父任务可用 exact `task_id + attempt + sender_target` 完成 record/read/accept/tombstone | Start/Stop identity、transcript 完整性、parent Stop、active freshness |
| Slice 4 真实 smoke | 顶层 `agents`、唯一 exact canonical target、单标签对象 `{"completed":"<summary>"}` 可形成 terminal observation；`fresh_until=null`；terminal 不生成业务结果 | running observation、Stop UI、summary 是正式结果 transport |
| Slice 4 同-Agent correction | 首次非法结果没有误写业务事实；第一次 governed `result_correction` 成功；更正后的 `business_result="complete"` 可完整闭环 | 任意非法 payload 可被自动修复；invalid payload 本身可授权新状态转换 |
| 当前机器语义与 TaskResult Schema | 平台 terminal status 包含 `completed`；业务结果只包含 `complete|blocked|failed|needs_decision`；两者属于不同平面 | 两个词可以互换或归一化 |
| 当前 runtime | `_task_result_reply_contract()` 同时用于 initial dispatch、`result_correction` 和 business resume；`validate_task_result()` 在持久化前拒绝非法枚举 | 当前 producer 指令已明确列出四个合法值或解释 `completed`/`complete` 差异 |

### 2.2 真实 smoke 暴露的产品/协议摩擦

Slice 4 真实 smoke 的第一次 current child terminal JSON 使用：

```json
{"business_result":"completed"}
```

该值是平台 terminal vocabulary，却不是业务 outcome vocabulary。插件正确拒绝了它，但用户可感知成本真实存在：

1. 首次正式结果不能记录；
2. 父任务需要识别错误并准备一次 governed `result_correction`；
3. 同一 Agent 需要再进行一次 native 往返；
4. correction budget 从 0 增至 1；
5. 任务闭环延迟，且弱网络下增加新的 unknown/failed 暴露面。

代码侧根因同样可复核：当前 `_task_result_reply_contract()` 只列出 `business_result` 字段名和三类场景附加字段，没有在相邻位置列出四个合法枚举，也没有说明“完成”必须写 `complete` 而不是平台状态 `completed`。当前校验错误只有“字段 business_result 枚举无效”，没有给出合法集合或两个词的平面差异。

这不是 Schema 错误，也不是 strict validator 过严；根因是机器语义在 producer/feedback 边界上的表达不充分。

### 2.3 Known limitation

- 有限 `list_agents` adapter 只接受已有正向证据的顶层 `agents` object/JSON string 和 exact canonical binding。
- format 4 没有 active freshness；exact running 也可能立即陈旧。
- parent Stop advisory 只显示 canonical 父责任，不证明 Agent 当前仍 active，也不替父任务验收结果。
- ObservationRecord 是收敛记录，不是 observation event log。
- native terminal summary 不是正式结果 transport；平台 transport 与 Hook 内部仍 opaque。
- 模型即使收到明确枚举仍可能输出非法值；本切片降低歧义，不承诺消除所有 protocol error。

这些限制不由 Slice 5 修复，也不构成其 blocker。

### 2.4 Backlog

- 只有取得官方或独立真实 TTL、刷新、乱序和跨重启保证后，才能以新切片和新状态格式重新评估 freshness。
- 只有 freshness authority 成立，且 parent Stop 真实展示、重入和 fail-open 有独立证据后，才能重新评估 limited hard gate。
- 新 wrapper/status 形状必须先保存正向平台证据并增加失败先行测试；不得用递归 parser 预适配。
- 若以后多次真实 smoke 证明“invalid current child notification 在没有 exact terminal observation 时无法进入 correction admission”是独立、稳定问题，应另行设计父任务 protocol-gap 入口；Slice 5 不借本次单一词汇摩擦新增该写入 authority。

### 2.5 Not_checked

- 真实 non-terminal/running `list_agents` observation。
- parent Stop advisory 在真实 Codex UI 中的展示、重入和退出行为。
- 独立 SubagentStart/SubagentStop payload、顺序、identity 关联和真实投递。
- Start/Stop identity、provider restart、compact/resume、乱序 observation 和跨版本 StateStore。
- Provider 内部日志面、Hook trust、稳定源、运行缓存、Marketplace、Registry、发布包和 N/N-1。

这些项目不能作为 Slice 5 authority，也不是 Slice 5 真实 smoke 的通过条件。

### 2.6 已完成且不得重复的旧工作

- D1-D6 已完成四层对象、派发/交付物、outcome/disposition、恢复边界、决策诊断和迁移切片设计；其中关于 Start 强绑定或 Stop 结果承载的早期文字已被平台能力 Slice 1-4 supersede。
- 旧 D6 S5 已完成 work-item-first diagnostics/group；旧 D6 S6 已完成 compatibility retirement/release preparation。新 Slice 5 与这两个编号没有继承关系。
- F1-F13 已完成 growth admission/reservation、same-Agent 迟到路由、duplicate risk、action-required 单一权威、growth projection、canonical Schema、残余清理、两轮架构 review、target lifecycle admission、initial rollback、interrupt stale-owner 修复和最终本地验收。
- Slice 1-4 已分别完成官方 Hook 能力降级、四平面 canonical state、父任务权威结果通道和有限 observation/Stop 边界。

Slice 5 不重做 diagnostics/group、compatibility、四平面、parent result channel、replacement、duplicate、growth、rollback 或 lifecycle admission。

### 2.7 插件无法修复的平台内部边界

- Provider 网络、worker 存活、mailbox 投递与 UI 展示是否可靠。
- 平台是否记录或变换 prompt、tool input、Hook output 或内部日志。
- 官方 Hook 没有提供的 attempt identity、active TTL、刷新顺序和跨重启保证。
- 原生模型是否始终遵守枚举、是否在一次 terminal notification 中输出完整 JSON。

插件只能让自身生成的契约更明确并保持拒绝边界；不能把上述平台内部未知变成保证。

## 3. 为什么 Slice 5 优先

| 候选 | 证据状态 | 裁决 |
| --- | --- | --- |
| `completed`/`complete` 正式结果词汇消歧 | 真实 smoke 已复现；当前 prompt 与校验反馈存在可定位缺口；现有 correction 证明恢复成本 | **纳入 Slice 5** |
| running observation authority | `not_checked` | 不准入 |
| parent Stop hard gate | 真实 UI 仍 `not_checked`，且没有 freshness | 不准入 |
| active TTL/freshness | 没有官方刷新、乱序或跨重启保证 | 不准入 |
| Start/Stop identity | 官方契约无 attempt 关联键 | 不准入 |
| transcript/summary/final-history 结果提取 | 已明确禁止，且 terminal summary 已证明不能替代正式结果 | 不准入 |
| 新 wrapper 预适配 | 没有新正向平台样本 | 留在 backlog |
| observation event log | 当前没有独立用户问题或 correctness 缺口证据 | 留作 known limitation/backlog，不建切片 |
| D6 S5/S6 或 F1-F13 任一功能 | 已完成 | 禁止重复 |

Slice 5 优先不是因为影响面最大，而是因为它是 Slice 4 后唯一同时具备“真实复现、代码根因、用户成本、最小可逆修复、独立验收条件”五项证据的候选。其余候选要么已经完成，要么仍是 limitation/backlog/not_checked，要么属于平台内部。

## 4. 唯一目标、用户价值与根因

### 4.1 唯一目标

让插件生成的每一条 TaskResult 生产指令和非法枚举反馈都从同一机器枚举明确表达：

```text
business_result = complete | blocked | failed | needs_decision
完成时使用 complete；completed 是平台终态，不是业务结果。
```

### 4.2 用户可感知价值

- 降低首次结果因词汇混淆被拒绝的概率。
- 避免一次不必要的 result-correction 往返和预算消耗。
- 父任务收到拒绝时可以直接知道合法值与错误平面，不必查询 Schema 或猜测。
- 保留严格结果边界，不以“方便”为由接受错误业务事实。

### 4.3 根因

机器层已经正确区分两个词，丢失发生在边界表达：

```text
机器语义：platform completed != business complete
       |
       v
当前 child 指令：只说需要 business_result，未列合法值
       |
       v
模型沿用邻近平台词 completed
       |
       v
validator 正确拒绝，但反馈只说 enum invalid
```

因此最小修复点是 producer contract 与 validator feedback，而不是 Schema、状态机或 observation/result authority。

## 5. 冻结不变量

1. `business_result` 合法集合保持 `complete|blocked|failed|needs_decision`，不增加 `completed`。
2. 平台 `completed` 只属于 exact terminal observation；它永远不映射、复制或归一化成业务 `complete`。
3. 业务结果仍只来自父任务根据 current native child notification 显式调用的 `--record-child-result`。
4. invalid TaskResult 在校验阶段拒绝；拒绝前后 StateStore、result 文件、observation、identity、result 和 closure 均不变。
5. initial dispatch、result correction 和 business resume 共用同一 TaskResult reply contract，不维护三份漂移文案。
6. 合法枚举列表从现有机器语义 `business_result` 来源生成，不新增第二份硬编码业务枚举。
7. `completed` 的消歧说明只解释现有平台/业务平面差异，不建立 parser alias 或平台到业务的转换表。
8. correction/recovery/spawn 的次数、admission、success/failed/unknown 和 parent action 不变。
9. 不新增持久字段、状态枚举、CLI、Hook 事件、后台任务或状态格式版本。
10. 不改变 Slice 4 的 `fresh_until=null` 与 parent Stop advisory-only。

## 6. 状态转换与 failure/unknown 路径

Slice 5 不增加状态转换，只复用现有状态机。

| 输入/观察 | 结果 | 允许的下一步 |
| --- | --- | --- |
| child 首次返回合法 `business_result="complete"` | parent exact record 后进入 valid/available + pending acceptance | read + `accept_result` 或 `reject_result` |
| child 返回合法 non-complete outcome | 按 blocked/failed/needs_decision 既有规则写入 | `decide_disposition` 或 `ask_user` |
| child 返回 `business_result="completed"` | validator 拒绝，并明确合法集合与平面差异；零状态/文件 mutation | 只有既有状态已允许 correction 时，准备同 attempt `result_correction` |
| invalid payload，但没有 correction admission 所需的既有可靠事实 | 不因 invalid payload 新建 protocol-gap authority | 保持原 parent action；继续 exact 对账或人工处置，不能自动写 `needs_correction` |
| correction native success | 只证明调用观察；等待 corrected current notification | 现有 wait/result path |
| correction native failed | 按既有 correction budget/状态处理 | 不伪造业务 failed |
| correction native unknown | `reconcile`，不重发、不归一化旧 payload | 等待迟到事实或显式处置 |
| correction budget exhausted | 既有 `exhausted + manual_review` | 不创建第三次 correction |
| exact `list_agents completed` 或 summary 含合法 JSON | 只写 terminal/result-gap observation；不扫描 summary | 等待 current notification + parent record |

## 7. 明确不做和不新增的 authority

- 不把 `completed` 加入 TaskResult Schema。
- 不接受大小写、时态、近义词或 typo alias。
- 不自动把 `completed` 改写为 `complete`，也不做 parent-side JSON repair。
- 不解析 terminal summary、transcript、`last_assistant_message`、history 或 Hook 扩展。
- 不让 invalid child payload 本身写 `needs_correction`、business result 或 observation。
- 不改变 exact sender binding、结果存储、幂等、冲突、accept/reject/close/select。
- 不新增 Start/Stop identity、running freshness、TTL、Stop block、scheduler、自动 recovery 或 replacement。
- 不扩展旧 D6 S5 diagnostics/group，不新增 AggregateResult、DAG、batch 或第二套编排。
- 不修改 stable source、cache、Hook trust、Marketplace、Registry 或发布元数据。

## 8. 后续实施的最小修改范围

| 面 | 是否修改 | 最小范围 |
| --- | --- | --- |
| runtime | 是 | 只修改 TaskResult reply contract 的渲染和 invalid `business_result` 的诊断文本；initial/result-correction/business-resume 继续共用同一 renderer；合法值从现有 `BUSINESS_RESULTS` 读取；不改 writer/state transition |
| Schema | **否** | 现有 TaskResult 与 governance semantics 已正确区分 `complete` 和 platform `completed`；增加 alias、映射或新字段都会错误扩大 authority |
| Skill | 是 | 在正式结果与 result-correction 义务处加入一次明确对照：完成业务写 `complete`，平台 `completed` 不合法；同时重申不得自动修复或从 summary 推断 |
| tests | 是 | 优先修改/新增 `tests/test_parent_result_channel.py` 与 `tests/test_communication_lifecycle.py`；必要时补 `tests/test_semantic_baseline.py`，证明机器枚举来源和无 alias；不新建大而重复的状态机 suite |
| docs | 是 | 新增 Slice 5 implementation report，并在平台 capability contract 中记录“producer/feedback disambiguation, no authority change”；README、D1-D6、旧报告和旧 smoke 不修改 |

实现不得顺带重构 prompt renderer、TaskResult dataclass、result storage、communication admission 或 CLI error framework。

## 9. 失败先行测试矩阵

### 9.1 必须先红的缺口测试

| ID | 用例 | 实现前预期 | 实现后预期 |
| --- | --- | --- | --- |
| S5-T1 | initial dispatch message 包含四个 exact 业务枚举，并明确 `complete != completed` | FAIL：当前只列字段名 | PASS |
| S5-T2 | same-attempt `result_correction` message 使用同一 exact 指令 | FAIL：当前仍只列字段名 | PASS |
| S5-T3 | business resume 的 TaskResult 义务使用同一 exact 指令 | FAIL：当前仍只列字段名 | PASS |
| S5-T4 | `validate_task_result({business_result:"completed"})` 的错误列出合法集合并说明平台词无效 | FAIL：当前只有“枚举无效” | PASS |

### 9.2 必须保持绿的不变量测试

| ID | 用例 | 必须证明 |
| --- | --- | --- |
| S5-T5 | `completed` envelope 进入 parent record | 返回 protocol error；StateStore 原始字节、result 文件集合和四平面不变 |
| S5-T6 | `complete` envelope | exact sender 下正常 stored/read/pending；不会因平台词消歧改变 digest 或结果语义 |
| S5-T7 | blocked/failed/needs_decision | 四种业务 outcome 及场景字段规则全部不回退 |
| S5-T8 | terminal observation 为 `completed`，无 TaskResult | business result 仍为 null；不得因新文案或错误提示自动合成 `complete` |
| S5-T9 | summary/transcript 中出现 `business_result="complete"` | no-op；不扫描、不记录 |
| S5-T10 | invalid value 后走 governed correction | correction count、claim/PostTool 三态和原 attempt 规则不变；corrected `complete` 可记录 |
| S5-T11 | machine enum parity | producer/feedback 包含现有全部 `BUSINESS_RESULTS`，没有额外可接受 alias |

所有主动状态测试使用 `TemporaryDirectory` 下的新 StateStore/results/prepared；不得读取既有 smoke StateStore 或其业务正文。

## 10. 本地门禁

后续实施至少运行并记录：

```bash
python3 -m unittest -v \
  tests.test_parent_result_channel \
  tests.test_communication_lifecycle \
  tests.test_platform_capability_slice4 \
  tests.test_semantic_baseline
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
python3 scripts/release_preflight.py --mode development
git diff --check
```

另需：

- 解析全部 repository JSON；
- 对新增未跟踪文本做独立 whitespace 检查；
- 对 TaskResult enum、runtime `BUSINESS_RESULTS`、producer 文案和 validator feedback 做双向来源检查；
- 如共享工作树存在既有基线错误，必须逐项精确报告，不能把部分通过写成全绿，也不能顺带修复无关问题。

本地门禁通过只允许进入独立验收，不批准测试部署或真实 smoke。

## 11. 独立验收

独立验收必须在新的对话中进行，不能由实施对话自验收。建议使用 `gpt-5.6-terra/high` 或 `gpt-5.6-sol/high`；不得使用 luna 或 `xhigh`。

验收者必须：

1. 从本冻结设计、当前 runtime/Skill/tests/diff 重新建立 writer、producer 和 validator inventory，不采信 implementation report 的 PASS。
2. 独立构造 S5-T1 至 S5-T11，所有状态使用临时目录。
3. 证明 invalid `completed` 没有任何 state/result mutation，而不是只检查返回字符串。
4. 证明 initial、correction、resume 三条 producer 路径使用同一来源，没有三份漂移文案。
5. 搜索并主动反例证明不存在 alias normalization、summary/transcript extraction 或 observation-to-result mapping。
6. 重新执行全部本地门禁并分类 blocker、known limitation、backlog、not_checked。

独立结论只有在全部失败先行目标通过、所有冻结不变量无回退且无新 blocker 时才可为 **GO**。GO 只允许准备测试 cachebuster 和新建真实 smoke；NO-GO 必须回到同一 Slice 5 修复，不得启动 Slice 6。

## 12. 真实 smoke 条件

真实 smoke 不是本设计或实施任务的一部分。只有开发仓库实现通过独立 GO、用户另行授权更新测试插件后，才按项目流程同步并在当前项目中新建对话。默认模型/强度固定为 `gpt-5.6-terra/high`；不得使用 luna 或 `xhigh`。

最小 smoke：

1. 使用新 Session、一个 `light`、`isolated` native Agent 和唯一 exact canonical target；不复用设计、实施或验收对话。
2. 派发一个短、确定、无需仓库写入的任务，让 child 依据生成契约提交 TaskResult。
3. 首次 current child terminal notification 必须使用合法 `business_result="complete"`。核心通过路径不得依赖 result correction。
4. exact target-only `list_agents` 可以同时报告平台 `completed`；在 parent record 前必须保持 `business_result=null`，证明两个词仍未合并。
5. 父任务按 exact sender 完成 record/read/accept/tombstone，并确认 observation 与 result plane 相互独立。
6. 不要求捕获 running 或触发 parent Stop UI；二者继续标为 `not_checked`，不能为了覆盖而干扰核心闭环。

若首次 child 仍返回 `completed`，可使用既有 correction 链安全收口测试任务，但 Slice 5 核心 smoke 必须判 **FAIL**，不能因为最终恢复成功而改写为 PASS。报告必须分别列出 blocker、known limitation、backlog 和 not_checked。

## 13. 上下文规模与对话拆分

| 阶段 | 预计上下文 | 对话裁决 |
| --- | --- | --- |
| 实施 | 中等，约 25k-40k tokens；需要本设计、runtime 两个小区域、Skill 两节和 focused tests | **新对话**。当前设计对话已读取大量 D1-D6、Slice 1-4 和历史报告，不应继续承载实现 |
| 独立验收 | 中等偏大，约 35k-55k tokens；需要主动反例、全量门禁和来源审计 | **另一个新对话**，与实施隔离 |
| 真实 smoke | 小到中等，但需要真实插件环境与完整生命周期 | **第三个新对话**，且必须在独立 GO 与测试更新授权之后 |

三个阶段均不得使用 luna 或 `xhigh`。实施和验收不需要完整继承本对话；以本文、Slice 4 真实报告、平台 capability contract 和精确 relevant files 作为有限背景即可。

## 14. Blocker、limitation、backlog 与准入

### Blocker

当前设计准入 blocker：无。

后续实施若无法证明 producer/feedback 从现有 machine enum 派生，或引入任何 alias normalization、state mutation、Schema 扩权，则为 Slice 5 blocker。

### Known limitation

见 2.3；Slice 5 不保证模型永不犯错，也不改变平台 transport、identity、freshness 或 Stop 能力。

### Backlog

见 2.4；TTL、Stop gate、新 wrapper 和可能的显式 protocol-gap authority 都必须各自获得新证据后另行设计。

### Not_checked

见 2.5；running、Stop UI、Start/Stop identity、provider internals 和 release surfaces 不进入 Slice 5 验收。

### 实现准入

**IMPLEMENT**。

下一步最小任务是在新对话中先补 S5-T1 至 S5-T4 的失败测试，再只修改共享 TaskResult reply contract 与 invalid-enum feedback，随后同步最小 Skill/能力契约/implementation report 并执行本地门禁。不得修改 Schema，不得部署或创建真实 Agent；实现完成后交给另一个新对话独立验收。

## 15. 真实 smoke blocker 与 Slice 5 回修

后续独立验收曾按本设计给出 GO，但 `2026-08-15` 的 Slice 5 真实 smoke 随后暴露了一个仍属于本切片的 producer-contract blocker：首次 child 已正确返回 `business_result="complete"`，却把必填的 `evidence` 和 `remaining` 写成字符串，而不是 JSON 字符串数组。插件严格拒绝该 payload，且没有写入正式结果；这证明 validator、writer 与四平面隔离仍正确，但也证明原共享回复契约只列字段名不足以让真实 child 首次机械地产生合法 TaskResult。

该 smoke 的 **CORE FAIL**、原独立验收的历史 GO 和原实现的本地 PASS 均保留，不互相改写。回修继续留在 Slice 5，不准入 Slice 6，也不新增 authority。修复范围冻结为：

1. initial dispatch、`result_correction` 与 `business_resume` 继续调用同一个 `_task_result_reply_contract()`。
2. 基础字段和场景字段从既有 `TASK_RESULT_BASE_REQUIRED_FIELDS`、`TASK_RESULT_SCENARIO_FIELDS` 与 `BUSINESS_RESULTS` 取得字段/枚举语义；JSON 类型只由一个共享 helper 渲染，并以 runtime/TaskResult Schema/renderer parity 测试约束。
3. `result`、`suggested_parent_next_step` 明确为 `string`；`evidence`、`remaining` 明确为必填 `string[]` 且允许 `[]`；blocked/failed 的 `attempted` 为允许 `[]` 的 `string[]`；needs_decision 的 `options` 为至少一项的 `string[]`。
4. producer contract 提供一个不含固定业务正文、包含 `task_id`、`attempt`、`business_result` 的最小 `complete` JSON 示例；其他 outcome 仍须追加对应场景必填字段。
5. scalar `evidence`、`remaining`、`attempted`、`options` 继续严格拒绝，不 coercion、不 alias、不 parent repair；invalid result 仍不得修改 StateStore、result 文件、dispatch/observation/result/closure、identity 或 closure。

本回修不修改两个 Schema，不改 writer、result state、observation、identity、closure、correction budget、`fresh_until` 或 Stop，也不解析 summary/transcript/history/Hook。完成本地门禁后只恢复“可再次独立验收”资格；不得用本次实施对话替代新的独立验收或真实 smoke。
