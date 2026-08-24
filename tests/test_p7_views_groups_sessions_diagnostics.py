#!/usr/bin/env python3
"""P7 regression matrix for shared work-item projections and read-only edges."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import load_governance

from scripts import governance_contracts as contracts
from scripts import governance_diagnostics as diagnostics
from scripts import governance_dispatch as dispatch
from scripts import governance_errors as errors
from scripts import governance_execution as execution_module
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


class P7ViewsGroupsSessionsDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = state_store_module.StateStore(self.root / "sessions")
        self.session_id = "p7-session"

    def add_task(self, task_id="task-a"):
        contract = contracts.TaskContract(
            semantic_name="p7", requested_mode="standard", resolved_mode="standard",
            resolution_reason="explicit_request", task_features={"risk": "medium", "read_only": False, "writes_files": True, "destructive": False, "production": False, "concurrent_write": False},
            objective="P7 projection", background="test", work_scope=["test"], forbidden_scope=["none"], completion_conditions=["ok"], evidence_requirements=[], relevant_files=[], context_manifest={"mode": "none"}, current_state=None, model=None, reasoning_effort=None, context_strategy="isolated", context_turns=None, context_reason=None,
        )
        record = dispatch.initial_task_record(1, "0123456789ab", "sg_standard_p7_t_0123456789ab", contract, 100)
        execution = record["executions"]["1"]
        execution["dispatch_record"].update(dispatch_state="acknowledged", dispatch_target="/root/p7", tool_use_id="spawn")
        execution_module.apply_canonical_execution_update(execution, "observed_execution_status", "running")
        execution_module.apply_canonical_execution_update(execution, "closure_parent_action", "wait")
        self.store.update(self.session_id, lambda state: (state["tasks"].update({task_id: record}), state["agents"].update({"/root/p7": {"task_id": task_id, "attempt": 1}})))
        return task_id

    def test_group_is_strict_and_trims_canonical_identifiers(self):
        task_id = self.add_task("trimmed")
        result = groups.upsert_group({"group_id": " group ", "objective_summary": " objective ", "members": [{"task_id": f" {task_id} ", "required": True}]}, self.session_id, state_store=self.store)
        self.assertEqual(result, {"status": "created", "group_id": "group"})
        self.assertIn("group", self.store.read(self.session_id)["groups"])
        with self.assertRaises(groups.GroupValidationError):
            groups.upsert_group({"group_id": "x", "objective_summary": "x", "members": [], "extra": True}, self.session_id, state_store=self.store)
        class MissingGroupsStore:
            def update(self, _session_id, callback, **_kwargs):
                return callback({"tasks": {task_id: {}}, "agents": {}})
        with self.assertRaises(groups.GroupValidationError):
            groups.upsert_group({"group_id": "missing-root", "objective_summary": "x", "members": []}, self.session_id, state_store=MissingGroupsStore())

    def test_session_end_keeps_degraded_health_even_when_work_item_tombstoned(self):
        task_id = self.add_task()
        state = self.store.read(self.session_id); execution = state["tasks"][task_id]["executions"]["1"]
        execution_module.close_attempt_record(state, task_id, 1, execution, "parent_closed", 120)
        state["tasks"][task_id]["work_item"]["lifecycle"] = "tombstoned"; state["tombstones"].clear(); state["health"]["status"] = "degraded"
        self.store.update(self.session_id, lambda current: current.update(state))
        path, _ = self.store._paths(self.session_id)
        hook.handle_hook({"session_id": self.session_id, "hook_event_name": "SessionEnd"}, self.store)
        self.assertTrue(path.exists())

    def test_session_start_keeps_readable_summary_after_one_maintenance_failure(self):
        self.add_task()
        with mock.patch.object(self.store, "cleanup_expired_tombstones", side_effect=RuntimeError("cleanup failed")):
            result = hook.handle_hook({"session_id": self.session_id, "hook_event_name": "SessionStart"}, self.store)
        text = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("工作项 ID：task-a", text)
        self.assertIn("维护告警", text)

    def test_diagnostics_v5_is_unsupported_and_zero_write(self):
        self.add_task()
        path, lock = self.store._paths(self.session_id)
        state = self.store.read(self.session_id); state["state_format_version"] = 5
        path.write_text(json.dumps(state), encoding="utf-8"); path.chmod(0o600)
        before = {item: (hashlib.sha256(item.read_bytes()).hexdigest(), item.stat().st_mtime_ns) for item in (path, lock)}
        document, exit_code = diagnostics.build_diagnostic_document(self.session_id, self.root)
        self.assertEqual(exit_code, 1); self.assertIn("unsupported_format", {item["code"] for item in document["issues"]})
        after = {item: (hashlib.sha256(item.read_bytes()).hexdigest(), item.stat().st_mtime_ns) for item in (path, lock)}
        self.assertEqual(before[path], after[path])
        self.assertEqual(before[lock], after[lock])

    def test_diagnostics_modules_are_read_only_and_runtime_is_only_adapter(self):
        root = Path(dispatch.__file__).parent
        diagnostics = (root / "governance_diagnostics.py").read_text()
        self.assertNotIn("governance_state_store", diagnostics)
        self.assertNotIn("cleanup_expired", diagnostics)
        for filename in ("governance_views.py", "governance_groups.py", "governance_sessions.py", "governance_diagnostics.py"):
            self.assertNotIn("subagent_governance", (root / filename).read_text())
        runtime = ast.parse((root / "subagent_governance.py").read_text())
        names = {node.name for node in runtime.body if isinstance(node, ast.FunctionDef)}
        self.assertFalse({"_attempt_projection", "_view_attempt_records", "_canonical_work_item_view", "_build_work_item_decision_snapshot", "upsert_group", "read_group", "_diagnostic_normalize_session_shape"} & names)


if __name__ == "__main__":
    unittest.main()
