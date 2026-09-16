"""Independent capability cases, not evidence of native platform delivery."""
import copy
import tempfile
import unittest
from pathlib import Path

from scripts.governance_contracts import contract_from_input
from scripts.governance_errors import NativeInputMismatch
from scripts.governance_hook import handle_hook
from scripts.governance_native_adapter import normalize_native_spawn
from scripts.governance_protocol import prepare_dispatch
from scripts.governance_state_store import StateStore


class NativeCompatibilityTests(unittest.TestCase):
    def prepare(self, interface, spawn):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = StateStore(Path(temporary.name) / "sessions")
        prepared = prepare_dispatch(
            {"objective": "Check compatibility", "scope": ["fixture"],
             "completion": ["Report evidence"], "spawn": spawn},
            "fixture-session", native_interface=interface, state_store=store, now=100,
        )
        return store, prepared

    def claim(self, store, args, call="call"):
        return handle_hook({
            "hook_event_name": "PreToolUse", "tool_name": "spawn_agent",
            "session_id": "fixture-session", "tool_use_id": call,
            "tool_input": args, "now": 101,
        }, store)["hookSpecificOutput"]

    def test_render_normalize_claim_with_explicit_inheritance(self):
        cases = [
            ("collaboration_turns", "none", None),
            ("collaboration_turns", "all", None),
            ("collaboration_turns", "3", "gpt-6-astra"),
            ("fork_context", "none", None),
            ("fork_context", "all", "gpt-6-astra"),
        ]
        for interface, turns, model in cases:
            with self.subTest(interface=interface, turns=turns):
                spawn = {"fork_turns": turns, "model": model,
                         "reasoning_effort": "high" if model else None}
                store, prepared = self.prepare(interface, spawn)
                args = prepared["spawn_args"]
                original = copy.deepcopy(args)
                normalized = normalize_native_spawn(interface, args)
                for field, value in spawn.items():
                    self.assertEqual(normalized[field], value)
                self.assertEqual(self.claim(store, args)["permissionDecision"], "allow")
                self.assertIn("code=already_claimed", self.claim(store, args)["additionalContext"])
                args["unknown_extension"] = True
                rejected = self.claim(store, args, "different-call")
                self.assertEqual(rejected["permissionDecision"], "deny")
                self.assertIn("code=claim_conflict", rejected["permissionDecisionReason"])
                self.assertEqual({k: v for k, v in args.items() if k != "unknown_extension"}, original)

    def test_native_omission_defaults_are_not_prepare_defaults(self):
        self.assertEqual(contract_from_input({"objective": "x", "scope": ["x"],
                                             "completion": ["x"]}).spawn["fork_turns"], "none")
        for interface, field, default, other in (
            ("collaboration_turns", "fork_turns", "all", "none"),
            ("fork_context", "fork_context", "none", "all"),
        ):
            for turns in (default, other):
                with self.subTest(interface=interface, turns=turns):
                    store, prepared = self.prepare(interface, {"fork_turns": turns})
                    args = prepared["spawn_args"]
                    del args[field]
                    self.assertEqual(normalize_native_spawn(interface, args)["fork_turns"], default)
                    output = self.claim(store, args)
                    self.assertEqual(output["permissionDecision"], "allow" if turns == default else "deny")

    def test_mutations_have_distinct_actions_and_never_claim(self):
        for interface, inheritance, other_field in (
            ("collaboration_turns", "fork_turns", "fork_context"),
            ("fork_context", "fork_context", "fork_turns"),
        ):
            cases = [
                ({"model": None}, "allow", "input_unavailable"),
                ({"reasoning_effort": None}, "allow", "input_unavailable"),
                ({"message": []}, "allow", "input_unavailable"),
                ({other_field: False}, "allow", "input_unavailable"),
                ({inheritance: None}, "deny", "native_conflict"),
                ({"model": 7}, "deny", "claim_conflict"),
                ({"reasoning_effort": "low"}, "deny", "claim_conflict"),
            ]
            for mutation, action, code in cases:
                with self.subTest(interface=interface, mutation=mutation):
                    store, prepared = self.prepare(interface, {"fork_turns": "none"})
                    args = {**prepared["spawn_args"], **mutation}
                    # Without either name or visible marker, fork_context is unmanaged.
                    if interface == "fork_context" and "message" in mutation:
                        self.assertIsNone(handle_hook({"hook_event_name": "PreToolUse",
                                                      "tool_name": "spawn_agent", "tool_input": args}, store))
                        continue
                    output = self.claim(store, args)
                    self.assertEqual(output["permissionDecision"], action)
                    self.assertIn("code=" + code, str(output))
                    task = store.read("fixture-session")["tasks"][prepared["task_id"]]
                    self.assertEqual(task["phase"], "prepared")

    def test_ascii_turn_boundary_matches_contract_and_normalization(self):
        for value in ("1", "999999999999", "١", "²", "1٢", "01", "1000000000000"):
            with self.subTest(value=value):
                data = {"objective": "x", "scope": ["x"], "completion": ["x"],
                        "spawn": {"fork_turns": value}}
                native = {"task_name": "ordinary", "message": "x", "fork_turns": value}
                if value in ("1", "999999999999"):
                    contract_from_input(data)
                    self.assertEqual(normalize_native_spawn("collaboration_turns", native)["fork_turns"], value)
                else:
                    with self.assertRaises(ValueError):
                        contract_from_input(data)
                    with self.assertRaises(NativeInputMismatch):
                        normalize_native_spawn("collaboration_turns", native)
