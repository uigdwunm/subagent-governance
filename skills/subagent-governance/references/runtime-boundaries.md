# Runtime boundaries

- 唯一当前持久格式是 `state_format_version=9`、namespace `state-v9`。v8 及更早状态不读取、不迁移、不修复、不写回、不删除。
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
- exact platform observation 只作用于已 bound target；unknown 只写有界 reconcile reason。
- normal message success/failed 只校验 exact identity 且零写入；unknown 只写 `delivery_unknown`，不保存正文或调用历史。
- terminal notification 保存 exact sender 对应的 status/time，不接收正文。interrupt 只保存明确 failed/inactive 机械结果；unknown reconcile。
- parent close 是显式写入，不调用原生 interrupt。closed task 固定保留最新 64 条，只由后续 ledger 写操作惰性裁剪。

## Current native adapter

TaskContract v2 and the state-v9 capability retain semantic `task_name` and
`fork_turns` fields internally. They are not serialized verbatim to native
`spawn_agent`: the generated message header carries the name, and `none|all`
map to boolean `fork_context`. Claim normalizes the current native arguments
back to that semantic shape and compares the entire message and configuration.
Unknown native fields and non-boolean context values are rejected for marked
calls. Finite-turn inheritance is unavailable and rejected during prepare.

The adapter requires a visible generated message header at PreToolUse. An
opaque or unmarked message cannot be associated with a prepared task; it passes
through without claim. A subsequent explicit confirm then reports missing claim
instead of inventing identity. Real Hook delivery and visibility must be checked
after installation in a fresh task.
