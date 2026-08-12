# 平台验收摘要

本文公开记录 `subagent-governance` 在真实 Codex 环境中的验收范围、故障演进和最终结论。原始验收记录包含本机路径、Session 标识和运行日志引用，不纳入版本控制。

## 验收环境

- 插件版本：`0.4.0-rc.10`
- 插件形态：Skill 与七类生命周期 Hook
- 安装来源：Personal Marketplace 的独立稳定发布副本
- 运行隔离：开发仓库、稳定发布源和版本化运行缓存互不使用符号链接
- 验收原则：仓库测试、文件存在或安装命令成功不能替代真实新任务中的 Skill、Hook 和生命周期证据

## 故障演进

真实平台验收按以下顺序发现并处理了三类问题：

1. 已打开的任务仍固定引用上一版本缓存中的 Hook 路径。重启并保留兼容缓存后，不再出现旧脚本路径缺失错误。
2. Hook 尚未完成交互式信任时，静态配置存在但不能证明实际执行。完成信任检查后，真实 `PreToolUse` 能够执行发送前门禁。
3. 生成器与 Hook 一度解析到不同的数据根，导致已创建的 PreparedContract 无法被 Hook 找到。统一插件数据根后，该问题不再复现。

这些失败均保留为发布流程的回归边界：不能用静态文件检查替代目标版本真实加载，不能绕过 Hook trust，也不能在缺少精确 PreparedContract 时把原生派发误判为受治理派发。

## 最终最小闭环

目标 cachebuster 在新任务中完成了一个 `light`、`isolated`、只读 Agent 的最小真实闭环：

| 验收项 | 结果 |
| --- | --- |
| 目标版本注册、启用和稳定源/缓存一致性 | passed |
| 当前任务加载目标版本 Skill | passed |
| 目标 Hook 配置和脚本实际执行 | passed |
| PreparedContract 创建和单次消费 | passed |
| 受治理身份精确绑定 | passed |
| 正式结构化结果提交与读取 | passed |
| 父任务接受结果并关闭任务 | passed |
| tombstone 与 `action_required=0` 闭环 | passed |
| 诊断入口保持只读 | passed |

平台在该次派发中只提供 canonical task path，没有提供第二个独立 Agent ID。项目契约允许使用任一可靠原生标识；canonical task path 已精确绑定到对应任务和 attempt，因此该情况不视为身份失败。

## 尚未由本摘要证明的范围

该最小闭环不等于所有场景均已完成真实平台验收。以下行为仍应在发布候选上按需单独验证：

- `standard`、`strict` 和 `auto` 的完整业务场景
- 平台恢复、结果纠正、业务继续和重复执行处置
- managed communication 与 interrupt 的全部 success、failed 和 unknown 分支
- 多任务轻量 group 的真实聚合显示
- SessionEnd 以及跨版本旧任务继续运行

这些场景已有单元测试覆盖；对外发布时仍应明确区分自动化测试证据和真实平台证据。

## 公开记录规则

公开验收文档不得包含：

- 用户主目录或其他主机专属绝对路径
- Codex Session、thread、task 或 rollout 标识
- 完整业务 prompt、业务输出或原始平台响应
- Token、Cookie、Hook trust 记录或其他认证材料

需要定位问题时，公开记录使用 `$HOME`、`<session-id>`、`<task-id>`、`<task-ref>` 和 `<plugin-cache-root>` 等占位符，并只保留复现问题所需的最小证据。
