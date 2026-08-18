import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_semantics_v5", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class SemanticBaselineTests(unittest.TestCase):
    def test_current_state_format_is_v5(self):
        self.assertEqual(governance.STATE_FORMAT_VERSION, 5)
        self.assertEqual(
            governance.SEMANTIC_RULES["canonical_record"]["state_format_version"],
            5,
        )

    def test_operation_types_exclude_result_correction(self):
        self.assertEqual(
            governance.OPERATION_TYPES,
            {"normal_message", "platform_recovery", "business_resume"},
        )
        self.assertEqual(
            governance.LIFECYCLE_OPERATION_TYPES,
            {"platform_recovery", "business_resume", "interrupt"},
        )

    def test_parent_disposition_is_lifecycle_only(self):
        self.assertEqual(governance.PARENT_DISPOSITIONS, {"close_task"})
        self.assertFalse(hasattr(governance, "CLOSURE_DISPOSITIONS"))
        self.assertNotIn("closure_disposition", governance.SEMANTIC_DEFINITIONS)
        self.assertNotIn("accept_result", governance.PARENT_ACTIONS)
        self.assertNotIn("correct_result", governance.PARENT_ACTIONS)
        self.assertNotIn("resolve_duplicate", governance.PARENT_ACTIONS)
        self.assertNotIn("manual_review", governance.PARENT_ACTIONS)
        self.assertNotIn("business_resume", governance.PARENT_ACTIONS)
        self.assertIn("business_resume", governance.OPERATION_TYPES)

    def test_decision_action_order_has_one_machine_semantics_source(self):
        self.assertEqual(
            governance._DECISION_ACTION_ORDER,
            tuple(governance.SEMANTIC_DEFINITIONS["decision_allowed_action"]["enum"]),
        )
        self.assertNotIn(
            "allowed_action_order",
            governance.SEMANTIC_RULES["work_item_decision_snapshot"],
        )
        self.assertNotIn(
            "resume_business_action_basis",
            governance.SEMANTIC_RULES["work_item_decision_snapshot"],
        )
        self.assertNotIn(
            "outputs_notification_body",
            governance.SEMANTIC_RULES["work_item_decision_snapshot"],
        )

    def test_retired_execution_auxiliary_semantics_are_absent(self):
        self.assertFalse(hasattr(governance, "prepare_replacement_dispatch"))
        self.assertNotIn("dispatch_kind", governance.SEMANTIC_DEFINITIONS)
        self.assertNotIn("dispatch_transition", governance.SEMANTIC_DEFINITIONS)
        self.assertNotIn("growth_authorization_action", governance.SEMANTIC_DEFINITIONS)
        self.assertNotIn("growth_authorization", governance.SEMANTIC_DEFINITIONS)
        self.assertNotIn("decision_growth_projection", governance.SEMANTIC_DEFINITIONS)
        self.assertNotIn("growth_projection", governance.SEMANTIC_RULES)
        self.assertNotIn("deliverable_contract", governance.SEMANTIC_DEFINITIONS)
        self.assertNotIn("recovery_status", governance.SEMANTIC_DEFINITIONS)
        self.assertFalse(hasattr(governance, "build_deliverable_contract"))

    def test_legacy_initial_attempt_projection_is_not_defined(self):
        self.assertNotIn("initial_attempt_state", governance.SEMANTIC_RULES)
        self.assertNotIn("attempt_state_fields", governance.SEMANTIC_RULES)
        self.assertFalse(hasattr(governance, "INITIAL_ATTEMPT_STATE"))

    def test_redundant_field_lists_are_not_machine_semantics(self):
        for field_list in (
            "communication_fields",
            "pending_action_fields",
            "last_lifecycle_operation_fields",
        ):
            with self.subTest(field_list=field_list):
                self.assertNotIn(field_list, governance.SEMANTIC_RULES)

    def test_retry_limits_have_no_result_correction_budget(self):
        self.assertEqual(governance.RETRY_LIMITS, {"spawn": 2, "recovery": 2})

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

    def test_schema_has_no_task_result_or_result_diagnostic_contract(self):
        definitions = governance.SEMANTIC_DEFINITIONS
        for name in (
            "task_result",
            "result_record",
            "business_result",
            "acceptance_status",
            "decision_outcome_availability",
        ):
            self.assertNotIn(name, definitions)
        self.assertIn("decision_terminal_notification", definitions)

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
