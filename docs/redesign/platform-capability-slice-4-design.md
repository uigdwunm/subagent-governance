# 平台能力 Slice 4：观察、等待与 Stop 边界冻结

日期：2026-08-15

状态：边界已冻结；实施与本地验收记录见 `platform-capability-slice-4-implementation.md`。

## 1. 为什么现在需要 Slice 4

Slice 1 撤销了非官方 Hook 字段形成的强身份、强生命周期、强结果和 parent Stop 权威；Slice 2 建立四平面 canonical StateStore 与 exact target observation；Slice 3 已改为父任务根据当前原生 child final 记录 TaskResult，并在最新独立真实 smoke 中完成 record/read/accept/tombstone 闭环。

结果通道已经闭环后，剩余平台候选集中在 observation、等待和 parent Stop。现行材料同时留下三个散落候选：有限平台 observation adapter、active freshness、parent Stop limited hard gate。它们没有一份针对当前平台证据重新冻结的 Slice 4 规格。历史 `D6 S4` 是旧重设计阶段的恢复/会话闭环实施切片，不是本 Slice 4；旧 credential Slice 3 文档也不是当前能力依据。

本 Slice 必须先回答哪些事实已经得到正向平台证据、哪些仍只是字段或设想，再决定是否允许它们影响状态或阻止 parent Stop。

## 2. 唯一目标

把当前有正向证据的 exact-target `list_agents` 观察限制为一个显式、有限、可测试的 adapter，并机械固化以下结论：当前没有证据启用 active freshness 或 parent Stop hard gate；parent Stop 只展示 canonical action-required advisory，绝不据此阻止停止。

## 3. 输入证据与证据等级

| 输入 | 可支持的正向事实 | 不能支持的事实 |
| --- | --- | --- |
| `schemas/codex-hook-events-v1.contract.json` 与官方 Hook 字段契约 | PostToolUse 可观察 `tool_name`、`tool_input`、`tool_response`；Stop 可返回 Hook 决策对象 | `SubagentStart` 精确 attempt 身份、`SubagentStop` TaskResult、平台 active TTL |
| `docs/restart-interruption-reconciliation.md` 的真实事故证据 | `list_agents.agent_status` 实际存在字符串和单标签对象；精确空 `agents`、`pending_init`、`interrupt_agent.previous_status` 有已观察形态 | 空列表等于 terminal；`pending_init` 等于未启动；任意嵌套响应都可靠 |
| Slice 2 exact-target 回归与真实错误 fixture | `path_prefix == agent_name == unique dispatch_target` 可作为有限 observation 绑定前提；未知/错配不写强事实 | alias、broad query、唯一候选、时间邻近可绑定身份 |
| Slice 3 parent-authority smoke | 当前 child final、exact sender、record/read/accept/tombstone 可闭环，无断流或恢复 | 独立 Start/Stop Hook、parent Stop、freshness、Provider 内部日志面 |

Slice 3 的完整真实测试证据见 [`docs/real-platform-test-2026-08-15-cachebuster-20260815030436-slice3-parent-authority-smoke.md`](../real-platform-test-2026-08-15-cachebuster-20260815030436-slice3-parent-authority-smoke.md)。

## 4. 三个候选的准入裁决

### 4.1 有限平台 observation adapter：纳入

只接受当前已有正向证据的最小形状：

- PostToolUse 的原生 `list_agents`/`collaboration.list_agents` 响应；
- 顶层 JSON 对象或其 JSON 字符串形式；
- 顶层唯一 `agents` 数组，不递归读取 `content`、`structuredContent`、summary、final-history 或 transcript；
- query `path_prefix` 必须是绝对 canonical target；
- 非空响应必须只有一个 entry，且 `path_prefix == agent_name ==` 唯一 canonical `dispatch_record.dispatch_target`；
- `agent_status` 只接受已观察到的字符串或单标签对象；已知标签固定为 `running|pending_init|completed|stopped|interrupted|errored|error|failed`；
- 多标签、未知标签、错 target、broad/alias scope、嵌套代理数据、错误或不兼容形状不产生 exact-bound 强事实。

adapter 只规范观察，不调用 `wait_agent`/`list_agents`，不建立后台 scheduler，也不将平台 error 写成业务 failed。

### 4.2 active freshness：不纳入并退役

当前没有真实或官方正向证据定义可依赖的 active TTL、刷新事件、时钟来源、乱序优先级或跨重启保证。`observed_at` 只说明观察发生时间，不证明未来窗口内仍 active。

因此 `observation_record.fresh_until` 在当前 format 4 中固定为 JSON `null`。runtime 不生成、迁移不补造、Schema 不接受非 null 值，Stop 和任何决策视图都不得读取它形成 authority。未来若平台提供正式证据，必须以新切片、状态格式与乱序测试重新准入，不能在 Slice 4 上静默启用。

### 4.3 parent Stop limited hard gate：不纳入，保持 advisory

最新真实 smoke 明确把 parent Stop 标为 `not_checked`；官方 Hook 契约也没有提供 current、fresh、exact attempt active guarantee。即使 StateStore 保存 exact `running`，它仍可能是一次旧观察，不能安全阻止 parent Stop。

因此 Slice 4 删除 runtime 中保留的潜在 blocking 分支。StateStore 可读时，Stop 可以从 canonical action-required predicate 生成有界 advisory，但固定返回 `continue=true`；StateStore 不可读时仍在同一次处理最多三读，全部失败后告警并 fail-open。Stop 不验收 TaskResult，不改变 observation/identity/result/closure，不写 StateStore。

## 5. 状态转换

### 5.1 exact `list_agents`

| 输入 | ObservationRecord | execution/result/closure 边界 |
| --- | --- | --- |
| exact `running` | `active + exact_dispatch_target`，`fresh_until=null` | 可投影 running/wait；不生成结果，不使 Stop hard-block |
| exact `completed|stopped|interrupted` | `terminal + exact_dispatch_target + terminal_status` | Agent terminal 不等于 TaskResult；缺结果只进入已有 correction/disposition 路径 |
| exact `errored|error|failed` | `error + exact_dispatch_target` | 平台错误不等于业务 failed；只进入有限恢复/授权/耗尽路径 |
| exact `pending_init` 或未知已解析标签 | `unknown + exact_dispatch_target` | 保留 reconcile；不改成未启动、terminal 或 failed |
| exact 空 `agents` | `absent_at_check + exact_dispatch_target` | 单独不生成 terminal；只可与已认领同 target interrupt/not_found 的既有组合规则收口 |
| malformed、nested-only、错 scope、错/多 target | no mutation | unknown/fail-open 不补造 target、identity、terminal 或结果事实 |

### 5.2 parent Stop

```text
read StateStore (最多三次)
  ├─ 不可读 -> continue=true + degraded warning
  ├─ 无 action-required -> continue=true
  └─ 有 action-required -> continue=true + bounded advisory
```

任何分支都不返回 `decision=block`，也不消费或写入 `fresh_until`。

## 6. 明确不做

- 不扫描 transcript、summary、`last_assistant_message`、历史 final text 或 rollout metadata。
- 不恢复 SubagentStart/SubagentStop identity authority，不从 Agent name、alias、同名、唯一候选或时间邻近猜 attempt。
- 不重新引入 credential、bearer、child submit、parent relay 或 PreToolUse message 改写。
- 不新增 scheduler、后台等待、自动 list、自动恢复、自动 replacement 或第二套编排。
- 不把平台错误转成业务失败，不把 Agent terminal 转成 TaskResult，不让结果改变 observation/identity。
- 不部署、安装、发布、同步稳定源/运行缓存，不修改 Marketplace、Hook trust 或 Registry，不创建真实测试任务。

## 7. 退出条件

Slice 4 只有在以下条件全部满足后才可进入独立验收：

1. 机器语义明确记录有限 adapter、freshness disabled 和 Stop advisory-only，runtime 与 Schema 双向一致。
2. 失败先行测试覆盖 exact 正向形状、nested/malformed/错 target 负向、`fresh_until=null`、exact running 不 hard-block、Stop advisory 与三读 fail-open。
3. runtime writer 不生成 non-null freshness；current format 4 非 null freshness 被拒绝且不重写。
4. Skill 与能力契约明确禁止 transcript/summary 扫描、Start/Stop identity authority 和 hard gate。
5. focused、全量 unittest、Python compile、Plugin validator、Skill validator、JSON、Schema/runtime parity、`git diff --check` 与 untracked whitespace 全部通过。
6. 实施报告记录 blocker、known limitation、backlog、not_checked 和下一步准入结论。

满足这些条件只允许开始独立验收，不等于批准真实测试、Slice 5 或稳定发布。
