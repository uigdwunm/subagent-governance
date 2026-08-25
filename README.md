# Subagent Governance

Subagent Governance 是 Codex-first 的原生子 Agent 生命周期治理插件。它保留 `spawn_agent`、`wait_agent`、`send_message`、`list_agents` 和 `interrupt_agent` 作为执行通道，不引入第二套编排平台，也不替代权限、沙箱、Hook trust 或父 Agent 的业务判断。

当前减法收口已完成第一纵向切片：

- `state_format_version=9` / `state-v9` current-only namespace；
- 单一 exact-Session ledger，一个 task 对应一个原生 Agent lifecycle；
- TaskContract v2（`standard|strict`）；
- `prepare-dispatch → governed spawn Pre claim → explicit exact-target confirm`；
- first-bind-wins、相同 confirm 幂等、冲突 reconcile；
- unmanaged spawn 在状态构造前 inert fail-open；
- best-effort、无锁、零写入的 SessionStart/status/diagnose。

旧 PreparedContractStore、agents index、PostToolUse receipt/index、attempt、pending action、tombstone、Group、business resume 和复杂 retry/recovery 状态机不再属于 runtime。

## 当前实现边界

本切片尚未开放 platform observation、terminal notification、interrupt result 和 parent close 的持久写 API。wait 不持久化；普通消息不保存正文或调用历史。完整目标架构与顺序见 [ADR](docs/architecture-reduction-adr.md) 和 [cutover plan](docs/improvement-plans/reduction-cutover.md)。

## TaskContract v2

```json
{
  "profile": "standard",
  "objective": "实现唯一当前目标",
  "scope": ["允许范围"],
  "forbidden_scope": [],
  "completion": ["可验证完成条件"],
  "evidence": [],
  "context": {"summary": "必要背景", "paths": ["scripts/example.py"]},
  "spawn": {"fork_turns": "none", "model": null, "reasoning_effort": null}
}
```

`objective`、非空 `scope` 和非空 `completion` 必填，其他字段可省略。strict 要求非空 forbidden scope 和 evidence。business digest 排除 spawn config。普通 paths 只是定位提示；需要 hash/tree verification 时显式使用 `context.verified`。

## 派发

```bash
python3 scripts/subagent_governance.py \
  --prepare-dispatch \
  --session '<exact-session-id>' < contract.json
```

将返回的 `spawn_args` 原样交给当前原生 `spawn_agent`。读取这次原生返回机械暴露的 exact target 后立即确认：

```bash
python3 scripts/subagent_governance.py \
  --confirm-dispatch \
  --session '<exact-session-id>' <<'JSON'
{"task_id":"<prepare task_id>","task_ref":"<prepare task_ref>","target":"<native exact target>"}
JSON
```

禁止用 list、task name、时间、summary、transcript 或 child final 补绑 identity。原生返回后 confirm 前崩溃时，task 保持 `claimed/unbound`，不自动重派。

明确证明 Agent 未创建时可提交 `record-dispatch-result=failed`；unknown 进入 reconcile。success 必须通过 confirm 携带 exact target。

## 安装

```bash
codex plugin marketplace add uigdwunm/subagent-governance --ref main
codex plugin add subagent-governance@subagent-governance
```

在 Codex 中使用 `$subagent-governance`，并通过 `/hooks` 检查 Hook。Windows PowerShell 使用相同的 Codex CLI 命令。

## 开发验证

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
python3 scripts/release_preflight.py --mode development
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
git diff --check
```

核心运行时不主动联网；只有显式 verified Git context 会调用本地 Git。安装、发布、stable source、Marketplace、Registry、runtime cache 和 Hook trust 写入需要独立授权。

许可证：[MIT](LICENSE)。安全报告见 [SECURITY.md](SECURITY.md)，贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。
