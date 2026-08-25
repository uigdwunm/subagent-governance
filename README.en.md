# Subagent Governance

Subagent Governance is a Codex-first lifecycle layer for native subagents. Native Agent tools remain the execution channel; the plugin is not a second orchestrator, permission system, sandbox, or platform trust boundary.

The dispatch and minimal-lifecycle reduction slices now provide:

- strict current-only `state_format_version=9` in `state-v9`;
- one exact-Session ledger and one native Agent lifecycle per task;
- TaskContract v2 with `standard|strict` profiles;
- `prepare-dispatch → governed spawn Pre claim → explicit exact-target confirm`;
- first-bind-wins, idempotent same-target replay, and reconcile on conflicts;
- exact platform observations, terminal notifications, interrupt results, and parent close;
- zero-write normal-call success/failed results, with only a reconcile reason for unknown;
- fixed retention of 64 closed tasks, lazily pruned only by later ledger writes;
- inert unmanaged spawn before StateStore construction;
- lock-free, zero-write SessionStart injection of the Hook-authoritative exact session ID with a best-effort state summary, plus read-only status/diagnose.

PreparedContractStore, the agents index, PostToolUse receipts/indexes, attempts, pending actions, tombstones, Groups, business resume, and complex retry/recovery state machines are no longer runtime authorities.

The Codex runtime is an exact projection of the machine-readable `.codex-plugin/runtime-bundle.json` allowlist: manifests, the Skill and references, core scripts, schemas, and minimal README/license material only. Tests, plans, validation reports, `AGENTS.md`, development dependencies, and deployment tools are excluded. `scripts/dev_deploy.py` is the repository's sole development deployment entry and defaults to a zero-write dry run; stable/cache/Codex writes still require separate explicit authorization.

Wait calls are not persisted, normal message bodies/history are not stored, and terminal notification bodies are never accepted. Business resume, managed followup, multiple attempts, complex recovery/retry budgets, and Groups are outside the first release. See the [reduction ADR](docs/architecture-reduction-adr.md) and [cutover plan](docs/improvement-plans/reduction-cutover.md).

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

`objective`, non-empty `scope`, and non-empty `completion` are required; other fields have mechanical defaults. Strict requires non-empty forbidden scope and evidence. The business digest excludes spawn config. Ordinary paths are location hints; hash/tree verification requires explicit `context.verified` opt-in. A `working_tree` baseline accepts per-file SHA-256 declarations only; directory dependencies require a `git_commit` tree object ID.

## Dispatch

Take the current task's `<exact-session-id>` only from the authoritative value injected by the SessionStart Hook. `<codex_delegation><source_thread_id>` identifies the source task, not the current session. If the SessionStart authority is not mechanically visible, stop before prepare instead of substituting a parent, list, or other ID.

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

Codex MultiAgent V2 encrypts `message` before the local PreToolUse boundary and may expose the flattened tool name `collaborationspawn_agent`. The plugin explicitly recognizes that name and claims the prepared capability from the derived task name/ref plus visible spawn configuration. It preserves the original opaque V2 input and does not claim plaintext-message attestation; the V1 plaintext path still compares the complete parameters.

## Minimal lifecycle

After binding, the CLI exposes exact-identity commands for platform observations, normal-call results, terminal notifications, interrupt results, and parent close. Platform terminal observations and terminal notifications establish `terminal`; interrupt `inactive` establishes a terminal fact; unknown results enter `reconcile`. Normal-call success/failed validates identity without writing the ledger. Parent close does not invoke native interrupt or store business text.

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
