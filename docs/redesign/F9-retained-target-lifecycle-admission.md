# F9: retained-target managed lifecycle admission

日期：2026-08-14

范围：仅修复 F8 P1-1；不处理 F10 initial preparation rollback

## 1. 结果

F8 的 retained-target lifecycle 绕过已在开发仓库本地修复。generator 与 PreToolUse 现在共享一个机械 target admission 分类器；`agents[target]` 只作 active lookup index，execution 的精确 `agent_id/canonical_task_path` 是 retained provenance。

当 StateStore 可读时，retained managed evidence 不再因为 active index 缺失、无效或过时而退化为 unmanaged。三类 governed lifecycle 必须继续经过 pending action、锁内 claim、恢复/补交预算、business-resume 新 attempt 和 PostToolUse 对账。

本切片没有修改 `_cleanup_initial_attempt()`、initial PreparedContract 删除顺序或其他 F10 代码、测试和设计。

## 2. Failure-first

先把 F8 临时 StateStore 反例转成 `tests/test_communication_lifecycle.py` 的稳定测试。修复前，首批 6 个 test methods 产生 9 个失败断言：

- `platform_recovery`、`result_correction`、`business_resume` 的 generator 在 retained provenance 存在但 index 缺失时全部返回 `managed=false`。
- 三类直接 `followup_task` PreToolUse 在没有 pending 且 index 缺失时全部错误 `allow`。
- 多 retained candidates、live stale-index conflict、retained normal/interrupt 仍进入旧 unmanaged 路径。

父侧验收随后发现第二个锁内反例：A1 已持有 prepared pending，但 PreTool claim 前 active index 与精确 provenance 合法切换到 A2。原 claim predicate 只检查 admission 仍为 managed 且 candidate 非空，因此会保留 A2 mapping，却错误认领 A1 pending。新增参数化失败测试在首次读取与 CAS 之间注入该切换；修复前 `platform_recovery`、`result_correction`、`business_resume` 三个 subtests 均错误 allow。

修复后扩展为 12 个 F9 lifecycle test methods 和 1 个 Schema semantic-anchor test，覆盖 missing、invalid stale、live conflict、ambiguous、closed history、truly unmanaged、generator/claim 锁内竞态、same-Agent A1/A2，以及 business-resume delivery-failure retry。

## 3. 单一分类权威

`_managed_target_admission(state, target)` 是 generator 与 PreToolUse 共用的纯分类器。它只读取：

- `state.agents[target]` 当前 lookup index；
- canonical `tasks[*].executions[*]`；
- execution 自身精确 `agent_id/canonical_task_path`；
- `attempt_closed=true` 可靠关闭事实。

它不读取 task name、同轮信息、正文、唯一模糊候选或 current-attempt 猜测，也不创建第二 identity index。

| 可观察事实 | 分类 | generator | 直接 PreToolUse |
| --- | --- | --- | --- |
| active index 指向精确、未关闭 provenance | managed | 走现有 pending 流程 | 有 pending 才可 claim；无 pending 拒绝 |
| index 缺失、无效或指向已关闭记录；仅一个精确未关闭 retained candidate | managed + repair | 锁内修复 index 并创建 pending | 有 pending 时锁内修复并 claim；无 pending 拒绝 |
| 无可靠 active index且有多个精确未关闭 candidates | reconcile | 明确拒绝 | 明确拒绝，不猜 operation/attempt |
| live index 指向的 execution 不含该 target provenance | reconcile | 明确拒绝 | 明确拒绝，不覆盖 index |
| 分类初读后在 pending 写入前变化 | reconcile/CAS conflict | 明确拒绝并要求重新生成或对账 | claim 锁内复判失败，拒绝 |
| A1 已有 prepared pending，claim 前 active candidate 精确切换到 A2 | reconcile/CAS conflict | 不适用；旧 pending 已存在 | 拒绝且保留 A1 pending；不消费预算、不创建 attempt、不回拨 A2 mapping |
| 只有 `attempt_closed=true` historical provenance | historical | 明确拒绝，不复活 | 明确拒绝，不按 unmanaged 放行 |
| 完全没有 canonical provenance | unmanaged | 保留原生兼容 | 保留原生兼容 |
| StateStore 不可读 | storage failure | normal message 与明确 interrupt 保留既有告警 fail-open；三类 governed lifecycle 拒绝 | `send_message`/明确 interrupt 保留既有告警 fail-open；governed follow-up 拒绝 |

active index 已精确指向 A2 时，即使 A1 仍保留同 target provenance，也使用这个显式 active mapping，不从 retained 集合猜测；这保留 same-Agent A1/A2 的当前执行与迟到事件分工。active index 缺失时，A1/A2 都未可靠关闭则属于多个 candidates，必须对账。

## 4. Writer、reader 与锁边界

### Generator

`_prepare_managed_action()` 初读 StateStore 后分类并校验现有 lifecycle 条件。真正创建 `pending_action` 时在 `StateStore.compare_and_set()` 锁内重新分类；只有 admission candidate 仍精确等于 pending owner 的 `(task_id, attempt)`，才由 `_repair_managed_target_index()` 写 active index，并在同一次 state write 中创建 pending。

因此 index 修复不能单独成功后再丢失 pending，也不能在分类变化后把旧 candidate 写成 current。可读状态的 CAS conflict 对所有 operation 都要求重新生成或对账；normal/interrupt 的既有 fail-open 只保留给真实 StateStore 不可用/不可写降级，不用于可读 identity conflict。

`business_resume` delivery-failure retry 也不放宽 owner 条件。prepared pending 始终写在当前 active admission candidate 上；若恢复来源是已因 `resume_delivery_failed` 关闭的 A2，则单独以 `prepared_on_attempt=2` 保存来源。认领仍要求 active candidate 精确等于 pending owner，例如 A1；新 A3 的 `origin_attempt` 再从 `prepared_on_attempt` 取得 A2。active owner 与业务来源是两项不同事实。

### PreToolUse

`_claim_pending_action()` 在无 pending 时使用同一分类器：managed target 拒绝直接调用，reconcile/historical 明确拒绝，只有无 canonical provenance 才 unmanaged allow。

有唯一 prepared pending 时，claim 的 CAS predicate 在锁内要求 managed admission candidate 精确等于 pending 所属 `(task_id, stored_attempt)`；writer 在任何 index 修复或状态修改前重复同一精确核对。通过后才在同一锁内修复 active index、认领 pending、绑定 `tool_use_id`，并原子增加 `recovery_count`/`correction_count` 或创建 business-resume 新 attempt。PostToolUse 的既有 `tool_use_id` 三态对账没有改变。

若 active candidate 已变化，CAS 失败返回 deny/reconcile。旧 pending 保持 `prepared`，`tool_use_id` 仍为空，不清理、不消费预算、不创建 attempt，也不把 mapping 回拨到旧 owner。父 Agent可先显式对账；如果不再使用该 pending，既有5分钟 prepared expiry 会在后续显式访问时精确清理，Hook 不引入后台 scheduler。

### 其他 reader/writer

F2 的 TaskResult/SubagentStop retained routing、SubagentStart identity binding、F6 compatibility reads 和 canonical write convergence 均未改动。`_managed_target_attempt()` 仍是 active-index lookup helper，但不再单独决定 lifecycle managed/unmanaged admission。

## 5. 回归证据

F9 tests 证明：

- 三类 governed lifecycle 的 generator 在 missing index 下均恢复 mapping、创建 pending 且返回 `managed=true`。
- generator 后再次删除 mapping，三类 PreTool claim 均恢复 mapping；recovery/correction 各消费一次预算，business resume 创建 A2。
- 三类直接无 pending PreToolUse 均拒绝，不能从正文猜 operation type。
- invalid stale index + 唯一 retained candidate 可修复；live conflicting index 不覆盖；多个 retained candidates 要求对账。
- historical provenance 拒绝且不复活；truly unmanaged 保持兼容。
- StateStore 可读时 retained normal/interrupt 走 managed generator；StateStore 不可用时既有合法降级测试仍通过。
- active exact A2 index 在 A1/A2 都保留 provenance 时仍选择 A2；F2 迟到 Stop/result 测试保持通过。
- pending 写入前的 identity race 被锁内复判拒绝，不产生旧 candidate pending。
- pending 准备后的 A1 -> A2 active-candidate race 被 claim predicate 与 writer 双重拒绝；三类 governed lifecycle 均保留 A1 pending，预算/attempt 不变且 mapping 不回拨。
- business-resume delivery-failure retry 把 active pending owner 与 `prepared_on_attempt` 来源分开；A1 精确认领后创建 A3，`origin_attempt=2`，没有为一般 A1/A2 race 开宽松例外。
- Schema `target_lifecycle_admission` 与 runtime/Skill/runtime-boundaries 保持一致。

## 6. 验证

定向与跨切片：

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.test_dispatch_identity \
  tests.test_communication_lifecycle \
  tests.test_formal_result_parent_closure \
  tests.test_wait_recovery_session_closure \
  tests.test_minimal_diagnostics_lightweight_groups \
  tests.test_state_store \
  tests.test_semantic_baseline \
  tests.test_canonical_record_schema \
  tests.test_s6_compatibility_retirement

Ran 288 tests
OK
```

全量：

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
Ran 364 tests
FAILED (errors=2)
```

362 项通过。仅保留任务明确允许的两个既有 D6 errors：

- `test_current_development_tree_passes_with_supported_ref`
- `test_release_requires_manifest_tag_and_marketplace_ref_to_match`

两项均为 `PreflightFailure: host-specific path in docs/redesign/D6-migration-and-slices.md`；F9 未修改或绕过 D6。

其他门禁：

- `python3 -m py_compile scripts/*.py`：通过，bytecode 写入独立临时目录后已清理。
- Plugin validator：`Plugin validation passed`。
- Skill validator：`Skill is valid!`。
- `rg --files -g '*.json'` 发现的全部 JSON 经 `python3 -m json.tool`：通过。
- `git diff --check`：通过。

## 7. not_checked

- 未安装、发布或同步测试插件，未写稳定发布源与运行缓存。
- 未写 Hook trust、Marketplace、Registry，未执行 cachebuster/reinstall。
- 未创建真实插件测试对话；真实 Skill/Hook/Provider/UI 加载均为 `not_checked`。
- 未验证真实 `followup_task`/`send_message`/`interrupt_agent` 参数形状、SubagentStart/Stop 时序、mailbox、上下文压缩或 provider 断流。
- 未检查稳定发布源与运行缓存哈希或非符号链接关系，因为本任务明确禁止发布流程。
- 未修复 D6 两项基线错误。

## 8. Remaining

F10 initial preparation rollback 仍是独立 P1：完整 task snapshot、PreparedContract 删除顺序、cleanup failure 诊断和 rollback-incomplete 状态均未由 F9 处理。在 F10 完成并重新通过本地综合复核前，仍不准同步测试插件或创建真实测试对话。

本切片没有引入 version/migration gate、事件日志、scheduler、第二 identity index 或第二状态机，也没有删除 F6 的 `last_disposition`、`parent_disposition`、pending disposition 或 PreparedContract legacy compatibility reads。
