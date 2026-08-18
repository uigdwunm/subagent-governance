#!/usr/bin/env python3

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_fixtures", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class HookFixtureTests(unittest.TestCase):
    def load_fixture(self, name):
        return json.loads((ROOT / "tests/fixtures" / name).read_text(encoding="utf-8"))

    @staticmethod
    def current_execution(state, task_id):
        task = state["tasks"][task_id]
        return task["executions"][str(task["work_item"]["current_attempt"])]

    @staticmethod
    def contract(**overrides):
        value = {
            "semantic_name": "fixture_task",
            "requested_mode": "standard",
            "objective": "检查 fixture 派发状态",
            "background": "WP-03 fixture。",
            "work_scope": ["只读检查 fixture"],
            "forbidden_scope": [],
            "completion_conditions": ["给出检查结果"],
            "evidence_requirements": ["记录 Hook 转换"],
            "relevant_files": [],
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
    def bind_fixture_identity(store, session_id, task_id, agent_id, canonical_path=None):
        def bind(state):
            execution = state["tasks"][task_id]["executions"]["1"]
            mapping = {"task_id": task_id, "attempt": 1}
            state["agents"][agent_id] = mapping
            if canonical_path:
                state["agents"][canonical_path] = mapping
            governance._apply_canonical_execution_update(
                execution,
                "dispatch_target",
                canonical_path or agent_id,
            )
            governance._apply_canonical_execution_update(execution, "observed_execution_status", "running")
            governance._apply_canonical_execution_update(execution, "closure_parent_action", "wait")
            execution.pop("last_lifecycle_operation", None)

        store.update(session_id, bind)

    def test_interrupt_lifecycle_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = governance.StateStore(root / "sessions")
            prepared_store = governance.PreparedContractStore(root / "prepared")
            dispatch = governance.prepare_dispatch(
                self.contract(semantic_name="interrupt_fixture"),
                "interrupt-session",
                state_store=store,
                prepared_store=prepared_store,
            )
            governance.handle(
                {
                    "session_id": "interrupt-session",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "spawn_agent",
                    "tool_use_id": "interrupt-spawn",
                    "tool_input": dispatch["spawn_args"],
                },
                store,
            )
            governance.handle(
                {
                    "session_id": "interrupt-session",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "spawn_agent",
                    "tool_use_id": "interrupt-spawn",
                    "tool_response": {
                        "agent_id": "interrupt-agent",
                        "canonical_task_path": "/root/interrupt-agent",
                    },
                },
                store,
            )
            self.bind_fixture_identity(
                store,
                "interrupt-session",
                dispatch["task_id"],
                "interrupt-agent",
                "/root/interrupt-agent",
            )
            events = self.load_fixture("interrupt-v1.json")
            intent = governance.prepare_interrupt(
                events[0]["tool_input"],
                "interrupt-session",
                state_store=store,
            )
            events[0]["tool_input"] = intent["native_args"]
            governance.handle(events[0], store)
            governance.handle(events[1], store)
            governance.handle(events[2], store)
            state = store.read("interrupt-session")
            record = self.current_execution(state, dispatch["task_id"])
            self.assertEqual(governance._execution_status(record), "interrupted")
            self.assertEqual(governance._parent_action(record), "reconcile")
            self.assertNotIn("closure_state", record["closure_record"])
            self.assertEqual(governance._execution_status(record), "interrupted")
            self.assertEqual(state["tombstones"], {})

    def test_opaque_spawn_fixture_uses_task_ref_without_body_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = governance.StateStore(root / "sessions")
            prepared_store = governance.PreparedContractStore(root / "prepared")
            prepared = governance.prepare_dispatch(
                self.contract(
                    semantic_name="security_review",
                    requested_mode="strict",
                    forbidden_scope=["不得修改 fixture"],
                ),
                "opaque-session",
                state_store=store,
                prepared_store=prepared_store,
            )
            payload = self.load_fixture("exact-task-ref-opaque-message-v1.json")
            payload["tool_input"] = {
                **prepared["spawn_args"],
                "message": payload["tool_input"]["message"],
            }
            result = governance.handle(payload, store)
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
            record = self.current_execution(store.read("opaque-session"), prepared["task_id"])
            self.assertEqual(record["resolved_mode"], "strict")
            self.assertNotIn("message_visibility", record)
            self.assertEqual(governance._dispatch_tool_use_id(record), "opaque-tool")

    def test_agent_status_fixture_writes_wp04_multidimensional_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = governance.StateStore(root / "sessions")
            prepared_store = governance.PreparedContractStore(root / "prepared")
            prepared = governance.prepare_dispatch(
                self.contract(
                    semantic_name="security_review",
                    requested_mode="strict",
                    forbidden_scope=["不得修改 fixture"],
                ),
                "status-session",
                state_store=store,
                prepared_store=prepared_store,
            )
            governance.handle(
                {
                    "session_id": "status-session",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "spawn_agent",
                    "tool_use_id": "spawn-tool",
                    "tool_input": prepared["spawn_args"],
                },
                store,
            )

            governance.handle({
                "session_id": "status-session",
                "hook_event_name": "PostToolUse",
                "tool_name": "collaboration.spawn_agent",
                "tool_use_id": "spawn-tool",
                "tool_response": {
                    "agent_id": "agent-status",
                    "canonical_task_path": "/root/sg_strict_security_review",
                },
            }, store)
            self.bind_fixture_identity(
                store,
                "status-session",
                prepared["task_id"],
                "agent-status",
                "/root/sg_strict_security_review",
            )
            governance.handle(self.load_fixture("agent-status-error-v1.json"), store)
            record = self.current_execution(store.read("status-session"), prepared["task_id"])
            self.assertNotIn("status", record)
            self.assertEqual(governance._execution_status(record), "not_started")
            self.assertEqual(record["observation_record"]["observed_state"], "error")
            self.assertEqual(governance._platform_observation(record), "error")
            self.assertEqual(governance._parent_action(record), "recover")

    def test_recovery_limit_fixture_handles_real_identifier_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = governance.StateStore(root / "sessions")
            prepared_store = governance.PreparedContractStore(root / "prepared")
            target = "/root/sg_light_platform_limit_fixture"
            dispatch = governance.prepare_dispatch(
                self.contract(
                    semantic_name="platform_limit_fixture",
                    requested_mode="light",
                    evidence_requirements=[],
                ),
                "recovery-fixture-session",
                state_store=store,
                prepared_store=prepared_store,
            )
            governance.handle(
                {
                    "session_id": "recovery-fixture-session",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "spawn_agent",
                    "tool_use_id": "spawn-call",
                    "tool_input": dispatch["spawn_args"],
                },
                store,
            )
            governance.handle(
                {
                    "session_id": "recovery-fixture-session",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "spawn_agent",
                    "tool_use_id": "spawn-call",
                    "tool_response": {
                        "agent_id": "native-recovery-agent",
                        "canonical_task_path": target,
                    },
                },
                store,
            )
            self.bind_fixture_identity(
                store,
                "recovery-fixture-session",
                dispatch["task_id"],
                "native-recovery-agent",
                target,
            )
            events = self.load_fixture("recovery-limit-v1.json")
            governance.handle(events[0], store)
            first = governance.prepare_communication(
                events[1]["tool_input"],
                "recovery-fixture-session",
                state_store=store,
            )
            first_record = self.current_execution(
                store.read("recovery-fixture-session"), dispatch["task_id"]
            )
            self.assertNotIn("authorized_recovery", first_record["pending_action"])
            events[1]["tool_input"] = first["native_args"]
            governance.handle(events[1], store)
            governance.handle(events[2], store)
            events[3]["agent_id"] = "native-recovery-agent"
            events[3]["canonical_task_path"] = target
            governance.handle(events[3], store)
            self.bind_fixture_identity(
                store,
                "recovery-fixture-session",
                dispatch["task_id"],
                "native-recovery-agent",
                target,
            )
            governance.handle(events[4], store)

            record = self.current_execution(
                store.read("recovery-fixture-session"), dispatch["task_id"]
            )
            self.assertNotIn("recovery_status", record)
            self.assertEqual(record["recovery_count"], 1)
            self.assertEqual(governance._parent_action(record), "ask_user")
            with self.assertRaisesRegex(
                governance.CommunicationPreparationError, "需要用户明确授权"
            ):
                governance.prepare_communication(
                    events[5]["tool_input"],
                    "recovery-fixture-session",
                    state_store=store,
                )
            second = governance.prepare_communication(
                events[5]["tool_input"],
                "recovery-fixture-session",
                authorized_recovery=True,
                state_store=store,
            )
            second_record = self.current_execution(
                store.read("recovery-fixture-session"), dispatch["task_id"]
            )
            self.assertEqual(second_record["pending_action"]["authorized_recovery"], True)
            events[5]["tool_input"] = second["native_args"]
            governance.handle(events[5], store)
            governance.handle(events[6], store)
            with self.assertRaisesRegex(governance.CommunicationPreparationError, "耗尽"):
                governance.prepare_communication(
                    events[7]["tool_input"],
                    "recovery-fixture-session",
                    authorized_recovery=True,
                    state_store=store,
                )
            record = self.current_execution(
                store.read("recovery-fixture-session"), dispatch["task_id"]
            )
            self.assertEqual(record["recovery_count"], 2)
            self.assertNotIn("recovery_status", record)
            self.assertEqual(governance._parent_action(record), "ask_user")


if __name__ == "__main__":
    unittest.main()
