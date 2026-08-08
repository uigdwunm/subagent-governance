#!/usr/bin/env python3

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/apply_agents_block.py"
CHECK_SCRIPT = ROOT / "scripts/check_installation.py"
SPEC = importlib.util.spec_from_file_location("apply_agents_block", SCRIPT)
tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = tool
SPEC.loader.exec_module(tool)


class ReleaseToolTests(unittest.TestCase):
    def test_apply_agents_block_replaces_only_managed_span(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            asset = root / "asset.md"
            agents.write_text(
                "before\n<!-- subagent-governance:start -->\nold\n<!-- subagent-governance:end -->\nafter\n",
                encoding="utf-8",
            )
            asset.write_text(
                "<!-- subagent-governance:start -->\nnew\n<!-- subagent-governance:end -->\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--execute", "--agents-file", str(agents), "--asset", str(asset)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                agents.read_text(encoding="utf-8"),
                "before\n<!-- subagent-governance:start -->\nnew\n<!-- subagent-governance:end -->\nafter\n",
            )

    def test_atomic_write_preserves_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "AGENTS.md"
            path.write_text("old", encoding="utf-8")
            path.chmod(0o640)
            tool.atomic_write(path, "new")
            self.assertEqual(path.read_text(encoding="utf-8"), "new")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o640)

    def test_installation_check_strict_mode_uses_stable_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            development = root / "development"
            stable = root / "stable"
            cache_parent = root / "cache"
            cache = cache_parent / "0.4.0"
            for plugin_root in (development, stable, cache):
                (plugin_root / ".codex-plugin").mkdir(parents=True)
                (plugin_root / "assets").mkdir()
                (plugin_root / ".codex-plugin/plugin.json").write_text(
                    json.dumps({"version": "0.4.0"}), encoding="utf-8"
                )
                (plugin_root / "assets/agents-governance.md").write_text(
                    "<!-- subagent-governance:start -->\nnew\n<!-- subagent-governance:end -->\n",
                    encoding="utf-8",
                )
            agents = root / "AGENTS.md"
            agents.write_text(
                "before\n<!-- subagent-governance:start -->\nnew\n<!-- subagent-governance:end -->\nafter\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable, str(CHECK_SCRIPT),
                    "--development-root", str(development),
                    "--stable-root", str(stable),
                    "--cache-parent", str(cache_parent),
                    "--agents-file", str(agents),
                    "--legacy-hook", str(root / "missing-hook.py"),
                    "--require-clean",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["clean"])
            self.assertTrue(report["agents_matches_stable_asset"])

            (development / "assets/agents-governance.md").write_text(
                "<!-- subagent-governance:start -->\ndev-only\n<!-- subagent-governance:end -->\n",
                encoding="utf-8",
            )
            result = subprocess.run(result.args, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertIn("development_asset_matches_stable_asset", report["issues"])


if __name__ == "__main__":
    unittest.main()
