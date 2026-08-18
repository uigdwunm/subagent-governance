# 平台能力重设计 Slice 3 修复后第二轮独立复验

日期：2026-08-14

结论：**NO-GO**。B2 canonical storage-error 修复与 B3 claim-time secret delivery 修复通过；B1 的多数 generation 路径通过，但存在一个新的稳定 blocker：spawn claim 已有精确 `SubagentStart`/active 事实后，迟到的 PostTool reliable `failed` 仍撤销该 credential，并把 observation/identity 回退为 `not_observed/unconfirmed`。这违反冻结矩阵中“已有 Start 证据的含糊 failure 保持 issued 并 reconcile”的要求。

在该 blocker 修复并再次独立复验前，**不得执行测试 cachebuster、不得进入真实 Slice 3 smoke、不得启动 Slice 4**。

## 1. 范围与边界

本轮重新阅读并检查：

- 最新 `docs/redesign/platform-capability-slice-3-implementation.md`
- `docs/redesign/platform-capability-contract-and-minimal-state-machine.md` 的最新显式结果协议与 generation 终止矩阵
- 当前 runtime、Schema、CLI、generator、Skill、tests 和共享工作树 diff
- 第一轮报告 `docs/redesign/platform-capability-slice-3-independent-review.md` 的 B1/B2/B3 最小反例

所有主动反例均使用新建临时目录、隔离 StateStore/result root 和进程内测试实例。未读取、修改或删除既有 smoke StateStore。除本报告外未修改实现、Schema、tests、fixtures 或既有文档；未部署、安装、同步、发布、提交、推送或创建真实任务；未启动 Slice 4。

本轮不采信实施报告的 PASS 声明。结论来自重新建立的 claim/credential/secret/result transaction inventory、三个原始最小反例、附加事件顺序反例、focused/full tests 和静态扫描。

## 2. 修复后资产与事务清单

| 面 | 当前权威路径 | 独立结论 |
| --- | --- | --- |
| prepare/generator | initial/retry/replacement/communication 只保存无 secret 基础消息；StateStore credential map 仍为空 | PASS |
| spawn claim | PreTool 参数/admission通过后生成 credential；hash、exact credential ID和 spawn claim同一次 StateStore write提交；随后只在 `updatedInput.message` 注入 bearer | PASS |
| correction/resume claim | PreTool pending/admission通过后生成 credential；hash、pending claim/new attempt和 exact credential ID同 CAS；随后只在 `updatedInput.message` 注入 bearer | PASS |
| reliable failure revoke | PostTool按 claimed `tool_use_id`、exact credential ID、task和 attempt撤销 generation | 部分 PASS；spawn已有 Start 时缺少含糊保护，见 B1 |
| result submit | credential lookup/secret/state/scope、strict TaskResult、canonical digest、文件和 StateStore transaction | PASS |
| storage error | 完整清空强结果事实并写 `storage_error + payload_valid=false`；credential保持 issued | PASS |
| reader | 只接受 StateStore `valid + available` 精确引用并回验确定性文件 | PASS；孤立文件不自动成为权威 |
| legacy bypass | 无 target-based submit、无 credential reassociate、无 final text/transcript/summary/Hook自动提取 | PASS |

静态调用图中 `_new_result_credential()` 只有两个生产调用点：spawn PreTool claim 和 correction/resume PreTool claim；`_render_result_submit_contract()` 也只在这两个 claim 成功返回面调用。`_associate_result_record()` 仍只有 credential-backed `submit_result_envelope()` 一个调用点。

## 3. B1：Generation 撤销状态机

### 3.1 通过项

| 场景 | 结果 |
| --- | --- |
| initial PreTool 参数不匹配 deny | 未签发 credential；deny无 `updatedInput` |
| initial reliable failed/not-created | exact claim credential转 `revoked` |
| retry reliable failed | 本次 retry generation转 `revoked` |
| replacement reliable failed | 只撤销 replacement exact generation；来源 generation不误撤销 |
| correction reliable delivery failed且无 Start | exact correction generation转 `revoked` |
| resume reliable delivery failed且无 Start | exact resume generation转 `revoked`，delivery attempt按既有策略关闭 |
| revoked bearer submit | `ResultCredentialError`；ResultRecord保持 `missing`，不建立 business result |
| spawn success、unknown、failed+target含糊 response | credential保持 `issued` |
| correction/resume success或unknown | credential保持 `issued` |
| correction/resume已有 `start_observed_at` 后 failed | credential保持 `issued`，进入 reconcile，不误关闭 |
| 迟到旧 spawn PostTool | 不撤销新 retry generation；old保持 revoked，new保持 issued |
| exact committed claim readback | 返回 allow并只在 `updatedInput.message` 交付 bearer |
| post-commit但权威 readback不可证明 | deny、无 `updatedInput`、无 bearer输出；已提交 hash/claim保留供对账 |
| 并发/重复 PreTool claim | 单一 allow、单一 issued generation |

### 3.2 Blocker：已有 Start 的 spawn failure 仍被当作可靠未创建

严重性：**blocker / security-state-machine / observation monotonicity**。

独立最小反例：

1. 在临时 StateStore prepare initial dispatch并成功 PreTool claim，取得一个 issued credential。
2. 在同一 claim等待 PostTool期间写入精确 Start/active事实：`dispatch_target=/root/prior-start`、`identity_status=confirmed`、`execution_status=running`、observation source=`subagent_start`、observed state=`active`，并建立 exact target mapping。该 raw format-3 state通过 canonical Schema，0 errors。
3. 投递同 `tool_use_id` 的迟到 spawn PostTool `{"isError": true}`。

实际结果：

```text
before: identity_status=confirmed, observed_state=active, source=subagent_start
credential: issued -> revoked
after: identity_status=unconfirmed, observed_state=not_observed
old bearer submit: ResultCredentialError
```

期望结果：已有 Start/active事实证明“native调用 failed”不能再解释为可靠未创建；应保留该 generation为 issued，并进入 advisory/reconcile，不得撤销 bearer，也不得回退已观察到的 active/confirmed事实。

精确范围：

- `scripts/subagent_governance.py:8475-8483` 的 predicate只核对 task/ref/tool_use_id/exact credential ID和未观察 response，没有检查既有 Start/active事实。
- `scripts/subagent_governance.py:8494-8506` 对所有 `spawn_observation == failed` 无条件撤销 exact credential。
- `scripts/subagent_governance.py:8507-8514` 随后把 identity/execution回退为 unconfirmed/not_started，覆盖已有 active observation。
- 对比 correction/resume，`scripts/subagent_governance.py:7020-7040` 已先检查 `start_observed_at`，只在无 Start的 reliable delivery failure撤销。
- `adapt_spawn_response()` 对同一 response中同时含 failure和 target的情况会降为 unknown并保留 credential；缺口只出现在 Start事实先于独立迟到 failed PostTool的事件顺序。

该反例不依赖 bearer猜测、跨 attempt alias或 Schema-invalid输入；它是一个 canonical、exact claim上的合法事件顺序。测试全绿不能覆盖该缺失分支。

## 4. B2：Canonical Storage Failure

结论：**PASS，第一轮 B2已关闭**。

重新注入 `_write_or_read_authoritative_result()` pre-storage failure，观察到：

```text
API status=storage_error
result_state=storage_error
payload_valid=false
submission_id/credential_id/business_result/result_reference/result_sha256/
submitted_at/acceptance_status/conflict/provenance = null
credential state=issued
raw format-3 canonical Schema errors=0
```

提交前后 raw ObservationRecord完全相等，identity projection保持 unconfirmed。同一 envelope随后重试返回 `stored`，credential转 `consumed`，ResultRecord转 `valid`。

另模拟 StateStore结果关联已经 commit、但写后报告/回读阶段抛出 `StateWriteError`：提交入口权威回读 exact credential、ResultRecord和文件 digest后返回 `stored`；credential保持 consumed，business result保持 complete，不写 `storage_error`，不降级已提交结果。

修复范围位于 `scripts/subagent_governance.py:4190-4236`：storage-error transition直接写完整 canonical ResultRecord，不再先设置 protocol valid。

## 5. B3：Claim-Time Secret Delivery

结论：**PASS，第一轮 B3已关闭**。

### 5.1 独立动态证据

- prepare-dispatch、prepare-spawn-retry和prepare-communication的 CLI stdout均不含 bearer、`credential_secret:` 或 `rc_<32 hex>`。
- Python普通 prepare返回的 `dispatch_prompt`、`spawn_args.message`、communication `message/native_args.message`和 argv均不含 bearer或 credential ID。
- prepare后、PreTool claim前，task-level `result_credentials`为空。
- 成功 spawn claim后，StateStore同一持久状态同时包含 `spawn_tool_use_id`、`spawn_result_credential_id`和匹配的 salted-hash credential record。
- bearer在完整 Hook输出中只出现1次，位置为 `hookSpecificOutput.updatedInput.message`；移除该 message后，Hook其余输出无 bearer。
- bearer不在 StateStore、PreparedContract、diagnostics或临时 data root的任何 generated file中。
- PreTool参数 deny、unsupported tool path和注入的 StateStore CAS failure均不返回 `updatedInput`、不输出 bearer、无 bearer落盘；deny/unsupported不签发 credential。
- 并发同一 PreparedContract claim为一个 allow、一个 deny，StateStore只有一个 issued generation。

### 5.2 静态 inventory

生产 secret generator只有：

```text
_new_result_credential definition
_handle_spawn PreTool claim
_claim_pending_action correction/resume PreTool claim
```

submit contract renderer也只有上述两个成功 claim返回面。未发现其他 public preparation/CLI/helper返回 bearer、日志/异常插值 secret、target/reassociate写旁路或自然语言自动提取路径。

本地 PASS只说明插件自己的普通输出和持久化边界。平台/provider/宿主是否记录 Hook `updatedInput`、最终目标 prompt或工具内部日志仍是 `not_checked`，不得扩大为平台级保密保证。

## 6. 其余 Slice 3 与跨切片复验

| 项目 | 结果 |
| --- | --- |
| format `None/1/2` migration、无 credential补造、Schema/runtime parity | 5/5 PASS |
| wrong secret/task/attempt、malformed/unknown ID、exact expiry、revoked、malformed hash、unknown state | 9/9 PASS |
| strict TaskResult：unknown/missing/type/deep/oversized、四场景、key order、Unicode escape/normalization、float attempt | 13/13 PASS |
| replay/conflict truth table | 7/7 PASS；仅同 submission+digest幂等，首份强事实不覆盖，consumed不跨 attempt |
| 线程 single winner | PASS |
| 两个独立 CLI进程 single winner | PASS；一个 stored、一个 conflict，secret不回显 |
| child submit / parent relay | 共享核心，分别记录 `child_submit` / `parent_relay` provenance |
| observation/identity invariant | 普通 submit与storage retry不改 observation/identity；credential不投影为 confirmed |
| Slice 1/2不变量 | full suite通过；Hook fail-open、canonical target authority、CAS/migration/retired parity未发现回退 |

## 7. 分类

### Blocker

- **B1-PostFix-1**：已有精确 Start/active事实时，迟到 spawn PostTool failed仍撤销 credential并回退 observation/identity。修复前不得测试部署或真实 smoke。

### 已知限制

- credential possession只证明 bearer possession，不证明 platform Agent、进程或用户身份。
- 结果文件与 StateStore不是跨文件系统事务；孤立文件不会自动成为权威，但可能保留完整业务结果并对同一 OS用户可读。
- post-commit claim无法权威证明时，插件安全 deny且不交付 bearer；已提交的 hashed credential/claimed pending可能保留为 action-required，需要显式对账或现有过期策略收口。
- salted SHA-256依赖当前 256-bit CSPRNG bearer，不适用于低熵用户口令。

### Backlog

- 增加“spawn Start/active先于迟到 failed PostTool”的固定回归，并与 correction/resume Start保护共享同一 generation终止谓词，避免语义再次漂移。
- 物理删除已退役但不可达的 transcript/result-gap/legacy identity helper。
- 移除结果通道不再使用的 `--agent-target` parser compatibility表面。

### Not Checked

- 未创建真实 child，未验证真实 child能否定位脚本/data root并调用 submit，也未验证真实 parent relay人工链路。
- 未验证 Codex平台/provider/宿主是否记录 `updatedInput`、最终 prompt、工具输入或内部日志。
- 未验证真实 prompt截断、restart、compact/resume、mailbox/event顺序、真实乱序/重复或跨版本行为。
- 未部署/同步插件，未检查稳定发布源、运行缓存、Marketplace、Hook trust、Registry或既有 smoke StateStore。

## 8. 门禁数字

| 门禁 | 结果 |
| --- | --- |
| 原 B1/B2/B3最小反例重放 | B2/B3关闭；B1可靠失败原反例关闭，但新增 prior-Start顺序 blocker |
| 独立 migration/parity | 5/5 PASS |
| 独立 credential validation | 9/9 PASS |
| 独立 TaskResult/canonicalization | 13/13 PASS |
| 独立 replay/conflict | 7/7 PASS |
| Focused result/security/canonical tests | 96 tests，OK |
| 完整 unittest | 435 tests，OK |
| Python compile | `scripts/` + `tests/` 共25个 `.py` 文件，PASS；pycache定向临时目录 |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| 全部 JSON parse | 13 files，PASS |
| secret/static bypass scan | generator/renderer各仅两个受控 claim调用点；association单一入口；无legacy写旁路；PASS，但不消除B1 |
| `git diff --check` | PASS |
| untracked trailing whitespace | PASS；报告创建后共51个 untracked files，0命中 |

## 9. 最终结论

**NO-GO。** B2和B3可以判定关闭；B1不能关闭。现有实现尚未满足“已有 Start/active事实的含糊 spawn failure不撤销 generation且不回退 observation”的冻结状态机要求。

因此当前**不允许测试 cachebuster，不允许真实 Slice 3 smoke，不允许启动 Slice 4**。修复应限定在开发仓库，补最小回归并重跑全部门禁后，再开启下一轮独立验收。本报告不授权任何部署、安装、同步或发布操作。
