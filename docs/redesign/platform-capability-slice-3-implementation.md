# Slice 3 父任务权威结果通道实现记录

## 结论

Slice 3 已从“子 Agent 持 bearer 调 CLI 提交”改为“父 Agent 根据当前原生子 Agent 终态通知记录结果”。旧方案会在 PreToolUse 阶段修改已经进入平台处理的 Agent message；真实 smoke 中，该修改表现为加密消息后追加明文提交块，并与受治理 Agent 连续断流稳定相关。旧 bearer 也进入了本地 rollout，违反 secret never-at-rest 目标。

新方案不生成密码、不保存 hash、不要求子 Agent 访问插件 CLI，也不通过 Hook 改写 native message。

## 当前流程

1. generator 在原生消息加密前写入公开的 `task_id + attempt`、任务契约和 TaskResult 字段要求。
2. PreToolUse 只认领 PreparedContract、核对参数并原样返回 native input。
3. 子 Agent 最终回复只输出一个严格 TaskResult JSON 对象。
4. 父 Agent 只处理当前原生子 Agent 终态通知，取得该通知对应的精确 sender target。
5. 父 Agent 将 `sender_target + task_id + attempt + task_result` 从 stdin 交给：

```bash
python3 scripts/subagent_governance.py --record-child-result --session <session_id>
```

6. 插件校验并保存首份权威结果；父 Agent 再通过 `--read-result` 和 `--parent-disposition` 验收、接受、拒绝或关闭。

## 输入协议

```json
{
  "sender_target": "/root/<exact-native-agent-target>",
  "task_id": "sg-...",
  "attempt": 1,
  "task_result": {
    "task_id": "sg-...",
    "attempt": 1,
    "business_result": "complete",
    "result": "...",
    "evidence": [],
    "remaining": [],
    "suggested_parent_next_step": "..."
  }
}
```

只允许这四个 envelope 字段。TaskResult 继续由 `schemas/task-result-v1.schema.json` 严格约束。

## 权威与边界

- 机械绑定是 `task_id + attempt + sender_target` 三元组；`sender_target` 必须原样等于该 execution 的 `dispatch_record.dispatch_target`。
- 同一 Agent 可在连续 business-resume attempt 中复用，因此不要求 sender target 在整个任务历史中全局唯一。
- 父 Agent 是记录入口的明确权威。本方案不宣称密码学防御恶意父 Agent；父 Agent 本来就能修改本地状态、代码和验收决定。
- 不扫描 transcript、summary、历史 final text、`last_assistant_message` 或 Hook payload。
- 不从自然语言、不完整 JSON 或缺失回复重建 TaskResult。
- 没有合法 child final 时没有业务结果；平台断流继续走既有有限恢复，不伪造 `failed`。
- 结果记录不改变 observation plane，也不确认 runtime Agent identity。

## 状态格式 4

StateStore 从 format 3 升为 format 4：

- canonical task root 只保留 `managed + task_id + work_item + executions`；
- 删除 `result_credentials`；
- 删除 execution 的 `spawn_result_credential_id`；
- 删除 pending action 的 `result_credential_id`；
- ResultRecord 用 `sender_target` 替代 `credential_id`；
- 新结果 provenance 固定为 `parent_recorded_native_sender`；
- format 3 迁移删除 credential material，不补造结果、身份或 observation 事实；已有合法历史结果以 `legacy_result_migration` 标识来源。

未知状态版本继续拒绝重写并 fail-open 报告。

## 幂等、冲突与存储

- TaskResult 使用 canonical JSON 和 SHA-256 生成确定性 digest。
- 同 sender/task/attempt 和同 digest 重放返回 `idempotent`，包括 attempt 已验收关闭后的只读重放。
- 不同 digest 不覆盖首份文件，只在 ResultRecord 写 `conflict_sha256 + conflict_first_seen_at` 并进入 `manual_review`。
- 正式结果仍使用安全确定性文件名、私有权限、原子写入和回读验证。
- pre-storage failure 写 canonical `storage_error + payload_valid=false`，不写 business result、结果引用、摘要、submitted time 或 provenance；同 envelope 可重试。
- StateStore 已提交但调用报告错误时先权威回读，避免把已落盘结果降级为 storage_error。

## 旧入口退役

以下 CLI 不再受支持，也不能写结果：

- `--submit-result`
- `--relay-result`

运行时不再导出 credential generator、hash verifier、credential installer/revoker、`submit_result_envelope()` 或 `submit_task_result()`。

## 本地验证范围

新增和迁移的测试覆盖：

- Hook input message 严格不变；
- exact sender 正向记录；
- wrong/missing task、attempt、sender 和关闭/中断 attempt 拒绝且不写；
- 同结果幂等、异结果冲突、首份结果保留；
- storage failure/retry 和 post-commit readback；
- 线程与独立 CLI 竞争；
- format 3 到 format 4 credential 清理；
- observation/identity 不变；
- result correction、business resume、父 disposition 和旧 Slice 1/2 状态机无回退；
- 旧写入口不可用。

真实平台是否稳定展示当前 child final、父 Agent 能否总是取得精确 sender target，以及 provider restart/compact/resume 行为仍需新的 cachebuster smoke；本实现记录不替代真实平台验收。
