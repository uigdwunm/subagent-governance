# Real platform lifecycle compatibility fix

Date: 2026-08-14

> Superseded on 2026-08-14 by the platform-capability slice 1 contract. Sections
> 3-7 below preserve the abandoned transcript-routing experiment as historical
> evidence only. They are not current runtime guarantees: SubagentStart is unbound,
> SubagentStop does not consume `task_result`, transcript metadata is not correctness
> authority, and parent Stop fails open on unreliable state. See
> `schemas/codex-hook-events-v1.contract.json` and
> `docs/redesign/platform-capability-slice-1-implementation.md`.

## Post-deployment correction

The installed `0.4.0-rc.12+codex.20260814081253` smoke disproved this slice's
SubagentStart input assumption. The Hook did run, but injected unmanaged context and
left the parent attempt unconfirmed. Current official OpenAI Hook documentation states
that subagent lifecycle `session_id` is the parent session, SubagentStart does not
define `agent_transcript_path`, and only SubagentStop adds that optional field. The
fixture and route below therefore model a non-canonical Start payload and are not real
platform acceptance evidence.

The corrected evidence, blocker classification, and safe next-slice boundary are in
`docs/real-platform-test-2026-08-14-cachebuster-20260814081253.md`. Until that blocker
is fixed and retested, this document remains a local implementation record rather than
a valid platform-compatibility conclusion.

## 1. Scope and boundary

This change fixes the development repository's parent/child session routing for real
`SubagentStart` and `SubagentStop` events. It does not update an installed plugin,
stable source, Marketplace, runtime cache, Hook trust, Registry, or either failed
smoke-test StateStore. It also does not create a real test task.

The affected smoke used parent thread
`019fff19-6a0c-7121-baa9-cb4687a4d80b`, child thread
`019fff1a-743b-7823-adb4-9fd25d2f6eef`, task ref `8924827a105b`, and canonical
path `/root/sg_light_verify_trusted_hooks_t_8924827a105b`.

## 2. Evidence boundary

### Observed

- The preserved parent StateStore records a consumed spawn claim, exact tool-use ID,
  `spawn_observation=success`, and
  `spawn_observed_canonical_path=/root/sg_light_verify_trusted_hooks_t_8924827a105b`.
  It also preserves `identity_status=unconfirmed`, `execution_status=not_started`,
  `agent_id=null`, `canonical_task_path=null`, and an empty Agent index.
- The parent rollout records the native function-call output as the JSON string
  `{"task_name":"/root/sg_light_verify_trusted_hooks_t_8924827a105b"}`. The current
  `_json_value()` plus `adapt_spawn_response()` path can parse that finite shape; the
  preserved StateStore proves that PostToolUse actually wrote the success observation.
- The parent rollout's `sub_agent_activity` record contains the child thread ID and
  exact canonical Agent path.
- The child rollout is a separate file and its first `session_meta` record contains:
  child `id`; top-level `parent_thread_id`; top-level `session_id` equal to that parent;
  `thread_source=subagent`; top-level `agent_path`; and the same parent/path under
  `source.subagent.thread_spawn`.
- The child rollout contains the injected start context with `治理任务 ID：未映射`,
  proving that the active SubagentStart Hook completed but did not associate the
  managed attempt.
- The current local Codex binary's serialized Hook field table includes
  `session_id`, `agent_transcript_path`, `agent_id`, and `agent_type` for subagent
  lifecycle input. It does not expose `task_name` or canonical path as lifecycle
  input fields.
- The child produced a natural-language terminal answer, while the preserved parent
  state contains no formal result and the exact read-result operation rejected it as
  unavailable.

### Not directly observed

- Raw SubagentStart and SubagentStop stdin was not logged. Therefore the exact real
  value of `agent_id`, and whether the failed smoke's Stop payload contained any
  `task_result` field, are not claimed as observed facts.
- The platform-internal construction order between lifecycle Hook input and rollout
  persistence is not observable. The implementation handles an unavailable, unsafe,
  oversized, malformed, or conflicting transcript by warning and allowing the native
  lifecycle to continue.
- A local fixture demonstrates the observed field relationship; it is not a substitute
  for a new installed-plugin test task.

No association decision in this change comes from a global filename, task-name, or
StateStore scan.

## 3. Root cause

The PostTool response adapter was not the failing component for this smoke. It already
accepts a top-level JSON string and recorded the exact canonical path as a spawn
observation without prematurely confirming identity.

The lifecycle handlers used only `payload.session_id` to select one StateStore. They
ignored `agent_transcript_path`, even though the child rollout's first metadata record
contains the exact parent thread and canonical Agent path. In addition,
`_event_task_name()` expected optional task/path fields that the current lifecycle Hook
field table does not provide. Consequently Start could not find the parent's exact task
ref, and Stop had no retained target provenance through which to associate a formal
result or record a protocol gap.

## 4. Design

`_read_subagent_event_route()` now derives one bounded route from the event's own
transcript only:

1. Require an absolute `agent_transcript_path` when the field is present.
2. Open it with no-follow semantics where supported; require a regular file owned by
   the current user and verify that the opened inode is the inspected inode.
3. Read only the first line, bounded by the existing Hook input limit, and require a
   UTF-8 JSON `session_meta` record with `thread_source=subagent`.
4. Require the top-level and nested parent thread IDs to agree, require metadata
   `session_id` to equal that parent, and require the Hook session to equal the child
   metadata ID.
5. Require top-level and nested canonical paths to agree and contain a valid governed
   task name/task ref. Any optional event path/task-name field must agree as well.
6. Before a Start write, require the selected parent StateStore to contain either an
   exact existing target mapping or the exact managed task name and task ref. This
   prevents a self-consistent but wrong transcript from creating an unrelated empty
   parent StateStore.

SubagentStart then runs the existing locked `_assign_starting_agent()` transition in
the exact parent session, binding both the event Agent ID and canonical path. The
existing conflict, terminal, late-event, and lifecycle-operation checks remain
authoritative. PreparedContract deletion also uses the resolved parent session.

SubagentStop resolves the same parent route before applying the existing retained
target and structured TaskResult rules. A Stop without a valid structured result still
becomes `needs_correction`; natural-language output is not promoted into business
truth.

All transcript/read/provenance/state conflicts are caught at the Hook boundary. Start
injects unmanaged context with a bounded warning; Stop returns `continue=true` with a
warning. Native subagent execution is never blocked by this compatibility adapter.

## 5. Preserved invariants

- PostTool success observes the native call only; it remains
  `not_started + unconfirmed` until an exact Start.
- Only exact SubagentStart/lifecycle authorization can write
  `running + confirmed`.
- Target identity remains `{task_id, attempt}` plus retained Agent ID/canonical-path
  provenance. The active Agent index remains a lookup, not identity authority.
- No same-name, newest-task, current-attempt, timestamp, directory, or global-state
  guessing was added.
- Conflicts do not overwrite another task, attempt, or session and do not create a
  replacement Agent.
- Only a schema-valid structured TaskResult can establish business result truth.
- Governance compatibility failures remain fail-open for native Start/Stop execution.

## 6. Failure-first and regression evidence

The revised `lifecycle-v1.json` models the real boundary: parent Pre/PostTool events,
string PostTool response, independent child lifecycle session, event-provided transcript
path, exact first-line session metadata, and Stop without a structured result.

Before the runtime change, the focused test failed with:

```text
AssertionError: 'unconfirmed' != 'confirmed'
```

After the change, the fixture proves:

- string PostTool response becomes `spawn_observation=success` while identity remains
  unconfirmed and execution remains not started;
- cross-session Start binds the exact parent attempt and enters running;
- the injected context names the managed task ID;
- cross-session Stop reaches the same retained execution and records
  `needs_correction` for the missing structured result;
- conflicting transcript provenance fails open without parent mutation or child-state
  creation;
- a self-consistent transcript naming the wrong parent cannot create an unrelated
  StateStore.

The final command results are recorded in section 8 after all gates complete.

## 7. Remaining limits and real retest condition

- The compatibility route is proven against Codex `0.147.0-alpha.6.5` rollout metadata.
  A future platform that changes or delays the first `session_meta` shape will degrade
  to unmanaged/fail-open until a new observed adapter is added.
- The real `agent_id` value and real Stop `task_result` visibility still need direct
  observation in a new test task. The adapter intentionally does not require Agent ID
  to equal child thread ID; it treats the event-provided non-empty Agent ID as the
  target and independently validates the event session against transcript child ID.
- This change makes deployment followed by a new real lifecycle test meaningful. It
  does not itself satisfy project real-platform acceptance because installation and a
  new task were explicitly out of scope.
- A new smoke must submit a schema-valid structured TaskResult through the supported
  path or deliberately verify the `needs_correction` flow. Repeating only a natural-
  language final answer cannot prove formal-result closure.

## 8. Final local verification

| Gate | Result |
| --- | --- |
| Failure-first focused fixture before runtime change | Failed as expected: parent identity remained `unconfirmed` |
| Hook fixture module after runtime change | 6 tests, OK |
| Dispatch identity module | 74 tests, OK |
| Communication, formal-result, and session-closure modules | 120 tests, OK |
| Full `python3 -m unittest discover -s tests -v` | 381 tests, OK |
| Required `python3 -m py_compile scripts/subagent_governance.py` | Passed |
| Existing five-script Python compile gate | Passed |
| Plugin validator | `Plugin validation passed` |
| Skill validator | `Skill is valid!` (Skill was not changed by this task) |
| All repository JSON parsed with `jq empty` | Passed |
| `git diff --check` | Passed |
| Release-preflight test module | 5 tests, OK |
| `python3 scripts/release_preflight.py --mode development` | Exit 0, `status=passed` |

These are development-repository results only. Installed-plugin synchronization and a
new real test task remain required before claiming the platform lifecycle is fully
fixed.
