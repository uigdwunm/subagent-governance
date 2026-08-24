#!/usr/bin/env python3

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts import governance_semantics as semantics
from scripts import governance_dispatch as dispatch
from scripts import governance_execution as execution_domain
from tests.support import load_governance

governance = load_governance("platform_observation")


class PlatformObservationAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = governance.StateStore(Path(self.temporary.name))
        self.session_id = "platform-observation"
        self.task_id = "platform-observation-task"
        self.target = "/root/platform_observation"
        contract = governance.TaskContract(
            semantic_name="platform_observation",
            requested_mode="standard",
            resolved_mode="standard",
            resolution_reason="explicit_request",
            task_features={
                "risk": "medium",
                "read_only": True,
                "writes_files": False,
                "destructive": False,
                "production": False,
                "concurrent_write": False,
            },
            objective="验证当前平台观察边界",
            background="current platform adapter test",
            work_scope=["list_agents adapter"],
            forbidden_scope=[],
            completion_conditions=["exact observation"],
            evidence_requirements=["unit test"],
            relevant_files=[],
            context_manifest={"mode": "none"},
            current_state=None,
            model=None,
            reasoning_effort=None,
            context_strategy="isolated",
            context_turns=None,
            context_reason=None,
        )
        task = dispatch.initial_task_record(
            1,
            "0123456789ab",
            "sg_standard_platform_observation_t_0123456789ab",
            contract,
            100,
        )
        execution = task["executions"]["1"]
        execution["dispatch_record"].update(
            dispatch_state="acknowledged",
            tool_use_id="spawn-tool",
            dispatch_target=self.target,
        )
        execution_domain.apply_canonical_execution_update(
            execution, "observed_execution_status", "running"
        )
        execution_domain.apply_canonical_execution_update(
            execution, "closure_parent_action", "wait"
        )
        self.state = governance.StateStore._empty_state(self.session_id)
        self.state["tasks"][self.task_id] = task
        self.state["agents"][self.target] = {"task_id": self.task_id, "attempt": 1}

    def tearDown(self):
        self.temporary.cleanup()

    def execution(self):
        return self.store.read(self.session_id)["tasks"][self.task_id]["executions"]["1"]

    def write_state(self):
        path, _lock = self.store._paths(self.session_id)
        path.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        if os.name != "nt":
            path.chmod(0o600)

    def observe(self, response, *, now=200):
        return governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "PostToolUse",
                "tool_name": "collaboration.list_agents",
                "tool_use_id": f"platform-list-{now}",
                "tool_input": {"path_prefix": self.target},
                "tool_response": response,
                "now": now,
            },
            self.store,
        )

    def test_machine_contract_defines_adapter_freshness_and_stop(self):
        adapter = semantics.SEMANTIC_RULES["platform_observation_adapter"]
        self.assertEqual(adapter["source"], "post_tool_use_list_agents")
        self.assertEqual(adapter["response_container"], "top_level_agents_only")
        self.assertEqual(adapter["query_binding"], "exact_canonical_path_prefix")
        self.assertEqual(
            adapter["nonempty_binding"],
            "path_prefix_equals_agent_name_equals_unique_dispatch_target",
        )
        self.assertEqual(
            adapter["native_status_shapes"], ["string", "single_tag_object"]
        )
        self.assertFalse(adapter["recursive_content_scan"])
        self.assertFalse(adapter["transcript_summary_final_history_scan"])
        self.assertEqual(
            adapter["unbound_warning_reasons"],
            [
                "missing_exact_path_prefix",
                "response_shape_unrecognized",
                "response_reported_error",
                "ambiguous_target_binding",
            ],
        )
        self.assertFalse(adapter["unbound_warning_persists_fact"])
        self.assertEqual(
            adapter["canonical_route_rejection_reasons"],
            [
                "current_identity_ambiguous",
                "active_index_provenance_mismatch",
                "closed_provenance_only",
                "unmanaged_target",
            ],
        )
        self.assertFalse(adapter["canonical_route_rejection_persists_observation"])
        self.assertEqual(adapter["boolean_error_flags"], ["isError", "is_error"])
        self.assertEqual(adapter["explicit_error_field"], "error")
        self.assertEqual(adapter["wrapper_status_fields"], ["status", "state"])
        self.assertEqual(
            adapter["wrapper_error_statuses"],
            ["errored", "error", "failed", "failure"],
        )
        self.assertEqual(
            adapter["wrapper_status_parse_policy"],
            "present_must_be_single_native_tag",
        )
        self.assertEqual(
            adapter["malformed_or_explicit_error"], "no_exact_bound_fact"
        )
        self.assertEqual(
            semantics.LIST_AGENTS_WRAPPER_STATUS_PARSE_POLICY,
            adapter["wrapper_status_parse_policy"],
        )
        self.assertEqual(
            semantics.LIST_AGENTS_MALFORMED_WRAPPER_POLICY,
            adapter["malformed_or_explicit_error"],
        )

        capability = semantics.SEMANTIC_RULES["hook_capability_contract"]
        self.assertEqual(capability["active_freshness_authority"], "disabled")
        self.assertEqual(capability["positive_parent_stop_gate"], "none")
        self.assertEqual(capability["parent_stop_behavior"], "advisory_continue")

    def test_exact_running_remains_nonfresh_and_stop_is_visible_advisory(self):
        self.write_state()
        self.observe(
            {"agents": [{"agent_name": self.target, "agent_status": "running"}]}
        )

        execution = self.execution()
        self.assertEqual(execution["observation_record"]["observed_state"], "active")

        stopped = governance.handle(
            {
                "session_id": self.session_id,
                "hook_event_name": "Stop",
                "stop_hook_active": False,
            },
            self.store,
        )
        self.assertTrue(stopped["continue"])
        self.assertNotIn("decision", stopped)
        self.assertIn("advisory", stopped["systemMessage"])
        self.assertIn(f"{self.task_id}#1", stopped["systemMessage"])

    def test_resume_shared_target_routes_exact_list_to_open_current_attempt(self):
        """A retained closed source must not shadow the current resume attempt."""
        source = self.state["tasks"][self.task_id]["executions"]["1"]
        execution_domain.apply_canonical_execution_update(
            source, "closure_reason", "business_resume"
        )
        execution_domain.apply_canonical_execution_update(source, "closure_closed_at", 150)
        execution_domain.apply_canonical_execution_update(source, "closure_parent_action", None)
        resumed = copy.deepcopy(source)
        resumed["task_ref"] = "abcdefabcdef"
        resumed["task_name"] = None
        execution_domain.apply_canonical_execution_update(
            resumed, "closure_reason", None
        )
        execution_domain.apply_canonical_execution_update(resumed, "closure_closed_at", None)
        execution_domain.apply_canonical_execution_update(resumed, "closure_parent_action", "wait")
        resumed["observation_record"] = {
            "source": "list_agents",
            "observed_state": "active",
            "observed_at": 149,
            "terminal_status": None,
        }
        self.state["tasks"][self.task_id]["executions"]["2"] = resumed
        self.state["tasks"][self.task_id]["work_item"]["current_attempt"] = 2
        self.state["agents"][self.target] = {"task_id": self.task_id, "attempt": 2}
        resume_state = copy.deepcopy(self.state)
        for status in ("running", "completed", "errored", "absent"):
            with self.subTest(status=status):
                state_path, _lock = self.store._paths(self.session_id)
                state_path.write_text(json.dumps(resume_state, ensure_ascii=False), encoding="utf-8")
                if os.name != "nt":
                    state_path.chmod(0o600)
                response = {"agents": []} if status == "absent" else {
                    "agents": [{"agent_name": self.target, "agent_status": status}]
                }
                self.observe(response)
                state = self.store.read(self.session_id)
                self.assertEqual(
                    state["tasks"][self.task_id]["executions"]["2"]["observation_record"]["source"],
                    "list_agents",
                )
                self.assertNotEqual(
                    state["tasks"][self.task_id]["executions"]["1"]["observation_record"]["source"],
                    "list_agents",
                )

    def test_exact_list_unsafe_identity_is_rejected_with_bounded_route_reason(self):
        response = {"agents": [{"agent_name": self.target, "agent_status": "running"}]}
        for scenario, expected in (
            ("index_mismatch", "active_index_provenance_mismatch"),
            ("two_open", "current_identity_ambiguous"),
            ("closed_only", "closed_provenance_only"),
        ):
            with self.subTest(scenario=scenario):
                state = copy.deepcopy(self.state)
                first = state["tasks"][self.task_id]["executions"]["1"]
                if scenario == "index_mismatch":
                    other = copy.deepcopy(first)
                    other["task_ref"] = "abcdefabcdef"
                    other["dispatch_record"]["dispatch_target"] = "/root/other"
                    state["tasks"][self.task_id]["executions"]["2"] = other
                    state["agents"][self.target] = {"task_id": self.task_id, "attempt": 2}
                elif scenario == "two_open":
                    other = copy.deepcopy(first)
                    other["task_ref"] = "abcdefabcdef"
                    state["tasks"][self.task_id]["executions"]["2"] = other
                    state["agents"].pop(self.target)
                else:
                    execution_domain.apply_canonical_execution_update(first, "closure_reason", "close_task:test")
                    execution_domain.apply_canonical_execution_update(first, "closure_closed_at", 150)
                    execution_domain.apply_canonical_execution_update(first, "closure_parent_action", None)
                path, _lock = self.store._paths(self.session_id)
                path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
                if os.name != "nt":
                    path.chmod(0o600)
                result = self.observe(response, now=210)
                self.assertTrue(result["continue"])
                self.assertIn(expected, result["systemMessage"])
                current = self.store.read(self.session_id)
                self.assertNotEqual(
                    current["tasks"][self.task_id]["executions"]["1"]["observation_record"]["source"],
                    "list_agents",
                )

    def test_nested_or_summary_agents_are_not_scanned(self):
        self.write_state()
        before = copy.deepcopy(self.execution())
        nested_agent = {
            "agents": [{"agent_name": self.target, "agent_status": "completed"}]
        }
        for index, response in enumerate(
            (
                {"structuredContent": nested_agent},
                {"content": [{"type": "text", "text": str(nested_agent)}]},
                {"summary": nested_agent, "final_history": nested_agent},
            ),
            start=1,
        ):
            with self.subTest(response=index):
                self.observe(response, now=200 + index)
                self.assertEqual(self.execution(), before)

    def test_malformed_or_explicit_error_wrappers_do_not_expose_agents(self):
        self.write_state()
        before = copy.deepcopy(self.execution())
        completed_agent = {
            "agents": [{"agent_name": self.target, "agent_status": "completed"}]
        }
        responses = (
            {"isError": "true", **completed_agent},
            {"is_error": 1, **completed_agent},
            {"isError": True, **completed_agent},
            {"error": "boom", **completed_agent},
            {"error": 0, **completed_agent},
            {"status": "ok", "state": "error", **completed_agent},
            {"status": "running", "state": "failed", **completed_agent},
            {"status": "error", "state": "ok", **completed_agent},
            {"status": None, **completed_agent},
            {"state": False, **completed_agent},
            {"status": 0, **completed_agent},
            {"state": 1, **completed_agent},
            {"status": "", **completed_agent},
            {"state": {}, **completed_agent},
            {"status": [], **completed_agent},
            {"status": {"ok": False}, **completed_agent},
            {"status": {"ok": True, "error": True}, **completed_agent},
            {"status": "ok", "state": None, **completed_agent},
            {"status": [], "state": "running", **completed_agent},
            str({"error": {"message": "boom"}, **completed_agent}),
        )
        for index, response in enumerate(responses, start=1):
            with self.subTest(response=index):
                self.observe(response, now=300 + index)
                self.assertEqual(self.execution(), before)


if __name__ == "__main__":
    unittest.main()
