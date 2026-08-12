# Security Policy

## Reporting a vulnerability

Please use GitHub's private **Report a vulnerability** / Security Advisory flow for this repository. Do not include credentials, private prompts, local paths, Session identifiers, or unreleased exploit details in a public issue.

If the private reporting flow is unavailable, contact the maintainer through the private contact method listed on the GitHub profile before publishing details. Public issues may be used for non-sensitive reliability and hardening discussions.

Please include:

- affected version or commit;
- supported Codex surface and operating system;
- required attacker access and trust assumptions;
- minimal reproduction steps;
- observed impact;
- whether the issue reproduces in an isolated temporary data root.

## Security model

Subagent Governance is a local Codex plugin. It runs with the authority of the current Codex process and operating-system user. It does not provide a separate login, remote control plane, privilege boundary, or sandbox between the parent Agent, child Agents, local CLI callers, and arbitrary processes already running as the same user.

The plugin's security responsibilities include:

- rejecting unsafe paths, symbolic links, malformed state, invalid identities, conflicting results, and unauthorized governed lifecycle transitions where the platform exposes enough facts;
- using bounded input, file locking, atomic replacement, and readback validation;
- preventing governance failures from silently creating false success states;
- avoiding disclosure of complete task prompts, business results, or evidence through diagnostics;
- keeping external command execution argument-based rather than shell-interpolated.

Codex remains responsible for sandboxing, approvals, tool authorization, Hook event delivery, Hook trust, native Agent identity, and model behavior.

## What normally counts as a security issue

- execution outside the permissions granted by Codex or the current OS user;
- cross-user modification or disclosure through unsafe filesystem handling;
- command injection or path traversal reachable from a lower-trust input;
- leakage of secrets, complete private task content, or protected local data;
- a lower-trust Agent or input gaining a capability that the documented threat model actually isolates from it.

## What is normally a reliability or governance issue

- a process already running as the same trusted OS user editing its own plugin state;
- parent/child role conventions that are not backed by a Codex or OS isolation boundary;
- Hook delivery failures, stream disconnections, or unknown native responses that cause incorrect lifecycle reporting but no privilege or data boundary crossing;
- denial of the caller's own task by an actor that already controls that task and its local state.

These issues can still be important bugs, especially when they create false terminal states or prevent recovery, but they should not be reported as high-impact security vulnerabilities without a concrete boundary-crossing attack path.

## Data and network behavior

- The core runtime does not initiate network requests and contains no telemetry.
- Codex may access the configured Git Marketplace during installation or upgrade.
- Runtime state and formal results are stored in the current user's local Codex plugin data directory.
- Diagnostic output is intentionally bounded and omits complete business result and evidence content.
- Raw platform acceptance logs may contain host paths and Session identifiers and must not be committed; the repository ignores `docs/real-platform-test-*.md`.

## Supported versions

Security fixes are applied to the current development line and the latest published release candidate or stable release when practical. Older release candidates are not guaranteed to receive separate patches.
