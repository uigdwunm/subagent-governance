# Contributing

Thank you for helping improve Subagent Governance. The project is designed primarily for Codex native subagents, Skills, and Hooks, so changes should preserve native Codex behavior and avoid introducing a second orchestration platform.

## Before opening a change

- Use an issue for substantial behavior changes so the task boundary and platform impact can be discussed first.
- Keep changes focused. Do not mix unrelated refactors, formatting, or cleanup into the same pull request.
- Preserve unmanaged native `spawn_agent` pass-through unless the change explicitly targets that boundary.
- Do not modify a user's installed plugin cache, Hook trust state, global configuration, or personal Marketplace as part of repository development.

## Development setup

Requirements:

- Python 3.11 or 3.12
- macOS, Linux, or Windows
- Codex only when performing real platform acceptance; unit tests do not require an active Codex task

Run the local validation suite:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts
ruff check scripts tests
coverage run -m unittest discover -s tests -v
coverage report
python3 scripts/release_preflight.py --mode development
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
```

On Windows, use `py -3` in place of `python3` where appropriate.

## Implementation expectations

- Add a minimal reliable regression test before fixing runtime bugs.
- Keep persisted governance state current-only and reject non-current data without migration or rewrite. The installation layout may retain exactly one previous immutable plugin cache so tasks that predate a Codex restart keep their original file paths; this retention must not introduce old-version logic into the current plugin.
- Keep protocol, Skill, Hook, Schema, and runtime semantics aligned.
- Treat unknown platform responses as unknown; do not silently convert them to success or failure.
- Preserve terminal notification observation and explicit parent lifecycle disposition as separate stages; do not add business-result persistence or acceptance state.
- Keep diagnostic operations read-only.
- Do not add network services, telemetry, databases, background daemons, or a second Agent scheduler without an explicitly approved project-level design change.

## Pull requests

A pull request should include:

- the problem and intended behavior;
- the files and boundaries changed;
- tests and validators run, with results;
- platform impact for Codex CLI, Codex desktop, macOS, Linux, and Windows where relevant;
- any real-platform checks that remain unverified.

Runtime code changes should pass the full unit suite, Python compilation, Plugin validator, and Skill validator. Documentation-only changes should at least run the relevant structure tests and validators.

## Real platform validation

Repository tests cannot prove Hook trust, actual Codex event delivery, installed-cache selection, or native Agent identity behavior. Changes affecting those areas should be verified in a new Codex task after installation. Public evidence must be redacted as described in [docs/platform-validation.md](docs/platform-validation.md).

Publishing, installing a stable release, modifying Marketplace state, trusting Hooks, or updating global `AGENTS.md` requires separate explicit authorization and is not implied by accepting a code change.
