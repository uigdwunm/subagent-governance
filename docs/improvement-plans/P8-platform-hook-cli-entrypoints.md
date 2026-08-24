# P8：平台适配、Hook 路由与 CLI 门面收口

状态：已确认，待独立对话实施。

前置：P1–P7。

## 目标

将原始平台响应限制在纯 adapter，将 Hook 限制为路由/错误映射，将 CLI 改为直接依赖领域模块；最终把 `subagent_governance.py` 缩成入口和显式公共 facade。

## `governance_platform.py`

纯 adapter，迁入 JSON-value、native status、spawn/call/list-agents 适配。

建议输出不可变 normalized types：

- `SpawnCallObservation(success|failed|unknown, canonical_target)`
- `LifecycleCallObservation(success|failed|unknown, target_observation)`
- `AgentStatusObservation(target, normalized_status, bounded_summary)`

只解析整个 response string 一次；不递归解析嵌套字符串，不扫描文本片段，不任意深度寻找 status/id。

显式 error 优先于 success；未知响应进入 unknown。Interrupt not-found 不直接证明 inactive。List-agents 只接受可信顶层 `agents` 和 exact `/...` query；多条/不匹配/模糊 query 不产生 canonical fact。

外部 Hook payload 允许未知平台字段以保持前向兼容；内部 persisted formats 仍 strict current-only。

## `governance_hook.py`

公开 `handle_hook(payload, state_store=None)`，负责：

- event/tool classification
- lazy store construction
-领域 service 调用
- allow/deny/fail-open Hook JSON

不实现 contract/state transitions、store callbacks 或 raw response guessing。

### Lazy store

Unknown event/tool、unmanaged spawn、governed-prefix malformed name 均不构造 store。只有需要治理事实时才构造；失败则使用 unavailable store 进入既定策略。

### PreToolUse

- unmanaged spawn 原样 allow、零存储触碰。
- governed malformed name deny、零存储触碰。
- governed claim 双门禁失败 deny。
- communication/interrupt 根据 P6 admission；normal/interrupt 明确 unavailable 可 fail-open，resume/recovery ambiguous/unavailable deny。

### PostToolUse

adapter 先规范化，再调用 P5/P6。原生调用已发生，任何记录失败只返回 warning/continue，不伪造 deny。

### Stop/Session

只格式化 P7 domain result；Stop 总是 advisory continue，SessionStart 输出 bounded additional context，SessionEnd 总是 continue。

## 输入失败边界

使用 P2 binary reader。

- 超限/非法 UTF-8/JSON/非对象发生在解析前，event 不可信：fail-open，不扫描前缀。
- 已解析 dict 且 event=PreToolUse 后的 handler error：deny。
- 其他 event error：continue + warning。
- unknown event：None、零存储、零输出。

## 重写 `governance_cli.py`

删除 `ModuleType` runtime 参数和所有 `runtime._private` 访问。直接导入 stores、context、dispatch、lifecycle、groups、diagnostics、hook。

建议 main 可注入 binary stdin/stdout 和 text stderr。所有 JSON stdin 模式共用 P2 reader；diagnose/read-group 不读 stdin。

保留现有 flags 和用户命令，不改 subcommands。保持退出码：0 成功/Hook fail-open，1 业务/诊断失败，2 参数错误。

写操作 explicit data root 才准备私有目录；diagnose explicit root 只读，不能创建目录。

## 最终 `subagent_governance.py`

只包含：

- CLI main
- Hook handle
- curated public re-exports
- `if __name__ == "__main__"`

显式 `__all__` 推荐保留 TaskContract、stores、prepare APIs、lifecycle/group APIs、handle hook。删除 `_data_root`、`_deny`、diagnostic/contract/execution 私有 helper 等 facade 兼容；测试改导入真实所有者，不建动态 proxy。

## Hooks manifest 对账

静态验证 matcher 与 tool classifier 一致：Pre spawn/send/followup/interrupt，Post 额外 list_agents；SessionStart matcher 和 `additionalContextLimit=1800` 一致；command/Windows command 指向唯一入口。

P8 不修改 Hook trust 或安装缓存。

## 实施顺序

1. 为所有 raw response 建 table-driven characterization。
2. 抽取 platform adapters，领域改收 normalized values。
3. 建 Hook router 和 lazy store。
4. 重写 CLI direct imports/binary streams。
5. 缩减 entrypoint、定义 public API、更新测试 imports。
6. matcher/router/Skill/README 命令对账。

## 测试重点

- adapter success/error/unknown/nested/interrupt/list exact 全矩阵。
- 每个 registered event/tool kind、unknown event/tool。
- unmanaged spawn 零目录写入。
- Store constructor failure 和各 event fail-open/deny。
- byte reader exact/over/多字节/invalid。
- CLI modes/conflicts/roots/exit/stdout/stderr。
- package import、直接脚本、不同 cwd、Windows branch compile。
- public API identity、私有符号消失。
- hooks matcher/router parity。

## 验收标准

- CLI 无 `ModuleType`、无 runtime private access。
- platform adapter 无状态 I/O。
- Hook router 无领域 mutation。
- unknown response 不递归猜测。
- unknown event和 unmanaged spawn 不构造 store。
- governed spawn failure deny，Post/Session failure fail-open。
- 所有输入按 UTF-8 bytes。
- 主运行时只剩入口/显式 facade，领域模块不反向导入。
- hooks/Skill/README 命令仍有效。
- 完整测试、编译、Plugin validator 通过；不安装发布。

## 停止条件

- CLI 仍需注入整个 runtime module。
- 为保留私有测试 API 引入 `__getattr__` 或动态 proxy。
- Hook router 需要重写领域状态规则。
- adapter 必须递归猜 provider response 才能让测试通过。
- diagnose 路径产生任何文件写入。
