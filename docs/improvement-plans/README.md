# Current-only 改进方案索引

本目录记录 2026-08-24 审查后确认的 current-only 改进方案，供后续在独立 Codex 对话中逐项实施。

## 统一执行约束

- 每个方案使用独立新对话执行。
- 执行模型：`gpt-5.6-terra`。
- 推理强度：`high`。
- 开始前读取仓库根目录 `AGENTS.md` 和本索引。
- 本仓库是唯一开发源；不得直接修改稳定发布源或运行缓存。
- 工作树当前已有大量用户改动；执行者必须保留这些改动，不能 reset、恢复已删除文件或清理无关内容。
- 不兼容历史状态、旧 TaskContract、旧 PreparedContract 或旧 task name；旧数据不得迁移到当前格式。
- 除 P10 外，不安装、不发布、不修改 Hook trust、Marketplace、Registry 或插件运行缓存。
- 每个方案完成后先提交仓库内验证证据，再开始下一个方案。
- 遇到文档中的停止条件时，停止扩展范围并向用户报告，不做临时跨层补丁。

## 顺序和依赖

| 顺序 | 方案 | 性质 | 前置 |
|---|---|---|---|
| P1 | [v6 严格状态契约与全新数据命名空间](P1-v6-strict-state-and-namespace.md) | 正确性、历史残留 | 无 |
| P2 | [统一 CLI/Hook UTF-8 字节边界](P2-utf8-byte-input-boundary.md) | 正确性 | 可与 P1 独立，但建议 P1 后执行 |
| P3 | [存储基础设施与 StateStore 拆分](P3-storage-and-state-store-extraction.md) | 架构债务 | P1 |
| P4 | [契约、上下文、PreparedContract 与派发协议拆分](P4-contract-context-prepared-protocol.md) | 架构债务 | P1、P3 |
| P5 | [Canonical Execution Kernel 与派发事务拆分](P5-execution-and-dispatch-transactions.md) | 正确性、架构债务 | P1–P4 |
| P6 | [通信、恢复、中断、Business Resume 与终态闭环](P6-lifecycle-operations.md) | 正确性、架构债务 | P1–P5 |
| P7 | [决策视图、Group、Session 与只读诊断](P7-views-groups-sessions-diagnostics.md) | 正确性、架构债务 | P1–P6 |
| P8 | [平台适配、Hook 路由与 CLI 门面](P8-platform-hook-cli-entrypoints.md) | 架构债务、边界收口 | P1–P7 |
| P9 | [仓库内综合验收与文档/Schema/Skill 一致性](P9-local-integrated-acceptance.md) | 验证 | P1–P8 |
| P10 | [经授权安装和新对话真实平台验证](P10-authorized-install-and-real-validation.md) | 真实验证 | P9 |
| P11 | [followup PostToolUse 与 exact-list 的 current-only 绑定](P11-followup-posttool-and-exact-list-binding.md) | 正确性、可观测性、真实验证修复 | P10-B V4 failure；须先完成P11本地门禁后才可重跑P10 |
| P12-A | [governed spawn PostToolUse 最小诊断门槛](P12A-minimal-spawn-post-diagnostics.md) | 有界诊断、停止门槛 | P11 已安装后的 P10-B V2 failure；不改 canonical 状态机 |
| P12-B | [governed spawn PostToolUse 与 canonical identity 条件修复](P12-governed-spawn-posttool-and-identity-binding.md) | 条件正确性修复 | 仅在 P12-A 真实证据满足激活门槛后实施，并按证据缩减范围 |
| P13 | [运行缓存双版本滚动保留与安装事务收口](P13-rolling-two-version-runtime-cache.md) | 安装正确性、旧会话重启兼容 | P12-A 本地门禁；下一次测试安装前必须完成 |
| P14 | [开发提交到稳定测试源的事务化同步](P14-transactional-stable-source-sync.md) | 部署正确性、稳定源事务安全 | P13；下一次 P10-A 测试安装前必须完成 |

P1–P8 必须顺序执行。即使某个后续方案看起来可以独立修改，也不能在前置模块尚未落地时复制临时实现。P11 是 P10-B 真实 V4 failure 后的独立修复方案。P12-A 只诊断 P11 已安装后在 V2 暴露的 spawn 前置缺口；P12-B 不是默认下一步，只有 P12-A 的真实证据满足激活门槛时才实施。P13 独立修复安装期间旧运行缓存消失的问题；P14 补齐开发提交到非 Git 稳定测试源的事务化同步入口。P13–P14 不决定 P12-B 是否激活，但都必须在下一次安装 P12-A 前完成。P11–P14 都不替代 P10 的重新授权安装和全新真实复验；P12-A 作出继续/停止决定前，不得继续验证 P11 的 V4。

## 新对话交接模板

除 P10 外，每个执行对话可以使用以下开场指令，并把 `<PLAN>` 替换为目标文档路径：

```text
请在当前 subagent-governance 工作树中执行 <PLAN>。

执行配置使用 gpt-5.6-terra、reasoning high。开始前完整读取仓库根 AGENTS.md、
docs/improvement-plans/README.md 和目标方案。严格遵守方案的前置条件、范围、
验收标准和停止条件；保留当前工作树已有用户改动，不恢复已删除文件，不做无关清理。

先核实前置方案确实已经落地，再实施。修改后运行方案要求的验证并提交证据；
没有证据时不要声称完成。不要兼容历史状态，不安装插件、不发布、不修改稳定源、
运行缓存、Hook trust、Marketplace 或 Registry。遇到停止条件就停止并向我报告。
```

P9 使用同一模板，但它是独立验收任务：除验收报告和验证文档外，不应顺手修复实现。

P10 必须按其文档拆成安装对话和安装后全新真实验证对话；不能仅把 `<PLAN>` 交给一个旧实现对话后连续完成全部步骤。

## 对现有流程的影响

正常用户主流程保持：准备契约 → 调用原生工具 → Hook 认领/观察 → 等待或恢复 → 终态通知 → 父方处置。

有意变化集中在异常和并发边界：

- 旧状态目录和旧格式不再读取。
- retry preparation 不再覆盖已有凭证。
- business resume 会完整转移 canonical identity，并在消息中明确新 attempt。
- open work item 即使当前 resume attempt 可靠关闭，仍会保留等待 resume/close。
- unknown event 和 unmanaged spawn 不再触碰治理存储。
- diagnostics 不再尝试解释部分旧状态。

## 总体验收

P1–P8 全部完成后，应达到：

- current-state runtime validator 与 Schema 结构边界一致。
- `state-v6` 是唯一默认运行数据命名空间。
- `subagent_governance.py` 只保留入口和显式公共 facade。
- 领域模块不反向导入入口模块。
- StateStore、PreparedContractStore、dispatch、lifecycle、views、diagnostics、Hook 和 CLI 有明确所有者。
- 所有输入大小按 UTF-8 bytes 统一限制。
- governed 操作在证据不足时拒绝或进入 reconcile，不猜成功。
- unmanaged 原生通道和非 PreToolUse 失败继续遵守 fail-open 边界。
- 完整本地测试、编译和 Plugin validator 通过。
- 在 P10 前没有安装或发布行为。
