# P10-B current-only 真实平台验证

日期：2026-08-24  
结论：`partial_validation_failed_at_v1`（完全退出并重新打开 Codex App 后，真实 PreToolUse 仍引用已不存在的 `rc.14` Hook 路径；没有热修、重装或绕过 Hook）

## 对象、授权边界与开始复核

- 验证任务为 P10-A 安装之后新建的独立 Codex 任务，执行配置为 `gpt-5.6-terra` / `high`。
- 开发 worktree 的 HEAD 是授权起点 `9875b60`（`chore: create P10-A2 test cachebuster`）。`9875b60` 位于 `codex/current-only-improvements` 历史中；本 worktree 当前为 detached HEAD，未修改分支指针。
- 目标 Manifest full version 是 `0.4.0-rc.13+codex.20260824083357`。开发 worktree、稳定测试源与 runtime cache（`…/subagent-governance/0.4.0-rc.13+codex.20260824083357`）均为不同的普通目录，非 symlink。
- `check_installation.py --require-development-sync` 实际返回 `runtime_healthy=true`、`deployment_in_sync=true`、`development_rules_in_sync=true`、`single_current_cache=true`、`installation_paths_separated=true`；stable/cache digest 同为 `c2ec653e8065d04dbc43668bf5ca2ffb8faef3a6943cd7fc66d4adfacc16eadb`。
- `codex plugin list` 实际列出 `subagent-governance@personal` 为 `installed, enabled`，版本为目标版本。该检查仍显示 `codex_registration_checked=false` 与 `hook_trust_checked=false`；未从文件状态推断为已验证。
- 本次只修改开发仓库中的本报告与 `docs/platform-validation.md`。未修改稳定源、cache、Hook trust、Marketplace、Registry、AGENTS、runtime/Schema/Skill/tests，未重装、发布或打 tag。

## 真实平台阻断事实

在确认 Codex App 已完全退出并重新打开后，V1 使用已加载的 `$subagent-governance` Skill 进行了一个安全的 unmanaged 原生 `spawn_agent`：task name 为 `p10b_unmanaged_probe`（无 `sg_` 治理前缀），`fork_turns=none`，模型为 `gpt-5.6-terra` / `high`。子任务仅被允许返回固定标记 `P10B_UNMANAGED_PROBE_OK`；禁止调用工具、访问文件、读写、派发或通信。该调用未创建 native target、tool-use 或治理状态。平台在 PreToolUse 直接拒绝，实际工具响应为：

```text
Tool call blocked by PreToolUse hook: python3: can't open file '…/subagent-governance/0.4.0-rc.14+codex.20260824014336/scripts/subagent_governance.py': [Errno 2] No such file or directory. Tool: collaborationspawn_agent
```

- 这发生在 App 重启后的当前独立任务，是实际原生工具和 Hook 交互，而不是 fixture、手工运行 router 或源码推断。
- cache 父目录只含目标 `rc.13` version；不存在报错中的 `rc.14` cache。因此新进程仍保留旧 Hook command/path 的平台级缓存或注册状态。
- 这违反了 unmanaged native spawn 应被 fail-open 放行、且不建 managed state 的真实平台预期。依据 P10 缺陷处理规则，立即停止本场景和后续场景；不通过直接编辑 Hook trust/cache、修改 runtime 或再次安装来绕过。

## V1–V7 结果

| 场景 | 状态 | 实际证据与边界 |
| --- | --- | --- |
| V1 插件/Hook 基线、unmanaged 放行 | `failed` | `codex plugin list` 和安装检查确认目标文件版本/单 cache/digest 健康；但重启后真实 unmanaged `spawn_agent` 仍在 PreToolUse 被不存在的 `rc.14` 路径阻断。无 target/tool-use/state；unknown/unmatched 零写入和成功 fail-open 均未取得。 |
| V2 governed spawn、wait、exact identity | `not_checked` | V1 已暴露会阻断全部受 Hook 管理 native spawn 的路径不一致；依 P10 停止，未伪造 TaskContract/PreparedContract 的 Hook claim 或 native response。 |
| V3 normal message、terminal notification、parent close | `not_checked` | 没有真实 managed target；未发送受治理消息、未记录通知，也未关闭 task。 |
| V4 business resume | `not_checked` | 没有 exact terminal notification，未调用 `followup_task`。 |
| V5 interrupt 与对账 | `not_checked` | 没有可安全中断的真实 managed Agent，未调用 `interrupt_agent`。 |
| V6 Stop、SessionStart、SessionEnd | `not_checked` | 观察到的只有本轮真实 PreToolUse 阻断。没有安全方式在不破坏当前父任务的情况下取得 action-required 状态；未将 Skill 加载或文件存在冒充 Session 事件证据。 |
| V7 restart/compact 恢复 | `not_checked_platform_unavailable` | 当前任务无法自主安全触发 Codex UI restart/compact，且在修复 Hook 路径不一致前也无法保留 managed Agent 或 work item。没有使用 fixture 替代。 |

## 后续与重新验证条件

本次不是 P10 完成，也不是 release-ready 结论。需要父任务或用户进一步处理 Codex 平台实际仍加载旧 `rc.14` PreToolUse command 的原因（包括确保已运行实例、Hook/插件注册配置都指向目标完整版本；不得直接编辑 trust/cache）。只有在新的开发修复/部署流程完成、重新取得安装授权并新建另一个独立 P10-B 任务后，才能从 V1 重新验证 V1–V7。
