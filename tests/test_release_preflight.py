#!/usr/bin/env python3

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/release_preflight.py"
SPEC = importlib.util.spec_from_file_location("release_preflight", SCRIPT)
preflight = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(preflight)


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
            "README.en.md",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
        ):
            shutil.copy2(ROOT / relative, destination / relative)

    def marketplace_path(self, root: Path) -> Path:
        return root / ".agents/plugins/marketplace.json"

    def set_marketplace_ref(self, root: Path, ref: str) -> None:
        path = self.marketplace_path(root)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["plugins"][0]["source"]["ref"] = ref
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def test_current_development_tree_passes_with_supported_ref(self):
        report = preflight.run_preflight(ROOT, "development")
        self.assertEqual(report["status"], "passed")
        self.assertIn(report["marketplace_ref"], {"main", "v0.4.0-rc.10"})
        self.assertEqual(report["expected_tag"], "v0.4.0-rc.10")

    def test_release_requires_manifest_tag_and_marketplace_ref_to_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.copy_public_tree(root)
            self.set_marketplace_ref(root, "main")
            with self.assertRaisesRegex(
                preflight.PreflightFailure, "release marketplace ref"
            ):
                preflight.run_preflight(root, "release", "v0.4.0-rc.10")
            self.set_marketplace_ref(root, "v0.4.0-rc.10")
            report = preflight.run_preflight(
                root, "release", "v0.4.0-rc.10"
            )
            self.assertEqual(report["status"], "passed")

    def test_release_rejects_tag_that_disagrees_with_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.copy_public_tree(root)
            self.set_marketplace_ref(root, "v0.4.0-rc.11")
            with self.assertRaisesRegex(preflight.PreflightFailure, "release tag"):
                preflight.run_preflight(root, "release", "v0.4.0-rc.11")

    def test_archive_rejects_private_platform_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.copy_public_tree(root)
            report = root / "docs/real-platform-test-private.md"
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


if __name__ == "__main__":
    unittest.main()
