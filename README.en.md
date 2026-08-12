# Subagent Governance

English | [简体中文](README.md)

Codex-first lifecycle governance for native subagents. It turns delegation, execution, waiting, recovery, and acceptance from informal context-dependent coordination into an explicit, traceable, recoverable, and verifiable workflow.

The plugin is designed and tested primarily for Codex native subagent tools, Codex Skills, Codex Hooks, Codex CLI, and Codex in the ChatGPT desktop app. It extends native `spawn_agent`; it does not introduce a second orchestration platform or replace Codex sandboxing, approvals, models, or the parent agent's judgment.

## Core capabilities

- Adaptive `light`, `standard`, `strict`, and `auto` governance levels.
- Explicit task contracts covering the objective, scope, prohibitions, completion criteria, model, reasoning effort, and context inheritance.
- Deterministic dispatch and exact agent-to-task identity binding.
- Ordered waiting, bounded recovery, explicit communication, and interrupt reconciliation.
- Structured formal results with evidence, remaining work, and a suggested parent next step.
- Separate execution completion, result validity, and parent acceptance states.
- Read-only diagnostics and lightweight multi-agent grouping without a second scheduler or group state machine.

## Install

```bash
codex plugin marketplace add uigdwunm/subagent-governance --ref main
codex plugin add subagent-governance@subagent-governance
```

Then start a new Codex task, open `/hooks`, review and trust the seven plugin Hooks, and start another new task for a smoke test.

Example:

```text
Use $subagent-governance in light mode to delegate a read-only review of the README installation steps.
```

Supported environments:

- Codex CLI and Codex in the ChatGPT desktop app
- macOS, Linux, and Windows
- Python 3.11 or 3.12

## Boundaries and data

- The core runtime does not initiate network requests and contains no telemetry.
- Runtime state and formal results are stored locally in the current user's Codex plugin data directory.
- This is a collaboration-governance layer, not a security sandbox. Parent agents, child agents, and local CLI operations remain within the permissions granted by Codex and the current OS user.
- Hook trust, event delivery, native agent identity, and tool responses remain Codex platform boundaries.
- Existing tasks may retain references to the plugin cache loaded when they started; validate upgrades in a new task.

See the [Chinese README](README.md) for complete installation, upgrade, diagnostics, and maintenance instructions. See [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [CHANGELOG.md](CHANGELOG.md) for project governance.

## License

MIT. See [LICENSE](LICENSE).
