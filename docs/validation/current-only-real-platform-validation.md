# P10-B 与 P12-A 全新真实平台验证

日期：2026-08-24
结论：`failed`（V2 的真实 PostToolUse / canonical identity 闭环未成立；依 P10 停止，未热修或重装）

## 基线与边界

- 独立新任务 `01a0339e-f49b-7990-a5db-d70ca7dee6d9`，开发 checkout 为 `37a3c9a02712fc5bc4ff026d31fcb24b892e3e61`，模型/推理为 `gpt-5.6-terra` / `high`。
- `codex plugin list` 实际显示 `subagent-governance@personal` 为 `installed, enabled`，完整版本 `0.4.0-rc.13+codex.20260824114902`。
- 当时的只读安装检查通过：stable/cache digest 均为 `8d4f05e2b61bf62af6bb86c55d0f1b7ec05febbe33c4c50ed7df9204b4e1f004`，当时的 `runtime_healthy`、`deployment_in_sync`、`development_rules_in_sync`、`single_current_cache`、`installation_paths_separated` 均为 true。该历史字段已由 P13 的 `current_cache_present`、`current_cache_matches_stable` 和 `rolling_cache_set_valid` 替代。
- 新任务实际加载的 `subagent-governance` Skill 版本为 `0.4.0-rc.13+codex.20260824114902`；这与目标 runtime cache 版本相符。主机私有缓存绝对路径不写入可发布验证文档。
- Codex registration 与 Hook trust 的独立状态均为 `not_checked`：`codex plugin list` 只能证明 installed/enabled，安装检查也明确返回 `codex_registration_checked=false`、`hook_trust_checked=false`。实际 V1/V2 PreToolUse Hook 输出证明 Pre hook 正在处理这两次 spawn，但不替代独立 trust/registration 结论，也不证明 PostToolUse 投递。
- 本次未修改运行代码、Schema、Hook、Skill、stable source、runtime cache、Hook trust、Marketplace、Registry 或 Manifest；未重装、发布、push 或 tag。

## 有界真实证据

- V1 unmanaged 原生 `spawn_agent` 的真实 target 为 `/root/p10_v1_unmanaged_probe`。实际 Hook 输出为“无治理前缀，本次原生 spawn 按 unmanaged 放行；不创建治理状态”，child 终态标记为 `P10B_V1_UNMANAGED_OK`。
- V2 使用当前安装版脚本准备 task `sg-815f797136ec2b64b6d4103d53c7f6f1`、attempt `1`、ref `10b5d5b82ac3`、contract digest `6d50b00eafa4bfbd5c2942a809803d682d345936407592d01c782a8da5461dc8`。真实 spawn target 为 `/root/sg_light_p10_v2_governed_probe_t_10b5d5b82ac3`；PreToolUse 输出确认已消费凭证并完成双门禁，child 终态标记为 `P10B_V2_GOVERNED_OK`。
- 随后以完整 canonical target 实际调用 `list_agents({"path_prefix":"/root/sg_light_p10_v2_governed_probe_t_10b5d5b82ac3"})`，原生 response 顶层 `agents` 仅含该 completed target。安装版只读 diagnose 却显示 attempt 1 为 `dispatch.state=claimed`、`post_observed=false`、`target_bound=false`、target 为 null、`observation_record.source=null`、platform 为 `not_checked`。因此该原生 list 不能作为 canonical observation，且不以 child terminal 或 list completed 反推 Post receipt/identity 成功。

## V1–V7 结果

| 场景 | 状态 | 结论与边界 |
| --- | --- | --- |
| V1 插件/Hook 基线、unmanaged 放行 | `passed` | 新任务实际观察到 PreToolUse Hook allow/no-state、unmanaged exact target 和 child terminal。独立 registration/Hook trust UI 状态仍为 `not_checked`。 |
| V2 governed spawn、wait、exact identity | `failed` | Pre claim 和 child terminal 实际出现，但 PostToolUse 未收口，attempt 仍为 `claimed`/`post_observed=false`/`target_bound=false`；精确 list 亦未写入 `source=list_agents`。按 P10 停止。 |
| V3 normal message、terminal notification、parent close | `not_checked` | V2 correctness failure 后停止；未用 V2 的 child terminal 伪造 managed terminal notification。 |
| V4 business resume | `not_checked` | V2 correctness failure 后停止；没有复用旧 V4 Agent、session 或 state-v6/v7。 |
| V5 interrupt 与受控对账 | `not_checked` | V2 correctness failure 后停止；未创建 interrupt probe。 |
| V6 Stop、SessionStart、SessionEnd | `not_checked` | V2 correctness failure 后停止；未将诊断或文件状态冒充 Session event/UI evidence。 |
| V7 restart/compact 恢复 | `not_checked` | V2 correctness failure 后停止；未请求 UI 操作，也未用 fixture 替代。 |

## 后续与保留策略

本次不是 P10 complete 或 release-ready 结论。失败后保持安装环境原样；应在开发仓库新的修复任务中以 V2 的有界机械事实最小复现 PostToolUse/target binding 缺口，完成相应本地门禁后重新取得安装授权，并创建另一独立 P10-B 任务从 V1 开始重跑。不得在本对话热修、重装或继续 V3–V7。

---

# P12-A governed spawn PostToolUse 最小真实门槛

日期：2026-08-24
结论：`stopped_p12_b`（三次独立样本都没有保存关联到该 claim 的 Post 事实）

## 基线与只读安装复核

- 新的重启后独立任务以 `gpt-5.6-terra` / `high` 执行；开发 checkout 为 `188a63142cc563dba520a36c95d64bdcb70cf823`。此工作树处于 detached HEAD，未把分支名作为已验证事实写入本报告。
- 实际加载的 `subagent-governance` Skill 与已安装版本均为 `0.4.0-rc.13+codex.20260824133045`。`codex plugin list` 显示其为 `installed, enabled`。
- 只读安装检查通过：stable/cache digest 均为 `4f881c261e7fbcc8d23ed1313bccafee64d2c67cd795662874cff460ab8a0775`，`runtime_healthy`、`deployment_in_sync`、`development_rules_in_sync`、`current_cache_present`、`current_cache_matches_stable`、`rolling_cache_set_valid` 与路径隔离均为 true；保留一个兼容旧版本缓存。Codex registration 与 Hook trust 的独立结论仍为 `not_checked`。
- 本次没有安装、更新、发布或修改 stable source、runtime cache、Hook trust、Marketplace、Registry、运行时代码、测试、Schema 或 canonical state Schema。

## 三次最小样本

每个样本均为独立的 governed `spawn_agent`，light、isolated、无材料依赖，且模型/强度固定为 `gpt-5.6-terra` / `high`。探针不读取文件、不调用工具、不含业务内容。下表不含 tool-use ID、原始工具名、prompt、message、response、child final 或完整 envelope。

| 样本 | Pre marker | probe receipt | name / ID-match / admission | claim / shape / handler | canonical 基线 | child 事实（独立） |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `published` | `absent` | `not_recorded` | `not_recorded` | 仍为 Pre claim；未出现 recognized legacy Post transition | 已创建；终态单独收到 |
| 2 | `published` | `absent` | `not_recorded` | `not_recorded` | 仍为 Pre claim；未出现 recognized legacy Post transition | 已创建；终态单独收到 |
| 3 | `published` | `absent` | `not_recorded` | `not_recorded` | 仍为 Pre claim；未出现 recognized legacy Post transition | 已创建；终态单独收到 |

每次诊断均显示零条关联 probe receipt。child 创建或终态仅是独立平台事实，不作为 Post、same-ID 或 canonical identity authority。

## 决策与未验证项

这命中 P12-A 决策矩阵的“3 次均无 same-ID receipt、Pre marker 成功且 child 实际创建”。唯一结论是：**停止 P12-B**。可以且只能表述为：插件没有保存关联到这些 claim 的 Post 事实。该结果不能归因于平台未投递、Codex bug、工具名称漂移、缺失/不同 ID 或 Hook runtime 丢失。

因此仍未验证 PostToolUse 是否到达、其真实工具名/ID/envelope、handler 是否进入或失败在哪个阶段；也未验证 P10 的 V3–V7、Hook trust、Codex registration 或桌面 UI。没有读取或保存 child prompt、summary、final、transcript、message、业务正文、tool response 值或完整 envelope。

下一步只能在独立实施任务中清理 P12-A 的临时 runtime probe，并按 P12-A 退出策略恢复不含 probe 的测试安装；该清理需要其自身的本地门禁和用户重新授权的安装流程。不得实施 P12-B、matcher-only 或 storage/handler 定点修复。
