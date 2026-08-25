import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import governance_cli
from scripts.governance_input import read_json_object


class GovernanceCliTests(unittest.TestCase):
    def invoke(self, arguments, stdin=b""):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = governance_cli.main(
            arguments, stdin=io.BytesIO(stdin), stdout=stdout, stderr=stderr
        )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_binary_reader_is_utf8_byte_bounded(self):
        self.assertEqual(read_json_object(io.BytesIO(b'{"x":"\xc3\xa9"}'), limit=10), {"x": "é"})
        with self.assertRaisesRegex(ValueError, "10 bytes"):
            read_json_object(io.BytesIO(b'{"x":"12345"}'), limit=10)

    def test_hook_parse_failure_is_fail_open(self):
        code, output, error = self.invoke([], b'{"hook_event_name":"PreToolUse"')
        self.assertEqual((code, error), (0, ""))
        self.assertTrue(json.loads(output)["continue"])

    def test_prepare_confirm_and_status_use_v9_commands(self):
        contract = {
            "objective": "CLI dispatch",
            "scope": ["tests"],
            "completion": ["confirmed"],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = ["--session", "cli-session", "--data-root", str(root)]
            code, output, error = self.invoke(
                ["--prepare-dispatch", *base], json.dumps(contract).encode()
            )
            self.assertEqual(code, 0, error)
            prepared = json.loads(output)
            from scripts.governance_hook import handle_hook
            from scripts.governance_state_store import StateStore

            store = StateStore(root / "sessions")
            claimed = handle_hook(
                {
                    "session_id": "cli-session",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "spawn_agent",
                    "tool_use_id": "call-1",
                    "tool_input": prepared["spawn_args"],
                },
                store,
            )
            self.assertEqual(claimed["hookSpecificOutput"]["permissionDecision"], "allow")
            confirm = {
                "task_id": prepared["task_id"],
                "task_ref": prepared["task_ref"],
                "target": "/root/cli-target",
            }
            code, output, error = self.invoke(
                ["--confirm-dispatch", *base], json.dumps(confirm).encode()
            )
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["result"], "bound")
            code, output, error = self.invoke(["--status", *base])
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["tasks"][0]["phase"], "bound")

    def test_status_missing_root_is_lock_free_and_zero_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "missing"
            code, output, error = self.invoke(
                ["--status", "--session", "s", "--data-root", str(root)]
            )
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["tasks"], [])
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
