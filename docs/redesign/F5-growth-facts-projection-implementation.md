# F5 Growth Facts Projection Implementation

Date: 2026-08-14

## Scope

This slice resolves P2-3 from `S1-S6-integrated-architecture-review.md`: S3 already persisted soft growth facts and counts, but S5 diagnostics, group members, and SessionStart did not expose them.

The only modification source is this development repository. F1 admission/reservation/rollback, F2 retained late-event routing, F3 replacement duplicate facts, and F4 action-required authority remain unchanged. P2-4 full canonical record Schema and P3 legacy cleanup are out of scope. No plugin installation, release, cache sync, Hook trust, Marketplace, Registry, staging, commit, push, PR, external task, or real plugin test was performed.

## Failure First

Before runtime changes, five tests covered the required paths:

1. Two real replacement preparation/PreToolUse/PostToolUse cycles reached `replacement_spawn_count=2` and `repeated_replacements=true`, then failed with `KeyError: growth` in WorkItemDecisionSnapshot.
2. Three real business-resume preparation/PreToolUse/PostToolUse cycles reached attempt 4 and `repeated_business_attempts=true`, then failed with `KeyError: growth`.
3. Current and prior executions carrying artificial `growth_facts[]` could not be distinguished from a canonical work-item aggregate because no work-item growth projection existed.
4. Group member snapshots did not expose growth, and SessionStart rendered no soft warning.
5. Bounded and invalid legacy reason behavior had no output contract.

The pre-fix run was stable:

```text
Ran 5 tests
FAILED (failures=1, errors=4)
```

The four errors were missing `snapshot["growth"]`; the failure proved SessionStart omitted the soft warning even when canonical counts and flags were present.

## Design Decision

Canonical `work_item` is the only growth authority. The output vocabulary is fixed to the runtime names:

```text
repeated_business_attempts
repeated_replacements
```

The earlier D6 singular spelling `repeated_replacement` is retired from canonical output. Execution candidates do not persist or project a second `growth_facts[]` authority.

`last_disposition` is not sufficient for the latest growth reason: a later `accept_result`, `reject_result`, `select_attempt`, or `close_task` disposition can replace it while the cumulative soft fact remains true. Each successful replacement or business-resume claim therefore atomically copies its validated growth disposition into one minimal `work_item.last_growth_authorization` record:

```json
{"attempt": 3, "action": "resume_business", "reason": "...", "recorded_at": 0}
```

This is a single latest summary, not an event log. It does not copy a dispatch prompt, communication content, outcome, or evidence.

## Output Shape

Every WorkItemDecisionSnapshot contains:

```json
{
  "growth": {
    "attempt_count": 4,
    "replacement_spawn_count": 2,
    "repeated_business_attempts": true,
    "repeated_replacements": true,
    "soft_warning": true,
    "facts": ["repeated_business_attempts", "repeated_replacements"],
    "latest_authorization": {
      "action": "resume_business",
      "attempt": 3,
      "reason_present": true,
      "reason_summary": "bounded summary",
      "recorded_at": 0
    }
  }
}
```

Counts are integers or null when an old record is invalid. Flags are deterministic booleans; facts use the fixed order above and appear only once in the work-item growth projection. The reason summary normalizes whitespace and is capped at 160 characters. A missing, non-string, empty, or over-persisted-limit legacy reason yields `reason_present=null`, `reason_summary=null`, and `growth_authorization_invalid`; diagnostic issues never embed the invalid value.

Group does not gain scheduling semantics. Each member only copies its WorkItemDecisionSnapshot `growth`; there is no group growth aggregate, action, budget, or disposition.

## Session And Closure Boundary

SessionStart consumes `snapshot.growth` rather than recalculating work-item fields. It renders `【软增长提醒】` only when `soft_warning=true`, including the two counts, fixed facts, latest growth action/attempt, and bounded reason summary. The text states that the next disposition should explain why work continues and that this is not a hard denial, automatic close, or automatic spawn.

Growth does not enter `_canonical_action_required_candidate()`, `_action_required_records()`, or `_stop_blocking_records()`. It neither blocks Stop nor preserves SessionEnd state by itself. Recent activity remains an independent display window.

## Changed Files

- `scripts/subagent_governance.py`
- `schemas/governance-semantics.schema.json`
- `tests/test_dispatch_identity.py`
- `tests/test_communication_lifecycle.py`
- `tests/test_minimal_diagnostics_lightweight_groups.py`
- `tests/test_wait_recovery_session_closure.py`
- `tests/test_semantic_baseline.py`
- `skills/subagent-governance/SKILL.md`
- `skills/subagent-governance/references/runtime-boundaries.md`
- `docs/redesign/D5-decision-diagnostics.md`
- `docs/redesign/D6-migration-and-slices.md`
- `docs/redesign/S1-S6-integrated-architecture-review.md`
- this file

## Verification

The five failure-first tests pass after implementation. The final focused set, including the machine-semantics assertion, passed `Ran 6 tests / OK`.

F1-F5/S6 cross-slice regression:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  tests.test_dispatch_identity \
  tests.test_communication_lifecycle \
  tests.test_formal_result_parent_closure \
  tests.test_wait_recovery_session_closure \
  tests.test_minimal_diagnostics_lightweight_groups \
  tests.test_state_store \
  tests.test_semantic_baseline \
  tests.test_s6_compatibility_retirement

Ran 251 tests / OK
```

Full suite:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
Ran 327 tests
FAILED (errors=2)
```

325 tests passed. The only errors are the two accepted D6 host-specific path baselines:

- `test_current_development_tree_passes_with_supported_ref`
- `test_release_requires_manifest_tag_and_marketplace_ref_to_match`

Both remain `PreflightFailure: host-specific path in docs/redesign/D6-migration-and-slices.md`; F5 did not modify or suppress that path rule.

Other gates:

- `python3 -m py_compile scripts/*.py`: passed with bytecode directed to an isolated temporary directory, then precisely removed.
- Plugin validator: `Plugin validation passed`.
- Skill validator: `Skill is valid!`.
- Every repository JSON file discovered by `rg --files -g '*.json'`: parsed with `python3 -m json.tool`.
- `git diff --check`: passed.

## not_checked

- Installed plugin or runtime cache loading.
- Real Provider spawn/followup/Start/Stop/Session hook ordering and payloads.
- Codex UI rendering of the SessionStart warning or diagnose/group JSON.
- Real new-task plugin test, N/N-1 upgrade, rollback, Marketplace, Registry, or Hook trust.

These remain not checked because this slice explicitly forbids installation, cache synchronization, external tasks, and real plugin testing.

## remaining

- P2-4: governance semantics is not yet the complete executable model for every runtime-emitted canonical record and disposition.
- P3: attempt-first/legacy dead readers, helpers, comments, and documentation cleanup remain separate work.
- The two D6 host-specific path release-preflight baseline errors remain unchanged and are not part of F5.
