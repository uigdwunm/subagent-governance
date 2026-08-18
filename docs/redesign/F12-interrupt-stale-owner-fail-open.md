# F12: interrupt stale-owner fail-open

日期：2026-08-14

范围：只修复 F11 P1-1；不重构 interrupt 状态机，不修改 F11 历史结论

## 1. 结果

`_claim_pending_action()` 不再把可读状态上的 pending-owner/admission CAS conflict 当成主动中断的存储降级。A1 的 prepared interrupt 在 claim 前遇到 active admission candidate 切换到 A2 时，PreToolUse 现在明确 deny；A1 pending 保持 `prepared`，`tool_use_id` 保持 `null`，A2 mapping 不回拨，预算、attempt 和 lifecycle 计数不变化，因此不会形成中断 A2 的 authority。

normal message、interrupt、platform recovery、result correction 和 business resume 共享同一个异常分类。只有明确的 StateStore unavailable/read-write failure 能进入既有降级策略；机械 conflict、identity/admission/pending conflict、可读状态上的 CAS predicate 失败和其他不安全异常都 fail-closed。

## 2. Failure-first

先在 `tests/test_communication_lifecycle.py` 增加五类 operation 的参数化 A1 -> A2 race。测试在 `_claim_pending_action()` 初读完成、CAS claim 前切换 active candidate，并保存切换后的完整 StateStore 快照；最终要求 deny、没有 `updatedInput`，且状态逐字段等于该快照。

旧 runtime 的定向结果：

```text
Ran 1 test
FAILED (failures=1)
```

唯一失败 subtest 是 `operation_type='interrupt'`：实际 `permissionDecision=allow`，预期 `deny`。其余四类已经 deny。这稳定证明问题来自 claim 后的宽泛 interrupt exception 分支，而不是共享 admission predicate 没有识别 owner switch。

## 3. 不变量

- pending owner 的 `task_id + stored_attempt` 必须精确等于锁内 admission candidate。
- 可读状态上的 `StateConflictError` 不得被任何 operation type 转换成 allow。
- stale pending claim 被拒绝后保留 pending，交由显式 reconcile 或既有5分钟 prepared expiry 收口。
- claim 失败不能绑定 `tool_use_id`、消费 recovery/correction budget、创建 business-resume attempt、更新其他 lifecycle 计数或修复到旧 mapping。
- deny 输出不包含 `updatedInput`，因此 Hook 不授予原生工具执行 authority。
- 存储降级与 identity conflict 是两种不同事实；异常文本保留原始异常信息供诊断。

## 4. 实现

runtime 新增最小 `_state_store_exception_category()`：

- `StateConflictError` -> `conflict`。
- `StateWriteError`、`OSError`，以及明确包含 `OSError` 原因链的异常 -> `unavailable`。
- read 阶段其他显式 `StateStoreError` 表示 StateStore 无法取得可用状态 -> `unavailable`。
- 其余异常 -> `unsafe`。

read 与 claim exception 路径消费同一分类。`normal_message` 和明确 target 的 interrupt 只对 `unavailable` 保留既有告警 fail-open；三类 governed follow-up 对存储失败仍硬拒绝。所有 operation 的 `conflict|unsafe` 均 deny，理由包含分类与原始异常，pending 保留。

新增第二项参数化测试模拟 claim 的 `StateWriteError`，证明 normal message/interrupt 告警 fail-open，platform recovery/result correction/business resume deny，且五类 pending 都保持未认领。这把允许的存储降级与禁止的 stale-owner conflict 固定为不同测试分支。

## 5. Schema 与文本语义

`schemas/governance-semantics.schema.json` 已同时规定：

- `pending_owner_must_equal_admission_candidate=true`
- `stale_pending_claim=deny_and_preserve_for_reconcile_or_expiry`
- `normal_message_store_unavailable=warn_fail_open`
- `explicit_interrupt_store_unavailable=warn_fail_open`

现有机器语义足够，本切片未修改 Schema。Skill 与 `references/runtime-boundaries.md` 只做最小澄清：interrupt fail-open 限于共享分类器确认的真实 StateStore unavailable/read-write failure；可读 CAS/identity/admission/pending conflict 必须拒绝并保留 pending。

## 6. 验证

定向与跨切片：

```text
F12 targeted: Ran 2 tests, OK
communication lifecycle: Ran 66 tests, OK
F9 targeted: Ran 12 tests, OK
F10 initial targeted: Ran 17 tests, OK
F9/F10 related cross-slice: Ran 304 tests, OK
```

全量：

```text
python3 -m unittest discover -s tests -v
Ran 380 tests
FAILED (errors=2)
```

精确结果为 378 passed、2 errors。两项均为任务明确保留的既有 D6 host-specific path errors：

- `test_current_development_tree_passes_with_supported_ref`
- `test_release_requires_manifest_tag_and_marketplace_ref_to_match`

两项只报告 `docs/redesign/D6-migration-and-slices.md`。F12 未修改、修复或绕过 D6，因此不能表述为 full pass。

其他门禁：

- `python3 -m py_compile scripts/subagent_governance.py`：通过，bytecode 输出到 `/tmp`。
- Plugin validator：`Plugin validation passed`。
- Skill validator：`Skill is valid!`。
- 仓库全部 JSON parse：通过。
- `git diff --check`：通过。

## 7. Remaining 与下一步门禁

- 未安装、发布、stage、commit、push 或创建 PR。
- 未修改已安装插件、稳定发布源、运行缓存、Hook trust、Marketplace 或 Registry。
- 未同步测试插件，未创建新对话；真实 Plugin/Skill/Hook/provider/mailbox/UI 与原生 interrupt 参数、投递和时序仍为 `not_checked`。
- 未检查稳定发布源与运行缓存哈希或非符号链接关系，因为本切片禁止进入发布流程。
- 两个既有 D6 errors 保留。

下一步是基于 F12 当前代码与证据进行一次独立、只读的本地架构 gate review，重新核对 F11 P1-1 是否关闭及 Schema/runtime/docs 一致性。在该 gate 明确通过且用户另行授权前，不得同步测试插件或启动真实测试；本切片本身不改变 F11 当时的 BLOCKED 历史事实，也不构成 release-ready 结论。
