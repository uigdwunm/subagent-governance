import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "subagent_governance.py"


def load_governance():
    spec = importlib.util.spec_from_file_location("subagent_governance_three_plane", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ThreePlaneStateModelTests(unittest.TestCase):
    def setUp(self):
        self.governance = load_governance()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = self.governance.StateStore(Path(self.temp.name) / "sessions")

    def contract(self):
        return self.governance.TaskContract(
            semantic_name="three_plane",
            requested_mode="standard",
            resolved_mode="standard",
            resolution_reason="explicit_request",
            task_features={"risk": "medium"},
            objective="验证三平面状态模型",
            background="v5 state model test",
            work_scope=["state"],
            forbidden_scope=["result persistence"],
            completion_conditions=["planes validate"],
            evidence_requirements=["unit test"],
            relevant_files=[],
            current_state=None,
            model=None,
            reasoning_effort=None,
            context_strategy="isolated",
            context_turns=None,
            context_reason="self-contained",
        )

    def initial_state(self, session_id="three-plane"):
        task_id = "three-plane-task"
        task_name = "sg_standard_three_plane_t_0123456789ab"
        state = self.governance.StateStore._empty_state(session_id)
        state["tasks"][task_id] = self.governance._initial_task_record(
            1,
            "0123456789ab",
            task_name,
            self.contract(),
            100,
        )
        return state, task_id

    def test_schema_and_runtime_define_same_three_planes(self):
        definitions = self.governance.SEMANTIC_DEFINITIONS
        expected = {
            "dispatch_record": self.governance.REQUIRED_DISPATCH_RECORD_FIELDS,
            "observation_record": self.governance.REQUIRED_OBSERVATION_RECORD_FIELDS,
            "closure_record": self.governance.REQUIRED_CLOSURE_RECORD_FIELDS,
        }
        for name, runtime_fields in expected.items():
            with self.subTest(name=name):
                active_properties = {
                    field
                    for field, definition in definitions[name]["properties"].items()
                    if definition is not False
                }
                self.assertEqual(active_properties, set(runtime_fields))
        self.assertEqual(
            self.governance.SEMANTIC_RULES["canonical_record"]["execution_plane_fields"],
            list(expected),
        )

    def test_initial_execution_contains_no_result_plane_or_result_fields(self):
        state, task_id = self.initial_state()
        execution = state["tasks"][task_id]["executions"]["1"]
        self.assertEqual(
            [name for name in execution if name.endswith("_record")],
            ["dispatch_record", "observation_record", "closure_record"],
        )
        for field in (
            "result_record",
            "business_result",
            "acceptance_status",
            "result_reference",
            "result_sha256",
            "correction_count",
        ):
            self.assertNotIn(field, execution)

    def test_v4_exact_parent_recorded_result_is_reduced_to_notification(self):
        state, task_id = self.initial_state()
        execution = state["tasks"][task_id]["executions"]["1"]
        target = "/root/three_plane"
        execution["dispatch_record"]["dispatch_target"] = target
        execution["result_record"] = {
            "task_id": task_id,
            "attempt": 1,
            "sender_target": target,
            "submission_provenance": "parent_recorded_native_sender",
            "result_state": "valid",
            "submitted_at": 150,
        }
        state["state_format_version"] = 4

        migrated = self.governance._migrate_state_to_current(state)
        current = migrated["tasks"][task_id]["executions"]["1"]

        self.assertEqual(migrated["state_format_version"], 5)
        self.assertNotIn("result_record", current)
        self.assertEqual(current["observation_record"]["source"], "terminal_notification")
        self.assertNotIn("closure_state", current["closure_record"])
        self.assertEqual(self.governance._execution_status(current), "stopped")
        self.assertEqual(self.governance._parent_action(current), "decide_disposition")

    def test_migration_removes_closure_state_and_preserves_complete_close_facts(self):
        state, task_id = self.initial_state()
        execution = state["tasks"][task_id]["executions"]["1"]
        execution["closure_record"].update(
            closure_state="closed",
            reason="legacy close",
            closed_at=150,
        )

        current = self.governance._migrate_state_to_current(state)["tasks"][task_id][
            "executions"
        ]["1"]

        self.assertNotIn("closure_state", current["closure_record"])
        self.assertTrue(self.governance._execution_is_closed(current))

    def test_migration_retains_only_final_recovery_authorization(self):
        cases = (
            ("normal_message", 0, True, False),
            ("platform_recovery", 0, False, False),
            ("platform_recovery", 0, True, False),
            ("platform_recovery", 1, True, True),
        )
        for operation_type, recovery_count, authorized, retained in cases:
            with self.subTest(
                operation_type=operation_type,
                recovery_count=recovery_count,
                authorized=authorized,
            ):
                state, task_id = self.initial_state()
                execution = state["tasks"][task_id]["executions"]["1"]
                execution["recovery_count"] = recovery_count
                execution["pending_action"] = {
                    "target": "/root/three_plane",
                    "attempt": 1,
                    "task_ref": "0123456789ab",
                    "operation_type": operation_type,
                    "phase": "prepared",
                    "created_at": 101,
                    "tool_use_id": None,
                    "claimed_at": None,
                    "authorized_recovery": authorized,
                }

                current = self.governance._migrate_state_to_current(state)["tasks"][
                    task_id
                ]["executions"]["1"]["pending_action"]

                self.assertEqual("authorized_recovery" in current, retained)

    def test_migration_downgrades_closed_state_without_complete_facts(self):
        state, task_id = self.initial_state()
        execution = state["tasks"][task_id]["executions"]["1"]
        execution["closure_record"].update(
            closure_state="closed",
            reason="legacy close",
        )

        current = self.governance._migrate_state_to_current(state)["tasks"][task_id][
            "executions"
        ]["1"]
        closure = current["closure_record"]

        self.assertNotIn("closure_state", closure)
        self.assertIsNone(closure["reason"])
        self.assertIsNone(closure["closed_at"])
        self.assertEqual(closure["parent_action"], "reconcile")
        self.assertFalse(self.governance._execution_is_closed(current))

    def test_v4_unbound_result_is_removed_without_inventing_notification(self):
        state, task_id = self.initial_state()
        execution = state["tasks"][task_id]["executions"]["1"]
        execution["result_record"] = {
            "task_id": task_id,
            "attempt": 1,
            "sender_target": "/root/wrong",
            "submission_provenance": "child_claimed",
            "result_state": "valid",
            "submitted_at": 150,
        }
        state["state_format_version"] = 4

        current = self.governance._migrate_state_to_current(state)["tasks"][task_id][
            "executions"
        ]["1"]

        self.assertNotIn("result_record", current)
        self.assertIsNone(current["observation_record"]["source"])

    def test_migration_does_not_promote_legacy_unbound_matching_subject(self):
        state, task_id = self.initial_state()
        execution = state["tasks"][task_id]["executions"]["1"]
        target = "/root/legacy-unbound"
        execution["dispatch_record"]["dispatch_target"] = target
        execution["observation_record"].update(
            subject=target,
            binding_basis="none",
            source="list_agents",
            observed_state="active",
            observed_at=120,
        )

        current = self.governance._migrate_state_to_current(state)["tasks"][task_id][
            "executions"
        ]["1"]

        self.assertNotIn("subject", current["observation_record"])
        self.assertEqual(current["observation_record"]["observed_state"], "not_observed")
        self.assertIsNone(current["observation_record"]["source"])
        self.assertIsNone(current["observation_record"]["observed_at"])
        self.assertEqual(self.governance._identity_status(current), "unconfirmed")

    def test_migration_preserves_legacy_exact_observation_without_subject_copy(self):
        state, task_id = self.initial_state()
        execution = state["tasks"][task_id]["executions"]["1"]
        target = "/root/legacy-exact"
        execution["dispatch_record"]["dispatch_target"] = target
        execution["observation_record"].update(
            subject=target,
            binding_basis="exact_dispatch_target",
            source="list_agents",
            observed_state="active",
            observed_at=120,
        )

        current = self.governance._migrate_state_to_current(state)["tasks"][task_id][
            "executions"
        ]["1"]

        self.assertNotIn("subject", current["observation_record"])
        self.assertEqual(current["observation_record"]["observed_state"], "active")
        self.assertEqual(self.governance._identity_status(current), "confirmed")

    def test_migration_downgrades_retired_observation_source(self):
        state, task_id = self.initial_state()
        execution = state["tasks"][task_id]["executions"]["1"]
        execution["dispatch_record"]["dispatch_target"] = "/root/retired-source"
        execution["observation_record"].update(
            source="wait",
            observed_state="active",
            observed_at=120,
        )

        current = self.governance._migrate_state_to_current(state)["tasks"][task_id][
            "executions"
        ]["1"]

        self.assertEqual(
            current["observation_record"],
            {
                "source": None,
                "observed_state": "not_observed",
                "observed_at": None,
                "terminal_status": None,
            },
        )
        self.assertEqual(self.governance._parent_action(current), "reconcile")

    def test_legacy_migration_drops_mismatched_platform_target_observation(self):
        observation = self.governance._legacy_observation_record(
            {
                "platform_checked_at": 120,
                "platform_observation_source": "list_agents",
                "platform_observation": "unknown",
                "platform_observation_target": "/root/wrong-target",
            },
            {"dispatch_target": "/root/right-target"},
        )

        self.assertEqual(
            observation,
            {
                "source": None,
                "observed_state": "not_observed",
                "observed_at": None,
                "terminal_status": None,
            },
        )

    def test_locked_write_persists_v5_and_removes_legacy_result_fields(self):
        state, task_id = self.initial_state("locked-migration")
        execution = state["tasks"][task_id]["executions"]["1"]
        execution.update(
            business_result="failed",
            acceptance_status=None,
            result_protocol_status="valid",
            result_storage_status="available",
            result_conflict=False,
            correction_count=1,
        )
        execution["dispatch_record"]["response_digest"] = "b" * 64
        execution["dispatch_record"]["response_observed_at"] = 120
        execution["dispatch_record"]["claimed_at"] = 121
        execution["observation_record"]["fresh_until"] = 999
        execution["observation_record"]["observation_id"] = "legacy-observation"
        execution["observation_record"]["subject_kind"] = "dispatch_target"
        execution["observation_record"]["bound_task_id"] = task_id
        execution["observation_record"]["bound_attempt"] = 1
        execution["observation_record"]["runtime_alias"] = "legacy-agent"
        execution["observation_record"]["binding_basis"] = "exact_dispatch_target"
        execution["spawn_task_name"] = None
        execution["origin_attempt"] = 1
        execution["origin_task_name"] = "legacy-task-name"
        execution["dispatch_kind"] = "initial_spawn"
        execution["transition"] = None
        execution["activity_at"] = 130
        state["state_format_version"] = 4
        path, _lock_path = self.store._paths("locked-migration")
        path.write_text(json.dumps(state), encoding="utf-8")
        path.chmod(0o600)

        self.store.update("locked-migration", lambda value: value.update(updated_at=200))
        persisted = json.loads(path.read_text(encoding="utf-8"))
        current = persisted["tasks"][task_id]["executions"]["1"]
        self.assertNotIn("updated_at", persisted)
        self.assertNotIn("response_digest", current["dispatch_record"])
        self.assertNotIn("response_observed_at", current["dispatch_record"])
        self.assertNotIn("claimed_at", current["dispatch_record"])
        self.assertNotIn("fresh_until", current["observation_record"])
        self.assertNotIn("observation_id", current["observation_record"])
        self.assertNotIn("subject_kind", current["observation_record"])
        self.assertNotIn("subject", current["observation_record"])
        self.assertNotIn("bound_task_id", current["observation_record"])
        self.assertNotIn("bound_attempt", current["observation_record"])
        self.assertNotIn("runtime_alias", current["observation_record"])
        self.assertNotIn("binding_basis", current["observation_record"])
        self.assertNotIn("spawn_task_name", current)
        self.assertNotIn("origin_attempt", current)
        self.assertNotIn("origin_task_name", current)
        self.assertNotIn("dispatch_kind", current)
        self.assertNotIn("transition", current)
        self.assertNotIn("activity_at", current)

        self.assertEqual(persisted["state_format_version"], 5)
        for field in (
            "business_result",
            "acceptance_status",
            "result_protocol_status",
            "result_storage_status",
            "result_conflict",
            "correction_count",
        ):
            self.assertNotIn(field, current)

    def test_current_state_migration_removes_retired_growth_and_deliverable_fields(self):
        state, task_id = self.initial_state()
        task = state["tasks"][task_id]
        task["task_id"] = task_id
        task["work_item"]["last_growth_authorization"] = {
            "attempt": 1,
            "action": "resume_business",
            "reason": "旧增长授权",
            "recorded_at": 120,
        }
        task["work_item"]["repeated_business_attempts"] = True
        task["work_item"]["objective_summary"] = "旧 work item 目标"
        task["work_item"]["created_at"] = 50
        task["work_item"]["updated_at"] = 140
        task["work_item"]["attempt_count"] = 99
        task["work_item"]["action_required"] = True
        task["work_item"]["last_parent_disposition"] = {
            "task_id": task_id,
            "attempt": 1,
            "action": "close_task",
            "reason": "旧关闭审计",
            "recorded_at": 120,
        }
        execution = task["executions"]["1"]
        execution["task_id"] = "conflicting-legacy-task"
        execution["attempt"] = 99
        execution["dispatch_record"]["task_id"] = task_id
        execution["dispatch_record"]["attempt"] = 1
        execution["dispatch_record"]["task_ref"] = execution["task_ref"]
        execution["contract_summary"] = {
            "completion_conditions": ["legacy completion condition"]
        }
        execution["closure_record"]["parent_disposition"] = "close"
        execution["closure_record"]["disposition_recorded_at"] = 120
        execution["closure_record"]["task_id"] = task_id
        execution["closure_record"]["attempt"] = 1
        execution["growth_authorization"] = {
            "attempt": 1,
            "action": "resume_business",
            "reason": "旧增长授权",
            "recorded_at": 120,
        }
        execution["pending_action"] = {
            "growth_authorization": copy.deepcopy(execution["growth_authorization"]),
            "disposition": copy.deepcopy(execution["growth_authorization"]),
        }
        execution["deliverable_contract"] = {"outcome_required": True}
        execution["pending_action"]["deliverable_contract"] = {"outcome_required": True}
        execution["pending_action"]["deliverable_contract_digest"] = "a" * 64
        execution["pending_action"]["resume_contract_summary"] = {"objective": "legacy"}
        execution["pending_action"]["resume_contract_digest"] = "b" * 64
        execution["pending_action"]["resume_task_ref"] = "0123456789ab"
        execution["pending_action"]["start_observed_at"] = 119
        execution["pending_action"]["task_id"] = task_id
        execution["pending_action"]["reason"] = "legacy pending reason"
        execution["pending_action"]["expires_at"] = 999
        execution["semantic_name"] = "three_plane"
        execution["requested_mode"] = "standard"
        execution["resolution_reason"] = "explicit_request"
        execution["created_at"] = 50
        execution["recovery_status"] = "awaiting_authorization"
        execution["terminal_reconciliation_reason"] = "legacy terminal audit"
        execution["terminal_reconciled_at"] = 119
        execution["reconciliation_reason"] = "legacy interrupted audit"
        execution["reconciled_thread_id"] = "019ff4ef-aac5-77c1-81ef-682411ff1a3f"
        execution["reconciled_thread_status"] = "interrupted"
        execution["spawn_close_reason"] = "spawn_retry_exhausted"
        execution["last_lifecycle_operation"] = {
            "target": "/root/legacy",
            "claimed_at": 121,
            "completed_at": 122,
            "reason": "legacy lifecycle reason",
            "native_status": "accepted",
        }
        state["tombstones"][f"{task_id}:1"] = {
            "task_id": task_id,
            "attempt": 1,
            "task_ref": execution["task_ref"],
            "agent_id": "legacy-agent",
            "canonical_task_path": "/root/legacy",
            "last_execution_status": "stopped",
            "close_reason": "legacy close",
            "closed_at": 120,
        }

        migrated = self.governance._migrate_state_to_current(state)
        current_task = migrated["tasks"][task_id]
        current_execution = current_task["executions"]["1"]
        current_tombstone = migrated["tombstones"][f"{task_id}:1"]

        self.assertNotIn("last_growth_authorization", current_task["work_item"])
        self.assertNotIn("task_id", current_task)
        self.assertNotIn("repeated_business_attempts", current_task["work_item"])
        self.assertNotIn("objective_summary", current_task["work_item"])
        self.assertNotIn("created_at", current_task["work_item"])
        self.assertNotIn("updated_at", current_task["work_item"])
        self.assertNotIn("attempt_count", current_task["work_item"])
        self.assertNotIn("action_required", current_task["work_item"])
        self.assertNotIn("last_parent_disposition", current_task["work_item"])
        self.assertNotIn("task_id", current_execution["dispatch_record"])
        self.assertNotIn("attempt", current_execution["dispatch_record"])
        self.assertNotIn("task_ref", current_execution["dispatch_record"])
        self.assertNotIn("growth_authorization", current_execution)
        self.assertNotIn("parent_disposition", current_execution["closure_record"])
        self.assertNotIn("disposition_recorded_at", current_execution["closure_record"])
        self.assertNotIn("task_id", current_execution["closure_record"])
        self.assertNotIn("attempt", current_execution["closure_record"])
        self.assertNotIn("growth_authorization", current_execution["pending_action"])
        self.assertNotIn("disposition", current_execution["pending_action"])
        self.assertNotIn("deliverable_contract", current_execution)
        self.assertNotIn("deliverable_contract", current_execution["pending_action"])
        self.assertNotIn("deliverable_contract_digest", current_execution["pending_action"])
        self.assertNotIn("resume_contract_summary", current_execution["pending_action"])
        self.assertNotIn("resume_contract_digest", current_execution["pending_action"])
        self.assertNotIn("resume_task_ref", current_execution["pending_action"])
        self.assertNotIn("start_observed_at", current_execution["pending_action"])
        self.assertNotIn("task_id", current_execution["pending_action"])
        self.assertNotIn("reason", current_execution["pending_action"])
        self.assertNotIn("expires_at", current_execution["pending_action"])
        self.assertNotIn("semantic_name", current_execution)
        self.assertNotIn("requested_mode", current_execution)
        self.assertNotIn("resolution_reason", current_execution)
        self.assertNotIn("created_at", current_execution)
        self.assertNotIn("recovery_status", current_execution)
        self.assertNotIn("terminal_reconciliation_reason", current_execution)
        self.assertNotIn("terminal_reconciled_at", current_execution)
        self.assertNotIn("reconciliation_reason", current_execution)
        self.assertNotIn("reconciled_thread_id", current_execution)
        self.assertNotIn("reconciled_thread_status", current_execution)
        self.assertNotIn("spawn_close_reason", current_execution)
        self.assertNotIn("managed", current_execution)
        self.assertNotIn("task_id", current_execution)
        self.assertNotIn("attempt", current_execution)
        self.assertEqual(
            set(current_execution["contract_summary"]),
            {"objective", "model"},
        )
        self.assertNotIn(
            "completion_conditions", current_execution["contract_summary"]
        )
        self.assertEqual(
            current_execution["contract_summary"]["objective"], "旧 work item 目标"
        )
        self.assertNotIn("claimed_at", current_execution["last_lifecycle_operation"])
        self.assertNotIn("completed_at", current_execution["last_lifecycle_operation"])
        self.assertNotIn("target", current_execution["last_lifecycle_operation"])
        self.assertNotIn("reason", current_execution["last_lifecycle_operation"])
        self.assertNotIn("native_status", current_execution["last_lifecycle_operation"])
        self.assertEqual(current_tombstone["dispatch_target"], "/root/legacy")
        self.assertNotIn("agent_id", current_tombstone)
        self.assertNotIn("canonical_task_path", current_tombstone)
        self.assertNotIn("last_execution_status", current_tombstone)
        self.assertNotIn("task_id", current_tombstone)
        self.assertNotIn("attempt", current_tombstone)

    def test_migration_removes_premature_spawn_retry_exhausted_tombstone(self):
        state, task_id = self.initial_state()
        execution = state["tasks"][task_id]["executions"]["1"]
        execution["spawn_retry_count"] = self.governance.RETRY_LIMITS["spawn"]
        execution["spawn_close_reason"] = "spawn_retry_exhausted"
        self.governance._apply_canonical_execution_update(
            execution, "dispatch_response", "failed"
        )
        self.governance._apply_canonical_execution_update(
            execution, "observed_execution_status", "stopped"
        )
        self.governance._apply_canonical_execution_update(
            execution, "closure_parent_action", "decide_disposition"
        )
        state["tombstones"][f"{task_id}:1"] = {
            "task_ref": execution["task_ref"],
            "close_reason": "spawn_retry_exhausted",
            "closed_at": 130,
        }
        state["tombstones"]["orphan:1"] = {
            "task_ref": "abcdef012345",
            "close_reason": "spawn_retry_exhausted",
            "closed_at": 130,
        }

        migrated = self.governance._migrate_state_to_current(state)
        current = migrated["tasks"][task_id]["executions"]["1"]

        self.assertNotIn("spawn_close_reason", current)
        self.assertNotIn(f"{task_id}:1", migrated["tombstones"])
        self.assertIn("orphan:1", migrated["tombstones"])
        self.assertFalse(self.governance._execution_is_closed(current))
        self.assertEqual(
            self.governance._parent_action(current), "decide_disposition"
        )

    def test_current_state_rejects_noncanonical_execution_key(self):
        state, task_id = self.initial_state()
        execution = state["tasks"][task_id]["executions"].pop("1")
        state["tasks"][task_id]["executions"]["01"] = execution

        with self.assertRaisesRegex(
            self.governance.StateValidationError, "非法 execution 键"
        ):
            self.governance._migrate_state_to_current(state)

    def test_state_store_read_and_update_expose_only_canonical_execution(self):
        state, task_id = self.initial_state("canonical-runtime")
        self.store.update("canonical-runtime", lambda current: current.update(state))

        read_execution = self.store.read("canonical-runtime")["tasks"][task_id][
            "executions"
        ]["1"]
        self.assertEqual(
            set(read_execution), set(self.governance.REQUIRED_EXECUTION_FIELDS)
        )

        callback_fields = self.store.update(
            "canonical-runtime",
            lambda current: set(
                current["tasks"][task_id]["executions"]["1"]
            ),
        )
        self.assertEqual(
            callback_fields, set(self.governance.REQUIRED_EXECUTION_FIELDS)
        )

    def test_canonical_update_rejects_legacy_execution_field_name(self):
        state, task_id = self.initial_state()
        execution = state["tasks"][task_id]["executions"]["1"]
        before = copy.deepcopy(execution)

        with self.assertRaisesRegex(ValueError, "unknown canonical execution update"):
            self.governance._apply_canonical_execution_update(
                execution, "execution_status", "running"
            )

        self.assertEqual(execution, before)

    def test_canonical_update_rejects_invalid_values_without_mutation(self):
        invalid_updates = (
            ("dispatch_response", []),
            ("dispatch_tool_use_id", ""),
            ("dispatch_target", ""),
            ("observed_execution_status", []),
            ("observed_platform_state", []),
            ("observation_observed_at", -1),
            ("observation_source", []),
            ("observation_subject", ""),
            ("observation_summary", []),
            ("closure_parent_action", []),
            ("closure_parent_action", "manual_review"),
            ("closure_parent_action", "business_resume"),
            ("closure_closed", True),
            ("closure_reason", ""),
            ("closure_closed_at", -1),
            ("closure_parent_disposition_record", None),
        )

        for operation, value in invalid_updates:
            with self.subTest(operation=operation, value=value):
                state, task_id = self.initial_state()
                execution = state["tasks"][task_id]["executions"]["1"]
                before = copy.deepcopy(execution)

                with self.assertRaisesRegex(ValueError, operation):
                    self.governance._apply_canonical_execution_update(
                        execution, operation, value
                    )

                self.assertEqual(execution, before)

    def test_canonical_update_rejects_unsatisfied_observation_preconditions(self):
        for operation, value in (
            ("observation_summary", "completed"),
        ):
            with self.subTest(operation=operation):
                state, task_id = self.initial_state()
                execution = state["tasks"][task_id]["executions"]["1"]
                before = copy.deepcopy(execution)

                with self.assertRaisesRegex(ValueError, operation):
                    self.governance._apply_canonical_execution_update(
                        execution, operation, value
                    )

                self.assertEqual(execution, before)


if __name__ == "__main__":
    unittest.main()
