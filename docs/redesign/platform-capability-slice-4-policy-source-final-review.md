# 平台能力 Slice 4：policy-source 最终独立复验

日期：2026-08-15

结论：**GO**。历史 malformed/explicit-error wrapper 行为 blocker 保持关闭；独立重放的 4,128 项隔离矩阵全部通过。`wrapper_status_parse_policy` 与 `malformed_or_explicit_error` 已由 runtime 从机器语义加载，并对 unsupported 值在 import 时 fail-fast；machine field-source parity 为 12/12。未发现稳定冻结不变量违例。

本结论只允许后续执行测试 cachebuster 与新建 Slice 4 真实 smoke，不批准也未执行部署、安装、稳定源或运行缓存同步、Hook trust 修改、其他真实任务、Slice 5、提交或推送。

## 1. 范围与写入边界

本次直接审查保存的开发仓库，保留审查开始前的全部已提交和未提交内容，不采信现有实现报告或历史 PASS。冻结范围只包括 wrapper 行为、machine policy/field source、Slice 4 其他关键不变量和指定本地门禁。

全部主动状态均在 `TemporaryDirectory` 中创建隔离 `StateStore`、结果目录或 runtime+Schema 副本。没有读取、修改或删除既有 smoke StateStore。除新增本报告外，没有修改实现、Schema、tests、fixtures、Skill、README 或既有报告。

审查时关键输入 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `scripts/subagent_governance.py` | `61e8889959cc2edafcfbad371081e945dbc6f4b9e989ae11a7f249bd6a66b8b9` |
| `schemas/governance-semantics.schema.json` | `ddcba490055629a66680486852c563624b5c250eeaed29e1add0f4dec95c39a1` |
| `tests/test_platform_capability_slice4.py` | `3bca79e44b65cd863151f0fb76360020e2fbad53b9bd19f0e29210dad1d754ba` |
| 第四轮历史 NO-GO 报告 | `f3fa2dae915cb082b38043f97ce0b92d4bd73fb033035a0d4c5de649884c4c2a` |
| Slice 4 冻结设计 | `17875871748961da19687e5e3a7791163e479f2f2f281e40bece807e9a6a025c` |

## 2. Wrapper 行为 blocker：CLOSED

独立重建第四轮等价核心矩阵，共 **4,128/4,128 PASS**：

| 分组 | 结果 | 核心覆盖 |
| --- | --- | --- |
| 单 `isError/is_error` | 80/80 | 缺失、严格 false、true、null、0、1、字符串、对象、数组 |
| 双 boolean flags | 648/648 | 两字段全类型交叉、顺序互换、object/JSON、空/非空 agents |
| explicit `error` | 40/40 | 缺失、null、false、true、`error=0`、其他 scalar/container |
| 单 `status` 或 `state` | 160/160 | 合法、四种 failure 标签、null/bool/number/空值/container/多标签 |
| 双 `status/state` | 3,200/3,200 | 全值交叉、顺序互换、object/JSON、空/非空 agents |

每个 case 使用独立临时 StateStore。空 `agents` 先用 exact `running` 建立 confirmed-active 基线。非法 wrapper 必须保持完整 canonical execution、StateStore 原始字节和结果文件快照三重不变；合法 wrapper 与去掉 wrapper 字段后的等价 control 响应逐字节一致。由此确认 malformed status/state、`error=0`、双 status/state、`failure`、object/JSON 和空/非空 agents 均无历史旁路。

## 3. Policy fail-fast 与 field-source parity

隔离复制 runtime+Schema 后得到：

| 变异 | import 结果 |
| --- | --- |
| 原始机器语义 | exit 0，`IMPORT_OK` |
| `wrapper_status_parse_policy=unsupported_final_review_value` | exit 1，`RuntimeError: unsupported list_agents wrapper status parse policy` |
| `malformed_or_explicit_error=unsupported_final_review_value` | exit 1，`RuntimeError: unsupported malformed list_agents wrapper policy` |

主动 field-source parity 为 **12/12 PASS**：

| 来源 | 结果 |
| --- | --- |
| `boolean_error_flags` | PASS |
| `explicit_error_field` | PASS |
| `wrapper_status_fields` | PASS |
| `wrapper_error_statuses` | PASS |
| `wrapper_status_parse_policy` | PASS，加载并拒绝 unsupported 值 |
| `malformed_or_explicit_error` | PASS，加载并拒绝 unsupported 值 |
| active/advisory/terminal/error 状态集合 | 4/4 PASS |
| 无 wrapper error 字面量旁路 | PASS |
| 无 `status/state` 单字段优先级旁路 | PASS |

另在隔离 Schema 中同时重命名四个 wrapper 字段来源和四组 Agent 状态标签，13/13 行为探针通过：runtime 只响应变异后的机器值，旧 `isError`、`error`、`status`、`failure` 和 `running` 字面量不再形成旁路。AST 对账同时确认 `_agent_status_entries()` 只遍历机器来源常量，函数体内没有 `failure` 或直接 `status/state` 字面量裁决。

## 4. 其他冻结回归

- exact canonical scope 可绑定；broad、relative、missing、wrong、duplicate target 均 no-op。
- nested `structuredContent/content/summary/final_history` 不被扫描；malformed 或非顶层 `agents` 不产生强事实。
- exact empty 只写 `absent_at_check`，不生成 terminal、业务 failed、TaskResult 或关闭事实。
- `fresh_until` 固定为 null；Schema 与 runtime 均拒绝 format 4 non-null freshness，且不重写非法原始字节。
- exact running 后 Stop 固定 advisory `continue=true` 且不写状态；两次 transient read failure 后第三读恢复，持续失败精确三读后告警 fail-open。
- 父结果只接受 exact `task_id + attempt + sender_target` 三元组；wrong task/attempt/sender/alias 在写前拒绝。合法记录保持 dispatch/observation invariant，Agent terminal 不替代 TaskResult。

## 5. 门禁数字

| 门禁 | 最终结果 |
| --- | --- |
| 独立 wrapper 扩展矩阵 | 4,128/4,128 PASS |
| 独立 policy 正常加载/unsupported 变异 | 3/3 PASS |
| 独立 machine field-source parity | 12/12 PASS |
| 隔离 field-source 行为变异探针 | 13/13 PASS |
| Slice 4 focused | 5/5，OK |
| 四平面 exact/empty/Schema focused | 22/22，OK |
| wait/Stop focused | 28/28，OK |
| parent result focused | 11/11，OK |
| semantic/canonical parity | 44/44，OK |
| Hook contract | 5/5，OK |
| 全量 unittest | 428/428，OK |
| `python3 -m py_compile scripts/subagent_governance.py` | PASS |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| 全部 repository JSON | 15/15 PASS |
| `git diff --check` | PASS |
| untracked whitespace | 63/63 个文本文件 PASS，0 issues |

## 6. Blocker

无。历史 wrapper 行为 blocker 和第四轮 machine policy-source blocker 均已关闭。

## 7. Known limitation

- adapter 只接受已有正向证据的顶层 `agents` object/JSON string；未知 wrapper 保持 no-op，不递归猜测。
- format 4 没有 active freshness；exact running 可能立即陈旧，因此 Stop 不能 hard-block。
- Stop advisory 只展示 canonical StateStore 中的父责任，不证明 Agent 当前仍运行，也不替父任务验收结果。
- ObservationRecord 是收敛记录，不是 observation event log。

这些限制符合 Slice 4 冻结设计，不影响本次 GO。

## 8. Backlog

- 取得官方或独立真实 TTL、刷新、乱序和跨重启保证后，才能以新切片和新状态格式重新评估 freshness。
- freshness authority 成立且 parent Stop 的真实 Hook 展示、重入与 fail-open 完成独立验证后，才能重新评估 limited hard gate。
- 新 wrapper/status 形状必须先保存正向平台证据并增加失败先行测试，不得用递归 parser 预适配未知平台。

## 9. Not_checked

- 测试 cachebuster 与新建 Slice 4 真实 smoke；这是本次 GO 后仅允许的下一步。
- 独立 SubagentStart/SubagentStop Hook payload、顺序与真实投递。
- parent Stop advisory 在真实 Codex UI 中的展示、重入和退出行为。
- Provider restart、compact/resume、乱序 observation 和跨版本 StateStore。
- Provider 内部日志面、Hook trust、稳定源、运行缓存、Marketplace、Registry 和发布包。

## 10. 下一步准入

本次结论为 **GO**，只允许后续执行测试 cachebuster，并在当前项目中新建对话完成 Slice 4 真实 smoke。真实 smoke 应使用项目规定的默认 `gpt-5.6-terra/high`，除非用户另行指定；不得复用本复验对话替代真实测试。

本次 GO 不自行批准部署、安装、稳定版发布、缓存同步、Hook trust 修改、其他真实任务、Slice 5、提交或推送。真实 smoke 未通过前，不得宣称 Slice 4 已完成真实平台闭环。
