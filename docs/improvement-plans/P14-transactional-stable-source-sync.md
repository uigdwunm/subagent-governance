# P14：开发提交到稳定测试源的事务化同步

状态：已确认方案，等待独立实现对话执行。

前置：P13 已在开发仓库完成并通过本地门禁；目标 cachebuster 提交已存在，但尚未同步稳定源或安装。

执行配置：`gpt-5.6-terra`、推理强度 `high`。

## 目标

为开发仓库与本地 Marketplace 稳定测试源之间补充一个明确、可重复、可回滚的同步入口，使 P10-A 不再依赖临时 `cp`、`rsync --delete` 或人工覆盖。

同步成功后：

- 稳定测试源精确表示调用时干净 Git `HEAD` 的 tracked 文件集合；
- 不包含 worktree `.git` 文件、未跟踪文件、`__pycache__` 或测试运行产物；
- 稳定源 Manifest full version 与开发提交一致；
- 稳定源 tree digest 等于同步工具构造并验证的 source projection digest；
- 旧稳定源在切换失败时可精确恢复；
- 同步事务与 `reinstall_plugin.py` 使用同一安装锁，不能并发改稳定源/cache。

P14 只实现同步工具、测试和文档，不执行真实稳定源同步、不安装插件、不写运行 cache。

## 已核实事实

- 开发仓库是唯一开发源，当前执行位于 Git worktree；worktree 根的 `.git` 是 Git 管理文件，不能进入插件稳定源。
- Marketplace `personal` 当前指向独立的 `<marketplace-stable-plugin-root>`。
- 该稳定源是普通目录但不是 Git checkout，不能通过 `git pull`、checkout 或 fast-forward 更新。
- 稳定源当前包含完整插件/仓库 tracked 内容，但不包含 `.git` 和 `__pycache__`。
- 仓库已有 `reinstall_plugin.py` 的 OS lock、ordinary-file/directory、owner/permission、tree digest、原子 JSON 与中断事务恢复模式，但没有稳定源同步入口。
- plugin-creator 的普通 update loop 假设 Marketplace 已指向正在编辑的来源；本项目有“开发仓库唯一源 + 独立稳定测试源”额外边界，因此需要项目内明确同步步骤后再进入其 reinstall 阶段。

## 范围

必须新增或修改：

- 新增 `scripts/sync_stable_plugin.py`；
- `tests/test_release_tools.py` 或一个职责明确的新测试模块；
- `docs/architecture.md`；
- `docs/release-process.md`；
- `docs/improvement-plans/P10-authorized-install-and-real-validation.md`；
- `README.md` 中本地更新流程；
- 必要时复用 `scripts/reinstall_plugin.py` / `scripts/check_installation.py` 已有安全 helper，但不改变 P13 的双版本缓存语义。

禁止：

- 在实现任务中写真实 Marketplace stable root；
- 安装、发布、生成第二个 cachebuster、修改 Marketplace/Registry/Hook trust/runtime cache；
- 将稳定源改成 symlink 或 Git worktree；
- 复制未跟踪文件或根据 `.gitignore` 猜部署内容；
- 调用外部 `rsync --delete` 作为核心实现；
- 使用目录 mtime、文件数量或 Manifest version 代替内容摘要；
- 为历史临时复制布局提供迁移兼容层。

## 同步契约

建议命令：

```bash
python3 scripts/sync_stable_plugin.py \
  --source-root <clean-development-worktree> \
  --stable-root <marketplace-stable-plugin-root> \
  --transaction-parent <plugin-install-transaction-parent> \
  --expected-head <full-commit-oid> \
  --expected-version <full-manifest-version>
```

所有身份都必须显式或从唯一事实读取：

- source root 必须是普通目录、当前用户拥有、权限安全且是 Git worktree；
- `HEAD` 必须是完整 commit OID，且精确等于 `--expected-head`；
- `git status --porcelain=v1 --untracked-files=all` 必须为空；
- deployed file set 固定为 `git ls-files -z` 返回的 tracked 文件集合；
- tracked path 必须是 source root 下的普通文件，不允许 symlink、目录替代、逃逸或重复；
- source Manifest full version 必须等于 `--expected-version`；
- stable root 必须是普通目录且不能是 source root、其父子目录、symlink 或同一真实路径；
- stable parent 与 transaction parent 必须通过已有 owner/permission 安全检查；
- stable root basename 必须是 `subagent-governance`，避免误指向宽泛目录。

不提供隐式“当前目录同步到默认 HOME 路径”执行模式。真实外部写入时必须把 source/stable/transaction/HEAD/version 全部显式传入，使审计日志能复原目标。

## Source projection

同步工具不直接对开发目录调用现有 `tree_digest` 作为部署摘要，因为 Git worktree 包含 `.git` 管理文件和可能的非部署产物。

固定流程：

1. 用 Git NUL 分隔输出读取 tracked path；
2. 拒绝空集合、绝对路径、`..`、重复路径和任何超出 source root 的解析结果；
3. 拒绝 tracked symlink、FIFO、socket、device 或目录；
4. 将每个 tracked 普通文件用 metadata-preserving copy 写入同级 staging；
5. staging 只创建 tracked 文件所需目录，不复制 `.git`、untracked 或 ignored 内容；
6. 对 staging 调用共享 `tree_digest`，得到 `source_projection_digest`；
7. 再次读取 source `HEAD` 和 clean status，防止投影期间源发生变化；
8. staging Manifest version 必须等于 expected version，Plugin validator 在同步前由外层门禁执行，工具本身只做必要的结构和摘要校验。

文件 mode 是 tree digest 的一部分；copy 后 mode 或内容不同必须失败。

## 事务目录与锁

同步与安装共用：

```text
<transaction-parent>/.install.lock
```

必须复用或提取现有 OS lock 实现，确保以下操作不能并发：

- stable sync；
- `reinstall_plugin.py` cache install；
- 任一未完成同步/安装事务恢复。

同步事务使用有界前缀，例如：

```text
<transaction-parent>/stable-sync-<pid>-<uuid>/
```

其中保存原子 JSON manifest；staging 与 backup 放在 stable root 的同一父目录，确保目录 rename 位于同一文件系统：

```text
<stable-parent>/.subagent-governance.staging-<uuid>
<stable-parent>/.subagent-governance.backup-<uuid>
```

禁止复用不属于当前 transaction id 的同名目录或清理无法绑定的遗留目录。

## 事务阶段

### 1. admission

- 获取共享 OS lock；
- 先检查并恢复唯一可识别的未完成 stable-sync transaction；
- 如果存在多个未完成 sync、存在未完成 install transaction 或残留目录无法与 manifest 唯一绑定，拒绝；
- 校验 source/stable/transaction 路径、HEAD、clean status、version；
- 计算并记录原 stable digest、source HEAD/version、目标路径和 transaction id。

### 2. stage

- 创建同级 staging 普通目录；
- 从 Git tracked file set 构造 source projection；
- 校验 staging digest/version；
- 再次校验 source HEAD/status 未变化；
- 原子记录 `stage_complete` 后才允许触碰 stable root。

### 3. preserve old stable

- 原 stable root 必须仍为初始校验的同一安全目录且 digest 未变化；
- 将 stable root 原子 rename 为本事务绑定的 backup sibling；
- 校验 backup digest 等于原 stable digest；
- 记录 `backup_activated`。

### 4. activate new stable

- 将 staging 原子 rename 到精确 stable root；
- 校验新 stable 为安全普通目录；
- 校验 version、tree digest 和 source projection digest 精确一致；
- 再次确认 source HEAD/status；
- 记录 `stable_activated`。

### 5. commit and cleanup

- 原子写 `sync_succeeded` 最终报告；
- 删除 backup；
- 删除 transaction working directory；
- 稳定保留 shared lock 和 `last-stable-sync.json`；
- 最终报告保留 source/stable path、HEAD、version、old/new digest、切换和清理状态。

如果 backup 删除失败，新 stable 仍是已验证结果，但状态必须是 `sync_succeeded_cleanup_required`，保留 manifest/backup 并返回非零；后续恢复只能在精确 digest 匹配下清理，不能回滚一个已经明确激活且验证成功的 stable。

## 失败与回滚

### 切换前失败

staging 构造、source 变化、digest/version 校验等失败时：

- stable root 保持原样；
- 删除本事务 staging；
- 保留最终失败报告；
- 不创建 backup。

### stable 已移到 backup、new stable 尚未激活

- 将 backup 原子 rename 回 stable root；
- 验证原 stable digest；
- 删除 staging；
- 报告 `sync_failed_rolled_back`。

### new stable 已激活但最终验证失败

- 只在 new stable 与本事务记录的 staging/target fact 可精确绑定时删除它；
- 将 backup rename 回 stable；
- 验证原 digest；
- 报告 `sync_failed_rolled_back`。

### rollback 失败

- 不继续删除 backup、staging 或 transaction manifest；
- 报告 `rollback_failed`、精确阶段和仍存在路径；
- 后续执行在共享锁下先恢复，不能开始新同步或安装。

## 中断恢复

下一次调用在取得共享锁后，根据 manifest stage 和实际路径/digest进行唯一恢复：

- `stage_complete` 且 stable 原样：删除/复用本事务 staging后结束为 rolled back；
- stable 缺失、backup 正确：恢复 backup；
- stable 是未完成的新投影、backup 正确：回滚到 backup，除非 manifest 已明确记录 `stable_activated` 且新 stable 完整验证成功；
- `stable_activated` 且新 stable digest/version 正确：roll forward，只清理 backup；
- 路径、digest 或 transaction id 不一致：拒绝并保留现场。

恢复逻辑不得根据目录时间或名字排序选择 transaction。

## 报告字段

`last-stable-sync.json` 至少包含：

- `transaction_id`
- `state`
- `failed_stage`
- `source_root`
- `stable_root`
- `expected_head`
- `actual_head_before`
- `actual_head_after`
- `expected_version`
- `source_projection_digest`
- `old_stable_digest`
- `new_stable_digest`
- `staging_path`
- `backup_path`
- `recovered_interrupted_transaction`
- `rollback_performed`
- `backup_removed`
- `created_at` / `updated_at`

错误信息可包含上述非敏感路径和阶段，但不得转储文件内容或环境变量。

## 测试矩阵

至少覆盖：

1. 干净 Git source A → stable B：成功后 stable 精确等于 tracked projection A。
2. source `.git` 文件/目录、untracked 文件、ignored `__pycache__` 不进入 stable。
3. tracked 文件内容、mode、嵌套路径正确保留。
4. source dirty、HEAD mismatch、version mismatch 在触碰 stable 前拒绝。
5. source symlink 或特殊文件拒绝。
6. source/stable 相同、父子路径、stable symlink、错误 basename、unsafe owner/permission 拒绝。
7. stage copy 失败：stable 不变。
8. source 在 stage 前后变化：stable 不变。
9. stable 在 admission 后变化：切换前拒绝且不覆盖并发内容。
10. old stable rename 后、new stable activate 前失败：恢复 old digest。
11. new stable activate 后 version/digest 失败：恢复 old digest。
12. rollback 失败：backup/manifest 保留且新事务拒绝。
13. backup cleanup 失败：返回 cleanup-required，不误报完整成功。
14. 中断在 stage、backup、activate、cleanup 各阶段的恢复。
15. 多个未完成 transaction 或 unbound staging/backup 拒绝。
16. shared lock 已占用时同步拒绝；同步占锁时 installer 也拒绝（至少通过共享 helper/lock path测试证明）。
17. 最终报告字段、路径、HEAD、version、old/new digest 与实际一致。
18. 第二次同步相同 HEAD/version 可幂等成功或明确 no-op，不制造新 backup 残留。

测试必须全部使用临时 Git 仓库和临时 stable/transaction 目录，不触碰真实 HOME 插件位置。

## 文档与流程更新

P10-A 固定为：

1. 开发仓库完成 cachebuster 提交和本地门禁；
2. 从该干净 commit 运行 `sync_stable_plugin.py`；
3. 只读验证 stable version/digest 与 sync report；
4. 从 stable root 运行 P13 `reinstall_plugin.py`；
5. 安装后运行 `check_installation.py`；
6. 用户重启；
7. 全新任务执行真实平台验证。

明确区分：

- stable sync backup：只保护稳定测试源切换；
- install transaction snapshot：只保护运行 cache 安装；
- retained previous cache：只为上一代旧会话提供重启前兼容；
- 三者不能互相替代。

## 实施顺序

1. 先建立临时 Git source/stable fixture和共享锁测试。
2. 增加 admission/source projection 失败测试。
3. 实现最小 tracked projection 与摘要验证。
4. 增加切换中各阶段 fault injection，再实现 backup/activate/rollback。
5. 实现唯一中断事务恢复和 cleanup-required 状态。
6. 更新 P10、release process、architecture 和 README。
7. 运行完整门禁并提交；不进行真实同步或安装。

## 验收标准

- 唯一部署输入是干净 expected Git HEAD 的 tracked 普通文件集合。
- 稳定源切换前已完成 staging version/digest 和 source 二次稳定性校验。
- 任一切换或最终验证失败均恢复旧稳定源精确 digest，或明确保留可恢复现场并拒绝后续事务。
- 中断恢复不依赖目录排序/mtime，不误删 unbound 目录。
- 与 installer 共用 OS lock，测试证明不能并发。
- P10 文档不再要求操作者自行选择复制命令。
- 实现任务未写真实 stable/cache/Marketplace/Registry/Hook trust。
- 以下验证全部通过：

```bash
python3 -m unittest tests.test_release_tools -v
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/sync_stable_plugin.py scripts/reinstall_plugin.py scripts/check_installation.py scripts/subagent_governance.py
python3 scripts/release_preflight.py --mode development
python3 <plugin-creator-skill-root>/scripts/validate_plugin.py .
git diff --check
```

## 停止条件

遇到以下任一情况停止并报告：

- Git tracked 文件集合不能完整表示当前稳定源所需内容；
- Marketplace stable root 需要保留不在 Git 中的人工文件；
- 目录切换无法在 stable parent 同一文件系统完成；
- 共享 installer lock 无法安全复用且必须建立两个可能死锁的锁；
- Codex 在未安装时要求 stable root 永远不能出现 rename 切换窗口；
- 实现需要修改 Marketplace、Hook trust 或平台内部 Registry；
- 现有用户改动与方案文件冲突；
- 本地门禁失败源于无关治理运行时代码。

## 后续

P14 提交、复审并合并后，另开 P10-A 安装任务：

- 以当前 cachebuster commit 为 expected HEAD/version同步真实 stable；
- 用 P13 installer 安装并保留 previous + target；
- 安装后旧对话 Hook 路径继续存在；
- 用户重启后再开全新 `gpt-5.6-terra` / `high` 真实验证任务。
