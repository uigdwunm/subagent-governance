---
name: subagent-governance
description: 治理 Codex 原生子 Agent 的派发、等待、通信、中断与验收。准备调用 spawn_agent、wait_agent、send_message、list_agents 或 interrupt_agent，或协调并发 Agent 时使用；普通任务不使用。
---

# 子 Agent 治理

Codex 原生 Agent 工具是唯一执行通道。本 Skill 明确任务契约、绑定 exact target、登记必要事实并支持父任务验收；不替代平台权限、安全边界或业务判断。普通任务不加载，也不只因可拆分就创建子 Agent。不修改或要求其他 Skill 采用本协议。

## 权威身份与边界

- exact Session 只取自本任务收到的 SessionStart 或 SubagentStart Hook 注入的 `当前 Hook 权威 exact session_id（JSON）`，所有治理命令的 `--session` 逐字使用该值。
- CLI 只取自同次注入的 `当前 Hook 权威 governance CLI entrypoint（JSON）`；解码后的路径作为 Python 的单个脚本参数。不得改用工作区相对脚本、其他 cache 版本或猜测安装路径。
- `<codex_delegation><source_thread_id>` 是来源任务，不是当前 Session；父任务 ID、任务列表等也不能替代。任一权威值缺失时，在 prepare/spawn 前停止并报告，不猜测或跨 Session 扫描。
- target 只由父任务依据本次原生 spawn 的机械返回显式绑定；不从调用前的短 task_name、`list_agents`、时间、summary、transcript、child final 或唯一候选推断 identity；原生返回的完整 canonical task_name 属于返回身份，不在此禁用范围。
- 治理异常只停止依赖缺失身份或冲突事实的操作；继续其他已授权工作，不用重复 spawn 绕过。每次真正 spawn 都是独立生命周期。

子 Agent Hook 的 `session_id` 使用父会话 ID；可信来源是本任务实际收到的启动 Hook，不是父任务手工传值。`agent_id/thread_id` 不替代 Session 或本次原生 spawn 回执。共享 Session 账本不提供派发者级访问隔离；只治理本任务获授权派发并取得精确回执的子任务，或明确交接且身份与契约齐全的任务，不因账本可见而接管父级或兄弟任务。SubagentStart 不读取或注入共享任务摘要。

## 编写任务契约

派发前先解决会改变实现方向的关键歧义，按任务判断难度、执行者能力及交接/验收成本决定是否委派，不只看代码量或模型价格。父任务负责关键判断、治理与验收，子任务负责有界执行和证据；调查未决设计时应明确调查目标。使用现有字段交接具体依据，不增加每步审批。

TaskContract v2 的最小完整示例：

```json
{
  "objective": "唯一当前目标",
  "scope": ["允许处理的范围"],
  "completion": ["可验证完成条件"],
  "context": {"summary": "足够独立执行的必要背景"},
  "spawn": {"fork_turns": "none"}
}
```

- objective、非空 scope、非空 completion 必填。可选字段为 profile、forbidden_scope、evidence、context、spawn；默认 standard、空数组/背景、fork_turns=none。profile 仅 standard/strict；strict 额外要求非空 forbidden_scope 和 evidence，详见 [profile](references/governance-profiles.md)。不使用 auto/light/task_features/attempt，不手写 task name/ref，标识由生成器派生。
- 模型选择服从用户授权和实际工具说明，不自动选择最低价模型。需要不同子模型时显式配置；collaboration_turns 的 fork_turns=all 不允许模型/推理覆盖，改用允许的隔离或有限继承并补足背景，不偷偷删除覆盖。spawn 可提供 model、reasoning_effort。fork_turns 为 none/all 或 1–12 位正整数字符串；先核对可见原生工具说明，再选择 collaboration_turns 或 fork_context，不猜测或混用接口。
- 用现有字段说明已定设计、自主范围、约束和验证证据；影响执行的边界写进契约，不仅留在父任务历史。边界明确则直接完成实现、验证和本次问题修复；重大设计未决或需改变既定接口、数据库、鉴权、架构边界等才尽早对齐，跨文件本身不触发审批。
- 普通方案沟通是进度消息；确实无法继续交付、需交还决定时才报告终态，不新增审批阶段或终态后恢复。父任务在已有授权内决定，越界或需用户选择才升级；结构校验不证明交付质量。并行写入需明确修改归属、共享接口、集成责任和必要顺序；父任务验收组合结果。复杂交接按需读 [任务交接示例](references/task-handoff.md)，不复制另一套示例。
- context.paths 只是定位提示，仅填写规范 POSIX 相对路径，如 `skills/example/SKILL.md`；不填绝对路径、反斜杠或含 `.`、`..`、空路径段的值。需要交接绝对位置或不同工作区的文件时，将完整路径及用途写入 context.summary，可省略 context.paths；相对路径的基准目录不明确时也在 summary 中说明。需机械校验材料才显式填写 context.verified，prepare 和 Pre claim 各验证一次。strict 也不自动扫描，材料校验不提供工作区隔离。声明格式与容量见 [runtime boundaries](references/runtime-boundaries.md)。
- 除 spawn 外的规范化契约保存为原始验收快照 contract_summary，最多 65,536 UTF-8 字节（含紧凑 JSON 开销），超限拒绝、不截断。只写必要约定，不放凭据、完整聊天、日志或业务结果。

## 派发与参数复用

1. 通过标准输入传入契约：

   ```bash
   python3 "<authoritative-cli-entrypoint>" --prepare-dispatch --native-interface <collaboration_turns|fork_context> --session <exact-session-id>
   ```

2. 完成派发前置核对后再 prepare，避免让准备凭据在其他长耗时工作中闲置。用一句话说明派发理由；本次启动披露应涵盖目标、范围、可验收的完成条件、模型、推理强度、上下文方式和治理等级。
   若上层流程的同次启动披露已覆盖这些信息，只补缺项，不逐字重述 user_message；没有上层披露时，以 user_message 为主体，另补派发理由。上层要求固定披露区块为最后一条用户可见消息时，补充项放在该区块之前。
   使用返回的 expires_at（Unix 秒）判断准备记录是否仍可首次派发；常规披露无需展示该内部时间戳。未覆盖模型/推理参数按原生配置解析，不冒充已核实配置。把 spawn_args 原样交给当前原生 spawn_agent。collaboration_turns 使用 message/task_name/fork_turns；fork_context 使用 message/fork_context。生成标记与 task name 保持一致。若发起调用前已知准备过期，先走下文的过期处置，不调用旧 spawn_args。
3. 按当前可见工具契约读取同一次原生返回：collaboration_turns 使用返回的完整 canonical `task_name`（如 `/root/parent/child`）；fork_context 仅在该接口确实返回 `agent_id` 时使用该值。身份原样传递，不用调用前的短名称拼接路径，也不截取末段。取 prepare 返回的 `operation_inputs["--confirm-dispatch"]`，仅补入该 target，立即用权威 CLI 的 `--confirm-dispatch --session <exact-session-id>` 提交 JSON stdin。返回缺少可寻址身份、字段类型不符、仅有无法确认的短名称或候选身份冲突时，停止绑定和依赖操作并报告，不补猜身份、不盲选字段。返回样例与 confirm 输入见 [身份契约样例](references/runtime-boundaries.md#原生返回身份契约样例)。
4. 首次确认建立 bound，保存 task/ref/target 映射。相同确认幂等，冲突保留首个绑定并 reconcile，不重派。Pre claim 的接口匹配和 fail-open 边界见 [runtime boundaries](references/runtime-boundaries.md)；派发失败、未知或缺少 claim 时走文末异常路由。

`operation_inputs` 的键是现有 CLI 命令，值是已填身份的 JSON stdin。prepare 提供 confirm 输入；confirm、平台观察和终态通知按实际阶段返回后续输入，精确 status 详情可按需恢复。prepared/claimed 的 confirm 输入不证明原生派发成功；bound 提供两种证据登记和 close；terminal/reconcile 仅提供 close；closed 为空。

复用值后补实际 target/status/reason，不把整个返回对象提交。参数只是便利数据：sender/target 是预期绑定身份，不证明通知归属或平台状态；close 输入不代表验收通过或应当关闭。仍核对证据，选择一个操作，使用当前权威 CLI 和 Session。过期输入仍受现有身份/阶段校验，不自动执行、不持久化、不另建身份记录。

## 等待与通信

- bind 后用原生 wait_agent 等待，单次 timeout_ms ≤ 60000。它只唤醒邮箱；超时、摘要或用户新输入不建立 Agent 状态，也无需记账。每次返回先处理消息；明确终态登记后进入验收，证据不足就报告，不为同一次执行再等一份终态。
- 在父任务上下文按 target 保留最后消息时间（尚无消息从 bind 起算）和最近核对时间。按实际时间，连续静默 5 分钟才用 list_agents 核对已绑定 exact target；后续核对不早于这两个时间较晚者之后 5 分钟。其他 target 的消息、用户输入、wait 返回不重置计时；每次唤醒仍检查所有等待 target 的核对时点。不轮询代码、日志或每次超时查询列表。

| exact target 核对结果 | 处置 |
| --- | --- |
| completed/stopped/interrupted | 登记平台终态并退出等待，按交付证据验收；缺证据不等于仍在运行 |
| running | 登记观察并继续等待；静默不判失败，不自动催促、中断、重派或重复播报相同状态 |
| error | 登记并报告具体错误，停止该 target 自动等待；error 不冒充 terminal |
| 不可见、工具不可用/报错、状态不识别 | 报告无法确认，停止自动等待和定时查询；能归属 target 的未知观察记 unknown，仅新相关证据或用户明确要求才重查 |

- 静默只触发核对，不限制总时长或修改 phase；停止等待不自动 close/interrupt，继续其他不依赖它的工作。恢复时丢失计时先按 [恢复步骤](references/recovery.md#恢复后等待时间丢失) 核对，不重新盲等；计时不写账本。
- 普通原生消息直接使用已保存 target；映射存疑先读 exact-session status，不每次发送前固定检查。success/failed 无需额外治理调用；unknown 必须登记且不自动重发，见 [未知回执](references/recovery.md#未知消息或观察)。
- 原范围后续工作使用同一 target 的 followup_task，不建立新 identity/attempt；终态后不受管恢复。

## 终态、验收与关闭

按实际来源选一个登记入口，复用对应 operation_inputs 并补一个 status：

| 证据 | 命令 | status |
| --- | --- | --- |
| 可归属已绑定 exact sender 的原生 child terminal notification | --record-terminal-notification | completed/stopped/interrupted |
| 已绑定 exact target 的平台观察 | --record-platform-observation | running/completed/stopped/interrupted/error/unknown |

不提交正文，不把 wait 摘要猜成平台状态，不为同一通知登记两种来源。独立来源确有新事实可补充；相同终态幂等，矛盾事实保留首个事实并 reconcile。

父任务按原始完成条件和后续实际约定验收，或明确决定停止跟踪后，使用 --close-task 的输入补 reason。终态事实与关闭决定分开提交；completed 不代表业务验收通过，close 不表示业务成功或资源释放。相同 reason 幂等，不同 reason 不覆盖，closed 不重开。中断回执按 [中断规则](references/recovery.md#中断回执) 处理。

验收不合格时，依据失败产物区分缺背景、局部错误和能力不匹配，按 [质量纠偏与接管](references/task-handoff.md#质量纠偏与接管) 处置。bound 下可有据纠偏；终态如实登记且不受管恢复，父任务可接管或明确收尾后安排独立修复任务。平台 unknown 不构成自动重派理由。

## 只读恢复

上下文恢复先用 `--status --session <exact-session-id>` 恢复映射；需原始验收约定或后续输入时，再读精确任务详情：

```bash
python3 "<authoritative-cli-entrypoint>" --status --session <exact-session-id> --task-id <task_id> --task-ref <task_ref>
```

task_id/task_ref 必须成对且来自该 Session，不存在或不匹配即报错，不换身份试探。详情返回 contract_summary 和 operation_inputs；按目标、范围、禁止范围、completion、evidence 和完整 context 核对交付。evidence 是原始要求，不是已通过的检查；后续消息改变的要求不自动进入快照，父任务在自身交接摘要中保留有效约定及来源；恢复时缺失则说明证据不足，不能把原快照当作全部最新要求。

prepare 返回 expires_at（Unix 秒）；prepared 视图还显示 expires_at 和 expired，以本次观察时间大于或等于 expires_at 为过期。expired=true 时 next_action 为 parent_review_expired_preparation：停止依赖旧 capability 的首次派发，按 [过期准备](references/recovery.md#过期准备) 核对实际回执和身份事实。仅过期或 Hook 拒绝不证明原生 Agent 未创建，不自动关闭、重新 prepare 或重派。未过期提示仅反映观察时点，不保证随后 claim 成功。claimed 已消费 capability，不适用此过期提示，仍按既有精确 confirm 和同一 tool_use_id 幂等规则处理。operation_inputs 保持身份部分输入语义，不代表执行许可；过期不作为 diagnose.issues 中的账本错误。

status/diagnose/SessionStart 保持无锁、零写、best-effort，不创建目录或空状态、不自动操作、不跨 Session 扫描。默认视图不展开快照或 operation_inputs，也不读取材料正文。路径声明不保证材料仍可恢复；closed 按现有策略淘汰后快照不可恢复。不因详情失败自动重派、验收或关闭。state-v12 不读取、迁移或清理旧格式；空账本不证明旧任务完成，diagnose.issues=[] 仅证明账本可读且结构有效。

## 按证据读取异常步骤

| 触发证据 | 参考 |
| --- | --- |
| Hook fail-open、claim 未确认或提交结果不确定 | [治理降级](references/recovery.md#治理降级) |
| prepare 已过期或收到 preparation_expired | [过期准备](references/recovery.md#过期准备) |
| spawn failed/unknown、缺少 claim、未绑定 target | [派发回执与缺失绑定](references/recovery.md#派发回执与缺失绑定) |
| 消息、中断或平台观察 unknown | [未知消息或观察](references/recovery.md#未知消息或观察) |
| 已调用原生中断 | [中断回执](references/recovery.md#中断回执) |
| 恢复后丢失等待时间 | [恢复后等待时间丢失](references/recovery.md#恢复后等待时间丢失) |
| 身份或终态冲突、需停止跟踪 | [矛盾事实与停止跟踪](references/recovery.md#矛盾事实与停止跟踪) |

unknown 不自动重发或倒改成功，reconcile 不自动解锁。参数生成不改变这些边界。
