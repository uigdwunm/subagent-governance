# 中断与 reconcile 边界

当前 state-v9 实现同时覆盖 dispatch identity 与最小 lifecycle：prepare、Pre claim、explicit exact-target confirm、明确 dispatch result、exact observation、terminal、interrupt result 和 parent close。

native spawn 返回后、confirm 前父任务中断时，task 保持 `claimed/unbound`：

- 不自动 retry；
- 不创建 attempt；
- 不用 `list_agents`、task name、时间、summary、transcript 或 child final 补绑；
- exact target 无法从当前 native return 机械取得时停止并报告。

first bind wins。相同 target confirm 重放幂等；不同 target 或 task/ref 不匹配保留已可靠身份并进入 reconcile。reconcile reason 有界，不保存冲突 target、业务正文或原生 response。

bind 后的 unknown normal-message delivery、unknown platform observation 和 unknown interrupt result 分别只写 `delivery_unknown`、`platform_observation_unknown` 和 `interrupt_unknown`。它们不触发自动重发、重查、补绑或 retry。已有可靠 terminal fact 时，后到的未知或 active 观察不能降级该事实。

原生 `interrupt_agent` 的明确 failed/inactive 机械结果通过 `record-interrupt-result` 写入；failed 保持 bound，inactive 建立 terminal fact。不得把模糊 success、not-found、时间或 list 结果自行解释为 inactive。

terminal status 冲突保留首个可靠 terminal fact并进入 `terminal_status_conflict` reconcile。父 Agent 最终通过 `close-task` 显式关闭；close 不调用 interrupt，也不把 reconcile 自动解释为成功。相同 close reason 重放幂等，不同 reason 不覆盖首次 close。
