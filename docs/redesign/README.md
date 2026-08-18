# 插件重设计历史文档

> 本目录记录 v4 设计与实施过程，已经被 v5 的三平面状态和 Terminal Notification Channel 取代，不再定义当前运行时契约。当前权威来源是 `docs/project-function-inventory.md`、`schemas/governance-semantics.schema.json`、`skills/subagent-governance/SKILL.md` 和 `skills/subagent-governance/references/runtime-boundaries.md`。正文中对四平面、TaskResult、结果持久化、accept/reject 或已删除 SG-F06/WP-05 文件的引用仅是历史证据。

本目录保存“工作项收敛协议”重设计的独立设计结果。文档按 D1-D6 编号，必须按依赖顺序阅读。

设计阶段只修改本开发仓库，不直接修改运行时代码或外部插件安装位置。每份文档都应记录证据、边界、失败路径、unknown 路径、迁移影响和下一步依赖。

历史状态：D1-D6、S1-S6、F1-F13 与平台能力 Slice 1-5 曾按 v4 方案收口。v5 已删除其中的正式结果持久化与业务验收子系统，因此旧 GO、PASS 和 smoke 结论不能用于验收 v5，也不等于 release-ready、稳定安装或发布批准。

- `D1-work-item-convergence.md`：四层对象、状态不变量和迁移接口。
- `D2-dispatch-deliverable-contract.md`：派发、交付物、执行角色和预算。
- `D4-platform-recovery-boundary.md`：平台观察、恢复、重启和 replacement。
- `D5-decision-diagnostics.md`：work item 决策视图和机械 allowed actions。
- `D6-migration-and-slices.md`：兼容迁移、增长控制和 S1-S6 实施顺序。

平台能力契约重设计另有以下当前材料：

- `platform-capability-contract-and-minimal-state-machine.md`：当前平台证据等级、四平面状态机和分片边界。
- `platform-capability-slice-1-implementation.md`：官方 Hook 字段契约和 advisory/fail-open 基线。
- `platform-capability-slice-2-implementation.md`：format-2 四平面 StateStore、legacy 单向投影和本地验收证据。
- `platform-capability-slice-3-implementation.md`：当前父任务权威结果通道、format 4 和本地实现边界。
- `platform-capability-slice-3-parent-authority-redesign.md`：旧 credential 方案的根因、替代设计、验证与准入状态。
- `platform-capability-slice-4-design.md`：当前 evidence-first observation、freshness 和 parent Stop 边界冻结。
- `platform-capability-slice-4-implementation.md`：Slice 4 失败先行实现、本地门禁和下一步准入记录。
- `platform-capability-slice-5-design.md`：TaskResult 词汇与字段形状的 producer clarity 边界，不新增结果 authority。
- `platform-capability-slice-5-implementation.md`：Slice 5 实施、真实 smoke blocker 回修与本地门禁。
- `platform-capability-slice-6-design.md`：平台能力序列停止于 Slice 5 的 `NO-SLICE` 裁决。
- `platform-capability-final-acceptance-report.md`：Slice 1-5 最终综合验收、历史 blocker 关闭链和发布边界。

旧 Slice 3 credential 独立报告和真实 smoke 文档只保留为历史证据；文件顶部的 superseded 标记优先于其正文中的旧 GO 或测试建议。其他历史 NO-GO/FAIL 报告同样保留，当前状态以其后明确 superseding 的修复、独立复验和真实 smoke 为准。
