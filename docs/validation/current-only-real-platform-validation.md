# state-v9 独立重启后真实平台验证

日期：2026-08-25  
结论：`failed`（V2 的 parent explicit exact-target confirm 进入 `reconcile`；依 correctness failure 停止）

## 基线、加载与独立状态

- 开发 checkout 为 `87f03570eafd6a1cd435f2bb92dfeb560e2a94e2`，工作树在开始验证时干净；期望且实际加载版本均为 `0.4.0-rc.13+codex.20260825035757`。实际 Skill 从该版本 runtime cache 读取。
- exact session identity 为 `01a03722-0244-7c32-82e7-0a2f52b52d3b`。验证使用 `gpt-5.6-terra` / `high`；受治理 child 使用 `fork_turns=none`。
- `codex plugin list` 显示 installed/enabled，仅作为安装可见性证据。失败后的只读 `hooks/list` 已独立确认当前 PreToolUse handler 为 `modified`：`currentHash=sha256:307fb66cae3e00fbcec4eb69f5227cb5f993a8583698df6bc6829330f9465081`，保存的 `trusted_hash=sha256:d2eedfe914bd63b8e1ebc1c872ee51f1a6ee221b4fa62a062dec61e602c95aff`。Codex registration 与桌面 UI 仍为 `not_checked`；不以 installed/enabled 或路径存在替代。
- 原验证任务没有修改 runtime、schema、Skill、stable source、runtime cache、Marketplace、Registry 或 Hook trust；仅产生验证所需的当前 exact-session v9 ledger 状态。

## V1–V7 结果

| 场景 | 状态 | 最小有界证据 |
| --- | --- | --- |
| V1 unmanaged spawn、fail-open、零治理状态 | `passed` | 原生 spawn 机械返回 exact target，child 给出独立终态；前后 status/diagnose 都显示本 session 为 `state_format_version=9` 且 `tasks=[]`。child final 不作为 identity authority。 |
| V2 prepare → governed Pre gate → native spawn → explicit confirm | `failed` | 当前 runtime prepare 后，本次 native spawn 的 exact target 被原样立即提交 `confirm-dispatch`；返回 `reconcile`。task id/ref 与 exact target 机械一致；代码分支复核证明旧 `dispatch_identity_mismatch` 实际由 confirm 时 phase 不是 `claimed` 触发。结合当前 Pre handler 的 `modified` trust 状态，原记录中的 Pre 阶段不能证明 durable claim 已写入 exact ledger。不以 child final、task name、时间或 list 补绑。 |
| V3 wait 与 exact bound-target observation | `not_checked` | V2 correctness failure 后停止；没有未绑定 target 的 observation。 |
| V4 normal message、terminal notification、minimal interrupt、parent close | `not_checked` | V2 correctness failure 后停止；未以 child terminal 构造 managed terminal fact。 |
| V5 exact-session SessionStart/status | `not_checked` | 仅执行了 CLI 的 exact-session 只读 status/diagnose；没有可归因于本次任务的 SessionStart 实际事件证据。 |
| V6 restart / compact | `not_checked` | V2 correctness failure 后停止。 |
| V7 Hook trust、Codex registration、桌面 UI、exact session identity | `failed_partial` | 当前 Pre handler 的 trust status 已只读确认为 `modified`；Codex registration 与桌面 UI 仍为 `not_checked`。exact session identity 已记录为 `01a03722-0244-7c32-82e7-0a2f52b52d3b`，不作为其他状态的替代证据。 |

## 验证命令与后续边界

- 只读基线：`git status --porcelain=v1`、`git rev-parse HEAD`、`codex plugin list`、当前 runtime 的 `--status` / `--diagnose`。
- 实际 V2 动作：当前 runtime 的 `--prepare-dispatch`、原生 `spawn_agent`、随后同一 task/ref 与该次 exact target 的 `--confirm-dispatch`；终态只读 `--diagnose`。
- 开发仓库最小复现使用同一 task id/ref 和 exact target 形状，证明：`claimed` fact 存在时 exact confirm 正常绑定；只有 `prepared` fact 时旧实现错误分类为 `dispatch_identity_mismatch`。本地修复改为 `dispatch_claim_missing` reconcile/no-bind，没有放宽 identity，也没有恢复推断或自动恢复机制。
- 用户随后明确授权部署与 Hook trust。部署前通过 Codex app-server `hooks/list` 取得当前最小 Hook 的 exact key/hash，并按 Codex TUI 使用的 `config/batchWrite` 语义写入后回读：PreToolUse `sha256:307fb66cae3e00fbcec4eb69f5227cb5f993a8583698df6bc6829330f9465081` 与 SessionStart `sha256:26915f4009c66b621d5a67739e8b7300d3bd462017bd31b72411317cf638cf45` 均为 `trusted`。这只证明两个当前 Hook 的信任状态；Codex registration 与桌面 UI 仍为 `not_checked`。
- 修复部署完成后当前任务必须停止并等待重启；新的独立任务从 V1/V2 重新取证。V2 修复后的真实行为及 V3–V7 仍未验证。

---

# P10-B 与 P12-A 全新真实平台验证（历史 v8 基线）

> 以下保留减法收口前的真实平台证据，不描述或替代当前 state-v9 runtime 的结果。

---

# P12-A probe cleanup 安装后重启复验

日期：2026-08-25  
结论：`completed_scoped_baseline`（cleanup 的开发—安装—重启—新任务闭环完成；P12-B 继续冻结，P10 V2 的 Post/canonical identity 未闭环仍是已知真实边界）

## 只读安装与加载来源

- 开发 checkout 为 `dbad9eb903c188614d5739f21b0bd291e5db80fa`，并只读确认它包含 cleanup 提交 `4c2567e` 与本次 cachebuster 提交 `dbad9eb`。
- 新任务实际加载的 `subagent-governance` Skill 和 `codex plugin list` 的 installed/enabled 版本均为 `0.4.0-rc.13+codex.20260825004015`；执行配置为 `gpt-5.6-terra` / `high`。
- `check_installation.py --require-development-sync` 通过：stable/current digest 均为 `7c6409be936130bcd9e384203273ed5e7cb6a6b30a9fa80ab37aa884e74eea92`，`runtime_healthy`、`deployment_in_sync`、`development_rules_in_sync`、`current_cache_present`、`current_cache_matches_stable`、`rolling_cache_set_valid` 与路径隔离均为 true；兼容缓存数为 1，版本为 `0.4.0-rc.13+codex.20260824133045`。
- Codex registration 与 Hook trust 的独立结论仍是 `not_checked`。本次未安装、重装、发布或改写 stable source、runtime cache、Hook trust、Marketplace、Registry、runtime、schema 或测试。

## V1–V2 最小真实基线

| 场景 | 状态 | 脱敏机械证据与结论 |
| --- | --- | --- |
| V1 unmanaged 原生 spawn | `passed` | PreToolUse 明确按 unmanaged fail-open 放行且不创建 governed state；child 给出独立终态。收到新增超时对账要求后，对完整 native target 做一次 exact `list_agents`，结果为唯一 completed。child final 不是 Post 或 identity authority。 |
| V2 light / isolated governed spawn | `failed_boundary_confirmed` | 当前安装 Skill 成功 prepare，PreToolUse 消费凭证并完成双门禁，真实 child 完成，规范 wait 结束，exact `list_agents` 返回唯一 completed。只读 canonical/diagnose 仍为 `dispatch.state=claimed`、`post_observed=false`、`target_bound=false`，`observation_record.source=null`。终态登记按精确 sender/dispatch-target 规则被拒绝，因为 canonical 尚无 dispatch target。 |

- 最初一次会话不匹配的 native 调用在 PreToolUse 硬门禁前被拒绝，未创建 child；未复用该凭证，且不计入 V2 样本。
- V2 的严格结论仅为：**Post/canonical identity 未闭环**。不得由此推断平台未投递、Codex bug、工具名或 ID 漂移，或 handler/storage 原因；exact list、时间、task name 和 child terminal 均不作为 owner 或 Post authority。
- 依既定停止策略，本次没有执行 V3–V7，也没有激活或实施 P12-B。

## cleanup 专项

- current runtime 不存在 `scripts/governance_spawn_post_probe.py`，且其 `scripts/` 与 `skills/` 不再引用 P12-A marker/receipt 目录或 probe runtime；只读 diagnose 没有 `spawn_post_probes` 投影。
- 对历史目录只做了前后元数据摘要：marker 目录存在、含 3 个顶层条目、目录 mtime/size 前后一致；receipt 目录前后均不存在。未读取业务内容，未删除、迁移或改写任何历史 probe/state/cache 数据。
- current Pre、recognized Post 与 unknown catch-all 实现均已不含退役 probe 路径；结合历史目录前后元数据不变，可确认本次没有创建或更新 `spawn-post-probe-ids-v1` / `spawn-post-probes-v1` 数据。以上不以历史数据是否存在来推断事件投递。

## 未验证项

- PostToolUse 是否到达、真实工具名/ID/envelope，以及 handler 的进入或失败阶段；P12-B activation evidence 仍未取得。
- P10 的 V3–V7、独立 Hook trust/registration 和桌面 UI 状态。

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

随后已在独立实施任务中完成 P12-A 临时 runtime probe 的开发仓库 cleanup，并通过其本地门禁；三次真实验证证据保持原样，未被改写为成功。cleanup 没有读取、迁移、清理或重写机器上的历史 probe 目录，也没有安装、更新、发布或写入 stable source、runtime cache、Hook trust、Marketplace 或 Registry。

下一步只能在用户重新授权后按 P10-A 安装不含 probe 的测试版、等待重启，并创建新的独立任务从 V1 开始验证。不得直接宣称插件环境已恢复，不得实施 P12-B、matcher-only 或 storage/handler 定点修复；P12-B 继续冻结。
