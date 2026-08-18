# 本地稳定版发布流程

## 目标结构

- 开发仓库：`~/workspace/subagent-governance`
- 稳定发布源：`~/plugins/subagent-governance`
- Personal Marketplace：`~/.agents/plugins/marketplace.json`
- 运行缓存：`~/.codex/plugins/cache/personal/subagent-governance/<version>`

Marketplace 继续指向稳定发布源。开发仓库永远不直接作为已安装插件来源。

## 发布门禁

发布前必须满足：

1. Git 工作树干净，目标提交已推送。
2. 单元测试、全部 Python 脚本编译、仓库发布预检、Plugin validator、Skill validator 全部通过。
3. 可执行代码变更已经完成安全审查。
4. Manifest 使用新的正式版本号，并在提交与打 tag 前生成唯一 Codex cachebuster。
5. 已记录回滚目标和上一稳定缓存路径。
6. 目标 `assets/agents-governance.md` 只包含合法的最小 Skill 入口并通过结构测试；发布前的全局标记区间应继续与当前稳定版一致，不要求提前匹配尚未安装的目标资产。
7. 对仍需由目标运行时继续处理的活动治理记录，只按下一次真实操作所需字段做结构预检；未知额外字段忽略，缺失字段明确列出，不按 stored version 拒绝，不执行状态迁移矩阵。
8. 活动治理记录必须具备 canonical `work_item + executions`；旧 root current/`prior_attempts` 只能作为历史诊断事实，发布流程不得原地迁移、补写或把它们计为可继续执行的活动任务。

仅做本地发布准备时，到上述只读检查和仓库验证为止。替换稳定发布源、更新 Marketplace/运行缓存、应用全局规则、确认 Hook trust 或清理缓存都属于另行授权的发布操作。

本地全量、validator 和只读安装检查通过也不等于目标版本已经加载。真实插件、Hook 和平台链路未执行时必须记录 `not_checked`，不能用旧稳定版或现有缓存状态代替。

## 建议步骤

### 1. 在开发仓库验证

```bash
cd ~/workspace/subagent-governance
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py scripts/apply_agents_block.py scripts/check_installation.py scripts/reinstall_preserving_caches.py scripts/release_preflight.py
python3 scripts/release_preflight.py --mode development
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
python3 ~/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py .
```

cachebuster 生成后需要重新运行上述校验，再提交、推送并创建 tag。公开 Marketplace 的 `source.ref` 在日常开发中可以使用 `main`；正式 tag 前必须改成 Manifest 公共版本对应的 `v<version>`。tag CI 会通过 `scripts/release_preflight.py --mode release --tag <tag>` 强制 Manifest 公共版本、Git tag 和 Marketplace ref 三者完全一致。发布副本必须来自该 tag，避免稳定发布源在导出后再次发生未入库修改。

### 2. 生成干净发布副本

从已提交的 Git tag 导出到临时目录，校验后再替换稳定发布源。不要使用符号链接，也不要从带未提交修改的工作树直接复制。

推荐使用 `git archive` 生成发布内容：

```bash
git archive --format=tar <tag> | tar -xf - -C <临时发布目录>
```

归档后必须在临时目录再次执行：

```bash
python3 <临时发布目录>/scripts/release_preflight.py \
  --root <临时发布目录> \
  --mode archive
```

该检查确认公开文档、插件/Skill 基础结构、Marketplace、版本边界和常见敏感信息均存在于实际发布包中，并拒绝把 `docs/real-platform-test-*.md` 原始验收记录带入归档。本机官方 Plugin validator 和 Skill validator 仍是发布门禁；仓库预检是无外部依赖、可在 GitHub Actions 和解压归档中运行的可携带补充校验，不替代官方 validator。

替换稳定发布源属于发布操作，必须保留上一版本备份并使用明确的绝对路径。

### 3. 更新 Codex 缓存

稳定发布源就位后，使用 tag 中已经生成的 cachebuster 通过保留缓存的包装器重装：

```bash
python3 ~/plugins/subagent-governance/scripts/reinstall_preserving_caches.py \
  --marketplace personal \
  --previous-version <升级前完整版本>
```

`<升级前完整版本>` 必须来自重装前记录的 Codex installed/current 状态，不能从缓存目录名称或修改时间推断。首次安装且缓存目录为空时可以省略该参数；只要已经存在任何版本缓存，缺少该参数就会停止。

该脚本实际调用 `codex plugin add subagent-governance@personal`，只快照显式指定的升级前版本 N-1，不再复制全部历史缓存。原生命令非零、无法启动、目标缓存未生成或发生其他异常时，工具会先恢复 N-1；同名目录内容冲突时停止并保留实际快照，不覆盖任何一方。快照目录与缓存目录必须由当前用户拥有、不能允许组用户或其他用户写入，并且必须位于同一文件系统。

工具使用 `~/.codex/plugin-cache-rollover/subagent-governance/.reinstall.lock` 阻止并发或未完成事务重入，并把最后事务状态原子写入同目录的 `last-transaction.json`。正常安装成功只进入 `reinstall_succeeded_pending_acceptance`，报告中的 `cleanup_candidates` 只是 N-2 及更早缓存的 dry-run 清单，`retention_cleanup_allowed` 在真实验收完成前保持 `false`；工具不会自动删除这些目录。

稳定缓存策略是：当前运行版本 N 必须存在；历史兼容缓存只保留升级前实际版本 N-1。目标版本真实验收通过后可以清理 `cleanup_candidates` 中的 N-2 及更早目录，不再保留全历史缓存。

不要手工修改 Marketplace 或 Codex-owned Hook 信任哈希。

Codex 任务在启动时会固定其 Hook 命令，其中可能包含当时版本缓存的绝对路径。原生 `codex plugin add` 会清理旧缓存，因此不能绕过上述包装器直接重装；否则仍打开的老任务会在后续 `Stop`、`SubagentStop` 等阶段因脚本路径不存在而报错。旧缓存只服务于已打开任务；新任务仍从当前 manifest 对应的新缓存加载。

新版稳定源和缓存就位后，使用稳定版脚本把最小 `$subagent-governance` Skill 入口应用到全局标记区间。完整协作规则保存在 Skill 中，不能再复制到全局 `AGENTS.md`。不要在稳定源替换和插件重装前使用开发仓库资产提前更新全局入口：

```bash
python3 ~/plugins/subagent-governance/scripts/apply_agents_block.py --execute
```

如果全局规则一致性检查失败，使用稳定发布源中的脚本查看目标路径、资产路径、受管理区间哈希和差异；不要改用开发仓库资产覆盖稳定规则：

```bash
python3 ~/plugins/subagent-governance/scripts/apply_agents_block.py --check --diff
```

脚本退出码为：`0` 表示一致或执行成功，`1` 表示 `--check` 发现内容差异，`2` 表示路径、权限、标记、读取或写入错误。脚本要求全局文件、资产文件及各自直接父目录属于当前用户、不是符号链接且不允许组用户或其他用户写入；执行时只替换受管理区间并保留其他用户规则。

当前工具支持三种安全状态：文件不存在时由 `--execute` 创建只含治理区间的新文件；文件存在但没有标记时在末尾追加治理区间；存在唯一合法标记区间时只替换该区间。重复、残缺或顺序错误的标记会停止执行；`--remove` 只移除治理区间并保留区间外的用户内容。

### 4. 验证与回滚

- 发布验收只能记录 `passed`、`failed` 或 `not_checked`；不能把仓库测试、trust hash 记录存在或 `codex plugin add` 返回 0 折算成真实验收成功。
- 先运行 `codex plugin list --marketplace personal --json`，记录 plugin ID、installed/enabled、Marketplace、稳定来源和目标完整版本。字段缺失或 Schema 不识别时记录 `not_checked`，不要猜测。
- 在新 Codex 任务中验证 Skill 和 Hook。已经打开的任务可能固定旧缓存，不能用于证明目标新版本已经加载。
- 在交互式 `/hooks` 中确认五个目标 Hook 的当前定义均为 enabled、trusted，且当前 `~/.codex/hooks.json` 没有旧 Hook 挂载。配置中的 trust hash 记录存在不等于当前定义已 trusted；未挂载的旧脚本路径可以暂时保留给已打开任务。
- 禁止使用 `--dangerously-bypass-hook-trust` 完成发布验收，也不要直接编辑 `config.toml` 中的 trust 记录。
- 用一个没有显式写 `$subagent-governance`、但确实适合只读子 Agent 的请求验证最小全局入口会先加载目标版本 Skill；随后派发一个 `light` 只读 smoke Agent，记录用户可见派发说明、Agent 标识、终态通知和父任务闭环。
- smoke 至少验证 PreToolUse、PostToolUse 和父任务 Stop；新任务启动提供 SessionStart 证据。SessionEnd 必须有实际事件或状态证据，不能仅凭关闭任务推定成功。
- 先运行 `scripts/check_installation.py` 检查当前运行安装；默认退出码只由目录隔离、稳定源/当前缓存、全局规则、缓存安全和旧独立 Hook 挂载决定。该脚本是只读文件系统检查，不替代活动任务字段预检或真实平台验收。
- 完成目标版本验证和 N-2 清理后，再运行 `scripts/check_installation.py --require-development-sync --require-retention-policy --expected-previous-version <升级前完整版本>`，要求开发治理规则已经进入稳定资产、只保留一份历史缓存，且该缓存确实是发布前记录的 N-1。
- 检查报告中的 `release_ready` 当前为 `null`；该脚本不替代版本/cachebuster、Git tag、候选副本、测试、validator 和安全审查组成的 release preflight。
- 检查脚本默认定位 `~/workspace/subagent-governance`；只有开发仓库位于其他路径时才传入 `--development-root`。
- 目标版本安装及真实加载验证通过后，只保留当前版本和升级前一个版本；N-2 及更早缓存可以清理，不再等待所有历史任务结束。清理动作必须发生在后置验证之后，并保留上一稳定发布备份；不要用符号链接代替缓存目录。
- 同样地，只有确认没有已打开任务固定引用旧独立 Hook 脚本路径后，才移动或删除该路径；安装检查以“是否仍被当前配置挂载”为严格门禁，而不是以文件是否存在为门禁。
- 只有 registration、deployment、Hook trust、目标 Skill、最小入口和生命周期 smoke 全部为 `passed` 时，才能记录 `release_acceptance_complete=passed` 并继续清理 N-2。
- 如果任一必需项为 `failed` 或 `not_checked`，停止发布收口和历史缓存清理。按以下顺序回滚：恢复上一稳定发布源；从原 Marketplace 重新选择或安装事务记录中的 N-1；确认 N-1 缓存与稳定源一致；使用恢复后的稳定版 `apply_agents_block.py --execute` 恢复上一版最小 Skill 入口；在 `/hooks` 中重新确认上一版定义的 trust；最后在新任务中重新完成 registration、Skill 和生命周期验收。不要把开发工作树直接用于运行，也不要通过修改 trust hash 伪造回滚完成。

建议为每次发布保存以下脱敏记录，不保存完整 prompt、业务输出或内部平台响应：

```text
target_version: <完整 Manifest version>
runtime_cache: <目标缓存绝对路径>
checked_at: <时间>
registration_verified: passed | failed | not_checked
deployment_verified: passed | failed | not_checked
hook_trust_verified: passed | failed | not_checked
skill_loaded_from_target: passed | failed | not_checked
global_entry_verified: passed | failed | not_checked
lifecycle_smoke_verified: passed | failed | not_checked
release_acceptance_complete: passed | failed | not_checked
evidence: <CLI 摘要、/hooks 状态摘要、任务或 Agent 引用>
```
