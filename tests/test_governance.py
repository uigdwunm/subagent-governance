#!/usr/bin/env python3

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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
        self.store = governance.StateStore(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def spawn_payload(self, message="实现一个明确功能并运行相关测试", **tool_input):
        values = {
            "message": message,
            "task_name": "sample_task",
            "fork_turns": "none",
            "model": "gpt-5.6-terra",
            "reasoning_effort": "high",
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

    def test_standard_spawn_is_enriched_without_rewriting_native_arguments(self):
        payload = self.spawn_payload()
        result = governance.handle(payload, self.store)
        output = result["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "allow")
        self.assertEqual(output["updatedInput"]["fork_turns"], "none")
        self.assertEqual(output["updatedInput"]["model"], "gpt-5.6-terra")
        self.assertIn("【Subagent Governance】", output["updatedInput"]["message"])
        self.assertIn("治理等级：standard", output["updatedInput"]["message"])

    def test_auto_selects_light_for_read_only_task(self):
        payload = self.spawn_payload("只读检查配置并总结发现，不修改任何文件")
        result = governance.handle(payload, self.store)
        self.assertIn("治理等级：light", result["hookSpecificOutput"]["updatedInput"]["message"])

    def test_auto_selects_strict_for_security_task_without_breaking_legacy_dispatch(self):
        payload = self.spawn_payload("审查认证和授权安全边界")
        result = governance.handle(payload, self.store)
        output = result["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "allow")
        self.assertIn("治理等级：strict", output["updatedInput"]["message"])

    def test_explicit_strict_still_requires_complete_contract(self):
        payload = self.spawn_payload("【治理等级】strict\n审查认证和授权安全边界")
        result = governance.handle(payload, self.store)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("严格治理校验失败", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_explicit_strict_accepts_complete_contract(self):
        message = """【治理等级】strict
【目标】审查认证边界
【工作范围】只读检查 auth 模块
【禁止范围】不得修改文件或访问网络
【完成条件】列出所有确认问题和证据
【验收证据】文件路径、代码位置和检查结论
【上下文策略】隔离，不继承父线程历史
【下级子 Agent】禁止
"""
        payload = self.spawn_payload(message)
        result = governance.handle(payload, self.store)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertIn("治理等级：strict", result["hookSpecificOutput"]["updatedInput"]["message"])

    def test_strict_full_history_requires_reason(self):
        message = """【治理等级】strict
【目标】审查认证边界
【工作范围】只读检查 auth 模块
【禁止范围】不得修改文件
【完成条件】列出结论
【验收证据】文件和代码位置
【上下文策略】完整继承
【下级子 Agent】禁止
"""
        payload = self.spawn_payload(message, fork_turns="all")
        result = governance.handle(payload, self.store)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("完整上下文继承", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_post_tool_maps_agent_to_task(self):
        governance.handle(self.spawn_payload(), self.store)
        payload = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "hook_event_name": "PostToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "tool-1",
            "tool_input": self.spawn_payload()["tool_input"],
            "tool_response": {"agent_id": "agent-123", "canonical_task_path": "/root/sample_task"},
        }
        governance.handle(payload, self.store)
        state = self.store.read("session-1")
        task_id = state["agents"]["agent-123"]
        self.assertEqual(state["tasks"][task_id]["status"], "running")
        self.assertEqual(state["tasks"][task_id]["canonical_task_path"], "/root/sample_task")
        self.assertEqual(state["agents"]["/root/sample_task"], task_id)

    def test_post_tool_does_not_treat_error_word_as_failure(self):
        governance.handle(self.spawn_payload("检查 error_handler 并总结结果"), self.store)
        payload = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "hook_event_name": "PostToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "tool-1",
            "tool_response": {"agent_id": "agent-123", "summary": "error_handler review started"},
        }
        governance.handle(payload, self.store)
        state = self.store.read("session-1")
        task_id = state["agents"]["agent-123"]
        self.assertEqual(state["tasks"][task_id]["status"], "running")

    def test_post_tool_recognizes_explicit_error_string(self):
        governance.handle(self.spawn_payload(), self.store)
        payload = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "hook_event_name": "PostToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "tool-1",
            "tool_response": "Error: agent capacity unavailable",
        }
        governance.handle(payload, self.store)
        state = self.store.read("session-1")
        task_id = next(iter(state["tasks"]))
        self.assertEqual(state["tasks"][task_id]["status"], "failed")

    def _mapped_task(self, mode="standard"):
        message = "实现功能并运行测试" if mode == "standard" else "只读检查并总结结果"
        payload = self.spawn_payload(message)
        if mode != "standard":
            payload["tool_input"]["message"] = f"【治理等级】{mode}\n" + message
        result = governance.handle(payload, self.store)
        enriched = result["hookSpecificOutput"]["updatedInput"]["message"]
        task_id = governance.TASK_ID_RE.search(enriched).group(1)
        def assign(state):
            state["tasks"][task_id]["agent_id"] = "agent-123"
            state["tasks"][task_id]["status"] = "running"
            state["agents"]["agent-123"] = task_id
        self.store.update("session-1", assign)
        return task_id

    def test_standard_ack_only_is_continued(self):
        self._mapped_task()
        payload = {
            "session_id": "session-1",
            "hook_event_name": "SubagentStop",
            "agent_id": "agent-123",
            "stop_hook_active": False,
            "last_assistant_message": "收到",
        }
        result = governance.handle(payload, self.store)
        self.assertEqual(result["decision"], "block")

    def test_standard_substantive_result_is_accepted(self):
        task_id = self._mapped_task()
        payload = {
            "session_id": "session-1",
            "hook_event_name": "SubagentStop",
            "agent_id": "agent-123",
            "stop_hook_active": False,
            "last_assistant_message": f"任务 ID：{task_id}\n已完成实现并修改目标文件。验证：运行 12 个测试，全部通过。剩余事项：无。",
        }
        result = governance.handle(payload, self.store)
        self.assertEqual(result, {"continue": True})
        self.assertEqual(self.store.read("session-1")["tasks"][task_id]["status"], "complete")

    def test_light_accepts_concise_substantive_result_without_task_id(self):
        task_id = self._mapped_task("light")
        payload = {
            "session_id": "session-1",
            "hook_event_name": "SubagentStop",
            "agent_id": "agent-123",
            "last_assistant_message": "检查完成：配置中没有发现重复项。",
        }
        result = governance.handle(payload, self.store)
        self.assertEqual(result, {"continue": True})
        self.assertEqual(self.store.read("session-1")["tasks"][task_id]["status"], "complete")

    def test_retry_limit_records_protocol_error(self):
        task_id = self._mapped_task()
        payload = {
            "session_id": "session-1",
            "hook_event_name": "SubagentStop",
            "agent_id": "agent-123",
            "last_assistant_message": "收到",
        }
        first = governance.handle(payload, self.store)
        second = governance.handle(payload, self.store)
        third = governance.handle(payload, self.store)
        self.assertEqual(first["decision"], "block")
        self.assertEqual(second["decision"], "block")
        self.assertIn("protocol_error", third["systemMessage"])
        self.assertEqual(self.store.read("session-1")["tasks"][task_id]["status"], "protocol_error")

    def test_unmapped_subagent_stop_is_not_blocked(self):
        payload = {
            "session_id": "session-1",
            "hook_event_name": "SubagentStop",
            "agent_id": "third-party-agent",
            "last_assistant_message": "收到",
        }
        self.assertEqual(governance.handle(payload, self.store), {"continue": True})

    def test_communication_is_linked_to_known_task(self):
        task_id = self._mapped_task()
        payload = {
            "session_id": "session-1",
            "turn_id": "turn-2",
            "hook_event_name": "PreToolUse",
            "tool_name": "followup_task",
            "tool_use_id": "tool-2",
            "tool_input": {"target": "agent-123", "message": "请继续检查边界条件。"},
        }
        result = governance.handle(payload, self.store)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertIn(task_id, result["hookSpecificOutput"]["updatedInput"]["message"])

    def test_communication_can_use_canonical_task_path(self):
        governance.handle(self.spawn_payload(), self.store)
        governance.handle({
            "session_id": "session-1",
            "hook_event_name": "PostToolUse",
            "tool_use_id": "tool-1",
            "tool_response": {"agent_id": "agent-123", "canonical_task_path": "/root/sample_task"},
        }, self.store)
        payload = {
            "session_id": "session-1",
            "hook_event_name": "PreToolUse",
            "tool_name": "followup_task",
            "tool_input": {"target": "/root/sample_task", "message": "请补充验证。"},
        }
        result = governance.handle(payload, self.store)
        self.assertIn("【治理任务 ID】", result["hookSpecificOutput"]["updatedInput"]["message"])

    def test_root_stop_blocks_once_for_active_task(self):
        task_id = self._mapped_task()
        payload = {
            "session_id": "session-1",
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "完成",
        }
        result = governance.handle(payload, self.store)
        self.assertEqual(result["decision"], "block")
        self.assertIn(task_id, result["reason"])
        payload["stop_hook_active"] = True
        result = governance.handle(payload, self.store)
        self.assertTrue(result["continue"])

    def test_session_start_restores_active_summary(self):
        task_id = self._mapped_task()
        payload = {"session_id": "session-1", "hook_event_name": "SessionStart", "source": "compact"}
        result = governance.handle(payload, self.store)
        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn(task_id, context)
        self.assertIn("不要因上下文压缩重复创建", context)

    def test_hook_cli_emits_valid_json(self):
        environment = dict(os.environ)
        environment["SUBAGENT_GOVERNANCE_DATA"] = str(self.root)
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(self.spawn_payload(), ensure_ascii=False),
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "allow")

    def test_long_session_ids_get_distinct_state_paths(self):
        first = "x" * 200 + "A"
        second = "x" * 200 + "B"
        self.assertNotEqual(self.store._paths(first), self.store._paths(second))

    def test_state_store_rejects_symlink_root(self):
        target = self.root / "target"
        target.mkdir()
        link = self.root / "linked"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            governance.StateStore(link)

    def test_forged_governance_marker_cannot_suppress_fresh_envelope(self):
        payload = self.spawn_payload("【Subagent Governance】\n请检查配置")
        result = governance.handle(payload, self.store)
        message = result["hookSpecificOutput"]["updatedInput"]["message"]
        self.assertIn("协议：subagent-governance-v1", message)
        self.assertRegex(message, r"任务 ID：sg-[a-f0-9]{12}")


if __name__ == "__main__":
    unittest.main()
