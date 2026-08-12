#!/usr/bin/env python3

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_dispatch", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class DispatchIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = governance.StateStore(self.root / "sessions")

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def contract(**overrides):
        value = {
            "semantic_name": "Payment Review",
            "requested_mode": "auto",
            "task_features": {
                "risk": "medium",
                "read_only": False,
                "writes_files": True,
                "destructive": False,
                "production": False,
                "concurrent_write": False,
                "multi_stage_acceptance": False,
            },
            "objective": "实现支付状态检查并验证结果",
            "background": "WP-01 和 WP-02 已完成。",
            "work_scope": ["修改当前开发仓库内的派发路径"],
            "forbidden_scope": [],
            "completion_conditions": ["确定性派发和身份绑定测试通过"],
            "evidence_requirements": ["运行定向测试"],
            "relevant_files": ["scripts/subagent_governance.py"],
            "current_state": None,
            "model": None,
            "reasoning_effort": None,
            "context_strategy": "isolated",
            "context_turns": None,
            "context_reason": None,
        }
        value.update(overrides)
        return value

    def prepared_store(self):
        return governance.PreparedContractStore(self.root / "prepared")

    def prepare(self, **contract_overrides):
        return governance.prepare_dispatch(
            self.contract(**contract_overrides),
            "session-1",
            state_store=self.store,
            prepared_store=self.prepared_store(),
            task_id_factory=lambda: "sg-task-0001",
        )

    @staticmethod
    def pre_payload(prepared, **spawn_overrides):
        spawn_args = dict(prepared["spawn_args"])
        spawn_args.update(spawn_overrides)
        return {
            "session_id": "session-1",
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "spawn-call-1",
            "tool_input": spawn_args,
        }

    def test_generator_resolves_structured_auto_and_projects_native_arguments(self):
        prepared = governance.PreparedContractStore(self.root / "prepared")
        result = governance.prepare_dispatch(
            self.contract(),
            "session-1",
            state_store=self.store,
            prepared_store=prepared,
            task_id_factory=lambda: "sg-task-0001",
        )

        self.assertEqual(result["contract"]["resolved_mode"], "standard")
        self.assertEqual(result["contract"]["resolution_reason"], "auto_standard")
        self.assertEqual(result["contract"]["semantic_name"], "payment_review")
        self.assertEqual(result["spawn_args"]["fork_turns"], "none")
        self.assertNotIn("model", result["spawn_args"])
        self.assertNotIn("reasoning_effort", result["spawn_args"])
        self.assertIn("继承主 Agent（未显式覆盖）", result["user_message"])
        self.assertRegex(
            result["task_name"],
            r"^sg_standard_payment_review_t_[a-f0-9]{12}$",
        )

    def test_installed_cache_generator_and_hook_share_plugin_data_root_without_env(self):
        codex_root = self.root / ".codex"
        installed_script = (
            codex_root
            / "plugins/cache/personal/subagent-governance/0.4.0-rc.12/scripts"
            / "subagent_governance.py"
        )
        expected_root = (
            codex_root
            / "plugins/data/subagent-governance-personal/state-v1"
        ).resolve()
        session_id = "installed-session"

        with (
            mock.patch.object(governance, "__file__", str(installed_script)),
            mock.patch.dict(
                governance.os.environ,
                {"SUBAGENT_GOVERNANCE_DATA": "", "PLUGIN_DATA": ""},
            ),
        ):
            self.assertEqual(governance._data_root_path(), expected_root)
            prepared = governance.prepare_dispatch(
                self.contract(),
                session_id,
                task_id_factory=lambda: "sg-installed-task",
            )
            payload = self.pre_payload(prepared)
            payload["session_id"] = session_id
            result = governance.handle(payload)["hookSpecificOutput"]

        self.assertEqual(result["permissionDecision"], "allow")
        persisted = governance.PreparedContractStore(expected_root / "prepared").read(
            session_id,
            prepared["task_ref"],
        )
        state = governance.StateStore(expected_root / "sessions").read(session_id)
        self.assertTrue(persisted["consumed"])
        self.assertEqual(persisted["tool_use_id"], "spawn-call-1")
        self.assertEqual(
            state["tasks"][prepared["task_id"]]["spawn_tool_use_id"],
            "spawn-call-1",
        )

    def test_generator_maps_all_context_strategies_and_optional_native_overrides(self):
        cases = (
            ({"context_strategy": "isolated", "context_turns": None, "context_reason": None}, "none"),
            (
                {"context_strategy": "limited", "context_turns": 3, "context_reason": "依赖最近三轮裁决"},
                "3",
            ),
            (
                {"context_strategy": "full", "context_turns": None, "context_reason": "存在未落盘状态"},
                "all",
            ),
        )
        for index, (overrides, expected) in enumerate(cases):
            with self.subTest(strategy=overrides["context_strategy"]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result = governance.prepare_dispatch(
                    self.contract(
                        **overrides,
                        model="gpt-5.6-terra",
                        reasoning_effort="high",
                    ),
                    f"session-{index}",
                    state_store=governance.StateStore(root / "sessions"),
                    prepared_store=governance.PreparedContractStore(root / "prepared"),
                    task_id_factory=lambda index=index: f"sg-task-{index}",
                )
                self.assertEqual(result["spawn_args"]["fork_turns"], expected)
                self.assertEqual(result["spawn_args"]["model"], "gpt-5.6-terra")
                self.assertEqual(result["spawn_args"]["reasoning_effort"], "high")

    def test_task_ref_collision_is_bounded_and_task_name_never_exceeds_limit(self):
        task_id = "sg-task-collision"
        all_candidates = {
            governance.derive_task_ref(task_id, 1, length)
            for length in governance.TASK_REF_LENGTHS
        }
        self.assertIsNone(governance.select_task_ref(task_id, 1, all_candidates))
        occupied = {
            governance.derive_task_ref(task_id, 1, length)
            for length in governance.TASK_REF_LENGTHS[:-1]
        }
        self.assertEqual(
            len(governance.select_task_ref(task_id, 1, occupied)),
            governance.TASK_REF_LENGTHS[-1],
        )
        task_name = governance.build_task_name(
            "strict",
            "very_long_semantic_name_" * 10,
            "a" * 32,
        )
        self.assertLessEqual(len(task_name), governance.TASK_NAME_MAX_LENGTH)
        self.assertIsNotNone(governance.parse_task_name(task_name))

    def test_prepare_dispatch_regenerates_task_id_once_after_32_character_collision(self):
        ids = iter(("sg-first", "sg-second"))
        with mock.patch.object(
            governance,
            "select_task_ref",
            side_effect=(None, "0123456789ab"),
        ) as selector:
            result = governance.prepare_dispatch(
                self.contract(),
                "session-1",
                state_store=self.store,
                prepared_store=self.prepared_store(),
                task_id_factory=lambda: next(ids),
            )
        self.assertEqual(result["task_id"], "sg-second")
        self.assertEqual(selector.call_count, 2)

    def test_prepare_dispatch_rejects_when_second_task_id_also_collides(self):
        ids = iter(("sg-first", "sg-second"))
        with mock.patch.object(governance, "select_task_ref", return_value=None):
            with self.assertRaisesRegex(governance.DispatchPreparationError, "两个新 task_id"):
                governance.prepare_dispatch(
                    self.contract(),
                    "session-1",
                    state_store=self.store,
                    prepared_store=self.prepared_store(),
                    task_id_factory=lambda: next(ids),
                )

    def test_prepared_contract_is_atomic_readable_and_contains_no_prepared_ref(self):
        prepared = self.prepare()
        record = self.prepared_store().read("session-1", prepared["task_ref"])
        self.assertEqual(record["task_id"], prepared["task_id"])
        self.assertEqual(record["attempt"], 1)
        self.assertFalse(record["consumed"])
        self.assertNotIn("prepared_ref", record)

    def test_prepared_contract_readback_failure_is_not_reported_as_success(self):
        prepared_store = self.prepared_store()
        original_read = prepared_store._read_path
        calls = 0

        def fail_readback(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise governance.PreparedContractValidationError("simulated readback failure")
            return original_read(*args, **kwargs)

        with mock.patch.object(prepared_store, "_read_path", side_effect=fail_readback):
            with self.assertRaises(governance.DispatchPreparationError):
                governance.prepare_dispatch(
                    self.contract(),
                    "session-1",
                    state_store=self.store,
                    prepared_store=prepared_store,
                    task_id_factory=lambda: "sg-task-readback",
                )
        self.assertEqual(self.store.read("session-1")["tasks"], {})

    def test_state_store_gate_failure_removes_prepared_contract_and_rejects(self):
        prepared_store = self.prepared_store()
        with mock.patch.object(
            self.store,
            "compare_and_set",
            side_effect=governance.StateWriteError("simulated state failure"),
        ):
            with self.assertRaises(governance.DispatchPreparationError):
                governance.prepare_dispatch(
                    self.contract(),
                    "session-1",
                    state_store=self.store,
                    prepared_store=prepared_store,
                    task_id_factory=lambda: "sg-task-gate",
                )
        self.assertEqual(prepared_store.list_records("session-1"), [])

    def test_unconsumed_prepared_contract_expires_with_initial_attempt(self):
        prepared = governance.prepare_dispatch(
            self.contract(),
            "session-1",
            state_store=self.store,
            prepared_store=self.prepared_store(),
            task_id_factory=lambda: "sg-task-expired",
            now=1_000,
        )
        result = governance.reconcile_prepared_dispatches(
            "session-1",
            state_store=self.store,
            prepared_store=self.prepared_store(),
            now=1_301,
        )
        self.assertEqual(result, {"expired": 1, "reconciled": 0})
        self.assertNotIn(prepared["task_id"], self.store.read("session-1")["tasks"])
        self.assertEqual(self.prepared_store().list_records("session-1"), [])

    def test_pre_tool_use_consumes_prepared_contract_once_and_checks_native_parameters(self):
        prepared = self.prepare()
        mismatch = governance.handle(self.pre_payload(prepared, fork_turns="all"), self.store)
        self.assertEqual(mismatch["hookSpecificOutput"]["permissionDecision"], "deny")
        record = self.prepared_store().read("session-1", prepared["task_ref"])
        self.assertFalse(record["consumed"])

        opaque_transport = governance.handle(
            self.pre_payload(prepared, message="gAAAAA" + "x" * 180),
            self.store,
        )
        self.assertEqual(
            opaque_transport["hookSpecificOutput"]["permissionDecision"],
            "allow",
        )
        record = self.prepared_store().read("session-1", prepared["task_ref"])
        self.assertTrue(record["consumed"])
        self.assertEqual(record["tool_use_id"], "spawn-call-1")
        state_record = self.store.read("session-1")["tasks"][prepared["task_id"]]
        self.assertEqual(state_record["spawn_tool_use_id"], "spawn-call-1")

        repeated = governance.handle(self.pre_payload(prepared), self.store)
        self.assertEqual(repeated["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_consumed_contract_is_not_deleted_by_five_minute_expiry(self):
        prepared = self.prepare()
        governance.handle(self.pre_payload(prepared), self.store)
        claimed_at = self.prepared_store().read("session-1", prepared["task_ref"])["claimed_at"]
        result = governance.reconcile_prepared_dispatches(
            "session-1",
            state_store=self.store,
            prepared_store=self.prepared_store(),
            now=claimed_at + 301,
        )
        self.assertEqual(result, {"expired": 0, "reconciled": 0})
        self.assertTrue(self.prepared_store().read("session-1", prepared["task_ref"])["consumed"])

    def test_missing_post_tool_use_becomes_unknown_only_after_twenty_minutes(self):
        prepared = self.prepare()
        governance.handle(self.pre_payload(prepared), self.store)
        claimed_at = self.prepared_store().read("session-1", prepared["task_ref"])["claimed_at"]
        early = governance.reconcile_prepared_dispatches(
            "session-1",
            state_store=self.store,
            prepared_store=self.prepared_store(),
            now=claimed_at + 1_199,
        )
        self.assertEqual(early["reconciled"], 0)
        record = self.store.read("session-1")["tasks"][prepared["task_id"]]
        self.assertIsNone(record["spawn_observation"])
        self.assertIsNone(record["parent_action"])

        late = governance.reconcile_prepared_dispatches(
            "session-1",
            state_store=self.store,
            prepared_store=self.prepared_store(),
            now=claimed_at + 1_200,
        )
        self.assertEqual(late["reconciled"], 1)
        record = self.store.read("session-1")["tasks"][prepared["task_id"]]
        self.assertEqual(record["spawn_observation"], "unknown")
        self.assertEqual(record["execution_status"], "not_started")
        self.assertEqual(record["identity_status"], "unconfirmed")
        self.assertEqual(record["parent_action"], "reconcile")
        self.assertTrue(self.prepared_store().read("session-1", prepared["task_ref"])["consumed"])

    def test_post_tool_spawn_success_binds_exact_identity_and_deletes_contract(self):
        prepared = self.prepare()
        governance.handle(self.pre_payload(prepared), self.store)
        result = governance.handle(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-1",
                "tool_response": {
                    "agent_id": "agent-1",
                    "canonical_task_path": "/root/sg_standard_payment_review",
                },
            },
            self.store,
        )
        self.assertIsNone(result)
        state = self.store.read("session-1")
        record = state["tasks"][prepared["task_id"]]
        self.assertEqual(record["spawn_observation"], "success")
        self.assertEqual(record["identity_status"], "confirmed")
        self.assertEqual(record["execution_status"], "running")
        self.assertEqual(record["parent_action"], "wait")
        expected_mapping = {"task_id": prepared["task_id"], "attempt": 1}
        self.assertEqual(state["agents"]["agent-1"], expected_mapping)
        self.assertEqual(state["agents"]["/root/sg_standard_payment_review"], expected_mapping)
        self.assertEqual(self.prepared_store().list_records("session-1"), [])

    def test_post_tool_success_without_identity_stays_not_started_and_reconcile(self):
        prepared = self.prepare()
        governance.handle(self.pre_payload(prepared), self.store)
        governance.handle(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-1",
                "tool_response": {"status": "ok"},
            },
            self.store,
        )
        record = self.store.read("session-1")["tasks"][prepared["task_id"]]
        self.assertEqual(record["spawn_observation"], "success")
        self.assertEqual(record["identity_status"], "unconfirmed")
        self.assertEqual(record["execution_status"], "not_started")
        self.assertEqual(record["parent_action"], "reconcile")

    def test_post_tool_failed_and_unknown_have_distinct_transitions(self):
        failed = self.prepare()
        governance.handle(self.pre_payload(failed), self.store)
        governance.handle(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-1",
                "tool_response": {"isError": True},
            },
            self.store,
        )
        failed_record = self.store.read("session-1")["tasks"][failed["task_id"]]
        self.assertEqual(failed_record["spawn_observation"], "failed")
        self.assertEqual(failed_record["parent_action"], "retry_spawn")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = governance.StateStore(root / "sessions")
            prepared_store = governance.PreparedContractStore(root / "prepared")
            unknown = governance.prepare_dispatch(
                self.contract(),
                "session-unknown",
                state_store=store,
                prepared_store=prepared_store,
                task_id_factory=lambda: "sg-task-unknown",
            )
            payload = self.pre_payload(unknown)
            payload["session_id"] = "session-unknown"
            governance.handle(payload, store)
            governance.handle(
                {
                    "session_id": "session-unknown",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "spawn_agent",
                    "tool_use_id": "spawn-call-1",
                    "tool_response": {"wrapper": {"agent_id": "must-not-bind"}},
                },
                store,
            )
            record = store.read("session-unknown")["tasks"][unknown["task_id"]]
            self.assertEqual(record["spawn_observation"], "unknown")
            self.assertEqual(record["parent_action"], "reconcile")
            self.assertEqual(store.read("session-unknown")["agents"], {})

    def test_spawn_retry_counts_are_claimed_before_call_and_bounded(self):
        prepared = self.prepare()
        governance.handle(self.pre_payload(prepared), self.store)
        governance.handle(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-1",
                "tool_response": {"isError": True},
            },
            self.store,
        )

        retry = governance.prepare_spawn_retry(
            self.contract(),
            "session-1",
            prepared["task_id"],
            state_store=self.store,
            prepared_store=self.prepared_store(),
        )
        retry_payload = self.pre_payload(retry)
        retry_payload["tool_use_id"] = "spawn-call-2"
        allowed = governance.handle(retry_payload, self.store)
        self.assertEqual(allowed["hookSpecificOutput"]["permissionDecision"], "allow")
        claimed = self.store.read("session-1")["tasks"][prepared["task_id"]]
        self.assertEqual(claimed["spawn_retry_count"], 1)
        self.assertIsNone(claimed["spawn_observation"])

        governance.handle(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-2",
                "tool_response": {"status": "failed"},
            },
            self.store,
        )
        failed_once = self.store.read("session-1")["tasks"][prepared["task_id"]]
        self.assertEqual(failed_once["spawn_retry_count"], 1)
        self.assertEqual(failed_once["parent_action"], "ask_user")

        with self.assertRaisesRegex(governance.DispatchPreparationError, "明确授权"):
            governance.prepare_spawn_retry(
                self.contract(),
                "session-1",
                prepared["task_id"],
                state_store=self.store,
                prepared_store=self.prepared_store(),
            )

        final_retry = governance.prepare_spawn_retry(
            self.contract(),
            "session-1",
            prepared["task_id"],
            authorized=True,
            state_store=self.store,
            prepared_store=self.prepared_store(),
        )
        final_payload = self.pre_payload(final_retry)
        final_payload["tool_use_id"] = "spawn-call-3"
        governance.handle(final_payload, self.store)
        claimed_final = self.store.read("session-1")["tasks"][prepared["task_id"]]
        self.assertEqual(claimed_final["spawn_retry_count"], 2)

        governance.handle(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-3",
                "tool_response": {"is_error": True},
            },
            self.store,
        )
        exhausted = self.store.read("session-1")["tasks"][prepared["task_id"]]
        self.assertEqual(exhausted["execution_status"], "stopped")
        self.assertEqual(exhausted["parent_action"], "decide_disposition")
        self.assertEqual(exhausted["spawn_close_reason"], "spawn_retry_exhausted")
        tombstone = self.store.read("session-1")["tombstones"][f"{prepared['task_id']}:1"]
        self.assertEqual(tombstone["close_reason"], "spawn_retry_exhausted")
        self.assertEqual(tombstone["task_ref"], prepared["task_ref"])
        with self.assertRaisesRegex(governance.DispatchPreparationError, "已经耗尽"):
            governance.prepare_spawn_retry(
                self.contract(),
                "session-1",
                prepared["task_id"],
                authorized=True,
                state_store=self.store,
                prepared_store=self.prepared_store(),
            )

    def test_unknown_retry_cannot_be_reused_or_turned_into_failed(self):
        prepared = self.prepare()
        governance.handle(self.pre_payload(prepared), self.store)
        governance.handle(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-1",
                "tool_response": {"isError": True},
            },
            self.store,
        )
        retry = governance.prepare_spawn_retry(
            self.contract(),
            "session-1",
            prepared["task_id"],
            state_store=self.store,
            prepared_store=self.prepared_store(),
        )
        payload = self.pre_payload(retry)
        payload["tool_use_id"] = "spawn-call-2"
        governance.handle(payload, self.store)
        governance.handle(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-2",
                "tool_response": {"unexpected": "shape"},
            },
            self.store,
        )

        record = self.store.read("session-1")["tasks"][prepared["task_id"]]
        self.assertEqual(record["spawn_observation"], "unknown")
        self.assertEqual(record["spawn_retry_count"], 1)
        self.assertEqual(record["parent_action"], "reconcile")
        with self.assertRaisesRegex(governance.DispatchPreparationError, "明确 failed"):
            governance.prepare_spawn_retry(
                self.contract(),
                "session-1",
                prepared["task_id"],
                authorized=True,
                state_store=self.store,
                prepared_store=self.prepared_store(),
            )

    def test_late_subagent_start_binds_by_task_ref_after_unknown(self):
        prepared = self.prepare()
        governance.handle(self.pre_payload(prepared), self.store)
        governance.handle(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-1",
                "tool_response": {"unexpected": True},
            },
            self.store,
        )
        result = governance.handle(
            {
                "session_id": "session-1",
                "hook_event_name": "SubagentStart",
                "agent_id": "late-agent",
                "task_name": prepared["task_name"],
            },
            self.store,
        )
        record = self.store.read("session-1")["tasks"][prepared["task_id"]]
        self.assertEqual(record["identity_status"], "confirmed")
        self.assertEqual(record["execution_status"], "running")
        self.assertEqual(record["parent_action"], "wait")
        self.assertIn("治理状态：running", result["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.prepared_store().list_records("session-1"), [])

    def test_identity_confirmation_contract_delete_failure_only_warns(self):
        prepared = self.prepare()
        governance.handle(self.pre_payload(prepared), self.store)
        with mock.patch.object(
            governance.PreparedContractStore,
            "delete",
            side_effect=governance.PreparedContractWriteError("simulated delete failure"),
        ):
            result = governance.handle(
                {
                    "session_id": "session-1",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "spawn_agent",
                    "tool_use_id": "spawn-call-1",
                    "tool_response": {"agent_id": "agent-delete-warning"},
                },
                self.store,
            )
        record = self.store.read("session-1")["tasks"][prepared["task_id"]]
        self.assertEqual(record["identity_status"], "confirmed")
        self.assertEqual(record["spawn_observation"], "success")
        self.assertIn("收缩失败", result["systemMessage"])

    def test_unmanaged_spawn_is_allowed_without_creating_state(self):
        payload = {
            "session_id": "session-1",
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "unmanaged-call",
            "tool_input": {
                "task_name": "plain_native_task",
                "message": "执行原生未治理任务",
                "fork_turns": "none",
            },
        }

        result = governance.handle(payload, self.store)

        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertEqual(result["hookSpecificOutput"]["updatedInput"], payload["tool_input"])
        self.assertEqual(self.store.read("session-1")["tasks"], {})

    def test_old_governed_name_is_rejected_instead_of_reading_business_body(self):
        payload = {
            "session_id": "session-1",
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "legacy-call",
            "tool_input": {
                "task_name": "sg_standard_legacy_task",
                "message": "【目标】正文不再是治理契约来源",
                "fork_turns": "none",
            },
        }

        result = governance.handle(payload, self.store)

        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("task_ref", result["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.store.read("session-1")["tasks"], {})

    def test_governed_spawn_does_not_fail_open_when_state_store_is_unavailable(self):
        class FailingStore:
            last_warning = None

            def read(self, *args, **kwargs):
                raise governance.StateWriteError("state unavailable")

            def update(self, *args, **kwargs):
                raise governance.StateWriteError("state unavailable")

            def compare_and_set(self, *args, **kwargs):
                raise governance.StateWriteError("state unavailable")

        payload = {
            "session_id": "session-1",
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "governed-call",
            "tool_input": {
                "task_name": "sg_standard_task_t_0123456789ab",
                "message": "已经由生成器渲染的派发正文",
                "fork_turns": "none",
            },
        }

        result = governance.handle(payload, FailingStore())

        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("硬门禁", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_unknown_nested_response_shape_is_not_recursively_guessed(self):
        observation = governance.adapt_spawn_response(
            {"wrapper": {"agent_id": "guessed-agent", "status": "failed"}}
        )

        self.assertEqual(observation["observation"], "unknown")
        self.assertIsNone(observation["agent_id"])
        self.assertIsNone(observation["canonical_path"])

    def test_subagent_start_without_task_ref_does_not_bind_unique_candidate(self):
        initial = {
            "task_id": "sg-task-0001",
            "attempt": 1,
            "task_ref": "0123456789ab",
            "task_name": "sg_standard_candidate_t_0123456789ab",
            "resolved_mode": "standard",
            "status": "pending",
            **governance.AttemptState().to_record(),
            "created_at": governance._now(),
            "updated_at": governance._now(),
        }
        self.store.update(
            "session-1",
            lambda state: state["tasks"].update({"sg-task-0001": initial}),
            admission="new_task",
        )

        result = governance.handle(
            {
                "session_id": "session-1",
                "hook_event_name": "SubagentStart",
                "agent_id": "unrelated-agent",
            },
            self.store,
        )

        state = self.store.read("session-1")
        self.assertNotIn("unrelated-agent", state["agents"])
        self.assertEqual(state["tasks"]["sg-task-0001"]["identity_status"], "unconfirmed")
        self.assertIn(
            "治理任务 ID：未映射",
            result["hookSpecificOutput"]["additionalContext"],
        )


if __name__ == "__main__":
    unittest.main()
