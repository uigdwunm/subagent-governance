# Subagent Governance

Subagent Governance 是 Codex-first 的原生子 Agent 生命周期治理插件。它保留 `spawn_agent`、`wait_agent`、`send_message`、`list_agents` 和 `interrupt_agent` 作为执行通道，不引入第二套编排平台，也不替代权限、沙箱、Hook trust 或父 Agent 的业务判断。

当前减法收口已完成派发与最小生命周期两个纵向切片：

- `state_format_version=9` / `state-v9` current-only namespace；
- 单一 exact-Session ledger，一个 task 对应一个原生 Agent lifecycle；
- TaskContract v2（`standard|strict`）；
- `prepare-dispatch → governed spawn Pre claim → explicit exact-target confirm`；
- first-bind-wins、相同 confirm 幂等、冲突 reconcile；
- exact platform observation、terminal notification、interrupt result 和 parent close；
- 普通消息 success/failed 零写入，unknown 只保留 reconcile reason；
- closed task 固定保留 64 条，并仅由后续 ledger 写操作惰性裁剪；
- unmanaged spawn 在状态构造前 inert fail-open；
- best-effort、无锁、零写入的 SessionStart/status/diagnose。

旧 PreparedContractStore、agents index、PostToolUse receipt/index、attempt、pending action、tombstone、Group、business resume 和复杂 retry/recovery 状态机不再属于 runtime。

Codex runtime 由 `.codex-plugin/runtime-bundle.json` 的机器 allowlist 精确构造，只含 Manifest、Hook、Skill/references、核心 scripts、Schema 与最小 README/license；tests、plans、validation、`AGENTS.md`、开发依赖和部署工具不进入 bundle。`scripts/dev_deploy.py` 是开发仓库唯一部署入口，默认零写入 dry-run，实际 stable/cache/Codex 写入仍需另行明确授权。

## 当前实现边界

wait 不持久化；普通消息不保存正文或调用历史；terminal notification 不保存正文。business resume、managed followup、多 attempt、复杂 recovery/retry budget 和 Group 不属于首版。完整目标架构与顺序见 [ADR](docs/architecture-reduction-adr.md) 和 [cutover plan](docs/improvement-plans/reduction-cutover.md)。

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

`objective`、非空 `scope` 和非空 `completion` 必填，其他字段可省略。strict 要求非空 forbidden scope 和 evidence。business digest 排除 spawn config。普通 paths 只是定位提示；需要 hash/tree verification 时显式使用 `context.verified`。`working_tree` baseline 只接受逐文件 SHA-256；目录依赖必须使用 `git_commit` tree object ID。

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

当前 Codex MultiAgent V2 在本地 PreToolUse 前加密 `message`，并可能以 flattened `collaborationspawn_agent` 暴露工具名。插件只对已确认的 `Agent`、`spawn_agent`、`collaboration.spawn_agent`、`collaborationspawn_agent` 精确匹配；第三方同后缀工具和未知未来名称按 unmanaged fail-open。V2 以派生 task name/ref 和可见 spawn config claim prepared capability；opaque message 不会被回写，插件也不宣称能在该边界验证明文正文。V1 明文路径仍执行完整参数比较。

明确证明 Agent 未创建时可提交 `record-dispatch-result=failed`；unknown 进入 reconcile。success 必须通过 confirm 携带 exact target。

## 最小生命周期

bound 后可使用以下 stdin JSON 命令；除 close 外均要求 exact task/ref/target（terminal 使用 `sender`）：

```text
--record-platform-observation  status=running|completed|stopped|interrupted|error|unknown
--record-call-result           result=success|failed|unknown
--record-terminal-notification status=completed|stopped|interrupted
--record-interrupt-result      result=failed|inactive|unknown
--close-task                   reason=<bounded parent reason>
```

平台 terminal observation 或 terminal notification 建立 `terminal`；interrupt `inactive` 建立 terminal fact；unknown 进入 `reconcile`。普通消息 success/failed 只校验 exact identity，不写 ledger。close 不调用原生 interrupt，也不保存业务正文。

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
