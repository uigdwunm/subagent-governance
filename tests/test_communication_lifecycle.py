#!/usr/bin/env python3

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import governance_contracts as contracts
from scripts import governance_dispatch as dispatch
from scripts import governance_dispatch_identity as identity
from scripts import governance_execution as execution_domain
from scripts import governance_lifecycle as lifecycle_domain
from scripts import governance_errors as errors
from scripts import governance_semantics as semantics
from scripts import governance_platform as platform
from tests.support import load_governance

governance = load_governance("communication")


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
        contract = contracts.contract_from_input(self.contract())
        task_ref = identity.derive_task_ref(task_id, 1, 12)
        container = dispatch.initial_task_record(
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
        )
        execution_domain.apply_canonical_execution_update(execution, "observed_execution_status", "running")
        execution_domain.apply_canonical_execution_update(execution, "closure_parent_action", "wait")
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
            semantics.OPERATION_NATIVE_TOOLS,
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
            platform.adapt_lifecycle_response({"status": "failed"}, "platform_recovery").to_record(),
            {"call_observation": "failed", "target_observation": None},
        )
        self.assertEqual(
            platform.adapt_lifecycle_response(
                {"previous_status": "running"}, "interrupt"
            ).to_record(),
            {
                "call_observation": "success",
                "target_observation": "previously_running",
            },
        )

    def test_lifecycle_record_omits_duplicate_execution_fields(self):
        lifecycle = lifecycle_domain._last_lifecycle_from_pending(
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

    def test_normal_message_post_receipt_uses_claimed_operation_type(self):
        task_id, target = self.add_managed()
        prepared = governance.prepare_communication(
            self.communication("normal_message", target), self.session_id,
            state_store=self.store, now=110,
        )
        governance.handle(
            {"session_id": self.session_id, "hook_event_name": "PreToolUse", "tool_name": "send_message", "tool_use_id": "normal-post", "tool_input": prepared["native_args"], "now": 111}, self.store,
        )
        self.assertIsNone(governance.handle(
            {"session_id": self.session_id, "hook_event_name": "PostToolUse", "tool_name": "send_message", "tool_use_id": "normal-post", "tool_response": {"success": True}, "now": 112}, self.store,
        ))
        record = self.execution(task_id)
        self.assertNotIn("pending_action", record)
        self.assertEqual(record["post_receipt"]["operation_type"], "normal_message")
        self.assertEqual(record["post_receipt"]["tool_family"], "communication")

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
                    record = execution_domain.task_record_for_attempt(current, task_id, 1)
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
        self.assertIn(f"task_id：{task_id}", prepared["message"])
        self.assertIn("attempt：2", prepared["message"])
        self.assertIn(f"target：{target}", prepared["message"])

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
        source = task["executions"]["1"]
        resumed = task["executions"]["2"]
        self.assertTrue(execution_domain.execution_is_closed(source))
        self.assertEqual(source["closure_record"]["reason"], "business_resume")
        self.assertEqual(resumed["dispatch_record"]["dispatch_target"], target)
        self.assertEqual(resumed["dispatch_record"]["tool_use_id"], "resume-tool")
        self.assertEqual(resumed["dispatch_record"]["dispatch_state"], "claimed")
        self.assertEqual(
            self.store.read(self.session_id)["agents"][target],
            {"task_id": task_id, "attempt": 2},
        )
        self.assertEqual(resumed["task_name"], None)
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
        self.assertEqual(
            task["executions"]["2"]["pending_action"]["resume_contract_digest"],
            contracts.contract_digest(contracts.contract_from_input(self.contract("继续执行"))),
        )
        self.assertNotIn("resume_task_ref", task["executions"]["2"]["pending_action"])
        self.assertNotIn("task_id", task["executions"]["2"]["pending_action"])
        self.assertNotIn("reason", task["executions"]["2"]["pending_action"])

    def test_followup_post_receipt_closes_current_resume_only_once(self):
        task_id, target = self.add_managed()
        self.notify(task_id, target)
        prepared = governance.prepare_communication(
            self.communication("business_resume", target, task_contract=self.contract("继续执行")),
            self.session_id, state_store=self.store, now=160,
        )
        governance.handle(
            {
                "session_id": self.session_id, "hook_event_name": "PreToolUse",
                "tool_name": "followup_task", "tool_use_id": "resume-post-tool",
                "tool_input": prepared["native_args"], "now": 161,
            }, self.store,
        )

        result = governance.handle(
            {
                "session_id": self.session_id, "hook_event_name": "PostToolUse",
                "tool_name": "followup_task", "tool_use_id": "resume-post-tool",
                "tool_response": "", "now": 162,
            }, self.store,
        )
        self.assertIsNone(result)
        source = self.execution(task_id, 1)
        resumed = self.execution(task_id, 2)
        self.assertTrue(execution_domain.execution_is_closed(source))
        self.assertEqual(resumed["dispatch_record"]["dispatch_state"], "acknowledged")
        self.assertNotIn("pending_action", resumed)
        self.assertEqual(
            resumed["post_receipt"],
            {
                "session_id": self.session_id, "task_id": task_id, "attempt": 2,
                "task_ref": resumed["task_ref"], "target": target,
                "expected_tool_use_id": "resume-post-tool",
                "received_tool_use_id": "resume-post-tool", "id_match": True,
                "tool_family": "followup", "tool_name_classification": "recognized",
                "operation_type": "business_resume", "response_shape": "empty",
                "processing_result": "success", "target_observation": None,
                "transition_state": "transition_applied",
                "recorded_at": 162,
            },
        )
        before = copy.deepcopy(self.store.read(self.session_id))
        self.assertIsNone(governance.handle(
            {
                "session_id": self.session_id, "hook_event_name": "PostToolUse",
                "tool_name": "followup_task", "tool_use_id": "resume-post-tool",
                "tool_response": "", "now": 163,
            }, self.store,
        ))
        self.assertEqual(self.store.read(self.session_id), before)

    def test_unknown_post_tool_name_with_exact_claimed_id_records_unrecognized_receipt(self):
        task_id, target = self.add_managed()
        self.notify(task_id, target)
        prepared = governance.prepare_communication(
            self.communication("business_resume", target, task_contract=self.contract("继续执行")),
            self.session_id, state_store=self.store, now=160,
        )
        governance.handle(
            {
                "session_id": self.session_id, "hook_event_name": "PreToolUse",
                "tool_name": "followup_task", "tool_use_id": "changed-name-post",
                "tool_input": prepared["native_args"], "now": 161,
            }, self.store,
        )
        unknown_name = "collaboration.future_post_event"
        payload = {
            "session_id": self.session_id, "hook_event_name": "PostToolUse",
            "tool_name": unknown_name, "tool_use_id": "changed-name-post",
            "tool_response": "", "now": 162,
        }
        self.assertIsNotNone(lifecycle_domain.claimed_post_index_lookup(payload, self.store))
        self.assertIsNone(governance.handle(payload, self.store))
        receipt = self.execution(task_id, 2)["post_receipt"]
        self.assertEqual(receipt["tool_name_classification"], "unrecognized")
        self.assertEqual(receipt["operation_type"], "business_resume")
        self.assertIsNone(lifecycle_domain.claimed_post_index_lookup(payload, self.store))
        self.assertNotIn(unknown_name, str(self.store.read(self.session_id)))

    def test_receipt_first_transition_failure_is_recovered_by_duplicate_post(self):
        task_id, target = self.add_managed()
        self.notify(task_id, target)
        prepared = governance.prepare_communication(
            self.communication("business_resume", target, task_contract=self.contract("继续执行")),
            self.session_id, state_store=self.store, now=160,
        )
        pre = {
            "session_id": self.session_id, "hook_event_name": "PreToolUse",
            "tool_name": "followup_task", "tool_use_id": "recover-transition",
            "tool_input": prepared["native_args"], "now": 161,
        }
        governance.handle(pre, self.store)
        post = {
            "session_id": self.session_id, "hook_event_name": "PostToolUse",
            "tool_name": "followup_task", "tool_use_id": "recover-transition",
            "tool_response": "", "now": 162,
        }
        with mock.patch.object(lifecycle_domain, "_apply_action_observation", side_effect=RuntimeError("transition disk failure")):
            failed = governance.handle(post, self.store)
        self.assertTrue(failed["continue"])
        self.assertIn("post_receipt_transition_failed", failed["systemMessage"])
        recorded = self.execution(task_id, 2)
        self.assertEqual(recorded["post_receipt"]["transition_state"], "transition_failed")
        self.assertEqual(recorded["pending_action"]["phase"], "claimed")
        self.assertEqual(recorded["closure_record"]["parent_action"], "reconcile")
        self.assertIsNone(governance.handle(post, self.store))
        recovered = self.execution(task_id, 2)
        self.assertEqual(recovered["post_receipt"]["transition_state"], "transition_applied")
        self.assertNotIn("pending_action", recovered)

    def test_completed_post_duplicate_is_inert_after_transition(self):
        task_id, target = self.add_managed()
        prepared = governance.prepare_communication(
            self.communication("normal_message", target), self.session_id,
            state_store=self.store, now=110,
        )
        governance.handle(
            {"session_id": self.session_id, "hook_event_name": "PreToolUse", "tool_name": "send_message", "tool_use_id": "completed-duplicate", "tool_input": prepared["native_args"], "now": 111}, self.store,
        )
        post = {"session_id": self.session_id, "hook_event_name": "PostToolUse", "tool_name": "send_message", "tool_use_id": "completed-duplicate", "tool_response": {"success": True}, "now": 112}
        self.assertIsNone(governance.handle(post, self.store))
        before = self.store.read(self.session_id)
        self.assertIsNone(governance.handle({**post, "now": 113}, self.store))
        self.assertEqual(self.store.read(self.session_id), before)

    def test_followup_post_missing_or_different_id_never_guesses_pending(self):
        task_id, target = self.add_managed()
        task_ref = self.execution(task_id)["task_ref"]
        # Construct a claimed pending directly to isolate the Post ID binding
        # boundary from preparation policy.
        self.store.update(self.session_id, lambda state: state["tasks"][task_id]["executions"]["1"].update({
            "pending_action": lifecycle_domain._pending_action_record(
                target=target, attempt=1, task_ref=task_ref,
                operation_type="business_resume", created_at=111,
                resume_contract=contracts.contract_from_input(self.contract()),
                resume_context_verification={"mode": "none"}, prepared_on_attempt=1,
            )
        }))
        self.store.update(self.session_id, lambda state: state["tasks"][task_id]["executions"]["1"]["pending_action"].update({"phase": "claimed", "tool_use_id": "expected-followup", "claimed_at": 112}))
        for tool_use_id in ("different-followup", ""):
            with self.subTest(tool_use_id=tool_use_id):
                result = governance.handle(
                    {"session_id": self.session_id, "hook_event_name": "PostToolUse", "tool_name": "followup_task", "tool_use_id": tool_use_id, "tool_response": "", "now": 113}, self.store,
                )
                self.assertIsNone(result)
                pending = self.execution(task_id)["pending_action"]
                self.assertEqual(pending["tool_use_id"], "expected-followup")
                self.assertNotIn("post_receipt", self.execution(task_id))

    def test_followup_post_write_failure_is_degraded_without_false_receipt(self):
        task_id, target = self.add_managed()
        task_ref = self.execution(task_id)["task_ref"]
        self.store.update(self.session_id, lambda state: state["tasks"][task_id]["executions"]["1"].update({
            "pending_action": {
                **lifecycle_domain._pending_action_record(
                    target=target, attempt=1, task_ref=task_ref,
                    operation_type="business_resume", created_at=111,
                    resume_contract=contracts.contract_from_input(self.contract()),
                    resume_context_verification={"mode": "none"}, prepared_on_attempt=1,
                ),
                "phase": "claimed", "tool_use_id": "write-failure", "claimed_at": 112,
            }
        }))
        with mock.patch.object(self.store, "compare_and_set", side_effect=errors.StateWriteError("disk full")):
            result = governance.handle(
                {"session_id": self.session_id, "hook_event_name": "PostToolUse", "tool_name": "followup_task", "tool_use_id": "write-failure", "tool_response": "", "now": 113}, self.store,
            )
        self.assertTrue(result["continue"])
        self.assertIn("post_receipt_write_failed", result["systemMessage"])
        self.assertIn("pending_action", self.execution(task_id))
        self.assertNotIn("post_receipt", self.execution(task_id))
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
        (workspace / "docs" / "context.md").write_text(
            "prepared\n",
            encoding="utf-8",
        )
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
                changed["health"]["status"] = "unavailable"
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
            result["hookSpecificOutput"]["permissionDecision"], "allow"
        )
        state = self.store.read(self.session_id)
        self.assertEqual(state["health"]["status"], "unavailable")
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
            execution_domain.apply_canonical_execution_update(record, "observed_execution_status", "stopped")
            execution_domain.apply_canonical_execution_update(record, "observed_platform_state", "error")
            execution_domain.apply_canonical_execution_update(record, "closure_parent_action", "recover")

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
            execution_domain.apply_canonical_execution_update(
                record, "closure_parent_action", "reconcile"
            )
            record["updated_at"] = 140

        self.store.update(self.session_id, mark_reconciliation_state)
        observation = {
            "task_id": task_id,
            "attempt": 1,
        }

        with self.assertRaisesRegex(errors.ReconciliationError, "unknown=thread_id"):
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
        self.assertEqual(execution_domain.parent_action(record), "decide_disposition")
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
            execution_domain.apply_canonical_execution_update(record, "observed_execution_status", "stopped")
            execution_domain.apply_canonical_execution_update(record, "observation_source", "list_agents")
            execution_domain.apply_canonical_execution_update(record, "observation_summary", "completed")
            execution_domain.apply_canonical_execution_update(record, "observation_observed_at", 140)
            execution_domain.apply_canonical_execution_update(record, "closure_parent_action", "reconcile")

        self.store.update(self.session_id, persist_terminal)
        record = self.execution(task_id)
        self.assertNotIn("closure_state", record["closure_record"])
        self.assertEqual(execution_domain.execution_status(record), "stopped")
        self.assertEqual(execution_domain.parent_action(record), "reconcile")

if __name__ == "__main__":
    unittest.main()
