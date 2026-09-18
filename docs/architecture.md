# 当前架构

Subagent Governance 是 Codex 原生子 Agent 的本地生命周期治理层。它继续使用原生 Agent 工具，不替代平台调度、权限、Hook trust、沙箱或父 Agent 的业务判断。

当前开发实现沿用 [减法收口 cutover](improvement-plans/reduction-cutover.md)，并按 [GPT-6 流程精简方案](improvement-plans/gpt6-workflow-simplification-2026-09-09.md) 分离 unknown 与生命周期：state-v12 单一 Session ledger、TaskContract v2、prepare、显式冻结的 governed spawn Pre claim、父 Agent explicit exact-target confirm，以及 observation/terminal/interrupt/close 已落地。当前代码不保留旧机制作为兼容 fallback。

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

## state-v12 单一 ledger

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

`prepared/claimed` 保存规范化完整 `prepared.contract`、材料校验元数据 `prepared.context_verification` 和 `prepared.expected_native_parameters`，后者包含完整生成派发 `message`。绑定、记录派发失败或未知、进入 reconcile 或显式关闭时移除 capability。过期只阻止首次 claim，不删除 capability 或未关闭记录。

`contract_summary` 是规范化 business contract 的精确快照，保留除 spawn 外的全部字段，包括 context.summary、paths 和 verified 声明。它在 prepare 生成，跨所有 phase 保留；prepared/claimed 阶段与 capability contract 去掉 spawn 后的业务部分精确相等，所有阶段校验 business digest。绑定或失败时可删除 capability，不删除验收约定。没有另一份模型生成摘要、专门的结果正文存储或自动复制的外部材料副本。字节预算和字段语义以 governance-semantics.schema.json 为源，详见 [验收快照边界](../skills/subagent-governance/references/runtime-boundaries.md#原始验收快照与容量)。

StateStore 只接受严格 `state_format_version=12`，默认 namespace 为 `state-v12`。v11 及更早状态不读取、不迁移、不修复、不写回、不删除。

## 存储位置与输出边界

以下描述 v0.5.0 的 state-v12 实现；真实验证范围见[平台证据](validation/current-only-real-platform-validation.md)。数据根按以下优先级解析，再使用其中的 `sessions/<安全化 Session 标识>.json` 和同名 `.lock`：

1. `SUBAGENT_GOVERNANCE_DATA`：直接作为数据根，不再追加 namespace。
2. `PLUGIN_DATA/state-v12`。
3. 从安装缓存路径解析出的 `plugins/data/<plugin>-<marketplace>/state-v12`。
4. 开发或未安装模块使用系统临时目录下的 `subagent-governance-<用户键>/state-v12`。

临时目录不代表到期删除承诺。未关闭任务不因过期或容量自动清除；closed 在实际账本写操作中最多保留最新 64 条，新增任务有容量压力时可提前淘汰最旧完整记录，没有定时删除服务。移除 capability 或裁剪记录指当前账本内容更新，不代表安全擦除或清理旧格式账本。

材料校验读取声明文件，但不自动把材料正文复制进账本。后续普通消息、终态通知正文、业务结果、transcript 和 child final 不被专门归档；主动填入契约或 `close_reason` 的文字仍随字段保存，没有自动脱敏。这与主动采集完整聊天记录不同。

默认 `status/diagnose` 投影包含 `objective`、`close_reason`、身份和生命周期事实；精确任务 status 额外返回完整 `contract_summary` 和操作输入。SessionStart 只注入权威 Session/CLI 信息及有界的未关闭任务身份、阶段和下一步，不展开目标、关闭原因或完整契约。spawn Hook 故障诊断采用固定码和说明，不回显输入或异常正文；`diagnose` 则包含数据根路径，读取失败时可包含最多 600 字符的异常说明。因此轻量、有界或只读输出不等于自动脱敏。

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

- `record-platform-observation` 只接受已 bound 的 exact target。running/error 更新最后观察；completed/stopped/interrupted 建立 terminal fact；unknown 只写 `unknown_facts.platform_observation_unknown`，保持 bound，允许后续确定终态。
- 普通消息 success/failed 不要求额外 CLI；显式 `record-call-result` 仍只校验 exact identity，状态文件字节不变。unknown 只写 `unknown_facts.delivery_unknown`，保持 bound，不保存 message、response 或调用历史。
- `record-terminal-notification` 要求 task/ref 与 exact sender 同时匹配；保存 status/time，不接收或保存正文。相同 terminal status 重放幂等，不同 status 保留首个 terminal fact 并进入 reconcile。
- `record-interrupt-result` 保存明确 failed/inactive 机械结果；inactive 建立 terminal fact，unknown 只写 `unknown_facts.interrupt_unknown`，保持 bound。它不依赖 Hook settlement。
- `close-task` 是父 Agent 显式判断，不自动调用 interrupt。close 后 capability 被收缩，保留 unknown_facts、首个 reconcile 原因及既有事实；closed 不重新开启；ledger 最多保留最新 64 条 closed task，并在真实写操作中惰性裁剪。新增任务使总条数超过 512 或超过 3 MiB 准入线时，按关闭时间、创建时间、task_id 升序淘汰最旧完整 closed 记录，直到满足准入线或无 closed 可淘汰。清理与插入同事务，prepare 返回 pruned_task_ids；仍超限则拒绝且不改写原账本。

allowed next action 由 phase 与上述可靠事实派生，不持久化 parent action。所有输入使用关闭字段集合，执行结果正文、transcript 和 child final 不进入 lifecycle facts；原始 context.summary 仅作为验收契约的一部分保留。

unknown_facts 是最多三项的可选对象，键为 delivery_unknown、platform_observation_unknown、interrupt_unknown，值只含首次 observed_at。它可随 bound → terminal → closed 保留，也可保留在有绑定身份的冲突记录中；不保存调用历史，不把原回执倒改为成功。同一证据只按实际来源登记一次；独立来源有新事实时才补充。

reconcile 只用于 dispatch_result_unknown、dispatch_claim_missing、dispatch_identity_mismatch、dispatch_target_conflict、terminal_status_conflict；保留首个阻断原因，不从后续通知补绑或自动解锁。消息投递未知后，父方仍须核实结果是否满足新增要求。

## Hook 与只读恢复

Hook manifest 当前只注册：

- native spawn 的 PreToolUse matcher；unmanaged task name 在 StateStore 构造前 inert fail-open，governed spawn 验证 exact prepared facts 并原子 claim；
- read-only SessionStart 始终注入 Hook stdin 提供的当前权威 exact session ID 与当前已安装 CLI entrypoint，并 best-effort 读取当前 exact Session 的未关闭摘要。

Hook router 只接受机器语义源列出的原生 spawn 精确名称。`collaboration_turns` 通过生成的 task_name 定位；`fork_context` 通过可见消息标记定位。claim 校验 task_name、fork_turns、model、reasoning_effort 和声明材料，不逐字匹配平台可能重写的消息正文。存在可见消息标记时，它必须与 task_name 一致。未知形状或不可验证输入 fail-open，不声称校验通过；明确不一致仍拒绝。claim 区分本次未尝试、未确认、结果不确定和已确认；写入报错只有精确回读匹配时才确认。故障分类与证据边界见 [运行时契约](../skills/subagent-governance/references/runtime-boundaries.md#hook-故障分类与证据契约)。父 Agent 必须原样提交 prepare 返回的 spawn_args；插件不宣称在 Pre 边界独立证明实际委派正文。

不存在 PostToolUse、Stop、SessionEnd 或 communication/followup/interrupt PreToolUse。

SessionStart、`status` 和 `diagnose` 使用无锁只读 reader；缺失目录时不创建目录、lock、临时文件或空状态，不 cleanup、rebuild、migrate、reconcile、自动关闭、自动重试、扫描其他 Session 或读取外部材料正文。治理命令必须使用 SessionStart 注入的已安装 CLI entrypoint，确保与 Hook 解析到同一插件数据根；工作区相对脚本和其他 cache 版本都不是 authority。`<codex_delegation><source_thread_id>` 只表示来源任务，不得替代当前 Hook 的 session ID。

默认 status/diagnose 和 SessionStart 仍为轻量 projection；`--status --task-id <task_id> --task-ref <task_ref>` 在 exact Session 内精确选取单条任务，并额外返回完整 contract_summary。选择参数缺一、身份不匹配或记录已淘汰均明确失败。SessionStart 只提示按需读取，不自动注入完整契约；读取不证明交付合格，不重读 verified 材料。

status、diagnose、SessionStart 共享 projection：phase 决定 next_action，unknown_facts 单独呈现。issues=[] 只证明账本可读且结构有效。新 namespace 不恢复 state-v11 的未关闭任务；新摘要为空不能证明旧任务完成。近期真实验证及未覆盖边界见上述平台证据。

## 安全存储边界

当前版本继续复用现有安全 storage primitives：

- UTF-8 byte-bounded stdin；
- owner、permission、symlink 和 non-regular 检查；
- 稳定 lock、临时文件 fsync、原子 replace 和写后回读；
- new-task soft limit 与 hard capacity limit；
- corruption/current-format mismatch 原地保留，不自动修复。

## 当前非能力

wait 不持久化。business resume、managed followup、多 attempt、复杂 recovery/retry budget、Group、PostToolUse settlement 和自动跨 Session 恢复不属于首版。

## 文件所有权

- `schemas/governance-semantics.schema.json`：state-v12、TaskContract v2、冻结 native interface 和 phase-specific closed Schema。
- `schemas/task-contract-v2.schema.json`：TaskContract v2 模型输入 wire schema。
- `scripts/governance_contracts.py`：v2 normalization 与 business/spawn digest。
- `scripts/governance_state.py`：strict state-v12 runtime validator。
- `scripts/governance_state_store.py`：单 ledger 安全存储和无锁只读 reader。
- `scripts/governance_protocol.py`：prepare composition。
- `scripts/governance_dispatch.py`：claim/confirm/dispatch-result transitions。
- `scripts/governance_lifecycle.py`：observation/call/terminal/interrupt/close transitions 与 closed retention。
- `scripts/governance_diagnostics.py`：status/diagnose 的无锁只读 projection。
- `scripts/governance_hook.py`：spawn Pre 与 read-only SessionStart router。
- `scripts/governance_cli.py`：薄 CLI transport。
- `scripts/subagent_governance.py`：稳定 executable facade。

## Runtime bundle 与开发部署

`.codex-plugin/runtime-bundle.json` 是机器可检查的 runtime allowlist。运行包精确包含 Manifest、Hook、Skill/references、核心 runtime scripts、运行时读取的 governance semantics Schema 与 `LICENSE`；仓库 `README.md` 和对外提供的 TaskContract v2 输入 Schema 只进入源码与 release archive，不进入 runtime。tests、CI、plans、validation、`AGENTS.md`、开发依赖、release preflight 及部署工具也不进入 bundle。bundle digest 只覆盖 allowlisted path、mode 和 bytes，目标 verifier 拒绝任何额外文件或符号链接。

`scripts/dev_deploy.py` 是唯一的本机开发测试部署入口，默认严格 dry-run。经另行授权后，它从干净 exact HEAD 构造 allowlisted staging，验证 digest，原子激活 stable，调用原生 Codex 安装，并精确保留 target 与可选 previous；失败或中断 transaction 恢复部署前 stable 和完整 cache 集合。该工具不写 Marketplace 配置、Registry、Hook trust 或全局 `AGENTS.md`，也不属于 runtime bundle。

开发仓库仍是唯一修改源。安装、发布、stable source、Marketplace、Registry、runtime cache 和 Hook trust 写入需要另行明确授权。
