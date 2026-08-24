#!/usr/bin/env python3

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.support import load_governance
from scripts import governance_state_store as state_store
from scripts import governance_storage as storage
from scripts import governance_store_support as store_support

governance = load_governance("state_store")


class StateStoreSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = governance.StateStore(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def record(attempt=1, task_ref="0123456789ab"):
        contract = governance.TaskContract(
            semantic_name="state_store", requested_mode="standard",
            resolved_mode="standard", resolution_reason="explicit_request",
            task_features={"risk": "medium", "read_only": False, "writes_files": True, "destructive": False, "production": False, "concurrent_write": False},
            objective="验证 canonical work item", background="S1 local test",
            work_scope=["StateStore"], forbidden_scope=[], completion_conditions=["canonical record exists"],
            evidence_requirements=["unit test"], relevant_files=[], context_manifest={"mode": "none"},
            current_state=None, model=None, reasoning_effort=None, context_strategy="isolated", context_turns=None, context_reason=None,
        )
        return governance._initial_task_record(attempt, task_ref, f"sg_standard_state_store_t_{task_ref}", contract, 100)

    def add_record(self, state, task_id="task"):
        state["tasks"][task_id] = self.record()

    def test_windows_lock_branch_initializes_locks_and_unlocks_one_byte(self):
        windows_api = SimpleNamespace(
            LK_LOCK=1,
            LK_UNLCK=2,
            locking=mock.Mock(),
        )
        lock_path = self.root / "windows.lock"

        with lock_path.open("a+", encoding="utf-8") as lock_file:
            with (
                mock.patch.object(store_support, "uses_windows_file_lock", return_value=True),
                mock.patch.object(store_support, "msvcrt", windows_api),
            ):
                with store_support.exclusive_file_lock(lock_file):
                    self.assertEqual(windows_api.locking.call_count, 1)

        self.assertEqual(lock_path.read_bytes(), b"\0")
        self.assertEqual(
            windows_api.locking.call_args_list,
            [
                mock.call(mock.ANY, windows_api.LK_LOCK, 1),
                mock.call(mock.ANY, windows_api.LK_UNLCK, 1),
            ],
        )

    def test_empty_state_has_versioned_session_envelope(self):
        state = self.store.read("session-1")

        self.assertEqual(
            set(state),
            {
                "state_format_version",
                "session_id",
                "tasks",
                "agents",
                "health",
                "tombstones",
                "groups",
            },
        )
        self.assertEqual(state["session_id"], "session-1")
        self.assertEqual(
            state["state_format_version"], governance.STATE_FORMAT_VERSION
        )

    def test_new_governed_record_uses_canonical_work_item_and_executions(self):
        contract = governance.TaskContract(
            semantic_name="state_store",
            requested_mode="standard",
            resolved_mode="standard",
            resolution_reason="explicit_request",
            task_features={
                "risk": "medium",
                "read_only": False,
                "writes_files": True,
                "destructive": False,
                "production": False,
                "concurrent_write": False,
            },
            objective="验证 canonical work item",
            background="S1 local test",
            work_scope=["StateStore"],
            forbidden_scope=[],
            completion_conditions=["canonical record exists"],
            evidence_requirements=["unit test"],
            relevant_files=[],
            context_manifest={"mode": "none"},
            current_state=None,
            model=None,
            reasoning_effort=None,
            context_strategy="isolated",
            context_turns=None,
            context_reason=None,
        )
        record = governance._initial_task_record(
            1, "0123456789ab", "sg_standard_state_store_t_0123456789ab", contract, 100
        )

        self.assertEqual(record["work_item"]["lifecycle"], "open")
        self.assertEqual(record["work_item"]["current_attempt"], 1)
        self.assertNotIn("task_id", record)
        self.assertNotIn("objective_summary", record["work_item"])
        self.assertNotIn("updated_at", record["work_item"])
        self.assertNotIn("action_required", record["work_item"])
        self.assertNotIn("task_id", record["executions"]["1"])
        self.assertNotIn("attempt", record["executions"]["1"])
        self.assertNotIn("managed", record["executions"]["1"])
        self.assertNotIn("created_at", record["executions"]["1"])
        self.assertNotIn("activity_at", record["executions"]["1"])
        self.assertNotIn("recovery_status", record["executions"]["1"])
        self.assertNotIn("task_id", record["executions"]["1"]["dispatch_record"])
        self.assertNotIn("attempt", record["executions"]["1"]["dispatch_record"])
        self.assertNotIn("task_ref", record["executions"]["1"]["dispatch_record"])
        self.assertNotIn("claimed_at", record["executions"]["1"]["dispatch_record"])
        self.assertNotIn("response_observed_at", record["executions"]["1"]["dispatch_record"])
        self.assertNotIn("bound_task_id", record["executions"]["1"]["observation_record"])
        self.assertNotIn("bound_attempt", record["executions"]["1"]["observation_record"])
        self.assertNotIn("runtime_alias", record["executions"]["1"]["observation_record"])
        self.assertNotIn("binding_basis", record["executions"]["1"]["observation_record"])
        self.assertNotIn("task_id", record["executions"]["1"]["closure_record"])
        self.assertNotIn("attempt", record["executions"]["1"]["closure_record"])

    def test_corrupt_state_stays_in_place_and_is_unavailable(self):
        state_path, _ = self.store._paths("session-1")
        state_path.write_text("{broken", encoding="utf-8")

        with self.assertRaises(governance.StateValidationError):
            self.store.read("session-1")

        self.assertEqual(state_path.read_text(encoding="utf-8"), "{broken")
        self.assertEqual(list(self.root.glob(f"{state_path.name}.corrupt-*")), [])

    def test_non_utf8_state_stays_in_place_and_is_unavailable(self):
        state_path, _ = self.store._paths("session-1")
        original = b"\xff\xfe\x00"
        state_path.write_bytes(original)

        with self.assertRaises(governance.StateValidationError):
            self.store.update("session-1", lambda state: state.update({"unexpected": True}))

        self.assertEqual(state_path.read_bytes(), original)
        self.assertEqual(list(self.root.glob(f"{state_path.name}.corrupt-*")), [])

    def test_non_regular_state_is_not_treated_as_empty(self):
        state_path, _ = self.store._paths("session-1")
        state_path.mkdir()

        with self.assertRaises(governance.StateValidationError):
            self.store.read("session-1")

        self.assertTrue(state_path.is_dir())

    def test_non_regular_lock_is_rejected_and_preserved(self):
        _state_path, lock_path = self.store._paths("session-1")
        lock_path.mkdir()

        with self.assertRaises(governance.StateValidationError):
            self.store.read("session-1")

        self.assertTrue(lock_path.is_dir())

    @unittest.skipIf(os.name == "nt", "Windows does not expose POSIX file ownership")
    def test_lock_owner_mismatch_is_rejected(self):
        _state_path, lock_path = self.store._paths("session-1")
        lock_path.touch(mode=0o600)
        original_fstat = os.fstat

        def mismatched_owner(descriptor):
            metadata = original_fstat(descriptor)
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_uid=os.getuid() + 1,
                st_size=metadata.st_size,
            )

        with mock.patch.object(storage.os, "fstat", side_effect=mismatched_owner):
            with self.assertRaises(governance.StateValidationError):
                self.store.read("session-1")

    @unittest.skipIf(os.name == "nt", "Windows does not expose POSIX file ownership")
    def test_state_owner_mismatch_is_rejected_without_rewriting(self):
        self.store.update("session-1", self.add_record)
        state_path, _ = self.store._paths("session-1")
        original_lstat = Path.lstat

        def mismatched_owner(path):
            metadata = original_lstat(path)
            if path == state_path:
                return SimpleNamespace(
                    st_mode=metadata.st_mode,
                    st_uid=os.getuid() + 1,
                    st_size=metadata.st_size,
                )
            return metadata

        before = state_path.read_bytes()
        with mock.patch.object(Path, "lstat", autospec=True, side_effect=mismatched_owner):
            with self.assertRaises(governance.StateValidationError):
                self.store.read("session-1")
        self.assertEqual(state_path.read_bytes(), before)

    @unittest.skipIf(os.name == "nt", "Windows does not use POSIX group/other mode bits")
    def test_unsafe_state_permissions_are_rejected_without_rewriting(self):
        self.store.update("session-1", self.add_record)
        state_path, _ = self.store._paths("session-1")
        before = state_path.read_bytes()
        state_path.chmod(0o644)

        with self.assertRaises(governance.StateValidationError):
            self.store.read("session-1")

        self.assertEqual(state_path.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o644)

    def test_missing_required_field_is_reported_without_setdefault(self):
        state_path, _ = self.store._paths("session-1")
        value = {
            "session_id": "session-1",
            "agents": {},
            "health": {"status": "ok"},
            "tombstones": {},
        }
        state_path.write_text(json.dumps(value), encoding="utf-8")
        state_path.chmod(0o600)

        with self.assertRaisesRegex(governance.StateValidationError, "tasks"):
            self.store.read("session-1", required_fields=("tasks", "agents"))

        self.assertNotIn("tasks", json.loads(state_path.read_text(encoding="utf-8")))

    def test_unknown_fields_are_rejected_without_rewrite(self):
        state_path, _ = self.store._paths("session-1")
        value = self.store._empty_state("session-1")
        value["future_extension"] = {"opaque": [1, 2, 3]}
        state_path.write_text(json.dumps(value), encoding="utf-8")
        state_path.chmod(0o600)

        before = state_path.read_bytes()
        with self.assertRaisesRegex(governance.StateValidationError, "未知字段"):
            self.store.read("session-1", required_fields=("tasks",))
        self.assertEqual(state_path.read_bytes(), before)

    def test_noncanonical_unresolved_records_are_rejected_on_read(self):
        state_path, _ = self.store._paths("session-1")
        value = self.store._empty_state("session-1")
        value["tasks"]["old"] = {"status": "blocked"}
        state_path.write_text(json.dumps(value), encoding="utf-8")
        state_path.chmod(0o600)
        with self.assertRaises(governance.StateValidationError):
            self.store.read("session-1")

    def test_new_task_soft_limit_rejects_without_overwriting(self):
        self.store.update("session-1", self.add_record)
        state_path, _ = self.store._paths("session-1")
        before = state_path.read_bytes()

        with mock.patch.object(state_store, "NEW_TASK_SOFT_LIMIT_BYTES", len(before) + 1):
            with self.assertRaises(governance.StateCapacityError):
                self.store.update(
                    "session-1",
                    lambda state: self.add_record(state, "new-task"),
                    admission="new_task",
                )

        self.assertEqual(state_path.read_bytes(), before)

    def test_existing_task_can_use_space_above_soft_limit_below_hard_limit(self):
        self.store.update("session-1", self.add_record)
        self.store.update("session-1", lambda state: state["health"].update({"status": "degraded"}))
        self.assertEqual(self.store.read("session-1")["health"]["status"], "degraded")

    def test_hard_limit_rejects_without_overwriting(self):
        self.store.update("session-1", self.add_record)
        state_path, _ = self.store._paths("session-1")
        before = state_path.read_bytes()

        with mock.patch.object(state_store, "MAX_STATE_BYTES", len(before) + 1):
            with self.assertRaises(governance.StateCapacityError):
                self.store.update(
                    "session-1",
                    lambda state: self.add_record(state, "overflow"),
                )

        self.assertEqual(state_path.read_bytes(), before)

    def test_oversized_existing_file_is_unavailable_and_unchanged(self):
        state_path, _ = self.store._paths("session-1")
        original = b"{" + b"x" * state_store.MAX_STATE_BYTES + b"}"
        state_path.write_bytes(original)
        state_path.chmod(0o600)

        with self.assertRaises(governance.StateCapacityError):
            self.store.read("session-1")

        self.assertEqual(state_path.read_bytes(), original)

    def test_compare_and_set_conflict_does_not_call_or_write(self):
        self.store.update("session-1", self.add_record)
        state_path, _ = self.store._paths("session-1")
        before = state_path.read_bytes()
        callback_called = False

        def callback(state):
            nonlocal callback_called
            callback_called = True
            state["health"]["status"] = "degraded"

        with self.assertRaises(governance.StateConflictError):
            self.store.compare_and_set(
                "session-1",
                lambda state: state.get("health", {}).get("status") == "unavailable",
                callback,
            )

        self.assertFalse(callback_called)
        self.assertEqual(state_path.read_bytes(), before)

    def test_compare_and_set_success_is_persisted_and_read_back(self):
        self.store.update("session-1", self.add_record)

        result = self.store.compare_and_set(
            "session-1",
            lambda state: state.get("health", {}).get("status") == "ok",
            lambda state: state["health"].update({"status": "degraded"}) or "committed",
        )

        self.assertEqual(result, "committed")
        self.assertEqual(self.store.read("session-1")["health"]["status"], "degraded")

    def test_atomic_replace_failure_keeps_previous_file(self):
        self.store.update("session-1", self.add_record)
        state_path, _ = self.store._paths("session-1")
        before = state_path.read_bytes()

        with mock.patch.object(storage.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(governance.StateWriteError):
                self.store.update("session-1", lambda state: state["health"].update({"status": "degraded"}))

        self.assertEqual(state_path.read_bytes(), before)

    def test_temporary_write_failure_keeps_previous_file(self):
        self.store.update("session-1", self.add_record)
        state_path, _ = self.store._paths("session-1")
        before = state_path.read_bytes()

        with mock.patch.object(storage.os, "fsync", side_effect=OSError("write fsync failed")):
            with self.assertRaises(governance.StateWriteError):
                self.store.update("session-1", lambda state: state["health"].update({"status": "degraded"}))

        self.assertEqual(state_path.read_bytes(), before)

    def test_readback_failure_is_not_reported_as_success(self):
        self.store.update("session-1", self.add_record)
        original_read = self.store._read_path
        calls = 0

        def fail_second_read(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise governance.StateValidationError("simulated readback failure")
            return original_read(*args, **kwargs)

        with mock.patch.object(self.store, "_read_path", side_effect=fail_second_read):
            with self.assertRaises(governance.StateWriteError):
                self.store.update("session-1", lambda state: state["health"].update({"status": "degraded"}))

    @unittest.skipIf(os.name == "nt", "Windows access control is not represented by POSIX mode bits")
    def test_state_and_lock_permissions_are_private(self):
        self.store.update("session-1", self.add_record)
        state_path, lock_path = self.store._paths("session-1")

        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)

    def test_expired_tombstones_cleanup_is_exact_and_keeps_lock(self):
        now = governance._now()
        def add_state(state):
            self.add_record(state, "unresolved")
            state["tombstones"].update({
                "tenant:task-old:1": {
                    "task_ref": "0123456789ab", "dispatch_target": None,
                    "close_reason": "explicit close",
                    "closed_at": now - governance.RETENTION_SECONDS["tombstone"] - 1,
                },
                "task-recent:2": {
                    "task_ref": "0123456789abcdef", "dispatch_target": None,
                    "close_reason": "explicit close",
                    "closed_at": now - governance.RETENTION_SECONDS["tombstone"] + 1,
                },
            })

        self.store.update("session-1", add_state)
        removed = self.store.cleanup_expired_tombstones(
            "session-1",
            now=now,
        )

        state = self.store.read("session-1")
        _state_path, lock_path = self.store._paths("session-1")
        self.assertEqual(removed, [("tenant:task-old", 1)])
        self.assertNotIn("tenant:task-old:1", state["tombstones"])
        self.assertIn("task-recent:2", state["tombstones"])
        self.assertIn("unresolved", state["tasks"])
        self.assertTrue(lock_path.is_file())

    def test_invalid_tombstone_is_not_guessed_or_deleted(self):
        now = governance._now()

        def add_invalid(state):
            state["tombstones"]["invalid"] = {
                "close_reason": "explicit close",
                "closed_at": now - governance.RETENTION_SECONDS["tombstone"] - 1,
            }

        state_path, _ = self.store._paths("session-1")
        state = self.store._empty_state("session-1")
        add_invalid(state)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        state_path.chmod(0o600)
        with self.assertRaises(governance.StateValidationError):
            self.store.cleanup_expired_tombstones("session-1", now=now)

    def test_delete_keeps_stable_lock_file(self):
        self.store.update("session-1", self.add_record)
        state_path, lock_path = self.store._paths("session-1")

        self.store.delete("session-1")

        self.assertFalse(state_path.exists())
        self.assertTrue(lock_path.is_file())


if __name__ == "__main__":
    unittest.main()
