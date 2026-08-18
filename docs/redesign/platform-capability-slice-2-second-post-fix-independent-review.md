# 平台能力契约重设计：Slice 2 第二轮修复后独立复验

日期：2026-08-14

结论：**NO-GO**。NB2 已关闭，原 B1-B4 及主要回归门禁未回退；NB1 的非空 `list_agents` 路径已满足三重机械等值和唯一 canonical target 要求，但空响应路径仍信任 `agents` runtime alias。一个 alias-scoped empty response 可以覆写既有 exact active observation，使 execution 从 `confirmed/running` 降为 `unconfirmed/not_started`。这是同类 canonical authority blocker，Slice 2 不能验收，不得进入 Slice 3。

## 1. 范围与冻结边界

本轮重新阅读最新：

- `docs/redesign/platform-capability-slice-2-blocker-fixes.md`
- `docs/redesign/platform-capability-slice-2-implementation.md`
- 本轮 runtime、Schema、fixtures、tests 和共享工作树 diff

复验不接受实施任务的 PASS 声明作为充分证据。NB1/NB2 和原 B1-B4 均使用临时目录中的独立 StateStore 或纯迁移断言重放；未读取、修改或删除既有 smoke StateStore。

除本报告外未修改实现、Schema、fixture、测试或既有文档。未部署、安装、发布、提交或推送；未创建真实测试任务；未启动 Slice 3。

## 2. NB1：非空路径通过，空响应仍有 blocker

### 2.1 已通过部分

独立非空矩阵确认以下输入均保持 `not_observed + none + unconfirmed + not_started`，不生成 exact、terminal、confirmed 或 stopped：

- broad `/root`；
- wrong prefix、missing prefix；
- 非 path runtime alias；
- `/root/...` runtime alias，即使 `agents` 中存在映射；
- query target 与 response target 不同；
- 多 response entries；
- canonical dispatch target 零匹配或多匹配。

只有原样 `path_prefix == 唯一 response agent_name == 唯一 dispatch_record.dispatch_target` 才可收敛。无 Start、无 active index 的 exact 正向路径仍得到：

```text
terminal + exact_dispatch_target + confirmed + stopped
```

实现中非空路径先在 `scripts/subagent_governance.py:7680-7697` 检查 exact query 和唯一同名返回项，再由 `scripts/subagent_governance.py:7636-7647` 要求唯一 canonical dispatch target；该部分关闭了上一轮 NB1。

### 2.2 新 blocker：empty response 仍以 runtime alias 作为 observation authority

严重性：blocker。

最小复现使用 format-2 临时 StateStore：同一 execution 已有 exact canonical target 的 active observation，同时 `agents["/root/runtime-alias"]` 指向该 attempt。随后调用：

```python
handle({
    "session_id": "slice-2-legacy",
    "hook_event_name": "PostToolUse",
    "tool_name": "list_agents",
    "tool_input": {"path_prefix": "/root/runtime-alias"},
    "tool_response": {"agents": []},
    "now": 150,
}, store)
```

实际持久化结果：

```text
handle_result None
before /root/sg_standard_slice_2_legacy_t_0123456789ab active confirmed running
after  /root/runtime-alias unknown unconfirmed not_started
```

原因是空响应在 `scripts/subagent_governance.py:7683-7690` 直接进入 `_record_exact_absence()`；该函数在 `scripts/subagent_governance.py:7565-7595` 使用 `_managed_target_attempt()` 的 `agents` 索引解析 attempt，而没有使用非空路径的 `_resolve_exact_dispatch_target_attempt()`。`_list_agents_exact_target()` 只检查字符串以 `/` 开头，并不能证明它是该 execution 的唯一 canonical dispatch target。随后 `platform_observation_target=alias` 清除 exact binding 并覆写原 observation。

这不是“错 scope 没有生成 terminal”即可接受的保守 no-op：错误 scope 已改变 managed canonical observation、identity 和 execution projection。runtime alias、broad path 或其他错误 absolute prefix 不能建立或覆写 observation authority。

精确修复范围应限于 empty `list_agents` 路由：在任何 mutation 前机械要求 query target 唯一匹配同 execution 的 `dispatch_record.dispatch_target`；不得从 `agents` alias、Start、active index、同名猜测或全局非唯一匹配取得 authority。exact canonical empty 的既有正向行为应保留。

## 3. NB2：PASS

format 1 与无版本 fixture 均满足：

- read-only `read()` 不改原文件；
- no-op locked update 后 raw `state_format_version=2`；
- 完整 `canonical_state` 校验为 0 errors；
- legacy `dispatch_kind=initial` 确定迁移为 `initial_spawn`。

独立输出：

```text
NB2_MIGRATION 1    2 initial_spawn 0
NB2_MIGRATION None 2 initial_spawn 0
```

legacy contract fallback 保守：优先使用合法 retained contract；缺失或非法字段使用 `work_item.objective_summary`、空 scope/evidence 列表和显式 parent-review completion condition，不伪造业务完成事实。弱、矛盾、missing 或 storage-error result 不携带 business result；合法完整结构化证据才迁移结果。unknown version 与损坏 format-2 plane 均拒绝且字节不变。

## 4. 原 B1-B4 与回归

| 项目 | 结论 | 独立证据 |
| --- | --- | --- |
| 原 B1 exact binding | **PASS（不含本轮新 empty-scope blocker）** | legacy missing 保持 `not_observed`，mismatch 为 unbound `unknown`，exact 才 terminal；format-2 cross-plane mismatch 拒绝且不回写。 |
| 原 B2 result/closure migration | **PASS** | 4 组弱/矛盾证据均无 business result；完整 valid/available/reference/SHA/time 证据保留结果；wrong task 与 wrong attempt disposition 均不迁移。 |
| 原 B3 retired parity/strip | **PASS** | Schema boolean-false fields 与 runtime strip set 双向一致，共 35 个；35 个字段逐项注入后 no-op write 均不回写。 |
| 原 B4 single canonical authority | **PASS** | `spawn_not_created=false/true` 不改变 allowed actions；`dispatch_state=rejected` 才派生 retry，`acknowledged + spawn_not_created=true` 不派生 not-created。 |

其他回归结论：

- empty、pending/unknown/error 不推导 terminal 或业务 failed；
- format-2 非语义 forward extension 可保留，但不改变 admission/allowed actions；
- raw canonical state 通过 Schema，compatibility-projected view 被拒绝；四平面 field parity 保持一致；
- 跨进程 CAS one-commit/one-conflict 与完整 concurrency suite 通过；
- Slice 1 official Hook contract、额外 correctness-critical field detector、unbound Start/Stop、unknown Stop extension、transcript variation、StateStore unreadable 与 parent Stop fail-open 未回退。

同类旁路搜索发现的唯一新 blocker 是 NB1 empty 分支。非空分支已经统一使用唯一 canonical dispatch target resolver；migration core-field fallback 未发现第二条绕过完整 canonical validation 的写入路径。

## 5. 分类

### Blocker

1. NB1 empty response scope bypass：absolute runtime alias 可借 `agents` 索引覆写 exact canonical observation，破坏 single canonical dispatch-target authority。

### 已知限制

- compatibility readers 尚未全部直接消费 plane record。
- 每个 execution 保存收敛后的 ObservationRecord，而非 observation event log。
- `fresh_until` 尚未驱动 hard gate；parent Stop 仍按设计 advisory/fail-open。
- result credential、签发/消费/撤销和真实 child submit 尚未实现，属于 Slice 3，且本轮未启动。

### Backlog

- 物理删除已退役 transcript/Start identity/result-gap helper。
- 逐项退役剩余 compatibility reader。
- observation event history、乱序审计与版本能力矩阵扩展。

### Not Checked

- 未捕获真实 raw Hook stdin，未验证真实 SubagentStop、SessionStart、SessionEnd、wait/mailbox 或 `list_agents` wire shape。
- 未验证 credential 暴露面、provider restart、compact/resume、真实乱序/重复事件或跨版本平台行为。
- 未安装或同步插件，未创建真实 Codex 测试任务。
- 未检查稳定发布源、运行缓存、Marketplace、Hook trust、Registry 或既有 smoke StateStore 内容。

## 6. 门禁数字

| 门禁 | 结果 |
| --- | --- |
| NB1 非空独立矩阵 | 9 组负向 + 1 组无 Start 正向，符合预期 |
| NB1 empty alias 最小反例 | **FAIL，稳定持久化错误 observation mutation** |
| NB2 独立迁移 | format 1 + 无版本均为 format 2、`initial_spawn`、0 Schema errors |
| 原 B1-B4 独立断言 | PASS；retired 35/35，weak result 4 组 |
| Focused suite | 230 tests，OK |
| 完整 unittest | 405 tests，OK |
| Python compile | `scripts/` + `tests/` 24 files，passed；pycache 定向到 `/tmp` |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| 全部 JSON parse | 17 files，passed |
| `git diff --check` | passed |
| untracked whitespace | passed；包含本报告共 46 files |

## 7. GO/NO-GO

**NO-GO。** NB2 可以验收，NB1 不能验收。现有 405 项测试和全部静态门禁为绿，但没有覆盖“既有 exact active observation + runtime alias index + empty response”组合。

恢复 GO 至少需要在同一 Slice 2 范围内修复 empty response resolver，使任何 observation mutation 都只能由唯一 canonical `dispatch_record.dispatch_target` 授权，并补充 alias/broad/wrong/zero/multiple empty-scope 回归，同时保留 exact canonical empty 与无 Start exact terminal 正向路径。修复后应重新执行本报告全部门禁和新的独立复验；在此之前不得进入 Slice 3。
