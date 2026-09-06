"""Independent fixtures for the two documented native spawn contracts."""

from __future__ import annotations

import copy
import unittest

from scripts.governance_errors import NativeInputMismatch, NativeInputUnavailable
from scripts.governance_native_adapter import (
    normalize_native_spawn,
    render_native_spawn,
    validate_native_spawn,
)


EXPECTED = {
    "task_name": "sg_standard_check_t_aaaaaaaaaaaa",
    "message": "[subagent-governance:sg_standard_check_t_aaaaaaaaaaaa]\n检查契约",
    "fork_turns": "none",
    "model": None,
    "reasoning_effort": None,
}


class NativeAdapterTests(unittest.TestCase):
    def test_rendered_shapes_are_exact_and_do_not_mutate_fixture(self):
        fixture = copy.deepcopy(EXPECTED)
        self.assertEqual(
            render_native_spawn("collaboration_turns", fixture),
            {"task_name": EXPECTED["task_name"], "message": EXPECTED["message"], "fork_turns": "none"},
        )
        self.assertEqual(
            render_native_spawn("fork_context", fixture),
            {"message": EXPECTED["message"], "fork_context": False},
        )
        self.assertEqual(fixture, EXPECTED)

    def test_turns_defaults_and_finite_history(self):
        finite = {**EXPECTED, "fork_turns": "3"}
        validate_native_spawn("collaboration_turns", finite)
        with self.assertRaisesRegex(ValueError, "有限"):
            validate_native_spawn("fork_context", finite)
        actual = normalize_native_spawn(
            "collaboration_turns",
            {"task_name": EXPECTED["task_name"], "message": EXPECTED["message"]},
        )
        self.assertEqual(actual["fork_turns"], "all")

    def test_all_overrides_only_conflict_for_turns(self):
        spawn = {"fork_turns": "all", "model": "gpt-5.6-terra", "reasoning_effort": "high"}
        with self.assertRaisesRegex(ValueError, "不允许"):
            validate_native_spawn("collaboration_turns", spawn)
        validate_native_spawn("fork_context", spawn)

    def test_known_mismatch_is_distinct_from_unavailable_input(self):
        with self.assertRaises(NativeInputMismatch):
            normalize_native_spawn("fork_context", {"message": EXPECTED["message"], "fork_context": "false"})
        with self.assertRaises(NativeInputUnavailable):
            normalize_native_spawn("collaboration_turns", {"message": EXPECTED["message"], "extra": True})
        with self.assertRaises(NativeInputUnavailable):
            normalize_native_spawn("collaboration_turns", {"task_name": EXPECTED["task_name"], "message": EXPECTED["message"], "model": None})

    def test_visible_task_name_with_unmarked_body_is_unavailable(self):
        with self.assertRaises(NativeInputUnavailable):
            normalize_native_spawn(
                "collaboration_turns",
                {"task_name": EXPECTED["task_name"], "message": "opaque-provider-body"},
            )

    def test_invalid_turn_strings_are_rejected(self):
        for value in ("0", "01", "+1", "-1", "1.0", "", 1, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_native_spawn("collaboration_turns", {"fork_turns": value})


if __name__ == "__main__":
    unittest.main()
