# v4 重设计工作流历史地图

## 状态

本文只保留 v4 重设计任务的导航关系。v5 已删除 outcome/TaskResult 持久化和 disposition 业务验收层，因此下列 D1-D6 文档不再定义当前运行时契约。

当前权威来源：

- `docs/project-function-inventory.md`
- `docs/optimization-plan.md`
- `schemas/governance-semantics.schema.json`
- `skills/subagent-governance/SKILL.md`
- `skills/subagent-governance/references/runtime-boundaries.md`

## 历史设计任务

| 编号 | 历史设计事项 | 文档 |
| --- | --- | --- |
| D1 | 工作项、execution 和旧四层对象边界 | `docs/redesign/D1-work-item-convergence.md` |
| D2 | 派发契约与重复执行预算 | `docs/redesign/D2-dispatch-deliverable-contract.md` |
| D4 | 平台观察、恢复和 replacement | `docs/redesign/D4-platform-recovery-boundary.md` |
| D5 | 诊断与工作项决策视图 | `docs/redesign/D5-decision-diagnostics.md` |
| D6 | 迁移、兼容和实施切片 | `docs/redesign/D6-migration-and-slices.md` |

原 D3 outcome disposition 文档已经删除；其正式结果、结果持久化和 accept/reject 设计不进入 v5。其他历史文档中引用 D3、旧 WP-05、SG-F06 或 `task-result-v1.schema.json` 时，应按历史证据理解，不应恢复相应文件或实现。

## v5 对应关系

```text
work_item
  -> execution
       -> dispatch_record
       -> observation_record
       -> closure_record
```

- 业务结果：父 Agent 直接阅读原生 child notification。
- 插件观察：只记录 exact sender、task、attempt、terminal status 和时间。
- 父处置：只使用 `close_task` 收口生命周期。
- 诊断与 group：只消费通知/关闭和 action-required 派生事实。

v5 的实施阶段和验收命令统一记录在 `docs/optimization-plan.md`。稳定发布、安装、Marketplace、运行缓存与 Hook trust 仍需单独授权。
