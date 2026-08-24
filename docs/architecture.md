# 当前架构

Subagent Governance 是 Codex 原生子 Agent 的本地生命周期治理层。它不创建第二套调度平台，不替代 Codex 权限、Hook trust、沙箱或父 Agent 的业务判断。

## 设计边界

- 原生 `spawn_agent`、`send_message`、`followup_task`、`wait_agent`、`list_agents` 和 `interrupt_agent` 仍是执行通道。
- 插件只维护可机械验证的派发、身份、平台观察、通知和关闭事实。
- 子 Agent 的原生最终回复是业务结果通道；插件不扫描或保存正文。
- 平台终态只证明 worker 状态，不替代原生终态通知。
- 父 Agent 直接判断业务质量，然后显式关闭生命周期。

## TaskContract 与上下文

所有治理等级使用同一 TaskContract，明确目标、背景、范围、禁止事项、完成条件、证据要求、任务特征、模型、推理强度和上下文策略。

`context_manifest` 必须选择：

- `none`：没有工作区材料依赖。
- `declared`：列出绝对工作区根、工作树或 Git commit 基线，以及全部必需路径。

declared manifest 在 prepare 和原生调用 claim 前分别验证。插件只读取声明路径，不扫描工作区推断依赖。

## 派发

`prepare_dispatch` 先验证 TaskContract 和 context manifest，再原子保存 PreparedContract 和初始 StateStore task。PreToolUse 根据确定性 task ref 认领 PreparedContract，并绑定原生 `tool_use_id`。

明确 failed 且可靠证明 Agent 未创建时，允许有界 spawn retry。unknown observation 不允许复用同一 attempt。

## 当前状态模型

每个 Session 使用一份 JSON 状态和一份稳定 lock。每个 managed task 包含：

- `managed`
- `work_item`
- `executions`

每个 execution 只包含三个 canonical plane：

- `dispatch_record`：派发准备、claim 和原生响应关联。
- `observation_record`：精确 target 的平台观察或终态通知。
- `closure_record`：等待、对账、父处置或关闭事实。

StateStore 只接受当前 `state_format_version=5`。缺少版本、其他版本或非 canonical managed record 都以 `unsupported_state_version` 或结构错误拒绝，不迁移、不修复、不写回。

未知根级扩展字段可以原样保留，但不能改变 canonical execution 语义。

## 身份与生命周期

`agents[target]` 是活动索引，execution 的 `dispatch_record.dispatch_target` 是身份来源。唯一未关闭的精确 execution 可以修复活动索引；多个候选或索引冲突必须对账。已关闭的精确 target 不会重新按 unmanaged 放行。

通信操作分为：

- `normal_message`
- `platform_recovery`
- `business_resume`
- `interrupt`

每次操作使用 prepared/claimed pending action 和 `tool_use_id` 对账。业务继续创建新 attempt；普通消息不改变生命周期；恢复预算有界；unknown 保持 reconcile。

## 终态通知与父处置

父 Agent 收到原生 child notification 后，记录精确 sender、task、attempt 和 terminal status。通知重放幂等，冲突状态进入 reconcile。

通知到达后，execution 等待父处置。当前父处置只有 `close_task`：关闭可靠非运行 attempts，并返回仍需主动中断的精确 targets。

## Session、Group 与诊断

- SessionStart 对账未完成的 prepared/claimed 操作，并输出 work-item 摘要。
- Stop 只给 advisory，固定 fail-open。
- SessionEnd 只在没有 action-required 且没有保留期 tombstone 时删除 Session JSON。
- Group 只聚合 required member 的生命周期就绪信号，不调度、不取消、不生成业务结论。
- diagnose 使用无锁只读路径，不创建目录、锁、临时文件或状态写入。

## 文件结构

- `schemas/governance-semantics.schema.json`：机器语义与状态枚举。
- `schemas/task-contract-v1.schema.json`：TaskContract wire contract。
- `schemas/codex-hook-events-v1.contract.json`：当前 Hook 字段能力边界。
- `scripts/subagent_governance.py`：生命周期状态机和 Hook facade。
- `scripts/governance_semantics.py`：机器语义加载与常量。
- `scripts/governance_contracts.py`：TaskContract 和任务特征值对象。
- `scripts/governance_state.py`：当前状态模型与结构验证。
- `scripts/governance_storage.py`：私有文件、锁和原子写入。
- `scripts/governance_errors.py`：运行时错误分类。
- `scripts/governance_cli.py`：命令行解析与运行时适配。
- `skills/subagent-governance/SKILL.md`：Agent 可执行协议。
- `skills/subagent-governance/references/runtime-boundaries.md`：运行边界摘要。

## 安装与发布

运行环境只允许一个当前插件缓存。`reinstall_plugin.py` 的快照仅服务一次安装事务：失败或进程中断时先验证快照摘要再回滚，成功后立即删除快照和其他缓存。安装锁由操作系统持有，进程退出后自动释放。

发布、安装、Marketplace、运行缓存和 Hook trust 的写入都需要单独授权。
