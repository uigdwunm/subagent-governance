# Subagent Governance

[English](README.en.md) | 简体中文

面向 Codex 原生子 Agent 的生命周期治理插件，让派发、执行、等待、恢复和验收从“依赖上下文与口头约定”变成可说明、可追踪、可恢复、可验证的协作闭环。

本项目以 **Codex-first** 为设计原则，主要适配并验证以下原生能力：

- `spawn_agent`、`send_message`、`followup_task`、`interrupt_agent` 等 Codex 子 Agent 工具；
- Codex Skills 的按需规则加载和任务契约生成；
- Codex Hooks 提供的派发前门禁、Agent 生命周期和会话事件；
- Codex CLI 与 ChatGPT 桌面版中的 Codex 运行环境。

它增强原生 `spawn_agent`，不引入第二套编排平台，也不替代 Codex 的沙箱、批准机制、模型能力或父 Agent 的业务判断。

## 为什么需要它

复杂任务使用子 Agent 时，常见问题并不是 Agent 不够聪明，而是协作过程缺少稳定边界：任务交代不清、继承了无关上下文、父任务不知道该等多久、断流后重复派发、子 Agent 停止却没有可验收结果，或者上下文压缩后丢失了正在等待的任务。

Subagent Governance 在原生工具之上增加一层轻量治理，让父 Agent 和用户都能看懂：为什么派发、由谁执行、允许处理什么、怎样算完成、当前处于什么状态，以及下一步需要谁处理。

## 核心能力

| 能力 | 解决的问题 |
| --- | --- |
| 分级治理 | 使用 `light`、`standard`、`strict` 或 `auto`，让治理强度与任务风险匹配。 |
| 统一任务契约 | 明确唯一目标、范围、禁止事项、完成条件、模型、推理强度和上下文策略。 |
| 克制的上下文交接 | 显式选择隔离、有限继承或完整继承，减少旧指令和无关历史造成的任务漂移。 |
| 确定性派发与身份绑定 | 在正文不可见或生命周期事件迟到时，仍能把原生 Agent 精确关联到对应任务与 attempt。 |
| 有序等待与有限恢复 | 以终态通知为主，区分正常长耗时、平台断流、静默停止和真实阻塞；优先恢复原 Agent，限制自动重试。 |
| 显式通信和中断对账 | 区分普通消息、平台恢复、结果补交、业务继续和主动中断，避免未知结果被误判为成功。 |
| 结构化正式结果 | 子 Agent 提交完整结果、证据、剩余事项和建议下一步；自由文本停止不等于生命周期闭环。 |
| 父任务验收闭环 | 将执行完成、结果合法和父 Agent 接受分开，避免“代码写完了”被直接当成任务已验收。 |
| 无副作用诊断 | 只读查看 Session、任务、Agent 映射、待处理动作和组件健康，不通过诊断修复或改写状态。 |
| 轻量多 Agent 汇总 | 用 group 关联多个独立任务并计算材料是否齐备，但不建立 DAG、批处理器或第二套组状态机。 |

## 工作方式

```mermaid
flowchart LR
    A["用户目标"] --> B["治理等级与任务契约"]
    B --> C["Codex 原生 spawn_agent"]
    C --> D["Hooks 跟踪身份与生命周期"]
    D --> E["等待、通信、恢复或中断"]
    E --> F["结构化正式结果"]
    F --> G["父 Agent 验收与关闭"]
```

所有 individual task 始终是生命周期和业务结果的权威来源。group 只提供关联和派生视图，不拥有执行状态，也不生成 `AggregateResult`。

## 适用范围

- Codex CLI 或 ChatGPT 桌面版中的 Codex
- macOS、Linux 和 Windows
- Python 3.11 或 3.12

本插件主要针对 Codex 的原生子 Agent、Skills 和 Hooks 语义设计。其他 Agent 平台即使提供相似概念，也不属于当前兼容性承诺。

## 快速安装

从公开 Git-backed Marketplace 安装：

```bash
codex plugin marketplace add uigdwunm/subagent-governance --ref main
codex plugin add subagent-governance@subagent-governance
```

安装后：

1. 结束当前任务并新建一个 Codex 任务；插件 Skill 和 Hook 只在新任务中加载。
2. 在 Codex CLI 中运行 `/hooks`，审查并信任 `subagent-governance` 提供的七类 Hook。
3. 再新建一个任务，显式请求使用 `$subagent-governance` 派发一个只读子 Agent，验证派发说明、生命周期和终态闭环。

插件包含非 managed 生命周期 Hook。未经用户 review/trust 的 Hook 会被 Codex 跳过。

## 最小使用示例

```text
使用 $subagent-governance，以 light 模式派发一个只读 Agent，
检查 README 的安装步骤是否完整，并返回可核对的结论。
```

派发前，插件会向用户说明治理等级、模型、推理强度、上下文继承方式、任务范围和完成条件。执行期间父 Agent 按规范等待；发生平台断流时优先恢复同一个 Agent；完成后父 Agent根据结构化结果和证据进行验收。

治理等级：

- `light`：边界清楚、只读、短时、低风险任务。
- `standard`：普通编码、诊断、研究和 Review。
- `strict`：安全、生产、破坏性、并发写入或多阶段验收任务。
- `auto`：根据结构化任务特征机械选择等级。

## 数据、网络与隐私

- 核心运行时不主动联网，也不包含遥测或远程控制面。
- Marketplace 安装和升级由 Codex 自身完成，可能需要访问插件 Git 仓库。
- 治理状态和正式结果保存在 Codex 提供的当前用户本地插件数据目录中。
- 状态可能包含任务标识、Agent 映射、生命周期、有限任务元数据和正式结果；诊断不会转储完整任务正文或完整业务结果。
- 卸载不会自动删除插件数据和为旧任务保留的兼容缓存，用户确认不再需要诊断或回滚后再人工清理。

## 重要边界

- 本插件是协作治理层，不是安全沙箱。父 Agent、子 Agent 和本地 CLI 仍运行在 Codex 与当前操作系统用户授予的权限范围内。
- 插件不授予额外文件、网络或外部系统权限，也不绕过 Codex 的批准机制。
- Hook trust、事件投递、原生 Agent 身份和工具响应属于 Codex 平台边界；插件只能验证平台提供的可观察事实。
- 无 `sg_` 前缀的原生 spawn 按 unmanaged 兼容放行且不创建治理状态；受治理派发使用确定性任务名称和 PreparedContract 进行发送前门禁。
- 已打开的任务可能固定引用启动时的插件缓存。升级后应新建任务验证目标版本。

完整安全与报告边界见 [SECURITY.md](SECURITY.md)。

## 可选的全局按需入口

插件安装后已经可以显式使用 `$subagent-governance`。如果希望 Codex 在准备调用原生子 Agent 工具时自动加载本 Skill，可以把最小入口写入全局 `AGENTS.md`。

macOS/Linux：

```bash
python3 <installed-plugin-root>/scripts/apply_agents_block.py --execute
```

Windows PowerShell：

```powershell
py -3 <installed-plugin-root>\scripts\apply_agents_block.py --execute
```

脚本只管理带有 `subagent-governance` 标记的区间，不覆盖其他用户规则。该步骤是可选的，不影响显式调用 Skill。

## 升级与卸载

升级前先刷新 Marketplace：

```bash
codex plugin marketplace upgrade subagent-governance
```

为避免重装删除仍被旧任务引用的上一版本缓存，使用：

```bash
python3 <installed-plugin-root>/scripts/reinstall_preserving_caches.py \
  --previous-version <current-version>
```

Windows PowerShell 使用 `py -3` 运行同一脚本。升级后重新检查 `/hooks`，并在新任务中验证目标版本。

如果安装过可选全局入口，卸载前运行：

```bash
python3 <installed-plugin-root>/scripts/apply_agents_block.py --remove
codex plugin remove subagent-governance@subagent-governance
codex plugin marketplace remove subagent-governance
```

## 常见问题

- **Skill 可见但没有生命周期记录**：打开 `/hooks`，确认七类 Hook 已 review/trust，并检查 `[features] hooks = true`。
- **升级后仍加载旧版本**：结束旧任务并新建任务；旧任务可能继续使用启动时固定的缓存。
- **Windows 找不到 Python**：确认 `py -3 --version` 可用，并安装 Python 3.11 或 3.12。
- **全局入口安装失败**：脚本会拒绝符号链接、非普通文件和损坏的标记区间；按错误报告修复路径问题。

## 诊断与轻量 group

诊断入口纯只读，不创建、修复或改写治理数据：

```bash
python3 scripts/subagent_governance.py --diagnose --data-root /path/to/governance-data
python3 scripts/subagent_governance.py --diagnose --data-root /path/to/governance-data --session <session_id>
```

父 Agent需要关联多个 individual task 时，可以使用轻量 group：

```bash
python3 scripts/subagent_governance.py --upsert-group --session <session_id> --data-root /path/to/governance-data < group.json
python3 scripts/subagent_governance.py --read-group --session <session_id> --group-id <group_id> --data-root /path/to/governance-data
```

`summary_ready` 表示 required 成员的完整汇总材料齐备；`group_action_required` 表示 required individual task 仍有未完成处置。optional 成员不影响这两个信号。

## 开发与贡献

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py scripts/apply_agents_block.py scripts/check_installation.py scripts/reinstall_preserving_caches.py scripts/release_preflight.py
python3 scripts/release_preflight.py --mode development
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
```

- 贡献说明：[CONTRIBUTING.md](CONTRIBUTING.md)
- 版本变化：[CHANGELOG.md](CHANGELOG.md)
- 安全报告：[SECURITY.md](SECURITY.md)
- 真实平台验收摘要：[docs/platform-validation.md](docs/platform-validation.md)
- 维护者发布流程：[docs/release-process.md](docs/release-process.md)
- 实现路线与历史：[docs/optimization-plan.md](docs/optimization-plan.md)

## 许可证

本项目采用 MIT 许可证，详情见 [LICENSE](LICENSE)。
