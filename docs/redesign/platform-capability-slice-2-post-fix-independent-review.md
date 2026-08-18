# 平台能力契约重设计：Slice 2 blocker 修复后独立复验

日期：2026-08-14

结论：**NO-GO**。原独立验收 B2-B4 已关闭，B1 报告中的 legacy target、cross-plane subject 和 alias 反例也已关闭；但新的独立复现仍发现 2 个 Slice 2 blocker：非 exact/broad `list_agents.path_prefix` 可以把返回项升级为 managed terminal/confirmed，以及 legacy 首次锁内写入会持久化 Schema-invalid 的 format-2 canonical state。不得进入 Slice 3。

## 1. 审查范围与边界

本轮完整阅读：

- `AGENTS.md`
- `docs/redesign/platform-capability-contract-and-minimal-state-machine.md`
- `docs/redesign/platform-capability-slice-2-implementation.md`
- `docs/redesign/platform-capability-slice-2-independent-review.md`
- `docs/redesign/platform-capability-slice-2-blocker-fixes.md`

并独立检查当前共享工作树中的 runtime、Schema、migration fixture、Hook fixture 和 tests。没有把修复报告或现有 focused tests 当作充分证据；原 B1-B4 反例另用临时目录中的独立断言脚本复跑。

除本文件外未修改实现、Schema、fixture、测试或既有文档。未安装、部署、发布、提交或推送；未写稳定发布源、Marketplace、运行缓存、Hook trust 或 Registry；未创建真实测试任务；未读取、修改或删除既有 smoke StateStore；未启动 Slice 3。

## 2. 四组原 blocker 逐项结论

| 原 blocker | 结论 | 独立证据 |
| --- | --- | --- |
| 1. exact observation binding | **部分关闭，整组仍 FAIL** | legacy missing 为 `not_observed`、mismatch 为 unbound `unknown`、exact 为 terminal；format-2 cross-plane subject mismatch 被 runtime 拒绝；错 alias 不生成 terminal；无 Start 的 exact target terminal 可收敛。但非空 `list_agents` 路径没有核对调用输入的 exact `path_prefix`，见 NB1。 |
| 2. conservative result/closure migration | **PASS** | 6 组弱、矛盾、missing/storage-error 证据均不携带 `business_result` 或 payload-valid；完整 valid/available/reference/SHA/timestamp 证据保留业务结果；wrong task 与 wrong attempt disposition 均不迁移。 |
| 3. retired field parity/strip | **PASS** | Schema boolean-false execution 字段与 `LEGACY_EXECUTION_PROJECTION_FIELDS` 双向相等，共 35 个；逐字段注入 format-2 raw state 后 no-op CAS 全部剥离。 |
| 4. single canonical not-created authority | **PASS** | `spawn_not_created=false|true` 不改变 `allowed_actions`；not-created 只由 `dispatch_record.dispatch_state=rejected` 派生；`acknowledged + spawn_not_created=true` 仍不满足 not-created；实际 retry admission 回归通过。 |

## 3. Blockers

### NB1. 非 exact/broad list 查询仍可生成 exact terminal/confirmed

严重性：blocker。

冻结不变量要求查询输入必须是该 attempt 的 exact `dispatch_target`，返回的明确单目标 terminal 才能绑定。当前非空响应路径在 `scripts/subagent_governance.py:7481-7617` 只遍历返回项，并由 `scripts/subagent_governance.py:7441-7451` 按返回项 `agent_name == dispatch_target` 路由；`tool_input.path_prefix` 只在空响应路径 `scripts/subagent_governance.py:7485-7494` 使用。

因此 broad query 或错 query 的返回项可以被重新解释为 exact target observation。最小复现使用现有 legacy fixture 迁移后的临时 StateStore，无 Start、无 `agents` mapping：

```python
handle({
    "session_id": "slice-2-legacy",
    "hook_event_name": "PostToolUse",
    "tool_name": "list_agents",
    "tool_input": {"path_prefix": "/root"},
    "tool_response": {"agents": [{
        "agent_name": dispatch_target,
        "agent_status": "completed",
    }]},
    "now": 200,
}, store)
```

实际结果：

```text
query=/root
observed_state=terminal
binding_basis=exact_dispatch_target
identity_status=confirmed
execution_status=stopped
```

`/root` 不是该 execution 的 exact `dispatch_target`。同样，把 `path_prefix` 设为另一个 target、响应仍含当前 dispatch target，也得到相同强事实。该问题不是 Schema cross-plane 等值缺口：写入后的 subject 确实等于 dispatch target；缺失的是 observation 来源调用本身的 exact-scope 证明。

精确修复范围应限于非空 `list_agents` observation 路由：机械要求 `tool_input.path_prefix == returned agent_name == unique dispatch_record.dispatch_target`，并拒绝 broad、缺失、错 scope、多目标或无法建立唯一 exact subject 的响应。不得借此引入 alias、Start、active index、同名或全局扫描 authority。

### NB2. legacy 首次写入会持久化 Schema-invalid format 2

严重性：blocker。

`scripts/subagent_governance.py:887-945` 在迁移时深拷贝 legacy execution，仅替换四个 plane；它没有把 legacy core fields 迁移成 `execution_record` 的 canonical shape。`StateStore._write_path()` 随后把版本写成 2，但没有对完整 `canonical_state` 执行 Schema 等价校验。

使用仓库当前 `tests/fixtures/state-v1-four-plane-migration.json`：

```python
store.update("slice-2-legacy", lambda _state: None)
raw = json.loads(state_path.read_text())
errors = validate_instance(
    raw,
    governance.SEMANTIC_DEFINITIONS["canonical_state"],
    root_schema=governance.MACHINE_SEMANTICS,
)
```

实际结果：

```text
PERSISTED_VERSION 2
PERSISTED_CANONICAL_STATE_ERRORS 20
contract_summary missing required properties: 13
deliverable_contract missing required properties: 6
dispatch_kind value not in enum: 1
DISPATCH_KIND initial
```

现有 `test_legacy_state_is_migrated_only_during_a_locked_write` 只断言版本、四个 plane 和 retired 字段；`test_migrated_execution_records_validate_against_schema` 只逐个验证四个 plane；raw-vs-projected 测试则使用全新 `_initial_task_record()`，没有验证 legacy 首次写入后的完整 raw state。因此 404/404 不覆盖该反例。

该问题违反 migration 后 format 2 是 canonical record、raw state 可通过 `canonical_state`、以及 Schema/runtime parity 的 Slice 2 退出条件。精确修复范围是 legacy execution core-field migration 与完整 raw canonical validation；不得通过放宽 Schema、把 invalid core fields 当作 forward extension或跳过 legacy fixture 来消除错误。

## 4. 回归复验

### Observation 与 fail-open

- 无 Start、无 active index 的 exact `dispatch_target` terminal：通过，收敛为 terminal；但仅在调用 scope 本身 exact 时才应视为正确，NB1 当前未执行该门禁。
- legacy target missing/mismatch：通过，分别保持 `not_observed` 与 unbound `unknown`。
- format-2 exact subject/dispatch target mismatch：runtime 拒绝且不回写。
- 错 alias/错返回 target：不生成 terminal/confirmed。
- empty、`pending_init`、unknown 和 error：均不生成 terminal、业务 failed 或 business result。独立矩阵结果分别为 `not_observed/unknown/unknown/error`，result 均为 `missing + business_result=null`。
- exact empty 且没有既有 `agents` mapping 时仍保持 `not_observed`，没有写成 `absent_at_check`。这是保守行为，不违反本轮“不得推导 terminal/failed”的负向要求，但与 Slice 2 实施文档“exact empty 写 absent_at_check”的宽泛陈述不完全一致，列为已知限制。

### Result、closure 与四平面 authority

- 完整一致 legacy result 才迁移 business result；弱 conflict 不提升 conflict。
- storage unavailable 不携带 business result、acceptance 或 payload-valid。
- closure disposition 严格绑定当前 `task_id + attempt`。
- 35 个 retired execution 字段与 runtime strip set 完全一致；全部 no-op write 后不持久化。
- `spawn_not_created` 没有 runtime 生产读者；retry preparation、claim 和 allowed actions 都使用 dispatch-derived predicate。
- 未知非语义 execution extension 可跨 storage 保留，且不改变 not-created/allowed-actions 结论。

### Schema、CAS 与 Slice 1

- 新建 `_initial_task_record()` 的 raw canonical state 通过 Schema；compatibility-projected view 被 Schema 拒绝。
- legacy migration 的完整 raw canonical state不通过，见 NB2。
- 四个 plane required/properties 与 runtime field set 双向一致。
- 跨进程四平面 CAS one-commit/one-conflict 通过；完整 concurrency suite 通过。
- unknown version、损坏 plane 和 CAS conflict 保留原文件。
- Slice 1 official Hook key contract、额外字段 detector、unbound Start/Stop、unknown Stop extension、transcript variation、StateStore unreadable 与 parent Stop fail-open 回归通过。

## 5. 分类

### Blocker

1. NB1：非 exact/broad `list_agents.path_prefix` 可以建立 managed terminal/confirmed。
2. NB2：legacy 首次写入持久化 Schema-invalid 的 `state_format_version=2`。

### 已知限制

- exact empty 在没有 active `agents` mapping 时保持 `not_observed`，没有形成 `absent_at_check`；结果保守且不产生 terminal/failed。
- compatibility readers 尚未全部改为直接消费 plane record。
- 每个 execution 只保存收敛后的 ObservationRecord，不是 observation event log。
- `fresh_until` 尚未驱动 hard gate；parent Stop 继续 advisory/fail-open。
- result credential、secret hash、签发/消费/撤销和真实 child submit 尚未实现，仍属于 Slice 3。

### Backlog

- 物理删除已退役 transcript/Start identity/result-gap helper。
- 在不扩大 Slice 2 blocker 修复的前提下逐项退役 compatibility reader。
- observation event history、乱序审计与版本能力矩阵扩展。

### Not Checked

- 未捕获真实 raw Hook stdin；未验证真实 SubagentStop、SessionStart、SessionEnd、wait/mailbox 或 `list_agents` wire shape。
- 未验证 child submit、credential 暴露面、provider restart、compact/resume、乱序、重复事件或跨版本行为。
- 未安装或同步插件，未创建新的真实 Codex 测试任务。
- 未检查稳定发布源、运行缓存、Marketplace、Hook trust、Registry 或历史 smoke StateStore 内容。

这些项目受本轮禁止范围约束，不能由本地测试替代。

## 6. 门禁结果

| 门禁 | 结果 |
| --- | --- |
| 独立原 B1-B4 断言 | 原 B1 已知反例通过；B2 6 组弱证据、完整证据和错绑 closure 通过；B3 35 字段 parity/no-op strip 通过；B4 decision/not-created parity 通过 |
| Focused：four-plane、canonical Schema、StateStore、concurrency、Hook、dispatch、formal closure、session/Stop、semantic baseline | 229 tests，OK |
| `python3 -m unittest discover -s tests -v` | 404 tests，OK |
| Python compile | `scripts/` 与 `tests/` 共 24 个 Python 文件，passed；pycache 定向到临时目录 |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| 仓库 JSON parse | 13 files，passed |
| Schema retired/runtime strip parity | 35/35，passed |
| 跨进程 CAS | one committed、one conflict，passed |
| `git diff --check` | passed |
| untracked whitespace | passed；45 files，包含本报告 |

现有门禁全绿不能覆盖 NB1/NB2；两者都由临时目录中的独立最小复现稳定触发。

## 7. GO/NO-GO

**NO-GO。** Slice 2 blocker 修复当前不能验收，不能部署为测试候选，不能进入 Slice 3。

恢复 GO 至少需要在同一 Slice 2 修复范围内：

1. 非空 `list_agents` observation 同时机械核对 exact query scope、返回 subject 与唯一 execution dispatch target，broad/错 scope 不生成 managed terminal/confirmed。
2. format 1/无版本 legacy 首次写入产生完整 Schema-valid format 2，且 migration fixture 的完整 `canonical_state` 而非仅四个 plane 通过验证。
3. 为以上两个最小反例补 focused regression，重新通过本报告全部门禁，并再次进行新的独立验收。

本报告不实施修复。主任务应据此继续同一 Slice 2 blocker 修复，不得启动 Slice 3。
