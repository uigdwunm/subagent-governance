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

    def test_dispatch_identity_lifecycle_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = governance.StateStore(root / "sessions")
            prepared_store = governance.PreparedContractStore(root / "prepared")
            events = self.load_fixture("lifecycle-v1.json")
            prepared = governance.prepare_dispatch(
                self.contract(model="gpt-5.6-terra", reasoning_effort="high"),
                "fixture-session",
                state_store=store,
                prepared_store=prepared_store,
            )
            spawn = events[1]
            spawn["tool_input"] = prepared["spawn_args"]
            self.assertEqual(
                governance.handle(spawn, store)["hookSpecificOutput"]["permissionDecision"],
                "allow",
            )
            events[2]["tool_response"]["task_name"] = f"/root/{prepared['task_name']}"
            governance.handle(events[2], store)
            governance.handle(events[3], store)

            state = store.read("fixture-session")
            record = state["tasks"][prepared["task_id"]]
            self.assertEqual(record["identity_status"], "confirmed")
            self.assertEqual(record["execution_status"], "running")
            self.assertEqual(
                state["agents"]["fixture-agent"],
                {"task_id": prepared["task_id"], "attempt": 1},
            )
            self.assertEqual(prepared_store.list_records("fixture-session"), [])

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
                    "tool_response": {"agent_id": "interrupt-agent"},
                },
                store,
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
            state = store.read("interrupt-session")
            record = state["tasks"][dispatch["task_id"]]
            self.assertEqual(record["execution_status"], "interrupted")
            self.assertEqual(record["parent_action"], "decide_disposition")
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
            record = store.read("opaque-session")["tasks"][prepared["task_id"]]
            self.assertEqual(record["resolved_mode"], "strict")
            self.assertNotIn("message_visibility", record)
            self.assertEqual(record["spawn_tool_use_id"], "opaque-tool")

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
            governance.handle(self.load_fixture("agent-status-error-v1.json"), store)
            record = store.read("status-session")["tasks"][prepared["task_id"]]
            self.assertNotIn("status", record)
            self.assertEqual(record["execution_status"], "stopped")
            self.assertEqual(record["platform_observation"], "error")
            self.assertEqual(record["parent_action"], "recover")

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
            events = self.load_fixture("recovery-limit-v1.json")
            governance.handle(events[0], store)
            first = governance.prepare_communication(
                events[1]["tool_input"],
                "recovery-fixture-session",
                state_store=store,
            )
            events[1]["tool_input"] = first["native_args"]
            governance.handle(events[1], store)
            governance.handle(events[2], store)
            events[3]["agent_id"] = "native-recovery-agent"
            events[3]["canonical_task_path"] = target
            governance.handle(events[3], store)
            governance.handle(events[4], store)

            record = store.read("recovery-fixture-session")["tasks"][dispatch["task_id"]]
            self.assertEqual(record["recovery_status"], "awaiting_authorization")
            second = governance.prepare_communication(
                events[5]["tool_input"],
                "recovery-fixture-session",
                authorized_recovery=True,
                state_store=store,
            )
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
            record = store.read("recovery-fixture-session")["tasks"][dispatch["task_id"]]
            self.assertEqual(record["recovery_count"], 2)
            self.assertEqual(record["recovery_status"], "exhausted")
            self.assertEqual(record["parent_action"], "ask_user")


if __name__ == "__main__":
    unittest.main()
