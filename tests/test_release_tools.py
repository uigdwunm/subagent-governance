#!/usr/bin/env python3

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import ROOT, load_module

APPLY_SCRIPT = ROOT / "scripts/apply_agents_block.py"
CHECK_SCRIPT = ROOT / "scripts/check_installation.py"
INSTALL_SCRIPT = ROOT / "scripts/reinstall_plugin.py"

apply_tool = load_module("apply_agents_block", APPLY_SCRIPT)
install_tool = load_module("reinstall_plugin", INSTALL_SCRIPT)


class ReleaseToolTests(unittest.TestCase):
    @staticmethod
    def managed_block(content="entry"):
        return (
            "<!-- subagent-governance:start -->\n"
            f"{content}\n"
            "<!-- subagent-governance:end -->\n"
        )

    def test_apply_agents_block_preserves_user_content_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            asset = root / "asset.md"
            agents.write_text("# Existing\n", encoding="utf-8")
            asset.write_text(self.managed_block(), encoding="utf-8")
            command = [
                sys.executable,
                str(APPLY_SCRIPT),
                "--execute",
                "--agents-file",
                str(agents),
                "--asset",
                str(asset),
            ]

            first = subprocess.run(command, capture_output=True, text=True, check=False)
            second = subprocess.run(command, capture_output=True, text=True, check=False)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(agents.read_text(encoding="utf-8"), "# Existing\n\n" + self.managed_block())

    def test_apply_agents_block_remove_preserves_user_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            agents.write_text("# Existing\n\n" + self.managed_block(), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(APPLY_SCRIPT),
                    "--remove",
                    "--agents-file",
                    str(agents),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(agents.read_text(encoding="utf-8"), "# Existing\n")

    def test_apply_rejects_invalid_asset_without_changing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            asset = root / "asset.md"
            agents.write_text(self.managed_block("old"), encoding="utf-8")
            asset.write_text("unexpected\n" + self.managed_block("new"), encoding="utf-8")
            before = agents.read_bytes()

            result = subprocess.run(
                [
                    sys.executable,
                    str(APPLY_SCRIPT),
                    "--execute",
                    "--agents-file",
                    str(agents),
                    "--asset",
                    str(asset),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(agents.read_bytes(), before)

    @unittest.skipIf(os.name == "nt", "Windows does not preserve POSIX mode bits")
    def test_atomic_write_preserves_mode_and_rejects_concurrent_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "AGENTS.md"
            path.write_text("old", encoding="utf-8")
            path.chmod(0o640)
            apply_tool.atomic_write(path, "new")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o640)

            expected = apply_tool.content_digest("new")
            path.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "读取后发生变化"):
                apply_tool.atomic_write(path, "replacement", expected_digest=expected)
            self.assertEqual(path.read_text(encoding="utf-8"), "changed")

    @unittest.skipIf(os.name == "nt", "Windows symlink creation may require privileges")
    def test_apply_rejects_symlink_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real.md"
            target = root / "AGENTS.md"
            asset = root / "asset.md"
            real.write_text(self.managed_block("old"), encoding="utf-8")
            target.symlink_to(real)
            asset.write_text(self.managed_block("new"), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(APPLY_SCRIPT),
                    "--execute",
                    "--agents-file",
                    str(target),
                    "--asset",
                    str(asset),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("符号链接", result.stderr)
            self.assertEqual(real.read_text(encoding="utf-8"), self.managed_block("old"))

    @staticmethod
    def create_plugin(root, version="0.4.0", rules="rules"):
        (root / ".codex-plugin").mkdir(parents=True)
        (root / "assets").mkdir()
        (root / ".codex-plugin/plugin.json").write_text(
            json.dumps({"version": version}), encoding="utf-8"
        )
        (root / "assets/agents-governance.md").write_text(
            ReleaseToolTests.managed_block(rules), encoding="utf-8"
        )

    def test_installation_check_allows_one_retained_previous_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            development = root / "development"
            stable = root / "stable"
            cache_parent = root / "cache"
            current = cache_parent / "0.4.0"
            for plugin_root in (development, stable, current):
                self.create_plugin(plugin_root)
            agents = root / "AGENTS.md"
            agents.write_text(self.managed_block("rules"), encoding="utf-8")
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
                "--require-development-sync",
            ]

            healthy = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(healthy.returncode, 0, healthy.stderr)
            report = json.loads(healthy.stdout)
            self.assertTrue(report["current_cache_present"])
            self.assertTrue(report["current_cache_matches_stable"])
            self.assertEqual(report["compatibility_cache_count"], 0)
            self.assertTrue(report["rolling_cache_set_valid"])
            self.assertIsNone(report["retained_previous_cache"])
            self.assertEqual(report["unexpected_cache_entries"], [])

            stale = cache_parent / "0.3.0"
            self.create_plugin(stale, version="0.3.0")
            compatible = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(compatible.returncode, 0, compatible.stderr)
            report = json.loads(compatible.stdout)
            self.assertEqual(report["compatibility_cache_count"], 1)
            self.assertTrue(report["rolling_cache_set_valid"])
            self.assertEqual(report["retained_previous_version"], "0.3.0")
            self.assertEqual(report["unexpected_cache_entries"], [])

            self.create_plugin(cache_parent / "0.2.0", version="0.2.0")
            unhealthy = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(unhealthy.returncode, 1)
            report = json.loads(unhealthy.stdout)
            self.assertFalse(report["rolling_cache_set_valid"])
            self.assertIn("rolling_cache_set_valid", report["runtime_issues"])
            self.assertIn("unexpected_extra_cache", report["warnings"])

    def test_installation_check_rejects_invalid_retained_previous_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            development = root / "development"
            stable = root / "stable"
            cache_parent = root / "cache"
            current = cache_parent / "B"
            retained = cache_parent / "A"
            for plugin_root in (development, stable, current):
                self.create_plugin(plugin_root, version="B")
            self.create_plugin(retained, version="wrong-version")
            agents = root / "AGENTS.md"
            agents.write_text(self.managed_block("rules"), encoding="utf-8")

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
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertFalse(report["rolling_cache_set_valid"])
            self.assertIsNone(report["retained_previous_cache"])
            self.assertIn(str(retained), report["unexpected_cache_entries"])

    def test_installation_check_reports_invalid_manifest_as_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            development = root / "development"
            stable = root / "stable"
            cache_parent = root / "cache"
            self.create_plugin(development)
            self.create_plugin(stable)
            (stable / ".codex-plugin/plugin.json").write_text(
                json.dumps({"version": 4}), encoding="utf-8"
            )
            cache_parent.mkdir()
            agents = root / "AGENTS.md"
            agents.write_text(self.managed_block(), encoding="utf-8")

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
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertEqual(report["runtime_issues"], ["check_failed"])
            self.assertIn("version 必须是非空字符串", report["fatal_error"]["message"])

    def test_public_marketplace_defaults(self):
        marketplace = "subagent-governance"
        self.assertEqual(
            install_tool.plugin_spec(marketplace),
            "subagent-governance@subagent-governance",
        )
        self.assertEqual(
            install_tool.default_cache_parent(marketplace),
            Path.home() / ".codex/plugins/cache/subagent-governance/subagent-governance",
        )

    @staticmethod
    def cache(path, marker, *, version=None):
        path.mkdir(parents=True)
        manifest = path / ".codex-plugin"
        manifest.mkdir()
        (manifest / "plugin.json").write_text(
            json.dumps({"version": version or path.name}), encoding="utf-8"
        )
        (path / "marker").write_text(marker, encoding="utf-8")

    def stable_source(self, root, target_version, marker="target"):
        source = root / "stable"
        self.cache(source, marker, version=target_version)
        return source

    def assert_digest_mismatch_rolls_back(self, mutate_target):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            target_version = "0.4.0-rc.3"
            source = self.stable_source(root, target_version)
            self.cache(cache_parent / "0.4.0-rc.1", "one")
            self.cache(cache_parent / "0.4.0-rc.2", "two")
            expected_digest = install_tool.tree_digest(source)

            def runner(command, check):
                shutil.rmtree(cache_parent / "0.4.0-rc.1")
                shutil.rmtree(cache_parent / "0.4.0-rc.2")
                target = cache_parent / target_version
                shutil.copytree(source, target, copy_function=shutil.copy2)
                mutate_target(target)
                return subprocess.CompletedProcess(command, 0)

            returncode, report = install_tool.install(
                cache_parent,
                snapshots,
                ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                previous_version="0.4.0-rc.2",
                target_version=target_version,
                confirm_previous_sessions_restarted=True,
                source_root=source,
                runner=runner,
            )

            self.assertEqual(returncode, 2)
            self.assertEqual(report["state"], "install_failed_rolled_back")
            self.assertEqual(report["failed_stage"], "post_install_verification")
            self.assertEqual(report["expected_stable_tree_digest"], expected_digest)
            self.assertEqual(report["actual_stable_tree_digest"], expected_digest)
            self.assertNotEqual(report["actual_target_tree_digest"], expected_digest)
            self.assertEqual(report["removed_cache_entries"], [])
            self.assertEqual(report["restored_caches"], ["0.4.0-rc.1", "0.4.0-rc.2"])
            self.assertEqual(
                sorted(path.name for path in cache_parent.iterdir()),
                ["0.4.0-rc.1", "0.4.0-rc.2"],
            )
            self.assertEqual((cache_parent / "0.4.0-rc.1" / "marker").read_text(), "one")
            self.assertEqual((cache_parent / "0.4.0-rc.2" / "marker").read_text(), "two")

    def test_target_missing_content_digest_mismatch_rolls_back_complete_cache_set(self):
        self.assert_digest_mismatch_rolls_back(
            lambda target: (target / "marker").unlink()
        )

    def test_target_extra_content_digest_mismatch_rolls_back_complete_cache_set(self):
        self.assert_digest_mismatch_rolls_back(
            lambda target: (target / "unexpected").write_text("extra", encoding="utf-8")
        )

    @unittest.skipIf(os.name == "nt", "file mode checks differ on Windows")
    def test_target_file_mode_digest_mismatch_rolls_back_complete_cache_set(self):
        def make_executable(target):
            marker = target / "marker"
            marker.chmod(marker.stat().st_mode | 0o100)

        self.assert_digest_mismatch_rolls_back(make_executable)

    def test_stable_source_change_during_command_rolls_back_complete_cache_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            target_version = "0.4.0-rc.3"
            source = self.stable_source(root, target_version)
            self.cache(cache_parent / "0.4.0-rc.1", "one")
            self.cache(cache_parent / "0.4.0-rc.2", "two")
            expected_digest = install_tool.tree_digest(source)

            def runner(command, check):
                shutil.rmtree(cache_parent / "0.4.0-rc.1")
                shutil.rmtree(cache_parent / "0.4.0-rc.2")
                shutil.copytree(source, cache_parent / target_version, copy_function=shutil.copy2)
                (source / "marker").write_text("changed", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            returncode, report = install_tool.install(
                cache_parent,
                snapshots,
                ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                previous_version="0.4.0-rc.2",
                target_version=target_version,
                confirm_previous_sessions_restarted=True,
                source_root=source,
                runner=runner,
            )

            self.assertEqual(returncode, 2)
            self.assertEqual(report["failed_stage"], "post_install_verification")
            self.assertEqual(report["expected_stable_tree_digest"], expected_digest)
            self.assertNotEqual(report["actual_stable_tree_digest"], expected_digest)
            self.assertEqual(report["actual_target_tree_digest"], expected_digest)
            self.assertEqual(report["restored_caches"], ["0.4.0-rc.1", "0.4.0-rc.2"])
            self.assertEqual(
                sorted(path.name for path in cache_parent.iterdir()),
                ["0.4.0-rc.1", "0.4.0-rc.2"],
            )

    def test_successful_install_restores_previous_deleted_by_native_add(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            current = cache_parent / "0.4.0-rc.1"
            source = self.stable_source(root, "0.4.0-rc.2")
            self.cache(current, "current")

            def runner(command, check):
                shutil.rmtree(current)
                target = cache_parent / "0.4.0-rc.2"
                shutil.copytree(source, target, copy_function=shutil.copy2)
                return subprocess.CompletedProcess(command, 0)

            returncode, report = install_tool.install(
                cache_parent,
                snapshots,
                ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                previous_version="0.4.0-rc.1",
                target_version="0.4.0-rc.2",
                source_root=source,
                runner=runner,
            )

            self.assertEqual(returncode, 0)
            self.assertEqual(report["state"], "install_succeeded")
            self.assertEqual(report["removed_cache_entries"], [])
            self.assertEqual(report["retained_previous_cache"], str(current))
            self.assertTrue(report["previous_cache_restored"])
            self.assertEqual(
                report["retained_previous_digest"], install_tool.tree_digest(current)
            )
            self.assertEqual(
                sorted(path.name for path in cache_parent.iterdir()),
                ["0.4.0-rc.1", "0.4.0-rc.2"],
            )
            self.assertEqual(
                sorted(path.name for path in snapshots.iterdir()),
                [".install.lock", "last-transaction.json"],
            )

    def test_successful_install_retains_unchanged_previous_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            previous = cache_parent / "previous-not-sorted-last"
            target_version = "target-not-sorted-first"
            source = self.stable_source(root, target_version)
            self.cache(previous, "previous")
            previous_digest = install_tool.tree_digest(previous)

            def runner(command, check):
                shutil.copytree(source, cache_parent / target_version, copy_function=shutil.copy2)
                return subprocess.CompletedProcess(command, 0)

            returncode, report = install_tool.install(
                cache_parent,
                snapshots,
                ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                previous_version=previous.name,
                target_version=target_version,
                source_root=source,
                runner=runner,
            )

            self.assertEqual(returncode, 0)
            self.assertFalse(report["previous_cache_restored"])
            self.assertEqual(report["retained_previous_digest"], previous_digest)
            self.assertEqual(
                sorted(path.name for path in cache_parent.iterdir()),
                sorted([previous.name, target_version]),
            )

    def test_changed_previous_after_native_add_rolls_back_full_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            previous = cache_parent / "A"
            source = self.stable_source(root, "B")
            self.cache(previous, "original")

            def runner(command, check):
                (previous / "marker").write_text("changed", encoding="utf-8")
                shutil.copytree(source, cache_parent / "B", copy_function=shutil.copy2)
                return subprocess.CompletedProcess(command, 0)

            returncode, report = install_tool.install(
                cache_parent,
                snapshots,
                ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                previous_version="A",
                target_version="B",
                source_root=source,
                runner=runner,
            )

            self.assertEqual(returncode, 2)
            self.assertEqual(report["failed_stage"], "restore_previous")
            self.assertEqual(report["restored_caches"], ["A"])
            self.assertEqual((previous / "marker").read_text(encoding="utf-8"), "original")
            self.assertFalse((cache_parent / "B").exists())

    def test_previous_restore_failure_rolls_back_full_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            previous = cache_parent / "A"
            source = self.stable_source(root, "B")
            self.cache(previous, "original")

            def runner(command, check):
                shutil.rmtree(previous)
                shutil.copytree(source, cache_parent / "B", copy_function=shutil.copy2)
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.object(
                install_tool,
                "restore_previous_cache",
                side_effect=OSError("restore previous failed"),
            ):
                returncode, report = install_tool.install(
                    cache_parent,
                    snapshots,
                    ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                    previous_version="A",
                    target_version="B",
                    source_root=source,
                    runner=runner,
                )

            self.assertEqual(returncode, 2)
            self.assertEqual(report["failed_stage"], "restore_previous")
            self.assertEqual(report["restored_caches"], ["A"])
            self.assertEqual((previous / "marker").read_text(encoding="utf-8"), "original")

    def test_failed_install_restores_preinstall_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            current = cache_parent / "0.4.0-rc.1"
            source = self.stable_source(root, "0.4.0-rc.2")
            self.cache(current, "original")

            def runner(command, check):
                shutil.rmtree(current)
                self.cache(cache_parent / "0.4.0-rc.2", "partial")
                return subprocess.CompletedProcess(command, 9)

            returncode, report = install_tool.install(
                cache_parent,
                snapshots,
                ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                previous_version="0.4.0-rc.1",
                target_version="0.4.0-rc.2",
                source_root=source,
                runner=runner,
            )

            self.assertEqual(returncode, 9)
            self.assertEqual(report["state"], "install_failed_rolled_back")
            self.assertEqual(report["restored_caches"], ["0.4.0-rc.1"])
            self.assertEqual((current / "marker").read_text(encoding="utf-8"), "original")
            self.assertFalse((cache_parent / "0.4.0-rc.2").exists())

    def test_missing_target_is_failure_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            current = cache_parent / "0.4.0-rc.1"
            source = self.stable_source(root, "0.4.0-rc.2")
            self.cache(current, "original")

            returncode, report = install_tool.install(
                cache_parent,
                snapshots,
                ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                previous_version="0.4.0-rc.1",
                target_version="0.4.0-rc.2",
                source_root=source,
                runner=lambda command, check: subprocess.CompletedProcess(command, 0),
            )

            self.assertEqual(returncode, 2)
            self.assertEqual(report["failed_stage"], "post_install_verification")
            self.assertEqual(report["state"], "install_failed_rolled_back")
            self.assertTrue(current.is_dir())

    def test_unexpected_runner_error_rolls_back_before_propagation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            current = cache_parent / "0.4.0-rc.1"
            source = self.stable_source(root, "0.4.0-rc.2")
            self.cache(current, "original")

            def runner(command, check):
                shutil.rmtree(current)
                raise RuntimeError("runner failed")

            with self.assertRaisesRegex(RuntimeError, "runner failed"):
                install_tool.install(
                    cache_parent,
                    snapshots,
                    ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                    previous_version="0.4.0-rc.1",
                    target_version="0.4.0-rc.2",
                    source_root=source,
                    runner=runner,
                )

            self.assertEqual((current / "marker").read_text(encoding="utf-8"), "original")
            transaction = json.loads((snapshots / "last-transaction.json").read_text())
            self.assertEqual(transaction["state"], "command_exception_rolled_back")

    def test_two_caches_roll_forward_to_previous_and_target_after_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            source = self.stable_source(root, "0.4.0-rc.3")
            self.cache(cache_parent / "0.4.0-rc.1", "one")
            self.cache(cache_parent / "0.4.0-rc.2", "two")

            def runner(command, check):
                shutil.rmtree(cache_parent / "0.4.0-rc.1")
                shutil.rmtree(cache_parent / "0.4.0-rc.2")
                shutil.copytree(source, cache_parent / "0.4.0-rc.3", copy_function=shutil.copy2)
                return subprocess.CompletedProcess(command, 0)

            returncode, report = install_tool.install(
                cache_parent,
                snapshots,
                ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                previous_version="0.4.0-rc.2",
                target_version="0.4.0-rc.3",
                source_root=source,
                confirm_previous_sessions_restarted=True,
                runner=runner,
            )

            self.assertEqual(returncode, 0)
            self.assertEqual(
                [entry["name"] for entry in report["pre_install_caches"]],
                ["0.4.0-rc.1", "0.4.0-rc.2"],
            )
            self.assertTrue(
                all(len(entry["digest"]) == 64 for entry in report["pre_install_caches"])
            )
            self.assertEqual(report["previous_version"], "0.4.0-rc.2")
            self.assertEqual(report["target_version"], "0.4.0-rc.3")
            self.assertEqual(report["removed_cache_entries"], ["0.4.0-rc.1"])
            self.assertTrue(report["previous_cache_restored"])
            self.assertEqual(report["retained_previous_version"], "0.4.0-rc.2")
            self.assertEqual(
                sorted(path.name for path in cache_parent.iterdir()),
                ["0.4.0-rc.2", "0.4.0-rc.3"],
            )

    def test_compatibility_cache_requires_explicit_restart_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            self.cache(cache_parent / "A", "old")
            self.cache(cache_parent / "B", "current")

            with self.assertRaisesRegex(RuntimeError, "confirm-previous-sessions-restarted"):
                install_tool.install(
                    cache_parent,
                    snapshots,
                    ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                    previous_version="B",
                    target_version="C",
                    runner=lambda command, check: self.fail("command must not run"),
                )

    def test_two_caches_failed_add_restores_the_complete_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            first = cache_parent / "0.4.0-rc.1"
            second = cache_parent / "0.4.0-rc.2"
            source = self.stable_source(root, "0.4.0-rc.3")
            self.cache(first, "one")
            self.cache(second, "two")

            def runner(command, check):
                shutil.rmtree(first)
                shutil.rmtree(second)
                self.cache(cache_parent / "0.4.0-rc.3", "partial")
                return subprocess.CompletedProcess(command, 9)

            returncode, report = install_tool.install(
                cache_parent, snapshots, ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                previous_version="0.4.0-rc.2", target_version="0.4.0-rc.3",
                confirm_previous_sessions_restarted=True, source_root=source, runner=runner,
            )

            self.assertEqual(returncode, 9)
            self.assertEqual(report["restored_caches"], ["0.4.0-rc.1", "0.4.0-rc.2"])
            self.assertEqual((first / "marker").read_text(), "one")
            self.assertEqual((second / "marker").read_text(), "two")
            self.assertFalse((cache_parent / "0.4.0-rc.3").exists())

    def test_existing_cache_requires_explicit_previous_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            self.cache(cache_parent / "0.4.0-rc.1", "one")

            with self.assertRaisesRegex(RuntimeError, "--previous-version"):
                install_tool.install(
                    cache_parent, snapshots,
                    ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                    target_version="0.4.0-rc.2",
                    runner=lambda command, check: self.fail("command must not run"),
                )

    def test_explicit_previous_version_must_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            self.cache(cache_parent / "0.4.0-rc.1", "one")

            with self.assertRaisesRegex(RuntimeError, "升级前版本缓存不存在"):
                install_tool.install(
                    cache_parent, snapshots,
                    ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                    previous_version="0.4.0-rc.9", target_version="0.4.0-rc.2",
                    runner=lambda command, check: self.fail("command must not run"),
                )

    def test_empty_cache_install_succeeds_without_previous_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            cache_parent.mkdir()
            source = self.stable_source(root, "0.4.0-rc.2")

            def runner(command, check):
                self.cache(cache_parent / "0.4.0-rc.2", "target")
                return subprocess.CompletedProcess(command, 0)

            returncode, report = install_tool.install(
                cache_parent, snapshots,
                ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                target_version="0.4.0-rc.2", source_root=source, runner=runner,
            )

            self.assertEqual(returncode, 0)
            self.assertIsNone(report["previous_version"])
            self.assertEqual(report["pre_install_caches"], [])
            self.assertIsNone(report["retained_previous_cache"])
            self.assertFalse(report["previous_cache_restored"])
            self.assertEqual(
                [path.name for path in cache_parent.iterdir()], ["0.4.0-rc.2"]
            )

    def test_target_must_differ_from_explicit_previous_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            self.cache(cache_parent / "0.4.0-rc.1", "one")

            with self.assertRaisesRegex(RuntimeError, "必须不同"):
                install_tool.install(
                    cache_parent, snapshots,
                    ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                    previous_version="0.4.0-rc.1", target_version="0.4.0-rc.1",
                    runner=lambda command, check: self.fail("command must not run"),
                )

    def test_snapshot_fault_preserves_transaction_and_does_not_run_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            source = self.stable_source(root, "0.4.0-rc.2")
            self.cache(cache_parent / "0.4.0-rc.1", "one")

            with mock.patch.object(install_tool.shutil, "copytree", side_effect=OSError("copy failed")):
                with self.assertRaisesRegex(RuntimeError, "快照阶段失败"):
                    install_tool.install(
                        cache_parent, snapshots,
                        ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                        previous_version="0.4.0-rc.1", target_version="0.4.0-rc.2",
                        source_root=source,
                        runner=lambda command, check: self.fail("command must not run"),
                    )

            report = json.loads((snapshots / "last-transaction.json").read_text())
            self.assertEqual(report["state"], "snapshot_failed")
            self.assertTrue(any(path.name.startswith("transaction-") for path in snapshots.iterdir()))

    def test_cleanup_fault_rolls_back_complete_cache_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            source = self.stable_source(root, "0.4.0-rc.3")
            self.cache(cache_parent / "0.4.0-rc.1", "one")
            self.cache(cache_parent / "0.4.0-rc.2", "two")
            original_remove = install_tool.remove_cache
            raised = False

            def fail_once(path):
                nonlocal raised
                if path.name == "0.4.0-rc.1" and not raised:
                    raised = True
                    raise OSError("cleanup failed")
                original_remove(path)

            def runner(command, check):
                self.cache(cache_parent / "0.4.0-rc.3", "target")
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.object(install_tool, "remove_cache", side_effect=fail_once):
                returncode, report = install_tool.install(
                    cache_parent, snapshots,
                    ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                    previous_version="0.4.0-rc.2", target_version="0.4.0-rc.3",
                    confirm_previous_sessions_restarted=True, source_root=source, runner=runner,
                )

            self.assertEqual(returncode, 2)
            self.assertEqual(report["failed_stage"], "cleanup")
            self.assertEqual(report["restored_caches"], ["0.4.0-rc.1", "0.4.0-rc.2"])
            self.assertEqual(sorted(path.name for path in cache_parent.iterdir()), ["0.4.0-rc.1", "0.4.0-rc.2"])

    def test_restore_fault_is_reported_and_snapshot_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            source = self.stable_source(root, "0.4.0-rc.2")
            self.cache(cache_parent / "0.4.0-rc.1", "one")

            with mock.patch.object(install_tool, "restore_snapshot", side_effect=OSError("restore failed")):
                with self.assertRaisesRegex(RuntimeError, "回滚失败"):
                    install_tool.install(
                        cache_parent, snapshots,
                        ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                        previous_version="0.4.0-rc.1", target_version="0.4.0-rc.2",
                        source_root=source,
                        runner=lambda command, check: subprocess.CompletedProcess(command, 9),
                    )

            report = json.loads((snapshots / "last-transaction.json").read_text())
            self.assertEqual(report["state"], "rollback_failed")
            self.assertTrue(any(path.name.startswith("transaction-") for path in snapshots.iterdir()))

    @unittest.skipIf(os.name == "nt", "symlink support differs")
    def test_symlinked_cache_is_rejected_before_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            real = root / "real-cache"
            self.cache(real, "one")
            cache_parent.mkdir()
            (cache_parent / "0.4.0-rc.1").symlink_to(real, target_is_directory=True)

            with self.assertRaisesRegex(RuntimeError, "不能是符号链接"):
                install_tool.install(
                    cache_parent, snapshots,
                    ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                    previous_version="0.4.0-rc.1", target_version="0.4.0-rc.2",
                    runner=lambda command, check: self.fail("command must not run"),
                )

    def test_interrupted_transaction_is_rolled_back_before_next_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            cache_parent.mkdir()
            source = self.stable_source(root, "0.4.0-rc.2")
            snapshot = snapshots / "transaction-stale"
            self.cache(snapshot / "cache" / "0.4.0-rc.1", "original")
            install_tool.write_json_atomic(
                snapshot / "snapshot-manifest.json",
                {
                    "pre_install_caches": [{
                        "name": "0.4.0-rc.1",
                        "digest": install_tool.tree_digest(snapshot / "cache" / "0.4.0-rc.1"),
                    }],
                    "previous_version": "0.4.0-rc.1",
                    "target_version": "0.4.0-rc.2",
                    "transaction_id": "transaction-stale",
                },
            )

            def runner(command, check):
                self.assertEqual(
                    (cache_parent / "0.4.0-rc.1" / "marker").read_text(),
                    "original",
                )
                self.cache(cache_parent / "0.4.0-rc.2", "target")
                return subprocess.CompletedProcess(command, 0)

            returncode, report = install_tool.install(
                cache_parent,
                snapshots,
                ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                previous_version="0.4.0-rc.1",
                target_version="0.4.0-rc.2",
                source_root=source,
                runner=runner,
            )

            self.assertEqual(returncode, 0)
            self.assertEqual(report["recovered_interrupted_caches"], ["0.4.0-rc.1"])
            self.assertEqual(
                sorted(path.name for path in cache_parent.iterdir()),
                ["0.4.0-rc.1", "0.4.0-rc.2"],
            )

    def test_incomplete_transaction_snapshot_is_preserved_and_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            cache_parent.mkdir()
            incomplete = snapshots / "transaction-incomplete" / "cache" / "0.4.0-rc.1"
            self.cache(incomplete, "partial")

            with self.assertRaisesRegex(RuntimeError, "快照不完整"):
                install_tool.install(
                    cache_parent,
                    snapshots,
                    ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                    target_version="0.4.0-rc.2",
                    runner=lambda command, check: self.fail("command must not run"),
                )

            self.assertTrue(incomplete.is_dir())
            self.assertTrue((snapshots / ".install.lock").is_file())

    def test_invalid_snapshot_is_rejected_before_current_cache_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            self.cache(cache_parent / "0.4.0-rc.1", "current")
            snapshot = snapshots / "transaction-invalid"
            self.cache(snapshot / "cache" / "0.4.0-rc.1", "snapshot")
            install_tool.write_json_atomic(
                snapshot / "snapshot-manifest.json",
                {
                    "pre_install_caches": [{
                        "name": "0.4.0-rc.1",
                        "digest": "0" * 64,
                    }],
                    "previous_version": "0.4.0-rc.1",
                    "target_version": "0.4.0-rc.2",
                    "transaction_id": "transaction-invalid",
                },
            )

            with self.assertRaisesRegex(RuntimeError, "摘要不匹配"):
                install_tool.install(
                    cache_parent,
                    snapshots,
                    ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                    target_version="0.4.0-rc.2",
                    runner=lambda command, check: self.fail("command must not run"),
                )

            self.assertEqual(
                (cache_parent / "0.4.0-rc.1" / "marker").read_text(),
                "current",
            )

    def test_multiple_interrupted_transactions_are_rejected_as_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            cache_parent.mkdir()
            for name in ("transaction-first", "transaction-second"):
                snapshot = snapshots / name
                (snapshot / "cache").mkdir(parents=True)
                install_tool.write_json_atomic(
                snapshot / "snapshot-manifest.json",
                {
                    "pre_install_caches": [],
                    "previous_version": None,
                        "target_version": "0.4.0-rc.2",
                        "transaction_id": name,
                    },
                )

            with self.assertRaisesRegex(RuntimeError, "多个未完成安装事务"):
                install_tool.install(
                    cache_parent,
                    snapshots,
                    ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                    target_version="0.4.0-rc.2",
                    runner=lambda command, check: self.fail("command must not run"),
                )

    def test_persistent_lock_file_is_reused_after_process_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshots = root / "snapshots"
            snapshots.mkdir()

            with install_tool.operation_lock(snapshots) as first:
                self.assertTrue(first.is_file())
            with install_tool.operation_lock(snapshots) as second:
                self.assertEqual(first, second)

    @unittest.skipIf(os.name == "nt", "Windows permission checks differ")
    def test_install_directory_safety_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unsafe = root / "unsafe"
            unsafe.mkdir(mode=0o700)
            unsafe.chmod(0o777)
            with self.assertRaises(PermissionError):
                install_tool.ordinary_directory(unsafe, "测试目录")

            unsafe.chmod(0o700)
            with mock.patch.object(install_tool.os, "getuid", return_value=os.getuid() + 1):
                with self.assertRaises(PermissionError):
                    install_tool.ordinary_directory(unsafe, "测试目录")


if __name__ == "__main__":
    unittest.main()
