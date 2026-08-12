#!/usr/bin/env python3

import importlib.util
import json
import sys
import unittest
from dataclasses import fields
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/subagent_governance.py"
SPEC = importlib.util.spec_from_file_location("subagent_governance_semantics", SCRIPT)
governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = governance
SPEC.loader.exec_module(governance)


class SemanticBaselineTests(unittest.TestCase):
    def valid_task_contract(self, **overrides):
        values = {
            "semantic_name": "schema_baseline",
            "requested_mode": "standard",
            "resolved_mode": "standard",
            "resolution_reason": "explicit_request",
            "task_features": None,
            "objective": "建立统一语义基线",
            "background": "主盘点已经固定字段和机械校验边界。",
            "work_scope": ["修改当前开发仓库的语义、Schema 和测试"],
            "forbidden_scope": [],
            "completion_conditions": ["字段和枚举在所有机器入口一致"],
            "evidence_requirements": ["运行定向测试和全量测试"],
            "relevant_files": ["schemas/task-contract-v1.schema.json"],
            "current_state": None,
            "model": None,
            "reasoning_effort": None,
            "context_strategy": "isolated",
            "context_turns": None,
            "context_reason": None,
        }
        values.update(overrides)
        return values

    def valid_task_result(self, **overrides):
        values = {
            "task_id": "sg-123456789abc",
            "attempt": 1,
            "business_result": "complete",
            "result": "WP-01 语义基线已建立。",
            "evidence": [],
            "remaining": [],
            "suggested_parent_next_step": "验收本阶段并进入后续独立工作包。",
        }
        values.update(overrides)
        return values

    def test_machine_semantics_define_confirmed_enums_limits_and_fields(self):
        semantics = json.loads(
            (ROOT / "schemas/governance-semantics.schema.json").read_text(encoding="utf-8")
        )
        definitions = semantics["$defs"]
        machine = semantics["x-semantics"]

        self.assertEqual(
            definitions["requested_mode"]["enum"],
            ["auto", "light", "standard", "strict"],
        )
        self.assertEqual(
            definitions["resolved_mode"]["enum"],
            ["light", "standard", "strict"],
        )
        self.assertEqual(
            definitions["context_strategy"]["enum"],
            ["isolated", "limited", "full"],
        )
        self.assertEqual(
            definitions["operation_type"]["enum"],
            ["normal_message", "platform_recovery", "result_correction", "business_resume"],
        )
        self.assertEqual(
            definitions["parent_action"]["enum"],
            [
                "wait",
                "reconcile",
                "retry_spawn",
                "recover",
                "correct_result",
                "decide_disposition",
                "business_resume",
                "accept_result",
                "ask_user",
                "manual_review",
                "resolve_duplicate",
            ],
        )
        self.assertEqual(machine["retry_limits"], {"spawn": 2, "recovery": 2, "correction": 2})
        self.assertEqual(machine["retention_seconds"]["prepared_unclaimed"], 300)
        self.assertEqual(machine["retention_seconds"]["claimed_reconcile"], 1200)
        self.assertEqual(machine["retention_seconds"]["recent_activity"], 43200)
        self.assertEqual(machine["retention_seconds"]["tombstone"], 604800)
        self.assertEqual(machine["task_name"]["max_length"], 64)
        self.assertEqual(machine["task_name"]["task_ref_lengths"], [12, 16, 20, 24, 28, 32])
        self.assertEqual(machine["context_turns"], {"minimum": 1, "maximum": 100})
        self.assertEqual(
            machine["auto_resolution"],
            {
                "strict_risks": ["high"],
                "strict_true_fields": [
                    "destructive",
                    "production",
                    "concurrent_write",
                    "multi_stage_acceptance",
                    "allows_child_agents",
                ],
                "light_match": {
                    "risk": "low",
                    "read_only": True,
                    "writes_files": False,
                },
            },
        )
        self.assertEqual(
            machine["mode_minimums"],
            {
                "light": {"forbidden_scope": 0, "evidence_requirements": 0},
                "standard": {"forbidden_scope": 0, "evidence_requirements": 1},
                "strict": {"forbidden_scope": 1, "evidence_requirements": 1},
            },
        )
        self.assertEqual(
            machine["task_contract_optional_fields"],
            ["task_features", "model", "reasoning_effort"],
        )
        self.assertEqual(
            machine["task_result_scenario_fields"],
            {
                "blocked": ["blocker", "attempted", "required_to_resume"],
                "failed": ["failure_reason", "attempted", "retry_conditions"],
                "needs_decision": ["decision_question", "options", "recommendation"],
            },
        )
        self.assertNotIn("protocol", machine["task_contract_fields"])
        self.assertNotIn("protocol", machine["task_result_fields"])
        self.assertNotIn("child_agents", machine["task_contract_fields"])

    def test_python_data_structures_match_machine_field_sets(self):
        machine = governance.MACHINE_SEMANTICS["x-semantics"]
        self.assertEqual(
            [field.name for field in fields(governance.TaskContract)],
            machine["task_contract_fields"],
        )
        self.assertEqual(
            [field.name for field in fields(governance.TaskResult)],
            machine["task_result_fields"],
        )
        self.assertEqual(
            [field.name for field in fields(governance.AttemptState)],
            machine["attempt_state_fields"],
        )

    def test_contract_schema_and_result_schema_use_current_fields_without_version_gate(self):
        contract = json.loads(
            (ROOT / "schemas/task-contract-v1.schema.json").read_text(encoding="utf-8")
        )
        result = json.loads(
            (ROOT / "schemas/task-result-v1.schema.json").read_text(encoding="utf-8")
        )
        machine = governance.MACHINE_SEMANTICS["x-semantics"]

        self.assertEqual(list(contract["properties"]), machine["task_contract_fields"])
        self.assertEqual(list(result["properties"]), machine["task_result_fields"])
        self.assertNotIn("protocol", contract["properties"])
        self.assertNotIn("protocol", result["properties"])
        self.assertNotIn("status", result["properties"])
        self.assertTrue(contract["additionalProperties"])
        self.assertTrue(result["additionalProperties"])

        required_contract_fields = set(machine["task_contract_fields"]) - set(
            machine["task_contract_optional_fields"]
        )
        self.assertEqual(set(contract["required"]), required_contract_fields)
        self.assertEqual(
            set(result["required"]),
            set(machine["task_result_base_required_fields"]),
        )

        optional_native_settings = self.valid_task_contract()
        optional_native_settings.pop("model")
        optional_native_settings.pop("reasoning_effort")
        self.assertEqual(governance.validate_task_contract(optional_native_settings), [])

    def test_explicit_mode_is_not_reclassified_by_task_features(self):
        features = {
            "risk": "high",
            "read_only": False,
            "writes_files": True,
            "destructive": True,
            "production": True,
            "concurrent_write": True,
            "multi_stage_acceptance": True,
            "allows_child_agents": True,
        }
        for mode in ("light", "standard", "strict"):
            with self.subTest(mode=mode):
                self.assertEqual(
                    governance.resolve_governance_mode(mode, features),
                    (mode, "explicit_request"),
                )

    def test_auto_uses_only_structured_task_features(self):
        light = {
            "risk": "low",
            "read_only": True,
            "writes_files": False,
            "destructive": False,
            "production": False,
            "concurrent_write": False,
            "multi_stage_acceptance": False,
        }
        standard = {**light, "risk": "medium", "read_only": False, "writes_files": True}
        strict = {**standard, "risk": "high"}

        self.assertEqual(governance.resolve_governance_mode("auto", light), ("light", "auto_light"))
        self.assertEqual(
            governance.resolve_governance_mode("auto", standard),
            ("standard", "auto_standard"),
        )
        self.assertEqual(
            governance.resolve_governance_mode("auto", strict),
            ("strict", "auto_strict"),
        )
        self.assertEqual(
            governance.resolve_governance_mode("auto", {**light, "allows_child_agents": True}),
            ("strict", "auto_strict"),
        )

    def test_task_contract_validator_enforces_only_mechanical_combinations(self):
        self.assertEqual(governance.validate_task_contract(self.valid_task_contract()), [])

        invalid = self.valid_task_contract(
            requested_mode="auto",
            resolved_mode="light",
            resolution_reason="auto_light",
            task_features=None,
        )
        self.assertIn("task_features", " ".join(governance.validate_task_contract(invalid)))

        contradictory = self.valid_task_contract(
            requested_mode="auto",
            resolved_mode="standard",
            resolution_reason="auto_standard",
            task_features={
                "risk": "medium",
                "read_only": True,
                "writes_files": True,
                "destructive": False,
                "production": False,
                "concurrent_write": False,
                "multi_stage_acceptance": False,
            },
        )
        self.assertIn("read_only", " ".join(governance.validate_task_contract(contradictory)))

        strict_without_evidence = self.valid_task_contract(
            requested_mode="strict",
            resolved_mode="strict",
            resolution_reason="explicit_request",
            forbidden_scope=[],
            evidence_requirements=[],
        )
        errors = " ".join(governance.validate_task_contract(strict_without_evidence))
        self.assertIn("forbidden_scope", errors)
        self.assertIn("evidence_requirements", errors)

    def test_context_strategy_combinations_are_mechanical(self):
        cases = (
            ({"context_strategy": "isolated", "context_turns": 1}, "context_turns"),
            (
                {"context_strategy": "limited", "context_turns": None, "context_reason": "需要连续语义"},
                "context_turns",
            ),
            ({"context_strategy": "limited", "context_turns": 2, "context_reason": None}, "context_reason"),
            ({"context_strategy": "full", "context_turns": 2, "context_reason": "需要全部历史"}, "context_turns"),
            ({"context_strategy": "full", "context_turns": None, "context_reason": None}, "context_reason"),
        )
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                errors = governance.validate_task_contract(self.valid_task_contract(**overrides))
                self.assertIn(expected, " ".join(errors))

        for valid in (
            {},
            {"context_strategy": "limited", "context_turns": 3, "context_reason": "任务依赖最近三轮裁决"},
            {"context_strategy": "full", "context_turns": None, "context_reason": "存在未落盘连续状态"},
        ):
            with self.subTest(valid=valid):
                self.assertEqual(
                    governance.validate_task_contract(self.valid_task_contract(**valid)),
                    [],
                )

    def test_task_result_validator_requires_scenario_fields_without_business_judgment(self):
        self.assertEqual(governance.validate_task_result(self.valid_task_result()), [])
        self.assertEqual(governance.validate_task_result(self.valid_task_result(evidence=[])), [])

        blocked = self.valid_task_result(
            business_result="blocked",
            blocker="缺少外部授权",
            attempted=["检查现有本地配置"],
            required_to_resume="用户提供授权范围",
        )
        failed = self.valid_task_result(
            business_result="failed",
            failure_reason="目标测试仍失败",
            attempted=["复现并检查失败路径"],
            retry_conditions="依赖修复后重新执行",
        )
        decision = self.valid_task_result(
            business_result="needs_decision",
            decision_question="是否接受未验证的平台风险？",
            options=["接受风险", "暂缓"],
            recommendation="暂缓并补真实平台验证",
        )
        for value in (blocked, failed, decision):
            with self.subTest(result=value["business_result"]):
                self.assertEqual(governance.validate_task_result(value), [])

        missing = self.valid_task_result(business_result="blocked")
        errors = " ".join(governance.validate_task_result(missing))
        for field_name in ("blocker", "attempted", "required_to_resume"):
            self.assertIn(field_name, errors)

    def test_text_and_optional_result_fields_keep_schema_validator_parity(self):
        definitions = governance.MACHINE_SEMANTICS["$defs"]
        for definition_name in (
            "business_text",
            "nullable_business_text",
            "short_text",
            "nullable_short_text",
            "model",
        ):
            self.assertEqual(definitions[definition_name]["pattern"], "\\S")
        self.assertEqual(definitions["text_list"]["items"]["pattern"], "\\S")

        contract_errors = governance.validate_task_contract(
            self.valid_task_contract(objective="   ")
        )
        self.assertIn("objective", " ".join(contract_errors))

        result_errors = governance.validate_task_result(
            self.valid_task_result(result="\n", blocker=123, attempted=["ok"])
        )
        self.assertIn("result", " ".join(result_errors))
        self.assertIn("blocker", " ".join(result_errors))

    def test_attempt_state_defaults_match_confirmed_initial_values(self):
        initial = {
            "execution_status": "not_started",
            "spawn_observation": None,
            "identity_status": "unconfirmed",
            "platform_observation": None,
            "business_result": None,
            "acceptance_status": None,
            "result_protocol_status": None,
            "result_storage_status": None,
            "result_conflict": False,
            "recovery_status": None,
            "parent_action": None,
            "spawn_retry_count": 0,
            "recovery_count": 0,
            "correction_count": 0,
        }
        self.assertEqual(governance.MACHINE_SEMANTICS["x-semantics"]["initial_attempt_state"], initial)
        self.assertEqual(governance.AttemptState().to_record(), initial)

    def test_removed_semantic_targets_are_not_runtime_authorities(self):
        for name in (
            "PROTOCOL",
            "RESULT_PROTOCOL",
            "COMMUNICATION_PROTOCOL",
            "STATE_VERSION",
            "HIGH_RISK_MARKERS",
            "READ_ONLY_MARKERS",
            "WRITE_MARKERS",
            "NEGATION_MARKERS",
            "ACK_ONLY",
            "EVIDENCE_MARKERS",
            "STRICT_TERMINAL_FIELDS",
        ):
            self.assertFalse(hasattr(governance, name), name)

    def test_natural_language_rules_align_without_copying_full_machine_protocol(self):
        skill = (ROOT / "skills/subagent-governance/SKILL.md").read_text(encoding="utf-8")
        levels = (
            ROOT / "skills/subagent-governance/references/governance-levels.md"
        ).read_text(encoding="utf-8")
        boundaries = (
            ROOT / "skills/subagent-governance/references/runtime-boundaries.md"
        ).read_text(encoding="utf-8")
        asset = (ROOT / "assets/agents-governance.md").read_text(encoding="utf-8")

        for field_name in (
            "requested_mode",
            "resolved_mode",
            "task_features",
            "context_strategy",
            "context_turns",
            "context_reason",
            "business_result",
            "suggested_parent_next_step",
        ):
            self.assertIn(field_name, skill)
        for operation in governance.OPERATION_TYPES:
            self.assertIn(operation, skill)
        semantics = governance.MACHINE_SEMANTICS["x-semantics"]
        self.assertEqual(
            semantics["communication_fields"],
            ["target", "purpose", "reason", "content", "expected_result", "operation_type"],
        )
        self.assertEqual(
            semantics["operation_native_tools"],
            {
                "normal_message": "send_message",
                "platform_recovery": "followup_task",
                "result_correction": "followup_task",
                "business_resume": "followup_task",
                "interrupt": "interrupt_agent",
            },
        )
        self.assertEqual(
            set(governance._semantic_enum("pending_action_phase")),
            {"prepared", "claimed"},
        )
        self.assertIn("sg_<resolved_mode>_<semantic_name>_t_<task_ref>", skill)
        self.assertIn("结构化", levels)
        self.assertIn("只做字段存在、类型、长度、枚举、引用和基本组合校验", skill)
        self.assertIn("未知额外字段", boundaries)
        self.assertNotIn("【下级子 Agent】", skill)
        self.assertNotIn("正文信号", levels)
        self.assertIn("$subagent-governance", asset)
        self.assertNotIn("task_features", asset)


if __name__ == "__main__":
    unittest.main()
