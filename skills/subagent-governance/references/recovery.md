# 异常与恢复

仅在根 Skill 的异常路由命中时读取对应小节。所有命令均使用当前 SessionStart 或 SubagentStart Hook 的权威 CLI 与 exact Session，stdin 是 JSON；task_id/task_ref 来自该 Session 的精确记录，target/sender 必须符合既有绑定。本文不新增恢复状态或自动重试。

## 过期准备

`expires_at` 到达后，不再用旧 spawn_args 发起首次派发。若已调用原生 `spawn_agent`，先核对本次完整工具回执与精确 `--status --task-id ... --task-ref ...`；`preparation_expired` 只说明 Hook 拒绝了本次 claim，本身不证明原生执行结果。

仅当本次原生工具回执明确表示调用在 PreToolUse 阶段被阻止、Agent 未创建，且精确任务仍为 prepared、没有相反或不确定的执行证据时，父任务才可将本次结果按 `--record-dispatch-result` 的 `result=failed` 登记并关闭旧记录。发起调用前发现过期、因而根本未调用原生工具时，也可在核实没有该次调用后按同一路径关闭旧准备。不得仅凭 Hook 输出、账本 prepared 状态或“没看到子 Agent”推定未创建。

旧记录收尾后，先核对本次已有的用户授权是否覆盖重新派发；用户当前明确指令覆盖上层流程的失败停止规则时，以用户指令为准。若未覆盖而上层流程要求报告并停止，则遵循该规则。本插件的账本收尾本身不授权重派。若可继续，父任务重新核对当前材料和契约，再 prepare 并及时调用新的 spawn_args；不复用旧 task/ref 或凭据，也不形成自动重试循环。

若工具回执是 unknown、未明确拦截或缺失，不按 failed 收尾，也不新建派发；按实际证据走 [治理降级](recovery.md#治理降级) 和 [派发回执与缺失绑定](recovery.md#派发回执与缺失绑定)。重复过期应检查派发前为何耗时，不能循环 prepare 和重试。

## 派发回执与缺失绑定

- 原生调用明确 failed 且机械证明 Agent 未创建时，用 `--record-dispatch-result` 提交 `{"task_id":"...","task_ref":"...","result":"failed"}`。结果 unknown 时改用 `result=unknown`；success 必须走 confirm 并携带本次原生返回的 exact target。
- spawn 返回后、confirm 前父任务中断，记录保持 claimed/unbound。只有仍持有本次原生返回的 exact target 才能 confirm；不能从列表、调用前的短名称、时间、通知或唯一候选恢复身份。仍持有的同次原生返回完整 canonical task_name 可以原样使用，不属于按名称推断；字段选择见根 Skill 的派发步骤。
- 缺少 claim、派发 unknown、身份或终态冲突进入 reconcile。不得通过后续通知补绑、自动解锁、重派或创建 attempt 绕过。
- 同一 exact target confirm 重放幂等，first bind 保留；terminal/closed 后相同 confirm 不重新开启执行。不同 target 或 task/ref 按既有冲突规则处理。生成参数不改变这些规则。

## 未知消息或观察

已绑定且没有冲突的任务，三类 unknown 在 bound/terminal 均可记为 unknown_facts，phase 和已有 terminal_fact 保持不变；首次返回 unknown_recorded，同类重放返回 already_unknown。仅保存 delivery_unknown、platform_observation_unknown、interrupt_unknown 各自首次时间，不保存消息历史，不能据此确认回执对应哪次调用。terminal 补记仅用于晚到事实，不授权继续业务操作；closed 拒绝新增或重放 unknown，reconcile 不自动解锁。

- 普通消息回执 unknown：用 `--record-call-result` 提交 `{"task_id":"...","task_ref":"...","target":"...","result":"unknown"}`，不自动重发。success/failed 不要求额外治理调用；显式调用只校验且零写。
- 平台状态无法确认：能归属已绑定 target 时用 `--record-platform-observation` 提交相同 identity 和 `status=unknown`。停止该 target 的自动等待和定时查询，只有新的相关证据或用户明确要求再次核实时才重查。
- 消息或中断回执 unknown 本身不停止等待；有新证据、需要判断能否收尾、达到根 Skill 的静默核对时点或恢复时丢失等待信息，才做有目的的状态观察。
- 后续明确状态或终态可以正常登记，同时保留 unknown，不将旧调用倒改为成功。即使 Agent 已完成，也要核实是否满足未知投递消息中的新增要求，不能仅凭终态验收。

## 中断回执

原生 `interrupt_agent` 后，用 `--record-interrupt-result` 提交 `{"task_id":"...","task_ref":"...","target":"...","result":"failed|inactive|unknown"}`；实际 result 只选一个。

previous_status 只证明操作前状态；没有明确操作后事实时记录 unknown，不自动重试中断。inactive 不等于 completed；后续明确 completed/stopped/interrupted 仍可登记。原生中断不会代替父任务 close，close 也不会调用原生中断或证明资源已释放。

## 恢复后等待时间丢失

先用 exact-session status 恢复映射。若 bound target 的等待时间信息丢失，先按根 Skill 的状态核对表观察一次，不重新开始未经核对的等待。只有明确 running 才以本次核对时间为新的等待基点；terminal/closed/reconcile 按已有阶段处置。时间信息仅用于父任务决策，不写账本，不增加 attempt。

缺失身份、账本读取失败或平台状态不可识别时，停止依赖这些事实的操作，继续其他已授权工作；不猜测、不跨 Session 扫描、不自动重派。

## 矛盾事实与停止跟踪

相同终态幂等；独立来源确有新事实可补充，矛盾终态保留首个事实并 reconcile。不为同一通知重复登记不同来源。

reconcile 不提供正常执行参数，也不自动解锁。若父任务明确决定停止跟踪，可使用 `--close-task`，提交 task_id/task_ref 和实际 reason；这不是验收成功。close 保留 unknown_facts、首个 reconcile 原因和既有事实。相同 reason 幂等，不同 reason 不覆盖，closed 不重新开启。


## 治理降级

收到 fail-open 或 claim 未确认提示时，先区分 Hook 决定、claim 证据和本次原生回执；原因码与阶段见 [故障契约](runtime-boundaries.md#hook-故障分类与证据契约)。不要将 allow／continue 当作校验通过，也不要将内部异常当作未提交或未创建。

- 仍持有本次原生返回的 exact target 时，按现有 confirm 路径处理；缺 claim 会进入 reconcile，不手工补 claim、不根据通知补绑。
- 原生机械证明未创建或结果未知时，按“派发回执与缺失绑定”登记实际 failed／unknown；Hook 的拒绝或错误提示本身不是未创建证据。
- 缺失权威身份或账本不可读取时，停止依赖这些事实的操作，报告原因码和阶段；不跨 Session 扫描、不猜身份、不自动重派，继续其他已授权工作。
- 用户明确要求检查通过才执行，而父任务在发起调用前已知检查不可完成时，停止依赖该检查的调用。调用中才出现的降级不能通过后续提示撤销原生执行。

诊断不包含业务正文或异常原文；不为补诊断建立另一个账本或自动重试。strict 与 standard 的降级处置相同。
