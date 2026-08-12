#!/usr/bin/env python3

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_wp05", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class FormalResultParentClosureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = governance.StateStore(self.root / "sessions")
        self.results_root = self.root / "results"

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def result(task_id="sg-wp05-task", attempt=1, business_result="complete", **overrides):
        value = {
            "task_id": task_id,
            "attempt": attempt,
            "business_result": business_result,
            "result": "已完成 WP-05 目标实现。",
            "evidence": ["定向测试通过"],
            "remaining": [],
            "suggested_parent_next_step": "父 Agent 读取正式结果并显式处置。",
        }
        if business_result == "blocked":
            value.update({
                "blocker": "缺少外部授权",
                "attempted": ["检查本地配置"],
                "required_to_resume": "用户提供授权",
            })
        elif business_result == "failed":
            value.update({
                "failure_reason": "目标测试仍失败",
                "attempted": ["复现并定位失败"],
                "retry_conditions": "依赖修复后重新执行",
            })
        elif business_result == "needs_decision":
            value.update({
                "decision_question": "是否接受尚未验证的平台风险？",
                "options": ["接受", "暂缓"],
                "recommendation": "暂缓并补真实平台验证",
            })
        value.update(overrides)
        return value

    def add_managed(
        self,
        *,
        task_id="sg-wp05-task",
        attempt=1,
        target="agent-wp05",
        current=True,
        **overrides,
    ):
        now = 100
        record = {
            "managed": True,
            "task_id": task_id,
            "attempt": attempt,
            "task_ref": governance.derive_task_ref(task_id, attempt, 12),
            "task_name": "sg_standard_formal_result_t_"
            + governance.derive_task_ref(task_id, attempt, 12),
            "semantic_name": "formal_result",
            "requested_mode": "standard",
            "resolved_mode": "standard",
            "resolution_reason": "explicit_request",
            "contract_summary": {"objective": "验证正式结果闭环"},
            **governance.AttemptState().to_record(),
            "identity_status": "confirmed",
            "execution_status": "running",
            "platform_observation": "normal",
            "parent_action": "wait",
            "agent_id": target,
            "canonical_task_path": None,
            "created_at": now,
            "updated_at": now,
        }
        record.update(overrides)

        def add(state):
            if current or task_id not in state["tasks"]:
                state["tasks"][task_id] = record
            else:
                task = state["tasks"][task_id]
                task.setdefault("prior_attempts", {})[str(attempt)] = record
            state["agents"][target] = {"task_id": task_id, "attempt": attempt}

        self.store.update("session-wp05", add)
        return record

    def submit(self, value, target="agent-wp05", now=200):
        return governance.submit_task_result(
            value,
            "session-wp05",
            agent_target=target,
            state_store=self.store,
            results_root=self.results_root,
            now=now,
        )

    def test_result_path_is_deterministic_and_does_not_trust_task_id_as_path(self):
        hostile = "../../含空格/../../../secret"
        first = governance.result_file_path(self.results_root, hostile, 7)
        second = governance.result_file_path(self.results_root, hostile, 7)

        self.assertEqual(first, second)
        self.assertEqual(first.parent, self.results_root)
        self.assertNotIn("..", first.name)
        self.assertNotIn("/", first.name)
        self.assertRegex(first.name, r"^result-[a-f0-9]{64}-attempt-7\.json$")

    def test_complete_submission_writes_file_before_state_and_is_readable(self):
        self.add_managed()
        submitted = self.submit(self.result())

        self.assertEqual(submitted["status"], "stored")
        state = self.store.read("session-wp05")
        record = state["tasks"]["sg-wp05-task"]
        self.assertEqual(record["execution_status"], "stopped")
        self.assertEqual(record["business_result"], "complete")
        self.assertEqual(record["result_protocol_status"], "valid")
        self.assertEqual(record["result_storage_status"], "available")
        self.assertEqual(record["acceptance_status"], "pending")
        self.assertEqual(record["parent_action"], "accept_result")
        self.assertNotIn("result", record)
        self.assertNotIn("evidence", record)
        result_path = self.results_root / record["result_reference"]
        self.assertTrue(result_path.is_file())
        if os.name != "nt":
            self.assertEqual(result_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.results_root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(
            governance.read_task_result(
                "session-wp05",
                "sg-wp05-task",
                1,
                state_store=self.store,
                results_root=self.results_root,
            ),
            self.result(),
        )

    def test_each_business_result_has_exact_parent_state(self):
        expected = {
            "blocked": (None, "decide_disposition"),
            "failed": (None, "decide_disposition"),
            "needs_decision": (None, "ask_user"),
        }
        for index, (business_result, (acceptance, action)) in enumerate(expected.items(), start=1):
            task_id = f"sg-wp05-{business_result}"
            target = f"agent-wp05-{index}"
            self.add_managed(task_id=task_id, target=target)
            self.submit(self.result(task_id=task_id, business_result=business_result), target=target)
            record = self.store.read("session-wp05")["tasks"][task_id]
            self.assertEqual(record["execution_status"], "stopped")
            self.assertEqual(record["business_result"], business_result)
            self.assertEqual(record["acceptance_status"], acceptance)
            self.assertEqual(record["parent_action"], action)

    def test_subagent_stop_without_or_with_invalid_result_uses_correction_budget(self):
        self.add_managed()
        missing = governance.handle(
            {
                "session_id": "session-wp05",
                "hook_event_name": "SubagentStop",
                "agent_id": "agent-wp05",
                "last_assistant_message": "自由文本不能成为正式结果",
            },
            self.store,
        )
        self.assertTrue(missing["continue"])
        record = self.store.read("session-wp05")["tasks"]["sg-wp05-task"]
        self.assertEqual(record["result_protocol_status"], "needs_correction")
        self.assertEqual(record["parent_action"], "correct_result")
        self.assertIsNone(record["business_result"])

        self.store.update(
            "session-wp05",
            lambda state: state["tasks"]["sg-wp05-task"].update({
                "execution_status": "running",
                "correction_count": 2,
                "parent_action": "wait",
            }),
        )
        invalid = governance.handle(
            {
                "session_id": "session-wp05",
                "hook_event_name": "SubagentStop",
                "agent_id": "agent-wp05",
                "task_result": {"task_id": "sg-wp05-task", "attempt": 1},
            },
            self.store,
        )
        self.assertTrue(invalid["continue"])
        record = self.store.read("session-wp05")["tasks"]["sg-wp05-task"]
        self.assertEqual(record["result_protocol_status"], "exhausted")
        self.assertEqual(record["parent_action"], "manual_review")
        self.assertIsNone(record["business_result"])

    def test_subagent_stop_accepts_only_explicit_structured_task_result(self):
        self.add_managed()
        handled = governance.handle(
            {
                "session_id": "session-wp05",
                "hook_event_name": "SubagentStop",
                "agent_id": "agent-wp05",
                "last_assistant_message": "这段自由文本不是权威结果。",
                "task_result": self.result(),
                "timestamp": 220,
            },
            self.store,
        )

        self.assertTrue(handled["continue"])
        self.assertIn("stored", handled["systemMessage"])
        record = self.store.read("session-wp05")["tasks"]["sg-wp05-task"]
        self.assertEqual(record["business_result"], "complete")
        self.assertEqual(record["acceptance_status"], "pending")

    def test_same_result_replay_is_idempotent_and_different_result_sets_one_conflict(self):
        self.add_managed()
        first = self.submit(self.result(), now=200)
        replay = self.submit(self.result(), now=300)
        conflict_value = self.result(result="不同但机械合法的结果 B")
        conflict = self.submit(conflict_value, now=400)
        conflict_replay = self.submit(conflict_value, now=500)

        self.assertEqual(first["status"], "stored")
        self.assertEqual(replay["status"], "idempotent")
        self.assertEqual(conflict["status"], "conflict")
        self.assertEqual(conflict_replay["status"], "conflict")
        record = self.store.read("session-wp05")["tasks"]["sg-wp05-task"]
        self.assertTrue(record["result_conflict"])
        self.assertEqual(record["result_conflict_first_seen_at"], 400)
        self.assertEqual(record["parent_action"], "manual_review")
        self.assertEqual(record["business_result"], "complete")
        self.assertEqual(
            governance.read_task_result(
                "session-wp05",
                "sg-wp05-task",
                1,
                state_store=self.store,
                results_root=self.results_root,
            )["result"],
            "已完成 WP-05 目标实现。",
        )

    def test_result_reader_revalidates_authoritative_file(self):
        self.add_managed()
        self.submit(self.result())
        path = governance.result_file_path(self.results_root, "sg-wp05-task", 1)
        path.write_text("{}\n", encoding="utf-8")
        path.chmod(0o600)

        with self.assertRaisesRegex(governance.ResultStorageError, "协议校验失败"):
            governance.read_task_result(
                "session-wp05",
                "sg-wp05-task",
                1,
                state_store=self.store,
                results_root=self.results_root,
            )

    def test_state_association_failure_keeps_orphan_and_can_reassociate(self):
        self.add_managed()
        original_write = self.store._write_path
        calls = 0

        def fail_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise governance.StateWriteError("simulated association failure")
            return original_write(*args, **kwargs)

        with mock.patch.object(self.store, "_write_path", side_effect=fail_once):
            result = self.submit(self.result())

        self.assertEqual(result["status"], "storage_unavailable")
        result_path = governance.result_file_path(self.results_root, "sg-wp05-task", 1)
        self.assertTrue(result_path.is_file())
        record = self.store.read("session-wp05")["tasks"]["sg-wp05-task"]
        self.assertEqual(record["result_protocol_status"], "valid")
        self.assertEqual(record["result_storage_status"], "unavailable")
        self.assertIsNone(record["business_result"])
        self.assertEqual(record["parent_action"], "manual_review")

        repaired = governance.reassociate_task_result(
            "session-wp05",
            "sg-wp05-task",
            1,
            state_store=self.store,
            results_root=self.results_root,
            now=300,
        )
        self.assertEqual(repaired["status"], "reassociated")
        record = self.store.read("session-wp05")["tasks"]["sg-wp05-task"]
        self.assertEqual(record["result_storage_status"], "available")
        self.assertEqual(record["business_result"], "complete")

    def test_result_file_failure_is_storage_unavailable_not_protocol_error(self):
        self.add_managed()
        with mock.patch.object(
            governance,
            "_write_or_read_authoritative_result",
            side_effect=governance.ResultStorageError("simulated result write failure"),
        ):
            submitted = self.submit(self.result())

        self.assertEqual(submitted["status"], "storage_unavailable")
        record = self.store.read("session-wp05")["tasks"]["sg-wp05-task"]
        self.assertEqual(record["result_protocol_status"], "valid")
        self.assertEqual(record["result_storage_status"], "unavailable")
        self.assertIsNone(record["business_result"])
        self.assertEqual(record["parent_action"], "manual_review")

    def test_parallel_same_result_submission_has_one_authoritative_file(self):
        self.add_managed()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.submit, self.result(), now=200 + index) for index in range(2)]
        statuses = sorted(future.result()["status"] for future in futures)

        self.assertEqual(statuses, ["idempotent", "stored"])
        files = list(self.results_root.glob("result-*.json"))
        self.assertEqual(len(files), 1)
        record = self.store.read("session-wp05")["tasks"]["sg-wp05-task"]
        self.assertFalse(record["result_conflict"])

    def test_late_old_attempt_result_stays_on_old_attempt_and_marks_duplicate(self):
        task_id = "sg-wp05-late"
        self.add_managed(
            task_id=task_id,
            attempt=2,
            target="agent-new",
            spawn_observation="success",
        )
        self.add_managed(
            task_id=task_id,
            attempt=1,
            target="agent-old",
            current=False,
            spawn_observation="unknown",
            identity_status="confirmed",
        )
        self.submit(self.result(task_id=task_id, attempt=1), target="agent-old")

        task = self.store.read("session-wp05")["tasks"][task_id]
        self.assertEqual(task["attempt"], 2)
        self.assertTrue(task["duplicate_execution"])
        self.assertEqual(task["parent_action"], "resolve_duplicate")
        old = task["prior_attempts"]["1"]
        self.assertEqual(old["business_result"], "complete")
        self.assertEqual(old["result_storage_status"], "available")

    def test_result_after_successful_interrupt_is_rejected(self):
        self.add_managed(execution_status="interrupted", parent_action="decide_disposition")
        with self.assertRaisesRegex(governance.ResultSubmissionError, "中断"):
            self.submit(self.result())
        self.assertFalse(governance.result_file_path(self.results_root, "sg-wp05-task", 1).exists())

    def test_reject_result_preserves_file_and_accept_result_closes_task(self):
        self.add_managed()
        self.submit(self.result())
        rejected = governance.apply_parent_disposition(
            {
                "task_id": "sg-wp05-task",
                "attempt": 1,
                "action": "reject_result",
                "reason": "父 Agent 验收发现业务条件未满足",
            },
            "session-wp05",
            state_store=self.store,
            now=300,
        )
        self.assertEqual(rejected["status"], "rejected")
        record = self.store.read("session-wp05")["tasks"]["sg-wp05-task"]
        self.assertEqual(record["acceptance_status"], "rejected")
        self.assertEqual(record["parent_action"], "decide_disposition")
        self.assertTrue(governance.result_file_path(self.results_root, "sg-wp05-task", 1).exists())

        self.store.update(
            "session-wp05",
            lambda state: state["tasks"]["sg-wp05-task"].update({
                "acceptance_status": "pending",
                "parent_action": "accept_result",
            }),
        )
        accepted = governance.apply_parent_disposition(
            {
                "task_id": "sg-wp05-task",
                "attempt": 1,
                "action": "accept_result",
                "reason": "父 Agent 已核对实现与证据",
            },
            "session-wp05",
            state_store=self.store,
            now=400,
        )
        self.assertEqual(accepted["status"], "accepted")
        state = self.store.read("session-wp05")
        record = state["tasks"]["sg-wp05-task"]
        self.assertEqual(record["acceptance_status"], "accepted")
        self.assertTrue(record["attempt_closed"])
        self.assertIsNone(record["parent_action"])
        self.assertIn("sg-wp05-task:1", state["tombstones"])
        replay = self.submit(self.result(), now=500)
        self.assertEqual(replay["status"], "idempotent")
        replayed = self.store.read("session-wp05")["tasks"]["sg-wp05-task"]
        self.assertEqual(replayed["acceptance_status"], "accepted")
        self.assertTrue(replayed["attempt_closed"])

    def test_accept_result_requires_duplicate_resolution_and_clears_result_conflict(self):
        self.add_managed()
        self.submit(self.result())
        self.submit(self.result(result="冲突结果 B"), now=250)
        self.store.update(
            "session-wp05",
            lambda state: state["tasks"]["sg-wp05-task"].update({
                "duplicate_execution": True,
            }),
        )
        with self.assertRaisesRegex(governance.ParentDispositionConflict, "重复执行"):
            governance.apply_parent_disposition(
                {
                    "task_id": "sg-wp05-task",
                    "attempt": 1,
                    "action": "accept_result",
                    "reason": "已重新核对权威结果",
                },
                "session-wp05",
                state_store=self.store,
            )

        self.store.update(
            "session-wp05",
            lambda state: state["tasks"]["sg-wp05-task"].update({
                "duplicate_execution": False,
            }),
        )
        governance.apply_parent_disposition(
            {
                "task_id": "sg-wp05-task",
                "attempt": 1,
                "action": "accept_result",
                "reason": "已重新核对权威结果",
            },
            "session-wp05",
            state_store=self.store,
            now=300,
        )
        record = self.store.read("session-wp05")["tasks"]["sg-wp05-task"]
        self.assertFalse(record["result_conflict"])
        self.assertNotIn("result_conflict_sha256", record)

    def test_close_task_refuses_running_attempt_and_select_attempt_does_not_auto_interrupt(self):
        task_id = "sg-wp05-multi"
        self.add_managed(task_id=task_id, attempt=2, target="agent-running")
        self.add_managed(
            task_id=task_id,
            attempt=1,
            target="agent-stopped",
            current=False,
            execution_status="stopped",
            duplicate_execution=True,
            parent_action="resolve_duplicate",
        )
        self.store.update(
            "session-wp05",
            lambda state: state["tasks"][task_id].update({
                "duplicate_execution": True,
                "parent_action": "resolve_duplicate",
            }),
        )

        with self.assertRaises(governance.ParentDispositionConflict) as caught:
            governance.apply_parent_disposition(
                {
                    "task_id": task_id,
                    "attempt": 2,
                    "action": "close_task",
                    "reason": "用户明确放弃全部执行",
                },
                "session-wp05",
                state_store=self.store,
            )
        self.assertEqual(caught.exception.interrupt_targets, ["agent-running"])

        selected = governance.apply_parent_disposition(
            {
                "task_id": task_id,
                "attempt": 1,
                "action": "select_attempt",
                "reason": "保留已停止且已有可核对进度的旧执行",
            },
            "session-wp05",
            state_store=self.store,
            now=500,
        )
        self.assertEqual(selected["status"], "selected")
        self.assertEqual(selected["interrupt_targets"], ["agent-running"])
        task = self.store.read("session-wp05")["tasks"][task_id]
        self.assertEqual(task["attempt"], 1)
        running = task["prior_attempts"]["2"]
        self.assertTrue(running["duplicate_not_selected"])
        self.assertFalse(running.get("attempt_closed", False))
        self.assertTrue(task["duplicate_execution"])

    def test_select_attempt_closes_nonrunning_candidates_and_close_task_closes_all_attempts(self):
        task_id = "sg-wp05-select-close"
        self.add_managed(task_id=task_id, attempt=2, target="agent-current", execution_status="stopped")
        self.add_managed(
            task_id=task_id,
            attempt=1,
            target="agent-old",
            current=False,
            execution_status="stopped",
        )
        self.store.update(
            "session-wp05",
            lambda state: state["tasks"][task_id].update({
                "duplicate_execution": True,
                "parent_action": "resolve_duplicate",
            }),
        )

        selected = governance.apply_parent_disposition(
            {
                "task_id": task_id,
                "attempt": 2,
                "action": "select_attempt",
                "reason": "选择当前停止的执行",
            },
            "session-wp05",
            state_store=self.store,
            now=500,
        )
        self.assertEqual(selected["interrupt_targets"], [])
        state = self.store.read("session-wp05")
        task = state["tasks"][task_id]
        self.assertFalse(task["duplicate_execution"])
        self.assertTrue(task["prior_attempts"]["1"]["attempt_closed"])
        self.assertIn(f"{task_id}:1", state["tombstones"])

        closed = governance.apply_parent_disposition(
            {
                "task_id": task_id,
                "attempt": 2,
                "action": "close_task",
                "reason": "用户明确放弃剩余任务",
            },
            "session-wp05",
            state_store=self.store,
            now=600,
        )
        self.assertEqual(closed["status"], "closed")
        state = self.store.read("session-wp05")
        self.assertTrue(state["tasks"][task_id]["attempt_closed"])
        self.assertIn(f"{task_id}:2", state["tombstones"])

    def test_cli_submit_read_reassociate_and_parent_disposition_modes_are_explicit(self):
        data_root = self.root / "cli-data"
        cli_store = governance.StateStore(data_root / "sessions")
        original_store = self.store
        self.store = cli_store
        try:
            self.add_managed()
        finally:
            self.store = original_store
        submit = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--submit-result",
                "--session",
                "session-wp05",
                "--agent-target",
                "agent-wp05",
                "--data-root",
                str(data_root),
            ],
            input=json.dumps(self.result(), ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(submit.returncode, 0, submit.stderr)
        self.assertEqual(json.loads(submit.stdout)["status"], "stored")

        read = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--read-result",
                "--session",
                "session-wp05",
                "--task-id",
                "sg-wp05-task",
                "--attempt",
                "1",
                "--data-root",
                str(data_root),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertEqual(json.loads(read.stdout), self.result())

        disposition = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--parent-disposition",
                "--session",
                "session-wp05",
                "--data-root",
                str(data_root),
            ],
            input=json.dumps({
                "task_id": "sg-wp05-task",
                "attempt": 1,
                "action": "reject_result",
                "reason": "CLI 显式验收未通过",
            }, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(disposition.returncode, 0, disposition.stderr)
        self.assertEqual(json.loads(disposition.stdout)["status"], "rejected")

    def test_machine_semantics_anchor_formal_result_storage_and_parent_disposition(self):
        semantics = json.loads((ROOT / "schemas/governance-semantics.schema.json").read_text(encoding="utf-8"))
        rules = semantics["x-semantics"]
        self.assertEqual(rules["formal_result_storage"]["directory"], "results")
        self.assertFalse(rules["formal_result_storage"]["state_embeds_full_result"])
        self.assertEqual(
            rules["parent_disposition_fields"],
            ["task_id", "attempt", "action", "reason"],
        )


if __name__ == "__main__":
    unittest.main()
