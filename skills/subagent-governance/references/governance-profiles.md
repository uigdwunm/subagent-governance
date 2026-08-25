# Governance profiles

## Standard

默认 profile，适用于普通编码、研究、诊断和 review。`forbidden_scope` 与 `evidence` 可以为空，但 objective、scope 和 completion 仍须可执行、可验证。

## Strict

用于用户明确要求更强边界或任务确实需要显式禁止范围和验收证据的场景。strict 要求：

- 非空 `forbidden_scope`；
- 非空 `evidence`；
- 影响结果的工作区材料需要机械验证时，显式使用 `context.verified`。

profile 是协作协议，不是权限、风险检测或自动安全升级。runtime 不读取任务正文来自动选择 profile。

## Derived identity

task name 格式为 `sg_<profile>_<derived-semantic-name>_t_<task-ref>`，最长 64 字符。task ref 从 task ID 确定性派生并在当前 exact Session 内检查碰撞。模型不得自行构造或修改这些字段。
