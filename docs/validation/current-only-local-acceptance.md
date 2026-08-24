# P9 current-only 本地综合验收

日期：2026-08-24  
结论：`passed`（精确提交的独立仓库内验收；未安装、未发布、非 release-ready，真实平台仍为 `not_checked`）

## 对象、边界与开始状态

- 目标基线：分支 `codex/current-only-improvements` 的 `937edbd75404dacca4439e03012245acc7bc8193`，提交信息 `fix: verify installer target tree digest`，父提交 `424a2ff042df177b6c4119ff9228673d1dc6e53e`。开始时 HEAD 精确等于目标，`git status --short` 为空。
- `git diff --name-only aa408ed..937edbd75404dacca4439e03012245acc7bc8193` 为 168 条 P1–P8/current-only/P10 相关路径变更。Manifest 完整版本为 `0.4.0-rc.13+codex.20260823131943`；`STATE_FORMAT_VERSION=6`，默认 data namespace 为 `state-v6`。
- 此次只修改本报告与 `docs/platform-validation.md`。未安装依赖、插件或 Skill；未读取或写入稳定源、运行 cache、Hook trust、Marketplace、Registry 或 AGENTS；未生成 cachebuster、改版本或发布。

## 环境与门禁

| 命令 | exit | 摘要 |
| --- | ---: | --- |
| `python3 --version` | 0 | Python 3.9.6 |
| `python3.11 --version` | 0 | Python 3.11.15 |
| `python3.12 --version` | 0 | Python 3.12.13 |
| `python3 -m unittest discover -s tests -v` | 0 | 284 tests |
| `python3.11 -m unittest discover -s tests -v` | 0 | 284 tests |
| `python3.12 -m unittest discover -s tests -v` | 0 | 284 tests |
| `python3 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3.11 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3.12 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3 scripts/release_preflight.py --mode development` | 0 | `status=passed` |
| Plugin validator | 0 | passed |
| Skill validator | 0 | valid |
| `git diff --check`（报告更新前） | 0 | 无空白错误 |
| P9 A–F focused suite（Python 3.11、18 modules） | 0 | 212 tests |
| `python3.11 -m unittest -v tests.test_release_tools` | 0 | 32 installer/release tests |
| `git archive --format=tar 937edbd…` 后 archive preflight | 0 | 精确 target archive，`status=passed` |

`ruff` 与 `coverage` 都不在 PATH；按 P9 的“可用时运行”规则未安装、未运行，也没有记为通过。这不属于项目声明的 required 环境缺失，故状态不是 `blocked_environment`。

## A–F current-only 复核

| 层次 | 复核证据 | 结果 |
| --- | --- | --- |
| A. 状态契约和 Schema | `test_v6_strict_state_contract`、`test_canonical_record_schema` 的完整 producer corpus、必填字段/类型/unknown/dangling mutation 与 task-name 双向矩阵 | passed |
| B. UTF-8 与 Hook | `test_cli`、`test_hook_fixtures`、`test_hook_event_contract`、`test_p8_platform_hook_cli` | passed |
| C. storage 与事务 | `test_state_store`、`test_state_store_modules`、`test_concurrency`、`test_p5_dispatch_transactions`、`test_dispatch_identity` | passed |
| D. lifecycle 与 identity | `test_communication_lifecycle`、`test_terminal_notification_channel`、`test_wait_recovery_session_closure`、`test_dispatch_identity` | passed |
| E. views、Group、Session、Diagnostics | `test_p7_views_groups_sessions_diagnostics`、`test_minimal_diagnostics_lightweight_groups`、`test_wait_recovery_session_closure` | passed |
| F. 架构和入口边界 | `test_current_only_repository`、`test_state_store_modules`、`test_p5_dispatch_transactions`、`test_p7_views_groups_sessions_diagnostics`、`test_p8_platform_hook_cli` | passed |

- A 的 corpus 包含 initial prepared/claimed/success/failed/unknown、retry 1/2、normal/recovery/interrupt pending、business-resume prepared/claimed/success/failed、terminal notification、parent close/tombstone、group 及 rollback/degraded health；runtime validator 与 JSON Schema 均接受。结构 mutation 共同拒绝，允许的跨字段冲突由 diagnostics 标记而不被规范化。
- B 复核共享 binary reader 的 exact limit、limit+1、多字节 UTF-8、invalid UTF-8/JSON/root 和最多读取 limit+1 bytes；Hook 复核 parse-before-event fail-open、PreToolUse handler failure deny、Post/Stop/Session continue、unknown event/tool 零 store construction、unmanaged spawn 零治理目录写入。
- C–E 覆盖 import 无副作用、owner/permission/symlink/nonregular/size/UTF-8/JSON、atomic/fsync/replace/readback、CAS conflict callback、package/direct import、current-only resolver、dispatch fault/concurrency、recovery budget、business-resume N+1 identity、terminal/list-agents、canonical group/session/diagnostic view、read-only diagnostic scan、排序和 UTF-8 byte cap。
- F 的 AST/import assertions 确认领域模块不反向导入 `subagent_governance`，`governance_execution` 没有 store/I/O 依赖，`governance_platform` 没有 state/store 依赖，Hook 无领域 mutation callback，CLI 无 `ModuleType` 或 runtime private access；主入口、公开 facade、唯一符号定义和 monkeypatch 所有者均由套件覆盖。
- README、architecture、release process、Schema、runtime、fixtures 与当前 Skill 对 v6、`state-v6`、operation/native tools、retry/recovery、Session retention、terminal notification、business-resume identity、no migration 及 Hook fail-open/deny 的一致性检查均通过；`state-v1` 仅存在于拒绝测试和明确历史说明，非 active runtime/Schema/fixture/Skill 路径。

## Installer current-only 事务复验

- `test_release_tools` 覆盖 empty/single/multiple cache、明确 `--previous-version`、target 不得等于 previous、完整 pre-install 集合快照、成功后只留 target、命令/cleanup/snapshot/restore 失败的完整恢复、遗留 transaction、persistent lock、same-filesystem 以及 cache 的 owner/permission/symlink/nonregular 安全边界。
- 对 version 和 Manifest 都正确的 target，已直接重放三种错误 tree digest：缺少文件、额外文件、文件模式变化。三项均返回失败，阶段为 `post_install_verification`，未删除旧 cache，且恢复 `0.4.0-rc.1` 与 `0.4.0-rc.2` 的完整集合。
- 稳定源在命令期间变化的直接重放同样返回 `post_install_verification` 并恢复完整旧集合。事务报告有界记录 `expected_stable_tree_digest`、`actual_stable_tree_digest`、`actual_target_tree_digest` 和 `failed_stage`；测试断言 stable 和 target 的 expected/actual 差异及恢复结果。
- 成功路径只在 Manifest version、stable source command 前后 digest、target tree digest 三者全部匹配时收敛为只留 target；因此上一轮 f6a72ae 的“仅 version 正确、target 内容错误仍成功”缺陷已不再出现。

## Archive、文档复跑与平台边界

archive 严格针对 `937edbd75404dacca4439e03012245acc7bc8193`：`git archive` extract exit 0，随后 `python3 "$archive_root/scripts/release_preflight.py" --root "$archive_root" --mode archive` exit 0、`status=passed`。这是精确提交的 archive gate，不是安装、发布或 release-ready 结论。

本报告和 `docs/platform-validation.md` 更新后，重新运行三套完整 unittest、development preflight、Plugin validator、Skill validator 与 `git diff --check`。`test_only_current_documents_are_shipped` 和未知 validation 文档拒绝检查随三套完整 suite 执行。

| 文档更新后的命令 | exit | 摘要 |
| --- | ---: | --- |
| Python 3.9 / 3.11 / 3.12 完整 unittest | 0 / 0 / 0 | 各 284 tests |
| `python3 scripts/release_preflight.py --mode development` | 0 | `status=passed` |
| Plugin validator / Skill validator | 0 / 0 | passed / valid |
| `git diff --check` | 0 | 无空白错误 |

真实平台保持 `not_checked`：没有安装插件或创建真实验证 task；native spawn/wait/notification、Hook trust、事件顺序、桌面 UI、restart/compact 和真实 business resume 均未验证。本地 fixture、mock、archive 与 Hook router 结果不构成真实平台证据。

## 结论

P9 current-only 独立仓库内验收为 `passed`。所有 required 且可用的 gate 通过；`ruff`/`coverage` 如实保持未运行；真实平台保持 `not_checked`，因此不作 release-ready 表述。
