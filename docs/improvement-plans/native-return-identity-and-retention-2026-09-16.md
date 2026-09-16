# 原生返回身份契约与失败派发保留上限修复方案

- 日期：2026-09-16
- 状态：开发仓库实施完成，本地 228 项测试通过；重启后真实复验待执行。部署状态以单独获授权的事务报告为准。
- 基线：`90dd3ca467cbf18e11245764f3e329714783ba55`，TaskContract v2 / state-v12。
- 本机已安装版本：`0.4.0+codex.20260916120318`。
- 方案编写时已有改动：根 `AGENTS.md` 与 `docs/release-process.md` 将真实验证模型改为 `gpt-5.6-terra/high`；本轮保留并一并提交。

## 目标与已确认依据

修复会让父 Agent 对同一原生返回作出不同绑定决定的说明缺陷，补上返回到绑定之间的验证缺口，并统一两种关闭入口的历史保留上限。

| 问题 | 已确认事实 | 影响 |
| --- | --- | --- |
| 身份字段说明错误 | 当前 Skill 写明 `agent_id` 是 exact target；2026-09-16 两个真实任务的 `collaboration.spawn_agent` 都返回 `{"task_name":"/root/…"}` | 一个父任务使用返回路径成功绑定；另一个因缺少 `agent_id` 停止绑定并进入 reconcile |
| 验证缺口 | `tests/test_acceptance_recovery.py` 的 bind helper 自行构造 target；独立真实测试完成流程，却没有报告 Skill 与实际返回不一致 | 状态机测试通过不能证明父 Agent 可以无歧义地遵循说明 |
| 失败派发保留上限偏差 | `record_dispatch_result(failed)` 在关闭之前裁剪；临时账本连续 65 次 prepare/failed 后保留 65 条 closed | 超过约定的 64 条；不会无限增长，但与 `close_task` 路径不一致 |

真实证据来源：任务「排查1拷问入口问题」`01a0aa18-039d-7a70-814b-12b77b08690d`；独立任务「验证本机新版子 Agent 治理插件」`01a0aa72-29be-7dd3-af83-ac5f56680c09`。这些 ID 仅用于复核历史证据，绝不能用作新任务的治理 session 参数。首个任务较早出现的 `claim_conflict` 根因未由本方案确认，不纳入修复完成声明。

## 第一组：身份说明与契约验证

### 统一身份来源

保持原生 spawn 和父任务显式 confirm。按当前可见工具契约解释同一次 spawn 返回，不新增自动绑定器、返回扫描器、CLI 命令或身份字段。

| 对象 | 使用规则 |
| --- | --- |
| prepare 生成、调用前提交的短 `task_name` | 只用于派发及 claim 定位；不能拼接 `/root/` 后充当绑定证据 |
| `collaboration_turns` 原生返回的完整 canonical `task_name`，例如 `/root/parent/child` | 原样作为 confirm 的 `target`；不截取末段，不重建父路径。这是原生返回的身份，不属于“按名称猜测” |
| `fork_context` 的 `agent_id` 返回形态 | 仅在该工具的可见契约及本次返回确实提供此身份时，原样用作 target；不声称本轮已完成该接口真实验证 |
| 缺失身份、类型不符、只出现无法证明可寻址性的短名称，或多个候选身份冲突 | 停止依赖身份的操作并报告实际回执；不从列表、通知、时间或唯一候选补猜，不盲目优先选择某个字段 |

不能把身份问题统一登记为“未创建”。明确失败且机械证明未创建才记录 failed；创建结果或可用身份无法确认时按现有异常路径处理，保持 reconcile 和人工停止跟踪的边界，不修改既有历史记录。

### 修改范围

- `skills/subagent-governance/SKILL.md`：权威身份条款、派发第 3 步及一个简短的原生返回到 confirm 示例。
- `references/recovery.md`、`references/runtime-boundaries.md`：同步区别输入短名称与原生返回的完整目标身份。
- README 及仍指导当前行为的架构说明：仅同步相同表述；历史方案和验收报告保留当时事实，不批量替换历史文字。
- `tests/`：新增原生返回形态样例和相关契约检查，不改写全部底层状态机测试。

现有 confirm 接收的仍是 `{task_id, task_ref, target}`，运行时无需认识 `agent_id` 或 `task_name` 这两个原生返回键。不要为了让测试运行而新增无人调用的生产解析函数。

### 本地验证

1. 使用去除业务正文的固定返回样例，显式标记真实采样与合成异常样例。覆盖完整 canonical task name、嵌套父路径、条件性的 agent_id 形态，以及缺失、类型错误、短名称和冲突形态。
2. 从样例原生返回中取出身份，执行 prepare → claim → confirm → terminal → close，断言账本 target 与原始身份逐字一致。不得用 prepare 的 task_id/task_name 拼出 target。
3. 对 Skill 中可执行的 JSON 示例做结构与值的一致性检查，防止文档示例重新写成固定 `agent_id`；保留实际工具契约是前提的说明。异常样例不应产生 confirm 输入。
4. 这些样例和结构检查只证明示例契约、运行时接收与状态转换相容，不能自动证明模型正确理解自然语言。必须通过下面的独立真实验证补齐这一点。

### 重启后的真实验证

实施和本地验证完成后，另经用户授权部署，按仓库事务入口执行；无论成败立即停止，等待重启。用户确认重启后，在独立任务中使用 `gpt-5.6-terra/high`，受测子 Agent 也显式采用相同配置。

至少覆盖两个有界用例：standard 的只读文件一致性任务（复现原误停场景）和 strict 的普通通信、终态、关闭任务。测试者先读取新版 Skill，不额外提示“忽略 agent_id，用 task_name”。记录实际返回字段、绑定提交和最终阶段，核实是否仅依据新版说明就完成操作。若需要自行绕过或纠正文档，即使运行时成功也不得判定该项通过。

父子模型配置分别核实，缺少证据则标未验证。测试不是为比较模型能力；两种 profile 用例也不能替代其他原生接口的验证。unknown、restart/compact 等未实际发生的路径继续明确标为未覆盖，不人为制造平台故障。每个用例结束都核对本次任务的治理收尾和实际 Agent 状态，不能以 `issues: []` 代替业务验收。

## 第二组：失败派发后的保留上限

先补一个通过公开函数复现的回归测试，再修复 `scripts/governance_dispatch.py` 的 `record_dispatch_result`：将 closed 裁剪放在本次状态变更之后、同一 StateStore 更新事务提交之前。复用 `prune_closed_tasks`，不更改保留数量、排序、其他生命周期语义或返回协议。

回归条件：

- 连续 65 次明确未创建的失败派发结束后，恰好保留最新 64 条，最早的一条被移除。
- 经 `close_task` 和 failed 两个入口混合关闭，仍遵守同一上限及排序。
- 其他 prepared、claimed、bound、terminal、reconcile 记录不被误删；可采用少量代表记录加缩小保留上限的测试，避免冗长重复用例。
- 最后一次 failed 的响应仍指向本次任务，读取账本有效，其他保留记录的契约和事实不被改写；unknown 仍进入 reconcile，不被当作 closed 裁剪。

## 实施顺序与完成标准

两组可在同一实施任务中依次完成，建议分别提交以便审阅和回退。先第一组，再第二组，最后做统一回归。无需增加新的状态机、恢复轮次或治理等级。

完成实施时运行：

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
git diff --check
```

可用时运行仓库 Ruff 检查；拟部署时再完成 development release preflight。报告要分开列出本地回归、部署事务、重启后真实验证，尚未执行的环节明确标记，不用上一版的 223 项测试结果代替本次回归。

本地完成标准：身份说明与当前工具返回一致、文档示例和返回样例检查通过、失败关闭立即遵守 64 条上限、全量门禁通过。完整真实验收还要求新版部署及独立任务验证通过；部署与真实测试之外的接口形态只报告已有证据范围。

## 范围与回退

本次不修改原生工具、不自动恢复旧账本、不改变 fail-open、first-bind-wins、精确 Session/CLI、终态幂等与 closed 不重开的规则；不修复尚未证实的旧 claim_conflict，不清理其他任务或旧版本状态。

第一组以文档和测试为主，第二组为小范围运行时修复；两组均无需状态格式迁移。实现回退可按各组提交单独撤销；任何已部署内容的回退仍必须通过获授权的部署事务，不手改稳定源或运行缓存。

## 本轮实施证据

- 第一组：修正主 Skill、恢复与运行边界说明，以及 README 和原生兼容矩阵；在发布流程加入无额外字段提示的真实验收要求。返回样例直接保存在被测试的说明中，包含 canonical、嵌套路径、条件性的 agent_id 及五类异常，未新增生产返回解析器。
- 新增 `tests/test_native_return_contract.py` 三项测试，检查样例一致性、成功样例的 claim/confirm/terminal/close 链路及主 Skill 的入口引用。异常样例检查的是文档未给出可提交身份，不代表平台或模型会自动执行这些判断。
- 第二组：将失败结果处理的裁剪移至状态变更之后、事务提交之前。`tests/test_dispatch_retention.py` 两项测试修复前均失败、修复后均通过，覆盖实际 65 次失败关闭及混合入口对五类未关闭记录的保护。
- 本地验证：全量 228 项 unittest 通过；最后一次样例断言补强后单独复跑三项返回契约测试通过；compileall、Ruff、Plugin validator、Skill validator、development release preflight 和 diff 检查通过。
- 实施验收时尚未执行本次修复的部署、重启和独立真实验证；后续部署以事务报告为准，旧版本成功轨迹不作为新版说明一致性的证明。
