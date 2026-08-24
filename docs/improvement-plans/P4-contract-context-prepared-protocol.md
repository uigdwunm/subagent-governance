# P4：契约、上下文、PreparedContract 与派发协议拆分

状态：已确认，待独立对话实施。

前置：P1、P3。

## 目标和边界

拆出无状态的契约、上下文、派发身份/渲染协议和 PreparedContractStore。P4 不移动 `prepare_dispatch`、claim、rollback 或 reconcile；这些事务属于 P5。

## 目标模块

### `governance_validation.py`

只放跨领域值级纯函数：required fields、text、text-list。不得堆入业务语义。

### `governance_context.py`

迁入：

- context manifest 结构校验
- verification record 校验
- file SHA-256
- Git baseline 调用
- `verify_context_manifest`

结构校验不访问磁盘；verify 才允许文件/Git I/O。路径逃逸、缺失文件、hash/revision 不一致继续抛 `ContextVerificationError`。

### 扩展 `governance_contracts.py`

作为 TaskContract 唯一语义入口，拥有：

- `TaskFeatures`
- `TaskContract`
- task features 校验
- mode resolution
- contract validation/parse
- canonical serialization
- contract summary/digest

Digest 只基于 canonical `to_record()`、sorted compact JSON 和 UTF-8。

### `governance_dispatch_identity.py`

拥有：

- semantic name normalization
- task ref derive/select
- task name build/parse

不检查 StateStore/PreparedStore 占用；占用集合由 P5 传入。

### `governance_dispatch_rendering.py`

拥有：

- context projection
- dispatch prompt
-用户可见派发说明
- native spawn arguments

输入必须是已解析 contract 和已验证 context；不读状态和文件。拆分前后输出逐字节一致。

### `governance_prepared_store.py`

拥有：

- PreparedContract record builder
-严格 record validator
- `PreparedContractStore`
- prepared-root resolver

Builder 与 validator 必须同模块，避免格式漂移。复用 P3 storage support，不重新实现锁、权限、atomic write 或 data-root。

## 依赖方向

```text
semantics/errors
  -> validation
  -> context
  -> contracts
  -> dispatch_identity / dispatch_rendering
  -> prepared_store
  -> runtime facade
```

`context` 不导入 `contracts`；新模块均不导入主运行时。

## PreparedContract 严格性

精确声明 session/task/attempt/ref/name/mode、contract/digest、context verification、native parameters、timestamps、claim fields、retry count 和 operation。缺失或未知字段拒绝。

必须验证：

- path identity 与 record 一致
- task name 与 mode/ref 一致
- digest 与 canonical contract 一致
- context verification 与 manifest 一致
- initial attempt/retry count 规则
- consumed claim 完整性
- UTF-8 encoded byte limit

## 过渡策略

主运行时临时显式 re-export 公共符号，但不保留第二份实现。测试 monkeypatch 实际模块所有者，不建立动态代理。

## 实施顺序

1. 为 contract、context、identity、prompt、Prepared record 建 characterization/golden tests。
2. 抽取 validation/context。
3. 收拢 contracts。
4. 抽取 identity/rendering。
5. 抽取 PreparedContractStore。
6. 删除主运行时重复实现并检查依赖 DAG。

## 验收标准

- canonical record、digest、prompt、native args 与拆分前一致。
- PreparedStore 锁、CAS、atomic write、readback 语义不变。
- module import 无文件写入。
- package/direct-script import 均通过。
- `runtime.TaskContract is governance_contracts.TaskContract` 等类型 identity 成立。
- 主运行时只有 import/re-export。
- 不兼容旧 contract/prepared/task-name。
- 完整测试、编译和 Plugin validator 通过。

## 停止条件

- 新模块需要导入主运行时。
- digest 或 prompt 非预期变化。
- 必须移动 execution state machine 才能继续。
- 为旧测试建立动态 proxy 或双重实现。
