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

    def test_complete_lifecycle_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            store = governance.StateStore(Path(directory))
            task_id = None
            state_path, _ = store._paths("fixture-session")
            for payload in self.load_fixture("lifecycle-v1.json"):
                if task_id and isinstance(payload.get("last_assistant_message"), str):
                    payload["last_assistant_message"] = payload["last_assistant_message"].replace(
                        "{{TASK_ID}}", task_id
                    )
                result = governance.handle(payload, store)
                if payload["hook_event_name"] == "PreToolUse":
                    message = result["hookSpecificOutput"]["updatedInput"]["message"]
                    task_id = governance.TASK_ID_RE.search(message).group(1)
                self.assertIsNotNone(result) if payload["hook_event_name"] != "PostToolUse" else None
            self.assertFalse(state_path.exists())

    def test_interrupt_lifecycle_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            store = governance.StateStore(Path(directory))
            task_id = None
            for payload in self.load_fixture("interrupt-v1.json"):
                result = governance.handle(payload, store)
                if payload["hook_event_name"] == "PreToolUse":
                    message = result["hookSpecificOutput"]["updatedInput"]["message"]
                    task_id = governance.TASK_ID_RE.search(message).group(1)
            self.assertIsNotNone(task_id)
            state = store.read("interrupt-session")
            self.assertEqual(state["tasks"][task_id]["status"], "interrupted")

    def test_opaque_spawn_fixture_uses_task_name_governance(self):
        with tempfile.TemporaryDirectory() as directory:
            store = governance.StateStore(Path(directory))
            payload = self.load_fixture("opaque-spawn-v1.json")
            result = governance.handle(payload, store)
            message = result["hookSpecificOutput"]["updatedInput"]["message"]
            task_id = governance.TASK_ID_RE.search(message).group(1)
            record = store.read("opaque-session")["tasks"][task_id]
            self.assertEqual(record["mode"], "strict")
            self.assertEqual(record["message_visibility"], "opaque")

    def test_agent_status_fixture_reconciles_platform_error(self):
        with tempfile.TemporaryDirectory() as directory:
            store = governance.StateStore(Path(directory))
            spawn = self.load_fixture("opaque-spawn-v1.json")
            spawn["session_id"] = "status-session"
            spawn["tool_use_id"] = "spawn-tool"
            result = governance.handle(spawn, store)
            task_id = governance.TASK_ID_RE.search(
                result["hookSpecificOutput"]["updatedInput"]["message"]
            ).group(1)

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
            record = store.read("status-session")["tasks"][task_id]
            self.assertEqual(record["status"], "platform_error")
            self.assertIn("stream disconnected", record["platform_error"])


if __name__ == "__main__":
    unittest.main()
