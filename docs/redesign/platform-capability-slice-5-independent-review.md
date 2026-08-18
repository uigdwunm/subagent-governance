# 平台能力 Slice 5：独立验收审查

日期：2026-08-15

结论：**GO**。运行时行为、独立 S5 矩阵和设计第 10 节本地门禁均通过；没有发现属于 Slice 5 task delta 的 blocker。此 GO 只允许后续测试 cachebuster 和新建独立 Slice 5 真实 smoke，不代表本审查已经部署或创建真实 Agent。

本审查完整读取 `platform-capability-slice-5-design.md`。`platform-capability-slice-5-implementation.md` 仅作为被审材料，未将其 PASS 作为任何验收证据。未修改 runtime、Schema、tests、Skill、README、既有报告、Hook、缓存或发布面；未创建真实 Agent，且主动状态均在 `TemporaryDirectory` 下创建。

## Baseline Diff 更正

首次审查错误地把 `git diff HEAD` 中的下列共享工作树历史差异归因为 Slice 5：

```json
"additionalProperties": true
```

变为：

```json
"additionalProperties": false
```

`git diff -- schemas/task-result-v1.schema.json` 只能证明相对 `HEAD` 的差异，不能确定写入者或所属 task delta。重新核验显示：

- `schemas/task-result-v1.schema.json` mtime 为 `2026-08-14 21:47:57 +0800`；
- Slice 5 设计为 `2026-08-15 13:08:38 +0800`，runtime 为 `13:12:36`，相关 tests 为 `13:14-13:20`，implementation report 为 `13:21:20`；
- Schema 文件在 Slice 5 开始前已经是工作树中的 `M`，而 Slice 5 实施文件清单不含该文件。

故该 Schema 行为变化是既有未提交基线，不是已证明的 Slice 5 写入；冻结设计的“Schema：否”约束的是 Slice 5 task delta，不授权回退其他切片或用户已有修改。该文件也不含 business enum alias 或 Slice 5 producer/feedback 的变更。审查没有直接证据证明它在 Slice 5 实施期间被写入，因此撤销此前 blocker，且未修改或恢复 Schema。

## Blocker

无。

## 独立矩阵

主动测试没有复用实现测试的断言作为唯一证据。每个场景新建临时 StateStore、prepared 和 results 根；initial dispatch 通过实际 PreToolUse claim 建立，再按 exact sender 路径执行。

| ID | 独立证据 | 结果 |
| --- | --- | --- |
| S5-T1 | initial dispatch 实际消息含四个 exact 值和 `complete`/`completed` 平面说明 | PASS |
| S5-T2 | terminal 后实际 `result_correction` preparation 含当前 attempt 的同一 renderer 输出 | PASS |
| S5-T3 | legal blocked 后实际 `business_resume` preparation 含新 attempt 的同一 renderer 输出 | PASS |
| S5-T4 | `completed` 错误列出 canonical 合法集合并说明平台终态与业务结果差异 | PASS |
| S5-T5 | `completed` record 被拒；StateStore 原始字节、result 文件集合和字节、四平面、identity 严格不变 | PASS |
| S5-T6 | exact sender 的 `complete` record/read/accept 保持 canonical digest、pending 再 accepted 路径 | PASS |
| S5-T7 | `complete`、`blocked`、`failed`、`needs_decision` 全部保留原 scenario 校验和 parent action | PASS |
| S5-T8 | exact terminal observation `completed` 不合成 TaskResult，business result 仍为 null | PASS |
| S5-T9 | summary、transcript、history、last assistant message、observation 中的结果形文本均为 no-op | PASS |
| S5-T10 | invalid 不授予写入 authority；exact terminal 后同 attempt correction 计数为 1，corrected complete 可记录 | PASS |
| S5-T11 | machine enum、runtime、producer、feedback 一致；`completed`、大小写和空白/时态类值被拒 | PASS |

独立矩阵：**11/11 PASS，0 failures**。

## Inventory 与边界审计

- 唯一机器 enum 是 `schemas/governance-semantics.schema.json` 的 `$defs.business_result.enum`：`complete | blocked | failed | needs_decision`。`schemas/task-result-v1.schema.json` 仅以 `$ref` 使用它；runtime `BUSINESS_RESULTS` 在加载时由同一定义生成。
- renderer 是 `scripts/subagent_governance.py:2179` 的 `_task_result_reply_contract()`；initial dispatch 在 `render_dispatch_prompt()` 调用它，`render_communication_message()` 只在 `result_correction` 和 `business_resume` 分支调用同一函数。不存在三份 producer 文案。
- validator `validate_task_result()` 位于 `scripts/subagent_governance.py:1991`；非法 `business_result` 由 `BUSINESS_RESULTS` 判定，并由 `_business_result_values_text()` 从 canonical enum 输出反馈。writer `record_child_result()` 位于 `scripts/subagent_governance.py:4094`，在 StateStore/result writer 前调用 validator。
- 双向核对结果：Schema enum 4、runtime enum 4、producer 4、feedback 4；未发现第二份可接受业务结果枚举。`completed` 不在 `BUSINESS_RESULTS`。
- 搜索 `alias`、`normalize`、`lower`、`upper`、`strip`、`replace` 与所有 business-result 调用点，未发现对业务结果的 alias normalization、大小写或时态映射。`normalize_semantic_name()` 只处理 task semantic name，不参与 TaskResult。
- 搜索 `list_agents`、summary、transcript、history、`last_assistant_message`、Hook 和 observation 的结果旁路，未发现从这些来源产生或接受 business result 的路径。平台 adapter 的 terminal `completed` 仅在 observation plane 使用。
- platform capability contract 明确记录 shared renderer、strict rejection 与无 alias/repair/observation-to-result mapping；Skill 两处同步说明业务完成写 `complete`，`completed` 为平台终态。
- Slice 4 不变量仍存在：`fresh_until` 在 Schema 中为 JSON `null`，runtime 拒绝非 null；hook capability contract 仍为 `active_freshness_authority=disabled`、`parent_stop_behavior=advisory_continue`。terminal observation 不等于 TaskResult 已由 S5-T8 主动验证。

## 本地门禁

| 门禁 | 结果 |
| --- | --- |
| focused unittest（设计第 10 节四模块） | 117/117 PASS |
| full unittest discover | 439/439 PASS |
| `py_compile` | PASS |
| Plugin validator | PASS |
| Skill validator | PASS |
| development preflight | PASS |
| repository JSON parse | 17/17 PASS |
| `git diff --check` | PASS |
| untracked UTF-8 text whitespace | 66/66 checked，0 issues |

全量门禁：**9/9 PASS**。

## Known Limitation

- 明确 producer/feedback 只能降低模型首次混淆，不能保证模型永不发出非法 payload。
- native terminal summary 不是正式结果 transport；平台 transport 与 Hook 内部仍 opaque。
- Slice 4 的有限 top-level `agents` adapter、`fresh_until=null` 和 Stop advisory-only 不提供 freshness 或 hard-gate authority。

## Backlog

- active freshness、parent Stop hard gate、新 wrapper/status 形状以及显式 protocol-gap authority，仍需要独立的平台证据和新设计。

## Not Checked

- 真实 running/Stop UI、Start/Stop identity、provider internals。
- provider restart、compact/resume、乱序 observation、跨版本 StateStore。
- Hook trust、稳定源、运行缓存、Marketplace、Registry、发布包和真实 Slice 5 smoke。

这些均不是本次通过条件，也没有被表述为已验证。

## 准入

功能验收数字为 **11/11**，本地门禁数字为 **9/9**，baseline diff 已与 Slice 5 delta 区分，故为 **GO**。**允许后续测试 cachebuster 和新建独立 Slice 5 真实 smoke**；本审查没有执行部署、cachebuster、真实 Agent、稳定发布、提交或推送。
