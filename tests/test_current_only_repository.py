import unittest

from tests.support import ROOT


VALIDATION_DOCUMENTS = {
    "docs/validation/current-only-local-acceptance.md",
    "docs/validation/current-only-real-platform-validation.md",
}


CURRENT_DOCUMENTS = {
    "docs/architecture.md",
    "docs/context-completeness-contract.md",
    "docs/interruption-reconciliation.md",
    "docs/platform-validation.md",
    "docs/release-process.md",
} | VALIDATION_DOCUMENTS


def _shipped_documents():
    return {
        str(path.relative_to(ROOT))
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
