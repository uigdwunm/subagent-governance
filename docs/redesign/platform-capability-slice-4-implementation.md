# 平台能力 Slice 4 实施记录

日期：2026-08-15

状态：开发仓库实现与本地门禁完成；可以开始独立验收。未部署、未安装、未发布、未创建真实测试任务，未批准 Slice 5。

## 1. 目标与冻结结论

本 Slice 从当前官方 Hook 契约、真实 restart interruption 证据、Slice 2 exact-target 回归和 Slice 3 parent-authority smoke PASS 出发，重新评估三个候选。冻结设计见 `platform-capability-slice-4-design.md`。

唯一目标是加固 observation、等待和 parent Stop 边界，不扩大平台 authority：

- 纳入有限 `list_agents` observation adapter；
- 不启用 active freshness，`fresh_until` 退役为 const null；
- 不启用 parent Stop limited hard gate，Stop 固定 advisory + `continue=true`。

历史 `D6 S4` 是旧恢复/会话闭环切片，旧 credential Slice 3 也已被父任务权威结果通道替代，两者都没有被误用为本 Slice 规格。

## 2. 失败先行

实现前新增 `tests/test_platform_capability_slice4.py` 并独立运行 4 项：

| 失败先行检查 | 实现前结果 | 暴露缺口 |
| --- | --- | --- |
| Slice 4 machine contract | error | 缺少 `platform_observation_adapter` 与 Slice 4 Stop/freshness 语义 |
| non-null freshness 拒绝 | failure | Schema 与 runtime 仍接受整数 `fresh_until` |
| exact running + Stop advisory | error | exact running 已保持 nonfresh，但 Stop 没有可见 advisory |
| nested/summary 不扫描 | pass | 既有 runtime 已保持 top-level-only no-op 边界 |

首次结果：**4 项，1 pass、1 failure、2 errors**。失败均与冻结规格直接对应，没有依赖 timing、网络或外部状态。

## 3. 实现

### 3.1 有限 observation adapter

`governance-semantics.schema.json` 新增 `platform_observation_adapter` 机器语义。runtime 从该语义加载 active、advisory、terminal 和 error 原生状态集合，避免代码与 Schema 各自维护标签。

adapter 只读取 PostToolUse 顶层对象或 JSON 字符串中的顶层 `agents`。非空响应仍必须满足：

```text
tool_input.path_prefix
  == response.agents[0].agent_name
  == unique execution.dispatch_record.dispatch_target
```

状态只接受字符串或单标签对象。`content`、`structuredContent`、summary、final-history、transcript、多标签、错 scope、错/多 target 和 malformed 形状不建立 exact-bound 强事实。exact error 只改变 observation/recovery 路径，不生成业务 failed；exact terminal 不生成 TaskResult。

### 3.2 active freshness 退役

`observation_record.fresh_until` 保留 required 字段以维持 format 4 记录形状，但 Schema 改为 `type=null`。runtime current-plane validator 同样拒绝 non-null，并在错误中明确 active freshness 当前禁用。

initial、legacy migration 和所有 observation writer 继续只写 null。`observed_at`、exact running、StateStore `updated_at`、recent activity 和等待时间均不能推导 freshness。

### 3.3 Stop advisory-only

删除 `_managed_stop_blocking()` 和 `_stop_blocking_records()` 潜在 hard-block 分支。Stop 直接消费共享 canonical `_action_required_records()`：

- 无 action-required：`continue=true`；
- 有 action-required：`continue=true + bounded systemMessage`，明确只作 advisory；
- StateStore 不可读：同一次最多三读，全部失败后 `continue=true + degraded warning`。

Stop 不返回 `decision=block`，不读 `fresh_until`，不写 StateStore，不验收 TaskResult，也不改变 observation、identity、result 或 closure。

## 4. 不变量验收

本实现保持：

1. 平台 error 不等于业务 failed。
2. Agent terminal 不等于 TaskResult；缺结果只进入既有 correction/disposition。
3. ResultRecord 不改变 observation 或 identity。
4. 只有 exact canonical target observation 有权；active index、alias、broad query、唯一候选和时间邻近无权。
5. unknown/malformed/fail-open 不递归扫描或补造事实。
6. observation 更新继续走 StateStore update/CAS 与 canonical 四平面 writer；未引入第二写入源。
7. 父任务结果继续精确绑定 `task_id + attempt + sender_target` 三元组；Slice 4 未修改结果入口。
8. 未恢复 Start/Stop identity authority，未引入 credential、message Hook 改写或第二套编排。

## 5. 验证

最终门禁数字：

| 门禁 | 最终结果 |
| --- | --- |
| Slice 4 focused | 5/5，OK |
| observation/wait/Stop/Schema focused | 144/144，OK |
| release-preflight/WP-08 regression | 10/10，OK |
| `python3 -m unittest discover -s tests -v` | 428/428，OK |
| `python3 -m py_compile scripts/subagent_governance.py` | PASS |
| Plugin validator | PASS |
| Skill validator | PASS |
| repository JSON parse | 15/15，PASS |
| Schema/runtime parity | PASS；adapter status sets、freshness const-null、四平面字段/枚举双向测试通过 |
| `git diff --check` | PASS |
| untracked whitespace | PASS |

全量首次运行曾为 424/427，3 errors：一个旧 WP-08 测试仍直接引用已删除 blocking helper；两个 release-preflight error 来自起始 Slice 3 文档中的主机绝对路径。前者改为断言 blocking helper 已退役，后者改为非主机绑定的测试部署路径表示；定向 10/10 与最终全量均通过。这些修复不写稳定源或运行缓存。

首次独立验收随后发现 B1：带畸形 `isError/is_error` 或明确顶层 `error` 的 wrapper 仍可夹带 `agents` 并建立 exact terminal。修复后，错误标志字段、显式错误字段和拒绝策略均进入 `platform_observation_adapter` 机器语义；runtime 在读取 `agents` 前拒绝非布尔错误标志、真错误标志和明确错误内容。新增 5 组 object/JSON-string 回归证明这些响应严格 no-op，首轮验收报告保留为历史 NO-GO 证据。

第二轮独立复验确认原两例关闭，但扩展矩阵发现 `error=0` 会因 Python 相等比较被误当作 `False`，且同时存在 `status/state` 时只核对首个字段。修复将 `wrapper_status_fields=[status,state]` 纳入机器语义并逐字段拒绝 error/failure；显式 `error` 只允许 identity-exact `None` 或 `False`，整数 0 不再被接受。对应回归覆盖双字段冲突和两种字段顺序，第二轮报告继续保留为历史 NO-GO 证据。

第三轮独立复验确认前述旁路关闭，但发现已出现且不可解析的 `status/state` 仍会继续消费 `agents`，同时 wrapper 的 `failure` 标签仍是 runtime 硬编码。修复新增机器语义 `wrapper_error_statuses` 与 `wrapper_status_parse_policy=present_must_be_single_native_tag`；runtime 逐个解析所有已出现的 wrapper 状态字段，任一解析失败或命中 wrapper 错误标签即 strict no-op。回归覆盖 null、bool、number、空字符串、容器、多标签、false-valued 单标签和合法/畸形双字段组合；第三轮报告保留为历史 NO-GO 证据。

第四轮独立复验的 4,128 项 wrapper 行为矩阵全部通过，但发现 `wrapper_status_parse_policy` 与 `malformed_or_explicit_error` 尚未被 runtime 读取。修复将两项 policy 加载为运行时常量并在模块初始化时只接受当前机器语义值；任何不兼容 Schema policy 都会 fail-fast，不能静默沿用旧 adapter 行为。focused parity 同时核对 runtime 常量与机器语义原值；第四轮报告保留为历史 NO-GO 证据。

## 6. Blocker、限制与 Backlog

### Blocker

开发仓库范围内没有已知 blocker。

### Known limitation

- adapter 只支持已有真实证据的顶层 `agents` 形状；未来平台若只提供新的 wrapper，当前行为会保持 no-op/unknown，不递归猜测。
- current format 4 无 active freshness；exact running 可能很快变旧，因此 Stop 不能 hard-block。
- Stop advisory 只能提示 canonical StateStore 已知责任，不能证明平台 Agent 当前仍运行，也不能替父任务验收结果。
- 每个 execution 仍保存收敛后的 ObservationRecord，不是 observation event log。

### Backlog

- 只有获得当前官方或独立真实测试的正向 TTL、刷新、乱序和跨重启保证后，才能以新切片/状态格式重新评估 active freshness。
- 只有 freshness authority 成立且 parent Stop 的真实 Hook 展示、重入与 fail-open 行为完成独立验证后，才能重新评估 limited hard gate。
- 新的真实 `list_agents` wrapper/status 形状必须先保存正向证据并新增失败测试，再扩展机器 adapter；不得用通用递归 parser 预适配未知平台。

### not_checked

- 独立 SubagentStart/SubagentStop Hook payload 与顺序；
- parent Stop advisory 在真实 Codex UI 中的展示、重入和退出行为；
- Provider restart、compact/resume、乱序 observation 和跨版本 StateStore；
- Provider 内部日志面、Hook trust 与真实插件/Skill 加载；
- 新测试 cachebuster、稳定源、运行缓存、Marketplace、Registry 和发布包。

本任务按授权没有部署、安装、发布、同步缓存、修改 Hook trust/Marketplace/Registry、创建真实测试任务、提交或推送，也没有读取、修改或删除既有 smoke StateStore。

## 7. 下一步准入

结论：**GO，仅允许开始 Slice 4 独立验收**。

独立验收应复跑 exact/malformed/nested observation、non-null format 4 state、Stop action-required/no-action/read-failure 和 parent result 三元组不变性反例。它不得自行部署、创建真实 smoke、启动 Slice 5 或批准稳定发布；这些动作需要后续明确授权和新的准入结论。
