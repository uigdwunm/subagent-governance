#!/usr/bin/env python3

import json
import re
import unittest
from pathlib import Path

from tests.schema_validation import assert_schema_supported

ROOT = Path(__file__).resolve().parents[1]


class PluginStructureTests(unittest.TestCase):
    def test_hook_surface_is_minimal(self):
        hooks = json.loads((ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(set(hooks), {"PreToolUse", "SessionStart"})
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "(^Agent$|.*spawn_agent$)")
        matcher = re.compile(hooks["PreToolUse"][0]["matcher"])
        self.assertIsNotNone(matcher.search("collaboration.spawn_agent"))
        for removed in ("send_message", "followup_task", "interrupt_agent", "list_agents"):
            self.assertIsNone(matcher.search("collaboration." + removed))

    def test_hook_commands_use_thin_entrypoint(self):
        hooks = json.loads((ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
        commands = {
            handler["command"]
            for groups in hooks.values()
            for group in groups
            for handler in group["hooks"]
        }
        self.assertEqual(commands, {'python3 "$PLUGIN_ROOT/scripts/subagent_governance.py"'})

    def test_current_schemas_are_v9_and_task_contract_v2(self):
        semantics = json.loads((ROOT / "schemas/governance-semantics.schema.json").read_text(encoding="utf-8"))
        contract = json.loads((ROOT / "schemas/task-contract-v2.schema.json").read_text(encoding="utf-8"))
        assert_schema_supported(semantics)
        self.assertEqual(semantics["x-semantics"]["state_format_version"], 9)
        self.assertEqual(contract["$ref"], "governance-semantics.schema.json#/$defs/task_contract_input")
        self.assertFalse((ROOT / "schemas/task-contract-v1.schema.json").exists())

    def test_manifest_and_skill_resolve(self):
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "subagent-governance")
        self.assertEqual(manifest["skills"], "./skills/")
        skill = (ROOT / "skills/subagent-governance/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: subagent-governance", skill)

    def test_removed_runtime_authorities_are_deleted(self):
        for name in (
            "governance_prepared_store.py", "governance_post_index.py",
            "governance_execution.py", "governance_groups.py",
        ):
            self.assertFalse((ROOT / "scripts" / name).exists(), name)
        lifecycle = (ROOT / "scripts/governance_lifecycle.py").read_text(
            encoding="utf-8"
        )
        for removed in (
            "attempt", "pending_action", "post_receipt", "business_resume",
            "recovery_budget", "group_id",
        ):
            self.assertNotIn(removed, lifecycle)

    def test_development_deploy_has_one_entry_and_no_global_agents_writer(self):
        self.assertTrue((ROOT / "scripts/dev_deploy.py").is_file())
        self.assertTrue((ROOT / "scripts/runtime_bundle.py").is_file())
        for removed in (
            "apply_agents_block.py", "check_installation.py",
            "reinstall_plugin.py", "sync_stable_plugin.py",
        ):
            self.assertFalse((ROOT / "scripts" / removed).exists(), removed)
        self.assertFalse((ROOT / "assets/agents-governance.md").exists())
        deploy = (ROOT / "scripts/dev_deploy.py").read_text(encoding="utf-8")
        self.assertIn("本机开发测试专用", deploy)
        self.assertNotIn("confirm-previous-sessions-restarted", deploy)
        self.assertNotIn("AGENTS.md", json.loads(
            (ROOT / ".codex-plugin/runtime-bundle.json").read_text(encoding="utf-8")
        )["files"])


if __name__ == "__main__":
    unittest.main()
