# TaskContract v2 上下文完整性

TaskContract v2 把“帮助 Agent 定位”和“机械证明材料未变化”分开：

- `context.summary`：足以独立执行的必要背景；可为空字符串。
- `context.paths[]`：规范 POSIX 相对路径提示；不读取文件、不证明存在、不进入 identity。
- `context.verified`：显式 opt-in 的机械材料校验。

`context.verified` 沿用 declared manifest：absolute workspace root、`working_tree|git_commit` baseline 和 non-empty required paths。

- working tree 只接受逐文件 SHA-256；
- Git commit 使用完整 commit OID，要求 current HEAD 与声明 commit 一致，并验证声明 blob/tree；
- prepare 和 governed spawn Pre claim 各校验一次；
- runtime 只读取声明材料，不扫描其他路径或业务正文；
- 校验只覆盖上述时点的声明材料，不保证运行期间材料不变，不锁定文件或隔离工作区；并行修改的归属、共享接口和集成责任仍由任务交接明确；
- strict profile 不自动扫描工作区，但影响完成条件的材料应显式列入 verified manifest；standard 提供该字段即明确 opt in。

business contract digest 包含 context，因为它会改变任务含义；model、reasoning effort 和 fork turns 位于 spawn config，不进入 business digest。

派发正文保留非空背景、路径、禁止范围和验收证据，省略空区块；目标、工作范围和完成条件始终保留。提示精简不改变 declared manifest 的 prepare/claim 双重验证，也不证明父 Agent 已声明全部必要材料。

## 上下文恢复后的验收

state-v12 在单一账本的 `contract_summary` 原样保留规范化 business contract：profile、objective、scope、forbidden_scope、completion、evidence 及完整 context，不包含 spawn。context.summary 必须随完成条件保留，使“符合已定接口”等要求所引用的背景和设计约定仍可读取；范围、分工、集成依赖和禁止事项同样不被另行概括。

这里的 evidence 是派发时提出的证据／报告要求，不是执行后已经产生的检查结果；报告要求也可位于 completion。快照不证明说明充分或交付合格，不替代父任务对实际结果和后续新增要求的验收。

prepare/claimed 的快照与 capability contract 精确相等，所有阶段验证其 business digest；绑定时清理 capability 后，快照仍随失败、对账、终态和关闭保留，直到 closed 记录被既有保留策略淘汰。快照是确定性字段投影，不存完整聊天、工具日志、业务结果或材料正文。

父任务使用当前 Hook 的权威 CLI 和 exact session，调用 `--status --task-id <task_id> --task-ref <task_ref>` 按需取回单个任务及快照。身份不匹配或记录不存在时明确失败，不猜测、重派或自动验收。默认 status/diagnose 与 SessionStart 不输出全部验收正文。

字段、列表、字节及账本容量上限见 [runtime boundaries](../skills/subagent-governance/references/runtime-boundaries.md#原始验收快照与容量)。超限拒绝 prepare，不截断或自动改写。路径和 verified declaration 可以恢复，但不保证外部材料仍可用；恢复本身不重新读取或校验文件。旧格式 v11 及更早状态不读取、不迁移、不拼接为新快照。
