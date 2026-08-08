#!/usr/bin/env python3

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/apply_agents_block.py"
CHECK_SCRIPT = ROOT / "scripts/check_installation.py"
SPEC = importlib.util.spec_from_file_location("apply_agents_block", SCRIPT)
tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = tool
SPEC.loader.exec_module(tool)
REINSTALL_SCRIPT = ROOT / "scripts/reinstall_preserving_caches.py"
REINSTALL_SPEC = importlib.util.spec_from_file_location("reinstall_preserving_caches", REINSTALL_SCRIPT)
reinstall_tool = importlib.util.module_from_spec(REINSTALL_SPEC)
assert REINSTALL_SPEC.loader is not None
sys.path.insert(0, str(ROOT / "scripts"))
REINSTALL_SPEC.loader.exec_module(reinstall_tool)


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
            home = root / "home"
            development = home / "workspace" / "subagent-governance"
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
            active_hooks_config = root / "hooks.json"
            active_hooks_config.write_text('{"hooks": {}}', encoding="utf-8")
            agents.write_text(
                "before\n<!-- subagent-governance:start -->\nnew\n<!-- subagent-governance:end -->\nafter\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable, str(CHECK_SCRIPT),
                    "--stable-root", str(stable),
                    "--cache-parent", str(cache_parent),
                    "--agents-file", str(agents),
                    "--legacy-hook", str(root / "missing-hook.py"),
                    "--active-hooks-config", str(active_hooks_config),
                    "--require-clean",
                ],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "HOME": str(home)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["clean"])
            self.assertTrue(report["agents_matches_stable_asset"])

            (development / "assets/agents-governance.md").write_text(
                "<!-- subagent-governance:start -->\ndev-only\n<!-- subagent-governance:end -->\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                result.args,
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "HOME": str(home)},
            )
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertIn("development_asset_matches_stable_asset", report["issues"])

    def test_installation_check_allows_and_reports_retained_compatibility_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            development = root / "development"
            stable = root / "stable"
            cache_parent = root / "cache"
            current_cache = cache_parent / "0.4.0"
            retained_cache = cache_parent / "0.1.0"
            for plugin_root in (development, stable, current_cache):
                (plugin_root / ".codex-plugin").mkdir(parents=True)
                (plugin_root / "assets").mkdir()
                (plugin_root / ".codex-plugin/plugin.json").write_text(
                    json.dumps({"version": "0.4.0"}), encoding="utf-8"
                )
                (plugin_root / "assets/agents-governance.md").write_text(
                    "<!-- subagent-governance:start -->\nnew\n<!-- subagent-governance:end -->\n",
                    encoding="utf-8",
                )
            retained_cache.mkdir(parents=True)
            (retained_cache / "runtime-marker").write_text("active older task", encoding="utf-8")
            agents = root / "AGENTS.md"
            legacy_hook = root / "subagent_policy.py"
            legacy_hook.write_text("# retained for open tasks\n", encoding="utf-8")
            active_hooks_config = root / "hooks.json"
            active_hooks_config.write_text('{"hooks": {}}', encoding="utf-8")
            agents.write_text(
                "<!-- subagent-governance:start -->\nnew\n<!-- subagent-governance:end -->\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable, str(CHECK_SCRIPT),
                    "--development-root", str(development),
                    "--stable-root", str(stable),
                    "--cache-parent", str(cache_parent),
                    "--agents-file", str(agents),
                    "--legacy-hook", str(legacy_hook),
                    "--active-hooks-config", str(active_hooks_config),
                    "--require-clean",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["clean"])
            self.assertEqual(report["retained_compatibility_caches"], [str(retained_cache)])
            self.assertEqual(report["invalid_cache_entries"], [])
            self.assertTrue(report["legacy_hook_present"])
            self.assertFalse(report["legacy_hook_mounted"])

            unsafe_entry = cache_parent / "unexpected-file"
            unsafe_entry.write_text("not a versioned cache directory", encoding="utf-8")
            result = subprocess.run(result.args, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertIn("cache_entries_safe", report["issues"])
            self.assertEqual(report["invalid_cache_entries"], [str(unsafe_entry)])

            unsafe_entry.unlink()
            active_hooks_config.write_text(
                json.dumps({"command": f"python3 {legacy_hook}"}), encoding="utf-8"
            )
            result = subprocess.run(result.args, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertIn("legacy_hook_unmounted", report["issues"])
            self.assertTrue(report["legacy_hook_mounted"])

    def test_reinstall_restores_caches_pruned_by_codex(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshot_parent = root / "snapshots"
            for version in ("0.1.0", "0.4.0-rc.1"):
                cache = cache_parent / version
                cache.mkdir(parents=True)
                (cache / "marker").write_text(version, encoding="utf-8")

            def fake_codex(command, check):
                self.assertEqual(command, ["codex", "plugin", "add", "subagent-governance@personal"])
                self.assertFalse(check)
                for cache in list(cache_parent.iterdir()):
                    shutil.rmtree(cache)
                current = cache_parent / "0.4.0-rc.4"
                current.mkdir()
                (current / "marker").write_text("current", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            returncode, report = reinstall_tool.reinstall(
                cache_parent,
                snapshot_parent,
                ["codex", "plugin", "add", "subagent-governance@personal"],
                runner=fake_codex,
            )

            self.assertEqual(returncode, 0)
            self.assertEqual(
                sorted(path.name for path in cache_parent.iterdir()),
                ["0.1.0", "0.4.0-rc.1", "0.4.0-rc.4"],
            )
            self.assertEqual(report["restored_caches"], ["0.1.0", "0.4.0-rc.1"])
            self.assertEqual(list(snapshot_parent.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
