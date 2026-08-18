# 平台能力 Slice 5：正式结果词汇消歧实施记录

日期：2026-08-15

状态：**PASS**。开发仓库实现与本地门禁完成，可以开始新的独立验收对话；未部署、未更新 cachebuster、未写稳定源或运行缓存、未创建真实 Agent、未提交或推送。

## 1. 目标与边界

本 Slice 只在插件生成的 TaskResult 生产者指令和 invalid `business_result` 校验反馈中机械区分平台 terminal `completed` 与业务结果 `complete`。冻结规格为 `platform-capability-slice-5-design.md`。

实现保持：

- `business_result` 仍只有 `complete | blocked | failed | needs_decision`；
- 不接受 `completed` alias，不做 normalization 或 JSON repair；
- 不从 `list_agents`、summary、transcript、history、Hook 或 observation 生成正式结果；
- 业务结果仍只由父任务根据 current native child notification，以 exact sender 调用 `--record-child-result` 建立；
- correction/recovery/spawn budget、admission、状态转换、`fresh_until=null` 和 Stop advisory-only 均不变；
- 未修改 Schema、状态格式、CLI、Hook、字段、枚举或后台行为。

## 2. 失败先行

先只在现有 focused test 文件中新增 S5-T1 至 S5-T4，未修改 runtime，并精确运行四项。结果为：

| 检查 | 实现前 | 缺口 |
| --- | --- | --- |
| S5-T1 initial dispatch | FAIL | 缺少合法枚举与 `complete`/`completed` 对照 |
| S5-T2 result correction | FAIL | 共享回复契约未渲染消歧 |
| S5-T3 business resume | FAIL | 共享回复契约未渲染消歧 |
| S5-T4 validator feedback | FAIL | 仅返回“字段 business_result 枚举无效” |

失败先行数字：**4 tests，0 pass、4 failures**。最小实现后同四项为 **4/4 PASS**。

## 3. 最小实现

### Runtime

- `_business_result_values_text()` 直接读取 canonical machine definition `SEMANTIC_DEFINITIONS["business_result"]["enum"]`，保留机器源顺序；没有新增第二份业务枚举。
- `_task_result_reply_contract()` 增加同一枚举渲染和固定平面说明。initial dispatch 直接调用该 renderer；`render_communication_message()` 的 `result_correction` 与 `business_resume` 分支继续调用同一 renderer。
- `validate_task_result()` 对非法枚举从同一 helper 列出合法集合，并说明业务完成使用 `complete`、平台 terminal `completed` 不是业务结果。拒绝仍发生在 StateStore 与 result writer 之前。

### Skill 与能力契约

- Skill 在正式结果和 `result_correction` 义务处明确相同词汇边界，并重申不自动修复或从非正式 transport 推断结果。
- platform capability contract 记录 producer/feedback disambiguation，明确 Slice 5 不增加 authority。

## 4. S5-T5 至 S5-T11 不变量

| ID | 最终结果 | 证明 |
| --- | --- | --- |
| S5-T5 | PASS | invalid `completed` 返回 protocol error；StateStore 原始字节、result 文件集合、identity 字段和 dispatch/observation/result/closure 四平面逐项不变 |
| S5-T6 | PASS | exact sender 的合法 `complete` 正常 stored/read；canonical digest、pending acceptance 与 `accept_result` 语义不变 |
| S5-T7 | PASS | `complete|blocked|failed|needs_decision` 四种 outcome 与场景字段规则全部合法 |
| S5-T8 | PASS | exact terminal `completed` 只形成 terminal/result-gap；`business_result` 仍为 null，closure 未 closed 且无 tombstone |
| S5-T9 | PASS | summary、transcript 与 `last_assistant_message` 中的 TaskResult 文本为严格 no-op，StateStore 原始字节不变 |
| S5-T10 | PASS | invalid payload 不授权 correction；既有 exact terminal fact 才允许同 attempt correction；count 为 1，更正后的 `complete` 可记录。现有 focused 回归继续覆盖 PostTool success/unknown/failed 与两次预算 |
| S5-T11 | PASS | machine enum、runtime set、producer 顺序、feedback 顺序双向一致；`completed|Complete|COMPLETE` 均被拒绝 |

S5-T5 至 S5-T11 定向最终数字：**7/7 PASS**。

## 5. 验证数字

| 门禁 | 结果 |
| --- | --- |
| S5-T1 至 S5-T4 失败先行 | 4 tests：0 pass、4 failures |
| S5-T1 至 S5-T4 修复后 | 4/4 PASS |
| S5-T5 至 S5-T11 | 7/7 PASS |
| 设计第 10 节 focused | 117/117 PASS |
| `python3 -m unittest discover -s tests -v` | 439/439 PASS |
| runtime `py_compile` | PASS |
| Plugin validator | PASS |
| Skill validator | PASS |
| `release_preflight --mode development` | PASS |
| repository JSON parse | 15/15 PASS |
| machine enum/producer/feedback 双向来源审计 | PASS：machine/runtime/producer/feedback 各 4 值；3 producer 路径、2 shared-renderer callers；4 legal outcomes、3 invalid aliases |
| `git diff --check` | PASS |
| untracked UTF-8 文本 whitespace | 65/65 PASS，0 issues |

首次 untracked whitespace shell 探针因使用 zsh 特殊变量名 `path` 临时破坏命令查找，其 `text=0` 输出无效；已改用不修改 shell PATH 的独立 UTF-8/NUL 分类与 `git diff --no-index --check` 完整重跑。上表只记录最终有效结果。

## 6. 修改文件

- `scripts/subagent_governance.py`
- `tests/test_parent_result_channel.py`
- `tests/test_communication_lifecycle.py`
- `tests/test_semantic_baseline.py`
- `skills/subagent-governance/SKILL.md`
- `docs/redesign/platform-capability-contract-and-minimal-state-machine.md`
- `docs/redesign/platform-capability-slice-5-implementation.md`

未修改 Schema、README、D1-D6、旧实现/审查/smoke 报告或发布面。共享工作树中的其他既有修改全部保留。

## 7. Blocker、限制与后续

### Blocker

无。producer 与 validator feedback 均从现有 machine enum 派生，invalid payload 零 mutation，未扩大 authority。

### Known limitation

- 明确枚举只能降低首次词汇混淆，不能保证模型永不输出非法 payload。
- native terminal summary 仍不是正式结果 transport；平台 transport、Hook trust 与 provider 内部保持 opaque。
- Slice 4 有限 top-level `agents` adapter、`fresh_until=null` 和 Stop advisory-only 边界保持不变。

### Backlog

- active freshness、parent Stop hard gate、新 wrapper/status 形状与可能的显式 protocol-gap authority，仍需各自新的官方或真实证据与独立设计。
- 不在 Slice 5 重做旧 D6 S5/S6、F1-F13、diagnostics/group、replacement、duplicate、growth 或 rollback。

### Not_checked

- 真实 non-terminal/running `list_agents` observation；
- parent Stop advisory 的真实 Codex UI 展示、重入与退出；
- 独立 SubagentStart/SubagentStop identity、顺序与投递；
- provider restart、compact/resume、乱序 observation、内部日志面与跨版本 StateStore；
- 稳定源、运行缓存、Marketplace、Registry、发布包和真实 Slice 5 smoke。

## 8. 独立验收准入

结论：**可以开始独立验收**。验收必须在新的对话中重新建立 writer/producer/validator inventory，独立构造 S5-T1 至 S5-T11 并重跑全部门禁，不采信本报告的 PASS。

该准入不批准测试部署、cachebuster、真实 Agent、稳定发布、提交或推送。只有独立结论为 GO 后，才可由用户另行授权测试插件更新与新的真实 smoke。

## 9. 真实 smoke blocker 回修

原实施记录的 PASS 与后续独立 GO 只描述当时的本地证据。随后真实 smoke 首次 child 虽已使用合法 `business_result="complete"`，但把 `evidence`、`remaining` 输出为 scalar string；插件正确拒绝且零业务结果写入，因此真实 smoke 判定 **CORE FAIL**。本节追加回修事实，不覆盖前述历史数字或结论。

### 9.1 失败先行

在 runtime 未修改时先扩展四项现有 focused 用例，覆盖 initial、`result_correction`、`business_resume` 和 Schema/runtime/renderer parity。精确结果为：**4 tests，0 pass、4 failures**。四项分别证明基础类型与 JSON 示例缺失、两个通信路径缺少同源类型说明、共享类型 renderer 尚不存在。

### 9.2 最小实现

- `_task_result_field_json_type()` 是唯一 JSON 类型映射 helper；`_render_task_result_fields()` 只负责把该类型说明应用到字段列表。
- 基础/场景必填集合继续读取 `TASK_RESULT_BASE_REQUIRED_FIELDS` 与 `TASK_RESULT_SCENARIO_FIELDS`，业务枚举继续读取现有 machine semantics；没有另建可接受枚举。
- `_task_result_reply_contract()` 统一渲染基础字段、三个场景字段及一个最小 `complete` JSON 示例。initial 与 communication 的两个既有调用点不变，`result_correction`/`business_resume` 仍共用 communication 内的同一调用。
- validator 与 writer 未修改；scalar array 字段仍在任何 StateStore/result writer 之前被拒绝。
- Skill 只补充数组形状和最小项规则；两个 Schema 保持本 task delta 未修改。

### 9.3 回修验证

| 门禁 | 结果 |
| --- | --- |
| 四项失败先行 | 4 tests：0 pass、4 failures |
| 同四项修复后 | 4/4 PASS |
| focused 四模块 | 118/118 PASS |
| full unittest discover | 440/440 PASS |
| runtime `py_compile` | PASS |
| Plugin validator | PASS |
| Skill validator | PASS |
| development preflight | PASS |
| TaskResult Schema/runtime/renderer 类型审计 | PASS：15 字段、7 个基础必填、3 个场景、4 个业务枚举、2 个 renderer 调用点 |

最终 whitespace、完整 JSON 扫描与 diff 检查见 `platform-capability-slice-5-smoke-blocker-fix.md`；本回修完成后只可再次进入新的独立验收，不在本对话启动独立验收或真实 smoke。
