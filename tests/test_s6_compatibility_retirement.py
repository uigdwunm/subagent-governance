#!/usr/bin/env python3

import ast
import importlib.util
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_s6", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class CompatibilityRetirementTests(unittest.TestCase):
    @staticmethod
    def contract(objective: str) -> governance.TaskContract:
        return governance.TaskContract(
            semantic_name="s6_retirement",
            requested_mode="standard",
            resolved_mode="standard",
            resolution_reason="explicit_request",
            task_features=None,
            objective=objective,
            background="S6 local retirement test",
            work_scope=["读取 canonical work item"],
            forbidden_scope=["不写兼容投影"],
            completion_conditions=["只保留 canonical state"],
            evidence_requirements=["unit test"],
            relevant_files=[],
            current_state=None,
            model=None,
            reasoning_effort=None,
            context_strategy="isolated",
            context_turns=None,
            context_reason=None,
        )

    def test_runtime_does_not_export_legacy_projection_helpers(self):
        retired = {
            "_execution_projection",
            "_execution_compatibility_projection",
            "_project_state_compatibility",
            "_set_execution_fact",
            "_sync_legacy_task_projection",
            "_sync_execution_to_legacy_projection",
        }
        self.assertEqual(
            sorted(name for name in retired if hasattr(governance, name)),
            [],
        )

    def test_canonical_only_residuals_do_not_reappear(self):
        retry_preparation = inspect.getsource(governance.prepare_spawn_retry)
        diagnostic_session = ast.parse(
            inspect.getsource(governance._diagnostic_session_snapshot)
        )
        retired_locals = {"snapshots", "allowed_keys", "action_keys", "recent_keys"}
        assigned_names = {
            target.id
            for node in ast.walk(diagnostic_session)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Name)
        }
        checks = {
            "dead diagnostic attempt helper": not hasattr(
                governance, "_diagnostic_attempt_snapshot"
            ),
            "legacy retry adapter claim": "legacy records" not in retry_preparation,
            "dead diagnostic snapshot locals": not retired_locals & assigned_names,
        }
        for residual, retired in checks.items():
            with self.subTest(residual=residual):
                self.assertTrue(retired)

    def test_current_guidance_does_not_publish_internal_snapshot_helpers(self):
        current_guidance = (
            ROOT / "skills/subagent-governance/SKILL.md",
            ROOT / "skills/subagent-governance/references/runtime-boundaries.md",
        )
        internal_helpers = (
            "_action_required_records",
            "_recent_activity_records",
            "_canonical_work_item_view",
            "_build_work_item_decision_snapshot",
            "_diagnostic_attempt_snapshot",
        )
        for path in current_guidance:
            text = path.read_text(encoding="utf-8")
            for helper in internal_helpers:
                with self.subTest(path=path.name, helper=helper):
                    self.assertNotIn(helper, text)

    def test_new_managed_record_has_only_canonical_task_container_fields(self):
        contract = self.contract("验证 S6 canonical-only record")
        record = governance._initial_task_record(
            1,
            "0123456789ab",
            "sg_standard_s6_t_0123456789ab",
            contract,
            1234,
        )
        self.assertEqual(
            set(record),
            {"managed", "work_item", "executions"},
        )
        self.assertNotIn("task_id", record)
        self.assertNotIn("prior_attempts", json.dumps(record, sort_keys=True))

    def test_historical_attempt_first_record_is_not_lazily_migrated(self):
        historical = {
            "managed": True,
            "task_id": "historical-attempt-first",
            "attempt": 1,
            "task_ref": "0123456789ab",
            "execution_status": "running",
        }
        state = {
            "tasks": {"historical-attempt-first": historical},
            "agents": {},
            "groups": {},
            "health": {"status": "ok"},
            "tombstones": {},
        }
        with self.assertRaisesRegex(governance.StateConflictError, "canonical"):
            governance._ensure_canonical_task_record(
                state, "historical-attempt-first"
            )
        self.assertEqual(
            state["tasks"]["historical-attempt-first"], historical
        )
        self.assertEqual(
            governance._task_record_for_attempt(
                state, "historical-attempt-first", 1
            ),
            None,
        )
        self.assertEqual(governance._iter_task_attempts(state), [])

    def test_diagnose_omits_attempt_first_compatibility_arrays(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = governance.StateStore(root / "sessions")
            contract = self.contract("验证 S6 diagnostics")
            record = governance._initial_task_record(
                1,
                "abcdef012345",
                "sg_standard_s6_diag_t_abcdef012345",
                contract,
                1234,
            )

            def add(state):
                state["tasks"]["s6-diagnostic"] = record

            store.update("session-s6", add, admission="new_task")
            document, exit_code = governance._build_diagnostic_document(
                "session-s6",
                data_root=root,
            )
            self.assertEqual(exit_code, 0)
            session = document["sessions"][0]
            self.assertIn("work_items", session)
            self.assertNotIn("action_required", session)
            self.assertNotIn("recent_activity", session)

    def test_group_members_omit_retired_compatibility_aliases(self):
        contract = self.contract("验证 S6 group member")
        task = governance._initial_task_record(
            1,
            "fedcba987654",
            "sg_standard_s6_group_t_fedcba987654",
            contract,
            1234,
        )
        state = {
            "tasks": {"s6-group-member": task},
            "agents": {},
            "groups": {},
            "health": {"status": "ok"},
            "tombstones": {},
        }
        group, _issues, _incomplete = governance._derive_group_snapshot(
            state,
            {
                "group_id": "s6-group",
                "objective_summary": "验证 canonical group",
                "members": [{"task_id": "s6-group-member", "required": True}],
            },
            session_id="session-s6",
        )
        member = group["members"][0]
        self.assertNotIn("individual_action_required", member)
        self.assertNotIn("disposition_complete", member)
        self.assertNotIn("summary_material_ready", member)


if __name__ == "__main__":
    unittest.main()
