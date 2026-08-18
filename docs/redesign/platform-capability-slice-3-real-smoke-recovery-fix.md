# Slice 3 真实 smoke 恢复收敛修复

> **状态：历史记录。** 本文的有限恢复状态机证据仍保留，但其中 bearer credential、child submit/parent relay 和旧测试候选均已被父任务权威结果通道替代，不再代表当前 Slice 3 的测试流程或准入结论。当前方案见 `platform-capability-slice-3-parent-authority-redesign.md`。

## 结论

开发仓库本地修复 **PASS**，测试候选 `0.4.0-rc.12+codex.20260815010308` 已部署，并在 Codex 重启后的新任务中完成真实恢复链路验证。真实 smoke 暴露的“第一次恢复已消耗，但 exact error 未进入最后一次授权状态”已稳定复现、修复并在真实平台关闭。

本次新 smoke 的 initial、第一次自动恢复和用户授权的第二次最终恢复均发生 `stream disconnected before completion: Upstream request failed`。插件正确完成两次有限恢复、精确对账并收敛为 `recovery_count=2 + recovery_status=exhausted`，没有第三次恢复、替代 Agent、伪造结果或残留 pending。由于子 Agent 三次都未完成正式 result submit，Slice 3 的 credential-backed child submit、父验收和 closure 仍未通过真实平台验证，因此 Slice 4 继续 **NO-GO**。

## 真实证据

测试 Session `01a002bb-ff1c-71a2-a325-2cf9d88115a9` 的 task `sg-c59adaf565bca7ef63fee0f6d989c089` 出现以下顺序：

1. initial Agent 被 exact `list_agents` 报告 errored；
2. 第一次 `platform_recovery` 已认领，`recovery_count=1`，原生调用观察为 success；
3. 未观察到中间 Start/running，同一 canonical target 再次被 exact `list_agents` 报告 errored；
4. raw StateStore 仍保留 `last_lifecycle_operation.call_observation=success`，同时 `recovery_status=null`；
5. 用户明确授权最后一次恢复后，`--prepare-communication --authorize-recovery` 被 `_has_unresolved_lifecycle()` 拒绝，诊断显示 `action_required=true` 但 `allowed_actions=[]`。

没有绕过门禁、没有调用未准备的 `followup_task`，也没有手工修改该 smoke StateStore。

修复后的新真实 smoke 使用 Session `019ff979-63ed-7750-b217-99e8302522dd`、task `sg-7a3123edd33481b04d0783d6d236b250`、attempt `1` 和唯一 canonical target `/root/sg_light_slice3_recovery_fix_smoke_t_79ea832efa5a`：

1. initial Agent 断流，exact target-only `list_agents` 记录 `platform_observation=error`；
2. 第一次自动 `platform_recovery` 被准备、PreToolUse 认领并投递，同一 Agent 再次断流；
3. exact target-only 对账后，raw StateStore 为 `recovery_count=1`、`recovery_status=awaiting_authorization`、`parent_action=ask_user`，且没有 stale `pending_action` 或 `last_lifecycle_operation`；
4. 未授权 preparation 被正确拒绝；用户明确授权后，第二次也是最后一次恢复被准备、认领并投递；
5. 最终恢复再次断流，exact target-only 对账后收敛为 `recovery_count=2`、`recovery_status=exhausted`、`parent_action=ask_user`，`pending_action=null`、`last_lifecycle_operation=null`；
6. `--read-result` 明确拒绝，原因是正式结果尚未处于 `valid + available`；credential 保持 `issued`，没有 submission、business result、acceptance、closure 或 tombstone。

本次真实 smoke 没有第三次恢复、replacement、parent relay、手工 StateStore 修改或从 final/transcript/summary 重建结果。完整记录见 `docs/real-platform-test-2026-08-15-cachebuster-20260815010308-slice3-recovery-fix-smoke.md`。

## 根因

`list_agents=error` 原逻辑只有在 compatibility projection 的 `execution_status=running` 时才推进恢复状态。恢复调用 success 后若没有 Start，canonical observation 仍为 error，projection 因而是 `not_started`。后续更强的 exact error 虽更新了观察时间，却没有：

- 解决旧的 success/unknown recovery lifecycle；
- 按 `recovery_count` 写 `awaiting_authorization|exhausted`；
- 把父动作推进到 `ask_user`。

准备门禁随后先看到 unresolved lifecycle 并拒绝，形成有责任但无合法动作的死状态。

## 冻结不变量

- recovery 调用 success/unknown 只证明原生调用观察，不证明 Agent 已恢复。
- 只有原样 exact canonical `path_prefix == response agent_name == dispatch_target` 的 error 可以解决该 recovery lifecycle。
- exact error 不要求此前出现 Start/running；恢复次数才决定下一状态。
- `recovery_count=1` 时进入 `awaiting_authorization + ask_user`；用户授权后只允许第二次也是最后一次恢复。
- `recovery_count=2` 时进入 `exhausted + ask_user`，不得产生第三次恢复。
- broad、wrong、missing、alias、zero/multiple canonical match 继续 no-op；平台错误不得生成业务结果或消费 result credential。

## 修改

- `scripts/subagent_governance.py`：exact error 对账识别同 target 的 success/unknown `platform_recovery` lifecycle，清除已被新事实解决的记录，并按恢复次数推进状态。
- `tests/test_communication_lifecycle.py`：新增 success 直达 error 的完整两次预算测试，以及 unknown 直达 error 的收敛测试。
- `docs/project-function-inventory.md`、`docs/redesign/D4-platform-recovery-boundary.md`、`docs/redesign/S4-platform-recovery-session-closure-implementation.md`、`skills/subagent-governance/SKILL.md`：同步不变量和事件顺序。

Schema 字段、枚举和持久化形状未变化，因此不修改 Schema。

## 验证

- 修复前最小回归：稳定失败，`recovery_status` 实际为 null，期望 `awaiting_authorization`。
- 新增事件顺序测试：2/2 PASS。
- communication/wait/Hook 聚焦回归：101/101 PASS。
- full unittest：442/442 PASS。
- `scripts/` 与 `tests/` Python compile：PASS。
- Plugin validator：PASS。
- Skill validator：PASS。
- 仓库 JSON parse：PASS。
- `git diff --check`：PASS。
- 真实失败 StateStore 临时回放：PASS；进入 `awaiting_authorization`，已授权最后一次恢复 preparation 成功，原始文件 SHA-256 前后不变。

## 测试部署

- target version：`0.4.0-rc.12+codex.20260815010308`；
- stable backup：`<stable-backup>`；
- runtime cache：`<runtime-cache>`；
- previous cache `0.4.0-rc.12+codex.20260814155846` 保留，未执行历史清理；
- 开发仓库、稳定源和目标缓存的 runtime SHA-256 均为 `c2fa5d415decd71bc3376fbb47e8683c2841555fc489cd047e80bfa5e1427eba`；
- `codex plugin list` 显示目标版本 installed/enabled；
- `check_installation.py` 显示 `deployment_in_sync=true`、`installation_paths_separated=true`、`runtime_healthy=true`；
- 全局治理入口与稳定资产一致；Hook trust 未检查、未修改。

## 未检查

- 网络稳定时 child 显式 submit、父验收和 closure 是否完整走通；
- 平台/provider 是否记录 updatedInput 或目标 prompt。

已确认新 cachebuster 在重启后的新任务中加载，第二次授权恢复也已在真实平台完成 preparation、PreToolUse claim 和原生投递。剩余项目必须在平台连接能够维持到子 Agent 完成时通过新的真实 smoke 验证，不能由本地 fixture 替代。
