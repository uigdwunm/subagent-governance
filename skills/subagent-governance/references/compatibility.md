# 兼容性边界

- 不改变 `spawn_agent`、`send_message`、`followup_task` 和 `interrupt_agent` 的原生语义。
- 普通调用不需要显式使用本 Skill；缺少治理等级时按 auto 处理。
- 不读取不稳定的 transcript 格式。
- 不自动运行项目测试，不自动修改项目文件。
- 不把用户级 Hook 描述成沙箱、权限或企业策略边界。
- 不保证模型理解正确，只验证可观察的派发和终态信号。
- 无法修复 Codex 内部序列化、provider 转换或消息投递缺陷；任务 ID 缺失只能标记为 delivery-suspected。
- 原生 `spawn_agent` 可能在 `PreToolUse` 前把 `message` 转成不透明密文。插件用 `task_name` 的 `sg_<mode>_` 前缀传递可机械识别的等级，不读取 transcript 解密或重建原文。
- 多个匹配 Hook 可能并发运行。本组件只维护自己的状态文件，不假设能阻止其他 Hook 启动。
- 未映射到本组件任务 ID 的子 Agent 不执行终态阻止，避免干扰第三方或特殊启动路径；其启动阶段仍会收到轻量执行边界提示。
- 状态文件损坏时会隔离损坏副本并重新建立状态；其他状态存储错误告警后降级放行，不把治理组件故障转化为原生 Agent 不可用。
- `SessionEnd` 只清理主任务的治理状态；它不会用于控制或终止子 Agent。
- 成功的 `interrupt_agent` 调用将映射任务标记为 `interrupted`；中断失败不会改变任务状态。
- `PostToolUse` 会观察 `list_agents`，把普通 `errored` 状态对账为 `platform_error`；明确的加密函数输出解码失败会标记为 `provider_protocol_incompatible` 并直接进入 `needs_decision`。插件不把任何此类记录描述成已修复 provider 故障。
