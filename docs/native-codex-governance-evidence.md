# Governance evidence for native Codex subagents

Subagent Governance keeps native Codex as the execution channel and adds a local, auditable protocol around handoff and lifecycle actions. This page connects three practical protections to repository evidence and states what each result does—and does not—prove.

OpenAI's current guidance for Codex-oriented agent work recommends stating the goal, relevant context, constraints, required evidence, success criteria, and output format. Subagent Governance turns those task inputs and the surrounding lifecycle into explicit, locally checked records; it does not replace native Codex execution or model judgment. See [OpenAI's model and prompting guidance](https://developers.openai.com/api/docs/guides/latest-model).

## Evidence summary

| Added protection | Observed behavior | Helps avoid |
| --- | --- | --- |
| Declared-material freshness | Opt-in verified materials are checked when a task is prepared and checked again when the native spawn claims it | Starting governed work after a declared file or Git object has changed |
| Exact-target continuity | A governed task binds only to the exact target returned by its current native spawn; the first valid binding is retained | Follow-up, observation, or completion being attached to the wrong concurrent task |
| Conservative unknown handling | An unconfirmed platform result remains `unknown` and moves to bounded reconciliation without an automatic retry | Duplicate dispatches, messages, or interruptions caused by guessing success or failure |

## 1. Detect declared material changes before dispatch

### Reproducible condition

The task opts in to `context.verified` and declares either:

- working-tree files, recorded by SHA-256; or
- a full Git commit OID plus declared blob or tree objects.

The runtime verifies that manifest during `prepare`. When the matching native spawn reaches the governed Pre claim, it verifies the same manifest again and refuses the governed claim if the result differs from the prepared record.

### Evidence

- [`tests/test_context_contract_v2.py`](../tests/test_context_contract_v2.py) verifies working-tree hashing, Git object identity, schema rejection, and Git workspace drift detection.
- [`scripts/governance_dispatch.py`](../scripts/governance_dispatch.py) performs the second verification during claim and raises a state conflict when the prepared and current verification records differ.
- The exact manifest rules are documented in the [TaskContract v2 context completeness contract](context-completeness-contract.md).

### Practical effect

This prevents one specific stale-context path: a governed task does not begin after a material explicitly declared by the parent has changed between preparation and claim. That can avoid work based on an obsolete file or Git object and the follow-up correction it would require.

### Boundary

Verification is opt-in and declared-only. Ordinary `context.paths` remain location hints, `strict` does not scan the workspace automatically, and the plugin cannot prove that the parent declared every material the task needed.

## 2. Keep concurrent work attached to the exact native target

### Reproducible condition

Each governed task receives a unique contract reference. After native `spawn_agent` returns, the parent confirms only the exact target returned by that call. The first valid binding wins; replaying the same fact is idempotent, while a conflicting target enters `reconcile` and does not replace the original identity.

Later observations, messages, terminal notifications, interruptions, and close decisions must use that stored binding.

### Evidence

- `test_confirm_first_bind_wins_same_replay_is_idempotent` and `test_conflicting_confirm_enters_reconcile_and_keeps_first_identity` in [`tests/test_v9_dispatch_chain.py`](../tests/test_v9_dispatch_chain.py) verify first-bind-wins, replay, and conflict behavior.
- `test_competing_confirms_preserve_first_bind_and_reconcile` in [`tests/test_concurrency.py`](../tests/test_concurrency.py) verifies the same invariant under competing confirmations.
- The latest [real Codex validation](validation/current-only-real-platform-validation.md) completed a governed `prepared → claimed → bound → terminal → closed` lifecycle using only the exact target mechanically returned by that native spawn. Concurrent competing confirmations are covered separately by the automated test above.

### Practical effect

This removes task names, nearby timestamps, candidate lists, transcripts, summaries, and child final text from identity decisions. In concurrent work, it helps prevent follow-up or completion evidence from being applied to the wrong native child and avoids the investigation or rework that a misbinding can cause.

### Boundary

Native Codex still creates, runs, and reports every child. The plugin governs the identity record around those actions; it does not create a separate execution system or attest to model output quality.

## 3. Preserve uncertainty instead of duplicating actions

### Reproducible condition

A governed task is already bound, but a message, interruption, dispatch, or platform observation does not return enough mechanical evidence to classify the action as successful or failed.

The runtime records a bounded reason such as `delivery_unknown`, `interrupt_unknown`, or `platform_observation_unknown`, enters `reconcile`, and does not automatically resend, respawn, or invent a terminal fact.

### Evidence

- `test_explicit_failed_closes_and_unknown_reconciles_without_retry` in [`tests/test_v9_dispatch_chain.py`](../tests/test_v9_dispatch_chain.py) verifies that an unknown dispatch outcome reconciles without retry.
- `test_unknown_platform_observation_records_only_reconcile_reason`, `test_normal_call_success_and_failed_are_zero_write_unknown_reconciles`, and `test_interrupt_failed_fact_inactive_terminal_and_unknown_reconcile` in [`tests/test_v9_lifecycle.py`](../tests/test_v9_lifecycle.py) verify the message, observation, and interruption boundaries.
- In the latest [real Codex validation](validation/current-only-real-platform-validation.md), an unconfirmed message result remained `delivery_unknown` and an interruption result that only reported the previous running state remained `interrupt_unknown`. Neither was rewritten as platform success.

### Practical effect

This helps avoid duplicate side effects caused by treating an ambiguous response as a definite failure and automatically repeating the action. It also keeps unresolved facts visible so the parent can make a deliberate reconciliation decision.

### Boundary

`unknown` is not success evidence. Reconciliation may still require the parent or user to inspect current native Codex state and decide what to do next. The real validation proves the conservative recording invariant, not that the underlying message was delivered or the interruption completed.

## What these results support

The evidence supports a bounded claim: Subagent Governance can reduce avoidable rework in the specific paths above by rejecting changed declared materials, retaining exact task identity, and refusing to guess when a platform result is ambiguous.

It does not establish that:

- every necessary context item will be declared;
- model reasoning or business output is improved;
- every task will complete in one pass; or
- an overall rework rate has been reduced by a measured percentage.

For the broader runtime matrix, historical failures, and explicitly unverified boundaries, see [platform validation](platform-validation.md) and [current real-platform validation](validation/current-only-real-platform-validation.md).
