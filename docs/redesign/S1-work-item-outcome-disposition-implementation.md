# S1 work-item / outcome / disposition 实施记录

## 范围

本记录只覆盖 D6 S1「四层最小闭环」在开发仓库内的本地实现：canonical `work_item` / `executions`、正式 outcome、complete 的 pending 验收、显式 disposition，以及同锁 tombstone。没有安装、发布、缓存同步、真实对话或 Hook trust 写入。

## 失败先行基线

先在 `tests/test_state_store.py` 和 `tests/test_formal_result_parent_closure.py` 添加以下最小断言，再运行：

```bash
python3 -m unittest -v tests.test_state_store tests.test_formal_result_parent_closure
```

基线结果：51 tests 中 7 errors。新建 governed record 不含 `work_item`，canonical outcome 路径不含 `executions`，所以读取 `work_item` / `executions["1"]` 均为 `KeyError`。这证明旧 root/current + `prior_attempts` 形状尚未满足 S1。

## 实际修改

- `governance-semantics.schema.json` 新增 S1 的 `work_item_lifecycle`、`work_item`、`execution_record` defs，以及 `canonical_record` 机器语义锚点；明确 root current / `prior_attempts` 是非权威兼容投影。
- `_initial_task_record()` 直接建立 `tasks[task_id].work_item` 与 `executions["1"]`；根 current 和 `prior_attempts` 由 canonical execution 投影生成。
- 结果提交、结果重新关联和存储 unavailable 标记均在同一 StateStore 写入中惰性迁移旧 managed record，并只写 canonical execution；兼容 root/proir projection 在同一写入中刷新。
- `complete` 写入 `stopped + valid + available + pending + accept_result`；`blocked`、`failed`、`needs_decision` 写入 stopped execution，保持 work item `open`，且 acceptance 保持 `null`。
- `accept_result` 在同一 StateStore 锁/CAS 中校验 current complete、关闭 execution、生成 tombstone，并写 `work_item.lifecycle=tombstoned` 与 `last_disposition`。存在 running candidate 时仍返回精确 interrupt target，提交不产生 accepted/open 中间态。
- 同 payload 重放仍为 idempotent；不同合法 payload 保留第一份权威结果并标记 conflict；权威结果存储或关联不可用时保持 `business_result=null`、`result_protocol_status=valid`、`result_storage_status=unavailable`。

## 父验收修正：select_attempt 不得覆盖 canonical record

父验收发现旧 `_replace_current_attempt()` 会将 `tasks[task_id]` 替换为 selected execution 的扁平副本，再用 `prior_attempts` 保存其余 execution。该写法会删除 canonical `work_item + executions`，违反 S1 的单一权威来源。

先新增 `test_select_attempt_preserves_canonical_work_item_and_all_executions` 并单独运行。失败基线为测试在 select 后读取 `task["work_item"]` 抛出 `KeyError`，稳定证明 canonical record 已被扁平替换。

修正后，`_select_canonical_current_attempt()` 仅修改 `work_item.current_attempt`，保留完整 `executions` 映射，并调用 `_sync_legacy_task_projection()` 刷新 root current / `prior_attempts`。select 分支也在同一事务写入 `work_item.last_disposition`、`action_required` 与时间。新增断言覆盖：选中 attempt、`executions` 保留所有 attempt、root current 与 `prior_attempts` 均为与 canonical 相符的兼容投影。

针对 S1 直接写路径的复查结论：`submit_task_result`、`reassociate_task_result`、storage-unavailable 标记和全部 `apply_parent_disposition` 分支均通过 canonical execution 写入/投影刷新；不再存在 S1 disposition 将整个 task 覆盖为平面 execution 的路径。`_create_resume_attempt()` 仍有扁平替换，但它属于明确排除的 S3 business resume 路径，本次未改动。

全量回归暴露既有 select 后 interrupt 收口仍持有旧 `prior_attempts` 投影对象。为使该已存在的关闭 helper 不绕过 canonical execution，做了最小兼容接线：它按 task/attempt 重新定位 canonical execution 后再关闭、写 tombstone 并刷新投影；未改变 interrupt、平台恢复或派发语义。

## S1 状态转换

```text
new task -> work_item(open) + executions["1"]
complete outcome -> execution(stopped, complete, pending) + work_item(open)
accept_result -> execution(accepted, closed) + work_item(tombstoned) + tombstone
blocked|failed|needs_decision -> execution(stopped) + work_item(open)
storage unavailable -> execution(valid, unavailable, business_result=null) + work_item(open)
```

## 验证证据

- 初始 S1 定向：`python3 -m unittest -v tests.test_state_store tests.test_formal_result_parent_closure`：通过，51 tests。
- 父验收修正后定向回归：`python3 -m unittest -v tests.test_state_store tests.test_formal_result_parent_closure tests.test_communication_lifecycle tests.test_dispatch_identity`：通过，117 tests。
- `python3 -m py_compile scripts/subagent_governance.py`：通过。
- `git diff --check`：通过。

全量验证结果：

- `python3 -m unittest discover -s tests -v`（父验收修正后）：241 tests 中 239 通过；仅 2 个既有 release-preflight tests 失败，均为 `docs/redesign/D6-migration-and-slices.md` 中已存在的 host-specific path 被 public-text 扫描拒绝，和 S1 运行时/Schema/测试改动无关；未新增失败。
- Plugin validator：通过。

父验收修正后的命令将重新运行并以本轮正式交付为准。

## not_checked 与剩余事项

- `not_checked`：真实 SubagentStop 结构化 payload、真实 Hook 加载与投递、平台 Start/Stop 时序、缓存安装、N/N-1、Codex UI/恢复行为。
- S2 以后才处理派发与精确身份主路径；S3 处理 business resume/replacement；S4 处理平台恢复、等待和会话关闭；S5 切换 diagnostics/group；S6 才能退役旧 root/current/`prior_attempts` 投影。
- 本 S1 未修改 hooks.json、Skill、诊断/group、派发、SubagentStart、business resume/replacement 或 Session/Stop 平台恢复路径。为保持现有消费者兼容，只新增 canonical 到旧 root/current/`prior_attempts` 的同锁投影。
