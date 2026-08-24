# P1：v6 严格状态契约与全新数据命名空间

状态：已确认，待独立对话实施。

## 目标

消除 runtime current-state 校验、JSON Schema 和实际生产者之间的结构漂移；停止读取旧 `state-v1` 命名空间。P1 不迁移历史数据，不兼容旧状态。

## 已确认问题

- `require_current_state_format` 只检查版本和部分 `managed=true` task。
- `managed!=true` task 被跳过，缺失根字段、非法 agent 和多种非法 execution 字段可通过 runtime。
- Schema 会拒绝这些样本，形成 runtime accept / Schema reject。
- 测试明确保留 unknown root field 和旧式 unresolved task。
- 状态格式版本为 5，但默认目录仍硬编码 `state-v1`。
- canonical persisted definitions 多处 `additionalProperties:true`，合法当前字段又依赖开放边界存在。
- runtime 实际写入 `groups`，但当前 root Schema 未完整声明。

## 当前格式

将 `STATE_FORMAT_VERSION` 提升为 6。根对象精确要求：

- `state_format_version`
- `session_id`
- `tasks`
- `agents`
- `health`
- `tombstones`
- `groups`

根对象和所有 persisted nested records 使用显式字段集合；未知字段拒绝。

### Task

精确包含：

- `managed`，固定为 `true`
- `work_item`
- `executions`

不再允许 `managed=false` task 混入 current-state；unmanaged 调用不创建 task record。

### Work item

精确包含：

- `lifecycle`
- `current_attempt`

`current_attempt` 必须关联 executions 中的 canonical attempt key。

### Execution

必需字段：

- `task_ref`
- `task_name`；initial spawn 为字符串，same-Agent resume 允许 `null`
- `resolved_mode`
- `contract_summary`
- `contract_digest`
- `dispatch_record`
- `observation_record`
- `closure_record`
- `spawn_retry_count`
- `recovery_count`
- `updated_at`

按变体允许：

- `pending_action`
- `last_lifecycle_operation`
- `initial_preparation_rollback`

不得通过 historical-field blacklist 间接定义 current 格式。

### Pending action

按 operation type 使用关闭变体：

- `normal_message`
- `interrupt`
- `platform_recovery`
- `business_resume`

Business resume 变体必须声明：

- `resume_contract`
- `resume_contract_digest`
- `resume_context_verification`
- `prepared_on_attempt`

### Health、tombstone、agents、groups

- Health 使用关闭字段边界，并正式声明 rollback marker。
- Tombstone 精确声明 task ref、target、reason、closed time。
- Agents 是 canonical index；结构必须合法，但 index/provenance 冲突仍可作为待 reconcile 的当前事实存在。
- Groups 正式进入根 Schema，group/member 关闭未知字段。

## TaskContract 和 PreparedContract

- 将完整 TaskContract definition 放入统一 semantics source。
- standalone TaskContract Schema 引用相同定义，不复制字段。
- TaskContract 未知字段拒绝。
- PreparedContract 根字段关闭；builder 与 validator 必须一致。
- 不接受旧 contract、旧 working-tree 字段或旧 prepared record。

## Runtime 与 Schema 关系

结构层要求：

```text
runtime accept => Schema accept
Schema reject  => runtime reject
```

Runtime 可以额外执行 Schema 不适合表达的跨引用校验，但必须文档化。不能让 runtime 结构校验比 Schema 更宽松。

提供两个入口：

```python
validate_current_state_format(value) -> list[StateFormatIssue]
require_current_state_format(value) -> dict[str, Any]
```

StateStore 使用 `require`；P7 diagnostics 使用 `validate` 生成有界字段路径。

## 新数据命名空间

- 默认目录常量改为 `state-v6`。
- installed plugin、`PLUGIN_DATA` 和临时/测试根均通过同一 resolver。
- 显式 `--data-root` 精确使用用户指定目录，不自动拼旧版本名。
- 旧 `state-v1` 原样保留，但不扫描、不读取、不迁移、不删除。
- 禁止 fallback 到 unversioned 或旧目录。

## 实施顺序

1. 建立生产者 corpus：initial、retry、resume、pending、terminal、close、group、health marker。
2. 为 corpus 同时运行 runtime validator 和 Schema。
3. 定义 v6 semantics/Schema。
4. 重写 runtime validator，删除 managed skip 和 partial required-fields gate。
5. 更新所有生产者，使其只写 v6。
6. 切换默认 namespace 到 `state-v6`。
7. 重写保留旧字段/旧 task 的冲突测试。
8. 增加字段删除、类型修改、未知字段注入的 mutation matrix。

## 必须删除或改写的测试原则

- unknown root fields 不再 survive read/update。
- 非 canonical unresolved records 不再因年龄或数量被保留；它们在读取阶段直接失败。
- future extension 不通过任意 unknown persisted field 表达。
- 旧 `state-v1` 只验证“不接触”，不验证迁移。

## 验收标准

- 所有 canonical producer 样本同时通过 runtime 和 Schema。
- 任意必填字段删除、非法类型、未知字段注入同时被两者拒绝。
- `managed=false` task 被拒绝。
- agents、groups、pending variants、rollback markers 有正式 Schema。
- 默认写入只发生在 `state-v6`。
- 旧目录内容和 mtime 不变。
- 完整测试、py_compile 和 Plugin validator 通过。
- 没有安装或发布。

## 停止条件

- Schema 与 runtime 仍需维护不同字段清单。
- 为通过测试需要读取或迁移旧状态。
- business resume 当前记录无法用 v6 Schema 精确表达。
- namespace resolver 仍依赖旧目录 fallback。
