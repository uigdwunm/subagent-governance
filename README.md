# Subagent Governance

为 Codex 原生子 Agent 提供分级派发、生命周期跟踪、终态验收、状态恢复与诊断能力。

本项目只增强原生 `spawn_agent`，不引入第二套编排平台，也不依赖 OpenAI Agents SDK。

Codex 的原生子 Agent 调用可能在 Hook 运行前加密任务正文。因此插件采用双通道契约：完整任务说明仍放在 `message` 中交给子 Agent，治理等级同时通过 `task_name=sg_<mode>_<semantic_name>` 传递给 Hook。未使用前缀且正文不可见时，插件默认使用 standard 兼容模式。

## 目录角色

本机采用开发版与稳定运行版分离的结构：

| 角色 | 路径 | 用途 |
| --- | --- | --- |
| 开发仓库 | `~/workspace/subagent-governance` | Git/GitHub、开发、测试和评审 |
| 稳定发布源 | `~/plugins/subagent-governance` | Personal Marketplace 指向的已发布副本 |
| 当前运行缓存 | `~/.codex/plugins/cache/personal/subagent-governance/<version>` | 新任务实际加载的版本化缓存；老任务可能继续引用上一版本缓存 |

三个目录不得使用符号链接连接。修改开发仓库不会自动影响当前运行版；只有经过验证和显式发布，代码才会进入稳定发布源及运行缓存。

## 组件

- `.codex-plugin/plugin.json`：插件清单和 Codex UI 元数据。
- `hooks/hooks.json`：声明派发、启动、终态、恢复等生命周期 Hook。
- `scripts/subagent_governance.py`：治理状态机和诊断入口。
- `scripts/reinstall_preserving_caches.py`：调用官方插件重装命令，同时暂存并恢复老任务依赖的版本化缓存。
- `skills/subagent-governance/`：父 Agent 的治理等级选择与派发指南。
- `assets/agents-governance.md`：安装到全局 `AGENTS.md` 标记区间的规范化协作规则。
- `schemas/`：任务契约和终态结果协议。
- `tests/`：状态机与插件结构测试。

运行时还会观察 `list_agents` 的明确 `errored` 状态，将 provider 流故障记录为 `platform_error`，避免任务长期停留在假 `running`；插件只能诊断和辅助恢复，不能修复 provider 的流传输。

## 本地开发

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
python3 scripts/check_installation.py
```

## 发布原则

1. 只在开发仓库中修改代码。
2. 完成测试、Plugin 校验、Skill 校验和安全审查。
3. 确定正式版本号并创建 Git tag。
4. 将该 tag 对应的干净工作树复制到稳定发布源；不得直接把开发仓库配置成 Marketplace 源。
5. 在稳定发布源上再次运行 Plugin 和 Skill 校验。
6. 使用 `scripts/reinstall_preserving_caches.py` 调用 Codex 官方插件重装流程，在生成新缓存的同时恢复被官方命令清理的旧缓存。
7. 在新任务中验证新版本；验证通过前保留上一稳定缓存和回滚备份。
8. 即使验证通过，也不要删除仍可能被已打开任务引用的旧版本缓存；只在确认相关老任务全部结束后清理。

旧版本目录会由安装检查报告为 `retained_compatibility_caches`，它们是滚动升级兼容层，不等同于仍被挂载的 legacy Hook，也不会导致严格检查失败。未挂载但为老任务保留的 legacy 脚本路径同样只作信息报告；只有当前 `~/.codex/hooks.json` 仍引用它时才失败。普通开发检查只报告当前安装差异；发布验收使用 `python3 scripts/check_installation.py --require-clean`，任何稳定源/当前缓存不一致、不安全缓存条目、全局规则不匹配或 legacy Hook 仍被挂载都会返回失败。

详细发布流程见 [docs/release-process.md](docs/release-process.md)，改进路线见 [docs/optimization-plan.md](docs/optimization-plan.md)。
