# Slice 5 真实 smoke 数组字段 blocker 独立复验

日期：2026-08-15

结论：**GO**。当前开发工作树中的 Slice 5 producer contract 修复满足本地独立验收条件；它没有扩大结果 authority，也没有放宽 TaskResult 的严格类型边界。此 GO **只**准入新的测试 cachebuster 和新的独立真实 smoke，不准入 Slice 6、稳定发布、安装、Hook trust/Marketplace/Registry 写入、提交或推送。

本复验完整读取了 Slice 5 design、implementation、smoke blocker fix 和原真实 smoke 报告；implementation/fix 中的 PASS 没有作为证据使用。所有主动 StateStore 检查均在 `TemporaryDirectory` 新建的 sessions/prepared/results 下完成，未读取或修改任何既有 smoke StateStore 业务正文。

## 独立矩阵

| 检查 | 独立结果 | 证据 |
| --- | --- | --- |
| 三条 producer | PASS | 对 `prepare_dispatch`、`prepare_communication(result_correction)`、`prepare_communication(business_resume)` 分别植入只读 probe；三次均命中同一 `_task_result_reply_contract()`，调用 scope 为 initial `task#1`、correction `task#1`、resume `task#2`。runtime 只有 initial 的 `scripts/subagent_governance.py:2275` 和 communication 的 `scripts/subagent_governance.py:6073` 两个 caller。 |
| 生成说明与 skeleton | PASS | 共享 renderer 明确 `result`、`suggested_parent_next_step` 为 `string`，`evidence`、`remaining` 为可空列表形式的 `string[]`，`attempted` 为 `string[]`，`options` 为至少一项的 `string[]`。`scripts/subagent_governance.py:2179` 的 `_task_result_field_json_type` 是唯一字段类型映射；`scripts/subagent_governance.py:2201` 的 reply renderer 最小 JSON 固定实际 `task_id`/`attempt`，其余文本均为 `<string>` 占位符，业务值仅为示例所需的 `complete`。 |
| 原始 scalar smoke 反例 | PASS | 构造 `business_result=complete` 且分别令 `evidence`、`remaining` 为 scalar。两个 `record_child_result` 均在 `scripts/subagent_governance.py:4170` 的 validator 调用后、任何 writer 前抛出 `ResultSubmissionError`。逐项比对 StateStore 原始字节、结果文件集合/字节、dispatch/observation/result/closure 和 `identity_status`/`agent_id`/`canonical_task_path`：严格零 mutation。 |
| 正反类型组合 | PASS | `complete`、`blocked`、`failed`、`needs_decision` 的合法 `[]`/string arrays 均通过；scalar `evidence`、`remaining`、`attempted`、`options` 均拒绝，空 `options` 亦拒绝。未见 coercion 或 wrap 行为；数组验证由 `scripts/subagent_governance.py:1801` 的 `_validate_text_list` 直接要求 `list`。 |
| Schema/runtime/renderer parity | PASS | 15/15 TaskResult 字段逐一比对 `task-result-v1.schema.json`、runtime helper 与 renderer：7 个基础必填字段、3 个场景、4 个业务 outcome 均一致。基础和场景必填继续分别来自 `TASK_RESULT_BASE_REQUIRED_FIELDS`、`TASK_RESULT_SCENARIO_FIELDS`，即 machine semantics；没有新增独立场景表。 |
| vocabulary 与 Slice 4 边界 | PASS | `business_result` 机器枚举为 `complete|blocked|failed|needs_decision`；validator 对 `completed` 明确拒绝并引用同一枚举。Slice 4 的 `fresh_until=null` 仍受 runtime 拒绝非 null 值，`scripts/subagent_governance.py:10247` 的 Stop 始终返回 `continue=true`，仅 advisory。 |
| 旁路搜索 | PASS | 审计 runtime、tests、Skill、capability contract：无 `business_result` alias/normalization/coercion/wrap/parent JSON repair；无 summary/transcript/history/`last_assistant_message`/Hook extraction；无 observation-to-result mapping。匹配项仅为禁止性 contract/Skill 表述与拒绝测试。 |

TaskResult Schema 的 15 个字段为：`task_id`、`attempt`、`business_result`、`result`、`evidence`、`remaining`、`suggested_parent_next_step`、`blocker`、`attempted`、`required_to_resume`、`failure_reason`、`retry_conditions`、`decision_question`、`options`、`recommendation`。类型分类是 11 个 `string`、1 个 `integer`、4 个 `string[]`；`options` 的场景约束是至少一项，其余数组可为 `[]`。

## 本地门禁

| 门禁 | 结果 |
| --- | --- |
| 独立临时反例/正例 | PASS：2 个 record-time scalar 拒绝、4 个合法 outcome、5 个负向数组形状检查 |
| 共享 producer probe | PASS：3/3 actual producer calls 命中同一 renderer |
| focused | PASS：`118/118` |
| full unittest | PASS：`440/440` |
| `python3 -m py_compile scripts/subagent_governance.py` | PASS |
| Plugin validator | PASS |
| Skill validator | PASS |
| `scripts/release_preflight.py --mode development` | PASS |
| repository JSON parse | PASS：`15/15` |
| `git diff --check` | PASS |
| 全部 untracked whitespace | PASS：`68/68`，0 issues |

## Scope 与基线

`schemas/task-result-v1.schema.json` 和 `schemas/governance-semantics.schema.json` 在本复验开始时已是共享工作树既有未提交修改。相对 `HEAD` 的 diff 分别为 `1/1` 和 `1244/5`（added/deleted lines），但本工作树没有修复实施窗口内的直接写入证据可将其归因给本数组字段修复；因此它们不构成本 Slice 5 scope blocker，也未被修改或回退。

本结论评估的是 Slice 5 task delta，而不是要求共享工作树相对 `HEAD` 干净。此次复验只新增本文件。

## 分类

### Blocker

无。

### Known limitation

- 生成契约降低数组/词汇误用概率，不能保证原生 child 首次回复永远机械合法。
- 平台 terminal `completed`、native summary 与正式业务 `complete` 仍是不同平面；正式结果仍只允许精确 sender 的父任务 record path。
- `list_agents` 的 active freshness 仍禁用，`fresh_until=null`；parent Stop 仍 advisory-only。

### Backlog

- 新 wrapper/status 形状、freshness/TTL、Stop hard gate 和任何 protocol-gap authority 仍需独立的官方或真实证据与新切片。

### Not_checked

- 未创建真实 Agent，未部署/cachebuster，因而未复验修复后原生模型在全新 session 是否首次提交 array-shaped TaskResult。
- running observation、Stop UI 交互、SubagentStart/SubagentStop 精确关联、provider restart/compact/乱序与 Hook trust/运行缓存/稳定源均不在本地复验范围。

## 准入

向主任务报告：**GO**。下一步仅可在用户另行授权后，更新测试 cachebuster 并在本项目新建独立真实 smoke；核心路径必须要求首个 current child TaskResult 使用合法 `complete` 和 `evidence`/`remaining` JSON arrays，不能用 correction 代替首次成功。
