#!/usr/bin/env python3

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import governance_store_support as support
from tests.support import ROOT


class StateStoreModuleBoundaryTests(unittest.TestCase):
    def test_imports_are_side_effect_free(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "explicit"
            result = subprocess.run(
                [sys.executable, "-c", "import scripts.governance_store_support; import scripts.governance_state_store"],
                cwd=ROOT,
                env={**os.environ, "SUBAGENT_GOVERNANCE_DATA": str(target)},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(target.exists())

    def test_namespace_resolution_is_current_only_v9(self):
        installed = support.data_root_path(
            ROOT / "scripts/governance_state_store.py",
            environment={"SUBAGENT_GOVERNANCE_DATA": "", "PLUGIN_DATA": "/tmp/plugin-data"},
        )
        cache = support.data_root_path(
            Path("/tmp/codex/plugins/cache/personal/example/1.2.3/scripts/entrypoint.py"),
            environment={"SUBAGENT_GOVERNANCE_DATA": "", "PLUGIN_DATA": ""},
        )
        self.assertEqual(installed, Path("/tmp/plugin-data/state-v9"))
        self.assertEqual(cache, Path("/tmp/codex/plugins/data/example-personal/state-v9").resolve())
        self.assertNotIn("state-v8", str(installed) + str(cache))

    def test_storage_modules_do_not_import_entrypoint(self):
        for name in ("governance_state_store.py", "governance_store_support.py", "governance_storage.py"):
            self.assertNotIn("subagent_governance", (ROOT / "scripts" / name).read_text())


if __name__ == "__main__":
    unittest.main()
