# P9 current-only 本地综合验收

日期：2026-08-24  
结论：`failed`（仅仓库内验收；未安装、未发布、非 release-ready，也不是真实平台验收）

## 验收对象与边界

- 目标实现为分支 `codex/current-only-improvements` 的 `57f270e489f16158efd0e8f94479509465ec9030`（`test: allow current P9 validation report`）。该分支 ref 精确指向此提交；开始时工作树无未提交改动。
- 相对根提交 `d23493ecf4e46327d04f7dee7074a3a619cbd142`，目标有 113 条路径变更；P1–P8 实现提交仍可由历史追溯。计划文档的“待独立对话实施”是计划状态，不被误记为 runtime 状态。
- Manifest 版本：`0.4.0-rc.13+codex.20260823131943`。`STATE_FORMAT_VERSION=6`，默认 namespace 为 `state-v6`。
- 本次只更新本报告和 `docs/platform-validation.md`；未修改实现、测试、Schema、Skill 或 fixtures，亦未安装依赖/插件/Skill、访问稳定源或运行缓存、改 Hook trust/Marketplace/Registry，且未启动 P10。

## 环境与命令

| 命令 / 探测 | exit | 结果 |
| --- | ---: | --- |
| `python3 --version` | 0 | Python 3.9.6 |
| `python3.11 --version` | 0 | Python 3.11.15 |
| `python3.12 --version` | 0 | Python 3.12.13 |
| `ruff --version` | 127 | 未安装；未安装它 |
| `coverage --version` | 127 | 未安装；未安装它 |
| `python3 -m unittest discover -s tests -v` | 0 | 267 tests |
| `python3.11 -m unittest discover -s tests -v` | 0 | 267 tests |
| `python3.12 -m unittest discover -s tests -v` | 0 | 267 tests |
| `python3 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3.11 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3.12 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3 scripts/release_preflight.py --mode development` | 0 | `status=passed` |
| Plugin validator | 0 | passed |
| Skill validator | 0 | passed |
| `git diff --check`（报告改动前） | 0 | 无空白错误 |
| P9 专项 A–F suite（134 tests） | 0 | passed |

`ruff check scripts tests`、`coverage run -m unittest discover -s tests -v` 和 `coverage report` 未运行；唯一原因是相应命令不存在。它们没有被记为通过。

## A–F 结果

| 层次 | 独立证据 | 结果 |
| --- | --- | --- |
| A. current-only 状态契约 | `test_v6_strict_state_contract`、`test_canonical_record_schema`、独立 corpus/mutation matrix | **failed** |
| B. UTF-8 与 Hook 边界 | `test_cli`、`test_hook_fixtures`、`test_hook_event_contract`、`test_p8_platform_hook_cli` | passed |
| C. storage 与事务 | `test_state_store`、`test_state_store_modules`、`test_concurrency`、`test_p5_dispatch_transactions`、`test_dispatch_identity` | passed |
| D. lifecycle 与 identity | `test_communication_lifecycle`、`test_terminal_notification_channel`、`test_wait_recovery_session_closure`、`test_dispatch_identity` | passed |
| E. views/group/session/diagnostics | `test_p7_views_groups_sessions_diagnostics`、`test_minimal_diagnostics_lightweight_groups`、`test_wait_recovery_session_closure` | passed |
| F. AST/import 架构边界 | `test_current_only_repository`、`test_p5_dispatch_transactions`、`test_p7_views_groups_sessions_diagnostics`、`test_p8_platform_hook_cli` 与独立 AST 审计 | passed |

专项 suite 运行了 134 项；三套 267 项完整 suite 都在本报告已存在的最终工作树上通过。`test_only_current_documents_are_shipped` 现已精确允许本 P9 报告，`test_unknown_validation_document_is_not_shipped` 仍确认未知额外 validation 文档会被拒绝。

producer corpus 覆盖 initial prepared/claimed/success/failed/unknown、retry 1/2、normal/recovery/interrupt pending、business-resume prepared/claimed/success/failed、terminal notification、parent close/tombstone、group 和 rollback/degraded health；`test_full_producer_corpus_is_accepted_by_runtime_and_schema` 验证其 canonical producer state 同时被 runtime 和 JSON Schema 接受。

独立 structural matrix 对 canonical v6 record 的 33/33 个定义必填字段删除及 root/task/work-item/execution/三 records 的 7/7 个未知字段注入，均得到 runtime 与 Schema 的共同拒绝。非法 managed/enum/count/digest/ref/name 的六项变异中，5/6 共同拒绝；唯一失败如下。

```text
canonical execution.task_name = "bad name"
runtime: rejected（不符合 task name 格式）
JSON Schema: accepted
```

runtime 使用 `machine_semantics.task_name.pattern` 的严格 `sg_<mode>_..._t_<ref>` 格式；`schemas/governance-semantics.schema.json` 的 `execution_record.task_name` 仅要求长度 1–64 且匹配 `\\S`，因此接受含空格的非 canonical 值。该 runtime/Schema 结论不一致违反 P9 A 的 mutation 标准，故即使完整测试均通过，P9 仍为 `failed`。这是本次验收的停止条件；修复需修改 Schema 或实现/测试，超出纯验收边界。

事务与 identity tests 覆盖 CAS conflict 不调用 callback、atomic/fsync/replace/readback、prepare/claim/Post/reconcile 并发、exact compensation 不覆盖较新状态、orphan credential 幂等收缩、late failure 不覆盖 positive evidence、recovery budget 在 claim 时消耗、business-resume N+1 identity、delivery failed 后 resume/close 及 parent close 精确清理 agents mapping。

诊断测试确认 unsupported v5/invalid 输入仅报告而不修补；scan 前后 state/lock 的 SHA-256 与 mtime 不变，且不生成 lock/temp。`resume_delivery_failed` 的 open work item 仍 action-required；SessionEnd 保留 open/indeterminate、pending、tombstone 和 degraded health；Stop 为 advisory-only，输出排序与 UTF-8 byte cap 已覆盖。

## 架构与一致性审计

- 独立 AST 审计：25 个 `governance_*` 模块；领域模块反向导入 `subagent_governance` 为 0；`governance_execution` 的 store/storage/dispatch 依赖为 0；`governance_platform` 的 state/store 依赖为 0；CLI 的 `ModuleType`/`runtime.` 动态私有访问为 0；主入口定义仅为 `handle`、`main`。
- current-only lexical audit 未发现 active `state_format_version=5`、`STATE_FORMAT_VERSION=5`、旧 `TaskContractV*`、旧 `PreparedContractV*` 或 deleted root projection。`state-v1` 仅出现在 current-only 拒绝/不迁移测试和明确历史说明，不是 runtime/Schema/fixture fallback。
- 除上述 `execution_record.task_name` mismatch 外，semantics、runtime、fixtures、docs/Skill 中 v6、`state-v6`、operation/native-tool、retry/recovery、retention/SessionEnd、terminal notification、business resume N+1 与 Hook fail-open/deny 的现有一致性测试通过。

## Archive 与平台边界

严格使用目标提交，而非 HEAD 或工作树：

```bash
archive_root="$(mktemp -d)"
git archive --format=tar 57f270e489f16158efd0e8f94479509465ec9030 | tar -xf - -C "$archive_root"
python3 "$archive_root/scripts/release_preflight.py" --root "$archive_root" --mode archive
```

archive extract exit `0`；archive preflight exit `0`，输出 `status=passed`、`mode=archive`、manifest `0.4.0-rc.13+codex.20260823131943`。这只验证目标提交的 archive gate，不表示安装、发布或 release-ready。

真实平台状态：`not_checked`。未安装插件、未创建新的真实验证 task，也没有把 mock、fixture 或本地 Hook router 的结果描述为真实 native spawn/wait/notification、Hook trust、事件顺序、桌面 UI、restart/compact 或 business-resume 验证。P10 未启动。

## 停止条件

已触发：同一非法 canonical execution `task_name` 样本被 runtime 拒绝而被 JSON Schema 接受。P9 仅记录失败，不做跨层修复。
