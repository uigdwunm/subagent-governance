#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_wp07", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class MinimalDiagnosticsLightweightGroupsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "governance-data"

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def managed_record(
        task_id,
        *,
        attempt=1,
        target=None,
        updated_at=2_000_000,
        **overrides,
    ):
        target = target or f"agent-{task_id}-{attempt}"
        record = {
            "managed": True,
            "task_id": task_id,
            "attempt": attempt,
            "task_ref": governance.derive_task_ref(task_id, attempt, 12),
            "task_name": (
                "sg_standard_wp07_task_t_"
                + governance.derive_task_ref(task_id, attempt, 12)
            ),
            "semantic_name": "wp07_task",
            "requested_mode": "standard",
            "resolved_mode": "standard",
            "resolution_reason": "explicit_request",
            "contract_summary": {
                "objective": f"诊断 {task_id}",
                "completion_conditions": ["形成可验证状态"],
            },
            **governance.AttemptState().to_record(),
            "identity_status": "confirmed",
            "execution_status": "running",
            "platform_observation": "normal",
            "parent_action": "wait",
            "agent_id": target,
            "canonical_task_path": f"/root/{target}",
            "created_at": updated_at,
            "updated_at": updated_at,
        }
        record.update(overrides)
        return record

    @staticmethod
    def formal_result(task_id, attempt=1, business_result="complete"):
        value = {
            "task_id": task_id,
            "attempt": attempt,
            "business_result": business_result,
            "result": f"{task_id} 的正式结果正文不应完整进入诊断。",
            "evidence": ["定向测试证据"],
            "remaining": [],
            "suggested_parent_next_step": "父 Agent 显式处置。",
        }
        if business_result == "blocked":
            value.update(
                {
                    "blocker": "等待外部条件",
                    "attempted": ["检查本地状态"],
                    "required_to_resume": "外部条件满足",
                }
            )
        return value

    def store(self):
        return governance.StateStore(self.root / "sessions")

    def run_diagnose(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--diagnose", "--data-root", str(self.root), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )

    def tree_snapshot(self):
        if not self.root.exists() and not self.root.is_symlink():
            return None
        snapshot = {}
        paths = [self.root, *sorted(self.root.rglob("*"), key=lambda item: str(item))]
        for path in paths:
            metadata = path.lstat()
            kind = (
                "symlink"
                if stat.S_ISLNK(metadata.st_mode)
                else "directory"
                if stat.S_ISDIR(metadata.st_mode)
                else "file"
                if stat.S_ISREG(metadata.st_mode)
                else "other"
            )
            digest = None
            if kind == "file":
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            snapshot[str(path.relative_to(self.root)) if path != self.root else "."] = {
                "kind": kind,
                "inode": metadata.st_ino,
                "mtime_ns": metadata.st_mtime_ns,
                "mode": stat.S_IMODE(metadata.st_mode),
                "size": metadata.st_size,
                "sha256": digest,
            }
        return snapshot

    def write_tasks(self, session_id, *records):
        store = self.store()

        def add(state):
            for record in records:
                state["tasks"][record["task_id"]] = record
                for target in (record.get("agent_id"), record.get("canonical_task_path")):
                    if target:
                        state["agents"][target] = {
                            "task_id": record["task_id"],
                            "attempt": record["attempt"],
                        }

        store.update(session_id, add)
        return store

    def test_diagnose_missing_data_root_is_complete_empty_and_does_not_create_it(self):
        self.assertFalse(self.root.exists())

        result = self.run_diagnose()

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertFalse(output["data_root_exists"])
        self.assertEqual(output["scope"], "all_sessions")
        self.assertEqual(output["sessions"], [])
        self.assertEqual(
            output["scan"],
            {
                "requested": 0,
                "checked": 0,
                "succeeded": 0,
                "failed": 0,
                "omitted": 0,
                "complete": True,
            },
        )
        self.assertFalse(self.root.exists())

    def test_single_session_snapshot_is_normalized_and_has_no_filesystem_side_effects(self):
        record = self.managed_record("task-running", updated_at=governance._now())
        self.write_tasks("session-wp07", record)
        before = self.tree_snapshot()

        result = self.run_diagnose("--session", "session-wp07")

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["scope"], "single_session")
        self.assertEqual(output["requested_session"], "session-wp07")
        self.assertEqual(len(output["sessions"]), 1)
        snapshot = output["sessions"][0]
        self.assertEqual(snapshot["session_id"], "session-wp07")
        self.assertNotIn("tasks", snapshot)
        self.assertNotIn("agents", snapshot)
        self.assertEqual(snapshot["counts"]["action_required"], 1)
        attempt = snapshot["action_required"][0]
        self.assertEqual(attempt["task_id"], "task-running")
        self.assertTrue(attempt["action_required"])
        self.assertTrue(attempt["recent_activity"])
        self.assertNotIn("pending_action", attempt)
        self.assertNotIn("last_lifecycle_operation", attempt)
        self.assertEqual(self.tree_snapshot(), before)

    def test_single_session_missing_returns_exit_one_with_stable_json(self):
        self.root.mkdir(parents=True)
        before = self.tree_snapshot()

        result = self.run_diagnose("--session", "missing-session")

        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertFalse(output["scan"]["complete"])
        self.assertEqual(output["scan"]["failed"], 1)
        self.assertIn("session_missing", {issue["code"] for issue in output["issues"]})
        self.assertEqual(self.tree_snapshot(), before)

    def test_invalid_current_attempt_fields_are_reported_without_crashing(self):
        sessions_root = self.root / "sessions"
        sessions_root.mkdir(parents=True)
        state = governance.StateStore._empty_state("session-invalid-attempt")
        invalid_task = self.managed_record(
            "task-placeholder",
            result_storage_status="available",
            result_reference="unexpected.json",
        )
        invalid_task["task_id"] = ""
        state["tasks"] = {
            "": invalid_task,
            "task-missing-attempt": {
                "managed": True,
                "task_id": "task-missing-attempt",
            },
        }
        path = sessions_root / f"{governance._safe_name('session-invalid-attempt')}.json"
        path.write_text(json.dumps(state), encoding="utf-8")
        path.chmod(0o600)
        before = self.tree_snapshot()

        result = self.run_diagnose("--session", "session-invalid-attempt")

        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        codes = {issue["code"] for issue in output["sessions"][0]["issues"]}
        self.assertIn("current_required_field_missing", codes)
        self.assertIn("current_required_field_invalid", codes)
        self.assertFalse(output["scan"]["complete"])
        self.assertEqual(self.tree_snapshot(), before)

    def test_global_partial_failure_keeps_good_session_and_returns_exit_one(self):
        self.write_tasks("good-session", self.managed_record("good-task"))
        sessions_root = self.root / "sessions"
        bad_path = sessions_root / "broken.json"
        bad_path.write_text("{broken", encoding="utf-8")
        bad_path.chmod(0o600)
        before = self.tree_snapshot()

        result = self.run_diagnose()

        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["scan"]["requested"], 2)
        self.assertEqual(output["scan"]["checked"], 2)
        self.assertEqual(output["scan"]["succeeded"], 1)
        self.assertEqual(output["scan"]["failed"], 1)
        self.assertEqual([item["session_id"] for item in output["sessions"]], ["good-session"])
        self.assertIn("session_json_invalid", {issue["code"] for issue in output["issues"]})
        self.assertEqual(self.tree_snapshot(), before)

    @unittest.skipIf(os.name == "nt", "Windows uses different permission and symlink semantics")
    def test_diagnose_reports_symlink_permission_and_four_mib_boundary_without_fixing(self):
        sessions_root = self.root / "sessions"
        sessions_root.mkdir(parents=True)
        target = sessions_root / "target.json"
        target.write_text("{}", encoding="utf-8")
        target.chmod(0o600)
        (sessions_root / "linked.json").symlink_to(target)

        unsafe = governance.StateStore._empty_state("unsafe")
        unsafe_path = sessions_root / "unsafe.json"
        unsafe_path.write_text(json.dumps(unsafe), encoding="utf-8")
        unsafe_path.chmod(0o644)

        boundary = governance.StateStore._empty_state("boundary")
        boundary["padding"] = ""
        encoded = json.dumps(boundary, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        boundary["padding"] = "x" * (governance.MAX_STATE_BYTES - len(encoded))
        encoded = json.dumps(boundary, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.assertEqual(len(encoded), governance.MAX_STATE_BYTES)
        boundary_path = sessions_root / f"{governance._safe_name('boundary')}.json"
        boundary_path.write_bytes(encoded)
        boundary_path.chmod(0o600)

        before = self.tree_snapshot()
        result = self.run_diagnose()

        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        codes = {issue["code"] for issue in output["issues"]}
        self.assertIn("session_symlink", codes)
        self.assertIn("session_permissions_unsafe", codes)
        self.assertIn("boundary", {item["session_id"] for item in output["sessions"]})
        self.assertEqual(self.tree_snapshot(), before)

        boundary_path.write_bytes(encoded + b" ")
        over_limit = self.run_diagnose("--session", "boundary")
        self.assertEqual(over_limit.returncode, 1, over_limit.stderr)
        self.assertIn(
            "session_oversized",
            {issue["code"] for issue in json.loads(over_limit.stdout)["issues"]},
        )

    def test_result_reference_damage_is_reported_without_changing_state(self):
        task_id = "task-result-damaged"
        record = self.managed_record(
            task_id,
            execution_status="stopped",
            business_result="complete",
            acceptance_status="pending",
            result_protocol_status="valid",
            result_storage_status="available",
            parent_action="accept_result",
        )
        results_root = self.root / "results"
        result_path = governance.result_file_path(results_root, task_id, 1)
        record["result_reference"] = result_path.name
        record["result_sha256"] = "0" * 64
        self.write_tasks("session-result", record)
        results_root.mkdir(mode=0o700)
        result_path.write_text("{broken", encoding="utf-8")
        result_path.chmod(0o600)
        before = self.tree_snapshot()

        result = self.run_diagnose("--session", "session-result")

        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        snapshot = output["sessions"][0]
        self.assertIn("result_invalid", {issue["code"] for issue in snapshot["issues"]})
        attempt = snapshot["action_required"][0]
        self.assertFalse(attempt["formal_result"]["readable"])
        self.assertNotIn("result", attempt["formal_result"])
        self.assertEqual(self.tree_snapshot(), before)

    def test_missing_result_reference_file_is_a_fact_and_not_reassociated(self):
        task_id = "task-result-missing"
        record = self.managed_record(
            task_id,
            execution_status="stopped",
            business_result="complete",
            acceptance_status="pending",
            result_protocol_status="valid",
            result_storage_status="available",
            parent_action="accept_result",
        )
        expected = governance.result_file_path(self.root / "results", task_id, 1)
        record["result_reference"] = expected.name
        record["result_sha256"] = "0" * 64
        self.write_tasks("session-result", record)
        before = self.tree_snapshot()

        result = self.run_diagnose("--session", "session-result")

        self.assertEqual(result.returncode, 1, result.stderr)
        snapshot = json.loads(result.stdout)["sessions"][0]
        self.assertIn("result_missing", {issue["code"] for issue in snapshot["issues"]})
        self.assertFalse(expected.exists())
        self.assertEqual(self.tree_snapshot(), before)

    def test_attempt_and_group_limits_report_omitted_and_exit_one(self):
        now = governance._now()
        records = [
            self.managed_record(f"task-{index:03d}", updated_at=now)
            for index in range(257)
        ]
        store = self.write_tasks("session-limits", *records)

        def add_groups(state):
            state["groups"] = {
                f"group-{index:03d}": {
                    "group_id": f"group-{index:03d}",
                    "objective_summary": "验证诊断 group 数量上限",
                    "members": [{"task_id": "task-000", "required": True}],
                    "created_at": now,
                    "updated_at": now,
                }
                for index in range(65)
            }

        store.update("session-limits", add_groups)

        result = self.run_diagnose("--session", "session-limits")

        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertGreaterEqual(output["scan"]["omitted"], 2)
        self.assertFalse(output["scan"]["complete"])
        snapshot = output["sessions"][0]
        self.assertLessEqual(len(snapshot["action_required"]), 256)
        self.assertLessEqual(len(snapshot["groups"]), 64)
        self.assertIn("scan_incomplete", {issue["code"] for issue in snapshot["issues"]})

    def test_total_output_byte_limit_omits_complete_sessions_without_partial_json(self):
        self.write_tasks(
            "session-output",
            self.managed_record(
                "task-output",
                updated_at=governance._now(),
                contract_summary={
                    "objective": "x" * 600,
                    "completion_conditions": ["y" * 600] * 3,
                },
            ),
        )
        with mock.patch.object(governance, "DIAGNOSTIC_OUTPUT_BYTES", 1200):
            document, exit_code = governance._build_diagnostic_document(
                "session-output",
                self.root,
            )
            encoded = governance._diagnostic_output_bytes(document)

        self.assertEqual(exit_code, 1)
        self.assertEqual(document["sessions"], [])
        self.assertGreater(document["scan"]["omitted"], 0)
        self.assertLessEqual(len(encoded), 1200)
        self.assertIsInstance(json.loads(encoded), dict)

    def test_upsert_group_persists_only_minimum_fields_and_preserves_created_at(self):
        self.write_tasks("session-group", self.managed_record("task-a"))
        created = governance.upsert_group(
            {
                "group_id": "group-main",
                "objective_summary": "汇总必需任务",
                "members": [{"task_id": "task-a", "required": True}],
                "ignored": {"status": "must-not-persist"},
            },
            "session-group",
            state_store=self.store(),
            now=100,
        )
        updated = governance.upsert_group(
            {
                "group_id": "group-main",
                "objective_summary": "更新后的汇总目标",
                "members": [{"task_id": "task-a", "required": False}],
            },
            "session-group",
            state_store=self.store(),
            now=200,
        )

        self.assertEqual(created["status"], "created")
        self.assertEqual(updated["status"], "updated")
        group = self.store().read("session-group")["groups"]["group-main"]
        self.assertEqual(
            set(group),
            {"group_id", "objective_summary", "members", "created_at", "updated_at"},
        )
        self.assertEqual(group["created_at"], 100)
        self.assertEqual(group["updated_at"], 200)

    def test_group_validation_rejects_missing_duplicate_and_non_boolean_members(self):
        self.write_tasks("session-group", self.managed_record("task-a"))
        invalid_values = (
            {
                "group_id": "missing",
                "objective_summary": "引用不存在任务",
                "members": [{"task_id": "missing-task", "required": True}],
            },
            {
                "group_id": "duplicate",
                "objective_summary": "重复引用",
                "members": [
                    {"task_id": "task-a", "required": True},
                    {"task_id": "task-a", "required": False},
                ],
            },
            {
                "group_id": "bad-required",
                "objective_summary": "required 类型非法",
                "members": [{"task_id": "task-a", "required": 1}],
            },
        )
        for value in invalid_values:
            with self.subTest(value=value["group_id"]):
                with self.assertRaises(governance.GroupValidationError):
                    governance.upsert_group(
                        value,
                        "session-group",
                        state_store=self.store(),
                    )

    def test_group_summary_ready_is_independent_from_group_action_required(self):
        complete = self.managed_record("task-complete", target="agent-complete")
        blocked = self.managed_record("task-blocked", target="agent-blocked")
        store = self.write_tasks("session-group", complete, blocked)
        governance.submit_task_result(
            self.formal_result("task-complete"),
            "session-group",
            agent_target="agent-complete",
            state_store=store,
            results_root=self.root / "results",
            now=100,
        )
        governance.submit_task_result(
            self.formal_result("task-blocked", business_result="blocked"),
            "session-group",
            agent_target="agent-blocked",
            state_store=store,
            results_root=self.root / "results",
            now=100,
        )
        governance.upsert_group(
            {
                "group_id": "group-main",
                "objective_summary": "两个必需任务",
                "members": [
                    {"task_id": "task-complete", "required": True},
                    {"task_id": "task-blocked", "required": True},
                ],
            },
            "session-group",
            state_store=store,
            now=110,
        )

        pending = governance.read_group(
            "session-group",
            "group-main",
            state_store=store,
            results_root=self.root / "results",
        )
        self.assertTrue(pending["summary_ready"])
        self.assertTrue(pending["group_action_required"])

        governance.apply_parent_disposition(
            {
                "task_id": "task-complete",
                "attempt": 1,
                "action": "accept_result",
                "reason": "结果验收通过",
            },
            "session-group",
            state_store=store,
            now=120,
        )
        governance.apply_parent_disposition(
            {
                "task_id": "task-blocked",
                "attempt": 1,
                "action": "close_task",
                "reason": "用户确认结束阻塞任务",
            },
            "session-group",
            state_store=store,
            now=121,
        )
        closed = governance.read_group(
            "session-group",
            "group-main",
            state_store=store,
            results_root=self.root / "results",
        )
        self.assertTrue(closed["summary_ready"])
        self.assertFalse(closed["group_action_required"])

    def test_empty_required_members_do_not_claim_summary_ready_and_optional_is_non_authoritative(self):
        store = self.write_tasks("session-group", self.managed_record("task-optional"))
        governance.upsert_group(
            {
                "group_id": "optional-only",
                "objective_summary": "只有 optional 成员",
                "members": [{"task_id": "task-optional", "required": False}],
            },
            "session-group",
            state_store=store,
            now=100,
        )

        group = governance.read_group(
            "session-group",
            "optional-only",
            state_store=store,
            results_root=self.root / "results",
        )

        self.assertFalse(group["summary_ready"])
        self.assertFalse(group["group_action_required"])
        self.assertTrue(group["members"][0]["individual_action_required"])

    def test_group_is_never_inferred_from_multiple_tasks(self):
        store = self.write_tasks(
            "session-group",
            self.managed_record("task-a"),
            self.managed_record("task-b"),
        )

        state = store.read("session-group")
        self.assertNotIn("groups", state)
        result = self.run_diagnose("--session", "session-group")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["sessions"][0]["groups"], [])

    def test_group_cli_upsert_and_read_are_explicit(self):
        self.write_tasks("session-group", self.managed_record("task-a"))
        payload = {
            "group_id": "group-cli",
            "objective_summary": "CLI 显式 group",
            "members": [{"task_id": "task-a", "required": True}],
        }
        upsert = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--upsert-group",
                "--session",
                "session-group",
                "--data-root",
                str(self.root),
            ],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(upsert.returncode, 0, upsert.stderr)
        self.assertEqual(json.loads(upsert.stdout)["status"], "created")

        read = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--read-group",
                "--session",
                "session-group",
                "--group-id",
                "group-cli",
                "--data-root",
                str(self.root),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertEqual(json.loads(read.stdout)["group_id"], "group-cli")

    def test_parallel_group_upserts_preserve_every_explicit_group(self):
        self.write_tasks("session-group", self.managed_record("task-a"))
        processes = []
        for index in range(16):
            payload = {
                "group_id": f"group-{index:02d}",
                "objective_summary": f"并发显式 group {index}",
                "members": [{"task_id": "task-a", "required": index % 2 == 0}],
            }
            processes.append(
                (
                    subprocess.Popen(
                        [
                            sys.executable,
                            str(SCRIPT),
                            "--upsert-group",
                            "--session",
                            "session-group",
                            "--data-root",
                            str(self.root),
                        ],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    ),
                    json.dumps(payload, ensure_ascii=False),
                )
            )

        for process, payload_text in processes:
            stdout, stderr = process.communicate(input=payload_text, timeout=15)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(json.loads(stdout)["status"], "created")

        state = self.store().read("session-group")
        self.assertEqual(
            set(state["groups"]),
            {f"group-{index:02d}" for index in range(16)},
        )
        expected_fields = {
            "group_id",
            "objective_summary",
            "members",
            "created_at",
            "updated_at",
        }
        self.assertTrue(
            all(set(group) == expected_fields for group in state["groups"].values())
        )

    def test_diagnose_cli_parameter_errors_keep_json_stdout(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--diagnose", "--session"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        output = json.loads(result.stdout)
        self.assertEqual(output["scope"], "single_session")
        self.assertFalse(output["scan"]["complete"])
        self.assertIn("scan_incomplete", {issue["code"] for issue in output["issues"]})

    def test_diagnose_rejects_non_diagnostic_selectors_with_json_stdout(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--diagnose", "--task-id", "task-a"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        output = json.loads(result.stdout)
        self.assertFalse(output["scan"]["complete"])
        self.assertIn("scan_incomplete", {issue["code"] for issue in output["issues"]})

    def test_wp07_machine_semantics_and_documentation_publish_minimum_boundaries(self):
        semantics = governance.SEMANTIC_RULES
        self.assertEqual(
            semantics["diagnostic_limits"],
            {
                "sessions": 128,
                "attempts_per_session": 256,
                "groups_per_session": 64,
                "issues": 256,
                "output_bytes": 2 * 1024 * 1024,
            },
        )
        self.assertEqual(
            semantics["group"]["fields"],
            ["group_id", "objective_summary", "members", "created_at", "updated_at"],
        )
        self.assertFalse(semantics["group"]["persists_derived_status"])
        skill = (ROOT / "skills/subagent-governance/SKILL.md").read_text(encoding="utf-8")
        boundaries = (
            ROOT / "skills/subagent-governance/references/runtime-boundaries.md"
        ).read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for text in (skill, boundaries, readme):
            self.assertIn("--diagnose", text)
            self.assertIn("--upsert-group", text)
            self.assertIn("summary_ready", text)
            self.assertIn("group_action_required", text)
            self.assertIn("AggregateResult", text)
        self.assertIn("| Agent | 目标 | 治理等级 | 模型 | 强度 | 上下文 | 范围 | 完成条件 |", skill)


if __name__ == "__main__":
    unittest.main()
