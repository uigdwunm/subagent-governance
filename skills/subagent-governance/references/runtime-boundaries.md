# Runtime boundaries

- 唯一当前持久格式是 `state_format_version=11`、namespace `state-v11`。v10 及更早状态不读取、不迁移、不修复、不写回、不删除。
- 每个 exact Session 只有一个 ledger，根字段精确为 `state_format_version`、`session_id`、`tasks`。
- 一个 task 对应一个原生 Agent lifecycle，不存在 attempt。
- phase 只有 `prepared|claimed|bound|terminal|closed|reconcile`。
- prepared capability、claim 和 lifecycle facts 使用同一文件锁与原子写入边界；没有 PreparedContractStore、agents index、Post receipt/index、pending action、tombstone 或 Group。
- identity 的唯一来源是父 Agent 对当前原生 spawn 返回 exact target 的显式 confirm。first bind wins；相同 confirm 幂等；冲突进入 reconcile。
- unmanaged spawn 在构造 StateStore 前判定并 inert fail-open。
- 当前 Hook 只注册 spawn PreToolUse 和 read-only SessionStart；SessionStart 始终注入 Hook stdin 的当前权威 exact session ID 与当前已安装 CLI entrypoint，状态摘要 best-effort；没有 PostToolUse、Stop、SessionEnd 或通信类 PreToolUse。
- status、diagnose 和 SessionStart 不创建目录、lock、临时文件或空状态，不 cleanup、rebuild、迁移、自动重试或扫描业务正文。
- 所有治理 CLI 操作必须使用 SessionStart 注入的已安装 entrypoint，使其与 Hook 解析到同一插件数据根；禁止改用工作区相对脚本、其他 cache 版本或猜测路径。
- `<codex_delegation><source_thread_id>` 只表示来源任务，不是当前 session ID；缺失任一 SessionStart 权威值时停止 governed dispatch，不从父任务、列表或其他 ID 猜测。
- transcript、summary、child final、时间邻近、task name 和 `list_agents` 都不是 correctness authority。
- exact platform observation 只作用于已 bound target；unknown 写 unknown_facts，保持 bound，后续确定终态可正常登记。
- 等待节奏由 Skill 的“等待与通信”定义：短次等待、按 target 静默时间核对、恢复时补核对。时间信息只保留在父任务上下文；wait 不持久化，不增加状态字段或 attempt。Hook 不执行定时巡检，status/diagnose 不读取原生平台状态；超时和静默不是终态证据。
- normal message success/failed 不要求额外 CLI；显式调用仍只校验 exact identity 且零写入。unknown 写 unknown_facts.delivery_unknown，不自动重发、不保存正文或调用历史。
- terminal notification 保存 exact sender 对应的 status/time，不接收正文。interrupt 只保存明确 failed/inactive 机械结果；unknown 写 unknown_facts.interrupt_unknown，保持 bound。
- unknown_facts 仅含三类首次时间，最多三项；与 phase 分开呈现，不证明当前状态未知，也不证明旧调用成功。身份／终态冲突及派发未知仍 reconcile，首个阻断原因保留。
- parent close 保留 unknown_facts、首个 reconcile 原因及既有事实；closed 不重新开启。parent close 是显式写入，不调用原生 interrupt。closed task 固定保留最新 64 条，只由后续 ledger 写操作惰性裁剪。

新 namespace 不恢复旧账本，新摘要为空不代表旧任务已完成。diagnose issues=[] 只表示账本可读且结构有效。

## Current native adapter

TaskContract v2 and the state-v11 capability retain semantic `task_name` and
`fork_turns` fields internally. A frozen `native_interface` selects either
`collaboration_turns` (message/task_name/fork_turns) or `fork_context`
(message/fork_context); the two shapes are never mixed. Claim normalizes the
selected shape and compares task_name, fork_turns, model and reasoning_effort.
It does not compare the full message text after platform rewriting.
Finite-turn inheritance is supported only by `collaboration_turns`.

`collaboration_turns` uses the visible generated task_name; a visible message
marker must agree with it. `fork_context` requires a visible generated message
header to locate the prepared task. Unknown shapes or unverifiable identity/config
fail open without a claim; known mismatches are rejected. Exact target binding
still requires the current native spawn return and explicit confirm.
Real Hook delivery and visibility must be checked after installation in a fresh task.
