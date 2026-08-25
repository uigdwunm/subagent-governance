#!/usr/bin/env python3

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT, load_module

SCRIPT = ROOT / "scripts/release_preflight.py"
preflight = load_module("release_preflight_test", SCRIPT)


class ReleasePreflightTests(unittest.TestCase):
    def copy_public_tree(self, destination: Path) -> None:
        for relative in (
            ".codex-plugin",
            ".agents",
            ".github",
            "hooks",
            "skills",
            "scripts",
            "docs",
        ):
            shutil.copytree(ROOT / relative, destination / relative)
        for relative in (
            "LICENSE",
            "README.md",
            "README.zh-CN.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
        ):
            shutil.copy2(ROOT / relative, destination / relative)

    def marketplace_path(self, root: Path) -> Path:
        return root / ".agents/plugins/marketplace.json"

    def manifest_path(self, root: Path) -> Path:
        return root / ".codex-plugin/plugin.json"

    def set_marketplace_ref(self, root: Path, ref: str) -> None:
        path = self.marketplace_path(root)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["plugins"][0]["source"]["ref"] = ref
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def test_current_development_tree_passes_with_supported_ref(self):
        report = preflight.run_preflight(ROOT, "development")
        self.assertEqual(report["status"], "passed")
        self.assertIn(report["marketplace_ref"], {"main", "v0.4.0-rc.15"})
        self.assertEqual(report["expected_tag"], "v0.4.0-rc.15")

    def test_release_requires_manifest_tag_and_marketplace_ref_to_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.copy_public_tree(root)
            self.set_marketplace_ref(root, "main")
            with self.assertRaisesRegex(
                preflight.PreflightFailure, "release marketplace ref"
            ):
                preflight.run_preflight(root, "release", "v0.4.0-rc.15")
            self.set_marketplace_ref(root, "v0.4.0-rc.15")
            report = preflight.run_preflight(
                root, "release", "v0.4.0-rc.15"
            )
            self.assertEqual(report["status"], "passed")

    def test_release_rejects_tag_that_disagrees_with_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.copy_public_tree(root)
            self.set_marketplace_ref(root, "v0.4.0-rc.12")
            with self.assertRaisesRegex(preflight.PreflightFailure, "release tag"):
                preflight.run_preflight(root, "release", "v0.4.0-rc.14")

    def test_archive_rejects_private_platform_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.copy_public_tree(root)
            report = root / "docs/private-platform-evidence-local.md"
            report.write_text("private evidence", encoding="utf-8")
            with self.assertRaisesRegex(
                preflight.PreflightFailure, "private platform evidence"
            ):
                preflight.run_preflight(root, "archive")

    def test_scanner_rejects_host_paths_and_common_secret_shapes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.copy_public_tree(root)
            leaked = root / "LEAK.md"
            leaked.write_text(
                "/" + "Users/example/private\n" + "gh" + "p_" + "A" * 24,
                encoding="utf-8",
            )
            with self.assertRaisesRegex(preflight.PreflightFailure, "host-specific"):
                preflight.run_preflight(root, "development")

    def test_manifest_rejects_unknown_fields_and_non_https_urls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.copy_public_tree(root)
            manifest_path = self.manifest_path(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            manifest["interface"]["unexpectedField"] = "must be rejected"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                preflight.PreflightFailure, "unsupported field"
            ):
                preflight.run_preflight(root, "development")

            manifest["interface"].pop("unexpectedField")
            manifest["homepage"] = "http://example.test/plugin"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                preflight.PreflightFailure, "homepage.*https"
            ):
                preflight.run_preflight(root, "development")


if __name__ == "__main__":
    unittest.main()
