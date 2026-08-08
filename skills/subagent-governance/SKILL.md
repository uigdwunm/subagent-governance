---
name: subagent-governance
description: 为 Codex 原生子 Agent 选择 light、standard、strict 或 auto 治理等级，并生成兼容直接 spawn_agent 的可靠派发说明。用于用户要求规划、派发、加强、诊断或治理子 Agent，任务需要上下文隔离、完成验收、失败恢复、并发协调，或需要判断某次子 Agent 交互为什么提前结束、漂移或缺少证据时。不要因为普通任务碰巧包含子 Agent 字样就主动引入重型流程。
---

# 子 Agent 治理

为当前任务选择最低但足够的治理等级。保持 Codex 原生 `spawn_agent` 为执行通道，不创建另一套编排平台。

## 选择治理等级

- 使用 `light` 处理边界清楚、只读、短时、失败影响低的任务。
- 使用 `standard` 处理普通编码、诊断、研究和 Review；这是无法确定时的默认等级。
- 使用 `strict` 处理安全、迁移、数据风险、长要求、多阶段验收、允许下级子 Agent 或并发写入相关任务。
- 使用 `auto` 让 Hook 根据可观察信号选择；当原生传输把正文加密时，未显式标记的 auto 会兼容降级为 standard，不要把它描述为语义正确性的保证。

完整边界见 [references/governance-levels.md](references/governance-levels.md)。

## 生成派发

1. 明确一个可验证目标、允许范围、禁止范围和完成条件。
2. 选择模型、推理强度和上下文继承策略。执行者和 Reviewer 优先使用隔离上下文；确实需要历史对话时保留有限或完整继承，并说明原因。
3. 把 `task_name` 写成 `sg_<mode>_<semantic_name>`，例如 `sg_strict_security_review`；这是 Hook 在加密传输下可靠可见的治理通道。正文中仍加入一行 `【治理等级】light|standard|strict|auto` 供子 Agent 阅读。
4. 未显式覆盖模型或强度时，用户可见说明写“继承主 Agent（未显式覆盖）”和“继承主 Agent 当前强度（未显式覆盖）”，不得猜测具体值。
5. `strict` 任务额外加入以下字段：

```text
【目标】<唯一当前目标>
【工作范围】<允许读取、修改和验证的范围>
【禁止范围】<不得执行的动作>
【完成条件】<可机械核对的条件>
【验收证据】<文件、命令、测试、检查或结论>
【上下文策略】<隔离 | 有限继承 | 完整继承及理由>
【下级子 Agent】<禁止 | 允许及边界>
```

6. 保留用户可见的中文派发说明，但不要向用户展示内部治理标记、状态文件或 Hook 实现细节，除非用户正在诊断治理组件。
7. 调用原生 `spawn_agent`。不要因为本 Skill 存在而创建用户可见的新任务或改用 Agents SDK。

## 处理终态

- 接受 `light` 的简洁实质结果，不要求形式主义报告。
- 要求 `standard` 至少说明实际结果、执行过的检查或证据、剩余问题。
- 只有显式 `strict` 要求中文终态卡并逐项给出验收证据；`auto` 提升到严格证据要求时不强制固定模板。
- 当 Hook 请求补充终态时，恢复同一个子 Agent；不要立即创建替代 Agent。
- 把需要用户选择的信息映射为“需要决策”，不要把它伪装成完成或阻塞。
- Hook 达到纠错上限后，把它作为协议错误交给父任务处理，不进行无限续跑。
- 成功中断的治理任务进入 `interrupted` 终态，不再阻止父任务结束；治理状态不可用时告警并降级放行原生子 Agent。
- mailbox 明确报告平台执行错误时，先调用目标范围的 `list_agents` 对账。确认 `errored` 后记录为 `platform_error`；允许对同一 Agent 自动恢复一次。恢复后再次确认平台错误时记录为 `needs_decision`，停止自动重试并请求用户决定是否切换 provider、模型或稍后重新派发。

## 诊断失败

按以下层次定位：

1. `dispatch`：派发参数为空、范围冲突或严格字段缺失。
2. `delivery-suspected`：Hook 看到的派发正确，但子 Agent 没有识别治理任务 ID。
3. `execution`：任务已识别，但没有实际执行或发生漂移。
4. `acceptance`：执行可能完成，但终态证据不足。
5. `orchestration`：父任务重复派发、错误中断、未等待或并发写入冲突。
6. `state-degraded`：状态文件损坏、不可读写或超限；Hook 应保留告警并避免禁用原生 Agent。
7. `transport-opaque`：原生工具参数中的任务正文已加密，Hook 不能机械读取正文契约；检查 `task_name` 是否使用 `sg_<mode>_` 前缀。
8. `platform-error`：`list_agents` 明确报告 Agent `errored`，例如 provider `stream disconnected`；这属于平台执行失败，不是 dispatch 内容错误。

不要宣称 Hook 能修复 Codex 内部消息传输；它只能检测、缓解和保留诊断证据。完整兼容边界见 [references/compatibility.md](references/compatibility.md)。

全局协作规则的规范化发布源是插件根目录的 `assets/agents-governance.md`。修改协议语义时，应同步运行时契约、该资产、本文和 JSON Schema，并通过对应一致性测试。

## 与其他 Skill 的关系

不要修改或要求现有 Skill 采用本协议。现有 Skill 继续直接调用 `spawn_agent` 时，Hook 只提供兼容性保护。记录但暂不适配的清单见 [references/related-skills.md](references/related-skills.md)。
