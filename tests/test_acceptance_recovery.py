"""Acceptance criteria must survive losing both the prompt and prepared capability."""

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import governance_cli as cli
from scripts import governance_contracts as contracts
from scripts import governance_diagnostics as diagnostics
from scripts import governance_dispatch as dispatch
from scripts import governance_hook as hook
from scripts import governance_lifecycle as lifecycle
from scripts import governance_protocol as protocol
from scripts import governance_semantics as semantics
from scripts import governance_state as state_domain
from scripts import governance_state_store as storage
from scripts import governance_store_support as support
from scripts.governance_errors import (
    DispatchPreparationError,
    StateConflictError,
    StateValidationError,
)
from tests.schema_validation import validate_instance


class AcceptanceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = storage.StateStore(self.root / "sessions")
        self.session = "acceptance-recovery"

    @staticmethod
    def minimal():
        return {"objective": "修复空输入", "scope": ["汇总函数及测试"],
                "completion": ["空输入返回零；报告实际检查及未验证项"]}

    def complete(self):
        material = self.root / "design.txt"
        material.write_text("原设计材料正文不应进入快照", encoding="utf-8")
        return {
            "profile": "strict", "objective": "交付查询层供父任务集成",
            "scope": ["仅查询实现和单测；实现细节自主决定", "父任务维护共享类型并集成，乙维护接口测试"],
            "forbidden_scope": ["不得修改乙的测试或共享类型", "接口变化先报告，继续独立工作"],
            "completion": ["满足 context 中的排序；单测通过", "交付不代表整体集成通过"],
            "evidence": ["报告检查结果、未验证项、接口依赖和父任务待做的组合验证"],
            "context": {"summary": "已定按 created_at、id 升序；旧调用保持兼容。\n保留引用：\"接口\" 与 \\ 标记。",
                        "paths": ["design.txt"],
                        "verified": {"mode": "declared", "workspace_root": str(self.root),
                                     "baseline": {"kind": "working_tree", "revision": None},
                                     "required_paths": [{"path": "design.txt", "type": "file"}]}},
            "spawn": {"fork_turns": "3", "model": "example-model", "reasoning_effort": "high"},
        }

    def prepare(self, value, task_id="task"):
        return protocol.prepare_dispatch(value, self.session, native_interface="collaboration_turns",
                                         state_store=self.store, task_id_factory=lambda: task_id, now=100)

    def claim(self, prepared):
        dispatch.claim_spawn(self.session, prepared["task_ref"], "call-" + prepared["task_id"],
                             prepared["spawn_args"], state_store=self.store, now=101)

    def bind(self, prepared):
        identity = {key: prepared[key] for key in ("task_id", "task_ref")}
        identity["target"] = "/root/" + prepared["task_id"]
        dispatch.confirm_dispatch(self.session, identity, state_store=self.store, now=102)
        return identity

    def detail(self, identity):
        # Public CLI, reconstructed solely from disk; never pass a contract or store object.
        stdout, stderr = io.StringIO(), io.StringIO()
        code = cli.main(["--status", "--session", self.session, "--data-root", str(self.root),
                         "--task-id", identity["task_id"], "--task-ref", identity["task_ref"]],
                        stdin=io.BytesIO(), stdout=stdout, stderr=stderr)
        self.assertEqual(code, 0, stderr.getvalue())
        return json.loads(stdout.getvalue())["tasks"][0]

    def assert_snapshot(self, identity, expected, phase):
        self.store = storage.StateStore(self.root / "sessions")
        detail = self.detail(identity)
        self.assertEqual(detail["phase"], phase)
        self.assertEqual(detail["contract_summary"], expected)
        persisted = self.store.read(self.session)
        self.assertEqual(state_domain.validate_current_state_format(persisted), [])
        self.assertEqual(validate_instance(persisted, semantics.SEMANTIC_DEFINITIONS["session_ledger"],
                                          root_schema=semantics.MACHINE_SEMANTICS), [])

    def test_disk_only_recovery_preserves_minimal_and_parallel_contract_through_lifecycle(self):
        for name, factory in (("minimal", self.minimal), ("parallel", self.complete)):
            with self.subTest(name=name):
                raw = factory()
                expected = contracts.contract_from_input(raw).business_record()
                prepared = self.prepare(raw, name)
                self.assert_snapshot(prepared, expected, "prepared")
                self.claim(prepared)
                self.assert_snapshot(prepared, expected, "claimed")
                identity = self.bind(prepared)
                raw.clear()
                del raw, prepared
                # The material need not still exist to recover its declaration.
                if name == "parallel":
                    (self.root / "design.txt").unlink()
                self.assertNotIn("prepared", self.store.read(self.session)["tasks"][name])
                self.assert_snapshot(identity, expected, "bound")
                lifecycle.record_call_result(self.session, {**identity, "result": "unknown"},
                                             state_store=self.store, now=103)
                lifecycle.record_interrupt_result(self.session, {**identity, "result": "inactive"},
                                                  state_store=self.store, now=104)
                notification = {"task_id": identity["task_id"], "task_ref": identity["task_ref"],
                                "sender": identity["target"], "status": "completed"}
                lifecycle.record_terminal_notification(self.session, notification, state_store=self.store, now=105)
                self.assert_snapshot(identity, expected, "terminal")
                lifecycle.record_platform_observation(self.session, {**identity, "status": "stopped"},
                                                      state_store=self.store, now=106)
                self.assert_snapshot(identity, expected, "reconcile")
                lifecycle.close_task(self.session, {"task_id": identity["task_id"], "task_ref": identity["task_ref"],
                                                     "reason": "父任务停止跟踪，未作业务通过判定"},
                                     state_store=self.store, now=107)
                self.assert_snapshot(identity, expected, "closed")

    def test_prebinding_failure_and_reconciliation_keep_original_criteria(self):
        for case in ("failed", "unknown", "missing_claim", "identity_conflict", "target_owned"):
            with self.subTest(case=case):
                value = self.minimal()
                expected = contracts.contract_from_input(value).business_record()
                prepared = self.prepare(value, case)
                identity = {key: prepared[key] for key in ("task_id", "task_ref")}
                if case in {"failed", "unknown"}:
                    self.claim(prepared)
                    dispatch.record_dispatch_result(self.session, {**identity, "result": case},
                                                    state_store=self.store, now=102)
                else:
                    submitted = {**identity, "target": "/root/owner"}
                    if case == "identity_conflict":
                        submitted["task_ref"] = "0" * 12
                    elif case == "target_owned":
                        owner = self.prepare(value, "owner")
                        self.claim(owner)
                        self.bind(owner)
                        self.claim(prepared)
                    dispatch.confirm_dispatch(self.session, submitted, state_store=self.store, now=102)
                del prepared, value
                self.assert_snapshot(identity, expected, "closed" if case == "failed" else "reconcile")

    @staticmethod
    def sized_contract(size, token="汉🙂\"\\"):
        raw = AcceptanceRecoveryTests.minimal()
        raw["scope"] = []
        # All text fields and lists stay below their individual limits.
        while True:
            candidate = copy.deepcopy(raw)
            candidate["scope"].append(token * 100)
            canonical = contracts.contract_from_input({**candidate, "scope": candidate["scope"] or ["x"]}).business_record()
            length = len(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
            if length > size:
                break
            raw = candidate
        raw["context"] = {"summary": ""}
        canonical = contracts.contract_from_input(raw).business_record()
        overhead = len(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
        raw["context"]["summary"] = "a" * (size - overhead)
        return raw

    def test_utf8_snapshot_limit_counts_json_escaping_and_rejects_without_rewrite(self):
        # Construct against the old normalizer too: no dependency on the new size validation.
        with mock.patch.object(contracts, "MAX_CONTRACT_SUMMARY_BYTES", 10**9):
            exact = self.sized_contract(65536)
        expected = contracts.contract_from_input(exact).business_record()
        self.assertEqual(len(json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()), 65536)
        prepared = self.prepare(exact)
        self.claim(prepared)
        identity = self.bind(prepared)
        self.assert_snapshot(identity, expected, "bound")
        path, _ = self.store._paths(self.session)
        before = path.read_bytes()
        exact["context"]["summary"] += "a"
        # Standard JSON Schema does not assert the byte-budget extension.
        oversized = copy.deepcopy(expected)
        oversized["context"]["summary"] += "a"
        self.assertEqual(validate_instance(oversized, semantics.SEMANTIC_DEFINITIONS["contract_summary"],
                                           root_schema=semantics.MACHINE_SEMANTICS), [])
        self.assertTrue(contracts.validate_contract_summary(oversized))
        with self.assertRaisesRegex(DispatchPreparationError, "65537.*65536"):
            self.prepare(exact, "oversized")
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn(exact["scope"][0], self._prepare_error(exact))

    def _prepare_error(self, raw):
        try:
            self.prepare(raw, "invalid")
        except DispatchPreparationError as exc:
            return str(exc)
        self.fail("expected invalid contract")

    def test_bound_snapshot_rejects_digest_mismatch_without_mutating_disk(self):
        prepared = self.prepare(self.minimal())
        self.claim(prepared)
        self.bind(prepared)
        path, _ = self.store._paths(self.session)
        before = path.read_bytes()
        with self.assertRaises(StateValidationError):
            self.store.update(self.session, lambda state: state["tasks"]["task"]["contract_summary"].update(
                objective="不同的目标"))
        self.assertEqual(path.read_bytes(), before)

    def test_binding_keeps_business_record_after_removing_prepared_capability(self):
        raw = self.complete()
        expected = contracts.contract_from_input(raw).business_record()
        prepared = self.prepare(raw)
        self.claim(prepared)
        self.bind(prepared)
        del raw, prepared
        task = storage.read_ledger_readonly(self.root / "sessions", self.session)["tasks"]["task"]
        self.assertNotIn("prepared", task)
        self.assertEqual(task["contract_summary"], expected)

    def test_summary_structure_matches_contract_schema_and_runtime(self):
        prepared = self.prepare(self.minimal())
        self.claim(prepared)
        self.bind(prepared)
        baseline = self.store.read(self.session)
        mutations = {
            "missing_completion": lambda s: s.pop("completion"),
            "empty_scope": lambda s: s.update(scope=[]),
            "list_type": lambda s: s.update(evidence="a report"),
            "list_limit": lambda s: s.update(evidence=["x"] * 65),
            "item_limit": lambda s: s.update(scope=["汉" * 1025]),
            "objective_limit": lambda s: s.update(objective="a" * 8193),
            "context_limit": lambda s: s["context"].update(summary="汉" * 8193),
            "path_limit": lambda s: s["context"].update(paths=["a" * 1001]),
            "unknown_field": lambda s: s.update(actual_result="passed"),
            "spawn_not_business": lambda s: s.update(spawn={}),
            "strict_missing_evidence": lambda s: s.update(profile="strict", forbidden_scope=["boundary"]),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                value = copy.deepcopy(baseline)
                summary = value["tasks"]["task"]["contract_summary"]
                mutate(summary)
                schema_errors = validate_instance(summary, semantics.SEMANTIC_DEFINITIONS["contract_summary"],
                                                  root_schema=semantics.MACHINE_SEMANTICS)
                self.assertTrue(schema_errors)
                self.assertTrue(contracts.validate_contract_summary(summary))
                self.assertTrue(state_domain.validate_current_state_format(value))
        summary = baseline["tasks"]["task"]["contract_summary"]
        self.assertEqual(validate_instance(summary, semantics.SEMANTIC_DEFINITIONS["contract_summary"],
                                           root_schema=semantics.MACHINE_SEMANTICS), [])

    def test_prepared_summary_cannot_diverge_even_with_matching_digest(self):
        prepared = self.prepare(self.minimal())
        from hashlib import sha256
        def diverge(state):
            task = state["tasks"][prepared["task_id"]]
            task["contract_summary"]["objective"] = "another objective"
            task["contract_digest"] = sha256(json.dumps(task["contract_summary"], ensure_ascii=False,
                                                        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.assertRaises(StateValidationError):
            self.store.update(self.session, diverge)

    def test_individual_field_limits_allow_exact_boundaries_without_truncation(self):
        variants = [
            {"objective": "汉" * 8192},
            {"context": {"summary": "🙂" * 8192}},
            {"scope": ["汉" * 1024]},
            {"completion": [str(i) for i in range(64)]},
            {"context": {"paths": ["a" * 1000]}},
        ]
        for overrides in variants:
            with self.subTest(field=next(iter(overrides))):
                normalized = contracts.contract_from_input({**self.minimal(), **overrides})
                summary = contracts.contract_summary(normalized)
                self.assertEqual(summary, normalized.business_record())
                self.assertEqual(contracts.validate_contract_summary(summary), [])
                self.assertEqual(validate_instance(summary, semantics.SEMANTIC_DEFINITIONS["contract_summary"],
                                                   root_schema=semantics.MACHINE_SEMANTICS), [])

    def test_closed_retention_removes_whole_records_without_trimming_other_contracts(self):
        expected = contracts.contract_from_input(self.minimal()).business_record()
        # Use a small retention count to exercise the real pruning path.
        with mock.patch.object(lifecycle, "CLOSED_TASK_RETENTION", 2):
            identities = []
            for index in range(3):
                prepared = self.prepare(self.minimal(), f"closed-{index}")
                identity = {key: prepared[key] for key in ("task_id", "task_ref")}
                lifecycle.close_task(self.session, {**identity, "reason": "cancelled before dispatch"},
                                     state_store=self.store, now=110 + index)
                identities.append(identity)
            self.assertEqual(set(self.store.read(self.session)["tasks"]), {"closed-1", "closed-2"})
            for identity in identities[1:]:
                self.assert_snapshot(identity, expected, "closed")
            with self.assertRaisesRegex(StateConflictError, "不存在.*不匹配"):
                diagnostics.status(self.session, self.root, **identities[0])

    def test_session_start_keeps_recovery_pointer_when_task_list_is_truncated(self):
        for index in range(8):
            self.prepare(self.minimal(), str(index) + "x" * 250)
        with mock.patch.object(hook, "data_root_path", return_value=self.root):
            result = hook.handle_hook({"hook_event_name": "SessionStart", "session_id": self.session})
        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(context), semantics.SESSION_SUMMARY_CONTEXT_LIMIT)
        self.assertIn("--task-id <task_id> --task-ref <task_ref>", context)

    def test_default_views_are_lightweight_and_exact_detail_is_readonly(self):
        prepared = self.prepare(self.complete())
        self.claim(prepared)
        identity = self.bind(prepared)
        path, lock = self.store._paths(self.session)
        lock.unlink()
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        self.assertIn("contract_summary", self.detail(identity))
        for view in (diagnostics.status(self.session, self.root), diagnostics.diagnose(self.session, self.root)):
            self.assertNotIn("contract_summary", json.dumps(view))
            self.assertNotIn("接口变化先报告", json.dumps(view, ensure_ascii=False))
        with mock.patch.object(hook, "data_root_path", return_value=self.root):
            message = hook.handle_hook({"hook_event_name": "SessionStart", "session_id": self.session})
        encoded = json.dumps(message, ensure_ascii=False)
        self.assertNotIn("接口变化先报告", encoded)
        self.assertIn("--task-ref", encoded)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertFalse(lock.exists())

    def test_detail_rejects_incomplete_wrong_or_missing_identity_without_writes(self):
        prepared = self.prepare(self.minimal())
        path, lock = self.store._paths(self.session)
        lock.unlink()
        before = path.read_bytes()
        base = ["--session", self.session, "--data-root", str(self.root)]
        for command, selectors in (
            ("--status", ["--task-id", "task"]),
            ("--status", ["--task-ref", prepared["task_ref"]]),
            ("--status", ["--task-id", "task", "--task-ref", "0" * 12]),
            ("--status", ["--task-id", "absent", "--task-ref", prepared["task_ref"]]),
            ("--diagnose", ["--task-id", "task", "--task-ref", prepared["task_ref"]]),
        ):
            with self.subTest(command=command, selectors=selectors):
                out, err = io.StringIO(), io.StringIO()
                code = cli.main([command, *base, *selectors], stdin=io.BytesIO(), stdout=out, stderr=err)
                self.assertNotEqual(code, 0)
                self.assertEqual(out.getvalue(), "")
                self.assertTrue(err.getvalue())
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(lock.exists())

    def test_new_state_namespace_never_recovers_old_summary(self):
        plugin_root = self.root / "plugin-data"
        old_root = plugin_root / "state-v11" / "sessions"
        old_store = storage.StateStore(old_root)
        old_path, _ = old_store._paths(self.session)
        original = json.dumps({"state_format_version": 11, "session_id": self.session, "tasks": {}}).encode()
        old_path.write_bytes(original)
        old_path.chmod(0o600)
        current = support.data_root_path(Path(__file__), environment={"PLUGIN_DATA": str(plugin_root),
                                                                      "SUBAGENT_GOVERNANCE_DATA": ""})
        self.assertEqual(current.name, "state-v12")
        self.assertEqual(diagnostics.status(self.session, current)["tasks"], [])
        self.assertFalse(current.exists())
        self.assertEqual(old_path.read_bytes(), original)
        with self.assertRaises(StateValidationError):
            storage.read_ledger_readonly(old_root, self.session)

    def test_new_task_soft_capacity_rejection_preserves_existing_recoverable_contract(self):
        prepared = self.prepare(self.minimal())
        self.claim(prepared)
        identity = self.bind(prepared)
        expected = contracts.contract_from_input(self.minimal()).business_record()
        path, _ = self.store._paths(self.session)
        before = path.read_bytes()
        with mock.patch.object(storage, "NEW_TASK_SOFT_LIMIT_BYTES", len(before)):
            with self.assertRaises(DispatchPreparationError):
                self.prepare(self.minimal(), "another")
        self.assertEqual(path.read_bytes(), before)
        self.assert_snapshot(identity, expected, "bound")


if __name__ == "__main__":
    unittest.main()
