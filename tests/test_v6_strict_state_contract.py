import copy
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


class V6StrictStateContractTests(unittest.TestCase):
    @staticmethod
    def contract():
        return contracts.TaskContract(
            semantic_name="v6_state",
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
            objective="verify v6 strict state contract",
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
        state = state_store_module.StateStore._empty_state("v6-state")
        state["tasks"]["v6-state-task"] = dispatch.initial_task_record(
            1,
            "0123456789ab",
            "sg_standard_v6_state_t_0123456789ab",
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

    def test_v6_corpus_is_accepted_by_runtime_and_schema(self):
        state = self.canonical_state()
        self.assertEqual(semantics.STATE_FORMAT_VERSION, 6)
        self.assertEqual(self.schema_errors(state), [])
        self.assertEqual(state_domain.validate_current_state_format(state), [])
        self.assertIs(state_domain.require_current_state_format(state), state)

    def test_full_producer_corpus_is_accepted_by_runtime_and_schema(self):
        state = self.canonical_state()
        task = state["tasks"]["v6-state-task"]
        execution = task["executions"]["1"]
        execution["pending_action"] = lifecycle._pending_action_record(
            target="/root/v6-state",
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
            "tool_use_id": "tool-v6",
            "call_observation": "unknown",
        }
        execution["initial_preparation_rollback"] = {
            "status": "rollback_incomplete",
            "task_ref": "0123456789ab",
            "observed_at": 102,
            "error": "initial rollback needs reconciliation",
        }
        state["agents"]["/root/v6-state"] = {"task_id": "v6-state-task", "attempt": 1}
        state["health"] = {
            "status": "degraded",
            "initial_preparation_rollback": copy.deepcopy(execution["initial_preparation_rollback"]),
        }
        state["groups"]["v6-group"] = {
            "group_id": "v6-group",
            "objective_summary": "verify canonical group producer",
            "members": [{"task_id": "v6-state-task", "required": True}],
        }
        state["tombstones"]["closed-task:1"] = {
            "task_ref": "abcdefabcdef",
            "dispatch_target": None,
            "close_reason": "close_task:corpus",
            "closed_at": 103,
        }
        self.assertEqual(self.schema_errors(state), [])
        self.assertEqual(state_domain.validate_current_state_format(state), [])

    def test_default_namespace_uses_state_v6_without_touching_state_v1(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory)
            old_root = plugin_root / "state-v1"
            old_root.mkdir()
            old_file = old_root / "legacy.json"
            old_file.write_text('{"legacy": true}', encoding="utf-8")
            before = old_file.stat().st_mtime_ns
            with mock.patch.dict(os.environ, {"SUBAGENT_GOVERNANCE_DATA": "", "PLUGIN_DATA": str(plugin_root)}):
                data_root = store_support.data_root_path(state_store_module.__file__)
                self.assertEqual(data_root, plugin_root / "state-v6")
                state_store_module.StateStore().read("namespace-v6")
            self.assertEqual(old_file.read_text(encoding="utf-8"), '{"legacy": true}')
            self.assertEqual(old_file.stat().st_mtime_ns, before)

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
                self.contract(), "prepared-v6", state_store=state_store,
                prepared_store=prepared_store, task_id_factory=lambda: "prepared-v6-task",
            )
            record = prepared_store.read("prepared-v6", prepared["task_ref"])
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
                    record, "prepared-v6", prepared["task_ref"], root / "record.json"
                )

    def test_mutations_are_rejected_by_runtime_and_schema(self):
        mutations = {
            "unknown_root": lambda value: value.update({"future_extension": True}),
            "managed_false": lambda value: value["tasks"]["v6-state-task"].update(
                {"managed": False}
            ),
            "missing_group_root": lambda value: value.pop("groups"),
            "unknown_execution": lambda value: value["tasks"]["v6-state-task"][
                "executions"
            ]["1"].update({"legacy": True}),
            "invalid_attempt_type": lambda value: value["tasks"]["v6-state-task"][
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
