# F7 canonical-only 残余清理实施记录

## 范围与结论

本切片重新审计 `S1-S6-integrated-architecture-review.md` 的 P3-1，不沿用旧行号或未经复核的结论。当前对外决策与诊断入口统一为 canonical work item 的 `WorkItemDecisionSnapshot`；attempt record 只作为其 `execution_candidates[]` 中的候选事实。开发仓库是唯一修改源，没有安装、发布、同步测试插件、修改运行缓存或创建真实插件测试对话。

结论：旧 finding 中通用的 root-current reader 和 legacy adapter 已大部分由 S6/F1-F6 消解；当前工作树仍有一个 duplicate 收口 root fallback、一条错误 adapter 注释，以及一套只写不读的 diagnostic attempt snapshot/map。本切片删除这三类残余并增加退役护栏，没有删除 F6 明确保留的 compatibility-read。

## 失败先行

先在 `tests/test_s6_compatibility_retirement.py` 增加当前源码退役护栏。修改 runtime 前执行：

```text
python3 -m unittest -v \
  tests.test_s6_compatibility_retirement.CompatibilityRetirementTests.test_canonical_only_residuals_do_not_reappear

Ran 1 test
FAILED (failures=3)
```

三个 subtest 分别证明：`_diagnostic_attempt_snapshot` 仍导出、duplicate 收口仍含 `task.get("attempt")` root fallback、retry preparation 注释仍宣称会为 legacy records 构造内存 view。当前 Skill/runtime-boundaries 不发布内部 snapshot helper 名的护栏在修改前已经通过，说明旧 review 中关于具体私有 helper 文案的证据已由前序切片消解；本切片不制造对应无意义改动，只补 work-item-first 数据流表述。

## 重新审计 inventory

| 项目 | 当前消费者/可达性证据 | 处理 |
| --- | --- | --- |
| duplicate selected 收口的 root `attempt` fallback | 收口函数只由未选 duplicate 可靠关闭路径调用；调用方已有 canonical execution，S6 又拒绝缺少 `work_item/executions` 的 managed task。fallback 只让非法旧形状绕过 canonical 边界。 | 删除 fallback，入口先经过 canonical task 校验，再从 `work_item.current_attempt -> executions` 选择 execution。 |
| retry preparation 的 legacy in-memory adapter 注释 | 实际下一行调用 canonical task 校验；该边界对历史 flat record 抛冲突，不构造 adapter。 | 改为“只接受持久化 canonical work-item shape”。 |
| diagnostic attempt snapshot helper | 全仓只有定义和 session diagnose 内一次调用；返回值只写入局部 map，map 从未读取、返回或进入 group/Session 输出。 | 删除 helper 与 map。 |
| diagnostic `allowed_keys/action_keys/recent_keys` | `allowed_keys` 无读取；后两者只供已删除 helper。 | 删除。保留 aggregate `action_all/recent_all`，因为 session counts 仍消费。 |
| `_action_required_records` / `_recent_activity_records` | SessionStart、Stop、SessionEnd、diagnose aggregate counts 和定向测试仍有消费者。它们遍历的只是 canonical execution 派生事实，不是独立对外 attempt snapshot。 | 保留。 |
| execution projection/view | action-required、recent、Stop 与 diagnose 的验证/聚合需要为 canonical execution 补充 `task_id/attempt/activity_at`；current attempt 直接读取 `work_item.current_attempt`。 | 保留为内部候选事实适配，不把 helper 名写成产品 API。 |
| 旧 review 所指通用 root-current fallback | 原行号现为 canonical aggregate 更新；全 runtime 扫描除本次 duplicate 分支外没有 `task.get("attempt")`。 | 记录为已由前序切片消解，不追加改动。 |
| 旧 review 所指通用 legacy adapter | canonical task 边界已拒绝历史 flat managed record；现存唯一命中是上述错误注释。 | 仅修正文案。 |

历史 S1/S3/S5 实施记录保留当时迁移阶段的事实，不作为当前运行说明；S6、F7、开发 Skill 和 runtime-boundaries 是 canonical-only 当前边界。D6 的两个 host-specific path 也按任务边界不修改。

## 明确保留的 compatibility 与职责

以下项目均有当前消费者，且属于 F6 的受控 compatibility-read/单向收敛，不按名称含 `legacy` 直接删除：

| 保留项 | 职责 |
| --- | --- |
| work-item `last_disposition` readers | 只读区分 formal parent disposition 与 growth authorization；diagnose/allowed-actions/growth projection 仍消费，并在 canonical write 时收敛到不同新字段。 |
| execution `parent_disposition` 及 reason/time companions | 为旧 canonical execution 补齐 formal disposition 或 growth authorization；冲突拒绝，写入时删除旧名。 |
| pending action `disposition` | 只把合法旧增长授权收敛到 `growth_authorization`，不作为第二权威。 |
| replacement PreparedContract `parent_disposition` | PreparedContract 读取边界兼容旧 replacement 授权；与新字段冲突时报错，随后只使用 canonical growth authorization。 |
| canonical attempt iteration/projection | same-Agent retained provenance、action-required、diagnose、group、SessionStart/Stop/End 和结果精确路由仍依赖全部 retained executions。 |
| Schema/semantic compatibility tests | 验证旧名只能单向收敛、冲突不能静默覆盖，并保持 canonical record/decision snapshot 约束。 |

本切片没有改变 formal result、same-Agent 迟到路由、duplicate selection、action-required、group、Session 或 Schema 状态机语义。

## 文档收口

- 开发 Skill 与 runtime-boundaries 现在明确：每个 canonical work item 生成一个 `WorkItemDecisionSnapshot`。
- attempt 事实只出现在所属 snapshot 的 `execution_candidates[]`，不提供顶层 attempt-first 决策数组。
- work-item/group、SessionStart、Stop 与 SessionEnd 消费同一 canonical candidate predicate 或其有界聚合；`recent_activity` 保持独立展示窗口。
- 当前指导文档不发布 runtime 私有 helper 名作为稳定 API。

## 验证

实现期定向验证：

```text
python3 -m unittest -v \
  tests.test_s6_compatibility_retirement \
  tests.test_minimal_diagnostics_lightweight_groups \
  tests.test_wait_recovery_session_closure \
  tests.test_canonical_record_schema

Ran 90 tests
OK
```

最终门禁结果：

```text
python3 -m unittest discover -s tests -v
Ran 351 tests
FAILED (errors=2)

python3 -m py_compile scripts/*.py
passed

Plugin validator
Plugin validation passed

Skill validator
Skill is valid!

全部仓库 JSON: python3 -m json.tool
passed

git diff --check
passed
```

全量中的 349 项通过；仅有任务明确允许保留的两个既有 D6 host-specific path errors：

- `test_release_preflight.ReleasePreflightTests.test_current_development_tree_passes_with_supported_ref`
- `test_release_preflight.ReleasePreflightTests.test_release_requires_manifest_tag_and_marketplace_ref_to_match`

两项都由 `release_preflight.PreflightFailure: host-specific path in docs/redesign/D6-migration-and-slices.md` 触发，没有新增失败。AST 调用对账确认 dead diagnostic helper 不再定义；保留的 action-required、recent-activity、work-item snapshot 与 duplicate 收口函数分别仍有 3、2、3、2 个 runtime call sites。负向扫描未再命中 root `task.get("attempt")`、错误 legacy adapter 注释、dead attempt helper 或其 snapshot/key map。

## not_checked

- 开发工作树安装、稳定源或运行缓存同步：`not_checked`，本任务禁止。
- 新对话真实插件加载与 Hook trust：`not_checked`，本任务禁止创建真实测试对话。
- 原生 spawn/send/followup/wait/list/interrupt、SubagentStart/Stop/TaskResult 时序：`not_checked`。
- Marketplace、Registry、发布、回滚与 N/N-1：`not_checked`。

## remaining

- F6 compatibility readers 继续保留，直到有独立迁移证据和明确退役切片；本切片不设置 version gate 或 migration。
- 历史 implementation records 继续保留迁移轨迹；当前边界以 S6/F7、开发 Skill、runtime-boundaries 和 Schema 为准。
- 真实 Codex 平台行为仍需后续获授权的安装与新对话验收；本地测试不能替代。
