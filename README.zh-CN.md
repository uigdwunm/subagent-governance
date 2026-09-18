# Subagent Governance

[English](README.md) · [简体中文](README.zh-CN.md)

[![CI](https://github.com/uigdwunm/subagent-governance/actions/workflows/ci.yml/badge.svg)](https://github.com/uigdwunm/subagent-governance/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![状态：稳定版](https://img.shields.io/badge/%E7%8A%B6%E6%80%81-%E7%A8%B3%E5%AE%9A%E7%89%88-2EA44F)](#发布状态)

**面向 Codex 原生子 Agent 的可验证交接与生命周期治理。**

保留原生 Codex 作为唯一执行层，同时让任务交接、声明材料的新鲜度、精确目标绑定、等待、中断和完成状态变得明确、可诊断。

Subagent Governance 是一个本地 Codex 插件，面向已经使用原生子 Agent、但不希望依靠任务名、时间邻近、对话记录或猜测来判断身份和终态的开发者。它在原生 Agent 工具之外增加一层小型、可审计的协作协议，同时保留原生工具作为唯一执行通道。

交接指导支持由强主模型作关键判断和最终验收、由合适的低成本子模型执行有界任务。明确契约和可恢复验收依据为这种分工提供支持，不要求父子使用相同模型。降低合格交付的总成本仍是未经证实的设计目标；受测模型组合及其边界见下方验证说明。

## 发布状态

当前稳定版为 [`v0.5.3`](https://github.com/uigdwunm/subagent-governance/releases/tag/v0.5.3)，Marketplace 固定到同一不可变标签。本补丁让 closed 历史淘汰同时考虑 512 条任务上限和字节上限：有可淘汰历史时为新任务腾位，全部未关闭时仍安全拒绝且不改写原账本。上述改动已通过本地检查；重启后的真实验收与成本收益评测尚未执行。

**升级边界：** state-v12 不读取、迁移或删除旧账本。升级前先结束已有受治理任务，随后重启 Codex 并使用新 Session；新摘要为空不证明旧任务已完成。近期独立 macOS 验证覆盖 standard 身份绑定和 strict 消息到最终回复的往返，详见[带日期的证据与未验证边界](docs/validation/current-only-real-platform-validation.md)。

## 它为原生 Codex 增加了什么？

原生 Codex 继续创建并执行每一个子 Agent。Subagent Governance 只在这些原生动作外增加一层本地协议：

| 原生 Codex 动作 | 本插件增加的治理 |
| --- | --- |
| 父 Agent 通过原生 `spawn_agent` 派发任务 | 强制提供一个当前目标、非空范围和可验证完成条件 |
| 原生 spawn 返回目标 | 只绑定本次机械返回的 exact target，不根据名称、列表、时间、transcript 或最终回复推断身份 |
| 父 Agent 选择任务上下文 | 可选在 prepare 和 claim 两个阶段验证声明的工作树文件或 Git 对象 |
| 父 Agent 等待、发送消息、中断并观察完成 | 记录明确的 `prepare → claim → bind → terminal → close` 生命周期 |
| 平台结果无法确认 | 保留 `unknown`，冲突事实进入 reconcile，不猜测或静默重试 |
| 普通原生派发未受治理 | unmanaged `spawn_agent` 保持 fail-open 和 inert |

## 核心能力

- **精确身份**：受治理任务只绑定本次原生 spawn 机械返回的 exact target。
- **明确生命周期**：`prepare → claim → bind → terminal → close`，派发未知及冲突进入 reconcile；已绑定调用的 unknown 单独保留，后续确定终态可正常收尾。
- **TaskContract v2**：一个当前目标、允许范围、完成条件、证据、上下文和明确的派发配置。
- **可选材料验证**：可以在 prepare 和 claim 阶段验证声明的工作树文件或 Git 对象。
- **本地治理状态**：一个当前 Session ledger，保存派发准备、原始业务契约和生命周期事实，已关闭任务有界保留。
- **只读恢复视图**：SessionStart 摘要、`status` 和 `diagnose` 不创建或修复状态。
- **可恢复的验收依据**：运行时有界保留原始业务契约，包括设计背景和证据要求；上下文丢失后可按精确任务读取，仍由父任务核对实际结果是否合格。

## 有证据支持的保护

仓库测试和真实 Codex 验收覆盖了三类实际保护：派发前发现显式声明任务材料的变化、在并发工作中保持 exact-target 身份，以及在平台结果无法确认时保留未知状态且不自动重试。这些机制在不替代原生 Codex 执行的前提下，旨在减少可避免的过期材料工作、错误目标跟进和重复动作。

完整的复现条件、证据来源、实际作用和结论边界见[原生 Codex 子 Agent 治理证据](docs/native-codex-governance-evidence.md)。

## 安装

使用以下命令从 `v0.5.3` 标签添加 Marketplace 并安装插件：

```bash
codex plugin marketplace add uigdwunm/subagent-governance --ref v0.5.3
codex plugin add subagent-governance@subagent-governance
```

随后重启 Codex、打开新 Session，并在信任插件 Hook 前检查其定义。Codex 官方支持从 ChatGPT/Codex 的受支持界面浏览和安装插件；Codex CLI 可通过 `/plugins` 打开插件浏览器。

仓库开发与验证方式见 [CONTRIBUTING.md](CONTRIBUTING.md)。开发验证本身不构成修改已安装插件、Marketplace、Hook trust 或运行缓存的授权。

## 5 分钟上手

直接用自然语言描述任务即可，不需要记忆命令，也不需要点名 Skill：

```text
把这个任务交给一个原生子 Agent：

检查当前项目的测试入口，并给出推荐运行的测试命令。
只读检查，不要修改文件；等待它完成后汇报证据，并收尾对应任务。
```

这个请求涉及原生子 Agent 的派发、等待和完成验收，因此插件内置 Skill 会自动应用治理流程：

```text
TaskContract v2
      │
      ▼
prepare ──► native spawn claim ──► exact-target confirm
                                         │
                                         ▼
                         wait / message / interrupt
                                         │
                                         ▼
                              terminal fact ──► close
```

Skill 会生成契约、说明派发信息、把生成参数交给原生 `spawn_agent`、确认原生返回的精确目标、等待终态证据并关闭治理任务。只有当前客户端无法自动选择 Skill 时，才需要显式调用 `$subagent-governance` 作为备用入口。

## 常见问题

### 这个插件如何帮助管理 Codex 原生子 Agent？

每个子 Agent 仍由原生 Codex 创建和执行。本插件只在这些原生动作外增加明确任务契约、可选声明材料验证、exact-target 绑定、生命周期记录和终态证据。

### 需要显式调用 `$subagent-governance` 吗？

通常不需要。涉及派发或协调原生子 Agent 的自然语言请求应自动选择插件内置 Skill；只有当前客户端无法自动选择时，才需要显式调用作为备用入口。

### verified context 能证明什么？

它只证明 `context.verified` 中显式声明的工作树文件或 Git 对象在 prepare 和 claim 阶段保持匹配。它不会扫描整个工作区，也不能证明父 Agent 已声明全部必要材料。

### Codex 结果无法确认时会怎样？

派发结果未知或身份／终态冲突进入 reconcile。已绑定任务的消息、中断或平台观察 unknown 记录为有界 unknown_facts，任务仍可接纳后续确定终态；关闭后保留未知回执。本插件不会自动重发、重新派发或把旧回执改为成功。

## TaskContract v2

```json
{
  "profile": "standard",
  "objective": "实现一个当前目标",
  "scope": ["允许范围"],
  "forbidden_scope": [],
  "completion": ["可验证完成条件"],
  "evidence": [],
  "context": {
    "summary": "必要背景",
    "paths": ["scripts/example.py"]
  },
  "spawn": {
    "fork_turns": "none",
    "model": null,
    "reasoning_effort": null
  }
}
```

`objective`、非空 `scope` 和非空 `completion` 必填。`strict` profile 还要求明确的禁止范围和验收证据。普通 `context.paths` 是规范的相对 POSIX 路径提示；绝对位置及相对路径基准放入 `context.summary`，材料机械验证通过 `context.verified` 显式启用。

## 工作原理

每个 exact Codex Session 只有一个 `state-v12` ledger。一个受治理任务代表一个原生 Agent 生命周期，phase 只有：

```text
prepared | claimed | bound | terminal | closed | reconcile
```

当前 Session identity 和治理 CLI entrypoint 只来自同一次 SessionStart Hook 注入。父 Agent 原样提交生成的 spawn 参数，读取本次原生返回的 exact target，并立即确认。调用者提交的短任务名、时间邻近、`list_agents`、transcript、summary 或 child final 都不能建立身份。`collaboration_turns` 机械返回的完整 canonical `task_name` 是精确目标；仅在所选原生接口提供 `agent_id` 时使用该字段。返回值必须原样保留。

绑定后，父 Agent 可以记录精确平台观察、普通调用结果、终态通知、中断结果和显式关闭决定。相同事实重放幂等；冲突或未知事实保持可见，而不是触发自动重试或猜测终态。

完整状态机和存储边界见[当前架构](docs/architecture.md)、[减法收口 ADR](docs/architecture-reduction-adr.md)和 [runtime boundaries](skills/subagent-governance/references/runtime-boundaries.md)。

## 安全与隐私

- 核心 runtime 不主动发起网络请求，不包含遥测。
- 在 state-v12 中，`prepared/claimed` 记录保存完整生成派发消息、规范化任务契约和材料校验元数据。后续阶段转换移除 prepared capability，但保留 `contract_summary`，即除 `spawn` 外的完整业务契约，用于恢复验收依据。
- runtime 不专门归档外部材料正文、后续普通消息、终态通知正文、业务结果、transcript 或 child final。主动填入契约字段或关闭原因的文字仍会保存；没有自动脱敏。
- prepared 过期阻止新的 claim，不删除记录。未关闭记录不自动清除；closed 记录在账本写操作中最多保留最新 64 条；新增任务使总条数超过 512 或超过 3 MiB 准入线时，还会按关闭时间、创建时间、任务 ID 的升序淘汰最旧完整 closed 记录，并返回 `pruned_task_ids`。淘汰与插入同事务，准入失败不改写原账本；没有定时删除服务。state-v12 不读取、迁移或删除旧账本。
- 默认 `status/diagnose` 包含目标和关闭原因；精确任务 status 还返回完整业务契约。SessionStart 不注入完整契约。spawn Hook 故障诊断使用固定说明，不能据此承诺所有输出均不含业务文字。
- 存储位置与输出边界详见[当前架构](docs/architecture.md#存储位置与输出边界)。
- 状态写入使用有界输入、文件锁、原子替换、权限检查和写后回读。
- 治理层不可用时，unmanaged 原生 spawn 继续 fail-open。
- runtime bundle 由机器 allowlist 构建，不包含测试、计划、部署工具和开发专用文件。

Subagent Governance **不是**沙箱、权限系统、远程控制平面、Hook trust 权威，也不是同一 OS 用户下不同进程之间的安全边界。Codex 仍负责批准、沙箱、工具授权、Hook 投递和模型行为。详见 [SECURITY.md](SECURITY.md)。

## 当前边界

- wait 调用不持久化。
- 不提供 managed business resume、managed follow-up、多 attempt 重试系统、Group 抽象或自动跨 Session 恢复。
- 原生 spawn 返回后、exact-target confirm 前崩溃时保持 `claimed/unbound`；插件不猜身份，也不自动重派。
- 已绑定调用的 unknown 与 phase 分别记录；父 Agent 仍需核实业务结果是否满足投递未知的追加要求。
- prepare 显式冻结 `collaboration_turns` 或 `fork_context` 原生适配器。Hook 校验生成的 task name 和派发配置，不逐字比较平台重写后的消息；fork_context 需要可见消息标记，collaboration_turns 可用显式 task_name 定位。身份／配置不可验证、输入形状未知或内部不可读时透传，不建立 claim。

## 验证情况

按证据来源区分验证范围：

- 仓库检查覆盖协议、状态、跨进程并发、生命周期、存储安全、打包和部署事务，以及编译、lint、coverage 和 release/archive preflight。
- CI 在 Ubuntu、macOS、Windows 上运行 Python 3.11、3.12 自动化测试；顶部徽章链接到实际运行结果。
- 独立 state-v12 macOS 任务验证了 standard 派发、原生 canonical target 绑定、terminal/close，以及 strict 随机令牌消息到最终回复的往返；父任务与子 Agent 均为 `gpt-5.6-terra/high`。

最新[异构验收](docs/validation/heterogeneous-real-acceptance-2026-09-17.md)覆盖 Astra/high 父任务与 Terra/high 子任务的正常交付、真实消息、模拟缺陷接管，以及子任务终态后的 compact 恢复。受测为本机安装成 0.5.0 的 `c968fb1`，并非最终 v0.5.1 标签；未覆盖 `fork_context`、真实 unknown、restart、执行中的 compact 或成本收益。早期证据保留为历史记录。详见[本地验收](docs/validation/current-only-local-acceptance.md)和[带日期的平台证据](docs/validation/current-only-real-platform-validation.md)。

## 项目文档

- [当前架构](docs/architecture.md)
- [原生 Codex 子 Agent 治理证据](docs/native-codex-governance-evidence.md)
- [上下文完整性契约](docs/context-completeness-contract.md)
- [中断与 reconcile](docs/interruption-reconciliation.md)
- [平台验证](docs/platform-validation.md)
- [发布流程](docs/release-process.md)
- [贡献指南](CONTRIBUTING.md)

## 许可证

[MIT](LICENSE)
