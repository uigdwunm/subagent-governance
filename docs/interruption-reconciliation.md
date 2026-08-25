# 中断与 reconcile 边界

当前第一纵向切片只实现 dispatch identity：prepare、Pre claim、explicit exact-target confirm 和明确 failed/unknown dispatch result。

native spawn 返回后、confirm 前父任务中断时，task 保持 `claimed/unbound`：

- 不自动 retry；
- 不创建 attempt；
- 不用 `list_agents`、task name、时间、summary、transcript 或 child final 补绑；
- exact target 无法从当前 native return 机械取得时停止并报告。

first bind wins。相同 target confirm 重放幂等；不同 target 或 task/ref 不匹配保留已可靠身份并进入 reconcile。reconcile reason 有界，不保存冲突 target、业务正文或原生 response。

当前切片尚未实现 interrupt result 的持久写 API。原生 `interrupt_agent` 仍可由父 Agent 使用，但不能据此声称 state-v9 lifecycle 已完整 terminal/closed。该能力将在 cutover 的最小 lifecycle 阶段实现。
