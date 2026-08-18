# F13 final local acceptance report

Date: 2026-08-14

Nature: final read-only synthesis and local development-repository acceptance after F1-F12. This task only adds this report. It does not modify runtime code, tests, Schema, Skill, manifest, release inputs, installed plugins, stable sources, caches, Hook trust, Marketplace, Registry, or external tasks.

## 1. Final decision

**LOCAL ARCHITECTURE GATE: PASS**

**LOCAL DEVELOPMENT ACCEPTANCE: PASS WITH KNOWN BASELINE ERRORS**

No reproducible violation of a frozen invariant remains in the locally checked architecture. The F8 and F11 blockers are closed by F9, F10, and F12 with current runtime, Schema, Skill/runtime-boundary, and regression evidence.

This is not a release-ready statement. The full suite is not green: it ran 380 tests, with 378 passed and exactly two retained D6 host-specific-path errors. Real plugin, Hook, provider, mailbox, UI, installation, and release acceptance remain `not_checked`.

## 2. Acceptance baseline and boundary

The starting dirty worktree already contained all F1-F12 implementation and documentation changes. F13 did not attribute those changes to itself and did not clean, rewrite, stage, commit, or publish them.

The review scope was limited to:

- the frozen D1-D6 invariants and workstream map;
- the declared goals and evidence of F1-F12;
- F8 and F11 blockers and their stated closing slices;
- current Schema/runtime/Skill/runtime-boundary consistency;
- the agreed targeted, cross-slice, full-suite, validator, static, and release-preflight gates;
- the explicit local-only and no-external-write boundary.

The two existing release-preflight errors caused by `docs/redesign/D6-migration-and-slices.md` were preserved exactly. They were not fixed, suppressed, filtered, or treated as runtime architecture blockers.

## 3. F1-F12 acceptance matrix

| Phase | Goal | Main change or review result | Evidence considered | Current status |
| --- | --- | --- | --- | --- |
| F1 | Enforce one-way closure, replacement reservation/capacity, claim-time admission, and exact rollback/expiry | Added open/unclosed dual admission, one reserved candidate, two-candidate cap, exact reservation identity/snapshot, claim rollback, and action-required retention | Historical failure-first and focused tests; current 304-test cross-slice run; full suite | Accepted; original closure/reservation findings remain closed |
| F2 | Route same-Agent late Stop/TaskResult to the retained attempt | Made `task_id + attempt` plus retained target provenance authoritative; prevented active-index A2 from rejecting or corrupting A1; retained precise stale-mapping cleanup | Historical late-event and stale-mapping tests; current formal-result/cross-slice coverage | Accepted; late-event routing closed |
| F3 | Derive replacement duplicate risk from canonical execution facts | Shared coexistence predicate across all live candidates; excluded reliably inactive sources; preserved unresolved no-target duplicates until reliable closure | Historical directed candidate/select tests; current dispatch/formal-result/session/decision coverage | Accepted; duplicate-risk and false-select findings closed |
| F4 | Remove persisted `work_item.action_required` as a second authority | Made canonical candidate predicate the sole authority used by diagnose, group, Session, Stop, and closure paths | Historical failure-first tests; current state/session/diagnostic/Schema coverage | Accepted; action-required is derived only |
| F5 | Project canonical growth facts to diagnostics, group members, and SessionStart | Added work-item-only counts, soft facts, bounded latest authorization, and non-authorizing warning projection | Historical five failure-first tests; current communication/diagnostic/session/semantic coverage | Accepted; growth remains soft and non-authorizing |
| F6 | Make governance Schema the executable canonical-record anchor | Added canonical state/task/work-item/execution/transition/operation/result/closure/decision definitions, runtime fixture validation, enum/field parity, and controlled compatibility convergence | Current `test_canonical_record_schema` inside 304-test run; all 12 JSON files parsed | Accepted; Schema/runtime core parity holds locally |
| F7 | Remove canonical-only residual authorities and dead attempt-first diagnostics | Removed residual root fallback, misleading adapter guidance, and unused attempt snapshot path while preserving explicit compatibility reads | Current S6 compatibility-retirement tests inside 304-test run; residual guidance checks | Accepted; no reviewed second decision authority reappeared |
| F8 | Independently review F1-F7 integration | Confirmed the original nine findings, then found two new P1 blockers: retained-target lifecycle escape and unsafe initial rollback | F8 review evidence plus direct recheck of the closing slices | Historical BLOCKED decision preserved; both blockers now closed by F9/F10/F12 |
| F9 | Close retained-target managed lifecycle admission escape | Shared canonical-provenance classifier for generator/PreToolUse; active index became repairable lookup only; stale/ambiguous/conflicting owners fail closed | Current F9 targeted: 12/12; communication lifecycle: 66/66; Schema semantic anchor | Accepted, with F11's interrupt exception gap closed by F12 |
| F10 | Make initial preparation rollback exact and diagnosable | Deterministically rebuilt the sole initial post-state; required full-task equality; deleted task before credential; retained divergent task/credential with reconcile/degraded markers | Current F10 initial targeted: 17/17; current runtime/Schema/Skill inspection; 304-test cross-slice run | Accepted; F8 initial rollback blocker closed |
| F11 | Re-run the local architecture gate after F9/F10 | Closed F8 initial rollback, but found a new P1: stale interrupt owner conflict was converted to fail-open | F11 independent counterexample and current source comparison | Historical BLOCKED decision preserved; its sole blocker is closed by F12 |
| F12 | Close stale interrupt-owner fail-open without expanding the interrupt state machine | Added shared exception classification: readable conflict/unsafe deny; only real StateStore unavailable allows normal-message/explicit-interrupt degradation | Current F12 targeted: 2/2; five-operation owner-race test; write-failure policy test; communication 66/66 | Accepted; F11 blocker closed |

## 4. Blocker closure ledger

| Blocker | Required invariant | Closing evidence | F13 decision |
| --- | --- | --- | --- |
| F8 P1-1: retained provenance could escape lifecycle governance when active index was missing | Canonical execution target provenance is identity authority; active index is lookup only; governed calls require pending admission | F9 targeted 12/12 proves missing/stale/ambiguous/conflicting/historical/unmanaged and owner-race cases; F12 extends the same owner invariant through interrupt exception handling; communication module 66/66 | Closed |
| F8 P1-2: initial preparation rollback could delete concurrent facts or orphan an uncredentialed task | Full initial task equality is the only deletion predicate; task deletion precedes credential deletion; divergence remains diagnosable/action-required | F10 targeted 17/17 covers persist-then-error, every task-field change, cleanup/readback failures, orphan cleanup, health merge, and expiry; Schema anchor and current implementation agree | Closed |
| F11 P1-1: stale interrupt pending could fail open onto a new active owner | Pending owner must equal the locked admission candidate; readable conflict must deny and preserve pending; fail-open is limited to actual StateStore unavailability | F12 targeted 2/2: all five operation types deny the A1-to-A2 owner race with no mutation or `updatedInput`; separate write-failure test preserves only the documented normal-message/explicit-interrupt unavailable policy | Closed |

No new blocker was found. In particular, the two D6 release-preflight errors are unchanged public-text baseline errors, not violations of the runtime state, identity, result, or closure invariants.

## 5. Frozen invariant and consistency check

| Frozen invariant | Local result | Evidence boundary |
| --- | --- | --- |
| Four-layer authority: work item, execution, outcome, disposition remain distinct | Pass | Canonical Schema definitions, runtime records, result/disposition tests |
| Exact identity and retained provenance; no same-name/latest/current guessing | Pass | F2/F9/F12 tests and runtime classifier/claim inspection |
| `null` means not observed; `unknown` means observed but unresolved and never auto-terminal | Pass | Semantic, dispatch, communication, session, and formal-result regressions |
| Structured TaskResult is the only business result; complete remains pending until explicit parent acceptance | Pass | Formal-result and canonical-record coverage |
| Closure is explicit, one-way, tombstoned, and cannot be revived by dispatch or late events | Pass | F1/F2 and parent-closure/session regressions |
| Replacement/resume growth uses explicit authorization, candidate cap, duplicate facts, and reliable select/interrupt closure | Pass | F1/F3/F5, communication, dispatch, formal-result, and session coverage |
| `action_required` is a non-persisted canonical derived view independent of recent activity | Pass | State/session/diagnostic/Schema tests |
| Initial and replacement rollback do not overwrite newer concurrent facts | Pass | F1 and F10 rollback/CAS regressions |
| Pending owner equals locked admission candidate; readable conflict is fail-closed | Pass | F9/F12 targeted tests and Schema/runtime/docs comparison |
| Governance Schema is the canonical machine anchor and controlled names/enums match runtime | Pass | 304-test cross-slice run includes semantic and canonical Schema parity tests; all JSON parses |
| Native Agent tools remain the execution channel; no scheduler, DAG, second state machine, or inferred business truth was introduced | Pass within local inspection | Runtime boundaries, Skill, and current source; real platform behavior remains `not_checked` |

Current Schema, development Skill, `references/runtime-boundaries.md`, and runtime agree on the F9/F10/F12 points that mattered to the prior blockers:

- target lifecycle authority is canonical execution provenance;
- stale pending claims are denied and retained for reconciliation or expiry;
- explicit interrupt fail-open is limited to classified StateStore unavailable/read-write failure;
- initial expected state is rebuilt from the single PreparedContract source;
- exact full-task deletion precedes PreparedContract deletion;
- unsafe rollback remains retained, degraded, and action-required when persistence is possible.

## 6. Result categories

### 6.1 Blocker

None.

F13 found no stable reproduction of a frozen-invariant violation after F12.

### 6.2 Known limitations

- Two retained D6 host-specific-path baseline errors keep the full suite and development release-preflight non-green. They do not block the local architecture gate, but they do block any full-pass or release-ready statement.
- The governance layer cannot prove or repair native Provider transport, mailbox delivery, worker persistence, UI projection, or Hook trust. It can only govern locally observable facts and preserve unresolved state.
- JSON Schema cannot alone prove cross-object active-index/provenance consistency; runtime locked admission and regression tests enforce that relationship.
- The design intentionally has no background scheduler, second orchestrator, automatic duplicate selection, or automatic business closure.

### 6.3 Backlog

- Remove the D6 host-specific path in a separately authorized documentation change before a future release-preflight acceptance; this F13 deliberately preserves it.
- Retire the remaining explicitly controlled F6 compatibility reads only after independent migration evidence; current read/converge-on-write behavior is accepted and not a second authority.
- No new backlog item was created by F13, and no F14 or follow-on task is implied by this report.

### 6.4 not_checked

- Development-tree content was not synchronized to a test or installed runtime plugin.
- No new real test task was created; real Plugin/Skill/Hook loading and the seven Hook enabled/trusted states were not checked.
- Real `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `list_agents`, and `interrupt_agent` parameters, delivery, ordering, terminal shapes, and mailbox wakeups were not checked.
- Real SubagentStart/SubagentStop ordering, structured `task_result` visibility, same-Agent target behavior, provider disconnects, compact/resume behavior, and UI summaries were not checked.
- Stable release source, runtime cache, Marketplace, Registry, Hook trust, cachebuster, N/N-1 upgrade/rollback, source/cache hashes, and non-symlink release separation were not checked.
- No install, release, stage, commit, push, pull request, or external write was performed.

## 7. Exact gate results

| Gate | Result |
| --- | --- |
| F12 targeted: `tests.test_communication_lifecycle -k f12` | 2 tests, OK |
| F9 targeted: `tests.test_communication_lifecycle -k f9` | 12 tests, OK |
| F10 targeted: `tests.test_dispatch_identity -k initial` | 17 tests, OK |
| Communication lifecycle module | 66 tests, OK |
| Agreed cross-slice modules | 304 tests, OK |
| Full `unittest discover` | 380 tests: 378 passed, 0 failures, 2 errors |
| Release-preflight test module | 5 tests: 3 passed, 0 failures, 2 errors |
| `python3 -m py_compile scripts/subagent_governance.py` | Passed; bytecode directed outside the repository |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` |
| Repository JSON parse | 12 files parsed successfully |
| `git diff --check` | Passed for tracked diffs |
| `python3 scripts/release_preflight.py --mode development` | Exit 1; only `host-specific path in docs/redesign/D6-migration-and-slices.md` |

The two full-suite and release-preflight-module errors are exactly:

1. `test_release_preflight.ReleasePreflightTests.test_current_development_tree_passes_with_supported_ref`
2. `test_release_preflight.ReleasePreflightTests.test_release_requires_manifest_tag_and_marketplace_ref_to_match`

Both raise:

```text
release_preflight.PreflightFailure: host-specific path in docs/redesign/D6-migration-and-slices.md
```

No other test failure or error occurred. The result must not be described as a full pass.

## 8. F13 document and worktree boundary verification

The F13 file itself passed dedicated checks for:

- host-specific path patterns;
- common secret-shape patterns used by release-preflight;
- trailing whitespace and diff whitespace errors;
- JSON-independent Markdown readability and bounded local references.

Release-preflight was rerun after adding F13 and continued to report only the unchanged D6 path. F13 introduced no additional public-text finding.

The final dirty-worktree comparison against the recorded start baseline shows exactly one F13-owned addition:

```text
docs/redesign/F13-final-local-acceptance-report.md
```

All pre-existing tracked modifications and untracked F1-F12/design/test files remain present and are not claimed as F13 changes.

## 9. Final acceptance statement

The local development repository satisfies the frozen architecture gate after F12, with no open local architecture blocker found in the agreed scope.

The local development acceptance is therefore **PASS WITH KNOWN BASELINE ERRORS**. The two D6 release-preflight errors remain exact, known, and intentionally unmodified. Real plugin and release acceptance remain outside this result and are `not_checked`.
