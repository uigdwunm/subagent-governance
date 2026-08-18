# 平台能力契约重设计：实施切片 1

日期：2026-08-14

状态：开发仓库内实施与本地门禁完成；未安装、未部署、未发布、未执行真实平台测试。

## 1. 目标与边界

本切片只把当前官方 Codex Hook 字段边界固化为机器契约，并撤销依赖非官方字段或弱观测建立的强身份、强生命周期、强结果和 parent Stop 保证。原生 lifecycle 在 Start/Stop 无法关联、transcript 变化、结果缺失或 StateStore 不可读时必须继续运行。

本切片不实现四平面 Schema 全量迁移、result credential、完整 observation adapter、active freshness gate、limited hard gate 或 legacy 全量退役。开发仓库是唯一修改源；未修改稳定发布源、Marketplace、运行缓存、Hook trust、Registry 或历史 smoke StateStore。

## 2. 官方能力契约

机器契约位于 `schemas/codex-hook-events-v1.contract.json`，字段来源为 [OpenAI Hooks](https://learn.chatgpt.com/docs/hooks)，检查日期为 2026-08-14。`https://developers.openai.com/codex/hooks` 在检查时重定向到该页面。

适用边界是当前 release 文档明确列出的 common、SessionStart、SessionEnd、PreToolUse、PostToolUse、SubagentStart、SubagentStop 和 Stop 字段。生成的 main-branch Schema、本地序列化字段表、transcript/rollout 内部格式和未来扩展不属于本契约。

已固化的关键事实：

- subagent lifecycle 使用父 `session_id`。
- `SubagentStart` 不定义 `agent_transcript_path`、task ref、canonical path 或正式结果字段。
- `SubagentStop.agent_transcript_path` 与 `last_assistant_message` 可缺失或为 `null`。
- 官方 `SubagentStop` 不定义 `task_result`。
- common `transcript_path` 是可选便利路径，内容格式不是稳定 Hook correctness 接口。

`tests/test_hook_event_contract.py` 对 official fixture 执行 required/optional key 集合检查。fixture 出现 correctness-critical 非官方字段会失败；负向 fixture 当前覆盖 Start 的 `agent_transcript_path` 和 Stop 的 `task_result`。

## 3. 实施修改

### Fixture 与契约

- `tests/fixtures/lifecycle-v1.json` 的 subagent 事件统一使用父 session。
- Start 不再携带 `agent_transcript_path`。
- Stop 同时覆盖 optional 字段完全缺失和显式 `null`。
- 新增 `tests/fixtures/lifecycle-invalid-extra-v1.json`，机械证明错误扩展不能进入 official fixture correctness 基线。

### Runtime

- PostToolUse success 只记录 dispatch observation；观察到的 Agent ID/canonical path 不确认 attempt identity。
- SubagentStart 只返回通用 unbound context，不读取 transcript/rollout metadata，不按 task ref、同名、唯一候选、时间邻近或全局扫描绑定身份，也不写 `not_started`、`running` 或 `confirmed`。
- SubagentStop 不读取或修改 StateStore，不消费 `task_result`、`last_assistant_message` 或自然语言 JSON；缺失、nullable 和未知扩展均允许 native stop。
- parent Stop 最多读取 StateStore 三次；持续不可读时告警并 fail-open。identity unconfirmed、Start/Stop 缺失、result missing/unknown 和历史 running 位仅为 advisory，不再循环 hard block。
- PreparedContract 的 PreToolUse admission 仍保留为本切片已有的正向可靠发送前门禁；本切片没有可证明的正向 parent Stop hard gate，因此没有新增 gate。

旧 `_read_subagent_event_route()`、`_route_has_exact_parent_candidate()`、`_assign_starting_agent()` 和 `_record_managed_result_protocol_gap()` 仍作为未调用的历史内部函数保留。静态回归要求每个符号只出现于定义处，防止重新进入 Hook correctness 调用路径；本切片没有继续增强 transcript route。

### Schema 与发布声明

- `schemas/governance-semantics.schema.json` 引用 Hook contract，并声明 Start identity/state authority、Stop result authority 和 transcript correctness authority 均为 `none`。
- Skill、runtime boundaries 与 README 删除了 Start 确认 running/identity、Stop 自动消费 `task_result`、缺结果自动纠正和 parent Stop 依赖旧 lifecycle 位硬阻断的声明。
- 历史 transcript compatibility 文档已标记 superseded，其旧设计只保留为历史证据。

## 4. 回归证据

新增或迁移的回归覆盖：

- extra-field detector、required-field detector 和字段集 parity；
- subagent 事件使用父 session；
- Start 无 transcript 字段；Stop optional 字段缺失或 nullable；
- unbound Start/Stop 不修改 attempt 或 PreparedContract；
- transcript 路径变化、未知 Stop 扩展、`task_result` 和自然语言 JSON 不改变 correctness；
- StateStore 连续不可读、旧 running、identity unconfirmed、missing/unknown result 和缺失 lifecycle 事件不阻止 parent Stop；
- 当前显式 `--record-child-result` 路径按 `task_id + attempt + sender_target` 精确绑定当前原生子 Agent 通知并保存正式结果；旧 `--submit-result` 已退役。

本地门禁结果：

| 门禁 | 结果 |
| --- | --- |
| `python3 -m unittest discover -s tests -v` | 387 tests，OK |
| `python3 -m py_compile scripts/subagent_governance.py` | passed |
| Plugin validator | passed |
| Skill validator | passed |
| `python3 scripts/release_preflight.py --mode development` | passed；包含项目现有 Schema/runtime parity 门禁 |
| `git diff --check` | passed |
| 新增未跟踪文件独立 whitespace check | passed |

最后两项在本报告落盘后重新执行，以覆盖报告本身和所有 untracked 文件。

## 5. 已知限制

- Start 保持 unbound 后，当前 release 没有 Hook 内可用的可靠 attempt identity credential；StateStore 可能长期保留 `not_started + unconfirmed + reconcile` advisory 状态。
- 显式结果记录由父 Agent 针对当前原生子 Agent 通知执行；本切片没有验证真实平台通知是否稳定提供完整 TaskResult 与精确 sender target。
- action-required、diagnostic、SessionStart 和 SessionEnd 仍使用既有 canonical 状态模型；本切片只取消 parent Stop 对不可靠状态的 hard gate，没有完成四平面迁移。
- transcript route 和旧 Start/result-gap helper 已停用但尚未物理删除，以控制本切片修改范围。
- 当前没有 positive、current、reliable 的 parent Stop active evidence，因此本切片的 parent Stop 实际为 advisory/fail-open。

## 6. Backlog 与下一切片边界

后续切片可以单独处理：

- 设计 attempt-scoped 一次性 result credential 与显式提交通道。
- 把 dispatch、observation、result、closure 四平面完整落入 Schema 和 runtime。
- 建立仅消费官方字段或显式 credential 的 observation adapter。
- 在获得正向、当前、可靠 active evidence 后评估 limited hard gate 和 freshness 规则。
- 删除已停用 transcript/Start identity/result-gap dead code，并完成 legacy 路径退役。
- 迁移仍以 `not_started/running` 表达弱观测的旧 diagnostic/action-required 语义。

这些工作均未在本切片自动开始。

## 7. Not Checked

- 未安装或同步开发插件到任何本地运行缓存。
- 未创建新 Codex 任务或真实 subagent lifecycle smoke。
- 未直接捕获当前平台的 raw Hook stdin。
- 未验证子 Agent在真实沙箱中调用显式提交 CLI 的可达性与权限。
- 未验证 result credential、四平面迁移、active freshness gate 或 limited hard gate。
- 未修改或验证稳定发布源、Marketplace、Hook trust、Registry 和历史失败 smoke StateStore。

因此，本报告只证明开发仓库内的机器契约、runtime 降级语义和本地回归门禁，不宣称真实平台端到端生命周期或正式结果闭环已经完成。
