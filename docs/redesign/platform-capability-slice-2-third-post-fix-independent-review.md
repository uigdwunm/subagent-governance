# 平台能力契约重设计：Slice 2 第三轮修复后独立复验

日期：2026-08-14

结论：**GO**。第二轮报告中的 empty-response runtime alias blocker 已关闭；empty 与非空 `list_agents` 路径都只接受唯一 canonical `dispatch_record.dispatch_target` 作为 observation authority。NB2、原 B1-B4、retired parity、single canonical authority、CAS/concurrency 和 Slice 1 Hook fail-open 均未回退。未发现新 blocker；从本地 Slice 2 独立验收角度可以进入 Slice 3，但本任务未启动 Slice 3。

## 1. 审查范围与边界

本轮重新阅读并检查：

- `docs/redesign/platform-capability-slice-2-implementation.md`
- `docs/redesign/platform-capability-slice-2-blocker-fixes.md`
- 本轮 runtime、tests 和共享工作树 diff

所有独立反例均使用临时 StateStore。未读取、修改或删除既有 smoke StateStore。除本报告外未修改实现、Schema、tests、fixtures 或既有文档；未部署、安装、发布、提交或推送；未创建真实测试任务；未启动 Slice 3。

## 2. Empty-Response Blocker 复验

### 2.1 Runtime alias strict no-op：PASS

重新运行第二轮最小反例：已有 canonical exact active observation，`agents["/root/runtime-alias"]` 指向该 attempt，随后收到：

```python
tool_input = {"path_prefix": "/root/runtime-alias"}
tool_response = {"agents": []}
```

修复前会把 execution 从 `active/confirmed/running` 改成 `unknown/unconfirmed/not_started`。修复后 compatibility view 与持久化 raw canonical execution 均完整相等；subject、binding、observation、result、closure、identity projection、execution projection 和 execution timestamps 均未变化。

另对 broad `/root`、wrong path 和 zero-match path 做 raw canonical execution 比较，均为 strict no-op。

### 2.2 非 canonical empty scope：PASS

独立矩阵覆盖：

| 输入 | 结果 |
| --- | --- |
| absolute runtime alias，且 `agents` 有 active mapping | execution strict no-op |
| broad `/root`，且 `agents` 有 mapping | execution strict no-op |
| wrong/different absolute path，且 `agents` 有 mapping | execution strict no-op |
| missing `path_prefix` | fail-open，execution strict no-op |
| zero canonical match | execution strict no-op |
| 同 target 两个 canonical execution matches | 两个 execution 均 strict no-op |

所有路径都在 `_ensure_canonical_task_record()` 和任何 execution writer 之前返回；没有生成 absent、terminal、failed、confirmed 或 stopped，也没有覆盖已有 observation。

### 2.3 Unique exact canonical empty：PASS

无 Start、无 `agents` active index，但已有同 execution 的 exact canonical active observation时，唯一 exact `path_prefix` + empty response 得到：

```text
observed_state=absent_at_check
binding_basis=exact_dispatch_target
identity_status=confirmed
execution_status=not_started  # compatibility projection
terminal_status=None
business_result=None
result_state=missing
```

该路径只形成保守 absence observation，不生成 terminal 或业务 failed。

### 2.4 Reliable interrupt/not-found 收敛：PASS

唯一 exact canonical empty 与同 target、已认领且 `call_observation=success + target_observation=not_found` 的可靠 interrupt 组合仍可沿冻结规则收敛：

```text
observed_state=terminal
execution_status=stopped
parent_action=decide_disposition
business_result=None
```

`last_lifecycle_operation` 被消费；该路径没有从 empty response 单独推导业务结果。

### 2.5 Empty 入口审计：PASS

runtime 中 `agents=[]` 只经 `_agent_status_entries()` 后的单一 `if not entries` 分支进入 `_record_exact_absence()`。当前 `_record_exact_absence()` 在 `scripts/subagent_governance.py:7565` 首先调用 `_resolve_exact_dispatch_target_attempt()`；resolver 在 `scripts/subagent_governance.py:7636` 只扫描 managed execution 的 `dispatch_record.dispatch_target` 并要求恰好一个 match。

empty writer 不再调用 `_managed_target_attempt()`，也不读取 `agents` alias、active index、Start identity、runtime alias 或同名字符串建立 authority。未发现第二个 empty response writer 或旁路。

## 3. 无回退验证

| 项目 | 结论 | 独立证据 |
| --- | --- | --- |
| 非空 NB1 三重等值 | PASS | 9 组 broad/wrong/missing/alias/different response/multi response/zero/multi canonical 负向保持保守；唯一 exact query=response=dispatch target 正向 terminal 收敛。 |
| NB2 migration | PASS | format 1 与无版本 read 不回写；no-op update 后均为 format 2、`dispatch_kind=initial_spawn`、完整 `canonical_state` 0 errors。 |
| 原 B1 exact binding | PASS | legacy missing/mismatch 保守，exact 才绑定；format-2 cross-plane mismatch 拒绝且不回写。 |
| 原 B2 result/closure | PASS | 4 组弱/矛盾 result 不携带 business result；完整一致证据才迁移；wrong task/attempt disposition 不迁移。 |
| 原 B3 retired parity | PASS | Schema boolean-false 与 runtime strip set 为 35/35；35 个字段逐项 no-op write 均不回写。 |
| 原 B4 canonical authority | PASS | `spawn_not_created` 扩展不改变 admission/allowed actions；not-created 只由 `dispatch_record` 派生。 |
| Raw/projected 与 Schema/runtime | PASS | raw canonical valid、projected view rejected、四平面 field parity 保持一致。 |
| CAS/concurrency | PASS | 跨进程 compare-and-set one commit/one conflict；并发 dispatch preparation 通过。 |
| Slice 1 Hook fail-open | PASS | official key contract、unbound Start/Stop、unknown extension、StateStore failure 与 parent Stop advisory 行为未回退。 |

## 4. 分类

### Blocker

无。

### 已知限制

- compatibility readers 尚未全部直接消费 plane record。
- 每个 execution 保存收敛后的 ObservationRecord，而不是 observation event log。
- `fresh_until` 尚未驱动 hard gate；parent Stop 继续 advisory/fail-open。
- result credential、secret hash、签发/消费/撤销和真实 child submit 尚未实现；这些属于 Slice 3。

### Backlog

- 物理删除已退役 transcript/Start identity/result-gap helper。
- 逐项退役剩余 compatibility reader。
- observation event history、乱序审计与版本能力矩阵扩展。

### Not Checked

- 未捕获真实 raw Hook stdin，未验证真实 SubagentStop、SessionStart、SessionEnd、wait/mailbox 或 `list_agents` wire shape。
- 未验证 credential 暴露面、provider restart、compact/resume、真实乱序/重复事件或跨版本平台行为。
- 未安装或同步插件，未创建真实 Codex 测试任务。
- 未检查稳定发布源、运行缓存、Marketplace、Hook trust、Registry 或既有 smoke StateStore 内容。

这些项目受本轮冻结边界约束，不构成本地 Slice 2 blocker；Slice 3 和发布验收仍需各自完成对应验证。

## 5. 门禁数字

| 门禁 | 结果 |
| --- | --- |
| 独立 empty matrix | 8 cases，全部符合预期；另有 4 类 raw canonical execution strict no-op 比较 |
| 非空 NB1 | 9 负向 + 1 无 Start 正向，PASS |
| NB2 | format 1 + 无版本，均 0 Schema errors |
| 原 B1-B4 | PASS；retired 35/35，weak result 4 cases |
| Focused unittest | 234 tests，OK |
| 完整 unittest | 409 tests，OK |
| CAS/concurrency | 2 tests，OK；包含 one-commit/one-conflict |
| Python compile | `scripts/` + `tests/` 24 files，passed；pycache 定向到 `/tmp` |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| 全部 JSON parse | 17 files，passed |
| `git diff --check` | passed |
| untracked whitespace | passed；包含本报告共 47 files |

## 6. GO/NO-GO

**GO。** 第二轮 empty-response canonical target blocker 已关闭，没有新 blocker。Slice 2 的本地独立验收条件满足，可以进入 Slice 3。

此 GO 只覆盖开发仓库内 Slice 2 能力契约、runtime、Schema、fixtures、tests 和本地门禁。它不等于部署、发布、真实平台兼容或 Slice 3 credential 验收；本任务未执行这些动作。
