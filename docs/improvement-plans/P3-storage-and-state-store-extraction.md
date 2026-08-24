# P3：存储基础设施与 StateStore 拆分

状态：已确认，待独立对话实施。

前置：P1。

## 目标

将环境路径、私有目录、文件锁和 StateStore 从主运行时分离，保持存储语义不变。P3 不迁移 PreparedContractStore 的完整实现，也不改变 dispatch 流程。

## 模块边界

### `governance_storage.py`

继续作为通用私有文件 primitives：

- bounded secure read
- atomic write
- locked file
- storage error types

### 新建 `governance_store_support.py`

迁入：

- current uid/ownership 检查
- private permission 检查
- descriptor/path restriction
- directory fsync
- platform file-lock adapter
- user storage key
- safe filename
- private directory preparation
- installed plugin data-root detection
- current `state-v6` data-root resolver

不得放入 task/activity/lifecycle 语义。

### 新建 `governance_state_store.py`

迁入：

- `StateStore`
- `UnavailableStateStore`

依赖：

- `governance_state`
- `governance_store_support`
- `governance_storage`
- semantics/errors

禁止导入主运行时。

### `governance_state.py`

继续拥有：

- v6 初始状态
- canonical plane records
- current-state validator
- attempt/tombstone key parser 等状态模型能力

## Data-root resolver

不能继续依赖 `subagent_governance.py` 的文件名推断安装根。实现纯函数，显式接收 module path，并结构化识别：

- developer repository
- installed plugin
- plugin cache
- explicit data root

默认 namespace 必须来自 P1 的 `state-v6` 常量。

## PreparedContractStore 的 P3 边界

P3 不迁移该 class，因为它直接依赖 contract/context/digest/task-name 逻辑。它暂时留在主运行时，但改用新的 store support helper。P4 再迁移。

## 过渡 facade

主运行时可以暂时 re-export：

- `StateStore`
- `UnavailableStateStore`
- 必要 data-root helper

但不得保留第二份实现。P8 清除私有 facade。

## 测试

- 直接导入 `governance_state_store` 测试，不只经主门面。
- patch 真正符号所有者，例如 file-lock adapter、`os.replace`、`fsync`。
- package import 和 scripts 目录直接 import。
- import 模块不创建目录或 lock。
- constructor 才准备目录。
- owner、permission、symlink、non-regular、oversize、UTF-8/JSON、atomic replace、readback。
- CAS predicate conflict 不调用 callback、不写文件。
- Windows lock branch 静态/模拟测试。
- resolver developer/installed/cache/explicit cases。
- 新模块无反向 runtime import和循环依赖。

## 验收标准

- 主运行时不再定义 StateStore class 或底层 storage support。
- StateStore 行为和错误分类不变。
- P1 的完整 v6 validator 是每次读取/写入边界。
- resolver 只选择 `state-v6`，不 fallback。
- import 无文件系统副作用。
- 完整测试、编译和 Plugin validator 通过。

## 停止条件

- StateStore 需要导入主运行时才能工作。
- resolver 仍依赖入口文件固定名字。
- 为拆分改变 CAS、锁或原子写语义。
- 必须同时迁移 dispatch 才能完成 StateStore 拆分。
