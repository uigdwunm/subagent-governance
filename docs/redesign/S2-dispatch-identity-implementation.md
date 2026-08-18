# S2 契约、派发与精确身份实施记录

> 2026-08-14 状态：本文是历史实施记录。平台能力切片 1 已撤销“由
> SubagentStart 精确确认 running/identity”的运行时保证；当前边界以
> `schemas/codex-hook-events-v1.contract.json` 和
> `docs/redesign/platform-capability-slice-1-implementation.md` 为准。

## 范围

本记录覆盖 D6 S2 在开发仓库内的最小实现：确定性 deliverable contract、initial/replacement native spawn 的 canonical execution 落点、PreparedContract 收缩，以及只由精确 Start 确认身份。未安装、发布、同步缓存、修改 Hook trust、stage 或 commit。

## 失败先行基线

先在 `tests/test_dispatch_identity.py` 增加 S2 断言并运行：

```bash
python3 -m unittest -v tests.test_dispatch_identity
```

基线 28 tests 中 3 errors：`deliverable_contract` 不存在；`contract_digest`/确定性 helper 不存在；`prepare_replacement_dispatch` 不存在。随后新增测试还固定了 PostToolUse success 不得直接确认 running、相似 task name 不得绑定和无 `spawn_not_created` 事实不得 retry。

### 父验收修正

父验收额外指出两个 S2 风险：replacement 计数必须一次成功只加一且 CAS 失败不改变计数；`prepare_spawn_retry()` 不能以根级 legacy current projection 决定 retry。先增加两个最小测试：第一个覆盖成功 replacement 后 `replacement_spawn_count=1` 及模拟 CAS conflict 后仍为 1；第二个故意把 root projection 伪造成 `failed + spawn_not_created`，canonical execution 保持 `unknown`，并断言 retry 被拒绝。修正前第二个测试稳定失败：helper 错误按 root projection 授权 retry。

## 实际实现

- `governance-semantics.schema.json` 增加 `deliverable_contract` 和 `dispatch_transition` 逻辑定义；`task-contract-v1` 不新增 transport identity 字段。
- `build_deliverable_contract()` 从已验证 `TaskContract` 按原数组索引确定性生成 completion/evidence refs、空 artifact expectations、四种 outcome guidance 和 `review_required=true`。`contract_digest()` 使用 canonical JSON 同时覆盖 TaskContract 与该 deliverable contract。
- initial execution 在 canonical `work_item.executions["1"]` 保存 contract summary、deliverable contract、digest、`initial_spawn`、immutable `origin_task_name`；PreparedContract 保存完整 contract、deliverable、digest、ref/name 和 native 参数，并在 Start 确认后删除。
- `prepare_replacement_dispatch()` 创建同一 work item 的新 attempt/new ref/new task name/new PreparedContract/new canonical execution；旧 attempt 保留不改写。unknown 旧 attempt 与 replacement 并存时两个 execution 都写 `duplicate_execution=true + resolve_duplicate`，不改写 S1 outcome/disposition。
- PostToolUse 仅写 `success|failed|unknown` call observation。success 即使含 response target 也保持 `not_started/unconfirmed/reconcile`；可靠 failed 额外记录 `spawn_not_created=true`，只有该事实才允许同 attempt retry；unknown 保留 ref/PreparedContract 且拒绝 retry。
- `_task_record_for_attempt`、`_iter_task_attempts` 和 task-ref 占用检查优先 canonical executions。S2 写路径在同一 CAS 中懒迁移旧 managed record 并刷新 legacy projection；纯读取不迁移。
- Start 仅接受 exact parsed `task_ref + task_name`，或已有 exact target/typed lifecycle binding。它不按正文、相似 name、latest/current attempt 或唯一候选猜测；Start 后才写 confirmed/running、最小 Agent mapping，并收缩对应 PreparedContract。
- 父验收修正后，`prepare_spawn_retry()` 只从 canonical `work_item.current_attempt -> executions[attempt]` 读取 retry 资格、契约、ref/name 和计数。兼容旧 record 时只构造内存 canonical adapter；纯准备不写 StateStore。replacement 的计数赋值保留在创建 execution 的同一 CAS 内且单次 `+1`；CAS 失败仅清理本次 PreparedContract。

## 状态转换

```text
Prepared -> claimed -> PostToolUse(success|failed|unknown)
success -> not_started/unconfirmed/reconcile
failed + confirmed not-created -> same-attempt retry eligible
unknown -> retain ref + reconcile; no automatic retry/replacement
exact SubagentStart -> running/confirmed + delete matching PreparedContract
explicit replacement -> A(N+1), new ref/name/prepared/execution; candidates remain duplicate
```

replacement 的 public helper 仅实现 S2 所需 native spawn identity；S3 same-Agent business resume、candidate 增长预算和 disposition workflow 未实现。现有 S4 list/status/recovery/interrupt 语义只做最小 fixture 接线以要求 exact Start 后再参与，未重写其状态机。

## 验证证据

- `python3 -m unittest -v tests.test_dispatch_identity tests.test_hook_fixtures`：本轮修正后 36 tests 通过。
- `python3 -m unittest -v tests.test_dispatch_identity tests.test_hook_fixtures tests.test_state_store tests.test_formal_result_parent_closure tests.test_communication_lifecycle`：本轮修正后 128 tests 通过。
- `python3 -m unittest discover -s tests -v`：本轮 247 tests 中 245 通过；仅 2 个既有 release-preflight errors，均为 `docs/redesign/D6-migration-and-slices.md` 含 host-specific path，未新增 S2 failure。
- `python3 -m py_compile scripts/subagent_governance.py`：通过。
- `python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .`：`Plugin validation passed`。
- `git diff --check`：通过。
- 父验收修正定向：`python3 -m unittest -v tests.test_dispatch_identity`：本轮修正后 31 tests 通过。

## not_checked 与剩余事项

- `not_checked`：原生 spawn response 的实际 shape、SubagentStart 实际携带 ref/target、真实 context 参数映射、Hook 加载/投递、缓存安装和真实新对话。
- 已知全量的 2 个 release-preflight errors 来自 D6 中已有 host-specific path；本 S2 不修改它们。最终全量结果会区分该既有失败与新增失败。
- S3 处理 same-Agent business resume、replacement 授权/增长护栏；S4 才统一等待、Session/Stop 和平台恢复的 canonical consumer；S5/S6 未实施。
