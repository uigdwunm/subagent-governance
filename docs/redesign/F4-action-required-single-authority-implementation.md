# F4 action-required 单一权威实施记录

## 1. 范围与目标

本切片只处理 `S1-S6-integrated-architecture-review.md` 的 P2-2：持久化 `work_item.action_required` 与 canonical derived view 对同一责任给出不同值。保留 F1 的增长准入/reservation、F2 的 same-Agent 迟到事件路由、F3 的 replacement duplicate-risk/selection 事实和 S6 canonical-only 边界；不处理 P2-3 growth facts、P2-4 Schema 总模型或 P3 清理。

成功标准：action-required 只有一个事实权威；current/prior executions、initial claim、replacement reservation、pending lifecycle、unconfirmed success/unknown identity、running 和 unresolved duplicate/select 都由同一 predicate 判定；Stop、SessionStart、SessionEnd、diagnose 和 group/work-item snapshot 一致消费；可靠关闭后为空；recent activity 继续是独立时间窗口。

## 2. 失败先行

先只新增测试并运行：

```text
python3 -m unittest \
  tests.test_state_store.StateStoreSafetyTests.test_new_governed_record_uses_canonical_work_item_and_executions \
  tests.test_wait_recovery_session_closure.WaitRecoverySessionClosureTests.test_action_required_has_one_canonical_candidate_authority \
  tests.test_minimal_diagnostics_lightweight_groups.MinimalDiagnosticsLightweightGroupsTests.test_action_required_is_shared_by_diagnose_group_and_reliable_close -v
```

结果稳定为 `Ran 3 tests / FAILED (failures=3)`：

1. 新 canonical work item 仍持久化 `action_required=true`。
2. initial spawn 已 claim、`spawn_tool_use_id` 非空、`spawn_observation=null`、`parent_action=null` 时，同锁同步把持久字段写成 `false`，但 `_action_required_records()` 包含该 attempt。
3. 可靠关闭后同步仍保留持久字段，证明它持续作为第二份可误读状态存在。

这复现的是 stored/derived 双权威，不依赖 recent window、旧 root projection 或 attempt-first legacy reader。

## 3. 设计裁决

唯一权威是 runtime 的 `_canonical_action_required_candidate(state, record)`。它只读取 canonical work item 下的 executions、tombstone 和 execution facts；`_action_required_records()` 是该 predicate 的有序 attempt 投影，work-item snapshot 是 `any(canonical candidate)`，group 再从 work-item snapshot 聚合。

不保留持久化缓存，原因如下：

- action-required 没有独立事件或状态转换，它完全由 execution/close facts 决定；持久化只会增加同步失败面。
- `parent_action` 只是下一步，不能代表 running、调用已 claim 未观察、unknown identity、reservation 或 duplicate 责任。
- Stop 的策略仍只阻止机械运行/对账风险，但其候选集合先经过同一 action-required predicate；reportable action-required 不因此全部阻止 Stop。
- recent activity 只负责12小时展示排序，不进入 predicate、关闭或 SessionEnd 删除判断。

## 4. 实现与字段影响

- `work_item.action_required` 从新记录构造、所有显式写入和 `governance-semantics.schema.json` 的 required/properties 中删除。
- `_sync_canonical_work_item()` 不计算缓存，只维护持久聚合计数/时间，并 `pop` 历史同名字段。调用仍发生在既有 StateStore 锁内，因此不会引入离线迁移或第二套状态机。
- 旧 JSON 可继续读取，因为状态边界兼容未知扩展；只读 diagnose 忽略旧字段且绝不回写。首次相关 canonical 写入会自然移除它。没有批量迁移、版本门禁或 attempt-first fallback。
- `_action_required_records()`、diagnostic candidate、work-item snapshot、group member/group aggregation、Stop candidate gate、SessionStart 和 SessionEnd 共享 canonical predicate 或其有界聚合。
- Schema `x-semantics.derived_views.action_required` 明确 `persisted_on_work_item=false`、authority、聚合方式、关闭语义和旧字段兼容策略；Skill/runtime boundary 同步为相同自然语言规则。

## 5. 覆盖的不变量

- initial claim 无 parent action 仍 action-required；新持久记录不含缓存字段。
- current 与 prior execution 使用相同 predicate；prior 不因不是 current 或超出 recent window而丢失责任。
- 未 claim replacement reservation、prepared/claimed pending action、未解决 lifecycle observation、unconfirmed success/unknown identity、running 和 duplicate/select unresolved 都进入责任视图。
- Stop、SessionStart、SessionEnd、diagnose candidate/work-item 与 group 对同一开放事实给出一致结果。
- 所有 candidate 可靠关闭后 attempt/work-item/group action-required 均为 false/空；SessionEnd 在没有有效 tombstone 时可删除 Session JSON。
- canonical-only 保持：不读取旧 root current/`prior_attempts` 作为权威，不恢复 attempt-first diagnose arrays。

## 6. 验证

定向跨切片：

```text
python3 -m unittest -v \
  tests.test_dispatch_identity \
  tests.test_communication_lifecycle \
  tests.test_formal_result_parent_closure \
  tests.test_wait_recovery_session_closure \
  tests.test_minimal_diagnostics_lightweight_groups \
  tests.test_state_store \
  tests.test_semantic_baseline \
  tests.test_s6_compatibility_retirement
```

结果：`Ran 247 tests / OK`。

全量与门禁：

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`：`Ran 323 tests`，321 passed；仅两个已知 D6 host-specific path errors：`test_current_development_tree_passes_with_supported_ref`、`test_release_requires_manifest_tag_and_marketplace_ref_to_match`。没有 F4 新增失败。
- `PYTHONPYCACHEPREFIX=/tmp/subagent-governance-f4-pycache python3 -m py_compile scripts/*.py`：passed。
- Plugin validator：`Plugin validation passed`。
- Skill validator：`Skill is valid!`。
- `rg --files -g '*.json'` 枚举的全部仓库 JSON 逐个经 `python3 -m json.tool` 解析：passed。
- `git diff --check`：passed。

编译产生的独立系统临时 bytecode 目录已在验证后精确清除；仓库外未保留测试产物。没有安装、同步、发布、stage、commit、push 或创建 PR。

## 7. not_checked

按本切片授权，以下均为 `not_checked`：未安装或同步本地插件/稳定源/运行缓存；未修改 Hook trust、Marketplace 或 Registry；未新建真实插件对话；未验证真实 Stop/Session Hook 顺序、provider payload 或 UI 展示。它们不是本地通过项。

## 8. remaining

- P2-3：growth facts 尚未进入 S5/SessionStart 投影，本切片不处理。
- P2-4：Schema 仍不是完整 runtime-emitted canonical record 总模型，本切片只删除 P2-2 冲突字段并增加语义锚点。
- P3：Skill/runtime 其他 attempt-first/legacy 残余清理不在本切片范围。
- 两个 D6 host-specific path 全量基线错误保持原状，不在 F4 修复。
