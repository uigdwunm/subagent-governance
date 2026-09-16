# Native context adapter: local verification

> 历史快照，保留当时实现和验收配置。当前消息比较边界、接口证据与真实测试要求以[兼容矩阵](../native-compatibility-matrix.md)为准。

Date: 2026-09-06

## Change and evidence

The active native spawn interface accepts message, fork_context, model and
reasoning_effort (or structured items), and returns agent_id. It has no task_name
or fork_turns parameters. The governed adapter submits a generated message
header and boolean fork_context; the state-v9 semantic capability shape stays
unchanged. Finite history counts are rejected before prepare. Model/effort are
omitted for inheritance and included only for explicit user overrides.

PreToolUse identifies the generated header, normalizes native input into the
semantic capability, and compares the full message and configuration. The
current supported tool spellings and the Hook matcher are tested together.
Opaque/unmarked inputs are inert: they do not claim a prepared task. Missing
claim is an anomaly at confirm, not permission to infer identity or retry spawn.

## Local results

- Full unittest suite: 98 tests passed.
- Python scripts compilation passed.
- Plugin validator and Skill validator passed.
- Development release preflight passed.
- Regression tests cover default isolation/inheritance, full-context explicit
  overrides, marked input tampering, unsupported finite history, missing claim,
  exact UUID binding, lifecycle and installed runtime bundle execution.

## Remaining acceptance

Real Hook delivery, visibility of the generated message header, runtime model
inheritance and actual native lifecycle are not proven by local tests. Deploy
through the existing transaction, stop, and restart Codex. Run the real test in
a new task outside the implementation task with model gpt-5.6-terra and reasoning
high, unless the user explicitly changes that configuration. The new task must
use its own Hook-authoritative session and entrypoint. Do not reuse this task's
identity, manufacture a claim, or replace a missing native target.

After a read-only governed lifecycle passes, test the workflow-pipeline Stage 2
entry with an isolated frozen requirement fixture. No real planning publication
or original-topic state transition is authorized by this smoke test.
