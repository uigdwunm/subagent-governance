# P6：通信、恢复、中断、Business Resume 与终态闭环

状态：已确认，待独立对话实施。

前置：P1–P5。

## 目标

拆出 communication rendering 和 managed lifecycle transaction；修复 business resume 没有完成 canonical identity 转移、父处置留下 stale agents index 等正确性问题。

## 已确认的新缺陷

当前 business resume 创建 N+1 后更新 `work_item.current_attempt`，但没有把 dispatch target/tool-use identity 和 `agents[target]` 转移到 N+1，也没有可靠关闭 source attempt。后续 communication、list_agents 和 terminal notification 可能仍定位 N。

当前 parent close 会关闭 executions 和写 tombstones，但不清理精确指向该 task 的 agents mapping。

## `governance_communication.py`

纯输入/渲染模块，拥有：

- strict communication/interrupt request parse
- user message
- native message
- operation-to-native-tool mapping

未知领域字段拒绝；不从正文猜 operation。

Business resume message 必须明确新 `task_id/attempt/task_ref/target` 和终态通知身份，使 resumed Agent 不依赖旧历史猜 attempt。

## `governance_lifecycle.py`

迁入：

- pending action build/match/find/reconcile
- communication/interrupt/recovery/resume preparation
- managed target admission use
- claim transaction
- business resume attempt creation
- lifecycle call observation
- interrupted reconciliation
- normalized agent status application
- terminal notification
- parent disposition

不解析原始 Hook JSON，不生成 allow/deny JSON，不导入 runtime。

## Pending variants

严格使用 P1 变体。Business resume 要求 full resume contract、digest、verification、prepared-on-attempt；recovery 的第二次授权必须显式，其他 operation 不得携带无关字段。

## Preparation

- normal message 不绕过 platform error recovery。
- platform recovery 仅 observation error；budget 0→1、授权 1→2、2 耗尽。
- interrupt 已中断/关闭时拒绝。
- business resume 要求 exact terminal notification 或 current `resume_delivery_failed`、parent decide、model 不变、context 验证、新 ref。
- preparation 只把 prepared pending 放在 source/current owner，不创建 N+1、不关闭 source。

## Claim commit witness

当前完整 session before/after 比较会把无关 task 并发更新误判为 ambiguous。改用受影响投影：

- `tasks[task_id]`
- `agents[target]`
- 本次 tombstone keys
- current attempt
- pending tool-use identity

投影等于 committed 即已提交；等于 before 即未提交；其他才 ambiguous。

## Business resume 原子 identity 转移

在一个 StateStore CAS 中：

1. 重验 source/current/pending/context。
2. 可靠关闭 source attempt，reason=`business_resume`，写 tombstone。
3. 创建 N+1，`task_name=null`。
4. 新 execution 写 resume contract summary/digest。
5. dispatch plane 进入 claimed，target=原 Agent，tool-use id=followup call。
6. pending action 移到 N+1 并 claimed。
7. `agents[target]` 指向 N+1。
8. work item current attempt=N+1。

这样不留下两个 open attempts 共享 target。

## Call observation

- normal message：移除 pending，只更新时间。
- recovery success/unknown/failed：分别 wait/reconcile/ask-user，budget 不回滚。
- business resume success：dispatch acknowledged、not-started、wait。
- resume unknown：dispatch indeterminate、reconcile。
- resume failed：dispatch rejected、N+1 reliable close=`resume_delivery_failed`、decide disposition；不复活 source。
- interrupt 只有可信 inactive 证据才终态；not-found 单独不够。

Delivery failed 后允许从 current closed attempt 受限地再次 resume，或父方 close；一般 closed target 不能复活。

## Agent status 与 terminal notification

- normalized exact list_agents status 只更新唯一 dispatch provenance。
- resume 后同 target 必须更新 N+1，不得命中 N。
- weak list fact 不覆盖 terminal notification。
- terminal envelope 精确要求 sender/task/attempt/status；相同幂等、冲突 reconcile、closed ignored。
- resumed Agent 使用消息中的 N+1 identity。

## Parent disposition

- 只能处置 current attempt。
- active targets 必须先 interrupt。
- close task 关闭所有 attempts、写 tombstones、work item tombstoned。
- 同 transaction 删除精确指向该 task 的 agents mapping；并发已改到其他 task 的 mapping 不删除。

## Fail-open

- unmanaged 原生路径继续放行。
- normal message/interrupt 的明确 storage unavailable 可 fail-open。
- business resume/recovery 的 unavailable 或 ambiguous claim 必须拒绝。
- semantic conflict 不是治理故障，不能按 unmanaged 降级。

## 测试重点

- business resume source close、新 target/tool-use/index/current attempt。
- resume message identity 和 N+1 terminal notification。
- list_agents 更新 N+1。
- delivery failed 后再次 resume/close。
- unrelated task concurrency 不误判 claim。
- target task concurrency 进入 ambiguous。
- recovery budget、interrupt not-found、pending TTL/Post 缺失。
- terminal notification 正常/幂等/冲突/迟到。
- parent close exact agent cleanup。

## 验收标准

- communication 与 lifecycle mutation 分离。
- resume identity 完整且原子。
- source/N+1 不同时 open。
- resumed Agent 明确知道新身份。
- claim commit 不受无关 session 更新影响。
- parent close 不留 exact stale mapping。
- runtime 不再包含 lifecycle StateStore callbacks。
- 完整测试、编译、Plugin validator 通过；不安装发布。

## 停止条件

- v6 Schema 无法表达 same-Agent execution 的 `task_name=null`。
- identity 转移必须分成多个非原子 StateStore 写入。
- delivery failure 只能靠复活旧 attempt 才能继续。
- 平台原始 response 解析被引入 lifecycle domain。
