# Subagent Governance

为 Codex 原生子 Agent 提供分级派发、生命周期跟踪、终态验收、状态恢复与诊断能力。

本项目只增强原生 `spawn_agent`，不引入第二套编排平台，也不依赖 OpenAI Agents SDK。

## 目录角色

本机采用开发版与稳定运行版分离的结构：

| 角色 | 路径 | 用途 |
| --- | --- | --- |
| 开发仓库 | `~/workspace/subagent-governance` | Git/GitHub、开发、测试和评审 |
| 稳定发布源 | `~/plugins/subagent-governance` | Personal Marketplace 指向的已发布副本 |
| 当前运行缓存 | `~/.codex/plugins/cache/personal/subagent-governance/<version>` | Codex 实际加载的版本化缓存 |

三个目录不得使用符号链接连接。修改开发仓库不会自动影响当前运行版；只有经过验证和显式发布，代码才会进入稳定发布源及运行缓存。

## 组件

- `.codex-plugin/plugin.json`：插件清单和 Codex UI 元数据。
- `hooks/hooks.json`：声明派发、启动、终态、恢复等生命周期 Hook。
- `scripts/subagent_governance.py`：治理状态机和诊断入口。
- `skills/subagent-governance/`：父 Agent 的治理等级选择与派发指南。
- `schemas/`：任务契约和终态结果协议。
- `tests/`：状态机与插件结构测试。

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
6. 使用 Codex 官方插件重装流程生成新的版本化缓存。
7. 在新任务中验证新版本；验证通过前保留上一稳定缓存和回滚备份。

详细发布流程见 [docs/release-process.md](docs/release-process.md)，改进路线见 [docs/optimization-plan.md](docs/optimization-plan.md)。
