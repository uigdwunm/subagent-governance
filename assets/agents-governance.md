<!-- subagent-governance:start -->
## 子 Agent 治理

- 普通任务不需要加载子 Agent 治理规则，也不要仅因任务可以拆分就主动创建子 Agent。
- 当任务确实需要规划、派发、通信、等待、恢复、中断或验收原生子 Agent 时，在调用相关 Agent 工具前先使用 `$subagent-governance` Skill，并按该 Skill 的当前版本执行。
- 完整协作契约、治理等级、消息格式、等待恢复和终态规则只在 Skill 中维护；本区间只保留按需加载入口，避免长期占用全局 `AGENTS.md` 上下文。
- Skill 和 Hook 只增强 Codex 原生 Agent 工具，不替代沙箱、批准机制、provider 或平台能力。
<!-- subagent-governance:end -->
