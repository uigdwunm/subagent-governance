# 平台能力 Slice 4：第三轮独立复验

日期：2026-08-15

结论：**NO-GO**。原始 B1 的两个样例与第二轮发现的 `error=0`、错误 `status/state` 被非错误字段遮蔽的旁路已经关闭，但 malformed `status/state` 仍可消费顶层 `agents` 并写入 exact-bound observation；机器语义与 runtime 的 wrapper 状态标签和 malformed policy 来源也仍未机械闭合。稳定冻结不变量因此仍被违反，不得进入测试 cachebuster 或新建 Slice 4 真实 smoke。

## 1. 范围、方法与写入边界

本次直接审查保存的开发仓库，不采信当前实现、测试或历史报告中的 PASS。证据从冻结设计、两份历史 NO-GO、当前 runtime、机器 Schema 和 focused tests 重新建立。审查开始时记录的目标文件 SHA-256 为：

| 文件 | SHA-256 |
| --- | --- |
| `platform-capability-slice-4-design.md` | `17875871748961da19687e5e3a7791163e479f2f2f281e40bece807e9a6a025c` |
| `platform-capability-slice-4-independent-review.md` | `87ccdd6528ec94db883e975986447c0791c27b8831420c1b652b7f21036ad7c2` |
| `platform-capability-slice-4-post-fix-independent-review.md` | `dc534f86913847d75e7bb798ae5e428217a206b8e04e5f873e090d92043e2872` |
| `scripts/subagent_governance.py` | `37acee44c5908b7e75720d22b7caf372bce6c11dee60c72d98cedce5af3f4748` |
| `schemas/governance-semantics.schema.json` | `d4d173f8479f228b7f070013f9ec8a645bd4f9c1daca2719b8ab99ec3cf84c7c` |
| `tests/test_platform_capability_slice4.py` | `b2094a8f108b930653981c2a1b2818b9cd2874e13cbe0500cc39cdc5f096efa1` |

全部主动状态测试均在 `TemporaryDirectory` 中创建隔离 `StateStore`、prepared 和 result 根目录。没有读取、修改或删除既有 smoke StateStore。除新增本报告外，没有修改实现、Schema、tests、fixtures、Skill、README 或既有报告；没有部署、安装、同步缓存、修改 Hook trust、创建真实任务、启动 Slice 5、提交或推送。

## 2. B1 与第二轮旁路状态

### 2.1 已关闭部分

- 原始 B1：`isError="true"` 与 `error="boom"` 的 object/JSON string、空/非空 `agents` 均 strict no-op。
- `isError/is_error`：缺失或严格布尔 `false` 才可消费合法 `agents`；`true` 及 null、0、1、字符串、对象、数组全部 strict no-op。80/80 通过。
- `error`：缺失、null、严格布尔 `false` 可消费；0、1、空字符串、非空字符串、对象、数组和 `true` 全部 strict no-op。40/40 通过，第二轮 `error=0` 旁路已关闭。
- 多布尔错误字段：两个字段都必须为严格布尔 `false`；任一 true 或非 bool 即 no-op，字段顺序不影响结果。200/200 通过。
- `status/state` 同时出现时，任一字段为 `error|failed|failure` 都会拒绝 wrapper；`status="ok" + state="error"` 等第二轮单字段优先级旁路在正反顺序、object/JSON string、空/非空 `agents` 下均已关闭。

### 2.2 Blocker B1：malformed `status/state` 仍可建立强观察事实

runtime 会遍历全部 `wrapper_status_fields`，但只拒绝能够由 `_native_status_tag()` 解析为 `error|failed|errored` 或硬编码 `failure` 的值。字段已出现但值为 null、false、0、1、空字符串、空对象、数组、多标签对象或 false-valued 单标签对象时，解析结果为 null，runtime 随后仍返回并消费顶层 `agents`。

最小非空反例：

```json
{
  "status": null,
  "agents": [
    {"agent_name": "<exact-target>", "agent_status": "completed"}
  ]
}
```

结果把 canonical observation 写成 `terminal + exact_dispatch_target + completed`，并进入结果缺口处置。最小空响应反例是在已建立 exact active 后提交：

```json
{"state": 0, "agents": []}
```

结果写成 `absent_at_check`。两类反例在 object/JSON string 下均改变完整 canonical execution 和 StateStore 原始字节；result 文件保持不变，但这不足以消除已经产生的错误 exact observation authority。

主动 wrapper 矩阵共 **824 个隔离用例：656 passed、168 failed**：

| 分组 | 结果 | 结论 |
| --- | --- | --- |
| `isError/is_error` 全类型、object/JSON、空/非空 | 80/80 | PASS |
| `error` 全请求值及额外 `true`、object/JSON、空/非空 | 40/40 | PASS |
| 单独 `status` 或 `state` | 40/112 | 72 个 malformed 变体错误消费 `agents` |
| `status/state` 同时出现、顺序互换 | 296/392 | 错误标签冲突已关闭；96 个 malformed 与合法标签组合仍旁路 |
| 多 boolean error flags、顺序互换 | 200/200 | PASS |

因此原 B1 不能判定整体关闭；第三轮发现的是同一 frozen malformed-wrapper 类别的稳定旁路，不得降级为 known limitation 或 backlog。

## 3. Machine semantic 与 runtime parity

主动 field-source parity 为 **10/12 PASS，2 FAIL**：

- PASS：`boolean_error_flags`、`explicit_error_field`、`wrapper_status_fields` 均由机器语义加载，字段值与 runtime 常量一致。
- PASS：Agent `active/advisory/terminal/error` 四组状态集合与 runtime 双向一致。
- PASS：已不存在 `status if present else state` 的单字段优先级；explicit `error` 也不再使用会让 `0 == False` 绕过的 equality 判定。
- FAIL：runtime 在 `_agent_status_entries()` 中直接并入硬编码 `{"failure"}`，机器语义没有 wrapper 状态标签集合来源。
- FAIL：机器语义声明 `malformed_or_explicit_error=no_exact_bound_fact`，runtime 没有消费该 policy，并把无法解析的已出现 wrapper status 当成可继续处理。

当前 Schema 的 Agent status 值集合本身一致，不代表 wrapper status field-source 一致。现有 focused test 只覆盖 error 标签冲突，没有覆盖单独或组合 malformed `status/state`，所以 428 个全量测试通过仍无法关闭该 blocker。

## 4. 其他主动不变量

除 wrapper blocker 外，独立主动检查按冻结边界通过。首轮脚本中有 45 个审查脚本断言把“未关闭”错误写成固定 `closure_state=open` 或固定 error execution status；这些断言不属于冻结规格，已丢弃且不计为产品失败。改为核对 `closed_at=null`、`attempt_closed!=true`、结果与 observation 平面分离后，接受的非 wrapper 机械断言为 **362/362 PASS**，父结果断言另为 **19/19 PASS**。

- exact canonical `path_prefix == agent_name == unique dispatch_target` 可绑定；broad、relative、missing、wrong scope，wrong/multiple response target 均 strict no-op。
- structuredContent、content、summary、history、final-history、transcript、malformed JSON、JSON scalar/array、malformed agents container/entry 均不被递归扫描。
- exact empty 只写 `absent_at_check`；非 canonical empty no-op，不生成 terminal、业务 failed、TaskResult、result 文件或关闭事实。
- `running|pending_init|completed|stopped|interrupted|errored|error|failed` 的 string/单标签对象与 object/JSON string 共 32 个状态用例全部按 active/advisory/terminal/error 规则收敛；每例 `fresh_until=null`。
- 平台 error 不生成业务 `failed`；Agent terminal 不生成 TaskResult。所有状态用例均保持 `business_result=null`、权威 result missing、attempt 未关闭。
- format 4 non-null `fresh_until` 被 Schema 与 runtime 拒绝，非法 StateStore 字节不重写；migration 产出 null。
- exact running 后 parent Stop 固定 `continue=true`、无 `decision=block`、有 advisory 且 StateStore 字节不变。两次 transient failure 后第三读成功；persistent failure 精确三读后告警 fail-open。
- 父任务 exact `task_id + attempt + sender_target` 成功记录结果，`submission_provenance=parent_recorded_native_sender`，observation 与 dispatch 逐字段不变。wrong task、attempt、sender 和 alias sender 均在写入前拒绝，StateStore 字节和文件集合不变。

## 5. 门禁数字

| 门禁 | 第三轮独立结果 |
| --- | --- |
| 主动 wrapper 交叉矩阵 | 824 cases：656 passed、168 failed（B1 malformed status） |
| 主动其他 observation/freshness/Stop/lifecycle | 362/362 accepted assertions PASS |
| 主动父结果与 invariant | 19/19 PASS |
| 主动 machine semantic field-source parity | 10/12 PASS、2 FAIL |
| Slice 4 focused | 5/5，OK |
| observation/wait/Stop/Schema focused | 123/123，OK |
| parent result focused | 11/11，OK |
| semantic/canonical parity tests | 44/44，OK |
| 全量 unittest | 428/428，OK |
| Python compile | PASS |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| 全部 JSON | 19/19，PASS |
| `git diff --check` | PASS |
| untracked whitespace | 报告写入后 60/60 个文本文件 PASS，0 issues |

绿门禁证明已编码范围没有回归；主动矩阵和 field-source parity 仍直接违反冻结不变量，所以总体必须为 NO-GO。

## 6. Known limitation

- adapter 只支持已有正向证据的顶层 `agents` object/JSON string；未知 wrapper 应保持 no-op/unknown，不递归猜测。
- format 4 没有 active freshness；exact running 可能立即陈旧，Stop 不能 hard-block。
- Stop advisory 只展示 canonical StateStore 中的父责任，不证明 Agent 当前仍运行，也不替父任务验收结果。
- ObservationRecord 是收敛记录，不是 observation event log。

这些限制符合冻结设计，不是本次 NO-GO 的原因。

## 7. Backlog

- 取得官方或独立真实 TTL、刷新、乱序和跨重启保证后，才能以新切片和新状态格式重新评估 freshness。
- freshness authority 成立且 parent Stop 的真实 Hook 展示、重入与 fail-open 完成独立验证后，才能重新评估 limited hard gate。
- 新 wrapper/status 形状必须先保存正向平台证据并增加失败先行测试；不得用递归 parser 预适配未知平台。

B1 malformed wrapper 与 field-source 缺口不得进入 backlog。

## 8. Not_checked

- 独立 SubagentStart/SubagentStop Hook payload、顺序与真实投递。
- parent Stop advisory 在真实 Codex UI 中的展示、重入和退出行为。
- Provider restart、compact/resume、乱序 observation 和跨版本 StateStore。
- Provider 内部日志面、Hook trust 与真实插件/Skill 加载。
- 测试 cachebuster、稳定源、运行缓存、Marketplace、Registry 和发布包。
- 真实 Slice 4 smoke；本次 NO-GO 未获准创建。

## 9. 下一步准入

当前只允许回到同一 Slice 4 修复 malformed `status/state` fail-open 与机器语义 field-source：机器语义应完整声明 wrapper 状态标签/分类与 malformed policy，runtime 只从该来源机械消费，并对每个已出现字段先完成形状与标签校验；任一 malformed 或 explicit error 都必须在读取 `agents` 前 strict no-op。

修复后必须新增失败先行测试，覆盖本报告的单字段/双字段、顺序互换、object/JSON string、空/非空矩阵，并重新执行全部主动矩阵与门禁。只有新的独立结论为 GO 后，才允许测试 cachebuster 和新建 Slice 4 真实 smoke；不得自行部署、安装、同步缓存、修改 Hook trust、创建其他真实任务、启动 Slice 5、提交或推送。
