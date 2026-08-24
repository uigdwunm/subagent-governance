#!/usr/bin/env python3

import copy
import tempfile
import unittest
from pathlib import Path

from tests.support import load_governance

from scripts import governance_contracts as contracts
from scripts import governance_dispatch as dispatch
from scripts import governance_dispatch_identity as dispatch_identity
from scripts import governance_errors as errors
from scripts import governance_execution as execution_module
from scripts import governance_lifecycle as lifecycle
from scripts import governance_state_store as state_store_module


class TerminalNotificationChannelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = state_store_module.StateStore(self.root / "sessions")
        self.session_id = "session-terminal-notification"
        self.task_id = "sg-terminal-notification-task"
        self.target = "/root/sg_standard_terminal_notification_t_0123456789ab"
        contract = contracts.TaskContract(
            semantic_name="terminal_notification",
            requested_mode="standard",
            resolved_mode="standard",
            resolution_reason="explicit_request",
            task_features={
                "risk": "medium",
                "read_only": False,
                "writes_files": True,
                "destructive": False,
                "production": False,
                "concurrent_write": False,
            },
            objective="验证终态通知观察",
            background="notification-only state model",
            work_scope=["terminal notification"],
            forbidden_scope=[],
            completion_conditions=["notification observation converges"],
            evidence_requirements=["unit test"],
            relevant_files=[],
            context_manifest={"mode": "none"},
            current_state=None,
            model=None,
            reasoning_effort=None,
            context_strategy="isolated",
            context_turns=None,
            context_reason=None,
        )
        task = dispatch.initial_task_record(
            1,
            dispatch_identity.derive_task_ref(self.task_id, 1, 12),
            "sg_standard_terminal_notification_t_0123456789ab",
            contract,
            100,
        )
        execution = task["executions"]["1"]
        execution_module.apply_canonical_execution_update(
            execution, "dispatch_target", self.target
        )
        execution_module.apply_canonical_execution_update(execution, "observed_execution_status", "running")
        execution_module.apply_canonical_execution_update(execution, "closure_parent_action", "wait")
        self.store.update(
            self.session_id,
            lambda state: (
                state["tasks"].update({self.task_id: task}),
                state["agents"].update(
                    {self.target: {"task_id": self.task_id, "attempt": 1}}
                ),
            ),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def envelope(self, **overrides):
        value = {
            "sender_target": self.target,
            "task_id": self.task_id,
            "attempt": 1,
            "terminal_status": "completed",
        }
        value.update(overrides)
        return value

    def record(self, **overrides):
        return lifecycle.record_terminal_notification(
            self.envelope(**overrides),
            self.session_id,
            state_store=self.store,
            now=200,
        )

    def execution(self):
        return self.store.read(self.session_id)["tasks"][self.task_id]["executions"][
            "1"
        ]

    def test_exact_notification_becomes_sticky_terminal_observation(self):
        result = self.record()
        self.assertEqual(result["status"], "recorded")
        execution = self.execution()
        self.assertEqual(execution_module.execution_status(execution), "stopped")
        self.assertEqual(execution_module.parent_action(execution), "decide_disposition")
        self.assertNotIn("result_record", execution)
        self.assertEqual(
            execution["observation_record"],
            {
                "source": "terminal_notification",
                "observed_state": "terminal",
                "observed_at": 200,
                "terminal_status": "completed",
            },
        )
        self.assertNotIn("closure_state", execution["closure_record"])
        self.assertEqual(execution_module.execution_status(execution), "stopped")
        self.assertEqual(execution_module.parent_action(execution), "decide_disposition")
        self.assertFalse((self.root / "results").exists())

    def test_replay_is_idempotent_and_does_not_change_timestamp(self):
        self.record()
        replayed = lifecycle.record_terminal_notification(
            self.envelope(),
            self.session_id,
            state_store=self.store,
            now=300,
        )
        self.assertEqual(replayed["status"], "idempotent")
        self.assertEqual(self.execution()["observation_record"]["observed_at"], 200)

    def test_wrong_sender_is_rejected_without_state_change(self):
        before = copy.deepcopy(self.store.read(self.session_id))
        with self.assertRaises(errors.NotificationObservationError):
            self.record(sender_target="/root/wrong")
        self.assertEqual(self.store.read(self.session_id), before)

    def test_conflicting_terminal_status_requires_reconciliation(self):
        self.record()
        conflict = lifecycle.record_terminal_notification(
            self.envelope(terminal_status="interrupted"),
            self.session_id,
            state_store=self.store,
            now=300,
        )
        self.assertEqual(conflict["status"], "conflict")
        execution = self.execution()
        self.assertEqual(execution["observation_record"]["terminal_status"], "completed")
        self.assertEqual(execution_module.parent_action(execution), "reconcile")

    def test_notification_allows_parent_to_close_without_business_acceptance(self):
        self.record()
        closed = lifecycle.apply_parent_disposition(
            {
                "task_id": self.task_id,
                "attempt": 1,
                "action": "close_task",
                "reason": "父 Agent 已处理原生终态通知",
            },
            self.session_id,
            state_store=self.store,
            now=300,
        )
        self.assertEqual(closed["status"], "closed")
        task = self.store.read(self.session_id)["tasks"][self.task_id]
        self.assertEqual(task["work_item"]["lifecycle"], "tombstoned")
        closure = task["executions"]["1"]["closure_record"]
        self.assertNotIn("closure_state", closure)
        self.assertTrue(execution_module.execution_is_closed(task["executions"]["1"]))
        self.assertEqual(closure["reason"], "close_task:父 Agent 已处理原生终态通知")
        self.assertNotIn("parent_disposition", closure)
        self.assertNotIn("disposition_recorded_at", closure)
        self.assertNotIn("last_parent_disposition", task["work_item"])
        self.assertNotIn(self.target, self.store.read(self.session_id)["agents"])


if __name__ == "__main__":
    unittest.main()
