#!/usr/bin/env python3
"""Transactional tests for the single local-development deploy entry."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
        # The bundle omits repository attributes; isolate the fixture from host EOL settings.
        subprocess.run(
            ["git", "-C", str(self.source), "config", "core.autocrlf", "false"],
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

    def test_install_residue_rolls_back_and_can_recover_on_reentry(self):
        for previous_present, partial, interrupted in (
            (False, False, False), (True, False, False),
            (True, True, False), (True, True, True), (False, False, True),
        ):
            with self.subTest(previous=previous_present, partial=partial, interrupted=interrupted):
                case = DevDeployTests()
                case.setUp()
                try:
                    previous = "0.3.0+codex.previous" if previous_present else None
                    if previous:
                        case.cache(previous)
                    before = dev_deploy._cache_facts(case.cache_parent)
                    stable_before = dev_deploy._safe_tree_digest(case.stable)

                    def failed_install(*args, **kwargs):
                        for entry in case.cache_parent.iterdir():
                            shutil.rmtree(entry)
                        residue = case.cache_parent / case.version
                        residue.mkdir()
                        if partial:
                            (residue / "partial").write_bytes(b"partial install")
                            (residue / "empty").mkdir()
                        if interrupted:
                            raise KeyboardInterrupt("interrupted install")
                        return SimpleNamespace(returncode=1)

                    if interrupted:
                        with self.assertRaises(KeyboardInterrupt):
                            dev_deploy.deploy(**case.arguments(previous_version=previous),
                                              runner=failed_install)
                        with dev_deploy._operation_lock(case.transactions):
                            dev_deploy._recover_interrupted(
                                case.transactions, case.stable, case.cache_parent)
                    else:
                        code, report = dev_deploy.deploy(
                            **case.arguments(previous_version=previous), runner=failed_install)
                        self.assertEqual(code, 2)
                        self.assertEqual(report["state"], "deploy_failed_rolled_back", report)
                    self.assertEqual(dev_deploy._cache_facts(case.cache_parent), before)
                    self.assertEqual(dev_deploy._safe_tree_digest(case.stable), stable_before)
                    self.assertEqual(list(case.transactions.glob("transaction-*")), [])
                finally:
                    case.tearDown()

    def test_hidden_uncommitted_projection_is_rejected_without_writes(self):
        for flag in ("--skip-worktree", "--assume-unchanged"):
            for relative in ("scripts/governance_errors.py", ".codex-plugin/runtime-bundle.json",
                             ".codex-plugin/plugin.json"):
                for execute in (False, True):
                    with self.subTest(flag=flag, relative=relative, execute=execute):
                        case = DevDeployTests()
                        case.setUp()
                        try:
                            subprocess.run(["git", "-C", str(case.source), "update-index",
                                            flag, relative], check=True)
                            path = case.source / relative
                            path.write_bytes(path.read_bytes() + b"\n")
                            self.assertEqual(dev_deploy._git(case.source, "status", "--porcelain"), "")
                            stable_before = dev_deploy._safe_tree_digest(case.stable)
                            runner = mock.Mock()
                            code, report = dev_deploy.deploy(
                                **case.arguments(execute=execute), runner=runner)
                            self.assertEqual(code, 2, report)
                            self.assertEqual(report["failed_stage"], "admission")
                            runner.assert_not_called()
                            self.assertEqual(dev_deploy._safe_tree_digest(case.stable), stable_before)
                            self.assertEqual(list(case.transactions.iterdir()), [])
                            self.assertEqual(list(case.cache_parent.iterdir()), [])
                        finally:
                            case.tearDown()

    def test_rollback_refuses_unbound_or_unsafe_residue_before_deleting_caches(self):
        kinds = ["unknown", "symlink", "root_symlink", "file", "wrong_owner"]
        if os.name != "nt":
            kinds += ["fifo", "writable_directory", "writable_file"]
        for kind in kinds:
            with self.subTest(kind=kind):
                case = DevDeployTests()
                case.setUp()
                try:
                    previous = "0.3.0+codex.previous"
                    case.cache(previous)
                    previous_digest = dev_deploy._safe_tree_digest(case.cache_parent / previous)
                    unsafe_inode = None
                    owns = dev_deploy._owned_by_current_user

                    def ownership(metadata):
                        return metadata.st_ino != unsafe_inode and owns(metadata)

                    def failed_install(*args, **kwargs):
                        nonlocal unsafe_inode
                        target = case.cache_parent / case.version
                        target.mkdir()
                        (target / "partial").write_bytes(b"partial")
                        if kind == "unknown":
                            (case.cache_parent / "unrelated").mkdir()
                        elif kind == "symlink":
                            (target / "link").symlink_to(case.source)
                        elif kind == "root_symlink":
                            shutil.rmtree(target)
                            target.symlink_to(case.source, target_is_directory=True)
                        elif kind == "wrong_owner":
                            unsafe_inode = (target / "partial").stat().st_ino
                        elif kind == "file":
                            shutil.rmtree(target)
                            target.write_bytes(b"not directory")
                        elif kind == "fifo":
                            os.mkfifo(target / "fifo")
                        elif kind == "writable_directory":
                            (target / "nested").mkdir(mode=0o777)
                            (target / "nested").chmod(0o777)
                        else:
                            (target / "partial").chmod(0o666)
                        return SimpleNamespace(returncode=1)

                    with mock.patch.object(dev_deploy, "_owned_by_current_user",
                                           side_effect=ownership):
                        code, report = dev_deploy.deploy(
                            **case.arguments(previous_version=previous), runner=failed_install)
                    self.assertEqual(code, 2)
                    self.assertEqual(report["state"], "rollback_failed", report)
                    self.assertIn("返回 1", report["error"])
                    self.assertEqual(dev_deploy._safe_tree_digest(case.cache_parent / previous),
                                     previous_digest)
                    self.assertEqual(len(list(case.transactions.glob("transaction-*"))), 1)
                finally:
                    case.tearDown()

    @unittest.skipIf(os.name == "nt", "POSIX executable bits")
    def test_executable_bit_mismatch_is_rejected_even_when_git_ignores_filemode(self):
        subprocess.run(["git", "-C", str(self.source), "config", "core.filemode", "false"],
                       check=True)
        path = self.source / "scripts/governance_errors.py"
        path.chmod(path.stat().st_mode ^ 0o100)
        code, report = dev_deploy.deploy(**self.arguments(execute=False))
        self.assertEqual(code, 2, report)
        self.assertEqual(report["failed_stage"], "admission")

    def test_staged_bytes_must_match_commit_before_activation(self):
        original = dev_deploy.stage_runtime_bundle

        def stage_then_tamper(source, target):
            digest = original(source, target)
            path = target / "scripts/governance_errors.py"
            path.write_bytes(path.read_bytes() + b"\n# staged tampering\n")
            return digest

        runner = mock.Mock()
        before = dev_deploy._safe_tree_digest(self.stable)
        with mock.patch.object(dev_deploy, "stage_runtime_bundle", side_effect=stage_then_tamper):
            code, report = dev_deploy.deploy(**self.arguments(), runner=runner)
        self.assertEqual(code, 2, report)
        runner.assert_not_called()
        self.assertEqual(report["state"], "deploy_failed_rolled_back", report)
        self.assertEqual(dev_deploy._safe_tree_digest(self.stable), before)

    def test_partial_cache_restore_failure_is_recoverable_on_next_deploy(self):
        previous = "0.3.0+codex.previous"
        self.cache(previous)
        digest = dev_deploy._safe_tree_digest(self.cache_parent / previous)
        original = shutil.copytree

        def fail_restore(source, target, *args, **kwargs):
            if Path(target) == self.cache_parent / previous:
                Path(target).mkdir()
                raise OSError("injected partial restore")
            return original(source, target, *args, **kwargs)

        with mock.patch.object(dev_deploy.shutil, "copytree", side_effect=fail_restore):
            code, report = dev_deploy.deploy(
                **self.arguments(previous_version=previous),
                runner=self.native_runner(returncode=1))
        self.assertEqual(code, 2)
        self.assertEqual(report["state"], "rollback_failed", report)
        self.assertIn("返回 1", report["error"])
        self.assertIn("injected partial restore", report["rollback_error"])
        code, report = dev_deploy.deploy(
            **self.arguments(previous_version=previous), runner=self.native_runner())
        self.assertEqual(code, 0, report)
        self.assertTrue(report["recovered_interrupted_transaction"])
        self.assertEqual(dev_deploy._safe_tree_digest(self.cache_parent / previous), digest)

    def test_hidden_source_change_during_install_rolls_back(self):
        relative = "scripts/governance_errors.py"
        subprocess.run(["git", "-C", str(self.source), "update-index",
                        "--skip-worktree", relative], check=True)
        native = self.native_runner()
        before = dev_deploy._safe_tree_digest(self.stable)

        def install_and_mutate(*args, **kwargs):
            result = native(*args, **kwargs)
            path = self.source / relative
            path.write_bytes(path.read_bytes() + b"\n# changed during install\n")
            return result

        code, report = dev_deploy.deploy(**self.arguments(), runner=install_and_mutate)
        self.assertEqual(code, 2)
        self.assertEqual(report["state"], "deploy_failed_rolled_back", report)
        self.assertEqual(dev_deploy._safe_tree_digest(self.stable), before)
        self.assertEqual(list(self.cache_parent.iterdir()), [])

    def test_source_change_before_staging_cannot_be_installed(self):
        before = dev_deploy._safe_tree_digest(self.stable)

        def mutate(stage):
            if stage == "after_snapshot":
                path = self.source / "scripts/governance_errors.py"
                path.write_bytes(path.read_bytes() + b"\n# changed before staging\n")

        runner = mock.Mock()
        with mock.patch.object(dev_deploy, "_failpoint", side_effect=mutate):
            code, report = dev_deploy.deploy(**self.arguments(), runner=runner)
        self.assertEqual(code, 2)
        runner.assert_not_called()
        self.assertEqual(report["state"], "deploy_failed_rolled_back", report)
        self.assertEqual(dev_deploy._safe_tree_digest(self.stable), before)

    def test_git_clean_crlf_conversion_is_rejected_as_different_raw_bytes(self):
        relative = "scripts/governance_errors.py"
        (self.source / ".gitattributes").write_text(f"{relative} text eol=crlf\n")
        subprocess.run(["git", "-C", str(self.source), "add", ".gitattributes"], check=True)
        subprocess.run(["git", "-C", str(self.source), "commit", "-qm", "CRLF checkout"],
                       check=True)
        self.head = dev_deploy._git(self.source, "rev-parse", "HEAD").strip()
        path = self.source / relative
        path.unlink()
        subprocess.run(["git", "-C", str(self.source), "checkout", "--", relative], check=True)
        self.assertIn(b"\r\n", path.read_bytes())
        self.assertEqual(dev_deploy._git(self.source, "status", "--porcelain"), "")
        code, report = dev_deploy.deploy(**self.arguments(execute=False))
        self.assertEqual(code, 2, report)
        self.assertIn(relative, report["error"])

    def test_replacement_blob_cannot_override_expected_commit_bytes(self):
        relative = "scripts/governance_errors.py"
        old_oid = dev_deploy._git(self.source, "rev-parse", f"HEAD:{relative}").strip()
        path = self.source / relative
        path.write_bytes(path.read_bytes() + b"\n# replacement content\n")
        new_oid = subprocess.check_output(
            ["git", "-C", str(self.source), "hash-object", "-w", str(path)], text=True).strip()
        subprocess.run(["git", "-C", str(self.source), "replace", old_oid, new_oid], check=True)
        subprocess.run(["git", "-C", str(self.source), "update-index", "--assume-unchanged",
                        relative], check=True)
        code, report = dev_deploy.deploy(**self.arguments(execute=False))
        self.assertEqual(code, 2, report)
        self.assertIn(relative, report["error"])

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

    def competing_deploy(self):
        """Probe from another process, stopping before any recovery or install writes."""
        script = """
import json
import sys
from pathlib import Path
from unittest import mock
from scripts import dev_deploy

arguments = json.loads(sys.argv[1])
for name in ('source_root', 'stable_root', 'cache_parent', 'transaction_parent'):
    arguments[name] = Path(arguments[name])
with mock.patch.object(
    dev_deploy, '_recover_interrupted', side_effect=RuntimeError('probe entered')
) as recovery, mock.patch.object(dev_deploy, '_recover_transaction') as rollback:
    runner = mock.Mock()
    code, report = dev_deploy.deploy(**arguments, runner=runner)
print(json.dumps(dict(code=code, report=report, entered=recovery.called,
                     rolled_back=rollback.called, installed=runner.called)))
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script, json.dumps(self.arguments(), default=str)],
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=15,
        )
        return json.loads(result.stdout)

    def assert_competitor_blocked(self):
        result = self.competing_deploy()
        self.assertFalse(result["entered"], result)
        self.assertFalse(result["rolled_back"], result)
        self.assertFalse(result["installed"], result)
        self.assertEqual(result["code"], 2)
        self.assertEqual(result["report"]["state"], "deploy_failed")
        self.assertEqual(result["report"]["failed_stage"], "admission")
        self.assertIn("已有开发部署事务正在运行", result["report"]["error"])

    def test_deployment_and_success_cleanup_hold_lock_until_return(self):
        native = self.native_runner()
        remove = dev_deploy._safe_remove_tree
        observed = []

        def runner(*args, **kwargs):
            self.assert_competitor_blocked()
            self.assert_competitor_blocked()  # Failed acquisition must not unlock the owner.
            observed.append("install")
            return native(*args, **kwargs)

        def cleanup(*args, **kwargs):
            self.assert_competitor_blocked()
            observed.append("cleanup")
            return remove(*args, **kwargs)

        with mock.patch.object(dev_deploy, "_safe_remove_tree", side_effect=cleanup):
            code, report = dev_deploy.deploy(**self.arguments(), runner=runner)
        self.assertEqual(code, 0, report)
        self.assertEqual(observed, ["install", "cleanup"])
        self.assertTrue(self.competing_deploy()["entered"])

    def test_rollback_holds_lock_through_restore_verification_and_cleanup(self):
        recover = dev_deploy._recover_transaction
        restore_cache = dev_deploy._restore_cache_snapshot
        observed = []
        stable_digest = dev_deploy._safe_tree_digest(self.stable)

        def restoring(*args, **kwargs):
            self.assert_competitor_blocked()
            restore_cache(*args, **kwargs)
            self.assert_competitor_blocked()
            observed.append("cache_restored")

        def recovering(*args, **kwargs):
            self.assert_competitor_blocked()
            recover(*args, **kwargs)
            self.assert_competitor_blocked()
            observed.append("rollback_complete")

        with (
            mock.patch.object(dev_deploy, "_recover_transaction", side_effect=recovering),
            mock.patch.object(dev_deploy, "_restore_cache_snapshot", side_effect=restoring),
        ):
            code, report = dev_deploy.deploy(
                **self.arguments(), runner=self.native_runner(returncode=1),
            )
        self.assertEqual(code, 2, report)
        self.assertEqual(report["state"], "deploy_failed_rolled_back", report)
        self.assertEqual(observed, ["cache_restored", "rollback_complete"])
        self.assertEqual(dev_deploy._safe_tree_digest(self.stable), stable_digest)
        self.assertEqual(list(self.transactions.glob("transaction-*")), [])
        self.assertTrue(self.competing_deploy()["entered"])

    def test_rollback_failure_preserves_evidence_and_releases_lock(self):
        def failed_recovery(*args):
            self.assert_competitor_blocked()
            raise RuntimeError("injected recovery failure")

        with mock.patch.object(dev_deploy, "_recover_transaction", side_effect=failed_recovery):
            code, report = dev_deploy.deploy(
                **self.arguments(), runner=self.native_runner(returncode=1),
            )
        self.assertEqual(code, 2)
        self.assertEqual(report["state"], "rollback_failed")
        self.assertEqual(report["failed_stage"], "codex_command")
        self.assertIn("返回 1", report["error"])
        self.assertEqual(report["rollback_error"], "injected recovery failure")
        transactions = list(self.transactions.glob("transaction-*"))
        self.assertEqual(len(transactions), 1)
        self.assertTrue((transactions[0] / dev_deploy.TRANSACTION_MANIFEST).is_file())
        self.assertTrue((transactions[0] / dev_deploy.STABLE_SNAPSHOT).is_dir())
        self.assertTrue(self.competing_deploy()["entered"])

    @unittest.skipIf(dev_deploy.fcntl is None, "POSIX lock acquisition failure")
    def test_failed_lock_acquisition_does_not_attempt_unlock(self):
        with mock.patch.object(
            dev_deploy.fcntl, "flock", side_effect=BlockingIOError("busy")
        ) as flock:
            with self.assertRaisesRegex(RuntimeError, "已有开发部署事务正在运行"):
                with dev_deploy._operation_lock(self.transactions):
                    self.fail("lock body must not run")
        self.assertEqual(flock.call_count, 1)

    def test_invalid_source_admission_has_no_deployment_writes(self):
        before = dev_deploy._safe_tree_digest(self.stable)
        runner = mock.Mock()
        code, report = dev_deploy.deploy(
            **self.arguments(expected_head="0" * 40), runner=runner,
        )
        self.assertEqual(code, 2)
        self.assertEqual(report["failed_stage"], "admission")
        runner.assert_not_called()
        self.assertEqual(dev_deploy._safe_tree_digest(self.stable), before)
        self.assertEqual(list(self.transactions.iterdir()), [])
        self.assertEqual(list(self.cache_parent.iterdir()), [])

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
