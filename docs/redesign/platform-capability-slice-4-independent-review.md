# 平台能力 Slice 4 独立验收报告

日期：2026-08-15

结论：**NO-GO**。不得进入测试 cachebuster、新建 Slice 4 真实 smoke、Slice 5、部署、安装、缓存同步或发布；必须回到同一 Slice 4 修复有限 `list_agents` adapter 的 malformed/error wrapper fail-open 缺口，并重新完成独立验收。

## 1. 验收范围与方法

本次直接审查保存的 `<development-repository>`，不采信实施报告中的 PASS。全部主动用例使用 `TemporaryDirectory` 下的新建隔离 `StateStore` 和结果目录；没有读取、修改或删除任何既有 smoke StateStore。

只读审查覆盖冻结设计、最小状态机、Slice 3 真实 smoke、runtime、机器 Schema、Slice 4 测试、Skill 与 runtime boundaries。除本报告外，没有修改实现、Schema、tests、fixtures、Skill、README 或既有文档；没有提交、推送、部署、安装、同步缓存、修改 Hook trust、创建真实任务或启动 Slice 5。

主动反例分两组：

- adapter/freshness/Stop/lifecycle 组共 124 个机械断言，122 passed、2 failed；两个失败来自同一个稳定 adapter blocker。
- 父任务结果与 Schema 组共 10 个机械断言，10 passed；覆盖 exact 三元组成功、wrong task/attempt/sender 拒绝且状态字节不变、结果不改 observation，以及 Schema 拒绝 non-null freshness。

## 2. Blocker

### B1. malformed/error wrapper 可被提升为 exact terminal 强事实

冻结机器语义要求 `unknown_or_malformed=no_exact_bound_fact`，设计表要求 malformed/error wrapper no mutation 或保守 unknown。runtime 的 `_agent_status_entries()` 只在 `isError is True`、`is_error is True` 或 `status/state` 被识别为错误标签时拒绝 wrapper；其他畸形或显式错误 wrapper 仍返回顶层 `agents`，随后 exact-target reconcile 把其中的 `completed` 写成 terminal。

稳定反例一：

```json
{
  "isError": "true",
  "agents": [
    {
      "agent_name": "/root/sg_standard_slice_2_legacy_t_0123456789ab",
      "agent_status": "completed"
    }
  ]
}
```

稳定反例二：

```json
{
  "error": "boom",
  "agents": [
    {
      "agent_name": "/root/sg_standard_slice_2_legacy_t_0123456789ab",
      "agent_status": "completed"
    }
  ]
}
```

两例均得到：

```text
observed_state=terminal
binding_basis=exact_dispatch_target
terminal_status=completed
source=list_agents
```

这违反冻结不变量，不是 known limitation：不兼容或错误 wrapper 本应 fail-open，不能仅因内部夹带一个形似有效的顶层 `agents` 就建立 exact terminal authority。当前 focused 和全量测试均未覆盖这两个反例，因此测试全绿不能消除该 blocker。

要求在同一 Slice 4 中修复：对已出现但类型非法的错误标志保守 no-op/unknown；对明确错误 wrapper 不消费其中的 `agents`；补充失败先行用例覆盖 malformed `isError/is_error`、显式 error wrapper、空与非空 `agents`，并证明均不生成 active/terminal/error/result/closure 强事实。

## 3. 逐项证据

### 3.1 有限 `list_agents` adapter

- PASS：exact canonical `path_prefix == agent_name == unique dispatch_target` 下，`running|pending_init|completed|stopped|interrupted|errored|error|failed` 的 string 与 single-tag object 共 16 种正向形状按预期映射。
- PASS：broad、wrong、missing、alias prefix，零匹配 canonical target、重复 canonical target、wrong response target、多 Agent均未建立目标强事实。
- PASS：多标签、unknown、`null`、`false` 状态只形成保守 unknown；没有 TaskResult 或业务 failed。
- PASS：nested `content`、`structuredContent`、summary、final-history、transcript 与 malformed agents container/entry 均未被递归扫描。
- PASS：JSON string 顶层 `agents` 正向形状可用。
- FAIL：B1 的 malformed/error wrapper 被错误提升为 exact terminal。
- PASS：exact empty 在已确认 exact active 后只写 `absent_at_check`；`terminal_status=null`、result missing、closure 未关闭。
- PASS：exact error 未形成 business failed；exact terminal 未形成 TaskResult，只进入既有结果缺口处置。

### 3.2 Freshness 退役

- PASS：Schema 对 `observation_record.fresh_until` 使用 `type=null`。
- PASS：runtime current-plane validator 拒绝 format 4 non-null `fresh_until`，隔离 StateStore 原始字节保持不变，没有重写。
- PASS：initial writer 与 legacy migration 均产出 `fresh_until=null`；全仓 runtime 搜索只有两个 null writer 和一个 non-null rejector，没有其他写入源。
- PASS：`observed_at`、execution/work-item `updated_at` 和 `recent_activity` 没有被 Stop 消费为 freshness；exact 或旧 running 均只形成 advisory。

### 3.3 Stop advisory-only

- PASS：有 action-required、无 action-required、exact/旧 running、identity unconfirmed、result missing、Start/Stop 缺失均没有 `decision=block`，只返回 `continue=true`，有责任时附有界 advisory。
- PASS：隔离真实 StateStore 的 Stop 前后文件字节相同；Stop 不调用 writer、不验收结果、不改四平面。
- PASS：两次 transient read failure 后第三读成功，共三读、两次 bounded retry，返回 `continue=true`。
- PASS：persistent read failure 精确三读后告警 fail-open，仍无 `decision=block`。

### 3.4 Slice 1-3 不变量与父结果权威

- PASS：PostToolUse platform error 不生成业务 `failed`；Agent terminal 不生成 TaskResult。
- PASS：SubagentStart 与 SubagentStop 主处理路径均不写隔离 StateStore；伪造 task name、canonical path、transcript、last message 与 `task_result` 扩展没有获得 identity/result authority。
- PASS：summary、transcript、final-history 与 nested content 不能自动生成结果。
- PASS：父任务 exact `task_id + attempt + sender_target` 可记录结果，`submission_provenance=parent_recorded_native_sender`，且 observation 逐字段不变。
- PASS：wrong task、wrong attempt、wrong/alias sender target 均在状态写入前拒绝，StateStore 原始字节不变。
- PASS：runtime/Schema/Skill 未恢复 credential、message rewrite 或第二状态权威；`handle()` 仍只保留原生工具与 canonical StateStore 边界。

## 4. 门禁数字

| 门禁 | 独立结果 |
| --- | --- |
| 主动 adapter/freshness/Stop/lifecycle 反例 | 124 checks：122 passed、2 failed（B1） |
| 主动父结果/Schema 反例 | 10/10 passed |
| Slice 4 focused | 4/4，OK |
| observation/wait/Stop/Schema focused | 144/144，OK |
| parent result focused | 11/11，OK |
| 全量 unittest | 427/427，OK |
| Python compile | PASS |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| repository JSON parse | 15/15，PASS |
| Schema/runtime parity | 7/7，OK；字段/枚举双向、四平面、Hook capability、Slice 4 freshness/adapter 锚点一致 |
| `git diff --check` | PASS |
| untracked whitespace | 58 个 untracked 文件（含本报告），PASS |

这些门禁证明现有已编码回归没有失败，但 B1 是现有测试集未覆盖且稳定复现的冻结不变量违例，因此总体结论必须是 NO-GO。

## 5. Known limitation

- adapter 只支持已有正向证据的顶层 `agents` object/JSON string；未来平台只提供新 wrapper 时应保持 no-op/unknown，不能递归猜测。
- format 4 没有 active freshness；exact running 可能立即陈旧，Stop 不能 hard-block。
- Stop advisory 只展示 canonical StateStore 中的父责任，不证明 Agent 仍运行，也不替父任务验收结果。
- ObservationRecord 是收敛记录，不是 observation event log。

以上限制符合冻结设计，不是本次 NO-GO 的原因。

## 6. Backlog

- 获得官方或独立真实 TTL、刷新、乱序和跨重启正向保证后，才能通过新切片/新状态格式重新评估 freshness。
- freshness authority 成立且 parent Stop 的真实 Hook 展示、重入与 fail-open 完成独立验证后，才能重新评估 limited hard gate。
- 新 wrapper/status 形状必须先保存正向平台证据并新增失败测试，不能用通用递归 parser 预适配。

B1 不得降级进入 backlog，必须在当前 Slice 4 修复。

## 7. Not_checked

- 独立 SubagentStart/SubagentStop Hook payload 与顺序。
- parent Stop advisory 在真实 Codex UI 中的展示、重入和退出行为。
- Provider restart、compact/resume、乱序 observation 和跨版本 StateStore。
- Provider 内部日志面、Hook trust 与真实插件/Skill 加载。
- 新测试 cachebuster、稳定源、运行缓存、Marketplace、Registry 和发布包。
- 真实 Slice 4 smoke；因本次为 NO-GO，未获准创建。

## 8. 下一步准入

当前只允许回到同一 Slice 4 修复 B1，并在开发仓库补失败先行回归。修复后必须重新执行主动 malformed/error wrapper 反例、focused、全量 unittest、compile、validators、全部 JSON、Schema/runtime parity、diff 与 untracked whitespace，并重新进行独立验收。

在新的独立结论变为 GO 之前，不允许测试 cachebuster、新建 Slice 4 真实 smoke、部署、安装、同步缓存、修改 Hook trust、创建真实任务、启动 Slice 5 或发布。
