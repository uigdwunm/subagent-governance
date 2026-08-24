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
        return (
            governance_cli.main(arguments, stdin=io.BytesIO(stdin), stdout=stdout, stderr=stderr),
            stdout.getvalue(), stderr.getvalue(),
        )

    def test_binary_reader_is_byte_bounded(self):
        self.assertEqual(read_json_object(io.BytesIO(b'{"x":"\xc3\xa9"}'), limit=10), {"x": "é"})
        with self.assertRaisesRegex(ValueError, "10 bytes"):
            read_json_object(io.BytesIO(b'{"x":"12345"}'), limit=10)
        with self.assertRaises(UnicodeDecodeError):
            read_json_object(io.BytesIO(b'{"x":"\xff"}'))
        with self.assertRaisesRegex(ValueError, "JSON object"):
            read_json_object(io.BytesIO(b"[]"))

    def test_hook_parse_failure_is_fail_open_before_event_is_trusted(self):
        code, output, error = self.invoke([], b'{"hook_event_name":"PreToolUse"')
        self.assertEqual((code, error), (0, ""))
        self.assertTrue(json.loads(output)["continue"])

    def test_context_mode_and_argument_errors(self):
        code, output, error = self.invoke(["--verify-context-manifest"], b'{"mode":"none"}')
        self.assertEqual((code, json.loads(output), error), (0, {"mode": "none"}, ""))
        code, _output, error = self.invoke(["--prepare-dispatch", "--prepare-interrupt"])
        self.assertEqual(code, 2); self.assertIn("cannot be combined", error)

    def test_diagnose_explicit_missing_root_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "not-created"
            code, output, error = self.invoke(["--diagnose", "--data-root", str(root)])
            self.assertEqual(code, 0, error)
            self.assertFalse(root.exists())
            self.assertEqual(json.loads(output)["data_root"], str(root))

    def test_read_group_does_not_consume_stdin(self):
        with tempfile.TemporaryDirectory() as directory:
            code, _output, _error = self.invoke(["--read-group", "--session", "s", "--group-id", "g", "--data-root", directory], b"not json")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
