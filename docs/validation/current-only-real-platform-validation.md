# P10-B 全新真实平台复验

日期：2026-08-24  
结论：`failed`（V4 的真实 business-resume PostToolUse / exact-list 绑定未闭环；依 P10 停止，未热修或重装）

## 基线与边界

- 独立新任务，当前 checkout 为 `46b13b7c9999aad51df5c20e6d6f7e0d5dbc1be7`，模型/推理为 `gpt-5.6-terra` / `high`。
- `codex plugin list` 实际显示 `subagent-governance@personal` 为 `installed, enabled`，完整版本 `0.4.0-rc.13+codex.20260824094559`。
- 只读安装检查通过：stable/cache digest 均为 `fc1ee1e029bca90e8cc4fd7a7179fb7f2df73dc0a372e2733899ffa5101255f3`，`runtime_healthy`、`deployment_in_sync`、`development_rules_in_sync`、`single_current_cache`、`installation_paths_separated` 均为 true。
- Codex registration 与 Hook trust 仍为 `not_checked`；未由文件、Skill 可见性或 `installed, enabled` 状态推断通过。
- 本次未修改运行代码、stable source、runtime cache、Hook trust、Marketplace、Registry 或 Manifest，未重装、发布、push 或 tag。

## 有界真实证据

- V1 unmanaged 原生 `spawn_agent` 的真实 target 为 `/root/p10_v1_unmanaged_probe`。实际 Hook 输出“无治理前缀，本次原生 spawn 按 unmanaged 放行；不创建治理状态”，child final 为 `P10_V1_UNMANAGED_OK`。
- V2 使用安装版脚本准备 task `sg-878396d7350b7b70007282ed2cd2fcd5`、attempt `1`、ref `e0efb549c586`、contract digest `3170e7e7088a0c9650a28f0a9e72b1ed7491135381f50166bd23c579a6abb3f0`。真实 spawn target 为 `/root/sg_light_p10_v2_governed_probe_t_e0efb549c586`；PreToolUse 消息确认已消费凭证并完成双门禁。
- 对 V2 已显式调用 `list_agents({"path_prefix":"/root/sg_light_p10_v2_governed_probe_t_e0efb549c586"})`，原生 response 顶层 `agents` 仅含该 completed target。随后的只读诊断确认 `dispatch.state=acknowledged`、`post_observed=true`、`target_bound=true`、`observation_record.source=list_agents`、identity confirmed。
- V3 的 installed-script normal-message preparation/真实 `send_message` 获 Hook claim 消息；诊断显示 pending 已收口。child final 以 exact sender 记录为 terminal notification；重放返回 `idempotent`，错误 sender 返回 `sender_target 与 dispatch target 不匹配`；parent `close_task` 返回 `closed`，诊断显示 tombstone 且 active identity 已清理。
- V4 source target 为 `/root/sg_light_p10_v4_resume_probe_t_35dea8c6c743`。attempt 1 的 exact list 先落账，再记录 exact terminal notification；诊断显示允许 `resume_business`。真实 `followup_task` 的 PreToolUse 输出为“已认领 business_resume pending_action 并绑定 tool_use_id”，child final 为 `P10_V4_RESUMED_OK`。随后对同一完整 target 的 exact list 返回 completed，但 attempt 2 的只读诊断仍为 `dispatch.state=claimed`、`post_observed=false`、`target_bound=true`、`observation_record.source=null`、`platform=not_checked`；因此该 list 不能作为 canonical observation。记录 attempt 2 exact terminal notification 后状态才确认 identity，不能反向补足 PostToolUse 或 exact-list evidence。

## V1–V7 结果

| 场景 | 状态 | 结论与边界 |
| --- | --- | --- |
| V1 插件/Hook 基线、unmanaged 放行 | `passed` | 真实 Hook allow/no-state、exact target 和 child final 均已观察。registration/Hook trust 的单独 UI 状态仍为 `not_checked`，不作为本项通过依据。 |
| V2 governed spawn、wait、exact identity | `passed` | 已真实 spawn/wait；exact `path_prefix` list 已落账为 `source=list_agents`，且 dispatch acknowledged/post-observed/target-bound 均为 true。 |
| V3 normal message、terminal notification、parent close | `passed` | normal-message pending 闭环、exact terminal notification、重放幂等、sender-mismatch 拒绝、tombstone/index cleanup 均有真实证据。 |
| V4 business resume | `failed` | follow-up 成功触发并收到 child final，但 attempt 2 的 PostToolUse 未写入；随后 exact list 未生成 `source=list_agents` observation。身份转移的必需闭环未通过。 |
| V5 interrupt 与受控对账 | `not_checked` | V4 correctness failure 后依 P10 停止；未创建 interrupt probe。 |
| V6 Stop、SessionStart、SessionEnd | `not_checked` | V4 correctness failure 后依 P10 停止；未将诊断或文件状态冒充 Session event/UI evidence。 |
| V7 restart/compact 恢复 | `not_checked` | V4 correctness failure 后依 P10 停止；未请求 UI 操作，也未用 fixture 替代。 |

## 后续与保留策略

本次不是 P10 complete 或 release-ready 结论。失败后保持安装环境原样；应在开发仓库新任务中最小复现 V4 的 `followup_task` PostToolUse / exact-list 绑定缺口，完成相应本地门禁后重新取得安装授权，并创建另一个全新 P10-B 任务从 V1 重新执行。不得在本对话热修、重装或继续 V5–V7。
