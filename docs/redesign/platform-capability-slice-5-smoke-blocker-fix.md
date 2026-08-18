# Slice 5 真实 smoke blocker 修复报告

日期：2026-08-15

状态：**本地修复完成，可再次独立验收**。本任务未部署、未 cachebuster、未写稳定源/运行缓存/Hook trust/Marketplace/Registry，未创建真实 Agent，未提交或推送。

## 1. Blocker 与边界

真实 smoke 的首次 child TaskResult 已正确使用 `business_result="complete"`，但 `evidence` 和 `remaining` 是字符串而非数组。现有 validator 严格拒绝该 payload，且 StateStore、正式结果、四平面、identity 与 closure 没有业务结果 mutation；真实 smoke 因首次结果不 mechanically valid 而判 **CORE FAIL**。

根因是共享 `_task_result_reply_contract()` 只列出字段名，未明确 JSON 类型和场景必填约束。修复继续留在 Slice 5，只改善 producer contract，不改变 Schema、validator 接受集合、writer 或状态机 authority。

## 2. 失败先行

runtime 未修改时先运行四项精确测试：

| 用例 | 修复前结果 | 命中缺口 |
| --- | --- | --- |
| initial dispatch | FAIL | 缺少基础字段 JSON 类型和最小示例 |
| `result_correction` | FAIL | 缺少同源基础/场景类型说明 |
| `business_resume` | FAIL | 缺少同源基础/场景类型说明 |
| Schema/runtime/renderer parity | FAIL | 缺少共享类型 helper |

失败先行数字：**4 tests，0 pass、4 failures**。最小实现后同四项为 **4/4 PASS**。

## 3. 实现

### 单一类型说明来源

- `_task_result_field_json_type()` 是唯一 JSON 类型映射 helper。
- `_render_task_result_fields()` 只消费该 helper，不维护另一份类型表。
- 基础字段和场景字段分别来自既有 `TASK_RESULT_BASE_REQUIRED_FIELDS` 与 `TASK_RESULT_SCENARIO_FIELDS`。
- `business_result` 合法值继续来自 canonical machine semantics 与 `BUSINESS_RESULTS`，没有新增枚举或 alias。
- parity 测试逐字段把 helper 输出与未修改的 `task-result-v1.schema.json` 对照，并确认 validator、renderer 和 Schema 对数组/字符串/整数规则一致。

共享 renderer 现在明确：

- `task_id`、`business_result`、`result`、`suggested_parent_next_step` 为 `string`；`attempt` 为 `integer`。
- `evidence`、`remaining` 为必填 `string[]` 且允许 `[]`。
- blocked/failed 的 `attempted` 为 `string[]` 且允许 `[]`。
- needs_decision 的 `options` 为至少一项的 `string[]`。
- 最小 `complete` JSON 示例包含 `task_id`、`attempt`、`business_result` 及全部基础字段，只使用占位字符串，不注入固定业务正文。

initial dispatch、`result_correction` 和 `business_resume` 继续通过两个既有调用点消费同一个 `_task_result_reply_contract()`；communication 内的一个调用同时服务 correction 与 resume，没有复制三份文案。

## 4. 严格拒绝与零 mutation

新增测试在 `TemporaryDirectory` 中建立 initial dispatch 与 exact target，分别提交 scalar `evidence` 和 scalar `remaining`。两次均在 validator 阶段返回“必须是数组”，并逐项确认：

- StateStore 原始字节不变；
- result 文件集合与内容不变；
- dispatch/observation/result/closure 四平面不变；
- `identity_status`、`agent_id`、`canonical_task_path` 不变。

validator 还继续拒绝 scalar `attempted`/`options` 与空 `options`；合法 `evidence=[]`、`remaining=[]`、非空字符串数组、`attempted=[]` 和非空 `options` 正常。`complete`/`completed` 消歧、无 alias/no repair 边界保持不变。

## 5. 验证

| 门禁 | 结果 |
| --- | --- |
| 四项失败先行 | 4 tests：0 pass、4 failures |
| 同四项修复后 | 4/4 PASS |
| focused：parent result、communication lifecycle、Slice 4、semantic baseline | 118/118 PASS |
| `python3 -m unittest discover -s tests -v` | 440/440 PASS |
| `python3 -m py_compile scripts/subagent_governance.py` | PASS |
| Plugin validator | PASS |
| Skill validator | PASS |
| `scripts/release_preflight.py --mode development` | PASS |
| TaskResult Schema/runtime/renderer 类型来源审计 | PASS：15 字段、7 个基础必填、3 个场景、4 个业务枚举、2 个共享 renderer 调用点 |
| repository JSON parse | 15/15 PASS（包含隐藏仓库文件，排除 `.git`） |
| `git diff --check` | PASS |
| 全部未跟踪文件 whitespace | 67/67 PASS，0 issues |

## 6. 修改文件

- `scripts/subagent_governance.py`
- `tests/test_parent_result_channel.py`
- `tests/test_communication_lifecycle.py`
- `tests/test_semantic_baseline.py`
- `skills/subagent-governance/SKILL.md`
- `docs/redesign/platform-capability-slice-5-design.md`
- `docs/redesign/platform-capability-slice-5-implementation.md`
- `docs/redesign/platform-capability-slice-5-smoke-blocker-fix.md`

未修改 `schemas/task-result-v1.schema.json` 或 `schemas/governance-semantics.schema.json`；共享工作树中的既有 Schema diff 和其他历史修改均保留。

## 7. 准入结论

真实 smoke 唯一 blocker 已在 Slice 5 的 producer contract 内完成本地修复，严格 validator 与零 mutation 边界无回退。当前状态是 **可再次独立验收**；本报告不构成独立 GO，也不批准或替代新的真实 smoke。
