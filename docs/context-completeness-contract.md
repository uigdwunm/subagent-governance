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
- strict profile 不自动扫描工作区，但影响完成条件的材料应显式列入 verified manifest；standard 提供该字段即明确 opt in。

business contract digest 包含 context，因为它会改变任务含义；model、reasoning effort 和 fork turns 位于 spawn config，不进入 business digest。
