#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

from tests.support import load_governance

from scripts import governance_contracts as contracts
from scripts import governance_dispatch as dispatch
from scripts import governance_dispatch_identity as dispatch_identity
from scripts import governance_execution as execution_module
from scripts import governance_hook as hook
from scripts import governance_lifecycle as lifecycle
from scripts import governance_semantics as semantics
from scripts import governance_state_store as state_store_module
from scripts import governance_views as views


class WaitRecoverySessionClosureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = state_store_module.StateStore(self.root / "sessions")
        self.session_id = "session-v5"

    @staticmethod
    def contract():
        return contracts.TaskContract(
            semantic_name="session_v5",
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
            objective="验证会话恢复与关闭",
            background="notification-only session test",
            work_scope=["session lifecycle"],
            forbidden_scope=["result persistence"],
            completion_conditions=["state remains consistent"],
            evidence_requirements=[],
            relevant_files=[],
            context_manifest={"mode": "none"},
            current_state=None,
            model=None,
            reasoning_effort=None,
            context_strategy="isolated",
            context_turns=None,
            context_reason=None,
        )

    def add_task(self, task_id="session-task", *, attempt=1, target=None, now=100):
        target = target or f"/root/{task_id}-{attempt}"
        ref = dispatch_identity.derive_task_ref(task_id, attempt, 12)
        container = dispatch.initial_task_record(
            attempt,
            ref,
            f"sg_standard_session_v5_t_{ref}",
            self.contract(),
            now,
        )
        execution = container["executions"][str(attempt)]
        execution["dispatch_record"].update(
            dispatch_state="acknowledged",
            dispatch_target=target,
            tool_use_id=f"spawn-{attempt}",
        )
        execution_module.apply_canonical_execution_update(execution, "observed_execution_status", "running")
        execution_module.apply_canonical_execution_update(execution, "closure_parent_action", "wait")

        def add(state):
            state["tasks"][task_id] = container
            state["agents"][target] = {"task_id": task_id, "attempt": attempt}

        self.store.update(self.session_id, add)
        return task_id, target

    def test_machine_semantics_anchor_wait_and_derived_views(self):
        self.assertEqual(semantics.SEMANTIC_RULES["wait_timeout_ms"], 1_200_000)
        self.assertEqual(semantics.SEMANTIC_RULES["stop_read_attempts"], 3)
        self.assertFalse(
            semantics.SEMANTIC_RULES["derived_views"]["action_required"][
                "persisted_on_work_item"
            ]
        )

    def test_running_attempt_is_action_required_and_recent(self):
        task_id, _target = self.add_task(now=state_store_module._now())
        state = self.store.read(self.session_id)
        self.assertEqual(
            [(item["task_id"], item["attempt"]) for item in views.action_required_records(state)],
            [(task_id, 1)],
        )
        recent = views.recent_activity_records(state)
        self.assertEqual(len(recent), 1)
        self.assertNotIn("is_current_attempt", recent[0])

    def test_terminal_notification_is_action_required_until_parent_closes(self):
        task_id, target = self.add_task()
        lifecycle.record_terminal_notification(
            {
                "sender_target": target,
                "task_id": task_id,
                "attempt": 1,
                "terminal_status": "completed",
            },
            self.session_id,
            state_store=self.store,
            now=150,
        )
        state = self.store.read(self.session_id)
        self.assertEqual(
            state["tasks"][task_id]["executions"]["1"]["closure_record"][
                "parent_action"
            ],
            "decide_disposition",
        )
        self.assertEqual(len(views.action_required_records(state)), 1)

        lifecycle.apply_parent_disposition(
            {
                "task_id": task_id,
                "attempt": 1,
                "action": "close_task",
                "reason": "已读取原生通知",
            },
            self.session_id,
            state_store=self.store,
            now=160,
        )
        self.assertEqual(views.action_required_records(self.store.read(self.session_id)), [])

    def test_session_start_summary_uses_notification_view(self):
        task_id, target = self.add_task()
        lifecycle.record_terminal_notification(
            {
                "sender_target": target,
                "task_id": task_id,
                "attempt": 1,
                "terminal_status": "completed",
            },
            self.session_id,
            state_store=self.store,
            now=150,
        )
        result = hook.handle_hook(
            {
                "session_id": self.session_id,
                "hook_event_name": "SessionStart",
                "source": "compact",
            },
            self.store,
        )
        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("notification：observed", context)
        self.assertIn("allowed_actions：close_task", context)
        self.assertNotIn("outcome", context)
        self.assertNotIn("完成条件", context)
        self.assertNotIn("state remains consistent", context)

    def test_session_end_preserves_action_required_state(self):
        self.add_task()
        path, lock_path = self.store._paths(self.session_id)
        result = hook.handle_hook(
            {"session_id": self.session_id, "hook_event_name": "SessionEnd"},
            self.store,
        )
        self.assertTrue(path.exists())
        self.assertTrue(lock_path.exists())
        self.assertIn("仍需恢复或决策", result["systemMessage"])
        self.assertIn("(running)", result["systemMessage"])

    def test_stop_advisory_summary_uses_canonical_execution_status(self):
        self.add_task()
        result = hook.handle_hook(
            {"session_id": self.session_id, "hook_event_name": "Stop"},
            self.store,
        )
        self.assertIn("session-task", result["systemMessage"])
        self.assertIn("(running)", result["systemMessage"])
        self.assertNotIn("(None)", result["systemMessage"])
        self.assertNotIn("(unknown)", result["systemMessage"])

    def test_session_end_deletes_closed_state_but_keeps_lock(self):
        task_id, target = self.add_task()
        lifecycle.record_terminal_notification(
            {
                "sender_target": target,
                "task_id": task_id,
                "attempt": 1,
                "terminal_status": "completed",
            },
            self.session_id,
            state_store=self.store,
            now=150,
        )
        lifecycle.apply_parent_disposition(
            {
                "task_id": task_id,
                "attempt": 1,
                "action": "close_task",
                "reason": "关闭 work item",
            },
            self.session_id,
            state_store=self.store,
            now=160,
        )
        path, lock_path = self.store._paths(self.session_id)
        hook.handle_hook(
            {"session_id": self.session_id, "hook_event_name": "SessionEnd"},
            self.store,
        )
        self.assertFalse(path.exists())
        self.assertTrue(lock_path.exists())

    def test_resume_delivery_failed_remains_action_required_with_close_and_resume(self):
        task_id, _target = self.add_task()
        state = self.store.read(self.session_id)
        execution = state["tasks"][task_id]["executions"]["1"]
        execution_module.apply_canonical_execution_update(
            execution, "observed_execution_status", "stopped"
        )
        execution_module.apply_canonical_execution_update(
            execution, "closure_reason", "resume_delivery_failed"
        )
        execution_module.apply_canonical_execution_update(execution, "closure_closed_at", 150)
        execution_module.apply_canonical_execution_update(
            execution, "closure_parent_action", "decide_disposition"
        )
        self.store.update(self.session_id, lambda current: current.update(state))

        view, issues, incomplete = views.work_item_decision_snapshot(
            self.store.read(self.session_id), task_id, session_id=self.session_id
        )
        self.assertFalse(incomplete, issues)
        self.assertEqual(view["lifecycle"], "open")
        self.assertTrue(view["action_required"])
        self.assertEqual(view["allowed_actions"], ["close_task", "resume_business"])

    def test_session_end_does_not_delete_open_current_closed_resume_failure(self):
        task_id, _target = self.add_task()
        state = self.store.read(self.session_id)
        execution = state["tasks"][task_id]["executions"]["1"]
        execution_module.apply_canonical_execution_update(execution, "observed_execution_status", "stopped")
        execution_module.apply_canonical_execution_update(execution, "closure_reason", "resume_delivery_failed")
        execution_module.apply_canonical_execution_update(execution, "closure_closed_at", 150)
        execution_module.apply_canonical_execution_update(execution, "closure_parent_action", "decide_disposition")
        self.store.update(self.session_id, lambda current: current.update(state))
        path, _lock = self.store._paths(self.session_id)

        hook.handle_hook({"session_id": self.session_id, "hook_event_name": "SessionEnd"}, self.store)

        self.assertTrue(path.exists())

    def test_expired_tombstone_is_removed(self):
        now = state_store_module._now()
        self.store.update(
            self.session_id,
            lambda state: state["tombstones"].update(
                {
                    "closed-task:1": {
                        "task_ref": "0123456789ab",
                        "dispatch_target": None,
                        "close_reason": "parent_closed",
                        "closed_at": now - semantics.RETENTION_SECONDS["tombstone"] - 1,
                    }
                }
            ),
        )
        hook.handle_hook(
            {"session_id": self.session_id, "hook_event_name": "SessionStart"},
            self.store,
        )
        self.assertNotIn(
            "closed-task:1", self.store.read(self.session_id)["tombstones"]
        )

    def test_stop_fails_open_when_store_is_unavailable(self):
        unavailable = state_store_module.UnavailableStateStore(RuntimeError("state unavailable"))
        result = hook.handle_hook(
            {"session_id": self.session_id, "hook_event_name": "Stop"},
            unavailable,
        )
        self.assertTrue(result["continue"])
        self.assertIn("降级放行", result["systemMessage"])


if __name__ == "__main__":
    unittest.main()
