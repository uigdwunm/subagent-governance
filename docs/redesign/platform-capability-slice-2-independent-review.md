# 平台能力契约重设计：Slice 2 独立验收

日期：2026-08-14

结论：**NO-GO**。本轮发现 4 组可稳定复现的 blocker，分别违反 exact observation 绑定、legacy 结果/closure 保守迁移、retired 字段不回写和四平面单一 canonical authority 冻结不变量。未修改实现、Schema、fixture、测试或既有文档；本文件是唯一新增文件。

## 1. 审查范围与边界

本轮完整阅读并以以下文件为验收基线：

- `AGENTS.md`
- `docs/redesign/platform-capability-contract-and-minimal-state-machine.md`
- `docs/redesign/platform-capability-slice-1-implementation.md`
- `docs/redesign/platform-capability-slice-2-implementation.md`
- 当前共享工作树中的 runtime、Schema、fixtures 和 tests

只读审查覆盖：

1. format-2 raw Schema、compatibility projection 和写盘剥离边界；
2. managed execution 的 dispatch、observation、result、closure 写入路径；
3. format 1/无版本迁移对 running、缺失 lifecycle、exact/unbound observation、result 和 closure 的处理；
4. unknown version、损坏 plane、读失败和 CAS conflict；
5. Schema/runtime parity、raw/projected validation、跨进程 CAS 和 Slice 1 Hook 回归；
6. 本地完整门禁。

未安装、部署、发布或同步插件；未写稳定源、运行缓存、Marketplace、Hook trust 或 Registry；未创建真实测试任务；未修改或删除任何既有 smoke StateStore；未提交或推送；未启动 Slice 3。

## 2. 总结判断

现有测试证明了已覆盖路径内部自洽，但没有覆盖本轮反例。具体而言：

- Schema 对 34 个已知 retired execution 字段使用 boolean `false`；runtime 写前剥离集合只有 31 个。
- migration fixture 证明了旧 `running` 不升级为 active，但没有覆盖 observation target 错配、弱 result 字段或错绑 parent disposition。
- plane required/properties parity 通过，但没有验证 `exact_dispatch_target` 的 subject 必须等于同一 execution 的 `dispatch_record.dispatch_target`。
- raw canonical fixture 通过、projected reader view 被拒绝，但没有证明任意 Schema-invalid format-2 raw state都会被 runtime 拒绝，也没有证明全部 retired 字段不会写回。
- 四平面相同的两个 execution，仅改变平面外 `spawn_not_created` 就会改变 `allowed_actions`，说明四平面尚不是完整的 canonical authority。

因此本轮不能以 395/395、validator 或 CAS 绿灯覆盖 blocker，Slice 2 不满足退出条件。

## 3. Blockers

### B1. exact observation 可在 target 错配时被绑定并形成 terminal/confirmed 强事实

严重性：blocker。

冻结不变量要求只有对该 attempt 的 exact `dispatch_target` 的 target-scoped observation 才能绑定；错配、空、unknown 或 unbound 证据不得生成 identity、active 或 terminal。

实现存在三条相互叠加的缺口：

- `scripts/subagent_governance.py:678-723` 的 `_legacy_observation_record()` 只检查存在 `dispatch_target`、source 为 `list_agents` 且 summary 为 terminal；它完全不读取或核对旧 `platform_observation_target`。
- `scripts/subagent_governance.py:1302-1309` 的 `_set_execution_fact(..., "platform_observation_target", value)` 对任意非空 value 都写 `binding_basis=exact_dispatch_target`，不核对 value 是否等于 `dispatch_record.dispatch_target`。
- `scripts/subagent_governance.py:1019-1026` 的 format-2 runtime validation 只核对 bound task/attempt，不核对 observation subject 与 dispatch target。Schema 同样没有表达该跨 plane 等值约束。

最小复现 1，legacy 错目标被重绑：

```python
legacy = json.load(open("tests/fixtures/state-v1-four-plane-migration.json"))
execution = legacy["tasks"]["sg-slice-2-legacy"]["executions"]["1"]
execution.update(
    platform_observation="normal",
    platform_observation_source="list_agents",
    platform_observation_summary="completed",
    platform_observation_target="/root/different-target",
)
observation = governance._migrate_state_to_current(legacy)["tasks"][
    "sg-slice-2-legacy"
]["executions"]["1"]["observation_record"]
print(observation["subject"], observation["binding_basis"], observation["observed_state"])
```

实际结果：

```text
/root/sg_standard_slice_2_legacy_t_0123456789ab exact_dispatch_target terminal
```

旧 observation 明确指向 `/root/different-target`，migration 却把它重绑到当前 dispatch target 并生成 terminal。

最小复现 2，format-2 cross-plane 错配被接受：从一个 raw Schema-valid canonical state 出发，把 dispatch target 设为 A，把 observation subject 设为 B，同时设置 `binding_basis=exact_dispatch_target`、当前 task/attempt 和 terminal。结果是：

```text
base_schema_errors 0
mismatched_binding_schema_errors 0
identity_status confirmed
execution_status stopped
dispatch_target /root/sg_standard_slice_2_review_t_0123456789ab
observation_subject /root/different-target
```

StateStore `read()` 接受该状态，compatibility projection 产生 `confirmed + stopped`，随后 no-op `update()` 继续原样持久化错配 binding。该路径可以从非 exact 证据建立 managed terminal/identity authority。

### B2. legacy result 与 closure migration 从弱或错绑字段生成业务/处置强事实

严重性：blocker。

`scripts/subagent_governance.py:745-805` 先独立计算 `result_state`，随后无条件保留任何枚举合法的旧 `business_result`。因此旧 record 即使没有 valid protocol、available storage、result reference、digest 或 submitted time，也能把 `failed` 带入 format 2。

最小复现：

```python
execution["business_result"] = "failed"
execution["result_protocol_status"] = None
execution["result_storage_status"] = None
result = governance._migrate_state_to_current(legacy)["tasks"][task_id][
    "executions"
]["1"]["result_record"]
```

实际结果：

```text
result_state missing
payload_valid false
business_result failed
result_record Schema errors 1
```

compatibility projection 还会因 result state/business result 把该 execution 展示为 stopped/failed。该行为违反“业务结果只来自合法结构化结果”和“弱证据不能推导 failed”。

closure 也存在同类错绑：`scripts/subagent_governance.py:817-849` 从旧 `parent_disposition_record` 读取 action/reason/time，但不核对其中的 `task_id + attempt`。把 `task_id=other-task, attempt=99, action=accept_result` 放入 attempt 1 后，migration 产生当前 task attempt 1 的 `closure_record.parent_disposition=accept`。错 attempt 的处置由此被重新归属到当前 execution。

### B3. 三个 Schema-retired 字段不在写前剥离集合，可被 format-2 no-op CAS 写回

严重性：blocker。

机械集合对比结果：

```text
Schema boolean-false retired fields: 34
LEGACY_EXECUTION_PROJECTION_FIELDS: 31
missing from runtime strip set:
  parent_disposition
  parent_disposition_at
  parent_disposition_reason
```

证据：

- `schemas/governance-semantics.schema.json:582-629` 对上述字段和其他 retired 字段使用 boolean `false`。
- `scripts/subagent_governance.py:246-279` 的剥离集合缺少上述三个字段。
- `scripts/subagent_governance.py:1030-1061` 和 `1204-1217` 的 read/write 边界只按该不完整集合删除字段。
- `scripts/subagent_governance.py:3410-3438` 的旧名 canonicalizer 仍直接读写旧 execution disposition 语义，没有统一进入 `_set_execution_fact(..., "parent_disposition_record", ...)` 的 closure plane 路径。

隔离复现使用一个 `canonical_state` Schema errors 为 0 的新状态，注入这三个字段后 Schema errors 为 3；StateStore `read()` 接受，no-op `update()` 后原文件仍包含全部三个字段，输出 Schema errors 仍为 3：

```text
retired_after_noop_write {
  "parent_disposition": "reject_result",
  "parent_disposition_at": 120,
  "parent_disposition_reason": "legacy reason"
}
retired_output_schema_errors 3
```

这直接违反 compatibility 只存在于读取边界、format-2 retired 字段不写回，以及 Schema/runtime parity。

### B4. 平面外 `spawn_not_created` 仍能改变 canonical allowed action

严重性：blocker。

`spawn_not_created` 是 dispatch/not-created 语义事实，但不属于 `DispatchRecord`，不在 compatibility projection，也不是 execution Schema 的已声明 property。由于 `execution_record.additionalProperties=true`，它可以持久化；runtime 在以下路径把它当作权威：

- `scripts/subagent_governance.py:7620`：PostTool failed 直接写 `record["spawn_not_created"] = True`，绕过 `_set_execution_fact()`。
- `scripts/subagent_governance.py:5268`、`6846`：retry preparation/claim 以该字段作为 admission 前置条件。
- `scripts/subagent_governance.py:8864-8868`：decision snapshot 以该字段决定是否提供 `retry_spawn`。

最小复现构造两个四平面完全相同、均为 dispatch rejected 的 execution，只切换该扩展字段：

```text
spawn_not_created=false -> allowed_actions [reconcile]
spawn_not_created=true  -> allowed_actions [reconcile, retry_spawn]
```

这证明 canonical decision authority 仍可被四平面之外的 execution 字段改变，违反“语义写入进入 Dispatch/Observation/Result/Closure Record”和四平面单一权威要求。该问题属于 Slice 2 自身，不应推迟到 Slice 3 credential 实现。

## 4. 逐项验收证据

### 4.1 Raw Schema 与 compatibility projection

部分通过：

- raw canonical fixture 可通过 `canonical_state`。
- reader projection 因包含 `execution_status` 等 false property 而被 Schema 拒绝。
- 34 个已知 retired 字段在 Schema 中均为 boolean `false`。
- `_execution_compatibility_projection()` 是 canonical 到 reader 的深拷贝投影；31 个投影字段正常在写前剥离。

未通过：B3 证明三个 retired 字段不剥离并可写回；runtime 也没有在 format-2 read/write 边界执行等价于 `canonical_state` 的完整校验。

### 4.2 Managed execution writer inventory

静态搜索得到 168 个 `_set_execution_fact()`/`_pop_execution_fact()` 定义或调用出现点。主要 writer 分组如下：

| 平面 | 主要 writer |
| --- | --- |
| Dispatch | spawn claim、prepared reconcile、PostTool spawn observation、retry/replacement claim |
| Observation | exact absence、list_agents reconcile、interrupt/recovery observation、explicit reconciliation |
| Result | submit/reassociate、storage unavailable、conflict、acceptance |
| Closure | parent action、close attempt、parent disposition、duplicate resolution |

已确认绝大多数旧投影字段写入通过 `_set_execution_fact()` 同步到 plane；`_state_for_storage()` 再剥离投影。

未通过的旁路：

- B3 的旧 disposition canonicalizer 直接处理旧 execution 字段，且写前集合不完整。
- B4 的 `spawn_not_created` 直接写平面外字段并参与 admission/decision authority。
- `scripts/subagent_governance.py:7306` 直接写 `observation_record.observed_state=absent_at_check`，这是 plane 内写入，本身不构成旁路；其随后 target binding 仍受 B1 的 target 等值缺口影响。
- `_read_subagent_event_route()`、`_assign_starting_agent()` 和 `_record_managed_result_protocol_gap()` 仍保留定义，但静态回归证明 Hook 调用路径没有重新引用它们；这是已知退役 backlog，不是本轮新 blocker。

### 4.3 Legacy/无版本迁移

通过：

- format 1 和无版本使用同一内存迁移。
- 旧 `execution_status=running` 单独存在时迁移为 `not_observed`，不生成 active。
- 缺少 Start/Stop 不生成 running/failed。
- read-only migration 不回写；首次锁内 write 才保存 format 2。
- 明确 platform error 进入 observation error，不直接生成业务 failed。

未通过：B1 的 exact target 错绑、B2 的弱 result 与错绑 closure disposition。

### 4.4 Unknown version、损坏、读失败和 CAS

通过的边界：

- unknown `state_format_version` 抛出 `StateValidationError`，read/update 都不改原文件。
- plane 缺字段、额外内部字段、未知 enum、非法 timestamp 和已覆盖的 binding task/attempt 错配会失败且不回写。
- parent Stop 最多三次读取；持续失败后 `continue=true` 并明确告警，不持久化新事实。
- StateStore CAS predicate conflict 不调用 callback、不写文件。
- governed admission 的 CAS/owner conflict 按既有 Slice 1/F12 规则 deny 并保留 pending；normal/明确允许 fail-open 的 unavailable 路径告警后放行。这与“不可读不形成新 canonical 事实”一致。

未通过：B1 的 cross-plane subject/dispatch target 损坏未被识别；B3 的 Schema-invalid format-2 retired 字段可被重新写回。

### 4.5 Schema/runtime parity、raw/projected、CAS 与 Slice 1

通过：

- 四个 plane 的 runtime field set 与 Schema required/properties 双向一致。
- raw canonical state 通过、projected reader view 失败。
- 两个独立 Python 进程竞争同一 `dispatch_record.dispatch_state=claimed` predicate，结果固定为一个 `committed`、一个 `conflict`。
- Slice 1 official Hook key contract、extra/missing detector、parent session fixture、unbound Start/Stop、unknown Stop extension、transcript variation和 parent Stop fail-open 回归均通过。

不足：field-set parity 没有覆盖跨 plane 等值和 result/closure 组合；raw/projected test 只抽查了一个投影字段；CAS 正确性不能补偿错误 semantic predicate。

## 5. 分类

### Blocker

1. B1：exact observation target 绑定不完整，可生成错误 terminal/confirmed。
2. B2：legacy result/closure 从弱或错绑证据生成业务/处置强事实。
3. B3：三个 retired 字段可写回，Schema/runtime parity 失效。
4. B4：`spawn_not_created` 平面外字段仍改变 canonical admission/decision。

### 已知限制

- compatibility readers 尚未全部改为直接读取 plane；在输入严格由 canonical projection 生成的前提下，这本身不阻止 Slice 2，但 B3/B4 证明当前边界尚未封闭。
- 每个 execution 只有收敛后的 ObservationRecord，不是 observation event log。
- `fresh_until` 未驱动 hard gate，parent Stop 保持 advisory/fail-open。
- result credential、secret hash 和真实 child submit 尚未实现；这是明确的 Slice 3 边界，不用于本轮 blocker 判定。

### Backlog

- 物理删除已停用 transcript/Start identity/result-gap helper。
- 在不扩大到 Slice 3 的前提下，逐项退役 compatibility reader。
- 后续 observation event history、乱序审计和版本能力矩阵扩展。

### Not Checked

- 未捕获真实 raw Hook stdin；未验证真实 SubagentStop、SessionStart、SessionEnd、wait/mailbox wire shape。
- 未验证 child submit 可达性、credential 传递、provider restart、compact/resume、乱序或跨版本平台行为。
- 未安装或同步任何插件副本，未创建新 Codex 真实测试任务。
- 未检查稳定发布源、运行缓存、Marketplace、Hook trust、Registry 或历史 smoke StateStore 内容。

这些项目受本轮禁止范围约束，不由本地测试替代。

## 6. 门禁结果

| 门禁 | 结果 |
| --- | --- |
| Focused：four-plane、canonical Schema、StateStore、concurrency、Hook contract/fixtures | 71 tests，OK |
| `python3 -m unittest discover -s tests -v` | 395 tests，OK |
| Python compile：`scripts/*.py tests/*.py`，pycache 定向临时目录 | passed |
| Plugin validator | `Plugin validation passed` |
| Skill validator（共享工作树组合验证） | `Skill is valid!` |
| 仓库 JSON parse | 13 files，passed |
| 跨进程 CAS | one committed、one conflict，passed |
| `git diff --check` | passed |
| untracked 文件 whitespace scan | passed；覆盖报告在内的全部 untracked 文件 |

测试与 validator 全绿只说明已覆盖路径通过；B1-B4 是现有 suite 未覆盖的独立、可稳定复现反例。

## 7. GO/NO-GO

**NO-GO。** Slice 2 当前不能验收、不能部署为测试候选，也不能开始 Slice 3 来绕过本轮问题。

恢复 GO 评审前至少需要在同一 Slice 2 范围内满足：

1. exact observation 的 subject 必须机械等于同一 execution 的 dispatch target；legacy target 缺失或错配保持 unbound/not_observed/unknown，不得重绑。
2. legacy result 只有在完整、相互一致的 valid/available 证据下才能携带 business result；storage error/missing 不得携带业务失败。closure disposition 必须核对 task/attempt binding。
3. Schema false retired 集合与 runtime 剥离/拒绝集合双向一致，format-2 read/write 不得接受并回写已知 retired 语义字段。
4. `spawn_not_created` 等会改变 admission/decision 的 dispatch 事实进入 DispatchRecord，或从受校验的 DispatchRecord 唯一派生；平面外扩展不得成为 authority。
5. 为上述反例增加 focused regression，并重新通过本报告全部本地门禁与一次新的独立验收。

本报告只作验收裁决，不实施修复。等待用户决定是否开启新的 Slice 2 修复任务；不得自动进入 Slice 3。
