# 运行边界

- 插件保留 Codex 原生 `spawn_agent`、`send_message`、`followup_task`、`wait_agent` 和 `interrupt_agent`，不替代平台调度、沙箱或批准机制。
- 任务正文、证据质量和父 Agent 的业务判断不由 Hook 解析或评分。
- 当前状态格式为 v5。每个 execution 的 canonical authority 只有 `dispatch_record`、`observation_record` 和 `closure_record`。
- `StateStore.read()`、`update()` 和 CAS callback 只暴露这三个 canonical plane，不生成 execution 顶层兼容字段；所有当前运行路径也只通过三平面读取和写入状态。
- v1-v4 旧 execution 字段只作为一次性迁移输入。读取时仅在内存中转换，下一次成功写入时落为 v5；后续不再反向投影旧字段或维护第二份状态。
- v4 状态在锁内写入时迁移：精确绑定的旧父记录可降维为 terminal notification；业务结果、验收、结果协议、存储引用和 correction 字段全部退休。
- 未知格式版本 fail-open 且不重写原文件。

## 派发与身份

- PreparedContract 是 governed spawn 的前置凭证；PreToolUse 只按 task ref、StateStore 和可观察原生参数认领，不读取业务正文。
- TaskContract 的每个输入方向都必须显式出现；`context_manifest.mode=none` 表示明确无材料依赖，`declared` 只验证声明工作区、基线、路径、类型和摘要等机械事实。
- declared context 在 prepare 与 claim 两处验证。确定性缺失或变化拒绝 governed 操作；内部 Hook 异常仍遵守既有 fail-open 边界并保留诊断。
- `relevant_files[]` 是非权威定位提示，不替代 context manifest；插件不扫描未声明路径或业务正文推断潜在依赖。
- `--verify-context-manifest` 是无 Session、无状态写入的运输中立预检，可用于独立任务交接；它不拦截 `create_thread`，也不将该任务纳入原生子 Agent生命周期。
- `agents[target]` 是 active index，canonical execution 中的精确 dispatch target 是 retained provenance。
- 唯一未关闭 retained candidate 可恢复失效索引；多个 candidate 或索引冲突必须 reconcile。
- historical closed target 不复活；完全没有 provenance 才按 unmanaged 兼容。

## 通信与恢复

- `operation_type=normal_message|platform_recovery|business_resume`；主动中断使用独立 interrupt 入口。
- managed communication 先创建 prepared pending action，再由匹配 PreToolUse 原子 claim。
- normal message 只传递信息；platform recovery 只处理精确 observation error；business resume 需要精确 terminal notification 和父方 disposition gate。
- 同一 attempt 最多两次平台恢复，第二次必须用户授权。没有结果补交操作或计数。
- PostToolUse unknown 不自动重发，不伪造 running、failed、interrupted 或 closed。

## 观察与通知

- `list_agents` adapter 只读取顶层 `agents`，且非空响应必须满足 query target、agent name 和唯一 dispatch target 精确一致。
- completed、stopped、interrupted 只建立平台终态观察；它们不替代 child notification。
- 原生终态通知由父 Agent 通过 `--record-terminal-notification` 记录最小事实。
- 通知只包含 exact sender target、task、attempt、terminal status 和观察时间；正文不扫描、不持久化。
- 相同通知幂等；terminal status 冲突保留首个事实并进入 reconcile。
- 平台终态先到时为 `await_notification`；通知到达后为 `await_parent`。

## 关闭

- `--parent-disposition` 只接受 `close_task`。
- close 不自动中断明确 running 的 attempt，只返回精确 targets。
- 关闭生成7天 tombstone。v5 不读取、创建或删除旧 `results/` 文件。

## Session 与诊断

- Stop 最多读取 StateStore 三次并固定 fail-open；action-required 仅作 advisory。
- SessionEnd 仅在无 action-required 且无保留期 tombstone 时删除 Session JSON；稳定 lock 永不删除。
- diagnose 是无锁只读路径，不创建数据目录、锁、临时文件，不修复或回写状态。
- work-item diagnostics 展示 execution、identity、platform、notification、closure 和 allowed lifecycle actions；不展示业务正文或结果文件元数据。

## 平台能力

- 插件不注册 `SubagentStart`、`SubagentStop`；原生事件不参与 managed 状态维护或终态通知处理。
- transcript、summary、final history、Provider 错误文本和本地 fixture 都不能建立 correctness-critical 事实。
- 真实投递、mailbox 展示、Hook trust 和上下文映射必须通过真实 Codex 测试验证。
