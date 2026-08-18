# Codex 应用重启后的子 Agent 对账与收口

## 事故边界

真实事故同时包含两个不同层次的问题：

1. Codex 桌面进程停止后，已经运行并产生副作用的 worker thread 被标记为 `interrupted`，而原生 `list_agents` 随后先投影为 `pending_init`、再返回精确空列表。当前仓库不能修复桌面进程重启、thread rollout 中断或原生活动列表投影。
2. `subagent-governance` 没有读取 `interrupt_agent` 的真实 `previous_status` 字段，也没有兼容字符串 `agent_status` 或精确空 `agents`，导致 `previous_status=not_found` 被写成 `unknown`，旧 attempt 永久停留在 `running/unknown/reconcile`。

不能把两层问题合并为同一根因。现有证据只支持“首次执行中断与应用进程重启时间吻合”，不支持插件触发了平台中断。

## 已验证假设

- `adapt_call_response()` 只读 `status/state` 是事故中 interrupt 响应适配失败的直接原因。
- `previous_status=running` 是调用前事实：目标存在且中断请求已交付；它不单独确认目标已经停止。
- `previous_status=not_found` 只表示调用时精确 target 不存在；陌生 target、身份未确认或没有匹配 interrupt 意图时不得用它收口。
- `pending_init` 可出现在已经 confirmed/running 并产生副作用的 worker 上，因此不能据此重派或改写成 `not_started`。
- 精确 canonical `path_prefix` 的空列表可以安全记录 target 当前 absent，但仍不能单独证明 thread 终态。

## 响应与状态合同

真实平台状态既可能是字符串，也可能是带终态摘要的单标签对象，例如 `{"completed":"<summary>"}`。`list_agents.agent_status` 与 `interrupt_agent.previous_status` 使用同一有限标签归一化：只接受单个已知标签且值不是 `null|false`，不递归解释任意对象，也不接受多标签对象。

interrupt 适配结果拆成两个维度：

- `call_observation=success|failed|unknown`：原生调用是否被接受。
- `target_observation`：原生响应对目标状态提供的最小事实，如 `previously_running`、`not_found`、`stopped` 或 `interrupted`。

具体规则：

- `previous_status=running`：记录 `success + previously_running`，保持原 `execution_status`，进入 `parent_action=reconcile`。
- `previous_status=not_found`：记录 `success + not_found`。只有同 target 已有精确空 `list_agents`、身份 confirmed、spawn success、attempt 仍为 running 且 interrupt 已认领时，才能直接写 `stopped + decide_disposition`。
- `status=stopped|completed`：目标已确认不活跃，写 `stopped + decide_disposition`。
- `status=interrupted|cancelled|canceled`：目标已确认中断，写 `interrupted + decide_disposition`。
- `pending_init`：写 `platform_observation=unknown + parent_action=reconcile`，保留 running 先验。

这些状态只收口旧执行，不关闭治理任务，不产生业务结果，也不自动创建替代 worker。

## 已完成但缺少终态通知的相邻状态

重启恢复并不是唯一会留下“worker 已不活跃、治理仍未收口”的场景。原生 `list_agents` 也可能对精确 canonical target 返回 `stopped`、`completed` 或单标签对象 `{"completed":"<summary>"}`，但父 Agent 尚未收到并记录当前原生 child notification。平台终态观察只证明 worker 不再活跃，不替代通知，也不建立业务事实。

该场景不使用 `--reconcile-interrupted-attempt`，也不把 summary 转成业务结果：

- 精确身份映射仍必须指向同一 `task_id + attempt + canonical target`；
- `completed|stopped` 只确认 `execution_status=stopped` 和平台正常终态，closure 进入 `await_notification`；
- 精确 child notification 到达后，父 Agent 使用 `--record-terminal-notification` 记录最小观察，closure 再进入 `await_parent`；
- `interrupted` 进入 `execution_status=interrupted`，其生命周期处置仍由父 Agent 明确决定；
- 父处置仅把 confirmed/running attempt 返回为 interrupt target。stopped/interrupted attempt 即使仍保留精确身份映射，也可以直接 `close_task`，不会形成重复中断循环。

精确 list terminal fact 持久化后，closure 会直接派生为 `await_notification`，不需要额外补账入口，也不会伪造通知或业务结论。

## 父 Agent 提供 thread 事实的受控入口

Hook 无法读取任意 worker thread 的 `latestTurnStatus`。当应用重启后的只读 rollout/桌面证据已经明确 thread 为 `interrupted`，父 Agent可以显式确认需要收口的治理身份：

```json
{
  "task_id": "sg-example",
  "attempt": 1
}
```

运行：

```bash
python3 scripts/subagent_governance.py \
  --reconcile-interrupted-attempt \
  --session <session_id> \
  --data-root <governance-data-root> < observation.json
```

调用该专用入口表示父 Agent 已用外部只读证据确认 worker thread 为 `interrupted`。入口从治理状态内部核对精确 `task_id + attempt`、confirmed identity、spawn success、保存的 canonical target、`agents` 映射、已有 list unknown 观察，以及已认领且带稳定 `tool_use_id` 的 interrupt lifecycle。旧版已把中断响应记为 `call_observation=unknown` 时允许兼容收口；调用方不再重复回显这些已持久化事实，也不提交插件无法关联验证的 thread UUID。

成功只写：

- `execution_status=interrupted`
- `platform_observation=normal`
- `parent_action=decide_disposition`

随后父 Agent 应先检查并保留旧 worker 的工作副作用，再决定关闭或经授权创建新 attempt。替代 worker 不得复用旧 attempt。

## 事故幽灵 attempt 的建议恢复

如果事故状态仍保持 `running/unknown/reconcile`，在安装包含本修复的测试版本并重新核对真实状态文件未发生变化后，可为该 attempt 构造一次上述 observation，其中：

- session：`019ff4e9-c01e-75a3-bff7-206465e72130`
- task：`sg-f445488aa333acc6c2616ac2af6f4a4a#1`
- target：`/root/sg_strict_structured_options_state_t_751537376606`
- thread：`019ff4ef-aac5-77c1-81ef-682411ff1a3f`
- interrupt tool use：`call_Wy4BtLTgbbJwSXBg1ZVF9rQP`

未经用户确认不得实际运行该写入操作；事故状态文件应继续作为证据保留。如果该 attempt 已被其他授权流程显式关闭并生成 tombstone，则不得再运行 reconciliation，也不得重复关闭或重新派发。

## 平台限制

- 插件不能阻止或恢复 Codex 桌面进程重启造成的原 turn 中断。
- 插件不能修复 `list_agents` 在重启后把已运行 worker 投影为 `pending_init` 或从活动列表移除。
- 插件不能直接查询任意 worker thread 的持久化终态，只能验证父 Agent提供的受限观察与本地治理事实是否一致。
- 本地 fixture 和单元测试不能替代安装后新对话中的真实 Codex 验收。
