# ADR：Subagent Governance 减法收口目标架构

- 状态：Accepted
- 日期：2026-08-25
- 适用范围：下一轮架构收口与验收
- 实施状态：实施中；state-v9 / TaskContract v2 / prepare→claim→explicit confirm 第一纵向切片已落地，当前运行边界以 `docs/architecture.md` 为准

## 背景

当前实现已经完成严格 current-only 状态、UTF-8 byte 边界、安全存储、领域模块拆分、真实平台验证和本机开发部署事务等改造。这些工作同时暴露出一个更根本的问题：实现把尚未由真实 Codex 平台证明可靠的 `PostToolUse` 事件链作为生命周期结算权威，并通过双存储、claimed-ID index、receipt、rebuild、补偿和多 attempt 状态机处理这条链的不确定性。

真实验证只能证明 governed spawn 的 Pre claim 和原生 child 创建实际发生；三次 P12-A 样本均没有保存可安全关联到 claim 的 same-ID Post receipt。该事实不能归因于平台未投递、工具名或 ID 漂移、Hook router、handler 或 storage，但足以否定“在当前证据下继续扩建 Post-based correctness authority”的方向。

本 ADR 决定先收缩产品承诺和权威数量，再重建最小状态机。项目继续使用 Codex 原生子 Agent 工具，不引入第二套编排平台，也不把协作协议描述为权限、安全或平台级信任边界。

## 决策

### 产品承诺

首个收口版本只承诺一个可跨同一 exact Session identity 的 compact/restart 恢复的最小生命周期：

```text
prepare
→ PreToolUse claim
→ native spawn_agent
→ explicit exact-target confirmation
→ wait / exact platform observation
→ normal message
→ terminal notification
→ minimal interrupt
→ parent close
```

首版不承诺 managed business resume、复杂 platform recovery、同 target 多 attempt、Group、自动跨事件修复或依赖 PostToolUse 的调用结算。

### 身份权威

父 Agent 读取当前原生 `spawn_agent` 返回后，显式提交 exact target。该提交是 canonical identity 的唯一来源：

- 只允许绑定当前 `claimed` 且尚未绑定的精确 task。
- first bind wins；相同 target 重放幂等，不同 target 冲突进入 reconcile。
- `list_agents` 只能观察已经绑定的 exact target，不能反推或补绑身份。
- task name、时间邻近、唯一候选、child final、terminal notification、summary 和 transcript 都不能建立 identity。
- 原生返回后、确认前发生中断时，task 保持 `claimed/unbound`，不自动重派或猜测恢复。

该机制是父 Agent 负责执行的协作正确性协议，不是平台原子事务或安全边界。

### 单一 Session ledger

一条 task 对应一个原生 Agent 生命周期。首版不保留 attempt 概念。每条记录只保存：

- `task_id`
- `task_ref`
- `phase`
- business contract digest 与最小摘要
- 仅在 prepare/claim 阶段存在的 prepared capability
- bind 后存在的 exact target
- 最后一次必要的平台观察
- 最小 terminal notification
- 有界 reconcile reason
- 必要时间戳

`phase` 只使用：

```text
prepared | claimed | bound | terminal | closed | reconcile
```

prepared capability 与生命周期状态位于同一 ledger，并在同一文件锁和原子写边界内 claim。bind 后可以把完整 capability 收缩为 digest 和最小摘要。

以下事实不再独立持久化：

- PreparedContractStore
- `agents[target]` active index
- ClaimedPostIndex
- PostToolUse receipt
- pending action 与 last lifecycle operation
- 独立 tombstone
- Group

target mapping、allowed action 和关闭视图从有界 task records 派生。closed task 本身是有限保留的关闭事实，由后续 ledger 写操作惰性清理；diagnostics 和 SessionStart 不执行清理。

新模型使用新的严格 current-only namespace。旧 v8 及更早数据不读取、不迁移、不修复、不写回、不删除。

### 持久化边界

只持久化会影响后续安全决策的事实：

| 操作 | 持久化规则 |
| --- | --- |
| spawn claim/result | success 绑定 exact target；failed 记录未创建并关闭；unknown 进入 reconcile |
| wait | 不持久化 |
| exact platform observation | 只作用于已绑定 target，记录必要的 running/terminal/error/unknown 事实 |
| normal message success/failed | 不保存正文或调用历史，不改变生命周期 |
| normal message unknown | 只保存有界 delivery-unknown reconcile reason，禁止自动重发 |
| terminal notification | 保存 exact sender、status 和时间，不保存正文 |
| interrupt result | 明确 inactive 可建立平台终态；unknown 进入 reconcile |
| parent close | phase 转为 closed |

插件不维护自动 recovery/retry budget，不通过 followup 建立 managed resume，也不保存普通消息日志。

### TaskContract

删除 `auto/light/standard/strict` 四级体系，改为默认 `standard` 与显式 `strict` 两种 profile。`auto` 依赖模型自报的 task features，不能建立真实风险事实，因此不再保留六字段 `task_features`。

模型输入收缩为：

```json
{
  "profile": "standard",
  "objective": "...",
  "scope": ["..."],
  "forbidden_scope": [],
  "completion": ["..."],
  "evidence": [],
  "context": {
    "summary": "...",
    "paths": []
  },
  "spawn": {
    "fork_turns": "none",
    "model": null,
    "reasoning_effort": null
  }
}
```

- `objective`、`scope` 和 `completion` 必填。
- 其他字段可省略，由生成器补默认值；不要求模型手写空数组或 null。
- strict 要求非空 forbidden scope 和 evidence，并可要求 verified materials。
- 普通 context paths 只是定位提示；完整 working-tree hash 或 Git tree verification 仅供 strict 或显式 opt-in 使用。
- 原生 `fork_turns` 直接表达上下文继承，不再拆成 strategy、turns 和 reason。
- semantic name、task ref 和显示字段由生成器派生。
- business contract digest 不包含 model、reasoning effort 等 spawn config；后者单独记录。

strict 仍是协作协议，不是自动风险检测、权限或安全边界。

### Hook 与恢复

只保留：

1. governed spawn 的精确 PreToolUse：unmanaged spawn 完全 inert；governed spawn 验证并原子执行 `prepared → claimed`。
2. best-effort、只读 SessionStart：按当前 exact session ID 展示未关闭 task 摘要和派生下一步。

删除全部 PostToolUse、Stop、SessionEnd，以及通信、followup 和 interrupt 的 PreToolUse。

SessionStart 不得创建目录、lock 或空状态，不 cleanup、migrate、rebuild、自动关闭、自动重试、扫描其他 Session 或调用原生工具。SessionStart 未投递不影响 ledger correctness；显式只读 status 命令提供兜底。

自动恢复只覆盖平台继续提供同一 exact session ID 的场景。新 Session identity 不触发跨 Session 扫描或模糊关联；该平台行为仍需真实验证。

### Runtime bundle 与开发部署

运行包使用显式 allowlist，只包含：

- `.codex-plugin/plugin.json`
- Hook manifest
- 当前 Skill 及必要 references
- 核心 runtime scripts
- 当前 Schema
- 必要 assets
- 最小发布材料

tests、CI、improvement plans、validation reports、AGENTS、开发依赖、release preflight、stable sync、installer、installation checker 和 cache 管理工具不进入 runtime bundle。bundle digest 只覆盖 allowlist，开发文档或测试变化不再改变 runtime digest。

本机开发部署只暴露一个入口，内部完成 allowlisted bundle、staging、digest verification、atomic stable activation、Codex 原生安装、精确 previous compatibility bundle、失败回滚和最终检查。

P13 的 exact previous、双版本、digest 和 rollback 原则，以及 P14 的 clean exact HEAD、staging、atomic activation 和 rollback 原则继续保留，但只属于开发测试部署工具，不是 runtime 产品能力。直接处理 Codex 内部 cache 的代码必须明确标记为本机开发测试专用。

删除可选全局 AGENTS block 自动写入能力；显式 Skill 与插件 Hook 是唯一产品入口。

## P1–P14 处置

| 方案 | 决定 |
| --- | --- |
| P1 | 保留 strict current-only、Schema/runtime 对齐和独立 namespace；在新最小格式上重建 |
| P2 | 保留 UTF-8 byte 输入边界 |
| P3 | 保留安全存储 primitives；重做 StateStore 数据模型 |
| P4 | 保留模块边界、digest、rendering 和可选 context verification；删除 PreparedContractStore 与重型契约 |
| P5 | 撤回双存储 saga、补偿、spawn Post settlement 和同 attempt retry 状态机 |
| P6 | 保留 terminal、parent close、minimal interrupt；删除 business resume、platform recovery、pending/Post 协议 |
| P7 | 保留纯只读 view/diagnostics；删除 Group、Stop、SessionEnd 和 SessionStart maintenance |
| P8 | 保留薄 CLI、Hook router 和 platform adapter；Hook 收缩为 spawn Pre 与只读 SessionStart |
| P9 | 保留仓库综合验收原则；围绕新产品承诺重写测试矩阵 |
| P10 | 保留真实平台验证；场景改为 prepare/claim/confirm/wait/terminal/interrupt/restart |
| P11 | 删除 Post receipt/index/replay；只保留 exact list 不得推断 identity 的原则 |
| P12-A | 作为已完成的有界实验归档；不恢复 runtime probe |
| P12-B | rejected/archived；当前平台证据下不得实施 |
| P13 | 保留开发部署原则，不进入 runtime 产品 |
| P14 | 保留原子激活原则；改为 allowlisted bundle，并合入单一开发部署入口 |

## 保留的既有正确性成果

本次减法不撤销以下成果：

- strict current-only 数据和独立 namespace
- runtime validator 与 canonical Schema 对齐
- UTF-8 byte 输入上限
- 原子写入、容量、owner/permission、symlink 和 non-regular 防护
- unmanaged 原生工具 fail-open
- 薄入口和清晰模块所有权
- diagnostics 无锁只读、不回写、不扫描业务正文
- transcript、summary、child final 不作为 correctness authority
- 真实平台验证优先于 mock/fixture
- 未知事实保持 unknown，不按时间、名称或唯一候选猜测成功
- 开发部署中的 digest verification、atomic activation 和失败回滚原则

## 后果

预期收益：

- correctness authority 从未经证实的异步 Hook 事件转为父 Agent 当前可见的原生返回。
- 双存储 saga、Post receipt/index/replay 和多 attempt 路由可以整体删除。
- Hook 全局执行面积显著缩小。
- 状态、Schema、Skill、测试和部署包围绕同一最小产品承诺收敛。

接受的代价：

- 父 Agent 必须显式确认原生结果并记录必要事实。
- confirm 前崩溃不会自动恢复 identity。
- 首版没有 managed followup/business resume、自动 recovery 或 Group。
- restart/compact 恢复依赖 exact session identity；其他场景需要显式旧 Session 查询。
- 现有实现和测试需要按删除后的产品语义重写，不能通过兼容层维持旧状态机。

## 非目标

本 ADR 不包含文件级实施顺序、代码迁移方案、发布授权或运行缓存更新。实施前应另行制定有界减法计划和新验收矩阵；在实施完成并取得真实平台证据前，`docs/architecture.md`、当前 Skill 和现有 runtime 仍描述当前已实现行为。
