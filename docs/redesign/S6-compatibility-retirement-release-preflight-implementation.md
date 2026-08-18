# S6 兼容投影退役与发布前检查实施记录

## 范围与结论

本切片按 `docs/redesign/D6-migration-and-slices.md` 的 S6 和 `docs/refactor-plans/WP-08-legacy-retirement-release-readiness.md` 实施。唯一修改源是开发仓库 `$HOME/workspace/subagent-governance`。

结论：迁移期 root current/`prior_attempts` writer、reader 和 attempt-first 输出已退役；受治理 task 的唯一运行时形状为 `managed/task_id/work_item/executions`。历史 flat record 保留在磁盘时不迁移、不补写、不进入运行或决策视图，只由只读诊断报告结构问题。开发仓库已进入本地发布前检查阶段；稳定发布、安装和真实平台验收没有执行。

本轮没有修改稳定发布源、Marketplace、运行缓存、Hook trust、Registry 或全局规则，没有安装、发布、缓存同步、stage、commit、push 或 PR。

## 失败先行

修改运行时代码前新增 `tests/test_s6_compatibility_retirement.py`。修正测试自身的 canonical fixture 构造后，先运行：

```text
python3 -m unittest -v tests.test_s6_compatibility_retirement
Ran 5 tests
FAILED (failures=5)
```

五项稳定失败分别证明：

1. `_execution_projection`、`_sync_legacy_task_projection`、`_sync_execution_to_legacy_projection` 仍由运行时导出。
2. 新 task 仍把 current execution 字段和 `prior_attempts` 写到 root。
3. 历史 attempt-first managed record 仍会惰性迁移。
4. diagnose Session 仍输出顶层 attempt-first `action_required/recent_activity` 数组。
5. group member 仍输出 `individual_action_required/disposition_complete/summary_material_ready` 三个兼容别名。

实现后加入 canonical 映射损坏不能误标为历史记录的回归，同一套件为 `Ran 6 tests, OK`。该失败基线只证明 S6 缺口，未用测试构造错误冒充运行时失败。

## 实际退役

### canonical-only StateStore

- `_initial_task_record()` 的 task root 只写 `managed/task_id/work_item/executions`。
- `_task_record_for_attempt()`、`_iter_task_attempts()`、`_task_attempt_records()` 只读取 canonical `executions`。
- `_ensure_canonical_task_record()` 不再迁移 flat record；缺少 `work_item/executions` 时报告 `StateConflictError`。
- 删除三个 projection helper；canonical 写入只更新 execution 与 work-item 聚合。
- replacement、business resume、精确 identity、平台观察、结果关联、父处置、Session 与 Stop 均通过 `work_item.current_attempt` 和精确 execution 工作。
- stale root 字段即使仍存在也不会被读取或刷新；负向回归验证 canonical 更新与 stale root 保持互不影响。

task root 的 `managed` 和 `task_id` 是容器身份，不属于被退役的 execution 投影，继续保留。

### 历史数据边界

- 不做批量或惰性迁移，不按版本号拒绝整个 Session，也不静默补造 canonical 字段。
- 历史 flat task 不进入 Hook、CLI、Session、Stop、action-required/recent、diagnose work-items 或 group 决策。
- diagnose skipped-record issues 仍读取容器并报告缺失的 `managed/task_id/work_item/executions`，纯读取不创建 lock 或改写文件。
- 精确 Agent 映射指向历史/非 canonical task 时，Start/Stop 只给出有界告警并按 unmanaged 边界 fail-open；不执行旧生命周期、不从自由文本生成正式结果。
- 未知额外 root 字段仍可随 StateStore 普通读写保留，但没有运行时权威性。

### attempt-first 输出退役

- Session diagnose 保留 counts 与 `work_items[]`，删除顶层 attempt-first `action_required/recent_activity` 数组。
- work-item decision snapshot 只消费 canonical work item/executions，不生成兼容 attempt snapshots。
- group member 保留 `action_required/lifecycle/outcome_availability`，删除三个旧别名。
- `governance-semantics` 将派生视图改为 `includes_all_executions`，work-item snapshot 标记为 `canonical_executions_only`，canonical record 标记 `legacy_projection_retired=true`。

## 测试迁移

派发、通信、结果、等待、诊断和 Hook fixture 测试已从 task root 改为读取 `work_item.current_attempt` 指向的 execution。保留的 stale-root 用例只作为负向证据，验证运行时忽略且不刷新旧字段；它们不再声称 projection 是输出合同。

历史 flat fixture 单独用于诊断问题与 fail-open 边界，不进入 current managed helper。`tests/test_governance.py` 的初始状态断言改为检查 canonical execution 默认值和 root 无旧字段。

## 当前本地验证

已取得的实现期证据：

```text
python3 -m unittest -v tests.test_s6_compatibility_retirement
Ran 6 tests
OK

python3 -m unittest -q tests.test_minimal_diagnostics_lightweight_groups tests.test_semantic_baseline
Ran 40 tests
OK

python3 -m unittest -v tests.test_governance tests.test_wp08_legacy_retirement tests.test_hook_fixtures tests.test_s6_compatibility_retirement
Ran 28 tests
OK

python3 -m unittest discover -s tests -v
Ran 285 tests
FAILED (errors=2)
```

全量中的 283 项通过；仅保留两个用户明确要求如实记录的 D6 host-specific path errors：

- `test_release_preflight.ReleasePreflightTests.test_current_development_tree_passes_with_supported_ref`
- `test_release_preflight.ReleasePreflightTests.test_release_requires_manifest_tag_and_marketplace_ref_to_match`

两项均由 `release_preflight.PreflightFailure: host-specific path in docs/redesign/D6-migration-and-slices.md` 触发。S6 未修改该 D6 设计文档路径，也不把带这两个错误的全量结果写成全绿。

其余最终门禁：

```text
S1-S6 综合定向：234 tests OK
release tools：29 tests OK
五个 Python 脚本 py_compile：passed
Plugin validator：passed
Skill validator：passed
三个 Schema 与全部 JSON fixture：python3 -m json.tool passed
git diff --check：passed
```

旧 projection 符号/机器语义扫描只命中 S6 的否定断言，没有运行时 writer、reader 或现行 Schema 消费者。测试中的 stale-root 数据只验证旧字段不被读取或刷新。

只读审查并执行 `python3 scripts/check_installation.py`，exit 0：

- 开发仓库、稳定源和当前运行缓存三路径分离，均为普通目录且不是符号链接。
- 当前旧稳定版为 `0.4.0-rc.12+codex.20260813004209`；稳定源与当前缓存 hash 同为 `83e180a72d6243532666f1e346f4616ec390ea402a438915bfb2aec876c2df23`。
- `runtime_healthy=true`、`deployment_in_sync=true`，只表示当前旧稳定安装的文件系统/缓存/全局规则现状。
- 保留 4 份 compatibility cache，`retention_policy_satisfied=false`；本轮没有清理。
- `codex_registration_checked=false`、`hook_trust_checked=false`、`release_ready=null`、`release_readiness_status=not_evaluated`。

该脚本已确认只读：只读取路径、权限、Manifest、规则区间并计算 hash，不创建、替换、删除或改权。现有旧稳定版与缓存一致不能证明本开发工作树已经加载。

## 真实插件与平台

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 本开发工作树真实加载 | not_checked | 本轮禁止安装或缓存同步 |
| 七类 Hook enabled/trusted | not_checked | 旧稳定版状态不能替代目标工作树 |
| light/standard/strict/auto 派发 | not_checked | 未新建真实插件测试任务 |
| send/followup/list/interrupt | not_checked | 本地测试不替代平台投递与乱序 |
| SubagentStart/SubagentStop/TaskResult | not_checked | 未观察目标版本真实 payload |
| Stop、SessionStart/End、compact/resume | not_checked | 未执行真实 Hook 时序 |
| diagnose 与 group UI/父任务链 | not_checked | 仅有本地只读与派生测试 |
| N/N-1 整体安装与回滚 | not_checked | 只允许本地工具测试和外部只读检查 |

真实矩阵摘要为 `passed=0, failed=0, not_checked=8`。这表示授权范围内未执行真实插件/平台验收，不表示本地测试失败，也不允许推导“稳定版已发布或可无条件发布”。

## 发布判定

S6 只形成开发仓库发布前证据。两个已知 D6 host-specific path errors 仍存在，真实插件与平台均为 `not_checked`，因此最终表述必须是：兼容投影退役已在开发仓库实现并完成允许范围内的本地检查；稳定发布未执行、目标版本未验收。
