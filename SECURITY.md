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

- rejecting unsafe paths, symbolic links, malformed state, invalid identities, conflicting terminal observations, and unauthorized governed lifecycle transitions where the platform exposes enough facts;
- using bounded input, file locking, atomic replacement, and readback validation;
- preventing governance failures from silently creating false success states;
- keeping spawn Hook failure diagnostics free of input bodies and exception text, while exposing documented contract fields through local recovery views as described below;
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
- The following storage behavior describes the unreleased state-v12 development line, not a deployed release; the stable tag remains v0.4.0.
- Each Session ledger stores lifecycle metadata and the original normalized business contract. In `prepared/claimed`, it also stores the complete generated dispatch message, full normalized task contract, and material-verification metadata. Later transitions remove the prepared capability while retaining the business contract excluding `spawn` for acceptance recovery.
- The runtime does not separately archive external material contents, subsequent ordinary messages, terminal notification bodies, business results, transcripts, or child finals. Text supplied in contract fields or a close reason is still stored without automatic redaction.
- Prepared expiry prevents a new claim; it does not delete the record. Open records are not automatically cleared; closed records are lazily pruned to the newest 64 during ledger writes, without timed deletion. State-v12 does not read, migrate, or delete older ledgers.
- Default `status/diagnose` includes objectives and close reasons; exact-task status returns the full business contract. SessionStart omits the full contract. Spawn Hook failure diagnostics use fixed messages, whereas `diagnose` can also report a data-root path and a bounded read error. These outputs are not automatically redacted.
- The data root depends on environment overrides and installation layout; development and uninstalled modules default to a per-user temporary root. See [storage locations and output boundaries](docs/architecture.md#存储位置与输出边界). A temporary location does not establish a deletion deadline.
- Raw platform evidence may contain host paths and Session identifiers and must not be committed; the repository ignores `docs/private-platform-evidence-*.md`.

## Supported versions

Security fixes target the current development line and the current published release. The project does not maintain parallel release lines.
