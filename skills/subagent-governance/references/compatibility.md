# 兼容性边界

- 不改变 `spawn_agent`、`send_message`、`followup_task` 和 `interrupt_agent` 的原生语义。
- 普通调用不需要显式使用本 Skill；缺少治理等级时按 auto 处理。
- 不读取不稳定的 transcript 格式。
- 不自动运行项目测试，不自动修改项目文件。
- 不把用户级 Hook 描述成沙箱、权限或企业策略边界。
- 不保证模型理解正确，只验证可观察的派发和终态信号。
- 无法修复 Codex 内部序列化、provider 转换或消息投递缺陷；任务 ID 缺失只能标记为 delivery-suspected。
- 多个匹配 Hook 可能并发运行。本组件只维护自己的状态文件，不假设能阻止其他 Hook 启动。
- 未映射到本组件任务 ID 的子 Agent 不执行终态阻止，避免干扰第三方或特殊启动路径；其启动阶段仍会收到轻量执行边界提示。
