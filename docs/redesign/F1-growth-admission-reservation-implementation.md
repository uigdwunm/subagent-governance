# F1 关闭准入、Replacement Reservation 与精确回滚实施记录

日期：2026-08-14

## 范围

本切片只修复 `S1-S6-integrated-architecture-review.md` 的 P1-1 与 P1-2：关闭单向性、replacement reserved candidate 容量、PreToolUse 锁内最终准入，以及5分钟未 claim replacement 的精确幂等回滚。

不修复 P1-3/P1-4/P2/P3；不增加后台 scheduler、第二套状态机、protocol version 或 migration gate。唯一修改源是开发仓库；未安装、发布、同步缓存、修改 Hook trust/Marketplace/Registry、stage、commit、push、PR 或外部对话。

## 失败先行

修改运行时代码前，在 `tests/test_dispatch_identity.py` 新增7个 F1 反例并执行：

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.test_dispatch_identity.DispatchIdentityTests.test_tombstoned_work_item_rejects_replacement_prepare_without_resurrection \
  tests.test_dispatch_identity.DispatchIdentityTests.test_closed_execution_rejects_retry_prepare_and_prepared_retry_claim \
  tests.test_dispatch_identity.DispatchIdentityTests.test_replacement_reservation_consumes_capacity_and_is_unique_before_claim \
  tests.test_dispatch_identity.DispatchIdentityTests.test_replacement_claim_rechecks_locked_capacity_and_rolls_back_own_reservation \
  tests.test_dispatch_identity.DispatchIdentityTests.test_replacement_claim_after_close_denies_without_native_spawn_fact_or_resurrection \
  tests.test_dispatch_identity.DispatchIdentityTests.test_expired_replacement_rolls_back_exact_reservation_and_is_idempotent \
  tests.test_dispatch_identity.DispatchIdentityTests.test_expired_replacement_does_not_delete_concurrently_changed_execution

Ran 7 tests
FAILED (failures=6, errors=1)
```

失败分别证明：tombstoned replacement prepare 被放行；closed retry prepare/claim 被放行；replacement 没有 reservation；claim 不重查 candidate cap；prepare 已提前推进 current，导致关闭边界冲突；replacement 过期不清理；并发变化被静默跳过。

修正测试中历史固定时间与真实 PreToolUse TTL 的交互后，同一7项反例全部通过；固定旧时间只保留在专门的过期测试中，避免因错误的 TTL 分支形成假阳性。

关键路径静态复核随后补充“StateStore 已持久化 reservation、但写后回读报告失败”的 prepare rollback 反例。修复前单测稳定为 `Ran 1 test / FAILED (failures=1)`，残留 attempt 2 reserved execution；实现 operation-aware state rollback 后该项通过。

SessionEnd 边界复核另补充 reservation 必须维持 `action_required` 的反例。修复前单测稳定为 `Ran 1 test / FAILED (failures=1)`，SessionEnd 会把只含未 claim reservation 的状态误判为无待办并删除；将 reservation 纳入 canonical action-required 派生后该项通过。三批失败先行运行时反例合计9项。

父任务独立验收随后复现了更窄的 claim 半提交：`StateStore.update()` 已真实持久化 replacement claim，随后才抛出 readback/返回错误。先新增 replacement、initial 与 retry 的三个反例，执行 `Ran 3 tests / FAILED (failures=3)`。失败状态均为 Hook deny 但 canonical execution 保留 `spawn_tool_use_id`；replacement 还保留 `current_attempt`、duplicate、disposition 与 growth claim facts，而 PreparedContract 已被 unclaim，因而无原生 spawn 却形成 split-brain。修复后，三个精确恢复反例和一个“持久化后额外并发写入”degraded 反例均通过；后者断言不覆盖较新字段且 PreparedContract 保持 consumed，避免重复 native spawn。

第二次父验收复现 `StateStore.update()` 在 claim callback 前立即失败：initial execution 保留但唯一 PreparedContract 被删除，形成既不能重试也没有 native call 事实的悬空 task。先新增 initial/replacement/retry 三个 pre-callback 反例；修复前 initial 与 retry 稳定报错读取不到 PreparedContract，replacement 则因旧 cleanup 本身再次触发同一个 mock 而偶然保留凭证，不能作为正确状态证明。现统一为：仅当 callback 前的 canonical task 快照仍逐字段匹配时，三类 operation 都 unclaim 并保留同一 task/ref 供重试；另有并发反例断言任何字段变化时 deny + degraded、PreparedContract 保持 consumed。

## 状态机设计

```text
replacement prepare
  -> PreparedContract(dispatch_operation=replacement_spawn,
       source_attempt, reservation_id, reservation_snapshot_sha256,
       replacement_authorization)
  -> canonical reserved execution(replacement_reservation)
  -> 不改变 current_attempt/duplicate/disposition/replacement count/growth facts

PreToolUse claim（StateStore 同一锁内）
  -> lifecycle=open
  -> source execution 存在且未关闭、仍是 current source
  -> 唯一 reservation identity + 完整 execution snapshot 匹配
  -> live/reserved candidate count <= 2
  -> 原子移除 reservation，提交 current/duplicate/disposition/growth，写 spawn claim

claim persist-then-error
  -> claim callback 保存完整 canonical task 的 pre/post 快照
  -> 当前 task 精确等于本次 post-state：恢复完整 pre-state，PreparedContract 回到未消费，可用原 task ref 重试
  -> 当前 task 已等于 pre-state：按未持久化失败的既有清理路径处理
  -> 其他任意字段变化：不覆盖，保留已消费凭证并明确 degraded

claim pre-callback error
  -> 当前 task 精确等于发送前快照：unclaim PreparedContract，保留原 canonical task/ref 供重试
  -> callback 已进入但未形成 post-state：按既有 operation-specific admission failure cleanup
  -> 发送前快照缺失或任意字段变化：不覆盖，保留已消费凭证并明确 degraded

unclaimed 5分钟过期
  -> snapshot 完全匹配：删除 reserved execution，再删除 PreparedContract
  -> 重放：无记录，幂等返回0
  -> 已 claim/启动/结果/关闭/身份不匹配/并发变化：不删除 execution，明确 conflict/degraded
```

initial、replacement 与 spawn retry 的最终 claim 都使用同一 open/unclosed admission。replacement 与 retry preparation 也提前执行该 admission，但 preparation 快照不代替 claim 锁内判断。

## 并发与回滚不变量

- 未 claim replacement 是 reserved business candidate；同一 work item 最多一个 reservation。
- old live/unknown candidate 加一个 reservation 已达到 two-candidate cap；第三个 live/reserved candidate 不能 claim。
- reservation execution 由 `reservation_id + task_ref + source_attempt + created_at + reservation_snapshot_sha256` 精确识别。摘要覆盖 reserved execution 的完整规范化快照，任一并发字段变化都会阻止删除。
- prepare 不修改 source execution 或 work-item growth facts；正常 expiry 只删除自身 reservation，因此 canonical work item/source execution 恢复为 preparation 前的逐字段语义。
- 未 claim reservation 是 canonical action-required 状态；SessionEnd 不得把仅因尚未 claim 而仍需处理的 reservation 当作可删除状态。
- claim 在 PreparedContract 先认领、StateStore 后提交；若 StateStore 在回调执行后报错，只有 canonical task 逐字段等于本次 claim 保存的完整 post-state 才能恢复完整 pre-state，随后 unclaim PreparedContract 并保留同一 task ref 供重试。callback 已完整执行但 state 仍是 pre-state、或 callback 尚未执行且发送前快照仍精确匹配时，也 unclaim 并保留同一 task/ref；callback 已进入但未形成 post-state 仍走既有 operation-specific admission failure cleanup。任何其他差异、快照缺失或回滚失败都进入明确 deny/degraded，不覆盖较新 state，也不重新开放已消费凭证。
- lifecycle/关闭 admission 失败不写 `spawn_tool_use_id`，不清除 tombstone，不把 execution 改回 open/running。
- reconcile 不再捕获冲突后静默 `continue`；无法证明回滚安全时抛出有 task/attempt 上下文的 `PreparedContractConflictError`，SessionStart/SessionEnd 因而进入既有 degraded 路径。

## 语义与文档

- `governance-semantics.schema.json` 的 `x-semantics.spawn_admission` 固定双门禁、two-candidate cap、单 reservation、claim 原子提交、persist-then-error 的精确 pre-claim 恢复、pre-callback 的精确凭证复用与精确 expiry。
- 开发 Skill 与 runtime boundary 明确 reservation 容量、关闭单向性、claim 提交点和 unsafe rollback degraded。
- P1-3/P1-4/P2/P3 的代码、Schema 与文档语义未在本切片扩展处理。

## 验证

已执行并通过：

```text
F1 运行时定向反例：17 tests OK
tests.test_dispatch_identity：53 tests OK
communication/hook/state/formal-result/session 定向：134 tests OK
dispatch/communication/session/state/formal-result/S1-S6 相关回归：254 tests OK
五个 scripts/*.py：py_compile passed
Plugin validator：Plugin validation passed
Skill validator：Skill is valid
当前4个修改/新增 JSON：python3 -m json.tool passed
git diff --check：passed
```

完整回归：

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
Ran 303 tests
FAILED (errors=2)
```

其中301项通过，只有两个用户要求按基线保留的 D6 host-specific path release-preflight errors：

- `test_release_preflight.ReleasePreflightTests.test_current_development_tree_passes_with_supported_ref`
- `test_release_preflight.ReleasePreflightTests.test_release_requires_manifest_tag_and_marketplace_ref_to_match`

二者均由 `release_preflight.PreflightFailure: host-specific path in docs/redesign/D6-migration-and-slices.md` 触发。本切片没有修改该 D6 host-specific path，也没有把完整回归表述为全绿。

## 修改文件

- `scripts/subagent_governance.py`
- `tests/test_dispatch_identity.py`
- `tests/test_semantic_baseline.py`
- `schemas/governance-semantics.schema.json`
- `skills/subagent-governance/SKILL.md`
- `skills/subagent-governance/references/runtime-boundaries.md`
- `docs/redesign/S1-S6-integrated-architecture-review.md`
- `docs/redesign/F1-growth-admission-reservation-implementation.md`

## not_checked

- 当前开发工作树的真实插件加载与七类 Hook enabled/trusted；
- provider 的 native spawn response、PreToolUse/PostToolUse/SubagentStart 真实时序；
- 真实 Agent spawn、replacement/duplicate/select/interrupt；
- send/followup/list/interrupt 的真实投递、乱序、断流与 terminal shape；
- Stop、SessionStart/SessionEnd、compact/resume 的真实 Hook 顺序；
- N/N-1 安装、升级与回滚。

以上项目因本切片禁止安装、缓存同步、Hook trust 修改和外部真实测试对话而保持 `not_checked`，不能由单元测试推导为通过。

## 未执行事项

未安装、发布或同步任何插件/缓存；未修改稳定发布源、运行缓存、Hook trust、Marketplace、Registry 或外部对话；未 stage、commit、push 或创建 PR。未执行真实插件加载、真实 Agent spawn/provider 时序或 N/N-1 回滚测试。
