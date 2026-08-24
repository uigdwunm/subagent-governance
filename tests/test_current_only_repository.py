import unittest

from tests.support import ROOT


class CurrentOnlyRepositoryTests(unittest.TestCase):
    def test_only_current_documents_are_shipped(self):
        documents = {
            str(path.relative_to(ROOT))
            for path in (ROOT / "docs").rglob("*")
            if path.is_file()
            and not path.name.startswith("private-platform-evidence-")
            and "improvement-plans" not in path.parts
        }
        self.assertEqual(
            documents,
            {
                "docs/architecture.md",
                "docs/context-completeness-contract.md",
                "docs/interruption-reconciliation.md",
                "docs/platform-validation.md",
                "docs/release-process.md",
            },
        )

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
