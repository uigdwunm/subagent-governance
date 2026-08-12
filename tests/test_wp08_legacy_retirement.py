#!/usr/bin/env python3

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_wp08", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class LegacyRetirementTests(unittest.TestCase):
    def test_legacy_runtime_symbols_are_retired(self):
        retired = {
            "ACTIVE_STATUSES",
            "INTERRUPTIBLE_STATUSES",
            "TERMINAL_STATUSES",
            "RESOLVABLE_STATUSES",
            "STOP_BLOCKING_STATUSES",
            "SESSION_RESTORABLE_STATUSES",
            "SESSION_END_PRESERVED_STATUSES",
            "LEGACY_AUTOMATIC_RECOVERY_LIMIT",
            "_terminal_field",
            "_legacy_terminal_errors",
            "_legacy_reported_status",
            "_legacy_action_required",
            "_recent_records",
            "_active_records",
            "_managed_action_required_records",
            "_session_restore_records",
            "_session_end_preserved_records",
            "_platform_status_summary",
        }
        remaining = sorted(name for name in retired if hasattr(governance, name))
        self.assertEqual(remaining, [])

    def test_historical_nonmanaged_mapping_is_warned_and_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = governance.StateStore(Path(directory) / "sessions")
            now = governance._now()

            def add_historical(state):
                state["tasks"]["historical-task"] = {
                    "task_id": "historical-task",
                    "attempt": 1,
                    "status": "running",
                    "retry_count": 0,
                    "created_at": now,
                    "updated_at": now,
                }
                state["agents"]["historical-agent"] = {
                    "task_id": "historical-task",
                    "attempt": 1,
                }

            store.update("session-1", add_historical)
            result = governance.handle(
                {
                    "session_id": "session-1",
                    "hook_event_name": "SubagentStop",
                    "agent_id": "historical-agent",
                    "last_assistant_message": "状态：完成\n自由文本结果",
                },
                store,
            )
            record = store.read("session-1")["tasks"]["historical-task"]
            self.assertTrue(result["continue"])
            self.assertIn("历史或非 managed", result["systemMessage"])
            self.assertEqual(record["status"], "running")
            self.assertNotIn("result_document", record)
            self.assertNotIn("protocol_errors", record)

    def test_authoritative_views_ignore_historical_nonmanaged_records(self):
        state = {
            "session_id": "session-1",
            "tasks": {
                "historical-task": {
                    "task_id": "historical-task",
                    "status": "running",
                    "created_at": governance._now(),
                    "updated_at": governance._now(),
                }
            },
            "agents": {},
            "groups": {},
            "health": {"status": "ok"},
            "tombstones": {},
            "updated_at": governance._now(),
        }
        self.assertEqual(governance._action_required_records(state), [])
        self.assertEqual(governance._recent_activity_records(state), [])
        self.assertEqual(governance._stop_blocking_records(state), [])

    def test_opaque_fixture_has_current_exact_identity_name(self):
        fixtures = ROOT / "tests/fixtures"
        current = fixtures / "exact-task-ref-opaque-message-v1.json"
        retired = fixtures / "opaque-spawn-v1.json"
        self.assertTrue(current.is_file())
        self.assertFalse(retired.exists())
        payload = json.loads(current.read_text(encoding="utf-8"))
        self.assertIn("_t_", payload["tool_input"]["task_name"])
        self.assertTrue(payload["tool_input"]["message"].startswith("gAAAAA"))

    def test_current_documents_do_not_defer_legacy_retirement_to_wp08(self):
        current_documents = [
            ROOT / "README.md",
            ROOT / "skills/subagent-governance/SKILL.md",
            ROOT / "skills/subagent-governance/references/runtime-boundaries.md",
            ROOT / "docs/release-process.md",
        ]
        forbidden = (
            "尚待 WP-08",
            "WP-08 再删除",
            "WP-08 原子退役",
            "后续 WP 接管",
        )
        for path in current_documents:
            text = path.read_text(encoding="utf-8")
            for phrase in forbidden:
                with self.subTest(path=path.name, phrase=phrase):
                    self.assertNotIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
