# F11 local architecture gate review

日期：2026-08-14

性质：F9/F10 完成后的独立本地架构准入复核；只新增本文，未修改 runtime、Schema、Skill、测试或既有文档

## 1. 结论

**Local architecture gate: BLOCKED。**

F8 P1-2 已由 F10 的 exact initial rollback 在当前本地证据范围内关闭。F8 P1-1 的 missing/stale/ambiguous/closed retained-target 主缺口，以及三类 governed follow-up 的 pending owner race，已由 F9 关闭；但本次独立推演发现同一 owner invariant 在主动中断 PreToolUse 上仍有一个 P1 反例：A1 的 prepared interrupt 在 claim 前 target active owner 切换到 A2 时，锁内 CAS 已正确识别冲突，`_claim_pending_action()` 随后的宽泛 interrupt exception 分支却 fail-open，原生中断会被投影到当前 target A2。

这会把 A1 的未认领中断意图发送给另一个 active managed execution；A1 pending 仍为 `prepared` 且没有 `tool_use_id`，StateStore 也仍可正常读写。因此它不是允许的 StateStore unavailable 降级，而是可读 identity conflict 被错误 fail-open。

当前阶段不能同步测试插件，不能创建真实测试对话，也不是“只需等待真实测试授权”。下一步必须先完成一个独立本地修复切片并重新执行本地综合准入。该切片通过后，才由用户授权同步测试插件，并按项目规则在新对话使用 `gpt-5.6-terra`、`high` 做真实验收。

本结论不是 `release-ready`。全量 378 tests 仍有两个既有 D6 release-preflight errors，且真实 Hook/provider/mailbox/UI 全部为 `not_checked`。

## 2. Findings

### P0

无。

### P1-1: interrupt claim 把可读 pending-owner conflict 错误 fail-open

**证据位置**

- `scripts/subagent_governance.py:6166-6178`：claim predicate 正确要求 admission candidate 精确等于 pending owner 的 `task_id + attempt`。
- `scripts/subagent_governance.py:6180-6190`：writer 再次执行相同 owner 核对，冲突时抛出 `StateConflictError`。
- `scripts/subagent_governance.py:6225-6233`：上述 CAS/identity conflict 被宽泛 `except Exception` 捕获；只要 `interrupt=True` 就返回 allow/fail-open，没有区分可读冲突与 StateStore unavailable。
- `schemas/governance-semantics.schema.json:1134-1137`：机器语义要求 pending owner 等于 admission candidate，stale pending claim 必须 deny 并保留供 reconcile/expiry。
- `docs/redesign/F9-retained-target-lifecycle-admission.md:45`、`:58`：F9 明确承诺 owner 切换时拒绝，且可读 CAS conflict 不使用 normal/interrupt fail-open。

**独立反例**

1. A1 是 target 的 active managed execution，generator 为 A1 创建 `interrupt` pending。
2. PreToolUse 前，同一精确 target 的 active mapping 与 provenance 合法切换到 A2；A1 pending 保留。
3. PreToolUse 调用 `interrupt_agent(target)`；锁内 predicate 发现 admission candidate A2 不等于 pending owner A1，CAS 产生 `StateConflictError`。
4. exception 分支返回 allow，并把原生参数保持为同一 target。

临时 StateStore 的实际输出：

```text
decision=allow
active_owner=f11-interrupt-owner-a2
pending_owner=f11-interrupt-owner-a1
pending_phase=prepared
tool_use_id=None
```

**影响**

- A1 的中断授权可以中断 A2，破坏精确 identity、pending claim 与 same-Agent/current-owner 边界。
- 原生调用与治理记录分离：平台可能执行中断，但 StateStore 没有 claimed pending 或 `tool_use_id`，后续 PostToolUse 无法形成可靠因果关联。
- 该错误位于主动生命周期控制，不是无副作用的普通消息降级；可能停止错误 worker 并丢失进度。
- F9 的 Schema anchor 与 runtime 行为不一致，现有 12 项 F9 tests 没有覆盖 interrupt owner-switch claim。

**最小独立修复切片**

1. 先增加 failure-first 回归：prepared interrupt 属于 A1，claim 前 active candidate 切到 A2；断言 deny、A1 pending 保持 prepared、A2 mapping 不回拨、无 `tool_use_id`，且不形成原生 interrupt authority。
2. 在 `_claim_pending_action()` 中区分 `StateConflictError`/机械 identity conflict 与明确 StateStore unavailable/write failure。可读 owner/CAS conflict 对 interrupt 必须 fail-closed；只有项目明确允许的真实存储不可用边界才保留告警 fail-open。
3. 参数化抽查 normal、interrupt、platform recovery、result correction、business resume 的 A1 -> A2 race，避免 exception 类型再次绕过共享 classifier。
4. 核对 Schema、Skill 与 runtime-boundaries 的文字边界；仅在现有语义不足时做最小同步，不扩大为 interrupt 状态机重构。

### P2

无独立 P2 finding。

### P3

无独立 P3 finding。缺少 interrupt owner-switch regression 已包含在 P1-1 的证据和修复条件中。

## 3. F8 两项 P1 逐条验收

### 3.1 F8 P1-1 retained-target lifecycle admission

| 场景 | Generator | Direct/claim PreToolUse | 结果 |
| --- | --- | --- | --- |
| active index missing + 唯一 open retained provenance | 锁内修复 index 并创建 managed pending | 无 pending 拒绝；有 pending 可锁内修复并认领 | 通过 |
| invalid/stale index + 唯一 open retained provenance | 只从精确 execution provenance 修复 | 共享 classifier | 通过 |
| live index/provenance conflict | reconcile/fail-closed，不覆盖 index | deny | 通过 |
| 无可靠 index + 多个 open retained candidates | reconcile，不猜 current attempt | deny | 通过 |
| 只有 closed historical provenance | reject，不复活 | deny，不按 unmanaged 放行 | 通过 |
| 完全没有 canonical provenance | unmanaged compatibility | unmanaged compatibility | 通过 |
| 三类 governed lifecycle 无 pending 直接调用 | 不适用 | deny，不从正文猜 operation | 通过 |
| 三类 governed lifecycle 的 A1 pending -> active A2 race | 不适用 | deny；保留 A1 pending，不消费预算、不创建 attempt、不回拨 mapping | 通过 |
| business-resume delivery-failure retry | active owner 承载 pending，`prepared_on_attempt` 单独绑定 closed source | A1 owner claim 后从 A2 source 创建 A3 | 通过 |
| normal message / interrupt，StateStore 可读 | retained target 继续 managed | 必须认领 prepared pending | normal 通过；interrupt owner race 失败 |
| normal message / explicit interrupt，StateStore 不可用 | 告警 fail-open，不声称治理已记录 | 告警 fail-open | 通过 |

验收结论：F8 原始“三类 governed follow-up 因 missing index 退化 unmanaged”的绕过已关闭，但 F9 声明的共享 owner invariant 没有覆盖 interrupt claim exception 分流。按本次要求的完整 lifecycle 准入边界，F8 P1-1 **未能最终验收关闭**。

### 3.2 F8 P1-2 initial preparation exact rollback

| 场景 | 当前行为 | 结果 |
| --- | --- | --- |
| exact initial task | 完整 task 等于 PreparedContract 确定性 post-state 时，StateStore CAS 先删 task，确认 absent 后 exact-delete credential | 通过 |
| diverged task | 任一 extension/timestamp/identity/claim/`parent_action` 变化都保留 task 与 PreparedContract | 通过 |
| StateStore persist-then-error | readback 后按 exact/diverged 分流；原始 error 与 cleanup error 均可见 | 通过 |
| StateStore task cleanup failure | 保留 credential；可写时写 `parent_action=reconcile` 和 rollback marker | 通过 |
| StateStore readback failure | 不猜 task 状态，不删 credential，明确 rollback-incomplete | 通过 |
| PreparedContract cleanup failure | task absent 后保留 retryable orphan，并报告 exact task identity | 通过 |
| PreparedContract full-record conflict | `delete_if(value == prepared)` 拒绝删除并发变化后的 credential | 通过 |
| expiry 时 task absent orphan | 安全 exact-delete credential，失败则保留并报告 | 通过 |
| marker task CAS | predicate 只绑定 observed full task；新 task fact 会阻止 marker 覆盖 | 通过 |
| execution/work-item `updated_at` | 有效旧值使用 `max(old, now)`，不回拨较新时间 | 通过 |
| health unavailable/newer marker/其他字段 | `unavailable` 不降级；较新 marker 和其他 health facts 保留 | 通过 |
| invalid health status/marker | 原形保留供 diagnose，不覆盖为伪合法状态 | 通过 |
| health-only race | health 不扩展 task predicate；callback 在锁内按当前 health 做单调最小合并 | 通过 |

验收结论：F8 P1-2 在当前 runtime、Schema anchor、Skill/runtime-boundaries 与本地测试范围内 **已关闭**。没有发现第二 task snapshot、transaction log、隐藏 rollback state 或跨锁伪事务。

## 4. 原 9 项 findings 抽查

| 原 finding | 结果 | 独立抽查依据 |
| --- | --- | --- |
| closed/tombstoned work item 可再次 spawn | 通过 | replacement prepare、retry prepare 与 stale claim 均拒绝，不复活 task |
| unclaimed replacement 绕过 cap/expiry | 通过 | reservation 计入 capacity/action-required；exact expiry 与 claim rollback 保留并发事实 |
| same-Agent A1 late Stop/result 污染 A2 | 通过 | payload `task_id + attempt` 与 retained provenance 把迟到结果留在 A1 |
| duplicate risk 依赖 reason code | 通过 | prepare/claim 都从全部 canonical live executions 派生 coexistence risk |
| reliably stopped source 形成 false duplicate/select | 通过 | stopped/interrupted/closed 被 coexistence predicate 排除 |
| persisted `work_item.action_required` 成为第二权威 | 通过 | Schema 禁止该字段；diagnose/group/Session/Stop 使用共享 derived predicate |
| diagnose/SessionStart 缺 growth facts | 通过 | growth 只从 canonical work item 投影并由 group member snapshot 透传 |
| Schema 不是 executable canonical anchor | 通过 | runtime enums/field sets 双向匹配；canonical combination tests 与 validator 通过 |
| canonical-only 后仍有 legacy dead authority | 通过 | compatibility convergence 冲突时拒绝；S6 residual test 通过 |

F9/F10 未回归 close growth、replacement reservation、same-Agent Stop/result、duplicate select、action-required 或 Schema/compatibility。新增 finding 是 interrupt claim exception 分流违反 F9 owner invariant。

## 5. 不变量矩阵

| 不变量 | 结果 | 证据与边界 |
| --- | --- | --- |
| closed growth 单向性 | 通过 | prepare/claim 均检查 open work item 与 unclosed source |
| replacement reservation/claim/expiry/rollback | 通过 | reservation snapshot 与 claim full-task snapshot 各自 exact CAS |
| retained identity authority | 部分通过 | execution provenance 是唯一 authority，active index 可修复；interrupt stale-owner exception 仍可绕过 claim |
| pending owner = admission candidate | **失败** | predicate/writer 正确，但 interrupt exception 把 conflict 转成 allow |
| business-resume source/owner 分离 | 通过 | active pending owner 与 `prepared_on_attempt` source 各自明确 |
| initial rollback exactness | 通过 | deterministic post-state；task-first、credential-second 删除 |
| rollback 可诊断性/action-required | 通过 | diverged/retained task 可写时进入 reconcile/degraded；不可写时 credential retained 与 error 可见 |
| duplicate/select/interrupt closure | 通过（已测路径） | selected/non-selected、running/stopped/unknown 均不伪关闭；本 finding 发生在 interrupt admission 之前 |
| same-Agent late result/Stop | 通过 | retained attempt routing 不受 active mapping 否定 |
| action-required 单一派生权威 | 通过 | canonical candidate predicate；work item 不持久化该字段 |
| snapshot authority | 通过 | decision snapshot 只读；initial expected task 从唯一 PreparedContract 事实重建，不复制第二 snapshot |
| identity authority | 通过（结构） | 未新增第二 identity index；但 P1 可绕过现有 authority 的执行门禁 |
| rollback state | 通过 | marker 是 execution/health 上的诊断事实，不是隐藏状态机 |
| lock/transaction 边界 | 通过 | StateStore 与 PreparedContract 各自锁；文档明确不宣称跨锁事务 |
| fail-open/fail-closed | **失败** | interrupt 可读 CAS identity conflict 被错误 fail-open |
| dead state reachability | 通过（已检查路径） | F10 split-brain/orphan 有明确 retain、action-required 或 expiry retry；未发现不可达新 dead state |
| Schema/runtime/docs 一致性 | **失败** | stale interrupt claim runtime allow 与 Schema/F9 deny 语义冲突 |
| 真实平台能力 | `not_checked` | 本地 fixture 不证明真实 Hook/provider/UI 行为 |

## 6. 竞态反例

| 竞态 | 预期 | 实际 | 结论 |
| --- | --- | --- | --- |
| governed follow-up A1 pending，claim 前 active A2 | deny，保留 A1 pending | 三类 governed lifecycle 均 deny；预算/attempt/mapping 不变 | 通过 |
| interrupt A1 pending，claim 前 active A2 | deny，保留 A1 pending | CAS conflict 后 allow/fail-open；原生 target 指向 A2 | **失败，P1-1** |
| generator 初读唯一 A1，锁前新增同 target A2 | CAS conflict，不创建 pending | reconcile/fail-closed | 通过 |
| initial exact task persist-then-error | task 先删，credential 后删 | 顺序与 full equality 均满足 | 通过 |
| initial task 在 cleanup 前增加任意事实 | 不删 task/credential，写 marker | extension/timestamp/identity/claim/action 反例均保留 | 通过 |
| marker 前仅 health 更新 | task marker 可落盘，health 单调合并 | unavailable/newer/invalid/其他字段均保留 | 通过 |
| task absent 后 credential 并发变化 | exact delete conflict，保留 credential | full-record predicate 拒绝删除 | 通过 |

## 7. 验证

### 定向验证

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests.test_communication_lifecycle -k f9
Ran 12 tests
OK

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests.test_dispatch_identity -k initial
Ran 17 tests
OK

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.test_semantic_baseline.SemanticBaselineTests.test_f10_initial_preparation_semantics_anchor_exact_rollback
Ran 1 test
OK

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.test_semantic_baseline.SemanticBaselineTests.test_f9_target_lifecycle_admission_semantics_anchor
Ran 1 test
OK
```

原 9 findings 使用 14 个具名 tests 独立抽查，结果：

```text
Ran 14 tests
OK
```

新增 interrupt 反例使用 inline Python 和临时 StateStore 非破坏性复现；它不是仓库 test，因此不计入 unittest 数量。输出为 `decision=allow`、active owner A2、pending owner A1、pending 仍 `prepared`、`tool_use_id=None`。

### 跨切片与全量

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.test_dispatch_identity tests.test_state_store \
  tests.test_communication_lifecycle tests.test_wait_recovery_session_closure \
  tests.test_formal_result_parent_closure \
  tests.test_minimal_diagnostics_lightweight_groups \
  tests.test_semantic_baseline tests.test_canonical_record_schema \
  tests.test_s6_compatibility_retirement
Ran 302 tests
OK

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
Ran 378 tests
FAILED (errors=2)
```

全量精确结果是 376 passed、2 errors。两项 error 都是已知 D6 release-preflight 例外，见下一节；不能写成 full pass 或 release-ready。新增 P1 是未被现有 tests 覆盖的独立反例，因此不与当前 suite 结果矛盾。

### 静态门禁

以下命令通过：

```text
PYTHONPYCACHEPREFIX=<temporary-directory> python3 -m py_compile scripts/*.py
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
rg --files -g '*.json' -0 | xargs -0 -n1 jq empty
```

本文新增后的最终复验：

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests.test_release_preflight
Ran 5 tests
FAILED (errors=2)

python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
Plugin validation passed

git diff --check
# exit 0

F11 单文件 trailing-whitespace scan
# exit 0

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
Ran 378 tests
FAILED (errors=2)
```

release-preflight 定向测试是 3 passed、2 errors，仍只指向 D6；F11 没有新增 host-specific path、secret-shape 或 archive evidence finding。加入本文后的全量仍为精确 376 passed、2 errors。工作树路径对账确认相较审查开始基线只新增本文，未产生其他新文件或修改。

## 8. 已知 D6 例外

全量仅有以下两个既有 errors：

- `test_current_development_tree_passes_with_supported_ref`
- `test_release_requires_manifest_tag_and_marketplace_ref_to_match`

两项都只报告 `host-specific path in docs/redesign/D6-migration-and-slices.md`。本任务按禁止范围没有修复或绕过 D6。该例外不导致新增 P1，但它使全量非全绿，并独立阻止 release-preflight/full-release 表述。

## 9. not_checked

- 未安装、发布或同步测试插件。
- 未写稳定发布源、运行缓存、Hook trust、Marketplace 或 Registry。
- 未执行 cachebuster/reinstall，未检查稳定源与运行缓存哈希或非符号链接关系。
- 未创建真实测试对话；未验证真实 Plugin/Skill/Hook 加载。
- 未验证真实 `spawn_agent`、`send_message`、`followup_task`、`interrupt_agent` 参数与 Hook payload。
- 未验证真实 SubagentStart/Stop 顺序、`task_result` 可见性、same-Agent target 标识或 `previous_status`。
- 未验证 Provider 断流、mailbox 唤醒、wait/list 投影、上下文压缩恢复或 UI 终态展示。
- 未把 fixture、adapter、inline StateStore 反例或单元测试写成真实 Hook/provider/UI 证据。
- 未 stage、commit、push 或创建 PR。

## 10. 真实测试准入前提和下一步

当前不满足真实测试准入前提。最小顺序是：

1. 新建独立本地修复切片，修复 P1-1 interrupt stale-owner conflict 的错误 fail-open，并补 failure-first regression。
2. 重新运行 F9/F10 定向、原 9 findings 抽查、302 跨切片、378 全量及静态门禁；D6 若仍未授权修复，继续作为两个已知 release-preflight errors 单列。
3. 再做一次只读本地架构 gate review；只有得到 `Local architecture gate: PASSED` 才能请求下一阶段授权。
4. 用户明确授权后，从开发仓库同步测试插件；不得先写稳定源或发布。
5. 在当前项目新建真实测试对话，使用 `gpt-5.6-terra`、`high` 验证真实 Hook/provider/mailbox/UI。
6. 真实测试通过只代表测试插件环境验收，不等于 stable install、release-ready 或已发布。

因此，F11 的最终父任务动作是：**先修本地 P1，不同步插件，不等待或启动真实测试。**
