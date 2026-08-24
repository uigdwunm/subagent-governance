#!/usr/bin/env python3

import copy
import json
import stat
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import governance_contracts as contracts
from scripts import governance_diagnostics as diagnostics
from scripts import governance_dispatch as dispatch
from scripts import governance_dispatch_identity as dispatch_identity
from scripts import governance_errors as errors
from scripts import governance_execution as execution_module
from scripts import governance_hook as hook
from scripts import governance_lifecycle as lifecycle
from scripts import governance_platform as platform
from scripts import governance_prepared_store as prepared_store_module
from scripts import governance_protocol as protocol
from scripts import governance_semantics as semantics
from scripts import governance_sessions as sessions
from scripts import governance_state_store as state_store_module
from scripts import governance_storage as storage
from scripts import governance_store_support as store_support
from scripts import governance_views as views


class DispatchIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = state_store_module.StateStore(self.root / "sessions")

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def current_execution(state, task_id):
        task = state["tasks"][task_id]
        return task["executions"][str(task["work_item"]["current_attempt"])]

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
            },
            "objective": "实现支付状态检查并验证结果",
            "background": "派发前置条件已满足。",
            "work_scope": ["修改当前开发仓库内的派发路径"],
            "forbidden_scope": [],
            "completion_conditions": ["确定性派发和身份绑定测试通过"],
            "evidence_requirements": ["运行定向测试"],
            "relevant_files": ["scripts/subagent_governance.py"],
            "context_manifest": {"mode": "none"},
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
        return prepared_store_module.PreparedContractStore(self.root / "prepared")

    def observe_spawn_in_dispatch_domain(self, prepared, response, *, session_id="session-1", store=None, prepared_store=None):
        """Keep the legacy dispatch-domain transition tests off the P12-A Hook route."""
        target_store = self.store if store is None else store
        target_prepared = self.prepared_store() if prepared_store is None else prepared_store
        return dispatch.observe_spawn_post_tool(
            session_id, target_prepared.read(session_id, prepared["task_ref"]),
            platform.adapt_spawn_response(response).to_record(), int(time.time()),
            target_store, target_prepared,
        )

    def prepare(self, **contract_overrides):
        return protocol.prepare_dispatch(
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
        prepared = prepared_store_module.PreparedContractStore(self.root / "prepared")
        result = protocol.prepare_dispatch(
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

    def test_dispatch_persists_current_task_contract_digest(self):
        prepared = self.prepare()
        state = self.store.read("session-1")
        execution = state["tasks"][prepared["task_id"]]["executions"]["1"]
        self.assertEqual(
            set(execution["contract_summary"]),
            {"objective", "model"},
        )
        self.assertEqual(execution["contract_digest"], prepared["contract_digest"])
        self.assertEqual(
            prepared["contract_digest"],
            contracts.contract_digest(contracts.contract_from_input(prepared["contract"])),
        )
        changed = contracts.contract_from_input(
            {**prepared["contract"], "objective": "另一个业务目标"}
        )
        self.assertNotEqual(prepared["contract_digest"], contracts.contract_digest(changed))
        stored = self.prepared_store().read("session-1", prepared["task_ref"])
        self.assertEqual(stored["contract_digest"], prepared["contract_digest"])

    def test_spawn_retry_rejects_changed_contract_by_complete_digest(self):
        prepared = self.prepare()
        hook.handle_hook(self.pre_payload(prepared), self.store)
        hook.handle_hook(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-1",
                "tool_response": {"isError": True},
            },
            self.store,
        )
        self.observe_spawn_in_dispatch_domain(prepared, {"isError": True})

        with self.assertRaisesRegex(
            errors.DispatchPreparationError,
            "完整契约不一致",
        ):
            protocol.prepare_spawn_retry(
                self.contract(semantic_name="Another Task"),
                "session-1",
                prepared["task_id"],
                state_store=self.store,
                prepared_store=self.prepared_store(),
            )

    def test_spawn_retry_rejects_working_tree_directory_before_replacement(self):
        prepared = self.prepare()
        hook.handle_hook(self.pre_payload(prepared), self.store)
        hook.handle_hook(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-1",
                "tool_response": {"isError": True},
            },
            self.store,
        )
        self.observe_spawn_in_dispatch_domain(prepared, {"isError": True})
        workspace = self.root / "retry-workspace"
        (workspace / "docs").mkdir(parents=True)
        invalid_contract = self.contract(
            context_manifest={
                "mode": "declared",
                "workspace_root": str(workspace),
                "baseline": {"kind": "working_tree", "revision": None},
                "required_paths": [{"path": "docs", "type": "directory"}],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "working_tree.*directory.*逐文件.*git_commit",
        ):
            protocol.prepare_spawn_retry(
                invalid_contract,
                "session-1",
                prepared["task_id"],
                state_store=self.store,
                prepared_store=self.prepared_store(),
            )

        execution = self.current_execution(
            self.store.read("session-1"),
            prepared["task_id"],
        )
        self.assertEqual(execution["spawn_retry_count"], 0)
        self.assertEqual(execution_module.spawn_observation(execution), "failed")

    def test_pre_tool_use_denies_legacy_working_tree_directory_contract(self):
        prepared = self.prepare()
        prepared_store = self.prepared_store()
        record = prepared_store.read("session-1", prepared["task_ref"])
        workspace = self.root / "legacy-workspace"
        (workspace / "docs").mkdir(parents=True)
        record["contract"]["context_manifest"] = {
            "mode": "declared",
            "workspace_root": str(workspace),
            "baseline": {"kind": "working_tree", "revision": None},
            "required_paths": [{"path": "docs", "type": "directory"}],
        }
        record["context_verification"] = {
            "mode": "declared",
            "workspace_root": str(workspace),
            "baseline": {"kind": "working_tree", "revision": None},
            "required_paths": [
                {"path": "docs", "type": "directory", "mtime_ns": 1}
            ],
        }
        record_path, _lock_path = prepared_store._paths(
            "session-1",
            prepared["task_ref"],
        )
        record_path.write_text(
            json.dumps(record, ensure_ascii=False),
            encoding="utf-8",
        )

        denied = hook.handle_hook(self.pre_payload(prepared), self.store)

        output = denied["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertRegex(
            output["permissionDecisionReason"],
            "PreparedContract.*working_tree.*directory",
        )
        execution = self.current_execution(
            self.store.read("session-1"),
            prepared["task_id"],
        )
        self.assertIsNone(execution_module.dispatch_tool_use_id(execution))

    def test_initial_spawn_claim_uses_only_derived_action_required(self):
        prepared = self.prepare()

        hook.handle_hook(self.pre_payload(prepared), self.store)

        state = self.store.read("session-1")
        task = state["tasks"][prepared["task_id"]]
        execution = task["executions"]["1"]
        self.assertEqual(execution_module.dispatch_tool_use_id(execution), "spawn-call-1")
        self.assertIsNone(execution_module.spawn_observation(execution))
        self.assertIsNone(execution_module.parent_action(execution))
        self.assertNotIn("action_required", task["work_item"])
        self.assertEqual(
            [
                (record["task_id"], record["attempt"])
                for record in views.action_required_records(state)
            ],
            [(prepared["task_id"], 1)],
        )

    def test_spawn_retry_rejects_legacy_root_projection(self):
        prepared = self.prepare()
        hook.handle_hook(self.pre_payload(prepared), self.store)
        hook.handle_hook(
            {
                "session_id": "session-1", "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent", "tool_use_id": "spawn-call-1",
                "tool_response": {"unexpected": True},
            }, self.store,
        )
        with self.assertRaises(errors.StateValidationError):
            self.store.update(
                "session-1",
                lambda state: state["tasks"][prepared["task_id"]].update(
                    {"spawn_observation": "failed", "identity_status": "unconfirmed"}
                ),
            )

    def test_closed_execution_rejects_retry_prepare_and_prepared_retry_claim(self):
        initial = self.prepare()
        hook.handle_hook(self.pre_payload(initial), self.store)
        hook.handle_hook(
            {
                "session_id": "session-1", "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent", "tool_use_id": "spawn-call-1",
                "tool_response": {"isError": True},
            }, self.store,
        )
        self.observe_spawn_in_dispatch_domain(initial, {"isError": True})
        retry = protocol.prepare_spawn_retry(
            self.contract(), "session-1", initial["task_id"],
            state_store=self.store, prepared_store=self.prepared_store(),
        )
        lifecycle.apply_parent_disposition(
            {
                "task_id": initial["task_id"], "attempt": 1,
                "action": "close_task", "reason": "关闭 failed execution",
            },
            "session-1", state_store=self.store, now=1_150,
        )

        retry_payload = self.pre_payload(retry)
        retry_payload["tool_use_id"] = "retry-after-close"
        denied = hook.handle_hook(retry_payload, self.store)
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        state = self.store.read("session-1")
        record = state["tasks"][initial["task_id"]]["executions"]["1"]
        self.assertTrue(execution_module.execution_is_closed(record))
        self.assertNotEqual(execution_module.dispatch_tool_use_id(record), "retry-after-close")
        self.assertEqual(state["tasks"][initial["task_id"]]["work_item"]["lifecycle"], "tombstoned")
        self.assertNotIn(retry["task_ref"], self.prepared_store().refs("session-1"))

        with self.assertRaisesRegex(errors.DispatchPreparationError, "tombstoned|关闭"):
            protocol.prepare_spawn_retry(
                self.contract(), "session-1", initial["task_id"],
                state_store=self.store, prepared_store=self.prepared_store(), now=1_200,
            )

    def test_initial_claim_persist_then_raise_restores_unclaimed_contract(self):
        initial = self.prepare()
        before = copy.deepcopy(self.store.read("session-1")["tasks"][initial["task_id"]])
        original_update = self.store.update
        update_calls = 0

        def persist_then_report_failure(*args, **kwargs):
            nonlocal update_calls
            update_calls += 1
            result = original_update(*args, **kwargs)
            if update_calls == 1:
                raise RuntimeError("simulated initial claim readback failure")
            return result

        payload = self.pre_payload(initial)
        payload["tool_use_id"] = "initial-claim-partial"
        with mock.patch.object(self.store, "update", side_effect=persist_then_report_failure):
            denied = hook.handle_hook(payload, self.store)

        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(
            self.store.read("session-1")["tasks"][initial["task_id"]], before
        )
        prepared = self.prepared_store().read("session-1", initial["task_ref"])
        self.assertFalse(prepared["consumed"])
        self.assertIsNone(prepared["tool_use_id"])
        self.assertIn(initial["task_ref"], self.prepared_store().refs("session-1"))

    def test_prepared_claim_persist_then_raise_restores_unclaimed_contract(self):
        initial = self.prepare()
        before = copy.deepcopy(self.store.read("session-1")["tasks"][initial["task_id"]])
        original_write = prepared_store_module.PreparedContractStore._write_path
        write_calls = 0

        def persist_then_report_failure(prepared_store, *args, **kwargs):
            nonlocal write_calls
            write_calls += 1
            result = original_write(prepared_store, *args, **kwargs)
            if write_calls == 1:
                raise errors.PreparedContractWriteError(
                    "simulated PreparedContract claim readback failure"
                )
            return result

        payload = self.pre_payload(initial)
        payload["tool_use_id"] = "prepared-claim-partial"
        with mock.patch.object(
            prepared_store_module.PreparedContractStore,
            "_write_path",
            persist_then_report_failure,
        ):
            denied = hook.handle_hook(payload, self.store)

        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(
            self.store.read("session-1")["tasks"][initial["task_id"]], before
        )
        prepared = self.prepared_store().read("session-1", initial["task_ref"])
        self.assertFalse(prepared["consumed"])
        self.assertIsNone(prepared["tool_use_id"])
        self.assertIsNone(prepared["claimed_at"])
        retried = hook.handle_hook(payload, self.store)
        self.assertEqual(
            retried["hookSpecificOutput"]["permissionDecision"], "allow"
        )

    def test_prepared_claim_failure_preserves_concurrently_changed_contract(self):
        initial = self.prepare()
        before = copy.deepcopy(self.store.read("session-1")["tasks"][initial["task_id"]])
        original_write = prepared_store_module.PreparedContractStore._write_path
        write_calls = 0

        def persist_change_then_report_failure(
            prepared_store,
            path,
            session_id,
            task_ref,
            record,
        ):
            nonlocal write_calls
            write_calls += 1
            result = original_write(
                prepared_store,
                path,
                session_id,
                task_ref,
                record,
            )
            if write_calls == 1:
                changed = copy.deepcopy(record)
                changed["post_observed_at"] = 1_234
                original_write(
                    prepared_store,
                    path,
                    session_id,
                    task_ref,
                    changed,
                )
                raise errors.PreparedContractWriteError(
                    "simulated claim failure after concurrent change"
                )
            return result

        payload = self.pre_payload(initial)
        payload["tool_use_id"] = "prepared-claim-diverged"
        with mock.patch.object(
            prepared_store_module.PreparedContractStore,
            "_write_path",
            persist_change_then_report_failure,
        ):
            denied = hook.handle_hook(payload, self.store)

        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("degraded", str(denied))
        self.assertEqual(
            self.store.read("session-1")["tasks"][initial["task_id"]], before
        )
        prepared = self.prepared_store().read("session-1", initial["task_ref"])
        self.assertTrue(prepared["consumed"])
        self.assertEqual(prepared["tool_use_id"], "prepared-claim-diverged")
        self.assertEqual(prepared["post_observed_at"], 1_234)

    def test_initial_claim_pre_callback_failure_keeps_unclaimed_contract_and_task(self):
        initial = self.prepare()
        before = copy.deepcopy(self.store.read("session-1")["tasks"][initial["task_id"]])
        payload = self.pre_payload(initial)
        payload["tool_use_id"] = "initial-pre-callback-failure"

        with mock.patch.object(
            self.store,
            "update",
            side_effect=RuntimeError("simulated StateStore failure before claim callback"),
        ):
            denied = hook.handle_hook(payload, self.store)

        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(
            self.store.read("session-1")["tasks"][initial["task_id"]], before
        )
        prepared = self.prepared_store().read("session-1", initial["task_ref"])
        self.assertFalse(prepared["consumed"])
        self.assertIsNone(prepared["tool_use_id"])
        self.assertIn(initial["task_ref"], self.prepared_store().refs("session-1"))

    def test_retry_claim_pre_callback_failure_keeps_unclaimed_contract_and_state(self):
        initial = self.prepare()
        hook.handle_hook(self.pre_payload(initial), self.store)
        hook.handle_hook(
            {
                "session_id": "session-1", "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent", "tool_use_id": "spawn-call-1",
                "tool_response": {"isError": True},
            }, self.store,
        )
        self.observe_spawn_in_dispatch_domain(initial, {"isError": True})
        retry = protocol.prepare_spawn_retry(
            self.contract(), "session-1", initial["task_id"],
            state_store=self.store, prepared_store=self.prepared_store(),
        )
        before = copy.deepcopy(self.store.read("session-1")["tasks"][initial["task_id"]])
        payload = self.pre_payload(retry)
        payload["tool_use_id"] = "retry-pre-callback-failure"

        with mock.patch.object(
            self.store,
            "update",
            side_effect=RuntimeError("simulated StateStore failure before claim callback"),
        ):
            denied = hook.handle_hook(payload, self.store)

        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(
            self.store.read("session-1")["tasks"][initial["task_id"]], before
        )
        prepared = self.prepared_store().read("session-1", retry["task_ref"])
        self.assertFalse(prepared["consumed"])
        self.assertIsNone(prepared["tool_use_id"])
        self.assertIn(retry["task_ref"], self.prepared_store().refs("session-1"))

    def test_pre_callback_failure_with_concurrent_change_is_degraded_without_reopening_contract(self):
        initial = self.prepare()
        original_update = self.store.update
        update_calls = 0

        def concurrently_change_then_report_pre_callback_failure(*args, **kwargs):
            nonlocal update_calls
            update_calls += 1
            if update_calls == 1:
                original_update(
                    "session-1",
                    lambda state: state["health"].update({"status": "unavailable"}),
                    required_fields=("tasks", "tombstones"),
                )
                raise RuntimeError("simulated StateStore failure before claim callback")
            return original_update(*args, **kwargs)

        payload = self.pre_payload(initial)
        payload["tool_use_id"] = "initial-pre-callback-concurrent"
        with mock.patch.object(
            self.store,
            "update",
            side_effect=concurrently_change_then_report_pre_callback_failure,
        ):
            denied = hook.handle_hook(payload, self.store)

        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        task = self.store.read("session-1")["tasks"][initial["task_id"]]
        self.assertEqual(self.store.read("session-1")["health"]["status"], "unavailable")
        self.assertIsNone(task["executions"]["1"]["dispatch_record"]["tool_use_id"])
        prepared = self.prepared_store().read("session-1", initial["task_ref"])
        self.assertFalse(prepared["consumed"])
        self.assertIsNone(prepared["tool_use_id"])

    def test_retry_claim_persist_then_raise_restores_unclaimed_contract(self):
        initial = self.prepare()
        hook.handle_hook(self.pre_payload(initial), self.store)
        hook.handle_hook(
            {
                "session_id": "session-1", "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent", "tool_use_id": "spawn-call-1",
                "tool_response": {"isError": True},
            }, self.store,
        )
        self.observe_spawn_in_dispatch_domain(initial, {"isError": True})
        retry = protocol.prepare_spawn_retry(
            self.contract(), "session-1", initial["task_id"],
            state_store=self.store, prepared_store=self.prepared_store(),
        )
        before = copy.deepcopy(self.store.read("session-1")["tasks"][initial["task_id"]])
        original_update = self.store.update
        update_calls = 0

        def persist_then_report_failure(*args, **kwargs):
            nonlocal update_calls
            update_calls += 1
            result = original_update(*args, **kwargs)
            if update_calls == 1:
                raise RuntimeError("simulated retry claim readback failure")
            return result

        payload = self.pre_payload(retry)
        payload["tool_use_id"] = "retry-claim-partial"
        with mock.patch.object(self.store, "update", side_effect=persist_then_report_failure):
            denied = hook.handle_hook(payload, self.store)

        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(
            self.store.read("session-1")["tasks"][initial["task_id"]], before
        )
        prepared = self.prepared_store().read("session-1", retry["task_ref"])
        self.assertFalse(prepared["consumed"])
        self.assertIsNone(prepared["tool_use_id"])
        self.assertIn(retry["task_ref"], self.prepared_store().refs("session-1"))

    def test_installed_cache_generator_and_hook_share_plugin_data_root_without_env(self):
        codex_root = self.root / ".codex"
        installed_script = (
            codex_root
            / "plugins/cache/personal/subagent-governance/0.4.0-rc.12/scripts"
            / "subagent_governance.py"
        )
        expected_root = (
            codex_root
            / "plugins/data/subagent-governance-personal/state-v8"
        ).resolve()
        session_id = "installed-session"

        with (
            mock.patch.object(state_store_module, "__file__", str(installed_script)),
            mock.patch.object(prepared_store_module, "__file__", str(installed_script)),
            mock.patch.dict(
                store_support.os.environ,
                {"SUBAGENT_GOVERNANCE_DATA": "", "PLUGIN_DATA": ""},
            ),
        ):
            self.assertEqual(store_support.data_root_path(installed_script), expected_root)
            prepared = protocol.prepare_dispatch(
                self.contract(),
                session_id,
                task_id_factory=lambda: "sg-installed-task",
            )
            payload = self.pre_payload(prepared)
            payload["session_id"] = session_id
            result = hook.handle_hook(payload)["hookSpecificOutput"]

        self.assertEqual(result["permissionDecision"], "allow")
        persisted = prepared_store_module.PreparedContractStore(expected_root / "prepared").read(
            session_id,
            prepared["task_ref"],
        )
        state = state_store_module.StateStore(expected_root / "sessions").read(session_id)
        self.assertTrue(persisted["consumed"])
        self.assertEqual(persisted["tool_use_id"], "spawn-call-1")
        self.assertEqual(
            self.current_execution(state, prepared["task_id"])["dispatch_record"][
                "tool_use_id"
            ],
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
                result = protocol.prepare_dispatch(
                    self.contract(
                        **overrides,
                        model="gpt-5.6-terra",
                        reasoning_effort="high",
                    ),
                    f"session-{index}",
                    state_store=state_store_module.StateStore(root / "sessions"),
                    prepared_store=prepared_store_module.PreparedContractStore(root / "prepared"),
                    task_id_factory=lambda index=index: f"sg-task-{index}",
                )
                self.assertEqual(result["spawn_args"]["fork_turns"], expected)
                self.assertEqual(result["spawn_args"]["model"], "gpt-5.6-terra")
                self.assertEqual(result["spawn_args"]["reasoning_effort"], "high")

    def test_task_ref_collision_is_bounded_and_task_name_never_exceeds_limit(self):
        task_id = "sg-task-collision"
        all_candidates = {
            dispatch_identity.derive_task_ref(task_id, 1, length)
            for length in semantics.TASK_REF_LENGTHS
        }
        self.assertIsNone(dispatch_identity.select_task_ref(task_id, 1, all_candidates))
        occupied = {
            dispatch_identity.derive_task_ref(task_id, 1, length)
            for length in semantics.TASK_REF_LENGTHS[:-1]
        }
        self.assertEqual(
            len(dispatch_identity.select_task_ref(task_id, 1, occupied)),
            semantics.TASK_REF_LENGTHS[-1],
        )
        task_name = dispatch_identity.build_task_name(
            "strict",
            "very_long_semantic_name_" * 10,
            "a" * 32,
        )
        self.assertLessEqual(len(task_name), semantics.TASK_NAME_MAX_LENGTH)
        self.assertIsNotNone(dispatch_identity.parse_task_name(task_name))

    def test_prepare_dispatch_regenerates_task_id_once_after_32_character_collision(self):
        ids = iter(("sg-first", "sg-second"))
        with mock.patch.object(
            protocol,
            "select_task_ref",
            side_effect=(None, "0123456789ab"),
        ) as selector:
            result = protocol.prepare_dispatch(
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
        with mock.patch.object(protocol, "select_task_ref", return_value=None):
            with self.assertRaisesRegex(errors.DispatchPreparationError, "两个新 task_id"):
                protocol.prepare_dispatch(
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
        self.assertNotIn("initial_task_snapshot", record)
        self.assertNotIn("initial_task_snapshot_sha256", record)
        self.assertEqual(
            dispatch.initial_task_post_state(record),
            self.store.read("session-1")["tasks"][prepared["task_id"]],
        )

        invalid_attempt = copy.deepcopy(record)
        invalid_attempt["attempt"] = 2
        with self.assertRaisesRegex(
            errors.PreparedContractValidationError, "attempt 必须为1"
        ):
            prepared_store_module.PreparedContractStore._validate_record(
                invalid_attempt,
                "session-1",
                prepared["task_ref"],
                self.root / "invalid-initial-attempt.json",
            )

    def test_prepared_contract_rechecks_opened_file_metadata(self):
        prepared = self.prepare()
        prepared_store = self.prepared_store()
        path, _lock_path = prepared_store._paths("session-1", prepared["task_ref"])
        opened_as_symlink = SimpleNamespace(st_mode=stat.S_IFLNK, st_size=0)

        with mock.patch.object(
            storage.os, "fstat", return_value=opened_as_symlink
        ):
            with self.assertRaisesRegex(
                errors.PreparedContractValidationError, "普通文件"
            ):
                prepared_store._read_path(path, "session-1", prepared["task_ref"])

    def test_prepared_contract_readback_failure_is_not_reported_as_success(self):
        prepared_store = self.prepared_store()
        original_read = prepared_store._read_path
        calls = 0

        def fail_readback(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise errors.PreparedContractValidationError("simulated readback failure")
            return original_read(*args, **kwargs)

        with mock.patch.object(prepared_store, "_read_path", side_effect=fail_readback):
            with self.assertRaisesRegex(
                errors.DispatchPreparationError, "simulated readback failure"
            ):
                protocol.prepare_dispatch(
                    self.contract(),
                    "session-1",
                    state_store=self.store,
                    prepared_store=prepared_store,
                    task_id_factory=lambda: "sg-task-readback",
                )
        self.assertEqual(self.store.read("session-1")["tasks"], {})
        self.assertEqual(prepared_store.list_records("session-1"), [])

    def test_initial_prepare_persist_then_error_exactly_rolls_back_task_before_contract(self):
        prepared_store = self.prepared_store()
        original_compare_and_set = self.store.compare_and_set
        compare_calls = 0
        delete_observations = []

        def persist_then_report_failure(*args, **kwargs):
            nonlocal compare_calls
            compare_calls += 1
            result = original_compare_and_set(*args, **kwargs)
            if compare_calls == 1:
                raise errors.StateWriteError("simulated initial persist-then-error")
            return result

        original_delete_if = prepared_store.delete_if

        def observe_delete(session_id, task_ref, predicate, **kwargs):
            delete_observations.append(
                "sg-task-initial-exact" in self.store.read("session-1")["tasks"]
            )
            return original_delete_if(session_id, task_ref, predicate, **kwargs)

        with mock.patch.object(
            self.store, "compare_and_set", side_effect=persist_then_report_failure
        ), mock.patch.object(prepared_store, "delete_if", side_effect=observe_delete):
            with self.assertRaisesRegex(
                errors.DispatchPreparationError,
                "simulated initial persist-then-error",
            ):
                protocol.prepare_dispatch(
                    self.contract(),
                    "session-1",
                    state_store=self.store,
                    prepared_store=prepared_store,
                    task_id_factory=lambda: "sg-task-initial-exact",
                )

        self.assertEqual(delete_observations, [False])
        self.assertNotIn(
            "sg-task-initial-exact", self.store.read("session-1")["tasks"]
        )
        self.assertEqual(prepared_store.list_records("session-1"), [])

    def test_initial_prepare_persist_then_error_retains_concurrently_changed_task_and_contract(self):
        prepared_store = self.prepared_store()
        original_compare_and_set = self.store.compare_and_set
        compare_calls = 0

        def persist_change_then_report_failure(*args, **kwargs):
            nonlocal compare_calls
            compare_calls += 1
            result = original_compare_and_set(*args, **kwargs)
            if compare_calls == 1:
                original_compare_and_set(
                    "session-1",
                    lambda state: "sg-task-initial-diverged" in state["tasks"],
                    lambda state: state["tasks"]["sg-task-initial-diverged"]
                    ["executions"]["1"].update({"updated_at": 9_999}),
                    required_fields=("tasks", "tombstones"),
                )
                raise errors.StateWriteError(
                    "simulated initial persist-then-concurrent-error"
                )
            return result

        with mock.patch.object(
            self.store, "compare_and_set", side_effect=persist_change_then_report_failure
        ):
            with self.assertRaisesRegex(
                errors.DispatchPreparationError,
                "degraded.*rollback-incomplete.*PreparedContract retained",
            ):
                protocol.prepare_dispatch(
                    self.contract(),
                    "session-1",
                    state_store=self.store,
                    prepared_store=prepared_store,
                    task_id_factory=lambda: "sg-task-initial-diverged",
                )

        state = self.store.read("session-1")
        task = state["tasks"]["sg-task-initial-diverged"]
        execution = task["executions"]["1"]
        self.assertGreaterEqual(task["executions"]["1"]["updated_at"], 9_999)
        self.assertEqual(execution_module.parent_action(execution), "reconcile")
        self.assertEqual(state["health"]["status"], "degraded")
        self.assertEqual(len(prepared_store.list_records("session-1")), 1)
        action_required = views.action_required_records(state)
        self.assertEqual(
            [(record["task_id"], record["attempt"]) for record in action_required],
            [("sg-task-initial-diverged", 1)],
        )
        diagnostic, _exit_code = diagnostics.build_diagnostic_document(
            "session-1", self.root
        )
        diagnostic_item = diagnostic["sessions"][0]["work_items"][0]
        self.assertTrue(diagnostic_item["action_required"])
        session_start = hook.handle_hook(
            {
                "session_id": "session-1",
                "hook_event_name": "SessionStart",
                "source": "resume",
            },
            self.store,
        )
        context = session_start["hookSpecificOutput"]["additionalContext"]
        self.assertIn("sg-task-initial-diverged", context)
        self.assertIn("reconcile", context)

    def test_initial_prepare_task_cleanup_write_failure_is_action_required_and_retains_contract(self):
        prepared_store = self.prepared_store()
        original_compare_and_set = self.store.compare_and_set
        compare_calls = 0

        def fail_cleanup_after_persist(*args, **kwargs):
            nonlocal compare_calls
            compare_calls += 1
            if compare_calls == 1:
                original_compare_and_set(*args, **kwargs)
                raise errors.StateWriteError("simulated initial write readback error")
            if compare_calls == 2:
                raise errors.StateWriteError("simulated task cleanup write failure")
            return original_compare_and_set(*args, **kwargs)

        with mock.patch.object(
            self.store, "compare_and_set", side_effect=fail_cleanup_after_persist
        ):
            with self.assertRaisesRegex(
                errors.DispatchPreparationError,
                "rollback-incomplete.*task cleanup write failure.*PreparedContract retained",
            ):
                protocol.prepare_dispatch(
                    self.contract(),
                    "session-1",
                    state_store=self.store,
                    prepared_store=prepared_store,
                    task_id_factory=lambda: "sg-task-cleanup-failure",
                )

        state = self.store.read("session-1")
        execution = state["tasks"]["sg-task-cleanup-failure"]["executions"]["1"]
        self.assertEqual(execution_module.parent_action(execution), "reconcile")
        self.assertEqual(state["health"]["status"], "degraded")
        self.assertEqual(len(prepared_store.list_records("session-1")), 1)

    def test_initial_prepare_contract_cleanup_failure_reports_orphan_after_safe_task_delete(self):
        prepared_store = self.prepared_store()
        original_compare_and_set = self.store.compare_and_set
        compare_calls = 0

        def persist_then_report_failure(*args, **kwargs):
            nonlocal compare_calls
            compare_calls += 1
            result = original_compare_and_set(*args, **kwargs)
            if compare_calls == 1:
                raise errors.StateWriteError("simulated initial gate readback error")
            return result

        with mock.patch.object(
            self.store, "compare_and_set", side_effect=persist_then_report_failure
        ), mock.patch.object(
            prepared_store,
            "delete_if",
            side_effect=errors.PreparedContractWriteError(
                "simulated PreparedContract cleanup failure"
            ),
        ):
            with self.assertRaisesRegex(
                errors.DispatchPreparationError,
                "rollback-incomplete.*PreparedContract cleanup failure.*orphan",
            ):
                protocol.prepare_dispatch(
                    self.contract(),
                    "session-1",
                    state_store=self.store,
                    prepared_store=prepared_store,
                    task_id_factory=lambda: "sg-task-prepared-cleanup-failure",
                )

        self.assertNotIn(
            "sg-task-prepared-cleanup-failure", self.store.read("session-1")["tasks"]
        )
        self.assertEqual(len(prepared_store.list_records("session-1")), 1)

    def test_initial_prepare_state_readback_failure_retains_credential_and_reports_incomplete(self):
        prepared_store = self.prepared_store()
        original_read = self.store.read
        read_calls = 0

        def fail_after_occupancy_read(*args, **kwargs):
            nonlocal read_calls
            read_calls += 1
            if read_calls == 1:
                return original_read(*args, **kwargs)
            raise errors.StateValidationError("simulated StateStore readback failure")

        with mock.patch.object(self.store, "read", side_effect=fail_after_occupancy_read):
            with self.assertRaisesRegex(
                errors.DispatchPreparationError,
                "rollback-incomplete.*StateStore readback failure.*PreparedContract retained",
            ):
                protocol.prepare_dispatch(
                    self.contract(),
                    "session-1",
                    state_store=self.store,
                    prepared_store=prepared_store,
                    task_id_factory=lambda: "sg-task-state-readback-failure",
                )

        self.assertIn(
            "sg-task-state-readback-failure", original_read("session-1")["tasks"]
        )
        self.assertEqual(len(prepared_store.list_records("session-1")), 1)

    def test_state_store_gate_failure_removes_prepared_contract_and_rejects(self):
        prepared_store = self.prepared_store()
        with mock.patch.object(
            self.store,
            "compare_and_set",
            side_effect=errors.StateWriteError("simulated state failure"),
        ):
            with self.assertRaises(errors.DispatchPreparationError):
                protocol.prepare_dispatch(
                    self.contract(),
                    "session-1",
                    state_store=self.store,
                    prepared_store=prepared_store,
                    task_id_factory=lambda: "sg-task-gate",
                )
        self.assertEqual(prepared_store.list_records("session-1"), [])

    def test_unconsumed_prepared_contract_expires_with_initial_attempt(self):
        prepared = protocol.prepare_dispatch(
            self.contract(),
            "session-1",
            state_store=self.store,
            prepared_store=self.prepared_store(),
            task_id_factory=lambda: "sg-task-expired",
            now=1_000,
        )
        result = sessions.reconcile_prepared_dispatches(
            "session-1",
            state_store=self.store,
            prepared_store=self.prepared_store(),
            now=1_301,
        )
        self.assertEqual(result, {"expired": 1, "reconciled": 0})
        self.assertNotIn(prepared["task_id"], self.store.read("session-1")["tasks"])
        self.assertEqual(self.prepared_store().list_records("session-1"), [])

    def test_missing_unclaimed_initial_credential_is_tombstoned_after_expiry(self):
        prepared_store = self.prepared_store()
        prepared = protocol.prepare_dispatch(
            self.contract(),
            "session-1",
            state_store=self.store,
            prepared_store=prepared_store,
            task_id_factory=lambda: "sg-task-missing-credential",
            now=1_000,
        )
        prepared_store.delete("session-1", prepared["task_ref"], missing_ok=False)

        result = sessions.reconcile_prepared_dispatches(
            "session-1",
            state_store=self.store,
            prepared_store=prepared_store,
            now=1_301,
        )

        self.assertEqual(result, {"expired": 1, "reconciled": 0})
        state = self.store.read("session-1")
        task = state["tasks"][prepared["task_id"]]
        execution = task["executions"]["1"]
        self.assertEqual(task["work_item"]["lifecycle"], "tombstoned")
        self.assertEqual(
            execution["closure_record"],
            {
                "closed_at": 1_301,
                "parent_action": None,
                "reason": "automatic_close:expired_unclaimed_dispatch",
            },
        )
        self.assertEqual(
            state["tombstones"][f'{prepared["task_id"]}:1']["close_reason"],
            "automatic_close:expired_unclaimed_dispatch",
        )
        self.assertEqual(
            execution["observation_record"],
            {
                "observed_at": None,
                "observed_state": "not_observed",
                "source": None,
                "terminal_status": None,
            },
        )

    def test_missing_unclaimed_initial_credential_is_retained_before_expiry(self):
        prepared_store = self.prepared_store()
        prepared = protocol.prepare_dispatch(
            self.contract(),
            "session-1",
            state_store=self.store,
            prepared_store=prepared_store,
            task_id_factory=lambda: "sg-task-young-missing-credential",
            now=1_000,
        )
        prepared_store.delete("session-1", prepared["task_ref"], missing_ok=False)

        result = sessions.reconcile_prepared_dispatches(
            "session-1",
            state_store=self.store,
            prepared_store=prepared_store,
            now=1_299,
        )

        self.assertEqual(result, {"expired": 0, "reconciled": 0})
        task = self.store.read("session-1")["tasks"][prepared["task_id"]]
        self.assertEqual(task["work_item"]["lifecycle"], "open")
        self.assertEqual(task["executions"]["1"]["closure_record"]["closed_at"], None)

    def test_missing_credential_never_auto_closes_unknown_spawn(self):
        prepared_store = self.prepared_store()
        prepared = protocol.prepare_dispatch(
            self.contract(),
            "session-1",
            state_store=self.store,
            prepared_store=prepared_store,
            task_id_factory=lambda: "sg-task-unknown-missing-credential",
            now=1_000,
        )

        def mark_unknown(state):
            execution = state["tasks"][prepared["task_id"]]["executions"]["1"]
            execution_module.apply_canonical_execution_update(
                execution, "dispatch_tool_use_id", "unknown-tool-use"
            )
            execution_module.apply_canonical_execution_update(
                execution, "dispatch_response", "unknown"
            )
            execution_module.apply_canonical_execution_update(
                execution, "closure_parent_action", "reconcile"
            )
            execution["updated_at"] = 1_000

        self.store.update("session-1", mark_unknown)
        prepared_store.delete("session-1", prepared["task_ref"], missing_ok=False)

        result = sessions.reconcile_prepared_dispatches(
            "session-1",
            state_store=self.store,
            prepared_store=prepared_store,
            now=10_000,
        )

        self.assertEqual(result, {"expired": 0, "reconciled": 0})
        task = self.store.read("session-1")["tasks"][prepared["task_id"]]
        execution = task["executions"]["1"]
        self.assertEqual(task["work_item"]["lifecycle"], "open")
        self.assertEqual(execution_module.spawn_observation(execution), "unknown")
        self.assertEqual(execution_module.parent_action(execution), "reconcile")
        self.assertIsNone(execution["closure_record"]["closed_at"])

    def test_missing_credential_auto_close_preserves_concurrent_state_change(self):
        prepared_store = self.prepared_store()
        prepared = protocol.prepare_dispatch(
            self.contract(),
            "session-1",
            state_store=self.store,
            prepared_store=prepared_store,
            task_id_factory=lambda: "sg-task-concurrent-missing-credential",
            now=1_000,
        )
        prepared_store.delete("session-1", prepared["task_ref"], missing_ok=False)
        original_compare_and_set = self.store.compare_and_set
        changed = False

        def change_before_close(*args, **kwargs):
            nonlocal changed
            if not changed:
                changed = True
                original_compare_and_set(
                    "session-1",
                    lambda _state: True,
                    lambda state: state["tasks"][prepared["task_id"]]["executions"]["1"].update(
                        {"updated_at": 1_200}
                    ),
                )
            return original_compare_and_set(*args, **kwargs)

        with mock.patch.object(
            self.store,
            "compare_and_set",
            side_effect=change_before_close,
        ):
            result = sessions.reconcile_prepared_dispatches(
                "session-1",
                state_store=self.store,
                prepared_store=prepared_store,
                now=1_301,
            )

        self.assertEqual(result, {"expired": 0, "reconciled": 0})
        task = self.store.read("session-1")["tasks"][prepared["task_id"]]
        self.assertEqual(task["executions"]["1"]["updated_at"], 1_200)
        self.assertEqual(task["work_item"]["lifecycle"], "open")
        self.assertIsNone(task["executions"]["1"]["closure_record"]["closed_at"])

    def test_unclaimed_initial_expiry_retains_concurrent_change_and_marks_reconcile(self):
        prepared = protocol.prepare_dispatch(
            self.contract(), "session-1", state_store=self.store,
            prepared_store=self.prepared_store(),
            task_id_factory=lambda: "sg-task-expiry-diverged", now=1_000,
        )
        self.store.update(
            "session-1",
            lambda state: state["tasks"][prepared["task_id"]]["executions"]["1"].update(
                {"updated_at": 1_200}
            ),
        )

        with self.assertRaisesRegex(
            errors.PreparedContractConflictError,
            "degraded.*rollback-incomplete.*PreparedContract retained",
        ):
            sessions.reconcile_prepared_dispatches(
                "session-1", state_store=self.store,
                prepared_store=self.prepared_store(), now=1_301,
            )

        state = self.store.read("session-1")
        task = state["tasks"][prepared["task_id"]]
        self.assertEqual(task["executions"]["1"]["updated_at"], 1_301)
        self.assertEqual(
            task["executions"]["1"]["closure_record"]["parent_action"], "reconcile"
        )
        self.assertEqual(state["health"]["status"], "degraded")
        self.assertEqual(len(self.prepared_store().list_records("session-1")), 1)

    def test_unclaimed_initial_expiry_task_cleanup_failure_retains_contract(self):
        prepared = protocol.prepare_dispatch(
            self.contract(), "session-1", state_store=self.store,
            prepared_store=self.prepared_store(),
            task_id_factory=lambda: "sg-task-expiry-cleanup-failure", now=1_000,
        )
        original_compare_and_set = self.store.compare_and_set
        compare_calls = 0

        def fail_cleanup_then_allow_marker(*args, **kwargs):
            nonlocal compare_calls
            compare_calls += 1
            if compare_calls == 1:
                raise errors.StateWriteError("simulated expiry task cleanup failure")
            return original_compare_and_set(*args, **kwargs)

        with mock.patch.object(
            self.store, "compare_and_set", side_effect=fail_cleanup_then_allow_marker
        ):
            with self.assertRaisesRegex(
                errors.PreparedContractConflictError,
                "rollback-incomplete.*expiry task cleanup failure.*PreparedContract retained",
            ):
                sessions.reconcile_prepared_dispatches(
                    "session-1", state_store=self.store,
                    prepared_store=self.prepared_store(), now=1_301,
                )

        state = self.store.read("session-1")
        self.assertEqual(
            state["tasks"][prepared["task_id"]]["executions"]["1"]["closure_record"][
                "parent_action"
            ],
            "reconcile",
        )
        self.assertEqual(len(self.prepared_store().list_records("session-1")), 1)

    def test_unclaimed_initial_expiry_contract_cleanup_failure_leaves_retryable_orphan(self):
        prepared_store = self.prepared_store()
        prepared = protocol.prepare_dispatch(
            self.contract(), "session-1", state_store=self.store,
            prepared_store=prepared_store,
            task_id_factory=lambda: "sg-task-expiry-prepared-failure", now=1_000,
        )
        with mock.patch.object(
            prepared_store,
            "delete_if",
            side_effect=errors.PreparedContractWriteError(
                "simulated expiry PreparedContract cleanup failure"
            ),
        ):
            with self.assertRaisesRegex(
                errors.PreparedContractConflictError,
                "rollback-incomplete.*PreparedContract cleanup failure.*orphan",
            ):
                sessions.reconcile_prepared_dispatches(
                    "session-1", state_store=self.store,
                    prepared_store=prepared_store, now=1_301,
                )

        self.assertNotIn(prepared["task_id"], self.store.read("session-1")["tasks"])
        self.assertEqual(len(prepared_store.list_records("session-1")), 1)

    def test_unclaimed_initial_expiry_does_not_delete_concurrently_changed_contract(self):
        prepared_store = self.prepared_store()
        prepared = protocol.prepare_dispatch(
            self.contract(), "session-1", state_store=self.store,
            prepared_store=prepared_store,
            task_id_factory=lambda: "sg-task-expiry-contract-diverged", now=1_000,
        )
        original_delete_if = prepared_store.delete_if
        changed = False

        def change_then_delete(session_id, task_ref, predicate, **kwargs):
            nonlocal changed
            if not changed:
                changed = True
                prepared_store.compare_and_set(
                    session_id,
                    task_ref,
                    lambda _value: True,
                    lambda value: value.update({"created_at": 9_999}),
                )
            return original_delete_if(
                session_id, task_ref, predicate, **kwargs
            )

        with mock.patch.object(
            prepared_store, "delete_if", side_effect=change_then_delete
        ):
            with self.assertRaisesRegex(
                errors.PreparedContractConflictError,
                "rollback-incomplete.*exact delete.*orphan",
            ):
                sessions.reconcile_prepared_dispatches(
                    "session-1", state_store=self.store,
                    prepared_store=prepared_store, now=1_301,
                )

        self.assertNotIn(prepared["task_id"], self.store.read("session-1")["tasks"])
        retained = prepared_store.read("session-1", prepared["task_ref"])
        self.assertEqual(retained["created_at"], 9_999)

    def test_unclaimed_initial_expiry_deletes_task_absent_orphan(self):
        prepared_store = self.prepared_store()
        prepared = protocol.prepare_dispatch(
            self.contract(), "session-1", state_store=self.store,
            prepared_store=prepared_store,
            task_id_factory=lambda: "sg-task-expiry-orphan", now=1_000,
        )
        self.store.update(
            "session-1",
            lambda state: state["tasks"].pop(prepared["task_id"]),
        )

        result = sessions.reconcile_prepared_dispatches(
            "session-1", state_store=self.store,
            prepared_store=prepared_store, now=1_301,
        )

        self.assertEqual(result, {"expired": 1, "reconciled": 0})
        self.assertEqual(prepared_store.list_records("session-1"), [])

    def test_unclaimed_initial_exact_cleanup_rejects_every_task_field_change(self):
        mutations = {
            "timestamp": lambda task: task["executions"]["1"].update(
                {"updated_at": 9_999}
            ),
            "observation": lambda task: execution_module.apply_canonical_execution_update(
                task["executions"]["1"], "observation_observed_at", 9_998
            ),
            "claim": lambda task: execution_module.apply_canonical_execution_update(
                task["executions"]["1"], "dispatch_tool_use_id", "concurrent-claim"
            ),
            "closure_parent_action": lambda task: execution_module.apply_canonical_execution_update(
                task["executions"]["1"], "closure_parent_action", "wait"
            ),
        }
        for index, (name, mutate) in enumerate(mutations.items()):
            with self.subTest(field=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                store = state_store_module.StateStore(root / "sessions")
                prepared_store = prepared_store_module.PreparedContractStore(root / "prepared")
                task_id = f"sg-task-exact-field-{index}"
                prepared_result = protocol.prepare_dispatch(
                    self.contract(), "session-fields", state_store=store,
                    prepared_store=prepared_store,
                    task_id_factory=lambda value=task_id: value, now=1_000,
                )
                stored_prepared = prepared_store.read(
                    "session-fields", prepared_result["task_ref"]
                )

                store.update(
                    "session-fields",
                    lambda state: mutate(state["tasks"][task_id]),
                )
                cleanup = dispatch.cleanup_initial_attempt(
                    "session-fields",
                    stored_prepared,
                    store,
                    error_context=f"field mutation: {name}",
                    now=1_301,
                )

                self.assertFalse(cleanup["safe_for_prepared_delete"])
                state = store.read("session-fields")
                self.assertIn(task_id, state["tasks"])
                execution = state["tasks"][task_id]["executions"]["1"]
                if name == "observation":
                    self.assertEqual(
                        execution["observation_record"]["observed_at"],
                        9_998,
                    )
                if name == "timestamp":
                    self.assertEqual(execution["updated_at"], 9_999)
                if name == "claim":
                    self.assertEqual(
                        execution_module.dispatch_tool_use_id(execution), "concurrent-claim"
                    )
                self.assertEqual(execution_module.parent_action(execution), "reconcile")
                self.assertEqual(len(prepared_store.list_records("session-fields")), 1)

    def test_initial_rollback_marker_preserves_newer_unavailable_health_facts(self):
        prepared_result = protocol.prepare_dispatch(
            self.contract(), "session-health-race", state_store=self.store,
            prepared_store=self.prepared_store(),
            task_id_factory=lambda: "sg-task-health-race", now=1_000,
        )
        prepared = self.prepared_store().read(
            "session-health-race", prepared_result["task_ref"]
        )
        observed_task = copy.deepcopy(
            self.store.read("session-health-race")["tasks"][prepared["task_id"]]
        )
        newer_health_marker = {
            "status": "rollback_incomplete",
            "task_ref": "abcdefabcdef",
            "observed_at": 9_999,
            "error": "newer health observation",
        }
        self.store.update(
            "session-health-race",
            lambda state: state["health"].update(
                {
                    "status": "unavailable",
                    "initial_preparation_rollback": copy.deepcopy(
                        newer_health_marker
                    ),
                }
            ),
        )

        marked = dispatch.mark_initial_rollback_incomplete(
            "session-health-race",
            prepared,
            self.store,
            observed_task,
            error="older F10 cleanup observation",
            now=1_301,
        )

        self.assertTrue(marked)
        state = self.store.read("session-health-race")
        execution = state["tasks"][prepared["task_id"]]["executions"]["1"]
        self.assertEqual(execution_module.parent_action(execution), "reconcile")
        self.assertEqual(
            execution["initial_preparation_rollback"]["observed_at"], 1_301
        )
        self.assertEqual(state["health"]["status"], "unavailable")
        self.assertEqual(
            state["health"]["initial_preparation_rollback"],
            newer_health_marker,
        )

    def test_initial_rollback_marker_rejects_invalid_health_shape(self):
        prepared_result = protocol.prepare_dispatch(
            self.contract(), "session-health-invalid", state_store=self.store,
            prepared_store=self.prepared_store(),
            task_id_factory=lambda: "sg-task-health-invalid", now=1_000,
        )
        prepared = self.prepared_store().read(
            "session-health-invalid", prepared_result["task_ref"]
        )
        observed_task = copy.deepcopy(
            self.store.read("session-health-invalid")["tasks"][prepared["task_id"]]
        )
        with self.assertRaises(errors.StateValidationError):
            self.store.update(
                "session-health-invalid",
                lambda state: state["health"].update({"status": "invalid-health-status"}),
            )

    def test_pre_tool_use_consumes_prepared_contract_once_and_checks_native_parameters(self):
        prepared = self.prepare()
        stored_prepared = self.prepared_store().read("session-1", prepared["task_ref"])
        self.assertNotIn("message_sha256", stored_prepared["native_parameters"])
        mismatch = hook.handle_hook(self.pre_payload(prepared, fork_turns="all"), self.store)
        self.assertEqual(mismatch["hookSpecificOutput"]["permissionDecision"], "deny")
        record = self.prepared_store().read("session-1", prepared["task_ref"])
        self.assertFalse(record["consumed"])

        opaque_transport = hook.handle_hook(
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
        state = self.store.read("session-1")
        state_record = self.current_execution(state, prepared["task_id"])
        self.assertEqual(execution_module.dispatch_tool_use_id(state_record), "spawn-call-1")

        repeated = hook.handle_hook(self.pre_payload(prepared), self.store)
        self.assertEqual(repeated["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_consumed_contract_is_not_deleted_by_five_minute_expiry(self):
        prepared = self.prepare()
        hook.handle_hook(self.pre_payload(prepared), self.store)
        claimed_at = self.prepared_store().read("session-1", prepared["task_ref"])["claimed_at"]
        result = sessions.reconcile_prepared_dispatches(
            "session-1",
            state_store=self.store,
            prepared_store=self.prepared_store(),
            now=claimed_at + 301,
        )
        self.assertEqual(result, {"expired": 0, "reconciled": 0})
        self.assertTrue(self.prepared_store().read("session-1", prepared["task_ref"])["consumed"])

    def test_missing_post_tool_use_becomes_unknown_only_after_twenty_minutes(self):
        prepared = self.prepare()
        hook.handle_hook(self.pre_payload(prepared), self.store)
        claimed_at = self.prepared_store().read("session-1", prepared["task_ref"])["claimed_at"]
        early = sessions.reconcile_prepared_dispatches(
            "session-1",
            state_store=self.store,
            prepared_store=self.prepared_store(),
            now=claimed_at + 1_199,
        )
        self.assertEqual(early["reconciled"], 0)
        state = self.store.read("session-1")
        record = self.current_execution(state, prepared["task_id"])
        self.assertIsNone(execution_module.spawn_observation(record))
        self.assertIsNone(execution_module.parent_action(record))

        late = sessions.reconcile_prepared_dispatches(
            "session-1",
            state_store=self.store,
            prepared_store=self.prepared_store(),
            now=claimed_at + 1_200,
        )
        self.assertEqual(late["reconciled"], 1)
        state = self.store.read("session-1")
        record = self.current_execution(state, prepared["task_id"])
        self.assertEqual(execution_module.spawn_observation(record), "unknown")
        self.assertEqual(execution_module.execution_status(record), "not_started")
        self.assertEqual(execution_module.identity_status(record), "unconfirmed")
        self.assertEqual(execution_module.parent_action(record), "reconcile")
        self.assertTrue(self.prepared_store().read("session-1", prepared["task_ref"])["consumed"])

    def test_post_tool_spawn_success_is_probe_only_and_remains_claimed(self):
        prepared = self.prepare()
        hook.handle_hook(self.pre_payload(prepared), self.store)
        result = hook.handle_hook(
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
        record = self.current_execution(state, prepared["task_id"])
        self.assertIsNone(execution_module.spawn_observation(record))
        self.assertEqual(execution_module.identity_status(record), "unconfirmed")
        self.assertEqual(execution_module.execution_status(record), "not_started")
        self.assertIsNone(execution_module.parent_action(record))
        self.assertTrue(self.prepared_store().list_records("session-1"))
    def test_post_tool_success_without_identity_is_probe_only(self):
        prepared = self.prepare()
        hook.handle_hook(self.pre_payload(prepared), self.store)
        hook.handle_hook(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-1",
                "tool_response": {"status": "ok"},
            },
            self.store,
        )
        state = self.store.read("session-1")
        record = self.current_execution(state, prepared["task_id"])
        self.assertIsNone(execution_module.spawn_observation(record))
        self.assertEqual(execution_module.identity_status(record), "unconfirmed")
        self.assertEqual(execution_module.execution_status(record), "not_started")
        self.assertIsNone(execution_module.parent_action(record))

    def test_post_tool_failed_and_unknown_are_probe_only(self):
        failed = self.prepare()
        hook.handle_hook(self.pre_payload(failed), self.store)
        hook.handle_hook(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-1",
                "tool_response": {"isError": True},
            },
            self.store,
        )
        state = self.store.read("session-1")
        failed_record = self.current_execution(state, failed["task_id"])
        self.assertIsNone(execution_module.spawn_observation(failed_record))
        self.assertIsNone(execution_module.parent_action(failed_record))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = state_store_module.StateStore(root / "sessions")
            prepared_store = prepared_store_module.PreparedContractStore(root / "prepared")
            unknown = protocol.prepare_dispatch(
                self.contract(),
                "session-unknown",
                state_store=store,
                prepared_store=prepared_store,
                task_id_factory=lambda: "sg-task-unknown",
            )
            payload = self.pre_payload(unknown)
            payload["session_id"] = "session-unknown"
            hook.handle_hook(payload, store)
            hook.handle_hook(
                {
                    "session_id": "session-unknown",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "spawn_agent",
                    "tool_use_id": "spawn-call-1",
                    "tool_response": {"wrapper": {"agent_id": "must-not-bind"}},
                },
                store,
            )
            state = store.read("session-unknown")
            record = self.current_execution(state, unknown["task_id"])
            self.assertIsNone(execution_module.spawn_observation(record))
            self.assertIsNone(execution_module.parent_action(record))
            self.assertEqual(store.read("session-unknown")["agents"], {})

    def test_spawn_retry_counts_are_claimed_before_call_and_bounded(self):
        prepared = self.prepare()
        hook.handle_hook(self.pre_payload(prepared), self.store)
        hook.handle_hook(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-1",
                "tool_response": {"isError": True},
            },
            self.store,
        )
        self.observe_spawn_in_dispatch_domain(prepared, {"isError": True})

        retry = protocol.prepare_spawn_retry(
            self.contract(),
            "session-1",
            prepared["task_id"],
            state_store=self.store,
            prepared_store=self.prepared_store(),
        )
        retry_payload = self.pre_payload(retry)
        retry_payload["tool_use_id"] = "spawn-call-2"
        allowed = hook.handle_hook(retry_payload, self.store)
        self.assertEqual(allowed["hookSpecificOutput"]["permissionDecision"], "allow")
        state = self.store.read("session-1")
        claimed = self.current_execution(state, prepared["task_id"])
        self.assertEqual(claimed["spawn_retry_count"], 1)
        self.assertIsNone(execution_module.spawn_observation(claimed))

        hook.handle_hook(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-2",
                "tool_response": {"status": "failed"},
            },
            self.store,
        )
        self.observe_spawn_in_dispatch_domain(retry, {"status": "failed"})
        state = self.store.read("session-1")
        failed_once = self.current_execution(state, prepared["task_id"])
        self.assertEqual(failed_once["spawn_retry_count"], 1)
        self.assertEqual(execution_module.parent_action(failed_once), "ask_user")

        with self.assertRaisesRegex(errors.DispatchPreparationError, "明确授权"):
            protocol.prepare_spawn_retry(
                self.contract(),
                "session-1",
                prepared["task_id"],
                state_store=self.store,
                prepared_store=self.prepared_store(),
            )

        final_retry = protocol.prepare_spawn_retry(
            self.contract(),
            "session-1",
            prepared["task_id"],
            authorized=True,
            state_store=self.store,
            prepared_store=self.prepared_store(),
        )
        final_payload = self.pre_payload(final_retry)
        final_payload["tool_use_id"] = "spawn-call-3"
        hook.handle_hook(final_payload, self.store)
        state = self.store.read("session-1")
        claimed_final = self.current_execution(state, prepared["task_id"])
        self.assertEqual(claimed_final["spawn_retry_count"], 2)

        hook.handle_hook(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-3",
                "tool_response": {"is_error": True},
            },
            self.store,
        )
        self.observe_spawn_in_dispatch_domain(final_retry, {"is_error": True})
        state = self.store.read("session-1")
        exhausted = self.current_execution(state, prepared["task_id"])
        self.assertEqual(execution_module.execution_status(exhausted), "stopped")
        self.assertEqual(execution_module.parent_action(exhausted), "decide_disposition")
        self.assertNotIn("spawn_close_reason", exhausted)
        self.assertNotIn(
            f"{prepared['task_id']}:1",
            state["tombstones"],
        )
        self.assertFalse(execution_module.execution_is_closed(exhausted))
        self.assertEqual(
            [
                (record["task_id"], record["attempt"])
                for record in views.action_required_records(state)
            ],
            [(prepared["task_id"], 1)],
        )
        snapshot, issues, incomplete = views.work_item_decision_snapshot(
            state,
            prepared["task_id"],
        )
        self.assertEqual(snapshot["lifecycle"], "open")
        self.assertTrue(snapshot["action_required"])
        self.assertFalse(incomplete)
        self.assertEqual(issues, [])
        with self.assertRaisesRegex(errors.DispatchPreparationError, "已经耗尽"):
            protocol.prepare_spawn_retry(
                self.contract(),
                "session-1",
                prepared["task_id"],
                authorized=True,
                state_store=self.store,
                prepared_store=self.prepared_store(),
            )

    def test_unknown_retry_cannot_be_reused_or_turned_into_failed(self):
        prepared = self.prepare()
        hook.handle_hook(self.pre_payload(prepared), self.store)
        hook.handle_hook(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-1",
                "tool_response": {"isError": True},
            },
            self.store,
        )
        self.observe_spawn_in_dispatch_domain(prepared, {"isError": True})
        retry = protocol.prepare_spawn_retry(
            self.contract(),
            "session-1",
            prepared["task_id"],
            state_store=self.store,
            prepared_store=self.prepared_store(),
        )
        payload = self.pre_payload(retry)
        payload["tool_use_id"] = "spawn-call-2"
        hook.handle_hook(payload, self.store)
        hook.handle_hook(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "spawn-call-2",
                "tool_response": {"unexpected": "shape"},
            },
            self.store,
        )
        self.observe_spawn_in_dispatch_domain(retry, {"unexpected": "shape"})

        state = self.store.read("session-1")
        record = self.current_execution(state, prepared["task_id"])
        self.assertEqual(execution_module.spawn_observation(record), "unknown")
        self.assertEqual(record["spawn_retry_count"], 1)
        self.assertEqual(execution_module.parent_action(record), "reconcile")
        with self.assertRaisesRegex(errors.DispatchPreparationError, "明确 failed"):
            protocol.prepare_spawn_retry(
                self.contract(),
                "session-1",
                prepared["task_id"],
                authorized=True,
                state_store=self.store,
                prepared_store=self.prepared_store(),
            )

    def test_retry_requires_reliable_not_created_fact(self):
        prepared = self.prepare()
        hook.handle_hook(self.pre_payload(prepared), self.store)
        with self.assertRaises(errors.StateValidationError):
            self.store.update(
                "session-1",
                lambda state: state["tasks"][prepared["task_id"]]["executions"]["1"].update(
                    {"spawn_observation": "failed", "identity_status": "unconfirmed"}
                ),
            )

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

        result = hook.handle_hook(payload, self.store)

        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertEqual(result["hookSpecificOutput"]["updatedInput"], payload["tool_input"])
        self.assertEqual(self.store.read("session-1")["tasks"], {})

    def test_malformed_governed_name_is_rejected_without_reading_business_body(self):
        payload = {
            "session_id": "session-1",
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "malformed-call",
            "tool_input": {
                "task_name": "sg_standard_malformed_task",
                "message": "【目标】正文不再是治理契约来源",
                "fork_turns": "none",
            },
        }

        result = hook.handle_hook(payload, self.store)

        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("task_ref", result["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.store.read("session-1")["tasks"], {})

    def test_governed_spawn_does_not_fail_open_when_state_store_is_unavailable(self):
        class FailingStore:
            last_warning = None

            def read(self, *args, **kwargs):
                raise errors.StateWriteError("state unavailable")

            def update(self, *args, **kwargs):
                raise errors.StateWriteError("state unavailable")

            def compare_and_set(self, *args, **kwargs):
                raise errors.StateWriteError("state unavailable")

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

        result = hook.handle_hook(payload, FailingStore())

        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("硬门禁", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_unknown_nested_response_shape_is_not_recursively_guessed(self):
        observation = platform.adapt_spawn_response(
            {"wrapper": {"agent_id": "guessed-agent", "status": "failed"}}
        )

        self.assertEqual(observation.observation, "unknown")
        self.assertIsNone(observation.canonical_target)


if __name__ == "__main__":
    unittest.main()
