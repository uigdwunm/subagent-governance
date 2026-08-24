#!/usr/bin/env python3
"""Characterization and transaction safety coverage for P5 dispatch work."""

from __future__ import annotations

import copy
import ast
import tempfile
import unittest
from pathlib import Path

from scripts import governance_dispatch as dispatch
from scripts import governance_errors as errors
from scripts import governance_execution as execution_module
from scripts import governance_prepared_store as prepared_store_module
from scripts import governance_protocol as protocol
from scripts import governance_state_store as state_store_module


def _contract() -> dict[str, object]:
    return {
        "semantic_name": "P5 retry safety",
        "requested_mode": "standard",
        "task_features": {
            "risk": "medium", "read_only": False, "writes_files": True,
            "destructive": False, "production": False, "concurrent_write": True,
        },
        "objective": "验证 retry 凭证事务", "background": "P5 regression coverage",
        "work_scope": ["tests"], "forbidden_scope": ["外部系统"],
        "completion_conditions": ["事务安全"], "evidence_requirements": ["unittest"],
        "relevant_files": [], "context_manifest": {"mode": "none"},
        "current_state": None, "model": None, "reasoning_effort": None,
        "context_strategy": "isolated", "context_turns": None, "context_reason": None,
    }


class P5DispatchTransactionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.state = state_store_module.StateStore(root / "sessions")
        self.prepared = prepared_store_module.PreparedContractStore(root / "prepared")
        self.session_id = "p5-session"
        self.initial = protocol.prepare_dispatch(
            _contract(), self.session_id, state_store=self.state,
            prepared_store=self.prepared, task_id_factory=lambda: "p5-task", now=10,
        )
        self._make_retry_eligible()

    def tearDown(self):
        self.directory.cleanup()

    def _make_retry_eligible(self):
        task_id = self.initial["task_id"]
        def reject(state):
            execution = state["tasks"][task_id]["executions"]["1"]
            execution_module.apply_canonical_execution_update(execution, "dispatch_response", "failed")
            execution["updated_at"] = 11
        self.state.update(self.session_id, reject)

    def test_retry_refuses_existing_credential_without_overwriting_it(self):
        task_ref = self.initial["task_ref"]
        original = self.prepared.read(self.session_id, task_ref)
        claimed = copy.deepcopy(original)
        claimed.update(consumed=True, tool_use_id="other-tool", claimed_at=12)
        self.prepared.compare_and_set(
            self.session_id, task_ref, lambda value: value == original,
            lambda value: (value.clear(), value.update(claimed)),
        )

        with self.assertRaises(errors.DispatchPreparationError):
            protocol.prepare_spawn_retry(
                _contract(), self.session_id, self.initial["task_id"],
                state_store=self.state, prepared_store=self.prepared, now=13,
            )
        self.assertEqual(self.prepared.read(self.session_id, task_ref), claimed)

    def test_retry_fault_cleanup_does_not_delete_concurrently_claimed_credential(self):
        task_ref = self.initial["task_ref"]
        self.prepared.delete(self.session_id, task_ref)
        original_update = self.state.update

        def fail_after_concurrent_claim(*args, **kwargs):
            current = self.prepared.read(self.session_id, task_ref)
            claimed = copy.deepcopy(current)
            claimed.update(consumed=True, tool_use_id="concurrent-tool", claimed_at=12)
            self.prepared.compare_and_set(
                self.session_id, task_ref, lambda value: value == current,
                lambda value: (value.clear(), value.update(claimed)),
            )
            raise errors.StateWriteError("injected state failure")

        self.state.update = fail_after_concurrent_claim
        try:
            with self.assertRaises(errors.DispatchPreparationError):
                protocol.prepare_spawn_retry(
                    _contract(), self.session_id, self.initial["task_id"],
                    state_store=self.state, prepared_store=self.prepared, now=13,
                )
        finally:
            self.state.update = original_update
        self.assertTrue(self.prepared.read(self.session_id, task_ref)["consumed"])
        self.assertEqual(self.prepared.read(self.session_id, task_ref)["tool_use_id"], "concurrent-tool")

    def test_execution_kernel_transition_table_and_import_boundary(self):
        record = self.state.read(self.session_id)["tasks"][self.initial["task_id"]]["executions"]["1"]
        execution_module.apply_canonical_execution_update(record, "dispatch_tool_use_id", "tool-1")
        execution_module.apply_canonical_execution_update(record, "dispatch_response", "success")
        execution_module.apply_canonical_execution_update(record, "dispatch_target", "/root/worker")
        execution_module.apply_canonical_execution_update(record, "observed_execution_status", "running")
        execution_module.apply_canonical_execution_update(record, "observation_observed_at", 20)
        execution_module.apply_canonical_execution_update(record, "observation_source", "list_agents")
        self.assertEqual(execution_module.execution_status(record), "running")
        self.assertEqual(execution_module.identity_status(record), "confirmed")
        with self.assertRaises(ValueError):
            execution_module.apply_canonical_execution_update(record, "dispatch_response", "maybe")
        imports = ast.parse(Path(execution_module.__file__).read_text()).body
        imported = "\n".join(ast.unparse(node) for node in imports if isinstance(node, (ast.Import, ast.ImportFrom)))
        for forbidden in ("governance_store", "governance_contract", "governance_context", "governance_dispatch", "subagent_governance"):
            self.assertNotIn(forbidden, imported)

    def test_dispatch_module_has_no_runtime_or_hook_dependency(self):
        source = Path(dispatch.__file__).read_text()
        self.assertNotIn("subagent_governance", source)
        self.assertNotIn("governance_cli", source)

    def test_p6_lifecycle_module_ownership_boundaries(self):
        root = Path(dispatch.__file__).parent
        lifecycle = ast.parse((root / "governance_lifecycle.py").read_text())
        communication = ast.parse((root / "governance_communication.py").read_text())
        runtime = ast.parse((root / "subagent_governance.py").read_text())

        def imported_modules(tree):
            return {
                alias.name
                for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in (node.names if isinstance(node, ast.Import) else [node])
                if isinstance(alias, ast.alias)
            } | {
                node.module or "" for node in tree.body if isinstance(node, ast.ImportFrom)
            }

        self.assertFalse(any("subagent_governance" in name for name in imported_modules(lifecycle)))
        self.assertFalse(any("subagent_governance" in name or "state_store" in name for name in imported_modules(communication)))
        lifecycle_functions = {node.name for node in lifecycle.body if isinstance(node, ast.FunctionDef)}
        self.assertNotIn("_deny", lifecycle_functions)
        self.assertNotIn("_allow_updated", lifecycle_functions)
        self.assertNotIn("_json_value", lifecycle_functions)
        migrated = {"record_terminal_notification", "apply_parent_disposition", "prepare_communication", "prepare_interrupt", "reconcile_pending_actions", "_claim_pending_action", "_create_resume_attempt"}
        runtime_functions = {node.name for node in runtime.body if isinstance(node, ast.FunctionDef)}
        self.assertFalse(migrated & runtime_functions)


if __name__ == "__main__":
    unittest.main()
