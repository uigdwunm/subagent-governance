# 平台能力 Slice 4：第四轮最终独立复验

日期：2026-08-15

结论：**NO-GO**。历史 malformed/explicit-error wrapper 行为 blocker 已经关闭，4,128 项扩展隔离矩阵全部通过；但 `wrapper_status_parse_policy` 与 `malformed_or_explicit_error` 仍只是机器语义中的声明，runtime 没有读取或校验这两个 policy，field-source parity 只有 10/12。该缺口直接违反本轮“全部字段来源均由机器语义机械驱动”的稳定冻结准入条件，不能降级为 known limitation 或 backlog。

当前不得进入测试 cachebuster、新建 Slice 4 真实 smoke、Slice 5、部署、安装、缓存同步、Hook trust 修改、真实任务、提交、推送或发布；只允许继续同一 Slice 4 修复并重新独立复验。

## 1. 范围、方法与写入边界

本次直接审查保存的开发仓库，从冻结设计、三份历史 NO-GO、当前 runtime、机器 Schema 与测试重新建立证据，不采信当前实施报告中的 PASS。

全部主动状态均在 `TemporaryDirectory` 中创建隔离 `StateStore` 和结果目录。没有读取、修改或删除既有 smoke StateStore。除新增本报告外，没有修改实现、Schema、tests、fixtures、Skill、README 或既有报告；没有部署、安装、同步缓存、修改 Hook trust、创建真实任务、启动 Slice 5、提交或推送。

## 2. 历史 blocker 状态

### 2.1 Wrapper 行为 blocker：CLOSED

- 首轮 B1 的 `isError="true"`、`error="boom"` 已保持 strict no-op。
- 第二轮 B1-a 的 `error=0` 已关闭：只有缺失、JSON `null` 或 identity-exact boolean `false` 可继续。
- 第二轮 B1-b 的 `status/state` 字段优先级旁路已关闭：runtime 遍历所有已出现字段，字段顺序不影响裁决。
- 第三轮 malformed `status/state` 穿透已关闭：null、bool、number、空字符串、容器、多标签和 false-valued 单标签均在读取 `agents` 前 strict no-op。
- 第三轮硬编码 `failure` 标签缺口已关闭：wrapper error 标签集合来自机器语义，`_agent_status_entries()` 内不存在 `failure` 字面量旁路。

每个非法 wrapper 均同时比较完整 canonical execution、StateStore 原始字节和结果文件集合；三者全部不变。合法 wrapper 才可消费 `agents`。

### 2.2 Machine policy field-source：OPEN / BLOCKER

机器语义在 `platform_observation_adapter` 中声明：

```json
{
  "wrapper_status_parse_policy": "present_must_be_single_native_tag",
  "malformed_or_explicit_error": "no_exact_bound_fact"
}
```

runtime 会加载字段名、错误标签和四组 Agent 状态集合，当前硬编码行为也恰好符合这两个 policy；但 runtime 没有读取、保存、分派或拒绝未知的上述两个机器语义值。仓库搜索中两个键只出现在 Schema 和 focused test 的值断言中，不出现在 runtime；改变机器 policy 不会机械改变 adapter，也不会触发不兼容拒绝。

因此当前是“实现行为与声明相同”，不是“实现由机器声明驱动”。本轮明确要求后者，field-source parity 不能判 PASS。

## 3. 主动 wrapper 隔离矩阵

扩展矩阵共 **4,128/4,128 PASS**，超过前三轮 824 项矩阵，并覆盖 object/JSON string、空/非空 `agents`。空响应先用 exact running 建立 confirmed active 基线，确保合法空 wrapper 必须实际消费并写入 `absent_at_check`，非法空 wrapper 仍必须三重不变。

| 分组 | 结果 | 覆盖 |
| --- | --- | --- |
| 单 `isError/is_error` | 80/80 | 缺失、false、true、null、0、1、空/非空字符串、对象、数组 |
| 多 boolean flags | 648/648 | 两字段全类型组合、字段顺序互换、object/JSON、空/非空 agents |
| explicit `error` | 40/40 | 缺失、null、false、true、0、1、空/非空字符串、对象、数组 |
| 单 `status` 或 `state` | 160/160 | 缺失、合法字符串/单标签、四种 error 标签、null/bool/number/空字符串/容器/多标签/false-valued 单标签 |
| `status/state` 同时出现 | 3,200/3,200 | 全值交叉、顺序互换、object/JSON、空/非空 agents |

## 4. 其他主动不变量

独立主动断言 **269/269 PASS**：

- exact canonical `path_prefix == agent_name == unique dispatch_target` 可绑定；broad、relative、missing、wrong scope、wrong response target 和 multiple entries 均 strict no-op。
- `structuredContent`、`content`、summary、history、final-history、transcript、malformed JSON、JSON scalar/array、malformed agents container/entry 均不被递归扫描。
- exact empty 只写 `absent_at_check`；不生成 terminal、业务 failed、TaskResult、结果文件或关闭事实。
- `running|pending_init|completed|stopped|interrupted|errored|error|failed` 的 string/单标签对象与 object/JSON string 共 32 个状态用例均按 active/advisory/terminal/error 规则收敛，且 `fresh_until=null`。
- 平台 error 不生成业务 `failed`；Agent terminal 不生成 TaskResult。全部状态用例保持 `business_result=null`、权威 result missing、attempt 未关闭。
- format 4 non-null `fresh_until` 被 Schema 与 runtime 拒绝，非法 StateStore 原始字节不重写。
- exact running 后 parent Stop 固定 `continue=true`、无 `decision=block`、显示 advisory 且 StateStore 字节不变；两次 transient failure 后第三读成功，persistent failure 精确三读后告警 fail-open。
- 父结果 focused test 证明 exact `task_id + attempt + sender_target` 才能记录结果，且 observation invariant 保持；wrong task/attempt/sender/alias sender 在写入前拒绝，不生成结果文件。

## 5. Field-source parity

主动 field-source parity 为 **10/12 PASS、2 FAIL**：

| 来源 | 结果 |
| --- | --- |
| `boolean_error_flags` | PASS，runtime 从机器语义加载并遍历 |
| `explicit_error_field` | PASS，runtime 从机器语义加载 |
| `wrapper_status_fields` | PASS，runtime 从机器语义加载并遍历全部字段 |
| `wrapper_error_statuses` | PASS，runtime 从机器语义加载，无 `failure` 字面量旁路 |
| `wrapper_status_parse_policy` | **FAIL**，只在 Schema/test 中存在，runtime 未消费 |
| malformed/explicit-error policy | **FAIL**，只在 Schema/test 中存在，runtime 未消费 |
| active/advisory/terminal/error Agent 状态集合 | 4/4 PASS，均由机器语义双向加载 |
| 无 `failure` 硬编码旁路 | PASS |
| 无 `status if present else state` 优先级旁路 | PASS |

修复不能只继续增加行为回归；runtime 必须机械消费两个 policy，或在加载时只接受受支持值并对不一致 fail-fast，使 Schema 成为真实语义来源而非说明性常量。

## 6. 门禁数字

| 门禁 | 第四轮独立结果 |
| --- | --- |
| 主动 wrapper 扩展矩阵 | 4,128/4,128 PASS |
| 主动其他 observation/freshness/Stop/lifecycle | 269/269 PASS |
| 主动 machine semantic field-source parity | **10/12 PASS、2 FAIL** |
| Slice 4 focused | 5/5，OK |
| observation/wait/Stop/Schema focused | 61/61，OK |
| parent result focused | 11/11，OK |
| semantic/canonical parity tests | 44/44，OK |
| 全量 unittest | 428/428，OK |
| Python compile | PASS |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| 全部 repository JSON | 15/15，PASS |
| `git diff --check` | PASS |
| untracked whitespace | 报告写入后复核，见最终工作区检查 |

绿门禁证明当前行为没有已知 wrapper 穿透或其他 Slice 1-4 回归；它们不能覆盖明确失败的机器语义来源准入条件。

## 7. Known limitation

- adapter 只支持已有正向证据的顶层 `agents` object/JSON string；未知 wrapper 应保持 no-op/unknown，不递归猜测。
- format 4 没有 active freshness；exact running 可能立即陈旧，Stop 不能 hard-block。
- Stop advisory 只展示 canonical StateStore 中的父责任，不证明 Agent 当前仍运行，也不替父任务验收结果。
- ObservationRecord 是收敛记录，不是 observation event log。

这些限制符合冻结设计，不是本次 NO-GO 的原因。

## 8. Backlog

- 取得官方或独立真实 TTL、刷新、乱序和跨重启保证后，才能以新切片和新状态格式重新评估 freshness。
- freshness authority 成立且 parent Stop 的真实 Hook 展示、重入与 fail-open 完成独立验证后，才能重新评估 limited hard gate。
- 新 wrapper/status 形状必须先保存正向平台证据并增加失败先行测试；不得用递归 parser 预适配未知平台。

两项 machine policy field-source 缺口不得进入 backlog。

## 9. Not_checked

- 独立 SubagentStart/SubagentStop Hook payload、顺序与真实投递。
- parent Stop advisory 在真实 Codex UI 中的展示、重入和退出行为。
- Provider restart、compact/resume、乱序 observation 和跨版本 StateStore。
- Provider 内部日志面、Hook trust 与真实插件/Skill 加载。
- 测试 cachebuster、稳定源、运行缓存、Marketplace、Registry 和发布包。
- 真实 Slice 4 smoke；本次 NO-GO 未获准创建。

## 10. 下一步准入

当前只允许继续同一 Slice 4 修复 `wrapper_status_parse_policy` 与 malformed/explicit-error policy 的 runtime 机器来源，并补充能证明 policy 被消费或不兼容值会 fail-fast 的双向 parity 测试。修复后必须重新执行 field-source parity、主动 wrapper 矩阵和全部门禁。

只有新的独立结论为 GO 后，才允许后续测试 cachebuster 与新建 Slice 4 真实 smoke；GO 也不自行批准部署、安装、同步缓存、修改 Hook trust、创建其他真实任务、启动 Slice 5、提交或推送。
