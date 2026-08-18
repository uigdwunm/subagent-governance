# Changelog

All notable changes to this project are documented here. The project follows semantic versioning for public releases; Codex cachebuster metadata may be appended to the Manifest version without changing the public feature version.

## Unreleased

- Replaced the four-plane outcome model with StateStore format 5 and three canonical execution planes: dispatch, observation, and closure.
- Added stdin-only `--record-terminal-notification` with exact sender/task/attempt binding and idempotent replay.
- Removed TaskResult persistence, result files, digests, correction operations, result conflicts, and accept/reject business acceptance state.
- Limited parent disposition to the lifecycle-only `close_task` operation.
- Simplified `business_resume` to rely on its explicit operation, source attempt, lifecycle gate, and revalidated TaskContract, removing duplicate transition, growth authorization, and soft-warning state.
- Removed the redundant deliverable-contract projection; contract integrity now binds directly to the complete TaskContract digest.
- Removed duplicate semantic-name, requested-mode, and resolution-reason execution projections; spawn retry now compares the complete TaskContract digest.
- Removed the unused native-status projection from lifecycle operation records while retaining semantic call and target observations.
- Reduced persisted contract summaries to the objective, completion conditions, and model actually consumed at runtime; full contract integrity remains digest-based.
- Removed the duplicate lifecycle-operation completion timestamp; execution activity continues to use the same event time through `updated_at`.
- Removed the write-only work-item update timestamp; execution timestamps remain the authority for activity and full snapshots remain the concurrency guard.
- Removed the redundant execution creation timestamp; `updated_at` already starts at creation time and remains the activity and concurrency authority.
- Removed duplicate task and attempt identity fields from closure records; the enclosing execution remains the lifecycle identity authority.
- Removed duplicate task, attempt, and task-ref identity fields from dispatch records; the enclosing execution remains the dispatch identity authority.
- Removed the stale work-item objective projection; diagnostics now read the current execution contract objective directly.
- Removed the derived recovery-status projection; recovery admission now uses the authoritative observation, retry count, parent action, and explicit authorization.
- Removed the duplicate lifecycle-operation target; execution dispatch identity remains the native target authority after a call is recorded.
- Removed the derived pending-action expiry timestamp; prepared expiry now uses the persisted creation time and the canonical retention rule directly.
- Made the task container the sole managed/unmanaged authority and removed the duplicate execution-level marker.
- Centralized legacy `action_required` cleanup in state migration and removed the now-empty work-item synchronization helper.
- Changed platform terminal observations to wait for the native child notification instead of synthesizing business outcomes.
- Updated diagnostics and lightweight groups to derive readiness from terminal notifications or explicit closure.
- Preserved legacy on-disk result files without reading, creating, or deleting them during v5 operation.
- Kept spawn-retry-exhausted attempts open and action-required until explicit parent disposition; migration removes only the matching premature tombstones.
- Reduced interrupted-attempt reconciliation input to task ID and attempt, deriving target, mapping, and interrupt lifecycle checks from canonical state.
- Removed the unconsumed platform-observation summary helper and current-attempt projection field.
- Fixed Stop and SessionEnd advisory summaries to derive execution status from canonical observation facts.
- Removed the unreachable `start_observed_at` lifecycle field, obsolete CLI selectors, and duplicate recovery branches.
- Removed the ineffective `SubagentStart` and `SubagentStop` runtime Hooks, deleted the unused closure-state helper and parameter plumbing, constrained authorization CLI combinations, and persisted recovery authorization only for the final authorized recovery claim.

## 0.4.0-rc.12

- Fixed the Windows regression test fixture so its platform-specific Hook directory exists before writing the test file.

## 0.4.0-rc.11 (unreleased candidate)

- Fixed Windows CI portability for temporary home-directory resolution and regular-expression assertions.
- Recognized JSON-escaped Windows paths when checking whether a retained legacy Hook is still mounted.

## 0.4.0-rc.10 (unreleased candidate)

- Added a public Git-backed Marketplace entry and external installation flow.
- Added Windows Hook commands, cross-platform file locking, Windows-aware release tools, and a macOS/Linux/Windows CI matrix.
- Added optional safe initialization and removal of the managed global `AGENTS.md` entry.
- Added MIT licensing, public metadata, privacy-safe platform validation documentation, and host-path checks in CI.
- Reworked the README around Codex-first positioning, core governance capabilities, runtime boundaries, and external contributors.

## 0.4.0-rc.9

- Stopped incompatible provider recovery from being treated as a recoverable Agent failure.

## 0.4.0-rc.8

- Reconciled native Agent identifiers across Hook events.

## 0.4.0-rc.7

- Bound canonical Agent paths from actual spawn responses.

## 0.4.0-rc.6

- Bounded repeated platform-error recovery.

## 0.4.0-rc.5

- Resolved the development repository from stable plugin installations.

## 0.4.0-rc.4

- Preserved pinned runtime caches across plugin reinstall.

## 0.4.0-rc.3

- Distinguished legacy Hook mounts from compatibility paths.

## 0.4.0-rc.2

- Preserved runtime caches during plugin upgrades.

## 0.4.0-rc.1

- Introduced the hardened subagent-governance lifecycle baseline.
