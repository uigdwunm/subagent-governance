# P9 current-only 本地综合验收

日期：2026-08-24  
结论：`failed`（仓库内验收；不是真实平台验收，也不代表已发布或 release-ready）

## 验收对象与边界

- 目标实现 commit：`8757287e0b14e1f901f9fa93186ce09af842634d`（`refactor: split platform hook and cli entrypoints`）。开始时 detached `HEAD`、`codex/current-only-improvements` 都指向此对象，`git diff --quiet 8757287 --` exit `0`，`git status --short` 为空。
- P9 报告分支：`codex/p9-local-integrated-acceptance`，从上述目标提交创建。验收期间没有安装依赖、插件或 Skill，也没有访问稳定源、运行缓存、Hook trust、Marketplace 或 Registry。
- 目标与根提交 `d23493ecf4e46327d04f7dee7074a3a619cbd142` 相比有 109 条路径变更：scripts 30、tests 35、docs 17、schemas 4、Skill 6、其余 17。完整可复现清单：`git diff --name-status d23493e..8757287`。实现提交序列为 P1 `b391322`、P2 `afa1279`、P3 `66711b7`、P4 `e0578a1`、P5 `5552997`、P6 `7bd99d0`/`011a34e`/`f1fb6c6`、P7 `acef8eb`、P8 `8757287`。
- 所有 P1–P9 计划文件仍写作“已确认，待独立对话实施”；这里如实记录为计划文档状态，不把它误写为 runtime 状态。提交历史和本验收针对的 target 是 P1–P8 实现证据。
- Manifest：`.codex-plugin/plugin.json` 的完整版本为 `0.4.0-rc.13+codex.20260823131943`。`STATE_FORMAT_VERSION=6`，默认 `STATE_STORAGE_NAMESPACE=state-v6`。

## 环境与命令

| 命令 / 探测 | exit | 结果 |
| --- | ---: | --- |
| `python3 --version` | 0 | Python 3.9.6 |
| `python3.11 --version` | 0 | Python 3.11.15 |
| `python3.12 --version` | 0 | Python 3.12.13 |
| `ruff --version` | 127 | 未安装；可选 gate 未运行，未安装它 |
| `coverage --version` | 127 | 未安装；可选 gate 未运行，未安装它 |
| `python3 -m unittest discover -s tests -v`（报告写入前） | 0 | 266 tests |
| `python3.11 -m unittest discover -s tests -v`（报告写入前） | 0 | 266 tests |
| `python3.12 -m unittest discover -s tests -v`（报告写入前） | 0 | 266 tests |
| `python3 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3.11 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3.12 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3 scripts/release_preflight.py --mode development` | 0 | passed |
| `python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .` | 0 | passed |
| `python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance` | 0 | passed |
| `git diff --check`（报告修改前） | 0 | 无空白错误 |
| `python3.11 -m unittest -v tests.test_current_only_repository`（报告写入后） | 1 | 3 tests；1 failure |
| `python3 -m unittest discover -s tests -v`（报告写入后） | 1 | 266 tests；1 failure |
| `python3.11 -m unittest discover -s tests -v`（报告写入后） | 1 | 266 tests；1 failure |
| `python3.12 -m unittest discover -s tests -v`（报告写入后） | 1 | 266 tests；1 failure |
| `git diff --check`（报告写入后） | 0 | 无空白错误 |
| `python3 scripts/release_preflight.py --mode development`（报告状态更新后） | 0 | passed |
| Plugin validator（报告状态更新后） | 0 | passed |
| Skill validator（报告状态更新后） | 0 | passed |
| `git diff --check`（报告状态更新后） | 0 | 无空白错误 |

`ruff check scripts tests`、`coverage run -m unittest discover -s tests -v` 和 `coverage report` 未运行，唯一原因是相应命令不在环境中；它们是“可用时必跑”的可选项，不能记为通过。

报告写入后的 4 个 unittest 命令有同一个、可定位的 failure：`tests.test_current_only_repository.CurrentOnlyRepositoryTests.test_only_current_documents_are_shipped` 硬编码了 `docs/` 只允许 5 个文件，而 P9 要求新增的 `docs/validation/current-only-local-acceptance.md` 正是额外项。报告前 target 的 3 套完整测试均通过；报告进入工作树后每套 266 tests 都只此 1 项失败。P9 严格边界禁止修改 tests 或实现，故不修复而将本验收标为 `failed`。

## A–F 验收矩阵

| 层次 | 证据 | 结果 |
| --- | --- | --- |
| A. current-only 状态契约 | `test_v6_strict_state_contract`、`test_canonical_record_schema`、`test_current_only_repository`（15 tests）；独立 structural matrix | passed |
| B. UTF-8 与 Hook 边界 | `test_cli`、`test_hook_fixtures`、`test_hook_event_contract`、`test_p8_platform_hook_cli`（20 tests） | passed |
| C. storage 与事务 | `test_state_store`、`test_state_store_modules`、`test_concurrency`、`test_p5_dispatch_transactions`、`test_dispatch_identity`（95 tests） | passed |
| D. lifecycle 与 identity | `test_communication_lifecycle`、`test_terminal_notification_channel`、`test_wait_recovery_session_closure`、`test_dispatch_identity`（87 tests） | passed |
| E. views/group/session/diagnostics | `test_p7_views_groups_sessions_diagnostics`、`test_minimal_diagnostics_lightweight_groups`、`test_wait_recovery_session_closure`（24 tests） | passed |
| F. AST/import 架构边界 | `test_current_only_repository`、`test_p5_dispatch_transactions`、`test_p7_views_groups_sessions_diagnostics`、`test_p8_platform_hook_cli`（20 tests）及独立 AST 审计 | passed |

上述分项有重叠，不能相加替代完整套件的 266 tests。producer corpus 由 initial/retry、claimed/unknown/failed、normal/recovery/interrupt pending、business-resume、notification/parent-close/tombstone、group、degraded health 的对应 P1–P8 测试共同生成并验证；`test_full_producer_corpus_is_accepted_by_runtime_and_schema` 还验证合成的 canonical producer state 同时被 runtime 与 JSON Schema 接受。

独立 runtime/Schema mutation 命令以一个新的 canonical v6 record 为样本，结果如下：

| 检查 | runtime 与 JSON Schema 同时拒绝 |
| --- | ---: |
| 每个已定义必填字段删除 | 33/33 |
| 已存在非 null 字段改为错误类型 | 25/25 |
| root/task/work-item/execution/三 planes 注入未知字段 | 7/7 |
| 非法 enum/count/digest/ref/name | 6/6 |

跨字段引用、并发与 fault 不是被“修正”的输入：对应测试覆盖 CAS callback 不执行、atomic/fsync/replace/readback 失败、prepare/claim/cleanup 并发、late failure 不覆盖正向证据、orphan credential 收缩、recovery budget claim 时消费、business resume N+1 identity、delivery failed 后继续 resume/close，以及 parent close 精确清除 `agents` mapping。diagnostics 对可接受但冲突的 cross-field 事实只标记问题，不写回规范化。

B 层测试覆盖二进制 stdin 的精确 byte limit、limit+1、多字节 UTF-8、非法 UTF-8/JSON/root 与最多 `limit+1` bytes 请求；Hook 覆盖 parse-before-event fail-open、PreToolUse deny、Post/Stop/Session continue、unknown event 零 store construction、unmanaged spawn 零治理目录写入及未知外部字段不放宽内部契约。

E 层的零写入证据包括 v5/invalid diagnostics 前后 state/lock 的 SHA-256 和 mtime 一致；诊断 scan 不创建 lock/temp、不更改目录 tree。`resume_delivery_failed` 的 open work item 仍为 action-required；SessionEnd 保留 open/indeterminate、pending、tombstone 和 degraded health；Stop 是 advisory-only，摘要排序和 UTF-8 byte cap 由 views/diagnostics 测试覆盖。

## 架构与一致性审计

- AST/import 审计：领域模块反向导入 `subagent_governance` 为 0；`governance_execution` 无 store/storage/support 依赖；`governance_platform` 无 state/store/storage/support 依赖；CLI runtime private attribute access 为 0；入口顶层定义恰为 `handle`、`main`；26 个 governance 模块、109 条内部边、循环依赖 0。
- 迁移符号的单一所有者由 P5/P7/P8 AST tests 验证；扫描发现的同名私有通用辅助函数均位于不同领域（例如 `_now`），并非 moved lifecycle/view/entrypoint 实现，未构成重复所有权。
- 文档/Schema/Skill/fixtures 对账通过：machine semantics、runtime、Schema 均为 v6；Schema const 为 6，namespace resolver 仅生成 `state-v6`；operation/native-tool、retry/recovery limit、retention/SessionEnd、terminal notification 的 exact sender binding、business resume 的 `prepared_on_attempt`/N+1、current-only、Hook fail-open/deny 都由 `test_semantic_baseline`、schema/fixture tests 和 plugin structure tests 共同约束。
- target 上对 scripts、schemas、Skill、fixtures、README 和非计划/非验收 docs 的 lexical audit：`state_format_version=5`/`STATE_FORMAT_VERSION=5` 0，旧 `TaskContractV*` 0，旧 `PreparedContractV*` 0，`root_projection` 0。仅有 4 个 `state-v1` 提及，全部是 README、architecture 或 Skill 中“旧数据不读取、不迁移、不删除”的 current-only 禁止说明；不是 active runtime/Schema/fixture fallback。

## Archive 与平台边界

目标实现已提交，因此严格使用目标对象而非其他 HEAD：

```bash
archive_root="$(mktemp -d)"
git archive --format=tar 8757287e0b14e1f901f9fa93186ce09af842634d | tar -xf - -C "$archive_root"
python3 "$archive_root/scripts/release_preflight.py" --root "$archive_root" --mode archive
```

extract exit `0`；archive preflight exit `0`，输出 `status=passed`、`mode=archive`、manifest `0.4.0-rc.13+codex.20260823131943`。这只证明该提交的 archive gate，通过不等于安装/发布。

真实平台状态：`not_checked`。没有安装本地插件，没有创建新真实验证 task，也没有把 mock、fixture 或本地 Hook router 的结果描述成真实 spawn/wait/notification/Hook trust/UI 验证。P10 未启动。

## 停止条件

已触发：报告作为 P9 必需产物加入 `docs/validation/` 后，完整测试发生上述固定的一项 regression。根因是现有文档库存 gate 没有排除 P9 所要求的验证报告路径；修复它需要修改 test，超出本次仅验收边界。目标 P1–P8 commit 可确定，runtime/Schema matrix、required validators 和 archive gate 均通过；可选 `ruff` 和 `coverage` 缺失已如实记录，不需要安装。
