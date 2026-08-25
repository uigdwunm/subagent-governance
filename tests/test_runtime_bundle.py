#!/usr/bin/env python3
"""Runtime allowlist and bundle-digest acceptance tests."""

from __future__ import annotations

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts import runtime_bundle
from tests.support import ROOT


EXPECTED_RUNTIME_FILES = {
    ".codex-plugin/plugin.json",
    ".codex-plugin/runtime-bundle.json",
    "LICENSE",
    "README.md",
    "hooks/hooks.json",
    "schemas/governance-semantics.schema.json",
    "schemas/task-contract-v2.schema.json",
    "scripts/governance_cli.py",
    "scripts/governance_context.py",
    "scripts/governance_contracts.py",
    "scripts/governance_diagnostics.py",
    "scripts/governance_dispatch.py",
    "scripts/governance_dispatch_identity.py",
    "scripts/governance_dispatch_rendering.py",
    "scripts/governance_errors.py",
    "scripts/governance_hook.py",
    "scripts/governance_input.py",
    "scripts/governance_lifecycle.py",
    "scripts/governance_protocol.py",
    "scripts/governance_semantics.py",
    "scripts/governance_state.py",
    "scripts/governance_state_store.py",
    "scripts/governance_storage.py",
    "scripts/governance_store_support.py",
    "scripts/governance_validation.py",
    "scripts/subagent_governance.py",
    "skills/subagent-governance/SKILL.md",
    "skills/subagent-governance/agents/openai.yaml",
    "skills/subagent-governance/references/governance-profiles.md",
    "skills/subagent-governance/references/runtime-boundaries.md",
}


class RuntimeBundleTests(unittest.TestCase):
    def test_machine_allowlist_is_exact_minimal_and_all_files_exist(self):
        manifest = json.loads(
            (ROOT / ".codex-plugin/runtime-bundle.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(manifest), {"format_version", "files"})
        self.assertEqual(manifest["format_version"], 1)
        self.assertEqual(manifest["files"], sorted(EXPECTED_RUNTIME_FILES))
        self.assertEqual(runtime_bundle.runtime_files(ROOT), tuple(manifest["files"]))
        for relative in manifest["files"]:
            self.assertTrue((ROOT / relative).is_file(), relative)

        forbidden_parts = {
            "tests", ".github", "improvement-plans", "validation", "AGENTS.md",
            "requirements-dev.txt", "pyproject.toml",
        }
        forbidden_names = {
            "dev_deploy.py", "release_preflight.py", "apply_agents_block.py",
            "check_installation.py", "reinstall_plugin.py", "sync_stable_plugin.py",
        }
        for relative in manifest["files"]:
            path = Path(relative)
            self.assertFalse(forbidden_parts.intersection(path.parts), relative)
            self.assertNotIn(path.name, forbidden_names)

    def test_bundle_staging_is_exact_and_digest_ignores_development_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bundle"
            digest = runtime_bundle.stage_runtime_bundle(ROOT, target)
            staged = {
                str(path.relative_to(target))
                for path in target.rglob("*")
                if path.is_file()
            }
            self.assertEqual(staged, EXPECTED_RUNTIME_FILES)
            self.assertEqual(digest, runtime_bundle.bundle_digest(target))
            self.assertEqual(digest, runtime_bundle.bundle_digest(ROOT))

            excluded = target / "tests/noise.txt"
            excluded.parent.mkdir()
            excluded.write_text("development-only change\n", encoding="utf-8")
            self.assertEqual(runtime_bundle.bundle_digest(target), digest)
            with self.assertRaisesRegex(RuntimeError, "文件集合不精确"):
                runtime_bundle.verify_runtime_bundle(target)
            excluded.unlink()
            excluded.parent.rmdir()

            runtime_path = target / "scripts/governance_errors.py"
            runtime_path.write_text(
                runtime_path.read_text(encoding="utf-8") + "\n# runtime change\n",
                encoding="utf-8",
            )
            self.assertNotEqual(runtime_bundle.bundle_digest(target), digest)

    def test_allowlisted_python_imports_are_closed_over_runtime_modules(self):
        allowed = set(runtime_bundle.runtime_files(ROOT))
        for relative in sorted(path for path in allowed if path.endswith(".py")):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                module = node.module
                if module.startswith("scripts.governance_"):
                    dependency = module.replace(".", "/") + ".py"
                elif module.startswith("governance_"):
                    dependency = "scripts/" + module + ".py"
                else:
                    continue
                self.assertIn(dependency, allowed, f"{relative} imports {dependency}")

    def test_symlinked_allowlisted_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            runtime_bundle.stage_runtime_bundle(ROOT, source)
            target = source / "scripts/governance_errors.py"
            target.unlink()
            target.symlink_to(ROOT / "scripts/governance_errors.py")
            with self.assertRaisesRegex(RuntimeError, "符号链接"):
                runtime_bundle.bundle_digest(source)

    def test_symlinked_allowlisted_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            runtime_bundle.stage_runtime_bundle(ROOT, source)
            scripts = source / "scripts"
            relocated = source / "relocated-scripts"
            scripts.rename(relocated)
            scripts.symlink_to(relocated, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "符号链接"):
                runtime_bundle.bundle_digest(source)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are required")
    def test_group_writable_allowlisted_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            runtime_bundle.stage_runtime_bundle(ROOT, source)
            target = source / "scripts/governance_errors.py"
            target.chmod(target.stat().st_mode | 0o020)
            with self.assertRaisesRegex(PermissionError, "组用户或其他用户写入"):
                runtime_bundle.bundle_digest(source)


if __name__ == "__main__":
    unittest.main()
