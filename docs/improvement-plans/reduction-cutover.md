# Subagent Governance reduction cutover

- 状态：Accepted plan，尚未实施
- 日期：2026-08-25
- 决策来源：`docs/architecture-reduction-adr.md`
- 实施方式：新的 `codex/` 分支，按本计划顺序完成；不兼容或迁移现有运行状态

## 目标

将当前以 PostToolUse、双存储和多 attempt 为核心的实现切换为：

- 一个 task 对应一个原生 Agent 生命周期；
- 单一 Session ledger；
- governed spawn PreToolUse 原子 claim；
- 父 Agent 显式提交原生 spawn 返回的 exact target；
- 只持久化影响后续安全决策的 observation、terminal、interrupt、close 和 reconcile 事实；
- 只读 SessionStart/status；
- allowlisted runtime bundle 与单一开发部署入口。

完成标准不是保留现有 API 或测试数量，而是新 ADR 中的产品承诺全部具有本地验证证据，并删除不再属于产品的状态、Hook、命令、文档和测试。

## 前置与边界

- 实施前从当前精确 HEAD 创建新的 `codex/` 分支；不要在 detached HEAD 上形成实施提交。
- ADR 与本计划先作为独立决策基线提交，再开始运行时修改。
- 开发仓库始终是唯一修改源。
- 不读取、迁移、修复、写回或删除 `state-v8` 及更早 namespace。
- 不兼容旧 TaskContract、PreparedContract、task name、CLI write contract 或 lifecycle records。
- 本地实现阶段不安装、不发布、不写 stable source、runtime cache、Hook trust、Marketplace 或 Registry。
- 不建立 old/new 双写、fallback adapter、compatibility reader 或影子 Post settlement。
- `docs/architecture.md`、README 和 Skill 只有在对应实现落地后才切换为新语义，不能提前描述未实现行为。

## 固定协议

### Current-only 版本

- 新状态格式：`state_format_version=9`。
- 新默认 namespace：`state-v9`。
- 新 TaskContract wire contract：v2。
- v8 及更早状态只返回 unsupported-current-format，不进入 partial diagnostics。

### Session ledger

根记录精确包含：

```text
state_format_version
session_id
tasks
```

每条 task 的公共字段精确包含：

```text
task_ref
phase
contract_digest
contract_summary
created_at
updated_at
```

phase 只有：

```text
prepared | claimed | bound | terminal | closed | reconcile
```

phase-specific 字段：

- `prepared`：prepared capability。
- `claimed`：prepared capability、claimed time。
- `bound`：exact target，可选 last platform observation。
- `terminal`：exact target、至少一个可靠 terminal fact，可选 terminal notification。
- `closed`：可选 exact target、close reason、closed time。
- `reconcile`：有界 reason，并保留此前已可靠建立的 exact target、observation 或 terminal fact。

prepared capability 只保存 claim 所需的 current TaskContract、context verification、expected native parameters 和 expiry。bind、明确 failed 或 close 后不继续保存完整 capability。

根和所有 persisted nested records 使用关闭字段集合。跨字段 validator 至少保证：

- task key、task ref 和 phase-specific 字段一致；
- target 只在已绑定或保留可靠 identity 的 phase 出现；
- terminal fact、notification、close fact 结构完整；
- unknown field、managed=false、attempt、agents、groups、tombstones、receipt 和旧 plane 字段全部拒绝；
- runtime accept 的结构样本同时由 canonical Schema 接受。

### TaskContract v2

模型输入：

```text
profile
objective
scope
forbidden_scope
completion
evidence
context
spawn
```

- `profile=standard|strict`，默认 standard。
- objective、非空 scope 和非空 completion 必填。
- forbidden scope、evidence、context 和 spawn 可省略并由生成器补默认值。
- strict 要求非空 forbidden scope 和 evidence。
- context 只包含 summary、普通定位 paths 和可选 verified materials。
- spawn 只包含原生 fork_turns、model 和 reasoning_effort。
- semantic name、task ref、task name 和显示文本由生成器派生。
- business contract digest 不包含 spawn config。
- 删除 auto/light、requested/resolved mode、resolution reason、task features、background/current state 重复字段和 context strategy/turns/reason。

### 写操作

首版 write API 固定为：

```text
prepare-dispatch
confirm-dispatch
record-dispatch-result
record-platform-observation
record-call-result
record-terminal-notification
record-interrupt-result
close-task
```

只读 API：

```text
status --session <exact-session-id>
diagnose [--session <exact-session-id>]
```

关键输入边界：

- `confirm-dispatch`：task id、task ref、exact target；只接受 claimed/unbound。相同 target 重放幂等，不同 target 进入 reconcile。
- `record-dispatch-result`：只处理明确 failed 或 unknown；failed 表示未创建并关闭，unknown 进入 reconcile。
- `record-platform-observation`：task id、已绑定 exact target、规范化 status；target 不匹配拒绝，绝不补绑 identity。
- `record-call-result`：normal message success/failed 为无状态结果；unknown 只写 delivery-unknown reconcile reason，不保存 message。
- `record-terminal-notification`：exact sender、task id、terminal status；不再接收 attempt，不保存正文。
- `record-interrupt-result`：明确 inactive 建立 terminal fact；unknown 进入 reconcile。
- `close-task`：父 Agent 完成判断后显式关闭；不自动调用 interrupt。

所有 JSON stdin 继续共用 UTF-8 byte bounded reader。

### Hook

最终 Hook manifest 只注册：

- governed/unmanaged spawn 的 PreToolUse matcher；
- best-effort、只读 SessionStart matcher。

删除 PostToolUse、Stop、SessionEnd 和 communication/followup/interrupt PreToolUse。

SessionStart 使用 diagnostics 同等级的无锁只读 reader，不创建目录、lock、临时文件或空 Session，不 cleanup、rebuild、reconcile、自动关闭、自动调用工具或扫描其他 Session。

## 实施阶段

### 1. 决策基线与新验收骨架

- 建立实施分支并提交 ADR、cutover plan 和文档 allowlist。
- 新增 v9/v2 producer corpus、mutation matrix 和 CLI contract tests。
- 新测试以 ADR 行为为目标，不导入旧 runtime 私有函数。
- 明确旧测试文件的 keep/rewrite/delete 清单。

完成条件：新协议的合法/非法样本、phase transitions 和 identity 冲突规则能在测试中独立表达；尚未要求旧 runtime 通过这些新测试。

### 2. 单一 ledger 与精简契约

- 重写 canonical Schema、semantics、TaskContract parser/digest 和 strict runtime validator。
- 保留并复用安全 storage primitives、StateStore lock/atomic write/readback 和容量边界。
- StateStore 只读写 v9 单 ledger；不创建 PreparedContract 或辅助 index root。
- 实现无锁只读 status/diagnostic reader。

完成条件：v9 producer corpus 同时通过 runtime 与 Schema；required deletion/type/unknown mutations 同时被拒绝；v8 文件保持字节与 mtime 不变。

### 3. 派发与 explicit identity

- 实现 prepare-dispatch，在同一 ledger 写 prepared capability。
- PreToolUse 只验证 unmanaged/governed spawn，并原子执行 prepared→claimed。
- 实现 confirm-dispatch、明确 failed 和 unknown dispatch result。
- 删除 spawn Post adapter、Post observation 和 retry generation。

完成条件：prepare/claim 单次消费、exact target first-bind-wins、相同确认幂等、冲突确认 reconcile、confirm 前崩溃保持 claimed/unbound，且任何 list/final/time/name 都不能补绑 identity。

### 4. 最小生命周期

- 实现 exact platform observation、normal-message unknown、terminal、interrupt result 和 close。
- normal message success/failed 不写调用历史。
- running/terminal/error/unknown 的 allowed next action 全部由 phase 和可靠事实派生，不持久化 parent action。
- closed task 由后续 ledger 写操作按固定 retention 惰性清理。

完成条件：所有 write API 均满足 exact task/target admission、重放和冲突规则；正文、response、summary 和 transcript 不进入状态。

### 5. 删除旧机制并收缩边界

删除运行时所有引用和对应 Schema/Skill/CLI：

- PreparedContractStore 与 prepared root；
- ClaimedPostIndex、Post receipt 和 catch-all router；
- agents index、attempt、多 execution 和 resume identity routing；
- pending action、last lifecycle operation、recovery/retry budget；
- Group 和独立 tombstone；
- business resume、platform recovery、followup managed protocol；
- Stop、SessionEnd 和 SessionStart maintenance；
- auto/light/task features 与旧 TaskContract fields。

优先删除整个机制和测试，不保留返回固定错误的 retired API stub。

完成条件：runtime、Schema、Skill 和 active docs 中没有上述 current capability；历史计划和验证报告可保留事实性提及。

### 6. Runtime bundle 与开发部署

- 建立机器可检查的 runtime allowlist。
- bundle digest 只覆盖 allowlisted projection。
- 将 P13/P14 原则合入一个开发仓库入口；stable sync、installer、checker 和 cache transaction code不进入 bundle。
- 删除全局 AGENTS block 写入脚本、asset、文档和检查逻辑。
- 保留 exact previous、最多双版本、digest、atomic activation 和 rollback 的开发测试能力。

完成条件：runtime bundle 不含 tests、CI、improvement plans、validation reports、AGENTS、开发依赖或部署工具；普通文档/测试变化不改变 bundle digest。

### 7. 当前文档与本地综合验收

- 只有在实现完成后才更新 README、architecture、Skill、runtime boundaries、Hook contract 和 release process。
- 将 P12-B 标记为 rejected/archived，将 P1–P14 索引标记为历史改造记录。
- 重写本地 acceptance report，不能复用旧 325-test 通过结论。

必须运行：

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
python3 scripts/release_preflight.py --mode development
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
git diff --check
```

如果可用，继续运行项目支持的其他 Python 版本、ruff 和 coverage；未运行项如实记录。

### 8. 经授权安装与真实平台验证

本地验收通过后，另行取得 stable/cache 写入授权并使用新的部署入口。安装、重启后在新的独立任务顺序验证：

```text
V1 unmanaged spawn：fail-open、零状态
V2 prepare → claim → native spawn → confirm exact target
V3 wait 与 exact list observation
V4 normal message 与 terminal notification
V5 minimal interrupt 与 parent close
V6 SessionStart/status 的 exact-session 恢复
V7 用户触发的 restart/compact
```

任一 correctness failure 都停止后续场景，返回开发仓库新任务修复；不热修 runtime cache。Hook trust、registration、UI 和 exact session identity 分别记录，不能由文件存在或 installed/enabled 推断。

## 测试处置原则

必须保留或重写：

- strict Schema/runtime parity；
- UTF-8 byte boundary；
- owner/permission/symlink/non-regular/capacity/atomicity/concurrency；
- unmanaged fail-open；
- prepare/claim/confirm 和 crash gap；
- exact target observation、terminal、interrupt、close；
- conflict/replay/unknown 不猜测；
- SessionStart/status 零写入；
- privacy projection；
- runtime allowlist、bundle digest、atomic dev deploy；
-真实 smoke matrix。

删除而不迁移：

- 双 store compensation、rollback marker 和 orphan credential characterization；
- Post index/receipt/replay/catch-all 测试；
- business resume、multi-attempt、platform recovery budget；
- Group、Stop、SessionEnd maintenance；
-历史 phase/plane/agents/tombstone 字段 mutation；
-按 P4/P5/P7/P8 实施阶段命名但只锁定已删除内部结构的测试。

测试数量和代码行数不是验收指标；以产品承诺覆盖、无重复 authority 和真实平台证据为指标。

## 停止条件

遇到以下任一情况时停止当前阶段并报告，不通过新增状态机绕过：

- 父 Agent 无法从原生 spawn 返回机械取得 exact target；
- explicit confirmation 必须依赖 transcript、summary、时间或 list 猜测；
- 单一 ledger 需要第二份 correctness-authoritative store 才能完成 claim；
- 平台要求 PostToolUse 才能执行最小产品承诺；
- SessionStart 的 exact session identity 在真实环境中不稳定；此时只降级自动恢复承诺，不扫描其他 Session；
- runtime allowlist 无法表示 Codex 可安装插件的必要文件；
- 开发部署必须修改 Hook trust、Registry 或 Marketplace 内部状态才能构造 bundle；
- 本地验证要求兼容或迁移旧 state/contract；
- 实施范围与用户已有修改发生无法安全合并的冲突。

## 不在本计划内

- managed followup/business resume；
-跨 Session 自动发现或迁移；
- DAG、Group、batch 或并发调度；
-平台权限、安全或密码学 trust；
-公共发布、tag、Marketplace 更新；
-为旧运行状态提供兼容期；
-以代码规模目标驱动机械拆文件。
