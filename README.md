# Subagent Governance

[English](README.md) · [简体中文](README.zh-CN.md)

[![CI](https://github.com/uigdwunm/subagent-governance/actions/workflows/ci.yml/badge.svg)](https://github.com/uigdwunm/subagent-governance/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Status: stable](https://img.shields.io/badge/status-stable-2EA44F)](#release-status)

**Verifiable handoff and lifecycle governance for native Codex subagents.**

Keep native Codex as the execution layer while making task handoff, declared-context freshness, exact-target binding, waiting, interruption, and completion explicit and diagnosable.

Subagent Governance is a local Codex plugin for developers who use native subagents but do not want identity, lifecycle state, or terminal decisions to depend on task names, timing, transcripts, or guesses. It adds a small, auditable protocol around the native Agent tools while keeping those tools as the only execution channel.

## Release status

The current stable release is `v0.4.0`. Its Marketplace entry is pinned to the same immutable tag. It consolidates the lifecycle and identity fixes validated across the release-candidate series and includes the natural-language quick start.

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
- **Explicit lifecycle** — `prepare → claim → bind → terminal → close`, with bounded reconcile states for conflicting or unknown facts.
- **TaskContract v2** — one current objective, allowed scope, completion conditions, evidence, context, and explicit spawn configuration.
- **Optional verified context** — declared working-tree files or Git objects can be checked at prepare and claim time.
- **Minimal local state** — one current Session ledger, no prompt archive, no terminal body persistence, and bounded closed-task retention.
- **Read-only recovery views** — SessionStart summaries, `status`, and `diagnose` do not create or repair state.

## Evidence-backed protections

Repository tests and real Codex acceptance cover three practical protections: detecting changes to explicitly declared task materials before dispatch, retaining exact-target identity across concurrent work, and preserving unconfirmed platform results without automatic retries. These mechanisms are designed to reduce avoidable stale-material work, wrong-target follow-up, and duplicate actions without replacing native Codex execution.

See [governance evidence for native Codex subagents](docs/native-codex-governance-evidence.md) for reproducible conditions, evidence sources, practical effects, and claim boundaries.

## Installation

Install the verified `v0.4.0` release with:

```bash
codex plugin marketplace add uigdwunm/subagent-governance --ref v0.4.0
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

`objective`, non-empty `scope`, and non-empty `completion` are required. The `strict` profile also requires explicit forbidden scope and evidence. Ordinary `context.paths` are location hints; material verification is opt-in through `context.verified`.

## How it works

Each exact Codex Session has one `state-v9` ledger. One governed task represents one native Agent lifecycle and moves through these phases:

```text
prepared | claimed | bound | terminal | closed | reconcile
```

The current Session identity and governance CLI entrypoint come only from the same SessionStart Hook injection. The parent sends the generated spawn arguments unchanged, reads the exact target from that native return, and immediately confirms it. A name, nearby timestamp, `list_agents`, transcript, summary, or child final cannot establish identity.

After binding, the parent can record exact platform observations, normal-call results, terminal notifications, interrupt results, and an explicit close decision. Same-fact replay is idempotent. Conflicting or unknown facts remain visible instead of triggering an automatic retry or guessed terminal state.

For the full state machine and storage boundaries, see [Architecture](docs/architecture.md), the [reduction ADR](docs/architecture-reduction-adr.md), and [runtime boundaries](skills/subagent-governance/references/runtime-boundaries.md).

## Safety and privacy

- The core runtime does not initiate network requests and contains no telemetry.
- It does not persist complete task prompts, message bodies, terminal notification bodies, business results, transcripts, or child finals.
- State writes use bounded input, file locking, atomic replacement, permission checks, and readback validation.
- Unmanaged native spawns remain fail-open if the governance layer is unavailable.
- The runtime bundle is built from a machine-readable allowlist and excludes tests, plans, deployment tooling, and development-only files.

Subagent Governance is **not** a sandbox, permission system, remote control plane, Hook trust authority, or security boundary between processes running as the same OS user. Codex remains responsible for approvals, sandboxing, tool authorization, Hook delivery, and model behavior. See [SECURITY.md](SECURITY.md).

## Current boundaries

- Wait calls are not persisted.
- There is no managed business resume, managed follow-up, multi-attempt retry system, Group abstraction, or automatic cross-Session recovery.
- A crash after native spawn but before exact-target confirmation remains `claimed/unbound`; the plugin does not guess identity or automatically respawn.
- An unknown message, interrupt, or platform response remains unknown and may require parent reconciliation.
- Codex MultiAgent V2 exposes an opaque message at the local PreToolUse boundary, so the plugin binds the derived task reference and visible spawn configuration rather than claiming plaintext-message attestation.

## Verification

The current development line includes:

- 96 automated tests for protocol, state, concurrency, lifecycle, storage safety, packaging, and deployment transactions;
- CI on Ubuntu, macOS, and Windows with Python 3.11 and 3.12;
- plugin, Skill, archive, schema, compilation, lint, and release-preflight gates;
- real Codex acceptance covering governed dispatch, exact-target binding, active wait wake-up, concurrent governed Agents, strict verified context, message handling, interruption, terminal notification, close, and read-only diagnostics.

Local tests cannot prove every platform failure mode. Real acceptance evidence and explicit unverified boundaries are recorded in [platform validation](docs/platform-validation.md) and [current real-platform validation](docs/validation/current-only-real-platform-validation.md).

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
