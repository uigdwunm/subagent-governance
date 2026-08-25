# Subagent Governance

[English](README.md) · [简体中文](README.zh-CN.md)

[![CI](https://github.com/uigdwunm/subagent-governance/actions/workflows/ci.yml/badge.svg)](https://github.com/uigdwunm/subagent-governance/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![状态：候选发布版](https://img.shields.io/badge/%E7%8A%B6%E6%80%81-%E5%80%99%E9%80%89%E5%8F%91%E5%B8%83%E7%89%88-F59E0B)](#发布状态)

**面向 Codex 原生子 Agent 的可靠生命周期治理。**

在不替代原生 `spawn_agent` 的前提下，让派发、精确目标绑定、等待、中断和完成状态变得明确、可诊断。

Subagent Governance 是一个本地 Codex 插件，面向已经使用原生子 Agent、但不希望依靠任务名、时间邻近、对话记录或猜测来判断身份和终态的开发者。它在原生 Agent 工具之外增加一层小型、可审计的协作协议，同时保留原生工具作为唯一执行通道。

## 发布状态

当前候选发布版为 `v0.4.0-rc.15`。Marketplace 入口固定到相同的不可变标签，因此安装结果可复现，同时包含 `v0.4.0-rc.14` 之后新增的生命周期与身份修复。

## 为什么需要它？

原生子 Agent 很有用，但当父 Agent 需要推断创建了哪个子 Agent、派发是否被正确认领、哪个终态事实可信，或者未知平台结果能否安全重试时，生命周期协作会变得脆弱。

Subagent Governance 将这些判断变为明确协议：

| 问题 | 治理行为 |
| --- | --- |
| 通过任务名、列表或最终回复推断 Agent 身份 | 只绑定当前原生 spawn 机械返回的 exact target |
| 重复或冲突的目标确认 | 保留首次绑定；相同事实幂等重放；冲突进入 reconcile |
| 父子 Agent 对完成状态理解不一致 | 在父任务关闭前记录精确观察和终态事实 |
| 消息、中断或平台结果未知 | 保留 `unknown`，不静默转换为成功或失败 |
| 普通原生派发遇到治理组件异常 | unmanaged `spawn_agent` 保持 fail-open 和 inert |

## 核心能力

- **精确身份**：受治理任务只绑定本次原生 spawn 机械返回的 exact target。
- **明确生命周期**：`prepare → claim → bind → terminal → close`，冲突或未知事实进入有界 reconcile。
- **TaskContract v2**：一个当前目标、允许范围、完成条件、证据、上下文和明确的派发配置。
- **可选材料验证**：可以在 prepare 和 claim 阶段验证声明的工作树文件或 Git 对象。
- **最小本地状态**：一个当前 Session ledger，不保存 prompt 档案或终态正文，已关闭任务有界保留。
- **只读恢复视图**：SessionStart 摘要、`status` 和 `diagnose` 不创建或修复状态。

## 快速了解

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

让 Codex 使用插件内置 Skill：

```text
使用 $subagent-governance 将这个任务派发给 Codex 原生子 Agent，
等待其终态通知，并关闭对应的治理任务。
```

Skill 会生成契约、向用户说明派发信息、把生成参数交给原生 `spawn_agent`、确认原生返回的精确目标，并只记录后续判断需要的最小生命周期事实。

## 安装

从已验证的发布提交创建并推送 `v0.4.0-rc.15` 标签后，使用以下命令添加 Marketplace 并安装插件：

```bash
codex plugin marketplace add uigdwunm/subagent-governance --ref main
codex plugin add subagent-governance@subagent-governance
```

随后重启 Codex、打开新 Session、调用 `$subagent-governance`，并在信任插件 Hook 前检查其定义。Codex 官方支持从 ChatGPT/Codex 的受支持界面浏览和安装插件；Codex CLI 可通过 `/plugins` 打开插件浏览器。

仓库开发与验证方式见 [CONTRIBUTING.md](CONTRIBUTING.md)。开发验证本身不构成修改已安装插件、Marketplace、Hook trust 或运行缓存的授权。

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

`objective`、非空 `scope` 和非空 `completion` 必填。`strict` profile 还要求明确的禁止范围和验收证据。普通 `context.paths` 只是定位提示；材料机械验证通过 `context.verified` 显式启用。

## 工作原理

每个 exact Codex Session 只有一个 `state-v9` ledger。一个受治理任务代表一个原生 Agent 生命周期，phase 只有：

```text
prepared | claimed | bound | terminal | closed | reconcile
```

当前 Session identity 和治理 CLI entrypoint 只来自同一次 SessionStart Hook 注入。父 Agent 原样提交生成的 spawn 参数，读取本次原生返回的 exact target，并立即确认。任务名、时间邻近、`list_agents`、transcript、summary 或 child final 都不能建立身份。

绑定后，父 Agent 可以记录精确平台观察、普通调用结果、终态通知、中断结果和显式关闭决定。相同事实重放幂等；冲突或未知事实保持可见，而不是触发自动重试或猜测终态。

完整状态机和存储边界见[当前架构](docs/architecture.md)、[减法收口 ADR](docs/architecture-reduction-adr.md)和 [runtime boundaries](skills/subagent-governance/references/runtime-boundaries.md)。

## 安全与隐私

- 核心 runtime 不主动发起网络请求，不包含遥测。
- 不持久化完整任务 prompt、消息正文、终态通知正文、业务结果、transcript 或 child final。
- 状态写入使用有界输入、文件锁、原子替换、权限检查和写后回读。
- 治理层不可用时，unmanaged 原生 spawn 继续 fail-open。
- runtime bundle 由机器 allowlist 构建，不包含测试、计划、部署工具和开发专用文件。

Subagent Governance **不是**沙箱、权限系统、远程控制平面、Hook trust 权威，也不是同一 OS 用户下不同进程之间的安全边界。Codex 仍负责批准、沙箱、工具授权、Hook 投递和模型行为。详见 [SECURITY.md](SECURITY.md)。

## 当前边界

- wait 调用不持久化。
- 不提供 managed business resume、managed follow-up、多 attempt 重试系统、Group 抽象或自动跨 Session 恢复。
- 原生 spawn 返回后、exact-target confirm 前崩溃时保持 `claimed/unbound`；插件不猜身份，也不自动重派。
- 未知消息、中断或平台结果继续保持 unknown，可能需要父 Agent reconcile。
- Codex MultiAgent V2 在本地 PreToolUse 边界暴露的是 opaque message，因此插件绑定派生 task ref 和可见 spawn 配置，不宣称提供明文消息证明。

## 验证情况

当前开发线包括：

- 96 个协议、状态、并发、生命周期、存储安全、打包和部署事务自动化测试；
- Ubuntu、macOS 和 Windows 上的 Python 3.11、3.12 CI；
- Plugin、Skill、archive、Schema、编译、lint 和 release-preflight 门禁；
- 真实 Codex 验收，覆盖受治理派发、exact-target 绑定、active wait 唤醒、双 Agent 并发、strict verified context、消息处理、中断、终态通知、close 和只读诊断。

本地测试不能证明所有平台故障模式。真实验收证据和明确的未验证边界记录在[平台验证](docs/platform-validation.md)和[当前真实平台验证](docs/validation/current-only-real-platform-validation.md)中。

## 项目文档

- [当前架构](docs/architecture.md)
- [上下文完整性契约](docs/context-completeness-contract.md)
- [中断与 reconcile](docs/interruption-reconciliation.md)
- [平台验证](docs/platform-validation.md)
- [发布流程](docs/release-process.md)
- [贡献指南](CONTRIBUTING.md)

## 许可证

[MIT](LICENSE)
