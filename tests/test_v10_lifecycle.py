#!/usr/bin/env python3
"""Acceptance coverage for the minimal state-v12 lifecycle slice."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import governance_diagnostics as diagnostics
from scripts import governance_lifecycle as lifecycle
from scripts import governance_protocol as protocol
from scripts import governance_semantics as semantics
from scripts import governance_state as state_domain
from scripts.governance_errors import StateConflictError
from scripts.governance_hook import handle_hook
from scripts.governance_state_store import StateStore
from tests.schema_validation import validate_instance


class V10LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = StateStore(self.root / "sessions")
        self.session_id = "lifecycle-session"

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self, task_id: str = "lifecycle-task", *, now: int = 100):
        return protocol.prepare_dispatch(
            {
                "objective": f"Exercise lifecycle {task_id}",
                "scope": ["tests"],
                "completion": ["lifecycle fact recorded"],
            },
            self.session_id,
            native_interface="fork_context",
            state_store=self.store,
            task_id_factory=lambda: task_id,
            now=now,
        )

    def bind(self, task_id: str = "lifecycle-task"):
        prepared = self.prepare(task_id)
        allowed = handle_hook(
            {
                "session_id": self.session_id,
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": f"call-{task_id}",
                "tool_input": prepared["spawn_args"],
                "now": 101,
            },
            self.store,
        )
        self.assertEqual(
            allowed["hookSpecificOutput"]["permissionDecision"], "allow"
        )
        from scripts.governance_dispatch import confirm_dispatch

        target = f"/root/{task_id}"
        confirm_dispatch(
            self.session_id,
            {
                "task_id": prepared["task_id"],
                "task_ref": prepared["task_ref"],
                "target": target,
            },
            state_store=self.store,
            now=102,
        )
        return prepared, target

    def task(self, task_id: str = "lifecycle-task"):
        return self.store.read(self.session_id)["tasks"][task_id]

    @staticmethod
    def identity(prepared, target, **extra):
        return {
            "task_id": prepared["task_id"],
            "task_ref": prepared["task_ref"],
            "target": target,
            **extra,
        }

    def assert_current_schema(self):
        state = self.store.read(self.session_id)
        self.assertEqual(state_domain.validate_current_state_format(state), [])
        self.assertEqual(
            validate_instance(
                state,
                semantics.MACHINE_SEMANTICS["$defs"]["session_ledger"],
                root_schema=semantics.MACHINE_SEMANTICS,
            ),
            [],
        )

    def test_platform_observation_requires_bound_exact_target(self):
        prepared, target = self.bind()
        request = self.identity(prepared, target, status="running")
        result = lifecycle.record_platform_observation(
            self.session_id, request, state_store=self.store, now=103
        )
        replay = lifecycle.record_platform_observation(
            self.session_id, request, state_store=self.store, now=999
        )
        self.assertEqual(result["result"], "recorded")
        self.assertEqual(replay["result"], "already_observed")
        self.assertEqual(
            self.task()["platform_observation"],
            {"status": "running", "observed_at": 103},
        )
        self.assertEqual(self.task()["phase"], "bound")
        with self.assertRaisesRegex(StateConflictError, "target"):
            lifecycle.record_platform_observation(
                self.session_id,
                {**request, "target": "/root/not-bound"},
                state_store=self.store,
                now=104,
            )
        with self.assertRaisesRegex(ValueError, "字段"):
            lifecycle.record_platform_observation(
                self.session_id,
                {**request, "response": "must not persist"},
                state_store=self.store,
                now=104,
            )
        self.assert_current_schema()

    def test_terminal_unknown_recording_replay_identity_and_closed(self):
        operations = ((lifecycle.record_call_result, "result", "delivery_unknown"),
                      (lifecycle.record_platform_observation, "status", "platform_observation_unknown"),
                      (lifecycle.record_interrupt_result, "result", "interrupt_unknown"))
        for operation, field, code in operations:
            for early in (False, True):
                for source in ("platform", "notification", "inactive"):
                    task_id = f"{code}-{early}-{source}"
                    with self.subTest(task=task_id):
                        prepared, target = self.bind(task_id)
                        request = self.identity(prepared, target, **{field: "unknown"})
                        if early:
                            operation(self.session_id, request, state_store=self.store, now=103)
                        if source == "platform":
                            lifecycle.record_platform_observation(self.session_id,
                                self.identity(prepared, target, status="completed"), state_store=self.store, now=104)
                        elif source == "notification":
                            lifecycle.record_terminal_notification(self.session_id,
                                {"task_id": task_id, "task_ref": prepared["task_ref"], "sender": target,
                                 "status": "completed"}, state_store=self.store, now=104)
                        else:
                            lifecycle.record_interrupt_result(self.session_id,
                                self.identity(prepared, target, result="inactive"), state_store=self.store, now=104)
                        terminal = self.task(task_id)["terminal_fact"]
                        result = operation(self.session_id, request, state_store=self.store, now=105)
                        self.assertEqual(result["result"], "already_unknown" if early else "unknown_recorded")
                        before = self.task(task_id)
                        self.assertEqual(before["phase"], "terminal")
                        self.assertEqual(before["terminal_fact"], terminal)
                        self.assertEqual(before["unknown_facts"][code], {"observed_at": 103 if early else 105})
                        self.assertEqual(operation(self.session_id, request, state_store=self.store, now=999)["result"],
                                         "already_unknown")
                        self.assertEqual(self.task(task_id), before)
                        for key, wrong in (("task_id", "absent"), ("task_ref", "wrong"), ("target", "/root/wrong")):
                            with self.assertRaises(StateConflictError):
                                operation(self.session_id, {**request, key: wrong}, state_store=self.store, now=999)
                            self.assertEqual(self.task(task_id), before)
                        lifecycle.close_task(self.session_id, {"task_id": task_id, "task_ref": prepared["task_ref"],
                            "reason": "done"}, state_store=self.store, now=106)
                        closed = self.task(task_id)
                        with self.assertRaises(StateConflictError):
                            operation(self.session_id, request, state_store=self.store, now=999)
                        self.assertEqual(self.task(task_id), closed)
                        for other, other_field, _ in operations:
                            with self.assertRaises(StateConflictError):
                                other(self.session_id, self.identity(prepared, target, **{other_field: "unknown"}),
                                      state_store=self.store, now=999)
                            self.assertEqual(self.task(task_id), closed)
                        self.assert_current_schema()

    def test_unknown_receipts_allow_later_terminal_and_survive_close(self):
        operations = (
            (lifecycle.record_call_result, "result", "delivery_unknown"),
            (lifecycle.record_platform_observation, "status", "platform_observation_unknown"),
            (lifecycle.record_interrupt_result, "result", "interrupt_unknown"),
        )
        for operation, field, code in operations:
            for source in ("platform", "notification"):
                task_id = f"{code}-{source}"
                with self.subTest(code=code, source=source):
                    prepared, target = self.bind(task_id)
                    operation(
                        self.session_id, self.identity(prepared, target, **{field: "unknown"}),
                        state_store=self.store, now=103,
                    )
                    # Exercise the complete chain before checking phase so the old
                    # implementation demonstrates that it ignores a later terminal.
                    if source == "platform":
                        lifecycle.record_platform_observation(
                            self.session_id, self.identity(prepared, target, status="interrupted"),
                            state_store=self.store, now=104,
                        )
                    else:
                        lifecycle.record_terminal_notification(
                            self.session_id,
                            {"task_id": task_id, "task_ref": prepared["task_ref"],
                             "sender": target, "status": "interrupted"},
                            state_store=self.store, now=104,
                        )
                    self.assertEqual(self.task(task_id)["phase"], "terminal")
                    first_terminal = self.task(task_id)["terminal_fact"]
                    # An independent matching observation may supplement the
                    # notification without replacing its provenance or time.
                    lifecycle.record_platform_observation(
                        self.session_id, self.identity(prepared, target, status="interrupted"),
                        state_store=self.store, now=105,
                    )
                    self.assertEqual(self.task(task_id)["terminal_fact"], first_terminal)
                    lifecycle.close_task(
                        self.session_id,
                        {"task_id": task_id, "task_ref": prepared["task_ref"], "reason": "parent_stopped_tracking"},
                        state_store=self.store, now=106,
                    )
                    task = self.task(task_id)
                    self.assertEqual(task["unknown_facts"], {code: {"observed_at": 103}})
                    self.assertEqual(task["terminal_fact"]["source"], source)
                    self.assertEqual(task["terminal_fact"]["status"], "interrupted")
                    self.assertEqual(task["phase"], "closed")
                    self.assert_current_schema()

    def test_close_preserves_first_reconcile_reason(self):
        prepared, target = self.bind()
        from scripts.governance_dispatch import confirm_dispatch

        confirm_dispatch(
            self.session_id, self.identity(prepared, "/root/other"),
            state_store=self.store, now=103,
        )
        reason = self.task()["reconcile"]
        lifecycle.close_task(
            self.session_id,
            {"task_id": prepared["task_id"], "task_ref": prepared["task_ref"], "reason": "stop_conflicted_task"},
            state_store=self.store, now=104,
        )
        self.assertEqual(self.task().get("reconcile"), reason)
        self.assertEqual(self.task()["target"], target)
        self.assert_current_schema()

    def test_all_unknown_categories_are_bounded_idempotent_and_keep_known_status(self):
        prepared, target = self.bind()
        lifecycle.record_platform_observation(
            self.session_id, self.identity(prepared, target, status="running"),
            state_store=self.store, now=103,
        )
        operations = (
            (lifecycle.record_call_result, "result", "delivery_unknown"),
            (lifecycle.record_platform_observation, "status", "platform_observation_unknown"),
            (lifecycle.record_interrupt_result, "result", "interrupt_unknown"),
        )
        expected = {}
        path = next((self.root / "sessions").glob("*.json"))
        for index, (operation, field, code) in enumerate(operations):
            request = self.identity(prepared, target, **{field: "unknown"})
            result = operation(self.session_id, request, state_store=self.store, now=104 + index)
            self.assertEqual(result["result"], "unknown_recorded")
            expected[code] = {"observed_at": 104 + index}
            before = path.read_bytes()
            replay = operation(self.session_id, request, state_store=self.store, now=999)
            self.assertEqual(replay["result"], "already_unknown")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.task()["unknown_facts"], expected)
            self.assertEqual(self.task()["phase"], "bound")
            self.assertEqual(self.task()["platform_observation"]["status"], "running")
            self.assert_current_schema()
        # A certain error still is not a completion; unknown receipts survive it.
        lifecycle.record_platform_observation(
            self.session_id, self.identity(prepared, target, status="error"),
            state_store=self.store, now=107,
        )
        self.assertEqual(self.task()["phase"], "bound")
        self.assertNotIn("terminal_fact", self.task())
        self.assertEqual(self.task()["unknown_facts"], expected)

    def test_unknown_facts_survive_conflict_without_weakening_identity_or_close(self):
        prepared, target = self.bind()
        lifecycle.record_call_result(
            self.session_id, self.identity(prepared, target, result="unknown"),
            state_store=self.store, now=103,
        )
        request = {"task_id": prepared["task_id"], "task_ref": prepared["task_ref"],
                   "sender": target, "status": "completed"}
        path = next((self.root / "sessions").glob("*.json"))
        for field, wrong in (("task_id", "missing"), ("task_ref", "wrong"), ("sender", "/root/other")):
            before = path.read_bytes()
            with self.assertRaises(StateConflictError):
                lifecycle.record_terminal_notification(
                    self.session_id, {**request, field: wrong}, state_store=self.store, now=104,
                )
            self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(StateConflictError):
            lifecycle.record_terminal_notification("other-session", request, state_store=self.store, now=104)
        lifecycle.record_terminal_notification(self.session_id, request, state_store=self.store, now=104)
        terminal = self.task()["terminal_fact"]
        lifecycle.record_terminal_notification(
            self.session_id, {**request, "status": "interrupted"}, state_store=self.store, now=105,
        )
        first = self.task()
        self.assertEqual(first["reconcile"]["code"], "terminal_status_conflict")
        from scripts.governance_dispatch import confirm_dispatch

        for operation, payload in (
            (lifecycle.record_terminal_notification, request),
            (lifecycle.record_platform_observation, self.identity(prepared, target, status="completed")),
            (lifecycle.record_interrupt_result, self.identity(prepared, target, result="unknown")),
            (lifecycle.record_call_result, self.identity(prepared, target, result="unknown")),
            (confirm_dispatch, {**self.identity(prepared, target), "task_ref": "wrong"}),
        ):
            result = operation(self.session_id, payload, state_store=self.store, now=106)
            self.assertEqual(result["result"], "reconcile")
            self.assertEqual(self.task(), first)
        close = {"task_id": prepared["task_id"], "task_ref": prepared["task_ref"], "reason": "stop_conflicted_task"}
        lifecycle.close_task(self.session_id, close, state_store=self.store, now=107)
        closed = self.task()
        self.assertEqual(closed["unknown_facts"], {"delivery_unknown": {"observed_at": 103}})
        self.assertEqual(closed["reconcile"], first["reconcile"])
        self.assertEqual(closed["terminal_fact"], terminal)
        lifecycle.close_task(self.session_id, close, state_store=self.store, now=999)
        self.assertEqual(self.task(), closed)
        replay = confirm_dispatch(
            self.session_id, self.identity(prepared, target), state_store=self.store, now=999,
        )
        self.assertEqual(replay["result"], "already_closed")
        self.assertEqual(self.task(), closed)
        for operation, payload in (
            (lifecycle.record_terminal_notification, request),
            (lifecycle.record_platform_observation, self.identity(prepared, target, status="completed")),
            (lifecycle.close_task, {**close, "reason": "different"}),
        ):
            with self.assertRaises(StateConflictError):
                operation(self.session_id, payload, state_store=self.store, now=999)
            self.assertEqual(self.task(), closed)
        self.assert_current_schema()

    def test_unknown_schema_and_runtime_reject_malformed_or_unbound_facts(self):
        prepared, target = self.bind()
        lifecycle.record_interrupt_result(
            self.session_id, self.identity(prepared, target, result="unknown"),
            state_store=self.store, now=103,
        )
        baseline = self.store.read(self.session_id)
        invalid = [None, {}, [], {"fourth": {"observed_at": 103}},
                   {"interrupt_unknown": {}}, {"interrupt_unknown": {"observed_at": True}},
                   {"interrupt_unknown": {"observed_at": -1}},
                   {"interrupt_unknown": {"observed_at": 103, "body": "forbidden"}}]
        for phase in ("bound", "terminal", "reconcile", "closed"):
            valid = copy.deepcopy(baseline)
            task = valid["tasks"][prepared["task_id"]]
            task["phase"] = phase
            if phase == "terminal":
                task["terminal_fact"] = {"source": "notification", "status": "completed", "observed_at": 103}
            if phase == "reconcile":
                task["reconcile"] = {"code": "dispatch_target_conflict", "observed_at": 103}
            if phase == "closed":
                task.update(close_reason="stop", closed_at=103)
            candidates = []
            for value in invalid:
                candidate = copy.deepcopy(valid)
                candidate["tasks"][prepared["task_id"]]["unknown_facts"] = value
                candidates.append(candidate)
            for missing in ("target", "bound_at"):
                candidate = copy.deepcopy(valid)
                del candidate["tasks"][prepared["task_id"]][missing]
                candidates.append(candidate)
            for candidate in candidates:
                with self.subTest(phase=phase, task=candidate["tasks"][prepared["task_id"]]):
                    self.assertTrue(state_domain.validate_current_state_format(candidate))
                    self.assertTrue(validate_instance(candidate, semantics.MACHINE_SEMANTICS["$defs"]["session_ledger"], root_schema=semantics.MACHINE_SEMANTICS))
            self.assertEqual(state_domain.validate_current_state_format(valid), [])
            self.assertEqual(validate_instance(valid, semantics.MACHINE_SEMANTICS["$defs"]["session_ledger"], root_schema=semantics.MACHINE_SEMANTICS), [])
        unbound = self.prepare("unbound-unknown")
        invalid_state = self.store.read(self.session_id)
        invalid_state["tasks"][unbound["task_id"]]["unknown_facts"] = {"interrupt_unknown": {"observed_at": 103}}
        self.assertTrue(state_domain.validate_current_state_format(invalid_state))
        self.assertTrue(validate_instance(invalid_state, semantics.MACHINE_SEMANTICS["$defs"]["session_ledger"], root_schema=semantics.MACHINE_SEMANTICS))

    def test_recovery_views_show_unknown_separately_and_are_readonly(self):
        prepared, target = self.bind()
        lifecycle.record_interrupt_result(
            self.session_id, self.identity(prepared, target, result="unknown"),
            state_store=self.store, now=103,
        )
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.store.root.iterdir()}
        current = diagnostics.status(self.session_id, self.root)["tasks"][0]
        self.assertEqual(current["next_action"], "observe_exact_target")
        self.assertEqual(current["unknown_facts"], {"interrupt_unknown": {"observed_at": 103}})
        self.assertIsNone(current["reconcile_reason"])
        report = diagnostics.diagnose(self.session_id, self.root)
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["status"]["tasks"][0], current)
        with mock.patch("scripts.governance_hook.data_root_path", return_value=self.root):
            result = handle_hook({"hook_event_name": "SessionStart", "session_id": self.session_id})
        summary = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn(target, summary)
        self.assertIn("phase=bound", summary)
        self.assertIn("next_action=observe_exact_target", summary)
        self.assertIn("interrupt_unknown", summary)
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.store.root.iterdir()})
        lifecycle.close_task(
            self.session_id,
            {"task_id": prepared["task_id"], "task_ref": prepared["task_ref"], "reason": "stop_tracking"},
            state_store=self.store, now=104,
        )
        current = diagnostics.status(self.session_id, self.root)["tasks"][0]
        self.assertEqual(current["next_action"], "none")
        self.assertIn("interrupt_unknown", current["unknown_facts"])
        with mock.patch("scripts.governance_hook.data_root_path", return_value=self.root):
            result = handle_hook({"hook_event_name": "SessionStart", "session_id": self.session_id})
        self.assertNotIn(target, result["hookSpecificOutput"]["additionalContext"])

    def test_platform_terminal_replay_and_conflict_preserve_first_fact(self):
        prepared, target = self.bind()
        completed = self.identity(prepared, target, status="completed")
        first = lifecycle.record_platform_observation(
            self.session_id, completed, state_store=self.store, now=103
        )
        replay = lifecycle.record_platform_observation(
            self.session_id, completed, state_store=self.store, now=999
        )
        self.assertEqual(first["result"], "terminal")
        self.assertEqual(replay["result"], "already_terminal")
        task = self.task()
        self.assertEqual(task["phase"], "terminal")
        self.assertEqual(
            task["terminal_fact"],
            {"source": "platform", "status": "completed", "observed_at": 103},
        )
        self.assertEqual(task["updated_at"], 103)
        conflict = lifecycle.record_terminal_notification(
            self.session_id,
            {
                "task_id": prepared["task_id"],
                "task_ref": prepared["task_ref"],
                "sender": target,
                "status": "stopped",
            },
            state_store=self.store,
            now=104,
        )
        self.assertEqual(conflict["result"], "reconcile")
        task = self.task()
        self.assertEqual(task["phase"], "reconcile")
        self.assertEqual(task["reconcile"]["code"], "terminal_status_conflict")
        self.assertEqual(task["terminal_fact"]["status"], "completed")
        self.assertNotIn("stopped", json.dumps(task))
        self.assert_current_schema()

    def test_unknown_platform_observation_keeps_bound_and_first_receipt(self):
        prepared, target = self.bind()
        result = lifecycle.record_platform_observation(
            self.session_id,
            self.identity(prepared, target, status="unknown"),
            state_store=self.store,
            now=103,
        )
        self.assertEqual(result["result"], "unknown_recorded")
        task = self.task()
        self.assertEqual(task["phase"], "bound")
        self.assertEqual(
            task["unknown_facts"],
            {"platform_observation_unknown": {"observed_at": 103}},
        )
        self.assertNotIn("platform_observation", task)
        replay = lifecycle.record_platform_observation(
            self.session_id,
            self.identity(prepared, target, status="unknown"),
            state_store=self.store,
            now=999,
        )
        self.assertEqual(replay["result"], "already_unknown")
        self.assertEqual(self.task()["updated_at"], 103)
        self.assert_current_schema()

    def test_normal_call_success_and_failed_are_zero_write_unknown_is_retained(self):
        prepared, target = self.bind()
        state_path = next((self.root / "sessions").glob("*.json"))
        before = state_path.read_bytes()
        for result_name in ("success", "failed"):
            result = lifecycle.record_call_result(
                self.session_id,
                self.identity(prepared, target, result=result_name),
                state_store=self.store,
                now=103,
            )
            self.assertEqual(result["result"], result_name)
            self.assertFalse(result["persisted"])
            self.assertEqual(state_path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "字段"):
            lifecycle.record_call_result(
                self.session_id,
                self.identity(
                    prepared,
                    target,
                    result="success",
                    message="must not be accepted",
                ),
                state_store=self.store,
                now=103,
            )
        unknown = lifecycle.record_call_result(
            self.session_id,
            self.identity(prepared, target, result="unknown"),
            state_store=self.store,
            now=104,
        )
        self.assertEqual(unknown["result"], "unknown_recorded")
        task = self.task()
        self.assertEqual(task["unknown_facts"], {"delivery_unknown": {"observed_at": 104}})
        self.assertNotIn("message", json.dumps(task))
        self.assert_current_schema()

    def test_terminal_notification_uses_exact_sender_and_is_idempotent(self):
        prepared, target = self.bind()
        request = {
            "task_id": prepared["task_id"],
            "task_ref": prepared["task_ref"],
            "sender": target,
            "status": "completed",
        }
        with self.assertRaisesRegex(StateConflictError, "target"):
            lifecycle.record_terminal_notification(
                self.session_id,
                {**request, "sender": "/root/other-sender"},
                state_store=self.store,
                now=103,
            )
        first = lifecycle.record_terminal_notification(
            self.session_id, request, state_store=self.store, now=103
        )
        replay = lifecycle.record_terminal_notification(
            self.session_id, request, state_store=self.store, now=999
        )
        self.assertEqual(first["result"], "terminal")
        self.assertEqual(replay["result"], "already_terminal")
        self.assertEqual(
            self.task()["terminal_fact"],
            {"source": "notification", "status": "completed", "observed_at": 103},
        )
        self.assertNotIn("body", json.dumps(self.task()))
        self.assert_current_schema()

    def test_interrupt_failed_fact_inactive_terminal_and_unknown_receipt(self):
        failed_prepared, failed_target = self.bind("interrupt-failed")
        failed = lifecycle.record_interrupt_result(
            self.session_id,
            self.identity(failed_prepared, failed_target, result="failed"),
            state_store=self.store,
            now=103,
        )
        self.assertEqual(failed["result"], "failed")
        self.assertEqual(self.task("interrupt-failed")["phase"], "bound")
        self.assertEqual(
            self.task("interrupt-failed")["interrupt_fact"],
            {"result": "failed", "observed_at": 103},
        )

        inactive_prepared, inactive_target = self.bind("interrupt-inactive")
        request = self.identity(inactive_prepared, inactive_target, result="inactive")
        first = lifecycle.record_interrupt_result(
            self.session_id, request, state_store=self.store, now=104
        )
        replay = lifecycle.record_interrupt_result(
            self.session_id, request, state_store=self.store, now=999
        )
        self.assertEqual(first["result"], "terminal")
        self.assertEqual(replay["result"], "already_terminal")
        inactive = self.task("interrupt-inactive")
        self.assertEqual(
            inactive["interrupt_fact"],
            {"result": "inactive", "observed_at": 104},
        )
        self.assertEqual(
            inactive["terminal_fact"],
            {"source": "interrupt", "status": "inactive", "observed_at": 104},
        )

        unknown_prepared, unknown_target = self.bind("interrupt-unknown")
        unknown = lifecycle.record_interrupt_result(
            self.session_id,
            self.identity(unknown_prepared, unknown_target, result="unknown"),
            state_store=self.store,
            now=105,
        )
        self.assertEqual(unknown["result"], "unknown_recorded")
        self.assertEqual(
            self.task("interrupt-unknown")["unknown_facts"],
            {"interrupt_unknown": {"observed_at": 105}},
        )
        self.assertNotIn("interrupt_fact", self.task("interrupt-unknown"))
        self.assert_current_schema()

    def test_parent_close_shrinks_capability_and_lazily_prunes_old_closed_tasks(self):
        first = self.prepare("closed-000", now=100)
        close_request = {
            "task_id": first["task_id"],
            "task_ref": first["task_ref"],
            "reason": "parent_accepted",
        }
        closed = lifecycle.close_task(
            self.session_id, close_request, state_store=self.store, now=101
        )
        replay = lifecycle.close_task(
            self.session_id, close_request, state_store=self.store, now=999
        )
        self.assertEqual(closed["result"], "closed")
        self.assertEqual(replay["result"], "already_closed")
        self.assertNotIn("prepared", self.task("closed-000"))
        self.assertEqual(self.task("closed-000")["updated_at"], 101)

        for index in range(1, semantics.CLOSED_TASK_RETENTION + 2):
            task_id = f"closed-{index:03d}"
            prepared = self.prepare(task_id, now=100 + index * 2)
            lifecycle.close_task(
                self.session_id,
                {
                    "task_id": task_id,
                    "task_ref": prepared["task_ref"],
                    "reason": "parent_accepted",
                },
                state_store=self.store,
                now=101 + index * 2,
            )
        tasks = self.store.read(self.session_id)["tasks"]
        self.assertEqual(len(tasks), semantics.CLOSED_TASK_RETENTION)
        self.assertNotIn("closed-000", tasks)
        self.assertIn(
            f"closed-{semantics.CLOSED_TASK_RETENTION + 1:03d}", tasks
        )
        self.assert_current_schema()

    def test_status_derives_next_action_and_projects_only_minimal_facts(self):
        prepared, target = self.bind()
        lifecycle.record_platform_observation(
            self.session_id,
            self.identity(prepared, target, status="error"),
            state_store=self.store,
            now=103,
        )
        current = diagnostics.status(self.session_id, self.root)["tasks"][0]
        self.assertEqual(current["next_action"], "observe_exact_target")
        self.assertEqual(current["platform_status"], "error")
        self.assertIsNone(current["terminal_status"])
        self.assertIsNone(current["reconcile_reason"])
        self.assertNotIn("contract", current)
        self.assertNotIn("message", current)

    def test_lifecycle_nested_records_are_closed_in_runtime_and_schema(self):
        prepared, target = self.bind()
        lifecycle.record_interrupt_result(
            self.session_id,
            self.identity(prepared, target, result="failed"),
            state_store=self.store,
            now=103,
        )
        baseline = self.store.read(self.session_id)
        schema = semantics.MACHINE_SEMANTICS["$defs"]["session_ledger"]
        mutations = (
            lambda task: task["interrupt_fact"].update(response="opaque"),
            lambda task: task["interrupt_fact"].update(result="unknown"),
            lambda task: task.update(platform_observation={"status": "future", "observed_at": 104}),
        )
        for mutate in mutations:
            value = copy.deepcopy(baseline)
            mutate(value["tasks"][prepared["task_id"]])
            self.assertTrue(state_domain.validate_current_state_format(value))
            self.assertTrue(
                validate_instance(
                    value, schema, root_schema=semantics.MACHINE_SEMANTICS
                )
            )


if __name__ == "__main__":
    unittest.main()
