# S3 Same-Agent Resume、Replacement 与增长护栏实施记录

## 范围

本切片在开发仓库实现 D6 第 4 至 7 节的最小本地闭环。权威状态始终是
`tasks[task_id].work_item + executions`；root current 与 `prior_attempts` 只由同锁
projection writer 更新。本切片不修改 S4 等待/list_agents/session/stop、S5
diagnostics/group 或 S6 retirement。

## 失败先行基线

新增定向用例后，旧实现失败于三处：

- resume 在 `_create_resume_attempt()` 中用旧 `task_name` 新建 execution，并把新
  execution 提前写为 `identity_status=confirmed`；
- `business_resume` 没有强制 transition 和 reason-bearing disposition；
- 旧 task name 在没有 lifecycle 凭证时可影响新 attempt 的 Start 绑定。

这些失败由 `tests.test_communication_lifecycle` 的新 resume identity、authorization
和 weak Start 用例稳定复现。

本轮并发准入回归还复现了另一处缺口：replacement 与 business_resume 都只在准备时读取的
snapshot 上检查 candidate 数；在其后的 CAS callback 前注入第二个 live candidate 时，旧代码
仍会创建第三个 execution。replacement 还会留下已经创建的 PreparedContract。

## 实现

- `business_resume` 现在要求 `transition.reason_code` 为
  `blocker_resolved|decision_received|result_rejected|scope_or_conditions_changed`，并要求
  `disposition={action: resume_business, reason}`。两者均是非空、有界的机械输入。
- claim 时创建新的 canonical execution：新 `attempt/task_ref`、新 TaskContract/
  deliverable contract/digest，持久化 `origin_attempt` 与 immutable
  `origin_task_name`；不会创建 native spawn task name，也不会复制旧结果或旧 identity。
- resume 新 execution 初始为 `not_started/unconfirmed`。只有同 target 的 claimed
  `business_resume` pending 或其成功/unknown lifecycle record 才能授权 Start；删除该
  凭证后，普通 mapping、旧/相似 task name 或唯一候选不能启动 A(N+1)。
- followup success 保持新 execution `not_started + wait`，failed 只写
  `resume_delivery_failed` 的 execution close 且 work item 保持 open/action-required；
  unknown 保持 `not_started + reconcile`，不回写 business failed。
- replacement 继续复用 S2 native PreparedContract 入口；新增 `spawn_replacement`
  reason-bearing disposition 记录、origin attempt 和软增长事实。旧 unknown 时仍要求
  `unknown_duplicate_risk_accepted + duplicate_risk_accepted=true`，不成为 platform
  recovery 或 retry 的 fallback。
- 每个 work item 最多两个未关闭且仍可能执行业务的 candidate；第三个 resume/replacement
  在创建 canonical execution 前拒绝；replacement 如已创建 PreparedContract 则在锁内拒绝后
  回滚。判定先排除 `attempt_closed=true` 以及可靠
  `stopped`/`interrupted` 的 execution；其后 `running` 计入。initial/replacement 只在已经
  claimed native spawn（存在 `spawn_tool_use_id`）且 observation 为 `null`、`success` 或
  `unknown` 时计入；business resume 则在 pending 为 `claimed`，或已保存 lifecycle observation
  为 `success`/`unknown` 时计入。单独的 `platform_observation=unknown` 不构成 candidate；
  reliable failed 或 closed execution 不计入。每个 target 的 pending lifecycle action 仍由单一
  exact-target 查询保护。
- candidate 准入同时在 prepare snapshot 和真正创建 canonical execution 的 StateStore CAS
  callback 内执行。后者使用锁内最新 state；若已达到两个 candidate，replacement 不会写
  execution/count/disposition，并删除刚创建的 PreparedContract。若该删除失败，明确报出
  rollback failure，不会吞掉残留风险。resume 在 `_create_resume_attempt()` 开始时拒绝，因而
  不移动旧 pending、不更新 current attempt/disposition，也不创建 execution；PreToolUse 返回
  deny。StateStore callback 抛错发生在 `_write_path()` 之前，故该 mutation 不会落盘。
- resume claim 和 replacement execution 创建在各自 StateStore CAS 内同时写
  `work_item.last_disposition={attempt,action,reason,recorded_at}`，其中 attempt 是来源
  attempt；execution 保留审计副本，root/current 与 prior projection 继续由 canonical
  executions 同锁刷新。Prepared/CAS 写失败不会留下这条 disposition。
- attempt >= 4 写 `repeated_business_attempts`，replacement count >= 2 写
  `repeated_replacements`；它们是软事实，不硬拒绝业务继续，也不会自动派 reviewer。

`tests/fixtures/work-item-resume-v1.json` 记录 canonical resume 的最小持久化形状。

## 兼容接线

已有 S1 lazy canonical adapter 保持不变。resume 从 origin execution 的 typed pending
创建新的 `executions[attempt]`，随后由 `_sync_canonical_work_item()` 刷新 legacy
projection；没有扁平 task replacement。S2 replacement 的 native spawn preparation 和
PreparedContract 双门禁保持原入口，仅补充 S3 授权/增长字段。

## 验证

- 并发 stale-snapshot 定向回归覆盖 replacement PreparedContract rollback，以及 resume
  PreToolUse deny/no mutation。
- `python3 -m unittest -v tests.test_communication_lifecycle tests.test_formal_result_parent_closure`：76 tests OK。
- `python3 -m unittest -v tests.test_state_store tests.test_dispatch_identity tests.test_hook_fixtures`：69 tests OK。
- `python3 -m unittest discover -s tests -v`：270 tests，268 OK；仅两个既有
  `release_preflight` errors，均为 `D6-migration-and-slices.md` 的 host-specific path。
- `python3 -m py_compile scripts/subagent_governance.py`、Plugin validator、Skill validator、
  JSON `json.tool` 和 `git diff --check` 均通过。

## Not Checked

- 真实 followup success/unknown 与 Start 的平台乱序；
- 同 target 跨 attempt 的真实平台可识别性；
- native replacement spawn；
- Hook 在已安装插件中的加载。

本轮未做真实插件测试、安装、发布、缓存同步、stage 或 commit。已知 release-preflight 的
两个 D6 host-specific path errors 不在本切片修复范围内；仅确认没有新增错误。
