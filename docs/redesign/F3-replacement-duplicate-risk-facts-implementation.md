# F3 Replacement Duplicate-Risk Facts Implementation

Date: 2026-08-14

## Scope

This slice resolves P1-4 and P2-1 from `S1-S6-integrated-architecture-review.md`.
It changes only the development repository. F1 reservation identity, candidate capacity,
expiry, and rollback semantics remain intact; F2 retained late-event routing is unchanged.

Semantic name: `replacement_duplicate_risk_facts`.

## Failure First

Before the runtime change, the new targeted tests failed in five assertions:

- a confirmed running source with `agent_unavailable` and `duplicate_risk_accepted=false` prepared a replacement;
- a claimed unknown source with `user_requested_replacement` and `false` did the same;
- stopped and interrupted sources were admitted but claim wrote both executions as duplicate;
- a source changed from stopped at prepare to running before claim, and claim still allowed the native spawn.

The special `unknown_duplicate_risk_accepted=false` rejection already existed and remains
a mechanical consistency check, independent of source facts.

## Shared Predicate And State Transition

Parent acceptance found that source-only projection was insufficient: A1 may remain live
after current A2 reliably fails, so A3 must coexist with A1 even though A2 cannot run.
`_replacement_source_may_coexist(record)` remains the single-execution canonical predicate;
`_replacement_coexisting_candidates(task, exclude_attempt=...)` derives all existing live
candidates from it and excludes only the replacement reservation/target. The base predicate
uses canonical execution fields only:

| Source fact | May coexist |
| --- | --- |
| `attempt_closed=true`, reliable `stopped`, or reliable `interrupted` | no |
| `execution_status=running` | yes |
| claimed initial/replacement spawn with observation `null`, `success`, or `unknown` | yes |
| claimed business resume or its lifecycle observation `success` or `unknown` | yes |

The existing live-candidate predicate consumes this same base predicate and adds only the F1
unclaimed replacement reservation capacity case. This preserves the two-candidate cap
without creating a second near-equivalent interpretation of execution liveness.

Replacement preparation rejects any unaccepted existing live candidate before creating a
PreparedContract or reservation. The PreToolUse claim callback reevaluates the same
candidate set inside the StateStore lock after identity, lifecycle, reservation, and capacity
checks. A failed final recheck uses the existing operation-specific rollback, leaving no
native spawn claim/current/duplicate/growth half-commit.

At successful claim:

- any final live candidate requires accepted risk and writes that candidate plus the new
  attempt `duplicate_execution=true` with `parent_action=resolve_duplicate`;
- a reliable failed/stopped/interrupted current source is made non-duplicate prior even if a
  different earlier candidate remains live;
- no final live candidate writes no duplicate fact, consumes the prior source next-step
  through the persisted `spawn_replacement` disposition, and makes the new attempt current.

`reason_code` remains an audited explanation. It cannot bypass a true source risk;
`unknown_duplicate_risk_accepted=false` remains invalid even when the source has stopped.

## Tests And Projection

New F3 coverage proves running and unknown sources cannot use non-special reason codes
to bypass `false`; stopped and interrupted sources may use normal replacement reason
codes with `false`; claim-time source changes are rechecked; a risk-accepted prepare whose
source stops before claim emits no duplicate; and S5 projects stopped-source replacement as
`prior` plus `current`, without `selection_pending`, `select_attempt`, or
`request_interrupt`.

The parent-acceptance regression adds A1 unknown -> A2 replacement reliably failed -> A3:
`false` is rejected before any A3 reservation or PreparedContract exists; `true` permits A3,
marks only A1/A3 duplicate, and permits `select_attempt(A3)`. S5 displays the same A1/A3
selection state while A2 remains prior.

The subsequent parent-acceptance counterexample selects A3 while A1 is still an unknown,
unconfirmed live candidate without an exact interrupt target. `select_attempt` now considers
only open executions already in the duplicate set. It leaves A1 open with
`duplicate_execution + duplicate_not_selected + resolve_duplicate`, keeps A3 duplicate and
`selection_pending`, and leaves reliable failed A2 as an untouched prior. Empty
`interrupt_targets` is therefore not evidence that the duplicate is resolved. The selected
duplicate clears only after every actual unselected duplicate candidate has a reliable
inactive/closed fact; confirmed running candidates retain the existing explicit interrupt
flow.

The established positive duplicate/select, F1 rollback/reservation, and F2 same-Agent
late-event tests remain part of the regression runs below.

## Modified Files

- `scripts/subagent_governance.py`
- `tests/test_dispatch_identity.py`
- `tests/test_formal_result_parent_closure.py`
- `tests/test_wait_recovery_session_closure.py`
- `tests/test_minimal_diagnostics_lightweight_groups.py`
- `tests/test_semantic_baseline.py`
- `schemas/governance-semantics.schema.json`
- `skills/subagent-governance/SKILL.md`
- `skills/subagent-governance/references/runtime-boundaries.md`
- `docs/redesign/S1-S6-integrated-architecture-review.md`
- this file

## Validation

- Parent-acceptance A1 unknown -> A2 failed -> A3 directed path now includes the
  `select_attempt(A3)` no-target counterexample and S5 `selection_pending` projection;
  the new assertions failed before the select fix and pass after it.
- Dispatch/F1 reservation rollback, communication/S3, formal-result/F2, session/S4,
  S5, semantic, and StateStore regressions: `236 tests OK`.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`: 318 tests run,
  316 passed; only the two known D6 host-specific-path errors remain:
  `test_current_development_tree_passes_with_supported_ref` and
  `test_release_requires_manifest_tag_and_marketplace_ref_to_match`. Both report
  `PreflightFailure: host-specific path in docs/redesign/D6-migration-and-slices.md`.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile scripts/*.py`: passed.
- Plugin validator: passed. Skill validator: passed.
- Modified JSON files parse with `python3 -m json.tool`; `git diff --no-ext-diff --check`:
  passed.

## Not Checked

Real plugin loading, Hook trust, Provider native spawn and event timing, real replacement/
duplicate/select/interrupt behavior, and external test conversations remain `not_checked`.
This slice did not install, publish, synchronize caches, alter a stable source, stage,
commit, push, or create a PR.
