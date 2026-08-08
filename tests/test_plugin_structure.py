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
            {"PreToolUse", "PostToolUse", "SessionStart", "SubagentStart", "SubagentStop", "Stop"},
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


if __name__ == "__main__":
    unittest.main()
