#!/usr/bin/env python3

"""Golden behavior for the P4 contract and dispatch protocol extraction."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts import governance_context as context
from scripts import governance_contracts as contracts
from scripts import governance_dispatch_identity as identity
from scripts import governance_dispatch_rendering as rendering
from scripts import governance_prepared_store as prepared_records
from tests.support import load_governance


governance = load_governance("p4_protocol_characterization")


class P4ProtocolCharacterizationTests(unittest.TestCase):
    @staticmethod
    def input_contract() -> dict[str, object]:
        return {
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

    def test_contract_canonical_record_and_digest_are_stable(self):
        contract = contracts.contract_from_input(self.input_contract())

        self.assertEqual(
            contract.to_record(),
            {
                **self.input_contract(),
                "semantic_name": "payment_review",
                "resolved_mode": "standard",
                "resolution_reason": "auto_standard",
            },
        )
        self.assertEqual(
            contracts.contract_digest(contract),
            "a681502ac7a09782a093a29645b61202d9c322b624f40beb0561330c5ff8de2c",
        )

    def test_identity_prompt_and_native_arguments_are_byte_stable(self):
        contract = contracts.contract_from_input(self.input_contract())
        task_ref = "0123456789ab"
        task_name = identity.build_task_name(
            contract.resolved_mode, contract.semantic_name, task_ref
        )
        verification = {"mode": "none"}
        prompt = rendering.render_dispatch_prompt(contract, verification)
        message = rendering.render_dispatch_user_message(contract, verification)
        arguments = rendering.spawn_args(contract, task_name, verification)

        self.assertEqual(task_name, "sg_standard_payment_review_t_0123456789ab")
        self.assertEqual(identity.parse_task_name(task_name), ("standard", "payment_review", task_ref))
        self.assertEqual(
            hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "f5e7eb781b79324a350483f481e9309b7637c6bbb7eff1f73f751347f6c3428f",
        )
        self.assertEqual(
            hashlib.sha256(message.encode("utf-8")).hexdigest(),
            "77b8869fa5efbfdaa880531ee1482d887e35a43155c72365dbab0b6c29ff53dd",
        )
        self.assertEqual(
            arguments,
            {"task_name": task_name, "message": prompt, "fork_turns": "none"},
        )

    def test_prepared_record_is_strict_and_round_trips_unchanged(self):
        contract = contracts.contract_from_input(self.input_contract())
        task_ref = "0123456789ab"
        task_name = "sg_standard_payment_review_t_0123456789ab"
        spawn_args = rendering.spawn_args(contract, task_name, {"mode": "none"})
        record = prepared_records.prepared_record(
            "session-1", "sg-task-0001", 1, task_ref, task_name, contract,
            {"mode": "none"}, spawn_args, created_at=42, spawn_retry_count=0,
            dispatch_operation="initial_spawn",
        )
        with tempfile.TemporaryDirectory() as directory:
            store = governance.PreparedContractStore(Path(directory) / "prepared")
            store.create(record)
            self.assertEqual(store.read("session-1", task_ref), record)
        self.assertEqual(record["contract_digest"], contracts.contract_digest(contract))
        self.assertEqual(record["native_parameters"], {
            "task_name": task_name,
            "fork_turns": "none",
            "model": None,
            "reasoning_effort": None,
        })

    def test_context_structure_validation_does_not_need_workspace_access(self):
        manifest = {
            "mode": "declared",
            "workspace_root": "/does/not/need/to/exist",
            "baseline": {"kind": "working_tree", "revision": None},
            "required_paths": [{"path": "docs/task.md", "type": "file"}],
        }
        self.assertEqual(context.validate_context_manifest(manifest), [])


if __name__ == "__main__":
    unittest.main()
