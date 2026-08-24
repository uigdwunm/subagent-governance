#!/usr/bin/env python3

"""Direct-import boundaries for the P3 persistence modules."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.support import ROOT
from scripts import governance_state_store as state_store
from scripts import governance_storage as storage
from scripts import governance_store_support as store_support


class StateStoreModuleBoundaryTests(unittest.TestCase):
    def test_package_and_scripts_imports_do_not_prepare_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                **os.environ,
                "SUBAGENT_GOVERNANCE_DATA": str(root / "explicit"),
                "PLUGIN_DATA": "",
            }
            package = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import scripts.governance_store_support; import scripts.governance_state_store",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            scripts = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    f"import sys; sys.path.insert(0, {str(ROOT / 'scripts')!r}); import governance_store_support; import governance_state_store",
                ],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(package.returncode, 0, package.stderr)
            self.assertEqual(scripts.returncode, 0, scripts.stderr)
            self.assertFalse((root / "explicit").exists())

    def test_constructor_prepares_storage_after_direct_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sessions"
            self.assertFalse(root.exists())

            store = state_store.StateStore(root)

            self.assertEqual(store.root, root)
            self.assertTrue(root.is_dir())

    def test_direct_store_preserves_compare_and_set_conflict_without_callback_or_write(self):
        with tempfile.TemporaryDirectory() as directory:
            store = state_store.StateStore(Path(directory))
            state_path, _lock_path = store._paths("session-1")
            store.update("session-1", lambda state: state["health"].update({"status": "degraded"}))
            before = state_path.read_bytes()
            callback = mock.Mock()

            with self.assertRaises(state_store.StateConflictError):
                store.compare_and_set("session-1", lambda state: state["health"]["status"] == "ok", callback)

            callback.assert_not_called()
            self.assertEqual(state_path.read_bytes(), before)

    def test_direct_store_patches_atomic_write_symbol_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            store = state_store.StateStore(Path(directory))
            store.update("session-1", lambda state: state["health"].update({"status": "degraded"}))
            state_path, _lock_path = store._paths("session-1")
            before = state_path.read_bytes()

            with mock.patch.object(storage.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(state_store.StateWriteError):
                    store.update("session-1", lambda state: state["health"].update({"status": "ok"}))

            self.assertEqual(state_path.read_bytes(), before)

    def test_windows_lock_branch_patches_store_support_owner(self):
        windows_api = SimpleNamespace(LK_LOCK=1, LK_UNLCK=2, locking=mock.Mock())
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "windows.lock"
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

    def test_resolver_has_only_current_namespace_for_explicit_installed_cache_and_developer_cases(self):
        explicit = store_support.data_root_path(
            ROOT / "scripts" / "governance_state_store.py",
            environment={"SUBAGENT_GOVERNANCE_DATA": "/tmp/explicit-state", "PLUGIN_DATA": "/tmp/plugin-data"},
        )
        installed = store_support.data_root_path(
            ROOT / "scripts" / "governance_state_store.py",
            environment={"SUBAGENT_GOVERNANCE_DATA": "", "PLUGIN_DATA": "/tmp/plugin-data"},
        )
        cache = store_support.data_root_path(
            Path("/tmp/codex/plugins/cache/personal/example/1.2.3/scripts/entrypoint.py"),
            environment={"SUBAGENT_GOVERNANCE_DATA": "", "PLUGIN_DATA": ""},
        )
        developer = store_support.data_root_path(
            ROOT / "scripts" / "governance_state_store.py",
            environment={"SUBAGENT_GOVERNANCE_DATA": "", "PLUGIN_DATA": ""},
            temporary_directory="/tmp/developer-state",
        )

        self.assertEqual(explicit, Path("/tmp/explicit-state"))
        self.assertEqual(installed, Path("/tmp/plugin-data/state-v6"))
        self.assertEqual(
            cache,
            Path("/tmp/codex/plugins/data/example-personal/state-v6").resolve(),
        )
        self.assertEqual(developer.parent, Path("/tmp/developer-state") / developer.parent.name)
        self.assertEqual(developer.name, "state-v6")
        self.assertNotIn("state-v1", str(developer))
        self.assertTrue(store_support.is_developer_module(ROOT / "scripts" / "governance_state_store.py"))

    def test_store_modules_do_not_import_runtime_entrypoint(self):
        for name in ("governance_state_store.py", "governance_store_support.py"):
            source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertNotIn("subagent_governance", source)


if __name__ == "__main__":
    unittest.main()
