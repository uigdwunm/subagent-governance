import io
import json
import tempfile
import unittest
from unittest import mock

from scripts import governance_cli
from tests.support import load_governance

governance = load_governance("cli")


class GovernanceCliTests(unittest.TestCase):
    def invoke(self, arguments, stdin=b""):
        stdout = io.StringIO()
        stderr = io.StringIO()
        if isinstance(stdin, str):
            stdin = stdin.encode("utf-8")
        input_stream = io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")
        with (
            mock.patch.object(governance_cli.sys, "stdin", input_stream),
            mock.patch.object(governance_cli.sys, "stdout", stdout),
            mock.patch.object(governance_cli.sys, "stderr", stderr),
        ):
            returncode = governance_cli.main(governance, arguments)
        return returncode, stdout.getvalue(), stderr.getvalue()

    @staticmethod
    def json_bytes_of_size(size, character="a"):
        prefix = b'{"value":"'
        suffix = b'"}'
        encoded_character = character.encode("utf-8")
        remaining = size - len(prefix) - len(suffix)
        if remaining < 0 or remaining % len(encoded_character):
            raise ValueError("size cannot contain an integral JSON string payload")
        return prefix + encoded_character * (remaining // len(encoded_character)) + suffix

    def test_binary_reader_enforces_ascii_limit_and_limit_plus_one(self):
        limit = 64
        exact = self.json_bytes_of_size(limit)
        self.assertEqual(
            governance_cli._read_json(io.BytesIO(exact), limit=limit)["value"],
            "a" * (limit - len(b'{"value":"') - len(b'"}')),
        )
        with self.assertRaisesRegex(ValueError, rf"{limit} bytes"):
            governance_cli._read_json(
                io.BytesIO(self.json_bytes_of_size(limit + 1)), limit=limit
            )

    def test_binary_reader_enforces_encoded_multibyte_limits(self):
        for character in ("é", "€", "😀"):
            with self.subTest(character=character):
                width = len(character.encode("utf-8"))
                limit = len(b'{"value":"') + len(b'"}') + width * 8
                exact = self.json_bytes_of_size(limit, character)
                self.assertEqual(len(exact), limit)
                self.assertEqual(
                    governance_cli._read_json(io.BytesIO(exact), limit=limit)["value"],
                    character * 8,
                )
                with self.assertRaisesRegex(ValueError, rf"{limit} bytes"):
                    governance_cli._read_json(
                        io.BytesIO(self.json_bytes_of_size(limit + width, character)),
                        limit=limit,
                    )

    def test_binary_reader_rejects_invalid_utf8_invalid_json_and_non_objects(self):
        with self.assertRaises(UnicodeDecodeError):
            governance_cli._read_json(io.BytesIO(b'{"value":"\xff"}'))
        with self.assertRaises(json.JSONDecodeError):
            governance_cli._read_json(io.BytesIO(b'{"value":'))
        for value in (b"[]", b"null"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "JSON object"):
                    governance_cli._read_json(io.BytesIO(value))

    def test_binary_reader_requests_only_limit_plus_one_bytes(self):
        class RecordingBytesIO(io.BytesIO):
            def __init__(self, value):
                super().__init__(value)
                self.requests = []

            def read(self, size=-1):
                self.requests.append(size)
                return super().read(size)

        stream = RecordingBytesIO(b"{}")
        self.assertEqual(governance_cli._read_json(stream, limit=37), {})
        self.assertEqual(stream.requests, [38])

    def test_context_manifest_verification_mode(self):
        returncode, stdout, stderr = self.invoke(
            ["--verify-context-manifest"],
            json.dumps({"mode": "none"}),
        )
        self.assertEqual(returncode, 0, stderr)
        self.assertEqual(json.loads(stdout), {"mode": "none"})

    def test_prepare_dispatch_rejects_multibyte_input_over_byte_limit_before_runtime(self):
        payload = json.dumps(
            {"background": "€" * 750_000}, ensure_ascii=False
        )
        self.assertGreater(
            len(payload.encode("utf-8")), governance_cli.MAX_HOOK_INPUT_BYTES
        )
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                governance, "prepare_dispatch", return_value={}
            ) as prepare_dispatch:
                returncode, _stdout, stderr = self.invoke(
                    [
                        "--prepare-dispatch",
                        "--session",
                        "session-1",
                        "--data-root",
                        directory,
                    ],
                    payload,
                )
        self.assertEqual(returncode, 1)
        self.assertIn(
            str(governance_cli.MAX_HOOK_INPUT_BYTES), stderr
        )
        prepare_dispatch.assert_not_called()

    def test_over_limit_input_does_not_construct_stores_or_call_business_operations(self):
        payload = b'{"value":"' + b"a" * governance_cli.MAX_HOOK_INPUT_BYTES + b'"}'
        modes = (
            ([], "handle", 0),
            (["--verify-context-manifest"], "verify_context_manifest", 1),
            (["--prepare-dispatch", "--session", "session-1"], "prepare_dispatch", 1),
            (
                ["--prepare-spawn-retry", "task-1", "--session", "session-1"],
                "prepare_spawn_retry",
                1,
            ),
            (
                ["--prepare-communication", "--session", "session-1"],
                "prepare_communication",
                1,
            ),
            (["--prepare-interrupt", "--session", "session-1"], "prepare_interrupt", 1),
            (
                ["--reconcile-interrupted-attempt", "--session", "session-1"],
                "reconcile_interrupted_attempt",
                1,
            ),
            (
                ["--record-terminal-notification", "--session", "session-1"],
                "record_terminal_notification",
                1,
            ),
            (["--parent-disposition", "--session", "session-1"], "apply_parent_disposition", 1),
            (["--upsert-group", "--session", "session-1"], "upsert_group", 1),
        )
        for arguments, operation, expected_returncode in modes:
            with self.subTest(arguments=arguments):
                with (
                    mock.patch.object(governance, "StateStore") as state_store,
                    mock.patch.object(
                        governance, "PreparedContractStore"
                    ) as prepared_store,
                    mock.patch.object(governance, operation) as business_operation,
                ):
                    returncode, _stdout, stderr = self.invoke(arguments, payload)
                self.assertEqual(returncode, expected_returncode)
                self.assertIn(
                    f"{governance_cli.MAX_HOOK_INPUT_BYTES} bytes",
                    stderr if expected_returncode else _stdout,
                )
                state_store.assert_not_called()
                prepared_store.assert_not_called()
                business_operation.assert_not_called()

    def test_all_json_cli_modes_use_the_binary_reader(self):
        modes = (
            ([], "handle"),
            (["--verify-context-manifest"], "verify_context_manifest"),
            (["--prepare-dispatch", "--session", "session-1"], "prepare_dispatch"),
            (
                ["--prepare-spawn-retry", "task-1", "--session", "session-1"],
                "prepare_spawn_retry",
            ),
            (
                ["--prepare-communication", "--session", "session-1"],
                "prepare_communication",
            ),
            (["--prepare-interrupt", "--session", "session-1"], "prepare_interrupt"),
            (
                ["--reconcile-interrupted-attempt", "--session", "session-1"],
                "reconcile_interrupted_attempt",
            ),
            (
                ["--record-terminal-notification", "--session", "session-1"],
                "record_terminal_notification",
            ),
            (["--parent-disposition", "--session", "session-1"], "apply_parent_disposition"),
            (["--upsert-group", "--session", "session-1"], "upsert_group"),
        )
        with tempfile.TemporaryDirectory() as directory:
            for arguments, operation in modes:
                with self.subTest(arguments=arguments):
                    scoped_arguments = list(arguments)
                    if scoped_arguments and "--verify-context-manifest" not in scoped_arguments:
                        scoped_arguments.extend(["--data-root", directory])
                    with (
                        mock.patch.object(
                            governance_cli, "_read_json", return_value={}
                        ) as read_json,
                        mock.patch.object(governance, operation, return_value={}),
                    ):
                        returncode, _stdout, stderr = self.invoke(scoped_arguments)
                    self.assertEqual(returncode, 0, stderr)
                    read_json.assert_called_once()

    def test_hook_parse_failure_with_pretooluse_text_fails_open(self):
        raw_input = b'{"note":"PreToolUse",'
        with mock.patch.object(governance, "handle") as handle:
            returncode, stdout, stderr = self.invoke([], raw_input)
        self.assertEqual(returncode, 0, stderr)
        result = json.loads(stdout)
        self.assertTrue(result["continue"])
        self.assertNotIn("hookSpecificOutput", result)
        handle.assert_not_called()

    def test_hook_pretooluse_handler_error_denies_after_successful_parse(self):
        with mock.patch.object(
            governance, "handle", side_effect=RuntimeError("domain failure")
        ):
            returncode, stdout, stderr = self.invoke(
                [], b'{"hook_event_name":"PreToolUse"}'
            )
        self.assertEqual(returncode, 0, stderr)
        result = json.loads(stdout)
        self.assertEqual(
            result["hookSpecificOutput"]["permissionDecision"], "deny"
        )

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
