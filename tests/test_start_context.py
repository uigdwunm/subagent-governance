"""Startup authority is independent of task ownership and ledger health."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import governance_hook as hook


class StartContextTests(unittest.TestCase):
    def test_subagent_receives_hook_session_and_cli_without_reading_shared_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "absent"
            installed = Path(directory) / "cache/version/scripts/governance_hook.py"
            with (
                mock.patch.dict(os.environ, {"SUBAGENT_GOVERNANCE_DATA": str(root)}),
                mock.patch.object(hook, "__file__", str(installed)),
                mock.patch.object(hook, "read_ledger_readonly", side_effect=OSError("broken ledger")) as read,
            ):
                payload = {"hook_event_name": "SubagentStart", "session_id": "parent-session",
                           "agent_id": "different-child-id", "agent_type": "worker"}
                result = hook.handle_hook(payload)
                self.assertIsNotNone(result)
                self.assertEqual(result, hook.handle_hook(payload))
                read.assert_not_called()
            output = result["hookSpecificOutput"]
            self.assertEqual(output["hookEventName"], "SubagentStart")
            context = output["additionalContext"]
            self.assertIn('exact session_id（JSON）："parent-session"', context)
            self.assertIn(json.dumps(str(installed.with_name("subagent_governance.py").resolve())), context)
            self.assertNotIn("different-child-id", context)
            self.assertNotIn("next_action=", context)
            self.assertLessEqual(len(context), hook.SESSION_SUMMARY_CONTEXT_LIMIT)
            self.assertFalse(root.exists())

    def test_startup_never_substitutes_child_identity_for_missing_session(self):
        for event in ("SessionStart", "SubagentStart"):
            for value in (None, "", " ", False, 7, [], {}):
                with self.subTest(event=event, session=value):
                    self.assertIsNone(hook.handle_hook({"hook_event_name": event,
                        "session_id": value, "agent_id": "child", "source_thread_id": "parent"}))

    def test_unrelated_event_does_not_inject_authority(self):
        self.assertIsNone(hook.handle_hook({"hook_event_name": "SubagentStop", "session_id": "parent"}))
