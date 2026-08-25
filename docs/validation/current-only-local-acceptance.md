# state-v9 减法收口本地验收

日期：2026-08-25
结论：`passed`（开发仓库本地验收；不以安装或真实平台状态替代本地证据）

## 验收对象与边界

- 决策基线：`dc99228`；部署边界补充：`5bc2b1b`。
- state-v9 dispatch：`3729ec3`；最小 lifecycle：`a6fcaa4`。
- allowlisted runtime 与单一开发部署实现：`bc6a61ff0e5aff1fae7cc76cc99ab213607b886b`。
- cache rollover 二次确认删除：`3a3a66ff8e014a3d56c4e6384704fcb200a2e65b`。
- missing claim 精确分类修复：`308f28f3fe6a6a0d152f888e9dcdcea79b0f5f65`。
- 当前部署候选版本：`0.4.0-rc.13+codex.20260825045151`。
- 当前格式精确为 `state_format_version=9` / `state-v9`；TaskContract 为 v2。
- 本记录只描述开发仓库证据；外部安装与真实平台证据单独记录。生成本次候选时尚未运行 `dev_deploy.py --execute`。

## 产品承诺覆盖

| 边界 | 本地证据 | 结果 |
| --- | --- | --- |
| 单一 ledger/current-only | strict v9 runtime/Schema parity；v8 保持原样且无 migration/read/repair/delete | passed |
| TaskContract v2 | standard/strict defaults、strict required fields、verified opt-in、business/spawn digest 分离 | passed |
| prepare/claim/confirm | 同一 ledger 原子 `prepared→claimed`；first-bind-wins；same replay 幂等；冲突 reconcile | passed |
| crash gap | native return 后 confirm 前保持 claimed/unbound；无 retry/list/name/time/final 推断 | passed |
| 最小 lifecycle | exact bound observation、terminal sender/status/time、interrupt 机械结果、parent close | passed |
| 非持久事实 | wait 不持久化；normal call success/failed 零写入；unknown 仅最小 reconcile reason | passed |
| Hook/恢复 | 仅 spawn Pre 与 read-only SessionStart；unmanaged inert fail-open；missing state 零写入 | passed |
| 存储安全 | UTF-8 byte limit、owner/permission、symlink/nonregular、capacity、atomic replace、并发 | passed |
| runtime bundle | 30 文件机器 allowlist；import closure；exact projection；额外文件、symlink、unsafe mode 拒绝 | passed |
| 开发部署 | clean exact HEAD、dry-run 零写、exact previous、双版本 retention、digest、atomic activation、rollback/interruption recovery | passed |
| 删除旧 authority | PreparedContractStore、agents index、Post receipt/index、attempt、pending action、tombstone、Group 与四个旧部署入口不存在 | passed |

## Runtime projection

- allowlist：`.codex-plugin/runtime-bundle.json`，精确 30 files。
- 验收 digest：`d67d3a11975df6f8287ea3e374f33a914c6638d48e3c5c56b40f6f2b65789dcb`。
- 独立 temporary staging 的 `verify_runtime_bundle` 与 Plugin validator 均通过。
- tests、CI、plans、validation、`AGENTS.md`、开发依赖、release preflight、`runtime_bundle.py`、`dev_deploy.py` 均不在 projection。
- 修改被排除的开发文件不改变 bundle digest；目标树多一个文件即被 exact verifier 拒绝。

## 门禁结果

| 命令 | exit | 摘要 |
| --- | ---: | --- |
| `python3 -m unittest discover -s tests -v` | 0 | Python 3.9.6，81 tests passed |
| `python3.11 -m unittest discover -s tests -v` | 0 | Python 3.11.15，81 tests passed |
| `python3.12 -m unittest discover -s tests -v` | 0 | Python 3.12.13，81 tests passed |
| 三版本 `python -m py_compile scripts/*.py` | 0 | passed |
| `python3 scripts/release_preflight.py --mode development` | 0 | `status=passed` |
| repository Plugin validator | 0 | passed |
| exact staged runtime Plugin validator | 0 | passed |
| Skill validator | 0 | valid |
| `git diff --check` | 0 | passed |

`ruff` 与 `coverage` 不在 PATH；本次没有安装，也没有记为通过。测试数量从历史 325 缩到当前 81 是删除旧内部机制锁定测试的结果，不作为单独质量指标。

## 开发部署事务边界

`scripts/dev_deploy.py` 是唯一入口，默认 dry-run。单元测试覆盖：

- empty/single/two cache admission、显式 previous identity，以及无需二次确认的 `A+B → B+C` 轮换；
- target cache 预存在时在调用原生命令前拒绝；
- successful target + exact previous retention，以及 A+B → B+C rollover；
- 原生命令失败、target digest 错误时恢复部署前 stable 和完整 cache set；
- stable activation 后中断，以及两次 atomic rename 之间 stable 暂时缺失时的精确 transaction recovery。

这些测试使用 temporary Git source、stable 与 cache，并用 runner fixture 模拟原生命令；它们不构成真实 Codex 安装证据。

## 未验证边界

以下项目不由本地验收给出结论：

- 实际 stable activation、Codex runtime cache selection 与 exact previous retention；
- Hook trust、Codex registration、桌面 UI；其中 Hook trust 的独立平台证据见真实验证记录；
- 真实 prepare → claim → native spawn → explicit confirm；
- wait/list observation、terminal、interrupt、close、SessionStart 与 restart/compact。

实际部署必须单独获得用户授权；本次授权与执行状态不作为本地验收结论。`dev_deploy.py --execute` 完成后应停止当前任务并等待重启，再在新的独立任务执行真实验证。P12-B 已 rejected/archived，不作为后续待办。
