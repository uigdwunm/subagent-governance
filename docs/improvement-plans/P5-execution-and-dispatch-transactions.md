# P5：Canonical Execution Kernel 与派发事务拆分

状态：已确认，待独立对话实施。

前置：P1–P4。

## 目标

建立纯 canonical execution kernel，并把 initial prepare、retry、PreToolUse claim、PostToolUse observation 和 prepared reconciliation 迁入独立 dispatch transaction 层。

正常派发步骤不变；有意收紧异常和并发路径。

## 已确认的并发风险

当前 retry preparation 使用 `PreparedContractStore.create(..., replace=True)`，失败后又无条件 delete。同 task ref 已存在或并发 claim 时，可能覆盖或删除调用方没有创建的较新凭证。

P5 必须改成 exclusive create 和 exact `delete_if`。现有凭证意味着旧 claim、PostToolUse、reconcile 或另一个 prepare 尚未收口，不能静默覆盖。

## `governance_execution.py`

纯状态模块，迁入：

- dispatch/observation/closure plane getters
- spawn、execution、identity、platform 派生状态
- observation binding 和 positive evidence
- reliable-not-created
- canonical named update
- task/attempt lookup、iteration、require canonical task
- retained target admission/index repair
- close execution/tombstone pure mutation

不得导入 store、contract、context、dispatch 或主运行时。

本轮保留 named-operation update 语义，不同时重写为新状态机 API；目标是唯一实现和可测试转换表。

## `governance_dispatch.py`

迁入：

- task-ref occupancy/new task id
- initial task builder/post-state reconstruction
- admission checks
- initial/retry preparation
- prepared claim/restore
- persisted state claim rollback
- unclaimed cleanup
- PostTool spawn observation mutation
- prepared expiry/reconciliation

依赖 P3 stores、P4 protocol 和 execution kernel，不导入 Hook/CLI/runtime。

## 双存储 saga 原则

StateStore 与 PreparedContractStore 不是假原子事务。所有路径遵循：

```text
write first store
  -> write second store
  -> read back both
  -> success or exact-snapshot compensation
```

只能回滚能证明由本次调用写入且未被并发修改的内容。未知结果保留证据并进入 reconcile。

## Initial preparation

顺序保持：contract/context → identity → unconsumed Prepared create → State CAS insert → 双回读 → 返回。

成功时两边 task id、attempt、ref、name、mode、digest 必须一致，execution 仍为 prepared/not-observed/open，retry/recovery 为 0。

失败补偿：

- task 不存在：exact delete prepared。
- task 等于完整 initial snapshot：CAS 删除 task，再 exact delete prepared。
- 写异常后回读已不存在：视为安全删除。
- task diverged：不删除；写 rollback-incomplete/reconcile marker。
- State 无法回读或 marker 失败：保留凭证，报告 degraded。

统一 cleanup result 类型，禁止当前 `bool/dict` 混用。

## Retry preparation

前置保持：work item open、execution 未关闭、spawn reliable failed、identity unconfirmed、contract digest 相同、context 再验证、retry 0→1 或授权 1→2。

修正：

- `replace=False` exclusive create。
- 失败只 `delete_if(current == prepared)`。
- 并发 claim 后不得删除 claimed record。
- retry count 只在 claim 时写入 StateStore。

## Pre-spawn claim

Hook 只格式化 allow/deny；dispatch service 负责：

- 读取凭证、TTL、native parameters、context 二次验证
- Prepared exact claim
- State exact claim
- initial/retry admission
- retry count/tool use id/parent action
- 两边补偿和 degraded 分类

只有两边 claim 都可靠完成后才能允许 governed native spawn。

故障矩阵必须覆盖 callback 前失败、落盘后抛错、回读失败、并发修改、单边恢复失败。不得恢复他人状态。

## PostTool observation

领域函数接收 P8 提供的 normalized observation。

- success：acknowledged，写 canonical target，parent reconcile；凭证写 post observed。
- unknown：indeterminate，parent reconcile；凭证写 post observed。
- failed：无 positive evidence 时 rejected，按 retry count 决定 retry/ask/decide，并删除凭证。
- late failed 与 active/terminal positive evidence 冲突：保留 positive evidence，dispatch unknown，进入 reconcile，不删除凭证。

State 已记录但凭证收缩失败时不回滚真实 observation；reconcile 必须能幂等补齐 orphan credential。

## Reconciliation

- unclaimed initial 只有完整 snapshot 相等时清理。
- unclaimed retry exact delete，不推进 count。
- initial credential 缺失自动关闭需要全部“从未 claim/observe”的严格证明。
- claimed 超时且无 PostTool：dispatch unknown、not-started、parent reconcile、标记 post observed。
- state 已完成但 prepared 未收缩：按 exact tool-use/ref 补齐。
- 重复运行幂等；与 claim/PostTool 并发时不覆盖新事实。

## 测试

- execution update 全转换表和非法值。
- initial 每个提交/回读/补偿故障点。
- 两个并行 initial prepare。
- retry existing credential、并行 prepare、prepare/claim 竞争。
- claim 两 store callback 前后故障和补偿。
- Post success/failed/unknown/late failure。
- reconcile TTL、missing credential、orphan shrink、重复和并发。

## 验收标准

- execution kernel 无 I/O。
- dispatch 模块不导入 runtime。
- Hook 层不再包含 dispatch StateStore callback。
- retry 不覆盖或无条件删除现有 PreparedContract。
- 所有补偿基于 exact snapshot/CAS。
- ambiguous 结果保留证据并 reconcile。
- 正常 initial/retry/spawn 输出不变。
- 完整测试、编译、Plugin validator 通过；不安装发布。

## 停止条件

- 需要全局跨文件锁假装两 store 原子事务。
- 补偿必须无条件覆盖当前 state 才能通过。
- Hook response formatting 被引入 dispatch domain。
- P1 严格 state 无法表达 rollback/reconcile marker。
