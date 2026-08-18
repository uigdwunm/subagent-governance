# 平台能力重设计 Slice 3 独立安全与状态机验收

日期：2026-08-14

结论：**NO-GO**。format 3、credential 加密材料、严格 TaskResult、固定校验顺序、重放/冲突、并发 single winner、正式读取权威和 child/relay 共核等主要机制通过独立验证，但存在三个稳定 blocker：可靠 native dispatch/delivery failure 后未撤销对应 credential generation；storage failure 会持久化不符合 canonical Schema 的 ResultRecord；generator CLI stdout 会输出 bearer-bearing 目标消息。426 项全量测试和现有定向测试全部通过，不能覆盖这些独立反例。

在上述 blocker 修复并重新独立验收前，**不得进入 Slice 3 测试部署或真实 smoke，不得启动 Slice 4**。

## 1. 范围与方法

本轮完整阅读并交叉检查：

- `AGENTS.md`
- `docs/redesign/platform-capability-contract-and-minimal-state-machine.md` 中 ResultCredential、显式结果协议、测试要求与 Slice 3
- `docs/redesign/platform-capability-slice-2-third-post-fix-independent-review.md`
- `docs/redesign/platform-capability-slice-3-implementation.md`
- `docs/refactor-plans/WP-05-formal-result-parent-closure.md`
- 当前 runtime、canonical/TaskResult Schema、CLI、generator、Skill、tests 和共享工作树 diff

所有主动反例均使用新建临时目录和隔离 StateStore/result root。未读取、修改或删除既有 smoke StateStore。除本报告外未修改实现、Schema、tests、fixtures 或既有文档；未部署、安装、发布、同步、提交或推送；未创建真实任务；未启动 Slice 4。

验收不接受实施报告中的 PASS 作为证据。以下结论来自独立 writer/reader/secret-flow/transaction inventory、定向测试、临时目录反例、全量回归和静态扫描。

## 2. 数据流与权威清单

### 2.1 Writer inventory

| 写入面 | 当前入口 | 权限与效果 | 结论 |
| --- | --- | --- | --- |
| credential 签发 | initial dispatch、replacement、spawn retry、result correction、business resume generator | native 调用前在 canonical task 的 `result_credentials` 写入 salted hash record；同 attempt 新 generation 撤销旧 issued generation | 准备阶段满足；native failure 后撤销不完整，见 B1 |
| 正式结果文件 | `_write_or_read_authoritative_result()` | 确定性地址、私有目录/文件、文件锁、临时文件 + `fsync` + replace、写后回读 | PASS |
| ResultRecord | `submit_result_envelope()` 内 `_associate_result_record()` | credential、scope、TaskResult 和 digest 通过后，在 StateStore update 中关联首份结果 | PASS；storage error 降级违反 Schema，见 B2 |
| credential consume | `submit_result_envelope()` | 与 ResultRecord 关联处于同一次 StateStore transaction | PASS |
| storage error | `_mark_result_storage_unavailable()` | 不消费 credential，写 manual-review/result storage 状态 | FAIL；`payload_valid` 残留 true，见 B2 |
| migration/repair | format 1/2 update migration、canonical repair | 只补空 `result_credentials` 容器，不签发或猜测 credential；不建立结果 | PASS |
| parent disposition | 显式 parent disposition CLI/core | 只写 closure/acceptance，不创建或覆盖 ResultRecord | PASS |

旧 `agent_target` provenance、target-based submit、无 credential reassociate 写入口均已退出正式写路径。runtime 中 `_associate_result_record()` 仅由 `submit_result_envelope()` 调用；CLI parser 保留的 `--agent-target` compatibility 参数未被正式结果提交读取，不能建立结果。

### 2.2 Reader inventory

| 读取面 | 权威规则 | 结论 |
| --- | --- | --- |
| credential lookup | 仅按格式正确的 `credential_id` 在 managed task 的 task-level map 查找；随后验证 secret、state、expiry 和 task/attempt scope | PASS |
| result submit/replay | 读取 credential accepted submission/digest、canonical ResultRecord 和确定性文件；首份已消费结果不可覆盖 | PASS |
| `read_task_result()` / `--read-result` | 必须先有 StateStore 中 `valid + available` 的精确引用，再校验确定性地址、TaskResult、task/attempt、canonical bytes 和 SHA-256 | PASS |
| projection/diagnostics | 读取 canonical result/closure facts；credential 不投影为 identity confirmed | PASS |
| legacy transcript/Hook helpers | 物理代码仍可能存在，但当前 managed Start/Stop/final text/transcript/summary 不调用其建立正式结果 | 无当前旁路；列入 backlog |

孤立结果文件不会仅因存在而被读取为权威；它必须由同 generation credential 的显式重试精确关联。不过文件可能保留完整业务结果并对同一 OS 用户可读，详见已知限制。

### 2.3 Secret-flow inventory

正常流为：32-byte CSPRNG bearer -> 目标 dispatch/correction message -> child stdin envelope；持久化流只保存 `sha256$<salt>$<digest>`。独立检查确认：

- bearer 用 `secrets.token_bytes(32)` 生成，base64url 后长度为 43；credential ID 使用 128-bit 随机值。
- salt 为 16 bytes，digest 为 32 bytes；hash 为 SHA-256(salt || UTF-8 secret)，验证先检查算法和长度，再调用 `hmac.compare_digest`。
- StateStore 和 PreparedContract 只保存 hash/公开 credential record；PreparedContract 保存目标消息 digest，不保存明文消息。
- submit/relay 的 argv、成功/冲突/幂等/错误输出不回显 bearer；diagnostics、capture、generated files、异常字符串和测试日志静态/动态检查未发现 bearer。
- 但是 preparation CLI 会把包含 bearer 的 `dispatch_prompt`、`spawn_args.message` 或 communication `message/native_args.message` 作为结果 JSON 打到 stdout，违反本次明确的“bearer 不进入 CLI output”门禁，见 B3。

### 2.4 Transaction inventory

单次 submit 的核心顺序为：在 StateStore session 稳定锁内查 credential并校验 -> 严格校验 TaskResult并计算 canonical digest -> 在结果文件锁内创建或读取确定性文件并回读 -> 同一 StateStore transaction 关联 ResultRecord且消费 credential -> StateStore 原子替换与回读。线程和独立进程竞争时只有一个首份 winner；后续请求进入 idempotent/conflict 状态机。

结果文件与 StateStore 是两个持久化对象，不是跨文件系统事务。文件成功而 StateStore 未提交时可留下孤立文件；同 credential 重试可按相同 digest关联。该设计不会把孤立文件自动读成权威，但 B2 证明 pre-storage failure 的诊断状态本身可能违反 canonical Schema。

## 3. 十一项独立验收

| # | 验收项 | 结论 | 独立证据 |
| --- | --- | --- | --- |
| 1 | format 3 record/container、format 1/2 migration、Schema/runtime parity | PASS | format `None/1/2`、空 credential map和双向字段/枚举 parity 共 5/5；旧状态只补空容器，不补造 credential |
| 2 | native 前签发；failure/rollback/replacement/retry/correction generation 语义 | **FAIL** | 准备失败 rollback、同 attempt replacement/retry 撤销路径存在；但 initial spawn PreTool deny、reliable PostTool failed及 correction reliable failed 后 bearer仍可提交，见 B1 |
| 3 | 32-byte CSPRNG、salted hash、secret 暴露面 | **FAIL** | 加密材料、at-rest、argv、diagnostics等通过；preparation CLI stdout 暴露 bearer-bearing message，见 B3 |
| 4 | 所有结果写路径必须经过 credential | PASS | 无 target/reassociate/internal helper/compatibility/migration repair 旁路；唯一 association helper 只在 credential核心内调用 |
| 5 | 固定验证顺序与 scope | PASS | wrong secret/task/attempt、unknown/malformed ID、revoked、exact expiry boundary、malformed hash、unknown state 共 9/9 |
| 6 | strict TaskResult 与 canonicalization | PASS | unknown/missing/wrong type/deep/oversized、四业务场景、key order、Unicode escape/normalization、float attempt 共 13/13；JSON key order/escape 不改变解析后 canonical digest，Unicode normalization 不被隐式折叠，非整数 attempt 被拒绝 |
| 7 | replay/conflict truth table | PASS | 7/7；仅 same submission + same digest 幂等，其他 submission/digest 组合进入 conflict；首份 reference/digest/business result不覆盖；consumed 不能跨 attempt |
| 8 | 并发、原子性、readback、storage failure | **FAIL** | 线程与双进程 single winner、consume + ResultRecord 同 transaction、post-commit readback和孤立文件重试通过；pre-storage failure 持久化 invalid canonical state，见 B2 |
| 9 | child submit / parent relay 与禁止自动提取 | PASS（本地） | 两入口共享同一核心，provenance 分别为 `child_submit` / `parent_relay`；未发现 final text/transcript/summary/Hook 自动提取 |
| 10 | plane isolation | PASS | submit 只改变 result/closure；observation raw record 和 identity projection保持不变；`result_credential` 不投影为 confirmed |
| 11 | Slice 1/2、CAS/migration/retired parity | PASS | focused cross-slice 和 full suite无回退；canonical target authority、CAS、format migration、retired parity与 Hook fail-open 保持通过 |

## 4. Blockers

### B1. 可靠 native failure 后 credential generation 仍可用

严重性：**blocker / security-state-machine**。

三个隔离临时 StateStore 最小反例均稳定复现：

1. initial spawn preparation 持久化 credential，PreTool allow/claim，PostTool 收到可靠 `failed`；execution 已为 `dispatch_state=rejected`，credential 仍为 `issued`。用原 bearer submit 返回 `status=stored`，并建立 `business_result=complete`。
2. initial spawn preparation 后，PreTool 因 native 参数与 PreparedContract 不匹配明确 `deny`；credential 仍为 `issued`，同 bearer submit仍返回 `stored`。
3. `result_correction` preparation 写入新 generation，followup PreTool allow，PostTool reliable failed；credential 仍为 `issued`，同 bearer submit仍返回 `stored`。

精确范围：

- initial spawn failed transition：`scripts/subagent_governance.py:8420` 起只更新 identity/execution/parent action，不撤销 attempt generation。
- result-correction failed transition：`scripts/subagent_governance.py:7080` 起不撤销新 generation。
- correction credential 安装：`scripts/subagent_governance.py:6758-6824`。
- issued credential 可建立正式结果：`scripts/subagent_governance.py:4232-4409`。
- `_revoke_failed_result_credential_generation()` 目前只在 spawn-retry preparation exception rollback 等有限路径调用，不能覆盖已进入 native 调用后的可靠失败。

影响：未派发或可靠未送达的 bearer 仍具有正式结果写权限，违反 generation 生命周期和“不留下未派发可用 credential”的冻结要求。状态机已明确知道 delivery/dispatch failed，因此不能把该 bearer继续解释为有效交付凭证。

### B2. storage failure 持久化的 ResultRecord 违反 canonical Schema

严重性：**blocker / canonical-state**。

最小反例：在隔离 submit 中注入 `_write_or_read_authoritative_result()` pre-storage failure。API 返回 `status=storage_error`，credential保持 issued，业务结果保持 null；但持久化记录为：

```text
result_state=storage_error
payload_valid=true
```

对该完整 StateStore 执行 canonical task Schema validation 稳定得到 1 个错误：

```text
$.executions.1.result_record.payload_valid: value does not match const
```

精确范围：`scripts/subagent_governance.py:4148-4179` 的 `_mark_result_storage_unavailable()` 在 4165 行先写 `result_protocol_status=valid`，兼容同步使 `payload_valid=true`；随后只写 storage unavailable，未清回 false。`schemas/governance-semantics.schema.json:505-515` 明确要求 `result_state=missing|storage_error` 时 `payload_valid=false`。

影响：一个公开支持且可重试的 storage failure 会让 StateStore 离开 runtime/Schema共同声明的合法状态，后续 read、migration、diagnostics或写入可能因不同 validator 边界产生分叉。canonical invariant 不能以“错误路径较少发生”为例外。

### B3. generator CLI stdout 包含 bearer

严重性：**blocker / secret exposure requirement**。

独立 subprocess 反例使用临时 data root，捕获 preparation CLI stdout后只报告匹配布尔值，不打印 secret：

```json
{
  "returncode": 0,
  "secret_present_in_prepare_dispatch_stdout": true,
  "secret_present_in_stderr": false,
  "stdout_contains_spawn_message": true,
  "secret_length": 43
}
```

精确范围：

- `_render_result_submit_contract()` 在 `scripts/subagent_governance.py:2263-2287` 将 bearer 放入目标消息，这是目标传递所需。
- `prepare_dispatch()` 在 `scripts/subagent_governance.py:5732-5742` 同时返回包含该消息的 `dispatch_prompt` 和 `spawn_args`。
- communication preparation 在 `scripts/subagent_governance.py:6851-6880` 返回 bearer-bearing `message` 与 `native_args.message`。
- CLI `main()` 在 `scripts/subagent_governance.py:11641` 将整个 preparation result JSON 输出到 stdout；replacement/retry路径具有同类返回形状。

Slice 3 设计把目标消息视为必要 bearer delivery surface，但本次验收门禁明确包括“bearer 不进入 CLI output”。当前 CLI 恰以 stdout 作为 generator结果通道，因此不满足该要求。submit/relay CLI不回显 secret 不能抵消 preparation CLI 的暴露。

## 5. 已知限制

- bearer 必须以明文进入目标子 Agent消息；平台/provider/宿主对 prompt、tool input或内部日志的留存和可见性无法由本地仓库证明。
- credential possession只证明 bearer possession，不证明 Codex runtime Agent、进程、用户身份或不可抵赖性。
- 结果文件与 StateStore无跨文件系统事务。孤立文件不会被自动视为权威，但可能保留完整业务结果，并可被同一 OS 用户读取；正式 reader 仍要求 StateStore精确引用和完整校验。
- salted SHA-256 的安全性依赖当前 256-bit随机 bearer；它不是低熵用户口令的 KDF。当前 generator不接受调用者提供 secret。

## 6. Backlog

- 物理删除已退役但当前不可达的 transcript/result-gap/legacy identity helper，减少未来误接回正式结果路径的风险。
- 移除 CLI parser仍接受但结果通道不使用的 `--agent-target` compatibility表面。
- 为 reliable PreTool deny、spawn PostTool failed和 result-correction delivery failed新增 generation revocation回归矩阵。
- 为所有 storage failure transition增加 canonical Schema逐状态验证，而不只断言 API response。

## 7. Not Checked

- 未创建真实 child；未验证真实 child环境能否定位脚本/data root并调用 `--submit-result`，也未验证真实 parent relay人工链路。
- 未验证真实平台的 prompt截断、provider restart、compact/resume、mailbox/event顺序、真实乱序/重复或跨版本行为。
- 未检查平台/provider/宿主内部日志是否记录目标消息中的 bearer。
- 未部署或同步测试插件，未读取稳定发布源、运行缓存、Marketplace、Hook trust、Registry或任何既有 smoke StateStore。

这些 not_checked不消除本地 blocker。即使真实平台 smoke成功，也不能覆盖 B1-B3 的稳定反例。

## 8. 门禁结果

| 门禁 | 结果 |
| --- | --- |
| 独立 format/migration/parity matrix | 5/5 PASS |
| 独立 credential validation/scope matrix | 9/9 PASS |
| 独立 strict TaskResult/canonicalization matrix | 13/13 PASS |
| 独立 replay/conflict truth table | 7/7 PASS |
| Focused security/atomicity unittest | 87 tests，OK |
| 完整 unittest | 426 tests，OK |
| 线程 + 独立进程 single winner | PASS |
| Python compile | `scripts/` + `tests/` 全部 25 个 `.py` 文件，PASS；pycache定向到临时目录 |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| 全部 JSON parse | PASS |
| secret/static bypass scan | target/reassociate/auto-extract无写旁路；发现 preparation CLI stdout bearer blocker |
| `git diff --check` | PASS |
| untracked trailing whitespace | PASS |

现有测试全绿只证明已编码断言的路径通过。B1-B3 均来自 suite之外的稳定、最小、隔离反例，因此门禁结论仍为 NO-GO。

## 9. 最终结论

**NO-GO。** Slice 3 目前不能进入测试部署或真实 smoke。必须先在开发仓库修复 B1 的 generation revocation、B2 的 canonical storage-error transition，并解决或重新明确 B3 的 CLI output安全契约；随后补回归测试、重跑全部本地门禁，再开启新的独立验收。

本报告不授权安装、同步、发布或 Slice 4 工作。
