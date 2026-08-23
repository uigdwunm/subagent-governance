#!/usr/bin/env python3

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts/subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = governance.StateStore(self.root / "sessions")

    def tearDown(self):
        self.temporary.cleanup()

    def unmanaged_spawn_payload(self, **tool_input):
        values = {
            "message": "执行原生未治理任务",
            "task_name": "plain_native_task",
            "fork_turns": "none",
        }
        values.update(tool_input)
        return {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "tool-1",
            "tool_input": values,
        }

    @staticmethod
    def managed_contract(**overrides):
        value = {
            "semantic_name": "sample_task",
            "requested_mode": "standard",
            "task_features": {
                "risk": "medium",
                "read_only": False,
                "writes_files": True,
                "destructive": False,
                "production": False,
                "concurrent_write": False,
            },
            "objective": "实现一个明确功能并运行相关测试",
            "background": "用于运行时回归测试。",
            "work_scope": ["当前测试工作区"],
            "forbidden_scope": [],
            "completion_conditions": ["相关测试通过"],
            "evidence_requirements": ["测试结果"],
            "relevant_files": ["scripts/subagent_governance.py"],
            "context_manifest": {"mode": "none"},
            "current_state": None,
            "model": None,
            "reasoning_effort": None,
            "context_strategy": "isolated",
            "context_turns": None,
            "context_reason": None,
        }
        value.update(overrides)
        return value

    def prepare_managed(self, *, session_id="session-1", tool_use_id="tool-1", **overrides):
        prepared = governance.prepare_dispatch(
            self.managed_contract(**overrides),
            session_id,
            state_store=self.store,
            prepared_store=governance.PreparedContractStore(self.root / "prepared"),
        )
        payload = {
            "session_id": session_id,
            "turn_id": "turn-1",
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": tool_use_id,
            "tool_input": dict(prepared["spawn_args"]),
        }
        return prepared, payload

    def test_tool_kind_recognizes_only_native_agent_operations(self):
        expected = {
            "Agent": "spawn",
            "spawn_agent": "spawn",
            "collaboration.spawn_agent": "spawn",
            "followup_task": "followup",
            "collaboration.followup_task": "followup",
            "send_message": "communication",
            "collaboration.send_message": "communication",
            "interrupt_agent": "interrupt",
            "collaboration.interrupt_agent": "interrupt",
            "list_agents": "agent_status",
            "collaboration.list_agents": "agent_status",
        }
        for tool_name, kind in expected.items():
            with self.subTest(tool_name=tool_name):
                self.assertEqual(governance._tool_kind(tool_name), kind)
        for tool_name in ("", "update_plan", "codex_app.send_message_to_thread"):
            with self.subTest(tool_name=tool_name):
                self.assertIsNone(governance._tool_kind(tool_name))

    def test_handle_routes_registered_events_and_ignores_unknown_events(self):
        routes = {
            "PostToolUse": "_handle_post_tool",
            "Stop": "_handle_stop",
            "SessionStart": "_handle_session_start",
            "SessionEnd": "_handle_session_end",
        }
        for event, handler_name in routes.items():
            sentinel = {"route": event}
            with self.subTest(event=event), mock.patch.object(
                governance, handler_name, return_value=sentinel
            ) as handler:
                payload = {"hook_event_name": event}
                self.assertEqual(governance.handle(payload, self.store), sentinel)
                handler.assert_called_once_with(payload, self.store)
        for event in ("SubagentStart", "SubagentStop", "UnknownEvent"):
            self.assertIsNone(governance.handle({"hook_event_name": event}, self.store))

    def test_main_fails_open_for_invalid_hook_input(self):
        for raw_input in ("{", "[]"):
            with self.subTest(raw_input=raw_input), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run(
                    [sys.executable, str(SCRIPT)],
                    input=raw_input,
                    capture_output=True,
                    text=True,
                    check=False,
                    env={**os.environ, "SUBAGENT_GOVERNANCE_DATA": directory},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(result.stdout)["continue"])

    def test_main_rejects_unknown_arguments_and_orphan_selectors(self):
        invocations = (
            (["--unexpected"], "unsupported arguments"),
            (["--reconcile-terminal-attempt"], "unsupported arguments"),
            (["--agent-target", "/root/agent"], "unsupported arguments"),
            (["--task-id", "task-1"], "unsupported arguments"),
            (["--attempt", "1"], "unsupported arguments"),
            (["--authorize-final-retry"], "requires --prepare-spawn-retry"),
            (["--authorize-recovery"], "requires --prepare-communication"),
            (["--upsert-group", "--group-id", "group-1"], "only valid with --read-group"),
            (["--session", "session-1"], "require --diagnose"),
            (["--data-root", str(self.root)], "require --diagnose"),
        )
        for arguments, expected in invocations:
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), *arguments],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)

    def test_unmanaged_spawn_remains_native_and_does_not_create_state(self):
        payload = self.unmanaged_spawn_payload()
        result = governance.handle(payload, self.store)["hookSpecificOutput"]
        self.assertEqual(result["permissionDecision"], "allow")
        self.assertEqual(result["updatedInput"], payload["tool_input"])
        self.assertEqual(self.store.read("session-1")["tasks"], {})

    def test_published_rules_match_current_runtime_contract(self):
        asset = (PLUGIN_ROOT / "assets/agents-governance.md").read_text(encoding="utf-8")
        skill = (PLUGIN_ROOT / "skills/subagent-governance/SKILL.md").read_text(encoding="utf-8")
        levels = (
            PLUGIN_ROOT / "skills/subagent-governance/references/governance-levels.md"
        ).read_text(encoding="utf-8")
        boundaries = (
            PLUGIN_ROOT / "skills/subagent-governance/references/runtime-boundaries.md"
        ).read_text(encoding="utf-8")
        self.assertIn("$subagent-governance", asset)
        self.assertIn("普通任务不加载", asset)
        self.assertIn("平台权限或安全边界", asset)
        self.assertIn("`requested_mode`", skill)
        for mode in governance.REQUESTED_MODES:
            self.assertIn(f"`{mode}`", skill)
            self.assertIn(mode, levels.lower())
        self.assertIn("sg_<resolved_mode>_<semantic_name>_t_<task_ref>", skill)
        self.assertIn("## 终态通知与父处置", skill)
        self.assertIn("不保存通知正文", skill)
        self.assertIn("不替代原生终态通知，也不生成业务结果", skill)
        self.assertIn("未知格式版本 fail-open 且不重写原文件", boundaries)
        self.assertIn("PostToolUse unknown 不自动重发", boundaries)

    def test_long_session_ids_get_distinct_state_paths(self):
        first = "x" * 200 + "A"
        second = "x" * 200 + "B"
        self.assertNotEqual(self.store._paths(first), self.store._paths(second))

    @unittest.skipIf(os.name == "nt", "Windows symlink creation may require elevated privileges")
    def test_state_store_rejects_symlink_root(self):
        target = self.root / "target"
        target.mkdir()
        link = self.root / "linked"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            governance.StateStore(link)

    def test_corrupt_and_non_utf8_state_are_preserved_for_unmanaged_spawn(self):
        state_path, _ = self.store._paths("session-1")
        for payload in (b"{broken", b"\xff\xfe\x00"):
            with self.subTest(payload=payload):
                state_path.write_bytes(payload)
                result = governance.handle(self.unmanaged_spawn_payload(), self.store)
                self.assertEqual(
                    result["hookSpecificOutput"]["permissionDecision"], "allow"
                )
                self.assertEqual(state_path.read_bytes(), payload)

    def test_unmanaged_spawn_survives_unavailable_state_store(self):
        class FailingStore:
            last_warning = None

            def update(self, session_id, callback):
                raise PermissionError("state directory is read-only")

        result = governance.handle(self.unmanaged_spawn_payload(), FailingStore())
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        with mock.patch.object(
            governance,
            "StateStore",
            side_effect=PermissionError("plugin data is unavailable"),
        ):
            result = governance.handle(self.unmanaged_spawn_payload())
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")

    def test_generator_creates_current_initial_attempt_without_legacy_fields(self):
        prepared, _payload = self.prepare_managed(
            semantic_name="payment_state",
            objective="核对支付状态机",
            work_scope=["只读检查 payment 模块"],
            completion_conditions=["列出状态转换和验证结论"],
        )
        record = self.store.read("session-1")["tasks"][prepared["task_id"]]
        execution = record["executions"][str(record["work_item"]["current_attempt"])]
        self.assertNotIn("created_at", record["work_item"])
        self.assertNotIn("attempt_count", record["work_item"])
        for retired in (
            "protocol",
            "status",
            "retry_count",
            "platform_status",
            "platform_error",
            "result_document",
            "message_visibility",
        ):
            self.assertNotIn(retired, record)
        self.assertEqual(set(execution), set(governance.REQUIRED_EXECUTION_FIELDS))
        self.assertEqual(execution["dispatch_record"]["dispatch_state"], "prepared")
        self.assertEqual(
            execution["observation_record"]["observed_state"], "not_observed"
        )
        self.assertNotIn("closure_state", execution["closure_record"])
        self.assertEqual(governance._execution_status(execution), "not_started")
        self.assertEqual(execution["dispatch_record"]["dispatch_state"], "prepared")
        self.assertIsNone(execution["closure_record"]["parent_action"])

    def test_runtime_task_contract_matches_schema_shape(self):
        schema = json.loads(
            (PLUGIN_ROOT / "schemas/task-contract-v1.schema.json").read_text(encoding="utf-8")
        )
        contract_fields = set(governance.TaskContract.__dataclass_fields__)
        self.assertEqual(set(schema["properties"]), contract_fields)
        self.assertTrue(set(schema["required"]) <= contract_fields)
        self.assertNotIn("protocol", schema["properties"])
        self.assertNotIn("child_agents", schema["properties"])


if __name__ == "__main__":
    unittest.main()
