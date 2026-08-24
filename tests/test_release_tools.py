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

    def test_installation_check_requires_only_current_cache(self):
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
            self.assertTrue(report["single_current_cache"])
            self.assertEqual(report["unexpected_cache_entries"], [])

            stale = cache_parent / "0.3.0"
            stale.mkdir()
            (stale / "marker").write_text("stale", encoding="utf-8")
            unhealthy = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(unhealthy.returncode, 1)
            report = json.loads(unhealthy.stdout)
            self.assertFalse(report["single_current_cache"])
            self.assertIn("single_current_cache", report["runtime_issues"])
            self.assertIn("unexpected_extra_cache", report["warnings"])

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
    def cache(path, marker):
        path.mkdir(parents=True)
        (path / "marker").write_text(marker, encoding="utf-8")

    def test_successful_install_keeps_only_target_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            current = cache_parent / "0.4.0-rc.1"
            self.cache(current, "current")

            def runner(command, check):
                target = cache_parent / "0.4.0-rc.2"
                self.cache(target, "target")
                return subprocess.CompletedProcess(command, 0)

            returncode, report = install_tool.install(
                cache_parent,
                snapshots,
                ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                target_version="0.4.0-rc.2",
                runner=runner,
            )

            self.assertEqual(returncode, 0)
            self.assertEqual(report["state"], "install_succeeded")
            self.assertEqual(report["removed_cache_entries"], ["0.4.0-rc.1"])
            self.assertEqual([path.name for path in cache_parent.iterdir()], ["0.4.0-rc.2"])
            self.assertEqual(
                sorted(path.name for path in snapshots.iterdir()),
                [".install.lock", "last-transaction.json"],
            )

    def test_failed_install_restores_preinstall_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            current = cache_parent / "0.4.0-rc.1"
            self.cache(current, "original")

            def runner(command, check):
                shutil.rmtree(current)
                self.cache(cache_parent / "0.4.0-rc.2", "partial")
                return subprocess.CompletedProcess(command, 9)

            returncode, report = install_tool.install(
                cache_parent,
                snapshots,
                ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                target_version="0.4.0-rc.2",
                runner=runner,
            )

            self.assertEqual(returncode, 9)
            self.assertEqual(report["state"], "install_failed_rolled_back")
            self.assertEqual(report["restored_cache"], "0.4.0-rc.1")
            self.assertEqual((current / "marker").read_text(encoding="utf-8"), "original")
            self.assertFalse((cache_parent / "0.4.0-rc.2").exists())

    def test_missing_target_is_failure_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            current = cache_parent / "0.4.0-rc.1"
            self.cache(current, "original")

            returncode, report = install_tool.install(
                cache_parent,
                snapshots,
                ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                target_version="0.4.0-rc.2",
                runner=lambda command, check: subprocess.CompletedProcess(command, 0),
            )

            self.assertEqual(returncode, 2)
            self.assertEqual(report["failed_stage"], "post_install_cache")
            self.assertEqual(report["state"], "install_failed_rolled_back")
            self.assertTrue(current.is_dir())

    def test_unexpected_runner_error_rolls_back_before_propagation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            current = cache_parent / "0.4.0-rc.1"
            self.cache(current, "original")

            def runner(command, check):
                shutil.rmtree(current)
                raise RuntimeError("runner failed")

            with self.assertRaisesRegex(RuntimeError, "runner failed"):
                install_tool.install(
                    cache_parent,
                    snapshots,
                    ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                    target_version="0.4.0-rc.2",
                    runner=runner,
                )

            self.assertEqual((current / "marker").read_text(encoding="utf-8"), "original")
            transaction = json.loads((snapshots / "last-transaction.json").read_text())
            self.assertEqual(transaction["state"], "command_exception_rolled_back")

    def test_multiple_existing_caches_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            self.cache(cache_parent / "0.4.0-rc.1", "one")
            self.cache(cache_parent / "0.4.0-rc.2", "two")

            with self.assertRaisesRegex(RuntimeError, "只允许一个"):
                install_tool.install(
                    cache_parent,
                    snapshots,
                    ["codex", "plugin", "add", "subagent-governance@subagent-governance"],
                    target_version="0.4.0-rc.3",
                    runner=lambda command, check: self.fail("command must not run"),
                )

    def test_interrupted_transaction_is_rolled_back_before_next_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_parent = root / "cache"
            snapshots = root / "snapshots"
            cache_parent.mkdir()
            snapshot = snapshots / "transaction-stale"
            self.cache(snapshot / "cache" / "0.4.0-rc.1", "original")
            install_tool.write_json_atomic(
                snapshot / "snapshot-manifest.json",
                {
                    "current_cache": "0.4.0-rc.1",
                    "current_cache_digest": install_tool.tree_digest(
                        snapshot / "cache" / "0.4.0-rc.1"
                    ),
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
                target_version="0.4.0-rc.2",
                runner=runner,
            )

            self.assertEqual(returncode, 0)
            self.assertEqual(report["recovered_interrupted_cache"], "0.4.0-rc.1")
            self.assertEqual([path.name for path in cache_parent.iterdir()], ["0.4.0-rc.2"])

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
                    "current_cache": "0.4.0-rc.1",
                    "current_cache_digest": "0" * 64,
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
                        "current_cache": None,
                        "current_cache_digest": None,
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
