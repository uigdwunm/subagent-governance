import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_diagnostics_v5", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class MinimalDiagnosticsLightweightGroupsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = governance.StateStore(self.root / "sessions")
        self.session_id = "diagnostics-v5"

    @staticmethod
    def contract(name):
        return governance.TaskContract(
            semantic_name=name,
            requested_mode="light",
            resolved_mode="light",
            resolution_reason="explicit_request",
            task_features=None,
            objective=f"验证 {name}",
            background="notification-only diagnostics",
            work_scope=["diagnostics"],
            forbidden_scope=["result persistence"],
            completion_conditions=["notification observed"],
            evidence_requirements=[],
            relevant_files=[],
            current_state=None,
            model=None,
            reasoning_effort=None,
            context_strategy="isolated",
            context_turns=None,
            context_reason=None,
        )

    def state_with_tasks(self, *task_ids):
        state = governance.StateStore._empty_state(self.session_id)
        for index, task_id in enumerate(task_ids, start=1):
            ref = f"{index:012x}"
            name = f"task_{index}"
            container = governance._initial_task_record(
                1,
                ref,
                f"sg_light_{name}_t_{ref}",
                self.contract(name),
                100 + index,
            )
            execution = container["executions"]["1"]
            target = f"/root/{name}"
            execution["dispatch_record"].update(
                dispatch_state="acknowledged",
                dispatch_target=target,
                tool_use_id=f"tool-{index}",
                claimed_at=105 + index,
            )
            state["tasks"][task_id] = container
            state["agents"][target] = {"task_id": task_id, "attempt": 1}
        self.store.update(self.session_id, lambda current: current.update(state))
        return state

    def notify(self, task_id, terminal_status="completed", now=200):
        state = self.store.read(self.session_id)
        execution = state["tasks"][task_id]["executions"]["1"]
        target = execution["dispatch_record"]["dispatch_target"]
        return governance.record_terminal_notification(
            {
                "sender_target": target,
                "task_id": task_id,
                "attempt": 1,
                "terminal_status": terminal_status,
            },
            self.session_id,
            state_store=self.store,
            now=now,
        )

    def test_work_item_snapshot_exposes_notification_not_business_result(self):
        self.state_with_tasks("task-a")
        self.notify("task-a")
        state = self.store.read(self.session_id)

        snapshot, issues, incomplete = governance._build_work_item_decision_snapshot(
            state,
            "task-a",
            session_id=self.session_id,
            now=220,
        )

        self.assertFalse(incomplete, issues)
        self.assertEqual(
            set(snapshot["terminal_notification"]),
            {"state", "attempt", "source", "terminal_status"},
        )
        self.assertEqual(snapshot["terminal_notification"]["state"], "observed")
        self.assertEqual(snapshot["terminal_notification"]["terminal_status"], "completed")
        self.assertNotIn("disposition", snapshot)
        self.assertNotIn("outcome_availability", snapshot)
        self.assertNotIn("growth", snapshot)
        self.assertNotIn("facts", snapshot)
        self.assertNotIn("timestamps", snapshot)
        self.assertNotIn("facts", snapshot["execution_candidates"][0])
        self.assertIn("timestamps", snapshot["execution_candidates"][0])
        self.assertNotIn("closed", snapshot["execution_candidates"][0])
        self.assertNotIn("recent_activity", snapshot["execution_candidates"][0])
        self.assertNotIn("business_result", snapshot["execution_candidates"][0])
        self.assertEqual(snapshot["allowed_actions"], ["close_task", "resume_business"])

    def test_group_summary_ready_requires_every_required_notification(self):
        self.state_with_tasks("required-a", "required-b", "optional-c")
        created = governance.upsert_group(
            {
                "group_id": "group-v5",
                "objective_summary": "汇总原生通知",
                "members": [
                    {"task_id": "required-a", "required": True},
                    {"task_id": "required-b", "required": True},
                    {"task_id": "optional-c", "required": False},
                ],
            },
            self.session_id,
            state_store=self.store,
        )
        self.assertNotIn("created_at", created)
        self.assertNotIn("updated_at", created)
        persisted = self.store.read(self.session_id)["groups"]["group-v5"]
        self.assertNotIn("created_at", persisted)
        self.assertNotIn("updated_at", persisted)
        legacy_state = self.store.read(self.session_id)
        legacy_state["groups"]["group-v5"]["created_at"] = 150
        legacy_state["groups"]["group-v5"]["updated_at"] = 175
        migrated = governance._migrate_state_to_current(legacy_state)
        self.assertNotIn("created_at", migrated["groups"]["group-v5"])
        self.assertNotIn("updated_at", migrated["groups"]["group-v5"])
        self.assertNotIn("created_at", governance.SEMANTIC_RULES["group"]["fields"])
        self.assertNotIn("updated_at", governance.SEMANTIC_RULES["group"]["fields"])
        self.notify("required-a", now=200)
        self.assertFalse(
            governance.read_group(
                self.session_id, "group-v5", state_store=self.store
            )["summary_ready"]
        )

        self.notify("required-b", now=210)
        group = governance.read_group(
            self.session_id, "group-v5", state_store=self.store
        )
        self.assertTrue(group["summary_ready"])
        self.assertNotIn("created_at", group)
        self.assertNotIn("updated_at", group)
        optional = next(item for item in group["members"] if item["task_id"] == "optional-c")
        self.assertEqual(optional["terminal_notification"]["state"], "pending")

    def test_closed_required_member_is_summary_ready_without_notification(self):
        self.state_with_tasks("closed-task")
        state = self.store.read(self.session_id)
        execution = state["tasks"]["closed-task"]["executions"]["1"]
        governance._close_attempt_record(
            state, "closed-task", 1, execution, "parent_closed", 180
        )
        state["tasks"]["closed-task"]["work_item"]["lifecycle"] = "tombstoned"
        self.store.update(self.session_id, lambda current: current.update(state))
        governance.upsert_group(
            {
                "group_id": "closed-group",
                "objective_summary": "关闭成员",
                "members": [{"task_id": "closed-task", "required": True}],
            },
            self.session_id,
            state_store=self.store,
        )
        self.assertTrue(
            governance.read_group(
                self.session_id, "closed-group", state_store=self.store
            )["summary_ready"]
        )

    def test_diagnose_reads_state_without_creating_results_directory(self):
        self.state_with_tasks("diagnose-task")
        document, exit_code = governance._build_diagnostic_document(
            self.session_id,
            self.root,
        )
        self.assertEqual(exit_code, 0, document)
        self.assertEqual(document["sessions"][0]["counts"]["work_items"], 1)
        self.assertNotIn("updated_at", document["sessions"][0])
        self.assertFalse((self.root / "results").exists())

    def test_diagnose_missing_session_is_bounded_and_read_only(self):
        document, exit_code = governance._build_diagnostic_document(
            "missing-session",
            self.root,
        )
        self.assertEqual(exit_code, 1)
        self.assertIn(
            "session_missing", {issue["code"] for issue in document["issues"]}
        )
        session_path, _lock_path = self.store._paths("missing-session")
        self.assertFalse(session_path.exists())
        self.assertFalse((self.root / "results").exists())

    @unittest.skipIf(os.name == "nt", "Windows does not expose POSIX file mode bits")
    def test_diagnose_rechecks_permissions_after_open(self):
        self.state_with_tasks("permission-race")
        state_path, _lock_path = self.store._paths(self.session_id)
        state_path.chmod(0o644)
        original_lstat = Path.lstat

        def safe_path_lstat(path):
            metadata = original_lstat(path)
            if path != state_path:
                return metadata
            return SimpleNamespace(
                st_mode=(metadata.st_mode & ~0o777) | 0o600,
                st_uid=metadata.st_uid,
                st_size=metadata.st_size,
            )

        with mock.patch.object(Path, "lstat", autospec=True, side_effect=safe_path_lstat):
            with self.assertRaises(governance.DiagnosticReadError) as raised:
                governance._read_session_file_read_only(
                    state_path,
                    requested_session=self.session_id,
                )

        self.assertEqual(raised.exception.code, "session_permissions_unsafe")
        self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o644)

    @unittest.skipIf(os.name == "nt", "Windows does not expose POSIX symlink behavior")
    def test_diagnose_maps_shared_private_read_symlink_error(self):
        self.state_with_tasks("symlink-state")
        state_path, _lock_path = self.store._paths(self.session_id)
        target = self.root / "state-target.json"
        target.write_bytes(state_path.read_bytes())
        state_path.unlink()
        state_path.symlink_to(target)

        with self.assertRaises(governance.DiagnosticReadError) as raised:
            governance._read_session_file_read_only(
                state_path,
                requested_session=self.session_id,
            )

        self.assertEqual(raised.exception.code, "session_symlink")

    def test_group_rejects_unknown_member(self):
        self.state_with_tasks("known")
        with self.assertRaises(governance.GroupValidationError):
            governance.upsert_group(
                {
                    "group_id": "invalid-group",
                    "objective_summary": "非法成员",
                    "members": [{"task_id": "unknown", "required": True}],
                },
                self.session_id,
                state_store=self.store,
            )


if __name__ == "__main__":
    unittest.main()
