# 治理等级

## 统一原则

- `requested_mode` 可以是 `auto|light|standard|strict`；实际运行等级 `resolved_mode` 只能是 `light|standard|strict`。
- 显式等级不由插件二次提升或降低，`resolution_reason=explicit_request`。
- `auto` 只读取结构化 `task_features`，不读取、分类或评分任务正文。
- 三种实际等级共用同一任务契约，差异只体现在契约最低数组要求和父 Agent期望的证据强度。
- 脚本只做字段、类型、长度、枚举、引用和基本组合校验，不判断风险描述是否真实或证据是否充分。
- `task_features` 在所有等级下必填；显式等级不按这些字段自动升降，但后续机械组合校验可以可靠读取任务形状。

## Light

- 适用于只读、短时、低风险任务。
- `forbidden_scope[]` 和 `evidence_requirements[]` 可以为空。
- 原生最终回复可以简洁，父 Agent仍直接判断业务结果。
- 网络恢复、状态安全和任务关联能力不会因 light 而关闭。

## Standard

- 适用于普通编码、研究、诊断和 Review。
- 至少提供一项 `evidence_requirements[]`。
- 父 Agent根据实际任务核对验证、证据和剩余事项。

## Strict

- 适用于安全、迁移、生产、破坏性操作、并发写入或复杂协作。
- 至少提供一项 `forbidden_scope[]` 和一项 `evidence_requirements[]`。
- strict 的证据要求更完整，但 Hook 不解析自然语言终态卡，不用字符数、关键词或固定标题判断业务完成。
- 插件不规定或持久化结构化业务结果，父 Agent直接阅读原生终态通知正文。

## Auto

所有模式都必须提供以下 `task_features`；`requested_mode=auto` 额外使用它们解析治理等级：

- `risk=low|medium|high`
- `read_only`
- `writes_files`
- `destructive`
- `production`
- `concurrent_write`

固定解析顺序：

1. `risk=high`，或 `destructive|production|concurrent_write` 任一为 true：`resolved_mode=strict`、`resolution_reason=auto_strict`。
2. 无 strict 信号，且 `risk=low + read_only=true + writes_files=false`：`resolved_mode=light`、`resolution_reason=auto_light`。
3. 其余合法组合：`resolved_mode=standard`、`resolution_reason=auto_standard`。

`read_only=true` 与 `writes_files=true` 是机械矛盾。

## task name

目标格式为 `sg_<resolved_mode>_<semantic_name>_t_<task_ref>`：

- 不生成 `sg_auto_` 运行时名称。
- `semantic_name` 只使用小写字母、数字和下划线。
- `task_ref` 由 `task_id + attempt` 确定性派生，长度按 12、16、20、24、28、32 位依次扩展。
- 完整名称最多 64 个字符；过长时只截断 semantic name。

运行时已经实现 task ref 的有界碰撞扩展、PreparedContract 原子写入和回读、初始 StateStore `admission="new_task"`、PreToolUse 单次认领以及精确 Agent 身份绑定。业务正文不参与等级、task ref 或身份判断。
