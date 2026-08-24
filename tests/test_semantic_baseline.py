import unittest

from scripts import governance_semantics as semantics


class SemanticBaselineTests(unittest.TestCase):
    def test_current_state_format_is_v8(self):
        self.assertEqual(semantics.STATE_FORMAT_VERSION, 8)
        self.assertEqual(
            semantics.SEMANTIC_RULES["canonical_record"]["state_format_version"],
            8,
        )

    def test_parent_disposition_is_lifecycle_only(self):
        self.assertEqual(semantics.PARENT_DISPOSITIONS, {"close_task"})
        self.assertEqual(
            semantics.OPERATION_TYPES,
            {"normal_message", "platform_recovery", "business_resume"},
        )

    def test_decision_action_order_has_one_machine_semantics_source(self):
        self.assertEqual(
            semantics._DECISION_ACTION_ORDER,
            tuple(semantics.SEMANTIC_DEFINITIONS["decision_allowed_action"]["enum"]),
        )

    def test_operation_native_tools_match_supported_operations(self):
        self.assertEqual(
            semantics.OPERATION_NATIVE_TOOLS,
            {
                "normal_message": "send_message",
                "platform_recovery": "followup_task",
                "business_resume": "followup_task",
                "interrupt": "interrupt_agent",
            },
        )

    def test_terminal_notification_channel_requires_exact_sender_binding(self):
        channel = semantics.SEMANTIC_RULES["terminal_notification_channel"]
        self.assertEqual(
            channel["scope"],
            ["task_id", "attempt", "sender_target", "terminal_status"],
        )
        self.assertEqual(
            channel["sender_binding"], "exact_task_attempt_dispatch_target"
        )
        self.assertFalse(channel["scans_notification_body"])
        self.assertFalse(channel["persists_notification_body"])

    def test_canonical_planes_are_dispatch_observation_and_closure(self):
        self.assertEqual(
            semantics.SEMANTIC_RULES["canonical_record"]["execution_plane_fields"],
            ["dispatch_record", "observation_record", "closure_record"],
        )

    def test_task_name_runtime_and_schema_share_one_definition(self):
        definition = semantics.SEMANTIC_DEFINITIONS["task_name"]
        self.assertEqual(
            semantics.TASK_NAME_RE.pattern,
            definition["pattern"],
        )
        self.assertEqual(semantics.TASK_NAME_MAX_LENGTH, definition["maxLength"])
        self.assertEqual(
            semantics.TASK_REF_LENGTHS,
            tuple(definition["x-task-ref-lengths"]),
        )


if __name__ == "__main__":
    unittest.main()
