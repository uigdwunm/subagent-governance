import unittest

from scripts import governance_semantics as semantics


class SemanticBaselineTests(unittest.TestCase):
    def test_current_only_versions_and_phases(self):
        self.assertEqual(semantics.STATE_FORMAT_VERSION, 9)
        self.assertEqual(semantics.STATE_STORAGE_NAMESPACE, "state-v9")
        self.assertEqual(semantics.TASK_CONTRACT_WIRE_VERSION, 2)
        self.assertEqual(
            semantics.PHASES,
            {"prepared", "claimed", "bound", "terminal", "closed", "reconcile"},
        )

    def test_removed_authorities_are_absent_from_machine_semantics(self):
        encoded = str(semantics.MACHINE_SEMANTICS)
        for removed in ("attempt", "agents", "groups", "tombstones", "pending_action", "post_receipt"):
            self.assertNotIn(removed, encoded)


if __name__ == "__main__":
    unittest.main()
