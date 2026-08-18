#!/usr/bin/env python3

import copy
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "schemas/codex-hook-events-v1.contract.json"
FIXTURE_ROOT = ROOT / "tests/fixtures"


def contract_errors(payload, contract):
    event_name = payload.get("hook_event_name")
    event_contract = contract["events"].get(event_name)
    if event_contract is None:
        return {"unknown_event": {event_name}}
    required = set(contract["common"]["required_keys"])
    required.update(event_contract["required_keys"])
    optional = set(contract["common"]["optional_keys"])
    optional.update(event_contract["optional_keys"])
    actual = set(payload)
    return {
        "missing": required - actual,
        "extra": actual - required - optional,
    }


class HookEventContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    @staticmethod
    def fixture(name):
        return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))

    def test_official_lifecycle_fixture_matches_required_and_optional_keys(self):
        fixture = self.fixture("lifecycle-v1.json")
        self.assertEqual(fixture["contract"], self.contract["contract_name"])
        for payload in fixture["events"]:
            with self.subTest(event=payload["hook_event_name"]):
                self.assertEqual(contract_errors(payload, self.contract), {
                    "missing": set(),
                    "extra": set(),
                })
        subagent_events = fixture["events"][3:]
        self.assertTrue(subagent_events)
        self.assertEqual(
            {event["session_id"] for event in subagent_events},
            {"fixture-parent-session"},
        )

    def test_detector_rejects_correctness_critical_nonofficial_fields(self):
        fixture = self.fixture("lifecycle-invalid-extra-v1.json")
        observed = {}
        for payload in fixture["events"]:
            errors = contract_errors(payload, self.contract)
            observed[payload["hook_event_name"]] = sorted(errors["extra"])
        self.assertEqual(observed, fixture["expected_extra_keys"])
        self.assertEqual(
            set(self.contract["events"]["SubagentStart"]["excluded_correctness_keys"]),
            {"agent_transcript_path", "task_name", "canonical_task_path", "task_result"},
        )
        self.assertEqual(
            self.contract["events"]["SubagentStop"]["excluded_correctness_keys"],
            ["task_result"],
        )

    def test_detector_rejects_missing_required_field(self):
        payload = copy.deepcopy(self.fixture("lifecycle-v1.json")["events"][3])
        payload.pop("agent_id")
        self.assertEqual(contract_errors(payload, self.contract)["missing"], {"agent_id"})

    def test_subagent_stop_optional_fields_may_be_missing_or_null(self):
        missing, nullable = self.fixture("lifecycle-v1.json")["events"][4:6]
        self.assertNotIn("agent_transcript_path", missing)
        self.assertNotIn("last_assistant_message", missing)
        self.assertIsNone(nullable["agent_transcript_path"])
        self.assertIsNone(nullable["last_assistant_message"])
        for payload in (missing, nullable):
            self.assertEqual(contract_errors(payload, self.contract), {
                "missing": set(),
                "extra": set(),
            })

    def test_deprecated_identity_and_result_routes_are_removed(self):
        runtime = (ROOT / "scripts/subagent_governance.py").read_text(encoding="utf-8")
        for symbol in (
            "_mapped_attempt",
            "_event_task_name",
            "SubagentEventRoute",
            "_read_subagent_event_route",
            "_route_has_exact_parent_candidate",
            "_assign_starting_agent",
            "_record_managed_result_protocol_gap",
        ):
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, runtime)


if __name__ == "__main__":
    unittest.main()
