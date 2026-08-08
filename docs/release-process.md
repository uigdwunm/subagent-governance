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
2. 单元测试、Python 编译、Plugin validator、Skill validator 全部通过。
3. 可执行代码变更已经完成安全审查。
4. Manifest 使用新的正式版本号，并在提交与打 tag 前生成唯一 Codex cachebuster。
5. 已记录回滚目标和上一稳定缓存路径。
6. 全局 `AGENTS.md` 中的标记区间与 `assets/agents-governance.md` 完全一致。

## 建议步骤

### 1. 在开发仓库验证

```bash
cd ~/workspace/subagent-governance
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
python3 ~/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py .
```

cachebuster 生成后需要重新运行上述校验，再提交、推送并创建 tag。发布副本必须来自该 tag，避免稳定发布源在导出后再次发生未入库修改。

### 2. 生成干净发布副本

从已提交的 Git tag 导出到临时目录，校验后再替换稳定发布源。不要使用符号链接，也不要从带未提交修改的工作树直接复制。

推荐使用 `git archive` 生成发布内容：

```bash
git archive --format=tar <tag> | tar -xf - -C <临时发布目录>
```

替换稳定发布源属于发布操作，必须保留上一版本备份并使用明确的绝对路径。

### 3. 更新 Codex 缓存

稳定发布源就位后，使用 tag 中已经生成的 cachebuster 通过保留缓存的包装器重装：

```bash
python3 ~/plugins/subagent-governance/scripts/reinstall_preserving_caches.py
```

该脚本实际调用 `codex plugin add subagent-governance@personal`，但会先把当前所有版本化缓存快照到缓存目录之外，重装后再恢复被 Codex 清理的旧目录。异常中断留下的快照会在下次运行时优先恢复；同名目录内容冲突时停止并保留快照，不覆盖任何一方。

不要手工修改 Marketplace 或 Codex-owned Hook 信任哈希。

Codex 任务在启动时会固定其 Hook 命令，其中可能包含当时版本缓存的绝对路径。原生 `codex plugin add` 会清理旧缓存，因此不能绕过上述包装器直接重装；否则仍打开的老任务会在后续 `Stop`、`SubagentStop` 等阶段因脚本路径不存在而报错。旧缓存只服务于已打开任务；新任务仍从当前 manifest 对应的新缓存加载。

使用插件内脚本把规范化协作规则应用到全局标记区间：

```bash
python3 ~/plugins/subagent-governance/scripts/apply_agents_block.py --execute
```

### 4. 验证与回滚

- 在新 Codex 任务中验证 Skill 和 Hook。
- 确认七个 Hook 均为 enabled、trusted，且当前 `~/.codex/hooks.json` 没有旧 Hook 挂载。未挂载的旧脚本路径可以暂时保留给已打开任务。
- 运行 `scripts/check_installation.py --require-clean` 检查目录隔离、稳定源/当前缓存、全局规则和旧 Hook 残留；`retained_compatibility_caches` 只作信息报告。
- 只有确认所有引用旧版本的任务均已关闭后，才可清理对应旧缓存。清理前保留发布备份；不要用符号链接代替缓存目录。
- 同样地，只有确认没有已打开任务固定引用 legacy 脚本路径后，才移动或删除该路径；安装检查以“是否仍被当前配置挂载”为严格门禁，而不是以文件是否存在为门禁。
- 如果验证失败，恢复上一稳定发布源和缓存，不把开发工作树直接用于运行。
