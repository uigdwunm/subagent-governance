import unittest

from tests.support import load_governance

governance = load_governance("semantic_baseline")


class SemanticBaselineTests(unittest.TestCase):
    def test_current_state_format_is_v5(self):
        self.assertEqual(governance.STATE_FORMAT_VERSION, 5)
        self.assertEqual(
            governance.SEMANTIC_RULES["canonical_record"]["state_format_version"],
            5,
        )

    def test_parent_disposition_is_lifecycle_only(self):
        self.assertEqual(governance.PARENT_DISPOSITIONS, {"close_task"})
        self.assertEqual(
            governance.OPERATION_TYPES,
            {"normal_message", "platform_recovery", "business_resume"},
        )

    def test_decision_action_order_has_one_machine_semantics_source(self):
        self.assertEqual(
            governance._DECISION_ACTION_ORDER,
            tuple(governance.SEMANTIC_DEFINITIONS["decision_allowed_action"]["enum"]),
        )

    def test_operation_native_tools_match_supported_operations(self):
        self.assertEqual(
            governance.OPERATION_NATIVE_TOOLS,
            {
                "normal_message": "send_message",
                "platform_recovery": "followup_task",
                "business_resume": "followup_task",
                "interrupt": "interrupt_agent",
            },
        )

    def test_terminal_notification_channel_requires_exact_sender_binding(self):
        semantics = governance.SEMANTIC_RULES["terminal_notification_channel"]
        self.assertEqual(
            semantics["scope"],
            ["task_id", "attempt", "sender_target", "terminal_status"],
        )
        self.assertEqual(
            semantics["sender_binding"], "exact_task_attempt_dispatch_target"
        )
        self.assertFalse(semantics["scans_notification_body"])
        self.assertFalse(semantics["persists_notification_body"])

    def test_canonical_planes_are_dispatch_observation_and_closure(self):
        self.assertEqual(
            governance.SEMANTIC_RULES["canonical_record"]["execution_plane_fields"],
            ["dispatch_record", "observation_record", "closure_record"],
        )

    def test_task_name_regex_comes_from_machine_semantics(self):
        self.assertEqual(
            governance.TASK_NAME_RE.pattern,
            governance.SEMANTIC_RULES["task_name"]["pattern"],
        )


if __name__ == "__main__":
    unittest.main()
