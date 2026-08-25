#!/usr/bin/env python3
"""Acceptance coverage for the minimal state-v9 lifecycle slice."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts import governance_lifecycle as lifecycle
from scripts import governance_diagnostics as diagnostics
from scripts import governance_protocol as protocol
from scripts import governance_state as state_domain
from scripts import governance_semantics as semantics
from scripts.governance_errors import StateConflictError
from scripts.governance_hook import handle_hook
from scripts.governance_state_store import StateStore
from tests.schema_validation import validate_instance


class V9LifecycleTests(unittest.TestCase):
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

    def test_unknown_platform_observation_records_only_reconcile_reason(self):
        prepared, target = self.bind()
        result = lifecycle.record_platform_observation(
            self.session_id,
            self.identity(prepared, target, status="unknown"),
            state_store=self.store,
            now=103,
        )
        self.assertEqual(result["result"], "reconcile")
        task = self.task()
        self.assertEqual(task["phase"], "reconcile")
        self.assertEqual(
            task["reconcile"],
            {"code": "platform_observation_unknown", "observed_at": 103},
        )
        self.assertNotIn("platform_observation", task)
        replay = lifecycle.record_platform_observation(
            self.session_id,
            self.identity(prepared, target, status="unknown"),
            state_store=self.store,
            now=999,
        )
        self.assertEqual(replay["result"], "reconcile")
        self.assertEqual(self.task()["updated_at"], 103)
        self.assert_current_schema()

    def test_normal_call_success_and_failed_are_zero_write_unknown_reconciles(self):
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
        self.assertEqual(unknown["result"], "reconcile")
        task = self.task()
        self.assertEqual(task["reconcile"]["code"], "delivery_unknown")
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

    def test_interrupt_failed_fact_inactive_terminal_and_unknown_reconcile(self):
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
        self.assertEqual(unknown["result"], "reconcile")
        self.assertEqual(
            self.task("interrupt-unknown")["reconcile"]["code"],
            "interrupt_unknown",
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
