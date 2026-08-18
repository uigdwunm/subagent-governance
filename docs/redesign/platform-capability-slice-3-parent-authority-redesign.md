# Slice 3 根因修复：父任务权威结果通道

## 决策

退役 attempt-scoped bearer credential 和 child CLI submit。使用父任务针对当前原生 child notification 的显式结果记录入口。

## 根因证据

真实 smoke 对照显示：

- unmanaged Agent 只收到平台原生处理后的消息并成功完成；
- governed Agent 的同类消息在 PreToolUse 后出现“平台处理内容 + 明文结果提交块”的组合，并连续报 `stream disconnected before completion: Upstream request failed`；
- 明文 bearer 同时进入本地 rollout，违背 secret never-at-rest。

因此问题不应继续按“网络不稳定”处理。插件在错误的阶段修改了原生 Agent message；给同权限子 Agent 发密码也没有建立真实安全边界。

报告不保存或复述任何真实 bearer 值。

## 实现变化

- StateStore format 4 删除 `result_credentials`、spawn/pending credential 引用和 ResultCredentialRecord。
- ResultRecord 用 `sender_target` 替代 `credential_id`。
- generator 在平台处理消息前写入公开 task/attempt 和 TaskResult 终态约束。
- PreToolUse 原样保留 spawn/followup native message。
- 新增 stdin-only `--record-child-result`。
- 删除 credential generation、hash、verify、install、revoke、expire、submit 和 relay 路径。
- 旧 `--submit-result` / `--relay-result` 返回 unsupported，不能写结果。
- format 3 迁移删除 credential material，不补造业务、identity 或 observation 事实。

## 固定不变量

1. 只有 `task_id + attempt + sender_target` 精确匹配才可记录。
2. sender target 必须等于该 execution 的 dispatch target。
3. TaskResult 内外 scope 必须一致并通过 strict Schema。
4. 已关闭或已中断 attempt 拒绝新内容；已提交同 digest 的只读重放仍幂等。
5. 不同内容不覆盖首份结果。
6. 结果记录不改变 observation/identity。
7. 不扫描 transcript、summary、历史 final text、`last_assistant_message` 或 Hook payload。
8. 缺失 child final 不生成业务结果，继续使用有界平台恢复。
9. 父 Agent 是明确权威，不宣称防御恶意父 Agent。

## 测试迁移

删除只证明 credential 生成、撤销和 secret hash 的旧专用测试，新增父任务结果通道测试，并把仍有业务价值的结果文件、并发、storage retry、post-commit readback、parent disposition、business resume 和 correction 覆盖迁到新入口。

重点矩阵：

- native message strict equality；
- exact sender 正向；
- wrong sender/task/attempt、closed/interrupted 负向且写前 no-op；
- 同 digest 幂等、异 digest 冲突；
- format 3 credential 清理；
- CLI 新旧入口边界；
- canonical Schema/runtime parity；
- Slice 1/2 dispatch、observation、CAS、recovery 和 fail-open 回归。

## 未检查

- provider restart、compact/resume、乱序通知和跨版本状态；
- provider 内部日志与消息处理面。

新测试插件 cachebuster、新任务真实 smoke，以及父 Agent 从当前原生通知取得精确 sender target 和完整 child final 的能力已经验证通过，详见下文“真实平台验收”。其余项目不由本地测试或本次 smoke 替代。

## 开发仓库验证

本轮最终本地门禁：

| 门禁 | 结果 |
| --- | --- |
| `python3 -m unittest discover -s tests -v` | 423/423，OK |
| `python3 -m compileall -q scripts tests` | PASS |
| Plugin validator | PASS |
| Skill validator | PASS |
| release preflight（由全量 unittest 覆盖） | PASS |
| 两独立 CLI 进程并发记录结果 | single winner/conflict，PASS |
| 仓库 JSON 解析 | 17/17，PASS |
| `git diff --check` | PASS |
| runtime credential writer/secret path 静态扫描 | PASS；只保留 format 3 清理、Schema 禁止字段、退役测试与历史报告语境 |

该阶段结论仅覆盖开发仓库：本实现具备新的独立复验条件。当时尚未部署测试 cachebuster，也未创建新的真实平台 smoke，不能据此宣称真实通知链路已通过。

## 独立复验收口

首次独立复验发现两个 blocker：format 2/3/4 的损坏 managed execution 会错误回退到 legacy migration；当前文档仍同时发布旧 credential GO 与一个未被 runtime 核对的 message digest 契约。

修复后：

- 只有无版本和 format 1 可以进入 legacy execution migration；format 2/3/4 缺少四平面时，read、no-op update 和直接 migration 均拒绝，输入对象与文件字节不变；
- PreparedContract 不再保存 message digest，PreToolUse 只核对 Hook 可稳定观察的 task name、model、reasoning effort 和 fork turns，并原样保留平台可能已变换的 message；
- 旧 credential 第三轮 GO 与真实 smoke 文档已标记 superseded/history，设计索引指向当前 parent-authority 实现；
- 主功能盘点、Skill 和 WP-06 已统一为父 Agent 根据当前原生终态通知调用 `--record-child-result`；新增静态文档回归防止旧 direct-submit 说法重新进入现行材料。

同一独立审查者完成三轮定向核验：首次 `NO-GO` 发现上述两项；第二轮确认迁移 blocker 关闭并定位两处残余现行文档；第三轮确认两个原 blocker 全部关闭，结论 `GO`，无新增范围内 blocker。

最终开发仓库准入：**GO，仅允许测试 cachebuster 与新建真实 Slice 3 smoke**。不等于稳定发布批准；真实 child final、精确 sender target、父任务记录结果、读取、验收和 closure 仍必须在重启后的新任务中验证。

## 测试部署

独立复验 `GO` 后，按本地测试流程部署候选 `0.4.0-rc.12+codex.20260815030436`：

- 稳定源备份：`<stable-source>/subagent-governance.backup-pre-parent-authority-20260815030436`；
- 当前运行缓存：`<runtime-cache>/subagent-governance/0.4.0-rc.12+codex.20260815030436`；
- 明确保留的上一版本：`0.4.0-rc.12+codex.20260815010308`；
- 重装事务：`reinstall_succeeded_pending_acceptance`，未清理历史缓存；
- `codex plugin list`：目标版本 installed + enabled，来源为独立稳定源；
- `check_installation.py --require-development-sync`：deployment in sync、路径分离、runtime healthy、上一缓存匹配；
- runtime SHA-256：开发仓库、稳定源和目标缓存均为 `decbc77866e104fd22ac0484de2296764d3eb1112e403a65f093f0eb77bbb9ee`；
- Skill SHA-256：三处均为 `e8540381b2f079a5cb7a47908538b2968f7ace5bb41a7b730aa93ed90f50952b`。

部署当时 Hook trust 未修改且仍为 `not_checked`，因此要求重启 Codex 并在当前项目中新建任务进行真实 smoke；该要求现已由下述独立任务完成。

## 真实平台验收

重启后创建独立任务 `Slice 3 父任务结果通道真实 Smoke`，使用 `gpt-5.6-terra/high`、`light` 治理和 `fork_turns=none`。唯一有效 Agent `sg_light_slice3_smoke_ack_t_b2b8a2d026eb` 通过原生终态通知返回完整 TaskResult；父任务以精确 sender target 调用 stdin-only `--record-child-result`，随后 `--read-result` 和 `--parent-disposition accept_result` 均成功。

最终状态为 `lifecycle=tombstoned`、`acceptance=accepted`、`action_required=false`、`tombstones=1`、`component_health=ok`。执行期间没有 stream disconnect、recovery 或 replacement，也没有 credential、密码、child submit、parent relay 或 PreToolUse message 改写。

第一次 preparation 因误用来源任务 session 被 PreToolUse 在原生 Agent 创建前安全拒绝；清理孤立 preparation 后使用测试任务当前 session 重新生成，没有产生额外 Agent 或错误投递。

完整证据见 [`docs/real-platform-test-2026-08-15-cachebuster-20260815030436-slice3-parent-authority-smoke.md`](../real-platform-test-2026-08-15-cachebuster-20260815030436-slice3-parent-authority-smoke.md)。

Slice 3 最终结论：**PASS，可进入 Slice 4**。这不是稳定发布批准；Hook trust、独立 Start/Stop 事件、parent Stop 以及 provider 内部日志面仍为 `not_checked`。
