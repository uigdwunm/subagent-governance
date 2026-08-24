# P7：决策视图、Group、Session 与只读诊断

状态：已确认，待独立对话实施。

前置：P1–P6。

## 目标

建立唯一 canonical work-item read model，供 Group、SessionStart/End/Stop 和 diagnostics 共享；修复 resume delivery failed 被排除出 action-required、SessionEnd 误删 open work item等问题。

## `governance_views.py`

纯 projection 模块，拥有：

- bounded attempt projection/activity
- close/call-in-progress/action-required 派生
- work-item lifecycle/notification/allowed-actions view
- recent/action-priority排序

使用显式 projection，不 shallow-copy 完整 execution；不得泄漏 full contract、context、message 或业务结果。

可使用 `ViewIssue`/`WorkItemViewResult` 向 Group/Diagnostics 传递稳定语义问题。

## Work-item 修正

- persisted tombstoned + 全部 reliable closed => tombstoned。
- persisted open + current attempt 精确存在 => open，即使 current execution 因 `resume_delivery_failed` reliable closed。
- 其余不一致 => indeterminate。

Action-required 从 work-item 判断：parent action、running、pending/claimed/unresolved、identity 未确认的 success/unknown、resume delivery failed、indeterminate。Prior closed attempt 本身不产生 action-required。

Open + terminal notification 或 resume delivery failed 允许 `close_task`/`resume_business`；spawn reliable failed 可 `retry_spawn`；顺序只来自 canonical action order。

## `governance_groups.py`

迁入 strict validate/upsert/read/derive。

- v6 根始终有 `groups`；不再 setdefault。
- group 精确字段：id、objective、members。
- member 精确字段：task id、required。
- trim 后 canonical id 用于写入和读取。
- duplicate/missing task/limit/unknown fields 拒绝。

`summary_ready` 要求 required 非空且每个 required member 已收到 current terminal notification 或 work item tombstoned。`group_action_required` 只由 required member 决定；optional 问题仍进入 snapshot/diagnostics。

## `governance_sessions.py`

领域接口：Stop advisory、SessionStart resume、SessionEnd finalize；不生成 Hook JSON。

### Stop

只读、有限重试、advisory-only；无可靠 state 时 fail-open。sleeper 可注入，测试不真实等待。

### SessionStart

顺序：prepared reconcile → pending reconcile → tombstone cleanup → strict read → work-item views → bounded context。

单项 maintenance 失败记录 warning 后继续尝试只读摘要；只有 state 不可读才完全 degraded。只保留一套 work-item summary，不再并存 attempt/work-item 两套决策规则。

### SessionEnd

同样先 reconcile/cleanup/read，再 `delete_if`。任一 maintenance 失败不删除。

删除条件：

- 所有 work items tombstoned；
- 无 open/indeterminate、pending/claimed/unresolved；
- 无 retained tombstone；
- health status=ok 且无 rollback/reconcile marker。

空 session 可删除。Groups 不单独阻止已完成整个 session 删除。

## `governance_diagnostics.py`

完全只读：不构造 StateStore、不创建 lock、不 cleanup/reconcile/migrate/repair。返回 document + exit code，不写 stdout。

安全检查 owner、permission、symlink、regular file、byte size、UTF-8、JSON、session id。

P1 后删除 partial historical normalizer：

- invalid v6 报 bounded structured paths，不派生部分业务视图。
- valid v6 使用 canonical views，报告跨字段/identity/group/health 问题。
- v5/旧状态只报 unsupported format，不解释迁移。

输出按 UTF-8 bytes 限制 session/attempt/group/issue/整体大小，排序确定；显示被实际检查的 lexical absolute path，不用 symlink resolve 结果替换 issue path。

## 实施顺序

1. 先补 resume-delivery-failed/work-item/SessionEnd 回归。
2. 抽取 views 并让三消费者共用。
3. 抽取 strict groups。
4. 抽取 sessions，统一 summary/delete predicate。
5. 抽取 diagnostics，删除旧式 partial normalize。
6. 主运行时只保留临时 Hook/CLI formatting wrapper。

## 测试重点

- lifecycle/view 全状态表、allowed action、recent cutoff、隐私 projection。
- group create/update/read/required/optional/missing/trim/unknown。
- SessionStart maintenance partial failure + readable summary。
- SessionEnd open current closed、degraded health、tombstones、并发 predicate。
- diagnostics missing/symlink/nonregular/owner/permission/nonUTF/nonJSON/v5/invalid v6。
- deterministic order、byte caps、全树 hash/mtime 零写入。

## 验收标准

- Group/Session/Diagnostics 共用唯一 work-item view。
- resume delivery failed 保留 action-required 和 resume/close actions。
- SessionEnd 不误删 open work item或 degraded health。
- Groups 使用 strict v6，不创建缺失根。
- diagnostics 不解释或修复历史格式，且零写入。
- 主运行时无 view/group/session/scanner 实现。
- 完整测试、编译、Plugin validator 通过；不安装发布。

## 停止条件

- 三个消费者仍需各自重写状态判断。
- invalid v6 必须被修补后才能诊断。
- SessionEnd 删除条件无法在 `delete_if` 当前快照内重算。
- diagnostics 需要构造 StateStore 或 lock 才能读取。
