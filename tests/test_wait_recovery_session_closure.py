#!/usr/bin/env python3

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_wp06", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class WaitRecoverySessionClosureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = governance.StateStore(self.root / "sessions")
        self.session_id = "session-wp06"

    def tearDown(self):
        self.temporary.cleanup()

    def managed_record(
        self,
        *,
        task_id="sg-wp06-task",
        attempt=1,
        target=None,
        updated_at=100,
        **overrides,
    ):
        target = target or f"agent-{attempt}"
        record = {
            "managed": True,
            "task_id": task_id,
            "attempt": attempt,
            "task_ref": governance.derive_task_ref(task_id, attempt, 12),
            "task_name": (
                "sg_standard_wait_recovery_t_"
                + governance.derive_task_ref(task_id, attempt, 12)
            ),
            "semantic_name": "wait_recovery",
            "requested_mode": "standard",
            "resolved_mode": "standard",
            "resolution_reason": "explicit_request",
            "contract_summary": {
                "objective": f"验证 WP-06 attempt {attempt}",
                "completion_conditions": ["完成机械闭环"],
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

    def write_task(self, current, *priors):
        def add(state):
            current_record = dict(current)
            current_record["prior_attempts"] = {
                str(record["attempt"]): dict(record) for record in priors
            }
            state["tasks"][current_record["task_id"]] = current_record
            for record in (current_record, *priors):
                for target in (record.get("agent_id"), record.get("canonical_task_path")):
                    if target:
                        state["agents"][target] = {
                            "task_id": record["task_id"],
                            "attempt": record["attempt"],
                        }

        self.store.update(self.session_id, add)

    @staticmethod
    def formal_result(task_id, attempt):
        return {
            "task_id": task_id,
            "attempt": attempt,
            "business_result": "complete",
            "result": "已完成等待与会话闭环验证。",
            "evidence": ["定向测试"],
            "remaining": [],
            "suggested_parent_next_step": "父 Agent 显式验收。",
        }

    def test_action_required_includes_stale_prior_attempt_and_recent_activity_does_not(self):
        now = 2_000_000
        stale = now - governance.RETENTION_SECONDS["recent_activity"] - 1
        current = self.managed_record(
            attempt=2,
            updated_at=now,
            execution_status="stopped",
            parent_action=None,
            attempt_closed=True,
        )
        prior = self.managed_record(
            attempt=1,
            updated_at=stale,
            execution_status="stopped",
            business_result="failed",
            parent_action="decide_disposition",
        )
        self.write_task(current, prior)
        state = self.store.read(self.session_id)

        action_required = governance._action_required_records(state)
        recent = governance._recent_activity_records(state, now=now)

        self.assertEqual(
            [(item["task_id"], item["attempt"]) for item in action_required],
            [("sg-wp06-task", 1)],
        )
        self.assertEqual(
            [(item["task_id"], item["attempt"]) for item in recent],
            [("sg-wp06-task", 2)],
        )

    def test_machine_semantics_anchor_wait_and_derived_views(self):
        semantics = governance.SEMANTIC_RULES
        self.assertEqual(semantics["wait_timeout_ms"], 1_200_000)
        self.assertEqual(semantics["stop_read_attempts"], 3)
        self.assertEqual(
            semantics["derived_views"]["action_required"],
            {
                "includes_prior_attempts": True,
                "uses_recent_activity_window": False,
                "primary_rule": "unclosed_parent_action_or_authoritative_call",
            },
        )
        self.assertFalse(
            semantics["derived_views"]["recent_activity"]["authoritative_lifecycle_state"]
        )

    def test_action_required_includes_authoritative_calls_without_parent_action(self):
        now = 2_000_000
        records = [
            self.managed_record(task_id="running", updated_at=now, parent_action=None),
            self.managed_record(
                task_id="spawn-claimed",
                updated_at=now,
                execution_status="not_started",
                parent_action=None,
                spawn_tool_use_id="spawn-tool",
                spawn_observation=None,
            ),
            self.managed_record(
                task_id="lifecycle-claimed",
                updated_at=now,
                execution_status="stopped",
                parent_action=None,
                pending_action={
                    "operation_type": "platform_recovery",
                    "phase": "claimed",
                    "target": "agent-1",
                    "tool_use_id": "followup-tool",
                },
            ),
            self.managed_record(
                task_id="identity-unknown",
                updated_at=now,
                execution_status="not_started",
                identity_status="unconfirmed",
                spawn_observation="unknown",
                parent_action=None,
            ),
        ]
        for record in records:
            self.write_task(record)

        required = governance._action_required_records(self.store.read(self.session_id))

        self.assertEqual(
            {item["task_id"] for item in required},
            {"running", "spawn-claimed", "lifecycle-claimed", "identity-unknown"},
        )

    def test_stop_allows_reportable_action_required_but_blocks_running(self):
        reportable = self.managed_record(
            task_id="complete-pending",
            execution_status="stopped",
            business_result="complete",
            result_protocol_status="valid",
            result_storage_status="available",
            acceptance_status="pending",
            parent_action="accept_result",
        )
        self.write_task(reportable)
        allowed = governance.handle(
            {"session_id": self.session_id, "hook_event_name": "Stop"},
            self.store,
        )
        self.assertEqual(allowed, {"continue": True})

        running = self.managed_record(task_id="still-running")
        self.write_task(running)
        blocked = governance.handle(
            {"session_id": self.session_id, "hook_event_name": "Stop"},
            self.store,
        )
        self.assertEqual(blocked["decision"], "block")
        self.assertIn("still-running", blocked["reason"])

    def test_stop_reads_at_most_three_times_and_recovers_from_transient_error(self):
        state = {"tasks": {}, "agents": {}, "tombstones": {}}

        class FlakyStore:
            last_warning = None

            def __init__(self):
                self.calls = 0

            def read(self, _session_id):
                self.calls += 1
                if self.calls < 3:
                    raise OSError("transient read failure")
                return state

        store = FlakyStore()
        sleeps = []
        result = governance._handle_stop(
            {"session_id": self.session_id, "hook_event_name": "Stop"},
            store,
            sleeper=lambda delay: sleeps.append(delay),
        )

        self.assertEqual(result, {"continue": True})
        self.assertEqual(store.calls, 3)
        self.assertEqual(len(sleeps), 2)

    def test_stop_blocks_after_three_read_failures_without_persisting(self):
        class FailingStore:
            last_warning = None

            def __init__(self):
                self.calls = 0

            def read(self, _session_id):
                self.calls += 1
                raise OSError("state unavailable")

        store = FailingStore()
        result = governance._handle_stop(
            {"session_id": self.session_id, "hook_event_name": "Stop"},
            store,
            sleeper=lambda _delay: None,
        )

        self.assertEqual(store.calls, 3)
        self.assertEqual(result["decision"], "block")
        self.assertIn("需要用户决策", result["reason"])
        self.assertIn("强制结束", result["reason"])

    def test_session_start_prioritizes_action_required_then_recent_activity(self):
        now = governance._now()
        recent = self.managed_record(
            task_id="recent-closed",
            updated_at=now,
            execution_status="stopped",
            parent_action=None,
            attempt_closed=True,
        )
        required = self.managed_record(
            task_id="stale-required",
            updated_at=now - governance.RETENTION_SECONDS["recent_activity"] - 10,
            execution_status="stopped",
            business_result="failed",
            parent_action="decide_disposition",
        )
        self.write_task(recent)
        self.write_task(required)

        context = governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "SessionStart",
                "source": "compact",
            },
            self.store,
        )["hookSpecificOutput"]["additionalContext"]

        self.assertLess(context.index("需要处理"), context.index("最近活动"))
        self.assertIn("任务 ID：stale-required｜attempt：1", context)
        self.assertIn("任务 ID：recent-closed｜attempt：1", context)
        self.assertIn("parent_action：decide_disposition", context)
        self.assertIn("不要因 compact/resume 重复创建", context)

    def test_session_start_reuses_five_and_twenty_minute_pending_reconcile(self):
        now = governance._now()
        expired = self.managed_record(
            task_id="expired-prepared-action",
            execution_status="stopped",
            parent_action=None,
            pending_action={
                "operation_type": "normal_message",
                "phase": "prepared",
                "target": "agent-1",
                "created_at": now - 301,
                "expires_at": now - 1,
            },
        )
        claimed = self.managed_record(
            task_id="claimed-action",
            execution_status="stopped",
            platform_observation="error",
            parent_action="recover",
            pending_action={
                "operation_type": "platform_recovery",
                "phase": "claimed",
                "target": "agent-1",
                "tool_use_id": "followup-tool",
                "claimed_at": now - governance.RETENTION_SECONDS["claimed_reconcile"] - 1,
                "reason": "恢复平台错误",
            },
        )
        self.write_task(expired)
        self.write_task(claimed)

        governance.handle(
            {"session_id": self.session_id, "hook_event_name": "SessionStart", "source": "resume"},
            self.store,
        )

        state = self.store.read(self.session_id)
        self.assertNotIn("pending_action", state["tasks"]["expired-prepared-action"])
        claimed_record = state["tasks"]["claimed-action"]
        self.assertNotIn("pending_action", claimed_record)
        self.assertEqual(
            claimed_record["last_lifecycle_operation"]["call_observation"],
            "unknown",
        )
        self.assertEqual(claimed_record["parent_action"], "reconcile")

    def test_session_start_read_failure_is_explicitly_degraded(self):
        class FailingStore:
            last_warning = None

            def read(self, _session_id):
                raise OSError("corrupt state")

        result = governance._handle_session_start(
            {"session_id": self.session_id, "source": "resume"},
            FailingStore(),
        )

        self.assertIn("degraded", result["systemMessage"])
        self.assertIn("无法确认", result["systemMessage"])

    def test_session_end_preserves_tombstone_then_deletes_json_but_not_lock(self):
        now = governance._now()

        def add_tombstone(state):
            state["tombstones"]["closed-task:1"] = {
                "task_id": "closed-task",
                "attempt": 1,
                "close_reason": "close_task:test",
                "closed_at": now,
            }

        self.store.update(self.session_id, add_tombstone)
        state_path, lock_path = self.store._paths(self.session_id)
        preserved = governance.handle(
            {"session_id": self.session_id, "hook_event_name": "SessionEnd"},
            self.store,
        )
        self.assertIn("tombstone", preserved["systemMessage"])
        self.assertTrue(state_path.exists())
        self.assertTrue(lock_path.exists())

        self.store.update(
            self.session_id,
            lambda state: state["tombstones"].clear(),
        )
        deleted = governance.handle(
            {"session_id": self.session_id, "hook_event_name": "SessionEnd"},
            self.store,
        )
        self.assertEqual(deleted, {"continue": True})
        self.assertFalse(state_path.exists())
        self.assertTrue(lock_path.exists())

    def test_session_start_cleans_only_exact_expired_tombstone_result(self):
        now = governance._now()
        task_id = "cleanup-task"
        results_root = self.root / "results"
        results_root.mkdir(mode=0o700)
        first = governance.result_file_path(results_root, task_id, 1)
        second = governance.result_file_path(results_root, task_id, 2)
        for attempt, path in ((1, first), (2, second)):
            path.write_bytes(governance._canonical_result_bytes(self.formal_result(task_id, attempt)))
            os.chmod(path, 0o600)

        def add_tombstone(state):
            state["tombstones"][f"{task_id}:1"] = {
                "task_id": task_id,
                "attempt": 1,
                "close_reason": "close_task:test",
                "closed_at": now - governance.RETENTION_SECONDS["tombstone"] - 1,
            }

        self.store.update(self.session_id, add_tombstone)
        governance.handle(
            {"session_id": self.session_id, "hook_event_name": "SessionStart", "source": "resume"},
            self.store,
        )

        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertNotIn(
            f"{task_id}:1",
            self.store.read(self.session_id)["tombstones"],
        )

    def test_result_cleanup_failure_keeps_tombstone(self):
        now = governance._now()
        task_id = "unsafe-result"
        results_root = self.root / "results"
        results_root.mkdir(mode=0o700)
        path = governance.result_file_path(results_root, task_id, 1)
        path.write_text("{}", encoding="utf-8")
        os.chmod(path, 0o600)

        self.store.update(
            self.session_id,
            lambda state: state["tombstones"].update({
                f"{task_id}:1": {
                    "task_id": task_id,
                    "attempt": 1,
                    "close_reason": "close_task:test",
                    "closed_at": now - governance.RETENTION_SECONDS["tombstone"] - 1,
                }
            }),
        )

        result = governance.handle(
            {"session_id": self.session_id, "hook_event_name": "SessionStart", "source": "resume"},
            self.store,
        )

        self.assertIn("degraded", result["systemMessage"])
        self.assertTrue(path.exists())
        self.assertIn(f"{task_id}:1", self.store.read(self.session_id)["tombstones"])

    def selected_duplicate_state(self, *, interrupt_observation=None):
        selected = self.managed_record(
            attempt=2,
            target="agent-selected",
            execution_status="stopped",
            business_result="complete",
            result_protocol_status="valid",
            result_storage_status="available",
            acceptance_status="pending",
            duplicate_execution=True,
            parent_action="resolve_duplicate",
        )
        pending = None
        if interrupt_observation is None:
            pending = {
                "operation_type": "interrupt",
                "phase": "claimed",
                "target": "agent-unselected",
                "tool_use_id": "interrupt-tool",
                "claimed_at": 150,
                "reason": "关闭未选 attempt",
            }
        prior = self.managed_record(
            attempt=1,
            target="agent-unselected",
            duplicate_not_selected=True,
            parent_action="resolve_duplicate",
            pending_action=pending,
            last_lifecycle_operation=(
                {
                    "operation_type": "interrupt",
                    "target": "agent-unselected",
                    "tool_use_id": "interrupt-tool",
                    "call_observation": interrupt_observation,
                    "completed_at": 160,
                }
                if interrupt_observation is not None
                else None
            ),
        )
        if pending is None:
            prior.pop("pending_action", None)
        if interrupt_observation is None:
            prior.pop("last_lifecycle_operation", None)
        self.write_task(selected, prior)

    def test_selected_duplicate_interrupt_success_closes_only_unselected_attempt(self):
        self.selected_duplicate_state()
        governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "PostToolUse",
                "tool_name": "collaboration.interrupt_agent",
                "tool_use_id": "interrupt-tool",
                "tool_response": {"status": "interrupted"},
                "now": 200,
            },
            self.store,
        )

        state = self.store.read(self.session_id)
        selected = state["tasks"]["sg-wp06-task"]
        unselected = selected["prior_attempts"]["1"]
        self.assertTrue(unselected["attempt_closed"])
        self.assertEqual(unselected["attempt_close_reason"], "select_attempt_interrupt_success")
        self.assertFalse(selected.get("duplicate_execution", False))
        self.assertEqual(selected["parent_action"], "accept_result")
        self.assertNotIn("agent-unselected", state["agents"])
        self.assertIn("sg-wp06-task:1", state["tombstones"])
        self.assertFalse(selected.get("attempt_closed", False))

    def test_apply_select_then_explicit_prepare_interrupt_uses_saved_close_intent(self):
        current = self.managed_record(
            attempt=1,
            target="agent-unselected",
            duplicate_execution=True,
            parent_action="resolve_duplicate",
        )
        selected = self.managed_record(
            attempt=2,
            target="agent-selected",
            execution_status="stopped",
            business_result="complete",
            result_protocol_status="valid",
            result_storage_status="available",
            acceptance_status="pending",
            parent_action="accept_result",
        )
        self.write_task(current, selected)

        disposition = governance.apply_parent_disposition(
            {
                "task_id": "sg-wp06-task",
                "attempt": 2,
                "action": "select_attempt",
                "reason": "保留已有完整结果",
            },
            self.session_id,
            state_store=self.store,
            now=180,
        )
        self.assertEqual(disposition["interrupt_targets"], ["agent-unselected"])

        prepared = governance.prepare_interrupt(
            {
                "target": "agent-unselected",
                "purpose": "关闭未选重复执行",
                "reason": "父 Agent 已选择 attempt 2",
                "content": "中断未选 attempt 1。",
                "expected_result": "返回明确中断观察",
            },
            self.session_id,
            state_store=self.store,
            now=190,
        )
        claimed = governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "PreToolUse",
                "tool_name": "collaboration.interrupt_agent",
                "tool_use_id": "interrupt-selected-flow",
                "tool_input": prepared["native_args"],
                "now": 191,
            },
            self.store,
        )
        self.assertEqual(
            claimed["hookSpecificOutput"]["permissionDecision"],
            "allow",
            claimed,
        )
        observed = governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "PostToolUse",
                "tool_name": "collaboration.interrupt_agent",
                "tool_use_id": "interrupt-selected-flow",
                "tool_response": {"status": "interrupted"},
                "now": 200,
            },
            self.store,
        )
        self.assertIsNone(observed)

        state = self.store.read(self.session_id)
        current_selected = state["tasks"]["sg-wp06-task"]
        self.assertEqual(current_selected["attempt"], 2)
        self.assertTrue(
            current_selected["prior_attempts"]["1"].get("attempt_closed"),
            state,
        )
        self.assertEqual(current_selected["parent_action"], "accept_result")
        self.assertFalse(current_selected.get("duplicate_execution", False))

    def assert_selected_duplicate_interrupt_remains_unclosed(self, response, expected_action):
        self.selected_duplicate_state()
        governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "PostToolUse",
                "tool_name": "collaboration.interrupt_agent",
                "tool_use_id": "interrupt-tool",
                "tool_response": response,
                "now": 200,
            },
            self.store,
        )
        selected = self.store.read(self.session_id)["tasks"]["sg-wp06-task"]
        unselected = selected["prior_attempts"]["1"]
        self.assertFalse(unselected.get("attempt_closed", False))
        self.assertTrue(selected["duplicate_execution"])
        self.assertEqual(unselected["parent_action"], expected_action)

    def test_selected_duplicate_interrupt_failed_remains_unclosed(self):
        self.assert_selected_duplicate_interrupt_remains_unclosed(
            {"status": "failed"},
            "ask_user",
        )

    def test_selected_duplicate_interrupt_unknown_remains_unclosed(self):
        self.assert_selected_duplicate_interrupt_remains_unclosed(
            {"status": "unexpected"},
            "reconcile",
        )

    def test_list_agents_stopped_closes_unknown_unselected_attempt(self):
        self.selected_duplicate_state(interrupt_observation="unknown")
        governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "PostToolUse",
                "tool_name": "collaboration.list_agents",
                "tool_response": {
                    "agents": [
                        {
                            "agent_name": "agent-unselected",
                            "agent_status": {"stopped": True},
                        }
                    ]
                },
                "now": 220,
            },
            self.store,
        )

        state = self.store.read(self.session_id)
        selected = state["tasks"]["sg-wp06-task"]
        unselected = selected["prior_attempts"]["1"]
        self.assertTrue(unselected["attempt_closed"])
        self.assertEqual(unselected["attempt_close_reason"], "select_attempt_platform_stopped")
        self.assertFalse(selected.get("duplicate_execution", False))
        self.assertEqual(selected["parent_action"], "accept_result")

    def test_skill_and_runtime_boundaries_publish_wp06_wait_contract(self):
        skill = (ROOT / "skills/subagent-governance/SKILL.md").read_text(encoding="utf-8")
        boundaries = (
            ROOT / "skills/subagent-governance/references/runtime-boundaries.md"
        ).read_text(encoding="utf-8")

        for expected in (
            "`timeout_ms: 1200000`",
            "只有 20 分钟正常等待超时才做一次目标巡检",
            "`action_required` 与 `recent_activity` 是独立派生视图",
            "StateStore 三次",
            "稳定 `.lock` 永不删除",
            "result 删除失败时 tombstone 保留",
        ):
            self.assertIn(expected, skill)
        self.assertIn("状态含糊或 list 失败时不得重建或猜测", boundaries)
        self.assertIn("正式 result 只按确定性地址", boundaries)


if __name__ == "__main__":
    unittest.main()
