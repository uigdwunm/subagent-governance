#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

from scripts import governance_semantics as semantics
from tests.schema_validation import assert_schema_supported, validate_instance
from tests.support import load_governance

governance = load_governance("canonical_schema")


class CanonicalRecordSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.store = governance.StateStore(root / "sessions")
        self.session_id = "session-v5-schema"

    @staticmethod
    def contract():
        return governance.TaskContract(
            semantic_name="v5_schema",
            requested_mode="standard",
            resolved_mode="standard",
            resolution_reason="explicit_request",
            task_features={
                "risk": "medium",
                "read_only": False,
                "writes_files": True,
                "destructive": False,
                "production": False,
                "concurrent_write": False,
            },
            objective="验证 canonical record Schema",
            background="v5 three-plane fixture",
            work_scope=["canonical records"],
            forbidden_scope=["formal result persistence"],
            completion_conditions=["Schema validation passes"],
            evidence_requirements=["unit test"],
            relevant_files=[],
            context_manifest={"mode": "none"},
            current_state=None,
            model=None,
            reasoning_effort=None,
            context_strategy="isolated",
            context_turns=None,
            context_reason=None,
        )

    def definition(self, name):
        return semantics.MACHINE_SEMANTICS["$defs"][name]

    def assert_valid(self, value, definition_name):
        errors = validate_instance(
            value,
            self.definition(definition_name),
            root_schema=semantics.MACHINE_SEMANTICS,
        )
        self.assertEqual([str(error) for error in errors], [])

    def initial_execution(self, task_id="v5-schema-task"):
        record = governance._initial_task_record(
            1,
            "0123456789ab",
            "sg_standard_v5_schema_t_0123456789ab",
            self.contract(),
            100,
        )
        return record, record["executions"]["1"]

    def test_repository_schema_uses_supported_keywords(self):
        assert_schema_supported(semantics.MACHINE_SEMANTICS)

    def test_runtime_required_field_sets_match_schema(self):
        mappings = {
            "canonical_task_container": semantics.REQUIRED_TASK_CONTAINER_FIELDS,
            "work_item": semantics.REQUIRED_WORK_ITEM_FIELDS,
            "execution_record": semantics.REQUIRED_EXECUTION_FIELDS,
            "dispatch_record": semantics.REQUIRED_DISPATCH_RECORD_FIELDS,
            "observation_record": semantics.REQUIRED_OBSERVATION_RECORD_FIELDS,
            "closure_record": semantics.REQUIRED_CLOSURE_RECORD_FIELDS,
            "pending_action": semantics.REQUIRED_PENDING_ACTION_FIELDS,
            "lifecycle_operation": semantics.REQUIRED_LIFECYCLE_OPERATION_FIELDS,
        }
        for definition_name, runtime_fields in mappings.items():
            with self.subTest(definition=definition_name):
                self.assertEqual(
                    set(runtime_fields),
                    set(self.definition(definition_name)["required"]),
                )

    def test_runtime_enums_match_schema(self):
        mappings = {
            "operation_type": governance.OPERATION_TYPES,
            "parent_action": governance.PARENT_ACTIONS,
            "parent_disposition": governance.PARENT_DISPOSITIONS,
            "observation_source": governance.OBSERVATION_SOURCES,
        }
        for definition_name, runtime_values in mappings.items():
            with self.subTest(definition=definition_name):
                self.assertEqual(
                    set(self.definition(definition_name)["enum"]),
                    set(runtime_values),
                )

    def test_initial_runtime_record_validates_as_three_plane_container(self):
        container, execution = self.initial_execution()
        task_id = "v5-schema-task"
        state = governance.StateStore._empty_state(self.session_id)
        self.assertEqual(self.definition("canonical_state")["properties"]["updated_at"], False)
        state["tasks"][task_id] = container
        stored = governance._state_for_storage(state)["tasks"][task_id]
        self.assert_valid(stored, "canonical_task_container")
        self.assert_valid(stored["executions"]["1"], "execution_record")

    def test_canonical_state_validates_task_identity_from_tasks_key(self):
        container, _execution = self.initial_execution()
        state = governance.StateStore._empty_state(self.session_id)
        state["tasks"][""] = container
        errors = validate_instance(
            state,
            self.definition("canonical_state"),
            root_schema=semantics.MACHINE_SEMANTICS,
        )
        self.assertTrue(
            any("tasks.<name>" in str(error) for error in errors),
            [str(error) for error in errors],
        )

    def test_canonical_state_validates_attempt_identity_from_execution_key(self):
        container, _execution = self.initial_execution()
        container["executions"]["01"] = container["executions"].pop("1")
        state = governance.StateStore._empty_state(self.session_id)
        state["tasks"]["v5-schema-task"] = container
        errors = validate_instance(
            state,
            self.definition("canonical_state"),
            root_schema=semantics.MACHINE_SEMANTICS,
        )
        self.assertTrue(
            any("executions.01" in str(error) for error in errors),
            [str(error) for error in errors],
        )

    def test_terminal_notification_and_close_records_validate(self):
        container, execution = self.initial_execution()
        task_id = "v5-schema-task"
        target = "/root/v5_schema"
        execution["dispatch_record"].update(
            dispatch_state="acknowledged",
            dispatch_target=target,
            tool_use_id="tool-v5",
        )
        state = governance.StateStore._empty_state(self.session_id)
        state["tasks"][task_id] = container
        state["agents"][target] = {"task_id": task_id, "attempt": 1}
        self.store.update(self.session_id, lambda current: current.update(state))

        governance.record_terminal_notification(
            {
                "sender_target": target,
                "task_id": task_id,
                "attempt": 1,
                "terminal_status": "completed",
            },
            self.session_id,
            state_store=self.store,
            now=120,
        )
        governance.apply_parent_disposition(
            {
                "task_id": task_id,
                "attempt": 1,
                "action": "close_task",
                "reason": "父 Agent 已读取原生终态通知",
            },
            self.session_id,
            state_store=self.store,
            now=130,
        )

        current_state = governance._state_for_storage(self.store.read(self.session_id))
        current = current_state["tasks"][task_id]
        tombstone = current_state["tombstones"][f"{task_id}:1"]
        self.assert_valid(current, "canonical_task_container")
        self.assert_valid(tombstone, "tombstone_record")
        execution = current["executions"]["1"]
        self.assertTrue(governance._execution_is_closed(execution))

if __name__ == "__main__":
    unittest.main()
