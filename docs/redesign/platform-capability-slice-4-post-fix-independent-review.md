# 平台能力 Slice 4：B1 修复后第二轮独立复验

日期：2026-08-15

结论：**NO-GO**。原 B1 报告中的两个精确样例已经关闭，但 B1 所代表的 malformed/error wrapper 类别仍存在稳定同类旁路，因此 B1 整体未关闭。不得进入测试 cachebuster、新建 Slice 4 真实 smoke、Slice 5、部署、安装、缓存同步、Hook trust 修改、真实任务、提交、推送或发布；当前只允许回到同一 Slice 4 修复。

## 1. 范围与方法

本次直接只读审查保存的开发仓库，不采信修复报告或新增测试的 PASS。除本报告外，没有修改实现、Schema、tests、fixtures、Skill、README 或既有报告，也没有读取、修改或删除任何既有 smoke StateStore。

所有主动反例均在 `TemporaryDirectory` 中创建独立 `StateStore` 和 result 根目录。对应为 no-op 的用例同时比较完整 canonical execution、StateStore 原始字节和 result 文件；不是只比较投影字段。

检查覆盖：

- 原 B1 两个精确样例；
- error flag/error/status/state 与 agents 的 object/JSON string、空/非空交叉矩阵；
- active/advisory/terminal/error Agent status 与 malformed/nested wrapper；
- exact scope/target、empty semantics、freshness const-null、Stop advisory-only；
- 父结果 `task_id + attempt + sender_target` 绑定与 observation invariant；
- focused、全量 unittest、compile、Plugin/Skill validator、全部 JSON、Schema/runtime parity、diff 和全部 untracked whitespace。

## 2. B1 状态

### 2.1 原两个样例：CLOSED

以下 object 输入使用 exact canonical `path_prefix` 和 exact completed agent 重放：

```json
{"isError":"true","agents":[{"agent_name":"<exact-target>","agent_status":"completed"}]}
```

```json
{"error":"boom","agents":[{"agent_name":"<exact-target>","agent_status":"completed"}]}
```

两例均为 strict no-op：完整 canonical execution 相等、StateStore 原始字节相等、`result_state=missing`、未关闭 closure，也没有生成 result 文件。相同内容的 JSON string 形式以及空 `agents` 变体也保持 no-op。

### 2.2 B1 类别：REOPENED / NOT CLOSED

扩展矩阵发现两个稳定同类旁路。

#### B1-a. `error=0` 被误当成合法无错误值

runtime 使用：

```python
value[LIST_AGENTS_EXPLICIT_ERROR_FIELD] not in (None, False)
```

Python 中 `0 == False`，因此类型非法的顶层 `error: 0` 被接受。object 与 JSON string、空与非空 agents 共 4 个变体全部发生 mutation：非空 completed 写成 exact terminal；在已建立 exact active 后，空 agents 写成 `absent_at_check`。这不是合法无错误 wrapper。

#### B1-b. `status/state` 冲突只检查第一个字段

runtime 使用 `status if present else state`。只要顶层存在非错误 `status`，明确错误的 `state` 就不再检查。例如：

```json
{
  "status": "ok",
  "state": "error",
  "agents": [
    {"agent_name": "<exact-target>", "agent_status": "completed"}
  ]
}
```

`status="ok" + state="error"`、`status="running" + state="failed"`、`status=null + state="error"` 的 object/JSON string、空/非空 agents 共 12 个变体全部发生 mutation。非空 agents 被写成 exact terminal，空 agents 在已有 exact active 后被写成 `absent_at_check`；StateStore 字节和 canonical execution 均改变。

### 2.3 Machine semantic 与 runtime field source：FAIL

机器语义声明了 `boolean_error_flags`、单个 `explicit_error_field` 和 Agent status 集合，但没有声明 wrapper 的 `status/state` 错误字段来源，也没有声明 runtime 额外硬编码的 `failure` 标签。runtime 随后直接读取 `status/state` 并使用优先选择，而不是消费一个完整、可机械对账的机器字段源。

值集合对账为 7/7 PASS，但 field-source parity 为 FAIL。现有 Slice 4 测试只覆盖单字段样例，没有覆盖 `error=0` 的严格类型边界或 `status/state` 同时出现时的冲突，因此 focused 和全量绿测不能关闭 B1。

## 3. 主动矩阵

### 3.1 Wrapper 交叉矩阵

最终交叉矩阵共 **163 checks：147 passed、16 failed**。

| 分组 | 结果 | 结论 |
| --- | --- | --- |
| `isError/is_error`：缺失、false、true、null、0、1、字符串、对象、数组；object/JSON；空/非空 agents | 80/80 | 缺失/false 可消费合法 agents；其余全部 strict no-op |
| `error`：缺失、null、false、空字符串、非空字符串、对象、数组；object/JSON；空/非空 agents | 28/28 | 缺失/null/false 可消费；其余保守 strict no-op |
| 额外 malformed `error=0` | 0/4 | 稳定旁路，B1-a |
| 多错误字段和 `status/state/agents` 冲突 | 24/36 | 12 个稳定旁路，B1-b |
| malformed JSON、JSON scalar/array、nested error/content/structuredContent/summary/final-history/transcript | 15/15 | 未递归扫描，strict no-op |

另行正向抽样 active、advisory、terminal、error Agent status 的 string/single-tag-object 与 object/JSON string 为 6/6 PASS。合法 wrapper 可分别建立 `active`、保守 `unknown`、`terminal`、`error` observation；terminal/error 未生成正式 TaskResult，也未关闭 closure。

### 3.2 Slice 1-4 关键不变量

独立主动回归共 **21/21 PASS**：

- exact canonical scope/target 正向可绑定；broad、wrong、missing、alias scope，以及 wrong/multiple response target 均 strict no-op；
- exact empty 在已确认 exact active 后只记录 `absent_at_check`，不生成 terminal、业务 failed、TaskResult 或 closed closure；非 canonical empty strict no-op；
- Schema 和 runtime 均拒绝 format 4 non-null `fresh_until`，非法 StateStore 原始字节不重写；
- exact running 后 Stop 固定 `continue=true`、无 `decision=block`、只显示 advisory，Stop 前后 StateStore 字节相同；transient 和 persistent read failure 均精确三读并 fail-open；
- 父任务 exact `task_id + attempt + sender_target` 可记录结果且 observation 逐字段不变；wrong task、attempt、sender 和 alias sender 在写入前拒绝，StateStore 字节不变且不创建 result 文件。

## 4. 门禁数字

| 门禁 | 第二轮独立结果 |
| --- | --- |
| 原 B1 两例 strict replay | 2/2 PASS |
| 扩展 wrapper 交叉矩阵 | 163 checks：147 passed、16 failed |
| exact/empty/freshness/Stop/parent-result 主动回归 | 21/21 PASS |
| Slice 4 focused | 5/5，OK |
| observation/wait/Stop/Schema 组合 focused | 77/77，OK |
| parent result focused | 11/11，OK |
| 全量 unittest | 428/428，OK |
| Python compile | PASS |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| JSON parse | 仓库内容 15/15 PASS；连同 4 个 `.git/worktrees` 元数据为 19/19 PASS |
| Schema/runtime value parity | 7/7 PASS |
| Schema/runtime field-source parity | **FAIL**；wrapper `status/state/failure` 仍由 runtime 硬编码 |
| `git diff --check` | PASS |
| untracked whitespace | 59/59 个未跟踪文本文件 PASS，0 issues |

门禁全绿部分只证明既有编码回归未失败；16 个主动失败和 field-source parity FAIL 均是冻结的 malformed/error wrapper no-op 不变量违例，因此总体仍为 NO-GO。

## 5. Blocker

- **B1 未关闭**：修复只关闭了首轮两个样例，没有关闭同类 wrapper。`error=0` 和 `status/state` 冲突能够稳定消费 agents 并写 exact-bound observation。
- 同一 blocker 还暴露机器语义与 runtime wrapper field source 不一致；仅继续增加 hardcoded bypass 不能满足验收。

同一 Slice 4 的修复至少需要：对 explicit `error` 使用严格类型/值判定，不能让整数零冒充布尔 false；把所有可形成 wrapper error 的字段和标签纳入单一机器语义来源；同时检查出现的全部错误字段，冲突时保守 no-op；补 object/JSON、空/非空、字段组合的失败先行回归。

## 6. Known limitation

- adapter 只支持已有正向证据的顶层 `agents` object/JSON string；未知 wrapper 应保持 no-op/unknown，不递归猜测。
- format 4 没有 active freshness；exact running 可能立即陈旧，Stop 不能 hard-block。
- Stop advisory 只展示 canonical StateStore 中的父责任，不证明 Agent 当前仍运行，也不替父任务验收结果。
- ObservationRecord 是收敛记录，不是 observation event log。

这些是冻结设计接受的限制，不是本次 NO-GO 的理由。

## 7. Backlog

- 取得官方或独立真实 TTL、刷新、乱序和跨重启保证后，才能以新切片/新状态格式重新评估 freshness。
- freshness authority 成立且 parent Stop 的真实 Hook 展示、重入和 fail-open 完成独立验证后，才能重新评估 limited hard gate。
- 新 wrapper/status 形状必须先保存正向平台证据并新增失败测试；不得用递归 parser 预适配未知平台。

B1 不得降级到 backlog。

## 8. Not_checked

- 独立 SubagentStart/SubagentStop Hook payload 与顺序；
- parent Stop advisory 在真实 Codex UI 中的展示、重入和退出行为；
- Provider restart、compact/resume、乱序 observation 和跨版本 StateStore；
- Provider 内部日志面、Hook trust 与真实插件/Skill 加载；
- 测试 cachebuster、稳定源、运行缓存、Marketplace、Registry 和发布包；
- 真实 Slice 4 smoke；因本次为 NO-GO，未获准创建。

## 9. 下一步准入

当前只允许回到同一 Slice 4 修复 B1-a、B1-b 和机器语义 field-source 缺口。修复后必须再次独立执行原 B1、完整交叉矩阵、关键不变量和全部门禁。

新的独立结论变为 GO 后，才允许测试 cachebuster 和新建 Slice 4 真实 smoke；GO 也不自动批准部署、安装、同步稳定源/运行缓存、修改 Hook trust、创建其他真实任务、启动 Slice 5、提交、推送或发布。
