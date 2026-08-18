# 平台能力重设计 Slice 3 第三轮独立复验

> **状态：已撤销并被替代。** 本文审查的是已退役的 bearer credential / child submit 方案，其 `GO` 不再有效，不得据此部署或测试旧结果通道。当前方案与准入状态以 `platform-capability-slice-3-parent-authority-redesign.md` 和 `platform-capability-slice-3-implementation.md` 为准；本文只保留为历史证据。

日期：2026-08-14

结论：**GO（仅限 Slice 3 测试 cachebuster 与新建真实 smoke）**。第二轮唯一 blocker 已关闭：同一 spawn claim 已有 exact-bound canonical active 或 terminal 正向事实时，迟到的同 `tool_use_id` reliable `failed` 现在保留 credential、ObservationRecord、identity 和 terminal 事实，把 dispatch 记为 indeterminate，并进入 `reconcile`。本轮未发现新的本地 blocker。

该 GO 不等于稳定发布批准，不证明平台内部不会记录 `updatedInput` 或最终 prompt，也不授权 Slice 4。可以在后续明确任务中执行测试 cachebuster，并按项目流程新建独立真实任务验证 Slice 3 child submit/parent relay；真实 smoke 未完成前仍不得宣称平台闭环通过。

## 1. 范围与方法

本轮重新阅读最新实施说明、主设计的 ResultCredential/显式结果协议/测试门禁、第二轮报告、当前 runtime/Schema/CLI/generator/Skill/tests 与共享工作树 diff。所有动态反例使用新建临时目录和隔离 StateStore/results root；未读取、修改或删除 smoke StateStore。

本轮不采信实施报告或新增单元测试的 PASS 声明。结论来自独立构造的事件顺序矩阵、存储与 claim 故障注入、credential/TaskResult/replay/migration 反例、静态 writer/reader/secret inventory、focused/full tests 与发布前本地门禁。除本报告外未修改实现、Schema、tests、fixtures 或既有文档；未部署、安装、同步、发布、提交、推送、创建真实任务或启动 Slice 4。

## 2. 第三轮目标矩阵

### 2.1 第二轮 blocker 重放

| 场景 | 独立结果 |
| --- | --- |
| exact canonical active + 同 `tool_use_id` 迟到 failed | credential 保持 `issued`；dispatch 为 `indeterminate`/兼容投影 `unknown`；`parent_action=reconcile`；原 ObservationRecord canonical JSON 逐字节相等；`identity_status=confirmed`、`execution_status=running` 保持；Schema 0 errors |
| exact canonical terminal + 同 `tool_use_id` 迟到 failed | credential 保持 `issued`；dispatch 为 `indeterminate`；`parent_action=reconcile`；原 ObservationRecord（含 terminal status/source/time）逐字节相等；confirmed/stopped 保持；Schema 0 errors |
| unbound Start | 不触发保护；reliable failed 撤销 exact credential并进入 `retry_spawn` |
| legacy `execution_status=running` only | 不触发保护；撤销 exact credential |
| alias/active index only | 不触发保护；撤销 exact credential |
| 唯一 candidate only | 不触发保护；撤销 exact credential |
| 真正 reliable no-Start failed | 撤销 exact credential；旧 bearer submit 被拒绝；ResultRecord 保持 `missing` 且没有结果文件 |
| unknown/indeterminate | credential 保持 `issued`，进入 `reconcile`，不误撤销 |
| 迟到旧 PostTool / 新 retry generation | old 保持 revoked，new 保持 issued，当前 `spawn_tool_use_id` 不变，Schema 0 errors |

独立顺序矩阵 **9/9 PASS**。

`_has_canonical_positive_execution_evidence()` 只调用 `_observation_has_exact_dispatch_target()`，要求 DispatchRecord 的 `dispatch_target` 与 ObservationRecord 的 subject、bound task、bound attempt 和 `binding_basis=exact_dispatch_target` 全部精确一致，再接受白名单 active/terminal source 与有效时间。它不读取 agents index、唯一候选、legacy running、credential 或 bearer，也不写 identity。`_handle_subagent_start()` 当前只返回 unbound advisory context；文件中旧 transcript/Start identity helper 无调用者，因此本次 predicate 修复没有恢复 Start identity authority。

### 2.2 retry/replacement 与 correction/resume guard

- retry 与 replacement reliable failure 只撤销本次 claim 的 exact generation；replacement 不撤销来源 generation。
- correction/resume 独立矩阵 **4/4 PASS**：两类操作在无 operation-scoped Start 时 reliable failed 撤销 exact generation；存在本次 pending 的 `start_observed_at` 时保持 issued并 `reconcile`。
- correction/resume 继续读取 operation-scoped pending Start，而不是把旧 terminal、credential possession 或全局 Start 当作消息投递证明。

## 3. B2：Canonical Storage Error

结论：**PASS**。

独立注入 pre-storage failure 后，API 返回 `storage_error`；raw format-3 state 通过完整 canonical Schema，0 errors。ResultRecord 为 `result_state=storage_error + payload_valid=false`，`submission_id`、`credential_id`、`business_result`、result reference/digest、submitted/acceptance/conflict/provenance 均为 null；credential 保持 issued。ObservationRecord 与 identity projection 在错误前后完全不变，同一 envelope 随后重试为 `stored` 并原子消费 credential。

另注入 StateStore 结果关联已经提交但写后报告错误：入口按 exact credential、ResultRecord 和文件 digest 权威回读，返回 `stored`；credential 保持 consumed，结果保持 valid/available/complete，没有降级为 storage_error。

## 4. B3：Claim-Time Bearer

结论：**PASS**。

- prepare-dispatch/retry/replacement/communication 的基础返回、stdout、native args、PreparedContract 和 claim 前 StateStore 不含 bearer；credential 只在 PreTool admission 通过后生成。
- 成功 claim 的 bearer 在完整 Hook 输出中只出现一次，唯一位置是 `hookSpecificOutput.updatedInput.message`。移除该 message 后，Hook 其余输出不含 bearer。
- bearer 为 CSPRNG 32 bytes；持久化值为 `sha256$<16-byte salt>$<32-byte digest>`，验证使用 `hmac.compare_digest`。StateStore 同一 claim post-state同时包含 exact tool binding、公开 credential ID 和 salted hash。
- bearer 不在 StateStore、PreparedContract、diagnostics、临时 data root generated files、argv 或普通命令返回中。parameter deny、unsupported path 和 pre-CAS failure均无 `updatedInput`、无 bearer、无 credential。
- 两线程竞争同一 PreparedContract得到一个 allow、一个 deny、一个 issued generation和一次 bearer delivery。
- claim 写后错误且 exact post-state可证明时，完整回滚 claim/credential并 deny，不交付 bearer；若 task 已发生 canonical 并发变化、无法安全证明回滚，则 deny且不交付 bearer，保留 hash/claim binding，Schema 0 errors，交由 reconcile/expiry 收口。

静态调用图中 `_new_result_credential()` 与 `_render_result_submit_contract()` 各只有两个生产调用点：spawn PreTool claim和 correction/resume PreTool claim。`_associate_result_record()` 与 `_write_or_read_authoritative_result()` 各只有 credential-backed `submit_result_envelope()` 内一个调用点。未发现 public secret-return helper、secret 日志/异常插值、target-based submit、credential-free reassociate 或 final text/transcript/summary/Hook 自动提取结果的可达路径。

## 5. 其余显式结果协议

| 项目 | 结果 |
| --- | --- |
| format `None/1/2` migration、旧状态不补造 credential、Schema/runtime parity | **5/5 PASS** |
| credential 固定校验顺序与边界 | **10/10 PASS**：wrong secret优先于scope；expired/revoked优先于scope；wrong task/attempt、unknown/malformed ID、dummy constant-time compare、malformed hash、unknown state与 exact expiry boundary均拒绝 |
| strict TaskResult 与 canonicalization | **13/13 PASS**：unknown/missing/wrong type/oversized/deep、四类业务结果、key order、Unicode escape、Unicode normalization和 float attempt符合当前 JSON规则 |
| replay/conflict truth table | **7/7 PASS**：仅 same submission+digest 幂等；其他三种组合冲突；首份文件和 digest不覆盖；consumed credential不能跨 attempt |
| 原子性 | 线程 single winner与两个独立 CLI进程 single winner通过；credential consume与ResultRecord同一 StateStore transaction；post-commit权威回读通过 |
| child submit / parent relay | 共享 `submit_result_envelope()` 核心校验，分别记录 `child_submit` / `parent_relay` provenance |
| observation/identity invariant | submit、storage failure与retry不修改 ObservationRecord/identity；credential possession不投影为 confirmed |
| reader与孤立结果 | read只接受 StateStore valid+available 的 exact reference并复验文件；孤立文件不会自动成为权威，但可能保留完整业务结果并对同一 OS用户可读 |
| Slice 1/2、CAS/migration/retired parity | focused/full suite通过；canonical target authority、Hook fail-open、CAS rollback、format migration和retired reader parity未发现回退 |

项目当前 JSON canonicalization 是 UTF-8、`ensure_ascii=false`、sorted keys和紧凑 separators：对象 key 顺序与 Unicode escape 表示不改变 digest；不执行 Unicode normalization，因此 NFC/NFD内容产生不同 digest；业务结果中的 `attempt` 只接受 JSON integer，不接受 `1.0`。

## 6. 分类

### Blocker

无。

### 已知限制

- credential possession只证明 bearer possession，不证明 platform Agent、进程或用户身份，也不提供不可抵赖性。
- 结果文件与 StateStore不是跨文件系统事务。孤立文件不会被 reader当作权威，但可能保留完整业务结果，并可能向同一 OS用户泄露。
- claim post-commit 状态无法安全回滚时，插件安全 deny且不交付 bearer，但已持久化的 issued hash/claim binding可能保留，需要 reconcile或expiry收口。
- salted SHA-256依赖当前 256-bit随机 bearer；不适用于低熵人工口令。

### Backlog

- 删除当前无调用者的 `_read_subagent_event_route()`、`_assign_starting_agent()` 等旧 transcript/Start identity helper，降低未来误接回 correctness path 的风险。
- 移除 formal-result 已不使用的 `--agent-target` parser compatibility表面和既有文档中的退役 `--reassociate-result`描述；当前 CLI实际 formal write仍强制 credential envelope。
- 将本轮 legacy running、alias/index、唯一候选、post-commit unproven和四类 operation guard反例全部固化为长期回归，避免只覆盖 active/terminal正例。

### Not Checked

- Codex平台/provider/宿主是否记录 Hook `updatedInput`、最终 prompt、工具输入或内部日志；本地 GO 不扩大为平台保密保证。
- 真实 child能否定位脚本/data root并调用 submit，真实 parent relay人工链路，以及 prompt截断/改写行为。
- 真实 restart、compact/resume、mailbox、乱序/重复 event和跨版本行为。
- 测试缓存、稳定发布源、Marketplace、Hook trust、Registry、既有 smoke StateStore和任何真实任务状态。

## 7. 门禁数字

| 门禁 | 结果 |
| --- | --- |
| 第三轮目标顺序矩阵 | **9/9 PASS** |
| correction/resume operation guard | **4/4 PASS** |
| B2 storage故障矩阵 | **2/2 PASS** |
| B3 claim/secret/rollback矩阵 | **7/7 PASS** |
| 独立 migration/parity | **5/5 PASS** |
| 独立 credential validation | **10/10 PASS** |
| 独立 TaskResult/canonicalization | **13/13 PASS** |
| 独立 replay/conflict | **7/7 PASS** |
| Result credential focused unittest | **30 tests，OK** |
| Focused result/security/canonical tests | **96 tests，OK** |
| 完整 unittest | **440 tests，OK** |
| Python compile | `scripts/` + `tests/` 共 **25** 个 `.py` 文件，PASS |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| 全部 JSON parse | **17 files，PASS** |
| Schema/runtime parity | credential fields、state enum、format version双向一致，PASS |
| secret/static bypass scan | generator/renderer各2个受控 claim调用点；result association/storage各1个credential-backed调用点；PASS |
| `git diff --check` | PASS |
| untracked trailing whitespace | **52** 个 untracked files，**0** 命中，PASS |

## 8. 最终裁决

**GO，允许进入 Slice 3 测试 cachebuster和新建真实 Slice 3 smoke。** 该授权仅覆盖测试候选验证，不覆盖稳定安装、发布、同步、提交、推送或 Slice 4。真实 smoke必须把平台内部 bearer记录面继续标为 `not_checked`，并独立验证 child显式 submit与parent relay可达性；smoke失败应回到开发仓库修复并重新独立验收。
