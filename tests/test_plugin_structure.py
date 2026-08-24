#!/usr/bin/env python3

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PluginStructureTests(unittest.TestCase):
    def test_hook_config_has_expected_events(self):
        hooks = json.loads((ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(
            set(hooks),
            {"PreToolUse", "PostToolUse", "SessionStart", "SessionEnd", "Stop"},
        )

    def test_hook_commands_use_plugin_root(self):
        hooks = json.loads((ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
        commands = []
        windows_commands = []
        for groups in hooks.values():
            for group in groups:
                for handler in group["hooks"]:
                    commands.append(handler["command"])
                    windows_commands.append(handler["commandWindows"])
        self.assertEqual(len(commands), len(hooks))
        self.assertEqual(
            set(commands),
            {'python3 "$PLUGIN_ROOT/scripts/subagent_governance.py"'},
        )
        self.assertEqual(
            set(windows_commands),
            {'py -3 "%PLUGIN_ROOT%\\scripts\\subagent_governance.py"'},
        )

    def test_repo_marketplace_exposes_root_plugin_from_git(self):
        marketplace_path = ROOT / ".agents/plugins/marketplace.json"
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        self.assertEqual(marketplace["name"], "subagent-governance")
        self.assertEqual(marketplace["interface"]["displayName"], "Subagent Governance")
        self.assertEqual(len(marketplace["plugins"]), 1)
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], "subagent-governance")
        source = entry["source"]
        self.assertEqual(source["source"], "url")
        self.assertEqual(
            source["url"],
            "https://github.com/uigdwunm/subagent-governance.git",
        )
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        expected_tag = f"v{manifest['version'].split('+', 1)[0]}"
        self.assertIn(source["ref"], {"main", expected_tag})
        self.assertEqual(
            entry["policy"],
            {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        )
        self.assertEqual(entry["category"], "Developer Tools")

    def test_hook_groups_have_expected_controls(self):
        hooks = json.loads((ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
        expected = {
            "PreToolUse": {
                "matcher": "(^Agent$|.*spawn_agent$|.*send_message$|.*followup_task$|.*interrupt_agent$)",
                "timeout": 10,
                "statusMessage": "检查子 Agent 派发与通信",
            },
            "PostToolUse": {
                "matcher": ".*",
                "timeout": 10,
                "statusMessage": "记录子 Agent 生命周期",
            },
            "SessionStart": {
                "matcher": "startup|resume|clear|compact",
                "timeout": 10,
                "statusMessage": "恢复子 Agent 治理状态",
                "additionalContextLimit": 1800,
            },
            "SessionEnd": {
                "matcher": "other",
                "timeout": 3,
                "statusMessage": "清理子 Agent 治理状态",
            },
            "Stop": {
                "timeout": 10,
                "statusMessage": "检查未完成的子 Agent",
            },
        }

        for event, controls in expected.items():
            self.assertEqual(len(hooks[event]), 1, event)
            group = hooks[event][0]
            self.assertEqual(len(group["hooks"]), 1, event)
            handler = group["hooks"][0]
            self.assertEqual(handler["type"], "command", event)
            self.assertEqual(handler["timeout"], controls["timeout"], event)
            self.assertEqual(handler["statusMessage"], controls["statusMessage"], event)
            if "matcher" in controls:
                self.assertEqual(group["matcher"], controls["matcher"], event)
            else:
                self.assertNotIn("matcher", group, event)
            if "additionalContextLimit" in controls:
                self.assertEqual(handler["additionalContextLimit"], controls["additionalContextLimit"], event)
            else:
                self.assertNotIn("additionalContextLimit", handler, event)

    def test_pre_tool_hook_matches_only_operations_with_preprocessing(self):
        hooks = json.loads((ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
        pre_tool_group = hooks["PreToolUse"][0]
        matcher = re.compile(pre_tool_group["matcher"])

        for tool_name in (
            "Agent",
            "collaboration.spawn_agent",
            "collaboration.send_message",
            "collaboration.followup_task",
            "collaboration.interrupt_agent",
        ):
            self.assertIsNotNone(matcher.search(tool_name), tool_name)

        for tool_name in (
            "collaboration.list_agents",
            "codex_app.send_message_to_thread",
        ):
            self.assertIsNone(matcher.search(tool_name), tool_name)

        handler = pre_tool_group["hooks"][0]
        self.assertEqual(handler["statusMessage"], "检查子 Agent 派发与通信")

    def test_manifest_uses_default_hook_config_path(self):
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        # Codex auto-discovers this conventional path, so the manifest need not repeat it.
        self.assertNotIn("hooks", manifest)
        self.assertTrue((ROOT / "hooks/hooks.json").is_file())
        self.assertEqual(manifest["name"], "subagent-governance")

    def test_public_metadata_and_readme_cover_open_source_installation(self):
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        repository = "https://github.com/uigdwunm/subagent-governance"

        self.assertEqual(manifest["license"], "MIT")
        self.assertEqual(manifest["homepage"], repository)
        self.assertEqual(manifest["repository"], repository)
        self.assertIn("Codex-first", manifest["description"])
        self.assertTrue((ROOT / "LICENSE").is_file())
        for public_document in (
            "README.en.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "scripts/release_preflight.py",
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml",
            ".github/pull_request_template.md",
        ):
            self.assertTrue((ROOT / public_document).is_file(), public_document)
        for expected in (
            "codex plugin marketplace add uigdwunm/subagent-governance --ref main",
            "codex plugin add subagent-governance@subagent-governance",
            "/hooks",
            "Windows PowerShell",
            "Codex-first",
            "核心能力",
            "核心运行时不主动联网",
        ):
            self.assertIn(expected, readme)

    def test_manifest_skill_path_resolves_to_skill_collection(self):
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["skills"], "./skills/")

        skill_root = (ROOT / manifest["skills"]).resolve()
        self.assertEqual(skill_root, (ROOT / "skills").resolve())
        self.assertTrue(skill_root.is_dir())
        self.assertTrue((skill_root / manifest["name"] / "SKILL.md").is_file())

    def test_plugin_metadata_matches_skill_entrypoint(self):
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        skill_text = (ROOT / "skills/subagent-governance/SKILL.md").read_text(encoding="utf-8")
        agent_text = (ROOT / "skills/subagent-governance/agents/openai.yaml").read_text(encoding="utf-8")
        plugin_name = manifest["name"]
        default_prompt = manifest["interface"]["defaultPrompt"]

        self.assertIn(f"name: {plugin_name}", skill_text)
        self.assertIn("统一任务契约", skill_text)
        self.assertIn(f"${plugin_name}", default_prompt)
        self.assertIn(f"${plugin_name}", agent_text)
        for expected in ("治理等级", "派发", "契约"):
            self.assertIn(expected, default_prompt)
            self.assertIn(expected, agent_text)

    def test_skill_frontmatter_has_discriminating_trigger_boundary(self):
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        skill_text = (ROOT / "skills/subagent-governance/SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill_text.startswith("---\n"))
        closing_marker = skill_text.find("\n---\n", 4)
        self.assertGreater(closing_marker, 0)

        fields = {}
        for line in skill_text[4:closing_marker].splitlines():
            key, separator, value = line.partition(":")
            if separator:
                fields[key.strip()] = value.strip()

        self.assertEqual(fields["name"], manifest["name"])
        self.assertTrue(fields["description"])
        self.assertIn("子 Agent", fields["description"])
        self.assertIn("普通任务不使用", fields["description"])
        for operation in ("派发", "通信", "等待", "恢复", "中断", "验收"):
            self.assertIn(operation, fields["description"])
        for tool in (
            "spawn_agent",
            "send_message",
            "followup_task",
            "wait_agent",
            "list_agents",
            "interrupt_agent",
        ):
            self.assertIn(tool, fields["description"])

    def test_skill_ui_metadata_has_expected_shape(self):
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        agent_text = (ROOT / "skills/subagent-governance/agents/openai.yaml").read_text(encoding="utf-8")
        values = {}
        for line in agent_text.splitlines():
            match = re.fullmatch(r"  ([a-z_]+):\s*(.+)", line)
            if match and match.group(1) in {"display_name", "short_description", "default_prompt"}:
                values[match.group(1)] = json.loads(match.group(2))

        self.assertEqual(set(values), {"display_name", "short_description", "default_prompt"})
        self.assertTrue(all(isinstance(value, str) and value.strip() for value in values.values()))
        self.assertEqual(values["display_name"], manifest["interface"]["displayName"])
        self.assertIn("子 Agent", values["short_description"])
        self.assertIn(f'${manifest["name"]}', values["default_prompt"])

    def test_skill_does_not_ship_environment_specific_related_skill_inventory(self):
        skill_text = (ROOT / "skills/subagent-governance/SKILL.md").read_text(encoding="utf-8")
        related_inventory = ROOT / "skills/subagent-governance/references/related-skills.md"

        self.assertFalse(related_inventory.exists())
        self.assertNotIn("related-skills.md", skill_text)
        self.assertIn("不要修改或要求现有 Skill 采用本协议", skill_text)

    def test_no_placeholder_remains(self):
        placeholder = "[" + "TODO:"
        for path in ROOT.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".json", ".yaml", ".py"}:
                self.assertNotIn(placeholder, path.read_text(encoding="utf-8"), str(path))

    def test_protocol_schemas_match_runtime_contract(self):
        semantics = json.loads(
            (ROOT / "schemas/governance-semantics.schema.json").read_text(encoding="utf-8")
        )
        contract = json.loads((ROOT / "schemas/task-contract-v1.schema.json").read_text(encoding="utf-8"))
        machine = semantics["x-semantics"]

        self.assertEqual(contract["$ref"], "governance-semantics.schema.json#/$defs/task_contract")
        task_contract = semantics["$defs"]["task_contract"]
        self.assertEqual(list(task_contract["properties"]), machine["task_contract_fields"])
        self.assertNotIn("protocol", task_contract["properties"])
        self.assertFalse((ROOT / "schemas/task-result-v1.schema.json").exists())
        self.assertNotIn("task_result_fields", machine)
        self.assertNotIn("business_result", semantics["$defs"])
        self.assertIn("terminal_notification_channel", machine)
        self.assertFalse(task_contract["additionalProperties"])

    def test_agents_governance_asset_has_single_marker_pair(self):
        text = (ROOT / "assets/agents-governance.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("<!-- subagent-governance:start -->"), 1)
        self.assertEqual(text.count("<!-- subagent-governance:end -->"), 1)
        self.assertLessEqual(len(text.encode("utf-8")), 512)
        self.assertIn("$subagent-governance", text)
        self.assertIn("先使用", text)
        self.assertIn("普通任务不加载", text)
        self.assertIn("平台权限或安全边界", text)
        self.assertNotIn("timeout_ms", text)
        self.assertNotIn("【子 Agent 终态】", text)
        self.assertNotIn("sg_<mode>_<semantic_name>", text)


if __name__ == "__main__":
    unittest.main()
