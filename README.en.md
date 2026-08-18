# Subagent Governance

[简体中文](README.md) | English

A Codex-first lifecycle governance plugin for native subagents. It keeps the native `spawn_agent`, messaging, waiting, recovery, and interrupt tools while adding explicit task contracts, deterministic dispatch admission, terminal-notification tracking, lifecycle closure, and read-only diagnostics.

It does not introduce a second orchestrator, define a business-result JSON format, persist result bodies, or replace the parent agent's judgment.

Version 5 StateStore reads, updates, and CAS callbacks expose only `dispatch_record`, `observation_record`, and `closure_record`. Legacy v1-v4 execution fields are accepted only as one-way migration input: reads convert them in memory, and the next successful write persists v5 without recreating a compatibility projection or maintaining a second state model.

## Capabilities

- `light`, `standard`, `strict`, and structured `auto` governance modes
- Explicit objectives, scope, completion conditions, model, reasoning effort, and context strategy
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

The runtime requires an exact dispatch-target and task/attempt match. Identical notifications are idempotent; conflicting terminal statuses preserve the first fact and require reconciliation. Notification bodies are neither scanned nor stored, and no `results/` directory is created.

The parent reads the native reply and decides whether to continue or close. `--parent-disposition` supports only `close_task`.

## Privacy and boundaries

- The core runtime does not initiate network access and has no telemetry.
- Local state contains bounded task metadata, identity mappings, lifecycle facts, notification observations, and tombstones.
- Version 5 does not read or delete legacy result files. Existing files remain for manual cleanup.
- The plugin does not register `SubagentStart` or `SubagentStop`; neither event participates in state maintenance or notification handling.
- Exact `list_agents` terminal observations wait for the native notification; they do not synthesize completion.
- Parent Stop remains advisory and fail-open.

## Diagnostics

```bash
python3 scripts/subagent_governance.py --diagnose --data-root /path/to/governance-data
python3 scripts/subagent_governance.py --diagnose --data-root /path/to/governance-data --session <session_id>
```

Diagnostics are read-only: they do not create locks, repair state, scan legacy results, or write back observations.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/subagent_governance.py
python3 scripts/release_preflight.py --mode development
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [CHANGELOG.md](CHANGELOG.md).

## License

MIT. See [LICENSE](LICENSE).
