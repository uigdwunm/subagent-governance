import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import governance_semantics as semantics
from tests.schema_validation import validate_instance
from tests.support import load_governance


from scripts import governance_contracts as contracts
from scripts import governance_diagnostics as diagnostics
from scripts import governance_dispatch as dispatch
from scripts import governance_errors as errors
from scripts import governance_execution as execution
from scripts import governance_groups as groups
from scripts import governance_hook as hook
from scripts import governance_lifecycle as lifecycle
from scripts import governance_prepared_store as prepared_store_module
from scripts import governance_protocol as protocol
from scripts import governance_semantics as semantics
from scripts import governance_state as state_domain
from scripts import governance_state_store as state_store_module
from scripts import governance_store_support as store_support
from scripts import governance_views as views


class V8StrictStateContractTests(unittest.TestCase):
    @staticmethod
    def contract():
        return contracts.TaskContract(
            semantic_name="v8_state",
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
            objective="verify v8 strict state contract",
            background="strict current-state corpus",
            work_scope=["state"],
            forbidden_scope=[],
            completion_conditions=["all mutations reject"],
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

    def canonical_state(self):
        state = state_store_module.StateStore._empty_state("v8-state")
        state["tasks"]["v8-state-task"] = dispatch.initial_task_record(
            1,
            "0123456789ab",
            "sg_standard_v8_state_t_0123456789ab",
            self.contract(),
            100,
        )
        return state

    def schema_errors(self, state):
        return validate_instance(
            state,
            semantics.MACHINE_SEMANTICS["$defs"]["canonical_state"],
            root_schema=semantics.MACHINE_SEMANTICS,
        )

    def assert_rejected_by_both(self, state):
        self.assertTrue(self.schema_errors(state))
        self.assertTrue(state_domain.validate_current_state_format(state))
        with self.assertRaises(errors.StateValidationError):
            state_domain.require_current_state_format(state)

    @staticmethod
    def invalid_task_names():
        return {
            "space": "bad name",
            "mode": "sg_legacy_task_t_0123456789ab",
            "semantic": "sg_standard_bad__name_t_0123456789ab",
            "short_ref": "sg_standard_task_t_0123456789a",
            "noncanonical_ref_length": "sg_standard_task_t_0123456789abc",
            "ref_character": "sg_standard_task_t_0123456789aG",
            "overlong": "sg_standard_" + ("a" * 64) + "_t_0123456789ab",
        }

    def test_v8_corpus_is_accepted_by_runtime_and_schema(self):
        state = self.canonical_state()
        self.assertEqual(semantics.STATE_FORMAT_VERSION, 8)
        self.assertEqual(self.schema_errors(state), [])
        self.assertEqual(state_domain.validate_current_state_format(state), [])
        self.assertIs(state_domain.require_current_state_format(state), state)

    def test_execution_task_name_accepts_initial_name_and_null_resume(self):
        initial = self.canonical_state()
        self.assertEqual(self.schema_errors(initial), [])
        self.assertEqual(state_domain.validate_current_state_format(initial), [])

        resumed = copy.deepcopy(initial)
        resumed["tasks"]["v8-state-task"]["executions"]["1"]["task_name"] = None
        self.assertEqual(self.schema_errors(resumed), [])
        self.assertEqual(state_domain.validate_current_state_format(resumed), [])

    def test_execution_task_name_invalid_values_are_rejected_by_runtime_and_schema(self):
        for name, task_name in self.invalid_task_names().items():
            with self.subTest(name=name):
                state = self.canonical_state()
                state["tasks"]["v8-state-task"]["executions"]["1"]["task_name"] = task_name
                self.assert_rejected_by_both(state)

    def test_full_producer_corpus_is_accepted_by_runtime_and_schema(self):
        state = self.canonical_state()
        task = state["tasks"]["v8-state-task"]
        execution = task["executions"]["1"]
        execution["pending_action"] = lifecycle._pending_action_record(
            target="/root/v8-state",
            attempt=2,
            task_ref="abcdefabcdef",
            operation_type="business_resume",
            created_at=101,
            resume_contract=self.contract(),
            resume_context_verification={"mode": "none"},
            prepared_on_attempt=1,
        )
        execution["last_lifecycle_operation"] = {
            "operation_type": "business_resume",
            "tool_use_id": "tool-v8",
            "call_observation": "unknown",
        }
        execution["initial_preparation_rollback"] = {
            "status": "rollback_incomplete",
            "task_ref": "0123456789ab",
            "observed_at": 102,
            "error": "initial rollback needs reconciliation",
        }
        state["agents"]["/root/v8-state"] = {"task_id": "v8-state-task", "attempt": 1}
        state["health"] = {
            "status": "degraded",
            "initial_preparation_rollback": copy.deepcopy(execution["initial_preparation_rollback"]),
        }
        state["groups"]["v8-group"] = {
            "group_id": "v8-group",
            "objective_summary": "verify canonical group producer",
            "members": [{"task_id": "v8-state-task", "required": True}],
        }
        state["tombstones"]["closed-task:1"] = {
            "task_ref": "abcdefabcdef",
            "dispatch_target": None,
            "close_reason": "close_task:corpus",
            "closed_at": 103,
        }
        self.assertEqual(self.schema_errors(state), [])
        self.assertEqual(state_domain.validate_current_state_format(state), [])

    def test_default_namespace_uses_state_v8_without_touching_old_namespaces(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory)
            old_files = []
            for name in ("state-v1", "state-v6", "state-v7"):
                old_root = plugin_root / name
                old_root.mkdir()
                old_file = old_root / "legacy.json"
                old_file.write_text('{"legacy": true}', encoding="utf-8")
                old_files.append((old_file, old_file.stat().st_mtime_ns))
            with mock.patch.dict(os.environ, {"SUBAGENT_GOVERNANCE_DATA": "", "PLUGIN_DATA": str(plugin_root)}):
                data_root = store_support.data_root_path(state_store_module.__file__)
                self.assertEqual(data_root, plugin_root / "state-v8")
                state_store_module.StateStore().read("namespace-v8")
            for old_file, before in old_files:
                self.assertEqual(old_file.read_text(encoding="utf-8"), '{"legacy": true}')
                self.assertEqual(old_file.stat().st_mtime_ns, before)

    def test_post_receipt_is_bounded_private_and_current_format_only(self):
        state = self.canonical_state()
        state["tasks"]["v8-state-task"]["executions"]["1"]["dispatch_record"]["dispatch_target"] = "/root/v8-state"
        state["tasks"]["v8-state-task"]["executions"]["1"]["post_receipt"] = {
            "session_id": "v8-state", "task_id": "v8-state-task", "attempt": 1,
            "task_ref": "0123456789ab", "target": "/root/v8-state",
            "expected_tool_use_id": "expected", "received_tool_use_id": "received",
            "id_match": True, "tool_family": "followup", "tool_name_classification": "unrecognized",
            "operation_type": "business_resume", "response_shape": "empty",
            "processing_result": "success", "target_observation": None,
            "transition_state": "transition_applied", "recorded_at": 101,
        }
        self.assertEqual(self.schema_errors(state), [])
        self.assertEqual(state_domain.validate_current_state_format(state), [])
        serialized = json.dumps(state, ensure_ascii=False)
        for forbidden in ("secret message", "response body", "contract/body", "transcript", "child final"):
            self.assertNotIn(forbidden, serialized)
        for field, value in (("message", "secret"), ("response_shape", "nested_content"), ("id_match", False), ("received_tool_use_id", "x" * 1025)):
            with self.subTest(field=field):
                invalid = copy.deepcopy(state)
                invalid["tasks"]["v8-state-task"]["executions"]["1"]["post_receipt"][field] = value
                self.assert_rejected_by_both(invalid)
        old = copy.deepcopy(state)
        for old_version in (6, 7):
            invalid = copy.deepcopy(state)
            invalid["state_format_version"] = old_version
            self.assert_rejected_by_both(invalid)

    def test_unfinished_receipt_requires_its_exact_claimed_pending(self):
        state = self.canonical_state()
        record = state["tasks"]["v8-state-task"]["executions"]["1"]
        record["dispatch_record"]["dispatch_target"] = "/root/v8-state"
        record["pending_action"] = {
            **lifecycle._pending_action_record(
                target="/root/v8-state", attempt=1, task_ref="0123456789ab",
                operation_type="business_resume", created_at=100,
                resume_contract=self.contract(),
                resume_context_verification={"mode": "none"}, prepared_on_attempt=1,
            ),
            "phase": "claimed", "tool_use_id": "claimed", "claimed_at": 101,
        }
        record["post_receipt"] = {
            "session_id": "v8-state", "task_id": "v8-state-task", "attempt": 1,
            "task_ref": "0123456789ab", "target": "/root/v8-state",
            "expected_tool_use_id": "claimed", "received_tool_use_id": "claimed",
            "id_match": True, "tool_family": "followup", "tool_name_classification": "recognized",
            "operation_type": "business_resume", "response_shape": "empty",
            "processing_result": "success", "target_observation": None,
            "transition_state": "receipt_recorded", "recorded_at": 102,
        }
        self.assertEqual(self.schema_errors(state), [])
        self.assertEqual(state_domain.validate_current_state_format(state), [])
        invalid = copy.deepcopy(state)
        invalid["tasks"]["v8-state-task"]["executions"]["1"]["pending_action"]["tool_use_id"] = "other"
        # JSON Schema keeps both records closed and bounded; the runtime adds
        # the dynamic same-ID cross-field invariant.
        self.assertEqual(self.schema_errors(invalid), [])
        self.assertTrue(state_domain.validate_current_state_format(invalid))
        with self.assertRaises(errors.StateValidationError):
            state_domain.require_current_state_format(invalid)

    def test_task_and_prepared_contracts_are_closed_and_share_semantics(self):
        contract = self.contract().to_record()
        contract["future"] = True
        self.assertTrue(
            validate_instance(
                contract,
                semantics.MACHINE_SEMANTICS["$defs"]["task_contract"],
                root_schema=semantics.MACHINE_SEMANTICS,
            )
        )
        with self.assertRaises(ValueError):
            contracts.contract_from_input(contract)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_store = state_store_module.StateStore(root / "sessions")
            prepared_store = prepared_store_module.PreparedContractStore(root / "prepared")
            prepared = protocol.prepare_dispatch(
                self.contract(), "prepared-v8", state_store=state_store,
                prepared_store=prepared_store, task_id_factory=lambda: "prepared-v8-task",
            )
            record = prepared_store.read("prepared-v8", prepared["task_ref"])
            self.assertEqual(
                validate_instance(
                    record,
                    semantics.MACHINE_SEMANTICS["$defs"]["prepared_contract"],
                    root_schema=semantics.MACHINE_SEMANTICS,
                ),
                [],
            )
            record["future"] = True
            with self.assertRaises(errors.PreparedContractValidationError):
                prepared_store_module.PreparedContractStore._validate_record(
                    record, "prepared-v8", prepared["task_ref"], root / "record.json"
                )

    def test_prepared_contract_and_native_parameters_reject_noncanonical_task_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_store = state_store_module.StateStore(root / "sessions")
            prepared_store = prepared_store_module.PreparedContractStore(root / "prepared")
            prepared = protocol.prepare_dispatch(
                self.contract(), "prepared-task-name", state_store=state_store,
                prepared_store=prepared_store, task_id_factory=lambda: "prepared-task-name-task",
            )
            record = prepared_store.read("prepared-task-name", prepared["task_ref"])
            definition = semantics.MACHINE_SEMANTICS["$defs"]["prepared_contract"]
            for location in ("task_name", "native_parameters.task_name"):
                for name, task_name in {"null": None, **self.invalid_task_names()}.items():
                    with self.subTest(location=location, name=name):
                        invalid = copy.deepcopy(record)
                        target = invalid if location == "task_name" else invalid["native_parameters"]
                        target["task_name"] = task_name
                        self.assertTrue(
                            validate_instance(
                                invalid, definition, root_schema=semantics.MACHINE_SEMANTICS,
                            )
                        )
                        with self.assertRaises(errors.PreparedContractValidationError):
                            prepared_store_module.PreparedContractStore._validate_record(
                                invalid, "prepared-task-name", prepared["task_ref"], root / "record.json"
                            )

    def test_mutations_are_rejected_by_runtime_and_schema(self):
        mutations = {
            "unknown_root": lambda value: value.update({"future_extension": True}),
            "managed_false": lambda value: value["tasks"]["v8-state-task"].update(
                {"managed": False}
            ),
            "missing_group_root": lambda value: value.pop("groups"),
            "unknown_execution": lambda value: value["tasks"]["v8-state-task"][
                "executions"
            ]["1"].update({"legacy": True}),
            "invalid_attempt_type": lambda value: value["tasks"]["v8-state-task"][
                "work_item"
            ].update({"current_attempt": "1"}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                state = copy.deepcopy(self.canonical_state())
                mutate(state)
                self.assert_rejected_by_both(state)


if __name__ == "__main__":
    unittest.main()
