# 当前架构

Subagent Governance 是 Codex 原生子 Agent 的本地生命周期治理层。它继续使用原生 Agent 工具，不替代平台调度、权限、Hook trust、沙箱或父 Agent 的业务判断。

当前实现已完成 [减法收口 cutover](improvement-plans/reduction-cutover.md) 的派发与最小生命周期切片：state-v9 单一 Session ledger、TaskContract v2、prepare、governed spawn Pre claim、父 Agent explicit exact-target confirm，以及 observation/terminal/interrupt/close 已落地。当前代码不保留旧机制作为兼容 fallback。

## TaskContract v2

模型输入只有：

```text
profile
objective
scope
forbidden_scope
completion
evidence
context(summary, paths, optional verified)
spawn(fork_turns, model, reasoning_effort)
```

- objective、非空 scope 和非空 completion 必填；其余字段有机械默认值。
- profile 只有 standard 与 strict；strict 要求非空 forbidden scope 和 evidence。
- 普通 context paths 是定位提示。`context.verified` 是显式 opt-in 的 declared working-tree/Git material verification；prepare 和 claim 各验证一次。
- semantic name、task ref 和 task name 由 runtime 派生。
- business contract digest 排除 spawn config；spawn config 使用独立 digest。

## state-v9 单一 ledger

每个 exact Session 只有一份 JSON ledger，根字段精确为：

```text
state_format_version
session_id
tasks
```

一个 task 对应一个原生 Agent lifecycle，没有 attempt。phase 只有：

```text
prepared | claimed | bound | terminal | closed | reconcile
```

prepared capability 位于 task record 内，和 lifecycle state 共享同一 lock 与原子写边界。当前持久状态没有 PreparedContractStore、agents index、Post receipt/index、pending action、tombstone 或 Group。

StateStore 只接受严格 `state_format_version=9`，默认 namespace 为 `state-v9`。v8 及更早状态不读取、不迁移、不修复、不写回、不删除。

## 派发与 identity

```text
prepare-dispatch
→ prepared
→ governed spawn PreToolUse atomic claim
→ claimed/unbound
→ native spawn_agent
→ parent confirms exact target from that current native return
→ bound
```

identity 的唯一权威是父 Agent 对当前原生 spawn 返回 exact target 的显式 `confirm-dispatch`：

- first bind wins；
- 相同 target 重放幂等；
- 不同 target 或 task/ref 不匹配进入 reconcile；
- task/ref 匹配但 exact Session task 仍为 `prepared` 时，以 `dispatch_claim_missing` 进入 reconcile，绝不把未形成 durable Pre claim 的 task 直接绑定；
- `list_agents`、task name、时间、summary、transcript 和 child final 不能建立或修复 identity；
- native return 后、confirm 前中断时保持 `claimed/unbound`，不自动重派。

明确 failed 且可靠证明 Agent 未创建时可用 `record-dispatch-result` 关闭该 task；unknown 进入 reconcile。success 必须携带 exact target 走 confirm。

## 最小生命周期

- `record-platform-observation` 只接受已 bound 的 exact target。running/error 更新最后观察；completed/stopped/interrupted 建立 terminal fact；unknown 只写 `platform_observation_unknown` reconcile reason。
- `record-call-result` 的 success/failed 只读取并校验 exact identity，状态文件字节不变；unknown 只写 `delivery_unknown`，不保存 message、response 或调用历史。
- `record-terminal-notification` 要求 task/ref 与 exact sender 同时匹配；保存 status/time，不接收或保存正文。相同 terminal status 重放幂等，不同 status 保留首个 terminal fact 并进入 reconcile。
- `record-interrupt-result` 保存明确 failed/inactive 机械结果；inactive 建立 terminal fact，unknown 只写 `interrupt_unknown`。它不依赖 Hook settlement。
- `close-task` 是父 Agent 显式判断，不自动调用 interrupt。close 后 capability 被收缩；ledger 只保留最新 64 条 closed task，并在后续真实写操作中惰性裁剪。

allowed next action 由 phase 与上述可靠事实派生，不持久化 parent action。所有输入使用关闭字段集合，正文、summary、transcript 和 child final 不进入 lifecycle state。

## Hook 与只读恢复

Hook manifest 当前只注册：

- native spawn 的 PreToolUse matcher；unmanaged task name 在 StateStore 构造前 inert fail-open，governed spawn 验证 exact prepared facts 并原子 claim；
- best-effort read-only SessionStart，只读取当前 exact Session 的未关闭摘要。

Codex MultiAgent V2 在 Hook stdin 中使用 flattened `collaborationspawn_agent`，并在到达本地 Hook 前把 `message` 变为 opaque encrypted value。router 只显式接受 `Agent`、`spawn_agent`、`collaboration.spawn_agent` 与 `collaborationspawn_agent`；V2 claim 要求派生的 `task_name/task_ref`、`fork_turns`、`model`、`reasoning_effort` 精确匹配 prepared capability，并要求 opaque message 为非空字符串。它不回写 `updatedInput`，从而保留平台原始加密调用。V1/非 opaque 路径仍精确比较明文 message。

这建立的是父 Agent 协作协议中的 prepared-capability 引用与可见 spawn config 绑定，不是 V2 plaintext message attestation。平台未向该 Hook 暴露明文，因此插件不宣称能在 Pre 边界独立验证实际委派正文；父 Agent 仍必须把 prepare 返回的 `spawn_args` 原样提交。

不存在 PostToolUse、Stop、SessionEnd 或 communication/followup/interrupt PreToolUse。

SessionStart、`status` 和 `diagnose` 使用无锁只读 reader；缺失目录时不创建目录、lock、临时文件或空状态，不 cleanup、rebuild、migrate、reconcile、自动关闭、自动重试、扫描其他 Session 或读取业务正文。

## 安全存储边界

v9 继续复用现有安全 storage primitives：

- UTF-8 byte-bounded stdin；
- owner、permission、symlink 和 non-regular 检查；
- 稳定 lock、临时文件 fsync、原子 replace 和写后回读；
- new-task soft limit 与 hard capacity limit；
- corruption/current-format mismatch 原地保留，不自动修复。

## 当前非能力

wait 不持久化。business resume、managed followup、多 attempt、复杂 recovery/retry budget、Group、PostToolUse settlement 和自动跨 Session 恢复不属于首版。

## 文件所有权

- `schemas/governance-semantics.schema.json`：state-v9、TaskContract v2 和 phase-specific closed Schema。
- `schemas/task-contract-v2.schema.json`：TaskContract v2 模型输入 wire schema。
- `scripts/governance_contracts.py`：v2 normalization 与 business/spawn digest。
- `scripts/governance_state.py`：strict v9 runtime validator。
- `scripts/governance_state_store.py`：单 ledger 安全存储和无锁只读 reader。
- `scripts/governance_protocol.py`：prepare composition。
- `scripts/governance_dispatch.py`：claim/confirm/dispatch-result transitions。
- `scripts/governance_lifecycle.py`：observation/call/terminal/interrupt/close transitions 与 closed retention。
- `scripts/governance_diagnostics.py`：status/diagnose 的无锁只读 projection。
- `scripts/governance_hook.py`：spawn Pre 与 read-only SessionStart router。
- `scripts/governance_cli.py`：薄 CLI transport。
- `scripts/subagent_governance.py`：稳定 executable facade。

## Runtime bundle 与开发部署

`.codex-plugin/runtime-bundle.json` 是机器可检查的 runtime allowlist。运行包精确包含 Manifest、Hook、Skill/references、核心 runtime scripts、当前 Schema 与最小 README/license；tests、CI、plans、validation、`AGENTS.md`、开发依赖、release preflight 及部署工具均不进入 bundle。bundle digest 只覆盖 allowlisted path、mode 和 bytes，目标 verifier 拒绝任何额外文件或符号链接。

`scripts/dev_deploy.py` 是唯一的本机开发测试部署入口，默认严格 dry-run。经另行授权后，它从干净 exact HEAD 构造 allowlisted staging，验证 digest，原子激活 stable，调用原生 Codex 安装，并精确保留 target 与可选 previous；失败或中断 transaction 恢复部署前 stable 和完整 cache 集合。该工具不写 Marketplace 配置、Registry、Hook trust 或全局 `AGENTS.md`，也不属于 runtime bundle。

开发仓库仍是唯一修改源。安装、发布、stable source、Marketplace、Registry、runtime cache 和 Hook trust 写入需要另行明确授权。
