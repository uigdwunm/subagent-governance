#!/usr/bin/env python3
"""Transactional tests for the single local-development deploy entry."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import dev_deploy, runtime_bundle
from tests.support import ROOT


class DevDeployTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        runtime_bundle.stage_runtime_bundle(ROOT, self.source)
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        subprocess.run(
            ["git", "-C", str(self.source), "config", "user.email", "tests@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.source), "config", "user.name", "Tests"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.source), "add", "-A"], check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "gc.auto=0",
                "-c",
                "maintenance.auto=false",
                "-C",
                str(self.source),
                "commit",
                "-qm",
                "runtime bundle",
            ],
            check=True,
        )
        self.head = subprocess.check_output(
            ["git", "-C", str(self.source), "rev-parse", "HEAD"], text=True
        ).strip()
        self.version = dev_deploy.manifest_version(self.source)

        self.stable_parent = self.root / "stable"
        self.stable_parent.mkdir()
        self.stable = self.stable_parent / "subagent-governance"
        runtime_bundle.stage_runtime_bundle(self.source, self.stable)
        self._set_version(self.stable, "0.3.0+codex.old")

        self.cache_parent = self.root / "cache"
        self.cache_parent.mkdir()
        self.transactions = self.root / "transactions"
        self.transactions.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _set_version(root: Path, version: str) -> None:
        path = root / ".codex-plugin/plugin.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["version"] = version
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def cache(self, version: str) -> Path:
        target = self.cache_parent / version
        runtime_bundle.stage_runtime_bundle(self.source, target)
        self._set_version(target, version)
        return target

    def arguments(self, **overrides):
        value = {
            "source_root": self.source,
            "stable_root": self.stable,
            "cache_parent": self.cache_parent,
            "transaction_parent": self.transactions,
            "expected_head": self.head,
            "expected_version": self.version,
            "marketplace": "personal",
            "previous_version": None,
            "execute": True,
        }
        value.update(overrides)
        return value

    def native_runner(self, *, returncode=0, corrupt_target=False):
        def run(command, check=False):
            self.assertEqual(
                command,
                ["codex", "plugin", "add", "subagent-governance@personal"],
            )
            self.assertFalse(check)
            for entry in list(self.cache_parent.iterdir()):
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry)
            if returncode == 0:
                target = self.cache_parent / self.version
                shutil.copytree(self.stable, target, copy_function=shutil.copy2)
                if corrupt_target:
                    path = target / "scripts/governance_errors.py"
                    path.write_text("corrupt\n", encoding="utf-8")
            return SimpleNamespace(returncode=returncode)

        return run

    def test_dry_run_verifies_clean_exact_source_and_is_zero_write(self):
        def deployment_paths():
            return sorted(
                path.relative_to(self.root).as_posix()
                for path in self.root.rglob("*")
                if ".git" not in path.relative_to(self.root).parts
            )

        before = deployment_paths()
        code, report = dev_deploy.deploy(**self.arguments(execute=False))
        after = deployment_paths()
        self.assertEqual(code, 0)
        self.assertEqual(report["state"], "dry_run_passed")
        self.assertEqual(report["source_bundle_digest"], runtime_bundle.bundle_digest(self.source))
        self.assertEqual(before, after)

    def test_git_observations_disable_optional_repository_writes(self):
        with mock.patch.object(
            dev_deploy.subprocess,
            "check_output",
            return_value=b"fixture\n",
        ) as check_output:
            self.assertEqual(dev_deploy._git(self.source, "status"), "fixture\n")
        check_output.assert_called_once_with(
            [
                "git",
                "--no-optional-locks",
                "-C",
                str(self.source),
                "status",
            ],
            stderr=subprocess.PIPE,
        )

    def test_success_atomically_activates_bundle_and_restores_exact_previous(self):
        previous_version = "0.3.0+codex.previous"
        previous = self.cache(previous_version)
        previous_digest = runtime_bundle.bundle_digest(previous)
        old_stable_digest = runtime_bundle.bundle_digest(self.stable)
        code, report = dev_deploy.deploy(
            **self.arguments(previous_version=previous_version),
            runner=self.native_runner(),
        )
        self.assertEqual(code, 0, report)
        self.assertEqual(report["state"], "deploy_succeeded")
        self.assertNotEqual(runtime_bundle.bundle_digest(self.stable), old_stable_digest)
        self.assertEqual(
            runtime_bundle.bundle_digest(self.stable),
            runtime_bundle.bundle_digest(self.source),
        )
        self.assertEqual(
            {path.name for path in self.cache_parent.iterdir()},
            {previous_version, self.version},
        )
        self.assertEqual(runtime_bundle.bundle_digest(self.cache_parent / previous_version), previous_digest)
        self.assertEqual(
            runtime_bundle.verify_runtime_bundle(self.cache_parent / previous_version),
            previous_digest,
        )
        self.assertEqual(
            runtime_bundle.bundle_digest(self.cache_parent / self.version),
            runtime_bundle.bundle_digest(self.source),
        )
        self.assertTrue(report["previous_cache_restored"])
        self.assertEqual(report["retained_previous_version"], previous_version)
        self.assertEqual(list(self.transactions.glob("transaction-*")), [])

    def test_rollover_drops_only_oldest_compatibility_cache(self):
        oldest_version = "0.2.0+codex.oldest"
        previous_version = "0.3.0+codex.previous"
        self.cache(oldest_version)
        self.cache(previous_version)
        code, report = dev_deploy.deploy(
            **self.arguments(previous_version=previous_version),
            runner=self.native_runner(),
        )
        self.assertEqual(code, 0, report)
        self.assertEqual(
            {path.name for path in self.cache_parent.iterdir()},
            {previous_version, self.version},
        )
        self.assertEqual(report["removed_cache_entries"], [oldest_version])

    def test_rollover_can_remove_dirty_oldest_when_selected_previous_is_exact(self):
        oldest_version = "0.2.0+codex.oldest"
        previous_version = "0.3.0+codex.previous"
        oldest = self.cache(oldest_version)
        extra = oldest / "scripts/__pycache__/legacy.pyc"
        extra.parent.mkdir()
        extra.write_bytes(b"legacy bytecode")
        self.cache(previous_version)
        code, report = dev_deploy.deploy(
            **self.arguments(previous_version=previous_version),
            runner=self.native_runner(),
        )
        self.assertEqual(code, 0, report)
        self.assertEqual(
            {path.name for path in self.cache_parent.iterdir()},
            {previous_version, self.version},
        )
        self.assertEqual(report["removed_cache_entries"], [oldest_version])

    def test_dirty_selected_previous_is_rejected_before_native_install(self):
        previous_version = "0.3.0+codex.previous"
        previous = self.cache(previous_version)
        extra = previous / "scripts/__pycache__/runtime.pyc"
        extra.parent.mkdir()
        extra.write_bytes(b"runtime bytecode")
        runner = mock.Mock()
        code, report = dev_deploy.deploy(
            **self.arguments(previous_version=previous_version),
            runner=runner,
        )
        self.assertEqual(code, 2, report)
        self.assertEqual(report["failed_stage"], "admission")
        self.assertIn("文件集合不精确", report["error"])
        runner.assert_not_called()

    def test_previous_mutated_after_restore_fails_exact_verification_and_rolls_back(self):
        previous_version = "0.3.0+codex.previous"
        previous = self.cache(previous_version)
        stable_digest = runtime_bundle.bundle_digest(self.stable)
        previous_digest = runtime_bundle.verify_runtime_bundle(previous)
        original_restore = dev_deploy._restore_previous

        def restore_then_mutate(*args, **kwargs):
            restored = original_restore(*args, **kwargs)
            extra = self.cache_parent / previous_version / "scripts/__pycache__/late.pyc"
            extra.parent.mkdir()
            extra.write_bytes(b"late bytecode")
            return restored

        with mock.patch.object(
            dev_deploy, "_restore_previous", side_effect=restore_then_mutate
        ):
            code, report = dev_deploy.deploy(
                **self.arguments(previous_version=previous_version),
                runner=self.native_runner(),
            )
        self.assertEqual(code, 2, report)
        self.assertEqual(report["failed_stage"], "post_install_verification")
        self.assertEqual(runtime_bundle.bundle_digest(self.stable), stable_digest)
        self.assertEqual(
            runtime_bundle.verify_runtime_bundle(previous), previous_digest
        )

    def test_native_failure_rolls_back_stable_and_complete_cache_set(self):
        previous_version = "0.3.0+codex.previous"
        previous = self.cache(previous_version)
        stable_digest = runtime_bundle.bundle_digest(self.stable)
        previous_digest = runtime_bundle.bundle_digest(previous)
        code, report = dev_deploy.deploy(
            **self.arguments(previous_version=previous_version),
            runner=self.native_runner(returncode=1),
        )
        self.assertEqual(code, 2)
        self.assertEqual(report["state"], "deploy_failed_rolled_back")
        self.assertEqual(runtime_bundle.bundle_digest(self.stable), stable_digest)
        self.assertEqual(
            {path.name for path in self.cache_parent.iterdir()}, {previous_version}
        )
        self.assertEqual(runtime_bundle.bundle_digest(previous), previous_digest)

    def test_target_digest_mismatch_rolls_back(self):
        previous_version = "0.3.0+codex.previous"
        previous = self.cache(previous_version)
        stable_digest = runtime_bundle.bundle_digest(self.stable)
        previous_digest = runtime_bundle.bundle_digest(previous)
        code, report = dev_deploy.deploy(
            **self.arguments(previous_version=previous_version),
            runner=self.native_runner(corrupt_target=True),
        )
        self.assertEqual(code, 2)
        self.assertEqual(report["failed_stage"], "post_install_verification")
        self.assertEqual(runtime_bundle.bundle_digest(self.stable), stable_digest)
        self.assertEqual(runtime_bundle.bundle_digest(previous), previous_digest)

    def test_existing_cache_requires_operator_provided_previous_identity(self):
        self.cache("0.3.0+codex.previous")
        runner = mock.Mock()
        code, report = dev_deploy.deploy(**self.arguments(), runner=runner)
        self.assertEqual(code, 2)
        self.assertEqual(report["failed_stage"], "admission")
        runner.assert_not_called()

    def test_preexisting_target_version_is_rejected_before_native_install(self):
        previous_version = "0.3.0+codex.previous"
        self.cache(previous_version)
        self.cache(self.version)
        runner = mock.Mock()
        code, report = dev_deploy.deploy(
            **self.arguments(previous_version=previous_version),
            runner=runner,
        )
        self.assertEqual(code, 2)
        self.assertIn("target version cache", report["error"])
        runner.assert_not_called()

    def test_interruption_between_atomic_renames_restores_missing_stable(self):
        previous_version = "0.3.0+codex.previous"
        self.cache(previous_version)
        stable_digest = runtime_bundle.bundle_digest(self.stable)

        def interrupt(stage):
            if stage == "after_stable_backup":
                raise KeyboardInterrupt("injected")

        with mock.patch.object(dev_deploy, "_failpoint", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                dev_deploy.deploy(
                    **self.arguments(previous_version=previous_version),
                    runner=self.native_runner(),
                )
        self.assertFalse(self.stable.exists())

        code, report = dev_deploy.deploy(
            **self.arguments(previous_version=previous_version),
            runner=self.native_runner(),
        )
        self.assertEqual(code, 0, report)
        self.assertTrue(report["recovered_interrupted_transaction"])
        self.assertNotEqual(runtime_bundle.bundle_digest(self.stable), stable_digest)

    def test_interrupted_activation_is_recovered_before_next_deploy(self):
        previous_version = "0.3.0+codex.previous"
        self.cache(previous_version)

        def interrupt(stage):
            if stage == "after_stable_activation":
                raise KeyboardInterrupt("injected")

        with mock.patch.object(dev_deploy, "_failpoint", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                dev_deploy.deploy(
                    **self.arguments(previous_version=previous_version),
                    runner=self.native_runner(),
                )
        self.assertEqual(len(list(self.transactions.glob("transaction-*"))), 1)

        code, report = dev_deploy.deploy(
            **self.arguments(previous_version=previous_version),
            runner=self.native_runner(),
        )
        self.assertEqual(code, 0, report)
        self.assertTrue(report["recovered_interrupted_transaction"])
        self.assertEqual(list(self.transactions.glob("transaction-*")), [])


if __name__ == "__main__":
    unittest.main()
