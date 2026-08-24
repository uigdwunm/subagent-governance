# P10：经授权安装和新对话真实平台验证

状态：已确认方案，执行时必须重新取得安装授权。

前置：P9 报告结论为 `passed`，且没有未解决的本地正确性失败。

执行配置：安装对话和真实验证对话均使用 `gpt-5.6-terra`、推理强度 `high`。

## 目标

在不发布稳定版的前提下，将已经通过 P9 的开发仓库版本安装到本地测试插件环境，并在安装后创建全新 Codex 对话验证真实 Hook、原生子 Agent、等待/通信/终态通知、restart/compact 和 business resume 行为。

P10 不是发布流程：

- 不推送 commit/tag。
- 不更新公共 Marketplace ref。
- 不发布稳定版本。
- 不把本地测试安装描述为 release-ready。

## 必须拆成两个对话

### P10-A：安装与安装后只读检查

- 使用本项目工作树。
- 读取本方案、`AGENTS.md` 和适用的 plugin-creator Skill。
- 取得明确安装授权后执行本地测试安装。
- 不执行真实子 Agent 场景来代替新对话。

### P10-B：全新真实平台验证

- 安装完成后由用户新建独立 Codex 对话。
- 不复用 P1–P9 或 P10-A 对话。
- 使用 `gpt-5.6-terra`、`high`。
- 在当前项目中运行真实插件场景。
- 使用 `$subagent-governance` 时按 Skill 真实派发原生子 Agent。

P10-A 不能因为安装成功就把 P10 标记完成；P10-B 未完成时状态只能是 `installed_not_real_validated`。

## P10-A 授权检查点

执行者必须在任何外部写入前向用户列出并确认：

- 开发仓库绝对路径和目标 commit/version。
- 稳定测试源路径。
- 当前运行 cache 路径和版本。
-将写入的稳定测试源、cache、transaction snapshot 和受管理 AGENTS block。
-安装后是保留测试版本还是另行恢复。

用户明确说“执行 P10 安装”可以作为授权，但如果目标路径、版本或保留策略与文档不一致，必须再次询问。

未经授权只能执行只读预检。

## 安装前只读预检

确认：

- P9 报告存在且 passed。
- target commit/worktree 与报告一致；如 cachebuster 造成 Manifest-only 变化，重新运行相关 P9 门禁。
- developer/stable/cache 是三个不同的普通目录，不是 symlink。
- owner/permissions 安全。
- 运行 `codex plugin list`，记录安装前实际 registered/current 的完整版本；cache parent 可以含遗留 cache，但该版本必须以 `--previous-version` 精确传入 installer，禁止按目录名、mtime 或语义版本推测。
-没有未完成/损坏的 install transaction；如果有，只使用受支持的 recovery 流程。
- 当前 stable/cache digests 和 Manifest version 已记录。
-当前 Hook trust 和 Codex registration 仍标记 not checked，而不是从文件存在推断。

不得使用 `rm -rf`、手工删除 cache 或直接编辑 cache 文件。

## 测试版本和同步

本地测试安装必须使用唯一完整 Manifest version，防止 Codex 复用旧 cache。

- 使用 plugin-creator 支持的 cachebuster/update 流程。
- 不改变 public version/tag/Marketplace ref，除非用户另行授权发布。
- cachebuster 修改发生在开发仓库唯一源。
- 修改后重跑 Manifest、development preflight、Plugin validator、Skill validator 和核心完整测试。
- 再通过受支持的本地插件同步/安装流程更新测试 stable source；不得先改 cache 再反向补仓库。

如果当前 plugin-creator 流程与仓库 `reinstall_plugin.py` 的事务要求不一致，停止并询问，不自行设计复制/覆盖命令。

## 安装事务

使用仓库支持的安装工具或 plugin-creator 指定流程，必须保留：

- OS file lock；
-当前 cache snapshot；
- same-filesystem 检查；
- 调用原生命令前从运行脚本的稳定测试源绑定完整 tree digest；命令返回后 stable digest 必须保持不变，且 target cache digest 必须精确相等；
-安装失败自动恢复；
-成功后保留目标 current 与精确安装前 current 作为 retained previous compatibility cache；下一次更新会在显式确认旧会话已重启或关闭后删除更早 cache；
- transaction snapshot 成功/回滚后清理。

P10-A 的安装命令必须同时传入只读事实中的精确 previous/current 与目标完整 Manifest version：

```bash
python3 <stable-plugin-root>/scripts/reinstall_plugin.py \
  --previous-version <exact-version-from-codex-plugin-list> \
  --target-version <target-full-manifest-version>
```

其中 `--previous-version` 是安装前 Codex registered/current 版本；`--target-version` 是安装后期望的 current 完整 Manifest version。两者不得相同。事务会先快照所有已有 cache，成功确认有效目标 cache 后精确保留 target 与 exact previous；如安装前已有 retained previous compatibility cache，还必须传入 `--confirm-previous-sessions-restarted`。该确认不推断会话状态，只表示操作者已重启或关闭仍依赖最早 cache 的会话。

不得：

- 直接编辑 `~/.codex/plugins/cache/...`；
-手工删除旧 cache 绕过 installer；
-在 cache 中调试代码；
-创建 developer/stable/cache symlink。

## 安装后只读检查

运行 `check_installation.py --require-development-sync` 或当前等价命令，必须证明：

- stable digest = cache digest；
- development rules 与部署规则一致；
- developer/stable/cache 路径独立；
-恰好一个 current cache，并允许零或一个 retained previous compatibility cache；
-无额外 transaction snapshot；
- Manifest full version 等于目标版本。

安装检查仍不能证明：

- Codex registration；
- Hook trust；
-真实事件投递。

这些字段继续保持 `not_checked`，交给 P10-B。

## P10-B 开始条件

新对话首先记录：

- 目标 Manifest full version。
-安装检查摘要/digest。
-当前项目路径。
-当前模型 `gpt-5.6-terra` 和 reasoning `high`。
- Skill/Hook 是否在新对话可见。

如果新对话未加载目标版本、Hook trust 要求用户确认或插件不可见：

- 暂停测试；
-让用户处理明确的 UI/trust/restart 步骤；
-不得通过直接修改 trust 文件绕过。

## 真实验证场景

每个场景必须记录：操作、原生 target/tool-use id、canonical state 摘要、实际 UI/Hook 现象和结论。不要记录不必要的业务正文或完整 transcript。

### V1：插件和 Hook 基线

- 确认实际加载目标版本。
- 触发已注册但无治理状态的安全事件，确认入口工作。
- unknown/unmatched 工具不产生治理状态。
- unmanaged native spawn 被放行，且不创建 managed task。
-确认 Hook trust/事件输出在 UI 中的实际表现。

### V2：Governed spawn、wait 与 exact identity

- 使用 Skill 生成合法 TaskContract 和 PreparedContract。
- 调用真实原生 `spawn_agent`。
-确认 PreToolUse claim、PostToolUse observation 和 canonical task/ref/digest。
-记录平台返回的 exact Agent target。
-使用真实 wait，并以平台返回的完整 target 调用 `list_agents({"path_prefix": "<exact target>"})`；禁止使用 `{}`、父路径或全量列表代替 exact observation。
-确认对应 attempt 的 `observation_record.source == "list_agents"`；若未写入，只能标记该 observation 未执行或被拒绝，必须记录 Hook 的有界原因码。
-禁止重复派发同一凭证。

### V3：通信、终态通知和父关闭

- 对 managed target 准备并发送 normal message。
-确认 pending prepare/claim/Post 收口。
-等待子 Agent 产生真实终态通知/最终消息。
-父方使用 exact sender target、task id、attempt 记录 terminal notification。
-验证 replay 幂等和 sender mismatch 拒绝；不要伪造业务结果。
-执行 parent close，确认 tombstone 和 exact agents index 清理。

### V4：Business resume

- 从 exact terminal notification + decide disposition 准备 resume contract。
-真实调用 `followup_task`。
-确认 source attempt closed、N+1 current、target/tool-use/index 全部转移。
-确认 followup message 中有 N+1 task/attempt/ref。
-对子 Agent 再次等待并记录 N+1 terminal notification。
-确认 list-agents/communication 命中 N+1，而不是 source attempt。

如果真实 followup response 为 unknown 或与 fixture 不一致，如实记录 adapter 结果；不得在验证对话修改 adapter。

### V5：Interrupt 和受控对账

- 创建一个可安全中断的长耗时 managed Agent。
-准备 exact interrupt pending，调用原生 interrupt。
-记录真实 `previous_status/status` response shape。
-使用 exact list/wait 对账；list 必须显式传入完整 canonical target 作为 `path_prefix`。
-确认 not-found 不被单独当作 inactive，或在所需先验齐全时完成受控 reconciliation。
-确认 recovery/interrupt budget 和 pending 没有重复消费。

### V6：Stop、SessionStart、SessionEnd

- 在存在 action-required work item 时观察 Stop advisory，确认不 hard block。
-观察 SessionStart summary、字段边界和 UI 展示。
-完成/关闭任务后观察 SessionEnd 删除或保留逻辑。
-确认 tombstone retention 和 degraded health 不被错误清理。

### V7：Restart/compact 恢复

- 保持至少一个 managed Agent 或待决策 work item。
- 由用户通过真实 Codex UI 触发 restart/resume 或 compact；不得用 fixture 代替。
-确认新 SessionStart 摘要出现。
-确认没有重复创建 Agent。
-使用 retained exact target 继续 wait/message/reconcile。
-记录 mailbox/通知在 compact 前后的可见性。

如果平台不允许当前环境安全触发 compact/restart，标记 `not_checked_platform_unavailable`，不能记 passed。

## 不作为默认要求的破坏性负向测试

真实安装失败回滚、故意损坏 cache、强制 Hook trust 失败等测试会影响外部状态，默认不执行。

只有用户另行明确授权具体负向场景后，才可使用 installer 支持的可恢复事务测试。仓库内 fault-injection 单测不能冒充真实回滚，但不需要为了 P10 通过而冒险破坏健康安装。

## 缺陷处理

真实验证发现缺陷时：

1. 停止当前场景，保存有界事实和状态摘要。
2. 不修改 stable source、cache 或 Hook trust。
3. 不在 P10-B 对话直接修复运行代码。
4. 回开发仓库开启新的修复对话，先本地复现。
5. 修复后重新执行相关 P1–P9 门禁。
6. 重新授权安装，并创建另一个全新真实验证对话。

同一个失败后的真实测试对话不能在热修改 cache 后继续充当验收。

## 验收报告

P10-B 创建或更新：

```text
docs/validation/current-only-real-platform-validation.md
```

报告包含：

- target version/commit/digests；
-安装授权和安装检查摘要；
- Hook trust/registration 的实际状态；
- V1–V7 每项 `passed`、`failed`、`not_checked`；
-真实 raw response 的有界结构摘要；
- restart/compact/mailbox/UI 观察；
-遗留问题和清理/保留策略。

同步更新 `docs/platform-validation.md`：只有实际执行并取得证据的条目才能从“尚待真实验证”移动到“已验证”。

## P10 完成标准

P10 只有以下成立才可宣称完整完成：

- P9 passed。
-授权安装事务成功，安装后 digests/paths/cache 检查通过。
-新独立对话实际加载目标插件版本。
- governed spawn、wait/exact identity、communication、terminal notification、parent close 通过。
- business resume identity 转移通过。
- interrupt 和 Session event 真实边界通过。
- restart/compact 已真实通过；若平台不可用，则整体结论必须注明部分验证，不能称完整通过。
- Hook trust/registration 不再由文件状态推断。
-报告和 platform-validation 文档已更新。
-没有发布、tag 或公共 Marketplace 写入。

## 停止条件

- P9 未 passed 或目标源码在 P9 后发生未验证变化。
-没有明确安装授权。
- developer/stable/cache 路径相同、symlink 或权限不安全。
- cache 多版本/transaction 状态异常且无法由受支持工具恢复。
- installer、plugin-creator 和仓库流程要求冲突。
-安装后 digest/version 不一致。
-新对话未加载目标插件或 Hook trust 未解决。
-真实场景出现正确性失败；返回开发仓库，不热修缓存。
