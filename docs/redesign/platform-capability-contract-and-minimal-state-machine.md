# 平台能力契约与最小状态机

## 设计结论

插件只治理 Codex 原生子 Agent，不替换 `spawn_agent`，不建立第二套调度平台，也不把 Hook 描述成平台内部安全边界。

状态机只保存四类互不替代的事实：

1. dispatch：父任务是否准备、认领并观察到原生调用响应；
2. observation：平台是否对精确 native target 给出 active、terminal、error 或缺失观察；
3. result：父任务是否根据当前原生 child notification 记录了严格 TaskResult；
4. closure：父任务是否验收、拒绝、选择或关闭。

平台错误不是业务失败；拿到结果不确认 runtime identity；Agent terminal 不等于结果 complete；子 Agent 声明 complete 不等于父任务验收通过。

## 平台能力边界

插件可依赖原生 Agent 工具和 Hook、PreparedContract、StateStore、精确 target 的平台观察、父任务收到的当前原生 child final notification，以及父任务显式调用的本地 CLI。

插件不可宣称：`SubagentStart` 能精确绑定 attempt；`SubagentStop` 自带官方 TaskResult；transcript 或 summary 完整可靠；Hook 能修复 provider 网络；本地密码能防御同权限父 Agent；不可靠 running 位能安全硬阻断 parent Stop。

## 派发状态

每个 execution 由 `task_id + attempt + task_ref` 标识。发送前必须存在唯一 PreparedContract，并核对 Hook 可稳定观察的 task name、model、reasoning effort 和 fork turns。平台可能在 Hook 前变换 message，因此 PreToolUse 不比较 message digest，也不改写 native message；任务正文由 generator 在平台处理前生成。

spawn 响应只记录 dispatch observation。只有精确 canonical target 的平台观察才能写 exact-bound observation；alias、同名、唯一候选、active index 或 broad query 都不能提升权威。

Slice 4 只准入有限 `list_agents` observation adapter：读取 PostToolUse 顶层 JSON 对象或 JSON 字符串中的顶层 `agents`，不递归读取 `content`、`structuredContent`、summary、final-history 或 transcript。非空响应必须满足 `path_prefix == agent_name ==` 唯一 canonical dispatch target；状态只接受真实已见的字符串或单标签对象。错 scope、多 target、多标签、未知或 malformed 输入不建立 exact-bound 强事实。

可靠 not-created 可进入同 attempt retry；unknown 或已出现 canonical positive observation 的迟到 failure 进入 reconcile。恢复与 retry 都有固定上限。

## 结果状态

generator 在原生消息加密前写入公开 `task_id + attempt` 和 TaskResult 字段要求。子 Agent 最终回复只输出一个 TaskResult JSON。

Slice 5 只强化 producer/feedback 的词汇消歧，不增加 authority：initial dispatch、`result_correction` 和 `business_resume` 共用同一 TaskResult reply renderer，并从 canonical `business_result` 机器枚举渲染 `complete | blocked | failed | needs_decision`。业务完成使用 `complete`；`completed` 只属于平台 terminal observation，不是合法业务结果。validator 对非法值从同一机器枚举列出合法集合并说明平面差异，但不接受 alias、不自动修 JSON，也不从 summary、transcript、history、Hook 或 observation 生成结果。

父 Agent 只处理当前原生 child notification，并从 stdin 调用：

```bash
python3 scripts/subagent_governance.py --record-child-result --session <session_id>
```

envelope 固定为：

```json
{
  "sender_target": "/root/<exact-native-agent-target>",
  "task_id": "sg-...",
  "attempt": 1,
  "task_result": {}
}
```

固定验证顺序：envelope 和 scope、strict TaskResult Schema、精确 task/attempt、sender 与 dispatch target 相等、attempt 未关闭、canonical digest、结果文件原子写入回读、StateStore 锁内关联。

同一 Agent 可顺序复用多个 attempt，所以绑定权威是 `task_id + attempt + sender_target` 精确三元组，不要求 sender target 在历史中全局唯一。

相同 digest 重放幂等；不同 digest 不覆盖首份结果，只写 conflict digest 和首次时间。存储错误不生成业务 `failed`。结果记录不修改 observation 或 identity。

父 Agent 是结果记录权威，不宣称防御恶意父 Agent。不得扫描 transcript、summary、历史 final text、`last_assistant_message` 或 Hook payload，不得从不完整回复重建结果。

## 结果与父处置

- `complete`：进入 `acceptance_status=pending + parent_action=accept_result`；
- `blocked`：进入 `parent_action=decide_disposition`；
- `failed`：进入 `parent_action=decide_disposition`；
- `needs_decision`：进入 `parent_action=ask_user`。

父处置固定为 `accept_result | reject_result | close_task | select_attempt`。accept/reject 只处理 current complete/valid/available/pending；close/select 不自动调用 interrupt，返回精确 targets 后由父任务显式执行。

## 生命周期与恢复

通信、platform recovery、result correction、business resume 和 interrupt 都先创建单一 pending action，再由 PreToolUse 原子认领、PostToolUse 按 tool_use_id 对账。success、failed、unknown 三态不得互相替代。

平台断流后先用 exact target 对账；明确 error 且无业务结果时恢复同一 Agent/attempt；恢复次数有界，最后一次需用户授权；耗尽后停止，不创建无限 followup 或伪造结果。replacement 必须显式接受 duplicate risk，并受 two-candidate cap 约束。

## 状态格式 4

canonical task root 只包含 `managed + task_id + work_item + executions`。execution 固定包含 DispatchRecord、ObservationRecord、ResultRecord、ClosureRecord。

format 4 删除所有 result credential 容器和引用；format 3 迁移只删除旧 credential material，不补造业务、身份或观察事实。只有无版本和 format 1 可以走 legacy execution migration；format 2/3/4 的 managed execution 缺失任一四平面记录时直接拒绝且不重写。未知版本同样不重写。

## 关闭与诊断

`action_required` 是从 canonical executions 派生的只读责任视图，不持久化。`observation_record.fresh_until` 在 format 4 固定为 JSON `null`；当前没有 active TTL、刷新事件或跨重启保证，因此 exact `observed_at/running` 也不能形成 future freshness authority。

parent Stop 对 canonical action-required 只返回有界 advisory 并固定 `continue=true`。StateStore 不可读时同一次最多三读，全部失败后告警 fail-open；身份未确认、Start/Stop/结果缺失、exact running 或旧 running 位都不形成 hard gate。Stop 不写 StateStore，也不验收业务结果。

诊断只读，不创建数据根、不加锁、不 reconcile、不修复、不输出完整结果正文。tombstone 精确保留 7 天；正式结果只按确定性引用清理。

## 真实平台验收

Slice 3 最新 parent-authority 真实 smoke 已验证 native message 未被 Hook 改写、current child final 与 exact sender 可达，以及父任务 record/read/accept/tombstone 闭环。Slice 4 最新真实 smoke 已验证顶层 exact `agents` 单标签 terminal shape、`fresh_until=null`、terminal 不生成业务结果，以及同 Agent correction 后的父任务正式结果闭环。Slice 5 最新真实 smoke 已验证唯一 Agent 的第一次 TaskResult 使用合法 `complete` 和数组字段，无 correction 即完成 record/read/accept/tombstone；同时证明平台 `completed` 没有映射为业务 `complete`。

平台能力 Slice 1-5 已在最终综合验收中收口，Slice 6 裁决为 `NO-SLICE`。该结论只覆盖当前本地开发仓库与上述真实 smoke 已实际观察的范围，不等于 release-ready 或稳定发布批准。真实 running observation、独立 Start/Stop Hook、parent Stop UI、Provider restart/compact/resume、Hook trust、跨版本状态和发布面仍为 `not_checked` 或平台边界。
