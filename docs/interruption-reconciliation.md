# 中断、unknown 与 reconcile 边界

当前 state-v11 沿用 prepare → Pre claim → exact-target confirm → 生命周期 → parent close。

## 派发与身份冲突

原生 spawn 返回后、confirm 前中断，任务保持 claimed/unbound。只接受本次原生返回的 exact target；不从 list、task_name、时间、summary、transcript 或 child final 补绑，不自动重派。

first bind wins。派发结果未知、missing claim、身份或终态冲突仍进入 reconcile，保留首个阻断原因及已有可靠事实。后续通知不能自动补绑或解锁。该异常只停止依赖缺失身份／冲突事实的操作；继续其他已授权且不依赖它的工作。

## 已绑定任务的未知回执

普通消息、平台观察、中断的 unknown 分别记录在 unknown_facts 的 delivery_unknown、platform_observation_unknown、interrupt_unknown 中。对象非空且最多三项，每项只有首次 observed_at；重复同类输入不改时间。它不保存调用历史，也不表示当前 Agent 必然未知。

任务保持 bound。消息或中断回执 unknown 本身不停止原生等待；等待节奏、按 target 静默核对及上下文恢复规则以 [Skill 的等待与通信](../skills/subagent-governance/SKILL.md#等待与通信) 为准。新证据、收尾判断、达到静默核对时点或恢复时丢失等待信息允许一次有目的的只读观察；状态核对本身无法确认时停止该 target 的自动等待及定时查询，不能仅凭时间经过重复查询。停止等待不自动 close 或 interrupt，也不阻止其他独立工作。

后续确定 running/error 更新观察但不建立终态；明确 completed/stopped/interrupted 才进入 terminal。明确 error 需要报告并处置，不继续盲等。unknown_facts 保留，原回执不倒改为成功，不自动重发消息或重试中断。

原生 interrupt 返回 previous_status 只证明操作前状态。只有明确 failed/inactive 回执才能按对应结果登记；inactive 不等于 completed。终态建立后，未知或 active 观察不能降级该事实。

## 终态与关闭

一条证据按来源选择 terminal notification 或 platform observation 入口，不重复登记。矛盾终态保留首个 terminal_fact 并 reconcile，已有 unknown_facts 不丢失。

父 Agent 按实际结果验收；Agent completed 本身不能证明它收到了投递未知的追加要求。完成验收或明确停止跟踪后调用 close，保留 unknown_facts、首个 reconcile 原因和已有可靠事实。相同 reason 幂等，不同 reason 不覆盖，closed 不重新开启。

close 不调用 interrupt，不证明业务成功或资源释放。status/diagnose 单独呈现历史 unknown，closed 的 next_action 为 none；issues=[] 只说明账本可读且结构有效。

state-v11 不读取、迁移或清理 state-v10。新版本摘要为空不证明旧任务已完成；当前实现尚未部署或真实复验。
