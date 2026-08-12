#!/usr/bin/env python3

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_wp04", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class CommunicationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = governance.StateStore(self.root / "sessions")

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def contract(**overrides):
        value = {
            "semantic_name": "communication_task",
            "requested_mode": "standard",
            "objective": "完成通信与生命周期状态机验证",
            "background": "WP-04 定向测试。",
            "work_scope": ["当前测试工作区"],
            "forbidden_scope": [],
            "completion_conditions": ["相关状态转换通过测试"],
            "evidence_requirements": ["单元测试结果"],
            "relevant_files": ["scripts/subagent_governance.py"],
            "current_state": None,
            "model": None,
            "reasoning_effort": None,
            "context_strategy": "isolated",
            "context_turns": None,
            "context_reason": None,
        }
        value.update(overrides)
        return value

    @staticmethod
    def communication(operation_type, **overrides):
        value = {
            "target": "agent-wp04",
            "operation_type": operation_type,
            "purpose": "继续原治理任务",
            "reason": "需要验证当前生命周期边界",
            "content": "请按当前目标继续，并返回实际结果。",
            "expected_result": "返回验证证据和剩余事项",
        }
        value.update(overrides)
        return value

    def add_managed(self, **overrides):
        now = governance._now()
        task_id = overrides.pop("task_id", "sg-task-wp04")
        attempt = overrides.pop("attempt", 1)
        target = overrides.pop("target", "agent-wp04")
        record = {
            "managed": True,
            "task_id": task_id,
            "attempt": attempt,
            "task_ref": governance.derive_task_ref(task_id, attempt, 12),
            "task_name": "sg_standard_communication_task_t_"
            + governance.derive_task_ref(task_id, attempt, 12),
            "semantic_name": "communication_task",
            "requested_mode": "standard",
            "resolved_mode": "standard",
            "resolution_reason": "explicit_request",
            "contract_summary": governance._contract_summary(
                governance._contract_from_input(self.contract())
            ),
            **governance.AttemptState().to_record(),
            "identity_status": "confirmed",
            "execution_status": "running",
            "platform_observation": "normal",
            "parent_action": "wait",
            "agent_id": target,
            "canonical_task_path": None,
            "created_at": now,
            "updated_at": now,
        }
        record.update(overrides)

        def add(state):
            state["tasks"][task_id] = record
            state["agents"][target] = {"task_id": task_id, "attempt": attempt}

        self.store.update("session-wp04", add)
        return task_id, target

    def test_generator_keeps_internal_operation_and_task_id_out_of_message(self):
        task_id, target = self.add_managed()
        prepared = governance.prepare_communication(
            self.communication("normal_message", target=target),
            "session-wp04",
            state_store=self.store,
            now=100,
        )

        self.assertIn("【子 Agent 通信】", prepared["user_message"])
        self.assertNotIn(task_id, prepared["message"])
        self.assertNotIn("normal_message", prepared["message"])
        self.assertEqual(prepared["native_args"], {"target": target, "message": prepared["message"]})
        record = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(record["pending_action"]["phase"], "prepared")
        self.assertEqual(record["pending_action"]["operation_type"], "normal_message")

    def test_recovery_budget_is_claimed_before_call_and_failed_does_not_roll_back(self):
        task_id, target = self.add_managed(
            execution_status="stopped",
            platform_observation="error",
            parent_action="recover",
        )
        prepared = governance.prepare_communication(
            self.communication("platform_recovery", target=target),
            "session-wp04",
            state_store=self.store,
        )
        pre = governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "recovery-call-1",
                "tool_input": prepared["native_args"],
            },
            self.store,
        )
        self.assertEqual(pre["hookSpecificOutput"]["permissionDecision"], "allow")
        claimed = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(claimed["recovery_count"], 1)
        self.assertEqual(claimed["pending_action"]["phase"], "claimed")

        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PostToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "recovery-call-1",
                "tool_response": {"isError": True, "status": "failed"},
            },
            self.store,
        )
        record = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(record["recovery_count"], 1)
        self.assertEqual(record["recovery_status"], "awaiting_authorization")
        self.assertEqual(record["parent_action"], "ask_user")
        self.assertNotIn("pending_action", record)

    def test_claimed_action_becomes_unknown_only_after_twenty_minutes(self):
        task_id, target = self.add_managed(
            execution_status="stopped",
            platform_observation="error",
            parent_action="recover",
        )
        prepared = governance.prepare_communication(
            self.communication("platform_recovery", target=target),
            "session-wp04",
            state_store=self.store,
            now=100,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "recovery-timeout",
                "tool_input": prepared["native_args"],
                "now": 110,
            },
            self.store,
        )
        self.assertEqual(
            governance.reconcile_pending_actions("session-wp04", state_store=self.store, now=1309),
            {"expired": 0, "reconciled": 0},
        )
        self.assertEqual(
            governance.reconcile_pending_actions("session-wp04", state_store=self.store, now=1310),
            {"expired": 0, "reconciled": 1},
        )
        record = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(record["parent_action"], "reconcile")
        self.assertEqual(record["last_lifecycle_operation"]["call_observation"], "unknown")

    def test_business_resume_creates_new_attempt_during_pre_tool_claim(self):
        task_id, target = self.add_managed(
            execution_status="stopped",
            business_result="blocked",
            parent_action="decide_disposition",
        )
        value = self.communication(
            "business_resume",
            target=target,
            task_contract=self.contract(current_state="阻塞条件已经解除"),
        )
        prepared = governance.prepare_communication(
            value,
            "session-wp04",
            state_store=self.store,
        )
        before = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(before["attempt"], 1)

        result = governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "resume-call-1",
                "tool_input": prepared["native_args"],
            },
            self.store,
        )
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        current = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(current["attempt"], 2)
        self.assertEqual(current["execution_status"], "not_started")
        self.assertIn("1", current["prior_attempts"])
        self.assertEqual(current["pending_action"]["phase"], "claimed")

    def test_interrupt_unknown_keeps_execution_state_and_requires_reconcile(self):
        task_id, target = self.add_managed()
        prepared = governance.prepare_interrupt(
            self.communication("normal_message", target=target),
            "session-wp04",
            state_store=self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "interrupt_agent",
                "tool_use_id": "interrupt-call-1",
                "tool_input": prepared["native_args"],
            },
            self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PostToolUse",
                "tool_name": "interrupt_agent",
                "tool_use_id": "interrupt-call-1",
                "tool_response": {"status": "running"},
            },
            self.store,
        )
        record = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(record["execution_status"], "running")
        self.assertEqual(record["parent_action"], "reconcile")
        self.assertEqual(record["last_lifecycle_operation"]["operation_type"], "interrupt")
        self.assertEqual(record["last_lifecycle_operation"]["call_observation"], "unknown")

    def test_prepared_action_expires_after_five_minutes_without_consuming_budget(self):
        task_id, target = self.add_managed(
            execution_status="stopped",
            platform_observation="error",
            parent_action="recover",
        )
        governance.prepare_communication(
            self.communication("platform_recovery", target=target),
            "session-wp04",
            state_store=self.store,
            now=100,
        )
        self.assertEqual(
            governance.reconcile_pending_actions("session-wp04", state_store=self.store, now=399),
            {"expired": 0, "reconciled": 0},
        )
        self.assertEqual(
            governance.reconcile_pending_actions("session-wp04", state_store=self.store, now=400),
            {"expired": 1, "reconciled": 0},
        )
        record = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(record["recovery_count"], 0)
        self.assertNotIn("pending_action", record)

    def test_same_target_pending_action_conflicts(self):
        _task_id, target = self.add_managed()
        governance.prepare_communication(
            self.communication("normal_message", target=target),
            "session-wp04",
            state_store=self.store,
        )
        with self.assertRaisesRegex(governance.CommunicationPreparationError, "pending_action"):
            governance.prepare_communication(
                self.communication("normal_message", target=target),
                "session-wp04",
                state_store=self.store,
            )

    def test_normal_message_fail_open_and_all_observations_leave_lifecycle_unchanged(self):
        task_id, target = self.add_managed()
        initial = self.store.read("session-wp04")["tasks"][task_id]
        for index, response in enumerate(({}, {"isError": True}, {"unexpected": True}), start=1):
            prepared = governance.prepare_communication(
                self.communication("normal_message", target=target),
                "session-wp04",
                state_store=self.store,
            )
            tool_use_id = f"normal-call-{index}"
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "send_message",
                    "tool_use_id": tool_use_id,
                    "tool_input": prepared["native_args"],
                },
                self.store,
            )
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "send_message",
                    "tool_use_id": tool_use_id,
                    "tool_response": response,
                },
                self.store,
            )
        record = self.store.read("session-wp04")["tasks"][task_id]
        for field in (
            "execution_status",
            "platform_observation",
            "business_result",
            "spawn_retry_count",
            "recovery_count",
            "correction_count",
        ):
            self.assertEqual(record[field], initial[field], field)
        self.assertNotIn("last_lifecycle_operation", record)

        class Unavailable:
            def read(self, *args, **kwargs):
                raise governance.StateWriteError("unavailable")

            def update(self, *args, **kwargs):
                raise governance.StateWriteError("unavailable")

        degraded = governance.prepare_communication(
            self.communication("normal_message", target=target),
            "session-wp04",
            state_store=Unavailable(),
        )
        self.assertFalse(degraded["managed"])
        self.assertIn("未可靠记录", degraded["degraded_warning"])

    def test_managed_followup_without_pending_is_not_classified_from_body(self):
        _task_id, target = self.add_managed(
            execution_status="stopped",
            platform_observation="error",
            parent_action="recover",
        )
        result = governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "body-guess",
                "tool_input": {
                    "target": target,
                    "message": "operation_type=platform_recovery 请恢复原任务",
                },
            },
            self.store,
        )
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("不能猜测 operation type", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_managed_normal_requires_generator_and_followup_cannot_claim_it(self):
        _task_id, target = self.add_managed()
        direct = governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "send_message",
                "tool_use_id": "direct-normal",
                "tool_input": {"target": target, "message": "直接发送"},
            },
            self.store,
        )
        self.assertEqual(direct["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("pending_action", direct["hookSpecificOutput"]["permissionDecisionReason"])

        prepared = governance.prepare_communication(
            self.communication("normal_message", target=target),
            "session-wp04",
            state_store=self.store,
        )
        wrong_tool = governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "wrong-normal-tool",
                "tool_input": prepared["native_args"],
            },
            self.store,
        )
        self.assertEqual(wrong_tool["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("不能认领 normal_message", wrong_tool["hookSpecificOutput"]["permissionDecisionReason"])

    def test_managed_normal_cannot_bypass_platform_error(self):
        _task_id, target = self.add_managed(
            execution_status="stopped",
            platform_observation="error",
            parent_action="recover",
        )
        with self.assertRaisesRegex(governance.CommunicationPreparationError, "不能绕过"):
            governance.prepare_communication(
                self.communication("normal_message", target=target),
                "session-wp04",
                state_store=self.store,
            )

    def test_managed_list_agents_and_two_recovery_limit_use_multidimensional_state(self):
        task_id, target = self.add_managed()
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PostToolUse",
                "tool_name": "list_agents",
                "tool_response": {
                    "agents": [{"agent_name": target, "agent_status": {"errored": "stream disconnected"}}]
                },
            },
            self.store,
        )
        record = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(record["execution_status"], "stopped")
        self.assertEqual(record["platform_observation"], "error")
        self.assertEqual(record["parent_action"], "recover")
        self.assertNotIn("status", record)

        first = governance.prepare_communication(
            self.communication("platform_recovery", target=target),
            "session-wp04",
            state_store=self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "recovery-first",
                "tool_input": first["native_args"],
            },
            self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PostToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "recovery-first",
                "tool_response": {"status": "success"},
            },
            self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "SubagentStart",
                "agent_id": target,
            },
            self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PostToolUse",
                "tool_name": "list_agents",
                "tool_response": {
                    "agents": [{"agent_name": target, "agent_status": {"errored": "again"}}]
                },
            },
            self.store,
        )
        record = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(record["recovery_status"], "awaiting_authorization")
        with self.assertRaisesRegex(governance.CommunicationPreparationError, "明确授权"):
            governance.prepare_communication(
                self.communication("platform_recovery", target=target),
                "session-wp04",
                state_store=self.store,
            )

        second = governance.prepare_communication(
            self.communication("platform_recovery", target=target),
            "session-wp04",
            authorized_recovery=True,
            state_store=self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "recovery-second",
                "tool_input": second["native_args"],
            },
            self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PostToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "recovery-second",
                "tool_response": {"isError": True},
            },
            self.store,
        )
        record = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(record["recovery_count"], 2)
        self.assertEqual(record["recovery_status"], "exhausted")
        with self.assertRaisesRegex(governance.CommunicationPreparationError, "耗尽"):
            governance.prepare_communication(
                self.communication("platform_recovery", target=target),
                "session-wp04",
                authorized_recovery=True,
                state_store=self.store,
            )

    def test_result_correction_has_independent_two_attempt_budget(self):
        task_id, target = self.add_managed(
            execution_status="stopped",
            result_protocol_status="needs_correction",
            parent_action="correct_result",
            spawn_retry_count=2,
            recovery_count=2,
        )
        for index, response in enumerate(({"isError": True}, {"isError": True}), start=1):
            prepared = governance.prepare_communication(
                self.communication("result_correction", target=target),
                "session-wp04",
                state_store=self.store,
            )
            self.assertIn("不重做业务任务", prepared["message"])
            tool_use_id = f"correction-{index}"
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "followup_task",
                    "tool_use_id": tool_use_id,
                    "tool_input": prepared["native_args"],
                },
                self.store,
            )
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "followup_task",
                    "tool_use_id": tool_use_id,
                    "tool_response": response,
                },
                self.store,
            )
        record = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(record["spawn_retry_count"], 2)
        self.assertEqual(record["recovery_count"], 2)
        self.assertEqual(record["correction_count"], 2)
        self.assertEqual(record["result_protocol_status"], "exhausted")
        self.assertEqual(record["parent_action"], "manual_review")

    def test_result_correction_success_and_unknown_keep_fixed_protocol_state(self):
        for index, (response, parent_action, observation) in enumerate(
            (
                ({"status": "success"}, "wait", "success"),
                ({"status": "running"}, "reconcile", "unknown"),
            ),
            start=1,
        ):
            task_id = f"correction-observation-{index}"
            target = f"correction-agent-{index}"
            self.add_managed(
                task_id=task_id,
                target=target,
                execution_status="stopped",
                result_protocol_status="needs_correction",
                parent_action="correct_result",
            )
            prepared = governance.prepare_communication(
                self.communication("result_correction", target=target),
                "session-wp04",
                state_store=self.store,
            )
            tool_use_id = f"correction-observation-call-{index}"
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "followup_task",
                    "tool_use_id": tool_use_id,
                    "tool_input": prepared["native_args"],
                },
                self.store,
            )
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "followup_task",
                    "tool_use_id": tool_use_id,
                    "tool_response": response,
                },
                self.store,
            )
            record = self.store.read("session-wp04")["tasks"][task_id]
            self.assertEqual(record["execution_status"], "stopped")
            self.assertEqual(record["result_protocol_status"], "needs_correction")
            self.assertEqual(record["correction_count"], 1)
            self.assertEqual(record["parent_action"], parent_action)
            self.assertEqual(record["last_lifecycle_operation"]["call_observation"], observation)

    def test_business_resume_success_unknown_and_failed_have_fixed_not_started_transitions(self):
        observations = (
            ("success", {"status": "success"}, "wait", False),
            ("unknown", {"status": "running"}, "reconcile", False),
            ("failed", {"isError": True}, "decide_disposition", True),
        )
        for index, (_name, response, parent_action, closed) in enumerate(observations, start=1):
            with self.subTest(observation=_name):
                task_id = f"resume-task-{index}"
                target = f"resume-agent-{index}"
                self.add_managed(
                    task_id=task_id,
                    target=target,
                    execution_status="stopped",
                    business_result="failed",
                    parent_action="decide_disposition",
                )
                prepared = governance.prepare_communication(
                    self.communication(
                        "business_resume",
                        target=target,
                        task_contract=self.contract(current_state="父 Agent 已决定继续"),
                    ),
                    "session-wp04",
                    state_store=self.store,
                )
                tool_use_id = f"resume-observation-{index}"
                governance.handle(
                    {
                        "session_id": "session-wp04",
                        "hook_event_name": "PreToolUse",
                        "tool_name": "followup_task",
                        "tool_use_id": tool_use_id,
                        "tool_input": prepared["native_args"],
                    },
                    self.store,
                )
                governance.handle(
                    {
                        "session_id": "session-wp04",
                        "hook_event_name": "PostToolUse",
                        "tool_name": "followup_task",
                        "tool_use_id": tool_use_id,
                        "tool_response": response,
                    },
                    self.store,
                )
                record = self.store.read("session-wp04")["tasks"][task_id]
                self.assertEqual(record["execution_status"], "stopped" if closed else "not_started")
                self.assertEqual(record["parent_action"], parent_action)
                self.assertEqual(record.get("attempt_closed", False), closed)

    def test_business_resume_start_rebinds_attempt_and_unknown_blocks_same_agent_reuse(self):
        task_id, target = self.add_managed(
            task_id="resume-rebind-task",
            target="resume-rebind-agent",
            execution_status="stopped",
            business_result="blocked",
            parent_action="decide_disposition",
        )
        old_task_name = self.store.read("session-wp04")["tasks"][task_id]["task_name"]
        prepared = governance.prepare_communication(
            self.communication(
                "business_resume",
                target=target,
                task_contract=self.contract(current_state="阻塞已经解除"),
            ),
            "session-wp04",
            state_store=self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "resume-rebind-call",
                "tool_input": prepared["native_args"],
            },
            self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PostToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "resume-rebind-call",
                "tool_response": {"status": "success"},
            },
            self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "SubagentStart",
                "agent_id": target,
                "task_name": old_task_name,
            },
            self.store,
        )
        state = self.store.read("session-wp04")
        self.assertEqual(state["tasks"][task_id]["attempt"], 2)
        self.assertEqual(state["tasks"][task_id]["execution_status"], "running")
        self.assertEqual(state["agents"][target], {"task_id": task_id, "attempt": 2})
        self.assertNotIn("last_lifecycle_operation", state["tasks"][task_id])

        unknown_task, unknown_target = self.add_managed(
            task_id="resume-unknown-task",
            target="resume-unknown-agent",
            execution_status="stopped",
            business_result="failed",
            parent_action="decide_disposition",
        )
        unknown = governance.prepare_communication(
            self.communication(
                "business_resume",
                target=unknown_target,
                task_contract=self.contract(current_state="父 Agent 决定继续"),
            ),
            "session-wp04",
            state_store=self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "resume-unknown-call",
                "tool_input": unknown["native_args"],
            },
            self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PostToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "resume-unknown-call",
                "tool_response": {"status": "running"},
            },
            self.store,
        )
        self.assertEqual(self.store.read("session-wp04")["tasks"][unknown_task]["attempt"], 2)
        with self.assertRaisesRegex(governance.CommunicationPreparationError, "new Agent"):
            governance.prepare_communication(
                self.communication(
                    "business_resume",
                    target=unknown_target,
                    task_contract=self.contract(current_state="尝试绕过 unknown"),
                ),
                "session-wp04",
                state_store=self.store,
            )

    def test_late_subagent_start_consumes_success_or_unknown_but_not_failed_or_interrupt(self):
        for index, response in enumerate(({"status": "success"}, {"status": "running"}), start=1):
            task_id = f"late-start-{index}"
            target = f"late-agent-{index}"
            self.add_managed(
                task_id=task_id,
                target=target,
                execution_status="stopped",
                platform_observation="error",
                parent_action="recover",
            )
            prepared = governance.prepare_communication(
                self.communication("platform_recovery", target=target),
                "session-wp04",
                state_store=self.store,
            )
            tool_use_id = f"late-recovery-{index}"
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "followup_task",
                    "tool_use_id": tool_use_id,
                    "tool_input": prepared["native_args"],
                },
                self.store,
            )
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "followup_task",
                    "tool_use_id": tool_use_id,
                    "tool_response": response,
                },
                self.store,
            )
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "SubagentStart",
                    "agent_id": target,
                },
                self.store,
            )
            record = self.store.read("session-wp04")["tasks"][task_id]
            self.assertEqual(record["execution_status"], "running")
            self.assertEqual(record["platform_observation"], "normal")
            self.assertNotIn("last_lifecycle_operation", record)

        failed_task, failed_target = self.add_managed(
            task_id="failed-start",
            target="failed-start-agent",
            execution_status="stopped",
            result_protocol_status="needs_correction",
            parent_action="correct_result",
        )
        correction = governance.prepare_communication(
            self.communication("result_correction", target=failed_target),
            "session-wp04",
            state_store=self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "failed-correction",
                "tool_input": correction["native_args"],
            },
            self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PostToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "failed-correction",
                "tool_response": {"isError": True},
            },
            self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "SubagentStart",
                "agent_id": failed_target,
            },
            self.store,
        )
        record = self.store.read("session-wp04")["tasks"][failed_task]
        self.assertEqual(record["execution_status"], "stopped")
        self.assertEqual(record["parent_action"], "reconcile")

    def test_interrupt_success_failed_unknown_and_list_reconciliation(self):
        cases = (
            ("success", {"status": "interrupted"}, "interrupted", "decide_disposition"),
            ("failed", {"isError": True}, "running", "wait"),
            ("unknown", {"status": "running"}, "running", "reconcile"),
        )
        for index, (_name, response, execution, parent_action) in enumerate(cases, start=1):
            task_id = f"interrupt-task-{index}"
            target = f"interrupt-agent-{index}"
            self.add_managed(task_id=task_id, target=target)
            prepared = governance.prepare_interrupt(
                self.communication("normal_message", target=target),
                "session-wp04",
                state_store=self.store,
            )
            tool_use_id = f"interrupt-case-{index}"
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "interrupt_agent",
                    "tool_use_id": tool_use_id,
                    "tool_input": prepared["native_args"],
                },
                self.store,
            )
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "interrupt_agent",
                    "tool_use_id": tool_use_id,
                    "tool_response": response,
                },
                self.store,
            )
            record = self.store.read("session-wp04")["tasks"][task_id]
            self.assertEqual(record["execution_status"], execution)
            self.assertEqual(record["parent_action"], parent_action)
            if _name == "success":
                self.assertNotIn("last_lifecycle_operation", record)
            else:
                self.assertEqual(record["last_lifecycle_operation"]["call_observation"], _name)

        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PostToolUse",
                "tool_name": "list_agents",
                "tool_response": {
                    "agents": [{"agent_name": "interrupt-agent-3", "agent_status": {"running": True}}]
                },
            },
            self.store,
        )
        record = self.store.read("session-wp04")["tasks"]["interrupt-task-3"]
        self.assertEqual(record["execution_status"], "running")
        self.assertEqual(record["parent_action"], "ask_user")
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "SubagentStart",
                "agent_id": "interrupt-agent-3",
            },
            self.store,
        )
        record = self.store.read("session-wp04")["tasks"]["interrupt-task-3"]
        self.assertEqual(record["parent_action"], "ask_user")

    def test_interrupt_unknown_list_error_and_stopped_use_observed_state(self):
        for index, (platform_status, execution, platform, parent_action) in enumerate(
            (
                ({"errored": "stream disconnected"}, "stopped", "error", "ask_user"),
                ({"stopped": True}, "stopped", "normal", "decide_disposition"),
            ),
            start=1,
        ):
            task_id = f"interrupt-list-task-{index}"
            target = f"interrupt-list-agent-{index}"
            self.add_managed(task_id=task_id, target=target)
            prepared = governance.prepare_interrupt(
                self.communication("normal_message", target=target),
                "session-wp04",
                state_store=self.store,
            )
            tool_use_id = f"interrupt-list-call-{index}"
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "interrupt_agent",
                    "tool_use_id": tool_use_id,
                    "tool_input": prepared["native_args"],
                },
                self.store,
            )
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "interrupt_agent",
                    "tool_use_id": tool_use_id,
                    "tool_response": {"status": "running"},
                },
                self.store,
            )
            governance.handle(
                {
                    "session_id": "session-wp04",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "list_agents",
                    "tool_response": {
                        "agents": [{"agent_name": target, "agent_status": platform_status}]
                    },
                },
                self.store,
            )
            record = self.store.read("session-wp04")["tasks"][task_id]
            self.assertEqual(record["execution_status"], execution)
            self.assertEqual(record["platform_observation"], platform)
            self.assertEqual(record["parent_action"], parent_action)
            self.assertEqual(record["last_lifecycle_operation"]["call_observation"], "unknown")

    def test_last_lifecycle_operation_has_no_time_ttl(self):
        task_id, target = self.add_managed(
            execution_status="stopped",
            platform_observation="error",
            parent_action="recover",
        )
        prepared = governance.prepare_communication(
            self.communication("platform_recovery", target=target),
            "session-wp04",
            state_store=self.store,
            now=100,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "no-ttl-call",
                "tool_input": prepared["native_args"],
                "now": 110,
            },
            self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PostToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "no-ttl-call",
                "tool_response": {"status": "success"},
                "now": 120,
            },
            self.store,
        )
        governance.reconcile_pending_actions(
            "session-wp04",
            state_store=self.store,
            now=120 + 365 * 24 * 60 * 60,
        )
        record = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(record["last_lifecycle_operation"]["tool_use_id"], "no-ttl-call")

    def test_cli_prepares_communication_and_interrupt(self):
        _task_id, target = self.add_managed()
        communication = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--prepare-communication",
                "--session",
                "session-wp04",
                "--data-root",
                str(self.root),
            ],
            input=json.dumps(self.communication("normal_message", target=target), ensure_ascii=False),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(communication.returncode, 0, communication.stderr)
        communication_output = json.loads(communication.stdout)
        self.assertEqual(communication_output["native_tool"], "send_message")

        claimed = governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "send_message",
                "tool_use_id": "cli-normal-call",
                "tool_input": communication_output["native_args"],
            },
            self.store,
        )
        self.assertEqual(claimed["hookSpecificOutput"]["permissionDecision"], "allow")
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PostToolUse",
                "tool_name": "send_message",
                "tool_use_id": "cli-normal-call",
                "tool_response": {"status": "success"},
            },
            self.store,
        )

        interrupt = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--prepare-interrupt",
                "--session",
                "session-wp04",
                "--data-root",
                str(self.root),
            ],
            input=json.dumps(self.communication("normal_message", target=target), ensure_ascii=False),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(interrupt.returncode, 0, interrupt.stderr)
        interrupt_output = json.loads(interrupt.stdout)
        self.assertEqual(interrupt_output["native_tool"], "interrupt_agent")
        self.assertEqual(interrupt_output["native_args"], {"target": target})

    def test_post_tool_state_write_failure_is_degraded_without_budget_rollback(self):
        task_id, target = self.add_managed(
            execution_status="stopped",
            platform_observation="error",
            parent_action="recover",
        )
        prepared = governance.prepare_communication(
            self.communication("platform_recovery", target=target),
            "session-wp04",
            state_store=self.store,
        )
        governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PreToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "degraded-post",
                "tool_input": prepared["native_args"],
            },
            self.store,
        )

        class FailingPostStore:
            last_warning = None

            def read(_self, *args, **kwargs):
                return self.store.read(*args, **kwargs)

            def compare_and_set(_self, *args, **kwargs):
                raise governance.StateWriteError("simulated post failure")

        result = governance.handle(
            {
                "session_id": "session-wp04",
                "hook_event_name": "PostToolUse",
                "tool_name": "followup_task",
                "tool_use_id": "degraded-post",
                "tool_response": {"status": "success"},
            },
            FailingPostStore(),
        )
        self.assertIn("degraded", result["systemMessage"])
        record = self.store.read("session-wp04")["tasks"][task_id]
        self.assertEqual(record["recovery_count"], 1)
        self.assertEqual(record["pending_action"]["phase"], "claimed")

    def test_unmanaged_communication_and_interrupt_do_not_create_governance_association(self):
        normal = governance.prepare_communication(
            self.communication("normal_message", target="unmanaged-agent"),
            "session-wp04",
            state_store=self.store,
        )
        interrupt = governance.prepare_interrupt(
            self.communication("normal_message", target="unmanaged-agent"),
            "session-wp04",
            state_store=self.store,
        )
        self.assertFalse(normal["managed"])
        self.assertFalse(interrupt["managed"])
        self.assertEqual(normal["native_tool"], "send_message")
        self.assertEqual(interrupt["native_tool"], "interrupt_agent")
        self.assertEqual(self.store.read("session-wp04")["tasks"], {})


if __name__ == "__main__":
    unittest.main()
