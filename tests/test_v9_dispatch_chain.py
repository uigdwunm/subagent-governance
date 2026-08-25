#!/usr/bin/env python3
"""Vertical acceptance coverage for the state-v9 dispatch cutover."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import governance_contracts as contracts
from scripts import governance_dispatch as dispatch
from scripts import governance_diagnostics as diagnostics
from scripts import governance_hook as hook
from scripts import governance_protocol as protocol
from scripts import governance_semantics as semantics
from scripts import governance_state as state_domain
from scripts import governance_state_store as state_store_module
from scripts import governance_store_support as store_support
from scripts.governance_errors import StateWriteError
from tests.schema_validation import validate_instance


class V9DispatchChainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = state_store_module.StateStore(self.root / "sessions")
        self.session_id = "v9-session"

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def contract(**overrides):
        value = {
            "profile": "standard",
            "objective": "Implement the exact-target dispatch chain",
            "scope": ["scripts", "tests"],
            "completion": ["The v9 dispatch tests pass"],
            "context": {
                "summary": "Use the current checkout only.",
                "paths": ["scripts/governance_dispatch.py"],
            },
            "spawn": {"fork_turns": "none"},
        }
        value.update(overrides)
        return value

    def prepare(self, **overrides):
        return protocol.prepare_dispatch(
            self.contract(**overrides),
            self.session_id,
            state_store=self.store,
            task_id_factory=lambda: "sg-task-v9",
            now=100,
        )

    def claim(self, prepared, *, tool_use_id="native-call-1", now=101):
        payload = {
            "session_id": self.session_id,
            "hook_event_name": "PreToolUse",
            "tool_name": "collaboration.spawn_agent",
            "tool_use_id": tool_use_id,
            "tool_input": copy.deepcopy(prepared["spawn_args"]),
            "now": now,
        }
        result = hook.handle_hook(payload, self.store)
        self.assertEqual(
            result["hookSpecificOutput"]["permissionDecision"], "allow", result
        )
        return result

    def test_contract_v2_defaults_strict_profile_and_business_digest(self):
        standard = contracts.contract_from_input(self.contract())
        self.assertEqual(standard.profile, "standard")
        self.assertEqual(standard.forbidden_scope, [])
        self.assertEqual(standard.evidence, [])
        self.assertEqual(
            standard.spawn,
            {"fork_turns": "none", "model": None, "reasoning_effort": None},
        )

        changed_spawn = contracts.contract_from_input(
            self.contract(
                spawn={
                    "fork_turns": "all",
                    "model": "gpt-5.6-terra",
                    "reasoning_effort": "high",
                }
            )
        )
        self.assertEqual(
            contracts.contract_digest(standard),
            contracts.contract_digest(changed_spawn),
        )
        self.assertNotEqual(
            contracts.spawn_digest(standard), contracts.spawn_digest(changed_spawn)
        )

        with self.assertRaisesRegex(ValueError, "strict"):
            contracts.contract_from_input(
                self.contract(profile="strict", forbidden_scope=[], evidence=[])
            )
        with self.assertRaisesRegex(ValueError, "unknown"):
            contracts.contract_from_input({**self.contract(), "task_features": {}})

    def test_contract_v2_input_schema_matches_required_defaults_and_strict_boundary(self):
        schema = semantics.MACHINE_SEMANTICS["$defs"]["task_contract_input"]
        minimal = {
            "objective": "Minimal contract",
            "scope": ["tests"],
            "completion": ["valid"],
        }
        self.assertEqual(
            validate_instance(
                minimal, schema, root_schema=semantics.MACHINE_SEMANTICS
            ),
            [],
        )
        for invalid in (
            {**minimal, "future": True},
            {**minimal, "scope": []},
            {
                **minimal,
                "profile": "strict",
                "forbidden_scope": [],
                "evidence": [],
            },
        ):
            self.assertTrue(
                validate_instance(
                    invalid, schema, root_schema=semantics.MACHINE_SEMANTICS
                )
            )

    def test_prepare_writes_one_strict_v9_ledger_and_schema_accepts_it(self):
        prepared = self.prepare()
        state = self.store.read(self.session_id)
        self.assertEqual(
            set(state), {"state_format_version", "session_id", "tasks"}
        )
        self.assertEqual(state["state_format_version"], 9)
        task = state["tasks"][prepared["task_id"]]
        self.assertEqual(task["phase"], "prepared")
        self.assertEqual(task["task_ref"], prepared["task_ref"])
        self.assertIn("prepared", task)
        def keys(value):
            if isinstance(value, dict):
                return set(value) | set().union(*(keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(keys(item) for item in value)) if value else set()
            return set()

        persisted_keys = keys(state)
        for removed in (
            "attempt",
            "agents",
            "groups",
            "tombstones",
            "pending_action",
            "post_receipt",
        ):
            self.assertNotIn(removed, persisted_keys)
        self.assertEqual(state_domain.validate_current_state_format(state), [])
        self.assertEqual(
            validate_instance(
                state,
                semantics.MACHINE_SEMANTICS["$defs"]["session_ledger"],
                root_schema=semantics.MACHINE_SEMANTICS,
            ),
            [],
        )

    def test_required_type_and_unknown_mutations_are_rejected_by_runtime_and_schema(self):
        prepared = self.prepare()
        baseline = self.store.read(self.session_id)
        mutations = {
            "version_v8": lambda value: value.update(state_format_version=8),
            "unknown_root": lambda value: value.update(agents={}),
            "missing_tasks": lambda value: value.pop("tasks"),
            "attempt_field": lambda value: value["tasks"][prepared["task_id"]].update(attempt=1),
            "managed_false": lambda value: value["tasks"][prepared["task_id"]].update(managed=False),
            "unknown_contract": lambda value: value["tasks"][prepared["task_id"]]["prepared"]["contract"].update(task_features={}),
            "wrong_timestamp_type": lambda value: value["tasks"][prepared["task_id"]].update(updated_at=True),
        }
        schema = semantics.MACHINE_SEMANTICS["$defs"]["session_ledger"]
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                value = copy.deepcopy(baseline)
                mutate(value)
                self.assertTrue(state_domain.validate_current_state_format(value))
                self.assertTrue(
                    validate_instance(
                        value, schema, root_schema=semantics.MACHINE_SEMANTICS
                    )
                )

    def test_pre_claim_is_atomic_in_the_same_ledger(self):
        prepared = self.prepare()
        self.claim(prepared)
        task = self.store.read(self.session_id)["tasks"][prepared["task_id"]]
        self.assertEqual(task["phase"], "claimed")
        self.assertEqual(task["claimed_tool_use_id"], "native-call-1")
        self.assertEqual(task["claimed_at"], 101)
        self.assertIn("prepared", task)
        self.assertFalse((self.root / "prepared").exists())

    def test_unmanaged_spawn_is_inert_even_when_storage_is_unavailable(self):
        missing = self.root / "must-not-exist"
        payload = {
            "session_id": self.session_id,
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "native-unmanaged",
            "tool_input": {
                "task_name": "plain_native_task",
                "message": "native",
                "fork_turns": "none",
            },
        }
        with mock.patch.object(state_store_module, "StateStore", side_effect=OSError("no")):
            result = hook.handle_hook(payload)
        self.assertIsNone(result)
        self.assertFalse(missing.exists())

    def test_exact_committed_prepare_and_claim_survive_reported_write_error(self):
        with tempfile.TemporaryDirectory() as directory:
            store = state_store_module.StateStore(Path(directory))
            original_update = store.update

            def persist_then_raise(*args, **kwargs):
                original_update(*args, **kwargs)
                raise StateWriteError("injected after commit")

            store.update = persist_then_raise
            prepared = protocol.prepare_dispatch(
                self.contract(), self.session_id, state_store=store,
                task_id_factory=lambda: "persisted-prepare", now=100,
            )
            self.assertIn("warning", prepared)
            task = store.read(self.session_id)["tasks"][prepared["task_id"]]
            self.assertEqual(task["phase"], "prepared")

            result = hook.handle_hook(
                {
                    "session_id": self.session_id,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "spawn_agent",
                    "tool_use_id": "persisted-claim",
                    "tool_input": prepared["spawn_args"],
                    "now": 101,
                },
                store,
            )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
            self.assertIn("claimed_after_write_error", result["hookSpecificOutput"]["additionalContext"])
            task = store.read(self.session_id)["tasks"][prepared["task_id"]]
            self.assertEqual(task["phase"], "claimed")

    def test_confirm_first_bind_wins_same_replay_is_idempotent(self):
        prepared = self.prepare()
        self.claim(prepared)
        request = {
            "task_id": prepared["task_id"],
            "task_ref": prepared["task_ref"],
            "target": "/root/exact-native-target",
        }
        first = dispatch.confirm_dispatch(
            self.session_id, request, state_store=self.store, now=102
        )
        replay = dispatch.confirm_dispatch(
            self.session_id, request, state_store=self.store, now=999
        )
        self.assertEqual(first["result"], "bound")
        self.assertEqual(replay["result"], "already_bound")
        task = self.store.read(self.session_id)["tasks"][prepared["task_id"]]
        self.assertEqual(task["phase"], "bound")
        self.assertEqual(task["target"], request["target"])
        self.assertEqual(task["bound_at"], 102)
        self.assertEqual(task["updated_at"], 102)
        self.assertNotIn("prepared", task)

    def test_conflicting_confirm_enters_reconcile_and_keeps_first_identity(self):
        prepared = self.prepare()
        self.claim(prepared)
        first = {
            "task_id": prepared["task_id"],
            "task_ref": prepared["task_ref"],
            "target": "/root/first",
        }
        dispatch.confirm_dispatch(
            self.session_id, first, state_store=self.store, now=102
        )
        conflict = {**first, "target": "/root/conflict"}
        result = dispatch.confirm_dispatch(
            self.session_id, conflict, state_store=self.store, now=103
        )
        self.assertEqual(result["result"], "reconcile")
        task = self.store.read(self.session_id)["tasks"][prepared["task_id"]]
        self.assertEqual(task["phase"], "reconcile")
        self.assertEqual(task["target"], "/root/first")
        self.assertEqual(task["reconcile"]["code"], "dispatch_target_conflict")
        self.assertNotIn("/root/conflict", json.dumps(task))

    def test_confirm_identity_mismatch_enters_reconcile_without_binding(self):
        prepared = self.prepare()
        self.claim(prepared)
        result = dispatch.confirm_dispatch(
            self.session_id,
            {
                "task_id": prepared["task_id"],
                "task_ref": "deadbeefdead",
                "target": "/root/untrusted",
            },
            state_store=self.store,
            now=102,
        )
        self.assertEqual(result["result"], "reconcile")
        task = self.store.read(self.session_id)["tasks"][prepared["task_id"]]
        self.assertEqual(task["phase"], "reconcile")
        self.assertNotIn("target", task)
        self.assertEqual(task["reconcile"]["code"], "dispatch_identity_mismatch")

    def test_real_target_shape_distinguishes_missing_claim_from_bound_identity(self):
        task_id = "sg-8b0fd6192a56b7afa8acf7843c9bd100"
        target = "/root/sg_standard_v2_t_d3386869e8aa"
        prepared = protocol.prepare_dispatch(
            self.contract(objective="V2"),
            self.session_id,
            state_store=self.store,
            task_id_factory=lambda: task_id,
            now=100,
        )
        self.assertEqual(prepared["task_ref"], "d3386869e8aa")
        self.assertEqual(prepared["spawn_args"]["task_name"], target.removeprefix("/root/"))
        confirmation = {
            "task_id": task_id,
            "task_ref": prepared["task_ref"],
            "target": target,
        }

        result = dispatch.confirm_dispatch(
            self.session_id, confirmation, state_store=self.store, now=102
        )

        self.assertEqual(result["result"], "reconcile")
        task = self.store.read(self.session_id)["tasks"][task_id]
        self.assertEqual(task["reconcile"]["code"], "dispatch_claim_missing")
        self.assertNotIn("target", task)

        claimed_session = "v9-session-with-claim"
        claimed = protocol.prepare_dispatch(
            self.contract(objective="V2"),
            claimed_session,
            state_store=self.store,
            task_id_factory=lambda: task_id,
            now=100,
        )
        claim_result = hook.handle_hook(
            {
                "session_id": claimed_session,
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": "native-call-real-shape",
                "tool_input": claimed["spawn_args"],
                "now": 101,
            },
            self.store,
        )
        self.assertEqual(
            claim_result["hookSpecificOutput"]["permissionDecision"], "allow"
        )
        self.assertEqual(
            self.store.read(claimed_session)["tasks"][task_id]["phase"], "claimed"
        )
        bound = dispatch.confirm_dispatch(
            claimed_session, confirmation, state_store=self.store, now=102
        )
        self.assertEqual(bound["result"], "bound")
        self.assertEqual(
            self.store.read(claimed_session)["tasks"][task_id]["target"], target
        )

    def test_crash_gap_stays_claimed_unbound_and_is_not_retried_or_inferred(self):
        prepared = self.prepare()
        self.claim(prepared)
        state_before = self.store.read(self.session_id)
        task = state_before["tasks"][prepared["task_id"]]
        self.assertEqual(task["phase"], "claimed")
        self.assertNotIn("target", task)

        status = diagnostics.status(self.session_id, self.root)
        self.assertEqual(status["tasks"][0]["next_action"], "confirm_exact_target")
        self.assertNotIn("retry", json.dumps(status).lower())
        self.assertEqual(self.store.read(self.session_id), state_before)

    def test_explicit_failed_closes_and_unknown_reconciles_without_retry(self):
        for result, expected_phase in (("failed", "closed"), ("unknown", "reconcile")):
            with self.subTest(result=result):
                with tempfile.TemporaryDirectory() as directory:
                    store = state_store_module.StateStore(Path(directory))
                    prepared = protocol.prepare_dispatch(
                        self.contract(), self.session_id, state_store=store,
                        task_id_factory=lambda: f"dispatch-{result}", now=100,
                    )
                    hook.handle_hook(
                        {
                            "session_id": self.session_id,
                            "hook_event_name": "PreToolUse",
                            "tool_name": "spawn_agent",
                            "tool_use_id": f"call-{result}",
                            "tool_input": prepared["spawn_args"],
                            "now": 101,
                        },
                        store,
                    )
                    dispatch.record_dispatch_result(
                        self.session_id,
                        {
                            "task_id": prepared["task_id"],
                            "task_ref": prepared["task_ref"],
                            "result": result,
                        },
                        state_store=store,
                        now=102,
                    )
                    task = store.read(self.session_id)["tasks"][prepared["task_id"]]
                    self.assertEqual(task["phase"], expected_phase)
                    self.assertNotIn("prepared", task)
                    self.assertNotIn("target", task)
                    self.assertNotIn("retry", json.dumps(task).lower())

    def test_session_start_is_exact_read_only_and_missing_root_is_inert(self):
        prepared = self.prepare()
        state_path, lock_path = self.store._paths(self.session_id)
        lock_path.unlink()
        before = (state_path.read_bytes(), state_path.stat().st_mtime_ns)
        with mock.patch.dict(
            os.environ, {"SUBAGENT_GOVERNANCE_DATA": str(self.root)}, clear=False
        ):
            result = hook.handle_hook(
                {"hook_event_name": "SessionStart", "session_id": self.session_id}
            )
        self.assertIn(prepared["task_ref"], result["hookSpecificOutput"]["additionalContext"])
        self.assertFalse(lock_path.exists())
        self.assertEqual((state_path.read_bytes(), state_path.stat().st_mtime_ns), before)

        missing = self.root / "missing"
        with mock.patch.dict(
            os.environ, {"SUBAGENT_GOVERNANCE_DATA": str(missing)}, clear=False
        ):
            self.assertIsNone(
                hook.handle_hook(
                    {"hook_event_name": "SessionStart", "session_id": "missing"}
                )
            )
        self.assertFalse(missing.exists())

    def test_default_namespace_is_state_v9_and_v8_is_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory)
            old_root = plugin_root / "state-v8"
            old_root.mkdir()
            old_file = old_root / "legacy.json"
            old_file.write_text('{"state_format_version": 8}', encoding="utf-8")
            before = (old_file.read_bytes(), old_file.stat().st_mtime_ns)
            with mock.patch.dict(
                os.environ,
                {"SUBAGENT_GOVERNANCE_DATA": "", "PLUGIN_DATA": str(plugin_root)},
            ):
                self.assertEqual(
                    store_support.data_root_path(state_store_module.__file__),
                    plugin_root / "state-v9",
                )
                state_store_module.StateStore().read("current-v9")
            self.assertEqual(
                (old_file.read_bytes(), old_file.stat().st_mtime_ns), before
            )


if __name__ == "__main__":
    unittest.main()
