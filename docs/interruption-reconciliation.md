# 中断与重启对账

Codex 进程重启、工具断流或 worker 中断可能使平台状态与治理状态暂时不同步。插件只根据当前可观察的精确事实推进生命周期，不从 transcript、summary 或推测恢复状态。

## 平台响应

`list_agents.agent_status` 与 `interrupt_agent.previous_status` 接受：

- 已知字符串标签；
- 只有一个已知键且值不是 `null|false` 的对象标签。

多标签对象、未知结构、嵌套正文和 summary 都不建立状态事实。

interrupt 结果分为两个维度：

- `call_observation=success|failed|unknown`：原生调用是否被接受。
- target observation：调用前或调用后的最小目标状态事实。

处理规则：

- `previous_status=running`：调用已交付，但不证明目标已经停止；保持执行状态并进入 reconcile。
- `previous_status=not_found`：只表示调用时目标不存在；只有身份和已有精确观察共同满足当前收口条件时才能推进。
- `status=stopped|completed`：目标已不活跃，等待通知或父处置。
- `status=interrupted|cancelled|canceled`：目标已确认中断，等待父处置。
- `pending_init`、未知标签或格式错误：保持 unknown/reconcile，不自动重派。

## 精确空列表

对 canonical target 发起的 exact `list_agents` 查询返回空顶层 `agents`，只证明目标在该次检查时 absent。它不能单独证明业务完成，也不能替代原生终态通知。

## 重启后的处理顺序

1. SessionStart 读取当前 StateStore。
2. 对账过期的 prepared/claimed 操作。
3. 根据 action-required 摘要选择等待、精确查询、恢复、中断或父处置。
4. 已看到平台终态但通知未到时，保持 `await_notification`。
5. 收到原生终态通知后记录 sender、task、attempt 和 terminal status。
6. 父 Agent 阅读原生最终回复并决定关闭或通过 `business_resume` 继续。

## 外部确认的 interrupted

当父 Agent 通过外部只读事实精确确认某个 execution 已被中断时，可以使用：

```bash
python3 scripts/subagent_governance.py \
  --reconcile-interrupted-attempt \
  --session <session_id>
```

stdin 必须包含精确 `task_id`、`attempt`、`target` 和确认理由。入口只更新匹配的当前 execution，不关闭 work item，不产生业务结果。

## 禁止行为

- 不把进程重启解释为 Agent 未创建。
- 不因 `pending_init` 或空列表自动重派。
- 不从 summary 或旧消息正文推断终态。
- 不把平台终态转换成业务完成。
- 不绕过 exact target、task 和 attempt 绑定。
