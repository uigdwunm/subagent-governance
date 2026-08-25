#!/usr/bin/env python3

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "schemas/codex-hook-events-v1.contract.json"


def contract_errors(payload, contract):
    event = contract["events"].get(payload.get("hook_event_name"))
    if event is None:
        return {"unknown_event": {payload.get("hook_event_name")}}
    required = set(contract["common"]["required_keys"]) | set(event["required_keys"])
    optional = set(contract["common"]["optional_keys"]) | set(event["optional_keys"])
    return {"missing": required - set(payload), "extra": set(payload) - required - optional}


class HookEventContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    @staticmethod
    def common(event):
        return {
            "session_id": "exact-parent-session",
            "cwd": "/workspace",
            "hook_event_name": event,
            "model": "gpt-test",
            "transcript_path": None,
        }

    def test_registered_event_shapes_match_official_contract(self):
        pre = {
            **self.common("PreToolUse"),
            "turn_id": "turn-1", "tool_name": "spawn_agent",
            "tool_use_id": "call-1", "tool_input": {}, "permission_mode": "default",
        }
        start = {
            **self.common("SessionStart"),
            "source": "resume", "permission_mode": "default",
        }
        for payload in (pre, start):
            self.assertEqual(contract_errors(payload, self.contract), {"missing": set(), "extra": set()})

    def test_nonofficial_identity_fields_are_rejected_as_extra(self):
        payload = {
            **self.common("PreToolUse"),
            "turn_id": "turn-1", "tool_name": "spawn_agent",
            "tool_use_id": "call-1", "tool_input": {}, "permission_mode": "default",
            "canonical_task_path": "/root/guess", "task_result": "body",
        }
        self.assertEqual(
            contract_errors(payload, self.contract)["extra"],
            {"canonical_task_path", "task_result"},
        )


if __name__ == "__main__":
    unittest.main()
