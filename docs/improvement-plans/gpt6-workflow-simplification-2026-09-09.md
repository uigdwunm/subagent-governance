# GPT-6 使用基线下的治理流程精简方案

> 后续定位（2026-09-17）：本文保留当时实施与验收事实。当前分工及评测采用[异构模型协作方案](heterogeneous-model-collaboration-2026-09-17.md)，不再将 GPT-6 父子同模型视为主要场景；流程精简不等于削减子任务必要交接。历史模型记录不改写。


- 日期：2026-09-09
- 状态：开发仓库实施完成；117 项测试及功能／契约门禁通过，lint 保留 3 项基线问题；未部署或真实验证。见[本地验收](../validation/current-only-local-acceptance.md)
- 审查基线：开发仓库 `468dc95`，TaskContract v2 / state-v10
- 范围：异常事实与生命周期分离、减少重复记账、精简提示、更新真实测试基线

## 1. 目标与依据

让父 Agent 用更少的步骤完成正常协作，并在调用回执未知后继续接纳同一已绑定 Agent 的确定事实。精确身份、业务验收和异常证据保持可验证。

现有代码和真实证据：

| 当前行为 | 影响 | 依据 |
| --- | --- | --- |
| 任一已绑定调用的 unknown 进入 reconcile；此后平台观察和终态通知直接返回 reconcile | 后续确定状态不能推动收尾 | [lifecycle](../../scripts/governance_lifecycle.py)，[9 月 9 日真实验收](../validation/state-v10-hook-trust-2026-09-09.md) |
| close 不保留 reconcile 原因 | 关闭后的摘要不能还原未确定的调用边界 | 同上 |
| 普通消息 success/failed 仍要求额外 CLI 调用，但只检查身份、零持久化 | 每次消息增加固定步骤，事后校验不能阻止先前误发 | [Skill](../../skills/subagent-governance/SKILL.md)，[lifecycle](../../scripts/governance_lifecycle.py) |
| 同一完成通知可能先登记平台观察，再登记终态通知 | 第二次登记只返回 already_terminal | [9 月 9 日真实验收](../validation/state-v10-hook-trust-2026-09-09.md) |
| 派发模板固定输出空区块和内部状态机说明 | 用户和子 Agent 都承担与当前任务无关的信息 | [生成器](../../scripts/governance_dispatch_rendering.py) |
| 真实测试固定为 gpt-5.6-terra/high | 未覆盖现在主要使用的 GPT-6 行为 | [AGENTS.md](../../AGENTS.md)，[验收配置](../validation/state-v10-hook-trust-2026-09-09.md) |

已在本任务查阅的 [OpenAI GPT-6 Astra 官方指导](https://developers.openai.com/api/docs/guides/latest-model)指出：模型对 Skill 和 AGENTS.md 指令更敏感，模糊规则可能造成提前停止，测试也可能超出小改动需要。因此优先澄清指令与缩短正常路径；不能据此推断身份绑定、Hook 可见性或消息回执问题已由模型解决。

本方案不承诺耗时或 token 降幅。步骤减少可由调用轨迹核对，效果须由实施后的同类任务验证。

## 2. 保留边界与不做事项

- 保留原生 spawn_agent 为唯一派发通道，以及 prepare → claim → exact-target confirm。
- 保留同一次 SessionStart 注入的 exact session/CLI 权威、first-bind-wins、幂等性和输入校验；task_name 只定位 prepared task，不能建立原生 target 身份。
- 保留现有原生参数适配器与 claim 边界；不重新引入 message 全文跨阶段匹配要求。最新基线见 [task_name claim 修复](task-name-claim-fix-2026-09-07.md)。
- 保留显式材料验证、文件锁、原子写入、只读诊断、unmanaged fail-open 和 closed 记录 64 条上限。
- 保留父 Agent 验收与显式 close；close 只表示停止跟踪，不证明业务成功或资源释放。
- TaskContract v2、standard/strict、上下文继承策略和模型参数入口保持不变；不增加自动模型路由。
- 不增加 Group、attempt、消息历史、自动重发、自动跨 Session 恢复、PostToolUse 权威或新编排层；不修改第三方 Skill。

## 3. 状态决策：unknown 记录为事实，不一律冻结生命周期

### 3.1 最小记录结构

沿用六个 phase。对已经 bound 且身份无冲突的任务，把下列 unknown 从 reconcile 原因改为可选 `unknown_facts` 对象：

```json
{
  "unknown_facts": {
    "interrupt_unknown": {"observed_at": 123}
  }
}
```

键只允许 `delivery_unknown`、`platform_observation_unknown`、`interrupt_unknown`，最多三项。值只含首次记录的时间；同类重放不改时间、不写新记录。不存在 unknown 时省略整个字段，不存空对象、正文、调用 ID 或操作历史。

它表示“曾收到这种不可判定结果”，不表示 Agent 当前必然未知，也不声称保存了每次调用。后续确定观察不删除该事实、不倒改原调用成功。该对象可以存在于 bound、terminal、带已绑定身份的 reconcile，以及其 closed 记录中；没有 target/bound_at 的记录不得携带它。

`reconcile` 专用于不能按普通生命周期继续处理的派发不确定或事实冲突：`dispatch_result_unknown`、`dispatch_claim_missing`、`dispatch_identity_mismatch`、`dispatch_target_conflict`、`terminal_status_conflict`。保留第一个此类阻断原因；新的低优先级 unknown 不能覆盖它。身份不匹配的请求继续按现有入口拒绝或 reconcile，不写入外来 target 的事实。

### 3.2 转移规则

| 当前状态与输入 | 新状态 | 证据与后续行为 |
| --- | --- | --- |
| bound + 消息／中断／平台观察 unknown | bound | 增加相应 unknown_facts；不重发消息、不重试中断、不重派 |
| bound（含 unknown_facts）+ exact running/error 观察 | bound | 更新确定的平台观察；error 不自动解释为终态 |
| bound（含 unknown_facts）+ exact completed/stopped/interrupted 观察或通知 | terminal | 按真实来源保存首个 terminal_fact，保留 unknown_facts |
| terminal + 同状态的同源证据重放 | terminal | 幂等，不增加记录或改首次时间 |
| terminal + 不同来源的同状态确定证据 | terminal | 可记录现有结构允许的补充观察，保留首个 terminal_fact；不要求主动补齐第二来源 |
| terminal + 矛盾终态 | reconcile | 保留首个 terminal_fact 和 unknown_facts，记录阻断原因；不以新状态覆盖旧终态 |
| 派发未绑定／身份或终态冲突 reconcile + 后续通知 | reconcile | 不补绑、不自动消除冲突；不能套用 bound 的放行规则 |
| 任意允许关闭的状态 + 父 Agent 明确 close | closed | 保留已有身份、平台／终态事实、unknown_facts 和 reconcile 原因，固定首次 close reason |

现有 `inactive` 中断结果语义保持不变：它只证明不再活跃，不改写成 completed；本轮不扩大中断与终态冲突的兼容规则。closed 不接受新的生命周期更新，也不自动恢复原任务。

### 3.3 诊断与恢复

status、diagnose 和 SessionStart 使用同一投影：phase 决定下一步，unknown_facts 单独显示“曾出现未确定回执”。bound 仍可等待，terminal 提示父方验收／关闭，closed 的 next_action 为 none，同时仍可查看历史 unknown 和阻断原因。

`diagnose.issues=[]` 仅说明账本可读且结构有效，不表示所有平台操作成功；不得以关闭或无结构错误掩盖未知回执。SessionStart 优先展示未关闭任务的身份、phase 和必要异常摘要，不在每次启动重复列出所有已关闭任务。

正常等待不增加巡检。出现新证据或需要决定能否收尾时，允许对已绑定 exact target 做一次有目的的只读观察；没有新证据不循环查询。消息投递未知后，即使 Agent 已完成，也不能宣称它执行了该消息中的新增要求；父 Agent 必须按业务输出验收，证据不足时明确指出。

### 3.4 状态格式切换

采用 `state_format_version=11`、namespace `state-v11`。原因是 unknown 的 phase 语义和允许字段均发生变化，旧 runtime 会拒绝或误解新记录；不应在同一个 state-v10 目录里混用。

这次只调整 ledger 语义与校验，不升级 TaskContract、不增加数据库或迁移器。新 runtime 不读、迁移、清理 state-v10；旧未关闭任务不会自动出现在新版本摘要中。部署交接须明确这一限制，不能把新 namespace 为空解释为旧任务已经完成。旧任务需要收尾时，在其原版本环境内处理；本轮方案不授权该操作。发布源、缓存隔离与仅保留一个不可变上一版本的既有规则继续适用。

## 4. 正常路径与通信精简

```text
准备契约 → 简短派发说明 → 原生 spawn → exact-target confirm
                                      ↓
                         原生 wait／必要的原生消息
                                      ↓
                    一次终态登记 → 父方验收 → close
```

1. 普通消息 success/failed 后不再要求调用 record-call-result。保留该命令的显式校验入口及零写行为，避免为减少必需步骤而删除可用接口；unknown 才是正常流程中必须额外记录的结果。
2. 发消息前直接使用已保存的 task/ref/target 映射。上下文恢复或映射存疑时，先通过 exact-session status 检查已绑定身份；不新增每次发送前的固定 CLI 检查，也不从列表反推身份。
3. exact child notification 使用 record-terminal-notification；明确的 exact-target 平台状态使用 record-platform-observation。wait 的邮箱摘要和超时不冒充终态。对同一证据选择一个入口；独立来源确实带来新事实时才补充。
4. 父 Agent 验收结果后显式 close。暂不增加“登记终态并自动验收关闭”的合并命令，避免业务验收被账本状态替代。
5. 治理异常只停止依赖缺失身份或冲突事实的操作；父 Agent 继续其他不依赖它的已授权工作。不得通过重复 spawn 绕过失败，也不得把用户授权扩展为部署或外部写入许可。

可直接验收的步骤差异：每次普通消息成功／失败减少一次必需治理 CLI；同一通知不再走 observation + notification 两次登记。prepare、confirm、首次终态登记、父方 close 的必要性保持不变。

## 5. 提示与真实测试基线

### 5.1 派发提示

父 Agent 先用一句话说明派发理由；无需为此增加 TaskContract 字段。生成器将目标、范围、完成条件和关键配置压缩为通常两三行，长度较大时允许换行，不截断必要约束。例如：

```text
交给子 Agent 独立核查测试入口，以补充验证证据。
目标：列出可运行的测试命令；范围：只读 tests/ 与项目配置；完成：给出命令和依据。
配置：模型 gpt-6-astra；推理 high；上下文隔离（fork_turns=none）；治理 standard。
```

模型／推理未显式覆盖时，显示“未覆盖，按原生配置解析”，不把请求省略值冒充已核实的实际运行配置。启用 verified context 时追加材料数量；未启用时省略该行。

子 Agent 提示保留唯一目标、范围、完成条件、非空背景／路径／禁止事项／证据、必要终态要求；省略空区块。身份治理细节集中在父方 Skill，只有子 Agent 自己要派发时才按 Skill 处理。保留生成的治理标记和原生适配参数，不能因排版修改破坏 claim。

同步收口 Skill、runtime-boundaries、governance-profiles 和当前架构文档中的正常／异常分支；按最新 task_name claim 实现修正文案，避免把历史 message 逐字比较当作本轮前提。历史验收记录保留原样。

### 5.2 验收配置

建议将项目主真实验收配置从 `gpt-5.6-terra/high` 调整为 `gpt-6-astra/high`：保留 high，以免模型与推理强度同时变化；用户明确指定其他强度时采用用户配置。方案初次落盘未修改 AGENTS.md；本次实施已将该规范写入 AGENTS.md 和当前真实测试交接。

实施时同时更新 AGENTS.md 与当前真实测试交接模板；历史方案中的 Terra 配置不回写。父任务和受测子 Agent 均显式指定并分别核实配置；无法确认的一方标为未验证。运行时仍允许原生继承或其他受支持模型，不硬编码 GPT-6。

本地完成后，只有取得部署与真实测试授权才进入安装事务；命令结束立即报告并停止，等待重启。重启后的真实测试在独立新任务执行，确认实际加载版本和 Hook 状态。旧模型仅在明确需要兼容验证时补测。

## 6. 实施顺序与修改范围

| 顺序 | 交付 | 主要文件 |
| --- | --- | --- |
| 1 | 用最小用例固定 unknown 后终态被忽略、close 丢失原因的当前行为，再实现上述新规则 | scripts/governance_lifecycle.py；相关 lifecycle 测试 |
| 2 | 同步 state-v11 字段、reason 分类、校验和只读投影；与步骤 1 组成完整候选 | schemas/governance-semantics.schema.json、scripts/governance_semantics.py、scripts/governance_state.py、scripts/governance_diagnostics.py；相关 Schema、存储、并发、CLI 测试 |
| 3 | 缩短提示与必需调用，更新 GPT-6 测试基线和当前契约说明 | scripts/governance_dispatch_rendering.py、Skill 及 references、AGENTS.md、当前架构／上下文／中断／验证说明、直接相关测试 |
| 4 | 完成本地门禁，记录结果及未覆盖边界 | 现有本地验证文档、专项方案状态与索引 |
| 5 | 经授权部署、重启、新任务真实验证 | 既有部署入口和验证记录；已获授权，部署后等待重启 |

步骤 1—3 可以在同一开发任务完成，不强制逐项新建对话或独立发布。不改 Hook matcher、部署事务实现或材料验证算法；状态版本常量的直接引用须一并更新，不机械替换历史文档里的 state-v10。

## 7. 验收标准

### 本地功能与回归

- 三类 bound unknown 各自保持 bound，exact 后续终态可到 terminal；unknown_facts 经 terminal、冲突 reconcile、close 仍保留。
- 同一任务先后发生不同类别 unknown 时，三项均可保存；同类重复输入字节不变；第四类、空对象、未知嵌套字段、无绑定身份携带 unknown_facts 均被 runtime 与 Schema 一致拒绝。
- 派发 unknown、missing claim、错误 session/task/ref/target、终态冲突不能借本次调整绑定或恢复；首个绑定和首个终态不被覆盖。
- close 保留 unknown 和阻断原因；相同 reason 重放幂等，不同 reason 不覆盖；closed 不重新开启；64 条保留上限不变。
- 一条通知只登记一次即可验收关闭；独立同状态来源不冲突；矛盾终态进入 reconcile；inactive、error、超时仍不冒充 completed。
- status/diagnose/SessionStart 零写入；unknown 摘要与 phase/next_action 一致；新 runtime 不访问 state-v10。
- 新提示保留必要任务信息和配置，空区块消失；生成参数仍通过现有 claim／适配回归；普通消息 success/failed 的原有显式 CLI 路径仍零写。
- 正常消息的减步通过 Skill 审查与真实调用轨迹验证，不用静态字符串测试冒充模型行为验证。

实施涉及运行时代码和 Skill，执行项目要求的门禁：

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
git diff --check
```

Schema／状态版本一致性、并发和 current-only 测试纳入全量门禁；已有检查失败须查明并记录，不能删断言凑通过。相关门禁通过后，除非新增修改或出现未解疑点，不重复扩大测试。

### 经授权后的真实验收

| 场景 | 成功条件 |
| --- | --- |
| GPT-6 正常派发、等待、消息和完成 | exact claim/bind 成功；成功消息无额外必需记账；单来源终态一次登记；父方验收后关闭 |
| 实际 unknown 后出现确定状态 | 保留 unknown，同时登记 exact 后续状态并收尾；若平台未产生 unknown，此项标为未验证，本地注入用例不冒充真实回执 |
| 中断边界 | previous_status 不当作操作后状态；只有确定观察才记录终态；不自动重试 |
| 同 exact Session compact／恢复 | 找回正确映射与 phase、unknown 摘要；不重派、不补猜身份 |
| 最小双 Agent 并发、strict verified context、unmanaged | 无交叉绑定；声明材料校验生效；unmanaged 不创建治理任务 |

记录父／子实际配置、加载版本、Hook 可用性、调用步骤和结果边界。原生接口没有覆盖到的形状单独标记未验证；不为扩大矩阵随意切换环境。开发仓库验证与真实验证分别报告，运行缓存一致性在未授权部署前为未验证。

## 8. 交付记录

方案阶段只新增本文并更新专项索引，文档检查通过。后续经用户授权，已完成步骤 1—4 的开发改动及检查；具体复现、117 项测试、73% 综合覆盖率和 3 项既有 lint 问题见[本地验收](../validation/current-only-local-acceptance.md)。用户已授权提交到 main、部署本机及重启后真实测试。部署候选缓存版本为 `0.4.0+codex.20260909113817`；本文记录于部署前，安装结果以事务输出为准。部署结束立即停止，待用户确认重启后创建独立的 gpt-6-astra/high 测试任务。
