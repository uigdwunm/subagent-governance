# Subagent Governance v5 改造总览

## 文档定位

- 本文是 v5 实施导航，具体产品边界以 `docs/project-function-inventory.md` 为准。
- v4 的四平面、TaskResult、正式结果文件、结果补交、结果冲突和 accept/reject 业务验收已经退休。
- 当前开发只修改本仓库；稳定发布、安装、Marketplace、运行缓存和 Hook trust 需要单独授权。
- 当前状态（2026-08-18）：WP-01～WP-08 已完成开发仓库实施和本地测试、validator 验证。真实平台验证与稳定发布不在本轮范围内。

## 总体路线

```text
WP-01 语义与 Schema 基线
  -> WP-02 StateStore 安全底座
  -> WP-03 确定性派发与身份绑定
  -> WP-04 通信与生命周期操作
  -> WP-05 终态通知通道
  -> WP-06 等待、恢复和会话闭环
  -> WP-07 最小诊断与轻量 group
  -> WP-08 旧路径退役与发布准备
```

共同原则：

1. 插件只维护机械可验证的调用、观察和生命周期事实。
2. 子 Agent 的原生最终回复是父 Agent 阅读业务结果的通道；插件不扫描或持久化通知正文。
3. 平台终态观察不等于终态通知，也不生成业务结论。
4. 父处置只关闭任务；继续执行必须通过显式 `business_resume` 创建新 attempt，不表达 accept/reject 业务验收。
5. `unknown` 只能通过更强证据或显式处置推进，不能自动解释成成功或失败。
6. 未解决任务不能因超时、容量、会话结束或治理组件异常静默消失。

## 阶段总览

| 阶段 | 核心目标 | 主要产出 | 前置依赖 |
| --- | --- | --- | --- |
| WP-01 | 固定协议语义和机械边界 | v5 Schema、运行时常量、一致性测试 | 无 |
| WP-02 | 建立可靠的最小持久状态 | 三平面 StateStore、稳定锁、原子写入、容量边界 | WP-01 |
| WP-03 | 建立确定性派发主路径 | PreparedContract、task ref、精确 identity/provenance | WP-01、WP-02 |
| WP-04 | 建立显式通信和生命周期操作 | pending operation、恢复、继续和中断对账 | WP-02、WP-03 |
| WP-05 | 建立终态通知观察通道 | exact sender 绑定、幂等通知记录、父处置入口 | WP-01～WP-04 |
| WP-06 | 完成等待、异常恢复和会话闭环 | action-required、巡检、Session、Stop、tombstone | WP-02～WP-05 |
| WP-07 | 收敛支撑能力 | 无副作用诊断、轻量 group、派生视图 | WP-02、WP-05、WP-06 |
| WP-08 | 清除旧设计并完成发布准备 | v4 结果路径退役、全仓验证、发布边界 | WP-01～WP-07 |

## 阶段边界

### WP-01 语义与 Schema 基线

- 统一 TaskContract、治理等级、上下文策略、execution 三平面和父生命周期动作。
- 固定状态枚举、空值与 `unknown`、有限次数和机械组合校验。
- 建立 Schema、Skill、运行时和测试的一致性检查。

### WP-02 StateStore 安全底座

- 每个 Session 使用一份 JSON 和稳定 lock。
- 锁内 compare-and-set、原子替换并回读验证。
- 损坏状态不得伪装为空 Session；未解决任务不得被通用裁剪。
- canonical execution 只包含 `dispatch_record`、`observation_record` 和 `closure_record`。

### WP-03 确定性派发与身份绑定

- 结构化参数生成 TaskContract 和确定性 task ref。
- governed spawn 在原生调用前完成 preparation、claim 和回读门禁。
- identity 只由可靠原生响应或精确 target provenance 建立。
- 删除业务正文解析和弱候选身份匹配。

### WP-04 通信与生命周期操作

- 使用显式 operation type 区分普通消息、平台恢复、business resume 和中断。
- pending operation 使用 prepared/claimed 两阶段与 `tool_use_id` 对账。
- follow-up 和 interrupt 分别处理 success、failed、unknown。
- 派发重试与平台恢复使用独立计数；不存在结果补交或结果纠正操作。

### WP-05 终态通知通道

- 父 Agent 从原生 child notification 获得业务结果，并提交 exact sender target、task、attempt 和 terminal status 的最小观察。
- 相同通知幂等；terminal status 冲突保留首个事实并进入 reconcile。
- 通知正文、证据和业务判断不进入 StateStore。
- `close_task` 只表达生命周期关闭；继续执行由 `business_resume` 创建新 attempt，不维护业务验收状态。

### WP-06 等待、恢复和会话闭环

- recent activity 与 action-required 分离。
- 正常等待20分钟后只做一次精确目标巡检；平台错误立即巡检。
- 平台终态先到时进入 `await_notification`；精确通知到达后进入 `await_parent`。
- Stop 固定 advisory/fail-open；SessionEnd 不删除未决任务或保留期 tombstone。

### WP-07 最小诊断与轻量 group

- 诊断无锁、只读、无副作用，不扫描 transcript、通知正文或旧结果目录。
- 输出 execution、identity、platform observation、notification、closure 和 allowed actions。
- group 只保存成员和 required 标志，聚合通知/关闭 readiness 与 individual action-required。
- 不引入 DAG、调度器、AggregateResult 或组级业务状态机。

### WP-08 旧路径退役与发布准备

- 删除 TaskResult Schema、结果读写 API、摘要/冲突字段、纠正重试和 accept/reject 分支。
- v4 -> v5 迁移删除旧结果字段；只有精确绑定的旧父记录可降维成 notification。
- v5 不读取、创建或删除旧磁盘 `results/`；历史数据由用户确认后手工清理。
- 当前文档、测试、Manifest 和 validator 必须只把 v5 描述为现行协议。

## 验收

运行时代码变更至少执行：

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
git diff --check
```

本地验证不能证明 Hook trust、真实通知投递、provider 行为或安装缓存选择。未执行的新任务真实插件测试必须标记为 `not_checked`，不得据此宣称稳定发布验收完成。

## 参考关系

- 当前功能与删除裁决：`docs/project-function-inventory.md`
- 机器语义：`schemas/governance-semantics.schema.json`
- Agent 执行协议：`skills/subagent-governance/SKILL.md`
- 运行边界：`skills/subagent-governance/references/runtime-boundaries.md`
- 发布流程：`docs/release-process.md`，仅在另行取得授权后执行
- `docs/redesign/` 与 `docs/function-inventory/SG-F*.md`：v4 历史证据，不是 v5 权威来源
