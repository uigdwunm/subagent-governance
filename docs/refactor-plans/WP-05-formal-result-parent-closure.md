# WP-05 正式结果与父任务闭环详细改造方案

## 一、状态、唯一目标与权威边界

- 工作包：WP-05「正式结果与父任务闭环」。
- 权威来源：`docs/project-function-inventory.md`，重点是 U-01～U-10、SG-F06、第十三节职责越界清单、终态链、第十六～十八节。
- 前置依赖：WP-01 的 `TaskResult`/validator/机器语义；WP-02 的稳定锁、CAS、原子替换、回读验证和精确 tombstone 底层能力；WP-03 的 `task_id + attempt + task_ref` 与精确 Agent 映射；WP-04 的 `result_correction`、`business_resume`、interrupt 三态和 `last_lifecycle_operation`。
- 唯一目标：按 `task_id + attempt` 建立唯一权威结构化结果文件，完成固定提交顺序、幂等/冲突/迟到保护、有限纠正衔接、complete 父验收，以及 `accept_result | reject_result | close_task | select_attempt` 的显式父处置入口，使父任务能基于持久化事实闭环。
- 当前状态：详细方案已先行创建；实施完成后在本文末尾同步实际结果、验证证据、`not_checked`、退出结论和 WP-06 交接。

本阶段不从自由文本、mailbox 文案、summary、工具响应文字或 lifecycle observation 推断业务结果；不建立 PreparedResult、候选结果库、revision、随机 result ID、事件历史或第二套编排平台。

## 二、修改前可复现基线与缺口

### 2.1 已执行基线

修改前执行：

```text
python3 -m unittest discover -s tests -v
  217 tests, OK
```

该结果证明 WP-01～WP-04 当前主路径稳定，但不证明 WP-05 已存在。

### 2.2 当前代码事实

1. `TaskResult`、`validate_task_result()` 和结果 Schema 已存在，但没有运行时正式提交消费者。
2. `_handle_subagent_stop()` 对 managed task 只返回“将在 WP-05 接管”的占位提示，不读取或保存结构化结果，也不更新多维结果状态。
3. `results/` 目录、确定性安全结果地址、私有权限、原子写入、回读验证和精确读取入口均不存在。
4. 没有“结果文件先可靠存在、StateStore 后关联”的提交路径，也没有孤立文件的精确重关联入口。
5. 同内容重放、不同内容冲突、冲突摘要、迟到旧 attempt 归属和中断后拒绝均没有实现。
6. `complete` 尚不能进入 `pending + accept_result`，也没有 accept/reject/close/select 的原子父处置入口。
7. managed Stop 没有在无合法结果时写 `needs_correction` 或 `exhausted`，无法与 WP-04 的 `correction_count` 和 result-correction lifecycle 闭环。
8. legacy `_legacy_terminal_errors()`、`_legacy_reported_status()` 和内嵌 `result_document` 仍有 legacy 测试消费者；它们不是正式结果来源，但本阶段不能在未保留 legacy 兼容消费者时先删除。

### 2.3 运行时代码修改前的失败基线

新增 `tests/test_formal_result_parent_closure.py` 后，先运行定向测试并确认至少以下目标稳定失败：

- 不存在安全确定性 result 路径和原子存储。
- managed SubagentStop 不消费 `task_result`，也不产生 needs-correction/exhausted。
- complete/blocked/failed/needs-decision 不会写入精确状态组合。
- 同内容重放、不同内容冲突、孤立文件重关联和精确读取不存在。
- accept/reject/close/select 接口不存在。

这些失败只针对 WP-05 缺口，不提前要求 WP-06 的等待/Session/Stop 完整改造。

实际失败基线：新增 10 项定向测试后首次执行得到 `10 tests / 9 errors / 1 failure`。错误均为正式结果路径、提交/读取/重关联、父处置异常或入口尚不存在；唯一 failure 为 managed `SubagentStop` 未写 `needs_correction`。该失败基线在运行时代码修改前确认。

## 三、允许与禁止范围

### 3.1 允许修改

- `scripts/subagent_governance.py` 的正式结果文件辅助、提交/读取/重关联、managed SubagentStop、父处置与 CLI。
- `schemas/governance-semantics.schema.json` 中 WP-05 状态字段、引用字段、父处置和有界输入的机器锚点；`task-result-v1.schema.json` 只在当前字段机械边界确有缺口时调整。
- `skills/subagent-governance/SKILL.md` 与 `references/runtime-boundaries.md` 中已落地的正式提交、读取和父验收入口。
- `tests/test_formal_result_parent_closure.py` 及直接冲突的 legacy/fixture/结构测试。
- `hooks/hooks.json` 仅在现有 SubagentStop 接线不够时调整；当前已有接线，原则上不改。
- 本方案文档。

### 3.2 明确禁止

- 不实现 WP-06 的20分钟父等待工作流、Stop 三次读取、SessionStart/End 完整 action-required 视图、选择后自动中断/关闭运行 attempt、整 Session tombstone 生命周期或后台清理器。
- 不实现 WP-07 诊断/group，不执行 WP-08 全面旧路径退役、发布、安装或真实平台操作。
- 不新增 PreparedResultStore、候选结果文件、revision、随机 result ID、提交历史、审计日志或复杂事务数据库。
- 不从自然语言结果卡、`last_assistant_message`、工具响应、mailbox 或 lifecycle call observation 生成 `business_result`。
- 不修改稳定发布源、Marketplace、运行缓存、Hook trust、Registry；不 stage、commit 或 push。

## 四、结果地址、编码与最小存储

### 4.1 数据根

正式结果位于 governance data 根的 `results/` 私有目录，与 `sessions/`、`prepared/` 同级。目录必须是当前用户拥有的普通目录，权限固定 `0700`，拒绝符号链接和所有者异常。

### 4.2 确定性安全文件名

不得直接把任意 `task_id` 拼接为路径。文件名固定为：

```text
result-<sha256(UTF-8 task_id)>-attempt-<attempt>.json
```

- SHA-256 使用64位小写十六进制，避免 `/`、`..`、Unicode 分隔符和超长 task ID 产生路径穿越或文件名问题。
- attempt 必须是正整数并以十进制写入。
- 文件内部仍完整保存原始 `task_id` 和 `attempt`，每次读取都重新核对，摘要碰撞或路径错误不能静默通过。
- StateStore 只保存相对 `result_reference`、`result_sha256`、结果时间和状态；不复制 `result`、`evidence[]`、`remaining[]` 或场景正文。

### 4.3 原子写与回读

- 在 `results/` 同目录创建随机临时普通文件，设置 `0600`。
- 使用稳定 canonical JSON：UTF-8、`ensure_ascii=false`、键排序、固定分隔符和尾换行；SHA-256 对实际写入字节计算。
- 写完整内容、flush、文件 fsync、`os.replace()`、目录 fsync。
- 通过安全读取路径重新读取；核对普通文件、所有者、权限、大小、UTF-8 JSON、`validate_task_result()`、task/attempt 和完整 canonical 内容。
- 任一步失败都不得宣称正式结果可靠存在。

## 五、SubagentStop 的可观察边界与 CLI/Hook 接口

### 5.1 当前可观察事实

当前仓库 fixture 和运行时只稳定使用 `last_assistant_message`；真实 Codex `SubagentStop` 是否提供任意结构化扩展字段尚无平台证据。Hook 配置能把整个事件 JSON 交给脚本，但本地测试不能证明平台会传递自定义 `task_result`。

### 5.2 本阶段明确接口

提供两个不互相猜测的入口：

1. Hook：仅当 SubagentStop payload 显式包含对象字段 `task_result` 时，把它作为结构化提交；不从其他字段或文本推断。
2. CLI：`--submit-result --session <session_id> --agent-target <agent_id|canonical_path>`，从 stdin 读取 TaskResult JSON，直接调用同一提交函数。该入口适合生成器或子 Agent在 Stop 前显式保存结果，也用于本地/人工原样重试合法结果。

另提供：

- `--read-result --session ... --task-id ... --attempt ...`：精确读取并重新机械校验正式结果。
- `--reassociate-result --session ... --task-id ... --attempt ...`：对已写成功但 StateStore 未关联的孤立文件执行精确、安全、幂等重关联。
- `--parent-disposition --session ...`：从 stdin 接收父处置对象并执行。

真实平台是否能让子 Agent直接调用该 CLI、SubagentStop 是否暴露 `task_result`、以及消息/summary 如何展示均保持 `not_checked`。

## 六、managed 与 legacy/unmanaged 分流

- 精确 Agent 映射到 managed `task_id + attempt`：进入 WP-05 正式结果状态机。
- Agent 映射缺失、unmanaged 或 legacy 记录：保持现有兼容放行；不得创建半套结果状态或要求 TaskResult。
- legacy `_legacy_terminal_errors()`、`_legacy_reported_status()` 和内嵌 `result_document` 在本阶段继续只服务 legacy 记录；managed 路径不再经过它们。
- managed 路径取得新消费者后，旧路径的全面删除留给 WP-08；本阶段只原子隔离，不先删 legacy 保护。

## 七、TaskResult 校验与固定提交状态机

### 7.1 机械校验

提交入口只执行：

- `validate_task_result()` 的字段、类型、长度、枚举和基本组合。
- `task_id + attempt` 精确引用。
- Agent ID/canonical path 对该 attempt 的精确映射；结果纠正的合法迟到结果可通过同 attempt 映射确认。
- 当前 attempt 未关闭，且不是已确认成功中断后到达。
- 已有权威结果、冲突和当前状态的锁内资格复核。

不判断结果真实性、证据充分性、建议正确性、文本长度“是否够”、关键词或中文卡片格式。

### 7.2 固定顺序

所有提交在 StateStore Session 稳定锁/CAS 语义下完成：

1. 精确定位 managed task、attempt 与 Agent身份。
2. 再次机械校验 TaskResult 及引用。
3. 原子写正式 result 文件。
4. 重新读取并校验文件内容。
5. 把 StateStore 关联到结果，写 `result_protocol_status=valid`、`result_storage_status=available`、`business_result`、`acceptance_status`、`parent_action` 和引用摘要。
6. 消费匹配的 result-correction pending/last lifecycle。
7. StateStore 原子替换并回读验证。

StateStore 更新失败时保留已经写入的结果文件，不删除、不覆盖。之后使用精确重关联入口恢复。

### 7.3 存储失败

合法结果的文件写入、读取或 StateStore 关联失败时：

- 尽力用独立可靠 StateStore 转换写 `execution_status=stopped`、`result_protocol_status=valid`、`result_storage_status=unavailable`、`business_result=null`、`acceptance_status=null`、`parent_action=manual_review`。
- `health` 记录有界的 result storage degraded 事实。
- 不增加 `correction_count`，不发送 result correction，不恢复 Agent。
- 若 StateStore 本身也不可写，只返回明确 degraded 失败，不声称上述状态已可靠记录。
- 已存在的合法孤立文件保留，后续重关联只读取原文件，不从自然语言重建。

### 7.4 业务结果到状态组合

| business_result | execution_status | result_protocol_status | result_storage_status | acceptance_status | parent_action |
| --- | --- | --- | --- | --- | --- |
| complete | stopped | valid | available | pending | accept_result |
| blocked | stopped | valid | available | null | decide_disposition |
| failed | stopped | valid | available | null | decide_disposition |
| needs_decision | stopped | valid | available | null | ask_user |

`suggested_parent_next_step` 不覆盖该表。

## 八、无合法结果与有限纠正衔接

managed SubagentStop 没有 `task_result`，或提交对象未通过机械校验时：

- 写 `execution_status=stopped`、`business_result=null`、`acceptance_status=null`。
- `correction_count < 2`：`result_protocol_status=needs_correction + parent_action=correct_result`。
- `correction_count >= 2`：`result_protocol_status=exhausted + parent_action=manual_review`。
- 消费本次已经结束的 result-correction pending/last lifecycle，避免同一停止事实继续授权 running。
- 格式错误只要求补交结构化结果，不重做业务；实际 follow-up 由 WP-04 `prepare_communication(operation_type=result_correction)` 执行。
- `exhausted` 仍允许同一 Agent/attempt 的合法迟到结果；成功后改为 valid/available，纠正计数不回退。

结果存储失败不进入本链，也不消耗补交次数。

## 九、幂等、冲突与迟到结果

### 9.1 幂等

- 同一 task/attempt、canonical 内容相同、SHA-256 相同的重放返回已有正式结果事实。
- 不重复改变 correction/recovery/spawn 计数，不把 accepted/rejected 改回 pending，不覆盖 close 或 parent disposition。
- 如果文件已存在但 StateStore 为 unavailable/null，幂等提交可直接执行精确重关联。

### 9.2 冲突

- 文件已存在合法 A，收到内容不同合法 B：绝不覆盖 A，不写第二份完整结果。
- StateStore 保持 A 的 `business_result`、valid、available 和 acceptance。
- 写 `result_conflict=true`、`result_conflict_sha256=<B摘要>`、`result_conflict_first_seen_at=<首次时间>`、`parent_action=manual_review`。
- 相同 B 重放保持首次时间和单个摘要，不增加历史。
- 已存在另一个不同冲突摘要时仍不建立历史；保留首次已记录冲突事实并报告需要人工检查。

### 9.3 迟到与多 attempt

- 精确按提交的 task/attempt 和 Agent映射写入原 attempt；不使用 current attempt、最大编号、最近时间或同名推断。
- 非 current attempt 的结果保存在自己的地址，不覆盖 current attempt。
- 旧 unknown attempt 迟到结果与其他未关闭 attempt 并存时，只记录 `duplicate_execution=true + parent_action=resolve_duplicate`，不自动中断、不自动选择。
- `duplicate_not_selected` attempt 的结果可保留为参考，但不自动进入 current task 验收。
- 成功中断后才到达的结果拒绝；中断前已经 available 的结果保持不变。

## 十、结果读取与孤立文件重关联

### 10.1 精确读取

`read_task_result(session_id, task_id, attempt)`：

- 读取 StateStore 精确 attempt 的 `result_reference/result_sha256`。
- 安全读取确定性结果文件，重新执行 TaskResult validator、task/attempt 和 SHA-256 核对。
- 只在 `result_protocol_status=valid + result_storage_status=available` 且引用一致时返回。
- 不返回或生成 acceptance/protocol/storage/disposition 到结果文件。

### 10.2 重关联

`reassociate_task_result()`：

- 在同一 StateStore 稳定锁内精确读取确定性路径。
- 重新校验文件、task/attempt、Agent/关闭/中断资格和冲突。
- 现有 StateStore 没有权威结果且文件合法时，补写与普通提交相同的 valid/available/业务/验收/父动作。
- 已有关联同内容时幂等；已有不同权威结果时按冲突处理。
- 不扫描目录猜测 task，不批量修复，不覆盖文件。

## 十一、父任务显式验收与处置

### 11.1 输入

统一输入：

```text
task_id
attempt
action=accept_result|reject_result|close_task|select_attempt
reason
```

`reason` 必须是有界非空字符串。函数和 CLI 均不从自然语言推断 action。

### 11.2 通用原子边界

- 使用 StateStore 稳定锁、expected current attempt compare-and-set、原子替换和回读验证。
- `accept_result/reject_result/close_task` 的 attempt 必须等于实际 current attempt；不一致返回实际值并拒绝。
- `select_attempt` 可以选择非 current，但必须属于同 task 且确有 `duplicate_execution=true`。
- `parent_disposition` 记录已经作出的 action；`parent_action` 只表示下一步。
- 所有成功处置记录 `parent_disposition`、有界 reason 和时间。
- result conflict 的标记、摘要和时间在 accept/reject/close 的同一锁内清除；新 attempt 创建时也清除旧 attempt 冲突。

### 11.3 accept_result

- 仅 current attempt 为 complete、valid/available、acceptance pending 且无 duplicate execution 时允许。
- 复用整 task 关闭检查：枚举 current 与 `prior_attempts` 的全部未关闭 attempt；存在 confirmed running attempt 时拒绝并返回全部精确中断 target，不写 accepted。
- 全部非运行 attempt 在同一事务中明确关闭并生成7天 tombstone；只有 current complete attempt 写 accepted。
- 同一事务清 `parent_action`、写 parent disposition 并回读；不得出现 accepted 但 task 未可靠关闭。

### 11.4 reject_result

- 仅 current complete + pending、无 duplicate execution时允许。
- 保留权威结果文件，写 rejected、`parent_action=decide_disposition` 和 parent disposition。
- 不自动创建新 attempt或关闭 task。

### 11.5 close_task

- 表示父 Agent或用户明确放弃、接受失败/阻塞、解决决策或完成其他处置。
- attempt 是 expected current attempt；成功范围是整个 task 的全部未关闭 attempt。
- 任一 confirmed running attempt 存在时拒绝并返回精确中断 target；本入口不调用 interrupt。
- 其余 stopped/interrupted/identity-unconfirmed/duplicate-not-selected attempt 全部关闭并各自生成 tombstone，保留各自结果到7天清理。
- 清 task 的 parent action 和冲突事实；不编造或覆盖业务结果。

### 11.6 select_attempt

- 仅在存在重复执行时允许，绝不自动选择。
- 同一锁内把传入 attempt 切换为 current，将原 current 快照放入 prior attempts，并把所有未选未关闭 attempt 标记 `duplicate_not_selected` 与选择关闭意图。
- 非运行未选 attempt 立即关闭并 tombstone；运行未选 attempt 保持未关闭并返回精确中断 target。
- 不自动接受所选结果，不自动调用 interrupt，不覆盖任一结果。
- 只有所有未选 attempt 已关闭时清除 `duplicate_execution`；运行未选的后续中断/关闭执行处置留给 WP-06。

## 十二、旧路径接管与退役边界

### 12.1 本阶段接管

- managed `_handle_subagent_stop()` 由 WP-05 正式结果消费者接管。
- managed 结果不再写内嵌 `result_document`，不调用 `_legacy_reported_status()`，不从自由文本生成 business result。
- 正式结果、无结果纠正、存储降级和 interrupt-after-result 资格全部走多维状态。

### 12.2 保留到 WP-08

- `_legacy_terminal_errors()`、`_legacy_reported_status()` 和 legacy `result_document` 继续供显式 legacy task 测试/兼容分支使用。
- legacy `status/retry_count/protocol_error` 的全面退役必须等 WP-06/08 新 Stop/Session 消费者完成后原子删除。
- `_active_records()`、legacy Session/Stop/diagnose 仍由 WP-06/07/08 接管；本阶段只确保 managed WP-05 状态能进入现有 `_managed_action_required_records()`。

不得先删除这些保护再留下无消费者；也不得让 legacy 自由文本重新成为 managed 正式结果来源。

## 十三、测试优先顺序

### 13.1 第一批失败测试

新增 `tests/test_formal_result_parent_closure.py`，先覆盖：

1. 安全确定性路径与路径穿越 task ID。
2. complete 提交顺序和状态组合。
3. blocked/failed/needs-decision 状态组合。
4. SubagentStop 无结果、非法结果、两次纠正耗尽。
5. 文件写/回读/StateStore 关联失败与孤立文件重关联。
6. 同内容幂等、不同内容冲突和相同冲突重放。
7. 迟到旧 attempt、纠正耗尽后合法迟到、成功中断后拒绝。
8. read-result 重新校验。
9. accept/reject/close/select 的前置条件、CAS、运行 target 返回、tombstone 和回读。

运行并记录失败后才修改运行时代码。

### 13.2 回归调整

- 将 `tests/test_governance.py` 中 managed SubagentStop 占位断言切换到 WP-05；legacy 测试继续保留。
- 更新 `test_semantic_baseline.py`、`test_plugin_structure.py` 的机器锚点和自然语言边界。
- 必要时增加 Hook fixture 的 structured result 本地形状，但明确 fixture 不证明真实平台字段。

## 十四、文件级实施步骤

1. 先创建本文并锁定全部状态、存储、失败和交接边界。
2. 新增 WP-05 定向测试，运行并记录稳定失败。
3. 在机器语义源补充结果引用/冲突/父处置有界字段锚点，不改变 TaskResult 基础字段和业务枚举。
4. 在运行时增加确定性结果路径、私有目录、安全读写、canonical hash 和原子回读函数。
5. 实现 `submit_task_result()`、`read_task_result()`、`reassociate_task_result()` 和存储失败降级。
6. 原子替换 managed `_handle_subagent_stop()`；保留 legacy 分支。
7. 实现 `apply_parent_disposition()` 与 CLI；复用最小 attempt 枚举、关闭/tombstone 和 current attempt 切换辅助。
8. 在 WP-04 business resume 新 attempt 创建的同一锁内清除旧 result conflict。
9. 更新 Skill/runtime boundaries 与一致性测试。
10. 运行定向、全量、编译、Plugin/Skill validator、Schema/fixture 校验和 `git diff --check`。
11. 回填本文实施结果、验证、`not_checked`、退出结论和 WP-06 交接。

## 十五、最低验证

```text
python3 -m unittest -v tests.test_formal_result_parent_closure
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
python3 $HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 $HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
3 个 Schema 与相关 fixture 的 JSON 解析、相对 $ref、JSON Pointer、正则和关键语义锚点校验
git diff --check
```

不得把未运行检查写为通过。

## 十六、退出条件

WP-05 只有同时满足以下条件才退出：

1. 方案与实际实施同步。
2. task/attempt 只有一个安全确定性权威结果文件，完整正文不进入 StateStore。
3. 提交顺序固定为文件原子写/回读后再关联 StateStore，关联失败保留孤立文件并可精确重关联。
4. 四种 business result 使用确认的精确状态组合；complete 不自动 accepted。
5. 无合法结果与 correction_count 正确衔接，存储故障不伪装成协议错误。
6. 同内容重放幂等，不同内容不覆盖并只保存冲突摘要/首次时间。
7. 迟到结果精确归属，成功中断后结果拒绝，纠正耗尽后合法迟到仍可接收。
8. read-result 重新机械校验，accept/reject/close/select 为显式、原子、可回读入口。
9. legacy 自由文本只留在 legacy 分支，managed 路径不再推断业务结果。
10. 未提前实现 WP-06～WP-08；全部适用本地验证通过，真实平台项如实 `not_checked`。

## 十七、not_checked

仓库内无法证明：

- 真实 Codex SubagentStop 是否暴露自定义 `task_result` 对象及其事件顺序。
- 子 Agent在真实运行环境中是否能稳定调用 `--submit-result`，以及 session/Agent target 如何由平台注入。
- 原生最终回复、mailbox、summary 与已经保存的正式结果之间的真实展示顺序。
- PostToolUse 缺失、SubagentStart 迟到、结果先于启动、中断与结果竞态的真实平台顺序。
- compact/resume 后父 Agent是否稳定调用 read-result/parent-disposition。
- Hook trust、Plugin/Skill 实际加载、运行缓存与用户可见提示。

本地 fixture 只证明接口和状态机，不把这些平台行为宣称为已通过。

## 十八、明确不在 WP-05 处理的后续事项

### WP-06

- action-required/recent-activity 完整派生视图。
- 父 Agent 20分钟等待/巡检工作流和 Stop 三次读取。
- SessionStart/End 完整恢复与清理。
- select_attempt 后运行未选 Agent的显式中断、成功关闭、failed/unknown 对账和 duplicate_execution 最终清除。
- 整 task/Session tombstone 生命周期、到期结果清理和空 session 删除。
- 多 attempt 新 spawn/替代执行的完整父任务编排。

### WP-07

- 无副作用规范化诊断、结果引用诊断和轻量 group。

### WP-08

- legacy `status`、`result_document`、`_legacy_*`、旧 Stop/Session/diagnose 的全面原子退役。
- README/发布流程总收口、稳定发布、安装、缓存与真实平台验收。

## 十九、WP-06 交接目标

WP-05 计划向 WP-06 提供：

- 安全确定性结果地址及原子读写/回读函数。
- `submit_task_result()`、`read_task_result()`、`reassociate_task_result()`。
- 每 attempt 的 result reference/hash、protocol/storage/business/acceptance/conflict 状态。
- `apply_parent_disposition()` 的 accept/reject/close/select 原子事实和运行中 target 返回。
- 7天 tombstone 的最小创建事实，但不接管到期清理编排。
- managed SubagentStop 的 needs-correction/exhausted/valid 主路径。

WP-06 必须在这些持久事实之上完成等待、Session/Stop、多 attempt选择后的运行处置和整 Session 生命周期；不得重新从自由文本生成结果、自动选择 attempt 或覆盖现有 result 文件。

## 二十、实施结果与交接

### 20.1 实际修改

本阶段只修改开发仓库内以下直接相关文件：

- `scripts/subagent_governance.py`
  - 新增 `ResultSubmissionError`、`ResultStorageError`、`ParentDispositionError` 和带 `interrupt_targets/current_attempt` 的 `ParentDispositionConflict`。
  - 新增安全确定性 `result_file_path()`、私有 results 目录、每结果稳定锁、canonical JSON、原子写、文件/目录 fsync、安全回读、权限/所有者/大小/Schema/引用/hash 校验。
  - 新增 `submit_task_result()`、`read_task_result()`、`reassociate_task_result()`。
  - 提交在 StateStore session 稳定锁内先写并回读结果文件，再关联状态；StateStore 写入失败时孤立文件保留，并以独立状态转换记录 `valid + unavailable + manual_review`。如果状态故障本身也无法写入则显式失败，不宣称已保存。
  - 同内容重放保持幂等，包括结果已经 accepted/关闭后的相同内容重放；不同合法结果保留 A，只保存 B 的 SHA-256 和首次时间。
  - managed `SubagentStop` 只消费显式对象 `task_result`；缺失/非法结果按 correction budget 写 needs-correction 或 exhausted，并消费匹配的 result-correction lifecycle。
  - 迟到结果按 Agent 精确映射写入原 attempt；与其他未关闭 attempt 并存时只写 duplicate/resolve-duplicate 事实。
  - 新增 `apply_parent_disposition()`，实现 accept/reject/close/select 的 expected-current、运行 target 返回、整 task 非运行关闭、逐 attempt tombstone、current attempt 原子切换和回读验证。
  - business resume 创建新 attempt 时在同一锁内清除旧 attempt 的 result conflict。
  - 新增 `--submit-result`、`--read-result`、`--reassociate-result`、`--parent-disposition` CLI。
- `schemas/governance-semantics.schema.json`
  - 增加正式结果状态字段、结果目录/文件名/canonical/hash 机器锚点、父处置输入字段和 reason 上限；未改变 TaskResult 基础字段、业务枚举或版本兼容规则。
- `tests/test_formal_result_parent_closure.py`
  - 新增 18 项定向测试，覆盖安全路径与权限、四种业务状态、Stop 协议纠正、文件/关联失败、孤立重关联、并发幂等、冲突、迟到、中断、读取复验、CLI 和四种父处置边界。
- `skills/subagent-governance/SKILL.md`
  - 将 WP-01 占位边界更新为已落地的结果与父处置工作流，并明确真实平台 `task_result` 字段仍未验证。
- `skills/subagent-governance/references/runtime-boundaries.md`
  - 记录 WP-05 已实现能力以及 WP-06 仍负责的等待、选择后运行处置和 Session/Stop 闭环。
- 本方案文档。

`hooks/hooks.json` 已有完整 `SubagentStop` 接线，不需要修改。`schemas/task-result-v1.schema.json` 与 `schemas/task-contract-v1.schema.json` 的既有机械协议已满足 WP-05，不为本阶段增加版本门禁或治理状态字段。legacy `_legacy_terminal_errors()`、`_legacy_reported_status()` 和 `result_document` 未删除，继续只服务 legacy/unmanaged 兼容分支。

### 20.2 验证证据

- 修改前全量基线：`python3 -m unittest discover -s tests -v` → `217 tests, OK`。
- 运行时代码修改前定向失败：`python3 -m unittest -v tests.test_formal_result_parent_closure` → `10 tests / 9 errors / 1 failure`。
- 最终定向：`python3 -m unittest -v tests.test_formal_result_parent_closure` → `18 tests, OK`。
- 最终全量：`python3 -m unittest discover -s tests -v` → `235 tests, OK`。
- 编译：`python3 -m py_compile scripts/subagent_governance.py` → exit 0。
- Plugin validator：`python3 $HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .` → `Plugin validation passed`。
- Skill validator：`python3 $HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance` → `Skill is valid!`。
- Schema/fixture 相关验证：全量中的 semantic baseline、plugin structure 和 hook fixture 均通过；额外确定性脚本解析3个 Schema、解析35个相对 `$ref`/JSON Pointer、编译10个正则并核对 WP-05 结果存储/父处置锚点，exit 0。
- `git diff --check` → exit 0。

验证期间出现两次仅由自然语言契约精确短语变化导致的既有测试失败，已通过保留原语义锚点修复；未改变产品裁决。最终结果以上述全绿命令为准。

### 20.3 not_checked

- 真实 Codex `SubagentStop` 是否会提供自定义 `task_result` 对象、字段是否在 Hook 前被过滤，以及真实事件顺序。
- 子 Agent在真实执行环境中能否获得正确 session/Agent target 并稳定调用 `--submit-result`。
- 真实 Hook trust、Plugin/Skill 加载、provider 消息加密、mailbox/summary 展示和 compact/resume 后父 Agent读取行为。
- 真实平台中的结果先于 `SubagentStart`、中断与提交竞态、PostToolUse 缺失等顺序；本地状态机和 fixture 已覆盖可构造形状，但不能替代平台验收。
- 未执行发布、安装、稳定源/运行缓存/hash 对账或 Marketplace/Registry 操作，符合本阶段禁止范围。

### 20.4 退出结论

WP-05 退出条件已满足：正式结果具有唯一安全确定性地址和完整读取入口；文件写/回读先于状态关联；存储故障、协议错误、业务结果和父验收已分层；同内容幂等、不同内容冲突、迟到结果和成功中断边界已固化；complete 只进入 pending，父 Agent必须显式 accept/reject；close/select 不自动调用原生中断；legacy 自由文本不再进入 managed 正式结果路径。

未发现当前代码事实与 `docs/project-function-inventory.md` 的已确认产品裁决存在无法兼容的实质冲突。

### 20.5 WP-06 交接

稳定接口：

- `submit_task_result(value, session_id, agent_target=..., state_store=..., results_root=...)`
- `read_task_result(session_id, task_id, attempt, ...)`
- `reassociate_task_result(session_id, task_id, attempt, ...)`
- `apply_parent_disposition({task_id, attempt, action, reason}, session_id, ...)`
- CLI：`--submit-result`、`--read-result`、`--reassociate-result`、`--parent-disposition`
- StateStore：`result_reference/result_sha256/result_stored_at`、protocol/storage/business/acceptance/conflict、`parent_disposition*`、`duplicate_execution/duplicate_not_selected`、逐 attempt close/tombstone。

临时兼容桥：

- managed `SubagentStop.task_result` 是本地明确接口，但真实平台可观察性仍 `not_checked`；CLI 是显式提交和重试路径。
- legacy `_legacy_*` 与内嵌 `result_document` 仍只服务旧记录，必须留到 WP-08 与其最后消费者一起原子退役。

WP-06 必须处理：

- 从 `parent_action != null`、运行/claimed 调用和关闭事实派生完整 action-required/recent-activity 视图。
- 20分钟等待巡检、Stop 三次读取、SessionStart/End 恢复与清理。
- `select_attempt` 返回运行中未选 targets 后的显式 interrupt、success 后依据已保存选择意图关闭/tombstone、failed/unknown 对账，以及全部未选关闭后清 duplicate。
- 整 task/Session tombstone 到期、精确正式结果清理和空 session 删除。
- 不重新从自由文本生成业务结果，不自动选择 attempt，不覆盖 WP-05 权威结果文件。
