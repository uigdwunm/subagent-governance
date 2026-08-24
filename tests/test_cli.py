import io
import json
import unittest
from unittest import mock

from scripts import governance_cli
from tests.support import load_governance

governance = load_governance("cli")


class GovernanceCliTests(unittest.TestCase):
    def invoke(self, arguments, stdin=""):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(governance_cli.sys, "stdin", io.StringIO(stdin)),
            mock.patch.object(governance_cli.sys, "stdout", stdout),
            mock.patch.object(governance_cli.sys, "stderr", stderr),
        ):
            returncode = governance_cli.main(governance, arguments)
        return returncode, stdout.getvalue(), stderr.getvalue()

    def test_context_manifest_verification_mode(self):
        returncode, stdout, stderr = self.invoke(
            ["--verify-context-manifest"],
            json.dumps({"mode": "none"}),
        )
        self.assertEqual(returncode, 0, stderr)
        self.assertEqual(json.loads(stdout), {"mode": "none"})

    def test_hook_mode_fails_open_for_invalid_input(self):
        returncode, stdout, stderr = self.invoke([], "[")
        self.assertEqual(returncode, 0, stderr)
        result = json.loads(stdout)
        self.assertTrue(result["continue"])
        self.assertIn("降级放行", result["systemMessage"])

    def test_mode_specific_required_arguments(self):
        for arguments, expected in (
            (["--prepare-dispatch"], "requires --session"),
            (["--reconcile-interrupted-attempt"], "requires --session"),
            (["--record-terminal-notification"], "require --session"),
            (["--upsert-group"], "require --session"),
            (["--read-group", "--session", "session-1"], "requires --group-id"),
        ):
            with self.subTest(arguments=arguments):
                returncode, _stdout, stderr = self.invoke(arguments)
                self.assertEqual(returncode, 2)
                self.assertIn(expected, stderr)

    def test_argument_conflicts_are_rejected(self):
        for arguments, expected in (
            (["--unexpected"], "unsupported arguments"),
            (
                ["--prepare-dispatch", "--prepare-communication"],
                "operation modes cannot be combined",
            ),
            (
                ["--verify-context-manifest", "--session", "session-1"],
                "does not accept --session",
            ),
            (["--authorize-final-retry"], "requires --prepare-spawn-retry"),
            (["--authorize-recovery"], "requires --prepare-communication"),
            (["--group-id", "group-1"], "only valid with --read-group"),
        ):
            with self.subTest(arguments=arguments):
                returncode, _stdout, stderr = self.invoke(arguments)
                self.assertEqual(returncode, 2)
                self.assertIn(expected, stderr)

    def test_diagnose_delegates_to_runtime(self):
        with mock.patch.object(governance, "_diagnose", return_value=7) as diagnose:
            returncode, stdout, stderr = self.invoke(
                ["--diagnose", "--session", "session-1"]
            )
        self.assertEqual(returncode, 7)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        diagnose.assert_called_once_with("session-1", None)


if __name__ == "__main__":
    unittest.main()
