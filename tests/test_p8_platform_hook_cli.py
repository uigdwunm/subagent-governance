"""P8 boundary characterization: adapters, lazy routing, and facade shape."""
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import governance_diagnostics, governance_hook, governance_platform
from scripts import governance_protocol as protocol
from scripts.governance_prepared_store import PreparedContractStore
from scripts.governance_state_store import StateStore
from tests.support import ROOT


class PlatformAdapterTests(unittest.TestCase):
    @staticmethod
    def _governed_contract():
        return {
            "semantic_name": "probe cleanup", "requested_mode": "standard",
            "task_features": {"risk": "low", "read_only": True, "writes_files": False,
                              "destructive": False, "production": False, "concurrent_write": False},
            "objective": "verify that retired probe sidecars stay inert", "background": "P12-A cleanup",
            "work_scope": ["tests"], "forbidden_scope": ["runtime probe persistence"],
            "completion_conditions": ["bounded cleanup"], "evidence_requirements": ["unittest"],
            "relevant_files": [], "context_manifest": {"mode": "none"}, "current_state": None,
            "model": None, "reasoning_effort": None, "context_strategy": "isolated",
            "context_turns": None, "context_reason": None,
        }

    def test_spawn_and_lifecycle_response_matrix(self):
        spawn_cases = [
            ({"isError": True, "canonical_path": "/root/a"}, "failed", None),
            ({"success": True, "canonical_path": "/root/a"}, "success", "/root/a"),
            ({"task_name": "/root/sg_light_real_platform_t_0123456789ab"}, "success", "/root/sg_light_real_platform_t_0123456789ab"),
            ('{"structuredContent":"{\\"canonical_path\\":\\"/root/a\\"}"}', "unknown", None),
            ("not json", "unknown", None),
        ]
        for raw, expected, target in spawn_cases:
            with self.subTest(raw=raw):
                observation = governance_platform.adapt_spawn_response(raw)
                self.assertEqual((observation.observation, observation.canonical_target), (expected, target))
        lifecycle_cases = [
            ({"status": "failed"}, "normal_message", "failed"),
            ({"success": True}, "normal_message", "success"),
            ({"previous_status": "not_found"}, "interrupt", "success"),
            ({"previous_status": "running"}, "interrupt", "success"),
            ({"content": '{"success":true}'}, "normal_message", "unknown"),
        ]
        for raw, operation, expected in lifecycle_cases:
            with self.subTest(raw=raw):
                self.assertEqual(governance_platform.adapt_lifecycle_response(raw, operation).observation, expected)
        running_interrupt = governance_platform.adapt_lifecycle_response(
            {"previous_status": "running"}, "interrupt"
        )
        self.assertEqual(running_interrupt.target_observation, "previously_running")

    def test_list_agents_accepts_only_one_exact_top_level_agent(self):
        target = "/root/worker"
        cases = [
            ({"agents": [{"agent_name": target, "agent_status": "running"}]}, "running"),
            ({"agents": []}, "absent"),
            ({"structuredContent": {"agents": [{"agent_name": target, "agent_status": "running"}]}}, None),
            ({"agents": [{"agent_name": target, "agent_status": "running"}], "error": 0}, None),
            ({"agents": [{"agent_name": "/root/other", "agent_status": "running"}]}, None),
        ]
        for response, expected in cases:
            with self.subTest(response=response):
                value = governance_platform.adapt_list_agents_response({"path_prefix": target}, response)
                self.assertEqual(value.normalized_status if value else None, expected)


class HookRouterTests(unittest.TestCase):
    def test_unknown_unmanaged_and_malformed_spawn_never_construct_store(self):
        payloads = [
            {"hook_event_name": "Other"},
            {"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "tool_input": {"task_name": "plain"}},
            {"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "tool_input": {"task_name": "sg_bad"}},
        ]
        with mock.patch.object(governance_hook, "_store_or_unavailable") as constructor:
            outputs = [governance_hook.handle_hook(payload) for payload in payloads]
        constructor.assert_not_called()
        self.assertIsNone(outputs[0])
        self.assertEqual(outputs[1]["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertEqual(outputs[2]["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_post_failure_is_continue_not_deny(self):
        store = mock.Mock()
        store.read.side_effect = OSError("offline")
        result = governance_hook.handle_hook({"hook_event_name": "PostToolUse", "tool_name": "send_message", "tool_use_id": "x"}, store)
        self.assertTrue(result["continue"])
        self.assertNotIn("hookSpecificOutput", result)

    def test_post_catch_all_keeps_unrelated_tools_fully_inert(self):
        with mock.patch.object(governance_hook, "_store_or_unavailable") as constructor:
            results = [
                governance_hook.handle_hook(
                    {"hook_event_name": "PostToolUse", "tool_name": "filesystem.write_file", "tool_use_id": "irrelevant"}
                ),
                governance_hook.handle_hook(
                    {"hook_event_name": "PostToolUse", "tool_name": "future.changed_name", "tool_use_id": "unclaimed"}
                ),
                governance_hook.handle_hook(
                    {"hook_event_name": "PostToolUse", "tool_name": "future.changed_name"}
                ),
            ]
        self.assertEqual(results, [None, None, None])
        constructor.assert_not_called()

    def test_unmanaged_spawn_does_not_create_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sessions"
            store = StateStore(root)
            result = governance_hook.handle_hook({"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "tool_input": {"task_name": "plain"}}, store)
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
            self.assertEqual(list(root.glob("*.json")), [])

    def test_governed_spawn_leaves_retired_probe_sidecars_unread_and_unmodified(self):
        """P12-A marker/receipt data is neither maintained nor projected after cleanup."""
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state-v8"
            store = StateStore(state_root / "sessions")
            prepared_store = PreparedContractStore(state_root / "prepared")
            legacy_marker = state_root / "spawn-post-probe-ids-v1" / "retired.json"
            legacy_receipt = state_root / "spawn-post-probes-v1" / "retired.json"
            for path in (legacy_marker, legacy_receipt):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"retired":true}\n', encoding="utf-8")
            before = {path: path.read_bytes() for path in (legacy_marker, legacy_receipt)}
            dispatch = protocol.prepare_dispatch(
                PlatformAdapterTests._governed_contract(), "retired-probe-session", state_store=store,
                prepared_store=prepared_store, task_id_factory=lambda: "retired-probe-task",
            )
            pre = governance_hook.handle_hook({
                "hook_event_name": "PreToolUse", "session_id": "retired-probe-session",
                "tool_name": "spawn_agent", "tool_use_id": "retired-probe-id",
                "tool_input": dispatch["spawn_args"],
            }, store)
            self.assertEqual(pre["hookSpecificOutput"]["permissionDecision"], "allow")
            state_before_post = store.read("retired-probe-session")
            self.assertIsNone(governance_hook.handle_hook({
                "hook_event_name": "PostToolUse", "session_id": "retired-probe-session",
                "tool_name": "future.renamed_spawn", "tool_use_id": "retired-probe-id",
                "tool_response": {"opaque": True},
            }, store))
            document, status = governance_diagnostics.diagnose("retired-probe-session", state_root)
            self.assertEqual(status, 0)
            self.assertNotIn("spawn_post_probes", document["sessions"][0])
            self.assertEqual(store.read("retired-probe-session"), state_before_post)
            self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_unbound_list_agents_is_visible_but_never_persisted(self):
        store = mock.Mock()
        result = governance_hook.handle_hook(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "list_agents",
                "tool_input": {},
                "tool_response": {
                    "agents": [
                        {"agent_name": "/root/a", "agent_status": "running"},
                        {"agent_name": "/root/b", "agent_status": "completed"},
                    ]
                },
            },
            store,
        )

        self.assertTrue(result["continue"])
        self.assertIn("missing_exact_path_prefix", result["systemMessage"])
        self.assertIn("未写入 canonical observation", result["systemMessage"])
        store.assert_not_called()

    def test_ambiguous_exact_list_agents_is_visible_but_never_persisted(self):
        store = mock.Mock()
        result = governance_hook.handle_hook(
            {
                "session_id": "session-1",
                "hook_event_name": "PostToolUse",
                "tool_name": "list_agents",
                "tool_input": {"path_prefix": "/root/a"},
                "tool_response": {
                    "agents": [
                        {"agent_name": "/root/a", "agent_status": "running"},
                        {"agent_name": "/root/b", "agent_status": "completed"},
                    ]
                },
            },
            store,
        )

        self.assertTrue(result["continue"])
        self.assertIn("ambiguous_target_binding", result["systemMessage"])
        self.assertIn("未写入 canonical observation", result["systemMessage"])
        store.assert_not_called()


class EntrypointAndManifestTests(unittest.TestCase):
    def test_entrypoint_is_explicit_and_has_no_private_facade(self):
        module = ast.parse((ROOT / "scripts" / "subagent_governance.py").read_text())
        functions = {item.name for item in module.body if isinstance(item, ast.FunctionDef)}
        self.assertEqual(functions, {"handle", "main"})
        self.assertNotIn("__getattr__", functions)
        source = (ROOT / "scripts" / "governance_cli.py").read_text()
        self.assertNotIn("ModuleType", source)
        self.assertNotIn("runtime.", source)

    def test_hook_manifest_matchers_cover_router_tools(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        pre = hooks["PreToolUse"][0]["matcher"]
        post = hooks["PostToolUse"][0]["matcher"]
        for tool in ("spawn_agent", "send_message", "followup_task", "interrupt_agent"):
            self.assertIn(tool, pre)
        self.assertEqual(post, ".*")
        start = hooks["SessionStart"][0]["hooks"][0]
        self.assertEqual(start["additionalContextLimit"], 1800)
        self.assertIn("subagent_governance.py", start["command"])
        self.assertIn("subagent_governance.py", start["commandWindows"])


if __name__ == "__main__":
    unittest.main()
