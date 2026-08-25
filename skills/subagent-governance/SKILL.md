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

当前 runtime 已实现 state-v9 的 `prepare → Pre claim → explicit exact-target confirm` 纵向链路。后续 observation、terminal、interrupt 和 close 写 API 尚未在本切片开放；等待和普通消息仍使用原生工具，但不得伪造持久化结算。

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

## Governed 派发

1. 用 TaskContract v2 通过标准输入调用：

   ```bash
   python3 scripts/subagent_governance.py --prepare-dispatch --session <exact-session-id>
   ```

2. 向用户展示返回的 `user_message`。把 `spawn_args` 原样传给当前原生 `spawn_agent`；不要重写 message、task name、model、effort 或 `fork_turns`。
3. governed spawn 的 PreToolUse 在同一个 Session ledger 原子执行 `prepared → claimed`。unmanaged task name 完全 inert，不创建治理状态。
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
- 普通 `send_message` success/failed 不保存正文或调用历史；当前切片不提供 managed followup/business resume。
- unknown delivery 不得自动重发。后续最小 lifecycle API 落地前，如实向用户报告这一未持久化限制。
- 中断继续使用原生 `interrupt_agent`，但当前切片不把结果写入 ledger，也不能据此声称 lifecycle 已完整关闭。

## 只读恢复与状态

`--status --session <exact-session-id>` 和 `--diagnose --session <exact-session-id>` 只读 exact Session；缺失目录时不创建目录、lock 或空状态。SessionStart 同样 best-effort、无锁只读，不 cleanup、rebuild、reconcile、自动关闭、自动调用工具或扫描其他 Session。

只在平台继续提供同一 exact Session identity 时显示未关闭摘要。新 Session 不跨目录扫描或猜测旧任务。
