# P9 current-only 本地综合验收

日期：2026-08-24  
结论：`passed`（仅仓库内/精确 archive 验收；非 release-ready，真实平台仍为 `not_checked`）

## 对象、边界与开始状态

- 目标基线：`166fa492c5f6a053d25a791f9033f748ca84bded`，提交信息 `fix: align task name schema with runtime`，父提交 `e57994cfc596ba756077254673b868cb5f12b237`，目标 ref `codex/current-only-improvements`。
- 验收开始时 worktree 为 detached HEAD，`git status --short` 为空；基线完全一致。验收文档随后仅在独立分支 `codex/p9-current-only-acceptance` 更新，不把该文档改动混入基线的 archive 验收。
- `git diff --name-only aa408ed..166fa492…` 记录 164 条 P1–P8/current-only 相关路径变更（runtime、Schema、Skill、fixtures、tests、docs 和 release gates）；该命令的完整清单已在本次验收会话中核对。当前运行资产的 P1–P8 实现由 `b391322` 至 `8757287` 以及目标基线中的后续 P9 修复组成。
- Manifest 完整版本：`0.4.0-rc.13+codex.20260823131943`。`STATE_FORMAT_VERSION=6`，默认 data namespace 为 `state-v6`。
- 没有安装依赖、插件或 Skill；没有访问或改动稳定发布源、运行缓存、Hook trust、Marketplace 或 Registry；没有改版本、生成 cachebuster 或发布。

## 环境与命令

所有运行测试均在由精确目标提交导出的临时 archive `/tmp/p9-current-only.aL4zYX` 中执行，除非命令明确是工作树的 `git` 操作。

| 命令 | exit | 摘要 |
| --- | ---: | --- |
| `python3 --version` | 0 | Python 3.9.6 |
| `python3.11 --version` | 0 | Python 3.11.15 |
| `python3.12 --version` | 0 | Python 3.12.13 |
| `command -v ruff` | 1 | 不可用；未安装 |
| `command -v coverage` | 1 | 不可用；未安装 |
| `git archive --format=tar 166fa492… \| tar -xf - -C "$archive_root"` | 0 | 精确目标 archive 已提取 |
| `python3 "$archive_root/scripts/release_preflight.py" --root "$archive_root" --mode archive` | 0 | `status=passed`, `mode=archive` |
| `python3 -m unittest discover -s tests -v` | 0 | 271 tests |
| `python3.11 -m unittest discover -s tests -v` | 0 | 271 tests |
| `python3.12 -m unittest discover -s tests -v` | 0 | 271 tests |
| P9 A–F 17-module focused suite（Python 3.11） | 0 | 180 tests |
| `python3 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3.11 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3.12 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3 scripts/release_preflight.py --mode development` | 0 | `status=passed` |
| `python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .` | 0 | Plugin validation passed |
| `python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance` | 0 | Skill is valid |

`ruff check scripts tests`、`coverage run -m unittest discover -s tests -v` 与 `coverage report` 未运行，因为两个可执行文件都不可用。它们是 P9 的“可用时运行”项，未被记为通过，也不构成 `blocked_environment`。

## A–F 结果

| 层次 | 覆盖与独立证据 | 结果 |
| --- | --- | --- |
| A. current-only 状态契约 | `test_v6_strict_state_contract`、`test_canonical_record_schema`、producer corpus、必填字段/类型/unknown/dangling mutation、task-name 双向矩阵 | passed |
| B. UTF-8 与 Hook 边界 | `test_cli`、`test_hook_fixtures`、`test_hook_event_contract`、`test_p8_platform_hook_cli` | passed |
| C. storage 与事务 | `test_state_store`、`test_state_store_modules`、`test_concurrency`、`test_p5_dispatch_transactions`、`test_dispatch_identity` | passed |
| D. lifecycle 与 identity | `test_communication_lifecycle`、`test_terminal_notification_channel`、`test_wait_recovery_session_closure`、`test_dispatch_identity` | passed |
| E. views/group/session/diagnostics | `test_p7_views_groups_sessions_diagnostics`、`test_minimal_diagnostics_lightweight_groups`、`test_wait_recovery_session_closure` | passed |
| F. AST/import 与入口边界 | `test_current_only_repository`、`test_state_store_modules`、`test_p5_dispatch_transactions`、`test_p7_views_groups_sessions_diagnostics`、`test_p8_platform_hook_cli` | passed |

### A. state 契约与 task-name 矩阵

- `test_full_producer_corpus_is_accepted_by_runtime_and_schema` 覆盖 initial prepared/claimed/success/failed/unknown、retry 1/2、normal/recovery/interrupt pending、business-resume prepared/claimed/success/failed、terminal notification、parent close/tombstone、group 与 rollback/degraded health；runtime validator 与 JSON Schema 都接受。
- structural matrix 覆盖 33/33 定义必填字段删除、7/7 root/task/work-item/execution unknown-field 注入及非法 managed/enum/count/digest/ref/name；双方共同拒绝，允许的跨字段冲突由 diagnostics 报告而非规范化。
- `execution.task_name` 的合法 initial 字符串及 same-Agent resume 的 `null` 都被 runtime 和 Schema 接受。含空格、错误 mode、错误 semantic、错误 ref 长度、错误 ref 字符和超长值都被两者拒绝。
- `schemas/governance-semantics.schema.json` 将严格规则收敛为 `$defs.task_name`；`execution_record.task_name` 是其与 `null` 的 `anyOf`，`prepared_contract.task_name` 和 `prepared_native_parameters.task_name` 均只引用严格定义。因此 Prepared/native 同时拒绝全部非法值和 `null`。这是先前 runtime/Schema 漂移的独立复验结果。
- current-only 检查确认 runtime/Schema/fixtures/当前 Skill 没有 active 的 v5、`state-v1` fallback、旧 TaskContract/PreparedContract 或已删除 root projection；`state-v1` 仅保留在“不得迁移/不得接触”的负向测试与明确历史说明。

### B–E. 边界、事务与生命周期

- binary reader 覆盖 exact byte limit、limit+1、多字节 UTF-8、invalid UTF-8/JSON/root 及最多读取 limit+1；Hook 覆盖 parse-before-event fail-open、PreToolUse handler failure deny、Post/Stop/Session continue、unknown event/tool 零 store 构造、unmanaged spawn 零治理目录写入。
- StateStore/PreparedStore import 无副作用；owner/permissions/symlink/nonregular/size/UTF-8/JSON、atomic/fsync/replace/readback、CAS conflict callback、package/direct import 和 namespace resolver 均通过；没有旧 namespace fallback。
- dispatch fault/concurrency 覆盖 initial rollback/degraded health、retry exclusive credential、prepare/claim/Post/reconcile、落盘后抛错、exact compensation、orphan credential 收缩及 late failure 不覆盖 positive evidence。
- recovery claim budget、normal/interrupt fail-open 与 resume/recovery deny、business resume N+1 identity、terminal notification/list-agents、delivery-failed 后 resume/close、无关 session update 与 parent close agents mapping 均通过。
- Group/Session/Diagnostics 使用 canonical work-item view；`resume_delivery_failed` open 状态仍 action-required；SessionEnd 不删除 open/indeterminate、pending、tombstone 或 degraded health；diagnostic scan 前后 tree、mtime、lock/temp 不变，输出排序和 UTF-8 cap 确定。

### F. 架构与一致性

- AST/import assertions 确认领域模块不反向导入 `subagent_governance`；`governance_execution` 无 store/contract/context/dispatch/main-runtime 依赖；`governance_platform` 不管理 state/store；Hook router 无领域 mutation callback；CLI 无 `ModuleType` 或 `runtime.` 私有动态访问。
- 主入口仅保留 `handle`、`main`；迁移后的 lifecycle/view functions 没有重复定义；公开 facade、direct/package import 和 monkeypatch 符号所有者均由完整套件覆盖。
- docs/Schema/Skill/fixtures 对 state v6、state-v6 namespace、operation/native tool、retry/recovery、Session retention、terminal notification、business-resume identity、current-only/no migration 和 Hook fail-open/deny 一致；Plugin/Skill validators 均通过。

## 文档复跑与 archive 边界

本报告和 `docs/platform-validation.md` 更新后，重新运行受影响的 current-documents 门禁、完整 unittest、development preflight、Plugin validator、Skill validator 与 `git diff --check`：

| 文档变动后的命令 | exit | 结果 |
| --- | ---: | --- |
| `python3 -m unittest discover -s tests -v` | 0 | 271 tests |
| `python3.11 -m unittest discover -s tests -v` | 0 | 271 tests |
| `python3.12 -m unittest discover -s tests -v` | 0 | 271 tests |
| `python3 scripts/release_preflight.py --mode development` | 0 | `status=passed` |
| Plugin validator / Skill validator | 0 / 0 | passed / valid |
| `git diff --check` | 0 | 无空白错误 |

这三套完整测试包含 `test_only_current_documents_are_shipped` 与未知 validation 文档拒绝检查，证明本报告本身没有触发 current-only 文档门禁。

archive 验证严格针对 `166fa492c5f6a053d25a791f9033f748ca84bded`，不是工作树或后续文档提交：`git archive` 提取 exit 0，archive preflight exit 0。该事实证明目标提交的 archive gate，不表示已安装、已发布或 release-ready。

真实平台：`not_checked`。未安装插件、未创建真实验证 task，未验证 native spawn/wait/notification、Hook trust、事件顺序、桌面 UI、restart/compact 或真实 business resume；fixture、mock 和本地 Hook 结果没有被表述为真实平台证据。

## 结论

P9 仓库内 independent current-only acceptance 为 `passed`。所有必须运行且可用的 gate 通过；不可用的 `ruff`/`coverage` 如实保持未运行；真实平台保持 `not_checked`。
