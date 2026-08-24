#!/usr/bin/env python3

import copy
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_communication_v5", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class CommunicationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.store = governance.StateStore(root / "sessions")
        self.session_id = "communication-v5"

    @staticmethod
    def contract(current_state=None):
        return {
            "semantic_name": "communication_task",
            "requested_mode": "standard",
            "task_features": {
                "risk": "medium",
                "read_only": False,
                "writes_files": True,
                "destructive": False,
                "production": False,
                "concurrent_write": False,
            },
            "objective": "完成通信与生命周期状态机验证",
            "background": "notification-only lifecycle test",
            "work_scope": ["当前测试工作区"],
            "forbidden_scope": ["formal result persistence"],
            "completion_conditions": ["相关状态转换通过测试"],
            "evidence_requirements": ["单元测试结果"],
            "relevant_files": ["scripts/subagent_governance.py"],
            "context_manifest": {"mode": "none"},
            "current_state": current_state,
            "model": None,
            "reasoning_effort": None,
            "context_strategy": "isolated",
            "context_turns": None,
            "context_reason": None,
        }

    @staticmethod
    def communication(operation_type, target, **overrides):
        value = {
            "target": target,
            "operation_type": operation_type,
            "purpose": "继续原治理任务",
            "reason": "需要验证当前生命周期边界",
            "content": "请按当前目标继续，并报告实际状态。",
            "expected_result": "返回验证证据和剩余事项",
        }
        value.update(overrides)
        return value

    def add_managed(self, task_id="communication-task", target="/root/communication"):
        contract = governance._contract_from_input(self.contract())
        task_ref = governance.derive_task_ref(task_id, 1, 12)
        container = governance._initial_task_record(
            1,
            task_ref,
            f"sg_standard_communication_task_t_{task_ref}",
            contract,
            100,
        )
        execution = container["executions"]["1"]
        execution["dispatch_record"].update(
            dispatch_state="acknowledged",
            dispatch_target=target,
            tool_use_id="spawn-tool",
            claimed_at=101,
        )
        governance._apply_canonical_execution_update(execution, "observed_execution_status", "running")
        governance._apply_canonical_execution_update(execution, "closure_parent_action", "wait")
        state = governance.StateStore._empty_state(self.session_id)
        state["tasks"][task_id] = container
        state["agents"][target] = {"task_id": task_id, "attempt": 1}
        self.store.update(self.session_id, lambda current: current.update(state))
        return task_id, target

    def execution(self, task_id, attempt=1):
        return self.store.read(self.session_id)["tasks"][task_id]["executions"][str(attempt)]

    def notify(self, task_id, target, status="completed", now=150):
        return governance.record_terminal_notification(
            {
                "sender_target": target,
                "task_id": task_id,
                "attempt": 1,
                "terminal_status": status,
            },
            self.session_id,
            state_store=self.store,
            now=now,
        )

    def test_supported_operation_types_have_native_tools(self):
        self.assertEqual(
            governance.OPERATION_NATIVE_TOOLS,
            {
                "normal_message": "send_message",
                "platform_recovery": "followup_task",
                "business_resume": "followup_task",
                "interrupt": "interrupt_agent",
            },
        )

    def test_interrupt_requires_only_exact_target(self):
        task_id, target = self.add_managed()
        prepared = governance.prepare_interrupt(
            {"target": target},
            self.session_id,
            state_store=self.store,
            now=110,
        )
        self.assertEqual(prepared["native_tool"], "interrupt_agent")
        self.assertEqual(prepared["native_args"], {"target": target})
        self.assertEqual(prepared["user_message"], f"【子 Agent 中断】\n对象：{target}")

        allowed = governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "PreToolUse",
                "tool_name": "interrupt_agent",
                "tool_use_id": "interrupt-tool",
                "tool_input": prepared["native_args"],
                "now": 111,
            },
            self.store,
        )
        self.assertEqual(
            allowed["hookSpecificOutput"]["permissionDecision"], "allow"
        )
        pending = self.execution(task_id)["pending_action"]
        self.assertEqual(pending["operation_type"], "interrupt")
        self.assertEqual(pending["phase"], "claimed")
        self.assertEqual(pending["tool_use_id"], "interrupt-tool")

    def test_call_response_keeps_only_semantic_observations(self):
        self.assertEqual(
            governance.adapt_call_response({"status": "failed"}, "platform_recovery"),
            {"call_observation": "failed", "target_observation": None},
        )
        self.assertEqual(
            governance.adapt_call_response(
                {"previous_status": "running"}, "interrupt"
            ),
            {
                "call_observation": "success",
                "target_observation": "previously_running",
            },
        )

    def test_lifecycle_record_omits_duplicate_execution_fields(self):
        lifecycle = governance._last_lifecycle_from_pending(
            {
                "operation_type": "interrupt",
                "target": "/root/communication",
                "tool_use_id": "interrupt-tool",
            },
            {
                "call_observation": "unknown",
                "target_observation": None,
            },
        )

        self.assertEqual(
            lifecycle,
            {
                "operation_type": "interrupt",
                "tool_use_id": "interrupt-tool",
                "call_observation": "unknown",
            },
        )

    def test_normal_message_prepares_and_claims_exact_pending_action(self):
        task_id, target = self.add_managed()
        prepared = governance.prepare_communication(
            self.communication("normal_message", target),
            self.session_id,
            state_store=self.store,
            now=110,
        )
        self.assertEqual(prepared["native_tool"], "send_message")
        self.assertNotIn(task_id, prepared["message"])
        self.assertIn("需要验证当前生命周期边界", prepared["message"])

        claimed = governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "PreToolUse",
                "tool_name": "send_message",
                "tool_use_id": "message-tool",
                "tool_input": prepared["native_args"],
                "now": 111,
            },
            self.store,
        )
        self.assertEqual(claimed["hookSpecificOutput"]["permissionDecision"], "allow")
        pending = self.execution(task_id)["pending_action"]
        self.assertNotIn("start_observed_at", pending)
        self.assertEqual(pending["phase"], "claimed")
        self.assertEqual(pending["tool_use_id"], "message-tool")
        self.assertNotIn("expires_at", pending)
        self.assertNotIn("reason", pending)
        self.assertNotIn("authorized_recovery", pending)

    def test_prepared_pending_expiry_derives_from_created_at(self):
        task_id, target = self.add_managed()
        prepared = governance.prepare_communication(
            self.communication("normal_message", target),
            self.session_id,
            state_store=self.store,
            now=100,
        )

        denied = governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "PreToolUse",
                "tool_name": "send_message",
                "tool_use_id": "expired-message-tool",
                "tool_input": prepared["native_args"],
                "now": 400,
            },
            self.store,
        )
        self.assertEqual(
            denied["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.assertNotIn("pending_action", self.execution(task_id))

        governance.prepare_communication(
            self.communication("normal_message", target),
            self.session_id,
            state_store=self.store,
            now=500,
        )
        self.assertEqual(
            governance.reconcile_pending_actions(
                self.session_id, state_store=self.store, now=799
            ),
            {"expired": 0, "reconciled": 0},
        )
        self.assertIn("pending_action", self.execution(task_id))
        self.assertEqual(
            governance.reconcile_pending_actions(
                self.session_id, state_store=self.store, now=800
            ),
            {"expired": 1, "reconciled": 0},
        )
        self.assertNotIn("pending_action", self.execution(task_id))

    def test_expired_pending_cleanup_does_not_delete_concurrent_claim(self):
        task_id, target = self.add_managed()
        prepared = governance.prepare_communication(
            self.communication("normal_message", target),
            self.session_id,
            state_store=self.store,
            now=100,
        )
        original_read = self.store.read
        original_compare_and_set = self.store.compare_and_set
        injected = False

        def read_then_claim(session_id, **kwargs):
            nonlocal injected
            snapshot = original_read(session_id, **kwargs)
            if not injected:
                injected = True

                def claim(current):
                    record = governance._task_record_for_attempt(current, task_id, 1)
                    assert record is not None
                    pending = record["pending_action"]
                    pending["phase"] = "claimed"
                    pending["tool_use_id"] = "racing-tool"
                    pending["claimed_at"] = 399

                original_compare_and_set(
                    session_id,
                    lambda current: True,
                    claim,
                )
            return snapshot

        with mock.patch.object(self.store, "read", side_effect=read_then_claim):
            denied = governance.handle(
                {
                    "session_id": self.session_id,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "send_message",
                    "tool_use_id": "expired-tool",
                    "tool_input": prepared["native_args"],
                    "now": 400,
                },
                self.store,
            )

        self.assertEqual(
            denied["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        pending = self.execution(task_id)["pending_action"]
        self.assertEqual(pending["phase"], "claimed")
        self.assertEqual(pending["tool_use_id"], "racing-tool")

    def test_result_correction_is_rejected_at_input_boundary(self):
        _task_id, target = self.add_managed()
        with self.assertRaises(governance.CommunicationPreparationError):
            governance.prepare_communication(
                self.communication("result_correction", target),
                self.session_id,
                state_store=self.store,
            )

    def test_business_resume_requires_terminal_notification(self):
        task_id, target = self.add_managed()
        value = self.communication(
            "business_resume",
            target,
            task_contract=self.contract("父 Agent 决定继续"),
        )
        with self.assertRaises(governance.CommunicationPreparationError):
            governance.prepare_communication(
                value,
                self.session_id,
                state_store=self.store,
            )

        self.notify(task_id, target)
        prepared = governance.prepare_communication(
            value,
            self.session_id,
            state_store=self.store,
            now=160,
        )
        self.assertEqual(prepared["operation_type"], "business_resume")
        self.assertNotIn("TaskResult", prepared["message"])

    def test_business_resume_claim_creates_next_attempt(self):
        task_id, target = self.add_managed()
        self.notify(task_id, target)
        prepared = governance.prepare_communication(
            self.communication(
                "business_resume",
                target,
                task_contract=self.contract("继续执行"),
            ),
            self.session_id,
            state_store=self.store,
            now=160,
        )
        result = governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "resume-tool",
                "tool_input": prepared["native_args"],
                "now": 161,
            },
            self.store,
        )
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        task = self.store.read(self.session_id)["tasks"][task_id]
        self.assertEqual(task["work_item"]["current_attempt"], 2)
        self.assertNotIn("last_growth_authorization", task["work_item"])
        self.assertNotIn("dispatch_kind", task["executions"]["2"])
        self.assertNotIn("transition", task["executions"]["2"])
        self.assertNotIn("growth_authorization", task["executions"]["2"])
        self.assertNotIn("deliverable_contract", task["executions"]["2"])
        self.assertEqual(task["executions"]["2"]["pending_action"]["tool_use_id"], "resume-tool")
        self.assertNotIn(
            "growth_authorization", task["executions"]["2"]["pending_action"]
        )
        self.assertNotIn(
            "deliverable_contract", task["executions"]["2"]["pending_action"]
        )
        self.assertNotIn("transition", task["executions"]["2"]["pending_action"])
        self.assertNotIn(
            "authorized_recovery", task["executions"]["2"]["pending_action"]
        )
        self.assertNotIn(
            "deliverable_contract_digest", task["executions"]["2"]["pending_action"]
        )
        self.assertNotIn(
            "resume_contract_summary", task["executions"]["2"]["pending_action"]
        )
        self.assertNotIn(
            "resume_contract_digest", task["executions"]["2"]["pending_action"]
        )
        self.assertNotIn("resume_task_ref", task["executions"]["2"]["pending_action"])
        self.assertNotIn("task_id", task["executions"]["2"]["pending_action"])
        self.assertNotIn("reason", task["executions"]["2"]["pending_action"])

    def test_business_resume_rechecks_working_tree_context_before_claim(self):
        task_id, target = self.add_managed()
        self.notify(task_id, target)
        workspace = Path(self.temporary.name) / "resume-workspace"
        workspace.mkdir()
        context_file = workspace / "context.md"
        context_file.write_text("prepared\n", encoding="utf-8")
        contract = self.contract("继续执行")
        contract["context_manifest"] = {
            "mode": "declared",
            "workspace_root": str(workspace),
            "baseline": {"kind": "working_tree", "revision": None},
            "required_paths": [{"path": "context.md", "type": "file"}],
        }
        prepared = governance.prepare_communication(
            self.communication(
                "business_resume",
                target,
                task_contract=contract,
            ),
            self.session_id,
            state_store=self.store,
            now=160,
        )
        context_file.write_text("changed\n", encoding="utf-8")

        result = governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "resume-context-drift",
                "tool_input": prepared["native_args"],
                "now": 161,
            },
            self.store,
        )

        self.assertEqual(
            result["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.assertIn(
            "必需上下文",
            result["hookSpecificOutput"]["permissionDecisionReason"],
        )
        task = self.store.read(self.session_id)["tasks"][task_id]
        self.assertEqual(task["work_item"]["current_attempt"], 1)

    def test_business_resume_rejects_working_tree_directory_before_pending_action(self):
        task_id, target = self.add_managed()
        self.notify(task_id, target)
        workspace = Path(self.temporary.name) / "resume-directory-workspace"
        (workspace / "docs").mkdir(parents=True)
        contract = self.contract("继续执行")
        contract["context_manifest"] = {
            "mode": "declared",
            "workspace_root": str(workspace),
            "baseline": {"kind": "working_tree", "revision": None},
            "required_paths": [{"path": "docs", "type": "directory"}],
        }

        with self.assertRaisesRegex(
            governance.CommunicationPreparationError,
            "working_tree.*directory.*逐文件.*git_commit",
        ):
            governance.prepare_communication(
                self.communication(
                    "business_resume",
                    target,
                    task_contract=contract,
                ),
                self.session_id,
                state_store=self.store,
                now=160,
            )

        task = self.store.read(self.session_id)["tasks"][task_id]
        self.assertNotIn("pending_action", task["executions"]["1"])

    def test_business_resume_claim_persist_then_raise_is_confirmed(self):
        task_id, target = self.add_managed()
        self.notify(task_id, target)
        prepared = governance.prepare_communication(
            self.communication(
                "business_resume",
                target,
                task_contract=self.contract("继续执行"),
            ),
            self.session_id,
            state_store=self.store,
            now=160,
        )
        payload = {
            "session_id": self.session_id,
            "hook_event_name": "PreToolUse",
            "tool_name": "followup_task",
            "tool_use_id": "resume-partial",
            "tool_input": prepared["native_args"],
            "now": 161,
        }
        original_write = self.store._write_path
        write_calls = 0

        def persist_then_report_failure(*args, **kwargs):
            nonlocal write_calls
            write_calls += 1
            result = original_write(*args, **kwargs)
            if write_calls == 1:
                raise governance.StateWriteError(
                    "simulated lifecycle claim readback failure"
                )
            return result

        with mock.patch.object(
            self.store,
            "_write_path",
            side_effect=persist_then_report_failure,
        ):
            result = governance.handle(payload, self.store)

        self.assertEqual(
            result["hookSpecificOutput"]["permissionDecision"], "allow"
        )
        task = self.store.read(self.session_id)["tasks"][task_id]
        self.assertEqual(task["work_item"]["current_attempt"], 2)
        self.assertEqual(
            task["executions"]["2"]["pending_action"]["phase"], "claimed"
        )
        self.assertEqual(
            task["executions"]["2"]["pending_action"]["tool_use_id"],
            "resume-partial",
        )

    def test_lifecycle_claim_failure_preserves_concurrent_state_change(self):
        task_id, target = self.add_managed()
        self.notify(task_id, target)
        prepared = governance.prepare_communication(
            self.communication(
                "business_resume",
                target,
                task_contract=self.contract("继续执行"),
            ),
            self.session_id,
            state_store=self.store,
            now=160,
        )
        payload = {
            "session_id": self.session_id,
            "hook_event_name": "PreToolUse",
            "tool_name": "followup_task",
            "tool_use_id": "resume-diverged",
            "tool_input": prepared["native_args"],
            "now": 161,
        }
        original_write = self.store._write_path
        write_calls = 0

        def persist_change_then_report_failure(*args, **kwargs):
            nonlocal write_calls
            write_calls += 1
            result = original_write(*args, **kwargs)
            if write_calls == 1:
                changed = copy.deepcopy(args[2])
                changed["health"]["concurrent_marker"] = True
                original_write(args[0], args[1], changed, **kwargs)
                raise governance.StateWriteError(
                    "simulated lifecycle claim failure after concurrent change"
                )
            return result

        with mock.patch.object(
            self.store,
            "_write_path",
            side_effect=persist_change_then_report_failure,
        ):
            result = governance.handle(payload, self.store)

        self.assertEqual(
            result["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.assertIn("degraded", str(result))
        state = self.store.read(self.session_id)
        self.assertTrue(state["health"]["concurrent_marker"])
        self.assertEqual(state["tasks"][task_id]["work_item"]["current_attempt"], 2)
        self.assertEqual(
            state["tasks"][task_id]["executions"]["2"]["pending_action"]["phase"],
            "claimed",
        )

    def test_platform_recovery_requires_observation_error_and_consumes_budget_on_claim(self):
        task_id, target = self.add_managed()

        def mark_error(state):
            record = state["tasks"][task_id]["executions"]["1"]
            observation = record["observation_record"]
            observation.update(
                source="list_agents",
                observed_state="error",
                observed_at=120,
            )
            governance._apply_canonical_execution_update(record, "observed_execution_status", "stopped")
            governance._apply_canonical_execution_update(record, "observed_platform_state", "error")
            governance._apply_canonical_execution_update(record, "closure_parent_action", "recover")

        self.store.update(self.session_id, mark_error)
        prepared = governance.prepare_communication(
            self.communication("platform_recovery", target),
            self.session_id,
            state_store=self.store,
            now=130,
        )
        governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "recovery-tool",
                "tool_input": prepared["native_args"],
                "now": 131,
            },
            self.store,
        )
        self.assertEqual(self.execution(task_id)["recovery_count"], 1)

    def test_interrupted_reconciliation_keeps_only_canonical_state(self):
        task_id, target = self.add_managed()

        def mark_reconciliation_state(state):
            record = state["tasks"][task_id]["executions"]["1"]
            record["observation_record"].update(
                source="list_agents",
                observed_state="unknown",
                observed_at=140,
                terminal_status=None,
            )
            record["last_lifecycle_operation"] = {
                "operation_type": "interrupt",
                "tool_use_id": "interrupt-tool",
                "call_observation": "success",
                "target_observation": "not_found",
            }
            governance._apply_canonical_execution_update(
                record, "closure_parent_action", "reconcile"
            )
            record["updated_at"] = 140

        self.store.update(self.session_id, mark_reconciliation_state)
        observation = {
            "task_id": task_id,
            "attempt": 1,
        }

        with self.assertRaisesRegex(governance.ReconciliationError, "unknown=thread_id"):
            governance.reconcile_interrupted_attempt(
                {
                    **observation,
                    "thread_id": "019ff4ef-aac5-77c1-81ef-682411ff1a3f",
                },
                self.session_id,
                state_store=self.store,
                now=150,
            )

        result = governance.reconcile_interrupted_attempt(
            observation,
            self.session_id,
            state_store=self.store,
            now=150,
        )
        self.assertEqual(result["status"], "confirmed_inactive")
        record = self.execution(task_id)
        self.assertEqual(
            record["observation_record"],
            {
                "source": "session",
                "observed_state": "terminal",
                "observed_at": 150,
                "terminal_status": "interrupted",
            },
        )
        self.assertEqual(governance._parent_action(record), "decide_disposition")
        self.assertNotIn("last_lifecycle_operation", record)
        self.assertNotIn("reconciliation_reason", record)
        self.assertNotIn("reconciled_thread_id", record)
        self.assertNotIn("reconciled_thread_status", record)

    def test_terminal_list_fact_waits_for_notification(self):
        task_id, target = self.add_managed()

        def persist_terminal(state):
            record = state["tasks"][task_id]["executions"]["1"]
            record["observation_record"].update(
                source="list_agents",
                observed_state="terminal",
                observed_at=140,
                terminal_status="completed",
            )
            governance._apply_canonical_execution_update(record, "observed_execution_status", "stopped")
            governance._apply_canonical_execution_update(record, "observation_source", "list_agents")
            governance._apply_canonical_execution_update(record, "observation_summary", "completed")
            governance._apply_canonical_execution_update(record, "observation_observed_at", 140)
            governance._apply_canonical_execution_update(record, "closure_parent_action", "reconcile")

        self.store.update(self.session_id, persist_terminal)
        record = self.execution(task_id)
        self.assertNotIn("closure_state", record["closure_record"])
        self.assertEqual(governance._execution_status(record), "stopped")
        self.assertEqual(governance._parent_action(record), "reconcile")

if __name__ == "__main__":
    unittest.main()
