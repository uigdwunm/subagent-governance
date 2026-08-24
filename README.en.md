# Subagent Governance

[简体中文](README.md) | English

A Codex-first lifecycle governance plugin for native subagents. It keeps the native `spawn_agent`, messaging, waiting, recovery, and interrupt tools while adding explicit task contracts, deterministic dispatch admission, terminal-notification tracking, lifecycle closure, and read-only diagnostics.

It does not introduce a second orchestrator, define a business-result JSON format, persist result bodies, or replace the parent agent's judgment.

The contract does not scan or score natural-language content. Every input direction must be present, with `[]` or `null` used explicitly where allowed. Required workspace materials are declared through `context_manifest`; only declared paths, baselines, types, and digests are checked. A `working_tree` baseline accepts file declarations only; directory dependencies use Git tree object IDs under a `git_commit` baseline.

For handoffs outside native `spawn_agent`, pipe the manifest to `python3 scripts/subagent_governance.py --verify-context-manifest` before dispatch. This read-only preflight returns verification facts without creating governance state and cannot hard-intercept `create_thread`.

StateStore accepts only strict `state_format_version=7` in the `state-v7` namespace. Root, task, execution, pending, health, tombstone, agent, and group records have closed field sets; missing or mismatched versions, `managed=false`, and unknown persisted fields are rejected without reading, migrating, or deleting legacy `state-v1` or `state-v6` data.

When an initial PreparedContract has been missing for more than five minutes and canonical state still proves the dispatch was never claimed, targeted, observed, or started, SessionStart/SessionEnd closes that unstarted work item into a seven-day tombstone. This does not synthesize completion or a terminal notification; claimed, unknown, concurrently changed, or possibly created Agents remain open for reconciliation.

## Capabilities

- `light`, `standard`, `strict`, and structured `auto` governance modes
- Required explicit objectives, task features, scope, completion conditions, model, reasoning effort, and context strategy
- A `context_manifest` that declares no material dependencies or verifies required paths against a working tree or exact Git commit, then rechecks them before the native call
- PreparedContract-based dispatch identity and bounded retries
- Ordered waiting, exact-target platform observations, and limited recovery
- Explicit normal messaging, platform recovery, business resume, and interrupt reconciliation
- Three canonical execution planes: dispatch, observation, and closure
- Minimal terminal-notification facts bound to the exact native sender
- Lifecycle-only parent disposition: `close_task`
- Read-only diagnostics and lightweight required-member groups

## Install

```bash
codex plugin marketplace add uigdwunm/subagent-governance --ref main
codex plugin add subagent-governance@subagent-governance
```

Start a new Codex task after installation, review the plugin hooks with `/hooks`, then test an explicit `$subagent-governance` dispatch.

## Terminal notifications

Subagents report their actual result, evidence, and remaining work through the native final reply. The parent can record only the minimal lifecycle observation:

```bash
python3 scripts/subagent_governance.py --record-terminal-notification --session <session_id>
```

```json
{
  "sender_target": "/root/<exact-native-agent-target>",
  "task_id": "<task_id>",
  "attempt": 1,
  "terminal_status": "completed"
}
```

The runtime requires an exact dispatch-target and task/attempt match. Identical notifications are idempotent; conflicting terminal statuses preserve the first fact and require reconciliation. Notification bodies are neither scanned nor stored.

The parent reads the native reply and decides whether to continue or close. `--parent-disposition` supports only `close_task`.

## Privacy and boundaries

- The core runtime does not initiate network access and has no telemetry.
- Local state contains bounded task metadata, identity mappings, lifecycle facts, notification observations, and tombstones.
- Local governance data uses only the current state format. Other formats are not read, transformed, or rewritten.
- The plugin does not register `SubagentStart` or `SubagentStop`; neither event participates in state maintenance or notification handling.
- Exact `list_agents` terminal observations wait for the native notification; they do not synthesize completion.
- Parent Stop remains advisory and fail-open.

## Diagnostics

```bash
python3 scripts/subagent_governance.py --diagnose --data-root /path/to/governance-data
python3 scripts/subagent_governance.py --diagnose --data-root /path/to/governance-data --session <session_id>
```

Diagnostics are read-only: they do not create locks, repair state, or write back observations.

## Development

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts
ruff check scripts tests
coverage run -m unittest discover -s tests -v
coverage report
python3 scripts/release_preflight.py --mode development
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and the [current architecture](docs/architecture.md).

## License

MIT. See [LICENSE](LICENSE).
