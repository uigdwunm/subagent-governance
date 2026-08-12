#!/usr/bin/env python3

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
import json
import shutil
from pathlib import Path
from unittest import mock


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
            second = subprocess.run(result.args, capture_output=True, text=True, check=False)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(
                agents.read_text(encoding="utf-8"),
                "before\n<!-- subagent-governance:start -->\nnew\n<!-- subagent-governance:end -->\nafter\n",
            )

    def test_apply_agents_block_initializes_and_removes_managed_span(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            asset = root / "asset.md"
            asset.write_text(
                "<!-- subagent-governance:start -->\nentry\n<!-- subagent-governance:end -->\n",
                encoding="utf-8",
            )

            install = subprocess.run(
                [sys.executable, str(SCRIPT), "--execute", "--agents-file", str(agents), "--asset", str(asset)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertEqual(agents.read_text(encoding="utf-8"), asset.read_text(encoding="utf-8").strip() + "\n")

            remove = subprocess.run(
                [sys.executable, str(SCRIPT), "--remove", "--agents-file", str(agents)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(remove.returncode, 0, remove.stderr)
            self.assertEqual(agents.read_text(encoding="utf-8"), "")

    def test_apply_agents_block_appends_and_removes_without_overwriting_user_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            asset = root / "asset.md"
            agents.write_text("# Existing rules\n\nKeep this content.\n", encoding="utf-8")
            asset.write_text(
                "<!-- subagent-governance:start -->\nentry\n<!-- subagent-governance:end -->\n",
                encoding="utf-8",
            )

            install = subprocess.run(
                [sys.executable, str(SCRIPT), "--execute", "--agents-file", str(agents), "--asset", str(asset)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertEqual(
                agents.read_text(encoding="utf-8"),
                "# Existing rules\n\nKeep this content.\n\n"
                "<!-- subagent-governance:start -->\nentry\n<!-- subagent-governance:end -->\n",
            )

            remove = subprocess.run(
                [sys.executable, str(SCRIPT), "--remove", "--agents-file", str(agents)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(remove.returncode, 0, remove.stderr)
            self.assertEqual(
                agents.read_text(encoding="utf-8"),
                "# Existing rules\n\nKeep this content.\n",
            )

    def test_public_marketplace_defaults_resolve_cache_and_plugin_spec(self):
        marketplace = "subagent-governance"
        self.assertEqual(
            reinstall_tool.plugin_spec(marketplace),
            "subagent-governance@subagent-governance",
        )
        self.assertEqual(
            reinstall_tool.default_cache_parent(marketplace),
            Path.home() / ".codex/plugins/cache/subagent-governance/subagent-governance",
        )

    @unittest.skipIf(os.name == "nt", "Windows does not preserve POSIX mode bits")
    def test_atomic_write_preserves_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "AGENTS.md"
            path.write_text("old", encoding="utf-8")
            path.chmod(0o640)
            tool.atomic_write(path, "new")
            self.assertEqual(path.read_text(encoding="utf-8"), "new")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o640)

    @unittest.skipIf(os.name == "nt", "Windows does not use POSIX group/other mode bits")
    def test_atomic_write_rejects_unsafe_file_and_parent_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "codex"
            parent.mkdir(mode=0o700)
            path = parent / "AGENTS.md"
            path.write_text("old", encoding="utf-8")

            path.chmod(0o620)
            with self.assertRaisesRegex(PermissionError, "组用户或其他用户写入"):
                tool.atomic_write(path, "new")
            self.assertEqual(path.read_text(encoding="utf-8"), "old")

            path.chmod(0o600)
            parent.chmod(0o720)
            with self.assertRaisesRegex(PermissionError, "父目录.*组用户或其他用户写入"):
                tool.atomic_write(path, "new")
            self.assertEqual(path.read_text(encoding="utf-8"), "old")

    @unittest.skipIf(os.name == "nt", "Windows does not use POSIX group/other mode bits")
    def test_apply_rejects_unsafe_asset_file_and_parent_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents_parent = root / "codex"
            asset_parent = root / "stable-assets"
            agents_parent.mkdir(mode=0o700)
            asset_parent.mkdir(mode=0o700)
            agents = agents_parent / "AGENTS.md"
            asset = asset_parent / "agents-governance.md"
            block = "<!-- subagent-governance:start -->\nentry\n<!-- subagent-governance:end -->\n"
            agents.write_text(block, encoding="utf-8")
            asset.write_text(block, encoding="utf-8")
            command = [
                sys.executable,
                str(SCRIPT),
                "--check",
                "--agents-file",
                str(agents),
                "--asset",
                str(asset),
            ]

            asset.chmod(0o664)
            unsafe_file = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(unsafe_file.returncode, 2)
            self.assertIn("治理规则资产不能允许组用户或其他用户写入", unsafe_file.stderr)

            asset.chmod(0o644)
            asset_parent.chmod(0o720)
            unsafe_parent = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(unsafe_parent.returncode, 2)
            self.assertIn("治理规则资产父目录不能允许组用户或其他用户写入", unsafe_parent.stderr)
            self.assertEqual(agents.read_text(encoding="utf-8"), block)

    def test_managed_span_rejects_invalid_marker_layouts(self):
        invalid_values = (
            "no markers",
            "<!-- subagent-governance:start -->\nmissing end",
            "<!-- subagent-governance:end -->\n<!-- subagent-governance:start -->",
            (
                "<!-- subagent-governance:start -->\n"
                "<!-- subagent-governance:start -->\n"
                "<!-- subagent-governance:end -->"
            ),
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                tool.managed_span(value)

    def test_execute_rejects_invalid_asset_without_changing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            asset = root / "asset.md"
            original = (
                "before\n<!-- subagent-governance:start -->\nold\n"
                "<!-- subagent-governance:end -->\nafter\n"
            )
            agents.write_text(original, encoding="utf-8")
            asset.write_text(
                "unexpected\n<!-- subagent-governance:start -->\nnew\n"
                "<!-- subagent-governance:end -->\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--execute", "--agents-file", str(agents), "--asset", str(asset)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("资产文件只能包含治理标记区间", result.stderr)
            self.assertEqual(agents.read_text(encoding="utf-8"), original)

    @unittest.skipIf(os.name == "nt", "Windows symlink creation may require elevated privileges")
    def test_execute_rejects_symlink_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_agents = root / "real-AGENTS.md"
            agents = root / "AGENTS.md"
            asset = root / "asset.md"
            original = "<!-- subagent-governance:start -->\nold\n<!-- subagent-governance:end -->\n"
            real_agents.write_text(original, encoding="utf-8")
            agents.symlink_to(real_agents)
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
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("符号链接", result.stderr)
            self.assertEqual(real_agents.read_text(encoding="utf-8"), original)

    @unittest.skipIf(os.name == "nt", "Windows does not expose POSIX file ownership")
    def test_atomic_write_rejects_owner_mismatch_and_concurrent_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "AGENTS.md"
            path.write_text("old", encoding="utf-8")
            with mock.patch.object(tool.os, "getuid", return_value=os.getuid() + 1):
                with self.assertRaises(PermissionError):
                    tool.atomic_write(path, "new")

            expected_digest = tool.content_digest("old")
            path.write_text("changed elsewhere", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "读取后发生变化"):
                tool.atomic_write(path, "new", expected_digest=expected_digest)
            self.assertEqual(path.read_text(encoding="utf-8"), "changed elsewhere")

    def test_check_reports_paths_hashes_and_optional_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            asset = root / "asset.md"
            agents.write_text(
                "<!-- subagent-governance:start -->\nsame\n<!-- subagent-governance:end -->\n",
                encoding="utf-8",
            )
            asset.write_text(agents.read_text(encoding="utf-8"), encoding="utf-8")
            command = [
                sys.executable, str(SCRIPT), "--check", "--agents-file", str(agents), "--asset", str(asset),
            ]
            matching = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(matching.returncode, 0, matching.stderr)
            self.assertIn(f"agents_file: {agents}", matching.stdout)
            self.assertIn(f"asset_file: {asset}", matching.stdout)
            self.assertIn("managed_sha256:", matching.stdout)

            asset.write_text(
                "<!-- subagent-governance:start -->\nnew\n<!-- subagent-governance:end -->\n",
                encoding="utf-8",
            )
            differing = subprocess.run(command + ["--diff"], capture_output=True, text=True, check=False)
            self.assertEqual(differing.returncode, 1, differing.stderr)
            self.assertIn("agents_managed_sha256:", differing.stdout)
            self.assertIn("asset_managed_sha256:", differing.stdout)
            self.assertIn("--- current managed block", differing.stdout)
            self.assertIn("+++ asset managed block", differing.stdout)

    def test_installation_check_separates_runtime_and_development_sync(self):
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
                    "--development-root", str(development),
                    "--stable-root", str(stable),
                    "--cache-parent", str(cache_parent),
                    "--agents-file", str(agents),
                    "--legacy-hook", str(root / "missing-hook.py"),
                    "--active-hooks-config", str(active_hooks_config),
                    "--require-development-sync",
                ],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "HOME": str(home)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["runtime_healthy"])
            self.assertTrue(report["deployment_in_sync"])
            self.assertTrue(report["development_rules_in_sync"])
            self.assertIsNone(report["release_ready"])
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
            self.assertTrue(report["runtime_healthy"])
            self.assertTrue(report["deployment_in_sync"])
            self.assertFalse(report["development_rules_in_sync"])
            self.assertIn("development_rules_not_deployed", report["warnings"])

            runtime_only = subprocess.run(
                result.args[:-1],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "HOME": str(home)},
            )
            self.assertEqual(runtime_only.returncode, 0, runtime_only.stderr)

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
                    "--require-retention-policy",
                    "--expected-previous-version", retained_cache.name,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["runtime_healthy"])
            self.assertTrue(report["retention_policy_satisfied"])
            self.assertEqual(report["retained_cache_count"], 1)
            self.assertEqual(report["retained_compatibility_caches"], [str(retained_cache)])
            self.assertTrue(report["retained_previous_cache_matches_expected"])
            self.assertEqual(report["invalid_cache_entries"], [])
            self.assertTrue(report["legacy_hook_present"])
            self.assertFalse(report["legacy_hook_mounted"])
            valid_args = list(result.args)

            extra_cache = cache_parent / "0.2.0"
            extra_cache.mkdir()
            result = subprocess.run(valid_args, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertTrue(report["runtime_healthy"])
            self.assertFalse(report["retention_policy_satisfied"])
            self.assertEqual(report["retained_cache_count"], 2)
            self.assertIn("retention_window_exceeded", report["warnings"])
            extra_cache.rmdir()

            wrong_expected = list(valid_args)
            wrong_expected[-1] = "0.2.0"
            result = subprocess.run(wrong_expected, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertFalse(report["retention_policy_satisfied"])
            self.assertFalse(report["retained_previous_cache_matches_expected"])
            self.assertIn("retained_previous_cache_mismatch", report["warnings"])

            unsafe_entry = cache_parent / "unexpected-file"
            unsafe_entry.write_text("not a versioned cache directory", encoding="utf-8")
            result = subprocess.run(valid_args, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertFalse(report["runtime_healthy"])
            self.assertIn("cache_entries_safe", report["runtime_issues"])
            self.assertEqual(report["invalid_cache_entries"], [str(unsafe_entry)])

            unsafe_entry.unlink()
            active_hooks_config.write_text(
                json.dumps({"command": f"python3 {legacy_hook}"}), encoding="utf-8"
            )
            result = subprocess.run(valid_args, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertFalse(report["runtime_healthy"])
            self.assertIn("legacy_hook_unmounted", report["runtime_issues"])
            self.assertTrue(report["legacy_hook_mounted"])

            escaped_legacy_hook = root / r"hooks\subagent_policy.py"
            escaped_legacy_hook.parent.mkdir(parents=True, exist_ok=True)
            escaped_legacy_hook.write_text("# Windows-style path\n", encoding="utf-8")
            escaped_args = list(valid_args)
            legacy_hook_index = escaped_args.index("--legacy-hook") + 1
            escaped_args[legacy_hook_index] = str(escaped_legacy_hook)
            active_hooks_config.write_text(
                json.dumps({"command": f"python3 {escaped_legacy_hook}"}), encoding="utf-8"
            )
            escaped_result = subprocess.run(
                escaped_args, capture_output=True, text=True, check=False
            )
            self.assertEqual(escaped_result.returncode, 1)
            escaped_report = json.loads(escaped_result.stdout)
            self.assertIn("legacy_hook_unmounted", escaped_report["runtime_issues"])
            self.assertTrue(escaped_report["legacy_hook_mounted"])

    def test_installation_check_reports_manifest_and_marker_errors_as_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            development = root / "development"
            stable = root / "stable"
            cache_parent = root / "cache"
            for plugin_root in (development, stable):
                (plugin_root / ".codex-plugin").mkdir(parents=True)
                (plugin_root / "assets").mkdir()
                (plugin_root / "assets/agents-governance.md").write_text(
                    "<!-- subagent-governance:start -->\nrules\n<!-- subagent-governance:end -->\n",
                    encoding="utf-8",
                )
            (stable / ".codex-plugin/plugin.json").write_text(
                json.dumps({"version": 4}),
                encoding="utf-8",
            )
            cache_parent.mkdir()
            agents = root / "AGENTS.md"
            agents.write_text("", encoding="utf-8")
            command = [
                sys.executable,
                str(CHECK_SCRIPT),
                "--development-root",
                str(development),
                "--stable-root",
                str(stable),
                "--cache-parent",
                str(cache_parent),
                "--agents-file",
                str(agents),
                "--legacy-hook",
                str(root / "legacy.py"),
                "--active-hooks-config",
                str(root / "hooks.json"),
            ]

            invalid_manifest = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(invalid_manifest.returncode, 1)
            report = json.loads(invalid_manifest.stdout)
            self.assertFalse(report["runtime_healthy"])
            self.assertEqual(report["runtime_issues"], ["check_failed"])
            self.assertIn("version 必须是非空字符串", report["fatal_error"]["message"])
            self.assertEqual(invalid_manifest.stderr, "")

            (stable / ".codex-plugin/plugin.json").write_text(
                json.dumps({"version": "0.4.0"}),
                encoding="utf-8",
            )
            current_cache = cache_parent / "0.4.0"
            shutil.copytree(stable, current_cache)
            invalid_rules = "<!-- subagent-governance:end -->\nrules\n<!-- subagent-governance:start -->\n"
            for path in (
                stable / "assets/agents-governance.md",
                current_cache / "assets/agents-governance.md",
            ):
                path.write_text(invalid_rules, encoding="utf-8")
            agents.write_text(invalid_rules, encoding="utf-8")

            invalid_markers = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(invalid_markers.returncode, 1)
            report = json.loads(invalid_markers.stdout)
            self.assertFalse(report["runtime_healthy"])
            self.assertIn("agents_matches_stable_asset", report["runtime_issues"])
            self.assertNotIn("fatal_error", report)

    @unittest.skipIf(os.name == "nt", "Windows permission and symlink checks use different OS semantics")
    def test_installation_check_validates_retained_cache_tree_and_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            development = root / "development"
            stable = root / "stable"
            cache_parent = root / "cache"
            current_cache = cache_parent / "0.4.0"
            for plugin_root in (development, stable, current_cache):
                (plugin_root / ".codex-plugin").mkdir(parents=True)
                (plugin_root / "assets").mkdir()
                (plugin_root / ".codex-plugin/plugin.json").write_text(
                    json.dumps({"version": "0.4.0"}),
                    encoding="utf-8",
                )
                (plugin_root / "assets/agents-governance.md").write_text(
                    "<!-- subagent-governance:start -->\nrules\n<!-- subagent-governance:end -->\n",
                    encoding="utf-8",
                )
            retained = cache_parent / "0.3.0"
            retained.mkdir()
            retained.chmod(0o777)
            agents = root / "AGENTS.md"
            agents.write_text(
                "<!-- subagent-governance:start -->\nrules\n<!-- subagent-governance:end -->\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECK_SCRIPT),
                    "--development-root",
                    str(development),
                    "--stable-root",
                    str(stable),
                    "--cache-parent",
                    str(cache_parent),
                    "--agents-file",
                    str(agents),
                    "--legacy-hook",
                    str(root / "legacy.py"),
                    "--active-hooks-config",
                    str(root / "hooks.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertFalse(report["runtime_healthy"])
            self.assertEqual(report["invalid_cache_entries"], [str(retained)])
            self.assertIn("组用户或其他用户写入", report["invalid_cache_details"][0]["error"])

            retained.chmod(0o700)
            target = retained / "marker"
            target.write_text("safe", encoding="utf-8")
            link = retained / "unsafe-link"
            link.symlink_to(target)
            result = subprocess.run(result.args, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertEqual(report["invalid_cache_entries"], [str(retained)])
            self.assertIn("符号链接", report["invalid_cache_details"][0]["error"])

    def test_reinstall_restores_previous_cache_pruned_by_codex(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshot_parent = root / "snapshots"
            previous = cache_parent / "0.4.0-rc.1"
            previous.mkdir(parents=True)
            (previous / "marker").write_text(previous.name, encoding="utf-8")
            obsolete = cache_parent / "0.1.0"
            obsolete.mkdir()
            (obsolete / "marker").write_text("obsolete", encoding="utf-8")

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
                previous_version=previous.name,
                target_version="0.4.0-rc.4",
                runner=fake_codex,
            )

            self.assertEqual(returncode, 0)
            self.assertEqual(
                sorted(path.name for path in cache_parent.iterdir()),
                ["0.4.0-rc.1", "0.4.0-rc.4"],
            )
            self.assertEqual(report["preserved_caches"], [previous.name])
            self.assertEqual(report["restored_caches"], ["0.4.0-rc.1"])
            self.assertIsNone(report["failed_stage"])
            self.assertEqual(report["state"], "reinstall_succeeded_pending_acceptance")
            self.assertEqual(report["cleanup_candidates"], [])
            self.assertFalse(report["retention_cleanup_allowed"])
            self.assertTrue(str(report["snapshot_id"]).startswith("rollover-"))
            self.assertEqual(
                report["snapshot_path"],
                str(snapshot_parent / str(report["snapshot_id"])),
            )
            self.assertEqual(
                json.loads((snapshot_parent / "last-transaction.json").read_text()),
                report,
            )
            self.assertEqual(
                sorted(path.name for path in snapshot_parent.iterdir()),
                ["last-transaction.json"],
            )

    def test_reinstall_restores_previous_cache_after_nonzero_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshot_parent = root / "snapshots"
            previous = cache_parent / "0.4.0-rc.1"
            previous.mkdir(parents=True)
            (previous / "marker").write_text("previous", encoding="utf-8")

            def fake_codex(command, check):
                shutil.rmtree(previous)
                return subprocess.CompletedProcess(command, 9)

            returncode, report = reinstall_tool.reinstall(
                cache_parent,
                snapshot_parent,
                ["codex", "plugin", "add", "subagent-governance@personal"],
                previous_version=previous.name,
                target_version="0.4.0-rc.2",
                runner=fake_codex,
            )

            self.assertEqual(returncode, 9)
            self.assertEqual(report["failed_stage"], "codex_command")
            self.assertEqual(report["state"], "reinstall_failed_previous_restored")
            self.assertEqual(report["restored_caches"], [previous.name])
            self.assertEqual((previous / "marker").read_text(encoding="utf-8"), "previous")
            self.assertEqual(
                sorted(path.name for path in snapshot_parent.iterdir()),
                ["last-transaction.json"],
            )

    def test_reinstall_requires_explicit_actual_previous_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshot_parent = root / "snapshots"
            for version in ("0.4.0-rc.1", "0.4.0-rc.2"):
                cache = cache_parent / version
                cache.mkdir(parents=True, exist_ok=True)
                (cache / "marker").write_text(version, encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "--previous-version"):
                reinstall_tool.reinstall(
                    cache_parent,
                    snapshot_parent,
                    ["codex", "plugin", "add", "subagent-governance@personal"],
                    target_version="0.4.0-rc.3",
                    runner=lambda command, check: subprocess.CompletedProcess(command, 0),
                )

            self.assertFalse((snapshot_parent / ".reinstall.lock").exists())

    def test_reinstall_reports_obsolete_cache_candidates_without_deleting_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshot_parent = root / "snapshots"
            previous = cache_parent / "0.4.0-rc.2"
            obsolete = cache_parent / "0.4.0-rc.1"
            for cache in (previous, obsolete):
                cache.mkdir(parents=True)
                (cache / "marker").write_text(cache.name, encoding="utf-8")

            def fake_codex(command, check):
                current = cache_parent / "0.4.0-rc.3"
                current.mkdir()
                (current / "marker").write_text("current", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            returncode, report = reinstall_tool.reinstall(
                cache_parent,
                snapshot_parent,
                ["codex", "plugin", "add", "subagent-governance@personal"],
                previous_version=previous.name,
                target_version="0.4.0-rc.3",
                runner=fake_codex,
            )

            self.assertEqual(returncode, 0)
            self.assertEqual(report["cleanup_candidates"], [obsolete.name])
            self.assertTrue(obsolete.is_dir())
            self.assertFalse(report["retention_cleanup_allowed"])

    def test_reinstall_rejects_concurrent_or_abandoned_transaction_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshot_parent = root / "snapshots"
            cache_parent.mkdir()
            snapshot_parent.mkdir()
            lock = snapshot_parent / ".reinstall.lock"
            lock.write_text('{"pid": 123}', encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "事务锁"):
                reinstall_tool.reinstall(
                    cache_parent,
                    snapshot_parent,
                    ["codex", "plugin", "add", "subagent-governance@personal"],
                    target_version="0.4.0-rc.1",
                    runner=lambda command, check: subprocess.CompletedProcess(command, 0),
                )

            self.assertEqual(lock.read_text(encoding="utf-8"), '{"pid": 123}')

    def test_reinstall_treats_missing_target_cache_as_failed_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshot_parent = root / "snapshots"
            previous = cache_parent / "0.4.0-rc.1"
            previous.mkdir(parents=True)
            (previous / "marker").write_text("previous", encoding="utf-8")

            returncode, report = reinstall_tool.reinstall(
                cache_parent,
                snapshot_parent,
                ["codex", "plugin", "add", "subagent-governance@personal"],
                previous_version=previous.name,
                target_version="0.4.0-rc.2",
                runner=lambda command, check: subprocess.CompletedProcess(command, 0),
            )

            self.assertEqual(returncode, 2)
            self.assertEqual(report["failed_stage"], "post_install_cache")
            self.assertEqual(report["state"], "reinstall_failed_previous_restored")
            self.assertIn("目标缓存不存在", report["command_error"])

    def test_reinstall_restores_previous_cache_when_command_cannot_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshot_parent = root / "snapshots"
            previous = cache_parent / "0.4.0-rc.1"
            previous.mkdir(parents=True)
            (previous / "marker").write_text("previous", encoding="utf-8")

            def fake_codex(command, check):
                shutil.rmtree(previous)
                raise OSError("codex unavailable")

            returncode, report = reinstall_tool.reinstall(
                cache_parent,
                snapshot_parent,
                ["codex", "plugin", "add", "subagent-governance@personal"],
                previous_version=previous.name,
                target_version="0.4.0-rc.2",
                runner=fake_codex,
            )

            self.assertEqual(returncode, 2)
            self.assertEqual(report["failed_stage"], "codex_command")
            self.assertEqual(report["command_error"], "codex unavailable")
            self.assertEqual(report["restored_caches"], [previous.name])
            self.assertTrue(previous.is_dir())
            self.assertEqual(
                sorted(path.name for path in snapshot_parent.iterdir()),
                ["last-transaction.json"],
            )

    def test_reinstall_restores_cache_before_propagating_unexpected_command_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshot_parent = root / "snapshots"
            previous = cache_parent / "0.4.0-rc.1"
            previous.mkdir(parents=True)
            (previous / "marker").write_text("previous", encoding="utf-8")

            def fake_codex(command, check):
                shutil.rmtree(previous)
                raise RuntimeError("unexpected runner failure")

            with self.assertRaisesRegex(RuntimeError, "unexpected runner failure"):
                reinstall_tool.reinstall(
                    cache_parent,
                    snapshot_parent,
                    ["codex", "plugin", "add", "subagent-governance@personal"],
                    previous_version=previous.name,
                    target_version="0.4.0-rc.2",
                    runner=fake_codex,
                )

            self.assertEqual((previous / "marker").read_text(encoding="utf-8"), "previous")
            transaction = json.loads(
                (snapshot_parent / "last-transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual(transaction["state"], "command_exception_previous_restored")

    def test_reinstall_recovers_complete_stale_snapshot_before_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshot_parent = root / "snapshots"
            cache_parent.mkdir()
            stale_cache = snapshot_parent / "rollover-stale" / "0.4.0-rc.1"
            stale_cache.mkdir(parents=True)
            (stale_cache / "marker").write_text("stale", encoding="utf-8")

            def fake_codex(command, check):
                current = cache_parent / "0.4.0-rc.2"
                current.mkdir()
                (current / "marker").write_text("current", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            returncode, report = reinstall_tool.reinstall(
                cache_parent,
                snapshot_parent,
                ["codex", "plugin", "add", "subagent-governance@personal"],
                previous_version="0.4.0-rc.1",
                target_version="0.4.0-rc.2",
                runner=fake_codex,
            )

            self.assertEqual(returncode, 0)
            self.assertEqual(report["recovered_stale_caches"], ["0.4.0-rc.1"])
            self.assertEqual(report["restored_caches"], [])
            self.assertEqual((cache_parent / "0.4.0-rc.1" / "marker").read_text(), "stale")
            self.assertEqual(
                sorted(path.name for path in snapshot_parent.iterdir()),
                ["last-transaction.json"],
            )

    def test_reinstall_refuses_incomplete_structured_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshot_parent = root / "snapshots"
            cache_parent.mkdir()
            incomplete = snapshot_parent / "rollover-incomplete" / "cache" / "0.4.0-rc.1"
            incomplete.mkdir(parents=True)
            (incomplete / "marker").write_text("partial", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "缺少完成 manifest"):
                reinstall_tool.reinstall(
                    cache_parent,
                    snapshot_parent,
                    ["codex", "plugin", "add", "subagent-governance@personal"],
                    target_version="0.4.0-rc.2",
                    runner=lambda command, check: self.fail("不应执行原生重装命令"),
                )

            self.assertTrue(incomplete.is_dir())
            self.assertFalse((snapshot_parent / ".reinstall.lock").exists())

    def test_restore_snapshot_reports_snapshot_and_target_on_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshot = root / "rollover-conflict"
            target = cache_parent / "0.4.0-rc.1"
            source = snapshot / target.name
            target.mkdir(parents=True)
            source.mkdir(parents=True)
            (target / "marker").write_text("new", encoding="utf-8")
            (source / "marker").write_text("old", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, re.escape(str(snapshot))) as caught:
                reinstall_tool.restore_snapshot(snapshot, cache_parent)

            self.assertIn(str(target), str(caught.exception))
            self.assertTrue(source.is_dir())
            self.assertEqual((target / "marker").read_text(encoding="utf-8"), "new")

    def test_reinstall_supports_first_install_without_previous_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshot_parent = root / "snapshots"
            cache_parent.mkdir()

            def fake_codex(command, check):
                current = cache_parent / "0.4.0-rc.1"
                current.mkdir()
                return subprocess.CompletedProcess(command, 0)

            returncode, report = reinstall_tool.reinstall(
                cache_parent,
                snapshot_parent,
                ["codex", "plugin", "add", "subagent-governance@personal"],
                target_version="0.4.0-rc.1",
                runner=fake_codex,
            )

            self.assertEqual(returncode, 0)
            self.assertEqual(report["preserved_caches"], [])
            self.assertEqual(report["restored_caches"], [])
            self.assertEqual(
                sorted(path.name for path in snapshot_parent.iterdir()),
                ["last-transaction.json"],
            )

    @unittest.skipIf(os.name == "nt", "Windows does not expose POSIX ownership and mode checks")
    def test_reinstall_directory_and_filesystem_safety_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unsafe = root / "unsafe"
            unsafe.mkdir(mode=0o700)
            unsafe.chmod(0o777)
            with self.assertRaisesRegex(PermissionError, "组用户或其他用户写入"):
                reinstall_tool.ordinary_directory(unsafe, "测试目录")

            unsafe.chmod(0o700)
            with mock.patch.object(reinstall_tool.os, "getuid", return_value=os.getuid() + 1):
                with self.assertRaisesRegex(PermissionError, "当前用户拥有"):
                    reinstall_tool.ordinary_directory(unsafe, "测试目录")

            cache_parent_path = root / "cache"
            unsafe_cache = cache_parent_path / "0.4.0-rc.1"
            unsafe_cache.mkdir(parents=True)
            unsafe_cache.chmod(0o777)
            with self.assertRaisesRegex(PermissionError, "组用户或其他用户写入"):
                reinstall_tool.cache_directories(cache_parent_path)

            cache_parent = mock.Mock()
            snapshot_parent = mock.Mock()
            cache_parent.stat.return_value.st_dev = 1
            snapshot_parent.stat.return_value.st_dev = 2
            with self.assertRaisesRegex(RuntimeError, "同一文件系统"):
                reinstall_tool.require_same_filesystem(cache_parent, snapshot_parent)


if __name__ == "__main__":
    unittest.main()
