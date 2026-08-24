"""P12-A bounded governed-spawn PostToolUse diagnostics."""
from __future__ import annotations

import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts import governance_diagnostics, governance_hook, governance_platform
from scripts import governance_protocol as protocol
from scripts import governance_spawn_post_probe as probe
from scripts.governance_prepared_store import PreparedContractStore
from scripts.governance_state_store import StateStore


def _contract() -> dict[str, object]:
    return {
        "semantic_name": "P12 A probe", "requested_mode": "standard",
        "task_features": {"risk": "low", "read_only": True, "writes_files": False,
                          "destructive": False, "production": False, "concurrent_write": False},
        "objective": "record bounded spawn Post diagnostics", "background": "P12-A",
        "work_scope": ["tests"], "forbidden_scope": ["canonical state changes"],
        "completion_conditions": ["receipt"], "evidence_requirements": ["unittest"],
        "relevant_files": [], "context_manifest": {"mode": "none"}, "current_state": None,
        "model": None, "reasoning_effort": None, "context_strategy": "isolated",
        "context_turns": None, "context_reason": None,
    }


class SpawnPostProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = StateStore(root / "state-v8" / "sessions")
        self.prepared_store = PreparedContractStore(root / "state-v8" / "prepared")
        self.session_id = "p12-a-session"
        self.now = int(time.time())
        self.dispatch = protocol.prepare_dispatch(
            _contract(), self.session_id, state_store=self.store,
            prepared_store=self.prepared_store, task_id_factory=lambda: "p12-a-task", now=self.now,
        )
        self.tool_use_id = "p12-a-tool-use"
        result = governance_hook.handle_hook({
            "hook_event_name": "PreToolUse", "session_id": self.session_id,
            "tool_name": "spawn_agent", "tool_use_id": self.tool_use_id,
            "tool_input": self.dispatch["spawn_args"], "now": self.now,
        }, self.store)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        self.pre_post_state = copy.deepcopy(self.store.read(self.session_id))

    def tearDown(self):
        self.temp.cleanup()

    def _post(self, *, tool_name="spawn_agent", tool_use_id=None, response=None):
        return governance_hook.handle_hook({
            "hook_event_name": "PostToolUse", "session_id": self.session_id,
            "tool_name": tool_name, "tool_use_id": self.tool_use_id if tool_use_id is None else tool_use_id,
            "tool_response": response, "now": self.now + 1,
        }, self.store)

    def _receipt(self):
        return probe.SpawnPostProbeStore(probe.probe_root_for_store(self.store)).lookup_receipt(
            self.session_id, self.tool_use_id, now=self.now + 1,
        )

    def test_marker_and_receipt_are_exact_bounded_and_private(self):
        storage = probe.SpawnPostProbeStore(Path(self.temp.name) / "private")
        marker = probe.marker_record(
            "session", "id", "task", 1, "0123456789ab", "initial_spawn", 0, claimed_at=100,
        )
        storage.record_marker(marker, now=100)
        storage.record_marker(marker, now=101)
        conflicting_owners = [
            probe.marker_record("session", "id", "other-task", 1, "0123456789ab", "initial_spawn", 0, claimed_at=100),
            probe.marker_record("session", "id", "task", 2, "0123456789ab", "initial_spawn", 0, claimed_at=100),
            probe.marker_record("session", "id", "task", 1, "0123456789ac", "initial_spawn", 0, claimed_at=100),
            probe.marker_record("session", "id", "task", 1, "0123456789ab", "spawn_retry", 1, claimed_at=100),
            probe.marker_record("session", "id", "task", 1, "0123456789ab", "initial_spawn", 1, claimed_at=100),
            probe.marker_record("session", "id", "task", 1, "0123456789ab", "initial_spawn", 0, claimed_at=101),
        ]
        for conflicting in conflicting_owners:
            with self.subTest(conflicting=conflicting):
                with self.assertRaises(Exception):
                    storage.record_marker(conflicting, now=101)
        self.assertEqual(storage.lookup_marker("session", "id", now=101), marker)
        self.assertIsNone(storage.lookup_marker("session", "different", now=101))
        self.assertIsNone(storage.lookup_marker("session", "id", now=marker["expires_at"] + 1))
        receipt = probe.receipt_record(marker, "recognized", "exact_probe_marker", recorded_at=101)
        self.assertEqual(receipt["claim_check"], "not_checked")
        storage.record_receipt(receipt, now=101, tool_use_id="id")
        stored = next((storage.receipts_root).glob("*.json")).read_text(encoding="utf-8")
        for forbidden in ("target", "message", "summary", "final", "transcript", "spawn_agent"):
            self.assertNotIn(forbidden, stored)
        with self.assertRaises(ValueError):
            storage.record_receipt({**receipt, "message": "secret"}, now=101, tool_use_id="id")
        with self.assertRaises(Exception):
            storage.record_receipt({**receipt, "task_id": "other"}, now=101, tool_use_id="id")

    def test_marker_and_receipt_enforce_capacity_and_expiry(self):
        storage = probe.SpawnPostProbeStore(Path(self.temp.name) / "capacity")
        first = probe.marker_record("session", "one", "task", 1, "0123456789ab", "initial_spawn", 0, claimed_at=100)
        second = probe.marker_record("session", "two", "task", 1, "0123456789ab", "initial_spawn", 0, claimed_at=100)
        with mock.patch.object(probe, "MAX_PROBE_RECORDS", 1):
            storage.record_marker(first, now=100)
            with self.assertRaises(Exception):
                storage.record_marker(second, now=100)
            self.assertEqual(storage.cleanup_expired_markers(now=first["expires_at"] + 1), 1)
            storage.record_marker(second, now=100)
        receipt = probe.receipt_record(second, "recognized", "exact_probe_marker", recorded_at=100)
        storage.record_receipt(receipt, now=100, tool_use_id="two")
        self.assertIsNotNone(storage.lookup_receipt("session", "two", now=receipt["updated_at"] + probe.RECEIPT_TTL_SECONDS))
        self.assertIsNone(storage.lookup_receipt("session", "two", now=receipt["updated_at"] + probe.RECEIPT_TTL_SECONDS + 1))
        self.assertEqual(storage.cleanup_expired_receipts(now=receipt["recorded_at"] + probe.RECEIPT_TTL_SECONDS), 0)
        self.assertEqual(storage.cleanup_expired_receipts(now=receipt["recorded_at"] + probe.RECEIPT_TTL_SECONDS + 1), 1)

    def test_receipt_is_monotonic_and_terminal_records_cannot_reset(self):
        storage = probe.SpawnPostProbeStore(Path(self.temp.name) / "monotonic")
        marker = probe.marker_record("session", "id", "task", 1, "0123456789ab", "initial_spawn", 0, claimed_at=100)
        received = probe.receipt_record(marker, "recognized", "exact_probe_marker", recorded_at=100)
        storage.record_receipt(received, now=100, tool_use_id="id")
        checked = {**received, "claim_check": "matched", "handler_stage": "claim_checked", "updated_at": 101}
        storage.record_receipt(checked, now=101, tool_use_id="id")
        shaped = {**checked, "response_shape": "top_level_object", "handler_stage": "shape_classified", "updated_at": 102}
        storage.record_receipt(shaped, now=102, tool_use_id="id")
        completed = {**shaped, "handler_stage": "completed", "updated_at": 103}
        storage.record_receipt(completed, now=103, tool_use_id="id")
        for invalid in (
            {**received, "updated_at": 104},
            {**completed, "handler_stage": "handler_failed", "updated_at": 104},
            {**completed, "updated_at": 102},
            {**completed, "tool_name_classification": "unrecognized", "updated_at": 104},
            {**completed, "admission_source": "recognized_prepared", "updated_at": 104},
            {**completed, "recorded_at": 101, "updated_at": 104},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(Exception):
                    storage.record_receipt(invalid, now=104, tool_use_id="id")
        failed_marker = probe.marker_record("session", "id-2", "task", 1, "0123456789ab", "initial_spawn", 0, claimed_at=100)
        failed = probe.receipt_record(failed_marker, "recognized", "exact_probe_marker", recorded_at=100)
        storage.record_receipt(failed, now=100, tool_use_id="id-2")
        storage.record_receipt({**failed, "claim_check": "validation_failed", "handler_stage": "handler_failed", "updated_at": 101}, now=101, tool_use_id="id-2")
        with self.assertRaises(Exception):
            storage.record_receipt({**failed, "updated_at": 102}, now=102, tool_use_id="id-2")

    def test_same_id_recognized_spawn_records_shape_and_keeps_legacy_canonical_transition(self):
        self.assertIsNone(self._post(response={"success": True}))
        receipt = self._receipt()
        self.assertEqual(receipt["tool_name_classification"], "recognized")
        self.assertEqual(receipt["admission_source"], "exact_probe_marker")
        self.assertEqual(receipt["claim_check"], "matched")
        self.assertEqual(receipt["response_shape"], "top_level_object")
        self.assertEqual(receipt["handler_stage"], "completed")
        execution = self.store.read(self.session_id)["tasks"]["p12-a-task"]["executions"]["1"]
        self.assertEqual(execution["dispatch_record"]["dispatch_state"], "acknowledged")
        self.assertEqual(execution["closure_record"]["parent_action"], "reconcile")

    def test_unknown_name_only_enters_on_exact_marker_and_preserves_state(self):
        self.assertIsNone(self._post(tool_name="future.renamed_spawn", response="not-json"))
        receipt = self._receipt()
        self.assertEqual(receipt["tool_name_classification"], "unrecognized")
        self.assertEqual(receipt["admission_source"], "exact_probe_marker")
        self.assertEqual(receipt["response_shape"], "json_decode_failed")
        self.assertEqual(self.store.read(self.session_id), self.pre_post_state)

    def test_recognized_marker_miss_uses_only_exact_prepared_fallback(self):
        marker_store = probe.SpawnPostProbeStore(probe.probe_root_for_store(self.store))
        marker_store.remove_marker(self.session_id, self.tool_use_id)
        self.assertIsNone(self._post(response={"nested": {"ignored": True}}))
        receipt = self._receipt()
        self.assertEqual(receipt["admission_source"], "recognized_prepared")
        self.assertEqual(receipt["claim_check"], "matched")
        execution = self.store.read(self.session_id)["tasks"]["p12-a-task"]["executions"]["1"]
        self.assertEqual(execution["dispatch_record"]["dispatch_state"], "indeterminate")

    def test_recognized_probe_stage_failure_warns_but_keeps_legacy_transition(self):
        with mock.patch.object(
            probe.SpawnPostProbeStore, "record_receipt",
            side_effect=[None, None, OSError("stage write failed")],
        ):
            result = self._post(response={"success": True})
        self.assertTrue(result["continue"])
        self.assertEqual(result["systemMessage"], "spawn_post_probe_handler_failed")
        execution = self.store.read(self.session_id)["tasks"]["p12-a-task"]["executions"]["1"]
        self.assertEqual(execution["dispatch_record"]["dispatch_state"], "acknowledged")

    def test_recognized_merges_probe_legacy_and_store_warnings(self):
        original = governance_hook.observe_spawn_post_tool

        def legacy(*args, **kwargs):
            original(*args, **kwargs)
            args[4].last_warning = "store-warning"
            return "legacy-warning"

        with mock.patch.object(governance_hook, "_record_spawn_probe_post", return_value="probe-warning"), mock.patch.object(
            governance_hook, "observe_spawn_post_tool", side_effect=legacy,
        ):
            result = self._post(response={"success": True})
        self.assertTrue(result["continue"])
        self.assertEqual(result["systemMessage"], "probe-warning；legacy-warning；store-warning")
        execution = self.store.read(self.session_id)["tasks"]["p12-a-task"]["executions"]["1"]
        self.assertEqual(execution["dispatch_record"]["dispatch_state"], "acknowledged")

    def test_duplicate_post_cannot_reset_completed_receipt(self):
        self.assertIsNone(self._post(response={"success": True}))
        receipt = copy.deepcopy(self._receipt())
        before = copy.deepcopy(self.store.read(self.session_id))
        result = self._post(response={"success": True})
        self.assertTrue(result["continue"])
        self.assertIn("spawn_post_probe_handler_failed", result["systemMessage"])
        self.assertEqual(self._receipt(), receipt)
        self.assertEqual(self.store.read(self.session_id), before)

    def test_missing_or_different_id_and_unknown_marker_miss_are_fully_inert(self):
        with mock.patch.object(governance_hook, "_store_or_unavailable") as constructor:
            self.assertIsNone(self._post(tool_name="future.renamed_spawn", tool_use_id="different"))
            self.assertIsNone(self._post(tool_name="future.renamed_spawn", tool_use_id=""))
        constructor.assert_not_called()
        self.assertIsNone(probe.SpawnPostProbeStore(probe.probe_root_for_store(self.store)).lookup_receipt(
            self.session_id, "different", now=self.now + 1,
        ))
        self.assertEqual(self.store.read(self.session_id), self.pre_post_state)

    def test_marker_hit_records_prepared_missing_without_canonical_mutation(self):
        self.prepared_store.delete(self.session_id, self.dispatch["task_ref"])
        self.assertIsNone(self._post(response={"success": True}))
        receipt = self._receipt()
        self.assertEqual(receipt["claim_check"], "prepared_missing")
        self.assertEqual(receipt["response_shape"], "not_checked")
        self.assertEqual(self.store.read(self.session_id), self.pre_post_state)

    def test_state_mismatch_is_bounded_and_does_not_apply_any_post_transition(self):
        def mismatch(state):
            state["tasks"]["p12-a-task"]["executions"]["1"]["task_ref"] = "0123456789ac"
        self.store.update(self.session_id, mismatch)
        before = copy.deepcopy(self.store.read(self.session_id))
        result = self._post(response={"success": True})
        self.assertTrue(result["continue"])
        self.assertEqual(self._receipt()["claim_check"], "state_mismatch")
        self.assertEqual(self.store.read(self.session_id), before)

    def test_marker_failure_is_fail_open_and_uses_only_fixed_code(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state-v8" / "sessions")
            prepared_store = PreparedContractStore(Path(directory) / "state-v8" / "prepared")
            now = int(time.time())
            dispatch = protocol.prepare_dispatch(_contract(), "failure", state_store=store, prepared_store=prepared_store, now=now)
            with mock.patch("scripts.governance_dispatch.SpawnPostProbeStore.record_marker", side_effect=OSError("private detail")):
                result = governance_hook.handle_hook({
                    "hook_event_name": "PreToolUse", "session_id": "failure", "tool_name": "spawn_agent",
                    "tool_use_id": "failure-id", "tool_input": dispatch["spawn_args"], "now": now,
                }, store)
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
            self.assertIn("spawn_post_probe_unavailable", result["hookSpecificOutput"]["additionalContext"])
            self.assertNotIn("private detail", result["hookSpecificOutput"]["additionalContext"])

    def test_response_shape_is_top_level_only(self):
        cases = [(None, "empty"), ("", "empty"), ("bad json", "json_decode_failed"),
                 (["x"], "non_object"), ({"error": "opaque"}, "explicit_error"),
                 ({"nested": {"success": True}}, "top_level_object")]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(governance_platform.spawn_response_shape(raw), expected)

    def test_diagnostics_projects_only_the_probe_whitelist(self):
        self._post(response={"content": {"target": "/root/private"}})
        document, status = governance_diagnostics.diagnose(self.session_id, self.store.root.parent)
        self.assertEqual(status, 0)
        projected = document["sessions"][0]["spawn_post_probes"]
        self.assertEqual(projected[0]["claim_check"], "matched")
        self.assertNotIn("tool_response", projected[0])
        self.assertNotIn("target", projected[0])


if __name__ == "__main__":
    unittest.main()
