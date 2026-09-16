# Runtime boundaries

- 唯一当前持久格式是 `state_format_version=12`、namespace `state-v12`。v11 及更早状态不读取、不迁移、不修复、不写回、不删除。
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

## 原始验收快照与容量

`contract_summary` 是规范化 TaskContract 去掉 `spawn` 后的精确结构化快照：`profile`、`objective`、`scope`、`forbidden_scope`、`completion`、`evidence` 和完整 `context`（summary、paths、verified）。它不重新概括、排序列表或截断约束，不记录实际业务结果。prepare/claimed 时与 capability contract 精确一致；所有阶段校验其 business digest，跨绑定、失败、对账、终态和关闭保留。digest 只校验一致性，不证明业务完成或防止同用户进程篡改。

- objective 和 context.summary 各最多 8,192 字符；scope、forbidden_scope、completion、evidence 各最多 64 项，每项最多 1,024 字符。
- context.paths 最多 64 项，每项最多 1,000 字符；verified 沿用最多 64 条 required_paths、每条路径最多 1,000 字符、workspace_root 最多 4,000 字符和原有 baseline 结构。
- 快照整体最多 65,536 字节，按 `json.dumps(ensure_ascii=False, sort_keys=True, separators=(",", ":"))` 的 UTF-8 编码计数，不含尾部换行，含键名、标点和转义；这些上限同时适用。标准 JSON Schema 检查结构和字符限制；运行时额外执行机器语义源中的字节预算。
- 每个 exact Session 最多 512 条任务；新增任务预计落盘超过 3 MiB 时拒绝准入，所有落盘写入硬上限 4 MiB。按实际账本序列化字节计算，包含 prepared 阶段的契约与派发正文副本；不承诺能同时存放 512 条最大契约。
- 超限拒绝且不覆盖原账本，不自动删减约束或另建正文存储；closed 仍只保留最近 64 条，由真实写操作惰性淘汰。未关闭任务不因容量自动清除。

精确 `--status --task-id ... --task-ref ... --session ...` 返回单个任务及快照，无锁零写。默认 status/diagnose 和 SessionStart 只给轻量状态；后者仅提示按需读取方法。恢复不访问材料文件，也不保留原 prepared 校验产生的文件哈希；`context.verified` 保留的是材料声明，不保证之后的文件存在或内容不变。

原始证据要求与实际执行证据分开：evidence/completion 中的报告要求可以恢复，通知正文、工具日志、业务结果和后续消息正文不持久化。不要向契约写入凭据或无关敏感正文；没有自动语义摘要或脱敏改写。

## Current native adapter

TaskContract v2 and the state-v12 capability retain semantic `task_name` and
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

## 后续 CLI 输入投影

`operation_inputs` 仅生成现有命令的部分 JSON stdin，不新增输入协议、状态字段、身份 token 或执行器。prepare、confirm、record-platform-observation、record-terminal-notification、close 的成功返回，以及精确 status 详情携带它；默认 status/diagnose/SessionStart 不展开。各输入在调用时仍须配当前权威 CLI 和 exact Session。

投影依据本次事务内的实际任务记录或精确只读记录，不按 result 字符串猜阶段、不使用冲突请求中的身份、不另读其他 Session。prepared/claimed 提供缺 target 的 confirm；bound 提供缺 status 的两种证据输入和缺 reason 的 close；terminal/reconcile 仅提供 close；closed 返回空对象。所有缺省事实由父任务核对后补入。输入集合不是操作许可或完整接口目录；独立新证据、中断和异常回执仍走原有 CLI。

写操作在原有事务回调内生成投影，生成异常发生在提交前；不新增持久化或额外回读。原子替换后发生回读错误不代表写入未发生，保留各入口原有错误语义及 prepare 的精确已提交回读逻辑，不自动重派或重试。参数不存入账本，不影响 contract_summary/digest 和 state-v12。旧输入仍有效；返回增加字段，消费方应按所需字段读取。

## Pre claim 与声明材料

PreToolUse 按可见 task name 或消息首行 `[subagent-governance:<生成的 task name>]` 定位精确 task ref，校验冻结接口和派发配置后在同一账本认领。当前匹配包括 spawn_agent、multi_agent_v1 形式、collaboration.spawn_agent、collaborationspawn_agent。不可验证标识/配置、未知输入或内部 Hook 故障 fail-open 且不 claim、不声称成功；明确可比的不一致才拒绝。后续 confirm 缺少 claim 进入 reconcile。

需要工作区材料校验时，context.verified 的 declared manifest 形状为：

```json
{
  "mode": "declared",
  "workspace_root": "/absolute/workspace",
  "baseline": {"kind": "working_tree", "revision": null},
  "required_paths": [{"path": "design.md", "type": "file"}]
}
```

也可使用 git_commit baseline 并提供 revision；按实际任务声明 required paths。prepare 与 Pre claim 各验证一次，不自动扫描工作区或提供运行期间隔离。business digest 不包含 spawn；spawn config 有独立 digest。
