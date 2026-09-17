"""Fault boundaries: Hook decisions are not platform execution evidence."""
import copy
import io
import json
import os
import socket
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from scripts import governance_cli as cli
from scripts import governance_hook as hook
from scripts import governance_protocol as protocol
from scripts.governance_errors import StateWriteError
from scripts.governance_state_store import StateStore


class HookFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / "sessions")
        self.prepared = protocol.prepare_dispatch(
            {"objective": "test", "scope": ["test"], "completion": ["test"],
             "spawn": {"fork_turns": "none"}},
            "test-session", native_interface="collaboration_turns", state_store=self.store,
            task_id_factory=lambda: "test-task", now=100,
        )
        self.payload = {
            "hook_event_name": "PreToolUse", "tool_name": "spawn_agent",
            "session_id": "test-session", "tool_use_id": "call", "now": 101,
            "tool_input": copy.deepcopy(self.prepared["spawn_args"]),
        }

    def check(self, result, action, code, claim):
        output = result["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], action)
        text = output.get("additionalContext", output.get("permissionDecisionReason"))
        self.assertIn(f"code={code}", text)
        self.assertIn(f"claim={claim}", text)
        self.assertNotIn("SECRET", text)
        return text

    def test_missing_identity_is_not_attempted(self):
        for field, code in (("session_id", "session_unavailable"), ("tool_use_id", "call_id_unavailable")):
            with self.subTest(field=field):
                payload = {**self.payload, field: None}
                with mock.patch.object(hook, "claim_spawn") as claim:
                    self.check(hook.handle_hook(payload, self.store), "allow", code, "not_attempted")
                    claim.assert_not_called()

    def test_unverifiable_shapes_are_visible_without_storage(self):
        for value in (None, [], {**self.payload["tool_input"], "task_name": 3}):
            with self.subTest(value=value):
                with mock.patch.object(hook, "StateStore", side_effect=AssertionError("storage touched")):
                    self.check(hook.handle_hook({**self.payload, "tool_input": value}),
                               "allow", "input_unavailable", "not_attempted")

    def test_unknown_native_fields_are_not_conflicts(self):
        self.payload["tool_input"]["SECRET"] = "SECRET"
        self.check(hook.handle_hook(self.payload, self.store), "allow", "input_unavailable", "unconfirmed")
        self.assertEqual(self.store.read("test-session")["tasks"]["test-task"]["phase"], "prepared")

    def test_known_parameter_conflict_is_denied(self):
        self.payload["tool_input"]["fork_turns"] = "all"
        self.check(hook.handle_hook(self.payload, self.store), "deny", "claim_conflict", "unconfirmed")

    def test_precommit_failure_does_not_claim_commit_unknown(self):
        with mock.patch.object(self.store, "update", side_effect=OSError("SECRET")):
            self.check(hook.handle_hook(self.payload, self.store), "allow", "state_unavailable", "unconfirmed")
        self.assertEqual(self.store.read("test-session")["tasks"]["test-task"]["phase"], "prepared")

    def test_postcommit_recovery_and_unreadable_result(self):
        original = self.store.update

        def commit_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise StateWriteError("SECRET")

        with mock.patch.object(self.store, "update", side_effect=commit_then_fail):
            with mock.patch.object(self.store, "read", side_effect=OSError("SECRET")):
                self.check(hook.handle_hook(self.payload, self.store), "allow", "claim_commit_unknown", "unknown")
        self.assertEqual(self.store.read("test-session")["tasks"]["test-task"]["phase"], "claimed")
        with mock.patch.object(self.store, "update", side_effect=commit_then_fail):
            self.check(hook.handle_hook(self.payload, self.store), "allow", "claimed_after_write_error", "confirmed")

    def test_outer_failure_is_safe_and_does_not_invent_claim(self):
        output = io.StringIO()
        with mock.patch.object(cli, "handle_hook", side_effect=RuntimeError("SECRET")):
            self.assertEqual(cli._hook(io.BytesIO(b'{}'), output), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(set(result), {"systemMessage"})
        self.assertIn("claim=unknown", result["systemMessage"])
        self.assertNotIn("SECRET", output.getvalue())

    def test_unmanaged_does_not_touch_storage(self):
        self.payload["tool_input"] = {"task_name": "ordinary", "message": "SECRET"}
        with mock.patch.object(hook, "StateStore", side_effect=AssertionError("storage touched")):
            self.assertIsNone(hook.handle_hook(self.payload))

    def test_parse_failure_does_not_echo_bytes_or_input(self):
        for raw in (b'[]', b'{"SECRET":', b'\xffSECRET'):
            with self.subTest(raw=raw):
                output = io.StringIO()
                self.assertEqual(cli._hook(io.BytesIO(raw), output), 0)
                result = json.loads(output.getvalue())
                self.assertEqual(set(result), {"systemMessage"})
                self.assertIn("code=input_parse_error", result["systemMessage"])
                self.assertIn("claim=not_attempted", result["systemMessage"])
                self.assertNotIn("SECRET", output.getvalue())

    def test_marker_and_known_native_shape_conflicts(self):
        cases = [
            ({"message": "[subagent-governance:SECRET]"}, "marker_conflict", "not_attempted"),
            ({"task_name": "SECRET"}, "marker_conflict", "not_attempted"),
            ({"fork_turns": False}, "native_conflict", "unconfirmed"),
        ]
        for change, code, claim in cases:
            with self.subTest(change=change):
                payload = {**self.payload, "tool_input": {**self.payload["tool_input"], **change}}
                self.check(hook.handle_hook(payload, self.store), "deny", code, claim)
        self.assertEqual(self.store.read("test-session")["tasks"]["test-task"]["phase"], "prepared")

    def test_state_corruption_is_not_a_contract_conflict(self):
        path, _ = self.store._paths("test-session")
        original = path.read_bytes()
        for raw in (b'SECRET', b'[]', original.replace(b'"state_format_version": 12', b'"state_format_version": 11')):
            with self.subTest(raw=raw[:30]):
                path.write_bytes(raw)
                self.check(hook.handle_hook(self.payload, self.store), "allow", "state_unavailable", "unconfirmed")
                self.assertEqual(path.read_bytes(), raw)
        path.write_bytes(original)

    def test_storage_initialization_and_lock_failure(self):
        with mock.patch.object(hook, "StateStore", side_effect=OSError("SECRET")):
            self.check(hook.handle_hook(self.payload), "allow", "state_unavailable", "not_attempted")
        with mock.patch.object(self.store, "_lock", side_effect=OSError("SECRET")):
            self.check(hook.handle_hook(self.payload, self.store), "allow", "state_unavailable", "unconfirmed")

    def test_write_before_replace_is_conservatively_unknown(self):
        # Entering persistence does not prove whether replacement happened.
        with mock.patch.object(self.store, "_write_path", side_effect=StateWriteError("SECRET")):
            self.check(hook.handle_hook(self.payload, self.store), "allow", "claim_commit_unknown", "unknown")
        self.assertEqual(self.store.read("test-session")["tasks"]["test-task"]["phase"], "prepared")

    def test_material_drift_and_unavailability_remain_distinct(self):
        from scripts import governance_dispatch as dispatch

        root = Path(self.temp.name)
        material = root / "SECRET.txt"
        material.write_text("baseline")
        contract = {"objective": "material", "scope": ["test"], "completion": ["test"],
                    "context": {"verified": {"mode": "declared", "workspace_root": str(root),
                    "baseline": {"kind": "working_tree", "revision": None},
                    "required_paths": [{"path": "SECRET.txt", "type": "file"}]}}}
        prepared = protocol.prepare_dispatch(contract, "material-session", native_interface="fork_context",
                                             state_store=self.store, now=100)
        payload = {**self.payload, "session_id": "material-session", "tool_input": prepared["spawn_args"]}
        material.write_text("changed")
        self.check(hook.handle_hook(payload, self.store), "deny", "material_conflict", "unconfirmed")
        material.unlink()
        self.check(hook.handle_hook(payload, self.store), "deny", "material_conflict", "unconfirmed")
        material.write_text("baseline")
        with mock.patch.object(dispatch, "verify_context_manifest", side_effect=PermissionError("SECRET")):
            self.check(hook.handle_hook(payload, self.store), "allow", "material_unavailable", "unconfirmed")

    def test_material_missing_type_and_io_boundaries(self):
        from scripts import governance_context as context
        from scripts.governance_errors import DispatchPreparationError

        for scenario in ("deleted", "directory", "ancestor_file", "root_deleted", "root_file",
                         "open_missing", "open_directory", "fstat_directory", "stat_missing",
                         "permission", "stat_permission", "io_error", "timeout"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "workspace"
                (root / "sub").mkdir(parents=True)
                material = root / "sub" / "input.txt"
                material.write_text("baseline")
                contract = {"profile": "strict", "objective": "material", "scope": ["test"],
                            "forbidden_scope": ["external writes"], "evidence": ["verification"],
                            "completion": ["test"], "context": {"verified": {
                                "mode": "declared", "workspace_root": str(root),
                                "baseline": {"kind": "working_tree", "revision": None},
                                "required_paths": [{"path": "sub/input.txt", "type": "file"}]}}}
                session = "material-" + scenario
                prepared = protocol.prepare_dispatch(contract, session, native_interface="fork_context",
                                                     state_store=self.store, now=100)
                payload = {**self.payload, "session_id": session, "tool_input": prepared["spawn_args"]}
                with ExitStack() as stack:
                    if scenario in {"deleted", "directory", "ancestor_file", "root_deleted", "root_file"}:
                        material.unlink()
                        if scenario == "directory":
                            material.mkdir()
                        elif scenario in {"ancestor_file", "root_deleted", "root_file"}:
                            material.parent.rmdir()
                            if scenario == "ancestor_file":
                                material.parent.write_text("file")
                            else:
                                root.rmdir()
                                if scenario == "root_file":
                                    root.write_text("file")
                    elif scenario == "stat_permission":
                        real_stat = Path.stat
                        resolved_material = material.resolve()
                        def stat_material(path, *args, **kwargs):
                            if path == resolved_material:
                                raise PermissionError("SECRET")
                            return real_stat(path, *args, **kwargs)
                        stack.enter_context(mock.patch.object(Path, "stat", stat_material))
                    elif scenario in {"open_missing", "open_directory", "permission", "io_error"}:
                        error = {"open_missing": FileNotFoundError, "open_directory": IsADirectoryError,
                                 "permission": PermissionError, "io_error": OSError}[scenario]
                        real_open = context.os.open
                        def open_material(path, *args, **kwargs):
                            if Path(path) == material.resolve():
                                raise error("SECRET")
                            return real_open(path, *args, **kwargs)
                        stack.enter_context(mock.patch.object(context.os, "open", side_effect=open_material))
                    elif scenario in {"fstat_directory", "stat_missing"}:
                        real_open, real_fstat = context.os.open, context.os.fstat
                        descriptors, calls = set(), []
                        directory_stat = root.stat()
                        def open_material(path, *args, **kwargs):
                            fd = real_open(path, *args, **kwargs)
                            if Path(path) == material.resolve():
                                descriptors.add(fd)
                            return fd
                        def fstat(fd):
                            if fd in descriptors:
                                calls.append(fd)
                                if scenario == "fstat_directory":
                                    return directory_stat
                                if len(calls) == 2:
                                    material.unlink()
                            return real_fstat(fd)
                        stack.enter_context(mock.patch.object(context.os, "open", side_effect=open_material))
                        stack.enter_context(mock.patch.object(context.os, "fstat", side_effect=fstat))
                    else:
                        stack.enter_context(mock.patch.object(context, "VERIFICATION_BUDGET_SECONDS", -1))
                    unavailable = scenario in {"permission", "stat_permission", "io_error", "timeout"}
                    self.check(hook.handle_hook(payload, self.store),
                               "allow" if unavailable else "deny",
                               "material_unavailable" if unavailable else "material_conflict", "unconfirmed")
                self.assertEqual(self.store.read(session)["tasks"][prepared["task_id"]]["phase"], "prepared")
                if scenario == "deleted":
                    with self.assertRaises(DispatchPreparationError):
                        protocol.prepare_dispatch(contract, "initial-missing", native_interface="fork_context",
                                                  state_store=self.store, now=100)
                    self.assertFalse(self.store._paths("initial-missing")[0].exists())

    @unittest.skipUnless(os.name == "posix" and hasattr(socket, "AF_UNIX"), "requires Unix sockets")
    def test_socket_replacement_before_stat_and_before_open(self):
        from scripts import governance_context as context

        for timing in ("before_stat", "before_open", "recheck_permission", "recheck_io"):
            with self.subTest(timing=timing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                material = root / "s"
                material.write_text("baseline")
                contract = {"objective": "material", "scope": ["test"], "completion": ["test"],
                            "context": {"verified": {"mode": "declared", "workspace_root": str(root),
                                "baseline": {"kind": "working_tree", "revision": None},
                                "required_paths": [{"path": "s", "type": "file"}]}}}
                session = "socket-" + timing
                prepared = protocol.prepare_dispatch(contract, session, native_interface="fork_context",
                                                     state_store=self.store, now=100)
                payload = {**self.payload, "session_id": session, "tool_input": prepared["spawn_args"]}
                real_open, real_lstat = context.os.open, Path.lstat
                attempted = []
                with socket.socket(socket.AF_UNIX) as endpoint:
                    def replace():
                        material.unlink()
                        endpoint.bind(str(material))
                    def open_material(path, *args, **kwargs):
                        if Path(path) == material:
                            replace()
                            attempted.append(path)
                        return real_open(path, *args, **kwargs)
                    def lstat_material(path, *args, **kwargs):
                        if path == material and attempted:
                            if timing == "recheck_permission":
                                raise PermissionError("SECRET")
                            if timing == "recheck_io":
                                raise OSError("SECRET")
                        return real_lstat(path, *args, **kwargs)
                    with ExitStack() as stack:
                        if timing == "before_stat":
                            replace()
                        else:
                            stack.enter_context(mock.patch.object(context.os, "open", side_effect=open_material))
                            stack.enter_context(mock.patch.object(Path, "lstat", lstat_material))
                        unavailable = timing.startswith("recheck_")
                        self.check(hook.handle_hook(payload, self.store), "allow" if unavailable else "deny",
                                   "material_unavailable" if unavailable else "material_conflict", "unconfirmed")
                    if timing != "before_stat":
                        self.assertEqual(len(attempted), 1)
                self.assertEqual(self.store.read(session)["tasks"][prepared["task_id"]]["phase"], "prepared")

    def test_unknown_interface_in_ledger_is_not_provider_conflict(self):
        path, _ = self.store._paths("test-session")
        state = json.loads(path.read_text())
        state["tasks"]["test-task"]["native_interface"] = "SECRET"
        path.write_text(json.dumps(state))
        self.check(hook.handle_hook(self.payload, self.store), "allow", "state_unavailable", "unconfirmed")

    def test_strict_has_same_failure_policy(self):
        prepared = protocol.prepare_dispatch(
            {"profile": "strict", "objective": "test", "scope": ["test"], "completion": ["test"],
             "forbidden_scope": ["external"], "evidence": ["tests"]},
            "strict-session", native_interface="fork_context", state_store=self.store, now=100,
        )
        payload = {**self.payload, "session_id": "strict-session", "tool_input": prepared["spawn_args"]}
        with mock.patch.object(self.store, "update", side_effect=OSError("SECRET")):
            self.check(hook.handle_hook(payload, self.store), "allow", "state_unavailable", "unconfirmed")

    def test_internal_fault_is_safe_and_missing_claim_still_reconciles(self):
        from scripts import governance_dispatch as dispatch

        with mock.patch.object(self.store, "update", side_effect=RuntimeError("SECRET")):
            self.check(hook.handle_hook(self.payload, self.store), "allow", "internal_error", "unconfirmed")
        result = dispatch.confirm_dispatch(
            "test-session", {"task_id": "test-task", "task_ref": self.prepared["task_ref"], "target": "actual-return"},
            state_store=self.store, now=102,
        )
        self.assertEqual(result["result"], "reconcile")
        task = self.store.read("test-session")["tasks"]["test-task"]
        self.assertEqual(task["reconcile"]["code"], "dispatch_claim_missing")
        self.assertIsNone(task.get("target"))

    def test_outer_exception_after_commit_reports_unknown(self):
        original = cli.handle_hook

        def handle_then_fail(payload):
            original(payload, self.store)
            raise RuntimeError("SECRET")

        output = io.StringIO()
        with mock.patch.object(cli, "handle_hook", side_effect=handle_then_fail):
            cli._hook(io.BytesIO(json.dumps(self.payload).encode()), output)
        result = json.loads(output.getvalue())
        self.assertEqual(set(result), {"systemMessage"})
        self.assertIn("claim=unknown", result["systemMessage"])
        self.assertNotIn("SECRET", output.getvalue())
        self.assertEqual(self.store.read("test-session")["tasks"]["test-task"]["phase"], "claimed")

    def test_failed_write_cannot_recover_another_call_claim(self):
        other_claim = self.store.read("test-session")
        task = other_claim["tasks"]["test-task"]
        task.update(phase="claimed", claimed_tool_use_id="other-call", claimed_at=101)
        with mock.patch.object(self.store, "_write_path", side_effect=StateWriteError("SECRET")):
            with mock.patch.object(self.store, "read", return_value=other_claim):
                self.check(hook.handle_hook(self.payload, self.store), "allow", "claim_commit_unknown", "unknown")
        self.assertEqual(self.store.read("test-session")["tasks"]["test-task"]["phase"], "prepared")

    def test_envelope_extensions_are_ignored_and_normal_claim_confirmed(self):
        self.payload["SECRET"] = "SECRET"
        self.check(hook.handle_hook(self.payload, self.store), "allow", "claimed", "confirmed")
        self.check(hook.handle_hook(self.payload, self.store), "allow", "already_claimed", "confirmed")
        self.payload["tool_use_id"] = "another-call"
        self.check(hook.handle_hook(self.payload, self.store), "deny", "claim_conflict", "unconfirmed")

    def test_unknown_tool_or_event_stays_inert(self):
        for change in ({"tool_name": "unknown.spawn_agent"}, {"hook_event_name": "UnknownEvent"}):
            with self.subTest(change=change):
                with mock.patch.object(hook, "StateStore", side_effect=AssertionError("storage touched")):
                    self.assertIsNone(hook.handle_hook({**self.payload, **change}))
