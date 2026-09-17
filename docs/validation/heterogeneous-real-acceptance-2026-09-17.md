# 异构模型独立真实验收（2026-09-17）

状态：本批三个真实场景与 compact 恢复验收通过，三条治理记录均已关闭。用途是运行与协作验收，不是成本收益实验；下表明确标注的未测门槛不在通过声明内。

## 授权、环境与精确身份

公开归档时将用户目录统一写为 `~`、系统临时目录写为 `<system-temp>`；文件名、证据编号、哈希及事件位置保留原值。

本任务由已确认部署、重启和独立真实验收的交接创建。只写本报告和隔离临时测试材料，没有修改运行时代码、安装目录、信任配置、Registry、Marketplace 或旧版账本，没有提交、合并、推送或再次部署。

- 当前 exact Session（来自本任务 SessionStart）：`01a0af04-34fd-70d1-a36e-637da926e788`。
- 当前权威 CLI：`~/.codex/plugins/cache/personal/subagent-governance/0.5.0/scripts/subagent_governance.py`。所有本次治理命令均使用该入口和上述 Session。
- 来源任务 `01a0ae25-5f1d-7c62-838f-e40ffcfbe9d8` 仅为交接来源，未用作治理身份。
- 开发源：`~/workspace/subagent-governance`。
- 本独立工作树：`~/.codex/worktrees/d038/subagent-governance`。
- 两者实际 HEAD 均为 `c968fb1382a862b11b62f181f7c6991195abd959`，检查时均干净。
- 稳定源：`~/plugins/subagent-governance`。
- 当前缓存：`~/.codex/plugins/cache/personal/subagent-governance/0.5.0`。
- 四处 runtime digest 均实测为 `69bd26d958d26bcb74fd5db4f795019eeb78f4ee39b6de80724dc1ef3a15adae`。开发源与工作树使用 `bundle_digest`，稳定源和缓存使用 `verify_runtime_bundle` 检查精确 allowlist 文件集合。通过 `python3 -B` 导入开发工具，未向 runtime 写 bytecode。
- 四个根目录均不是符号链接，开发源与稳定源实际路径不同。安装版为本机 `main@c968fb1` 构建的 `0.5.0`，不等同公开 `v0.5.0` 标签内容。
- 交接称保留上一缓存 `0.4.0+codex.20260917010311`；本批未访问或验证其逻辑、文件或账本。
- Codex 实际父任务 rollout 元数据：`cli_version=0.155.0-alpha.2.6`、`source=vscode`、`model_provider=custom`。

## 加载、信任与配置证据

实际读取安装缓存的 Skill，并读取工作树 AGENTS.md、release-process 真实平台验证条款和异构方案。SessionStart 注入了上述权威身份；初始 exact-session status 返回 state-v12、tasks=[]，不据此推断旧版任务已经完成。

`codex plugin list` 显示 `subagent-governance@personal` installed/enabled、版本 0.5.0、稳定源路径匹配。另起本地 app-server，只执行 initialize 和只读 hooks/list（指定本工作树 cwd），返回本插件两个 handler，sourcePath 均为当前缓存 hooks/hooks.json：

| Hook | enabled | trustStatus | currentHash |
| --- | --- | --- | --- |
| PreToolUse | true | trusted | `sha256:e9ec71bb3c0ccb81dbb1d0ef0eb80bbf6f99ca1df880dc56909fa6b98bf14010` |
| SessionStart | true | trusted | `sha256:26915f4009c66b621d5a67739e8b7300d3bd462017bd31b72411317cf638cf45` |

配置中相应 trusted_hash 与平台返回一致。注册可见性、独立 trust 回读与本任务真实 Hook 效果分别记录；没有把 installed/enabled 当作 trusted。Codex Manager Registry 独立存储及桌面 UI 未验证、未修改。

父任务和三次子任务均通过实际 rollout `turn_context`（各第 8 行）读取 model/effort，未只凭派发参数或子任务自报认定生效。元数据表示 Codex 记录的实际运行配置，不是对 custom provider 后端物理模型的独立鉴证。

| 执行者 | 实际 model / effort | rollout 文件（均在 ~/.codex/sessions/2026/09/17/） |
| --- | --- | --- |
| 父任务 | gpt-6-astra / high | `rollout-2026-09-17T03-58-03-01a0af04-34fd-70d1-a36e-637da926e788.jsonl` |
| standard | gpt-5.6-terra / high | `rollout-2026-09-17T04-00-29-01a0af06-6d48-77f0-a24e-b3c5d2df4840.jsonl` |
| strict | gpt-5.6-terra / high | `rollout-2026-09-17T04-02-21-01a0af08-2350-72e2-a10c-89c539781333.jsonl` |
| 模拟缺陷传递 | gpt-5.6-terra / high | `rollout-2026-09-17T04-03-36-01a0af09-477c-7dc2-a462-653543d4b7c6.jsonl` |

子任务 session_meta.source.subagent.thread_spawn 的 parent_thread_id 和 agent_path 分别匹配当前父任务与已经由原生 spawn 返回绑定的 target；只用于配置证据关联，没有从 rollout 反推治理 target。三次均显式 `fork_turns=none`，prepare/Pre claim 接受该配置。子任务初始记录为环境/规范、turn_context、NEW_TASK，没有父任务先前业务工具历史；共同环境规范仍可见。运行元数据没有独立的 resolved fork_turns 字段，因此隔离的证据边界是请求、成功 claim 与可观察的初始上下文，不声称底层所有上下文均已审计。父任务由独立新任务创建，未通过原生子 Agent fork 继承来源任务。

## 隔离材料与原生身份链

临时根：`<system-temp>/sg-acceptance-20260917-ei9jipu2`。standard、strict、takeover 各有独立目录。临时材料无凭据；未保存完整聊天。治理参数 operation_inputs 仅在父上下文即时复用，未另存持久参数记录。

| 场景 | task_id | task_ref | 同次 spawn 原生返回 task_name = confirm target |
| --- | --- | --- | --- |
| standard | `sg-ab4b694973a91e895f1e70d95a65eeb5` | `43c9b3893158` | `/root/sg_standard_task_t_43c9b3893158` |
| strict | `sg-16eef60708490f2ed26ee00ad9cd005a` | `41b5ae6bc13d` | `/root/sg_strict_task_t_41b5ae6bc13d` |
| 模拟缺陷 | `sg-0bda8981b96bef438afd2d82f995ba03` | `3301027651e4` | `/root/sg_standard_fixture_t_3301027651e4` |

三次原生返回均为单字段 JSON：`{"task_name":"<表中完整路径>"}`。输入为生成器返回的短 task_name，确认使用返回的完整路径，未拼接、截断或从候选对象推断。当前可见工具契约为 collaboration_turns；没有给测试者额外指定应选择哪个字段。prepare 的 spawn_args 原样传入原生 spawn；confirm 即时复用 prepare.operation_inputs，仅补原生 target；三次均返回 bound。按运行时契约，缺 Pre claim 不能得到 bound，因此真实 claim→confirm 链路成立。未手工执行 Hook 或伪造 tool_use_id。

## 已执行场景

### 1. standard 正常只读交付：通过并关闭

材料含 paid A=1200、cancelled B=800、paid C=350、paid D=0。子任务用 jq 实际读取筛选，原生 FINAL_ANSWER 报 completed、IDs A/C/D、数量 3、总额 1550 cents。父任务另用 Python 读取原材料重算并断言 ID、数量和整数总额一致。

父方按 exact sender 登记一次 record-terminal-notification，使用返回 operation_inputs 补理由关闭；结果 closed。没有把子任务声称完成直接当作业务验收通过。

### 2. strict 声明材料、消息与交付：通过，compact 恢复后关闭

prepare 对 declared working_tree 材料 stock.json 校验通过，SHA-256 为 `31636fdbb65155d9acb416d806588a9226bd86796ac19b8512e73bfd5a1ddb56`；原生 Pre claim 后 confirm 返回 bound。目标文件 availability.json 初始不存在。

父任务实际收到了以下原生 MESSAGE，均关联已绑定 exact sender，未把 child commentary 算作送达：

1. 子任务现场生成 challenge `4939c5bb301e4364a7ed8bbca1781ebb`，随消息发来 3 条库存材料摘要及 SHA-256。
2. 父任务在收到 challenge 后，通过原生 send_message 给 exact target 回复并修订输出根结构。
3. 子任务原生回传同一 challenge 和其实际收到的完整修订要点，随后生成产物。
4. 子任务发送明确 completed 通知，随后 FINAL_ANSWER 交付。父方只登记一次终态，未因重复 final 再登记一次。

父任务用独立 Python 读取输入重算，确认 items 为 book=8、pen=0、ruler=5，total_available=13，receipt 与现场 challenge 一致，输入 SHA-256 未变。

**有效后续修订（恢复用父任务摘要，来源为上述父→子 send_message 及子→父回传）**：availability.json 顶层由原契约的数组改为对象，包含 `items`（原条目数组）、`total_available`（整数求和）、`receipt`（上述 challenge）。此修订取代原根数组格式，其他原始规则与禁止范围保持。消息修订不自动进入 contract_summary。

compact 前精确 status 回读确认 contract_summary 仍保留原始根数组要求，完整 context.verified、completion、evidence、forbidden_scope 仍在；这次读取本身不算恢复。真实 compact 后又按权威 Session 恢复映射和原始契约，独立恢复消息修订并复验，最终关闭；具体证据见下文。

### 3. 模拟缺陷的终态后父方接管：通过并关闭

TEST-FIXTURE.md 提前明确这是人为模拟缺陷，业务要求 subtotal_cents=sum(cents*qty)，保留 label。子任务仅承担原样传递，不承担修复。输入为 125×3 与 40×2，预置 artifact 的 subtotal_cents=165。

子任务将 artifact.json 原样复制为 delivery.json，SHA-256 均为 `043732f338a2c39e47d7d2b9c0a7bf5d32e9ed6a0dab16154d53e737f5811835`，cmp 检查一致，发来原生 completed 通知并明确停止所有写入，随后 FINAL_ANSWER 到达。父任务登记 terminal 后，先收到实际 final，再接管同一临时产物；未把 close 当成停止证明。

父方独立初验确认 `165 != 455`，明确业务产物不合格，复制执行完成与业务合格分开。局部缺陷及规则已确定，父方直接将 delivery.json 总额修为 455，保留 label=simulated-defect，复验通过。修后 SHA-256 为 `8468f271096bdde4e6a444f6903d90a2426c4309dfc141982b4e141217a0b9c3`。原 artifact 保持 165，便于复核。最后按实际原因 close，结果 closed。

没有恢复旧生命周期、删除 terminal_fact、followup 或替换派发。本场景验证接管路径可执行，不证明模型自然犯错，不证明纠偏或成本收益。

## 等待、状态与覆盖边界

本批只派发三次有界任务。父任务两次调用 wait_agent(timeout_ms=60000)，均被实际消息唤醒。另在子任务执行期间完成互不依赖的 Hook 检查或测试准备；没有轮询代码、日志、产物或 agent list 猜进度。配置元数据用于独立核实配置，不作为进度信号。所有执行都在静默 5 分钟前完成，没有触发超时巡检。

| 门槛 | 本批结论 | 证据或限制 |
| --- | --- | --- |
| exact-session SessionStart/status | 通过 | 实际注入、初始空状态、后续 exact status |
| standard/strict prepare→Pre claim→spawn→confirm | 通过 | 两种等级真实 bound、完整路径一致；strict 声明材料通过 |
| 原生 wait | 通过 | 两次真实消息唤醒 |
| normal message success | 通过 | challenge 往返、变更回传及产物 receipt；无需额外消息记账 |
| failed message | 未验证 | 本批未发生 |
| 一条明确终态一次登记 | 通过 | 三次均只用 terminal notification 入口一次；后续重复 final 未重复登记 |
| parent close | 通过 | 三条记录均 closed；strict 在真实 compact 恢复验收后关闭 |
| exact target 平台 observation / 静默巡检 | 未验证 | 无静默到期，无需 list_agents；未将 wait 摘要当状态 |
| unmanaged fail-open 零状态 | 未验证 | 本批未增加 unmanaged 派发 |
| 实际 unknown 后补记确定状态 | 未验证 | 没有真实 unknown；未制造或伪造 |
| minimal interrupt | 未验证 | 子任务正常结束，无需中断 |
| restart 恢复 | 未验证 | 用户交接确认部署后已重启，只证明测试前提；本批未测试带任务的 restart 恢复 |
| 真实 compact 恢复 | 通过 | 本任务 rollout 第 261 行实际 compacted 事件；恢复原始契约、独立消息修订并完成复验关闭 |
| fork_context / 嵌套身份 | 未验证 | 当前只测 collaboration_turns 的一层路径 |
| F 的 S/N/G 与收益 | 未执行 | 未选正式样本，不推断成本、返工或收益 |

没有发现本批受测链路的运行时故障；本批验收已完成，不等于未测发布门槛通过，也不表示整个异构协作计划或收益实验已完成。

## compact 前最小交接（历史记录）

1. 用户在**当前任务**触发一次真实 compact，之后只需发送“继续验收”，不要在新提示重复业务约束。
2. 恢复后的父任务先核对新的 SessionStart 权威值；用该入口和 exact session 的轻量 status 恢复映射，再从状态取得 task_id/task_ref 读取 strict 原始完整契约。身份不匹配则停止依赖动作，不跨 Session 查找或猜测。
3. 核对实际 compact 事件证据，再依据原始契约逐项检查目标、scope、completion、evidence、forbidden_scope、context，另从本报告的有效后续修订摘要恢复变更及其来源。不要把本报告的结果数字或重新读取 JSON 冒充契约恢复。
4. 完成恢复后的证据核对，复用精确 status 返回的 close operation_inputs，按实际判断补 reason 并关闭 strict；不重新激活已经 terminal 的子 Agent。
5. 更新本报告的恢复结果、事件位置和最终治理状态，运行报告检查；无授权不提交/合并/推送。

交接时没有未结束的子执行；strict 是终态待父方关闭。计时恢复不适用，不需盲等。未将 operation_inputs 持久化，恢复时重新读取准确阶段。

## 真实 compact 后恢复与最终关闭

用户续接仅发送“继续验收”，没有重新提供库存业务约束。父任务实际 rollout `rollout-2026-09-17T03-58-03-01a0af04-34fd-70d1-a36e-637da926e788.jsonl` 第 261 行记录 `type=compacted`，时间为 `2026-09-17T11:11:02.761Z`，payload 含 message、replacement_history、retained_context 等字段。本报告只记录事件位置和元数据，不复制完整压缩上下文；事件证明发生真实压缩，不据其推断具体 UI 触发方式。恢复后第 272 行 turn_context（`2026-09-17T11:11:02.805Z`）仍为 `gpt-6-astra/high`。

恢复时新的 Hook 注入仍给出同一权威 CLI 和 exact Session。先执行轻量 status，从返回映射取得 strict task_id/ref，再执行精确 status。结果为 terminal/completed、next_action=parent_close、unknown_facts={}，原生 target 保持不变。没有从来源任务、摘要或 rollout 猜测身份，没有新增派发。

| 原始契约字段 | 恢复后的核对 |
| --- | --- |
| objective / profile | 生成库存可用量报告并完成父子消息往返；strict |
| scope | 只读 strict/stock.json，只写 strict/availability.json；available=qty-reserved，按 sku 升序 |
| forbidden_scope | 不改输入、代码、安装或账本，不再委派；收到真实回复前不结束、不预置回复，commentary 不算送达 |
| completion | 全部 SKU、整数计算、条目字段仅 sku/available；随机 challenge→父方回复→原生回传；final 明确 completed 并含命令、路径、往返与剩余事项 |
| evidence | 输出与独立计算；父方实际可见原生消息、回复和 final；沿用已验收的原生通知证据，不重新登记终态 |
| context | 原背景说明完整；verified 为 declared/working_tree，revision=null，required_paths 为 stock.json:file，workspace_root 为原 strict 临时目录 |

原始快照仍要求根数组，没有自动混入后续修订。有效对象结构、total_available 和 receipt 要求从本报告的父任务消息摘要单独恢复；摘要明确指向此前真实父→子修订和子→父回传。两类来源分别核对后，以实际修订替换根数组要求，保留其余原约束。

恢复后独立 Python 从原输入重新计算并断言完整对象相等：book=8、pen=0、ruler=5，整数总额 13，receipt 为 `4939c5bb301e4364a7ed8bbca1781ebb`；输入 SHA-256 仍为 `31636fdbb65155d9acb416d806588a9226bd86796ac19b8512e73bfd5a1ddb56`。strict 目录仅包含输入和输出两文件。该复验结合原契约、消息证据和实际 compact 事件成立，未将单纯重读 JSON 当成恢复。

使用本次精确 status 新返回的 close operation_inputs，仅补实际验收 reason，close 返回 closed、operation_inputs={}。子执行此前已终态，本次没有 wait、followup、send_message 或重新激活。最终 exact-session status 核对三条记录全部 closed、next_action=none、terminal_status=completed、unknown_facts={}；platform_status 均为 null，未冒充取得独立平台观察。

## 本批实际检查

- 四处 runtime 摘要及两处精确安装投影；工作树/源 HEAD 与初始状态；插件注册可见性及 hooks/list 只读核对。
- 父子实际 model/effort 元数据；三条真实身份链；两次原生等待；strict 真实消息往返；三次真实终态登记。
- standard 和 strict 父方独立计算，strict 输入哈希；模拟缺陷初验与父方接管后断言。
- 真实 compact 事件、恢复后的父模型配置；strict 原始契约与独立消息修订恢复、产物复验及最终三条关闭状态。
- 报告检查：见本次工具结果，`git diff --check` 及 Markdown 表格/必要章节/证据引用结构检查。
- 交接中的历史 236 项全量测试、31 项文档相关检查仅为历史证据；本批没有重跑，不写成此次实测。未修改 runtime，因此没有为本报告重复全量 unittest 或 compileall。
