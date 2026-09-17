import unittest

from tests.support import ROOT

VALIDATION_DOCUMENTS = {
    "docs/validation/heterogeneous-real-acceptance-2026-09-17.md",
    "docs/validation/J-deployment-recovery-source-consistency.md",
    "docs/validation/current-only-local-acceptance.md",
    "docs/validation/native-compatibility-2026-09-16.md",
    "docs/validation/current-only-real-platform-validation.md",
    "docs/validation/native-context-adapter-2026-09-06.md",
    "docs/validation/native-tool-contract-adaptation-implementation-2026-09-06.md",
    "docs/validation/state-v10-hook-trust-2026-09-09.md",
}


CURRENT_DOCUMENTS = {
    "docs/architecture-reduction-adr.md",
    "docs/architecture.md",
    "docs/context-completeness-contract.md",
    "docs/interruption-reconciliation.md",
    "docs/native-codex-governance-evidence.md",
    "docs/platform-validation.md",
    "docs/native-compatibility-matrix.md",
    "docs/release-process.md",
} | VALIDATION_DOCUMENTS


def _shipped_documents():
    return {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "docs").rglob("*")
        if path.is_file()
        and not path.name.startswith("private-platform-evidence-")
        and "improvement-plans" not in path.parts
    }


class CurrentOnlyRepositoryTests(unittest.TestCase):
    def test_only_current_documents_are_shipped(self):
        self.assertEqual(_shipped_documents(), CURRENT_DOCUMENTS)

    def test_unknown_validation_document_is_not_shipped(self):
        unknown_document = ROOT / "docs/validation/unexpected-validation.md"
        try:
            unknown_document.write_text("fixture\n", encoding="utf-8")
            with self.assertRaises(AssertionError):
                self.assertEqual(_shipped_documents(), CURRENT_DOCUMENTS)
        finally:
            unknown_document.unlink(missing_ok=True)

    def test_third_validation_document_is_not_shipped(self):
        third_document = ROOT / "docs/validation/third-arbitrary-validation.md"
        try:
            third_document.write_text("fixture\n", encoding="utf-8")
            with self.assertRaises(AssertionError):
                self.assertEqual(_shipped_documents(), CURRENT_DOCUMENTS)
        finally:
            third_document.unlink(missing_ok=True)

    def test_runtime_has_no_state_conversion_path(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "scripts").glob("governance_*.py"))
        )
        source += (ROOT / "scripts" / "subagent_governance.py").read_text(
            encoding="utf-8"
        )
        for forbidden in ("_mi" + "grate_", "LEG" + "ACY_", "RET" + "IRED_"):
            with self.subTest(symbol=forbidden):
                self.assertNotIn(forbidden, source)

    def test_runtime_uses_explicit_imports(self):
        for path in sorted((ROOT / "scripts").glob("*.py")):
            with self.subTest(path=path.name):
                self.assertNotIn("import " + "*", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
