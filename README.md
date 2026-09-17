# Subagent Governance

[English](README.md) · [简体中文](README.zh-CN.md)

[![CI](https://github.com/uigdwunm/subagent-governance/actions/workflows/ci.yml/badge.svg)](https://github.com/uigdwunm/subagent-governance/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Status: stable](https://img.shields.io/badge/status-stable-2EA44F)](#release-status)

**Verifiable handoff and lifecycle governance for native Codex subagents.**

Keep native Codex as the execution layer while making task handoff, declared-context freshness, exact-target binding, waiting, interruption, and completion explicit and diagnosable.

Subagent Governance is a local Codex plugin for developers who use native subagents but do not want identity, lifecycle state, or terminal decisions to depend on task names, timing, transcripts, or guesses. It adds a small, auditable protocol around the native Agent tools while keeping those tools as the only execution channel.

The handoff guidance supports a capable parent making key decisions and reviewing bounded work from suitable lower-cost child models. Explicit contracts and recoverable acceptance criteria support this division of work without requiring matching models. Lower total delivery cost is a design goal, not a demonstrated result; model-combination and cost evaluation remains pending.

## Release status

The current stable release is [`v0.5.0`](https://github.com/uigdwunm/subagent-governance/releases/tag/v0.5.0). The Marketplace entry is pinned to the same immutable tag. This release adds recoverable business contracts, bounded closed-task retention, clearer native-return identity guidance, and stronger deployment source verification.

**Upgrade boundary:** state-v12 does not read, migrate, or delete older ledgers. Finish existing governed tasks before upgrading, restart Codex, and use a new session. An empty new summary does not prove older tasks completed. Recent independent macOS validation covers standard identity binding and a strict message-to-final round trip; see the [dated evidence and remaining boundaries](docs/validation/current-only-real-platform-validation.md).

## What it adds to native Codex

Native Codex continues to create and run every subagent. Subagent Governance adds a local protocol around those native actions:

| Native Codex activity | Governance added by this plugin |
| --- | --- |
| The parent dispatches work through native `spawn_agent` | Require one current objective, non-empty scope, and verifiable completion conditions |
| Native spawn returns a target | Bind only that exact returned target; never infer identity from a name, list, time, transcript, or final response |
| The parent selects task context | Optionally verify declared working-tree files or Git objects at both prepare and claim time |
| The parent waits, messages, interrupts, and observes completion | Record an explicit `prepare → claim → bind → terminal → close` lifecycle |
| A platform result cannot be confirmed | Preserve `unknown` and reconcile conflicting facts instead of guessing or silently retrying |
| An ordinary native spawn is not governed | Keep unmanaged `spawn_agent` fail-open and inert |

## What it provides

- **Exact identity** — a governed task binds only to the exact target mechanically returned by its current native spawn.
- **Explicit lifecycle** — `prepare → claim → bind → terminal → close`, with reconcile for dispatch uncertainty and conflicts; bound-call unknown receipts are retained separately so later definite terminal facts can complete the lifecycle.
- **TaskContract v2** — one current objective, allowed scope, completion conditions, evidence, context, and explicit spawn configuration.
- **Optional verified context** — declared working-tree files or Git objects can be checked at prepare and claim time.
- **Local governance state** — one current Session ledger containing dispatch preparation, the original business contract, and lifecycle facts, with bounded closed-task retention.
- **Read-only recovery views** — SessionStart summaries, `status`, and `diagnose` do not create or repair state.
- **Recoverable acceptance criteria** — the runtime retains the original bounded business contract, including design context and required evidence, for exact-task retrieval after context loss. Completion still requires the parent's review of actual results.

## Evidence-backed protections

Repository tests and real Codex acceptance cover three practical protections: detecting changes to explicitly declared task materials before dispatch, retaining exact-target identity across concurrent work, and preserving unconfirmed platform results without automatic retries. These mechanisms are designed to reduce avoidable stale-material work, wrong-target follow-up, and duplicate actions without replacing native Codex execution.

See [governance evidence for native Codex subagents](docs/native-codex-governance-evidence.md) for reproducible conditions, evidence sources, practical effects, and claim boundaries.

## Installation

Install `v0.5.0` with:

```bash
codex plugin marketplace add uigdwunm/subagent-governance --ref v0.5.0
codex plugin add subagent-governance@subagent-governance
```

Restart Codex, open a new session, and review the bundled Hooks before trusting them. Codex officially supports browsing and installing plugins from supported ChatGPT/Codex surfaces; Codex CLI exposes the plugin browser through `/plugins`.

For repository development and validation, see [CONTRIBUTING.md](CONTRIBUTING.md). Development validation is not permission to modify an installed plugin, Marketplace, Hook trust, or runtime cache.

## Five-minute quick start

Ask naturally—there is no command to memorize and no need to name the Skill:

```text
Delegate this to a native subagent:

Inspect this repository's test entry points and recommend the commands I should run.
Read only; do not modify files. Wait for completion, report the evidence, and close
out the task.
```

Because this request requires native subagent dispatch, waiting, and completion, the bundled Skill automatically applies the governance flow:

```text
TaskContract v2
      │
      ▼
prepare ──► native spawn claim ──► exact-target confirm
                                         │
                                         ▼
                         wait / message / interrupt
                                         │
                                         ▼
                              terminal fact ──► close
```

The Skill generates the contract, explains the dispatch, passes the generated arguments to native `spawn_agent`, confirms the exact returned target, waits for terminal evidence, and closes the governed task. Explicitly invoking `$subagent-governance` is only a fallback when automatic Skill selection is unavailable in the current client.

## Frequently asked questions

### How does this plugin help manage native Codex subagents?

Native Codex still creates and runs every subagent. The plugin adds an explicit task contract, optional declared-material verification, exact-target binding, lifecycle records, and terminal evidence around those native actions.

### Do I need to invoke `$subagent-governance` explicitly?

Normally, no. A natural request that involves dispatching or coordinating a native subagent should select the bundled Skill automatically. Explicit invocation is only a fallback when automatic Skill selection is unavailable.

### What does verified context prove?

It proves only that the working-tree files or Git objects explicitly declared in `context.verified` match at prepare and claim time. It does not scan the workspace or prove that every necessary material was declared.

### What happens when a Codex result cannot be confirmed?

Dispatch uncertainty and identity or terminal conflicts enter reconcile. Unknown receipts for a bound task are kept in bounded unknown_facts; later definite terminal evidence can advance the task, and closure preserves those receipts. The plugin does not automatically resend, respawn, or rewrite an unknown receipt as success.

## TaskContract v2

```json
{
  "profile": "standard",
  "objective": "Implement one current objective",
  "scope": ["allowed scope"],
  "forbidden_scope": [],
  "completion": ["verifiable completion condition"],
  "evidence": [],
  "context": {
    "summary": "necessary background",
    "paths": ["scripts/example.py"]
  },
  "spawn": {
    "fork_turns": "none",
    "model": null,
    "reasoning_effort": null
  }
}
```

`objective`, non-empty `scope`, and non-empty `completion` are required. The `strict` profile also requires explicit forbidden scope and evidence. Ordinary `context.paths` are canonical relative POSIX path hints. Put absolute locations and the relative-path base in `context.summary`; material verification is opt-in through `context.verified`.

## How it works

Each exact Codex Session has one `state-v12` ledger. One governed task represents one native Agent lifecycle and moves through these phases:

```text
prepared | claimed | bound | terminal | closed | reconcile
```

The current Session identity and governance CLI entrypoint come only from the same SessionStart Hook injection. The parent sends the generated spawn arguments unchanged, reads the exact target from that native return, and immediately confirms it. A caller-supplied short task name, nearby timestamp, `list_agents`, transcript, summary, or child final cannot establish identity. A complete canonical `task_name` mechanically returned by `collaboration_turns` is an exact target; an `agent_id` is used only when the selected native interface exposes it. Preserve the returned value verbatim.

After binding, the parent can record exact platform observations, normal-call results, terminal notifications, interrupt results, and an explicit close decision. Same-fact replay is idempotent. Conflicting or unknown facts remain visible instead of triggering an automatic retry or guessed terminal state.

For the full state machine and storage boundaries, see [Architecture](docs/architecture.md), the [reduction ADR](docs/architecture-reduction-adr.md), and [runtime boundaries](skills/subagent-governance/references/runtime-boundaries.md).

## Safety and privacy

- The core runtime does not initiate network requests and contains no telemetry.
- In state-v12, `prepared/claimed` records store the complete generated dispatch message, normalized task contract, and material-verification metadata. Later transitions remove the prepared capability but retain `contract_summary`, the full business contract excluding `spawn`, for acceptance recovery.
- The runtime does not separately archive external material contents, subsequent ordinary messages, terminal notification bodies, business results, transcripts, or child finals. Text supplied in contract fields or a close reason is still stored; there is no automatic redaction.
- Prepared expiry prevents a new claim; it does not delete the record. Open records are not automatically cleared. Closed records are lazily pruned to the newest 64 during ledger writes, not by a timed deletion service. State-v12 does not read, migrate, or delete older ledgers.
- Default `status/diagnose` includes the objective and close reason; exact-task status also returns the complete business contract. SessionStart does not inject the full contract. Spawn Hook failure diagnostics use fixed messages; this is not a blanket guarantee that all output is free of business text.
- Storage roots and output boundaries are detailed in [Architecture](docs/architecture.md#存储位置与输出边界).
- State writes use bounded input, file locking, atomic replacement, permission checks, and readback validation.
- Unmanaged native spawns remain fail-open if the governance layer is unavailable.
- The runtime bundle is built from a machine-readable allowlist and excludes tests, plans, deployment tooling, and development-only files.

Subagent Governance is **not** a sandbox, permission system, remote control plane, Hook trust authority, or security boundary between processes running as the same OS user. Codex remains responsible for approvals, sandboxing, tool authorization, Hook delivery, and model behavior. See [SECURITY.md](SECURITY.md).

## Current boundaries

- Wait calls are not persisted.
- There is no managed business resume, managed follow-up, multi-attempt retry system, Group abstraction, or automatic cross-Session recovery.
- A crash after native spawn but before exact-target confirmation remains `claimed/unbound`; the plugin does not guess identity or automatically respawn.
- Unknown receipts for bound calls are recorded separately from phase. The parent still verifies whether results satisfy instructions whose delivery was unknown.
- A prepare explicitly freezes either the `collaboration_turns` or `fork_context` native adapter. The Hook checks the generated task name and spawn configuration without comparing rewritten message text. The fork_context adapter needs a visible marker; collaboration_turns can use explicit task_name. Unverifiable identity/configuration, unknown shapes, or internal failures pass through without a claim.

## Verification

Verification is split by evidence source:

- Repository checks cover protocol, state, cross-process concurrency, lifecycle, storage safety, packaging, and deployment transactions, plus compilation, lint, coverage, and release/archive preflight.
- CI runs the automated suite on Ubuntu, macOS, and Windows with Python 3.11 and 3.12. The badge links to actual run results.
- Independent state-v12 macOS tasks verified standard dispatch, native canonical target binding, terminal/close, and a strict random-token message-to-final round trip, with parent and child configured as `gpt-5.6-terra/high`.

The latest platform checks do not cover `fork_context`, real unknown-result recovery, or restart/compact recovery. Earlier concurrency, interruption, and recovery evidence remains historical and does not establish coverage for every new version. See [local acceptance](docs/validation/current-only-local-acceptance.md), [dated platform evidence](docs/validation/current-only-real-platform-validation.md), and [platform validation](docs/platform-validation.md).

## Project documentation

- [Architecture](docs/architecture.md)
- [Governance evidence for native Codex subagents](docs/native-codex-governance-evidence.md)
- [Context completeness contract](docs/context-completeness-contract.md)
- [Interruption and reconciliation](docs/interruption-reconciliation.md)
- [Platform validation](docs/platform-validation.md)
- [Release process](docs/release-process.md)
- [Contributing](CONTRIBUTING.md)

## License

[MIT](LICENSE)
