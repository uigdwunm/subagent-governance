# P9：仓库内综合验收与文档/Schema/Skill 一致性

状态：已确认，待独立对话实施。

前置：P1–P8 均已完成各自实现和局部验证。

执行模型：`gpt-5.6-terra`，推理强度 `high`。

## 目标

对 P1–P8 的最终工作树进行一次独立、跨模块、current-only 的仓库内验收，形成可供 P10 使用的证据包。

P9 是验收任务，不继续重构。发现问题时只做诊断和报告；除非用户明确把当前对话改成修复任务，否则不得顺手修改实现。

## 禁止事项

- 不安装 Python 依赖、插件或 Skill。
- 不访问或修改稳定发布源、运行缓存、Hook trust、Marketplace、Registry。
- 不生成 cachebuster、不改版本、不建 tag、不发布。
- 不恢复工作树中已有删除文件，不清理无关改动。
- 不把未运行的 Python 版本、validator 或真实平台测试记为通过。
- 不用 mock/fixture 结果声称真实 Hook 或原生 Agent 已验证。

## 开始前记录

建立验收上下文：

- 当前 commit id。
- `git status --short`。
- P1–P8 修改文件清单。
- Python 3.11/3.12、ruff、coverage 和 validator 的实际可用性。
- 当前 Manifest 完整版本。
- `STATE_FORMAT_VERSION` 和默认 data namespace。
- P1–P8 文档状态。

工作树允许包含用户原有改动。P9 不以“工作树干净”作为开发验收前提，但必须如实记录 dirty 状态，不能宣称 release-ready。

## 验收层次

### A. Current-only 状态契约

验证：

- runtime current-state validator 与 Schema 使用 v6。
- 默认 namespace 只为 `state-v6`。
- root/task/work-item/execution/planes/pending/health/tombstone/agents/groups 关闭未知字段。
- TaskContract 和 PreparedContract 使用当前严格定义。
- `managed=false` 和旧式 task 被拒绝。
- old `state-v1` 不读取、不迁移、不删除。

建立 producer corpus：

- initial prepared/claimed/success/failed/unknown；
- retry 1/2；
- normal message/recovery/interrupt pending；
- business resume prepared/claimed/success/failed；
- terminal notification；
- parent close/tombstone；
- group；
- rollback/degraded health。

对每个 corpus：

```text
runtime validator accepts
AND JSON Schema accepts
```

Mutation matrix 至少包含：

- 删除每个必填字段；
- 修改类型；
- 注入未知字段；
- 非法 enum/count/digest/ref/name；
- dangling attempt/group/agent references。

结构 mutation 必须同时被 runtime 和 Schema 拒绝；允许的跨字段冲突必须由 diagnostics 标记，而不是被错误规范化。

### B. 输入和外部协议边界

验证所有 JSON stdin 模式共享 binary reader：

- exact byte limit；
- limit+1；
- 2/3/4-byte UTF-8；
- invalid UTF-8/JSON/root；
- reader 最多请求 limit+1 bytes。

验证 Hook 边界：

- parse-before-event failure fail-open；
- parsed PreToolUse handler failure deny；
- Post/Stop/Session failure continue；
- unknown event/tool 零 store construction；
- unmanaged spawn 零治理目录写入；
- external unknown Hook fields 不导致内部 current-state 放宽。

### C. Storage 和事务

验证：

- StateStore/PreparedStore import 无副作用；
- owner/permission/symlink/nonregular/size/UTF-8/JSON；
- atomic write、fsync、replace、readback；
- CAS conflict 不调用 callback；
- package/direct import；
- data-root developer/installed/cache/explicit resolver；
-无旧 namespace fallback。

Dispatch fault matrix 覆盖每个提交点和“落盘后抛错”：

- initial exact rollback/degraded marker；
- retry exclusive credential；
- prepare/claim/Post/reconcile 并发；
- exact compensation 不覆盖较新状态；
- orphan credential 可幂等收缩；
- late failure 不覆盖 positive evidence。

### D. Lifecycle 和 identity

验证：

- recovery budget 在 claim 时消耗；
- normal/interrupt fail-open 与 resume/recovery deny 边界；
- business resume source close、N+1 target/tool-use/index/current attempt；
- resumed message 包含 N+1 identity；
- N+1 terminal notification 和 list-agents 命中 N+1；
- delivery failed 可再次 resume 或 close；
- unrelated session update 不误判 claim ambiguous；
- parent close 精确清理 agents mapping。

### E. Views、Group、Session、Diagnostics

验证：

- Group/Session/Diagnostics 共用 canonical work-item view。
- open + current `resume_delivery_failed` 仍 action-required。
- SessionEnd 不删除 open/indeterminate、pending、tombstone 或 degraded health。
- group summary-ready/action-required 规则。
- SessionStart maintenance warning 不吞掉可读摘要。
- Stop advisory-only。
- diagnostics 对 valid v6 派生、对 invalid/old format 只报告不修补。
- diagnostic scan 前后目录 tree、mtime、lock/temp 均不变。
-输出排序和 UTF-8 byte cap 确定。

### F. 架构边界

使用 AST/import 检查：

- 领域模块不导入 `subagent_governance`。
- `governance_execution` 无 store/I/O 依赖。
- `governance_platform` 无 state/store 依赖。
- `governance_hook` 无领域 mutation callback。
- CLI 无 `ModuleType` 和 runtime private access。
-主入口只有 entrypoint、curated facade、`__all__`。
- moved classes/functions 只有一个定义。
- 无循环依赖。
- monkeypatch 指向真实符号所有者。

## 文档、Schema、Skill 一致性

逐项对账：

| 事实 | 必须一致的位置 |
|---|---|
| state format v6 | semantics、Schema、runtime、fixtures、docs |
| state-v6 namespace | store support、tests、architecture、diagnostics |
| operation types/native tools | semantics、lifecycle、Skill、docs、Hook matcher |
| retry/recovery limits | semantics、runtime、Schema、Skill |
| retention/Session behavior | semantics、sessions、Skill、docs |
| terminal notification | rendering、lifecycle、Skill、README/docs |
| business resume identity | lifecycle、views、Schema、Skill、fixtures |
| current-only/no migration | runtime、tests、README/docs |
| Hook fail-open/deny | Hook、Skill、architecture、fixtures |
| platform not-checked facts | diagnostics、platform-validation、installation checker |

仓库运行资产中不得残留 `state-v1`、format v5、旧 TaskContract/PreparedContract 或已删除 root projections 的 active 引用。计划文档和明确的历史说明可以提及旧名，但不能被 runtime、Schema、Skill 当前指令或 fixtures 使用。

## 必须运行的验证

先检查命令是否存在，不自行安装缺失工具。

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
python3 scripts/release_preflight.py --mode development
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
git diff --check
```

如果可用，还必须运行：

```bash
python3.11 -m unittest discover -s tests -v
python3.12 -m unittest discover -s tests -v
python3.11 -m py_compile scripts/*.py
python3.12 -m py_compile scripts/*.py
ruff check scripts tests
coverage run -m unittest discover -s tests -v
coverage report
```

如果项目门禁声明某项为必需但环境缺失，P9 状态是 `blocked_environment`，不能记为通过，也不能自行 pip install。

## Archive 验证边界

只有当 P1–P8 的目标实现已经进入一个明确 commit 时，才运行：

```bash
archive_root="$(mktemp -d)"
git archive --format=tar <target-commit> | tar -xf - -C "$archive_root"
python3 "$archive_root/scripts/release_preflight.py" \
  --root "$archive_root" \
  --mode archive
```

如果目标实现仍未提交：

- 不得用 `git archive HEAD` 冒充验证工作树实现。
- archive validation 记为 `not_run_uncommitted`。
- 不经用户授权创建 commit。
- P9 可以完成“working-tree local acceptance”，但不能宣称 archive/release readiness。

## 验收报告

执行对话应创建或更新：

```text
docs/validation/current-only-local-acceptance.md
```

报告至少包含：

- target commit/worktree 状态；
-每条命令、exit code、关键计数；
- corpus/mutation/fault matrix 结果；
- architecture 和 consistency 检查；
-未运行项目及原因；
- real platform 明确标记 `not_checked`；
-结论：`passed`、`failed` 或 `blocked_environment`。

不要粘贴完整冗长测试日志；保留命令、摘要和可定位失败。

同时更新 `docs/platform-validation.md` 的本地验证部分，但真实插件项目仍必须保持 `not_checked`。

## 通过标准

P9 只有以下全部成立才可标记 `passed`：

- P1–P8 的局部和完整测试通过。
- runtime/Schema corpus 与 mutation 关系成立。
-事务 fault/concurrency matrix 通过。
-架构边界无反向依赖/重复实现/动态 runtime access。
- docs/Schema/Skill/fixtures 一致。
- required validators 和 development preflight 通过。
-没有安装、发布或外部状态写入。
-所有未验证真实平台事实标记 `not_checked`。

Archive 未运行时必须单独标记，不能影响 working-tree local acceptance 的事实表达，但会阻止 release-ready 声明。

## 停止条件

- 完整测试或 validator 出现回归。
- runtime 与 Schema 对同一结构样本结论不一致。
- 需要修改实现才能继续验收。
- 缺失必需运行时/工具且需要安装。
- 无法确定 P1–P8 的目标工作树/commit。
- 发现 P1–P8 之外的大范围问题；记录后请求新修复方案。
