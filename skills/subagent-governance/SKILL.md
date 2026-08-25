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
- 不修改或要求其他 Skill 采用本协议；真正调用 `spawn_agent` 的每个任务都是一个独立 governed lifecycle。

当前 runtime 已实现 state-v9 的 `prepare → Pre claim → explicit exact-target confirm → minimal lifecycle → parent close`。等待和普通消息仍使用原生工具；治理层只记录下述会改变后续决策的最小事实。

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
- business contract digest 不包含 `spawn`；spawn config 有独立 digest。
- `context.paths` 只是定位提示，不建立文件存在或内容正确的事实。

需要机械验证工作区材料时，在 `context.verified` 显式提供 declared manifest。它沿用 absolute workspace root、`working_tree|git_commit` baseline 和 required paths；prepare 与 Pre claim 各验证一次。普通 standard 任务只有显式提供该字段才 opt in；strict 也不自动扫描工作区。

profile 与状态边界见 [references/governance-profiles.md](references/governance-profiles.md) 和 [references/runtime-boundaries.md](references/runtime-boundaries.md)。

## Exact Session identity

- 当前任务的 exact session ID 只取自 SessionStart Hook 注入的 `当前 Hook 权威 exact session_id（JSON）`，治理命令的 `--session` 必须逐字使用该值。
- `<codex_delegation><source_thread_id>` 仅表示来源任务，不是当前任务的 session ID。父任务 ID、任务列表结果和其他可见 ID 也不能替代。
- 如果当前上下文没有机械可见的 SessionStart 权威值，在 prepare 或原生 spawn 前停止并报告 identity 缺失；不得猜测、跨 Session 扫描或先用其他 ID 尝试。

## Governed 派发

1. 用 TaskContract v2 通过标准输入调用：

   ```bash
   python3 scripts/subagent_governance.py --prepare-dispatch --session <exact-session-id>
   ```

2. 向用户展示返回的 `user_message`。把 `spawn_args` 原样传给当前原生 `spawn_agent`；不要重写 message、task name、model、effort 或 `fork_turns`。
3. governed spawn 的 PreToolUse 在同一个 Session ledger 原子执行 `prepared → claimed`。unmanaged task name 完全 inert，不创建治理状态。
   Codex MultiAgent V2 会在本地 Hook 前加密 message；runtime 通过派生 task name/ref 与仍可见的 spawn config 绑定 prepared capability，不宣称对 V2 明文正文提供独立 attestation。父 Agent 的原样提交义务不变。
4. 读取这一次原生 spawn 的机械返回。只有返回中明确给出的、可直接用于后续原生调用的 exact target 才能绑定；如果平台没有机械暴露 exact target，停止并报告，不使用 list/name/time/final 补绑。
5. 立即提交 exact target：

   ```bash
   python3 scripts/subagent_governance.py --confirm-dispatch --session <exact-session-id>
   ```

   stdin 精确为：

   ```json
   {"task_id":"<prepare 返回值>","task_ref":"<prepare 返回值>","target":"<原生 spawn 当前返回的 exact target>"}
   ```

6. 首次确认建立 `bound`；相同 target 重放幂等；不同 target 或 task/ref 不匹配进入 `reconcile`，first bind 保留。

原生调用明确 failed 且机械证明 Agent 未创建时，使用 `--record-dispatch-result` 提交 `result=failed`；结果 unknown 时提交 `result=unknown`。success 必须走 `--confirm-dispatch` 并携带 exact target。

spawn 返回后、confirm 前如果父任务中断，记录保持 `claimed/unbound`。不要自动重派、创建 attempt 或从其他信号恢复 identity。

## 等待与通信

- bind 后保存 runtime 返回的 exact target，并用原生 `wait_agent` 等待。
- wait 不持久化；正常超时不等于 failed、terminal 或需要重派。
- `list_agents` 只允许观察已经 bound 的 exact target，不能建立或修复 identity。
- 对 exact target 得到规范化平台观察后，提交：

  ```bash
  python3 scripts/subagent_governance.py --record-platform-observation --session <exact-session-id>
  ```

  stdin 精确为 `{"task_id":"...","task_ref":"...","target":"...","status":"running|completed|stopped|interrupted|error|unknown"}`。unknown 只进入 reconcile，不自动重查或猜 terminal。
- 普通 `send_message` 的机械结果用 `--record-call-result` 提交 exact task/ref/target 和 `result=success|failed|unknown`。success/failed 只校验 identity，ledger 字节不变；unknown 只写 `delivery_unknown`，不得自动重发。任何 message、response 或 summary 字段都会被拒绝。
- 当前切片不提供 managed followup 或 business resume。原生 `followup_task` 不建立新 attempt，也不进入治理持久状态。

## Terminal、中断与关闭

- 收到原生 child terminal notification 时，用 `--record-terminal-notification` 提交精确 `task_id`、`task_ref`、`sender` 与 `status=completed|stopped|interrupted`。不提交正文。sender 必须等于已 bound target；相同 status 重放幂等，冲突 status 保留首个 terminal fact 并 reconcile。
- 调用原生 `interrupt_agent` 后，用 `--record-interrupt-result` 提交 exact task/ref/target 和 `result=failed|inactive|unknown`。failed 保存明确失败事实但保持 bound；inactive 建立 terminal fact；unknown 进入 reconcile。不要把模糊成功或 not-found 自行改写为 inactive。
- 父 Agent 完成验收或明确决定停止跟踪后，用 `--close-task` 提交 `task_id`、`task_ref` 和有界 `reason`。close 不自动调用 interrupt。相同 reason 重放幂等；不同 reason 不覆盖首次 close。
- ledger 只保留最新 64 条 closed task，并只在后续真实写操作时惰性裁剪。status、diagnose 和 SessionStart 永不清理。

## 只读恢复与状态

`--status --session <exact-session-id>` 和 `--diagnose --session <exact-session-id>` 只读 exact Session；缺失目录时不创建目录、lock 或空状态。SessionStart 始终注入当前 Hook 提供的权威 exact session ID；状态摘要仍是 best-effort、无锁只读，不 cleanup、rebuild、reconcile、自动关闭、自动调用工具或扫描其他 Session。

只在平台继续提供同一 exact Session identity 时显示未关闭摘要。新 Session 不跨目录扫描或猜测旧任务。
