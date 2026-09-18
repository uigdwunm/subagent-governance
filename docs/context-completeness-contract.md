# TaskContract v2 上下文完整性

TaskContract v2 把“帮助 Agent 定位”和“机械证明材料未变化”分开：

- `context.summary`：足以独立执行的必要背景；可为空字符串。
- `context.paths[]`：规范 POSIX 相对路径提示；不读取文件、不证明存在、不进入 identity。
- `context.verified`：显式 opt-in 的机械材料校验。

`context.verified` 沿用 declared manifest：absolute workspace root、`working_tree|git_commit` baseline 和 non-empty required paths。

- working tree 只接受逐文件 SHA-256，保留解析工作区内符号链接目标的行为；
- Git commit 使用完整 commit OID，要求 current HEAD 与声明 commit 一致，并验证声明 blob/tree 和实际文件字节；
- prepare 和 governed spawn Pre claim 各校验一次；
- runtime 只读取声明材料，不扫描其他路径或业务正文；
- 校验只覆盖上述时点的声明材料，不保证运行期间材料不变，不锁定文件或隔离工作区；并行修改的归属、共享接口和集成责任仍由任务交接明确；
- strict profile 不自动扫描工作区，但影响完成条件的材料应显式列入 verified manifest；standard 提供该字段即明确 opt in。

business contract digest 包含 context，因为它会改变任务含义；model、reasoning effort 和 fork turns 位于 spawn config，不进入 business digest。

派发正文保留非空背景、路径、禁止范围和验收证据，省略空区块；目标、工作范围和完成条件始终保留。提供 verified 时，正文自动包含解析后的工作区根目录、基线种类、commit OID（如有），以及全部声明路径和类型，无需在 context.paths 重复填写。逐文件摘要和目录 object ID 留在验证记录中，不展开材料正文。提示精简不改变 declared manifest 的 prepare/claim 双重验证，也不证明父 Agent 已声明全部必要材料。

## 实际材料与时间预算

`git_commit` 使用实际普通文件字节计算 Git blob identity，不执行内容转换来认定字节等价。CRLF、LFS 或其他过滤器产生的不同字节不会通过，即使 Git status 显示干净；需要校验本地实际内容时可改用 `working_tree`。符号链接（包括路径中的目录链接）、子模块和非普通文件不受 Git 材料验证支持，不跟随到其他工作区或自动获取内容。

声明目录覆盖提交中的该目录及全部受跟踪后代；重叠声明不重复读取同一文件。缺失、实际类型或字节不匹配属于已确认材料冲突。稀疏检出、skip-worktree、assume-unchanged 不能替代实际读取：只有声明范围实际存在且匹配才能通过。不读取未声明子树的文件；保留声明范围内暂存修改和未忽略新增文件的冲突检查，忽略文件不纳入提交材料证明。

prepare 和 claim 各有共享的 5 秒材料验证预算，覆盖 Git 命令、目录条目处理和逐块文件哈希。claim 使用进入 Pre 处理时建立的截止时间，包含已消耗的账本访问时间；取得锁后不重置预算。Git 调用使用剩余时间，批量取得声明范围对象和 status，避免逐路径启动多个命令。

预算耗尽、读取失败、读取过程中观察到不稳定或不支持的材料均不得标记成功。prepare 报错且不创建 capability；claim 保持既有 `material_unavailable`、allow（fail-open）、unconfirmed 语义。已确定的 Git 材料冲突、prepare 后必需文件或工作区明确缺失／类型不匹配，以及 prepare/claim 验证记录不一致走 `material_conflict`，不消费 capability。超时不转成“材料缺失”，也不因 strict 改成 deny。

材料 Git 查询统一使用 `--no-optional-locks`，避免 `status` 的可选索引刷新写入。路径检查与打开／读取阶段发现的明确缺失或类型不匹配采用相同分类；权限不足、超时和不能确定内容的读取不稳定仍为不可用。首次 prepare 校验失败不创建 capability。打开或读取发生一般 I/O 错误后，在剩余预算内只复核一次路径类型；仅明确缺失或非普通、非符号链接类型判为冲突。复核不跟随新符号链接，权限、I/O 或预算导致不可判定时仍放行，并保留原始 I/O 错误原因。

该预算是尽力而为的执行边界，为 10 秒 Hook 留出余量，不是对操作系统 I/O、账本锁等待、进程启动或平台投递的硬中断保证。阻塞操作返回后才可能检查到超时；本地时钟及 subprocess 超时模拟不证明真实 Hook 超时或投递行为。材料验证不锁定工作区，也不保证整组文件的原子快照或后续执行期间不变。

## 上下文恢复后的验收

state-v12 在单一账本的 `contract_summary` 原样保留规范化 business contract：profile、objective、scope、forbidden_scope、completion、evidence 及完整 context，不包含 spawn。context.summary 必须随完成条件保留，使“符合已定接口”等要求所引用的背景和设计约定仍可读取；范围、分工、集成依赖和禁止事项同样不被另行概括。

这里的 evidence 是派发时提出的证据／报告要求，不是执行后已经产生的检查结果；报告要求也可位于 completion。快照不证明说明充分或交付合格，不替代父任务对实际结果和后续新增要求的验收。

`prepared/claimed` 的快照与 capability contract 去掉 `spawn` 后的业务部分精确相等，所有阶段验证其 business digest。同时，capability 另存规范化完整契约、材料校验元数据和完整生成派发消息 `expected_native_parameters.message`。绑定、派发失败或未知、进入 reconcile 或关闭时清理 capability，业务快照仍保留，直到 closed 记录被既有保留策略淘汰。prepared 过期不删除记录；未关闭记录不自动清除，closed 在真实写操作中最多保留最新 64 条；新增任务使总条数超过 512 或超过 3 MiB 准入线时可提前淘汰最旧完整 closed 记录。淘汰与插入同事务，返回 pruned_task_ids；准入失败不改写原账本。

快照是确定性字段投影，不主动采集完整聊天、工具日志、业务结果或材料正文；填入契约的文字仍会保存，不自动脱敏。这些说明对应尚未发布的 state-v12 开发线，不代表稳定 v0.4.0 已具备或部署该实现。

父任务使用当前 Hook 的权威 CLI 和 exact session，调用 `--status --task-id <task_id> --task-ref <task_ref>` 按需取回单个任务及快照。身份不匹配或记录不存在时明确失败，不猜测、重派或自动验收。默认 status/diagnose 不展开完整契约，但包含目标和关闭原因；SessionStart 不展开目标、关闭原因或完整契约。存储位置及诊断输出边界见[当前架构](architecture.md#存储位置与输出边界)。

字段、列表、字节及账本容量上限见 [runtime boundaries](../skills/subagent-governance/references/runtime-boundaries.md#原始验收快照与容量)。超限拒绝 prepare，不截断或自动改写。路径和 verified declaration 可以恢复，但不保证外部材料仍可用；恢复本身不重新读取或校验文件。旧格式 v11 及更早状态不读取、不迁移、不拼接为新快照。
