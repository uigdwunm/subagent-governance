---
name: subagent-governance
description: 治理 Codex 原生子 Agent 的派发、等待、通信、中断与验收。准备调用 spawn_agent、wait_agent、send_message、list_agents 或 interrupt_agent，或协调并发 Agent 时使用；普通任务不使用。
---

# 子 Agent 治理

保持 Codex 原生 Agent 工具为唯一执行通道。本 Skill 负责明确任务契约、把 governed spawn 单次绑定到原生返回的 exact target，并在未知事实时停止猜测。它不是第二套编排平台、权限机制或安全边界。

## 使用边界

- 普通任务不加载本 Skill，也不要只因任务可拆分就主动创建子 Agent。
- 准备派发、等待、通信、中断或验收原生子 Agent 时使用本 Skill。
- 不从 `list_agents`、task name、时间邻近、summary、transcript、child final 或唯一候选推断 identity。
- 治理异常只停止依赖缺失身份或冲突事实的操作；继续其他不依赖它的已授权工作，不用重复 spawn 绕过异常。
- 不修改或要求其他 Skill 采用本协议；真正调用 `spawn_agent` 的每个任务都是一个独立 governed lifecycle。

当前 runtime 已实现 state-v11 的 `prepare → Pre claim → explicit exact-target confirm → minimal lifecycle → parent close`。等待和普通消息仍使用原生工具；治理层只记录下述会改变后续决策的最小事实。v10 及更早账本不读取、迁移或清理。

## TaskContract v2

模型输入字段只有：

```json
{
  "profile": "standard",
  "objective": "唯一当前目标",
  "scope": ["允许处理的范围"],
  "forbidden_scope": [],
  "completion": ["可验证完成条件"],
  "evidence": [],
  "context": {
    "summary": "足够独立执行的必要背景",
    "paths": ["相对路径定位提示"]
  },
  "spawn": {
    "fork_turns": "none",
    "model": null,
    "reasoning_effort": null
  }
}
```

- `objective`、非空 `scope` 和非空 `completion` 必填。
- 其他字段可省略；生成器补 `profile=standard`、空数组、空 context 和 `spawn.fork_turns=none`。
- `profile` 只有 `standard|strict`。strict 必须提供非空 `forbidden_scope` 和 `evidence`。
- 不使用 `auto`、`light`、`task_features`、attempt 或模型手写 task name/ref。
- semantic name、task ref 和 task name 由生成器派生。
- `spawn.fork_turns` 接受 `none|all` 或 1–12 位正整数字符串。先核对当前任务可见的原生工具说明，再在 prepare 时显式选择 `collaboration_turns` 或 `fork_context`；不得猜测或混用接口。
- business contract digest 不包含 `spawn`；spawn config 有独立 digest。
- `context.paths` 只是定位提示，不建立文件存在或内容正确的事实。

需要机械验证工作区材料时，在 `context.verified` 显式提供 declared manifest。它沿用 absolute workspace root、`working_tree|git_commit` baseline 和 required paths；prepare 与 Pre claim 各验证一次。普通 standard 任务只有显式提供该字段才 opt in；strict 也不自动扫描工作区。

profile 与状态边界见 [references/governance-profiles.md](references/governance-profiles.md) 和 [references/runtime-boundaries.md](references/runtime-boundaries.md)。

## Exact Session identity

- 当前任务的 exact session ID 只取自 SessionStart Hook 注入的 `当前 Hook 权威 exact session_id（JSON）`，治理命令的 `--session` 必须逐字使用该值。
- 治理 CLI 只取自同一次 SessionStart 注入的 `当前 Hook 权威 governance CLI entrypoint（JSON）`。把 JSON 字符串解码后的路径作为 Python 的单个脚本参数；所有 prepare、confirm、status、diagnose 和 lifecycle 命令都必须使用它。
- 不得调用当前工作区的相对 `scripts/subagent_governance.py`、其他版本 cache 或自行猜测的安装路径；它们可能解析到与真实 Hook 不同的数据根。
- `<codex_delegation><source_thread_id>` 仅表示来源任务，不是当前任务的 session ID。父任务 ID、任务列表结果和其他可见 ID 也不能替代。
- 如果当前上下文缺少任一 SessionStart 权威值，在 prepare 或原生 spawn 前停止并报告 authority 缺失；不得猜测、跨 Session 扫描或先用其他 ID/路径尝试。

## Governed 派发

1. 用 TaskContract v2 通过标准输入调用：

   ```bash
   python3 "<authoritative-cli-entrypoint>" --prepare-dispatch --native-interface <collaboration_turns|fork_context> --session <exact-session-id>
   ```

2. 用一句话说明派发理由，再展示返回的 `user_message`；不增加契约字段或重复解释内部状态机。未覆盖的模型／推理参数按原生配置解析，不冒充已核实的运行配置。把 `spawn_args` 原样传给当前原生 `spawn_agent`：`collaboration_turns` 使用 message/task_name/fork_turns，`fork_context` 使用 message/fork_context。派生 task name 仍须与消息首行一致。
3. governed spawn 的 PreToolUse 根据可见 task name 或消息首行 `[subagent-governance:<生成的 task name>]` 定位精确 task ref，按已冻结接口校验生成的 task name 和派发配置；`collaboration_turns` 不逐字匹配平台可能重写的 message，`fork_context` 仍要求可见的生成标记，在同一个 Session ledger 原子执行 `prepared → claimed`。当前精确匹配包含 `spawn_agent`、`multi_agent_v1` 形式以及 `collaboration.spawn_agent`、`collaborationspawn_agent`。定位标识或必要配置不可验证、输入形状未知或内部 Hook 故障时 fail-open 且不 claim、不声称成功；明确可比的不一致才拒绝。后续 confirm 缺少 claim 进入 reconcile，不重派。
4. 读取这一次原生 spawn 的机械返回。当前接口返回的 `agent_id` 是 exact target；只有返回中明确给出的、可直接用于后续原生调用的 exact target 才能绑定；如果平台没有机械暴露 exact target，停止该任务的绑定及依赖操作并报告，不使用 list/name/time/final 补绑。
5. 立即提交 exact target：

   ```bash
   python3 "<authoritative-cli-entrypoint>" --confirm-dispatch --session <exact-session-id>
   ```

   stdin 精确为：

   ```json
   {"task_id":"<prepare 返回值>","task_ref":"<prepare 返回值>","target":"<原生 spawn 当前返回的 exact target>"}
   ```

6. 首次确认建立 `bound`；相同 target 重放幂等；不同 target 或 task/ref 不匹配进入 `reconcile`，first bind 保留。

原生调用明确 failed 且机械证明 Agent 未创建时，使用 `--record-dispatch-result` 提交 `result=failed`；结果 unknown 时提交 `result=unknown`。success 必须走 `--confirm-dispatch` 并携带 exact target。

spawn 返回后、confirm 前如果父任务中断，记录保持 `claimed/unbound`。不要自动重派、创建 attempt 或从其他信号恢复 identity。

## 等待与通信

- bind 后保存 task/ref/exact target 映射，并用原生 `wait_agent` 等待。它是邮箱唤醒接口；超时、邮箱摘要或用户新输入本身不建立 Agent 状态，也不需要额外记账。正常等待不轮询代码、日志或列表。
- 原生消息直接使用已保存的 exact target。上下文恢复或映射存疑时先读 exact-session status；不从 `list_agents`、名称或唯一候选补绑，也不在每次发送前增加固定检查。
- 普通 `send_message` 的 success/failed 不要求额外治理调用。`--record-call-result` 仍可用于显式校验，success/failed 零写；结果 unknown 时必须提交 `{"task_id":"...","task_ref":"...","target":"...","result":"unknown"}`，记录 delivery_unknown，不自动重发。
- 后续原范围内工作使用同一 exact target 的 `followup_task`；不建立新 identity 或 attempt。终态后不受管恢复。

## 终态、中断与关闭

一条终态证据只登记一次，按实际来源选入口：

| 证据来源 | 治理命令与 stdin |
| --- | --- |
| 可归属已绑定 exact sender 的原生 child terminal notification | `--record-terminal-notification`：`{"task_id":"...","task_ref":"...","sender":"...","status":"completed|stopped|interrupted"}` |
| 明确的已绑定 exact-target 平台状态 | `--record-platform-observation`：`{"task_id":"...","task_ref":"...","target":"...","status":"running|completed|stopped|interrupted|error|unknown"}` |

这些命令都通过标准输入传 JSON，并使用同一次 SessionStart 的权威 CLI 和 `--session`。不提交正文；表中的 status 列出允许值，实际输入只能选一个。不要把 wait 摘要猜成平台状态，也不为同一通知再补另一条登记。独立来源确有新事实时可以补充；相同终态幂等，矛盾终态保留首个事实并 reconcile。

- 原生 `interrupt_agent` 后，用 `--record-interrupt-result` 提交 exact task/ref/target 和 `result=failed|inactive|unknown`。previous_status 只证明操作前状态；没有明确操作后事实时记录 unknown，不自动重试中断。inactive 不等于 completed。
- 父 Agent 按完成条件验收结果，或明确决定停止跟踪后，用 `--close-task` 提交 `{"task_id":"...","task_ref":"...","reason":"..."}`。close 不表示业务成功或资源释放；相同 reason 幂等，不同 reason 不覆盖，closed 不重新开启。

## Unknown 与冲突

已绑定且没有冲突的任务，三类 unknown 记录为 `unknown_facts`，phase 保持 bound，命令返回 unknown_recorded；同类重放返回 already_unknown。该对象只保留 delivery_unknown、platform_observation_unknown、interrupt_unknown 各自首次时间，不保存消息历史。

继续等待；有新证据或需要判断能否收尾时，可以对已绑定 exact target 做一次有目的的只读观察，没有新证据不循环查询。后续确定状态或终态可以正常登记，同时保留 unknown；不把旧调用倒改为成功。即使 Agent 已完成，也要核实它是否满足未知投递消息中的新增要求，不能仅凭终态验收。

派发结果未知、缺少 claim、身份或终态冲突仍进入 reconcile，不能通过后续通知补绑或自动解锁。close 保留 unknown_facts 和首个 reconcile 原因；closed 只保留最新 64 条，由后续写操作惰性裁剪。

## 只读恢复与状态

`--status --session <exact-session-id>` 和 `--diagnose --session <exact-session-id>` 只读 exact Session；缺失目录时不创建目录、lock 或空状态。SessionStart 始终注入当前 Hook 提供的权威 exact session ID 与 CLI entrypoint；后者保证 CLI 与真实 Hook 使用同一安装版本和插件数据根。状态摘要仍是 best-effort、无锁只读，不 cleanup、rebuild、reconcile、自动关闭、自动调用工具或扫描其他 Session。

只在平台继续提供同一 exact Session identity 时显示未关闭摘要。新 Session 不跨目录扫描或猜测旧任务。

status/diagnose/SessionStart 分别呈现 phase、next_action 与历史 unknown；`diagnose.issues=[]` 仅证明账本可读且结构有效。新版本不读取旧 namespace，新账本为空不证明旧任务已完成。
