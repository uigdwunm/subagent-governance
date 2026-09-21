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
        child = {
            **self.common("SubagentStart"), "turn_id": "turn-1",
            "agent_id": "child", "agent_type": "worker", "permission_mode": "default",
        }
        for payload in (pre, start, child):
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


class HookOutputCompatibilityTests(unittest.TestCase):
    """Supported output subset checked against the 2026-09-16 docs review."""

    def test_pre_outputs_use_event_specific_decisions(self):
        from scripts.governance_hook import _allow, _deny

        for result, decision, text_field in (
            (_allow("safe diagnostic"), "allow", "additionalContext"),
            (_deny("safe diagnostic"), "deny", "permissionDecisionReason"),
        ):
            self.assertEqual(set(result), {"hookSpecificOutput"})
            output = result["hookSpecificOutput"]
            self.assertEqual(set(output), {"hookEventName", "permissionDecision", text_field})
            self.assertEqual(output["hookEventName"], "PreToolUse")
            self.assertEqual(output["permissionDecision"], decision)
            self.assertIsInstance(output[text_field], str)

    def test_identity_types_fail_open_without_attempting_claim(self):
        from unittest import mock

        from scripts import governance_hook as hook

        marked = {"task_name": "sg_standard_check_t_aaaaaaaaaaaa", "message": "fixture"}
        for field in ("session_id", "tool_use_id"):
            for value in (None, False, 7, [], {}, "", " "):
                with self.subTest(field=field, value=value):
                    payload = {"hook_event_name": "PreToolUse", "tool_name": "spawn_agent",
                               "session_id": "fixture", "tool_use_id": "call", "tool_input": marked,
                               field: value}
                    with mock.patch.object(hook, "claim_spawn") as claim:
                        result = hook.handle_hook(payload)["hookSpecificOutput"]
                        claim.assert_not_called()
                    self.assertEqual(result["permissionDecision"], "allow")
                    self.assertIn("claim=not_attempted", result["additionalContext"])


if __name__ == "__main__":
    unittest.main()
