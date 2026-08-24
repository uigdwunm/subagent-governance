# P10-B current-only 真实平台验证

日期：2026-08-24  
结论：`partial_validation_failed_at_v1`（新建独立任务中的真实 Hook 路径不一致；没有热修、重装或绕过 Hook）

## 对象、授权边界与开始复核

- 验证任务为安装后新建的独立 Codex 任务（session 标识已按证据最小化原则省略）；执行配置为 `gpt-5.6-terra` / `high`。
- 开发 worktree 的 HEAD 是 `b687422c4de15aef988801da66683795723ba9dc`（`chore: create P10 test cachebuster`），它由 `codex/current-only-improvements` 包含；父提交为 `16cb883…`。对应安装任务提交 `9ef12e15500236d6693371d7a347770a19a2aa5a` 也解析为同一变更和父提交。P9 已在该 cachebuster 前的 `937edbd…` 基线通过。
- 只读复核的 target Manifest full version：`0.4.0-rc.13+codex.20260824081325`。授权的稳定测试源和该版本的唯一 runtime cache 均可见且相互独立。
- `check_installation.py --require-development-sync` 返回 `runtime_healthy=true`、`deployment_in_sync=true`、`development_rules_in_sync=true`、`single_current_cache=true`、`installation_paths_separated=true`；stable/cache digest 都是 `a447a01694e88c1263970f1e7029d53bcd3a6be9c5e0d5b5e362b8991d7924d8`。
- `codex plugin list` 实际列出 `subagent-governance@personal` 为 `installed, enabled`，版本为目标版本。该检查仍显示 `codex_registration_checked=false` 与 `hook_trust_checked=false`；未从文件状态推断为已验证。
- 本任务只创建/更新本报告和 `docs/platform-validation.md`。未修改稳定源、cache、Hook trust、Marketplace、Registry、AGENTS、runtime/Schema/Skill/tests，未重装、发布或打 tag。

## 真实平台阻断事实

使用当前安装版本的 `$subagent-governance` Skill 后，V1 尝试了一个安全的 unmanaged 原生 `spawn_agent`：无治理前缀、`fork_turns=none`、`gpt-5.6-terra` / `high`，子任务被要求不调用工具、不读写文件并只返回一个固定标记。该调用未创建 native target 或 tool-use；平台在 PreToolUse 直接拒绝，有限错误为：

```text
python3: can't open file '.../subagent-governance/0.4.0-rc.14+codex.20260824014336/scripts/subagent_governance.py': [Errno 2] No such file or directory
```

- 真实 UI/Hook 现象：Codex 工具界面显示 `Tool call blocked by PreToolUse hook`，所以这不是 fixture、手工调用 router 或单纯文件推断。
- cache 父目录只含目标 `rc.13` version；不存在报错中的 `rc.14` cache。只读搜索还在历史 install transaction 中找到 `rc.14` 作为 previous/target 记录，但未改动它。
- 目标 cache 的只读 `--diagnose --session` 在失败后仍显示 `data_root_exists=false` 和 `session_missing`。因此本任务没有因 V1 尝试而写入 managed task、PreparedContract 或 state-v6 session。
- 这违反了 unmanaged native spawn 应被 fail-open 放行、且不建 managed state 的真实平台预期。依据 P10 缺陷处理规则，立即停止本场景和后续场景；不通过直接编辑 Hook trust/cache、修改 runtime 或再次安装来绕过。

## V1–V7 结果

| 场景 | 状态 | 实际证据与边界 |
| --- | --- | --- |
| V1 插件/Hook 基线、unmanaged 放行 | `failed` | 目标版本在 `codex plugin list` 可见且安装 digest 健康，但真实 unmanaged `spawn_agent` 在 PreToolUse 被不存在的 `rc.14` hook 路径阻断。无 target/tool-use/state；unknown/unmatched 零写入只取得失败后的诊断事实，未能取得成功放行证据。 |
| V2 governed spawn、wait、exact identity | `not_checked` | V1 已暴露会阻断全部受 Hook 管理 native spawn 的路径不一致；依 P10 停止，未伪造 TaskContract/PreparedContract 的 Hook claim 或 native response。 |
| V3 normal message、terminal notification、parent close | `not_checked` | 没有真实 managed target；未发送受治理消息、未记录通知，也未关闭 task。 |
| V4 business resume | `not_checked` | 没有 exact terminal notification，未调用 `followup_task`。 |
| V5 interrupt 与对账 | `not_checked` | 没有可安全中断的真实 managed Agent，未调用 `interrupt_agent`。 |
| V6 Stop、SessionStart、SessionEnd | `not_checked` | 观察到的只有本轮真实 PreToolUse 阻断。没有安全方式在不破坏当前父任务的情况下取得 action-required 状态；未将 Skill 加载或文件存在冒充 Session 事件证据。 |
| V7 restart/compact 恢复 | `not_checked_platform_unavailable` | 当前任务无法自主安全触发 Codex UI restart/compact，且在修复 Hook 路径不一致前也无法保留 managed Agent 或 work item。没有使用 fixture 替代。 |

## 后续与重新验证条件

本次不是 P10 完成，也不是 release-ready 结论。需要在新的开发修复任务中先复现并修复“enabled/current plugin 仍调用不存在 cache version 的 Hook command”这一安装/注册路径一致性缺陷，完成相关 P1–P9 门禁；随后重新取得安装授权，并新建另一个独立 P10-B 任务。修复后应重新验证 V1–V7（包括真实 UI restart/compact；若仍需用户操作，应由用户在 UI 执行后提供继续验证机会）。
