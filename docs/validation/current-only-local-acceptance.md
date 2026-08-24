# P9 current-only 本地综合验收

日期：2026-08-24  
结论：`failed`（精确提交的仓库内独立验收；未安装、未发布，真实平台仍为 `not_checked`）

## 对象、边界与开始状态

- 目标基线：`f6a72aed07554c2473b502f1d6ad19613005bd02`，提交信息 `fix: snapshot full cache set during plugin install`，父提交 `37774b12269124076a8297f08e7803a1b3903b9d`，目标 ref `codex/current-only-improvements`。开始时 HEAD 精确等于目标，`git status --short` 为空。
- `git diff --name-only aa408ed..f6a72aed07554c2473b502f1d6ad19613005bd02` 为 165 条 P1–P8/current-only/P10 相关路径变更。Manifest 完整版本为 `0.4.0-rc.13+codex.20260823131943`；`STATE_FORMAT_VERSION=6`，默认 namespace 为 `state-v6`。
- 全程未安装依赖、插件或 Skill；未触碰稳定源、运行 cache、AGENTS、Marketplace、Registry 或 Hook trust；未生成 cachebuster、修改版本或发布。

## 已完成门禁

| 命令 | exit | 摘要 |
| --- | ---: | --- |
| `python3 --version` | 0 | Python 3.9.6 |
| `python3.11 --version` | 0 | Python 3.11.15 |
| `python3.12 --version` | 0 | Python 3.12.13 |
| `python3 -m unittest discover -s tests -v` | 0 | 280 tests |
| `python3.11 -m unittest discover -s tests -v` | 0 | 280 tests |
| `python3.12 -m unittest discover -s tests -v` | 0 | 280 tests |
| `python3 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3.11 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3.12 -m py_compile scripts/*.py` | 0 | 30 scripts |
| `python3 scripts/release_preflight.py --mode development` | 0 | `status=passed` |
| Plugin validator | 0 | passed |
| Skill validator | 0 | valid |
| `git diff --check`（报告更新前） | 0 | 无空白错误 |
| P9 A–F focused suite（Python 3.11；含 `test_release_tools`） | 0 | 208 tests |
| archive：`git archive --format=tar f6a72ae…` 后 `release_preflight.py --mode archive` | 0 | 精确 target archive，`status=passed` |

`ruff` 与 `coverage` 均不在环境 PATH，按 P9 的“可用时运行”规则未安装、未运行，也未记为通过。

## A–F 与 P10 复核

- A–F focused suite 覆盖 v6 strict runtime/Schema corpus 和 structural mutation、共享 binary reader 与 Hook fail-open/deny、StateStore/PreparedStore 安全和事务、lifecycle identity、views/group/session/diagnostics，以及 AST/import/entrypoint 边界；208 项均通过。
- P10 的现有 `test_release_tools` 覆盖双 cache 成功后只保留 target、add 失败和命令异常回滚、目标缺失、显式 `--previous-version` 拒绝、target=previous 拒绝、快照/清理/恢复失败、遗留 transaction、OS lock、same-filesystem、symlink、owner/permission/nonregular 安全边界。
- README、`docs/release-process.md`、P10 与 CLI 都要求 `--previous-version` 和 `--target-version`，且明确禁止猜测 current；源码也记录完整 pre-install cache names/digests、previous、removed 和 restored facts。

## 失败证据：目标 digest 未验证

P10 新增要求包括“目标 cache 的 Manifest/version/digest 不正确时完整恢复”。该条件不成立。

- [`scripts/reinstall_plugin.py`](/Users/zhaolaiyuan/.codex/worktrees/022b/subagent-governance/scripts/reinstall_plugin.py:433) 对 target 仅调用 `tree_digest(target_cache)`，但丢弃返回值；随后只比较 `manifest_version(target_cache) == target_version`。
- installer 没有接收、计算或持久化任何预期 target digest，因此无法判断 target 内容是否被篡改；当前 `test_release_tools.py` 也没有该负向用例。
- 隔离 `tempfile.TemporaryDirectory()` 复现：预安装 cache 为 `0.4.0-rc.1`，runner 返回 0 并创建 version 正确、Manifest 正确但内容不同的 `0.4.0-rc.2`。预期 target digest 为 `271515f893b0c99544d740a9ebe4260c3029c918b3e96935c63c2a295cac103a`，实际为 `964b156e0ae31218b8b227db3e92582ae4cf11fa62ad392cf0d9e8c1a94442d6`；installer 仍返回 `0`、报告 `state=install_succeeded`、只余 `0.4.0-rc.2`，`rollback_occurred=false`。

这会在 `codex plugin add` 产生版本正确但内容不正确的目标 cache 时删除完整 pre-install 集合，违反本次 P10 事务修复的目标 digest/完整恢复要求。

## 停止边界与真实平台

发现上述正确性问题后，依照 P9 约束停止进一步验收：没有修改实现，也没有在报告更新后重复完整门禁。该缺陷修复并独立复验前，P9 不可标记 `passed`，archive preflight 的通过也不能改变该结论。

真实平台保持 `not_checked`：未安装插件，未验证真实 native spawn/wait/notification、Hook trust、事件顺序、桌面 UI、restart/compact 或真实 business resume。本地 fixture、mock 和 archive 结果不构成真实平台证据。
