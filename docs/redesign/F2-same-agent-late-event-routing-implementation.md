# F2 Same-Agent 迟到事件路由实施记录

> 2026-08-14 状态：本文保留为历史实施记录。SubagentStart 当前是 unbound
> observation，SubagentStop 不消费未知 `task_result` 扩展；旧 late-event
> Hook routing 不能作为当前 correctness 保证。

日期：2026-08-14

## 范围

本切片只修复 `S1-S6-integrated-architecture-review.md` 的 P1-3：same-Agent business resume 的 A2 Start 推进 active target index 后，A1 的迟到 Stop 或正式结果不得被拒绝，也不得写坏 A2。

唯一修改源是开发仓库。未修改稳定发布源、运行缓存、Hook trust、Marketplace、Registry、外部对话或其他项目；未安装、发布、同步缓存、stage、commit、push 或创建 PR。F1 的 spawn admission/reservation 状态机、P1-4、P2 与 P3 不在本切片范围。

## 失败先行

先在 `tests/test_formal_result_parent_closure.py` 增加 `test_same_agent_resume_routes_late_stop_and_result_to_retained_attempt`，场景为：A1 blocked，经过真实 local business-resume claim/PostToolUse 后创建 A2；A2 的精确 Start 把 `agents[target]` 推进到 attempt 2；随后重放携带 A1 `task_id + attempt` 的合法 Stop/TaskResult。

修复前执行该单测稳定失败：Stop 先按 active mapping 选择 A2，随后把 A1 的 payload mismatch 解释为 A2 的结果协议缺口。失败断言为预期 `stored`，实际得到“managed attempt 已停止但没有合法结构化结果；应使用 result_correction 补交本次结果”。

同一反例还覆盖：无精确身份 Stop、缺少一个 identity 字段的 payload、指向不存在 attempt 的 payload 都不允许 fallback；A2 自己的合法 Stop/result 仍可正常写入。

父任务独立验收发现兼容回归后，先在 `tests/test_governance.py` 增加两个反例：`test_stale_missing_task_mapping_is_removed_before_unmanaged_stop` 证明 `agents[target]` 指向完全不存在的 task 时恢复原有“清理失效映射后按 unmanaged 放行”的诊断语义；`test_stale_mapping_cleanup_rechecks_mapping_and_task_under_lock` 在初读与清理写锁之间分别注入映射改指和原 task 出现。修复前两项均落入“retained target provenance 不唯一”并永久保留失效映射；修复后前者删除精确旧映射，后者均保留新状态并提示父任务对账。

## 身份与路由不变量

- `task_id` 仍是 work item 唯一权威；`task_id + attempt` 仍是 execution 与正式结果唯一边界。
- `agents[target]` 是 active target index，只辅助当前 Start、通信和平台查找；它不能覆盖 retained execution 自己保存的 `agent_id/canonical_task_path` provenance。
- 显式 TaskResult 固定按 `payload.task_id + payload.attempt -> retained execution -> exact target provenance` 验证。active index 指向另一 attempt 不构成拒绝理由。
- 有精确 TaskResult 的 SubagentStop 使用相同路由。payload 与 target provenance 冲突、身份缺失或 execution 不存在时，只返回未关联的有界诊断，不更新任何另一 attempt 的 `execution_status`、`business_result`、`result_protocol_status`、`result_storage_status` 或 `parent_action`。
- 没有精确 identity 的 SubagentStop 只在 retained target provenance 唯一时保留既有结果纠正路径；same target 的 A1/A2 同时保留时，它是含糊事件，不能写 active/current attempt。
- same-Agent business resume 是顺序复用而非并发 duplicate：A1 的迟到正式结果不会把 A2 的 duplicate 或 parent-action 投影改写。不同 target 的既有 late-result duplicate 路径保持不变。
- 当没有 retained provenance 且 `agents[target]` 指向完全不存在的 task，兼容清理只在 `StateStore.update()` 写锁内再次确认映射仍逐值等于初读值、目标 task 仍不存在后才删除。任一事实在检查期间变化即不删除，并交父任务对账；该例外不适用于 canonical managed task 缺失 execution、历史/non-managed 映射、完全 unmapped 或多 retained 的 same-target Stop。

## 实现

- `scripts/subagent_governance.py` 增加 retained target provenance 查询；`submit_task_result()` 不再要求 payload identity 等于 active mapping，而是验证其精确 retained execution。
- SubagentStop 先解析可观察的 payload identity。精确身份按 retained execution 路由；不完整或冲突 identity 不回退；无身份仅在 provenance 唯一时进入旧的 protocol-gap 路径。
- protocol gap 写入前也复核目标 execution 的 retained provenance，防止 StateStore 锁内 active mapping 再次前移时污染其他 attempt。
- 结果路由后仅对不同 retained target 的非 current late result 保留既有 duplicate 投影；same target A1/A2 不产生虚假 duplicate。
- 恢复 `retained=[]` 且 mapping task 完全缺失时的精确清理兼容分支。清理回调在锁内比较初读 mapping，并复查 task 仍不存在；mapping 改到其他 execution 或 task 在期间出现时返回有界对账诊断，不删除任何当前 mapping。
- `governance-semantics.schema.json` 增加 `late_event_routing` 机器语义锚点；Skill 与 runtime boundary 说明 active index 和 retained provenance 的分工。

## 状态转换

```text
A1 retained(target=T) -> business_resume -> A2 Start(target=T)
  -> agents[T] = active A2

A1 TaskResult(task_id=W, attempt=1, target=T)
  -> retained W/A1 -> validate T belongs to A1 -> write result-W-attempt-1
  -> A2 remains unchanged

Stop without exact identity while A1 and A2 both retain T
  -> unassociated bounded diagnostic -> no execution mutation

A2 TaskResult(task_id=W, attempt=2, target=T)
  -> retained W/A2 -> normal formal-result path
```

## 修改文件

- `scripts/subagent_governance.py`
- `tests/test_governance.py`
- `tests/test_formal_result_parent_closure.py`
- `tests/test_semantic_baseline.py`
- `schemas/governance-semantics.schema.json`
- `skills/subagent-governance/SKILL.md`
- `skills/subagent-governance/references/runtime-boundaries.md`
- `docs/redesign/S1-S6-integrated-architecture-review.md`
- 本文件

## 验证

已执行并通过：

- F2 失败先行反例在修复前失败，修复后：`python3 -m unittest -v tests.test_formal_result_parent_closure.FormalResultParentClosureTests.test_same_agent_resume_routes_late_stop_and_result_to_retained_attempt tests.test_formal_result_parent_closure.FormalResultParentClosureTests.test_same_target_result_before_new_attempt_start_stays_on_old_attempt`，`2 tests OK`。
- 失效 mapping 清理失败先行用例在修复前失败，修复后连同 unmapped 与 S6 canonical 边界定向回归：`9 tests OK`；更广的 formal-result、business-resume、dispatch、communication、session/state、S6、legacy retirement、fixture 与语义锚点组合回归：`230 tests OK`。
- `python3 -m py_compile scripts/*.py`：通过。
- `python3 -m json.tool schemas/governance-semantics.schema.json`：通过。
- Plugin validator：`Plugin validation passed`。
- Skill validator：`Skill is valid!`。
- `git diff --check`：通过。

最终全量 unittest 的实际结果在下方“已知基线 errors”记录；本切片不修改该 D6 release-preflight 问题。

### 已知基线 errors

`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` 最终运行 308 项，其中 306 项通过，只有以下两个已有 error：

- `test_release_preflight.ReleasePreflightTests.test_current_development_tree_passes_with_supported_ref`
- `test_release_preflight.ReleasePreflightTests.test_release_requires_manifest_tag_and_marketplace_ref_to_match`

两者均为 `PreflightFailure: host-specific path in docs/redesign/D6-migration-and-slices.md`。它们不由 F2 引入，也不在本切片范围；新增测试后的最终复跑确认仍只有这两个 error。

## not_checked

- 真实 SubagentStop 是否携带 `task_result`，以及该 payload 是否可稳定携带 `task_id + attempt`；代码只消费已观察到的对象字段，未假定平台会提供它们。
- 真实 same-Agent business resume、Start/Stop/result 的乱序投递、Provider 断流和 Hook 加载。
- 插件安装、缓存同步、Hook trust、真实新对话、N/N-1 升级或回滚。

## 未执行事项

本切片不执行安装、发布、缓存同步、稳定源更新、Hook trust 修改、stage、commit、push 或 PR；不进行真实插件测试或外部对话操作。
