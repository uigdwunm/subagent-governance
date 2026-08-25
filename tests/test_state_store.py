#!/usr/bin/env python3

import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import governance_errors as errors
from scripts import governance_state_store as state_store
from scripts import governance_storage as storage


class StateStoreSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = state_store.StateStore(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def record(task_ref="0123456789ab"):
        from scripts.governance_contracts import contract_from_input
        from scripts.governance_dispatch import initial_task_record
        from scripts.governance_dispatch_identity import build_task_name

        contract = contract_from_input(
            {"objective": "State safety", "scope": ["tests"], "completion": ["stored"]}
        )
        return initial_task_record(
            task_ref, contract, build_task_name("standard", "state_safety", task_ref), None,
            100, expires_at=400,
        )

    def add_record(self, state, task_id="task"):
        task_ref = "0123456789ab" if task_id == "task" else "abcdefabcdef"
        state["tasks"][task_id] = self.record(task_ref)

    def test_empty_state_is_exact_v9_envelope(self):
        self.assertEqual(
            self.store.read("s"),
            {"state_format_version": 9, "session_id": "s", "tasks": {}},
        )

    def test_corrupt_non_utf8_and_unknown_state_are_preserved(self):
        state_path, _ = self.store._paths("s")
        for original in (b"{broken", b"\xff\xfe", b'{"state_format_version":8,"session_id":"s","tasks":{}}'):
            with self.subTest(original=original[:20]):
                state_path.write_bytes(original)
                state_path.chmod(0o600)
                with self.assertRaises(errors.StateValidationError):
                    self.store.read("s")
                self.assertEqual(state_path.read_bytes(), original)

    def test_symlink_nonregular_and_unsafe_permissions_are_rejected(self):
        state_path, _ = self.store._paths("s")
        target = self.root / "target"
        target.write_text("{}")
        state_path.symlink_to(target)
        with self.assertRaises(errors.StateValidationError):
            self.store.read("s")
        state_path.unlink()
        state_path.mkdir()
        with self.assertRaises(errors.StateValidationError):
            self.store.read("s")
        state_path.rmdir()
        self.store.update("s", self.add_record)
        if os.name != "nt":
            state_path.chmod(0o644)
            before = state_path.read_bytes()
            with self.assertRaises(errors.StateValidationError):
                self.store.read("s")
            self.assertEqual(state_path.read_bytes(), before)
            self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o644)

    @unittest.skipIf(os.name == "nt", "POSIX ownership only")
    def test_owner_mismatch_is_rejected_without_rewrite(self):
        self.store.update("s", self.add_record)
        state_path, _ = self.store._paths("s")
        before = state_path.read_bytes()
        original_lstat = Path.lstat

        def mismatch(path):
            metadata = original_lstat(path)
            if path == state_path:
                return SimpleNamespace(
                    st_mode=metadata.st_mode, st_uid=os.getuid() + 1,
                    st_size=metadata.st_size,
                )
            return metadata

        with mock.patch.object(Path, "lstat", autospec=True, side_effect=mismatch):
            with self.assertRaises(errors.StateValidationError):
                self.store.read("s")
        self.assertEqual(state_path.read_bytes(), before)

    def test_atomic_replace_failure_preserves_previous_state(self):
        self.store.update("s", self.add_record)
        state_path, _ = self.store._paths("s")
        before = state_path.read_bytes()
        with mock.patch.object(storage.os, "replace", side_effect=OSError("injected")):
            with self.assertRaises(errors.StateWriteError):
                self.store.update("s", lambda state: state["tasks"].pop("task"))
        self.assertEqual(state_path.read_bytes(), before)

    def test_compare_and_set_conflict_does_not_write(self):
        self.store.update("s", self.add_record)
        state_path, _ = self.store._paths("s")
        before = state_path.read_bytes()
        callback = mock.Mock()
        with self.assertRaises(errors.StateConflictError):
            self.store.compare_and_set("s", lambda state: False, callback)
        callback.assert_not_called()
        self.assertEqual(state_path.read_bytes(), before)

    def test_capacity_rejection_preserves_previous_state(self):
        self.store.update("s", self.add_record)
        state_path, _ = self.store._paths("s")
        before = state_path.read_bytes()
        with mock.patch.object(state_store, "MAX_STATE_BYTES", len(before) + 10):
            with self.assertRaises(errors.StateCapacityError):
                self.store.update("s", lambda state: self.add_record(state, "other"))
        self.assertEqual(state_path.read_bytes(), before)

    def test_readonly_reader_never_creates_root_or_lock(self):
        missing = self.root / "missing"
        self.assertIsNone(state_store.read_ledger_readonly(missing, "s"))
        self.assertFalse(missing.exists())
        self.store.update("s", self.add_record)
        state_path, lock_path = self.store._paths("s")
        lock_path.unlink()
        before = (state_path.read_bytes(), state_path.stat().st_mtime_ns)
        value = state_store.read_ledger_readonly(self.root, "s")
        self.assertEqual(value["tasks"]["task"]["phase"], "prepared")
        self.assertFalse(lock_path.exists())
        self.assertEqual((state_path.read_bytes(), state_path.stat().st_mtime_ns), before)

    def test_readonly_reader_rejects_symlink_root(self):
        target = self.root / "real"
        target.mkdir(mode=0o700)
        alias = self.root / "alias"
        alias.symlink_to(target, target_is_directory=True)
        with self.assertRaises(errors.StateValidationError):
            state_store.read_ledger_readonly(alias, "s")


if __name__ == "__main__":
    unittest.main()
