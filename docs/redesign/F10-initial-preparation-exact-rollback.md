# F10 initial preparation exact rollback

## 1. 范围与结论

F10 只修复 initial `PreparedContract + canonical task` preparation 双写及 5 分钟未 claim initial reconcile。replacement reservation/claim、F9 retained-target lifecycle admission、F6 compatibility readers 均未改变。

本切片不引入 transaction log、scheduler、离线 migration、version gate、事件溯源或第二状态机。PreparedContract 仍是短期 spawn credential；canonical task 仍是业务与生命周期权威。

结论：initial task 的唯一删除条件是当前完整 task 逐字段精确等于本次 initial post-state。StateStore task 未确认安全删除前，唯一 PreparedContract 不删除。任何额外事实均保留，并尽可能进入 `parent_action=reconcile` 与单调 health merge；无法持久化时错误明确报告 `PreparedContract retained`。

## 2. Failure-first

F8 临时反例先转为稳定测试。修复前 9 个 F10 定向用例中 8 个失败，task-absent orphan 的既有删除路径单独通过：

| 反例 | 修复前结果 |
| --- | --- |
| StateStore persist-then-error，task 未变化 | PreparedContract 在 task cleanup 前被删除；删除顺序断言失败 |
| persist-then-error 后并发 extension | task 与并发事实被整体删除，PreparedContract 也删除 |
| task cleanup 写失败 | cleanup error 被吞；task 保留但 PreparedContract 已删除 |
| PreparedContract cleanup 失败 | 原始 StateStore error 被遮蔽，orphan 上下文不可见 |
| PreparedContract readback failure | 只暴露外层错误，未验证完整回滚证据 |
| StateStore readback failure | task/credential 状态无法确认，但凭证仍被删除 |
| 5 分钟 exact initial | 既有路径可删除，但只使用局部 attempt 谓词 |
| 5 分钟 concurrent change | 局部谓词仍成立时误删 task 与并发事实 |
| 5 分钟两类 cleanup failure | 底层异常泄漏或 orphan 不可定位 |

修复后又增加逐字段反例，分别改变 extension、execution timestamp、identity、claim 和 `parent_action`；五类变化均阻止 task 与 PreparedContract 删除。

## 3. 单一 snapshot binding

没有给 PreparedContract 增加 `initial_task_snapshot` 或 digest 字段。现有 validated PreparedContract 已保存：

- 完整 TaskContract 与机械校验后的 `contract_digest`、deliverable contract；
- `task_id`、`attempt=1`、`task_ref`、`task_name`、`resolved_mode`；
- `created_at`。

`_initial_task_post_state()` 使用这些唯一事实调用 canonical `_initial_task_record()`，确定性重建完整 post-state，并交叉校验 attempt、mode、contract digest 和 deliverable。这样 snapshot binding 只有一个来源，可机械验证，也不复制第二份业务权威。

## 4. 阶段与决策表

### 4.1 双写阶段

| 阶段 | StateStore pre/current state | PreparedContract | 允许动作 | 最终保留物 |
| --- | --- | --- | --- | --- |
| pre-state | task absent | absent | 创建 PreparedContract | 成功则 prepared-only |
| prepared-only | task absent | present/unclaimed | StateStore CAS 创建 exact task；失败回滚可删凭证 | 成功进入 prepared+exact-task；失败后两者均 absent |
| prepared+exact-task | 完整 task 等于确定性 post-state | present/unclaimed | 回读成功则返回；异常时 CAS 锁内先删 task，确认 absent 后删凭证 | 正常为 task+credential；失败回滚为两者 absent |
| prepared+diverged-task | task 任一字段不同 | present/unclaimed | 禁止删 task，禁止删凭证；按 observed full task 做 CAS marker | diverged task + retained PreparedContract + 可持久化的 reconcile/degraded |
| task-absent/prepared-orphan | task absent | present | 可安全删除 orphan credential | 两者 absent；删除失败则保留 orphan 并报错 |
| task present/credential uncertain | task exact 或 diverged | create/readback/delete 状态不可确认 | 不以不确定凭证状态授权 spawn；先按 task exact 语义处理，所有凭证 cleanup error 可见 | exact task 可安全回滚；否则保留 task，错误说明凭证可能 retained |

### 4.2 即时 rollback 与过期 reconcile 统一决策

| 当前 task | 完整 equality | StateStore 动作 | PreparedContract 动作 | 结果 |
| --- | --- | --- | --- | --- |
| absent | 不适用 | 不写 task | 删除 | 安全清理 orphan |
| exact post-state | `true` | CAS 锁内删除整 task | 仅在确认 absent 后删除 | exact rollback complete |
| exact delete 写后报错，readback absent | 已由 readback 确认 | 不再写 | 删除；同时报告 cleanup error | rollback complete with visible error |
| exact delete 失败且 task retained | `true` | 尝试基于 observed full task 写 reconcile/degraded | 保留 | rollback-incomplete/action-required |
| diverged task | `false` | 不删除；仅以 observed full task CAS 写 marker | 保留 | 并发事实保留，action-required |
| StateStore readback unknown | 无法判断 | 不猜、不删 | 保留 | rollback-incomplete；错误说明 credential retained |

## 5. 锁与删除顺序

1. 从 PreparedContract 确定性重建 expected initial task。
2. 读取当前 task；absent 可直接进入 credential cleanup。
3. 仅当 `current_task == expected_task` 时，调用 StateStore `compare_and_set()`；predicate 在同一文件锁内再次比较整 task，callback 删除整 task。
4. CAS 失败或写后报错时回读：只有 readback absent 才视为 task 已安全删除；否则保留 PreparedContract。
5. diverged/retained task 只使用 observed full task 作为 marker CAS predicate，避免 marker 覆盖 marker 前的新 task 事实；无关 health 更新不加入 predicate，因此不会阻止 execution rollback marker 落盘。
6. 只有 task 已确认 absent 后才调用 PreparedContract full-record predicate delete；扫描后发生的 claim、替换或任意凭证变化都会导致 exact delete 冲突并保留新事实。

PreparedContract 与 StateStore 使用不同锁，本切片不伪装跨文件事务；安全性来自严格删除顺序、完整 equality、保留 credential 和可重试 reconcile。

### 5.1 marker health merge

execution 上的 `parent_action=reconcile` 与 `initial_preparation_rollback` 由 observed-task CAS 保护。health 在同一 callback 中独立做最小单调合并：

| 当前 health 事实 | F10 merge |
| --- | --- |
| `status=ok` | 提升为 `degraded` |
| `status=degraded` | 保持 `degraded` |
| `status=unavailable` | 保持 `unavailable`，不得降级 |
| status 缺失或非法 | 保留原值，交给现有 diagnose 边界暴露 |
| rollback marker 不存在 | 写入本次 marker |
| rollback marker 的合法 `observed_at <= now` | 用本次较新或同时间 marker 替换 |
| rollback marker 更新，或现有形状非法且无法比较 | 保留现有 marker |
| 其他 health 字段 | 原样保留 |

该合并不建立通用 health 状态机，也不把整 state equality 作为 task marker 的 CAS 条件。

## 6. 异常矩阵

| 异常 | task | PreparedContract | 可诊断终态 |
| --- | --- | --- | --- |
| PreparedContract persist/readback error，task absent | absent | 删除或 uncertain orphan | 原始 cause chain 可见；cleanup failure 明确报告 |
| StateStore persist-then-error，exact task | CAS 精确删除 | task absent 后删除 | exact rollback complete；cleanup error 不隐藏 |
| StateStore persist-then-error，diverged task | 保留全部并发事实 | 保留 | `parent_action=reconcile`、rollback marker、health 单调合并 |
| marker 前发生 health-only 并发更新 | task marker 正常落盘 | 保留 | `unavailable` 不降级；较新 health marker 与其他字段不覆盖 |
| StateStore task cleanup failure | 保留；不伪造 spawn observation | 保留 | 汇总原始 error、task cleanup error、marker error（如有） |
| StateStore readback/marker failure | 状态不猜测 | 保留 | 明确 marker 无法持久化、credential retained、显式 reconcile/expiry 可重试 |
| PreparedContract delete failure after safe task delete | absent | orphan retained/uncertain | 明确 orphan 与 task identity；后续 expiry 识别 task absent 后重试 |
| 5 分钟 exact unclaimed | 删除 | 随后删除 | `expired += 1` |
| 5 分钟 diverged/unreadable | 保留 | 保留 | 抛出 degraded/rollback-incomplete，不静默 continue |

所有 rollback-incomplete marker 只记录 cleanup 事实并设置 `parent_action=reconcile` / health degraded；不写 `spawn_observation=unknown|failed`，因为没有发生 native spawn observation。

## 7. 验证

已通过：

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.test_dispatch_identity tests.test_state_store \
  tests.test_semantic_baseline tests.test_canonical_record_schema
Ran 144 tests
OK
```

该切片包含 failure-first 反例、完整 snapshot reconstruction/validation、即时 exact rollback、diverged retain、task cleanup failure、PreparedContract cleanup/readback failure、StateStore readback failure、task-absent orphan、5 分钟 exact/concurrent/cleanup failure，以及 action-required/diagnose/SessionStart 可见性。

跨切片与全量：

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.test_dispatch_identity tests.test_state_store \
  tests.test_communication_lifecycle tests.test_wait_recovery_session_closure \
  tests.test_formal_result_parent_closure \
  tests.test_minimal_diagnostics_lightweight_groups \
  tests.test_semantic_baseline tests.test_canonical_record_schema \
  tests.test_s6_compatibility_retirement
Ran 302 tests
OK

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
Ran 378 tests
FAILED (errors=2)
```

全量 376 项通过，仅以下两项既有 release-preflight error：

- `test_current_development_tree_passes_with_supported_ref`；
- `test_release_requires_manifest_tag_and_marketplace_ref_to_match`。

两项均只报告 `host-specific path in docs/redesign/D6-migration-and-slices.md`。本切片按禁止范围未修 D6，未出现其他失败。

静态门禁全部通过：

```text
PYTHONPYCACHEPREFIX="<temporary-directory>" python3 -m py_compile scripts/*.py
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
rg --files -g '*.json' -0 | xargs -0 -n1 jq empty
git diff --check
```

## 8. not_checked

- 未安装、发布或同步测试插件；未写稳定源、运行缓存、Hook trust、Marketplace 或 Registry。
- 未 stage、commit、push 或创建 PR。
- 未新建真实插件测试对话；真实 Hook/provider/mailbox/UI 仍为 `not_checked`。
- 未检查稳定发布源与运行缓存哈希，因为本阶段禁止发布和同步。

## 9. remaining

F10 范围内当前没有已知本地架构阻塞项。真实插件测试仍是独立 `not_checked`，不能由本地测试替代；D6 两项既有 host-specific path release-preflight errors 未处理，也不属于 F10。
