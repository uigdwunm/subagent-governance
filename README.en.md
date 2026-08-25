# Subagent Governance

Subagent Governance is a Codex-first lifecycle layer for native subagents. Native Agent tools remain the execution channel; the plugin is not a second orchestrator, permission system, sandbox, or platform trust boundary.

The first reduction slice now provides:

- strict current-only `state_format_version=9` in `state-v9`;
- one exact-Session ledger and one native Agent lifecycle per task;
- TaskContract v2 with `standard|strict` profiles;
- `prepare-dispatch → governed spawn Pre claim → explicit exact-target confirm`;
- first-bind-wins, idempotent same-target replay, and reconcile on conflicts;
- inert unmanaged spawn before StateStore construction;
- lock-free, zero-write SessionStart/status/diagnose reads.

PreparedContractStore, the agents index, PostToolUse receipts/indexes, attempts, pending actions, tombstones, Groups, business resume, and complex retry/recovery state machines are no longer runtime authorities.

This slice does not yet expose persistent platform-observation, terminal-notification, interrupt-result, or parent-close APIs. Wait calls are not persisted, and normal message bodies/history are not stored. See the [reduction ADR](docs/architecture-reduction-adr.md) and [cutover plan](docs/improvement-plans/reduction-cutover.md).

## TaskContract v2

```json
{
  "profile": "standard",
  "objective": "Implement one current objective",
  "scope": ["allowed scope"],
  "forbidden_scope": [],
  "completion": ["verifiable completion condition"],
  "evidence": [],
  "context": {"summary": "necessary background", "paths": ["scripts/example.py"]},
  "spawn": {"fork_turns": "none", "model": null, "reasoning_effort": null}
}
```

`objective`, non-empty `scope`, and non-empty `completion` are required; other fields have mechanical defaults. Strict requires non-empty forbidden scope and evidence. The business digest excludes spawn config. Ordinary paths are location hints; hash/tree verification requires explicit `context.verified` opt-in.

## Dispatch

```bash
python3 scripts/subagent_governance.py --prepare-dispatch --session '<exact-session-id>' < contract.json
```

Pass the returned `spawn_args` unchanged to the current native `spawn_agent`. Then copy the exact target mechanically exposed by that current native return and confirm it:

```bash
python3 scripts/subagent_governance.py --confirm-dispatch --session '<exact-session-id>' <<'JSON'
{"task_id":"<prepare task_id>","task_ref":"<prepare task_ref>","target":"<native exact target>"}
JSON
```

Never bind identity from a list, task name, timing, summary, transcript, or child final. A crash after the native return but before confirmation leaves the task `claimed/unbound` and does not trigger automatic retry.

## Installation

```bash
codex plugin marketplace add uigdwunm/subagent-governance --ref main
codex plugin add subagent-governance@subagent-governance
```

Invoke `$subagent-governance` and inspect registration with `/hooks`. The same Codex CLI commands apply in Windows PowerShell.

## Development checks

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
python3 scripts/release_preflight.py --mode development
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
git diff --check
```

The core runtime does not proactively access the network. Installation, publishing, stable-source, Marketplace, Registry, runtime-cache, and Hook-trust writes require separate authorization.

Licensed under [MIT](LICENSE). See [SECURITY.md](SECURITY.md) and [CONTRIBUTING.md](CONTRIBUTING.md).
