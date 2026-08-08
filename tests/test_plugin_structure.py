#!/usr/bin/env python3

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PluginStructureTests(unittest.TestCase):
    def test_hook_config_has_expected_events(self):
        hooks = json.loads((ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(
            set(hooks),
            {"PreToolUse", "PostToolUse", "SessionStart", "SessionEnd", "SubagentStart", "SubagentStop", "Stop"},
        )

    def test_hook_commands_use_plugin_root(self):
        hooks = json.loads((ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
        commands = []
        for groups in hooks.values():
            for group in groups:
                commands.extend(handler["command"] for handler in group["hooks"])
        self.assertTrue(commands)
        self.assertTrue(all("$PLUGIN_ROOT/scripts/subagent_governance.py" in command for command in commands))

    def test_manifest_does_not_declare_unsupported_hooks_field(self):
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertNotIn("hooks", manifest)
        self.assertEqual(manifest["name"], "subagent-governance")

    def test_no_placeholder_remains(self):
        placeholder = "[" + "TODO:"
        for path in ROOT.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".json", ".yaml", ".py"}:
                self.assertNotIn(placeholder, path.read_text(encoding="utf-8"), str(path))

    def test_protocol_schemas_match_runtime_contract(self):
        contract = json.loads((ROOT / "schemas/task-contract-v1.schema.json").read_text(encoding="utf-8"))
        result = json.loads((ROOT / "schemas/task-result-v1.schema.json").read_text(encoding="utf-8"))
        self.assertTrue(
            {
                "protocol", "task_id", "mode", "requested_mode", "mode_reason", "objective", "scope",
                "completion", "message_visibility",
            }
            <= set(contract["required"])
        )
        self.assertEqual(contract["properties"]["protocol"]["const"], "subagent-governance-v1")
        self.assertEqual(result["properties"]["protocol"]["const"], "subagent-result-v1")
        self.assertIn("interrupted", result["properties"]["status"]["enum"])
        self.assertIn("platform_error", result["properties"]["status"]["enum"])

    def test_agents_governance_asset_has_single_marker_pair(self):
        text = (ROOT / "assets/agents-governance.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("<!-- subagent-governance:start -->"), 1)
        self.assertEqual(text.count("<!-- subagent-governance:end -->"), 1)
        self.assertIn("只有父 agent 显式选择 `strict`", text)
        self.assertIn("`interrupted` 终态", text)
        self.assertIn("sg_<mode>_<semantic_name>", text)
        self.assertIn("`platform_error`", text)


if __name__ == "__main__":
    unittest.main()
