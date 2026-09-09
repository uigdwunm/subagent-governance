# state-v11 流程精简本地验收

日期：2026-09-09。实施基线：`468dc95`。结论：`passed_functional_checks_with_existing_lint_findings`。本记录对应 state-v11 开发仓库候选；记录时尚未部署、未更改运行缓存或 Hook trust、未创建真实测试任务。

## 修改与复现证据

- 基线全量测试 109 项，108 项通过，唯一失败为文档白名单遗漏已经存在的 `state-v10-hook-trust-2026-09-09.md`。补充该文档登记，保留白名单与未知文档拒绝测试。
- 先增加两项回归测试：三类 unknown 分别接收 platform/notification 终态的六个场景全部停留在 reconcile；close 后首个 reconcile 原因消失。原代码共出现七处预期失败，修改后全部通过。
- 已绑定 unknown 改为最多三类首次时间的 unknown_facts；后续确定终态可推进，close 保留 unknown、首个阻断原因及既有事实。派发未知、身份和终态冲突仍阻断；晚到 confirm 不能重新打开 closed。
- Schema/runtime 同步切换 state-v11；TaskContract v2 与现有 claim 适配保持不变。新版本不读取或迁移 state-v10，新摘要为空不证明旧任务完成。
- status/diagnose/SessionStart 共享投影，phase 与历史 unknown 分开显示；只读路径保持零写入。新增并发用例证明不同类别 unknown 不互相覆盖。
- 普通消息 success/failed 不再要求额外 CLI；同一终态证据只走一个来源入口。提示省略空区块及父方身份细节，保留任务材料、完成条件和关键配置。
- AGENTS.md 和当前真实测试交接改为父／子分别显式指定并核实 gpt-6-astra/high；模型运行入口仍保持可选覆盖。

## 本地检查

| 检查 | 结果 |
| --- | --- |
| `python3 -m unittest discover -s tests -v` | 117 tests passed，Python 3.9.6；补充的终态来源／未绑定字段断言单独复验通过 |
| `python3.12 -m unittest discover -s tests -v` | 117 tests passed，Python 3.12.13 |
| `python3 -m compileall -q scripts` | passed |
| Plugin validator | passed |
| Skill validator | passed |
| `python3 scripts/release_preflight.py --mode development` | passed；未执行 release/archive 或安装 |
| Python 3.11.15 branch coverage | 117 tests passed；综合语句／分支覆盖率 73%，达到仓库 70% 门槛 |
| `ruff check scripts tests` | 未全通过：3 项既有 F401；HEAD 基线为 14 项，本次未新增 lint 问题 |
| `git diff --check` 及修改文档链接／结构 | passed |

新增用例覆盖 unknown → 确定终态 → close、三类 unknown 幂等与并发保留、错误身份零事实写入、首个终态／阻断原因保留、closed 不重开、runtime/Schema 非法字段与无绑定身份拒绝、只读恢复摘要、CLI 串联和精简正文的材料保真。既有精确绑定、存储、容量、unmanaged 和部署事务测试继续运行。

lint 使用 ruff 0.16.6，覆盖率使用 coverage 7.16.0，均安装在隔离的临时验证环境。为判断遗留问题，将 HEAD 的 scripts/tests 与 pyproject.toml 复制到临时目录，用同一版本 ruff 对比；14 项基线问题中的导入顺序问题在本轮涉及文件中整理，以下 3 项未使用导入保持原样，不扩大清理范围：

- scripts/governance_dispatch.py：NativeInputMismatch、NativeInputUnavailable；
- scripts/governance_native_adapter.py：MESSAGE_PREFIX。

因此可以确认本轮功能／契约门禁通过、没有新增 lint 问题，但不能宣称全部 CI 门禁通过。临时验证依赖不进入 runtime bundle，未改项目依赖声明或安装插件。

## 未验证与交接

- 未部署 stable source 或当前 runtime cache；未读取或修改旧账本，运行缓存一致性未验证。
- 未验证 GPT-6 的真实调用减步、Hook 加载、实际 unknown 回执、双 Agent 并发、strict 材料校验及 compact/restart 恢复；本地 fixture 不替代平台事实。
- 未在本机运行 Windows/Linux CI；不同 OS 的结果不由 macOS 本地检查推断。
- 用户随后授权提交到 main、部署本机及重启后真实测试；部署候选缓存版本更新为 `0.4.0+codex.20260909113817`，公共版本仍为 0.4.0。本文记录于部署前，安装结果以事务输出为准；命令结束停止，等待用户确认重启，再在独立新任务以显式 gpt-6-astra/high 验证。
- [实施方案](../improvement-plans/gpt6-workflow-simplification-2026-09-09.md)列明真实验收矩阵及 state-v11 切换限制。

---

以下为历史 state-v9 本地验收，不替代当前候选结果。

# state-v9 减法收口本地验收

日期：2026-08-25
结论：`passed`（开发仓库本地验收；不以安装或真实平台状态替代本地证据）

## 验收对象与边界

- 决策基线：`dc99228`；部署边界补充：`5bc2b1b`。
- state-v9 dispatch：`3729ec3`；最小 lifecycle：`a6fcaa4`。
- allowlisted runtime 与单一开发部署实现：`bc6a61ff0e5aff1fae7cc76cc99ab213607b886b`。
- cache rollover 二次确认删除：`3a3a66ff8e014a3d56c4e6384704fcb200a2e65b`。
- missing claim 精确分类修复：`308f28f3fe6a6a0d152f888e9dcdcea79b0f5f65`。
- 当前 working-tree 候选另含 Hook 原生工具精确 allowlist、runtime 禁写 bytecode、retained-previous 精确校验及其回归测试；用户已有的 `AGENTS.md` 修改保持原样，不属于本次实现。
- 当前 manifest 候选版本：`0.4.0-rc.13+codex.20260825073554`。
- 当前格式精确为 `state_format_version=9` / `state-v9`；TaskContract 为 v2。
- 本记录只描述开发仓库证据；外部安装与真实平台证据单独记录。当前候选尚未提交，工作树同时保留用户已有的 `AGENTS.md` 修改，不满足 `dev_deploy.py --execute` 的 clean exact HEAD admission，也未执行部署。

## 产品承诺覆盖

| 边界 | 本地证据 | 结果 |
| --- | --- | --- |
| 单一 ledger/current-only | strict v9 runtime/Schema parity；v8 保持原样且无 migration/read/repair/delete | passed |
| TaskContract v2 | standard/strict defaults、strict required fields、verified opt-in、business/spawn digest 分离 | passed |
| prepare/claim/confirm | 同一 ledger 原子 `prepared→claimed`；first-bind-wins；same replay 幂等；冲突 reconcile | passed |
| crash gap | native return 后 confirm 前保持 claimed/unbound；无 retry/list/name/time/final 推断 | passed |
| 最小 lifecycle | exact bound observation、terminal sender/status/time、interrupt 机械结果、parent close | passed |
| 非持久事实 | wait 不持久化；normal call success/failed 零写入；unknown 仅最小 reconcile reason | passed |
| Hook/恢复 | 仅四个已确认原生 spawn 名称的精确 Pre 与 read-only SessionStart；第三方/未知名称 inert fail-open；missing state 零写入 | passed |
| 存储安全 | UTF-8 byte limit、owner/permission、symlink/nonregular、capacity、atomic replace、并发 | passed |
| runtime bundle | 30 文件机器 allowlist；import closure；入口导入前禁写 bytecode；exact projection；额外文件、symlink、unsafe mode 拒绝 | passed |
| 开发部署 | clean exact HEAD、dry-run 零写、selected previous 三阶段精确校验、双版本 retention、digest、atomic activation、rollback/interruption recovery | passed |
| 删除旧 authority | PreparedContractStore、agents index、Post receipt/index、attempt、pending action、tombstone、Group 与四个旧部署入口不存在 | passed |

## Runtime projection

- allowlist：`.codex-plugin/runtime-bundle.json`，精确 30 files。
- 验收 digest：`50e1e2b3b26fd8eec37c4cbe0227a6f796b24028dd328b90a5f0685f590d8fc4`。
- 独立 temporary staging 的 `verify_runtime_bundle` 与 Plugin validator 均通过。
- tests、CI、plans、validation、`AGENTS.md`、开发依赖、release preflight、`runtime_bundle.py`、`dev_deploy.py` 均不在 projection。
- 修改被排除的开发文件不改变 bundle digest；目标树多一个文件即被 exact verifier 拒绝。

## 门禁结果

| 命令 | exit | 摘要 |
| --- | ---: | --- |
| `python3 -m unittest discover -s tests -v` | 0 | Python 3.9.6，92 tests passed |
| `python3.11 -m unittest discover -s tests -v` | 0 | Python 3.11.15，92 tests passed |
| `python3.12 -m unittest discover -s tests -v` | 0 | Python 3.12.13，92 tests passed |
| 三版本 `python -m py_compile scripts/*.py` | 0 | passed |
| `python3 scripts/release_preflight.py --mode development` | 0 | `status=passed` |
| repository Plugin validator | 0 | passed |
| exact staged runtime Plugin validator | 0 | passed |
| Skill validator | 0 | valid |
| `git diff --check` | 0 | passed |

`ruff` 与 `coverage` 不在 PATH；本次没有安装，也没有记为通过。测试数量从历史 325 缩到当前 92 是删除旧内部机制锁定测试的结果，不作为单独质量指标。

## 开发部署事务边界

`scripts/dev_deploy.py` 是唯一入口，默认 dry-run。单元测试覆盖：

- empty/single/two cache admission、显式 previous identity，以及无需二次确认的 `A+B → B+C` 轮换；
- target cache 预存在时在调用原生命令前拒绝；
- successful target + exact previous retention，以及 A+B → B+C rollover；
- selected previous 含额外 bytecode 时在原生命令前拒绝；脏 oldest 未被选择时仍可由成功 rollover 淘汰；
- 原生命令失败、target digest 错误时恢复部署前 stable 和完整 cache set；
- stable activation 后中断，以及两次 atomic rename 之间 stable 暂时缺失时的精确 transaction recovery。

这些测试使用 temporary Git source、stable 与 cache，并用 runner fixture 模拟原生命令；它们不构成真实 Codex 安装证据。

## 未验证边界

以下项目不由本地验收给出结论：

- 实际 stable activation、Codex runtime cache selection 与 exact previous retention；
- 已安装历史 previous 中现存的额外 `.pyc` 尚未清理；本地修复不会越权改写该缓存；
- Hook trust、Codex registration、桌面 UI；其中 Hook trust 的独立平台证据见真实验证记录；
- 真实 prepare → claim → native spawn → explicit confirm；
- wait/list observation、terminal、interrupt、close、SessionStart 与 restart/compact。

实际部署必须单独获得用户授权；本次授权与执行状态不作为本地验收结论。`dev_deploy.py --execute` 完成后应停止当前任务并等待重启，再在新的独立任务执行真实验证。P12-B 已 rejected/archived，不作为后续待办。
